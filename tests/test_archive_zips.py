"""ARC1: socket-free ZIP/route tests; web_auth also exercises the app's auth middleware."""

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("fastapi")

from auto_short import khaithi
from auto_short.khaithi import KhaiThi
from auto_short.review import content_disposition
from auto_short.review.publish import mark_downloaded
from auto_short.store import shorts as store_shorts
from auto_short.store.client import StoreClient, StoreMismatch, StoreRangeError, StoreUnavailable
from test_store_shorts import MemoryShortStore, NOW, prepared_shorts
from auto_short.web import episodes as ep
from auto_short.web.routes import files_catchall as routes
from web_helpers import login, web_client, write_episode

VID = "aaaaaaaaaa1"
SERIES = "Thập Thiện Nghiệp Đạo Kinh"


@pytest.fixture
def pair(tcfg):
    def make(vid=VID, *, series=SERIES, episode="29", shorts=True, kt=True):
        for eid, enabled in ((vid, shorts), (vid + ".kt", kt)):
            if not enabled:
                continue
            write_episode(tcfg, eid)
            if eid.endswith(".kt"):
                khaithi.write(Path(tcfg.workspace.dir) / eid, KhaiThi(vid, 4, 7))
            header = {"header": {"fields": {"series": series, "episode": episode}}}
            (Path(tcfg.workspace.dir) / eid / "titles.json").write_text(json.dumps(header), encoding="utf-8")
    return make


@pytest.mark.parametrize("episode_id", [VID, VID + ".kt"])
@pytest.mark.parametrize("normal_archive", [None, "0"])
def test_archive_zip_same_bytes_without_publish_or_tracking(tcfg, pair, monkeypatch, episode_id, normal_archive):
    pair()
    bodies = []
    stream = routes._zip_stream

    def capture(items):
        # Consume the real ZIP generator synchronously, without an ASGI event loop / sockets.
        bodies.append(b"".join(stream(items)))
        return iter([bodies[-1]])

    monkeypatch.setattr(routes, "_zip_stream", capture)
    ctx = SimpleNamespace(config=tcfg, tracked=Mock(side_effect=lambda dl, response: response),
                          mark_downloaded=Mock(side_effect=lambda eid, ids: mark_downloaded(eid, tcfg, ids)))
    endpoint = next(r.endpoint for r in routes.build(ctx).routes if r.path.startswith("/files/"))
    response = endpoint(episode_id, "all.zip", archive="1", dl="archive_token")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == content_disposition(ep.all_zip(tcfg, VID)[1])
    ctx.tracked.assert_not_called()
    ctx.mark_downloaded.assert_not_called()
    for eid in (VID, VID + ".kt"):
        assert not (Path(tcfg.workspace.dir) / eid / "publish.json").exists()
    with zipfile.ZipFile(io.BytesIO(bodies[0])) as zf:
        assert zf.testzip() is None
        assert zf.namelist() == [entry for _, _, entry in ep.all_zip(tcfg, VID)[0]]
    normal = endpoint(episode_id, "all.zip", archive=normal_archive, dl="web_token")
    assert normal.headers == response.headers and bodies[0] == bodies[1]
    ctx.tracked.assert_called_once_with("web_token", normal)
    assert ctx.mark_downloaded.call_count == 2
    for eid in (VID, VID + ".kt"):
        published = json.loads((Path(tcfg.workspace.dir) / eid / "publish.json").read_text())
        assert [item["clip_id"] for item in published["published"]] == ["k01", "k02"]
    # The archive option only applies to all.zip; shorts.zip keeps CP8.31 behavior.
    endpoint(episode_id, "shorts.zip", archive="1")
    assert ctx.mark_downloaded.call_count == 3 and ctx.tracked.call_count == 2


def test_archive_listing_fields_order_and_incomplete_pairs(tcfg, pair, monkeypatch):
    pair(episode="10")
    pair("aaaaaaaaaa2", episode="2")
    pair("aaaaaaaaaa3", series=None, episode=None)
    pair("aaaaaaaaaa4", kt=False)
    pair("aaaaaaaaaa5", shorts=False)
    pair("aaaaaaaaaa6", series='Z/a:b', episode="1")
    pair("aaaaaaaaaa7")
    (Path(tcfg.render.output_dir) / "aaaaaaaaaa7.kt" / "shorts" / "k01.mp4").unlink()
    (Path(tcfg.render.output_dir) / "aaaaaaaaaa7.kt" / "shorts" / "k02.mp4").unlink()
    # Metadata JSON may be read, but no MP4 content may be opened by the listing.
    original_open = Path.open

    def no_video_read(path, *args, **kwargs):
        assert path.suffix != ".mp4", "listing must only stat video files"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_video_read)
    router = routes.build(SimpleNamespace(config=tcfg))
    endpoint = next(r.endpoint for r in router.routes if r.path == "/api/archive/zips")
    rows = endpoint()
    assert [r["video_id"] for r in rows] == ["aaaaaaaaaa3", "aaaaaaaaaa2", VID, "aaaaaaaaaa6"]
    assert rows[0]["episode"] is None and rows[0]["series"] == ""
    assert rows[-1]["series"] == "Zab"
    assert rows == endpoint()
    for row in rows:
        entries, name = ep.all_zip(tcfg, row["video_id"])
        expected = "".join(f"{n}|{p.stat().st_size}|{p.stat().st_mtime_ns}\n" for _, p, n in entries)
        assert row == {"video_id": row["video_id"], "series": row["series"], "episode": row["episode"],
                       "name": name, "files": len(entries), "bytes": sum(p.stat().st_size for _, p, _ in entries),
                       "fingerprint": hashlib.sha256(expected.encode("utf-8")).hexdigest(),
                       "url": f"/files/{row['video_id']}/all.zip?archive=1"}
    assert [r["episode"] for r in rows[1:3]] == [2, 10]


