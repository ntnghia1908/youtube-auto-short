"""HD2b: fake store and small local bytes; no sockets or media services."""
import asyncio
import hashlib
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short.config import ConfigError, StoreConfig, from_dict
from auto_short.enhance import state as enh
from auto_short.render import full
from auto_short.review import backup
from auto_short.store import offload
from auto_short.store.client import StoreClient, StoreMismatch, StoreUnavailable
from auto_short.workspace import atomic_write_json, read_json_dict

from web_helpers import write_episode

VID, OTHER = "abcDEF12_-3", "zyxWVUT9876"
HD, VERTICAL = b"hd-source-bytes", b"vertical-bytes" * 10


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def ocfg(cfg):
    return replace(cfg, store=StoreConfig(enabled=True, offload=True))


def seed(config, owner=VID, *, hd=False, data=VERTICAL):
    """Shared with download tests: a current vertical from HD or an eligible original."""
    write_episode(config, owner)
    d = Path(config.workspace.dir) / owner
    source = d / "source.mp4"
    source.write_bytes(b"original")
    doc = read_json_dict(d / "manifest.json")
    doc["source"].update(path=source.name, size=source.stat().st_size, sha256=digest(b"original"))
    atomic_write_json(d / "manifest.json", doc)
    meta = read_json_dict(d / "metadata.json")
    atomic_write_json(d / "metadata.json", {**meta, "height": 1080})
    sha = digest(b"original")
    if hd:
        path = d / "source_hd.mp4"
        path.write_bytes(HD)
        doc = enh.new_doc(owner)
        doc.update(state=enh.DONE, wanted=True, source_hd_sha256=digest(HD), source_hd_size=len(HD),
                   source_hd_mtime_ns=path.stat().st_mtime_ns)
        enh.write(d, doc)
        sha = digest(HD)
    path = full.vertical_path(config, owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    atomic_write_json(path.parent / full.META_NAME, {"hd_sha256": sha, "size": len(data), "key": "key"})
    return d, path


class MemoryStore:
    def __init__(self):
        self.files, self.uploads = {}, []
        self.down = False
        self.after_put = None

    def head(self, owner, kind):
        if self.down:
            raise StoreUnavailable("3090 đang tắt")
        if (owner, kind) not in self.files:
            raise StoreMismatch("chưa có file")
        data = self.files[owner, kind]
        return dict(sha256=digest(data), size=len(data))

    def put(self, owner, kind, series, name, path, sha256):
        if self.down:
            raise StoreUnavailable("3090 đang tắt")
        if (owner, kind) in self.files and self.files[owner, kind] != path.read_bytes():
            raise StoreMismatch("kho có file khác sha")
        self.uploads.append((owner, kind, series, name))
        self.files[owner, kind] = path.read_bytes()
        assert digest(self.files[owner, kind]) == sha256
        if self.after_put:
            self.after_put()


@pytest.mark.parametrize("hd,confirmed", [(False, False), (True, False), (True, True)])
def test_push_confirm_release_rules(ocfg, monkeypatch, hd, confirmed):
    from auto_short.store import index_cache
    d, path = seed(ocfg, hd=hd)
    if confirmed:
        backup.confirm(ocfg, VID, "hd", digest(HD))
    client = MemoryStore()
    invalidations = []
    monkeypatch.setattr(index_cache, "invalidate", lambda: invalidations.append(True))
    result = offload.push_vertical(ocfg, VID, client=client)
    assert result["pushed"] and result["released"] == (not hd or confirmed)
    doc = backup.read_backup(d)
    assert doc["confirmed"]["vertical"]["sha256"] == digest(VERTICAL)
    assert client.uploads == [(VID, "vertical", "_khac", "[HD Mobile] Kinh Vô Lượng Thọ - Tập 3.mp4")]
    assert invalidations
    if hd and not confirmed:
        assert path.is_file() and (d / "source_hd.mp4").is_file()
        assert "chưa giải phóng" in result["status"]
    else:
        assert not path.exists()
        assert backup.released_vertical(ocfg, VID) == dict(sha256=digest(VERTICAL), size=len(VERTICAL))
        assert not (d / "source_hd.mp4").exists()
        assert (enh.read(d) or {}).get("released", False) == hd


def test_old_candidates_order_digest_cache_and_confirmation(ocfg, monkeypatch):
    d, path = seed(ocfg)
    seed(ocfg, OTHER, hd=True, data=VERTICAL * 10)
    atomic_write_json(Path(ocfg.workspace.dir) / "_playlists" / "PLtest.json",
                      {"series": "Bộ thử", "entries": [{"video_id": VID}]})
    hashes, real = [], backup.sha256_file
    monkeypatch.setattr(backup, "sha256_file", lambda p: (hashes.append(p), real(p))[1])
    assert [r["owner"] for r in offload.candidates(ocfg)] == [VID, OTHER]
    assert len(hashes) == 2
    offload.candidates(ocfg)
    assert len(hashes) == 2
    client = MemoryStore()
    offload.push_vertical(ocfg, VID, client=client)
    assert len(hashes) == 2  # PUT / confirm / release all reuse vertical_sha
    assert client.uploads[0][2:] == ("PLtest", "[HD Mobile] Bộ thử - Tập 3.mp4")
    backup.confirm(ocfg, OTHER, "vertical", digest(VERTICAL * 10))
    assert offload.candidates(ocfg) == []


@pytest.mark.parametrize("failure", ["down", "sha", "size", "existing", "mtime"])
def test_failures_never_confirm_or_delete(ocfg, failure):
    d, path = seed(ocfg)
    client = MemoryStore()
    if failure == "down":
        client.down = True
    elif failure == "existing":
        client.files[VID, "vertical"] = b"different"
    elif failure in ("sha", "size"):
        client.head = lambda *a: dict(sha256="0" * 64 if failure == "sha" else digest(VERTICAL),
                                     size=len(VERTICAL) + (failure == "size"))
    else:
        def change():
            st = path.stat()
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1000000))
        client.after_put = change
    with pytest.raises((StoreUnavailable, StoreMismatch)):
        offload.push_vertical(ocfg, VID, client=client)
    assert not backup.read_backup(d)["confirmed"] and path.is_file()


