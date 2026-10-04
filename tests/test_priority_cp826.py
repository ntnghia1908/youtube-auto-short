"""CP8.26 priority of videos in the job queue (docs/tasks/CP8.26-priority.md AC1-AC6): the lanes start the marked
videos first (mark order, stable), never interrupt a running job, keep pause / YouTube wait, the enhance lease puts
HD-waiting > priority > series order, the marks survive a restart. Fake lane steps, fake clocks, no network."""

import json
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, RenderConfig, WebConfig, WorkspaceConfig  # noqa: E402
from auto_short.enhance import state as st  # noqa: E402
from auto_short.enhance.service import EnhanceService  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web.auth import COOKIE_NAME  # noqa: E402
from auto_short.web.jobs import DONE, KIND_PIPELINE, KIND_RENDER, QUEUED, JobRunner, pipeline_target  # noqa: E402
from auto_short.web.priority import Priority, base_id  # noqa: E402

from enhance_helpers import enhance_cfg, make_yt_episode  # noqa: E402
from test_youtube_wait import Clock, Net, advance, blocked_error, blocked_n, submit  # noqa: E402

PW = "pw"
PL = "PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp"


def wait_for(pred, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.005)


class Rec:
    """A render-lane job: records its start, optionally waits on a gate."""

    def __init__(self, name, log, gate=None):
        self.name, self.log, self.gate = name, log, gate

    def __call__(self, job):
        self.log.append(self.name)
        if self.gate is not None:
            assert self.gate.wait(10)


@pytest.fixture
def runner():
    r = JobRunner()
    r.start()
    yield r
    r.stop(timeout=5)


def blocked_lane(runner, log):
    """A running job holding the render lane; returns its gate."""
    gate = threading.Event()
    runner.submit("hold", KIND_RENDER, Rec("hold", log, gate))
    wait_for(lambda: log == ["hold"])
    return gate


# --- AC1 / AC3 ---------------------------------------------------------------------------------------------------

def test_marked_job_starts_first_then_the_rest_in_order(runner):
    log = []
    gate = blocked_lane(runner, log)
    jobs = {n: runner.submit(n, KIND_RENDER, Rec(n, log))[0] for n in "abc"}
    runner.priority.mark(["c"])
    assert [runner.queue_position(jobs[n]) for n in "cab"] == [1, 2, 3]
    gate.set()
    assert runner.wait_idle(10)
    assert log == ["hold", "c", "a", "b"]


def test_marks_keep_mark_order_and_a_job_submitted_later_is_prioritised(runner):
    log = []
    gate = blocked_lane(runner, log)
    for n in "abcd":
        runner.submit(n, KIND_RENDER, Rec(n, log))
    runner.priority.mark(["d", "b"])
    runner.submit("e", KIND_RENDER, Rec("e", log))
    runner.priority.mark(["e"])
    runner.submit("b.kt", KIND_RENDER, Rec("b.kt", log))  # the khai thị episode shares the mark of its video
    gate.set()
    assert runner.wait_idle(10)
    assert log == ["hold", "d", "b", "b.kt", "e", "a", "c"]


def test_unmark_restores_the_normal_order_and_running_job_is_not_interrupted(runner):
    log = []
    gate = blocked_lane(runner, log)
    for n in "ab":
        runner.submit(n, KIND_RENDER, Rec(n, log))
    runner.priority.mark(["b", "hold"])  # marking the running one changes nothing for it
    assert runner.running()["render"].episode_id == "hold" and runner.running()["render"].status == "running"
    runner.priority.unmark(["b"])
    gate.set()
    assert runner.wait_idle(10)
    assert log == ["hold", "a", "b"] and all(j.status == DONE for j in runner.jobs())


def test_pause_keeps_working_with_priority(runner):
    log = []
    runner.pause("after")
    for n in "abc":
        runner.submit(n, KIND_RENDER, Rec(n, log))
    runner.priority.mark(["c"])
    time.sleep(0.1)
    assert log == []  # paused: nothing starts, marked or not
    runner.resume()
    assert runner.wait_idle(10)
    assert log == ["c", "a", "b"]


