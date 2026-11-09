"""FAVZIP1: ordered favorites ZIPs, store integrity, validation and part controls."""

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("fastapi")

from auto_short.compilation import Item, store
from auto_short.review import content_disposition
from auto_short.review.names import MAX_SERIES_BYTES, favorites_zip_name
from auto_short.store import shorts as store_shorts
from auto_short.store.client import StoreClient, StoreMismatch
from auto_short.web.routes import files, files_catchall
from auto_short.workspace import atomic_write_json
from compilation_helpers import PL
from test_store_shorts import MemoryShortStore, NOW, VID, prepared_shorts  # noqa: F401
from test_web_listen import run_player_js  # noqa: F401
from web_helpers import login, make_app

URL = f"/files/playlists/{PL}/favorites.zip"
ITEMS = f"{VID}.kt/k02,{VID}/k01"


@pytest.fixture
def favorite_zip(prepared_shorts, monkeypatch):
    config = prepared_shorts()
    doc = {"schema_version": 1, "playlist_id": PL, "title": "Danh sách thử", "series": "Bộ thử",
           "url": f"https://www.youtube.com/playlist?list={PL}", "fetched_at": "2026-10-01T00:00:00Z",
           "entries": [{"index": 1, "video_id": VID, "title": "Tập 3", "episode": "3", "available": True}]}
    atomic_write_json(Path(config.workspace.dir) / "_playlists" / f"{PL}.json", doc)
    for eid in (VID, VID + ".kt"):
        atomic_write_json(Path(config.workspace.dir) / eid / "titles.json",
                          {"header": {"fields": {"episode": "3", "series": "Bộ thử"}}})
    app = make_app(config)
    service = app.state.compilations
    store.write_favorites(service.folder(PL), [Item(VID, "k01"), Item(VID + ".kt", "k02")])
    # Same synchronous capture as ARC1: consume the real generator without an event-loop socketpair.
    bodies, stream = [], files_catchall._zip_stream

    def capture(items, **kw):
        bodies.append(b"".join(stream(items, **kw)))
        return iter([bodies[-1]])

    monkeypatch.setattr(files_catchall, "_zip_stream", capture)
    ctx = SimpleNamespace(config=config, compilations=service, mark_downloaded=Mock(), tracked=Mock(),
                          playlist_or_404=lambda pid: doc if pid == PL else None)
    endpoint = next(r.endpoint for r in files.build(ctx).routes if r.path == URL.replace(PL, "{playlist_id}"))
    return SimpleNamespace(config=config, app=app, service=service, endpoint=endpoint, bodies=bodies, ctx=ctx)


@pytest.mark.parametrize("filter,kind", [("short", "Shorts"), ("khaithi", "KhaiThị"), ("both", "Shorts+KhaiThị")])
def test_favorites_zip_name(filter, kind):
    assert favorites_zip_name(2, filter=filter, series=" /:* ") == f"YeuThich_{kind}_Phan2.zip"
    name = favorites_zip_name(3, filter=filter, series="Bộ / thử : " * 30)
    head, tail = name.split("_YeuThich_")
    assert len(head.encode("utf-8")) <= MAX_SERIES_BYTES and "/" not in head and ":" not in head
    assert tail == f"{kind}_Phan3.zip"


def test_local_zip_order_manifest_and_no_publication_or_tracking(favorite_zip):
    f = favorite_zip
    # An existing published file and a never-published episode must both stay unchanged.
    unpublished = Path(f.config.workspace.dir) / (VID + ".kt") / "publish.json"
    unpublished.unlink()
    published = Path(f.config.workspace.dir) / VID / "publish.json"
    before = published.read_bytes()
    response = f.endpoint(PL, items=ITEMS, filter="both", part="2")
    assert response.status_code == 200 and response.media_type == "application/zip"
    assert response.headers["content-disposition"] == content_disposition("Bộ thử_YeuThich_Shorts+KhaiThị_Phan2.zip")
    assert response.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(f.bodies[-1])) as zf:
        names = ["01_T3_KT02_Tiêu đề k02.mp4", "02_T3_S01_Tiêu đề k01.mp4", "danh-sach.txt"]
        assert zf.namelist() == names and zf.testzip() is None
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_STORED
        for name, eid, cid in [(names[0], VID + ".kt", "k02"), (names[1], VID, "k01")]:
            assert zf.read(name) == (Path(f.config.render.output_dir) / eid / "shorts" / f"{cid}.mp4").read_bytes()
        assert zf.read("danh-sach.txt").decode("utf-8").splitlines() == [
            "Bộ thử — Phần 2 — Short + Khai thị — Tổng thời lượng: 02:01",
            "01. T3_KT02 — Tiêu đề k02", "02. T3_S01 — Tiêu đề k01"]
    assert published.read_bytes() == before and not unpublished.exists()
    f.ctx.mark_downloaded.assert_not_called()
    f.ctx.tracked.assert_not_called()