@pytest.mark.parametrize("error", [StoreUnavailable("kho tắt"), StoreMismatch("sha khác")])
def test_failed_owner_does_not_starve_next(ocfg, error):
    from auto_short.web.app import create_app
    d, path = seed(ocfg, data=VERTICAL * 2)
    seed(ocfg, OTHER)
    app = create_app(ocfg, "pw", preflight=None, post_preflight=None)
    client = MemoryStore()
    put = client.put
    def fail(owner, *args):
        if owner == VID:
            raise error
        put(owner, *args)
    client.put = fail
    assert app.state.offload_pass(client) == []
    snapshot = app.state.storage.report()["offload"]
    assert snapshot == dict(pushed=0, pending=2, failed=1, bytes_pending=len(VERTICAL) * 3, last_error=str(error))
    assert app.state.offload_pass(client) == [OTHER]
    assert path.is_file() and not backup.read_backup(d)["confirmed"]
    assert app.state.offload_pass(client) == []  # clears failed set when every remaining candidate failed
    client.put = put
    assert app.state.offload_pass(client) == [VID]
    assert app.state.storage.report()["offload"] == dict(pushed=2, pending=0, failed=0, bytes_pending=0, last_error=None)


def test_unreadable_candidate_does_not_block_inventory(ocfg, monkeypatch):
    from auto_short.web.app import create_app
    d, path = seed(ocfg)
    seed(ocfg, OTHER)
    real = backup.sha256_file
    def sha(path):
        if VID in path.parts:
            raise OSError("không đọc được file")
        return real(path)
    monkeypatch.setattr(backup, "sha256_file", sha)
    app = create_app(ocfg, "pw", preflight=None, post_preflight=None)
    assert app.state.offload_pass(MemoryStore()) == [OTHER]
    assert path.is_file() and not backup.read_backup(d)["confirmed"]


