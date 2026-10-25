"""SRC3: endpoint/runner integration without HTTP sockets or real services."""
import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from auto_short.config import Config, RenderConfig, StoreConfig, WebConfig, WorkspaceConfig
from auto_short.hashing import sha256_file
from auto_short.ingest.youtube import Download, YoutubeBlocked
from auto_short.review import archive_source, list_titles, reject_clip
from auto_short.web.app import KIND_RESTORE_SOURCE, RestoreSourceTarget
from auto_short.web.jobs import JobRunner
from auto_short.web.routes.episode_edit import AddIn, CutIn, TitleIn

from cp9_helpers import EID, make_cp9_episode
from test_restore_source_cp837 import app_for, body, endpoint, snapshot
from web_helpers import write_episode

KT = EID + ".kt"
TITLE = "Tâm thiện thì tướng mạo cũng từ bi"


@pytest.fixture(params=["lanes", "serial"])
def cfg(tmp_path, request):
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"), web=WebConfig(queue_mode=request.param))


def episode(cfg, eid=EID):
    ws = make_cp9_episode(cfg.workspace.dir, episode_id=eid)
    data = (ws.dir / "source.mp4").read_bytes()
    # Supply the current rendered Shorts while keeping CP9's coherent caption/selection artifacts.
    write_episode(cfg, eid)
    manifest = ws.load_manifest()
    manifest["source"].update(path="source.mp4", sha256=sha256_file(ws.dir / "source.mp4"), size=len(data))
    ws.save_manifest(manifest)
    archive_source(eid, cfg)
    return ws, data


def fake_download(data, calls, *, fail=False):
    def fetch(uri, dest, ingest):
        calls.append("restore")
        if fail:
            data_out = b"different encoding without a valid Short reference"
        else:
            data_out = data
        path = dest / "source.mp4"
        path.write_bytes(data_out)
        return Download(path, {})
    return fetch


def renderer(calls):
    def render(eid, cfg):
        assert not (Path(cfg.workspace.dir) / eid / "archive.json").exists()
        calls.append(("render", eid))
        return SimpleNamespace(ran=True, rendered=3, clips=3, encoded=1, reused=2)
    return render


def run(app):
    runner = app.state.runner
    runner.start()
    try:
        assert runner.wait_idle(8)
    finally:
        runner.stop()


def request(app, action):
    if action == "title":
        return endpoint(app, "api_title")(EID, "k01", TitleIn(set=TITLE))
    if action == "restore":
        return endpoint(app, "api_short_restore")(EID, "k01")
    if action == "cut":
        return endpoint(app, "api_cut")(EID, "k01", CutIn(start_segment="s00002", end_segment="s00010"))
    if action == "reset_cut":
        return endpoint(app, "api_cut")(EID, "k01", CutIn(reset=True))
    if action == "add":
        return endpoint(app, "api_add_short")(EID, AddIn(candidate_id="c00005"))
    return endpoint(app, "api_add_short")(EID, AddIn(start_segment="s00050", end_segment="s00058"))


@pytest.mark.parametrize("action", ["title", "restore", "cut", "reset_cut", "add", "add_range"])
def test_archived_edits_restore_then_apply(cfg, action):
    ws, data = episode(cfg)
    if action == "restore":
        reject_clip(EID, cfg, "k01")
    calls = []

    def titler(eid, config, clip):
        calls.append(("title_added", eid, clip))
        return SimpleNamespace(title="Tiêu đề AI", error=None)

    app = app_for(cfg, restore_downloader=fake_download(data, calls), render=renderer(calls), titler=titler)
    review = (ws.dir / "review.json").read_bytes() if (ws.dir / "review.json").exists() else None
    response = request(app, action)
    assert response.status_code == 202
    assert body(response)["queued"] == "restore" and body(response)["job"]["kind"] == KIND_RESTORE_SOURCE
    assert ((ws.dir / "review.json").read_bytes() if (ws.dir / "review.json").exists() else None) == review
    job, = app.state.runner.jobs()
    if cfg.web.queue_mode == "lanes":
        assert [s.lane for s in job.steps] == ["prepare", "ai", "render"]
    run(app)
    assert job.status == "done", job.error
    assert calls[0] == "restore" and calls[-1] == ("render", EID)
    assert not (ws.dir / "archive.json").exists()
    if action == "title":
        assert list_titles(EID, cfg)["clips"][0]["title"] == TITLE
    elif action == "restore":
        assert not list_titles(EID, cfg)["clips"][0]["rejected"]
    elif action == "cut":
        assert json.loads((ws.dir / "review.json").read_text())["cuts"][0]["clip_id"] == "k01"
    elif action.startswith("add"):
        assert calls[1] == ("title_added", EID, "m01")
        assert json.loads((ws.dir / "review.json").read_text())["added"][0]["clip_id"] == "m01"


