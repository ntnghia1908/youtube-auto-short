"""Process archived episodes through the existing restore reservation, without HTTP sockets."""
import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path
from inspect import getclosurevars
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from auto_short import khaithi
from auto_short.config import StoreConfig
from auto_short.ingest import run_ingest
from auto_short.ingest.source import classify
from auto_short.ingest.stage import _used_config, reusable_source
from auto_short.hashing import config_hash
from auto_short.store.client import StoreClient
from auto_short.web.playlists import PlaylistStore
from auto_short.web.routes.episodes import SubmitIn

from test_restore_source_cp837 import app_for, body, endpoint
from test_src3_auto_restore import EID, KT, cfg, episode, fake_download, renderer, request, run, source_index


@pytest.mark.parametrize("checkpoint", ["none", "queued", "restored", "handoff"])
def test_process_restore_store_join_and_restart(cfg, monkeypatch, checkpoint, source_index):
    ws, data = episode(cfg)
    cfg = replace(cfg, store=StoreConfig(enabled=True))
    # A valid ingest reference makes the real K5 reuse check meaningful, without media tools.
    manifest = ws.load_manifest()
    spec = classify(f"https://youtu.be/{EID}")
    manifest["stages"]["ingest"]["config_hash"] = config_hash(_used_config(spec, cfg))
    ws.save_manifest(manifest)
    (ws.dir / "metadata.json").write_text(json.dumps({"youtube": {"id": EID}}))
    calls = []

    class Client:
        def head(self, vid, kind):
            assert (vid, kind) == (EID, "source")
            return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}

        def fetch(self, vid, kind, dest, sha):
            calls.append("store")
            dest.write_bytes(data)
            return dest

        def index(self):
            return [{"video_id": EID, "kind": "source"}]

    def pipeline(url, config, **kw):
        eid = kw.get("episode_id") or EID
        assert not (ws.dir / "archive.json").exists()
        if eid == KT:
            reused = reusable_source(Path(config.workspace.dir), EID, spec, config)
            assert reused is not None and reused.path.read_bytes() == data
            if kw.get("stages") is None or "ingest" in kw["stages"]:
                run_ingest(url, config, episode_id=KT, downloader=lambda *a: pytest.fail("K5 must reuse"))
                assert (Path(config.workspace.dir) / KT / "source.mp4").read_bytes() == data
            assert khaithi.read(Path(config.workspace.dir) / KT, config.khaithi.max_minutes_limit).min_minutes == 4
        calls.append((eid, kw.get("stages")))
        return SimpleNamespace(ok=True, episode_id=eid, stages=[], rendered=2, clips=2)

    monkeypatch.setattr("auto_short.ingest.probe.probe", lambda p: {"duration": 60, "height": 360})
    monkeypatch.setattr(StoreClient, "from_config", lambda c: Client())
    options = dict(pipeline=pipeline, restore_downloader=lambda *a: pytest.fail("must use store"))
    app = app_for(cfg, **options)
    submit = endpoint(app, "api_submit")
    first = submit(SubmitIn(url=f"https://youtu.be/{EID}", kinds=["short"], vertical=True))
    second = submit(SubmitIn(url=f"https://youtu.be/{EID}", kinds=["khaithi"], min_minutes=4,
                             max_minutes=7, series="Bộ kinh", episode="12", vertical=True))
    duplicate = submit(SubmitIn(url=f"https://youtu.be/{EID}", kinds=["khaithi"], min_minutes=4, max_minutes=7))
    assert first.status_code == second.status_code == 202
    assert body(first)["job"]["id"] == body(second)["job"]["id"] == body(duplicate)["job"]["id"]
    job, = app.state.runner.jobs()
    assert len(job.target.pipelines) == 2
    assert "Đang lấy lại nguồn" in job.summary
    if checkpoint in ("restored", "handoff"):
        job.target.prepare(job)
        # Duplicate clicks still join after the restore closes edit admission.
        repeated = submit(SubmitIn(url=f"https://youtu.be/{EID}", kinds=["short"]))
        assert repeated.status_code == 200 and body(repeated)["job"]["id"] == job.id
    if checkpoint == "handoff":
        # Simulate restart with the restore still running and both children already saved.
        with app.state.runner._lock:
            lane = job.steps[0].lane
            app.state.runner._queues[lane].remove(job)
            app.state.runner._current[lane] = job
        job.target.dispatch(job)
    if checkpoint != "none":
        with app.state.runner._lock:
            app.state.runner._save_locked()
        app = app_for(cfg, **options)
        assert app.state.runner.restore() >= 1
    app.state.runner.on_finished = None  # Pipeline double does not produce post / HD artifacts.
    run(app)
    assert all(j.status == "done" for j in app.state.runner.jobs()), [(j.status, j.error) for j in app.state.runner.jobs()]
    assert calls.count("store") == 1
    assert {c[0] for c in calls if isinstance(c, tuple)} == {EID, KT}
    kt = app.state.runner.latest(KT)
    assert (kt.target.series, kt.target.episode) == ("Bộ kinh", "12")
    assert app.state.auto_vertical.wanted(EID)


