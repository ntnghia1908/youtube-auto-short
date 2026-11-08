"""WATCH1: pure room invariants and authenticated HTTP integration, no real services."""
from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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


def test_auto_defaults_updates_preserve_playback_and_reset(room):  # LISTEN1 AC11
    r, now = room
    assert r.snapshot()["auto"] is True
    first = r.command("a", "set", queue=QUEUE, position=12)
    now[0] += 3
    manual = r.command("b", "auto", auto=False)
    assert manual["auto"] is False and not manual["paused"]
    assert manual["position"] == 15 and manual["index"] == 0 and manual["queue"] == QUEUE
    assert manual["version"] == first["version"] + 1 and manual["by"] == "b"
    assert r.snapshot("a")["auto"] is False
    assert r.command("a", "next", expect_version=manual["version"])["index"] == 1
    assert r.command("a", "set", queue=QUEUE)["auto"] is False
    assert r.command("b", "auto", auto=True)["auto"] is True
    r.command("a", "auto", auto=False)
    assert r.command("a", "end")["auto"] is True


@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
def test_auto_rejects_non_bool_atomically(room, value):  # LISTEN1 AC11
    r, _ = room
    r.command("a", "set", queue=QUEUE)
    before = r.snapshot()
    with pytest.raises(ValueError):
        r.command("b", "auto", auto=value)
    assert r.snapshot() == before
    with pytest.raises(ValueError):
        r.command("b", "auto")
    assert r.snapshot() == before


def test_auto_change_invalidates_stale_ended_version(room):
    r, _ = room
    playing = r.command("a", "set", queue=QUEUE)
    manual = r.command("b", "auto", auto=False)
    with pytest.raises(WatchConflict):
        r.command("a", "next", expect_version=playing["version"])
    assert r.snapshot()["index"] == 0 and r.snapshot()["auto"] is False
    assert r.command("a", "next", expect_version=manual["version"])["index"] == 1


def test_ended_countdown_is_shared_idempotent_and_advances_on_read(room):
    r, now = room
    first = r.command("a", "set", queue=QUEUE)
    ended = r.command("a", "ended", expect_version=first["version"], position=60)
    assert ended["index"] == 0 and ended["paused"] and ended["advance_at"] == now[0] + 3
    assert r.command("b", "ended", expect_version=first["version"], position=60) == ended
    now[0] += 2.999
    assert r.snapshot()["index"] == 0
    now[0] += .001
    advanced = r.snapshot()
    assert advanced["index"] == 1 and not advanced["paused"] and advanced["advance_at"] is None
    assert advanced["updated_at"] == now[0] and advanced["version"] == ended["version"] + 1
    # A late duplicate of the old ended never starts a countdown on the new video.
    assert r.command("b", "ended", expect_version=first["version"])["advance_at"] is None
    assert r.snapshot()["index"] == 1


def test_ended_simultaneous_only_creates_one_deadline(room):
    r, _ = room
    version = r.command("a", "set", queue=QUEUE)["version"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda client: r.command(client, "ended", expect_version=version), ["a", "b"]))
    assert results[0]["version"] == results[1]["version"] == version + 1
    assert results[0]["advance_at"] == results[1]["advance_at"]


def test_late_peer_ended_with_fresh_version_does_not_extend_or_restart_wait(room):
    r, now = room
    first = r.command("a", "set", queue=QUEUE)
    wait = r.command("a", "ended", expect_version=first["version"])
    now[0] += 1
    late = r.command("b", "ended", expect_version=wait["version"])
    assert late["advance_at"] == wait["advance_at"] and late["version"] == wait["version"]
    cancel = r.command("a", "cancel_advance")
    late = r.command("b", "ended", expect_version=cancel["version"])
    assert late["advance_at"] is None and late["version"] == cancel["version"]
    replay = r.command("a", "play", position=0)
    assert r.command("a", "ended", expect_version=replay["version"])["advance_at"] == now[0] + 3


