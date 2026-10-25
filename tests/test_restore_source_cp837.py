"""CP8.37: exact ingest restoration, shared parts, prepare jobs and archive grace. No real downloads."""

import hashlib
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from auto_short.config import Config, RenderConfig, WorkspaceConfig
from auto_short.hashing import sha256_file
from auto_short.ingest.youtube import Download, YoutubeBlocked
from auto_short.render import full, run_render
from auto_short.review import ReviewError, archive_source, reject_archived_clip, restore_clip, set_published, set_title
from auto_short.review.archive import check_not_archived, restore_source
from auto_short.theme_render.sources import cache_dir, cached_source
from auto_short.web.app import KIND_RESTORE_SOURCE, RestoreSourceTarget, create_app
from auto_short.web.jobs import Job, JobFailed, JobRunner
from auto_short.web.storage import GB, auto_archive_plan, episode_sizes, parse_time

from render_helpers import EID, TITLES, make_render_episode, make_source
from web_helpers import write_episode

KT = EID + ".kt"
DATA = b"original source bytes" * 100
STAMP = "2030-01-02T03:04:05Z"
NOW = parse_time(STAMP)


@pytest.fixture
def cfg(tmp_path):
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output", preset="ultrafast", threads=2))


def make_episode(cfg, eid=EID, *, data=DATA, archived=True, name="source.webm", height=360):
    write_episode(cfg, eid, titles=TITLES)
    folder = Path(cfg.workspace.dir) / eid
    source = folder / name
    source.write_bytes(data)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["source"] = {"kind": "youtube", "uri": f"https://youtu.be/{EID}", "path": name,
                          "sha256": sha256_file(source), "size": len(data), "mtime_ns": 123}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    (folder / "metadata.json").write_text(json.dumps({"title": "T", "duration": 60, "height": height}))
    if archived:
        archive_source(eid, cfg)
    return folder


def seed_cache(cfg, data=DATA):
    folder = cache_dir(cfg) / EID
    folder.mkdir(parents=True)
    source = folder / "source.mp4"
    source.write_bytes(data)
    ingest = json.loads((Path(cfg.workspace.dir) / EID / "manifest.json").read_text())["source"]
    sha = sha256_file(source)
    (folder / "meta.json").write_text(json.dumps({
        "schema_version": 1, "video_id": EID, "file": source.name, "uri": ingest["uri"],
        "sha256": sha, "ingest_sha256": ingest["sha256"], "differs_from_ingest": sha != ingest["sha256"],
        "size": len(data), "height": 360, "duration": 60, "downloaded_at": STAMP}))
    assert cached_source(cfg, EID) == source
    return source


def downloader(data=DATA, calls=None):
    def fetch(uri, dest, ingest):
        if calls is not None:
            calls.append(uri)
        path = dest / "download.mp4"
        path.write_bytes(data)
        return Download(path, {})
    return fetch


def no_download(*args):
    pytest.fail("cache restore must not download")


@pytest.mark.parametrize("failure", [None, "missing", "down", "sha", "size", "corrupt"])
def test_src1_restore_store_before_youtube_exact_ingest(cfg, monkeypatch, failure):
    from dataclasses import replace
    from auto_short.config import StoreConfig
    from auto_short.store.client import StoreClient, StoreMismatch, StoreUnavailable

    folder = make_episode(cfg)
    cfg = replace(cfg, store=StoreConfig(enabled=True))
    seen = []

    class Client:
        def fetch(self, video_id, kind, dest, sha):
            seen.append("store")
            assert video_id == EID and kind == "source" and sha == hashlib.sha256(DATA).hexdigest()
            if failure == "missing":
                raise StoreMismatch("missing")
            if failure == "down":
                raise StoreUnavailable("down")
            if failure == "sha":
                raise StoreMismatch("sha mismatch")
            dest.write_bytes(DATA[:-1] if failure == "size" else b"x" * len(DATA) if failure == "corrupt" else DATA)
            return dest

    def youtube(*args):
        seen.append("youtube")
        return downloader()(*args)

    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: Client())
    result = restore_source(EID, cfg, downloader=youtube, now=STAMP)
    assert seen == (["store"] if failure is None else ["store", "youtube"])
    assert result.downloaded and (folder / "source.webm").read_bytes() == DATA
    assert not (folder / "archive.json").exists()
    assert not list(folder.glob(".restore-source-*"))


