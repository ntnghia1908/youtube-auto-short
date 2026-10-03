"""CP8.22 queue pause / resume + saved queue (docs/tasks/CP8.22-queue-pause-persist.md AC1-AC5; contract
docs/decisions/CP8.3-web-contract.md W5, W6, W7). Fake lane steps synchronised with flags; a "step" that must be
interruptible polls with ``time.sleep`` (an async KeyboardInterrupt only lands between bytecodes)."""

import json
import threading
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_short.config import Config, RenderConfig, WorkspaceConfig
from auto_short.pipeline import PIPELINE_STAGES, StageDeps, run_pipeline
from auto_short.web.jobs import (AI, DONE, FAILED, INTERRUPTED, KIND_PIPELINE, KIND_RENDER, PREPARE, QUEUED, RENDER,
                                 RUNNING, JobRunner, Step, pipeline_target)

from web_helpers import write_episode


def wait_for(pred, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.005)


def settle() -> None:
    time.sleep(0.15)


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"))


class Target:
    """Three-lane job. ``hold[lane]`` (Event): the step polls until it is set (interruptible); ``runs`` counts starts."""

    def __init__(self, name, *, hold=None, spec=None):
        self.name, self.hold, self._spec = name, hold or {}, spec or {"name": name}
        self.runs: list[str] = []

    def step(self, lane):
        def run(job):
            job.stage = lane
            self.runs.append(lane)
            ev = self.hold.get(lane)
            while ev is not None and not ev.is_set():
                time.sleep(0.005)
        return run

    def lane_steps(self):
        return [Step(lane, self.step(lane)) for lane in (PREPARE, AI, RENDER)]

    def spec(self):
        return self._spec


@pytest.fixture
def mk(tmp_path):
    """JobRunner with a state file; ``rebuild`` makes a fresh Target from the saved spec (kept in ``made``)."""
    runners, made = [], {}

    def factory(path=None, *, mode="lanes"):
        r = JobRunner(mode)

        def rebuild(kind, eid, spec, clip_ids):
            if spec.get("bad"):
                return None
            t = Target(spec["name"], hold=made.get(spec["name"], {}).get("hold"))
            made[spec["name"]] = {"target": t, "hold": t.hold}
            return t

        r.configure_persistence(path or tmp_path / "queue.json", rebuild)
        runners.append(r)
        return r

    yield factory, made
    for r in runners:
        r.stop(timeout=5)


