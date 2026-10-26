"""SHO1b: render/retry, compilation and storage through the real store handler, without sockets."""
import hashlib
import io
import json
import os
import time
import urllib.error
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import Mock

import pytest

from auto_short import compilation as comp, khaithi
from auto_short.config import StoreConfig
from auto_short.render.stage import RenderError, StoreWait, run_render
from auto_short.review import reject_clip, restore_clip, set_title
from auto_short.review.logic import empty_review, with_added, with_cut
from auto_short.review.publish import mark_downloaded
from auto_short.store import shorts
from auto_short.store.client import StoreClient
from auto_short.web import episodes as ep
from auto_short.web.app import create_app, QUEUE_FILE
from auto_short.web.jobs import KIND_ADD, KIND_RENDER, INTERRUPTED, add_short_target, render_target
from auto_short.web.storage import StorageCache, store_temp_files, sweep_store_temps
from auto_short.workspace import atomic_write_json, read_json_dict

from render_helpers import EID, make_render_episode, make_source, sha, write_docs
from test_restore_source_cp837 import endpoint
from test_store_server import TOKEN, archive, request
from test_store_shorts import VID, NOW, prepared_shorts

PL = "PLshortedit001"


@pytest.fixture
def memory_store(archive, monkeypatch):
    service, folder, _ = archive
    state = SimpleNamespace(client=StoreClient("http://memory", TOKEN), service=service,
                            mode=None, fail_clip=None, calls=[])

    def urlopen(req, timeout):
        target = urlsplit(req.full_url)
        state.calls.append((req.method, target.path))
        fail = state.fail_clip is None or target.path.endswith(state.fail_clip)
        if state.mode == "down" and fail:
            raise urllib.error.URLError("down")
        body = req.data.read() if req.data else b""
        headers = {k.title(): v for k, v in req.header_items() if k.lower() != "authorization"}
        code, fields, data = request(service, req.method,
                                     target.path + ("?" + target.query if target.query else ""),
                                     headers=headers, body=body, auth=TOKEN)
        if fail and state.mode == "missing":
            code = 404
        if fail and state.mode == "sha" and req.method == "HEAD":
            fields.replace_header("X-Sha256", "0" * 64)
        if fail and state.mode == "corrupt" and req.method == "GET":
            data = b"!" * len(data)
        if code >= 400:
            raise urllib.error.HTTPError(req.full_url, code, "store", fields, io.BytesIO(data))
        response = io.BytesIO(data)
        response.status, response.headers = code, fields
        return response

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr(StoreClient, "from_config", lambda config: state.client)
    return state


@pytest.mark.parametrize("eid", [VID, VID + ".kt"])
@pytest.mark.parametrize("failure", [None, "down", "missing", "sha", "corrupt", "partial"])
def test_restore_released_exact_metadata_and_partial_retry(prepared_shorts, memory_store, eid, failure):
    config = prepared_shorts()
    out = Path(config.render.output_dir) / eid
    assert shorts.push_video(config, VID, clock=lambda: NOW)["released"]
    record = (out / "store.json").read_bytes()
    manifest = (out / ep.RENDER_MANIFEST).read_bytes()
    records = json.loads(record)["released"]
    memory_store.mode = "down" if failure == "partial" else failure
    memory_store.fail_clip = "k02.mp4" if failure == "partial" else None
    if failure:
        with pytest.raises(StoreWait, match="đợi 3090"):
            shorts.restore_released(config, eid)
        assert (out / "store.json").read_bytes() == record
        assert (out / ep.RENDER_MANIFEST).read_bytes() == manifest
        assert (out / "shorts/k01.mp4").exists() is (failure == "partial")
        memory_store.mode = None
    restored = {p.name for p in (out / "shorts").glob("*.mp4")}
    memory_store.calls.clear()
    shorts.restore_released(config, eid)
    assert not (out / "store.json").exists()
    for cid, r in records.items():
        path = out / "shorts" / f"{cid}.mp4"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == r["sha256"]
        assert (path.stat().st_size, path.stat().st_mtime_ns) == (r["size"], r["mtime_ns"])
    assert not any(method == "GET" and route.rsplit("/", 1)[-1] in restored
                   for method, route in memory_store.calls)
    other = VID if eid.endswith(".kt") else VID + ".kt"
    assert (Path(config.render.output_dir) / other / "store.json").exists()


