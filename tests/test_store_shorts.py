"""SHO1a release lifecycle: actual artifacts and fake store bytes, without sockets or services."""
import hashlib
import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from auto_short import khaithi
from auto_short.config import ConfigError, StoreConfig, from_dict
from auto_short.khaithi import KhaiThi
from auto_short.review.publish import mark_downloaded
from auto_short.store import shorts
from auto_short.store.client import StoreMismatch, StoreUnavailable
from auto_short.store.offload import OffloadStopped
from auto_short.web import episodes as ep
from auto_short.web.app import create_app
from auto_short.web.storage import DONE_STATE, PROCESSING, short_offload_plan
from auto_short.workspace import atomic_write_json, read_json_dict
from web_helpers import write_episode

VID, OTHER = "aaaaaaaaaa1", "aaaaaaaaaa2"
NOW = time.time() + 10 * 86400


class MemoryShortStore:
    """Shared socket-free transport for release and archive-route tests."""
    def __init__(self):
        self.data, self.names, self.streams = {}, {}, []
        self.up = True

    def available(self):
        return self.up

    def put(self, eid, kind, series, name, path, sha256, *, clip):
        assert kind == "short" and hashlib.sha256(path.read_bytes()).hexdigest() == sha256
        if not self.up:
            raise StoreUnavailable("down")
        self.data[eid, clip] = path.read_bytes()
        self.names[eid, clip] = (series, name)

    def head(self, eid, kind, *, clip):
        if not self.up:
            raise StoreUnavailable("down")
        data = self.data[eid, clip]
        return dict(sha256=hashlib.sha256(data).hexdigest(), size=len(data))

    def open_stream(self, eid, kind, range_header=None, *, clip):
        if not self.up:
            raise StoreUnavailable("down")
        from test_store_server import store
        data = self.data[eid, clip]
        headers = {"Accept-Ranges": "bytes"}
        if range_header:
            start, end = store.parse_range(range_header, len(data))
            headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
            data = data[start:end + 1]
        headers["Content-Length"] = str(len(data))
        class Chunks:
            def __init__(self):
                self.chunks = iter([data])
                self.close = Mock()

            def __iter__(self):
                return self

            def __next__(self):
                return next(self.chunks)
        stream = Chunks()
        self.streams.append(stream)
        return (206 if range_header else 200), headers, stream


@pytest.fixture
def prepared_shorts(tcfg):
    """Create real current hashes and publish ticks; all parts are older than grace at NOW."""
    config = replace(tcfg, store=StoreConfig(enabled=True, offload_shorts=True))

    def make(vid=VID, *, kt=True, clips=("k01", "k02")):
        for eid in ([vid, vid + ".kt"] if kt else [vid]):
            files = write_episode(config, eid, clips=clips)
            if eid.endswith(".kt"):
                khaithi.write(Path(config.workspace.dir) / eid, KhaiThi(vid, 4, 7))
            out = Path(config.render.output_dir) / eid
            doc = read_json_dict(out / ep.RENDER_MANIFEST)
            for short in doc["shorts"]:
                short["sha256"] = hashlib.sha256(files[short["clip_id"]]).hexdigest()
            atomic_write_json(out / ep.RENDER_MANIFEST, doc)
            mark_downloaded(eid, config, list(files))
        return config
    return make


@pytest.mark.parametrize("change,expected", [(None, True), ("recent", False), ("unpublished", False),
                                              ("busy", False), ("released", False)])
def test_short_plan_includes_khaithi_and_requires_every_part(change, expected):
    rows = [dict(id=eid, state=DONE_STATE, complete=True, complete_since=0) for eid in (VID, VID + ".kt")]
    local = {VID, VID + ".kt"}
    if change == "recent":
        rows[1]["complete_since"] = 99
    elif change == "unpublished":
        rows[1]["complete"] = False
    elif change == "busy":
        rows[1]["state"] = PROCESSING
    elif change == "released":
        local.clear()
    plan = short_offload_plan(rows, 100, 50, local)
    assert bool(plan) is expected
    if expected:
        assert plan == [dict(video_id=VID, episodes=[VID, VID + ".kt"], since=0)]