# --- AC3 YouTube wait ---------------------------------------------------------------------------------------------

@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"))


def test_youtube_wait_retries_the_marked_job_first(tcfg):
    A, B, C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"
    clock, net = Clock(), Net(blocked_error())
    r = JobRunner(youtube_retry_seconds=900.0, youtube_retry_max_seconds=7200.0, monotonic=clock.mono, wall=clock.wall)
    r.start()
    try:
        r.pause("after")
        jobs = [submit(r, tcfg, e, net) for e in (A, B, C)]
        r.priority.mark([C])
        r.resume()
        wait_for(blocked_n(r, 1))
        assert net.ingests() == [C]  # the first attempt (and the one blocked) is the marked video
        assert [j.status for j in jobs] == [QUEUED] * 3
        net.error = None
        advance(r, clock, 15 * 60.0)
        assert r.wait_idle(10)
        assert net.ingests() == [C, C, A, B]
        assert all(j.status == DONE for j in jobs)
    finally:
        r.stop(timeout=5)


# --- AC5 persistence + mark helpers -------------------------------------------------------------------------------

def test_marks_survive_a_restart_in_order(tmp_path):
    path = tmp_path / ".web_priority.json"
    p = Priority(path)
    p.mark(["x", "y.kt", "z"])
    p.unmark(["x"])
    again = Priority(path)
    assert again.videos() == ["y", "z"] and again.rank("y.kt") == 0 and again.rank("z#post") == 1
    assert again.rank("x") is None and base_id("q.kt#hd") == "q"
    path.write_text("not json", encoding="utf-8")
    assert Priority(path).videos() == []  # unreadable file: ignored


# --- AC2 / AC5 API ---------------------------------------------------------------------------------------------

V = [f"vid0000000{n}" for n in range(1, 6)]  # episodes 1..5; playlist order 3, 5, 1, 4, 2


def write_playlist(cfg):
    path = Path(cfg.workspace.dir) / "_playlists" / f"{PL}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = [{"index": i, "video_id": V[n - 1], "title": f"Địa Tạng Kinh tập {n}/102 - Pháp Sư Tịnh Không",
                "duration": 3000.0, "episode": str(n), "available": True}
               for i, n in enumerate((3, 5, 1, 4, 2), 1)]
    path.write_text(json.dumps({"schema_version": 1, "playlist_id": PL, "title": "Địa Tạng", "url": "u",
                                "fetched_at": "2026-10-04T00:00:00Z", "entries": entries}), encoding="utf-8")


def make_app(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 web=WebConfig(session_days=30))
    write_playlist(cfg)
    runner = JobRunner()
    app = app_mod.create_app(cfg, PW, runner=runner, disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9))
    client = TestClient(app, follow_redirects=False)
    r = client.post("/login", json={"password": PW})
    return client, {COOKIE_NAME: r.cookies[COOKIE_NAME]}, runner


def test_priority_whole_series_marks_in_episode_order_and_unmarks(tmp_path):
    client, cookie, runner = make_app(tmp_path)
    r = client.post(f"/api/playlists/{PL}/priority", json={"value": True}, cookies=cookie)
    assert r.status_code == 200 and r.json()["changed"] == 5
    assert runner.priority.videos() == V  # episode order, not playlist order
    view = client.get(f"/api/playlists/{PL}", cookies=cookie).json()
    assert view["priority_count"] == 5 and all(e["priority"] for e in view["entries"])
    # one episode on its own: marked last
    client.post(f"/api/playlists/{PL}/priority", json={"value": False}, cookies=cookie)
    assert runner.priority.videos() == []
    assert client.post(f"/api/episodes/{V[3]}/priority", json={"value": True}, cookies=cookie).json()["priority"]
    assert client.post(f"/api/episodes/{V[3]}.kt/priority", json={"value": True}, cookies=cookie).json()["priority"]
    assert runner.priority.videos() == [V[3]]
    assert client.post("/api/episodes/bad id/priority", json={"value": True}, cookies=cookie).status_code in (404, 422)
    assert client.post(f"/api/episodes/{V[3]}/priority", json={"value": "yes"}, cookies=cookie).status_code == 422
    assert client.post(f"/api/episodes/{V[3]}/priority", json={"value": False}, cookies=cookie).json()["priority"] is False


