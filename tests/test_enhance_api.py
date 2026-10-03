"""CP13.1b: the worker API (E3, E7, E8) on the web app: token auth (the web cookie never opens it), lease order and
expiry, source download with Range, segment upload checks + idempotency, ``may-run``, assembly of ``source_hd.mp4``
(AC2, AC3, AC7, AC10). Real ffmpeg, tiny videos (320x240 source, 25-frame segments)."""

import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.enhance import state as st  # noqa: E402
from auto_short.enhance.service import EnhanceService  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web.auth import COOKIE_NAME  # noqa: E402
from auto_short.web.jobs import AI, JobRunner, Step  # noqa: E402

from enhance_helpers import (FRAMES, OUT_H, OUT_W, SEG, T1, T2, enhance_cfg, make_clip, make_segment, make_yt_episode,
                             sha)  # noqa: E402
from web_helpers import fake_pipeline  # noqa: E402

pytestmark = pytest.mark.usefixtures("_video_template")
PW = "mật-khẩu"
H1 = {"Authorization": f"Bearer {T1}"}
H2 = {"Authorization": f"Bearer {T2}"}
E1, E2 = "vid00000001", "vid00000002"


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def _fast_login_delay(monkeypatch):
    monkeypatch.setattr(app_mod, "LOGIN_DELAY", 0.05)


@pytest.fixture(scope="module")
def segments(tmp_path_factory):
    """The four valid segments (25, 25, 25, 15 frames) of the helper source."""
    d = tmp_path_factory.mktemp("segments")
    return [make_segment(d / f"s{n}.mp4", n) for n in range(4)]


class Ctx:
    def __init__(self, tmp_path, **cfg_kw):
        self.cfg = enhance_cfg(tmp_path, yield_workers=("w3090",), **cfg_kw)
        self.clock = Clock()
        self.svc = EnhanceService(self.cfg, clock=self.clock)
        self.runner = JobRunner()
        self.app = app_mod.create_app(self.cfg, PW, runner=self.runner, preflight=lambda c: None,
                                      pipeline=fake_pipeline([]), enhance_tokens={"w3090": T1, "w3050": T2},
                                      enhance_service=self.svc)
        self.client = TestClient(self.app, follow_redirects=False)

    def web_login(self):
        r = self.client.post("/login", json={"password": PW})
        assert r.status_code == 200
        return {COOKIE_NAME: r.cookies[COOKIE_NAME]}

    def lease(self, headers=H1, gpu="RTX 3090"):
        r = self.client.post("/api/enhance/lease", json={"worker": "w", "gpu": gpu}, headers=headers)
        return r

    def put(self, lease_id, n, data, *, sha_header=None, headers=H1):
        return self.client.put(f"/api/enhance/{lease_id}/seg/{n}", content=data,
                               headers={**headers, "X-Sha256": sha_header or sha(data)})


@pytest.fixture
def ctx(tmp_path):
    c = Ctx(tmp_path)
    with c.client:
        yield c


def wait_for(pred, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.02)


# --- E8 / AC2: tokens, the cookie never opens a worker route ----------------------------------------------------

def test_worker_routes_need_the_token_not_the_cookie(ctx):
    make_yt_episode(ctx.cfg, E1)
    cookie = ctx.web_login()
    routes = [("POST", "/api/enhance/lease", {"json": {"worker": "w"}}), ("GET", "/api/enhance/may-run", {}),
              ("GET", "/api/enhance/abc/source", {}), ("PUT", "/api/enhance/abc/seg/0", {"content": b"x"}),
              ("POST", "/api/enhance/abc/heartbeat", {"json": {}}), ("POST", "/api/enhance/abc/release", {"json": {}})]
    for method, path, kw in routes:
        for label, headers, cookies in (("none", {}, {}), ("bad token", {"Authorization": "Bearer nope"}, {}),
                                        ("short token", {"Authorization": f"Bearer {T1[:-1]}"}, {}),
                                        ("cookie only", {}, cookie)):
            ctx.client.cookies.clear()
            r = ctx.client.request(method, path, headers=headers, cookies=cookies, **kw)
            assert r.status_code == 401, (method, path, label, r.status_code)
    ctx.client.cookies.clear()
    # the token opens only /api/enhance/*: the rest of the API still wants the web login
    for path in ("/api/episodes", f"/api/episodes/{E1}", "/api/queue", "/api/storage", "/api/enhance/status"):
        assert ctx.client.get(path, headers=H1).status_code == 401, path
    assert ctx.client.post(f"/api/episodes/{E1}/enhance", json={"enabled": False}, headers=H1).status_code == 401
    assert ctx.client.post("/api/enhance-pause", json={"paused": True}, headers=H1).status_code == 401
    # a valid token works (200 / 204), also for the second worker
    assert ctx.client.get("/api/enhance/may-run", headers=H1).json() == {"run": True, "reason": ""}
    assert ctx.client.get("/api/enhance/may-run", headers=H2).status_code == 200


