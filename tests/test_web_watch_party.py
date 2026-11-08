"""WATCH1: pure room invariants and authenticated HTTP integration, no real services."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

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
    calls = [("GET", "/api/watch"), ("POST", "/api/watch"),
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


FAV = {"playlist_id": "PLwatch00001", "episode_id": "youtube0001.kt", "clip": "k01", "favorite": False}


def test_favorite_metadata_and_action_preserve_playback(room):  # AC10
    r, now = room
    fav = dict(FAV)
    first = r.command("a", "set", queue=[{**QUEUE[0], "fav": fav}, QUEUE[1]], index=1, position=12, rate=1.5)
    assert first["queue"][0]["fav"] == FAV and "fav" not in first["queue"][1]
    fav["favorite"] = True
    first["queue"][0]["fav"]["episode_id"] = "changed"
    assert r.snapshot()["queue"][0]["fav"] == FAV  # input and nested snapshots are independent
    now[0] += 2
    view = r.command("b", "favorite", index=0, favorite=True)
    assert view["queue"][0]["fav"] == {**FAV, "favorite": True}
    assert (view["index"], view["position"], view["paused"], view["rate"]) == (1, 15, False, 1.5)
    assert view["version"] == first["version"] + 1 and view["by"] == "b"
    assert r.command("a", "favorite", index=0, favorite=False)["queue"][0]["fav"]["favorite"] is False
    assert r.snapshot("b")["queue"][0]["fav"] == FAV


BAD_FAVS = [None, True, "bad", [], {},
            {**FAV, "playlist_id": "//evil"}, {**FAV, "playlist_id": "WL"}, {**FAV, "playlist_id": 123},
            {**FAV, "episode_id": "../bad"}, {**FAV, "episode_id": None},
            {**FAV, "clip": "../clip"}, {**FAV, "clip": 1},
            {**FAV, "favorite": 1}, {**FAV, "favorite": "true"},
            {key: val for key, val in FAV.items() if key != "favorite"}]


@pytest.mark.parametrize("fav", BAD_FAVS)
def test_favorite_metadata_invalid_is_atomic_422(room, fav):  # AC10; direct router call, no TestClient
    from auto_short.web.routes.watch import build
    r, _ = room
    r.command("a", "set", queue=QUEUE)
    before = r.snapshot()
    with pytest.raises(ValueError):
        r.command("b", "set", queue=[QUEUE[0], {**QUEUE[1], "fav": fav}])
    assert r.snapshot() == before
    router = build(None)
    post = next(route.endpoint for route in router.routes if route.path == "/api/watch" and "POST" in route.methods)
    assert post({"client": "a", "action": "set", "queue": [{**QUEUE[0], "fav": fav}]}).status_code == 422


@pytest.mark.parametrize("data", [{"index": -1, "favorite": True}, {"index": 2, "favorite": True},
                                  {"index": True, "favorite": True}, {"index": 0, "favorite": "true"},
                                  {"index": 0}, {"index": 1, "favorite": True}])
def test_favorite_invalid_command_is_atomic_422(room, data):  # AC10
    from auto_short.web.routes.watch import build
    queue = [{**QUEUE[0], "fav": FAV}, QUEUE[1]]
    r, _ = room
    r.command("a", "set", queue=queue)
    before = r.snapshot()
    with pytest.raises(ValueError):
        r.command("b", "favorite", **data)
    assert r.snapshot() == before
    router = build(None)
    post = next(route.endpoint for route in router.routes if route.path == "/api/watch" and "POST" in route.methods)
    assert post({"client": "a", "action": "set", "queue": queue}).status_code == 200
    assert post({"client": "b", "action": "favorite", **data}).status_code == 422
    assert post({"client": "b", "action": "favorite", "index": 0, "favorite": True}).status_code == 200
