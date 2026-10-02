"""FIX-ollama-wait AC3-AC7: the ai lane waits for the GPU (Ollama) instead of failing; routes accept links / post
compose while Ollama is down; ``gpu`` / ``gpu_wait`` in the API. Fake pipeline / preflight / compose, retry time
injected (no 60 s wait)."""

from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace

import pytest

from auto_short.config import Config, RenderConfig, WebConfig, WorkspaceConfig
from auto_short.pipeline import OllamaUnavailable, PreflightError
from auto_short.selection.client import ChatUnavailable
from auto_short.web.jobs import (AI, DONE, FAILED, INTERRUPTED, KIND_ADD, KIND_PIPELINE, KIND_POST, PREFETCH_LIMIT,
                                 RUNNING, JobRunner, add_short_target, pipeline_target, post_compose_target)

RETRY = 0.05


def wait_for(pred, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.005)


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"))


@pytest.fixture
def runner():
    r = JobRunner(gpu_retry_seconds=RETRY)
    r.start()
    yield r
    r.stop(timeout=5)


class Gpu:
    """Controllable preflight: ``up`` False -> OllamaUnavailable; ``missing`` -> plain PreflightError."""

    def __init__(self, up=False):
        self.up, self.missing, self.calls = up, False, 0

    def __call__(self, cfg):
        self.calls += 1
        if not self.up:
            raise OllamaUnavailable("cannot reach Ollama at http://x")
        if self.missing:
            raise PreflightError("model 'm' is not available")


class FakePipe:
    """``run_pipeline`` stand-in: records (stage, episode) per lane run in ``log``; ``fail`` (stage) makes that
    stage fail once with ``error``; ``hold`` (Event) blocks the selection stage."""

    def __init__(self, gpu: Gpu | None = None):
        self.gpu, self.log, self.fail, self.hold, self.lock = gpu, [], None, None, threading.Lock()

    def __call__(self, url, config, *, series=None, episode=None, preflight=None, on_stage=None, stages=None,
                 episode_id=None, **kw):
        eid = episode_id or url.rsplit("/", 1)[-1]
        stages = stages or ("ingest", "transcript", "analysis", "selection", "titling", "render")
        if preflight is not None:
            preflight(config)
        for st in stages:
            with self.lock:
                self.log.append((st, eid))
            if st == "selection" and self.hold is not None:
                assert self.hold.wait(10)
            if self.fail == st:
                self.fail = None
                return SimpleNamespace(ok=False, failed_stage=st, error="boom", episode_id=eid, stages=[])
            if on_stage is not None:
                on_stage(SimpleNamespace(stage=st, ran=True, seconds=0.0, result=None))
        return SimpleNamespace(ok=True, failed_stage=None, error=None, episode_id=eid, rendered=1, clips=1,
                               stages=[])

    def ran(self, stage):
        return [e for s, e in self.log if s == stage]


def submit(runner, tcfg, eid, pipe, gpu):
    return runner.submit(eid, KIND_PIPELINE, pipeline_target(f"https://youtu.be/{eid}", tcfg, pipeline=pipe,
                                                             preflight=gpu))[0]


def waiting_for_gpu(job):
    return job.status == RUNNING and job.waiting and job.lane == AI and job.gpu_wait


# --- AC4 -----------------------------------------------------------------------------------------------------

def test_pipeline_waits_for_gpu_then_continues(runner, tcfg, caplog):
    caplog.set_level(logging.INFO, logger="auto_short")
    gpu, pipe = Gpu(up=False), None
    pipe = FakePipe()
    job = submit(runner, tcfg, "aaaaaaaaaaa", pipe, gpu)
    wait_for(lambda: waiting_for_gpu(job))
    assert job.status == RUNNING and job.error is None
    assert [s for s, _ in pipe.log] == ["ingest", "transcript", "analysis"]  # prepare done, no AI stage
    st = runner.gpu_status()
    assert st["state"] == "down" and st["since"] and st["next_check"] and "cannot reach Ollama" in st["error"]
    assert job.to_dict()["gpu_wait"] is True
    time.sleep(RETRY * 4)  # re-checked several times, still waiting (not failed)
    assert gpu.calls >= 2 and job.status == RUNNING
    gpu.up = True  # GPU is back: no re-submit needed
    assert runner.wait_idle(10) and job.status == DONE
    assert [s for s, _ in pipe.log] == ["ingest", "transcript", "analysis", "selection", "titling", "render"]
    st = runner.gpu_status()
    assert st == {"state": "ok", "since": None, "error": None, "next_check": None}
    assert job.gpu_wait is False
    assert "web: ollama is back" in caplog.text