@pytest.mark.parametrize("state", ["up", "down", "sha"])
def test_stored_short_zip_integrity_and_unavailable(favorite_zip, monkeypatch, state):
    f, client = favorite_zip, MemoryShortStore()
    originals = {c.item: c.path.read_bytes() for c in f.service.clips(f.app.state.playlists.load(PL))}
    assert store_shorts.push_video(f.config, VID, client=client, clock=lambda: NOW)["released"]
    monkeypatch.setattr(StoreClient, "from_config", lambda _: client)
    if state == "down":
        client.up = False
        response = f.endpoint(PL, items=ITEMS, filter="both", part="1")
        assert response.status_code == 503 and json.loads(response.body)["detail"] == "3090 đang tắt"
        assert not client.streams and not f.bodies
    elif state == "sha":
        data = client.data[VID + ".kt", "k02.mp4"]
        client.data[VID + ".kt", "k02.mp4"] = b"x" * len(data)
        with pytest.raises(StoreMismatch):
            f.endpoint(PL, items=ITEMS, filter="both", part="1")
        assert client.streams[-1].close.called and not f.bodies
    else:
        assert f.endpoint(PL, items=ITEMS, filter="both", part="1").status_code == 200
        with zipfile.ZipFile(io.BytesIO(f.bodies[-1])) as zf:
            assert [zf.read(n) for n in zf.namelist()[:-1]] == [
                originals[Item(VID + ".kt", "k02")], originals[Item(VID, "k01")]]
        assert all(s.close.called for s in client.streams)


@pytest.mark.parametrize("params", [
    {}, {"items": ""}, {"items": f"{VID}/k02"}, {"items": f"{VID}/k01,{VID}/k01"},
    {"items": "../k01"}, {"items": f"{VID}/k01/extra"}, {"items": f"{VID}/"},
    {"items": f"{VID}/k01,"}, {"items": f"{VID}/k01," * 500 + f"{VID}/k01"},
    {"filter": "invalid"}, {"filter": ""}, {"filter": "short"},
    {"part": "0"}, {"part": "-1"}, {"part": "1.5"}, {"part": "x"}, {"part": ""},
])
def test_invalid_favorites_zip_rejected_before_stream(favorite_zip, monkeypatch, params):
    f = favorite_zip
    called = Mock(side_effect=AssertionError("must reject before opening ZIP"))
    monkeypatch.setattr(files_catchall, "_zip_stream", called)
    args = {"items": ITEMS, "filter": "both", "part": "1", **params}
    if not params:
        args = {}
    assert f.endpoint(PL, **args).status_code == 400
    assert f.endpoint("PLunknown000", **args).status_code == 404
    called.assert_not_called()


def test_kept_favorite_and_missing_kept_file(favorite_zip):
    f = favorite_zip
    item = Item("bbbbbbbbbb2.kt", "k01", kept={
        "path": "kept/bbbbbbbbbb2.kt/k01.mp4", "title": "Bản giữ lại", "duration": 30,
        "episode_number": "9", "clip_number": 1, "clip_total": 1, "saved_at": "2026-10-01T00:00:00Z"})
    folder = f.service.folder(PL)
    path = folder / item.kept["path"]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"kept favorite")
    store.write_favorites(folder, [item])
    args = {"items": f"{item.episode_id}/{item.clip}", "filter": "khaithi", "part": "1"}
    assert f.endpoint(PL, **args).status_code == 200
    with zipfile.ZipFile(io.BytesIO(f.bodies[-1])) as zf:
        assert zf.read("01_T9_KT01_Bản giữ lại.mp4") == b"kept favorite"
    path.unlink()
    assert f.endpoint(PL, **args).status_code == 400 and len(f.bodies) == 1


def test_web_auth_and_favorites_zip(favorite_zip):
    """ORCHESTRATOR runs with TestClient sockets available."""
    from fastapi.testclient import TestClient

    with TestClient(favorite_zip.app, follow_redirects=False) as client:
        params = {"items": ITEMS, "filter": "both", "part": "1", "dl": "favorites_token"}
        assert client.get(URL, params=params).status_code == 401
        login(client)
        assert client.get(URL, params={**params, "filter": "wrong"}).status_code == 400
        response = client.get(URL, params=params)
        assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            assert zf.namelist()[-1] == "danh-sach.txt"
        assert client.get("/api/downloads/favorites_token").status_code == 404


def test_download_controls_use_grouped_favorites(run_player_js):
    run_player_js(r'''
sourceItems = Array.from({length: 38}, (_, n) => item(1, n));
sourceItems.push(item(1, 1, "khaithi"));
storage.set("auto-short-listen-filter", '"short"');
await boot();
const link = $("download-link"), pick = $("download-part");
function params() { return new URL(link.href, location.origin).searchParams; }
assert.equal($("download").hidden, false);
assert.deepEqual(pick.children.map(o => o.textContent), ["Phần 1 (bài 1–35)", "Phần 2 (bài 36–38)"]);
assert.equal(params().get("items"), Player.groupFavorites(sourceItems.filter(i => i.kind === "short"), "short")
  .filter(i => i.group.label === "Phần 1").map(i => `${i.episode_id}/${i.clip_id}`).join(","));
pick.value = pick.children[1].value; await pick.fire("change");
assert.equal(params().get("part"), "2"); assert.equal(params().get("items"), "ep1/k35,ep1/k36,ep1/k37");
await $("filter").children[1].fire("click");
assert.equal(params().get("filter"), "khaithi"); assert.equal(params().get("part"), "1");
assert.equal(params().get("items"), "ep1.kt/k1");
await $("favorite").fire("click");
assert.equal($("download").hidden, true); assert.equal(link.attrs.href, undefined);
// Unusable favorites never enter a download, even when the listening API supplied them.
sourceItems = [item(1, 1), {...item(1, 2), usable: false}];
storage.set("auto-short-listen-filter", '"both"');
await boot();
assert.equal(params().get("items"), "ep1/k1");
assert.equal(pick.children[0].textContent, "Phần 1 (Tập 1–1)");
''')