def test_ui_status_is_cookie_only_and_read_only(ctx):
    make_yt_episode(ctx.cfg, E1)
    assert ctx.client.get("/api/enhance/status").status_code == 401
    cookie = ctx.web_login()
    ctx.lease()  # a worker made contact
    r = ctx.client.get("/api/enhance/status", cookies=cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] and not body["paused"] and body["counts"]["running"] == 1
    assert [w["name"] for w in body["workers"]] == ["w3090"] and body["workers"][0]["yield"] is True
    assert body["workers"][0]["gpu"] == "RTX 3090" and body["workers"][0]["episode_id"] == E1
    # no worker action through the cookie: lease / may-run / source / put stay 401 (see the test above)
    assert ctx.client.post("/api/enhance/lease", json={}, cookies=cookie).status_code == 401


# --- E2 / AC2: lease order, expiry ------------------------------------------------------------------------------

def test_lease_gives_the_waiting_episode_first_then_by_time(ctx):
    for eid in (E1, E2, "vid00000003"):
        make_yt_episode(ctx.cfg, eid)
        ctx.clock.now += 10
    doc = st.read(ctx.cfg.workspace.dir / "vid00000003")
    doc["waiting_hd"] = True  # parked after titling: first
    st.write(ctx.cfg.workspace.dir / "vid00000003", doc)
    r = ctx.lease(H1)
    assert r.status_code == 200
    got = r.json()
    assert got["episode_id"] == "vid00000003"
    assert set(got) >= {"episode_id", "lease_id", "expires_at", "source_url", "source_sha256", "source_size", "fps",
                        "frames", "segment_frames", "params", "config_hash", "done_segments"}
    assert got["fps"] == "25" and got["frames"] == FRAMES and got["segment_frames"] == SEG
    assert got["params"] == {"model": "realesr-general-x4v3", "denoise": 1.0, "pre_height": 0, "out_height": OUT_H}
    assert got["source_url"] == f"/api/enhance/{got['lease_id']}/source" and got["done_segments"] == []
    assert got["source_size"] == (ctx.cfg.workspace.dir / "vid00000003" / "source.mp4").stat().st_size
    assert got["expires_at"].endswith("Z")
    assert ctx.lease(H1).json() == got  # a worker holding a valid lease gets that lease back
    assert ctx.lease(H2).json()["episode_id"] == E1  # then by time of the decision
    assert ctx.client.post("/api/enhance/lease", json={"worker": "x"}, headers={"Authorization": f"Bearer {T2}"}) \
        .json()["episode_id"] == E1
    # only E2 is left for a third caller: the first worker is the only one that may ask again -> its own lease
    assert ctx.lease(H1).json()["episode_id"] == "vid00000003"


def test_lease_204_when_nothing_to_do_disabled_or_paused(tmp_path):
    c = Ctx(tmp_path)
    with c.client:
        assert c.lease().status_code == 204  # no video wants enhance
        make_yt_episode(c.cfg, E1, height=720)  # >= 720: not wanted
        assert c.lease().status_code == 204
    off = Ctx(tmp_path / "off", enabled=False)
    with off.client:
        make_yt_episode(off.cfg, E1, height=240, with_enhance=False)
        st.decide(off.cfg, E1, force=True)  # a leftover wanted video
        assert off.client.get("/api/enhance/may-run", headers=H2).json()["run"] is False
        assert off.lease(H2).status_code == 204