def test_restore_store_disabled_and_local_file_wins(prepared_shorts, memory_store):
    config = prepared_shorts(kt=False)
    shorts.push_video(config, VID, clock=lambda: NOW)
    out = Path(config.render.output_dir) / VID
    memory_store.calls.clear()
    disabled = replace(config, store=StoreConfig())
    with pytest.raises(RenderError, match=r"bật \[store\]"):
        shorts.restore_released(disabled, VID)
    assert not memory_store.calls and (out / "store.json").exists()
    local = out / "shorts/k01.mp4"
    local.write_bytes(b"local copy wins")
    shorts.restore_released(config, VID)
    assert local.read_bytes() == b"local copy wins"
    assert not any(route.endswith("k01.mp4") for _, route in memory_store.calls)
    memory_store.calls.clear()
    shorts.restore_released(disabled, VID)  # ordinary episodes, with store off
    assert not memory_store.calls


@pytest.mark.parametrize("mode", ["serial", "lanes"])
@pytest.mark.parametrize("kind", [KIND_RENDER, KIND_ADD])
def test_short_wait_persists_and_retries_render_without_ai(prepared_shorts, memory_store, mode, kind):
    config = prepared_shorts(kt=False)
    config = replace(config, web=replace(config.web, queue_mode=mode))
    shorts.push_video(config, VID, clock=lambda: NOW)
    out = Path(config.render.output_dir) / VID
    before = {name: (out / name).read_bytes() for name in ("store.json", ep.RENDER_MANIFEST)}
    title_calls = []

    def title(eid, cfg, cid):
        title_calls.append(cid)
        atomic_write_json(Path(cfg.workspace.dir) / eid / "review.json", {"persisted_title": "new"})
        return SimpleNamespace(title="new", error=None)

    def render(eid, cfg):
        shorts.restore_released(cfg, eid)
        return SimpleNamespace(ran=True, rendered=2, clips=2, encoded=1, reused=1)

    def app():
        return create_app(config, "pw", preflight=None, post_preflight=None, render=render, titler=title)

    first = app()
    target = render_target(config, render=render) if kind == KIND_RENDER else \
        add_short_target(config, "m01", render=render, preflight=None, titler=title)
    first.state.runner.submit(VID, kind, target)
    memory_store.mode = "down"
    first.state.runner.start()
    try:
        assert first.state.runner.wait_idle(8)
    finally:
        first.state.runner.stop()
    job, = first.state.runner.jobs()
    assert job.status == INTERRUPTED and job.error.startswith("đợi 3090")
    assert {name: (out / name).read_bytes() for name in before} == before
    saved = read_json_dict(Path(config.workspace.dir) / QUEUE_FILE)
    assert saved["store_wait"][0]["kind"] == KIND_RENDER
    restarted = app()
    assert restarted.state.runner.restore() == 1
    assert restarted.state.store_retry_pass() == []
    memory_store.mode = "sha"
    assert restarted.state.store_retry_pass() == []
    memory_store.mode = None
    assert restarted.state.store_retry_pass() == [VID]
    assert restarted.state.store_retry_pass() == []
    restarted.state.runner.start()
    try:
        assert restarted.state.runner.wait_idle(8)
    finally:
        restarted.state.runner.stop()
    assert restarted.state.runner.latest(VID).status == "done"
    assert title_calls == (["m01"] if kind == KIND_ADD else [])
    assert not (out / "store.json").exists()