@pytest.mark.parametrize("kind", ["owner", "kt", "vertical", "lease", "render", "serial", "during_put"])
def test_busy_guards(ocfg, monkeypatch, kind):
    from auto_short.web.app import create_app
    from auto_short.web.jobs import KIND_PIPELINE, KIND_VERTICAL
    d, path = seed(ocfg, hd=True)
    app = create_app(ocfg, "pw", preflight=None, post_preflight=None)
    client = MemoryStore()
    def submit():
        app.state.runner.submit(VID + (".kt" if kind == "kt" else ""),
                                KIND_VERTICAL if kind == "vertical" else KIND_PIPELINE, lambda j: None)
    if kind in ("render", "serial"):
        monkeypatch.setattr(app.state.runner, "running", lambda: {kind: object()})
    elif kind == "lease":
        doc = enh.read(d)
        doc["lease"] = {"expires_at": enh.now_iso(time.time() + 3600)}
        enh.write(d, doc)
        assert offload.push_vertical(ocfg, VID, client=client)["busy"]
    elif kind == "during_put":
        client.after_put = submit
    else:
        submit()
    assert app.state.offload_pass(client) == []
    assert not backup.read_backup(d)["confirmed"] and path.is_file()
    assert len(client.uploads) == (1 if kind == "during_put" else 0)


def test_offload_disabled_and_config(ocfg, monkeypatch):
    from auto_short.web.app import create_app
    assert not from_dict({}).store.offload
    assert from_dict({"store": {"enabled": True, "offload": True}}).store.offload
    for value in (True, "yes"):
        with pytest.raises(ConfigError):
            from_dict({"store": {"offload": value}})
    seed(ocfg)
    disabled = replace(ocfg, store=replace(ocfg.store, offload=False))
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: pytest.fail("offload contacted store"))
    assert create_app(disabled, "pw", preflight=None, post_preflight=None).state.offload_pass() == []
    assert not offload.push_vertical(disabled, VID)["pushed"]


def test_released_vertical_current_source_checks_and_no_encode(ocfg, monkeypatch):
    d, path = seed(ocfg)
    offload.push_vertical(ocfg, VID, client=MemoryStore())
    assert full.current(ocfg, VID) and full.ready_file(ocfg, VID) is None
    monkeypatch.setattr(full, "_run_vertical", lambda *a, **k: pytest.fail("re-encoded a stored vertical"))
    assert not full.run_vertical(VID, ocfg).ran
    meta = full.read_meta(ocfg, VID)
    atomic_write_json(path.parent / full.META_NAME, {**meta, "size": meta["size"] + 1})
    assert not full.current(ocfg, VID)
    atomic_write_json(path.parent / full.META_NAME, {**meta, "hd_sha256": "0" * 64})
    assert full.on_store(ocfg, VID) is None


def test_new_vertical_after_hd_release_keeps_hd_history(ocfg):
    d, path = seed(ocfg, hd=True)
    backup.confirm(ocfg, VID, "hd", digest(HD))
    offload.push_vertical(ocfg, VID, client=MemoryStore())
    assert full.current(ocfg, VID)
    old_hd = backup.read_backup(d)["released"]["hd"]
    path.write_bytes(VERTICAL + b"new")
    backup.confirm(ocfg, VID + ".kt", "vertical", digest(path.read_bytes()))
    assert backup.released_vertical(ocfg, VID) is None
    assert backup.release(ocfg, VID).freed == len(VERTICAL) + 3
    assert backup.read_backup(d)["released"]["hd"] == old_hd
    assert enh.read(d)["released"]