def test_src1_restore_valid_cache_precedes_store(cfg, monkeypatch):
    from dataclasses import replace
    from auto_short.config import StoreConfig
    from auto_short.store.client import StoreClient

    make_episode(cfg)
    seed_cache(cfg)
    cfg = replace(cfg, store=StoreConfig(enabled=True))
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: pytest.fail("cache should precede store"))
    assert not restore_source(EID, cfg, downloader=no_download).downloaded


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def app_for(cfg, **kw):
    return create_app(cfg, "pw", preflight=lambda c: None, post_preflight=None,
                      disk_usage=lambda p: (100 * GB, 50 * GB, 50 * GB),
                      clock=lambda: NOW, auto_archive_interval=0, **kw)


def endpoint(app, name):
    def routes(items):
        for route in items:
            if hasattr(route, "original_router"):
                yield from routes(route.original_router.routes)
            else:
                yield route

    return next(r.endpoint for r in routes(app.routes) if getattr(r, "name", None) == name)


def body(response):
    return json.loads(response.body)


def test_cache_restores_both_parts_with_manifest_paths_and_shared_inode(cfg):
    main = make_episode(cfg)
    kt = make_episode(cfg, KT, name="source.mkv")
    cache = seed_cache(cfg)
    before = snapshot(Path(cfg.workspace.dir))
    result = restore_source(KT, cfg, downloader=no_download, now=STAMP)
    assert result.episodes == [EID, KT] and not result.downloaded
    for folder, name in ((main, "source.webm"), (kt, "source.mkv")):
        check_not_archived(folder, folder.name)
        assert (folder / name).read_bytes() == DATA
        assert (folder / name).stat().st_ino == cache.stat().st_ino
        assert json.loads((folder / "restored.json").read_text()) == {"restored_at": STAMP}
        for rel, contents in before.items():
            if rel.startswith(folder.name + "/") and not rel.endswith("archive.json"):
                assert (Path(cfg.workspace.dir) / rel).read_bytes() == contents
    assert full.remove_refetched_source(cfg, EID) == 0
    assert full.sweep_refetched_sources(cfg, set()) == 0
    assert (main / "source.webm").exists() and (kt / "source.mkv").exists()


def test_download_once_for_both_parts_and_clear_guards(cfg):
    make_episode(cfg)
    make_episode(cfg, KT)
    calls = []
    result = restore_source(EID, cfg, downloader=downloader(calls=calls), now=STAMP)
    assert result.downloaded and result.episodes == [EID, KT] and len(calls) == 1
    assert not list(Path(cfg.workspace.dir).rglob(".restore-source-*"))
    paths = [Path(cfg.workspace.dir) / eid / "source.webm" for eid in (EID, KT)]
    assert paths[0].stat().st_ino == paths[1].stat().st_ino


@pytest.mark.parametrize("data", [DATA[:-1], b"x" * len(DATA)], ids=["size", "sha256"])
@pytest.mark.parametrize("cache", [False, True])
def test_mismatched_sha_or_size_keeps_workspace_unchanged(cfg, data, cache):
    make_episode(cfg)
    make_episode(cfg, KT)
    if cache:
        seed_cache(cfg, data)
    before = snapshot(Path(cfg.workspace.dir))
    with pytest.raises(ReviewError, match="video tải lại khác bản gốc; không khôi phục được"):
        restore_source(EID, cfg, downloader=no_download if cache else downloader(data))
    assert snapshot(Path(cfg.workspace.dir)) == before
    assert not list(Path(cfg.workspace.dir).rglob(".restore-source-*"))