@pytest.mark.parametrize("change", ["mtime", "size", "entry_name"])
def test_archive_fingerprint_changes_on_rerender(tcfg, pair, change):
    pair()
    before = ep.archive_zips(tcfg)[0]
    path = ep.all_zip(tcfg, VID)[0][0][1]
    if change == "mtime":
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    elif change == "size":
        path.write_bytes(b"new render with a different size")
    else:
        manifest = Path(tcfg.render.output_dir) / VID / "render_manifest.json"
        doc = json.loads(manifest.read_text())
        doc["shorts"][0]["title"] = "Tên mới"
        manifest.write_text(json.dumps(doc), encoding="utf-8")
    after = ep.archive_zips(tcfg)[0]
    assert before["fingerprint"] != after["fingerprint"]
    assert (before["bytes"] != after["bytes"]) == (change == "size")


def test_web_auth_and_archive_download(tcfg, pair):
    """Run outside a sandbox that blocks TestClient's event-loop socketpair."""
    pair()
    with web_client(tcfg) as client:
        assert client.get("/api/archive/zips").status_code == 401
        assert client.get(f"/files/{VID}/all.zip?archive=1").status_code == 401
        login(client)
        rows = client.get("/api/archive/zips").json()
        assert len(rows) == 1 and rows[0]["video_id"] == VID
        response = client.get(rows[0]["url"] + "&dl=archive_token")
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            assert zf.testzip() is None and len(zf.infolist()) == rows[0]["files"]
            assert sum(i.file_size for i in zf.infolist()) == rows[0]["bytes"]
        for eid in (VID, VID + ".kt"):
            assert not (Path(tcfg.workspace.dir) / eid / "publish.json").exists()
        assert client.get("/api/downloads/archive_token").status_code == 404
        assert client.get(f"/files/{VID}/all.zip").content == response.content
        for eid in (VID, VID + ".kt"):
            assert (Path(tcfg.workspace.dir) / eid / "publish.json").exists()


@pytest.mark.parametrize("clips", [("k01", "k02"), ("k01", "m01")])
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("name,archive", [("shorts.zip", None), ("all.zip", None), ("all.zip", "1")])
def test_released_zip_bytes_metadata_fingerprint_and_store_down(prepared_shorts, monkeypatch, partial, name, archive, clips):
    config = prepared_shorts(clips=clips)
    before = ep.archive_zips(config)
    originals = ep.all_zip(config, VID)[0] if name == "all.zip" else ep.short_files(config, VID)
    expected = {n: p.read_bytes() for _, p, n in originals}
    local_zip = b"".join(routes._zip_stream(originals))
    store = MemoryShortStore()
    assert store_shorts.push_video(config, VID, client=store, clock=lambda: NOW)["released"]
    if partial:
        # A local file can coexist with its durable release record (e.g. a stopped unlink pass).
        saved = ep.short_locations(config, VID)[0][1]
        path = Path(config.render.output_dir) / VID / "shorts" / saved.clip
        path.write_bytes(store.data[VID, saved.clip])
        os.utime(path, ns=(saved.mtime_ns, saved.mtime_ns))
    assert ep.archive_zips(config) == before
    monkeypatch.setattr(StoreClient, "from_config", lambda _: store)
    bodies, real_stream = [], routes._zip_stream

    def capture(items, **kw):
        bodies.append(b"".join(real_stream(items, **kw)))
        return iter([bodies[-1]])

    monkeypatch.setattr(routes, "_zip_stream", capture)
    ctx = SimpleNamespace(config=config, tracked=Mock(side_effect=lambda dl, response: response), mark_downloaded=Mock())
    endpoint = next(r.endpoint for r in routes.build(ctx).routes if r.path.startswith("/files/"))
    response = endpoint(VID, name, archive=archive)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(bodies[0])) as remote, zipfile.ZipFile(io.BytesIO(local_zip)) as local:
        assert remote.testzip() is None
        assert {n: remote.read(n) for n in remote.namelist()} == expected
        assert [i.date_time for i in remote.infolist()] == [i.date_time for i in local.infolist()]
    assert all(s.close.called for s in store.streams)
    assert ctx.mark_downloaded.call_count == (0 if archive == "1" else (2 if name == "all.zip" else 1))
    ctx.mark_downloaded.reset_mock()
    store.up = False
    response = endpoint(VID, name, archive=archive)
    assert response.status_code == 503 and json.loads(response.body)["detail"] == "3090 đang tắt"
    ctx.mark_downloaded.assert_not_called()
    assert len(bodies) == 1  # Reject before opening a ZIP stream.