def test_expired_lease_goes_back_to_the_queue_and_keeps_segments(ctx, segments):
    make_yt_episode(ctx.cfg, E1)
    lease = ctx.lease(H1).json()
    assert ctx.put(lease["lease_id"], 0, segments[0]).status_code == 200
    assert ctx.put(lease["lease_id"], 1, segments[1]).status_code == 200
    assert ctx.lease(H2).status_code == 204  # the only video is leased
    ctx.clock.now += 49 * 3600  # the worker vanished for more than lease_hours
    for r in (ctx.put(lease["lease_id"], 2, segments[2]),
              ctx.client.post(f"/api/enhance/{lease['lease_id']}/heartbeat", json={}, headers=H1),
              ctx.client.get(f"/api/enhance/{lease['lease_id']}/source", headers=H1)):
        assert r.status_code == 409
    new = ctx.lease(H2).json()
    assert new["episode_id"] == E1 and new["lease_id"] != lease["lease_id"]
    assert new["done_segments"] == [0, 1]  # finished segments of the old lease are kept
    assert ctx.put(lease["lease_id"], 2, segments[2]).status_code == 409  # old lease stays dead
    assert ctx.put(new["lease_id"], 2, segments[2], headers=H2).status_code == 200


def test_heartbeat_and_release(ctx):
    make_yt_episode(ctx.cfg, E1)
    lease = ctx.lease().json()
    ctx.clock.now += 3600
    r = ctx.client.post(f"/api/enhance/{lease['lease_id']}/heartbeat", headers=H1,
                        json={"progress": {"segments_uploaded": 1, "segments_encoded": 2, "segments_total": 4,
                                           "junk": "x"}})
    assert r.status_code == 200 and r.json()["expires_at"] > lease["expires_at"]  # renewed
    doc = st.read(ctx.cfg.workspace.dir / E1)
    assert doc["lease"]["progress"] == {"segments_uploaded": 1, "segments_encoded": 2, "segments_total": 4}
    # another worker cannot touch this lease
    assert ctx.client.post(f"/api/enhance/{lease['lease_id']}/release", json={}, headers=H2).status_code == 409
    assert ctx.client.post(f"/api/enhance/{lease['lease_id']}/release", json={"reason": "dừng tay"},
                           headers=H1).json() == {"ok": True}
    assert st.read(ctx.cfg.workspace.dir / E1)["lease"] is None
    assert ctx.client.post(f"/api/enhance/{lease['lease_id']}/heartbeat", json={}, headers=H1).status_code == 409
    assert ctx.lease(H2).json()["episode_id"] == E1  # back in the queue


# --- E3: source with Range ---------------------------------------------------------------------------------------

def test_source_download_supports_range(ctx):
    ws = make_yt_episode(ctx.cfg, E1)
    lease = ctx.lease().json()
    data = (ws.dir / "source.mp4").read_bytes()
    r = ctx.client.get(lease["source_url"], headers=H1)
    assert r.status_code == 200 and r.content == data and r.headers["accept-ranges"] == "bytes"
    assert sha(r.content) == lease["source_sha256"]
    r = ctx.client.get(lease["source_url"], headers={**H1, "Range": f"bytes={len(data) - 100}-"})
    assert r.status_code == 206 and r.content == data[-100:]
    assert r.headers["content-range"] == f"bytes {len(data) - 100}-{len(data) - 1}/{len(data)}"
    assert ctx.client.get(f"/api/enhance/{lease['lease_id']}x/source", headers=H1).status_code == 409
    assert ctx.client.get("/api/enhance/not..ok/source", headers=H2).status_code == 409


# --- E3: PUT seg -------------------------------------------------------------------------------------------------

