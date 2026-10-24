"""PKG2: socket-free service tests plus authenticated HTTP coverage for ORCHESTRATOR."""
import io
import json
import zipfile
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from auto_short.packaging import PackageError, episode
from auto_short.web import episode_thumbs as web
from auto_short.web.auth import COOKIE_NAME
from auto_short.web.jobs import RENDER

from test_packaging_episode import IDS, PID, SERIES, add_images, seed_episodes
from test_packaging_thumbnail import fake_media
from test_web_theme_index import fx

BASE = f"/api/playlists/{PID}/thumbs"


@pytest.fixture
def service(tmp_path):
    cfg = seed_episodes(tmp_path)
    app = fx.build_app(cfg, "pw", restrict=False)
    thumbs = app.state.episode_thumbs
    calls = []
    def counted(cmd):
        calls.append(cmd)
        return fake_media(cmd)
    thumbs.media_runner = counted
    return SimpleNamespace(cfg=cfg, app=app, service=thumbs, runner=app.state.runner, calls=calls)


@pytest.fixture
def client(service, monkeypatch):
    from auto_short.web.routes import auth
    monkeypatch.setattr(auth, "LOGIN_DELAY", 0)
    s = service
    s.c = TestClient(s.app, follow_redirects=False)
    result = s.c.post("/login", json={"password": "pw"})
    s.c.cookies.set(COOKIE_NAME, result.cookies[COOKIE_NAME])
    return s


def test_service_job_lane_dedup_cache_and_single_override(service, tmp_path):
    s = service
    pool = add_images(s.cfg, tmp_path)
    first, created = s.service.render(PID)
    duplicate, again = s.service.render(PID)
    assert created and not again and first.id == duplicate.id
    assert first.kind == "episode_thumbs" and first.episode_id == f"episode_thumbs:{PID}"
    assert [step.lane for step in first.steps] == [RENDER]
    with pytest.raises(web.Unavailable):
        s.service.edit(PID, IDS[1], pool[1])
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        assert first.status == "done", first.error
        assert len(s.calls) == 3
        view = s.service.view(PID)
        assert view["series"] == SERIES and all(row["files"] for row in view["episodes"])
        for row in view["episodes"]:
            assert not row["skipped_reason"]
            for entry in row["files"].values():
                assert entry["preview_url"].startswith("/files/episodes/")
        s.calls.clear()
        job, _ = s.service.render(PID)
        assert s.runner.wait_idle(5) and job.status == "done"
        assert not s.calls
        unchanged = (episode.directory(s.cfg, IDS[0]) / "thumbs.json").read_bytes()
        job, _ = s.service.edit(PID, IDS[1], pool[1])
        assert s.runner.wait_idle(5) and job.status == "done", job.error
        assert len(s.calls) == 1
        assert unchanged == (episode.directory(s.cfg, IDS[0]) / "thumbs.json").read_bytes()
        with pytest.raises(PackageError):
            s.service.edit(PID, "another", None)
    finally:
        s.runner.stop()


@pytest.mark.parametrize("damage", ["bytes", "symlink", "missing", "header"])
def test_service_zip_only_verified_files_and_series_name(service, damage):
    s = service
    episode.build_playlist(s.cfg, PID, run=fake_media)
    data, name = s.service.archive(PID)
    assert SERIES in name
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert set(archive.namelist()) == {"T101_ngang.jpg", "T101_doc.jpg", "T102_ngang.jpg"}
        assert archive.read("T101_ngang.jpg").startswith(b"jpeg:")
    doc = episode.read(s.cfg, IDS[0])
    path = episode.directory(s.cfg, IDS[0]) / doc["files"]["landscape"]["file"]
    if damage == "bytes":
        path.write_bytes(b"tampered")
    elif damage == "symlink":
        path.unlink()
        path.symlink_to(s.cfg.workspace.dir / IDS[0] / "source.mp4")
    elif damage == "missing":
        path.unlink()
    else:
        title = s.cfg.workspace.dir / IDS[0] / "titles.json"
        changed = json.loads(title.read_text())
        changed["header"]["fields"]["episode"] = "999"
        title.write_text(json.dumps(changed))
    data, _ = s.service.archive(PID)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert "T101_ngang.jpg" not in archive.namelist()
        assert "T102_ngang.jpg" in archive.namelist()
        assert all(".." not in name for name in archive.namelist())


def test_service_failed_episode_continues_and_queue_not_restored(service):
    s = service
    job, _ = s.service.render(PID)
    # Persisted media requests require a fresh explicit request after restart, like PKG1.
    app2 = fx.build_app(s.cfg, "pw", restrict=False)
    assert app2.state.runner.restore() == 0
    assert app2.state.runner.latest(web.render_key(PID)) is None
    title = s.cfg.workspace.dir / IDS[0] / "titles.json"
    title.write_text('{"header":{"fields":{}}}')
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        assert job.status == "done" and "bỏ qua 1" in job.summary
        rows = s.service.view(PID)["episodes"]
        assert rows[0]["skipped_reason"] and not rows[0]["files"]
        assert rows[1]["files"]
        assert str(s.cfg.workspace.dir) not in json.dumps(rows)
    finally:
        s.runner.stop()