def test_countdown_cancel_now_auto_and_last_item(room):
    r, now = room
    def end():
        return r.command("a", "ended", expect_version=r.snapshot()["version"], position=60)
    r.command("a", "set", queue=QUEUE)
    wait = end()
    cancelled = r.command("b", "cancel_advance", expect_version=wait["version"])
    now[0] += 4
    assert r.snapshot()["index"] == 0 and r.snapshot()["advance_at"] is None and r.snapshot()["paused"]
    r.command("a", "play", position=0)
    wait = end()
    quick = r.command("b", "advance_now", expect_version=wait["version"])
    assert quick["index"] == 1 and not quick["paused"] and quick["advance_at"] is None
    assert r.command("b", "advance_now")["index"] == 1
    wait = end()
    r.command("b", "auto", auto=False)
    now[0] += 4
    assert r.snapshot()["index"] == 1 and r.snapshot()["advance_at"] is None
    r.command("a", "play", position=0)
    assert end()["advance_at"] is None
    r.command("b", "auto", auto=True)
    r.command("b", "goto", index=2)
    last = end()
    assert last["paused"] and last["advance_at"] is None and last["index"] == 2


def test_due_countdown_is_applied_before_commands_and_navigation_cancels(room):
    r, now = room
    first = r.command("a", "set", queue=QUEUE)
    r.command("a", "ended", expect_version=first["version"])
    now[0] += 5
    paused = r.command("b", "pause")
    assert paused["index"] == 1 and paused["position"] == 2
    r.command("b", "play", position=0)
    wait = r.command("a", "ended", expect_version=r.snapshot()["version"])
    r.command("b", "prev", expect_version=wait["version"])
    now[0] += 4
    assert r.snapshot()["index"] == 0 and r.snapshot()["advance_at"] is None


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
    calls = [("GET", "/api/watch"), ("POST", "/api/watch"),
             ("POST", "/api/watch/leave"), ("POST", "/api/watch/log"), ("DELETE", "/api/watch")]
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


def test_auto_route_defaults_fresh_snapshot_and_422(cfg):  # no TestClient/socket
    from web_helpers import make_app
    app = make_app(cfg)
    assert set_room(app, "/files/youtube0001/k01.mp4")["auto"] is True
    post, get = endpoint(app, "/api/watch", "POST"), endpoint(app, "/api/watch")
    response = post({"client": "a", "action": "auto", "auto": False})
    assert response.status_code == 200 and json.loads(response.body)["auto"] is False
    current = json.loads(get("b").body)
    assert current["auto"] is False
    for value in [None, 0, 1, "true", "false", [], {}]:
        invalid = post({"client": "a", "action": "auto", "auto": value})
        assert invalid.status_code == 422
        assert json.loads(get().body)["version"] == current["version"]
    assert post({"client": "a", "action": "auto"}).status_code == 422


def test_watch_codes_are_derived_from_download_manifest_not_client(cfg):
    from web_helpers import make_app, write_episode
    eid = "youtube0001"
    write_episode(cfg, eid)
    (Path(cfg.workspace.dir) / eid / "titles.json").write_text(json.dumps({"header": {"fields": {"episode": "20"}}}))
    path = Path(cfg.render.output_dir) / eid / "render_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["shorts"].insert(0, {"clip_id": "gone", "status": "skipped", "skip_reason": "rejected"})
    path.write_text(json.dumps(manifest))
    app = make_app(cfg)
    response = endpoint(app, "/api/watch", "POST")({"client": "a", "action": "set", "queue": [
        {"url": f"/files/{eid}/k01.mp4?v=abc", "title": "wrong", "code": "wrong"},
        {"url": f"/files/{eid}/k02.mp4", "title": "wrong"}, {"url": "/unknown.mp4", "title": "Other"}]})
    data = json.loads(response.body)
    assert data["code"] == "T20_S02" and data["number"] == 2 and data["total"] == 3
    assert data["title"] == "Tiêu đề k01"
    assert data["queue"][1]["code"] == "T20_S03" and data["queue"][1]["duration"] == 61
    assert "code" not in data["queue"][2]


