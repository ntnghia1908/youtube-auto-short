"""SRC4 G5/G6: store-first ingest and prepare scheduling, without sockets."""

import hashlib
import io
import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest

from auto_short import hashing, khaithi
from auto_short.ingest import IngestBlocked, needs_download, run_ingest
from auto_short.ingest.source import classify
from auto_short.ingest.stage import _used_config
from auto_short.ingest.youtube import YoutubeBlocked
from auto_short.store import index_cache
from auto_short.store.client import StoreClient, StoreUnavailable
from auto_short.titling.playlist import PLAYLISTS_DIR
from auto_short.web.jobs import DONE, KIND_PIPELINE, QUEUED, JobRunner, pipeline_target

from test_ingest_youtube import FakeDownloader, INFO, URL
from test_youtube_wait import Clock, Net, blocked_error
from wait_helpers import wait_for

VID = "rbjfCfFq3Dk"
OTHER = "bbbbbbbbbbb"
TITLE = "Phật Thuyết Thập Thiện Nghiệp Đạo Kinh tập 19"


class MemoryStore(StoreClient):
    """Use the real fetch/SHA implementation; replace transport with bytes in memory."""

    def __init__(self, data):
        super().__init__("http://unused", "fake-token")
        self.data = data
        self.sha = hashlib.sha256(data).hexdigest()
        self.rows = [{"video_id": VID, "kind": "source", "file": "[Goc] Tập 9.mp4"}]
        self.calls = []
        self.failure = None

    def index(self):
        self.calls.append("index")
        if self.failure == "index":
            raise StoreUnavailable("offline")
        return self.rows

    def head(self, video_id, kind):
        self.calls.append("head")
        assert (video_id, kind) == (VID, "source")
        if self.failure == "head":
            raise StoreUnavailable("offline")
        return {"size": len(self.data), "sha256": self.sha}

    def fetch(self, video_id, kind, dest, sha256):
        self.calls.append("fetch")
        if self.failure in ("fetch", "file"):
            dest.with_suffix(dest.suffix + ".part").write_bytes(b"partial")
            error = StoreUnavailable if self.failure == "fetch" else OSError
            raise error("interrupted")
        return super().fetch(video_id, kind, dest, sha256)

    def _open(self, path, **kwargs):
        self.calls.append("get")
        response = io.BytesIO(self.data)
        response.status = 200
        return response