def state(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def names(path, lane):
    return [(e["spec"]["name"], e["step"]) for e in state(path)["lanes"][lane]]


# --- AC2: "pause after the current step" ----------------------------------------------------------------------

def test_pause_after_step_lets_step_finish_then_nothing_starts(mk, tmp_path):
    factory, _ = mk
    r = factory()
    r.start()
    gate = threading.Event()
    a = Target("a", hold={PREPARE: gate})
    b = Target("b")
    ja, _ = r.submit("a", KIND_PIPELINE, a)
    jb, _ = r.submit("b", KIND_PIPELINE, b)
    wait_for(lambda: a.runs == [PREPARE])
    st = r.pause("after")
    assert st["paused"] and st["mode"] == "after" and st["running"] == 1
    gate.set()  # the running step finishes normally
    wait_for(lambda: ja.lane == AI and ja.waiting)
    settle()
    assert a.runs == [PREPARE] and b.runs == []  # nothing new started anywhere
    assert (ja.status, jb.status) == (RUNNING, QUEUED) and r.queue_state()["running"] == 0
    assert r.queue_state()["pending"] == 2
    r.resume()
    assert r.wait_idle(10)
    assert (ja.status, jb.status) == (DONE, DONE) and a.runs == [PREPARE, AI, RENDER]


# --- AC1: "pause now" ------------------------------------------------------------------------------------------

def test_pause_now_interrupts_requeues_at_head_and_resume_reruns(mk, tmp_path):
    factory, _ = mk
    r = factory()
    r.start()
    gate = threading.Event()
    a = Target("a", hold={PREPARE: gate})
    b = Target("b")
    ja, _ = r.submit("a", KIND_PIPELINE, a)
    jb, _ = r.submit("b", KIND_PIPELINE, b)
    wait_for(lambda: a.runs == [PREPARE])
    r.pause("now")
    wait_for(lambda: r.queue_position(ja) == 1)
    assert (ja.status, ja.error, ja.lane, ja.stage) == (QUEUED, None, None, None)  # not failed
    assert r.queue_position(jb) == 2 and r.running() == {}
    assert state(tmp_path / "queue.json")["paused"] is True
    assert names(tmp_path / "queue.json", PREPARE) == [("a", 0), ("b", 0)]
    settle()
    assert b.runs == [] and a.runs == [PREPARE]
    gate.set()
    r.resume()
    assert r.wait_idle(10)
    assert (ja.status, jb.status) == (DONE, DONE)
    assert a.runs == [PREPARE, PREPARE, AI, RENDER]  # the cut step ran again; finished ones did not
    assert list(r.running()) == [] and r.queue_state() == {"paused": False, "mode": None, "running": 0, "pending": 0}


def test_pause_now_in_later_lane_keeps_job_waiting_for_that_lane(mk):
    factory, _ = mk
    r = factory()
    r.start()
    gate = threading.Event()
    a = Target("a", hold={AI: gate})
    ja, _ = r.submit("a", KIND_PIPELINE, a)
    wait_for(lambda: a.runs == [PREPARE, AI])
    r.pause("now")
    wait_for(lambda: r.queue_position(ja) == 1)
    assert (ja.status, ja.lane, ja.waiting, ja.error) == (RUNNING, AI, True, None)
    gate.set()
    r.resume()
    assert r.wait_idle(10) and ja.status == DONE and a.runs == [PREPARE, AI, AI, RENDER]


def test_submit_while_paused_queues_without_running(mk):
    factory, _ = mk
    r = factory()
    r.start()
    r.pause("after")
    t = Target("x")
    j, created = r.submit("x", KIND_PIPELINE, t)
    settle()
    assert created and j.status == QUEUED and t.runs == [] and r.queue_position(j) == 1
    r.resume()
    assert r.wait_idle(10) and j.status == DONE


# --- AC4: saved queue, restore, stop ---------------------------------------------------------------------------

def test_queue_saved_in_order_with_step_and_spec(mk, tmp_path):
    factory, _ = mk
    r = factory()
    r.start()
    gate = threading.Event()
    r.submit("a", KIND_PIPELINE, Target("a", hold={AI: gate}))
    wait_for(lambda: r.job("1").lane == AI)
    r.submit("b", KIND_PIPELINE, Target("b", hold={PREPARE: gate}))
    r.submit("c", KIND_PIPELINE, Target("c", hold={PREPARE: gate}))
    wait_for(lambda: r.running().get(PREPARE) is not None and r.running()[PREPARE].episode_id == "b")
    path = tmp_path / "queue.json"
    assert names(path, AI) == [("a", 1)]  # running job at the head of its lane
    assert names(path, PREPARE) == [("b", 0), ("c", 0)]
    gate.set()
    assert r.wait_idle(10)
    assert names(path, PREPARE) == [] and names(path, AI) == []


def test_stop_then_restore_running_job_goes_first(mk, tmp_path):
    factory, made = mk
    r1 = factory()
    r1.start()
    gate = threading.Event()
    r1.submit("a", KIND_PIPELINE, Target("a", hold={PREPARE: gate}))
    r1.submit("b", KIND_PIPELINE, Target("b"))
    r1.submit("c", KIND_PIPELINE, Target("c"))
    wait_for(lambda: r1.running().get(PREPARE) is not None)
    r1.pause("after")
    r1.stop(timeout=5)  # Q3: Ctrl-C while a step runs
    j1 = r1.job("1")
    assert j1.status == INTERRUPTED
    assert names(tmp_path / "queue.json", PREPARE) == [("a", 0), ("b", 0), ("c", 0)]
    r2 = factory()
    assert r2.restore() == 3
    assert r2.queue_state() == {"paused": True, "mode": "after", "running": 0, "pending": 3}
    assert [(j.episode_id, j.status) for j in sorted(r2.jobs(), key=lambda j: int(j.id))] == [
        ("a", QUEUED), ("b", QUEUED), ("c", QUEUED)]
    made["a"]["hold"][PREPARE] = threading.Event()
    made["a"]["hold"][PREPARE].set()
    r2.start()
    settle()
    assert made["a"]["target"].runs == []  # still paused after the restart
    r2.resume()
    assert r2.wait_idle(10) and all(j.status == DONE for j in r2.jobs())


def test_restore_keeps_waiting_job_in_its_lane_and_skips_broken_entries(mk, tmp_path, caplog):
    factory, made = mk
    path = tmp_path / "queue.json"
    path.write_text(json.dumps({"version": 1, "mode": "lanes", "paused": False, "lanes": {
        "prepare": [{"kind": "pipeline", "episode_id": "p", "spec": {"name": "p"}, "clip_ids": [], "step": 0},
                    {"kind": "pipeline", "episode_id": "bad", "spec": {"name": "bad", "bad": True},
                     "clip_ids": [], "step": 0},
                    {"kind": "pipeline", "episode_id": "boom", "spec": {}, "clip_ids": [], "step": 0},  # KeyError
                    "not an entry"],
        "ai": [{"kind": "pipeline", "episode_id": "g", "spec": {"name": "g"}, "clip_ids": [], "step": 1}],
        "render": []}}), encoding="utf-8")
    r = factory()
    with caplog.at_level("WARNING", logger="auto_short"):
        assert r.restore() == 2  # the broken ones are skipped, not fatal
    assert sum("bỏ qua" in m for m in caplog.messages) == 3
    g = r.latest("g")
    assert (g.status, g.lane, g.waiting, g.step, g.stage) == (RUNNING, AI, True, 1, "selection")
    assert r.queue_position(g) == 1 and r.latest("p").status == QUEUED
    # a corrupt file restores nothing and does not raise
    path.write_text("{ not json", encoding="utf-8")
    assert factory().restore() == 0


def test_restore_other_mode_starts_every_job_from_step_zero(mk, tmp_path):
    factory, _ = mk
    r1 = factory()
    r1.start()
    gate = threading.Event()
    r1.submit("a", KIND_PIPELINE, Target("a", hold={AI: gate}))
    wait_for(lambda: r1.job("1").lane == AI)
    r1.stop(timeout=5)
    r2 = factory(mode="serial")
    assert r2.restore() == 1
    j = r2.latest("a")
    assert (j.status, j.step, j.lane) == (QUEUED, 0, None)


# --- web app -------------------------------------------------------------------------------------------------

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.web import app as app_mod  # noqa: E402

PW = "pw"
VA, VB = "tHtxw6ykUmM", "rbjfCfFq3Dk"


def fake_pipeline(calls):
    def runner(stage):
        def run(target_or_id, config, **kw):
            eid = (kw.get("episode_id") or target_or_id.rsplit("/", 1)[-1]) if stage == "ingest" else target_or_id
            calls.append((stage, eid))
            if stage == "ingest":
                (Path(config.workspace.dir) / eid).mkdir(parents=True, exist_ok=True)
                return SimpleNamespace(episode_id=eid, ran=True)
            if stage == "render":
                write_episode(config, eid)
                return SimpleNamespace(episode_id=eid, ran=True, rendered=2, clips=2, encoded=2, reused=0,
                                       path=Path(config.render.output_dir) / eid / "render_manifest.json")
            return SimpleNamespace(episode_id=eid, ran=True)
        return run

    return partial(run_pipeline, deps=StageDeps(runners={s: runner(s) for s in PIPELINE_STAGES}))


def client(cfg, calls):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, pipeline=fake_pipeline(calls),
                             disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9))
    c = TestClient(app, follow_redirects=False)
    return c


