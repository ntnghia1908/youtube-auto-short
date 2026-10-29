"""PKG2: socket-free service tests plus authenticated HTTP coverage for ORCHESTRATOR."""
import io
import json
import shutil
import zipfile
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from auto_short.packaging import PackageError, episode
from auto_short.web import episode_thumbs as web
from auto_short.web.auth import COOKIE_NAME
from auto_short.web.jobs import RENDER
from auto_short.workspace import atomic_write_json

from test_packaging_episode import IDS, PID, SERIES, episode_media, seed_episodes
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


def test_service_job_lane_dedup_cache_and_grid(service):
    s = service
    first, created = s.service.render(PID)
    duplicate, again = s.service.render(PID)
    assert created and not again and first.id == duplicate.id
    assert [step.lane for step in first.steps] == [RENDER]
    with pytest.raises(web.Unavailable):
        s.service.mutable(PID)
    s.runner.start()
    try:
        assert s.runner.wait_idle(5) and first.status == "done", first.error
        view = s.service.view(PID)
        assert view["series"] == SERIES and all(row["files"] for row in view["episodes"])
        assert "settings" not in view and "assets" not in view
        assert not view["covers"] and view["suggestion"] is None
        s.calls.clear()
        job, _ = s.service.render(PID)
        assert s.runner.wait_idle(5) and job.status == "done" and not s.calls
    finally:
        s.runner.stop()


@pytest.mark.parametrize("damage", ["bytes", "symlink", "missing", "header"])
def test_service_zip_only_verified_files_and_series_name(service, damage):
    s = service
    episode.build_playlist(s.cfg, PID, run=episode_media)
    data, name = s.service.archive(PID)
    assert SERIES in name
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert set(archive.namelist()) == {"T101_ngang.jpg", "T101_doc.jpg", "T102_ngang.jpg", "T102_doc.jpg"}
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
            assert set(archive.namelist()) == {"T101_ngang.jpg", "T101_doc.jpg", "T102_ngang.jpg", "T102_doc.jpg"}
        path = episode.directory(s.cfg, IDS[0]) / entry["file"]
        path.write_bytes(b"changed")
        assert s.c.get(entry["download_url"]).status_code == 404
        with zipfile.ZipFile(io.BytesIO(s.c.get(view["zip_url"]).content)) as archive:
            assert "T101_ngang.jpg" not in archive.namelist()
    finally:
        s.runner.stop()


def test_service_progress_counts_per_shape_and_reasons(service):
    s = service
    progress = s.service.view(PID)["progress"]
    reason = "chưa dựng hoặc đầu vào đã đổi — dựng lại"
    assert progress == dict(total=2, landscape=0, vertical=0, with_any=0, skipped=2, skipped_by_reason={reason: 2})
    episode.build_playlist(s.cfg, PID, run=episode_media)
    assert s.service.view(PID)["progress"] == dict(total=2, landscape=2, vertical=2, with_any=2, skipped=0, skipped_by_reason={})
    (s.cfg.workspace.dir / IDS[1] / "source.mp4").unlink()  # G8: the video is irrelevant, still both shapes
    episode.build_playlist(s.cfg, PID, run=episode_media)
    assert s.service.view(PID)["progress"] == dict(total=2, landscape=2, vertical=2, with_any=2, skipped=0, skipped_by_reason={})
    atomic_write_json(s.cfg.workspace.dir / IDS[1] / "titles.json", dict(header=dict(fields=dict(series=SERIES))))
    episode.build_playlist(s.cfg, PID, run=episode_media)  # an invalid header is what still skips an episode
    progress = s.service.view(PID)["progress"]
    assert (progress["total"], progress["landscape"], progress["vertical"], progress["with_any"], progress["skipped"]) \
        == (2, 1, 1, 1, 1)
    assert list(progress["skipped_by_reason"].values()) == [1] and list(progress["skipped_by_reason"])[0]
    assert str(s.cfg.workspace.dir) not in json.dumps(progress)