@pytest.mark.parametrize("outcome", ["failure", "cancel", "busy", "prepare_only", "normal"])
def test_process_restore_failure_cancel_and_normal(cfg, outcome):
    ws, data = episode(cfg)
    if outcome == "normal":
        (ws.dir / "archive.json").unlink()
        (ws.dir / "source.mp4").write_bytes(data)
    calls = []
    app = app_for(cfg, restore_downloader=fake_download(data, calls, fail=outcome == "failure"))
    runner = app.state.runner
    if outcome == "busy":
        runner.submit(KT, "pipeline", lambda j: None)
    if outcome == "prepare_only":
        # Exercise the same direct context call used by the playlist prepare route.
        ctx = getclosurevars(endpoint(app, "api_submit")).nonlocals["ctx"]
        item, = ctx.queue_video(EID, ["short"], None, None, None, None, prepare_only=True)
        assert item["queued"] == "restore"
    else:
        response = endpoint(app, "api_submit")(SubmitIn(url=f"https://youtu.be/{EID}", kinds=["short"]))
    if outcome == "busy":
        assert response.status_code == 409 and len(runner.jobs()) == 1
        return
    job, = runner.jobs()
    if outcome == "normal":
        assert job.kind == "pipeline" and response.status_code == 202 and calls == []
        return
    if outcome == "prepare_only":
        assert job.target.spec()["pipelines"][0]["prepare_only"] is True
        job.target.prepare(job)
        job.target.dispatch(job)
        child = runner.latest(EID)
        assert child.kind == "pipeline" and child.target.prepare_only is True
        assert len(child.target.lane_steps()) == 1
        return
    if outcome == "cancel":
        assert runner.cancel("restore_source") == [job]
    run(app)
    assert len(runner.jobs()) == 1
    assert job.status == ("failed" if outcome == "failure" else "cancelled")
    if outcome == "failure":
        assert "khôi phục nguồn:" in job.error
    assert (ws.dir / "archive.json").exists()


@pytest.mark.parametrize("with_edit", [False, True])
def test_manual_restore_accepts_pipeline_while_downloading(cfg, with_edit):
    ws, data = episode(cfg)
    started, release = threading.Event(), threading.Event()
    calls = []

    def fetch(*args):
        started.set()
        assert release.wait(3)
        return fake_download(data, calls)(*args)

    app = app_for(cfg, restore_downloader=fetch, render=renderer(calls))
    endpoint(app, "api_restore_source")(EID)
    runner = app.state.runner
    runner.start()
    try:
        assert started.wait(3)
        response = endpoint(app, "api_submit")(SubmitIn(url=f"https://youtu.be/{EID}", kinds=["khaithi"]))
        assert response.status_code == 202 and len(runner.jobs()) == 1
        if with_edit:
            assert request(app, "title").status_code == 202
        # Verify handoff without executing the real pipeline after download.
        job, = runner.jobs()
        job.target.queue_pipelines = lambda j, requests: calls.append(requests[0]["kinds"])
        release.set()
        assert runner.wait_idle(5)
        assert calls == ["restore"] + ([("render", EID)] if with_edit else []) + [["khaithi"]]
    finally:
        release.set()
        runner.stop()


@pytest.mark.parametrize("kt_state, action", [(None, "process"), ("rendered", "reprocess"), ("complete", "reprocess")])
def test_playlist_archived_actions(cfg, monkeypatch, kt_state, action):
    store = PlaylistStore(cfg)
    st = dict(state="rendered", archived=True, complete=False, shorts=2, published=0)
    monkeypatch.setattr(store, "_disk_status", lambda eid: dict(st, state=kt_state) if eid == KT else dict(st))
    monkeypatch.setattr(store, "_khaithi_id", lambda vid: KT if kt_state else None)
    doc = {"playlist_id": "PLtest", "entries": [{"video_id": EID, "available": True}]}
    entry, = store.view(doc, {})["entries"]
    assert entry["action"] == action
    running, = store.view(doc, {EID: {"status": "queued"}})["entries"]
    assert running["action"] is None
