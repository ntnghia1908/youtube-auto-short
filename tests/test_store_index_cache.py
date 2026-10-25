"""Upload confirmation invalidates the shared source snapshot; no transport is used."""
import socket
from dataclasses import replace

import pytest

from auto_short.config import StoreConfig
from auto_short.store import backup, index_cache, redownload
from auto_short.store.client import StoreClient, StoreMismatch
from auto_short.theme_render import sources

from test_store_backup import MemoryStore, VID, seed
from test_store_redownload import download, enough_disk, seed as archived_seed
from wait_helpers import wait_for


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("cache tests must not open sockets")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    index_cache.invalidate()
    yield
    wait_for(lambda: index_cache._REFRESHING is None, what="store refresh finished")
    index_cache.invalidate()


@pytest.mark.parametrize("operation", ["push", "redownload"])
@pytest.mark.parametrize("confirmed", [True, False])
def test_confirmed_upload_invalidates_source_snapshot(cfg, monkeypatch, operation, confirmed):
    config = replace(cfg, store=StoreConfig(enabled=True))
    client = MemoryStore()

    def index():
        return [dict(video_id=vid, kind="source", **client.head(vid, "source"))
                for vid in client.files]

    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: client)
    monkeypatch.setattr(client, "index", index, raising=False)
    assert index_cache.source_ids(config, blocking=True) == frozenset()
    generation = index_cache._GENERATION
    if not confirmed:
        monkeypatch.setattr(client, "head", lambda *args: {})
    if operation == "push":
        seed(config)
        if confirmed:
            assert backup.push_source(config, VID, client=client)["backed_up"]
        else:
            with pytest.raises(StoreMismatch, match="chưa xác nhận"):
                backup.push_source(config, VID, client=client)
    else:
        archived_seed(config, VID)
        monkeypatch.setattr(sources.probe, "probe", lambda _: dict(duration=3600, height=720))
        monkeypatch.setattr(redownload.shutil, "which", lambda _: "/bin/node")
        result = redownload.step(config, VID, client=client, downloader=download, disk_usage=enough_disk)
        assert result["status"] == ("done" if confirmed else "failed")
    assert index_cache._GENERATION == generation + int(confirmed)
    if confirmed:
        assert not index_cache._CACHE
        assert index_cache.source_ids(config, blocking=True) == {VID}
        assert index_cache.source_entry(config, VID)["sha256"] == client.head(VID, "source")["sha256"]
    else:
        assert index_cache.source_ids(config, blocking=True) == frozenset()