def test_http_auth_ids_traversal_and_static(client):
    s = client
    anon = TestClient(s.app, follow_redirects=False)
    assert anon.get(f"/playlists/{PID}/thumbs").status_code == 303
    for method, url, body in [("GET", BASE, None), ("POST", BASE, None),
                               ("PUT", BASE + "/" + IDS[0], {"asset_id": None}),
                               ("GET", f"/files/playlists/{PID}/thumbs.zip", None),
                               ("GET", f"/files/episodes/{IDS[0]}/thumbs/landscape.jpg", None)]:
        assert anon.request(method, url, json=body).status_code == 401
    for pid in ("bad!", "PLunknown0"):
        assert s.c.get(f"/api/playlists/{pid}/thumbs").status_code == 404
        assert s.c.post(f"/api/playlists/{pid}/thumbs").status_code == 404
        assert s.c.get(f"/files/playlists/{pid}/thumbs.zip").status_code == 404
    assert s.c.put(BASE + "/another", json={"asset_id": None}).status_code == 400
    for name in ("thumbs.json", "..%5Csecret.jpg", "landscape-invalid.jpg"):
        assert s.c.get(f"/files/episodes/{IDS[0]}/thumbs/{name}").status_code == 404
    assert s.c.get("/files/episodes/bad!/thumbs/landscape.jpg").status_code == 404
    assert s.c.get(f"/playlists/{PID}/thumbs").status_code == 200
    assert "thumbs-grid" in s.c.get("/static/thumbs.html").text
    assert "Thumbnail cả bộ" in s.c.get("/static/playlist.html").text
    assert "pl-thumbs" in s.c.get("/static/app.js").text
    assert s.c.get(BASE).headers["cache-control"] == "no-store"


def test_http_build_grid_download_zip_and_tamper(client):
    s = client
    before = {str(p): p.stat().st_mtime_ns for p in s.cfg.workspace.dir.rglob("*")}
    view = s.c.get(BASE).json()
    assert view["episodes"][0]["skipped_reason"]
    assert before == {str(p): p.stat().st_mtime_ns for p in s.cfg.workspace.dir.rglob("*")}
    assert s.c.post(BASE).status_code == 202
    assert s.c.post(BASE).status_code == 200
    assert s.c.put(BASE + "/" + IDS[0], json={"asset_id": None}).status_code == 409
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        view = s.c.get(BASE).json()
        entry = view["episodes"][0]["files"]["landscape"]
        assert s.c.get(entry["preview_url"]).status_code == 200
        downloaded = s.c.get(entry["download_url"])
        assert downloaded.status_code == 200 and downloaded.headers["content-type"] == "image/jpeg"
        assert "T101_ngang.jpg" in downloaded.headers["content-disposition"]
        assert s.c.get(f"/files/episodes/{IDS[0]}/thumbs/landscape.jpg").status_code == 200
        zipped = s.c.get(view["zip_url"])
        assert zipped.status_code == 200 and SERIES in unquote(zipped.headers["content-disposition"])
        with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
            assert set(archive.namelist()) == {"T101_ngang.jpg", "T101_doc.jpg", "T102_ngang.jpg"}
        path = episode.directory(s.cfg, IDS[0]) / entry["file"]
        path.write_bytes(b"changed")
        assert s.c.get(entry["download_url"]).status_code == 404
        with zipfile.ZipFile(io.BytesIO(s.c.get(view["zip_url"]).content)) as archive:
            assert "T101_ngang.jpg" not in archive.namelist()
    finally:
        s.runner.stop()


def test_http_override_rebuilds_only_selected_episode(client, tmp_path):
    s = client
    pool = add_images(s.cfg, tmp_path)
    episode.build_playlist(s.cfg, PID, run=fake_media)
    assert s.c.put(BASE + "/" + IDS[1], json={"asset_id": "x" * 64}).status_code == 400
    assert s.c.put(BASE + "/" + IDS[1], json={"asset_id": pool[1]}).status_code == 202
    assert s.c.put(BASE + "/" + IDS[1], json={"asset_id": pool[0]}).status_code == 409
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        assert len(s.calls) == 1
        view = s.c.get(BASE).json()
        assert view["episodes"][1]["override"] == pool[1]
        assert s.c.put(BASE + "/" + IDS[1], json={"asset_id": None}).status_code == 202
        assert s.runner.wait_idle(5)
        assert s.c.get(BASE).json()["episodes"][1]["override"] is None
    finally:
        s.runner.stop()
