"""AUD2 AC8. TestClient checks must be run by ORCHESTRATOR outside the socket-restricted sandbox."""
from __future__ import annotations

from contextlib import contextmanager
from urllib.parse import unquote
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from auto_short import khaithi
from auto_short.config import Config, PackagingConfig, PostConfig, RenderConfig, WorkspaceConfig
from auto_short.hashing import sha256_file
from auto_short.packaging import assets, music
from auto_short.store.client import StoreUnavailable
from auto_short.web import music as web_music
from auto_short.web.jobs import KIND_MUSIC, MODE_LANES, RENDER
from auto_short.workspace import atomic_write_json

from web_helpers import login, web_client, write_episode

EID = "aaaaaaaaaa1.kt"
BASE = f"/api/music/clip/{EID}/k01"
PID, CID, PLAN = "PLabcdefghijk", "0123456789ab", "abcd1234"


@pytest.fixture
def cfg(tmp_path):
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "out"),
                  packaging=PackagingConfig(asset_dir=tmp_path / "assets"), post=PostConfig(image_dir=tmp_path / "images"))


@pytest.fixture
def setup(cfg):
    write_episode(cfg, EID)
    khaithi.write(Path(cfg.workspace.dir) / EID, khaithi.KhaiThi(EID.removesuffix(".kt"), 4, 7))
    folder = cfg.packaging.asset_dir
    folder.mkdir(parents=True)
    path = folder / ("a" * 64 + ".wav")
    path.write_bytes(b"approved synthetic music bytes")
    digest = sha256_file(path)
    renamed = path.with_name(digest + ".wav")
    path.rename(renamed)
    entry = dict(id=digest, file=renamed.name, source="Studio", license="Verified", approved=True,
                 width=0, height=0, duration=60, tags=[], kind="music", title="Test title", artist="Test artist", attribution="Artist")
    atomic_write_json(folder / "library.json", dict(schema_version=1, assets=[entry]))
    return cfg, dict(asset_id=digest)