def test_fifo_order_after_gpu_returns(runner, tcfg):
    gpu, pipe = Gpu(up=False), FakePipe()
    jobs = [submit(runner, tcfg, e, pipe, gpu) for e in ("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc")]
    wait_for(lambda: all(waiting_for_gpu(j) for j in jobs))
    assert pipe.ran("selection") == []
    gpu.up = True
    assert runner.wait_idle(10)
    assert pipe.ran("selection") == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]
    assert all(j.status == DONE for j in jobs)


def test_stage_failure_while_ollama_dies_waits_then_reruns_lane(runner, tcfg):
    class Scripted(Gpu):  # preflight before the stage passes, the re-check after the stage failed does not
        def __init__(self, script):
            super().__init__(up=True)
            self.script = list(script)

        def __call__(self, cfg):
            if self.script:
                self.calls += 1
                if not self.script.pop(0):
                    raise OllamaUnavailable("cannot reach Ollama at http://x")
                return
            return super().__call__(cfg)

    gpu, pipe = Scripted([True, False]), FakePipe()
    pipe.fail = "selection"
    job = submit(runner, tcfg, "aaaaaaaaaaa", pipe, gpu)
    wait_for(lambda: waiting_for_gpu(job))
    assert job.status == RUNNING and job.error is None and runner.gpu_status()["state"] == "down"
    wait_for(lambda: runner.wait_idle(0.01) or job.status == DONE)  # script exhausted: Ollama is up again
    assert job.status == DONE
    assert pipe.ran("selection") == ["aaaaaaaaaaa", "aaaaaaaaaaa"]  # the lane is redone from its first stage


def test_real_stage_failure_with_ollama_up_fails(runner, tcfg):
    gpu, pipe = Gpu(up=True), FakePipe()
    pipe.fail = "selection"
    job = submit(runner, tcfg, "aaaaaaaaaaa", pipe, gpu)
    assert runner.wait_idle(10)
    assert job.status == FAILED and job.error == "selection: boom" and runner.gpu_status()["state"] == "ok"


def test_missing_model_fails_without_waiting(runner, tcfg):
    gpu, pipe = Gpu(up=True), FakePipe()
    gpu.missing = True
    job = submit(runner, tcfg, "aaaaaaaaaaa", pipe, gpu)
    assert runner.wait_idle(10)
    assert job.status == FAILED and job.error.startswith("ollama preflight: model 'm'")
    assert runner.gpu_status()["state"] == "ok"


def test_missing_model_after_outage_clears_gpu_down(runner, tcfg):
    gpu, pipe = Gpu(up=False), FakePipe()
    job = submit(runner, tcfg, "aaaaaaaaaaa", pipe, gpu)
    wait_for(lambda: waiting_for_gpu(job))
    gpu.up, gpu.missing = True, True  # Ollama answers again, but the model is gone: a config error, not an outage
    assert runner.wait_idle(10)
    assert job.status == FAILED and runner.gpu_status()["state"] == "ok"


def test_post_jobs_wait_like_pipeline(runner, tcfg):
    gpu, calls = Gpu(up=False), []

    def compose(episode_id, config, clips, lock=None, before_ai=None):
        before_ai()  # F1: the preflight now runs lazily, before the first AI call (all Shorts here need AI)
        calls.append((episode_id, clips))
        return SimpleNamespace(clip_ids=["k01"], ai=1, raw=0, errors={})

    job, _ = runner.submit("ep", KIND_POST, post_compose_target(tcfg, ["k01"], compose=compose, preflight=gpu))
    wait_for(lambda: waiting_for_gpu(job))
    assert calls == [] and job.status == RUNNING
    # a new request while it waits is merged into the waiting job (not lost, not a second pass)
    again, created = runner.submit("ep", KIND_POST, post_compose_target(tcfg, ["k02"], compose=compose, preflight=gpu))
    assert again is job and not created and job.again is False
    gpu.up = True
    assert runner.wait_idle(10) and job.status == DONE
    assert calls == [("ep", ["k01", "k02"])]