def test_page_has_suggestion_flow_and_no_legacy_form(client):
    html = client.c.get(f"/playlists/{PID}/thumbs").text
    for text in ("Gợi ý 4 mẫu", "Dùng bộ ảnh này", "Vẽ lại 3 ảnh", "Dựng cả bộ", "Tải zip", "Xem từng tập"):
        assert text in html
    for old in ("thumbs-style", "thumbs-vstyle", "thumbs-settings", "thumbs-assets", "thumbs-preview", "thumbs-focus"):
        assert f'id="{old}"' not in html
    assert 'id="thumbs-zoom"' in html and 'maxlength="200"' in html
    assert "position: sticky" in html and "bottom: 0" in html
    script = client.c.get("/static/thumbs.js").text
    assert "/suggest" in script and "view.progress" in script and "setTimeout(load" in script
    for route in ("/settings", "/preview"):
        assert client.c.post(BASE + route).status_code == 404


def test_http_episode_without_video_has_both_shapes_and_zip_names(client):  # G8 / AC4
    s = client
    work = s.cfg.workspace.dir
    (work / (IDS[0] + ".kt")).mkdir()
    (work / IDS[0] / "titles.json").replace(work / (IDS[0] + ".kt") / "titles.json")
    shutil.rmtree(work / IDS[0])
    shutil.rmtree(s.cfg.render.output_dir / IDS[0])
    episode.build_playlist(s.cfg, PID, run=episode_media)
    view = s.c.get(BASE).json()
    assert set(view["episodes"][0]["files"]) == {"landscape", "vertical"} and not view["episodes"][0]["skipped_reason"]
    assert view["progress"]["skipped"] == 0
    for entry in view["episodes"][0]["files"].values():
        assert s.c.get(entry["preview_url"]).status_code == 200
    with zipfile.ZipFile(io.BytesIO(s.c.get(view["zip_url"]).content)) as archive:
        assert {"T101_ngang.jpg", "T101_doc.jpg"} <= set(archive.namelist())


def test_service_suggestion_paths_and_symlinks(service, tmp_path):
    from auto_short.packaging import cover_suggest
    s = service
    doc = cover_suggest.create(s.cfg, PID)
    folder = cover_suggest.directory(s.cfg, PID, doc["run_id"])
    doc["options"] = {"option-1.png": dict(shape="vertical", box=[100, 700, 300, 100], preview="option-1-preview.jpg")}
    cover_suggest.save(folder, doc)
    (folder / "option-1.png").write_bytes(b"test")
    assert s.service.suggestion_image(PID, doc["run_id"], "option-1.png") == folder / "option-1.png"
    for name in ("../secret", "state.json", "option-2.png", "ref.png", "boxes.json"):
        with pytest.raises(PackageError):
            s.service.suggestion_image(PID, doc["run_id"], name)
    (folder / "option-1.png").unlink()
    (folder / "option-1.png").symlink_to(tmp_path / "outside.png")
    with pytest.raises(PackageError, match="symlink"):
        s.service.suggestion_image(PID, doc["run_id"], "option-1.png")


def test_http_suggest_auth_missing_binary_and_bad_ids(client):
    from dataclasses import replace
    from auto_short.config import ThumbsConfig
    from auto_short.packaging import cover_suggest
    s = client
    anon = TestClient(s.app, follow_redirects=False)
    ident = "a" * 32
    paths = [("POST", "/suggest", {}), ("GET", f"/suggest/{ident}", None),
             ("POST", f"/suggest/{ident}/select", dict(name="option-1.png")),
             ("POST", f"/suggest/{ident}/install", None), ("POST", f"/suggest/{ident}/cancel", None),
             ("GET", f"/suggest/{ident}/images/option-1.png", None), ("GET", "/covers/vertical", None)]
    for method, suffix, body in paths:
        assert anon.request(method, BASE + suffix, json=body).status_code == 401
    s.service.config = replace(s.cfg, thumbs=ThumbsConfig(codex_bin="/no/codex-here"))
    missing = s.c.post(BASE + "/suggest", json={})
    assert missing.status_code == 503 and "chưa cài Codex" in missing.json()["detail"]
    assert s.c.post(BASE + "/suggest", json=dict(notes="x" * 201)).status_code == 422
    for run_id in ("bad!", "..%5Csecret", "b" * 32):
        assert s.c.get(BASE + f"/suggest/{run_id}").status_code == 400
    assert s.c.get(BASE + f"/suggest/{ident}/images/state.json").status_code == 400


