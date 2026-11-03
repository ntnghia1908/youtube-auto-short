"""PUB2S AC1–5: temporary local images and injected YouTube HTTP only."""
import json
from dataclasses import replace
from pathlib import Path
import unicodedata
from urllib.parse import parse_qs, urlparse

import pytest

from auto_short.config import PackagingConfig
from auto_short.packaging import cover, episode, khaithi_thumbs as images
from auto_short.publish import shorts, thumbs, youtube
from auto_short.publish.__main__ import main
from auto_short.render.stage import _run, probe_media
from auto_short.workspace import atomic_write_json, read_json_dict
from test_packaging_cover import source_image
from test_publish_kt import IDS, PID, YT_PID, cli, listing, wire, workspace  # noqa: F401


@pytest.fixture
def local(workspace, cli, tmp_path):
    cfg = replace(workspace, packaging=PackagingConfig(tmp_path / "assets"))
    # CLI and direct planning must see the same isolated cover/portrait catalog.
    config_path = Path(cli[cli.index("--config") + 1])
    with config_path.open("a") as stream:
        stream.write(f'[packaging]\nasset_dir = "{cfg.packaging.asset_dir}"\n')
    cover.install(cfg, PID, "kt_vertical", source_image(tmp_path), [100, 700, 880, 700])
    return cfg


@pytest.fixture
def fast_draw(monkeypatch):
    calls = []

    def draw(work, title, fields, entry, shape, image, name, **kwargs):
        calls.append((title, fields, kwargs))
        path = work / name
        path.write_bytes(b"\xff\xd8fake-jpeg:" + title.encode())
        return path

    monkeypatch.setattr(images, "draw", draw)
    return calls


def test_code_matching_and_source_episode_authority(local, fast_draw):
    sources = [
        ("  T011_S010_ Giữ  tâm.mp4", "T11 S10 Tiêu đề khác", "T11_S10", "Giữ tâm"),
        ("không mã.mp4", " T7 S1 Bình an #Phật_pháp", "T7_S01", "Bình an"),
        (None, "T7_S123_Học Phật.MP4 #tag", "T7_S123", "Học Phật"),
        ("T11_S1_Tiêu đề.mp4", "không mã", "T11_S01", "Tiêu đề"),
        ("T11_S10_x.mp4", "T7 S10 x", None, "tên file và tiêu đề lệch mã"),
        ("T11_S10_x.mp4", "T11 S9 x", None, "tên file và tiêu đề lệch mã"),
        ("prefix T11_S10_x.mp4", "", None, "không có mã Short"),
        ("T11_S1000_x.mp4", "", None, "không có mã Short"),
        ("T11_KT01_x.mp4", "", None, "không có mã Short"),
    ]
    for name, title, code, expected in sources:
        source = dict(id="uploaded001", fileDetails=dict(fileName=name),
                      snippet=dict(title=unicodedata.normalize("NFD", title)))
        row = shorts.plan(local, [source], pid=PID)[0]
        if code:
            assert (row["code"], row["title"], row["status"], row["source"]) == (code, expected, "sẵn sàng", "youtube-title")
            assert row["shape"] == "vertical" and row["video_id"] in IDS
        else:
            assert row["status"] == "bỏ qua" and row["reason"] == expected
    # A .kt entry cannot become a Short episode; two base episodes with the same header are ambiguous.
    playlist_path = local.workspace.dir / "_playlists" / f"{PID}.json"
    doc = read_json_dict(playlist_path)
    doc["entries"].append(dict(video_id=IDS[0] + ".kt"))
    atomic_write_json(playlist_path, doc)
    source = dict(id="uploaded001", snippet=dict(title="T11 S10 Giữ tâm"))
    assert shorts.plan(local, [source], pid=PID)[0]["status"] == "sẵn sàng"
    path = local.workspace.dir / IDS[1] / "titles.json"
    doc = read_json_dict(path)
    doc["header"]["fields"]["episode"] = "11"
    atomic_write_json(path, doc)
    assert "nhiều tập" in shorts.plan(local, [source], pid=PID)[0]["reason"]
    source["snippet"]["title"] = "T9 S10 Giữ tâm"
    assert "không có tập" in shorts.plan(local, [source], pid=PID)[0]["reason"]