def test_put_checks_sha_frames_size_and_is_idempotent(ctx, segments, tmp_path):
    ws = make_yt_episode(ctx.cfg, E1)
    lease = ctx.lease().json()
    lid = lease["lease_id"]
    seg_dir = st.segments_dir(ws.dir, lease["config_hash"])
    # wrong sha256 / missing header
    assert ctx.put(lid, 0, segments[0], sha_header="0" * 64).status_code == 400
    assert ctx.client.put(f"/api/enhance/{lid}/seg/0", content=segments[0], headers=H1).status_code == 400
    # not an mp4 / wrong frame count (segment 3 has 15 frames, segment 0 must have 25) / wrong frame size
    assert ctx.put(lid, 0, b"not a video").status_code == 400
    r = ctx.put(lid, 0, segments[3])
    assert r.status_code == 400 and "khung" in r.json()["detail"]
    odd = make_clip(tmp_path / "odd.mp4", w=OUT_W // 2, h=OUT_H // 2, frames=SEG).read_bytes()
    r = ctx.put(lid, 0, odd)
    assert r.status_code == 400 and "kích thước" in r.json()["detail"]
    with_audio = make_clip(tmp_path / "aud.mp4", w=OUT_W, h=OUT_H, frames=SEG, audio=True).read_bytes()
    assert ctx.put(lid, 0, with_audio).status_code == 400  # video only
    assert ctx.put(lid, 7, segments[0]).status_code == 400  # outside 0..3
    assert not list(seg_dir.glob("*.mp4")) and not list(seg_dir.glob(".put-*"))  # nothing stored, no leftovers
    # a good one
    r = ctx.put(lid, 0, segments[0])
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["expires_at"] >= lease["expires_at"]
    assert (seg_dir / "seg_00000.mp4").read_bytes() == segments[0]
    assert st.read(ws.dir)["segments"]["0"]["sha256"] == sha(segments[0])
    # same segment again (a retry after a lost answer) -> 200 idempotent, stored once
    r = ctx.put(lid, 0, segments[0])
    assert r.status_code == 200 and r.json()["idempotent"] is True
    assert sorted(p.name for p in seg_dir.glob("*.mp4")) == ["seg_00000.mp4"]
    # lease / token mismatches
    assert ctx.put("deadbeef", 1, segments[1]).status_code == 409
    assert ctx.put(lid, 1, segments[1], headers=H2).status_code == 409
    # the last segment is shorter (15 frames) and valid at n = 3
    assert ctx.put(lid, 3, segments[3]).status_code == 200


def test_put_too_large_is_413(tmp_path):
    c = Ctx(tmp_path, max_segment_mb=1)
    with c.client:
        make_yt_episode(c.cfg, E1)
        lid = c.lease().json()["lease_id"]
        r = c.put(lid, 0, b"\0" * (1024 * 1024 + 1))
        assert r.status_code == 413
        r = c.client.put(f"/api/enhance/{lid}/seg/0", content=iter([b"\0" * 600_000] * 2),
                         headers={**H1, "X-Sha256": "0" * 64})  # no Content-Length: counted while streaming
        assert r.status_code == 413
        assert not list(st.segments_dir(c.cfg.workspace.dir / E1, st.read(c.cfg.workspace.dir / E1)["config_hash"])
                        .glob(".put-*"))


def test_segments_must_share_one_profile(ctx, segments, tmp_path):
    ws = make_yt_episode(ctx.cfg, E1)
    lid = ctx.lease().json()["lease_id"]
    assert ctx.put(lid, 0, segments[0]).status_code == 200
    # same size and frame count but another pixel format: concat copy would break
    other = tmp_path / "p.mp4"
    import subprocess
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={OUT_W}x{OUT_H}:rate=25",
                    "-frames:v", str(SEG), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv444p", "-an",
                    str(other)], check=True)
    r = ctx.put(lid, 1, other.read_bytes())
    assert r.status_code == 400 and "khác các đoạn" in r.json()["detail"]


# --- AC3: assembly -----------------------------------------------------------------------------------------------

