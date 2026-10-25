"""SRC2 acceptance checks: fake downloader/store only, without sockets."""
import asyncio
import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_short.compilation import store as favorites_store
from auto_short.compilation.spec import Item
from auto_short.config import StoreConfig
from auto_short.ingest.youtube import Download, DownloadError, YoutubeBlocked
from auto_short.store import redownload as rd
from auto_short.store.client import StoreClient, StoreUnavailable
from auto_short.theme_render import sources as sc
from auto_short.workspace import atomic_write_json
from web_helpers import write_episode

VIDS = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd", "eeeeeeeeeee", "fffffffffff"]
ORIGINAL, DOWNLOADED = b"ingest bytes", b"new downloaded bytes"


def forbidden(*args, **kwargs):
    pytest.fail("unexpected I/O")


def enough_disk(path):
    return 100 * 10**9, 50 * 10**9, 50 * 10**9


class MemoryStore:
    def __init__(self):
        self.files, self.uploads, self.heads, self.index_calls = {}, [], [], 0
        self.down = False

    def index(self):
        self.index_calls += 1
        if self.down:
            raise StoreUnavailable("kho tắt")
        return [dict(video_id=vid, kind="source") for vid in self.files]

    def put(self, vid, kind, series, name, path, sha):
        assert kind == "source" and path.read_bytes() == DOWNLOADED
        assert sha == hashlib.sha256(DOWNLOADED).hexdigest()
        self.uploads.append((vid, series, name, path))
        self.files[vid] = path.read_bytes()

    def head(self, vid, kind):
        self.heads.append((vid, kind))
        data = self.files[vid]
        return dict(sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def seed(cfg, vid, *, archived=True, present=False, kind="youtube", title="Kinh Vô Lượng Thọ tập 3"):
    write_episode(cfg, vid, title=title)
    folder = cfg.workspace.dir / vid
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["source"].update(kind=kind, path="source.mp4", sha256=hashlib.sha256(ORIGINAL).hexdigest(),
                              size=len(ORIGINAL))
    atomic_write_json(folder / "manifest.json", manifest)
    if archived:
        atomic_write_json(folder / "archive.json", dict(schema_version=1, archived_at="2026-10-25T00:00:00Z"))
    if present:
        (folder / "source.mp4").write_bytes(ORIGINAL)
    return folder


def favorite(cfg, *ids):
    favorites_store.write_favorites(favorites_store.directory(cfg.render.output_dir, "PLtest"),
                                    [Item(vid, "k01") for vid in ids])


def download(uri, dest, config):
    path = dest / "download.webm"
    path.write_bytes(DOWNLOADED)
    (dest / "leftover.part").write_bytes(b"partial")
    return Download(path, {})


@pytest.fixture
def rcfg(cfg, monkeypatch):
    monkeypatch.setattr(sc.probe, "probe", lambda _: dict(duration=3600, height=720))
    monkeypatch.setattr(rd.shutil, "which", lambda _: "/bin/node")
    return replace(cfg, store=StoreConfig(enabled=True, redownload=True),
                   storage=replace(cfg.storage, auto_archive=False))


@pytest.fixture
def background(rcfg):
    from auto_short.web.app import create_app
    now = [0.0]
    app = create_app(rcfg, "pw", preflight=None, post_preflight=None, secret=b"test-secret",
                     disk_usage=enough_disk, clock=lambda: now[0])
    return app, now


def test_pending_inventory_order_single_index_and_local_only_dry_run(rcfg, monkeypatch, tmp_path, capsys):
    a, b, c, d, e, f = VIDS
    seed(rcfg, a, title="Kinh Vô Lượng Thọ tập 10")
    seed(rcfg, b, title="Kinh Vô Lượng Thọ tập 2")
    seed(rcfg, c, title="Kinh Vô Lượng Thọ tập 20")
    seed(rcfg, d, present=True)
    seed(rcfg, e)
    sc.fetch_to_cache(rcfg, e, download)
    seed(rcfg, f)
    seed(rcfg, "ggggggggggg", archived=False)
    seed(rcfg, "hhhhhhhhhhh", kind="local")
    seed(rcfg, "iiiiiiiiiii.kt")  # owner deduplicates; khai thị-only is supported
    favorite(rcfg, c + ".kt")
    atomic_write_json(rcfg.workspace.dir / "_playlists" / "PLtest.json",
                      dict(series="Kinh Vô Lượng Thọ", entries=[dict(video_id=vid) for vid in (a, b, c)]))
    client = MemoryStore()
    client.files[f] = ORIGINAL
    assert rd.pending(rcfg, client=client) == [c, b, a, "iiiiiiiiiii"]
    assert client.index_calls == 1 and not client.heads
    config = tmp_path / "config.toml"
    config.write_text(f'[workspace]\ndir = "{rcfg.workspace.dir}"\n[render]\noutput_dir = "{rcfg.render.output_dir}"\n')
    monkeypatch.setattr(StoreClient, "from_config", forbidden)
    monkeypatch.setattr(rd, "ytdlp_download", forbidden)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert rd.main(["--config", str(config), "--dry-run"]) == 0
    text = capsys.readouterr().out
    assert "chưa đối chiếu kho" in text and "5 video, 1 ♥" in text and "GB ước tính" in text
    assert text.index(c) < text.index(b) < text.index(a)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("keep", [False, True])
def test_step_exact_bytes_head_cache_provenance_and_cleanup(rcfg, keep):
    vid = VIDS[0]
    folder = seed(rcfg, vid)
    if keep:
        favorite(rcfg, vid)
    before = {p: p.read_bytes() for p in folder.iterdir()}
    client = MemoryStore()
    real_head = client.head
    def head(ident, kind):
        assert not (sc.cache_dir(rcfg) / vid / "meta.json").exists()
        assert client.uploads[0][3].is_file()
        return real_head(ident, kind)
    client.head = head
    result = rd.step(rcfg, vid, downloader=download, client=client, clock=lambda: 0, disk_usage=enough_disk)
    assert result["status"] == "done" and result["cached"] == keep and result["differs_from_ingest"]
    assert client.files == {vid: DOWNLOADED} and client.heads == [(vid, "source")]
    assert client.uploads[0][1:3] == ("_khac", "[Goc] Kinh Vô Lượng Thọ - Tập 3.mp4")
    assert not list(sc.cache_dir(rcfg).glob(".*"))
    if keep:
        path = sc.cached_source(rcfg, vid)
        assert path.read_bytes() == DOWNLOADED
        assert {p.name for p in path.parent.iterdir()} == {"source.webm", "meta.json"}
        meta = json.loads(path.with_name("meta.json").read_text())
        assert meta["ingest_sha256"] == hashlib.sha256(ORIGINAL).hexdigest()
        assert meta["sha256"] == result["sha256"] and meta["downloaded_at"] == "1970-01-01T00:00:00Z"
    else:
        assert not list(sc.cache_dir(rcfg).iterdir())
    assert {p: p.read_bytes() for p in folder.iterdir()} == before


@pytest.mark.parametrize("failure", ["download", "duration", "height", "size", "suffix", "outside", "probe",
                                      "put", "head", "head_sha", "head_size", "meta", "publish", "cancel"])
def test_step_failures_clean_temporary_and_preserve_old_entry(rcfg, monkeypatch, failure):
    vid = VIDS[0]
    seed(rcfg, vid)
    favorite(rcfg, vid)
    old = sc.cache_dir(rcfg) / vid
    old.mkdir(parents=True)
    (old / "meta.json").write_bytes(b"invalid old cache")
    (old / "source.mp4").write_bytes(b"old bytes")
    before = {p: p.read_bytes() for p in old.iterdir()}
    client = MemoryStore()

    def broken(uri, dest, cfg):
        (dest / "incomplete.part").write_bytes(b"partial")
        if failure in ("download", "cancel"):
            raise DownloadError("download failed") if failure == "download" else KeyboardInterrupt()
        if failure == "outside":
            return Download(old / "source.mp4", {})
        got = download(uri, dest, cfg)
        if failure == "suffix":
            path = got.path.with_suffix(".bad!")
            got.path.rename(path)
            return Download(path, {})
        if failure == "size":
            got.path.write_bytes(b"")
        return got

    if failure in ("duration", "height"):
        monkeypatch.setattr(sc.probe, "probe", lambda _: dict(duration=4000 if failure == "duration" else 3600,
                                                              height=0 if failure == "height" else 720))
    if failure == "probe":
        monkeypatch.setattr(sc.probe, "probe", lambda _: (_ for _ in ()).throw(sc.probe.ProbeError("bad")))
    if failure in ("put", "head"):
        monkeypatch.setattr(client, failure, lambda *a: (_ for _ in ()).throw(StoreUnavailable("down")))
    if failure in ("head_sha", "head_size"):
        monkeypatch.setattr(client, "head", lambda *a: dict(sha256="0" * 64 if failure == "head_sha" else
                            hashlib.sha256(DOWNLOADED).hexdigest(), size=0 if failure == "head_size" else len(DOWNLOADED)))
    if failure == "meta":
        monkeypatch.setattr(rd, "atomic_write_json", lambda *a: (_ for _ in ()).throw(OSError("write")))
    if failure == "publish":
        real_replace = rd.os.replace
        def once(src, dst):
            # Fail the new directory publication, while allowing restoration of the old directory.
            if Path(dst) == old and Path(src).name != "cache":
                raise OSError("rename")
            return real_replace(src, dst)
        monkeypatch.setattr(rd.os, "replace", once)
    if failure == "cancel":
        with pytest.raises(KeyboardInterrupt):
            rd.step(rcfg, vid, downloader=broken, client=client, disk_usage=enough_disk)
    else:
        result = rd.step(rcfg, vid, downloader=broken, client=client, disk_usage=enough_disk)
        assert result["status"] == ("store_unavailable" if failure in ("put", "head") else "failed")
    assert {p: p.read_bytes() for p in old.iterdir()} == before
    assert not list(sc.cache_dir(rcfg).glob(".*"))


@pytest.mark.parametrize("error", [DownloadError("HTTP Error 403: Forbidden"), YoutubeBlocked("bot check"),
                                   DownloadError("HTTP Error 429"), DownloadError("confirm you're not a bot")])
def test_background_blocked_backoff_doubles_caps_and_retries_same_video(background, rcfg, error):
    app, now = background
    seed(rcfg, VIDS[0])
    client, calls = MemoryStore(), []
    def blocked(uri, dest, cfg):
        calls.append(uri)
        raise error
    for delay in (3600, 7200, 14400, 21600, 21600):
        result = app.state.redownload_pass(client, downloader=blocked)
        assert result["status"] == "blocked" and result["done"] == 0
        assert not app.state.runner.youtube_status()["blocked"]
        assert result["retry_at"] - now[0] == delay
        assert app.state.redownload_pass(client, downloader=forbidden) == result
        now[0] = result["retry_at"]
    assert len(calls) == 5 and len(set(calls)) == 1
    assert not list(sc.cache_dir(rcfg).iterdir())


def test_background_generic_error_moves_on_then_retries_after_others(background, rcfg):
    app, now = background
    for vid in VIDS[:2]:
        seed(rcfg, vid)
    client = MemoryStore()
    rng = SimpleNamespace(uniform=lambda lo, hi: (lo + hi) / 2)
    def failed(*args):
        raise DownloadError("unavailable format")
    first = app.state.redownload_pass(client, downloader=failed, rng=rng)
    assert first["status"] == "paused" and first["video_id"] == VIDS[0] and first["retry_at"] == 900
    now[0] = first["retry_at"]
    second = app.state.redownload_pass(client, downloader=download, rng=rng)
    assert second["video_id"] == VIDS[1] and second["done"] == 1 and second["total"] == 2
    now[0] = second["retry_at"]
    app.state.redownload_pass(client, downloader=forbidden)  # completed sweep resets failed set
    final = app.state.redownload_pass(client, downloader=download, rng=rng)
    assert final["done"] == final["total"] == 2
    assert app.state.storage.report()["redownload"] == final


@pytest.mark.parametrize("gate", ["disabled", "store_disabled", "prepare", "serial", "queued", "prepare_after_index", "youtube", "disk", "node", "store"])
def test_background_gates_never_download(background, rcfg, monkeypatch, gate):
    app, _ = background
    seed(rcfg, VIDS[0])
    client = MemoryStore()
    if gate in ("disabled", "store_disabled", "disk"):
        from auto_short.web.app import create_app
        cfg = replace(rcfg, store=replace(rcfg.store, redownload=gate != "disabled", enabled=gate != "store_disabled"))
        app = create_app(cfg, "pw", preflight=None, post_preflight=None,
                         disk_usage=(lambda _: (100 * 10**9, 81 * 10**9, 19 * 10**9)) if gate == "disk" else enough_disk)
    elif gate in ("prepare", "serial"):
        monkeypatch.setattr(app.state.runner, "running", lambda: {gate: object()})
    elif gate == "queued":
        # The public monitor API includes prepare jobs waiting between steps or before start.
        monkeypatch.setattr(app.state.runner, "monitor_queue", lambda **k: {"lanes": {"prepare": {"pending_total": 1}}})
    elif gate == "prepare_after_index":
        index = client.index
        def newly_queued():
            result = index()
            monkeypatch.setattr(app.state.runner, "running", lambda: {"prepare": object()})
            return result
        monkeypatch.setattr(client, "index", newly_queued)
    elif gate == "youtube":
        monkeypatch.setattr(app.state.runner, "youtube_status", lambda: dict(blocked=True, next_check=None))
    elif gate == "node":
        monkeypatch.setattr(rd.shutil, "which", lambda _: None)
    elif gate == "store":
        client.down = True
    result = app.state.redownload_pass(client, downloader=forbidden)
    assert result["status"] in ("paused", "blocked") and not client.uploads
    if gate == "store":
        assert result["retry_at"] > 0
    elif gate == "prepare_after_index":
        assert client.index_calls == 1
    else:
        assert client.index_calls == 0


def test_step_low_disk_stops_before_store_or_temp(rcfg):
    seed(rcfg, VIDS[0])
    client = SimpleNamespace(index=forbidden)
    result = rd.step(rcfg, VIDS[0], client=client, downloader=forbidden,
                     disk_usage=lambda _: (100 * 10**9, 81 * 10**9, 19 * 10**9))
    assert result["status"] == "paused" and "20 GB" in result["reason"]
    assert not sc.cache_dir(rcfg).exists()


def test_background_thread_sleep_snapshot_and_lifespan_cancellation(background, rcfg, monkeypatch):
    app, _ = background
    seed(rcfg, VIDS[0])
    client = MemoryStore()
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: client)
    for obj in (app.state.runner, app.state.monitor_sampler):
        for name in ("start", "stop"):
            monkeypatch.setattr(obj, name, lambda: None)
    threads, sleeps, snapshots, tasks = [], [], [], []
    main_thread = threading.get_ident()

    def step(cfg, vid, **kwargs):
        threads.append(threading.get_ident())
        snapshots.append(app.state.storage.report()["redownload"])
        return dict(status="store_unavailable", reason="kho tắt")
    monkeypatch.setattr(rd, "step", step)

    # Drive lifecycle coroutines at their sleep boundary without an event loop/socketpair.
    # The to_thread stand-in still executes every blocking callable on a real worker.
    async def to_thread(fn, *args):
        result, errors = [], []
        def work():
            try:
                result.append(fn(*args))
            except BaseException as exc:
                errors.append(exc)
        worker = threading.Thread(target=work)
        worker.start()
        worker.join(3)
        assert not worker.is_alive()
        if errors:
            raise errors[0]
        return result[0]

    class Sleep:
        def __init__(self, delay):
            self.delay = delay
        def __await__(self):
            sleeps.append(self.delay)
            yield self.delay

    class Task:
        def __init__(self, coro):
            self.coro, self.cancelled = coro, False
            tasks.append(self)
        def cancel(self):
            self.cancelled = True
            self.coro.close()

    async def gather(*items, **kwargs):
        assert all(item.cancelled for item in items)

    monkeypatch.setattr(asyncio, "to_thread", to_thread)
    monkeypatch.setattr(asyncio, "sleep", Sleep)
    monkeypatch.setattr(asyncio, "create_task", Task)
    monkeypatch.setattr(asyncio, "gather", gather)
    context = app.router.lifespan_context(app)
    with pytest.raises(StopIteration):
        context.__aenter__().send(None)
    task = next(t for t in tasks if t.coro.__name__ == "_redownload_loop")
    try:
        assert task.coro.send(None) == rcfg.store.retry_seconds
        monkeypatch.setattr(StoreClient, "from_config", forbidden)
        assert app.state.storage.report()["redownload"]["reason"] == "kho tắt"
    finally:
        with pytest.raises(StopIteration):
            context.__aexit__(None, None, None).send(None)
    assert task.cancelled and all(t.cancelled for t in tasks)
    assert threads and all(t != main_thread for t in threads)
    assert sleeps == [rcfg.store.retry_seconds]
    assert snapshots[0]["status"] == "downloading"


