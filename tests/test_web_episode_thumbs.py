"""PKG2: socket-free service tests plus authenticated HTTP coverage for ORCHESTRATOR."""
import io
import json
import re
import zipfile
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from auto_short.packaging import PackageError, assets, episode
from auto_short.web import episode_thumbs as web
from auto_short.web.auth import COOKIE_NAME
from auto_short.web.jobs import RENDER

from test_packaging_episode import IDS, PID, SERIES, add_images, episode_media, seed_episodes
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
        return episode_media(cmd)
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


def test_service_gallery_labels_and_numeric_tag_order(service, tmp_path):
    s = service
    expected = {}
    for label in ("67", "2", "portrait", None):
        path = tmp_path / f"{label}.jpg"
        path.write_bytes(str(label).encode())
        asset = assets.add(s.cfg.packaging.asset_dir, path, kind="image", source="local:test", license="CC0",
                           tags=[label] if label else [], run=episode_media)
        assets.approve(s.cfg.packaging.asset_dir, asset["id"])
        expected[label] = asset["id"]
    images = s.service.view(PID)["assets"]
    assert [asset["id"] for asset in images[:2]] == [expected["2"], expected["67"]]
    assert [asset["number"] for asset in images[:2]] == ["2", "67"]
    assert [asset["id"] for asset in images[2:]] == sorted([expected["portrait"], expected[None]])
    for position, asset in enumerate(images, 1):
        assert asset["number"] == (asset["tags"][0] if asset["tags"] else position)
        assert asset["preview_url"].startswith("/files/playlists/")


def test_service_job_lane_dedup_cache_and_playlist_settings(service):
    s = service
    settings = episode.read_settings(s.cfg, PID)
    first, created = s.service.render(PID)
    duplicate, again = s.service.render(PID)
    assert created and not again and first.id == duplicate.id
    assert first.kind == "episode_thumbs" and first.episode_id == f"episode_thumbs:{PID}"
    assert [step.lane for step in first.steps] == [RENDER]
    with pytest.raises(web.Unavailable):
        s.service.save_settings(PID, settings)
    with pytest.raises(web.Unavailable):
        s.service.preview(PID)
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
        s.service.save_settings(PID, dict(settings, style="B"))
        assert all(not row["files"] for row in s.service.view(PID)["episodes"])
        job, _ = s.service.render(PID)
        assert s.runner.wait_idle(5) and job.status == "done", job.error
        assert len(s.calls) == 3
    finally:
        s.runner.stop()


@pytest.mark.parametrize("damage", ["bytes", "symlink", "missing", "header"])
def test_service_zip_only_verified_files_and_series_name(service, damage):
    s = service
    episode.build_playlist(s.cfg, PID, run=episode_media)
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
                               ("PUT", BASE + "/settings", {"title_lines": ["Kinh"]}),
                               ("POST", BASE + "/preview", None),
                               ("GET", BASE + "/settings", None),
                               ("GET", f"/files/playlists/{PID}/thumbs/assets/{'a'*64}", None),
                               ("GET", f"/files/playlists/{PID}/thumbs.zip", None),
                               ("GET", f"/files/episodes/{IDS[0]}/thumbs/landscape.jpg", None)]:
        assert anon.request(method, url, json=body).status_code == 401
    for pid in ("bad!", "PLunknown0"):
        assert s.c.get(f"/api/playlists/{pid}/thumbs").status_code == 404
        assert s.c.post(f"/api/playlists/{pid}/thumbs").status_code == 404
        assert s.c.get(f"/files/playlists/{pid}/thumbs.zip").status_code == 404
    assert s.c.put(BASE + "/" + IDS[0], json={"asset_id": None}).status_code == 404
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
    assert s.c.put(BASE + "/settings", json={"title_lines": ["Kinh"]}).status_code == 409
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


def test_http_settings_validation_preview_and_rebuild(client, tmp_path):
    s = client
    pool = add_images(s.cfg, tmp_path)
    settings = s.c.get(BASE + "/settings").json()
    assert settings["style"] == "A" and settings["asset_id"] is None
    for patch in ({"style": "D"}, {"focus_x": -1}, {"title_lines": [" "]}, {"title_lines": ["x"*41]},
                  {"credit": "x"*61}, {"asset_id": "x"*64}):
        assert s.c.put(BASE + "/settings", json={**settings, **patch}).status_code in (400, 422)
    before = {str(p): p.read_bytes() for p in s.cfg.render.output_dir.rglob("*") if p.is_file()}
    preview = s.c.post(BASE + "/preview", json={**settings, "style": "C"})
    assert preview.status_code == 200
    assert set(preview.json()["files"]) == {"landscape", "vertical"}
    assert all(file["preview_url"].startswith("data:image/jpeg;base64,") for file in preview.json()["files"].values())
    assert before == {str(p): p.read_bytes() for p in s.cfg.render.output_dir.rglob("*") if p.is_file()}
    assert not episode.settings_path(s.cfg, PID).exists()
    view = s.c.get(BASE).json()
    assert s.c.get(view["assets"][0]["preview_url"]).status_code == 200
    episode.build_playlist(s.cfg, PID, run=episode_media)
    s.calls.clear()
    assert s.c.put(BASE + "/settings", json={**settings, "asset_id": pool[0], "style": "B"}).status_code == 200
    assert s.c.post(BASE).status_code == 202
    assert s.c.post(BASE + "/preview").status_code == 409
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        assert len([cmd for cmd in s.calls if "mjpeg" in cmd]) == 3
        view = s.c.get(BASE).json()
        assert view["settings"]["asset_id"] == pool[0]
        assert all(row["asset_id"] == pool[0] for row in view["episodes"])
    finally:
        s.runner.stop()