def test_title_image_jpeg_label_cache_and_invalidation(local, monkeypatch):
    source = dict(id="uploaded001", fileDetails=dict(fileName="T11_S10_  Giữ tâm thanh tịnh.mp4 #tag"))
    actual_draw = images.draw
    calls = []

    def draw(*args, **kwargs):
        calls.append((args[1], kwargs["label"]))
        return actual_draw(*args, **kwargs)

    monkeypatch.setattr(images, "draw", draw)
    row = shorts.plan(local, [source], pid=PID)[0]
    assert row["status"] == "sẵn sàng", row
    path = Path(row["file"])
    stream = probe_media(path, _run)["video"]
    assert stream["codec_name"] == "mjpeg" and (stream["width"], stream["height"]) == (1080, 1920)
    assert 0 < path.stat().st_size <= thumbs.MAX_BYTES and path.parent.name == "short_yt_thumbs"
    before = {p: p.read_bytes() for p in path.parent.iterdir()}
    assert shorts.plan(local, [source], pid=PID) == [row]
    assert before == {p: p.read_bytes() for p in path.parent.iterdir()}
    assert calls == [("Giữ tâm thanh tịnh", "TRÍCH ĐOẠN")]
    assert not (path.parent.parent / "short_intro_thumbs").exists()
    source["fileDetails"]["fileName"] = "T11_S10_Học cách buông bỏ.mp4"
    changed = shorts.plan(local, [source], pid=PID)[0]
    assert changed["file"] != row["file"] and len(calls) == 2
    # Current cache inputs are rechecked on apply, without regenerating the image.
    box = cover.current(local, PID)["kt_vertical"]["box"]
    box[1] += 10
    cover.install(local, PID, "kt_vertical", source_image(path.parent), box)
    result = thumbs.apply(local, [changed], youtube.YouTube(transport=lambda *a: pytest.fail("unexpected HTTP")))
    assert result[0]["status"] == "bỏ qua" and "đã cũ" in result[0]["reason"] and len(calls) == 2


def test_web_numbered_image_priority_and_invalid_fallback(local, fast_draw):
    ident = IDS[0]
    atomic_write_json(local.workspace.dir / ident / "titles.json", dict(
        header=dict(fields=episode.header(local, ident)), titles=[
            dict(clip_id=cid, candidate_id=f"c{n}", title=title, status="titled")
            for n, (cid, title) in enumerate((("k01", "Một"), ("k09", "Hai")), 1)]))
    fields = images.display_fields(local, PID, episode.header(local, ident))
    for cid in ("k01", "k09"):
        images.vertical_clip(local, ident, cid, pid=PID, fields=fields, short=True)
    folder = images._clip_directory(local, ident, short=True)
    before = {p: p.read_bytes() for p in folder.iterdir()}
    source = dict(id="uploaded001", snippet=dict(title="T11 S02 Tiêu đề YouTube"))
    row = shorts.plan(local, [source], pid=PID)[0]
    assert (row["source"], row["clip_id"], row["video_id"], row["status"]) == ("web", "k09", ident, "sẵn sàng")
    assert Path(row["file"]).parent == folder and len(fast_draw) == 2
    assert thumbs.apply(local, [row], type("Fake", (), {"set_thumbnail": lambda *a: None})())[0]["status"] == "đã gắn"
    # Hash damage, absent NN, and stale title each select (b), without touching KTI2 artifacts.
    for case in ("missing-number", "stale-title", "hash"):
        if case == "missing-number":
            source["snippet"]["title"] = "T11 S03 Tiêu đề YouTube"
        elif case == "stale-title":
            source["snippet"]["title"] = "T11 S02 Tiêu đề YouTube"
            title_path = local.workspace.dir / ident / "titles.json"
            doc = read_json_dict(title_path)
            doc["titles"][1]["title"] = "Đã sửa"
            atomic_write_json(title_path, doc)
        else:
            Path(row["file"]).write_bytes(b"damaged")
            before[Path(row["file"])] = b"damaged"
        fallback = shorts.plan(local, [source], pid=PID)[0]
        assert fallback["source"] == "youtube-title" and fallback["clip_id"] in ("s02", "s03")
        assert fallback["status"] == "sẵn sàng"
        assert {p: p.read_bytes() for p in folder.iterdir()} == before