def test_second_part_mismatch_does_not_restore_first_part(cfg):
    make_episode(cfg)
    make_episode(cfg, KT, data=b"other ingest")
    seed_cache(cfg)
    before = snapshot(Path(cfg.workspace.dir))
    with pytest.raises(ReviewError, match="khác bản gốc"):
        restore_source(EID, cfg, downloader=no_download)
    assert snapshot(Path(cfg.workspace.dir)) == before


def test_only_archived_parts_change(cfg):
    main = make_episode(cfg, archived=False)
    make_episode(cfg, KT)
    before = snapshot(main)
    result = restore_source(KT, cfg, downloader=downloader(), now=STAMP)
    assert result.episodes == [KT]
    assert snapshot(main) == before


@pytest.mark.parametrize("source_change", [
    {"kind": "local"}, {"path": "../escape.mp4"}, {"path": "/tmp/source.mp4"},
    {"sha256": None}, {"size": None}, {"uri": None},
])
def test_unrestorable_manifest_is_rejected_without_writes(cfg, source_change):
    folder = make_episode(cfg)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["source"].update(source_change)
    (folder / "manifest.json").write_text(json.dumps(manifest))
    before = snapshot(Path(cfg.workspace.dir))
    with pytest.raises(ReviewError):
        restore_source(EID, cfg, downloader=no_download)
    assert snapshot(Path(cfg.workspace.dir)) == before


def test_publication_failure_rolls_back_both_parts(cfg, monkeypatch):
    from auto_short.review import archive
    make_episode(cfg)
    make_episode(cfg, KT)
    before = snapshot(Path(cfg.workspace.dir))
    original = archive.atomic_write_json

    def fail_second(path, doc):
        if path.parent.name == KT:
            raise OSError("disk failed")
        return original(path, doc)
    monkeypatch.setattr(archive, "atomic_write_json", fail_second)
    with pytest.raises(OSError, match="disk failed"):
        restore_source(EID, cfg, downloader=downloader(), now=STAMP)
    assert snapshot(Path(cfg.workspace.dir)) == before


def test_restored_episode_can_edit_restore_short_and_render(cfg, tmp_path):
    template = make_source(tmp_path / "media.mp4", size="320x240")
    ws = make_render_episode(cfg.workspace.dir, template)
    manifest = ws.load_manifest()
    manifest["source"].update(kind="youtube", uri=f"https://youtu.be/{EID}")
    manifest["stages"]["render"] = {"status": "done"}
    ws.save_manifest(manifest)
    # A first render supplies the real render manifest for deleting an archived Short.
    run_render(EID, cfg)
    archive_source(EID, cfg)
    reject_archived_clip(EID, cfg, "k01")
    data = template.read_bytes()
    restore_source(EID, cfg, downloader=downloader(data), now=STAMP)
    assert restore_clip(EID, cfg, "k01")
    assert set_title(EID, cfg, "k02", "Tâm thiện thì tướng mạo cũng từ bi")
    result = run_render(EID, cfg)
    assert result.rendered == 2 and result.encoded == 2


def test_grace_starts_when_download_finishes_and_survives_new_app(cfg):
    folder = make_episode(cfg)
    for clip in ("k01", "k02"):
        set_published(EID, cfg, clip, True)
    clock = [NOW]

    def long_download(uri, dest, ingest):
        clock[0] += 7200
        return downloader()(uri, dest, ingest)

    restore_source(EID, cfg, downloader=long_download, clock=lambda: clock[0])
    since = episode_sizes(cfg)[0]["complete_since"]
    assert since == clock[0] and json.loads((folder / "restored.json").read_text())["restored_at"] != STAMP
    app = create_app(cfg, "pw", disk_usage=lambda p: (100 * GB, 50 * GB, 50 * GB), clock=lambda: clock[0])
    clock[0] += cfg.storage.auto_archive_grace_minutes * 60 - 1
    assert app.state.auto_archive_pass() == []
    assert auto_archive_plan(episode_sizes(cfg), clock[0], cfg.storage.auto_archive_grace_minutes * 60) == []
    clock[0] += 1
    assert app.state.auto_archive_pass() == [EID]