def publish_fake(source, intro_offset, spec, asset_dir, **kw):
    """Only replace ffmpeg for route tests; core tests verify actual encoding and gates."""
    kw["before_publish"]()
    folder = kw["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    ident = music.key(spec, sha256_file(source), spec["asset_id"], kw["audio_bitrate"])
    name = kw["stem"] + "-" + ident[:12]
    output = folder / (name + ".mp4")
    output.write_bytes(b"verified music output")
    doc = dict(key=ident, spec=spec, file=output.name, sha256=sha256_file(output), built_at="2026-11-01T12:00:00Z",
               source_sha256=sha256_file(source), attribution="Artist", music_version=music.MUSIC_VERSION)
    atomic_write_json(folder / (name + ".json"), doc)
    return doc


def test_auth_ids_traversal_symlink_and_no_music(setup, monkeypatch, tmp_path):
    cfg, spec = setup
    with web_client(cfg) as c:
        for method, path in (("GET", BASE), ("POST", BASE), ("POST", BASE + "/preview"),
                             ("POST", BASE + "/cancel"), ("DELETE", BASE), ("GET", BASE + "/file"), ("GET", BASE + "/preview/1")):
            assert c.request(method, path, json=spec if method == "POST" else None).status_code == 401
        login(c)
        assert c.post(BASE, json={"asset_id": ""}).json() == {"job": None}
        assert not (Path(cfg.render.output_dir) / EID / "music").exists()
        for path in ("/api/music/clip/aaaaaaaaaa1/k01", "/api/music/clip/bad!/k01", BASE.replace("k01", "bad!"),
                     "/api/music/unknown/aaaaaaaaaa1/k01", "/api/music/theme/bad!/abcd1234",
                     BASE.replace("k01", "%2e%2e%2fsecret")):
            assert c.get(path).status_code in (404, 422)
        out = Path(cfg.render.output_dir) / EID
        for target in (out / "music", out / "shorts" / "k01.mp4"):
            saved = target.with_suffix(".saved")
            if target.exists():
                target.rename(saved)
            target.symlink_to(tmp_path / "outside")
            assert c.get(BASE).status_code == 422
            target.unlink()
            if saved.exists():
                saved.rename(target)
        assert c.get(BASE + "/preview/0").status_code == 404
        assert c.get(BASE + "/preview/3").status_code == 404


def test_job_render_lane_dedup_cancel_restart(setup, monkeypatch):
    cfg, spec = setup
    calls = []
    monkeypatch.setattr(music, "mix", lambda *args, **kw: calls.append(args))
    with web_client(cfg) as c:
        login(c)
        runner = c.app.state.runner
        # Queue in render lane while paused; preview and full mix share the same video key.
        runner.pause("after")
        result = c.post(BASE, json=spec)
        assert result.status_code == 200
        job = result.json()["job"]
        assert job["kind"] == KIND_MUSIC
        current = runner.latest(c.app.state.music.job_key("clip", EID, "k01"))
        assert current.steps[0].lane == (RENDER if runner.mode == MODE_LANES else "serial")
        assert c.post(BASE, json=spec).status_code == 409
        assert c.post(BASE + "/preview", json=spec).status_code == 409
        assert c.delete(BASE).status_code == 409
        assert c.post(BASE + "/cancel").status_code == 200
        assert not current.active
        # Verify the app's queue recreation policy without restarting any running service.
        assert runner._rebuild(KIND_MUSIC, current.episode_id, {}, []) is None
        assert not calls


def test_download_stale_attribution_and_delete(setup, monkeypatch):
    cfg, spec = setup
    monkeypatch.setattr(music, "mix", publish_fake)
    with web_client(cfg) as c:
        login(c)
        assert c.post(BASE, json=spec).status_code == 200
        assert c.app.state.runner.wait_idle(10)
        view = c.get(BASE).json()
        assert view["state"] == "ready" and view["attribution"] == "Artist"
        assert view["description"] == "Nhạc: Artist"
        response = c.get(view["download_url"])
        assert response.status_code == 200
        assert " (nhạc).mp4" in unquote(response.headers["content-disposition"])
        assets.unapprove(cfg.packaging.asset_dir, spec["asset_id"])
        assert c.get(BASE).json()["state"] == "stale"
        assert c.get(BASE + "/file").status_code == 409
        assert c.get(BASE).json()["assets"] == []
        assets.approve(cfg.packaging.asset_dir, spec["asset_id"])
        source = Path(cfg.render.output_dir) / EID / "shorts" / "k01.mp4"
        source.write_bytes(b"new source revision")
        assert c.get(BASE).json()["state"] == "stale"
        assert c.get(BASE + "/file").status_code == 409
        assert c.delete(BASE).status_code == 200
        assert not list((source.parent.parent / "music").glob("*.mp4"))


def test_compilation_and_theme_sources_and_controls(setup, monkeypatch):
    cfg, spec = setup
    monkeypatch.setattr(music, "mix", publish_fake)
    with web_client(cfg) as c:
        login(c)
        service = c.app.state.music
        folder = Path(cfg.render.output_dir) / "_compilations" / PID
        folder.mkdir(parents=True)
        (folder / (CID + ".mp4")).write_bytes(b"compilation source")
        atomic_write_json(folder / (CID + ".json"), dict(cid=CID, playlist_id=PID, status="done", mode="concat", chapters=[],
                          title="Video", download_name="Original.mp4", description="Original description"))
        monkeypatch.setattr(service.compilations.playlists, "load", lambda pid: dict(playlist_id=pid, entries=[]))
        monkeypatch.setattr(service.compilations.playlists, "effective_hashtags", lambda doc: ([], True))
        monkeypatch.setattr(service.compilations, "compilation_view", lambda doc, tags: dict(description="00:00 Original chapter"))
        base = f"/api/music/compilation/{PID}/{CID}"
        assert c.post(base, json=spec).status_code == 200
        assert c.app.state.runner.wait_idle(10)
        assert c.get(base).json()["description"] == "00:00 Original chapter\n\nNhạc: Artist"
        theme = folder / "theme"
        theme.mkdir()
        path = theme / (PLAN + "-r1.mp4")
        path.write_bytes(b"theme source")
        monkeypatch.setattr(service.theme_plans, "find", lambda pid, plan: dict(plan_id=PLAN, revision=1))
        monkeypatch.setattr(service.theme_plans, "output", lambda *args, **kw: (path, dict(download_name="Theme.mp4", description="00:00 Theme chapter")))
        base = f"/api/music/theme/{PID}/{PLAN}"
        assert c.post(base, json=spec).status_code == 200
        assert c.app.state.runner.wait_idle(10)
        assert c.get(base).json()["state"] == "ready"
        assert list((theme / "music").glob(PLAN + "-r1-*.mp4"))
        monkeypatch.setattr(service.theme_plans, "find", lambda pid, plan: dict(plan_id=PLAN, revision=2))
        monkeypatch.setattr(service.theme_plans, "output", lambda *args, **kw: None)
        assert c.get(base).json()["state"] == "stale"
        assert c.get(base + "/file").status_code == 409
        for name, needle in (("app.js", 'musicBlock("clip"'), ("favorites.js", 'musicBlock("compilation"'), ("theme_plan.js", 'musicBlock("theme"')):
            assert needle in c.get("/static/" + name).text
        assert "Không nhạc" in c.get("/static/app.js").text


@pytest.mark.parametrize("unavailable", [False, True])
def test_store_borrow_and_unavailable_reason(setup, monkeypatch, unavailable):
    cfg, spec = setup
    out = Path(cfg.render.output_dir) / EID
    source = out / "shorts" / "k01.mp4"
    digest, size = sha256_file(source), source.stat().st_size
    doc = __import__("json").loads((out / "render_manifest.json").read_text())
    doc["shorts"][0].update(sha256=digest, intro=dict(sha256="b" * 64), content_offset=3)
    atomic_write_json(out / "render_manifest.json", doc)
    atomic_write_json(out / "store.json", dict(released=dict(k01=dict(sha256=digest, size=size, mtime_ns=1))))
    data = source.read_bytes()
    source.unlink()
    called = []
    @contextmanager
    def borrow(config, location, folder):
        called.append(location)
        if unavailable:
            raise StoreUnavailable("offline")
        copy = folder / "borrow.mp4"
        copy.write_bytes(data)
        atomic_write_json(copy.with_suffix(".intro.json"), doc["shorts"][0])
        try:
            yield copy
        finally:
            copy.unlink(missing_ok=True)
            copy.with_suffix(".intro.json").unlink(missing_ok=True)
    monkeypatch.setattr(web_music, "borrow_short", borrow)
    seen = []
    def build(*args, **kw):
        seen.append(args[1])
        return publish_fake(*args, **kw)
    monkeypatch.setattr(music, "mix", build)
    with web_client(cfg) as c:
        login(c)
        assert c.post(BASE, json=spec).status_code == 200
        assert c.app.state.runner.wait_idle(10)
        state = c.get(BASE).json()
        assert called
        if unavailable:
            assert state["job"]["status"] == "failed"
            assert state["job"]["error"] == "đang ở kho 3090, thử lại sau"
        else:
            assert seen == [3] and state["state"] == "ready"
            assert state["spec"]["fade_in"] == 3
        assert not source.exists()


def test_preview_two_thirty_second_files(setup, monkeypatch):
    cfg, spec = setup
    def preview(source, intro_offset, spec, asset_dir, **kw):
        folder = kw["folder"]
        folder.mkdir(parents=True, exist_ok=True)
        ident = music.key(spec, sha256_file(source), spec["asset_id"], kw["audio_bitrate"])
        stem = kw["stem"] + "-" + ident[:12]
        previews = []
        for i, start in enumerate((0, 40), 1):
            path = folder / f"{stem}-preview-{i}.m4a"
            path.write_bytes(b"preview AAC")
            previews.append(dict(file=path.name, sha256=sha256_file(path), start=start, duration=30))
        doc = dict(key=ident, spec=spec, source_sha256=sha256_file(source), attribution="Artist", built_at="now", previews=previews)
        atomic_write_json(folder / (stem + "-preview.json"), doc)
        return doc
    monkeypatch.setattr(music, "preview", preview)
    with web_client(cfg) as c:
        login(c)
        assert c.post(BASE + "/preview", json=spec).status_code == 200
        assert c.app.state.runner.wait_idle(10)
        view = c.get(BASE).json()
        assert len(view["previews"]) == 2
        assert [p["duration"] for p in view["previews"]] == [30, 30]
        for p in view["previews"]:
            assert c.get(p["url"]).status_code == 200