def test_post_compose_outage_midway_waits_and_reruns(runner, tcfg):
    state = {"n": 0}
    gpu = Gpu(up=True)

    def compose(episode_id, config, clips, lock=None, before_ai=None):
        before_ai()
        state["n"] += 1
        if state["n"] == 1:
            gpu.up = False  # Ollama goes away during the compose call
            raise ChatUnavailable("cannot reach Ollama")
        return SimpleNamespace(clip_ids=["k01"], ai=1, raw=0, errors={})

    job, _ = runner.submit("ep", KIND_POST, post_compose_target(tcfg, ["k01"], compose=compose, preflight=gpu))
    wait_for(lambda: waiting_for_gpu(job))
    assert job.error is None
    gpu.up = True
    assert runner.wait_idle(10) and job.status == DONE and state["n"] == 2


def test_post_compose_unavailable_but_preflight_ok_fails(runner, tcfg):
    def compose(episode_id, config, clips, lock=None, before_ai=None):
        before_ai()
        raise ChatUnavailable("cannot reach Ollama")

    job, _ = runner.submit("ep", KIND_POST, post_compose_target(tcfg, ["k01"], compose=compose, preflight=Gpu(up=True)))
    assert runner.wait_idle(10) and job.status == FAILED and "cannot reach Ollama" in job.error


def test_add_job_does_not_wait_while_gpu_down(runner, tcfg):
    gpu, pipe = Gpu(up=False), FakePipe()
    waiting = submit(runner, tcfg, "aaaaaaaaaaa", pipe, gpu)
    wait_for(lambda: waiting_for_gpu(waiting))
    renders = []

    def render(eid, config):
        renders.append(eid)
        return SimpleNamespace(ran=True, rendered=1, clips=1, encoded=1, reused=0)

    add, _ = runner.submit("addep", KIND_ADD, add_short_target(tcfg, "m01", render=render, preflight=gpu,
                                                               titler=lambda *a: pytest.fail("no AI while down")))
    wait_for(lambda: add.status == FAILED)  # untitled + rendered + failed "gõ tiêu đề tay" (CP9), no waiting
    assert renders == ["addep"] and "gõ tiêu đề tay" in add.error and "ollama preflight" in add.error
    assert waiting_for_gpu(waiting)  # the pipeline job still waits at the head
    gpu.up = True
    assert runner.wait_idle(10) and waiting.status == DONE


# --- AC5 -----------------------------------------------------------------------------------------------------

def test_stop_while_waiting_interrupts_without_waiting_retry_time(tcfg):
    runner = JobRunner(gpu_retry_seconds=60.0)
    runner.start()
    gpu, pipe = Gpu(up=False), FakePipe()
    job = submit(runner, tcfg, "aaaaaaaaaaa", pipe, gpu)
    wait_for(lambda: waiting_for_gpu(job))
    t0 = time.monotonic()
    runner.stop(timeout=30)
    assert time.monotonic() - t0 < 5
    assert job.status == INTERRUPTED and job.error == "interrupted while waiting for GPU" and not job.waiting


def test_stop_does_not_run_post_followup(tcfg):
    runner = JobRunner(gpu_retry_seconds=60.0)
    runner.start()
    gpu, composed = Gpu(up=False), []
    job, _ = runner.submit("ep", KIND_POST, post_compose_target(tcfg, ["k01"], compose=lambda *a, before_ai, **k: (before_ai(), composed.append(1)),
                                                                preflight=gpu))
    wait_for(lambda: waiting_for_gpu(job))
    job.again = True
    runner.stop(timeout=30)
    assert job.status == INTERRUPTED and composed == [] and runner.jobs() == [job]


def test_serial_mode_does_not_wait(tcfg):
    runner = JobRunner("serial", gpu_retry_seconds=RETRY)
    runner.start()
    try:
        gpu, pipe = Gpu(up=False), FakePipe()
        job = submit(runner, tcfg, "aaaaaaaaaaa", pipe, gpu)
        assert runner.wait_idle(10)
        assert job.status == FAILED and job.error == "ollama preflight: cannot reach Ollama at http://x"
        assert pipe.log == [] and runner.gpu_status()["state"] == "ok"
    finally:
        runner.stop(timeout=5)


# --- AC6 -----------------------------------------------------------------------------------------------------

