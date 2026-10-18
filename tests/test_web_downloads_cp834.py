"""CP8.34: ``?dl=<token>`` download progress (D3, D6, D7), ``GET /api/downloads/{token}``, unchanged routes without
``dl`` (AC2, AC7), and the playlist fields the sequential-download queue of the page uses (D1, AC4)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short import khaithi  # noqa: E402
from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.khaithi import KhaiThi  # noqa: E402
from auto_short.render import full  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web import downloads as dl_mod  # noqa: E402

from test_web_hd_cp827 import write_hd  # noqa: E402
from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
VID = "aaaaaaaaaa1"
VID2 = "bbbbbbbbbb2"
KT = VID + ".kt"
PL = "PLtestplaylist01"
TOK = "tok-abcdefgh01"
BIG = bytes(range(256)) * 1000  # 256 000 bytes: several 64 KiB chunks


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output", preset="ultrafast", threads=2))


def make_app(cfg):
    return app_mod.create_app(cfg, PW, preflight=lambda c: None, pipeline=fake_pipeline([]),
                              disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9))


def client(cfg):
    return TestClient(make_app(cfg), follow_redirects=False)


def login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def big_clip(cfg, eid, clip="k01"):
    (Path(cfg.render.output_dir) / eid / "shorts" / f"{clip}.mp4").write_bytes(BIG)


def progress(c, token=TOK):
    r = c.get(f"/api/downloads/{token}")
    assert r.status_code == 200, r.text
    return r.json()


# --- AC2: states, 404, 401 ----------------------------------------------------------------------------------------

def test_unknown_token_404_and_no_cookie_401(tcfg):
    c = client(tcfg)
    assert c.get(f"/api/downloads/{TOK}").status_code == 401
    login(c)
    assert c.get(f"/api/downloads/{TOK}").status_code == 404
    assert c.get("/api/downloads/x").status_code == 404  # malformed token
    write_episode(tcfg, VID, clips=("k01",))
    assert TestClient(make_app(tcfg)).get(f"/files/{VID}/shorts.zip?dl={TOK}").status_code in (401, 303)


def test_mp4_sending_to_done_with_total(tcfg):
    write_episode(tcfg, VID, clips=("k01",))
    big_clip(tcfg, VID)
    c = client(tcfg)
    login(c)
    r = c.get(f"/files/{VID}/k01.mp4?download=1&dl={TOK}")
    assert r.status_code == 200 and r.content == BIG
    assert progress(c) == {"state": "done", "bytes_sent": len(BIG), "bytes_total": len(BIG)}


def test_zip_done_total_unknown_and_same_bytes_without_dl(tcfg):
    write_episode(tcfg, VID, clips=("k01", "k02"))
    c = client(tcfg)
    login(c)
    plain = c.get(f"/files/{VID}/shorts.zip")
    tracked = c.get(f"/files/{VID}/shorts.zip?dl={TOK}")
    assert plain.status_code == tracked.status_code == 200
    assert tracked.content == plain.content and "content-length" not in plain.headers
    assert tracked.headers["content-disposition"] == plain.headers["content-disposition"]
    assert tracked.headers["cache-control"] == plain.headers["cache-control"]
    assert progress(c) == {"state": "done", "bytes_sent": len(plain.content), "bytes_total": None}


def test_no_dl_mp4_identical(tcfg):
    write_episode(tcfg, VID, clips=("k01",))
    big_clip(tcfg, VID)
    c = client(tcfg)
    login(c)
    a = c.get(f"/files/{VID}/k01.mp4?download=1")
    b = c.get(f"/files/{VID}/k01.mp4?download=1&dl={TOK}")
    assert a.content == b.content == BIG
    for h in ("content-type", "content-length", "content-disposition", "cache-control", "accept-ranges", "etag"):
        assert a.headers.get(h) == b.headers.get(h), h


def test_malformed_dl_is_ignored(tcfg):
    write_episode(tcfg, VID, clips=("k01",))
    c = client(tcfg)
    login(c)
    assert c.get(f"/files/{VID}/shorts.zip?dl=a").status_code == 200  # too short -> behaves as without dl
    assert c.get("/api/downloads/a").status_code == 404


def test_error_response_marks_aborted(tcfg):
    c = client(tcfg)
    login(c)
    assert c.get(f"/files/{VID}/shorts.zip?dl={TOK}").status_code == 404  # no such episode / no Short
    assert progress(c)["state"] == "aborted"


# --- AC2: client disconnect mid-stream (real ASGI, not a mock of the response) ---------------------------------------

def asgi_get(app, path, cookie, *, stop_after=None, headers=()):
    """Drive the ASGI app by hand; ``stop_after`` = raise on the n-th body send (the client went away)."""
    sent = {"body": 0, "messages": []}

    async def run():
        parts = urlsplit(path)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
                 "path": parts.path, "raw_path": parts.path.encode(), "query_string": parts.query.encode(),
                 "root_path": "", "client": ("127.0.0.1", 1), "server": ("testserver", 80),
                 "headers": [(b"cookie", cookie.encode()), (b"host", b"testserver"), *headers],
                 "extensions": {"http.response.pathsend": {}}}
        disconnected = asyncio.Event()

        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            sent["messages"].append(message)
            if message["type"] == "http.response.body":
                sent["body"] += 1
                if stop_after is not None and sent["body"] >= stop_after:
                    disconnected.set()
                    raise OSError("client went away")

        try:
            await app(scope, receive, send)
        except BaseException:
            pass

    asyncio.run(run())
    return sent


def session_cookie(c):
    return "; ".join(f"{k}={v}" for k, v in c.cookies.items())


def test_disconnect_mid_file_is_aborted(tcfg):
    write_episode(tcfg, VID, clips=("k01",))
    big_clip(tcfg, VID)
    app = make_app(tcfg)
    c = TestClient(app, follow_redirects=False)
    login(c)
    sent = asgi_get(app, f"/files/{VID}/k01.mp4?download=1&dl={TOK}", session_cookie(c), stop_after=2)
    assert sent["body"] == 2
    p = progress(c)
    assert p["state"] == "aborted" and 0 < p["bytes_sent"] < len(BIG) and p["bytes_total"] == len(BIG)


def test_disconnect_mid_zip_is_aborted(tcfg):
    write_episode(tcfg, VID, clips=("k01", "k02"))
    big_clip(tcfg, VID)
    app = make_app(tcfg)
    c = TestClient(app, follow_redirects=False)
    login(c)
    asgi_get(app, f"/files/{VID}/shorts.zip?dl={TOK}", session_cookie(c), stop_after=2)
    assert progress(c)["state"] == "aborted"


def test_full_run_through_raw_asgi_is_done_without_pathsend(tcfg):
    write_episode(tcfg, VID, clips=("k01",))
    big_clip(tcfg, VID)
    app = make_app(tcfg)
    c = TestClient(app, follow_redirects=False)
    login(c)
    sent = asgi_get(app, f"/files/{VID}/k01.mp4?download=1&dl={TOK}", session_cookie(c))
    assert all(m["type"] != "http.response.pathsend" for m in sent["messages"])
    assert progress(c)["state"] == "done"


def test_new_request_with_same_token_resets_to_latest(tcfg):
    write_episode(tcfg, VID, clips=("k01",))
    big_clip(tcfg, VID)
    app = make_app(tcfg)
    c = TestClient(app, follow_redirects=False)
    login(c)
    asgi_get(app, f"/files/{VID}/k01.mp4?download=1&dl={TOK}", session_cookie(c), stop_after=1)
    assert progress(c)["state"] == "aborted"
    assert c.get(f"/files/{VID}/k01.mp4?download=1&dl={TOK}").status_code == 200  # the manager retried
    assert progress(c)["state"] == "done"


# --- D7: Range --------------------------------------------------------------------------------------------------------

def test_range_to_last_byte_is_done_partial_is_not(tcfg):
    write_episode(tcfg, VID, clips=("k01",))
    big_clip(tcfg, VID)
    c = client(tcfg)
    login(c)
    n = len(BIG)
    r = c.get(f"/files/{VID}/k01.mp4?dl={TOK}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert progress(c) == {"state": "sending", "bytes_sent": 100, "bytes_total": n}
    r = c.get(f"/files/{VID}/k01.mp4?dl={TOK}", headers={"Range": "bytes=100-"})
    assert r.status_code == 206 and r.content == BIG[100:]
    assert progress(c) == {"state": "done", "bytes_sent": n, "bytes_total": n}


# --- HD landscape + vertical routes -----------------------------------------------------------------------------------

def test_hd_and_vertical_routes_track_and_stay_identical(tcfg):
    write_episode(tcfg, VID, clips=("k01",))
    write_hd(tcfg, VID, BIG)
    sha = hashlib.sha256(BIG).hexdigest()
    d = full.vertical_dir(tcfg, VID)
    d.mkdir(parents=True, exist_ok=True)
    (d / full.VIDEO_NAME).write_bytes(b"v" * 5000)
    (d / full.META_NAME).write_text(json.dumps({"hd_sha256": sha, "size": 5000, "key": "k"}), encoding="utf-8")
    c = client(tcfg)
    login(c)
    for n, (url, size) in enumerate(((f"/api/episodes/{VID}/source-hd", len(BIG)), (f"/api/episodes/{VID}/vertical", 5000))):
        tok = f"{TOK}-{n}"
        a = c.get(url)
        b = c.get(f"{url}?dl={tok}")
        assert a.status_code == b.status_code == 200 and a.content == b.content
        assert a.headers["content-disposition"] == b.headers["content-disposition"]
        assert progress(c, tok) == {"state": "done", "bytes_sent": size, "bytes_total": size}
    # a missing vertical (other episode) ends the token as aborted
    write_episode(tcfg, VID2, clips=("k01",))
    assert c.get(f"/api/episodes/{VID2}/vertical?dl=tok2-abcdefgh").status_code == 404
    assert progress(c, "tok2-abcdefgh")["state"] == "aborted"


# --- D6: the zip still ticks "Đã đăng" ---------------------------------------------------------------------------------

def test_zip_with_dl_ticks_posted(tcfg):
    write_episode(tcfg, VID, clips=("k01", "k02"))
    c = client(tcfg)
    login(c)

    def posted():
        shorts = c.get(f"/api/episodes/{VID}").json()["shorts"]
        return sorted(s["clip_id"] for s in shorts if s.get("published"))

    before = posted()
    assert c.get(f"/files/{VID}/shorts.zip?dl={TOK}").status_code == 200
    assert posted() == ["k01", "k02"] and before == []


def test_all_zip_with_dl_ticks_both_kinds(tcfg):
    write_episode(tcfg, VID, clips=("k01",))
    write_episode(tcfg, KT, clips=("k01",))
    khaithi.write(Path(tcfg.workspace.dir) / KT, KhaiThi(VID, 4, 7))
    c = client(tcfg)
    login(c)
    r = c.get(f"/files/{VID}/all.zip?dl={TOK}")
    assert r.status_code == 200 and progress(c)["state"] == "done"
    assert c.get(f"/api/episodes/{VID}").json()["published"] == 1


# --- table unit tests ---------------------------------------------------------------------------------------------------

def test_table_expiry_and_interval_merge():
    now = [0.0]
    t = dl_mod.DownloadTable(clock=lambda: now[0], ttl=100)
    t.begin("tokentoken1")
    t.set_total("tokentoken1", 100)
    t.add_bytes("tokentoken1", 0, 40)
    assert t.end("tokentoken1", "aborted") == "aborted"
    t.begin("tokentoken1")  # a new request after aborted -> sending again
    assert t.get("tokentoken1")["state"] == "sending"
    t.add_bytes("tokentoken1", 40, 100)
    assert t.end("tokentoken1", "finished") == "done"
    now[0] = 101.0
    assert t.get("tokentoken1") is None


def test_merge_interval():
    iv: list[list[int]] = []
    for a, b in ((50, 60), (0, 10), (10, 20), (55, 70), (30, 40), (20, 30), (40, 50)):
        dl_mod.merge_interval(iv, a, b)
    assert iv == [[0, 70]]


# --- D1 / AC4: the playlist API gives the page what it needs to skip missing kinds ---------------------------------------

def test_playlist_entries_expose_kinds_for_the_queue(tcfg):
    write_episode(tcfg, VID, clips=("k01",), title="Tập 1")
    write_episode(tcfg, VID2, clips=("k01",), title="Tập 2")
    write_hd(tcfg, VID, BIG)
    sha = hashlib.sha256(BIG).hexdigest()
    d = full.vertical_dir(tcfg, VID)
    d.mkdir(parents=True, exist_ok=True)
    (d / full.VIDEO_NAME).write_bytes(b"v" * 50)
    (d / full.META_NAME).write_text(json.dumps({"hd_sha256": sha, "size": 50, "key": "k"}), encoding="utf-8")
    root = Path(tcfg.workspace.dir) / "_playlists"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{PL}.json").write_text(json.dumps({
        "schema_version": 1, "playlist_id": PL, "title": "Thử", "url": "u", "fetched_at": "2026-10-01T00:00:00Z",
        "entries": [{"index": i, "video_id": v, "title": f"Tập {i}", "duration": 3000.0, "episode": str(i), "available": True}
                    for i, v in enumerate((VID, VID2), 1)]}), encoding="utf-8")
    c = client(tcfg)
    login(c)
    by = {e["video_id"]: e for e in c.get(f"/api/playlists/{PL}").json()["entries"]}
    assert by[VID]["zip_url"] and by[VID]["hd_url"] and by[VID]["vertical"]["ready"] and by[VID]["vertical"]["url"]
    assert by[VID2]["zip_url"] and not by[VID2].get("hd_url") and not (by[VID2]["vertical"] or {}).get("ready")
    assert {"shorts", "published", "khaithi_videos", "khaithi_published"} <= set(by[VID])


def test_playlist_page_static_wiring(tcfg):
    c = client(tcfg)
    login(c)
    html = c.get(f"/playlists/{PL}").text
    assert html.index("/static/dlqueue.js") < html.index("/static/app.js")
    for el_id in ("dq-kind", "dq-conc", "dq-unposted", "dq-start", "dq-pause", "dq-resume", "dq-rows"):
        assert f'id="{el_id}"' in html
    assert "Để trang này mở cho tới khi tải xong" in html and "Cho phép tải nhiều tệp" in html
    assert c.get("/static/dlqueue.js").status_code == 200


# --- A1a: a disconnect that the server's ``send`` swallows (uvicorn), found through ``receive`` -----------------------------

HUGE = bytes(range(256)) * 16384  # 4 MiB: 64 chunks of 64 KiB


def silent_asgi_get(app, path, cookie, *, disconnect_after=None, headers=()):
    """Like uvicorn after the peer left: ``send`` never raises, ``receive`` yields ``http.request`` and then
    ``http.disconnect`` once ``disconnect_after`` body chunks went out (``None`` = right when the final chunk is
    being sent, the way the middleware reports a finished response)."""
    sent = {"body": 0}

    async def run():
        parts = urlsplit(path)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
                 "path": parts.path, "raw_path": parts.path.encode(), "query_string": parts.query.encode(),
                 "root_path": "", "client": ("127.0.0.1", 1), "server": ("testserver", 80),
                 "headers": [(b"cookie", cookie.encode()), (b"host", b"testserver"), *headers],
                 "extensions": {"http.response.pathsend": {}}}
        gone = asyncio.Event()
        first = [True]

        async def receive():
            if first[0]:
                first[0] = False
                return {"type": "http.request", "body": b"", "more_body": False}
            await gone.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            await asyncio.sleep(0)  # let the other tasks run, as a socket write would
            if message["type"] == "http.response.body":
                sent["body"] += 1
                if disconnect_after is not None and sent["body"] >= disconnect_after:
                    gone.set()
                elif disconnect_after is None and not message.get("more_body", False):
                    gone.set()

        await app(scope, receive, send)

    asyncio.run(run())
    return sent


def big_app(tcfg, data=HUGE):
    write_episode(tcfg, VID, clips=("k01",))
    (Path(tcfg.render.output_dir) / VID / "shorts" / "k01.mp4").write_bytes(data)
    app = make_app(tcfg)
    c = TestClient(app, follow_redirects=False)
    login(c)
    return app, c, session_cookie(c)


def test_silent_disconnect_mid_file_is_aborted_with_partial_bytes(tcfg):
    app, c, cookie = big_app(tcfg)
    silent_asgi_get(app, f"/files/{VID}/k01.mp4?download=1&dl={TOK}", cookie, disconnect_after=5)
    p = progress(c)
    assert p["state"] == "aborted" and 0 < p["bytes_sent"] < len(HUGE) and p["bytes_total"] == len(HUGE)


def test_disconnect_reported_with_the_final_chunk_is_still_done(tcfg):
    app, c, cookie = big_app(tcfg)
    silent_asgi_get(app, f"/files/{VID}/k01.mp4?download=1&dl={TOK}", cookie, disconnect_after=None)
    assert progress(c) == {"state": "done", "bytes_sent": len(HUGE), "bytes_total": len(HUGE)}


def test_silent_disconnect_mid_zip_is_aborted(tcfg):
    app, c, cookie = big_app(tcfg)
    silent_asgi_get(app, f"/files/{VID}/shorts.zip?dl={TOK}", cookie, disconnect_after=3)
    assert progress(c)["state"] == "aborted"


# --- A1b: several Range requests of one token, merged -------------------------------------------------------------------

def test_ranges_any_order_bounded_middle_last_is_done(tcfg):
    app, c, _ = big_app(tcfg, BIG)
    n = len(BIG)
    for rng, state in (("100000-199999", "sending"), ("0-49999", "sending"), ("200000-", "sending")):
        assert c.get(f"/files/{VID}/k01.mp4?dl={TOK}", headers={"Range": f"bytes={rng}"}).status_code == 206
        assert progress(c)["state"] == state
    r = c.get(f"/files/{VID}/k01.mp4?dl={TOK}", headers={"Range": "bytes=50000-99999"})  # the hole, bounded, last
    assert r.status_code == 206 and r.content == BIG[50000:100000]
    assert progress(c) == {"state": "done", "bytes_sent": n, "bytes_total": n}


def test_missing_slice_and_no_running_request_is_aborted_then_recovers(tcfg):
    app, c, cookie = big_app(tcfg, HUGE)
    n = len(HUGE)
    half = n // 2
    assert c.get(f"/files/{VID}/k01.mp4?dl={TOK}", headers={"Range": f"bytes=0-{half - 1}"}).status_code == 206
    silent_asgi_get(app, f"/files/{VID}/k01.mp4?dl={TOK}", cookie, disconnect_after=3,
                    headers=[(b"range", f"bytes={half}-".encode())])
    p = progress(c)
    assert p["state"] == "aborted" and half < p["bytes_sent"] < n
    assert c.get(f"/files/{VID}/k01.mp4?dl={TOK}", headers={"Range": f"bytes={half}-"}).status_code == 206  # retry
    assert progress(c)["state"] == "done"


# --- A1a / AC8 on a real uvicorn server -------------------------------------------------------------------------------------

def run_uvicorn(app):
    import socket
    import threading
    import time

    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    return server, thread, port


def wait_state(get, want, seconds=15):
    import time

    deadline = time.time() + seconds
    last = None
    while time.time() < deadline:
        last = get()
        if last["state"] == want:
            return last
        time.sleep(0.1)
    raise AssertionError(f"state never became {want}: {last}")


def test_real_uvicorn_disconnect_is_aborted_and_full_download_is_done(tcfg):
    pytest.importorskip("uvicorn")
    import http.client
    import socket

    data = bytes(range(256)) * 262144  # 64 MiB: far more than the socket buffers hold
    app, c, _ = big_app(tcfg, data)
    server, thread, port = run_uvicorn(app)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        conn.request("POST", "/login", body=f"password={PW}", headers={"Content-Type": "application/x-www-form-urlencoded"})
        resp = conn.getresponse()
        resp.read()
        cookie = resp.getheader("set-cookie").split(";")[0]
        conn.close()

        def poll(token):
            def get():
                h = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                h.request("GET", f"/api/downloads/{token}", headers={"Cookie": cookie})
                r = h.getresponse()
                body = r.read()
                h.close()
                return json.loads(body) if r.status == 200 else {"state": f"http {r.status}"}
            return get

        # a client that reads a little and leaves
        s = socket.create_connection(("127.0.0.1", port), timeout=10)
        s.sendall(f"GET /files/{VID}/k01.mp4?download=1&dl=realabort01 HTTP/1.1\r\nHost: x\r\nCookie: {cookie}\r\n\r\n".encode())
        got = 0
        while got < 300_000:
            got += len(s.recv(65536))
        s.close()
        p = wait_state(poll("realabort01"), "aborted")
        assert p["bytes_sent"] < len(data) and p["bytes_total"] == len(data)

        # a client that downloads everything
        h = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        h.request("GET", f"/files/{VID}/k01.mp4?download=1&dl=realdone001", headers={"Cookie": cookie})
        r = h.getresponse()
        total = 0
        while chunk := r.read(1 << 20):
            total += len(chunk)
        h.close()
        assert total == len(data)
        assert wait_state(poll("realdone001"), "done")["bytes_sent"] == len(data)
    finally:
        server.should_exit = True
        thread.join(10)


def test_one_info_log_line_per_tracked_request(tcfg, caplog):
    import logging

    write_episode(tcfg, VID, clips=("k01",))
    big_clip(tcfg, VID)
    c = client(tcfg)
    login(c)
    with caplog.at_level(logging.INFO, logger="auto_short"):
        c.get(f"/files/{VID}/k01.mp4?download=1&dl={TOK}", headers={"Range": "bytes=0-99"})
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("web: tải")]
    assert len(lines) == 1
    assert TOK[:6] in lines[0] and "k01.mp4" in lines[0] and "bytes=0-99" in lines[0] and "partial" in lines[0]


def test_keep_awake_fallback_video_and_warning(tcfg):
    c = client(tcfg)
    login(c)
    html = c.get(f"/playlists/{PL}").text
    tag = html[html.index('<video id="dq-awake"'):]
    tag = tag[:tag.index(">") + 1]
    for attr in (" muted", " loop", " playsinline", 'src="/static/keepawake.mp4"'):
        assert attr in tag
    assert "display:none" not in tag.replace(" ", "")  # visible (the class is a small box), not hidden by style
    assert 'id="dq-awake-warn"' in html and "không mở bằng HTTPS" in html
    r = c.get("/static/keepawake.mp4")
    assert r.status_code == 200 and len(r.content) <= 10_000 and r.content[4:8] == b"ftyp"
    js = c.get("/static/app.js").text
    assert "keepAwakeMode" in js and ".muted = true" in js