@pytest.mark.parametrize("edit", ["title", "cut", "reject", "restore", "add"])
def test_released_edits_reuse_unchanged_short_and_reoffload(tcfg, tmp_path, memory_store, edit):
    config = replace(tcfg, store=StoreConfig(enabled=True, offload_shorts=True),
                     render=replace(tcfg.render, preset="ultrafast", threads=2))
    source = make_source(tmp_path / "source.mp4", size="160x120", rate="25")
    ws = make_render_episode(config.workspace.dir, source)
    sil = {"schema_version": 1, "episode_id": EID, "silences": []}
    atomic_write_json(ws.dir / "silences.json", sil)
    write_docs(ws, cand_extra={"params": {"max_pause": 0.5}, "silences_sha256": sha(sil)})
    if edit == "restore":
        reject_clip(EID, config, "k01")
    run_render(EID, config)
    mark_downloaded(EID, config, ["k01", "k02"])
    assert shorts.push_video(config, EID, clock=lambda: NOW)["released"]
    old = ep.render_manifest(config, EID)
    out = Path(config.render.output_dir) / EID
    record = read_json_dict(out / "store.json")
    if edit == "title":
        set_title(EID, config, "k01", "Tướng mạo đổi theo tâm thiện")
    elif edit == "reject":
        reject_clip(EID, config, "k01")
    elif edit == "restore":
        restore_clip(EID, config, "k01")
    elif edit == "cut":
        atomic_write_json(ws.dir / "review.json", with_cut(empty_review(EID), ["k01", "k02"],
                          clip_id="k01", candidate_id="c00001", start=0.6, end=3.5))
    else:
        atomic_write_json(ws.dir / "review.json", with_added(empty_review(EID), ["k01", "k02", "m01"],
                          dict(clip_id="m01", candidate_id="manual", start=0.5, end=3.5, source="transcript",
                               title="Short thêm tay", ai_title="Short thêm tay", alternatives=[])))
    result = run_render(EID, config)
    assert result.encoded == (0 if edit == "reject" else 1)
    assert result.reused == (2 if edit == "add" else 1)
    new = ep.render_manifest(config, EID)
    assert new["shorts"][1] == old["shorts"][1]
    assert (out / "shorts/k02.mp4").stat().st_mtime_ns == record["released"]["k02"]["mtime_ns"]
    assert not (out / "store.json").exists()
    if edit in ("title", "cut"):
        assert shorts.candidates(config, now=NOW) == []  # old publish tick is stale
    mark_downloaded(EID, config, ["k01", "k02", "m01"])
    assert shorts.push_video(config, EID, clock=lambda: NOW)["released"]
    rows = [r for r in memory_store.service.index() if r["video_id"] == EID]
    assert next(r for r in rows if r["clip"] == "k02.mp4")["file"].endswith(" - k02.mp4")
    if edit in ("title", "cut"):
        assert next(r for r in rows if r["clip"] == "k01.mp4")["file"].endswith(" - k01 (r2).mp4")


@pytest.fixture
def compilation_app(prepared_shorts, memory_store):
    config = prepared_shorts()
    shorts.push_video(config, VID, clock=lambda: NOW)
    doc = dict(schema_version=1, playlist_id=PL, title="Bộ thử", url="https://youtube.com/playlist?list=" + PL,
               fetched_at="2026-10-01T00:00:00Z", series="Bộ thử",
               entries=[dict(index=1, video_id=VID, episode="3", available=True, title="Tập 3", duration=100)])
    atomic_write_json(Path(config.workspace.dir) / "_playlists" / f"{PL}.json", doc)
    app = create_app(config, "pw", preflight=None, post_preflight=None, clock=lambda: NOW)
    return config, app, doc