def test_http_suggest_choose_install_build_zip_and_kt_links(client, tmp_path, monkeypatch):
    import threading
    from auto_short.packaging import cover, cover_suggest, khaithi_thumbs
    from test_cover_suggest import fake_codex
    from test_khaithi_thumbs import seed_kt
    from test_packaging_cover import source_image
    s = client
    seed_kt(s.cfg)
    artwork = {"vertical": source_image(tmp_path, (540, 960)), "landscape": source_image(tmp_path, (640, 360))}
    monkeypatch.setattr(cover_suggest, "available", lambda _: None)
    s.service.codex_runner = fake_codex(artwork)
    s.service.media_runner = None
    entered, release = threading.Event(), threading.Event()
    actual = s.service.codex_runner
    def hold(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return actual(*args, **kwargs)
    s.service.codex_runner = hold
    try:
        result = s.c.post(BASE + "/suggest", json=dict(notes="Hoa sen"))
        assert result.status_code == 202
        ident = result.json()["run_id"]
        assert entered.wait(2)
        assert s.c.post(BASE + "/suggest", json={}).status_code == 409
    finally:
        release.set()
    s.service.suggest_thread.join(30)
    assert not s.service.suggest_thread.is_alive()
    options = s.c.get(BASE + f"/suggest/{ident}").json()
    assert options["status"] == "done", options.get("error")
    assert s.c.get(options["options"]["option-1.png"]["preview_url"]).status_code == 200
    assert s.c.post(BASE + f"/suggest/{ident}/select", json=dict(name="../../bad.png")).status_code == 400
    s.service.codex_runner = actual
    assert s.c.post(BASE + f"/suggest/{ident}/select", json=dict(name="option-1.png")).status_code == 202
    s.service.suggest_thread.join(30)
    doc = s.c.get(BASE + f"/suggest/{ident}").json()
    assert doc["status"] == "done", doc.get("error")
    assert len(doc["previews"]) == 6  # first, last, one actual KT title; both shapes
    assert s.c.post(BASE + f"/suggest/{ident}/install").status_code == 200
    assert set(cover.current(s.cfg, PID)) == set(cover.SIZES)
    summary = episode.build_playlist(s.cfg, PID)
    assert summary["khaithi"]["built"] == 4
    zipped = s.c.get(f"/files/playlists/{PID}/thumbs.zip")
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
        assert {f"khai-thi/T101_KT{n:02d}_{shape}.jpg" for n in (1, 2) for shape in ("vertical", "landscape")} <= set(archive.namelist())
    files = khaithi_thumbs.valid_files(s.cfg, IDS[0] + ".kt")
    for shape, entry in files["k01"].items():
        url = f"/files/episodes/{IDS[0]}.kt/thumbs/{entry['file']}"
        assert s.c.get(url).status_code == 200
        assert s.c.get(f"/files/episodes/{IDS[0]}.kt/thumbs/k01-{shape}.jpg").status_code == 200
    path = khaithi_thumbs.directory(s.cfg, IDS[0] + ".kt") / files["k01"]["vertical"]["file"]
    path.write_bytes(b"tampered")
    assert s.c.get(f"/files/episodes/{IDS[0]}.kt/thumbs/k01-vertical.jpg").status_code == 404
    assert "Thumbnail dọc" in s.c.get("/static/app.js").text


def feedback_endpoint(app):
    return next(route.endpoint for route in app.routes if getattr(route, "path", None) ==
                "/api/playlists/{pid}/thumbs/suggest/{run_id}/feedback")


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
def test_feedback_api_creates_child_and_exposes_metadata_without_socket(service, monkeypatch, status):
    from auto_short.packaging import cover_suggest
    s = service
    monkeypatch.setattr(cover_suggest, "available", lambda _: None)
    parent = cover_suggest.create(s.cfg, PID, "hoa sen")
    parent.update(status=status, feedback=["Đổi màu"])
    cover_suggest.save(cover_suggest.directory(s.cfg, PID, parent["run_id"]), parent)
    executed = []
    monkeypatch.setattr(cover_suggest, "execute", lambda *args, **kwargs: executed.append(args[2]))
    result = feedback_endpoint(s.app)(pid=PID, run_id=parent["run_id"],
                                      body=dict(feedback="  Khung nhỏ hơn  ", mode="options"))
    assert result.status_code == 202
    child = json.loads(result.body)
    s.service.suggest_thread.join(3)
    assert executed == [child["run_id"]] and child["run_id"] != parent["run_id"]
    view = s.service.suggestion_view(PID, child["run_id"])
    assert view["parent_run"] == parent["run_id"] and view["reference"] is None
    assert view["feedback"] == ["Đổi màu", "Khung nhỏ hơn"] and view["notes"] == "hoa sen"


@pytest.mark.parametrize("body", [
    None, [], "text", {}, {"feedback": "", "mode": "options"},
    {"feedback": "  ", "mode": "options"}, {"feedback": "x" * 301, "mode": "options"},
    {"feedback": 1, "mode": "options"}, {"feedback": "x", "mode": "bad"},
    {"feedback": "x", "mode": "revise", "reference": "../option-1.png"},
    {"feedback": "x", "mode": "revise", "reference": "option-2.png"},
    {"feedback": "x", "mode": "variants"},
])
def test_feedback_api_invalid_input_is_400_without_socket(service, monkeypatch, body):
    from auto_short.packaging import cover_suggest
    monkeypatch.setattr(cover_suggest, "available", lambda _: None)
    doc = cover_suggest.create(service.cfg, PID)
    doc["status"] = "done"
    cover_suggest.save(cover_suggest.directory(service.cfg, PID, doc["run_id"]), doc)
    result = feedback_endpoint(service.app)(pid=PID, run_id=doc["run_id"], body=body)
    assert result.status_code == 400
    assert len(list(cover_suggest.directory(service.cfg, PID).iterdir())) == 1


def test_feedback_api_busy_parent_and_global_lock_without_socket(service, monkeypatch):
    import threading
    from auto_short.packaging import cover_suggest
    s = service
    monkeypatch.setattr(cover_suggest, "available", lambda _: None)
    parent = cover_suggest.create(s.cfg, PID)
    endpoint = feedback_endpoint(s.app)
    body = dict(feedback="Thu nhỏ khung", mode="options")
    assert endpoint(pid=PID, run_id=parent["run_id"], body=body).status_code == 409
    parent["status"] = "done"
    cover_suggest.save(cover_suggest.directory(s.cfg, PID, parent["run_id"]), parent)
    entered, release = threading.Event(), threading.Event()
    def hold(*args, **kwargs):
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(cover_suggest, "execute", hold)
    try:
        s.service.suggest(PID)
        assert entered.wait(2)
        assert endpoint(pid=PID, run_id=parent["run_id"], body=body).status_code == 409
        other = web.EpisodeThumbs(s.service.plans)
        with pytest.raises(web.Unavailable):
            other.suggest(PID, parent_run=parent["run_id"], feedback="Màu xanh", mode="options")
    finally:
        release.set()
        s.service.suggest_thread.join(3)
    assert endpoint(pid=PID, run_id=parent["run_id"], body=body).status_code == 202
    s.service.suggest_thread.join(3)


def test_feedback_ui_controls_without_socket():
    from pathlib import Path
    static = Path(web.__file__).parent / "static"
    html = (static / "thumbs.html").read_text()
    script = (static / "thumbs.js").read_text()
    assert 'id="thumbs-feedback" maxlength="300"' in html
    for text in ("Góp ý cho Codex", "Vẽ lại 4 mẫu theo góp ý", "Vẽ lại 3 ảnh theo góp ý", "Góp ý đã áp dụng"):
        assert text in html
    assert "Sửa mẫu này theo góp ý" in script
    assert 'feedback("options")' in script and 'feedback("variants")' in script and 'feedback("revise", name)' in script
    assert "feedbackDisabled" in script and "view.codex_unavailable" in script
    assert '$("thumbs-feedback-panel").hidden = !s || running' in script


def test_http_feedback_auth_and_input_status(client, monkeypatch):
    from auto_short.packaging import cover_suggest
    s = client
    monkeypatch.setattr(cover_suggest, "available", lambda _: None)
    parent = cover_suggest.create(s.cfg, PID)
    url = BASE + f"/suggest/{parent['run_id']}/feedback"
    body = dict(feedback="Thu nhỏ khung", mode="options")
    anon = TestClient(s.app, follow_redirects=False)
    assert anon.post(url, json=body).status_code == 401
    assert s.c.post(url, json=body).status_code == 409
    parent["status"] = "done"
    cover_suggest.save(cover_suggest.directory(s.cfg, PID, parent["run_id"]), parent)
    for invalid in ({}, [], dict(feedback=" ", mode="options"), dict(feedback="x" * 301, mode="options"),
                    dict(feedback="x", mode="revise", reference="../option-1.png")):
        assert s.c.post(url, json=invalid).status_code == 400
    monkeypatch.setattr(cover_suggest, "execute", lambda *args, **kwargs: None)
    result = s.c.post(url, json=body)
    assert result.status_code == 202 and result.json()["parent_run"] == parent["run_id"]
    s.service.suggest_thread.join(3)


def test_http_kt_current_cover_flow_auth_busy_ids_feedback_and_install(client, tmp_path, monkeypatch):
    """AC10: ORCHESTRATOR runs TestClient coverage outside the socket-restricted sandbox."""
    import threading
    from auto_short.packaging import cover, cover_suggest
    from test_cover_suggest import fake_codex
    from test_khaithi_thumbs import seed_kt, portrait_manifest
    from test_packaging_cover import source_image
    s = client
    seed_kt(s.cfg)
    portrait_manifest(s.cfg)
    monkeypatch.setattr(cover_suggest, "available", lambda _: None)
    anon = TestClient(s.app, follow_redirects=False)
    url = BASE + "/suggest-kt"
    assert anon.post(url, json={}).status_code == 401
    assert s.c.post("/api/playlists/bad!/thumbs/suggest-kt", json={}).status_code == 404
    monkeypatch.setattr(cover_suggest, "available", lambda _: "chưa cài Codex trên máy chủ")
    assert s.c.post(url, json={}).status_code == 503
    monkeypatch.setattr(cover_suggest, "available", lambda _: None)
    assert s.c.post(url, json={}).status_code == 400  # no installed vertical cover
    artwork = {"vertical": source_image(tmp_path, (540, 960)), "landscape": source_image(tmp_path, (640, 360))}
    for shape in ("vertical", "landscape"):
        cover.install(s.cfg, PID, shape, artwork[shape], [100, 700, 300, 100] if shape == "vertical" else [100, 240, 300, 50])
    original = cover.current(s.cfg, PID)
    reference = (cover.directory(s.cfg, PID) / original["vertical"]["file"]).read_bytes()
    s.service.media_runner = None
    entered, release = threading.Event(), threading.Event()
    def runner(cmd, **kwargs):
        from pathlib import Path
        assert Path(cmd[cmd.index("-i") + 1]).read_bytes() == reference
        entered.set()
        assert release.wait(10)
        return fake_codex(artwork)(cmd, **kwargs)
    s.service.codex_runner = runner
    try:
        result = s.c.post(url, json=dict(notes="Nền dịu"))
        assert result.status_code == 202
        run_id = result.json()["run_id"]
        assert entered.wait(3)
        assert s.c.post(url, json={}).status_code == 409
    finally:
        release.set()
        s.service.suggest_thread.join(30)
    assert not s.service.suggest_thread.is_alive()
    run_url = BASE + f"/suggest/{run_id}"
    done = s.c.get(run_url).json()
    assert done["phase"] == "kt" and done["status"] == "done", done.get("error")
    assert len(done["previews"]) == 2
    for preview in done["previews"]:
        assert s.c.get(preview["preview_url"]).status_code == 200
    assert s.c.get(run_url + "/images/ref.png").status_code == 400
    assert s.c.post(run_url + "/install").status_code == 200
    assert {shape: cover.current(s.cfg, PID)[shape] for shape in original} == original
    assert s.c.post(run_url + "/feedback", json=dict(mode="kt", feedback="Màu xanh dịu")).status_code == 202
    s.service.suggest_thread.join(30)
    assert not s.service.suggest_thread.is_alive()
    html = s.c.get(f"/playlists/{PID}/thumbs").text
    script = s.c.get("/static/thumbs.js").text
    assert "Vẽ ảnh khai thị theo bìa hiện tại" in html
    assert "Dùng 2 ảnh này" in script and "Vẽ lại 2 ảnh theo góp ý" in script
    assert '"/suggest-kt"' in script and 'feedback("kt")' in script