@pytest.mark.parametrize("clip_id", ["k01", "m01"])
@pytest.mark.parametrize("range_header,download,error,status", [(None, None, None, 200),
    ("bytes=2-9", "1", None, 206), (None, "1", "down", 503),
    ("bytes=999999-", "1", "range", 416), (None, "1", "missing", 404)])
def test_released_short_play_download_range_and_errors(prepared_shorts, monkeypatch, range_header, download, error, status, clip_id):
    config = prepared_shorts(clips=(clip_id,))
    store = MemoryShortStore()
    assert store_shorts.push_video(config, VID, client=store, clock=lambda: NOW)["released"]
    original = store.open_stream
    request = SimpleNamespace(headers={"range": range_header} if range_header else {})
    calls = []

    def stream(eid, kind, value=None, *, clip):
        calls.append((eid, kind, value, clip))
        if error == "down":
            raise StoreUnavailable("down")
        if error == "range":
            raise StoreRangeError("bytes */1003")
        if error == "missing":
            raise StoreMismatch("missing")
        return original(eid, kind, value, clip=clip)

    monkeypatch.setattr(StoreClient, "from_config", lambda _: SimpleNamespace(open_stream=stream))
    ctx = SimpleNamespace(config=config, tracked=lambda dl, response: response, mark_downloaded=Mock())
    endpoint = next(r.endpoint for r in routes.build(ctx).routes if r.path.startswith("/files/"))
    response = endpoint(VID + ".kt", clip_id + ".mp4", download=download, request=request)
    assert response.status_code == status
    assert calls == [(VID + ".kt", "short", range_header, clip_id + ".mp4")]
    if status in (200, 206):
        data = b"".join(response.stream)
        response.stream.close()
        expected = store.data[VID + ".kt", clip_id + ".mp4"]
        assert data == (expected[2:10] if range_header else expected)
        assert response.headers["content-length"] == str(len(data))
        assert response.headers["accept-ranges"] == "bytes"
        assert ("content-disposition" in response.headers) == bool(download)
        if range_header:
            assert response.headers["content-range"] == f"bytes 2-9/{len(expected)}"
    if status == 416:
        assert response.headers["content-range"] == "bytes */1003"
    if download and status in (200, 206):
        ctx.mark_downloaded.assert_called_once_with(VID + ".kt", [clip_id])
    else:
        ctx.mark_downloaded.assert_not_called()


@pytest.mark.parametrize("failure", ["disconnect", "truncated", "sha"])
def test_released_zip_failure_closes_upstream_without_complete_archive(failure):
    stored = ep.StoredShort(VID, "k01.mp4", hashlib.sha256(b"abc").hexdigest(), 3, 1_700_000_000_000_000_000)
    class Broken:
        close = Mock()

        def __iter__(self):
            yield b"bad" if failure == "sha" else b"ab"
            if failure == "disconnect":
                raise StoreUnavailable("connection lost")
    stream = Broken()
    generator = routes._zip_stream([("k01", stored, "k01.mp4")],
                                    client=SimpleNamespace(open_stream=lambda *a, **kw: (200, {}, stream)))
    data = next(generator)
    with pytest.raises((StoreUnavailable, StoreMismatch)):
        b"".join(generator)
    stream.close.assert_called_once()
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(data))


def test_released_routes_disabled_store_never_contact_it(prepared_shorts, monkeypatch):
    from dataclasses import replace
    from auto_short.config import StoreConfig
    config = prepared_shorts()
    store = MemoryShortStore()
    store_shorts.push_video(config, VID, client=store, clock=lambda: NOW)
    config = replace(config, store=StoreConfig())
    upstream = Mock()
    monkeypatch.setattr(StoreClient, "from_config", lambda _: upstream)
    ctx = SimpleNamespace(config=config, tracked=lambda dl, response: response, mark_downloaded=Mock())
    endpoint = next(r.endpoint for r in routes.build(ctx).routes if r.path.startswith("/files/"))
    for name in ("k01.mp4", "shorts.zip", "all.zip"):
        response = endpoint(VID, name, download="1")
        assert response.status_code == 503
    assert not upstream.method_calls
    ctx.mark_downloaded.assert_not_called()