def test_http_auto_sync_and_validation(web):
    from web_helpers import login
    login(web)
    assert web.post("/api/watch", json={"client": "a", "action": "set", "queue": QUEUE}).json()["auto"] is True
    assert web.post("/api/watch", json={"client": "a", "action": "auto", "auto": False}).json()["auto"] is False
    assert web.get("/api/watch?client=b").json()["auto"] is False
    for value in [None, 0, 1, "true", [], {}]:
        assert web.post("/api/watch", json={"client": "b", "action": "auto", "auto": value}).status_code == 422


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


def log_request(payload, *, raw=False):
    from starlette.requests import Request
    data = payload if raw else json.dumps(payload, ensure_ascii=False).encode()
    chunks = iter(((data[:20], True), (data[20:], False)))

    async def receive():
        chunk, more = next(chunks)
        return {"type": "http.request", "body": chunk, "more_body": more}

    return Request({"type": "http", "method": "POST", "path": "/api/watch/log", "headers": [],
                    "query_string": b""}, receive)


def log_batch(**changes):
    return {"client": "phone", "page": "watch", "events": [{"type": "pause_hidden", "t": 21.5, "hidden": True}], **changes}


def test_log_route_records_sanitized_events_and_limits_rate(cfg, monkeypatch, caplog):  # LISTEN1 AC16
    from auto_short.web.routes import watch
    from web_helpers import make_app
    now = [100.0]
    monkeypatch.setattr(watch.time, "monotonic", lambda: now[0])
    app = make_app(cfg)
    post = endpoint(app, "/api/watch/log", "POST")
    before = json.loads(endpoint(app, "/api/watch")().body)
    payload = log_batch(client="pho\nne\x00", events=[
        {"type": "pause_hidden", "t": 21.5, "hidden": True},
        {"type": "retry_blocked", "err": "NotAllowed\r\nError\x1b\u2028", "hidden": True},
        {"type": "seek_skipped_hidden", "drift": -3.25},
    ])
    with caplog.at_level(logging.INFO, logger="auto_short.web.watch"):
        assert asyncio.run(post(log_request(payload))).status_code == 200
        # Same client across pages shares one rate limit; another client is independent.
        assert asyncio.run(post(log_request(log_batch(page="listen")))).status_code == 429
        assert asyncio.run(post(log_request(log_batch(client="desktop")))).status_code == 200
        now[0] += 4.999
        assert asyncio.run(post(log_request(log_batch()))).status_code == 429
        now[0] += .001
        assert asyncio.run(post(log_request(log_batch()))).status_code == 200
    records = [r for r in caplog.records if r.name == "auto_short.web.watch"]
    assert len(records) == 5 and all(r.levelno == logging.INFO for r in records)
    decoded = [json.loads(r.getMessage().removeprefix("player ")) for r in records]
    assert decoded[1] == {"client": "phone", "page": "watch", "type": "retry_blocked", "err": "NotAllowedError", "hidden": True}
    assert decoded[2]["drift"] == -3.25
    assert all(not any(c in r.getMessage() for c in "\n\r\x00\x1b\u2028") for r in records)
    assert json.loads(endpoint(app, "/api/watch")().body)["version"] == before["version"]