@pytest.mark.parametrize("selected_playlist", [False, True])
def test_cli_filters_apply_journal_skip_force(local, cli, wire, fast_draw, capsys, selected_playlist):
    args = ["short-thumbs", *cli[1:]]
    if not selected_playlist:
        index = args.index("--yt-playlist")
        del args[index:index + 2]
    source = [dict(id=f"uploaded00{n}", snippet=dict(title=f"T{number} S{n:02d} Giữ tâm"))
              for n, number in enumerate((7, 11, 11), 1)]
    args += ["--episodes", "10-11", "--only", " uploaded002,other "]
    for extra, posts in [((), 0), (("--apply",), 1), (("--apply",), 0), (("--apply", "--force"), 1)]:
        wire.calls.clear()
        wire.replies.extend([*([dict(items=[dict(contentDetails=dict(relatedPlaylists=dict(uploads="UPLOADS")))])]
                              if not selected_playlist else []), *listing(*source), *[dict(items=[]) for _ in range(posts)]])
        assert main([*args, *extra], transport=wire.send) == 0
        captured = capsys.readouterr()
        result = json.loads(captured.out[captured.out.index("{\n"):])
        assert [r["youtube_id"] for r in result["rows"]] == ["uploaded002"]
        assert "\tNguồn\t" in captured.out and not captured.err and not wire.replies
        assert len([c for c in wire.calls if c[0] == "POST"]) == posts
        queries = [parse_qs(urlparse(c[1]).query) for c in wire.calls if c[0] == "GET"]
        assert queries[0 if selected_playlist else 1]["playlistId"] == [YT_PID if selected_playlist else "UPLOADS"]
        if not extra:
            assert not (local.workspace.dir / "_publish").exists()
        else:
            journal = thumbs._journal(local)[1]
            assert journal["schema_version"] == 1 and len(journal["records"]) == 1
            record = journal["records"][0]
            assert record["video_id"] == IDS[0] and record["clip_id"] == "s02" and record["code"] == "T11_S02"
            # Episode matching must ignore Short records, even when video_id is a base episode.
            row = thumbs.plan(local, [dict(id="uploaded002")], pid=PID, journal=journal)[0]
            assert row["status"] == "bỏ qua" and not row["matched_by"]


def test_77_short_dry_run_in_episode_range(local, cli, wire, fast_draw, capsys):
    entries, source = [], []
    for number, count in enumerate((6, 8, 10, 8, 6, 10, 9, 10, 10), 1):
        ident = f"lecture{number:04d}"
        atomic_write_json(local.workspace.dir / ident / "titles.json", dict(
            header=dict(fields=dict(series="Địa Tạng", episode=str(number), speaker="HT. Tịnh Không"))))
        entries.append(dict(video_id=ident, episode="999"))
        source.extend(dict(id=f"uploaded{number:02d}{n:02d}", snippet=dict(title=f"T{number} S{n:02d} Giữ tâm"))
                      for n in range(1, count + 1))
    atomic_write_json(local.workspace.dir / "_playlists" / f"{PID}.json", dict(playlist_id=PID, entries=entries))
    args = ["short-thumbs", *cli[1:], "--episodes", "1-9"]
    wire.replies.extend([dict(items=[dict(contentDetails=dict(videoId=v["id"])) for v in source]),
                         *[dict(items=source[offset:offset + 50]) for offset in (0, 50)]])
    assert main(args, transport=wire.send) == 0
    captured = capsys.readouterr()
    rows = json.loads(captured.out[captured.out.index("{\n"):])["rows"]
    assert len(rows) == 77 and all(r["status"] == "sẵn sàng" and r["source"] == "youtube-title" for r in rows)
    assert len(fast_draw) == 77 and all(c[0] == "GET" for c in wire.calls) and not wire.replies
    assert not (local.workspace.dir / "_publish").exists()


@pytest.mark.parametrize("damage", ["hash", "missing", "oversize", "metadata", "sidecar"])
@pytest.mark.parametrize("source_kind", ["web", "youtube-title"])
def test_apply_revalidates_short_images(local, fast_draw, wire, damage, source_kind):
    ident = IDS[0]
    if source_kind == "web":
        path = local.workspace.dir / ident / "titles.json"
        doc = read_json_dict(path)
        doc["titles"] = [dict(clip_id="k01", candidate_id="c01", title="Giữ tâm", status="titled")]
        atomic_write_json(path, doc)
        images.vertical_clip(local, ident, "k01", pid=PID, fields=episode.header(local, ident), short=True)
    row = shorts.plan(local, [dict(id="uploaded001", snippet=dict(title="T11 S01 Giữ tâm"))], pid=PID)[0]
    assert row["source"] == source_kind
    path = Path(row["file"])
    if damage == "metadata":
        atomic_write_json(local.workspace.dir / ident / "titles.json", dict(header=dict(fields={})))
    elif damage == "sidecar":
        atomic_write_json(path.parent / "thumbs.json", dict(schema_version=1, video_id=ident, clips=[]))
    elif damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"x" * (thumbs.MAX_BYTES + 1) if damage == "oversize" else b"damaged")
    result = thumbs.apply(local, [row], youtube.YouTube(transport=wire.send))
    assert result[0]["status"] == "bỏ qua" and result[0]["reason"] and not wire.calls
    assert not (local.workspace.dir / "_publish").exists()
