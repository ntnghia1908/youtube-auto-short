"""CP8.10 queue lanes prepare / ai / render (docs/tasks/CP8.10-queue-lanes.md AC1-AC8; contract
docs/decisions/CP8.3-web-contract.md W5). Fake lane steps / stages synchronised with events: no timing assumption
except the short settle before a negative assertion (a lane must *not* start a job)."""

import hashlib
import json
import logging
import threading
import time
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_short.config import Config, ConfigError, RenderConfig, WebConfig, WorkspaceConfig, from_dict
from auto_short.config import load as load_config
from auto_short.ingest import run_ingest
from auto_short.pipeline import PIPELINE_STAGES, PipelineError, PreflightError, StageDeps, run_pipeline
from auto_short.web.jobs import (AI, DONE, FAILED, INTERRUPTED, KIND_PIPELINE, KIND_RENDER, LANES, PREFETCH_LIMIT,
                                 PREPARE, QUEUED, RENDER, RUNNING, JobFailed, JobRunner, Step, pipeline_target)
from auto_short.web.storage import BLOCK_MESSAGE
from auto_short.workspace import FAILED as STAGE_FAILED, Workspace, run_stage

from web_helpers import fake_pipeline, write_episode

log = logging.getLogger("auto_short")


def wait_for(pred, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.005)


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"))


@pytest.fixture
def runner():
    r = JobRunner()
    r.start()
    yield r
    r.stop(timeout=5)