def test_priority_series_among_many_jobs_and_restart(tmp_path):
    client, cookie, runner = make_app(tmp_path)
    log = []
    runner.pause("after")
    for n in range(100):
        runner.submit(f"other{n:03d}", KIND_RENDER, Rec(f"other{n:03d}", log))
    for v in (V[2], V[0], V[1]):  # three episodes of the series queued late, in a wrong order
        runner.submit(v, KIND_RENDER, Rec(v, log))
    client.post(f"/api/playlists/{PL}/priority", json={"value": True}, cookies=cookie)
    assert [runner.queue_position(j) for j in runner.jobs() if j.episode_id in V] == [3, 1, 2]
    # restart: the marks come back from disk
    client2, cookie2, runner2 = make_app(tmp_path)
    assert runner2.priority.videos() == V
    assert client2.get(f"/api/playlists/{PL}", cookies=cookie2).json()["priority_count"] == 5
    client2.post(f"/api/playlists/{PL}/priority", json={"value": False}, cookies=cookie2)
    assert runner2.priority.videos() == []
    assert Priority(Path(tmp_path) / "work" / ".web_priority.json").videos() == []  # the unmark is on disk too


# --- AC4 enhance lease --------------------------------------------------------------------------------------------

def _hd_episode(cfg, eid, n, at, low_source, **extra):
    ws = make_yt_episode(cfg, eid, template=low_source)
    meta = ws.dir / "metadata.json"
    doc = json.loads(meta.read_text())
    doc["title"] = f"Địa Tạng Kinh tập {n}/102 - Pháp Sư Tịnh Không"
    meta.write_text(json.dumps(doc, ensure_ascii=False))
    d = st.read(ws.dir)
    d.update(wanted_at=f"2026-10-04T00:00:{at:02d}Z", **extra)
    st.write(ws.dir, d)


@pytest.fixture(scope="module")
def low_source(tmp_path_factory):
    from enhance_helpers import FPS, SRC_H, make_clip
    p = tmp_path_factory.mktemp("src") / "low.mp4"
    return make_clip(p, w=64, h=SRC_H, frames=FPS * 2)


def lease_all(svc, cfg, n):
    got = []
    for _ in range(n):
        lease = svc.lease("w1")
        assert lease is not None
        got.append(lease["episode_id"])
        d = st.read(cfg.workspace.dir / lease["episode_id"])
        d.update(state=st.DONE, lease=None)
        st.write(cfg.workspace.dir / lease["episode_id"], d)
    return got


def test_lease_order_waiting_hd_then_priority_then_series_order(tmp_path, low_source):
    cfg = enhance_cfg(tmp_path)
    for eid, n, at, extra in (("vidB0000001", 1, 0, {}), ("vidB0000002", 2, 1, {}), ("vidB0000003", 3, 2, {}),
                              ("vidB0000004", 4, 3, {}), ("vidB0000005", 5, 4, {"waiting_hd": True})):
        _hd_episode(cfg, eid, n, at, low_source, **extra)
    svc = EnhanceService(cfg)
    prio = Priority()
    prio.mark(["vidB0000004", "vidB0000003"])  # mark order: 4 then 3
    svc.priority_rank = prio.rank
    assert lease_all(svc, cfg, 5) == ["vidB0000005", "vidB0000004", "vidB0000003", "vidB0000001", "vidB0000002"]


def test_lease_order_without_marks_is_unchanged(tmp_path, low_source):
    cfg = enhance_cfg(tmp_path)
    for eid, n, at in (("vidB0000003", 3, 0), ("vidB0000001", 1, 1), ("vidB0000002", 2, 2)):
        _hd_episode(cfg, eid, n, at, low_source)
    assert lease_all(EnhanceService(cfg), cfg, 3) == ["vidB0000001", "vidB0000002", "vidB0000003"]