def _upload_all(ctx, lease, segments, headers=H1):
    for n, data in enumerate(segments):
        assert ctx.put(lease["lease_id"], n, data, headers=headers).status_code == 200


def test_all_segments_assemble_source_hd(ctx, segments):
    ws = make_yt_episode(ctx.cfg, E1)
    lease = ctx.lease().json()
    seg_dir = st.segments_dir(ws.dir, lease["config_hash"])
    _upload_all(ctx, lease, segments)
    wait_for(lambda: st.hd_fingerprint(ws.dir) is not None)
    wait_for(lambda: ctx.runner.latest_enhance(E1).status == "done")
    hd = st.hd_path(ws.dir)
    info = st.probe_video(hd)
    assert info["frames"] == FRAMES and (info["width"], info["height"]) == (OUT_W, OUT_H)
    assert str(info["fps"]) == "25" and info["audio_codec"] == "aac" and info["codec"] == "h264"
    # the audio is the source's, untouched (stream copy)
    src_info = st.probe_video(ws.dir / "source.mp4")
    assert abs(info["duration"] - src_info["duration"]) < 0.2
    doc = st.read(ws.dir)
    assert doc["state"] == st.DONE and doc["lease"] is None and doc["finished_at"]
    assert doc["source_hd_sha256"] == st.hd_fingerprint(ws.dir).sha256 and doc["workers"] and "RTX 3090" in doc["workers"][0]
    assert not seg_dir.exists() and not (ws.dir / st.ENHANCED_DIR).exists()
    # the lease ended with the last segment (the worker is not told to release): its old lease id is dead
    assert ctx.client.post(f"/api/enhance/{lease['lease_id']}/heartbeat", json={}, headers=H1).status_code == 409
    assert ctx.lease(H1).status_code == 204  # nothing left to enhance
    view = ctx.client.get(f"/api/episodes/{E1}", cookies=ctx.web_login()).json()["enhance"]
    assert view["state"] == "done" and view["hd_ready"] is True


def test_assembly_is_frame_accurate_across_workers(ctx, segments):
    """Segments from two workers (one died half way) give the same video: frame count = source, one video stream."""
    ws = make_yt_episode(ctx.cfg, E1)
    lease = ctx.lease(H1).json()
    for n in (0, 1):
        assert ctx.put(lease["lease_id"], n, segments[n]).status_code == 200
    ctx.clock.now += 50 * 3600
    new = ctx.lease(H2, gpu="RTX 3050").json()
    assert new["done_segments"] == [0, 1]
    for n in (2, 3):
        assert ctx.put(new["lease_id"], n, segments[n], headers=H2).status_code == 200
    wait_for(lambda: st.hd_fingerprint(ws.dir) is not None)
    info = st.probe_video(st.hd_path(ws.dir))
    assert info["frames"] == FRAMES and info["streams"] == 2
    doc = st.read(ws.dir)
    assert {s["gpu"] for s in doc["segments"].values()} == {"RTX 3090", "RTX 3050"} if doc["segments"] else True
    assert any("RTX 3050" in w for w in doc["workers"]) and any("RTX 3090" in w for w in doc["workers"])


def test_assembly_failure_is_recorded_and_retried_by_the_button(ctx, segments, monkeypatch):
    ws = make_yt_episode(ctx.cfg, E1)
    lease = ctx.lease().json()
    real = ctx.svc.ffmpeg
    ctx.svc.ffmpeg = "false"  # ffmpeg "fails"
    _upload_all(ctx, lease, segments)
    wait_for(lambda: ctx.runner.latest_enhance(E1) is not None and ctx.runner.latest_enhance(E1).status == "failed")
    doc = st.read(ws.dir)
    assert doc["state"] == st.FAILED and "ghép" in doc["error"] and not st.hd_path(ws.dir).exists()
    assert st.stored_segments(ws.dir, doc)  # segments kept
    assert ctx.lease(H2).status_code == 204  # not offered again by itself
    ctx.svc.ffmpeg = real
    cookie = ctx.web_login()
    r = ctx.client.post(f"/api/episodes/{E1}/enhance", json={"enabled": True}, cookies=cookie)
    assert r.status_code == 200
    wait_for(lambda: st.hd_fingerprint(ws.dir) is not None)