def login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def test_api_pause_resume_submit_while_paused_and_restart(tcfg):
    calls: list = []
    with client(tcfg, calls) as c:
        login(c)
        assert c.get("/api/queue").json() == {"paused": False, "mode": None, "running": 0, "pending": 0}
        assert c.post("/api/queue/pause", json={"mode": "bogus"}).status_code == 422
        assert c.post("/api/queue/pause", json={"mode": "after"}).json()["paused"] is True
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{VA}", "kinds": ["short"]})
        assert r.status_code == 202  # AC3: a link is accepted while paused
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{VB}", "series": "Kinh X", "episode": "7",
                                          "kinds": ["short", "khaithi"], "min_minutes": 6, "max_minutes": 12})
        assert r.status_code == 202
        settle()
        assert calls == [] and c.get("/api/queue").json()["pending"] == 3
        assert c.get("/api/episodes").json()["queue"]["paused"] is True
    # server restart (the lifespan exit saved the queue)
    saved = state(Path(tcfg.workspace.dir) / ".web_queue.json")
    assert saved["paused"] is True and [e["episode_id"] for e in saved["lanes"]["prepare"]] == [VA, VB, VB + ".kt"]
    with client(tcfg, calls) as c:
        login(c)
        runner = c.app.state.runner
        assert c.get("/api/queue").json() == {"paused": True, "mode": "after", "running": 0, "pending": 3}
        assert [(j.episode_id, j.active) for j in sorted(runner.jobs(), key=lambda j: int(j.id))] == [
            (VA, True), (VB, True), (VB + ".kt", True)]
        assert runner.latest(VB + ".kt").target.episode_id == VB + ".kt"  # khai thị job kept its episode
        kt = json.loads((Path(tcfg.workspace.dir) / (VB + ".kt") / "khaithi.json").read_text(encoding="utf-8"))
        assert 6 in kt.values() and 12 in kt.values()  # the minutes stay in the workspace (K2)
        assert c.app.state.auto_archive_pass() == []  # AC5: restored jobs count as "has a job"
        settle()
        assert calls == []
        assert c.post("/api/queue/resume").json()["paused"] is False
        assert runner.wait_idle(10)
        assert all(j.status == DONE for j in runner.jobs())
    assert state(Path(tcfg.workspace.dir) / ".web_queue.json")["lanes"] == {"prepare": [], "ai": [], "render": []}


def test_restore_skips_job_whose_workspace_is_gone(tcfg):
    ws = Path(tcfg.workspace.dir)
    ws.mkdir(parents=True)
    (ws / ".web_queue.json").write_text(json.dumps({"version": 1, "mode": "lanes", "paused": True, "lanes": {
        "prepare": [], "ai": [], "render": [
            {"kind": "render", "episode_id": "gone123", "spec": {}, "clip_ids": ["k01"], "step": 0}]}}),
        encoding="utf-8")
    with client(tcfg, []) as c:
        login(c)
        assert c.get("/api/queue").json() == {"paused": True, "mode": "after", "running": 0, "pending": 0}