def test_stale_auto_archive_snapshot_rechecks_restore_marker(cfg, monkeypatch):
    from auto_short.web import app as app_module
    make_episode(cfg, archived=False)
    for clip in ("k01", "k02"):
        set_published(EID, cfg, clip, True)
    old_rows = episode_sizes(cfg)
    old_rows[0]["complete_since"] = NOW - 10000
    archive_source(EID, cfg)
    restore_source(EID, cfg, downloader=downloader(), now=STAMP)
    monkeypatch.setattr(app_module, "episode_sizes", lambda *a: old_rows)
    assert app_for(cfg).state.auto_archive_pass() == []


def test_route_statuses_duplicate_sibling_and_busy_guards(cfg):
    make_episode(cfg, height=1080)
    make_episode(cfg, KT)
    app = app_for(cfg, restore_downloader=downloader())
    route = endpoint(app, "api_restore_source")
    assert route("missing").status_code == 404
    first = route(KT)
    assert first.status_code == 202 and body(first)["job"]["kind"] == KIND_RESTORE_SOURCE
    again = route(EID)
    assert again.status_code == 200 and body(again)["job"]["id"] == body(first)["job"]["id"]
    assert endpoint(app, "api_episode")(EID)["restore_job"]["id"] == body(first)["job"]["id"]
    assert endpoint(app, "api_episode")(KT)["restore_job"]["id"] == body(first)["job"]["id"]
    for name in ("api_archive", "api_episode_delete", "api_episode_vertical_make"):
        assert endpoint(app, name)(KT).status_code == 409
    runner = app.state.runner
    assert runner.jobs()[0].steps[0].lane == "prepare"
    runner.start()
    try:
        assert runner.wait_idle(5)
        assert runner.jobs()[0].status == "done"
        assert route(EID).status_code == 409
    finally:
        runner.stop()


def test_route_unrestorable_422_and_conflicting_job_409(cfg):
    folder = make_episode(cfg)
    app = app_for(cfg)
    app.state.runner.submit(KT, "render", lambda job: None)
    route = endpoint(app, "api_restore_source")
    assert route(EID).status_code == 409
    other = app_for(cfg)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["source"]["kind"] = "local"
    (folder / "manifest.json").write_text(json.dumps(manifest))
    assert endpoint(other, "api_restore_source")(EID).status_code == 422


def test_queued_restore_is_rebuilt_after_restart(cfg):
    make_episode(cfg)
    make_episode(cfg, KT)
    original = app_for(cfg, restore_downloader=downloader())
    assert endpoint(original, "api_restore_source")(KT).status_code == 202
    restarted = app_for(cfg, restore_downloader=downloader())
    runner = restarted.state.runner
    runner.restore()
    (job,) = runner.jobs()
    assert job.kind == KIND_RESTORE_SOURCE and job.steps[0].lane == "prepare"
    assert job.target.episode_id == KT and job.episode_id == EID
    runner.start()
    try:
        assert runner.wait_idle(5) and job.status == "done"
        for eid in (EID, KT):
            check_not_archived(Path(cfg.workspace.dir) / eid, eid)
    finally:
        runner.stop()