def test_restart_resumes_an_unfinished_assembly(tmp_path, segments):
    c = Ctx(tmp_path)
    ws = make_yt_episode(c.cfg, E1)
    doc = st.read(ws.dir)
    seg_dir = st.segments_dir(ws.dir, doc["config_hash"])
    seg_dir.mkdir(parents=True)
    for n, data in enumerate(segments):
        (seg_dir / f"seg_{n:05d}.mp4").write_bytes(data)
        doc["segments"][str(n)] = {"sha256": sha(data), "size": len(data), "worker": "w", "gpu": "g", "at": "x"}
    doc["state"] = st.ASSEMBLING  # the server stopped between the last segment and the end of the job
    st.write(ws.dir, doc)
    with c.client:  # start-up resumes it
        wait_for(lambda: st.hd_fingerprint(ws.dir) is not None)
    assert st.read(ws.dir)["state"] == st.DONE


# --- E7 / AC7: may-run -------------------------------------------------------------------------------------------

def test_may_run_yields_to_the_ai_lane_only_for_the_ollama_worker(ctx):
    started, release = threading.Event(), threading.Event()

    class Slow:
        def lane_steps(self):
            def run(job):
                started.set()
                assert release.wait(10)
            return [Step(AI, run)]

        def spec(self):
            return {}

    def ask(headers):
        return ctx.client.get("/api/enhance/may-run?worker=x", headers=headers).json()

    assert ask(H1) == {"run": True, "reason": ""} and ask(H2)["run"] is True
    ctx.runner.submit("somethingelse", "post", Slow())  # a post-compose job runs in the ai lane
    assert started.wait(5)
    r1, r2 = ask(H1), ask(H2)
    assert r1["run"] is False and "Ollama" in r1["reason"]  # the worker on the Ollama machine gives way
    assert r2["run"] is True  # the other worker does not
    release.set()
    assert ctx.runner.wait_idle(10)
    wait_for(lambda: ask(H1)["run"] is True)
    # "Tạm dừng enhance": every worker, and no new lease
    cookie = ctx.web_login()
    make_yt_episode(ctx.cfg, E1)
    assert ctx.client.post("/api/enhance-pause", json={"paused": True}, cookies=cookie).json()["paused"] is True
    assert ask(H1)["run"] is False and ask(H2)["run"] is False and "pause" in ask(H2)["reason"]
    assert ctx.lease(H2).status_code == 204
    assert ctx.client.post("/api/enhance-pause", json={"paused": False}, cookies=cookie).json()["paused"] is False
    assert ask(H2)["run"] is True and ctx.lease(H2).status_code == 200


def test_pause_is_kept_across_a_restart(tmp_path):
    c = Ctx(tmp_path)
    with c.client:
        cookie = c.web_login()
        c.client.post("/api/enhance-pause", json={"paused": True}, cookies=cookie)
    again = Ctx(tmp_path)
    assert again.svc.paused is True and again.svc.may_run("w3050")[0] is False


def test_queue_waiting_ai_jobs_do_not_count_while_paused(tmp_path):
    runner = JobRunner()
    gate, started = threading.Event(), threading.Event()

    class Hold:
        def lane_steps(self):
            def run(job):
                started.set()
                gate.wait(10)
            return [Step(AI, run)]

        def spec(self):
            return {}

    runner.start()
    try:
        assert runner.ai_busy() is False
        runner.submit("a", "post", Hold())
        runner.submit("b", "post", Hold())
        assert started.wait(5)  # one runs, one waits
        runner.pause("after")
        assert runner.ai_busy() is True  # one is still running
        gate.set()
        wait_for(lambda: runner.running() == {})
        assert runner.ai_busy() is False  # the waiting one is held by the pause: no Ollama use
        runner.resume()
        assert runner.wait_idle(10)
    finally:
        gate.set()
        runner.resume()
        runner.stop(5)