def test_short_release_atomic_records_and_unchanged_views(prepared_shorts, monkeypatch):
    config = prepared_shorts()
    client = MemoryShortStore()
    before = {eid: ep.episode_view(config, eid) for eid in (VID, VID + ".kt")}
    listing = ep.list_episodes(config)
    tracked = [Path(config.workspace.dir) / eid / "publish.json" for eid in before]
    tracked += [Path(config.render.output_dir) / eid / ep.RENDER_MANIFEST for eid in before]
    originals = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tracked}
    paths = {eid: [p for _, p, _ in ep.short_files(config, eid)] for eid in before}
    original_unlink = Path.unlink

    def unlink(path, *args, **kw):
        if path.suffix == ".mp4":
            # Every record (both parts) must already be durable before the first unlink.
            for eid, files in paths.items():
                doc = read_json_dict(Path(config.render.output_dir) / eid / "store.json")
                assert doc["at"] and set(doc["released"]) == {p.stem for p in files}
                for p in files:
                    r = doc["released"][p.stem]
                    assert r["sha256"] == client.head(eid, "short", clip=p.name)["sha256"]
        return original_unlink(path, *args, **kw)

    monkeypatch.setattr(Path, "unlink", unlink)
    assert shorts.push_video(config, VID, client=client, clock=lambda: NOW)["released"]
    assert all(not p.exists() for files in paths.values() for p in files)
    assert {eid: ep.episode_view(config, eid) for eid in before} == before
    assert ep.list_episodes(config) == listing
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == original for p, original in originals.items())
    assert all(ep.short_files(config, eid) == [] for eid in before)
    assert all(isinstance(p, ep.StoredShort) for eid in before for _, p, _ in ep.short_locations(config, eid))
    assert shorts.candidates(config, now=NOW) == []
    assert [name for _, name in client.names.values()] == [
        f"[Short] Kinh Vô Lượng Thọ - Tập 3 - k0{i}.mp4" for i in (1, 2)] + [
        f"[KhaiThi] Kinh Vô Lượng Thọ - Tập 3 - k0{i}.mp4" for i in (1, 2)]


@pytest.mark.parametrize("failure", ["down", "head_sha", "head_size", "missing", "local_sha", "changed",
                                      "manifest", "publish", "write", "busy", "stop"])
def test_short_release_failure_deletes_nothing_and_retries(prepared_shorts, monkeypatch, failure):
    config = prepared_shorts()
    client, stop = MemoryShortStore(), threading.Event()
    paths = [p for eid in (VID, VID + ".kt") for _, p, _ in ep.short_files(config, eid)]
    original_head = client.head
    busy = lambda _: False
    if failure == "down":
        client.up = False
    elif failure in ("head_sha", "head_size"):
        def head(*args, **kw):
            info = original_head(*args, **kw)
            info["sha256" if failure == "head_sha" else "size"] = "0" * 64 if failure == "head_sha" else 0
            return info
        client.head = head
    elif failure == "missing":
        paths[-1].unlink()
    elif failure == "local_sha":
        paths[-1].write_bytes(b"wrong")
    elif failure == "write":
        monkeypatch.setattr(shorts, "atomic_write_json", Mock(side_effect=OSError("full")))
    elif failure == "busy":
        busy = lambda _: bool(client.data)
    else:
        def head(*args, **kw):
            info = original_head(*args, **kw)
            if failure == "changed":
                paths[0].write_bytes(b"changed")
            elif failure == "manifest":
                manifest = Path(config.render.output_dir) / VID / ep.RENDER_MANIFEST
                doc = read_json_dict(manifest)
                doc["shorts"][0]["title"] = "changed"
                atomic_write_json(manifest, doc)
            elif failure == "publish":
                (Path(config.workspace.dir) / VID / "publish.json").unlink(missing_ok=True)
            elif failure == "stop":
                stop.set()
            return info
        client.head = head
    if failure in ("busy", "publish"):
        assert not shorts.push_video(config, VID, client=client, busy=busy, clock=lambda: NOW)["released"]
    else:
        with pytest.raises((StoreMismatch, StoreUnavailable, OSError, OffloadStopped)):
            shorts.push_video(config, VID, client=client, stop=stop, clock=lambda: NOW)
    assert all(p.exists() for p in paths if failure != "missing" or p != paths[-1])
    # A clean retry after any failure converges, without changing production render/publish artifacts.
    monkeypatch.undo()
    config = prepared_shorts()
    assert shorts.push_video(config, VID, client=MemoryShortStore(), clock=lambda: NOW)["released"]