def test_prefetch_limit_lifted_while_down_and_reapplied_after(runner, tcfg):
    gpu, pipe = Gpu(up=False), FakePipe()
    pipe.hold = threading.Event()
    jobs = [submit(runner, tcfg, e, pipe, gpu) for e in ("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd")]
    assert PREFETCH_LIMIT == 2
    wait_for(lambda: all(waiting_for_gpu(j) for j in jobs))  # all 4 prepared although only 2 may wait normally
    assert sorted(pipe.ran("analysis")) == sorted(j.episode_id for j in jobs)
    gpu.up = True  # the first job now runs selection (held by the event) and the ai queue holds 3 prepared jobs
    wait_for(lambda: pipe.ran("selection") == ["aaaaaaaaaaa"])
    late = submit(runner, tcfg, "eeeeeeeeeee", pipe, gpu)
    time.sleep(0.3)
    assert ("ingest", "eeeeeeeeeee") not in pipe.log  # limit 2 applies again: prepare does not start the new job
    pipe.hold.set()
    assert runner.wait_idle(10)
    assert all(j.status == DONE for j in [*jobs, late])


# --- AC3 / AC7: routes + API ---------------------------------------------------------------------------------

@pytest.fixture
def web(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from auto_short.web import app as app_mod
    from web_helpers import fake_pipeline

    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 web=WebConfig(session_days=30))
    gpu = Gpu(up=False)
    runner = JobRunner(gpu_retry_seconds=RETRY)
    monkeypatch.setattr(app_mod, "LOGIN_DELAY", 0.01)
    lister = lambda url, config: {"id": "PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp", "title": "T",
                                  "entries": [{"id": "aaaaaaaaaa1", "title": "Kinh tập 1", "duration": 3500.0}]}  # noqa: E731
    app = app_mod.create_app(cfg, "pw", runner=runner, preflight=gpu, post_preflight=gpu,
                             pipeline=fake_pipeline([]), playlist_lister=lister)
    with TestClient(app, follow_redirects=False) as c:
        assert c.post("/login", data={"password": "pw"}).status_code == 303
        yield SimpleNamespace(c=c, gpu=gpu, runner=runner, cfg=cfg)


def test_submit_202_and_gpu_field_while_down(web):
    r = web.c.post("/api/episodes", json={"url": "https://youtu.be/tHtxw6ykUmM", "kinds": ["short"]})
    assert r.status_code == 202 and r.json()["job"]["kind"] == "pipeline"  # no 503 while Ollama is down
    job = web.runner.latest("tHtxw6ykUmM")
    wait_for(lambda: waiting_for_gpu(job))
    lst = web.c.get("/api/episodes").json()
    assert lst["gpu"]["state"] == "down" and lst["gpu"]["since"] and lst["gpu"]["next_check"]
    item = next(e for e in lst["episodes"] if e["id"] == "tHtxw6ykUmM")
    assert item["job"]["gpu_wait"] is True and item["job"]["waiting"] is True
    ep = web.c.get("/api/episodes/tHtxw6ykUmM").json()
    assert ep["gpu"]["state"] == "down" and ep["job"]["gpu_wait"] is True
    web.gpu.up = True
    assert web.runner.wait_idle(10) and job.status == DONE
    assert web.c.get("/api/episodes").json()["gpu"] == {"state": "ok", "since": None, "error": None,
                                                        "next_check": None}
    assert web.c.get("/api/episodes/tHtxw6ykUmM").json()["gpu"]["state"] == "ok"


def test_playlist_view_has_gpu(web):
    pl = "PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp"
    r = web.c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={pl}"})
    assert r.status_code == 201
    assert web.c.get(f"/api/playlists/{pl}").json()["gpu"]["state"] == "ok"


def test_posts_compose_202_while_down(web, tmp_path):
    from post_helpers import make_post_episode
    make_post_episode(web.cfg.workspace.dir, web.cfg.render.output_dir)
    r = web.c.post("/api/episodes/post8TestEp1/posts", json={"clips": ["k01"]})
    assert r.status_code == 202 and r.json()["job"]["kind"] == "post"
    job = web.runner.latest_post("post8TestEp1")
    wait_for(lambda: waiting_for_gpu(job))
    assert web.c.get("/api/episodes/post8TestEp1").json()["post_job"]["gpu_wait"] is True


# --- FIX-post-doc-no-gpu: lazy preflight, a fresh post job does not wait while the GPU is down --------------------

