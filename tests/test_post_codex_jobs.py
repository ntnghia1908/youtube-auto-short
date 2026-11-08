"""PCX1 AC4: queue / persistence / automatic scheduling, without TestClient or sockets."""
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

from auto_short.post import codex_text as ct, stage, store
from auto_short.web import jobs
from post_helpers import EID
from test_post_codex_helpers import seed
from web_helpers import make_app


@pytest.mark.parametrize("origin,posted,auto,expected", [
    ("ai", False, True, ["k01"]), ("raw", False, True, ["k01"]),
    ("ai", True, True, []), ("doc", False, True, []), ("manual", False, True, []),
    ("codex", False, True, []), ("ai", False, False, []),
])
def test_compose_finished_schedules_only_eligible_result_clips(tmp_path, origin, posted, auto, expected):
    cfg, path = seed(tmp_path)
    cfg = replace(cfg, post=replace(cfg.post, codex_auto=auto))
    doc = store.read_posts(path, EID)
    doc["posts"][0].update(origin=origin, posted_at="2026-11-08T00:00:00Z" if posted else None)
    store.write(path, doc)
    app = make_app(cfg, post_preflight=lambda c: None, post_codex_rewrite=lambda *a, **kw: ct.Summary([]))
    runner = app.state.runner
    job = SimpleNamespace(id="compose", episode_id=EID, kind=jobs.KIND_POST,
                          target=SimpleNamespace(result=stage.ComposeSummary(["k01"])))
    runner.on_finished(job)
    codex_job = runner.latest_post_codex(EID)
    assert (codex_job.target.clips if codex_job else []) == expected
    assert not runner.latest_post(EID)  # a compose-finished event must never enqueue compose recursively


@pytest.mark.parametrize("mode", [jobs.MODE_LANES, jobs.MODE_SERIAL])
def test_codex_lane_is_serial_but_does_not_block_other_work_and_merges_pending(tmp_path, mode):
    cfg, _ = seed(tmp_path)
    gate, started = threading.Event(), threading.Event()
    other, pending = threading.Event(), threading.Event()
    calls = []
    def rewrite(eid, config, clips, **kwargs):
        calls.append((eid, list(clips), kwargs["include_posted"]))
        if len(calls) == 1:
            started.set()
            assert gate.wait(5)
        else:
            pending.set()
        return ct.Summary(list(clips), rewritten=list(clips))
    runner = jobs.JobRunner(mode)
    state = tmp_path / "queue.json"
    runner.configure_persistence(state, lambda kind, eid, spec, clips: jobs.PostCodexTarget(cfg, spec["clips"], rewrite=rewrite))
    target = jobs.PostCodexTarget(cfg, ["k01"], rewrite=rewrite)
    first, _ = runner.submit(EID, jobs.KIND_POST_CODEX, target)
    # Requests queued before start merge, including per-clip posted confirmation.
    same, created = runner.submit(EID, jobs.KIND_POST_CODEX,
                                  jobs.PostCodexTarget(cfg, ["k02"], include_posted=True, rewrite=rewrite))
    assert same is first and not created and target.clips == ["k01", "k02"]
    restored = jobs.JobRunner(mode)
    restored.configure_persistence(state, lambda kind, eid, spec, clips: jobs.PostCodexTarget(cfg, spec["clips"], rewrite=rewrite))
    assert restored.restore() == 1 and restored.latest_post_codex(EID).target.clips == ["k01", "k02"]
    runner.start()
    try:
        assert started.wait(3)
        runner.submit("other", jobs.KIND_RENDER, lambda job: other.set())
        assert other.wait(3)  # even serial mode has its own separate Codex worker
        runner.submit(EID, jobs.KIND_POST_CODEX, jobs.PostCodexTarget(cfg, ["k01"], rewrite=rewrite))
        assert not pending.is_set()  # the follow-up cannot run alongside the active Codex call
        gate.set()
        assert runner.wait_idle(5)
        assert calls == [(EID, ["k01"], False), (EID, ["k02"], True), (EID, ["k01"], False)]
        assert runner.latest_post_codex(EID).status == jobs.DONE
    finally:
        gate.set()
        runner.stop()