def playlist(cfg, playlist_id, *entries, series="Bộ kinh A"):
    path = cfg.workspace.dir / "_playlists" / f"{playlist_id}.json"
    atomic_write_json(path, dict(series=series, title="Tên playlist", entries=list(entries)))
    return path


def entry(vid, episode, *, duration=3600, available=True):
    return dict(video_id=vid, episode=str(episode), duration=duration,
                title=f"Kinh Vô Lượng Thọ tập {episode}", available=available)


def test_a2_pending_groups_order_cache_workspace_and_offline_hours(rcfg, monkeypatch, tmp_path, capsys):
    archived, new10, new2, later, remote, cached = VIDS
    seed(rcfg, archived, title="Kinh Vô Lượng Thọ tập 99")
    seed(rcfg, "ggggggggggg", archived=False)
    (rcfg.workspace.dir / "hhhhhhhhhhh.kt").mkdir()  # existing owner without even a manifest blocks A2
    (rcfg.workspace.dir / "iiiiiiiiiii").mkdir()
    cache_ws = seed(rcfg, cached)
    path = sc.fetch_to_cache(rcfg, cached, download)
    rd.shutil.rmtree(cache_ws)
    broken = "jjjjjjjjjjj"
    broken_ws = seed(rcfg, broken)
    broken_path = sc.fetch_to_cache(rcfg, broken, download)
    rd.shutil.rmtree(broken_ws)
    broken_path.write_bytes(b"bad")
    playlist(rcfg, "PL_A", entry(new10, 10), entry(new2, 2, duration=7200), entry(remote, 4),
             entry(cached, 5), entry("ggggggggggg", 6), entry("hhhhhhhhhhh", 7), entry("iiiiiiiiiii", 8),
             entry("kkkkkkkkkkk", 9, available=False), entry(None, 11), entry("../invalid", 12),
             entry(broken, 3), "bad entry")
    playlist(rcfg, "PL_Z", entry(later, 1, duration=1800), entry(new2, 2))  # deduplicate
    playlist(rcfg, "PL_bad", None)
    (rcfg.workspace.dir / "_playlists" / "PL_corrupt.json").write_text("{")
    client, groups = MemoryStore(), {}
    client.files[remote] = ORIGINAL
    assert rd.pending(rcfg, client=client, groups=groups) == [archived, new2, broken, new10, later]
    assert groups == dict(archived=[archived], unprocessed=[new2, broken, new10, later])
    assert client.index_calls == 1 and not client.heads
    assert sc.cached_source(rcfg, cached, reference=entry(cached, 5)) == path
    config = tmp_path / "config-a2.toml"
    config.write_text(f'[workspace]\ndir = "{rcfg.workspace.dir}"\n[render]\noutput_dir = "{rcfg.render.output_dir}"\n')
    monkeypatch.setattr(StoreClient, "from_config", forbidden)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert rd.main(["--config", str(config), "--dry-run"]) == 0
    text = capsys.readouterr().out
    assert "Đã dọn: 1 video, 1.00 giờ" in text and "Chưa xử lý: 5 video, 5.50 giờ" in text
    assert "Tổng: 6 video, 0 ♥; 6.50 giờ" in text and "chưa đối chiếu kho" in text
    assert text.index(archived) < text.index("Chưa xử lý:") < text.index(new2) < text.index(new10) < text.index(later)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("case", ["ok", "title_number", "duration_edge", "duration_bad", "duration_missing",
                                  "duration_nan", "duration_zero", "unavailable", "download", "put", "head", "head_sha", "blocked", "cancel"])