@pytest.mark.parametrize("failure", [None, "down", "sha", "corrupt", "assemble"])
def test_compilation_released_clips_borrow_and_cleanup(compilation_app, memory_store, monkeypatch, failure):
    config, app, doc = compilation_app
    service = app.state.compilations
    before = {eid: (Path(config.render.output_dir) / eid / "store.json").read_bytes()
              for eid in (VID, VID + ".kt")}
    clips = service.clips(doc)
    assert len(clips) == 4 and all(isinstance(c.path, ep.StoredShort) for c in clips)
    service._probe_runner = Mock(side_effect=AssertionError("must not probe a missing file"))
    assert service.duration(clips[0]) == 60
    service.set_favorite(PL, doc, comp.Item(VID, "k01"), True)
    assert service.favorites_view(PL, doc)[0]["usable"]
    view, _ = service.submit(PL, doc, {"mode": "concat", "items": [comp.Item(VID, "k01").to_json(),
                                       comp.Item(VID + ".kt", "k02").to_json()]})
    seen = []

    def assemble(paths, dest, enc, **kw):
        seen.extend(paths)
        assert all(p in store_temp_files(config) for p in paths)
        assert not any(store_temp_files(config)[p] for p in paths)  # protected while borrowed
        assert sweep_store_temps(config, set(), now=time.time() + 7 * 3600) == 0
        assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths] == [
            clips[0].path.sha256, clips[3].path.sha256]
        if failure == "assemble":
            raise comp.CompilationError("ffmpeg failed")
        dest.write_bytes(b"joined")
        return SimpleNamespace(parts=[60, 61], duration=121, size=6, reencoded=False)

    monkeypatch.setattr(comp, "assemble", assemble)
    memory_store.mode = None if failure == "assemble" else failure
    runner = app.state.runner
    runner.start()
    try:
        assert runner.wait_idle(8)
    finally:
        runner.stop()
    job = runner.jobs()[-1]
    assert job.status == ("failed" if failure else "done"), job.error
    if failure and failure != "assemble":
        assert "3090 không trả lời — bấm Ghép lại sau" in job.error
    assert not list(service.folder(PL).glob(".store-shorts-*")) and not store_temp_files(config)
    assert all(not p.exists() for p in seen)
    assert {eid: (Path(config.render.output_dir) / eid / "store.json").read_bytes() for eid in before} == before


@pytest.mark.parametrize("failure", [None, "down", "corrupt", "partial"])
def test_keep_released_favorites_or_abort_delete(compilation_app, memory_store, failure):
    config, app, doc = compilation_app
    service = app.state.compilations
    eid = VID + ".kt"
    service.set_favorite(PL, doc, comp.Item(eid, "k01"), True)
    if failure == "partial":
        service.set_favorite(PL, doc, comp.Item(eid, "k02"), True)
    original = (service.folder(PL) / "favorites.json").read_bytes()
    record = (Path(config.render.output_dir) / eid / "store.json").read_bytes()
    memory_store.mode = "down" if failure == "partial" else failure
    memory_store.fail_clip = "k02.mp4" if failure == "partial" else None
    service._info = Mock(side_effect=comp.CompilationError("fake mp4"))
    if failure:
        response = endpoint(app, "api_episode_delete")(eid)
        assert response.status_code == 500
        assert "không giữ lại được" in json.loads(response.body)["detail"]
        assert (Path(config.workspace.dir) / eid).is_dir()
        assert (service.folder(PL) / "favorites.json").read_bytes() == original
        assert not list(service.folder(PL).glob("kept/**/*.mp4*"))
    else:
        assert endpoint(app, "api_episode_delete")(eid) == {"deleted": eid}
        fav, = service.favorites(PL)
        kept = comp.store.kept_path(service.folder(PL), fav)
        assert hashlib.sha256(kept.read_bytes()).hexdigest() == json.loads(record)["released"]["k01"]["sha256"]
        assert not (Path(config.workspace.dir) / eid).exists()


