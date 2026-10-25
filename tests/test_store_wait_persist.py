"""FIX-store-wait-persist: restart/retry through real app rebuilds, without HTTP sockets."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from auto_short.config import StoreConfig
from auto_short.render.stage import StoreWait
from auto_short.review import list_titles
from auto_short.review.archive import restore_source
from auto_short.store.borrow import WAIT_PREFIX
from auto_short.store.client import StoreClient, StoreMismatch
from auto_short.web.app import KIND_RESTORE_SOURCE, QUEUE_FILE
from auto_short.web.jobs import INTERRUPTED, KIND_RENDER, KIND_VERTICAL, render_target, vertical_target
from auto_short.web.routes import episode_edit

from test_restore_source_cp837 import app_for, endpoint
from test_src3_auto_restore import (EID, TITLE, cfg, episode, fake_download, request as edit_request, run)

SHA = "a" * 64
ERROR = f"{WAIT_PREFIX}: HD unavailable"


@pytest.fixture(params=[KIND_RENDER, KIND_VERTICAL, KIND_RESTORE_SOURCE])
def waiting_app(cfg, monkeypatch, request):
    kind = request.param
    ws, data = episode(cfg)
    fetched, applied, rendered = [], [], []
    download = fake_download(data, fetched)
    if kind != KIND_RESTORE_SOURCE:
        restore_source(EID, cfg, downloader=download)
        fetched.clear()
    cfg = replace(cfg, store=StoreConfig(enabled=True))
    (ws.dir / "backup.json").write_text(json.dumps({"released": {"hd": {"sha256": SHA}}}))
    available, heads = [None], []

    class Client:
        def index(self):
            return []

        def head(self, vid, file_kind):
            assert vid == EID
            if file_kind == "source":
                raise StoreMismatch("source unavailable")
            assert file_kind == "hd"
            heads.append(vid)
            if available[0] is None:
                raise StoreMismatch("HD unavailable")
            return {"sha256": available[0], "size": 100}

    def render(eid, config):
        rendered.append(eid)
        if available[0] != SHA:
            raise StoreWait(ERROR)
        return SimpleNamespace(ran=True, rendered=2, clips=2, encoded=1, reused=1, size=100)

    real_apply = episode_edit.apply_restore_edit

    def apply(ctx, edit):
        applied.append(edit["payload"])
        return real_apply(ctx, edit)

    monkeypatch.setattr(StoreClient, "from_config", lambda c: Client())
    monkeypatch.setattr(episode_edit, "apply_restore_edit", apply)
    options = dict(restore_downloader=download, render=render, vertical=render)
    app = app_for(cfg, **options)
    runner = app.state.runner
    if kind == KIND_RESTORE_SOURCE:
        assert edit_request(app, "title").status_code == 202
    else:
        target = render_target(cfg, render=render) if kind == KIND_RENDER else \
            vertical_target(cfg, vertical=render, episode_id=EID)
        runner.submit(EID, kind, target, clip_ids=["k01"])
    run(app)
    job, = runner.jobs()
    assert (job.status, job.error) == (INTERRUPTED, ERROR)
    return SimpleNamespace(cfg=cfg, app=app, options=options, job=job, kind=kind, ws=ws,
                           available=available, client=Client(), heads=heads, fetched=fetched,
                           applied=applied, rendered=rendered,
                           path=Path(cfg.workspace.dir) / QUEUE_FILE)


def test_store_wait_restart_then_retry_without_reapplying_edits(waiting_app):
    w = waiting_app
    saved = json.loads(w.path.read_text())
    assert saved["version"] == 1
    assert saved["store_wait"] == [dict(w.app.state.runner._entry(w.job, w.job.step), error=ERROR)]
    assert not any(saved["lanes"].values()) and saved["parked"] == []
    if w.kind == KIND_RESTORE_SOURCE:
        assert w.job.target.restored is True
        assert all(edit["applied"] for edit in w.job.target.edits)
        assert len(w.applied) == len(w.fetched) == 1
    review = (w.ws.dir / "review.json").read_bytes() if w.kind == KIND_RESTORE_SOURCE else None
    app = app_for(w.cfg, **w.options)
    runner = app.state.runner
    assert runner.restore() == 1
    rebuilt, = runner.jobs()
    assert rebuilt.target is not w.job.target
    assert runner._entry(rebuilt, rebuilt.step) == w.app.state.runner._entry(w.job, w.job.step)
    assert (rebuilt.status, rebuilt.error, rebuilt.lane, rebuilt.waiting) == (INTERRUPTED, ERROR, None, False)
    assert runner._latest[rebuilt.key] is rebuilt
    assert not any(runner._queues.values()) and runner.parked() == []
    assert app.state.store_retry_pass(w.client) == []
    w.available[0] = "b" * 64
    assert app.state.store_retry_pass(w.client) == []
    assert runner.jobs() == [rebuilt] and json.loads(w.path.read_text())["store_wait"] == saved["store_wait"]
    w.available[0] = SHA
    assert app.state.store_retry_pass(w.client) == [EID]
    retry = runner._latest[rebuilt.key]
    assert retry is not rebuilt and retry.target is rebuilt.target and retry.kind == w.kind
    assert not json.loads(w.path.read_text()).get("store_wait")
    assert app.state.store_retry_pass(w.client) == []
    run(app)
    assert retry.status == "done", retry.error
    assert w.rendered == [EID, EID]
    if w.kind == KIND_RESTORE_SOURCE:
        assert len(w.applied) == len(w.fetched) == 1
        assert (w.ws.dir / "review.json").read_bytes() == review
        assert list_titles(EID, w.cfg)["clips"][0]["title"] == TITLE


@pytest.mark.parametrize("action", ["replace", "delete"])
def test_superseded_or_deleted_store_wait_is_removed_from_disk(waiting_app, action):
    w = waiting_app
    runner = w.app.state.runner
    if action == "replace":
        newer, created = runner.submit(EID, w.kind, w.job.target)
        assert created and newer is not w.job
    else:
        assert endpoint(w.app, "api_episode_delete")(EID) == {"deleted": EID}
        assert not w.ws.dir.exists()
    assert not json.loads(w.path.read_text()).get("store_wait")
    w.available[0] = SHA
    assert w.app.state.store_retry_pass(w.client) == []
    assert w.heads == []
    app = app_for(w.cfg, **w.options)
    assert app.state.runner.restore() == (1 if action == "replace" else 0)
    assert app.state.store_retry_pass(w.client) == []
    assert w.heads == []


@pytest.mark.parametrize("store_wait", [None, {"invalid": "not a list"}])
def test_legacy_queue_and_nonlist_store_wait_restore_normally(cfg, store_wait):
    episode(cfg)
    app = app_for(cfg)
    app.state.runner.submit(EID, KIND_VERTICAL, vertical_target(cfg, episode_id=EID))
    path = Path(cfg.workspace.dir) / QUEUE_FILE
    saved = json.loads(path.read_text())
    saved.pop("store_wait", None)
    if store_wait is not None:
        saved["store_wait"] = store_wait
    path.write_text(json.dumps(saved))
    app = app_for(cfg)
    assert app.state.runner.restore() == 1
    job, = app.state.runner.jobs()
    assert job.kind == KIND_VERTICAL and job.status == "queued"
    assert any(app.state.runner._queues.values())


@pytest.mark.parametrize("entry_case", ["malformed", "wrong_kind", "wrong_error", "unrebuildable", "raises", "active"])
def test_bad_store_wait_entry_is_skipped_without_losing_valid_entries(cfg, caplog, entry_case):
    episode(cfg)
    app = app_for(cfg)
    runner = app.state.runner
    job, _ = runner.submit(EID, KIND_VERTICAL, vertical_target(cfg, episode_id=EID))
    saved = json.loads((Path(cfg.workspace.dir) / QUEUE_FILE).read_text())
    entry = dict(runner._entry(job, 0), error=ERROR)
    if entry_case == "active":
        saved["store_wait"] = [entry]  # the lane entry wins this duplicate key
    else:
        saved["lanes"] = {lane: [] for lane in saved["lanes"]}
        bad = None if entry_case == "malformed" else dict(entry, episode_id="missing0001")
        if entry_case == "wrong_kind":
            bad = dict(entry, kind="pipeline")
        if entry_case == "wrong_error":
            bad = dict(entry, error="interrupted during render")
        saved["store_wait"] = [bad, entry]
    path = Path(cfg.workspace.dir) / QUEUE_FILE
    path.write_text(json.dumps(saved))
    app = app_for(cfg)
    runner = app.state.runner
    if entry_case == "raises":
        rebuild = runner._rebuild

        def broken(kind, eid, spec, clips):
            if eid == "missing0001":
                raise ValueError("broken rebuild")
            return rebuild(kind, eid, spec, clips)

        runner._rebuild = broken
    assert runner.restore() == 1
    job, = runner.jobs()
    assert job.episode_id == EID
    assert job.status == ("queued" if entry_case == "active" else INTERRUPTED)
    assert "bỏ qua" in caplog.text