def test_two_edits_share_restore_and_keep_order(cfg, monkeypatch):
    from auto_short.web.routes import episode_edit
    ws, data = episode(cfg)
    calls, applied = [], []
    real = episode_edit.set_title

    def set_title(eid, config, clip, text):
        applied.append(text)
        return real(eid, config, clip, text)

    monkeypatch.setattr(episode_edit, "set_title", set_title)
    app = app_for(cfg, restore_downloader=fake_download(data, calls), render=renderer(calls))
    first = request(app, "title")
    second = endpoint(app, "api_title")(EID, "k01", TitleIn(set="Tâm từ bi đem lại an lạc"))
    assert second.status_code == 202 and body(first)["job"]["id"] == body(second)["job"]["id"]
    assert len(app.state.runner.jobs()) == 1
    run(app)
    assert calls.count("restore") == 1
    assert applied == [TITLE, "Tâm từ bi đem lại an lạc"]
    assert list_titles(EID, cfg)["clips"][0]["title"] == applied[-1]


def test_arriving_edit_during_download_shares_job(cfg):
    ws, data = episode(cfg)
    started, release = threading.Event(), threading.Event()
    calls = []

    def fetch(*args):
        started.set()
        assert release.wait(5)
        return fake_download(data, calls)(*args)

    app = app_for(cfg, restore_downloader=fetch, render=renderer(calls))
    first = request(app, "title")
    runner = app.state.runner
    runner.start()
    try:
        assert started.wait(3)
        second = endpoint(app, "api_title")(EID, "k02", TitleIn(set=TITLE))
        assert second.status_code == 202 and body(first)["job"]["id"] == body(second)["job"]["id"]
        release.set()
        assert runner.wait_idle(8)
        assert runner.jobs()[0].status == "done"
        assert [c["title"] for c in list_titles(EID, cfg)["clips"]] == [TITLE, TITLE]
    finally:
        release.set()
        runner.stop()


def test_restore_failure_discards_edits(cfg):
    ws, data = episode(cfg)
    calls = []
    app = app_for(cfg, restore_downloader=fake_download(data, calls, fail=True), render=renderer(calls))
    before = snapshot(ws.dir)
    assert request(app, "title").status_code == 202
    assert request(app, "restore").status_code == 202
    run(app)
    job, = app.state.runner.jobs()
    assert job.status == "failed" and "khôi phục nguồn:" in job.error
    assert calls == ["restore"] and snapshot(ws.dir) == before


@pytest.mark.parametrize("action, payload", [
    ("api_title", TitleIn(set="")), ("api_title", TitleIn(alternative=99)),
    ("api_cut", CutIn(start_segment="bad", end_segment="s00010")),
    ("api_add_short", AddIn(candidate_id="missing")),
    ("api_add_short", AddIn(start_segment="s00001", end_segment="s00001")),
])
def test_invalid_edits_are_rejected_before_restore(cfg, action, payload):
    ws, data = episode(cfg)
    app = app_for(cfg)
    before = snapshot(ws.dir)
    args = (EID, payload) if action == "api_add_short" else (EID, "k01", payload)
    response = endpoint(app, action)(*args)
    assert response.status_code == 422 and not app.state.runner.jobs()
    assert snapshot(ws.dir) == before


