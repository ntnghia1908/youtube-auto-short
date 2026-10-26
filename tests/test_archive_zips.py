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
