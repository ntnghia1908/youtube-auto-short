"""WATCH1: pure room invariants and authenticated HTTP integration, no real services."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_short.web.watch_party import WatchConflict, WatchRoom

QUEUE = [{"url": f"/files/clip{i}.mp4", "title": f"Video {i}"} for i in range(3)]


@pytest.fixture
def room():
    now = [100.0]
    return WatchRoom(clock=lambda: now[0]), now


def test_commands_and_extrapolation(room):  # AC1,5
    r, now = room
    first = r.command("a", "set", queue=QUEUE, index=1, position=12)
    assert (first["video_url"], first["title"], first["position"], first["paused"], first["rate"]) == (
        QUEUE[1]["url"], "Video 1", 12, False, 1)
    now[0] += 3
    view = r.snapshot("b")
    assert view["position"] + (view["server_time"] - view["updated_at"]) * view["rate"] == 15
    paused = r.command("b", "pause")
    assert paused["position"] == 15 and paused["paused"] and paused["by"] == "b"
    now[0] += 4
    assert r.command("a", "seek", position=30)["position"] == 30
    assert r.command("a", "rate", rate=2)["rate"] == 2
    playing = r.command("a", "play")
    now[0] += 3
    view = r.snapshot()
    assert view["position"] + (view["server_time"] - view["updated_at"]) * view["rate"] == 36
    rated = r.command("a", "rate", rate=.5)
    assert rated["position"] == 36  # changing speed preserves the current anchor
    assert first["version"] < paused["version"] < playing["version"] < rated["version"]
    r.command("a", "pause", position=38)
    now[0] += 5
    assert r.snapshot()["position"] == 38


BAD_URLS = ["http://evil/video", "https://evil/video", "//evil/video", "javascript:alert(1)",
            "clip.mp4", "", "/\\evil/video", "/x\\y", "/x\ny", "/x\x00y", "/x\x7fy", "/" + "x" * 2048]


@pytest.mark.parametrize("url", BAD_URLS)
def test_reject_urls_atomically(room, url):  # AC2,8
    r, _ = room
    r.command("a", "set", queue=QUEUE)
    before = r.snapshot()
    with pytest.raises(ValueError):
        r.command("b", "set", queue=[QUEUE[0], {"url": url, "title": "bad"}])
    assert r.snapshot() == before


@pytest.mark.parametrize("data", [
    {"queue": []}, {"queue": QUEUE * 101}, {"queue": [{"url": "/v", "title": "x" * 201}]},
    {"queue": [None]}, {"queue": "oops"}, {"index": -1}, {"index": 3}, {"index": True},
    {"position": -1}, {"position": 10 ** 400}, {"position": float("inf")}, {"position": True}, {"rate": .24},
    {"rate": 4.01}, {"rate": float("nan")}, {"rate": "1"}, {"paused": "false"},
])
def test_reject_invalid_set_without_mutation(room, data):  # AC2,8
    r, _ = room
    r.command("a", "set", queue=QUEUE)
    before = r.snapshot()
    with pytest.raises(ValueError):
        r.command("b", "set", **({"queue": QUEUE} | data))
    assert r.snapshot() == before


def test_viewer_expiry_leave_end_and_copies(room):  # AC4
    r, now = room
    assert r.snapshot("idle")["viewers"] == {}
    r.command("a", "set", queue=QUEUE)
    view = r.snapshot("b")
    view["queue"][0]["url"] = "/changed"
    view["viewers"].clear()
    assert r.snapshot()["queue"] == QUEUE and len(r.snapshot()["viewers"]) == 2
    now[0] += 9.9
    assert set(r.snapshot("b")["viewers"]) == {"a", "b"}
    now[0] += .1
    assert set(r.snapshot()["viewers"]) == {"b"}
    assert r.command("b", "leave")["viewers"] == {}
    end = r.command("a", "end")
    assert end["video_url"] is None and end["queue"] == [] and end["paused"] and end["viewers"] == {}
    assert r.snapshot("b")["video_url"] is None


def test_queue_cas_navigation_and_end(room):  # AC8
    r, _ = room
    start = r.command("a", "set", queue=QUEUE, index=0)
    assert start["queue"] == QUEUE
    next_view = r.command("a", "next", expect_version=start["version"])
    assert next_view["index"] == 1 and next_view["position"] == 0
    with pytest.raises(WatchConflict):
        r.command("b", "next", expect_version=start["version"])
    assert r.snapshot()["index"] == 1 and r.snapshot()["version"] == next_view["version"]
    last = r.command("b", "goto", index=2)
    end = r.command("b", "next", expect_version=last["version"])
    assert end["index"] == 2 and end["paused"]
    assert r.command("a", "prev", expect_version=end["version"])["index"] == 1
    # Maximum accepted queue, title and URL boundaries.
    r.command("a", "set", queue=[{"url": "/" + "a" * 2047, "title": "t" * 200}] * 300, index=299)
    assert len(r.snapshot()["queue"]) == 300


def test_simultaneous_ended_only_advances_once(room):  # AC8
    r, _ = room
    version = r.command("a", "set", queue=QUEUE)["version"]
    def ended(client):
        try:
            r.command(client, "next", expect_version=version)
            return "ok"
        except WatchConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(ended, ["a", "b"])) == ["conflict", "ok"]
    assert r.snapshot()["index"] == 1


@pytest.mark.parametrize("action,data", [
    ("seek", {"position": -1}), ("rate", {"rate": 5}), ("goto", {"index": 3}),
    ("next", {}), ("prev", {"expect_version": True}), ("unknown", {}),
])
def test_bad_commands_leave_state_intact(room, action, data):
    r, _ = room
    r.command("a", "set", queue=QUEUE)
    before = r.snapshot()
    with pytest.raises(ValueError):
        r.command("b", action, **data)
    assert r.snapshot() == before


@pytest.fixture
def web(cfg):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from web_helpers import make_app
    with TestClient(make_app(cfg), follow_redirects=False) as client:
        yield client


def test_http_auth(web):  # AC3
    calls = [("GET", "/api/watch"), ("GET", "/api/watch/audio/youtube0001/k01"), ("POST", "/api/watch"),
             ("POST", "/api/watch/leave"), ("DELETE", "/api/watch")]
    for method, path in calls:
        assert web.request(method, path, json={"client": "a", "action": "set", "queue": QUEUE}).status_code == 401
    response = web.get("/watch")
    assert response.status_code in (302, 303, 307) and response.headers["location"].startswith("/login")


def test_http_room_lifecycle_and_validation(web):  # AC1,2,4,8
    from web_helpers import login
    login(web)
    page = web.get("/watch")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
    assert '/static/watch.js" defer' in page.text
    first = web.post("/api/watch", json={"client": "a", "action": "set", "queue": QUEUE, "index": 1, "position": 3}).json()
    view = web.get("/api/watch?client=b").json()
    assert view["queue"] == QUEUE and view["index"] == 1 and view["video_url"] == QUEUE[1]["url"]
    assert view["version"] == first["version"] and view["position"] == 3 and not view["paused"]
    assert set(view["viewers"]) == {"a", "b"} and "server_time" in view
    for action, args in [("pause", {"position": 4}), ("seek", {"position": 5}), ("rate", {"rate": 1.5}), ("play", {})]:
        response = web.post("/api/watch", json={"client": "b", "action": action, **args})
        assert response.status_code == 200 and response.json()["version"] > view["version"]
        view = response.json()
    for url in BAD_URLS:
        response = web.post("/api/watch", json={"client": "a", "action": "set", "video_url": url})
        assert response.status_code == 422
    for queue in [QUEUE * 101, [{"url": "/v", "title": "x" * 201}], [QUEUE[0], {"url": "//evil/x"}]]:
        assert web.post("/api/watch", json={"client": "a", "action": "set", "queue": queue}).status_code == 422
    assert web.get("/api/watch").json()["version"] == view["version"]
    assert web.post("/api/watch", json={"client": "a", "action": "next", "expect_version": first["version"]}).status_code == 409
    last = web.post("/api/watch", json={"client": "a", "action": "next", "expect_version": view["version"]}).json()
    end = web.post("/api/watch", json={"client": "b", "action": "next", "expect_version": last["version"]}).json()
    assert end["index"] == 2 and end["paused"]
    assert "b" not in web.post("/api/watch/leave", json={"client": "b"}).json()["viewers"]
    assert web.request("DELETE", "/api/watch", json={"client": "a"}).json()["video_url"] is None
    assert web.get("/api/watch").json()["queue"] == []


def test_http_rooms_are_per_app(cfg):
    from fastapi.testclient import TestClient
    from web_helpers import login, make_app
    with TestClient(make_app(cfg), follow_redirects=False) as a, TestClient(make_app(cfg), follow_redirects=False) as b:
        login(a)
        login(b)
        a.post("/api/watch", json={"client": "a", "action": "set", "queue": QUEUE})
        assert b.get("/api/watch").json()["queue"] == []


EID, PID = "youtube0001.kt", "PLwatch00001"


def endpoint(app, path, method="GET"):
    # FastAPI may keep included routers nested (same traversal as test_store_download.py).
    routes = list(app.routes)
    while routes:
        route = routes.pop(0)
        if hasattr(route, "original_router"):
            routes[0:0] = route.original_router.routes
        elif getattr(route, "path", None) == path and method in route.methods:
            return route.endpoint
    raise AssertionError(f"Missing route: {method} {path}")


def set_room(app, url):
    return json.loads(endpoint(app, "/api/watch", "POST")(
        {"client": "old-tab", "action": "set", "queue": [{"url": url, "title": "Video"}]}).body)


def test_client_fav_is_ignored_and_favorite_action_removed(room):  # AC15
    r, _ = room
    view = r.command("a", "set", queue=[{**QUEUE[0], "fav": {"untrusted": True}}], fav="ignored")
    assert view["queue"] == [QUEUE[0]]
    with pytest.raises(ValueError):
        r.command("a", "favorite", index=0, favorite=True)
    assert r.snapshot() == view


def test_fav_derived_and_refreshed_from_real_favorites(cfg):  # AC15, no TestClient/socket
    from auto_short.compilation import Item, store
    from web_helpers import make_app
    folder = Path(cfg.workspace.dir) / "_playlists"
    folder.mkdir(parents=True)
    (folder / (PID + ".json")).write_text(json.dumps({"playlist_id": PID,
        "entries": [{"video_id": "youtube0001", "available": True}]}))
    app = make_app(cfg)
    view = set_room(app, f"/files/{EID}/k01.mp4?inline=1")
    expected = dict(playlist_id=PID, episode_id=EID, clip="k01", favorite=False)
    assert view["fav"] == expected and "fav" not in view["queue"][0]
    store.write_favorites(app.state.compilations.folder(PID), [Item(EID, "k01")])
    fresh = json.loads(endpoint(app, "/api/watch")("other").body)
    assert fresh["fav"] == {**expected, "favorite": True}
    assert fresh["version"] == view["version"]  # derived metadata is not room playback state
    store.write_favorites(app.state.compilations.folder(PID), [])
    assert json.loads(endpoint(app, "/api/watch")().body)["fav"] == expected


@pytest.mark.parametrize("url", [f"/files/{EID}/k02.mp4?download=1", "/files/invalid!/k01.mp4",
                                   f"/files/{EID}/bad.clip.mp4", "/files/compilation.mp4"])
def test_fav_only_for_valid_clip_and_owned_episode(cfg, monkeypatch, url):  # AC15
    from web_helpers import make_app
    app = make_app(cfg)
    seen = []
    def favorites(episode):
        seen.append(episode)
        return None
    monkeypatch.setattr(app.state.compilations, "episode_favorites", favorites)
    assert set_room(app, url)["fav"] is None
    assert seen == ([EID] if url.startswith(f"/files/{EID}/k02") else [])


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    from auto_short.web import watch_audio
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert args[0] == "ffmpeg"
        assert args[args.index("-c:a") + 1] == "copy" and "-vn" in args
        assert args[args.index("-map") + 1] == "0:a:0"
        assert args[args.index("-movflags") + 1] == "+faststart"
        assert kwargs["check"] is True
        Path(args[-1]).write_bytes(b"m4a-data")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(watch_audio.subprocess, "run", run)
    return calls


def test_audio_route_local_remux_cache_and_changed_manifest(cfg, fake_ffmpeg):  # AC16
    from web_helpers import make_app, write_episode
    write_episode(cfg, EID)
    app = make_app(cfg)
    get = endpoint(app, "/api/watch/audio/{episode_id}/{clip}")
    assert get("invalid/path", "k01").status_code == 404
    assert get(EID, "invalid.clip").status_code == 404
    assert get(EID, "missing").status_code == 404
    first = get(EID, "k01")
    assert first.status_code == 200 and first.media_type == "audio/mp4"
    assert Path(first.path).name == "0" * 64 + ".m4a"
    args, _ = fake_ffmpeg[0]
    assert args[args.index("-i") + 1] == str(Path(cfg.render.output_dir) / EID / "shorts/k01.mp4")
    assert Path(first.path).read_bytes() == b"m4a-data"
    assert get(EID, "k01").path == first.path and len(fake_ffmpeg) == 1
    manifest = Path(cfg.render.output_dir) / EID / "render_manifest.json"
    doc = json.loads(manifest.read_text())
    doc["shorts"][0]["sha256"] = "a" * 64
    manifest.write_text(json.dumps(doc))
    assert Path(get(EID, "k01").path).name == "a" * 64 + ".m4a" and len(fake_ffmpeg) == 2


def test_audio_route_stored_short_offline_and_fetch_parameters(cfg, monkeypatch, fake_ffmpeg):  # AC16
    from auto_short.config import StoreConfig
    from auto_short.web.routes import watch
    from web_helpers import make_app, write_episode
    files = write_episode(cfg, EID)
    out = Path(cfg.render.output_dir) / EID
    source = out / "shorts/k01.mp4"
    stat = source.stat()
    (out / "store.json").write_text(json.dumps({"released": {"k01": {
        "sha256": "0" * 64, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}}}))
    source.unlink()
    off = endpoint(make_app(cfg), "/api/watch/audio/{episode_id}/{clip}")
    assert off(EID, "k01").status_code == 503 and not fake_ffmpeg
    fetched = []
    class Store:
        up = False
        def available(self):
            return self.up
        def fetch(self, video_id, kind, dest, sha256, *, clip):
            assert (video_id, kind, sha256, clip) == (EID, "short", "0" * 64, "k01.mp4")
            assert dest.parent.parent == Path(cfg.workspace.dir) / "_watch_audio"
            fetched.append(dest)
            dest.write_bytes(files["k01"])
    client = Store()
    monkeypatch.setattr(watch.StoreClient, "from_config", lambda config: client)
    online_cfg = replace(cfg, store=StoreConfig(enabled=True))
    get = endpoint(make_app(online_cfg), "/api/watch/audio/{episode_id}/{clip}")
    assert get(EID, "k01").status_code == 503 and not fake_ffmpeg
    client.up = True
    response = get(EID, "k01")
    assert response.status_code == 200 and len(fake_ffmpeg) == len(fetched) == 1
    assert not fetched[0].exists()  # temporary original is cleaned after remux
    assert get(EID, "k01").path == response.path and len(fetched) == 1


def test_audio_cache_concurrent_requests_remux_once(tmp_path):  # AC16
    from auto_short.web.watch_audio import AudioCache
    started, release = threading.Event(), threading.Event()
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        started.set()
        assert release.wait(5)
        Path(args[-1]).write_bytes(b"m4a")
    cache = AudioCache(tmp_path / "cache", run=run)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get, "a" * 64, tmp_path / "source.mp4")
        assert started.wait(5)
        second = pool.submit(cache.get, "a" * 64, tmp_path / "source.mp4")
        release.set()
        assert first.result(timeout=5) == second.result(timeout=5)
    assert len(calls) == 1


def test_audio_cache_failure_is_atomic_and_cleans_temp(tmp_path):  # AC16
    from auto_short.web.watch_audio import AudioCache, WatchAudioError
    def run(args, **kwargs):
        Path(args[-1]).write_bytes(b"partial")
        raise subprocess.CalledProcessError(1, args)
    cache = AudioCache(tmp_path / "cache", run=run)
    with pytest.raises(WatchAudioError):
        cache.get("a" * 64, tmp_path / "source.mp4")
    assert list(cache.root.iterdir()) == []
    with pytest.raises(WatchAudioError):
        cache.get("../escape", tmp_path / "source.mp4")


def test_audio_cache_evicts_oldest_mtime(tmp_path):  # AC16; small injected quota instead of 2 GB
    from auto_short.web.watch_audio import AudioCache
    def run(args, **kwargs):
        Path(args[-1]).write_bytes(b"1234")
    cache = AudioCache(tmp_path / "cache", run=run, max_bytes=8)
    a = cache.get("a" * 64, tmp_path / "source.mp4")
    b = cache.get("b" * 64, tmp_path / "source.mp4")
    os.utime(a, (10, 10))
    os.utime(b, (20, 20))
    c = cache.get("c" * 64, tmp_path / "source.mp4")
    assert not a.exists() and b.exists() and c.exists()
    assert sum(p.stat().st_size for p in cache.root.glob("*.m4a")) == 8


def test_audio_real_remux_has_only_aac_and_faststart(video, tmp_path):  # AC16, tiny local ffmpeg fixture
    from auto_short.web.watch_audio import AudioCache
    result = AudioCache(tmp_path / "cache").get(hashlib.sha256(video.read_bytes()).hexdigest(), video)
    streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
        "-of", "json", str(result)], check=True, capture_output=True, text=True).stdout)["streams"]
    assert streams == [{"codec_name": "aac", "codec_type": "audio"}]
    data = result.read_bytes()
    assert data.index(b"moov") < data.index(b"mdat")


def test_http_watch_fav_is_fresh_without_client_metadata(web, monkeypatch):  # AC15
    from web_helpers import login
    login(web)
    favorites = {"playlist_id": PID, "clips": []}
    monkeypatch.setattr(web.app.state.compilations, "episode_favorites", lambda eid: favorites)
    response = web.post("/api/watch", json={"client": "old-tab", "action": "set",
        "queue": [{"url": f"/files/{EID}/k01.mp4?inline=1", "title": "Video", "fav": "ignored"}]})
    assert response.json()["fav"]["favorite"] is False
    favorites["clips"].append("k01")
    assert web.get("/api/watch?client=other").json()["fav"]["favorite"] is True
    assert web.post("/api/watch", json={"client": "a", "action": "favorite", "index": 0, "favorite": False}).status_code == 422


def test_http_audio_range_auth_and_cache(cfg, fake_ffmpeg):  # AC16
    from fastapi.testclient import TestClient
    from web_helpers import login, make_app, write_episode
    write_episode(cfg, EID)
    with TestClient(make_app(cfg), follow_redirects=False) as client:
        path = f"/api/watch/audio/{EID}/k01"
        assert client.get(path).status_code == 401
        login(client)
        assert client.get(f"/api/watch/audio/{EID}/bad.clip").status_code == 404
        response = client.get(path)
        assert response.status_code == 200 and response.headers["content-type"].startswith("audio/mp4")
        partial = client.get(path, headers={"Range": "bytes=0-3"})
        assert partial.status_code == 206 and partial.content == response.content[:4]
        assert len(fake_ffmpeg) == 1