def test_vertical_only_release_retains_enhance_and_requires_current_confirmation(ocfg):
    d, path = seed(ocfg)
    edoc = enh.new_doc(VID)
    edoc.update(wanted=True, state=enh.PENDING)
    enh.write(d, edoc)
    with pytest.raises(backup.BackupError, match="chưa xác nhận"):
        backup.release(ocfg, VID)
    backup.confirm(ocfg, VID, "vertical", digest(VERTICAL))
    path.write_bytes(VERTICAL + b"new")
    with pytest.raises(backup.BackupError, match="không khớp"):
        backup.release(ocfg, VID)
    backup.confirm(ocfg, VID, "vertical", digest(path.read_bytes()))
    assert backup.release(ocfg, VID).changed
    assert enh.read(d) == edoc and backup.read_backup(d)["released"].get("hd") is None
    assert not backup.release(ocfg, VID).changed
    (d / "backup.json").unlink()
    with pytest.raises(backup.BackupError, match="chưa có bản dọc"):
        backup.release(ocfg, VID, allow_no_vertical=True)


def test_store_temp_report_and_safe_startup_sweep(ocfg, monkeypatch):
    from auto_short.web.app import create_app
    from auto_short.web.storage import store_temp_bytes
    from auto_short.store.borrow import _BORROWED
    d, vertical = seed(ocfg, hd=True)
    assert store_temp_bytes(ocfg) == 0  # a real HD is not a store temporary
    monkeypatch.setitem(_BORROWED, d / "source_hd.mp4", 1)
    tmp = d / ".restore-source-abcd"
    tmp.mkdir()
    files = [d / "source_hd.mp4.part", tmp / "store-0.mp4", tmp / "store-1.mp4.part"]
    for path in files:
        path.write_bytes(b"temp")
        os.utime(path, (time.time() - 7 * 3600,) * 2)
    fresh = d / "source_hd.mp4.part"
    os.utime(fresh, None)
    unknown = d / "other.part"
    unknown.write_bytes(b"keep")
    app = create_app(ocfg, "pw", preflight=None, post_preflight=None)
    assert store_temp_bytes(ocfg) == len(HD) + 12
    assert app.state.storage.report()["totals"]["store_tmp"] == len(HD) + 12
    assert app.state.sweep_store_temps() == 8
    assert fresh.is_file() and unknown.is_file() and vertical.is_file() and (d / "source_hd.mp4").is_file()
    from auto_short.web.jobs import KIND_PIPELINE
    app.state.runner.submit(VID, KIND_PIPELINE, lambda j: None)
    os.utime(fresh, (time.time() - 7 * 3600,) * 2)
    assert app.state.sweep_store_temps() == 0 and fresh.is_file()


def test_loop_uses_thread_and_short_success_delay(ocfg, monkeypatch):
    import threading
    from auto_short.web.app import create_app
    seed(ocfg)
    ocfg = replace(ocfg, storage=replace(ocfg.storage, auto_archive=False))
    app = create_app(ocfg, "pw", preflight=None, post_preflight=None)
    client, calls, sleeps = MemoryStore(), [], []
    put = client.put
    def record(*args):
        calls.append(threading.get_ident())
        return put(*args)
    client.put = record
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: client)
    for obj in (app.state.runner, app.state.monitor_sampler):
        for name in ("start", "stop"):
            monkeypatch.setattr(obj, name, lambda: None)
    real_sleep = asyncio.sleep
    async def run():
        waited = asyncio.Event()
        async def sleep(delay):
            if asyncio.current_task().get_coro().__name__ == "_offload_loop":
                sleeps.append(delay)
                waited.set()
            await real_sleep(delay)
        monkeypatch.setattr(asyncio, "sleep", sleep)
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(waited.wait(), 3)
            assert sleeps == [5]
    main = threading.get_ident()
    asyncio.run(run())
    assert len(calls) == 1 and calls[0] != main