def test_shared_manual_restore_and_sibling_edits(cfg):
    ws, data = episode(cfg)
    kt, _ = episode(cfg, KT)
    calls = []
    app = app_for(cfg, restore_downloader=fake_download(data, calls), render=renderer(calls))
    first = endpoint(app, "api_restore_source")(KT)
    second = request(app, "title")
    third = endpoint(app, "api_title")(KT, "k02", TitleIn(set=TITLE))
    assert first.status_code == second.status_code == third.status_code == 202
    assert body(first)["job"]["id"] == body(second)["job"]["id"] == body(third)["job"]["id"]
    run(app)
    assert calls == ["restore", ("render", EID), ("render", KT)]
    assert list_titles(KT, cfg)["clips"][1]["title"] == TITLE


def test_edits_survive_queued_restart(cfg):
    ws, data = episode(cfg)
    calls = []
    original = app_for(cfg, restore_downloader=fake_download(data, calls), render=renderer(calls))
    request(original, "title")
    endpoint(original, "api_title")(EID, "k02", TitleIn(set=TITLE))
    restarted = app_for(cfg, restore_downloader=fake_download(data, calls), render=renderer(calls))
    assert restarted.state.runner.restore() == 1
    run(restarted)
    assert restarted.state.runner.jobs()[0].status == "done"
    assert calls == ["restore", ("render", EID)]
    assert [c["title"] for c in list_titles(EID, cfg)["clips"]] == [TITLE, TITLE]


@pytest.fixture
def source_index():
    from auto_short.store import index_cache
    index_cache.invalidate()
    yield index_cache
    with index_cache._CHANGED:
        deadline = time.monotonic() + 3
        while index_cache._REFRESHING is not None and time.monotonic() < deadline:
            index_cache._CHANGED.wait(max(0, deadline - time.monotonic()))
        assert index_cache._REFRESHING is None
    index_cache.invalidate()


def test_restore_store_can_run_during_youtube_backoff(cfg, monkeypatch, source_index):
    from auto_short.store.client import StoreClient
    ws, data = episode(cfg)
    cfg = replace(cfg, store=StoreConfig(enabled=True))
    calls = []

    class Client:
        def index(self):
            return [{"video_id": EID, "kind": "source"}]

        def head(self, vid, kind):
            return {"sha256": __import__("hashlib").sha256(data).hexdigest(), "size": len(data)}

        def fetch(self, vid, kind, dest, sha):
            calls.append("store")
            dest.write_bytes(data)
            return dest

    monkeypatch.setattr(StoreClient, "from_config", lambda c: Client())
    runner = JobRunner("lanes")
    with runner._lock:
        runner._set_yt_blocked_locked("bot check")
    app = app_for(cfg, runner=runner, restore_downloader=lambda *args: pytest.fail("must use store"),
                  render=renderer(calls))
    assert request(app, "title").status_code == 202
    run(app)
    assert runner.jobs()[0].status == "done" and calls == ["store", ("render", EID)]