class Trace:
    """Start / end of every lane step + a check that a lane never runs two steps at once."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events: list[tuple[str, str, str]] = []
        self.busy = {lane: 0 for lane in (*LANES, "serial")}
        self.overlaps: list[str] = []

    def add(self, lane, name, what):
        with self.lock:
            self.events.append((lane, name, what))
            self.busy[lane] += 1 if what == "start" else -1
            if self.busy[lane] > 1:
                self.overlaps.append(f"{lane}: {name}")

    def starts(self, lane):
        return [n for ln, n, w in self.events if ln == lane and w == "start"]

    def has(self, lane, name, what="end"):
        with self.lock:
            return (lane, name, what) in self.events


class LaneTarget:
    """A job whose lane steps log a marker, record start / end, optionally wait on a gate or fail."""

    def __init__(self, name, trace, *, gates=None, fail=None):
        self.name, self.trace, self.gates, self.fail = name, trace, gates or {}, fail

    def step(self, lane, trace_lane=None):
        def run(job):
            job.stage = lane
            self.trace.add(trace_lane or lane, self.name, "start")
            try:
                log.info("mark %s %s", self.name, lane)
                gate = self.gates.get(lane)
                if gate is not None:
                    assert gate.wait(10)
                if self.fail == lane:
                    raise JobFailed(f"{lane}: boom")
            finally:
                self.trace.add(trace_lane or lane, self.name, "end")
        return run

    def lane_steps(self):
        return [Step(lane, self.step(lane)) for lane in LANES]

    def __call__(self, job):  # serial mode: the whole job
        for lane in LANES:
            self.step(lane, "serial")(job)


# --- AC1 lanes overlap, one job per lane, FIFO per lane -----------------------------------------------------

def test_lanes_overlap_fifo_and_render_job(runner):
    trace, gate = Trace(), threading.Event()
    ja, _ = runner.submit("a", KIND_PIPELINE, LaneTarget("a", trace, gates={RENDER: gate}))
    jb, _ = runner.submit("b", KIND_PIPELINE, LaneTarget("b", trace))
    jc, _ = runner.submit("c", KIND_PIPELINE, LaneTarget("c", trace))
    # A renders (blocked) while B and C go through prepare and ai, then wait for the render lane in order.
    wait_for(lambda: jc.waiting and jc.lane == RENDER)
    assert runner.running() == {RENDER: ja} and not trace.has(RENDER, "a")
    assert all(trace.has(lane, n) for lane in (PREPARE, AI) for n in "bc")
    assert (ja.status, ja.lane, ja.waiting) == (RUNNING, RENDER, False) and runner.queue_position(ja) is None
    assert (jb.status, jb.lane, jb.waiting, jb.stage) == (RUNNING, RENDER, True, "render")
    assert runner.queue_position(jb) == 1 and runner.queue_position(jc) == 2
    d = jb.to_dict(logs=False)
    assert (d["status"], d["lane"], d["waiting"]) == ("running", "render", True)
    # a render job (title edit) goes straight to the tail of the render lane (Q3: no priority)
    rendered = []
    jr, _ = runner.submit("r", KIND_RENDER, lambda job: rendered.append(job.id))
    assert (jr.status, jr.lane, jr.waiting) == (QUEUED, None, False) and runner.queue_position(jr) == 3
    gate.set()
    assert runner.wait_idle(10)
    assert trace.overlaps == []
    for lane in LANES:
        assert trace.starts(lane) == ["a", "b", "c"]
    assert trace.events.index((RENDER, "c", "end")) < len(trace.events) and rendered == [jr.id]
    for job in (ja, jb, jc, jr):
        assert (job.status, job.lane, job.waiting) == (DONE, None, False) and job.finished_at
    assert any("start pipeline job" in line for line in jb.logs)
    assert any("continues in lane render" in line for line in jb.logs)


def test_plain_callable_pipeline_job_runs_in_prepare(runner):
    done = []
    job, _ = runner.submit("x", KIND_PIPELINE, lambda j: done.append(j.id))
    assert runner.wait_idle(5) and done == [job.id] and job.status == DONE


# --- AC2 bounded prefetch + disk check before ingest ---------------------------------------------------------

def test_prefetch_limit(runner):
    trace, gate = Trace(), threading.Event()
    ja, _ = runner.submit("a", KIND_PIPELINE, LaneTarget("a", trace, gates={AI: gate}))
    others = [runner.submit(n, KIND_PIPELINE, LaneTarget(n, trace))[0] for n in "bcde"]
    jb, jc, jd, je = others
    wait_for(lambda: jb.waiting and jc.waiting)
    assert PREFETCH_LIMIT == 2
    time.sleep(0.2)  # settle: the prepare lane must not start D while B and C wait for the ai lane
    assert runner.running() == {AI: ja}
    assert trace.starts(PREPARE) == ["a", "b", "c"]
    assert (jd.status, jd.lane, runner.queue_position(jd)) == (QUEUED, None, 1)
    assert (jb.lane, runner.queue_position(jb), runner.queue_position(jc)) == (AI, 1, 2)
    gate.set()
    assert runner.wait_idle(10)
    assert trace.overlaps == [] and all(j.status == DONE for j in (ja, *others))
    assert trace.starts(PREPARE) == trace.starts(AI) == trace.starts(RENDER) == list("abcde")


def test_disk_block_before_ingest_fails_without_download(runner, tcfg):
    calls = []
    job, _ = runner.submit("abcdefghijk", KIND_PIPELINE, pipeline_target(
        "https://youtu.be/abcdefghijk", tcfg, pipeline=fake_pipeline(calls), preflight=None,
        disk_blocked=lambda: BLOCK_MESSAGE))
    assert runner.wait_idle(5)
    assert (job.status, job.error, job.lane) == (FAILED, BLOCK_MESSAGE, None) and calls == []


# --- web app helpers -----------------------------------------------------------------------------------------

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.web import app as app_mod  # noqa: E402

PW = "pw"
VA, VB = "tHtxw6ykUmM", "rbjfCfFq3Dk"


def gated_pipeline(calls, gates=None, *, ingest=None):
    """``run_pipeline`` with fake stages; ``gates[(stage, episode_id)]`` blocks that stage; ingest makes the
    workspace dir (or calls ``ingest``, e.g. the real ``run_ingest``); render writes a finished fake episode unless
    the workspace has a manifest."""
    gates = gates or {}

    def runner(stage):
        def run(target_or_id, config, **kw):
            eid = (kw.get("episode_id") or target_or_id.rsplit("/", 1)[-1]) if stage == "ingest" else target_or_id
            calls.append((stage, eid, "start"))
            gate = gates.get((stage, eid))
            if gate is not None:
                assert gate.wait(10)
            if stage == "ingest":
                if ingest is not None:
                    res = ingest(target_or_id, config, **kw)
                else:
                    (Path(config.workspace.dir) / eid).mkdir(parents=True, exist_ok=True)
                    res = SimpleNamespace(episode_id=eid, ran=True)
            elif stage == "render":
                if not (Path(config.workspace.dir) / eid / "manifest.json").exists():  # keep a real ingest's files
                    write_episode(config, eid)
                res = SimpleNamespace(episode_id=eid, ran=True, rendered=2, clips=2, encoded=2, reused=0,
                                      path=Path(config.render.output_dir) / eid / "render_manifest.json")
            else:
                res = SimpleNamespace(episode_id=eid, ran=True)
            calls.append((stage, eid, "end"))
            return res
        return run

    return partial(run_pipeline, deps=StageDeps(runners={s: runner(s) for s in PIPELINE_STAGES}))


def client(cfg, pipeline, *, disk=None, preflight=lambda c: None):
    app = app_mod.create_app(cfg, PW, preflight=preflight, pipeline=pipeline,
                             disk_usage=disk or (lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9)))
    c = TestClient(app, follow_redirects=False)
    return c


def _login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def _submit(c, vid, **extra):
    return c.post("/api/episodes", json={"url": f"https://youtu.be/{vid}", "kinds": ["short"], **extra})


def test_disk_block_rechecked_in_prepare_lane(tcfg):
    """AC2: the drive fills up while B waits in the prepare queue -> B fails with the W9 message, no ingest."""
    free = {"bytes": 50 * 10**9}
    calls, gate = [], threading.Event()
    with client(tcfg, gated_pipeline(calls, {("transcript", VA): gate}),
                disk=lambda p: (100 * 10**9, 100 * 10**9 - free["bytes"], free["bytes"])) as c:
        _login(c)
        assert _submit(c, VA).status_code == 202
        assert _submit(c, VB).status_code == 202
        free["bytes"] = 10**9
        gate.set()
        assert c.app.state.runner.wait_idle(10)
        job = c.get(f"/api/episodes/{VB}").json()["job"]
        assert (job["status"], job["error"]) == ("failed", BLOCK_MESSAGE)
        assert [e for s, e, w in calls if s == "ingest" and w == "start"] == [VA]
        assert c.get(f"/api/episodes/{VA}").json()["job"]["status"] == "done"


# --- AC3 Short -> khai thị order, source reused (Q7 / K5) ---------------------------------------------------

def test_khaithi_ingest_after_short_transcript_reuses_download(tcfg, video):
    from test_ingest_youtube import FakeDownloader

    downloader = FakeDownloader(video)
    calls = []
    real_ingest = partial(run_ingest, downloader=downloader)
    with client(tcfg, gated_pipeline(calls, ingest=real_ingest)) as c:
        _login(c)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{VB}"})  # default kinds: Short + khai thị
        assert r.status_code == 202 and [e["episode_id"] for e in r.json()["episodes"]] == [VB, VB + ".kt"]
        assert c.app.state.runner.wait_idle(20)
        for eid in (VB, VB + ".kt"):
            assert c.get(f"/api/episodes/{eid}").json()["job"]["status"] == "done", eid
    assert calls.index(("ingest", VB + ".kt", "start")) > calls.index(("transcript", VB, "end"))
    assert len(downloader.calls) == 1  # K5: the khai thị episode hardlinks the Short's download
    root = Path(tcfg.workspace.dir)
    assert (root / VB / "source.mp4").stat().st_ino == (root / (VB + ".kt") / "source.mp4").stat().st_ino


# --- AC4 a job waiting between two lanes is active (Q6) ------------------------------------------------------

def test_waiting_between_lanes_is_active(tcfg):
    calls, gate = [], threading.Event()
    write_episode(tcfg, VB)  # finished before: review / delete / archive would be possible without a job
    with client(tcfg, gated_pipeline(calls, {("selection", VA): gate})) as c:
        _login(c)
        first = _submit(c, VA).json()["job"]
        assert _submit(c, VB).status_code == 202
        runner = c.app.state.runner
        wait_for(lambda: runner.latest(VB).waiting)
        again = _submit(c, VB)
        assert again.status_code == 200 and again.json()["created"] is False
        job = again.json()["job"]
        assert (job["status"], job["lane"], job["waiting"], job["queue_position"], job["stage"]) == \
            ("running", "ai", True, 1, "selection")
        d = c.get(f"/api/episodes/{VB}").json()["job"]
        assert (d["status"], d["lane"], d["waiting"], d["queue_position"]) == ("running", "ai", True, 1)
        a = c.get(f"/api/episodes/{VA}").json()["job"]
        assert (a["id"], a["lane"], a["waiting"], a["queue_position"]) == (first["id"], "ai", False, None)
        items = {i["id"]: i for i in c.get("/api/episodes").json()["episodes"]}
        assert (items[VB]["job"]["lane"], items[VB]["job"]["waiting"]) == ("ai", True)
        for method, path, body in (
                ("post", f"/api/episodes/{VB}/shorts/k01/title", {"set": "Tiêu đề mới"}),
                ("post", f"/api/episodes/{VB}/shorts/k01/delete", None),
                ("post", f"/api/episodes/{VB}/shorts/k01/restore", None),
                ("post", f"/api/episodes/{VB}/archive", None),
                ("delete", f"/api/episodes/{VB}", None)):
            r = getattr(c, method)(path, **({"json": body} if body is not None else {}))
            assert r.status_code == 409 and r.json()["job"]["waiting"] is True, path
        gate.set()
        assert runner.wait_idle(10)
        d = c.get(f"/api/episodes/{VB}").json()["job"]
        assert (d["status"], d["lane"], d["waiting"], d["queue_position"]) == ("done", None, False, None)
        assert [s["stage"] for s in d["stages"]] == list(PIPELINE_STAGES)


# --- AC5 an error ends the job in its lane, other jobs go on ------------------------------------------------

def test_errors_end_job_in_their_lane(runner, tcfg):
    calls = []

    def down(c):
        raise PreflightError("cannot reach Ollama")

    url = "https://youtu.be/{}"
    j_render, _ = runner.submit("aaaaaaaaaaa", KIND_PIPELINE, pipeline_target(
        url.format("aaaaaaaaaaa"), tcfg, pipeline=fake_pipeline(calls, fail_stage="render"), preflight=None))
    j_pre, _ = runner.submit("bbbbbbbbbbb", KIND_PIPELINE, pipeline_target(
        url.format("bbbbbbbbbbb"), tcfg, pipeline=fake_pipeline(calls), preflight=down))
    j_ok, _ = runner.submit("ccccccccccc", KIND_PIPELINE, pipeline_target(
        url.format("ccccccccccc"), tcfg, pipeline=fake_pipeline(calls), preflight=lambda c: None))
    assert runner.wait_idle(10)
    assert (j_render.status, j_render.error, j_render.stage, j_render.lane) == \
        (FAILED, "render: render boom", "render", None)
    assert [s["stage"] for s in j_render.stages] == list(PIPELINE_STAGES[:5])
    # Q5: ingest ran with Ollama down; the job fails at the start of the ai lane (resumable)
    assert (j_pre.status, j_pre.error, j_pre.stage) == (FAILED, "ollama preflight: cannot reach Ollama", "preflight")
    assert [s["stage"] for s in j_pre.stages] == ["ingest", "transcript", "analysis"]
    assert (j_ok.status, j_ok.summary) == (DONE, "2/2 Shorts (2 encoded, 0 reused)")
    assert [s["stage"] for s in j_ok.stages] == list(PIPELINE_STAGES)
    # later lanes get the episode id ingest returned
    assert [t for s, t, _ in calls if s == "selection"] == ["aaaaaaaaaaa", "ccccccccccc"]


# --- AC6 stop() with several lanes running ------------------------------------------------------------------

class SpinTarget:
    """Pipeline-like job: quick steps, except ``spin`` = (lane, stage) which loops inside ``run_stage``."""

    def __init__(self, root, name, spin=None):
        self.root, self.name, self.spin = root, name, spin
        self.started = threading.Event()

    def step(self, lane):
        def run(job):
            log.info("mark %s %s", self.name, lane)
            if self.spin is None or self.spin[0] != lane:
                return
            stage = self.spin[1]
            job.stage = stage
            ws = Workspace(Path(self.root), job.episode_id)
            manifest = ws.new_manifest({"kind": "youtube", "uri": "u"})

            def action():
                self.started.set()
                while True:
                    time.sleep(0.01)

            run_stage(ws, manifest, stage, inputs=[], cfg_hash="h", force=False, action=action)
        return run

    def lane_steps(self):
        return [Step(lane, self.step(lane)) for lane in LANES]


def test_stop_interrupts_every_lane(tcfg):
    root = tcfg.workspace.dir
    r = JobRunner()
    r.start()
    a = SpinTarget(root, "a", (RENDER, "render"))
    b = SpinTarget(root, "b", (AI, "selection"))
    d = SpinTarget(root, "d")
    c = SpinTarget(root, "c", (PREPARE, "analysis"))
    ja, _ = r.submit("ea", KIND_PIPELINE, a)
    assert a.started.wait(5)
    jb, _ = r.submit("eb", KIND_PIPELINE, b)
    assert b.started.wait(5)
    jd, _ = r.submit("ed", KIND_PIPELINE, d)
    wait_for(lambda: jd.waiting)
    jc, _ = r.submit("ec", KIND_PIPELINE, c)
    assert c.started.wait(5)
    assert r.running() == {PREPARE: jc, AI: jb, RENDER: ja}
    t0 = time.monotonic()
    r.stop(timeout=10)
    assert time.monotonic() - t0 < 10
    for job, stage in ((ja, "render"), (jb, "selection"), (jc, "analysis")):
        assert (job.status, job.error) == (INTERRUPTED, f"interrupted during {stage}")
        entry = Workspace(Path(root), job.episode_id).load_manifest()["stages"][stage]
        assert (entry["status"], entry["error"]) == (STAGE_FAILED, "interrupted")
    assert (jd.status, jd.error) == (INTERRUPTED, "interrupted while waiting for ai")
    for job, name in ((ja, "a"), (jb, "b"), (jc, "c"), (jd, "d")):
        marks = [line for line in job.logs if " mark " in f" {line}"]
        assert marks and all(f"mark {name} " in line for line in marks), (name, list(job.logs))


# --- AC7 serial mode + config ------------------------------------------------------------------------------

def test_serial_mode_one_job_at_a_time(tcfg):
    r = JobRunner("serial")
    r.start()
    try:
        trace, gate = Trace(), threading.Event()
        ja, _ = r.submit("a", KIND_PIPELINE, LaneTarget("a", trace, gates={RENDER: gate}))
        jb, _ = r.submit("b", KIND_PIPELINE, LaneTarget("b", trace))
        wait_for(lambda: trace.has(RENDER, "a", "start") or trace.has("serial", "a", "start"))
        time.sleep(0.1)
        assert trace.starts("serial") == ["a"] * 3 and jb.status == QUEUED and r.queue_position(jb) == 1
        assert (ja.lane, ja.waiting) == (None, False)
        gate.set()
        assert r.wait_idle(5)
        assert trace.events == [("serial", n, w) for n in "ab" for _ in LANES for w in ("start", "end")]
        assert trace.overlaps == []
        # pipeline job: one run_pipeline call for the six stages, preflight at the job start (W5 before CP8.10)
        seen = []

        def pipeline(url, config, **kw):
            seen.append(sorted(kw))
            return fake_pipeline([])(url, config, **kw)

        order = []
        job, _ = r.submit("abcdefghijk", KIND_PIPELINE, pipeline_target(
            "https://youtu.be/abcdefghijk", tcfg, pipeline=pipeline, preflight=lambda c: order.append("preflight"),
            disk_blocked=lambda: BLOCK_MESSAGE))  # serial ignores the lane-only disk re-check
        assert r.wait_idle(5)
        assert job.status == DONE and [s["stage"] for s in job.stages] == list(PIPELINE_STAGES)
        assert len(seen) == 1 and "stages" not in seen[0] and order == ["preflight"]
    finally:
        r.stop(timeout=5)


def test_serial_preflight_failure_runs_no_stage(tcfg):
    r = JobRunner("serial")
    r.start()
    try:
        def down(c):
            raise PreflightError("down")

        calls = []
        job, _ = r.submit("abcdefghijk", KIND_PIPELINE, pipeline_target(
            "https://youtu.be/abcdefghijk", tcfg, pipeline=fake_pipeline(calls), preflight=down))
        assert r.wait_idle(5)
        assert (job.status, job.error, job.stages, calls) == (FAILED, "ollama preflight: down", [], [])
    finally:
        r.stop(timeout=5)


def test_queue_mode_config_and_app(tcfg):
    assert Config().web.queue_mode == "lanes"
    assert from_dict({"web": {"queue_mode": "serial"}}).web.queue_mode == "serial"
    for bad in ("parallel", "", 1, ["lanes"]):
        with pytest.raises(ConfigError, match="queue_mode"):
            from_dict({"web": {"queue_mode": bad}})
    with pytest.raises(ValueError):
        JobRunner("parallel")
    cfg = replace(tcfg, web=WebConfig(queue_mode="serial"))
    with client(cfg, gated_pipeline([])) as c:
        _login(c)
        assert c.app.state.runner.mode == "serial"
        assert _submit(c, VA).status_code == 202
        assert c.app.state.runner.wait_idle(5)
        job = c.get(f"/api/episodes/{VA}").json()["job"]
        assert (job["status"], job["lane"], job["waiting"]) == ("done", None, False)
    with client(tcfg, gated_pipeline([])) as c:
        assert c.app.state.runner.mode == "lanes"


def test_run_pipeline_stages_argument(tcfg):
    calls = []
    fp = fake_pipeline(calls)
    res = fp("https://youtu.be/abcdefghijk", tcfg, preflight=None, stages=["ingest", "transcript", "analysis"])
    assert [s.stage for s in res.stages] == ["ingest", "transcript", "analysis"]
    assert res.episode_id == "abcdefghijk"
    pre = []
    res = fp("https://youtu.be/abcdefghijk", tcfg, preflight=lambda c: pre.append(1), episode_id="abcdefghijk",
             stages=("selection", "titling"))
    assert [s.stage for s in res.stages] == ["selection", "titling"] and pre == [1]
    assert [t for s, t, _ in calls[3:]] == ["abcdefghijk", "abcdefghijk"]
    for bad in ([], ["render", "ingest"], ["ingest", "ingest"], ["review"], ["nope"]):
        with pytest.raises(PipelineError):
            fp("https://youtu.be/abcdefghijk", tcfg, preflight=None, stages=bad)
    with pytest.raises(PipelineError, match="episode_id is required"):
        fp("https://youtu.be/abcdefghijk", tcfg, preflight=None, stages=["render"])
    assert len(calls) == 5  # nothing ran for the invalid calls


# --- AC8 same artifacts as a serial run (real stages, fake Ollama, real ffmpeg) ---------------------------

def _tree(d: Path) -> dict[str, str]:
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*")) if p.is_file()}


def test_lanes_artifacts_identical_to_serial(lecture, tmp_path):
    from test_pipeline_e2e import SelectionClient, TitlingClient

    video, config_path = lecture
    base = load_config(config_path)
    results = {}
    for mode in ("serial", "lanes"):
        cfg = replace(base, workspace=replace(base.workspace, dir=tmp_path / mode / "work"),
                      render=replace(base.render, output_dir=tmp_path / mode / "output"))
        r = JobRunner(mode)
        r.start()
        try:
            pipe = partial(run_pipeline, deps=StageDeps(selection_client=SelectionClient(),
                                                        titling_client=TitlingClient()))
            job, _ = r.submit("local", KIND_PIPELINE, pipeline_target(
                str(video), cfg, series="Bài giảng", episode="9", pipeline=pipe, preflight=None))
            assert r.wait_idle(120)
        finally:
            r.stop(timeout=5)
        assert job.status == DONE, job.error
        eid = next(p.name for p in (tmp_path / mode / "work").iterdir() if (p / "manifest.json").is_file())
        text = (tmp_path / mode / "work" / eid / "manifest.json").read_text(encoding="utf-8")
        manifest = json.loads(text.replace(str(tmp_path / mode), "<run>"))  # render artifacts: absolute paths
        work = _tree(tmp_path / mode / "work" / eid)
        del work["manifest.json"]  # compared below without its timestamps
        for entry in manifest["stages"].values():
            assert entry.pop("started_at") and entry.pop("finished_at")
        results[mode] = {"eid": eid, "summary": job.summary, "manifest": manifest, "work": work,
                         "output": _tree(tmp_path / mode / "output" / eid)}
    serial, lanes = results["serial"], results["lanes"]
    assert serial["eid"] == lanes["eid"] and serial["summary"] == lanes["summary"]
    assert serial["manifest"] == lanes["manifest"]  # status, inputs, artifacts (sha256), config hash per stage
    assert [e["status"] for e in serial["manifest"]["stages"].values()] == ["done"] * 6
    assert serial["output"].keys() == lanes["output"].keys() and serial["work"].keys() == lanes["work"].keys()
    differ = sorted(k for k in serial["work"] if serial["work"][k] != lanes["work"][k]) + \
        sorted(f"output/{k}" for k in serial["output"] if serial["output"][k] != lanes["output"][k])
    assert differ == [], differ


from test_pipeline_e2e import lecture  # noqa: E402,F401  (fixture)