def test_short_background_fair_retry_busy_and_default_off(prepared_shorts):
    config = prepared_shorts()
    prepared_shorts(OTHER)
    client = MemoryShortStore()
    app = create_app(config, "pw", preflight=None, post_preflight=None, clock=lambda: NOW)
    original_head = client.head
    def head(eid, *args, **kw):
        if eid == VID:
            raise StoreMismatch("conflict")
        return original_head(eid, *args, **kw)

    client.head = head
    assert app.state.shorts_offload_pass(client) == []
    assert app.state.shorts_offload_pass(client) == [OTHER]
    assert app.state.shorts_offload_pass(client) == []
    client.head = original_head
    app.state.runner.submit(VID + ".kt", "run", lambda j: None)
    assert app.state.shorts_offload_pass(client) == []
    fresh = create_app(config, "pw", preflight=None, post_preflight=None, clock=lambda: NOW)
    assert fresh.state.shorts_offload_pass(client) == [VID]
    assert fresh.state.runner.jobs() == []  # release never submits render work
    disabled = replace(config, store=StoreConfig(enabled=True))
    assert not StoreConfig().offload_shorts
    no_push = Mock()
    assert not shorts.push_video(disabled, VID, client=no_push)["released"]
    app_off = create_app(disabled, "pw", preflight=None, post_preflight=None)
    assert app_off.state.shorts_offload_pass(no_push) == []
    no_push.assert_not_called()
    assert not no_push.method_calls
    assert from_dict({"store": {"enabled": True, "offload_shorts": True}}).store.offload_shorts
    with pytest.raises(ConfigError, match="offload_shorts"):
        from_dict({"store": {"offload_shorts": True}})


@pytest.mark.parametrize("interrupted_after", [0, 1, 3])
def test_short_release_recovers_after_record_commit(prepared_shorts, monkeypatch, interrupted_after):
    config = prepared_shorts()
    store = MemoryShortStore()
    original = Path.unlink
    removed = []

    def interrupt(path, *a, **kw):
        if path.suffix == ".mp4":
            if len(removed) == interrupted_after:
                raise OSError("interrupted unlink")
            removed.append(path)
        return original(path, *a, **kw)

    monkeypatch.setattr(Path, "unlink", interrupt)
    with pytest.raises(OSError, match="interrupted unlink"):
        shorts.push_video(config, VID, client=store, clock=lambda: NOW)
    assert len(removed) == interrupted_after
    assert all(p is not None for eid in (VID, VID + ".kt") for _, p, _ in ep.short_locations(config, eid))
    monkeypatch.undo()
    assert shorts.push_video(config, VID, client=store, clock=lambda: NOW)["released"]
    assert ep.short_files(config, VID) == ep.short_files(config, VID + ".kt") == []


@pytest.mark.parametrize("record", [None, {"sha256": "0" * 64, "size": 10, "mtime_ns": 1},
                                     {"sha256": "current", "size": -1, "mtime_ns": 1}])
def test_short_missing_without_current_release_record_stays_missing(prepared_shorts, record):
    config = prepared_shorts(kt=False)
    cid, path, _ = ep.short_files(config, VID)[0]
    path.unlink()
    if record is not None:
        if record["sha256"] == "current":
            record["sha256"] = ep.render_manifest(config, VID)["shorts"][0]["sha256"]
        atomic_write_json(Path(config.render.output_dir) / VID / "store.json", {"released": {cid: record}})
    assert ep.short_locations(config, VID)[0][1] is None
    assert len(ep.short_files(config, VID)) == 1
    with pytest.raises(StoreMismatch, match="thiếu file"):
        shorts.push_video(config, VID, client=MemoryShortStore(), clock=lambda: NOW)