@pytest.mark.parametrize("part", [EID, KT])
def test_restore_needs_download_uses_nonblocking_store_snapshot(cfg, monkeypatch, source_index, part):
    from auto_short.store.client import StoreClient
    episode(cfg)
    cfg = replace(cfg, store=StoreConfig(enabled=True))
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    heads, results, errors = [], [], []

    class Client:
        def index(self):
            entered.set()
            assert release.wait(3)
            return [{"video_id": EID, "kind": "source"}]

        def head(self, *args):
            # Regression guard: the old scheduler path would wait here while holding runner._lock.
            heads.append(args)
            entered.set()
            assert release.wait(3)
            return {"size": 1, "sha256": "a" * 64}

    monkeypatch.setattr(StoreClient, "from_config", lambda c: Client())
    target = RestoreSourceTarget(cfg, part)
    runner = JobRunner(cfg.web.queue_mode)

    def scheduled_check():
        try:
            with runner._lock:
                results.append(target.needs_download())
        except BaseException as exc:
            errors.append(exc)
        finally:
            returned.set()

    worker = threading.Thread(target=scheduled_check, daemon=True)
    worker.start()
    try:
        assert entered.wait(1)
        assert returned.wait(1), "store IO blocked needs_download under the scheduler lock"
        assert not errors and results == [True]  # cold snapshot: source not known yet
        assert runner._lock.acquire(timeout=.5), "scheduler lock remained held during store refresh"
        runner._lock.release()
        assert not heads
        release.set()
        assert source_index.has_source(cfg, EID)  # wait outside the scheduler for the fake refresh
        with runner._lock:
            assert target.needs_download() is False  # populated snapshot, including the .kt owner mapping
        assert not heads
    finally:
        release.set()
        worker.join(2)
        assert not worker.is_alive()


def test_applied_edits_resume_after_restore_checkpoint(cfg):
    ws, data = episode(cfg)
    calls = []
    original = app_for(cfg, restore_downloader=fake_download(data, calls), render=renderer(calls),
                       titler=lambda *a: SimpleNamespace(title="Tiêu đề AI", error=None))
    request(original, "add")
    job, = original.state.runner.jobs()
    # Checkpoint after AI but before render: the queue must not add the Short a second time on restart.
    job.target.prepare(job)
    job.target.edit(job)
    with original.state.runner._lock:
        original.state.runner._save_locked()
    restarted = app_for(cfg, restore_downloader=lambda *a: pytest.fail("already restored"), render=renderer(calls))
    assert restarted.state.runner.restore() == 1
    run(restarted)
    assert restarted.state.runner.jobs()[0].status == "done"
    assert [entry["clip_id"] for entry in json.loads((ws.dir / "review.json").read_text())["added"]] == ["m01"]
    assert calls == ["restore", ("render", EID)]


def test_youtube_block_keeps_edits_until_retry(cfg):
    ws, data = episode(cfg)
    calls, blocked = [], threading.Event()
    attempts = []

    def fetch(*args):
        attempts.append(1)
        if len(attempts) == 1:
            blocked.set()
            raise YoutubeBlocked("bot check")
        return fake_download(data, calls)(*args)

    runner = JobRunner("lanes", youtube_retry_seconds=60, youtube_retry_max_seconds=60)
    app = app_for(cfg, runner=runner, restore_downloader=fetch, render=renderer(calls))
    request(app, "title")
    runner.start()
    try:
        assert blocked.wait(3)
        with runner._lock:
            # Wait until the worker publishes backoff, without using an HTTP/socket boundary.
            deadline = time.monotonic() + 3
            while not runner.jobs()[0].yt_wait and time.monotonic() < deadline:
                runner._lock.wait(max(0, deadline - time.monotonic()))
            assert runner.jobs()[0].yt_wait
            assert (ws.dir / "archive.json").exists() and not (ws.dir / "review.json").exists()
            runner._yt_next = 0
            runner._lock.notify_all()
        assert runner.wait_idle(8)
        assert runner.jobs()[0].status == "done" and len(attempts) == 2
        assert list_titles(EID, cfg)["clips"][0]["title"] == TITLE
    finally:
        runner.stop()


def test_normal_title_edit_keeps_render_route(cfg):
    ws, data = episode(cfg)
    (ws.dir / "source.mp4").write_bytes(data)
    (ws.dir / "archive.json").unlink()
    calls = []
    app = app_for(cfg, restore_downloader=lambda *a: pytest.fail("source already available"), render=renderer(calls))
    response = request(app, "title")
    assert response.status_code == 202 and body(response)["job"]["kind"] == "render"
    assert "queued" not in body(response)
    job, = app.state.runner.jobs()
    job.target(job)
    assert calls == [("render", EID)]
