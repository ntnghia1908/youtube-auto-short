"""SRC1: no sockets, no downloads; verify uploads, ordering and deletion against the actual local bytes."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short.config import StoreConfig
from auto_short.review import ReviewError, archive_source
from auto_short.store import backup
from auto_short.store.client import StoreClient, StoreMismatch, StoreUnavailable
from auto_short.workspace import atomic_write_json

from web_helpers import write_episode

VID = "abcDEF12_-3"
OTHER = "zyxWVUT9876"
THIRD = "aaaaaaaaaaa"
DATA = b"original-source"


class MemoryStore:
    def __init__(self):
        self.files = {}
        self.uploads = []
        self.down = False

    def head(self, video_id, kind):
        assert kind == "source"
        if self.down:
            raise StoreUnavailable("3090 đang tắt")
        if video_id not in self.files:
            raise StoreMismatch("chưa có file")
        data = self.files[video_id]
        return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}

    def put(self, video_id, kind, series, name, path, sha256):
        assert sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        self.uploads.append((video_id, kind, series, name, path))
        self.files[video_id] = path.read_bytes()

    def fetch(self, video_id, kind, dest, sha256):
        info = self.head(video_id, kind)
        if info["sha256"] != sha256:
            raise StoreMismatch("khác sha")
        dest.write_bytes(self.files[video_id])
        return dest


@pytest.fixture
def bcfg(cfg):
    return replace(cfg, store=StoreConfig(enabled=True, backup_source=True))


def seed(config, vid=VID, *, data=DATA, kind="youtube"):
    write_episode(config, vid)
    folder = Path(config.workspace.dir) / vid
    path = folder / "source.mp4"
    path.write_bytes(data)
    doc = json.loads((folder / "manifest.json").read_text())
    doc["source"].update(kind=kind, path=path.name, size=len(data),
                         sha256=hashlib.sha256(data).hexdigest())
    atomic_write_json(folder / "manifest.json", doc)
    return path


def cache(config, vid=VID, data=b"redownloaded-source"):
    source = json.loads((Path(config.workspace.dir) / vid / "manifest.json").read_text())["source"]
    folder = Path(config.workspace.dir) / "_theme_sources" / vid
    folder.mkdir(parents=True)
    path = folder / "source.mp4"
    path.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    atomic_write_json(folder / "meta.json", dict(schema_version=1, video_id=vid, file=path.name,
        uri=source["uri"], ingest_sha256=source["sha256"], sha256=sha,
        differs_from_ingest=sha != source["sha256"], duration=3600, height=360, size=len(data),
        downloaded_at="2026-10-25T00:00:00Z"))
    return path


def test_push_workspace_name_head_and_idempotent(bcfg):
    path = seed(bcfg)
    atomic_write_json(Path(bcfg.workspace.dir) / "_playlists" / "PLtest.json",
                      dict(series="Kinh Vô Lượng Thọ", entries=[dict(video_id=VID)]))
    client = MemoryStore()
    assert backup.push_source(bcfg, VID, client=client)["backed_up"]
    assert client.uploads == [(VID, "source", "PLtest", "[Goc] Kinh Vô Lượng Thọ - Tập 3.mp4", path)]
    assert backup.push_source(bcfg, VID, client=client)["backed_up"]
    assert len(client.uploads) == 1


def test_push_verified_cache_real_sha_and_fallback_name(bcfg):
    original = seed(bcfg)
    original.write_bytes(b"corrupt")
    cached = cache(bcfg)
    atomic_write_json(original.parent / "metadata.json", dict(duration=3600, title="Không có số tập"))
    client = MemoryStore()
    state = backup.push_source(bcfg, VID, client=client)
    assert state["sha256"] == hashlib.sha256(cached.read_bytes()).hexdigest()
    assert client.uploads[0][2:] == ("_khac", f"[Goc] {VID}.mp4", cached)
    assert not backup.backup_state(bcfg, VID, client=client, path=original)["backed_up"]


def test_missing_local_uses_expected_ingest_and_never_downloads(bcfg):
    seed(bcfg).unlink()
    client = MemoryStore()
    client.files[VID] = DATA
    assert backup.backup_state(bcfg, VID, client=client)["backed_up"]
    with pytest.raises(StoreMismatch, match="không còn"):
        backup.push_source(bcfg, VID, client=client)


def test_khaithi_only_youtube_owner_is_included_once(bcfg):
    seed(bcfg, VID + ".kt")
    client = MemoryStore()
    assert backup.source_inventory(bcfg) == [VID]
    assert backup.push_source(bcfg, VID, client=client)["backed_up"]
    assert client.uploads[0][0] == VID


@pytest.mark.parametrize("failure", ["missing", "sha", "size", "down", "disabled", "cache", "extra"])
def test_archive_fails_closed_without_writes(bcfg, monkeypatch, failure):
    path = seed(bcfg)
    client = MemoryStore()
    client.files[VID] = DATA
    if failure == "missing":
        client.files.clear()
    elif failure == "sha":
        client.files[VID] = b"x" * len(DATA)
    elif failure == "size":
        client.files[VID] = DATA + b"x"
    elif failure == "down":
        client.down = True
    elif failure == "disabled":
        bcfg = replace(bcfg, store=replace(bcfg.store, enabled=False))
    elif failure == "cache":
        client.files[VID] = cache(bcfg).read_bytes()
    elif failure == "extra":
        (path.parent / "source.part").write_bytes(b"extra")
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: client)
    before = {p: p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
    with pytest.raises(ReviewError, match="chưa sao lưu lên 3090"):
        archive_source(VID, bcfg, auto=True)
    assert {p: p.read_bytes() for p in path.parent.iterdir() if p.is_file()} == before


def test_archive_exact_sha_size_records_backup(bcfg, monkeypatch):
    path = seed(bcfg)
    client = MemoryStore()
    client.files[VID] = DATA
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: client)
    result = archive_source(VID, bcfg, auto=True)
    assert result.changed and result.freed == len(DATA) and not path.exists()
    doc = json.loads((path.parent / "archive.json").read_text())
    assert doc["backup"] == dict(store="source", sha256=hashlib.sha256(DATA).hexdigest())
    assert doc["auto"] is True


def test_archive_rechecks_bytes_changed_during_head(bcfg, monkeypatch):
    path = seed(bcfg)
    client = MemoryStore()
    client.files[VID] = DATA
    real_head = client.head

    def head(*args):
        info = real_head(*args)
        path.write_bytes(b"x" * len(DATA))
        return info

    client.head = head
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: client)
    with pytest.raises(ReviewError, match="chưa sao lưu lên 3090"):
        archive_source(VID, bcfg)
    assert path.exists() and not (path.parent / "archive.json").exists()


def test_backup_disabled_archive_does_not_contact_store(bcfg, monkeypatch):
    path = seed(bcfg)
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: pytest.fail("store contacted"))
    config = replace(bcfg, store=replace(bcfg.store, backup_source=False))
    assert archive_source(VID, config).changed
    assert "backup" not in json.loads((path.parent / "archive.json").read_text())


def test_order_deadlines_then_favorites_skip_backed_and_local(bcfg, monkeypatch):
    from auto_short.web import storage

    for vid in (VID, OTHER, THIRD):
        seed(bcfg, vid)
    local = "bbbbbbbbbbb"
    seed(bcfg, local, kind="local")
    archived = "ccccccccccc"
    seed(bcfg, archived).unlink()
    cache(bcfg, OTHER)
    (Path(bcfg.workspace.dir) / OTHER / "source.mp4").unlink()
    monkeypatch.setattr(backup, "favorite_videos", lambda cfg: [OTHER])
    monkeypatch.setattr(storage, "auto_archive_plan", lambda rows, now, grace: [dict(video_id=VID, since=10)])
    client = MemoryStore()
    states = {}
    assert backup.backup_order(bcfg, client=client, states=states) == [VID, OTHER, THIRD]
    assert set(states) == {VID, OTHER, THIRD, archived}
    client.files[VID] = DATA
    assert backup.backup_order(bcfg, client=client) == [OTHER, THIRD]
    client.down = True
    with pytest.raises(StoreUnavailable):
        backup.backup_order(bcfg, client=client)


def test_background_one_upload_cache_report_and_render_pause(bcfg, monkeypatch):
    from auto_short.web.app import create_app

    seed(bcfg)
    seed(bcfg, OTHER)
    app = create_app(bcfg, "pw", preflight=None, post_preflight=None,
                     disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9))
    client = MemoryStore()
    assert len(app.state.source_backup_pass(client)) == 1
    assert len(client.uploads) == 1
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: pytest.fail("request contacted store"))
    report = app.state.storage.report()
    assert report["source_backup"] == dict(backed_up=1, total=2, pending=1)
    monkeypatch.setattr(app.state.runner, "running", lambda: {"render": object()})
    assert app.state.source_backup_pass(client) == [] and len(client.uploads) == 1
    monkeypatch.setattr(app.state.runner, "running", lambda: {})
    client.down = True
    assert app.state.source_backup_pass(client) == []
    assert app.state.storage.report()["source_backup"] == report["source_backup"]


def test_auto_archive_waits_for_source_backup(bcfg, monkeypatch):
    import time
    from auto_short.review import set_published
    from auto_short.web.app import create_app

    path = seed(bcfg)
    for clip in ("k01", "k02"):
        set_published(VID, bcfg, clip, True)
    client = MemoryStore()
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: client)
    now = time.time() + bcfg.storage.auto_archive_grace_minutes * 60 + 10
    app = create_app(bcfg, "pw", preflight=None, post_preflight=None, clock=lambda: now)
    assert app.state.auto_archive_pass() == [] and path.exists()
    assert not (path.parent / "archive.json").exists()
    client.files[VID] = DATA
    assert app.state.auto_archive_pass() == [VID] and not path.exists()


@pytest.mark.parametrize("error", [StoreMismatch("HTTP 409"), StoreUnavailable("URLError sending body")])
def test_one_conflicting_backup_does_not_starve_other_videos(bcfg, error):
    from auto_short.web.app import create_app

    seed(bcfg)
    seed(bcfg, OTHER)
    app = create_app(bcfg, "pw", preflight=None, post_preflight=None)
    client = MemoryStore()
    real_put = client.put

    def put(vid, *args):
        if vid == VID:
            raise error
        return real_put(vid, *args)

    client.put = put
    assert app.state.source_backup_pass(client) == []
    assert app.state.source_backup_pass(client) == [OTHER]


def test_ingest_on_store_satisfies_backup_even_with_different_cache(bcfg):
    seed(bcfg).unlink()
    cached = cache(bcfg)
    client = MemoryStore()
    client.files[VID] = DATA
    state = backup.backup_state(bcfg, VID, client=client)
    assert state["backed_up"] and state["sha256"] == hashlib.sha256(DATA).hexdigest()
    assert backup.backup_order(bcfg, client=client) == []
    assert backup.push_source(bcfg, VID, client=client)["backed_up"] and not client.uploads
    assert not backup.backup_state(bcfg, VID, client=client, path=cached)["backed_up"]


def test_order_memo_skips_unchanged_hashes_and_confirmed_heads(bcfg, monkeypatch):
    import os
    from auto_short import hashing

    path = seed(bcfg)
    seed(bcfg, OTHER)
    client = MemoryStore()
    client.files[VID] = DATA
    hashes, heads = [], []
    real_hash, real_head = hashing.sha256_file, client.head

    def digest(path):
        hashes.append(path)
        return real_hash(path)

    def head(vid, kind):
        heads.append(vid)
        return real_head(vid, kind)

    monkeypatch.setattr(hashing, "sha256_file", digest)
    monkeypatch.setattr(backup, "sha256_file", digest)
    client.head = head
    assert backup.backup_order(bcfg, client=client) == [OTHER]
    assert len(hashes) == 2 and heads == [VID, OTHER]
    hashes.clear()
    heads.clear()
    assert backup.backup_order(bcfg, client=client) == [OTHER]
    assert hashes == [] and heads == [OTHER]
    stamp = path.stat().st_mtime_ns
    os.utime(path, ns=(stamp + 1000000, stamp + 1000000))
    backup.backup_order(bcfg, client=client)
    assert hashes == [path.resolve()]
    hashes.clear()
    path.write_bytes(DATA + b"changed size")
    assert backup.backup_order(bcfg, client=client) == [OTHER]
    assert hashes == [path.resolve()]


def test_cache_provenance_and_duration_changes_invalidate_memo(bcfg, monkeypatch):
    from auto_short import hashing

    original = seed(bcfg)
    original.unlink()
    cached = cache(bcfg)
    client = MemoryStore()
    client.files[VID] = cached.read_bytes()
    assert backup.backup_state(bcfg, VID, client=client)["backed_up"]
    hashes = []
    real_hash = hashing.sha256_file

    def digest(path):
        hashes.append(path)
        return real_hash(path)

    monkeypatch.setattr(hashing, "sha256_file", digest)
    meta_path = cached.parent / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["downloaded_at"] = "2026-10-26T00:00:00Z"
    atomic_write_json(meta_path, meta)
    assert backup.backup_state(bcfg, VID, client=client)["backed_up"] and hashes == [cached.resolve()]
    atomic_write_json(original.parent / "metadata.json", dict(duration=100))
    assert not backup.backup_state(bcfg, VID, client=client)["backed_up"]


def test_push_reuses_order_digest_and_only_heads_after_put(bcfg, monkeypatch):
    from auto_short import hashing

    seed(bcfg)
    client = MemoryStore()
    assert backup.backup_order(bcfg, client=client) == [VID]

    def forbidden(*args):
        pytest.fail("unchanged source was hashed again during/after PUT")

    monkeypatch.setattr(hashing, "sha256_file", forbidden)
    monkeypatch.setattr(backup, "sha256_file", forbidden)
    assert backup.push_source(bcfg, VID, client=client)["backed_up"]
    assert len(client.uploads) == 1
    assert backup.backup_order(bcfg, client=client) == []


def test_cold_push_hashes_selected_source_only_once(bcfg, monkeypatch):
    from auto_short import hashing

    path = seed(bcfg)
    client = MemoryStore()
    hashes = []
    real_hash = hashing.sha256_file

    def digest(path):
        hashes.append(path)
        return real_hash(path)

    monkeypatch.setattr(hashing, "sha256_file", digest)
    monkeypatch.setattr(backup, "sha256_file", digest)
    assert backup.push_source(bcfg, VID, client=client)["backed_up"]
    assert hashes == [path.resolve()]


def test_archive_ignores_scheduling_confirmation_memo(bcfg, monkeypatch):
    path = seed(bcfg)
    client = MemoryStore()
    client.files[VID] = DATA
    assert backup.backup_order(bcfg, client=client) == []
    hashes = []
    real_hash = backup.sha256_file

    def digest(path):
        hashes.append(path)
        return real_hash(path)

    monkeypatch.setattr(backup, "sha256_file", digest)
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: client)
    assert backup.backup_state(bcfg, VID, client=client, path=path)["backed_up"]
    assert hashes == [path]
    client.down = True
    with pytest.raises(ReviewError, match="chưa sao lưu lên 3090"):
        archive_source(VID, bcfg)
    assert path.exists() and not (path.parent / "archive.json").exists()


def test_background_io_uses_thread_and_waits_retry_seconds(bcfg, monkeypatch):
    import asyncio
    import threading
    from auto_short.web.app import create_app

    seed(bcfg)
    bcfg = replace(bcfg, storage=replace(bcfg.storage, auto_archive=False))
    entered, release = threading.Event(), threading.Event()
    threads, sleeps = [], []
    main_thread = threading.get_ident()
    client = MemoryStore()

    def head(*args):
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(3), "backup blocked the event loop"
        raise StoreUnavailable("down")

    client.head = head
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: client)
    app = create_app(bcfg, "pw", preflight=None, post_preflight=None)
    for name in ("start", "stop"):
        monkeypatch.setattr(app.state.runner, name, lambda: None)
        monkeypatch.setattr(app.state.monitor_sampler, name, lambda: None)
    real_sleep = asyncio.sleep

    async def run():
        waiting = asyncio.Event()

        async def sleep(delay):
            if asyncio.current_task().get_coro().__name__ == "_source_backup_loop":
                sleeps.append(delay)
                waiting.set()
            await real_sleep(delay)

        monkeypatch.setattr(asyncio, "sleep", sleep)
        try:
            async with app.router.lifespan_context(app):
                assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 1), 2)
                release.set()
                await asyncio.wait_for(waiting.wait(), 2)
                assert len(threads) == 1 and threads[0] != main_thread
                assert sleeps == [bcfg.store.retry_seconds]
        finally:
            release.set()

    asyncio.run(run())
