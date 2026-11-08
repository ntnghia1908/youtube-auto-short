"""PCX1 AC8: backlog, durable ordinary-error suppression and quota retry/restart with a fake clock."""
import json
import threading
from dataclasses import replace
from datetime import datetime

import pytest

from auto_short.post import codex_text as ct, store
from auto_short.web import jobs
from post_helpers import EID, make_post_episode
from test_post_codex_helpers import Codex, Media, Whisper, seed
from web_helpers import make_app


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("exit_code", [0, 1])
def test_quota_wait_resumes_unfinished_clip_and_survives_restart(tmp_path, monkeypatch, restart, exit_code):
    cfg, path = seed(tmp_path)
    now = [1800000000.0]
    monkeypatch.setattr(ct.time, "time", lambda: now[0])
    calls = []
    waiting = threading.Event()
    runner = jobs.JobRunner(wall=lambda: now[0])
    def process(cmd, **kwargs):
        calls.append(cmd)
        # k01 succeeds, k02 hits its account limit, k02 succeeds on retry.
        return Codex(code=exit_code, output="You've hit your usage limit",
                     log=f'usage limit resets_at: {int(now[0] + 120)}')(cmd, **kwargs) if len(calls) == 2 \
            else Codex()(cmd, **kwargs)
    def rewrite(eid, config, clips, **kw):
        return ct.rewrite_posts(eid, config, clips, media_runner=Media(), whisper=Whisper(), **kw)
    make_app(cfg, runner=runner, post_codex_rewrite=rewrite, codex_runner=process)
    original = runner._requeue_codex
    def requeue(job, exc):
        original(job, exc)
        waiting.set()
    runner._requeue_codex = requeue
    runner.submit(EID, jobs.KIND_POST_CODEX, jobs.PostCodexTarget(cfg, ["k01", "k02"], rewrite=rewrite, runner=process))
    runner.start()
    try:
        assert waiting.wait(5)
        job = runner.latest_post_codex(EID)
        assert job.active and job.codex_wait and job.waiting and job.error is None
        assert job.current_clip == "k02" and job.target.clips == ["k02"]
        assert store.read_posts(path, EID)["posts"][0]["origin"] == "codex"
        assert store.read_posts(path, EID)["posts"][1]["paragraphs"] == ["Bài cũ."]
        assert ct.errors(cfg, EID)["k02"] is None
        assert runner.codex_quota()["retry_at"] == now[0] + 120
        saved = json.loads((cfg.workspace.dir / ".web_queue.json").read_text())
        assert saved["codex_quota"]["retry_at"] == now[0] + 120
        other = threading.Event()
        runner.submit("other", jobs.KIND_RENDER, lambda j: other.set())
        assert other.wait(3) and len(calls) == 2  # quota holds only the Codex lane
        if restart:
            runner.stop()
            runner = jobs.JobRunner(wall=lambda: now[0])
            make_app(cfg, runner=runner, post_codex_rewrite=rewrite, codex_runner=process)
            assert runner.restore() == 1
            assert runner.latest_post_codex(EID).target.clips == ["k02"]
            assert runner.codex_quota()["waiting"]
            runner.start()
        now[0] += 120
        with runner._lock:
            runner._lock.notify_all()
        assert runner.wait_idle(5)
        assert len(calls) == 3 and runner.latest_post_codex(EID).status == jobs.DONE
        assert all(p["origin"] == "codex" for p in store.read_posts(path, EID)["posts"])
    finally:
        runner.stop()


@pytest.mark.parametrize("message,seconds", [
    ("You've hit your usage limit", 1800),
    ("rate limit exceeded; retry after 2 minutes", 120),
    ("usage_limit_reached resets_at: 1800000600", 600),
    ("quota exhausted; try again at 2027-01-15T08:10:00Z", 600),
])
def test_quota_classification_and_unknown_reset_uses_config(tmp_path, message, seconds):
    cfg, _ = seed(tmp_path)
    now = 1800000000.0  # 2027-01-15 08:00 UTC
    exc = ct.quota_wait(message, now=now)
    assert exc is not None
    runner = jobs.JobRunner(wall=lambda: now)
    job, _ = runner.submit(EID, jobs.KIND_POST_CODEX, jobs.PostCodexTarget(cfg, ["k01"]))
    with runner._lock:
        runner._queues[jobs.CODEX].remove(job)
    runner._requeue_codex(job, exc)
    assert runner.codex_quota()["retry_at"] == now + seconds
    assert ct.quota_wait("at capacity server_overloaded", now=now) is None
    date = datetime.fromtimestamp(now + 600)
    for readable in (date.strftime("%b %d, %Y %I:%M %p"),
                     date.strftime("%I:%M %p on %B %d, %Y"), date.strftime("%I:%M %p")):
        assert ct.quota_wait("usage limit; try again at " + readable, now=now).retry_at == now + 600


def test_backlog_runs_all_episodes_skips_normal_errors_until_source_changes(tmp_path):
    cfg, path = seed(tmp_path)
    doc = store.read_posts(path, EID)
    doc["posts"][1]["posted_at"] = "2026-11-08T00:00:00Z"
    store.write(path, doc)
    other = "anotherTest"
    make_post_episode(cfg.workspace.dir, cfg.render.output_dir, episode_id=other)
    other_path = cfg.workspace.dir / other / "posts.json"
    other_doc = store.empty_posts(other)
    for cid in ("k01", "k02"):
        p = dict(doc["posts"][0], clip_id=cid, candidate_id="c00001" if cid == "k01" else "c00002",
                 origin="raw" if cid == "k01" else "manual")
        other_doc["posts"].append(p)
    store.write(other_path, other_doc)
    def rewrite(eid, config, clips, **kw):
        runner = Codex(output="bad") if eid == other else Codex()
        return ct.rewrite_posts(eid, config, clips, runner=runner, media_runner=Media(), whisper=Whisper(),
                                **{k: v for k, v in kw.items() if k != "runner"})
    app = make_app(cfg, post_codex_rewrite=rewrite)
    runner, backlog = app.state.runner, app.state.post_codex_backlog
    assert backlog.scan()[0] == [(other, "k01"), (EID, "k01")]
    runner.start()
    try:
        assert backlog.tick().episode_id == other
        assert runner.wait_idle(5)
        assert backlog.status()["skipped_errors"] == 1
        assert backlog.tick().episode_id == EID  # ordinary failure cannot strand later posts
        assert runner.wait_idle(5)
        assert backlog.scan() == ([], 1) and backlog.tick() is None
        # Restart the scheduler: the persisted attempt, not process memory, suppresses the failed source.
        new_app = make_app(cfg, post_codex_rewrite=rewrite)
        assert new_app.state.post_codex_backlog.scan() == ([], 1)
        clips = other_path.with_name("clips.json")
        changed = json.loads(clips.read_text())
        changed["clips"][0]["head_cut"] = {"words": "dòng 1", "original_start": 0}
        clips.write_text(json.dumps(changed))
        assert backlog.scan() == ([(other, "k01")], 0)
        disabled = jobs.PostCodexBacklog(replace(cfg, post=replace(cfg.post, codex_auto=False)), runner, lambda clips: None)
        assert disabled.tick() is None and not disabled.status()["enabled"]
    finally:
        runner.stop()