def test_service_progress_counts_per_shape_and_reasons(service):
    s = service
    progress = s.service.view(PID)["progress"]
    reason = "chưa dựng hoặc đầu vào đã đổi — dựng lại"
    assert progress == dict(total=2, landscape=0, vertical=0, with_any=0, skipped=2, skipped_by_reason={reason: 2})
    episode.build_playlist(s.cfg, PID, run=episode_media)
    assert s.service.view(PID)["progress"] == dict(total=2, landscape=2, vertical=1, with_any=2, skipped=0, skipped_by_reason={})
    (s.cfg.workspace.dir / IDS[1] / "source.mp4").unlink()  # no HD landscape and no vertical: skipped
    episode.build_playlist(s.cfg, PID, run=episode_media)
    progress = s.service.view(PID)["progress"]
    assert (progress["total"], progress["landscape"], progress["vertical"], progress["with_any"], progress["skipped"]) \
        == (2, 1, 1, 1, 1)
    assert list(progress["skipped_by_reason"].values()) == [1] and list(progress["skipped_by_reason"])[0]
    assert str(s.cfg.workspace.dir) not in json.dumps(progress)


def test_http_vertical_override_validation_preview_and_save(client, tmp_path):
    s = client
    pool = add_images(s.cfg, tmp_path)
    settings = s.c.get(BASE + "/settings").json()
    assert settings["vertical"] is None
    good = dict(style="B", asset_id=pool[0], focus_x=0.25)
    for bad in (dict(good, style="D"), dict(good, focus_x=1.5), dict(good, focus_x=-0.1), dict(good, asset_id="x" * 64),
                dict(good, asset_id="a" * 64), {"style": "A", "focus_x": 0.5}, "A"):
        for method, url in (("PUT", BASE + "/settings"), ("POST", BASE + "/preview")):
            assert s.c.request(method, url, json={**settings, "vertical": bad}).status_code in (400, 422), (method, bad)
    assert not s.calls and not episode.settings_path(s.cfg, PID).exists()
    preview = s.c.post(BASE + "/preview", json={**settings, "vertical": good})
    assert preview.status_code == 200 and set(preview.json()["files"]) == {"landscape", "vertical"}
    assert not episode.settings_path(s.cfg, PID).exists()
    saved = s.c.put(BASE + "/settings", json={**settings, "vertical": good})
    assert saved.status_code == 200 and saved.json()["vertical"] == good
    assert s.c.get(BASE).json()["settings"]["vertical"] == good
    # null (or no field) goes back to the shared look
    assert s.c.put(BASE + "/settings", json={**settings, "vertical": None}).json()["vertical"] is None
    assert s.c.put(BASE + "/settings", json={k: v for k, v in settings.items() if k != "vertical"}).json()["vertical"] is None


def test_http_vertical_override_only_rebuilds_vertical(client, tmp_path):
    s = client
    pool = add_images(s.cfg, tmp_path)
    episode.build_playlist(s.cfg, PID, run=episode_media)
    settings = s.c.get(BASE + "/settings").json()
    s.calls.clear()
    assert s.c.put(BASE + "/settings", json={**settings, "vertical": dict(style="C", asset_id=pool[1], focus_x=0.4)}).status_code == 200
    progress = s.c.get(BASE).json()["progress"]
    assert (progress["landscape"], progress["vertical"]) == (2, 0)
    assert s.c.post(BASE).status_code == 202
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        assert len([cmd for cmd in s.calls if "mjpeg" in cmd]) == 1
        progress = s.c.get(BASE).json()["progress"]
        assert (progress["landscape"], progress["vertical"], progress["with_any"]) == (2, 1, 2)
    finally:
        s.runner.stop()


def test_page_has_sticky_action_bar_and_collapsed_lists(client):
    html = client.c.get(f"/playlists/{PID}/thumbs").text
    parse = re.compile(r"<details\b([^>]*)>")
    assert "position: sticky" in html and "bottom: 0" in html
    bar = html[html.index('class="th-bar"'):]
    for control in ("thumbs-preview", "thumbs-build", "thumbs-zip"):
        assert control in bar
    assert bar.index("thumbs-build") < bar.index("</form>")  # the bar lives inside the form, after all settings
    details = {m.group(1) for m in parse.finditer(html)}
    assert all("open" not in attrs.split() for attrs in details)
    for ident in ("thumbs-details", "thumbs-vdetails", "thumbs-episodes"):
        assert f'id="{ident}"' in html
    assert re.search(r'id="thumbs-assets"[^>]*>', html) and "max-height: 50vh" in html and "overflow: auto" in html
    # the grid of episodes sits inside its closed <details>, the preview sits above the action bar
    assert html.index('id="thumbs-episodes"') < html.index('id="thumbs-grid"') < html.index('class="th-bar"')
    assert html.index('id="thumbs-preview-images"') < html.index('class="th-bar"')
    assert 'id="thumbs-vsep"' in html and 'id="thumbs-vgroup"' in html
    script = client.c.get("/static/thumbs.js").text
    assert "vertical:" in script and '"toggle"' in script and "view.progress" in script