@pytest.mark.parametrize("payload", [
    {}, [], log_batch(client=""), log_batch(client=5), log_batch(client="c" * 201), log_batch(page="other"),
    log_batch(events=[]), log_batch(events=[{"type": "visibility"}] * 21), log_batch(events="pause_hidden"),
    log_batch(events=[None]), log_batch(events=[{}]), log_batch(events=[{"type": "other"}]),
    log_batch(events=[{"type": "pause_hidden", "t": True}]), log_batch(events=[{"type": "pause_hidden", "t": -1}]),
    log_batch(events=[{"type": "waiting", "drift": float("nan")}]),
    log_batch(events=[{"type": "waiting", "drift": float("inf")}]),
    log_batch(events=[{"type": "waiting", "t": 10 ** 400}]),
    log_batch(events=[{"type": "waiting", "hidden": 1}]), log_batch(events=[{"type": "retry_blocked", "err": 4}]),
    log_batch(events=[{"type": "visibility", "unknown": True}]), log_batch(extra="unknown"),
])
def test_log_route_rejects_invalid_without_logging_or_rate_charge(cfg, payload, caplog):
    from web_helpers import make_app
    post = endpoint(make_app(cfg), "/api/watch/log", "POST")
    with caplog.at_level(logging.INFO, logger="auto_short.web.watch"):
        assert asyncio.run(post(log_request(payload))).status_code == 422
        assert not [r for r in caplog.records if r.name == "auto_short.web.watch"]
        assert asyncio.run(post(log_request(log_batch()))).status_code == 200


def test_log_route_byte_and_event_boundaries(cfg, caplog):
    from web_helpers import make_app
    post = endpoint(make_app(cfg), "/api/watch/log", "POST")
    # Exact raw bytes count, including whitespace and non-ASCII UTF-8 characters.
    raw = json.dumps(log_batch(client="máy", events=[{"type": "visibility"}] * 20), ensure_ascii=False).encode()
    with caplog.at_level(logging.INFO, logger="auto_short.web.watch"):
        assert asyncio.run(post(log_request(raw + b" " * (2049 - len(raw)), raw=True))).status_code == 422
        assert asyncio.run(post(log_request(raw + b" " * (2048 - len(raw)), raw=True))).status_code == 200
    assert len([r for r in caplog.records if r.name == "auto_short.web.watch"]) == 20
    assert asyncio.run(post(log_request(b"{", raw=True))).status_code == 422
    assert asyncio.run(post(log_request(b"\xff", raw=True))).status_code == 422


def test_log_route_accepts_pip_and_retry_cap_events(cfg, caplog):  # LISTEN1 AC18/19
    from web_helpers import make_app
    post = endpoint(make_app(cfg), "/api/watch/log", "POST")
    events = [{"type": "retry_gave_up", "t": 24.575, "hidden": True},
              {"type": "pip_enter", "hidden": False}, {"type": "pip_leave", "hidden": True}]
    events += [{"type": "pip_unsupported", "err": reason} for reason in ("insecure", "disabled", "api-missing")]
    with caplog.at_level(logging.INFO, logger="auto_short.web.watch"):
        assert asyncio.run(post(log_request(log_batch(events=events)))).status_code == 200
    records = [r for r in caplog.records if r.name == "auto_short.web.watch"]
    assert len(records) == len(events)
    assert [json.loads(r.getMessage().removeprefix("player ")) for r in records] == [
        {"client": "phone", "page": "watch", **event} for event in events]


def test_log_requires_auth_without_testclient(cfg):
    from web_helpers import make_app
    app = make_app(cfg)
    middleware = next(m.kwargs["dispatch"] for m in app.user_middleware
                      if m.kwargs.get("dispatch") and m.kwargs["dispatch"].__name__ == "auth_middleware")

    async def protected(request):
        pytest.fail("unauthenticated diagnostics reached the endpoint")

    assert asyncio.run(middleware(log_request(log_batch()), protected)).status_code == 401


def test_http_log_auth_validation_rate_and_records(web, caplog):
    from web_helpers import login
    assert web.post("/api/watch/log", json=log_batch()).status_code == 401
    login(web)
    assert web.post("/api/watch/log", json=log_batch(events=[])).status_code == 422
    with caplog.at_level(logging.INFO, logger="auto_short.web.watch"):
        assert web.post("/api/watch/log", json=log_batch()).status_code == 200
        assert web.post("/api/watch/log", json=log_batch()).status_code == 429
    assert len([r for r in caplog.records if r.name == "auto_short.web.watch"]) == 1