@pytest.fixture(autouse=True)
def isolated_cache_and_no_sockets(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("SRC4 tests must not open sockets")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    index_cache.invalidate()
    yield
    wait_for(lambda: index_cache._REFRESHING is None, what="store refresh finished")
    index_cache.invalidate()


@pytest.fixture
def store(video, cfg, monkeypatch):
    client = MemoryStore(video.read_bytes())
    monkeypatch.setattr(StoreClient, "from_config", classmethod(lambda cls, config: client))
    playlists = cfg.workspace.dir / PLAYLISTS_DIR
    playlists.mkdir(parents=True)
    (playlists / "lecture.json").write_text(json.dumps({"entries": [{"video_id": VID, "title": TITLE}]}),
                                           encoding="utf-8")
    return replace(cfg, store=replace(cfg.store, enabled=True)), client


def test_store_ingest_and_skip_preserve_cache_key(store, video):
    config, client = store
    downloader = FakeDownloader(video)
    result = run_ingest(f"https://www.youtube.com/watch?v={VID}&t=4", config, downloader=downloader)
    manifest = json.loads((result.workspace / "manifest.json").read_text())
    source = manifest["source"]
    assert result.ran and not downloader.calls
    assert source["uri"] == URL and source["kind"] == "youtube" and source["via"] == "store"
    assert source["path"] == "source.mp4"
    assert source["sha256"] == hashing.sha256_file(result.workspace / source["path"]) == client.sha
    assert source["size"] == len(client.data)
    meta = json.loads((result.workspace / "metadata.json").read_text())
    assert meta["source"]["sha256"] == source["sha256"]
    assert meta["youtube"]["id"] == VID and meta["duration"] == 2
    assert meta["title"] == meta["youtube"]["title"] == TITLE
    assert meta["channel"] is None and meta["youtube"]["channel"] is None
    assert not (result.workspace / ".ingest-tmp").exists()
    assert manifest["stages"]["ingest"]["config_hash"] == hashing.config_hash(_used_config(classify(URL), config))
    client.calls.clear()
    disabled = replace(config, store=replace(config.store, enabled=False))
    assert not run_ingest(URL, disabled, downloader=downloader).ran
    assert needs_download(URL, config) is False
    assert not client.calls and not downloader.calls


def test_store_extension_and_khaithi_reuse_before_store(store, video, monkeypatch):
    config, client = store
    client.rows[0]["file"] = "[Goc] source.mkv"
    result = run_ingest(URL, config, downloader=FakeDownloader(video))
    assert (result.workspace / "source.mkv").is_file()
    kt_dir = config.workspace.dir / (VID + ".kt")
    kt_dir.mkdir()
    khaithi.write(kt_dir, khaithi.KhaiThi(VID, 4, 10))

    def forbidden(config):
        pytest.fail("reuse must precede any store access")

    index_cache.invalidate()
    monkeypatch.setattr(StoreClient, "from_config", forbidden)
    downloader = FakeDownloader(video)
    assert needs_download(URL, config, VID + ".kt") is False
    reused = run_ingest(URL, config, episode_id=VID + ".kt", downloader=downloader)
    assert (reused.workspace / "source.mkv").read_bytes() == client.data
    assert not downloader.calls


@pytest.mark.parametrize("document", [None, "invalid JSON", [], {"entries": None},
                                    {"entries": [{"video_id": OTHER, "title": TITLE}]},
                                    {"entries": [{"video_id": VID, "title": "  "}]},
                                    {"entries": [{"video_id": VID, "title": 19}]}])
def test_missing_playlist_title_falls_back_to_youtube(store, video, document):
    config, client = store
    path = config.workspace.dir / PLAYLISTS_DIR / "lecture.json"
    if document is None:
        path.unlink()
    else:
        path.write_text(document if isinstance(document, str) else json.dumps(document), encoding="utf-8")
    assert index_cache.has_source(config, VID)  # even a known store hit is unusable without a title
    assert needs_download(URL, config) is True
    downloader = FakeDownloader(video)
    result = run_ingest(URL, config, downloader=downloader)
    meta = json.loads((result.workspace / "metadata.json").read_text())
    source = json.loads((result.workspace / "manifest.json").read_text())["source"]
    assert downloader.calls == [(URL, config.ingest.youtube_format)]
    assert meta["title"] == INFO["title"] and "via" not in source
    assert client.calls == ["index"]  # missing title never fetches from the store


@pytest.mark.parametrize("failure", ["disabled", "missing", "index", "head", "fetch", "sha", "media", "file"])
def test_store_fallback_cleans_temporary_files(store, video, failure, monkeypatch):
    config, client = store
    if failure == "disabled":
        config = replace(config, store=replace(config.store, enabled=False))
        monkeypatch.setattr(StoreClient, "from_config", lambda cfg: pytest.fail("disabled store created client"))
    elif failure == "missing":
        client.rows = []
    elif failure == "sha":
        client.sha = "0" * 64
    elif failure == "media":
        client.data = b"not a media file"
        client.sha = hashlib.sha256(client.data).hexdigest()
    else:
        client.failure = failure
    downloader = FakeDownloader(video)

    def download(url, dest, cfg):
        assert list(dest.iterdir()) == []  # no .part or corrupt store file reaches yt-dlp
        return downloader(url, dest, cfg)

    result = run_ingest(URL, config, downloader=download)
    source = json.loads((result.workspace / "manifest.json").read_text())["source"]
    assert downloader.calls == [(URL, config.ingest.youtube_format)]
    assert "via" not in source and source["sha256"] == hashing.sha256_file(video)
    assert sorted(p.name for p in result.workspace.iterdir()) == ["manifest.json", "metadata.json", "source.mp4"]


def test_fallback_retains_ingest_blocked(store):
    config, client = store
    client.failure = "fetch"

    def blocked(url, dest, cfg):
        assert not list(dest.iterdir())
        raise YoutubeBlocked("bot check")

    with pytest.raises(IngestBlocked, match="bot check"):
        run_ingest(URL, config, downloader=blocked)
    assert sorted(p.name for p in (config.workspace.dir / VID).iterdir()) == ["manifest.json"]


def test_index_ttl_shared_hits_misses_and_invalidation(store, monkeypatch):
    config, client = store
    clock = Clock()
    monkeypatch.setattr(index_cache, "time", SimpleNamespace(monotonic=clock.mono))
    assert index_cache.has_source(config, VID)  # populate the snapshot outside the scheduler
    assert needs_download(URL, config) is False
    assert needs_download(f"https://youtu.be/{OTHER}", config) is True
    client.rows.clear()
    clock.t = 299.9
    assert needs_download(URL, config) is False and client.calls == ["index"]
    clock.t = 300
    assert needs_download(URL, config) is False  # expired snapshot is returned while refreshing
    wait_for(lambda: needs_download(URL, config) is True)
    assert client.calls == ["index", "index"]
    index_cache.invalidate()
    assert not index_cache.has_source(config, VID)
    assert client.calls == ["index"] * 3


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_needs_download_refresh_never_blocks_scheduler(store, monkeypatch, warm, fails):
    config, client = store
    clock = Clock()
    monkeypatch.setattr(index_cache, "time", SimpleNamespace(monotonic=clock.mono))
    if warm:
        assert index_cache.has_source(config, VID)
        clock.t = 300
    entered, release = threading.Event(), threading.Event()
    refresh_threads = []

    def gated_index():
        refresh_threads.append(threading.get_ident())
        entered.set()
        if not release.wait(5):
            raise AssertionError("test failed to release store index")
        if fails:
            raise StoreUnavailable("offline")
        return client.rows

    monkeypatch.setattr(client, "index", gated_index)
    try:
        with ThreadPoolExecutor(max_workers=1) as scheduler:
            def check():
                return threading.get_ident(), needs_download(URL, config)

            caller, downloads = scheduler.submit(check).result(timeout=1)
            assert downloads is (not warm)  # cold -> True, stale hit -> False
            assert entered.wait(1)
            for _ in range(8):
                assert needs_download(URL, config) is (not warm)
            assert len(refresh_threads) == 1 and refresh_threads[0] != caller
    finally:
        release.set()
        wait_for(lambda: index_cache._REFRESHING is None, what="gated refresh finished")
    assert needs_download(URL, config) is fails
    assert len(refresh_threads) == 1  # failures also receive a fresh TTL


@pytest.mark.parametrize("failure", ["offline", "malformed"])
def test_index_errors_are_cached_and_never_raise(store, failure):
    config, client = store
    if failure == "offline":
        client.failure = "index"
    else:
        client.rows = None
    assert not index_cache.has_source(config, VID)
    assert needs_download(URL, config) is True
    assert client.calls == ["index"]


def test_index_concurrent_checks_and_store_isolation(store):
    config, client = store
    with ThreadPoolExecutor(max_workers=8) as workers:
        assert all(workers.map(lambda _: index_cache.has_source(config, VID), range(24)))
    assert client.calls == ["index"]
    other_store = replace(config, store=replace(config.store, url="http://other-unused"))
    client.rows.clear()
    assert not index_cache.has_source(other_store, VID)
    assert index_cache.has_source(config, VID)
    disabled = replace(config, store=replace(config.store, enabled=False))
    assert not index_cache.has_source(disabled, VID)
    assert client.calls == ["index", "index"]


@pytest.mark.parametrize("fails", [False, True])
def test_refresh_listeners_run_after_publish_outside_cache_lock(store, caplog, fails):
    config, client = store
    if fails:
        client.failure = "index"
    observed = []
    notified, broken_called = threading.Event(), threading.Event()

    def inspect_from_another_thread():
        acquired = index_cache._CHANGED.acquire(timeout=0.5)
        if not acquired:
            return "cache lock held during callback"
        try:
            return index_cache.has_source(config, VID, blocking=False)
        finally:
            index_cache._CHANGED.release()

    def listener():
        try:
            with ThreadPoolExecutor(max_workers=1) as reader:
                observed.append(reader.submit(inspect_from_another_thread).result(timeout=1))
        finally:
            notified.set()

    def broken():
        broken_called.set()
        raise ValueError("listener failure")

    caplog.set_level("DEBUG", logger="auto_short")
    index_cache.add_listener(listener)
    index_cache.add_listener(listener)  # registration is idempotent
    index_cache.add_listener(broken)
    try:
        assert index_cache.has_source(config, VID) is (not fails)
        assert notified.wait(2) and broken_called.wait(2)
        assert observed == [not fails]
        wait_for(lambda: "store index listener failed" in caplog.text)
    finally:
        index_cache.remove_listener(listener)
        index_cache.remove_listener(broken)


def test_runner_start_registers_once_and_stop_removes_listener():
    before = set(index_cache._LISTENERS)
    runner = JobRunner()
    try:
        for _ in range(2):  # restarting must re-register without retaining an old callback
            runner.start()
            runner.start()
            assert index_cache._LISTENERS == before | {runner._store_index_refreshed}
            runner.stop(timeout=5)
            assert index_cache._LISTENERS == before
    finally:
        runner.stop(timeout=5)


def test_prepare_from_store_runs_while_youtube_blocked(store):
    config, client = store
    clock, pipeline = Clock(), Net(blocked_error())
    runner = JobRunner(youtube_retry_seconds=900, monotonic=clock.mono, wall=clock.wall)
    runner.start()
    try:
        waiting = runner.submit(OTHER, KIND_PIPELINE, pipeline_target(
            f"https://youtu.be/{OTHER}", config, pipeline=pipeline, preflight=None))[0]
        wait_for(lambda: runner.youtube_status()["blocked"])
        before = runner.youtube_status()
        pipeline.reuse.add(VID)  # fake pipeline's ingest succeeds without going to YouTube
        ready = runner.submit(VID, KIND_PIPELINE, pipeline_target(
            URL, config, pipeline=pipeline, preflight=None))[0]
        wait_for(lambda: ready.status == DONE)
        assert waiting.status == QUEUED and pipeline.ingests().count(OTHER) == 1
        assert runner.youtube_status() == before  # store success does not clear YouTube's backoff
        assert client.calls == ["index"]
    finally:
        runner.stop(timeout=5)