def fake_compose(calls, need_ai):
    """compose_posts stand-in: Shorts in ``need_ai`` take the AI path (``before_ai`` once, before the first), the
    others come from the document (written to ``calls`` as ('doc', clip))."""
    done_doc: set[str] = set()

    def compose(episode_id, config, clips, lock=None, before_ai=None):
        started = False
        for cid in clips:
            if cid in need_ai:
                if not started and before_ai is not None:
                    before_ai()
                started = True
                calls.append(("ai", cid))
            else:
                done_doc.add(cid)
                calls.append(("doc", cid))
        return SimpleNamespace(clip_ids=list(clips), ai=len(need_ai & set(clips)), raw=0, doc=len(done_doc), errors={})
    return compose


def test_post_all_doc_done_while_gpu_down_without_preflight(runner, tcfg):  # AC1
    gpu, calls = Gpu(up=False), []
    # a pipeline job holds the GPU wait so that gpu_down is set
    waiting = submit(runner, tcfg, "aaaaaaaaaaa", FakePipe(), gpu)
    wait_for(lambda: waiting_for_gpu(waiting))
    own = Gpu(up=False)  # the post job's own preflight: must never be called
    job, _ = runner.submit("ep", KIND_POST, post_compose_target(tcfg, ["k01", "k02"], compose=fake_compose(calls, set()),
                                                                preflight=own))
    wait_for(lambda: job.status == DONE)
    assert calls == [("doc", "k01"), ("doc", "k02")] and job.gpu_wait is False
    assert own.calls == 0
    assert waiting_for_gpu(waiting)
    gpu.up = True
    assert runner.wait_idle(10)


def test_post_doc_then_ai_waits_at_first_ai_short_and_resumes(runner, tcfg):  # AC2
    gpu, calls = Gpu(up=False), []
    waiting = submit(runner, tcfg, "aaaaaaaaaaa", FakePipe(), gpu)
    wait_for(lambda: waiting_for_gpu(waiting))
    job, _ = runner.submit("ep", KIND_POST, post_compose_target(tcfg, ["k01", "k02", "k03"],
                                                                compose=fake_compose(calls, {"k02", "k03"}),
                                                                preflight=gpu))
    wait_for(lambda: waiting_for_gpu(job))
    assert calls == [("doc", "k01")] and job.error is None
    gpu.up = True
    assert runner.wait_idle(10) and job.status == DONE and waiting.status == DONE
    assert calls == [("doc", "k01"), ("doc", "k01"), ("ai", "k02"), ("ai", "k03")]  # no AI for the doc Short


def test_requeued_post_job_not_taken_again_until_next_check(tcfg):  # AC3
    runner = JobRunner(gpu_retry_seconds=0.4)
    runner.start()
    try:
        gpu, calls = Gpu(up=False), []
        job, _ = runner.submit("ep", KIND_POST, post_compose_target(tcfg, ["k01"], compose=fake_compose(calls, {"k01"}),
                                                                    preflight=gpu))
        wait_for(lambda: waiting_for_gpu(job))
        n = gpu.calls
        assert n == 1
        time.sleep(0.25)  # well inside the retry window: no busy loop
        assert gpu.calls == n
        gpu.up = True
        assert runner.wait_idle(10) and job.status == DONE
    finally:
        runner.stop(timeout=5)


def test_post_needing_ai_preflights_before_first_ai_when_gpu_ok(runner, tcfg):  # AC4
    gpu, calls = Gpu(up=True), []
    job, _ = runner.submit("ep", KIND_POST, post_compose_target(tcfg, ["k01", "k02"],
                                                                compose=fake_compose(calls, {"k01", "k02"}),
                                                                preflight=gpu))
    assert runner.wait_idle(10) and job.status == DONE
    assert gpu.calls == 1 and calls == [("ai", "k01"), ("ai", "k02")]


def test_serial_post_lazy_preflight(tcfg):  # F4
    runner = JobRunner("serial", gpu_retry_seconds=RETRY)
    runner.start()
    try:
        gpu, calls = Gpu(up=False), []
        ok, _ = runner.submit("ep", KIND_POST, post_compose_target(tcfg, ["k01"], compose=fake_compose(calls, set()),
                                                                   preflight=gpu))
        assert runner.wait_idle(10) and ok.status == DONE and gpu.calls == 0
        bad, _ = runner.submit("ep", KIND_POST, post_compose_target(tcfg, ["k02"],
                                                                    compose=fake_compose(calls, {"k02"}),
                                                                    preflight=gpu))
        assert runner.wait_idle(10) and bad.status == FAILED and "ollama preflight" in bad.error
    finally:
        runner.stop(timeout=5)