def test_short_storage_snapshot_and_orphan_temp_sweep(prepared_shorts, memory_store):
    config = prepared_shorts()
    app = create_app(config, "pw", preflight=None, post_preflight=None, clock=lambda: NOW)
    assert shorts.offload_snapshot(config, now=NOW)["eligible"] == 1
    assert shorts.offload_snapshot(config, now=time.time())["waiting_days"] == 1
    memory_store.mode = "down"
    assert app.state.shorts_offload_pass() == []
    snapshot = app.state.storage.report()["shorts_offload"]
    assert snapshot["failed"] == 1 and snapshot["last_error"]
    memory_store.mode = None
    assert app.state.shorts_offload_pass() == []  # rotation after the failed video
    assert app.state.shorts_offload_pass() == [VID]
    memory_store.calls.clear()
    report = endpoint(app, "api_storage")()
    so = report["shorts_offload"]
    expected_bytes = sum(r["size"] for eid in (VID, VID + ".kt") for r in read_json_dict(
        Path(config.render.output_dir) / eid / "store.json")["released"].values())
    assert so == dict(enabled=True, episodes=2, bytes=expected_bytes, eligible=0, waiting_days=0,
                      failed=0, last_error=None)
    # Startup with the flag off still reports existing released bytes, and no store calls.
    disabled = replace(config, store=StoreConfig())
    assert StorageCache(disabled, clock=lambda: NOW).report()["shorts_offload"]["bytes"] == expected_bytes
    assert not memory_store.calls
    orphan = Path(config.render.output_dir) / "_compilations" / PL / ".store-shorts-orphan" / "k01.mp4.part"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan")
    os.utime(orphan, (1, 1))
    real = orphan.parent.parent / "kept" / "k01.mp4"
    real.parent.mkdir()
    real.write_bytes(b"keep")
    assert store_temp_files(config) == {orphan: True}
    assert sweep_store_temps(config, set(), now=NOW) == 6 and real.read_bytes() == b"keep"


def test_real_compilation_mixes_released_and_local_short(prepared_shorts, memory_store, tmp_path):
    from compilation_helpers import make_clip, duration_of, frame_color

    config = prepared_shorts(kt=False)
    out = Path(config.render.output_dir) / VID
    doc = ep.render_manifest(config, VID)
    for entry, color in zip(doc["shorts"], ("red", "green")):
        path = make_clip(out / entry["file"], color, seconds=1)
        entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        entry["duration"] = duration_of(path)
    atomic_write_json(out / ep.RENDER_MANIFEST, doc)
    mark_downloaded(VID, config, ["k01", "k02"])
    shorts.push_video(config, VID, clock=lambda: NOW)
    # A partially restored episode must use its local clip and borrow just the absent clip.
    local = next(p for cid, p, _ in ep.short_locations(config, VID) if cid == "k02")
    shorts.fetch_released(config, local, out / "shorts/k02.mp4")
    playlist = dict(schema_version=1, playlist_id=PL, title="Bộ thử", url="https://youtube.com/playlist?list=" + PL,
                    fetched_at="2026-10-01T00:00:00Z", series="Bộ thử",
                    entries=[dict(index=1, video_id=VID, episode="3", available=True, title="Tập 3", duration=100)])
    atomic_write_json(Path(config.workspace.dir) / "_playlists" / f"{PL}.json", playlist)
    app = create_app(config, "pw", preflight=None, post_preflight=None)
    service = app.state.compilations
    view, _ = service.submit(PL, playlist, {"mode": "concat", "items": [comp.Item(VID, cid).to_json()
                                                                 for cid in ("k01", "k02")]})
    memory_store.calls.clear()
    app.state.runner.start()
    try:
        assert app.state.runner.wait_idle(15)
    finally:
        app.state.runner.stop()
    job, = app.state.runner.jobs()
    assert job.status == "done", job.error
    video = service.video_file(PL, view["cid"])
    assert abs(duration_of(video) - 2) < 0.2
    assert [frame_color(video, t) for t in (0.3, 1.3)] == ["r", "g"]
    assert [route.rsplit("/", 1)[-1] for method, route in memory_store.calls if method == "GET"] == ["k01.mp4"]
    assert (out / "store.json").exists() and (out / "shorts/k02.mp4").is_file()
    assert not list(service.folder(PL).glob(".store-shorts-*"))
