import threading
import time
from pathlib import Path

from auto_short.pipeline import PreflightError
from auto_short.web.jobs import DONE, FAILED, INTERRUPTED, KIND_PIPELINE, JobFailed, JobRunner, pipeline_target
from auto_short.workspace import FAILED as STAGE_FAILED, StageError, Workspace, run_stage

from web_helpers import fake_pipeline


def _runner():
    r = JobRunner()
    r.start()
    return r


def test_fifo_one_at_a_time_and_duplicates():
    r = _runner()
    gate, started, order, running = threading.Event(), threading.Event(), [], []
    try:
        def target(name):
            def t(job):
                started.set()
                running.append(name)
                assert len(running) == 1  # never two jobs at once
                if name == "a":
                    gate.wait(5)
                order.append(name)
                running.remove(name)
            return t

        a, created_a = r.submit("ep1", KIND_PIPELINE, target("a"))
        assert started.wait(5)
        b, created_b = r.submit("ep2", KIND_PIPELINE, target("b"))
        dup, created_dup = r.submit("ep1", KIND_PIPELINE, target("x"))
        assert created_a and created_b and not created_dup and dup is a
        assert r.queue_position(b) == 1
        gate.set()
        assert r.wait_idle(5)
        assert order == ["a", "b"] and a.status == b.status == DONE
        assert a.started_at and a.finished_at
        c, created_c = r.submit("ep1", KIND_PIPELINE, target("c"))  # finished -> new job accepted
        assert created_c and c is not a and r.latest("ep1") is c
        assert r.wait_idle(5)
    finally:
        r.stop()


def test_failures_and_logs():
    import logging
    r = _runner()
    try:
        def fails(job):
            logging.getLogger("auto_short").info("step one")
            raise JobFailed("nope")

        def crashes(job):
            raise RuntimeError("bug")

        j1, _ = r.submit("a", KIND_PIPELINE, fails)
        j2, _ = r.submit("b", KIND_PIPELINE, crashes)
        assert r.wait_idle(5)
        assert (j1.status, j1.error) == (FAILED, "nope")
        assert any(line.endswith("step one") for line in j1.logs)
        assert any("failed" in line for line in j1.logs)
        assert j2.status == FAILED and "RuntimeError: bug" in j2.error
        assert "logs" in j1.to_dict() and "logs" not in j1.to_dict(logs=False)
    finally:
        r.stop()


def test_log_ring_buffer_is_bounded():
    import logging
    r = _runner()
    try:
        def noisy(job):
            for i in range(500):
                logging.getLogger("auto_short").info("line %d", i)

        j, _ = r.submit("a", KIND_PIPELINE, noisy)
        assert r.wait_idle(5)
        assert len(j.logs) == 200 and j.logs[-1].endswith("done in " + j.logs[-1].split("done in ")[-1])
    finally:
        r.stop()


def test_stop_interrupts_running_stage(cfg):
    """Server shutdown -> the running stage records failed / interrupted (CP2), the job is interrupted."""
    ws = Workspace(Path(cfg.workspace.dir), "ep")
    started = threading.Event()

    def target(job):
        manifest = ws.new_manifest({"kind": "youtube", "uri": "u"})
        job.stage = "analysis"

        def action():
            started.set()
            while True:
                time.sleep(0.01)

        try:
            run_stage(ws, manifest, "analysis", inputs=[], cfg_hash="h", force=False, action=action)
        except StageError:  # pragma: no cover
            raise

    r = _runner()
    job, _ = r.submit("ep", KIND_PIPELINE, target)
    assert started.wait(5)
    r.stop(timeout=5)
    assert job.status == INTERRUPTED and job.error == "interrupted during analysis"
    entry = ws.load_manifest()["stages"]["analysis"]
    assert entry["status"] == STAGE_FAILED and entry["error"] == "interrupted"


def test_pipeline_target_success_and_failure(cfg):
    calls = []
    job = type("J", (), {"stage": None, "stages": [], "summary": None})()
    pre = []
    pipeline_target("https://youtu.be/abcdefghijk", cfg, series="S", episode="4",
                    pipeline=fake_pipeline(calls), preflight=lambda c: pre.append(c))(job)
    assert pre == [cfg] and job.summary == "2/2 Shorts (2 encoded, 0 reused)" and job.stage is None
    assert [s["stage"] for s in job.stages] == ["ingest", "transcript", "analysis", "selection", "titling", "render"]
    assert job.stages[2]["ran"] is False
    titling = next(kw for stage, _, kw in calls if stage == "titling")
    assert titling["series"] == "S" and titling["episode"] == "4"

    job = type("J", (), {"stage": None, "stages": [], "summary": None})()
    try:
        pipeline_target("https://youtu.be/abcdefghijk", cfg, pipeline=fake_pipeline([], fail_stage="transcript"),
                        preflight=None)(job)
    except JobFailed as exc:
        assert str(exc) == "transcript: transcript boom" and job.stage == "transcript"
    else:  # pragma: no cover
        raise AssertionError("expected JobFailed")

    def bad_preflight(c):
        raise PreflightError("cannot reach Ollama")

    job = type("J", (), {"stage": None, "stages": [], "summary": None})()
    try:
        pipeline_target("https://youtu.be/abcdefghijk", cfg, pipeline=fake_pipeline([]),
                        preflight=bad_preflight)(job)
    except JobFailed as exc:
        assert str(exc) == "ollama preflight: cannot reach Ollama" and job.stage == "preflight"
    else:  # pragma: no cover
        raise AssertionError("expected JobFailed")