def test_publication_uses_submit_lock_and_sweep_cannot_remove_restored_files(cfg, monkeypatch):
    from auto_short.review import archive
    folder = make_episode(cfg)
    seed_cache(cfg)
    app = app_for(cfg, restore_downloader=no_download)
    endpoint(app, "api_restore_source")(EID)
    (job,) = app.state.runner.jobs()
    # A late failure callback of a previous vertical job must respect the restore reservation too.
    (folder / "source.webm").write_bytes(DATA)
    app.state.runner.on_vertical_failed(SimpleNamespace(episode_id=EID))
    assert (folder / "source.webm").exists()
    lock = job.target.lock
    original = archive.atomic_write_json

    def guarded_write(path, doc):
        if path.name == "restored.json":
            assert lock.locked()
            assert (folder / "source.webm").read_bytes() == DATA
            assert (folder / "archive.json").exists()
        return original(path, doc)

    monkeypatch.setattr(archive, "atomic_write_json", guarded_write)
    job.target(job)
    assert app.state.sweep_refetched() == 0
    assert (folder / "source.webm").exists()


def test_job_failure_message_and_disk_check(cfg):
    make_episode(cfg)
    runner = JobRunner()
    bad, _ = runner.submit(EID, KIND_RESTORE_SOURCE, RestoreSourceTarget(cfg, EID, downloader=downloader(b"bad")))
    runner.start()
    try:
        assert runner.wait_idle(5)
        assert bad.status == "failed" and "video tải lại khác bản gốc" in bad.error
    finally:
        runner.stop()
    target = RestoreSourceTarget(cfg, EID, downloader=no_download, disk_blocked=lambda: "dưới 3 GB")
    with pytest.raises(JobFailed, match="dưới 3 GB"):
        target(Job(id="x", episode_id=EID, kind=KIND_RESTORE_SOURCE, target=target))


def test_youtube_block_waits_then_retries_without_unarchiving(cfg):
    folder = make_episode(cfg)
    calls = []
    blocked = threading.Event()

    def fetch(uri, dest, ingest):
        calls.append(uri)
        if len(calls) == 1:
            blocked.set()
            raise YoutubeBlocked("bot check")
        return downloader()(uri, dest, ingest)

    runner = JobRunner(youtube_retry_seconds=60, youtube_retry_max_seconds=60)
    job, _ = runner.submit(EID, KIND_RESTORE_SOURCE, RestoreSourceTarget(cfg, EID, downloader=fetch))
    runner.start()
    try:
        assert blocked.wait(3)
        deadline = time.monotonic() + 3
        while not job.yt_wait and time.monotonic() < deadline:
            time.sleep(.01)
        assert job.active and job.yt_wait and runner.youtube_status()["blocked"]
        assert (folder / "archive.json").exists() and not (folder / "source.webm").exists()
        with runner._lock:
            runner._yt_next = 0
            runner._lock.notify_all()
        assert runner.wait_idle(5)
        assert job.status == "done" and len(calls) == 2
        assert not runner.youtube_status()["blocked"]
    finally:
        runner.stop()


def test_cache_restore_runs_while_youtube_is_blocked(cfg):
    make_episode(cfg)
    seed_cache(cfg)
    runner = JobRunner()
    with runner._lock:
        runner._set_yt_blocked_locked("bot check")
    job, _ = runner.submit(EID, KIND_RESTORE_SOURCE, RestoreSourceTarget(cfg, EID, downloader=no_download))
    runner.start()
    try:
        assert runner.wait_idle(5) and job.status == "done"
        assert runner.youtube_status()["blocked"]  # cache access does not claim YouTube recovered
    finally:
        runner.stop()


def test_http_auth_and_restore(cfg):
    from fastapi.testclient import TestClient
    make_episode(cfg)
    with TestClient(app_for(cfg, restore_downloader=downloader()), follow_redirects=False) as client:
        url = f"/api/episodes/{EID}/restore-source"
        assert client.post(url).status_code == 401
        assert client.post("/login", data={"password": "pw"}).status_code == 303
        assert client.post(url).status_code == 202
        assert client.app.state.runner.wait_idle(5)
        view = client.get(f"/api/episodes/{EID}").json()
        assert view["archived"] is None and view["restore_job"]["status"] == "done"
        assert client.post(url).status_code == 409