def test_a2_step_playlist_duration_naming_no_provenance_or_workspace(rcfg, monkeypatch, case):
    vid = VIDS[0]
    ref = entry(vid, 2)
    if case == "unavailable":
        ref["available"] = False
    elif case == "title_number":
        ref["episode"] = None
    elif case.startswith("duration_") and case not in ("duration_bad", "duration_edge"):
        ref["duration"] = {"duration_missing": None, "duration_nan": float("nan"), "duration_zero": 0}[case]
    doc = playlist(rcfg, "PL_A", ref)
    favorite(rcfg, vid)  # stale favorites must never turn an unprocessed download into a TC3 cache
    before = doc.read_bytes()
    client, metadata = MemoryStore(), []
    verify = rd.download_verified
    def checked(*args, **kwargs):
        got = verify(*args, **kwargs)
        metadata.append(got[1])
        return got
    monkeypatch.setattr(rd, "download_verified", checked)
    if case in ("duration_edge", "duration_bad"):
        monkeypatch.setattr(sc.probe, "probe", lambda _: dict(duration=3636 if case == "duration_edge" else 3636.01, height=720))
    if case in ("put", "head"):
        monkeypatch.setattr(client, case, lambda *a: (_ for _ in ()).throw(StoreUnavailable("down")))
    elif case == "head_sha":
        monkeypatch.setattr(client, "head", lambda *a: dict(sha256="0" * 64, size=len(DOWNLOADED)))
    def downloading(uri, dest, cfg):
        assert uri == f"https://youtu.be/{vid}"
        got = download(uri, dest, cfg)
        if case in ("download", "blocked", "cancel"):
            raise {"download": DownloadError("format unavailable"), "blocked": DownloadError("HTTP Error 403"),
                   "cancel": KeyboardInterrupt()}[case]
        return got
    if case == "cancel":
        with pytest.raises(KeyboardInterrupt):
            rd.step(rcfg, vid, client=client, downloader=downloading, disk_usage=enough_disk)
    else:
        result = rd.step(rcfg, vid, client=client, downloader=downloading, disk_usage=enough_disk)
        expected = "done" if case in ("ok", "title_number", "duration_edge") else "store_unavailable" if case in ("put", "head") else "blocked" if case == "blocked" else "failed"
        assert result["status"] == expected and "differs_from_ingest" not in result
        if expected == "done":
            assert client.uploads[0][1:3] == ("PL_A", "[Goc] Bộ kinh A - Tập 2.mp4")
            assert client.heads == [(vid, "source")] and client.files[vid] == DOWNLOADED
            assert result["cached"] is False
    assert all("ingest_sha256" not in meta and "differs_from_ingest" not in meta for meta in metadata)
    assert not (rcfg.workspace.dir / vid).exists() and not (rcfg.workspace.dir / f"{vid}.kt").exists()
    assert doc.read_bytes() == before
    assert not sc.cache_dir(rcfg).exists() or not list(sc.cache_dir(rcfg).iterdir())


def test_a2_background_group_progress_and_readonly_storage(background, rcfg, monkeypatch):
    app, now = background
    a, b, c, d = VIDS[:4]
    seed(rcfg, a)
    seed(rcfg, b)
    playlist(rcfg, "PL_A", entry(c, 2), entry(d, 10))
    monkeypatch.setattr(StoreClient, "from_config", forbidden)
    assert app.state.storage.report()["redownload"]["groups"] == {
        "archived": dict(done=0, total=0), "unprocessed": dict(done=0, total=0)}
    client = MemoryStore()
    rng = SimpleNamespace(uniform=lambda lo, hi: 900)
    for i, vid in enumerate((a, b, c, d), 1):
        result = app.state.redownload_pass(client, downloader=download, rng=rng)
        assert result["video_id"] == vid and result["done"] == i and result["total"] == 4
        assert result["groups"] == {"archived": dict(done=min(i, 2), total=2),
                                     "unprocessed": dict(done=max(i - 2, 0), total=2)}
        assert app.state.storage.report()["redownload"] == result
        now[0] = result["retry_at"]
    assert app.state.redownload_pass(client, downloader=forbidden)["status"] == "idle"
