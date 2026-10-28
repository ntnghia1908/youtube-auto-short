"""THUMB1 AC4–5: title precedence, measured wrapping, cache and shared playlist output."""
import io
import zipfile

import pytest

from auto_short.hashing import sha256_file
from auto_short.packaging import PackageError, cover, episode, khaithi_thumbs as kt, thumbnail
from auto_short.render.stage import _run, probe_media
from auto_short.render.text import Font
from auto_short.review.logic import empty_review
from auto_short.workspace import atomic_write_json
from test_packaging_cover import source_image
from test_packaging_episode import IDS, PID, seed_episodes

TITLE = "Giữ tâm thanh tịnh trong cuộc sống để được an lạc mỗi ngày"


def seed_kt(cfg):
    ident = IDS[0] + ".kt"
    folder = cfg.workspace.dir / ident
    from auto_short.khaithi import KhaiThi, write
    write(folder, KhaiThi(IDS[0], 4, 7))
    atomic_write_json(folder / "titles.json", dict(header=dict(fields=episode.header(cfg, IDS[0])), titles=[
        dict(clip_id="k01", candidate_id="c01", title="Lời giảng về tâm thanh tịnh", status="titled"),
        dict(clip_id="k02", candidate_id="c02", title="Học cách buông bỏ", status="titled")]))
    return ident


@pytest.fixture
def cfg(tmp_path):
    cfg = seed_episodes(tmp_path)
    seed_kt(cfg)
    for shape, size in thumbnail.EPISODE_SIZES.items():
        w, h = size
        cover.install(cfg, PID, "kt_" + shape, source_image(tmp_path, size),
                      [int(w * .1), int(h * .4), int(w * .8), int(h * .45)])
    return cfg


def test_override_stale_rejected_and_two_shapes_cache(cfg):
    ident = IDS[0] + ".kt"
    review = empty_review(ident)
    review["titles"] = [dict(clip_id="k01", candidate_id="c01", title=TITLE, origin="manual"),
                        dict(clip_id="k02", candidate_id="stale", title="Sai", origin="manual")]
    atomic_write_json(cfg.workspace.dir / ident / "review.json", review)
    selected = kt.titles(cfg, ident)
    assert selected[0].title == TITLE and selected[1].title == "Học cách buông bỏ"
    counts = kt.build_episode(cfg, ident, pid=PID)
    assert counts == dict(built=4, reused=0, skipped_reason=None)
    files = kt.valid_files(cfg, ident)
    assert set(files) == {"k01", "k02"} and all(set(f) == set(thumbnail.EPISODE_SIZES) for f in files.values())
    for entry in files["k01"].values():
        path = kt.directory(cfg, ident) / entry["file"]
        stream = probe_media(path, _run)["video"]
        shape = "vertical" if "vertical" in entry["file"] else "landscape"
        assert (stream["width"], stream["height"]) == thumbnail.EPISODE_SIZES[shape]
        assert path.stat().st_size <= thumbnail.MAX_BYTES
    def no_render(_):
        pytest.fail("unchanged KT called ffmpeg")
    assert kt.build_episode(cfg, ident, pid=PID, run=no_render) == dict(built=0, reused=4, skipped_reason=None)
    review["titles"][0]["title"] = "Học cách sống an vui"
    atomic_write_json(cfg.workspace.dir / ident / "review.json", review)
    assert set(kt.valid_files(cfg, ident)) == {"k02"}
    assert kt.build_episode(cfg, ident, pid=PID)["built"] == 2
    review["rejected"] = [dict(clip_id="k02", candidate_id="c02")]
    atomic_write_json(cfg.workspace.dir / ident / "review.json", review)
    assert [t.clip_id for t in kt.titles(cfg, ident)] == ["k01"]
    assert set(kt.valid_files(cfg, ident)) == {"k01"}


@pytest.mark.parametrize("box", [[100, 700, 800, 700], [120, 290, 1040, 320]])
def test_long_title_fits_at_most_three_lines(box):
    font = Font(thumbnail.EPISODE_FONTS[cover.FONT_NAME])
    lines = kt.title_lines(TITLE, "374", box)
    assert 2 <= len(lines) <= 4 and lines[-1].text == "TẬP 374"
    assert " ".join(line.text for line in lines[:-1]) == TITLE
    assert lines[-1].size < lines[0].size
    x, y, w, h = box
    for line in lines:
        top, bottom = font.ink_bounds(line.text, line.size)
        assert font.width(line.text, line.size) <= w * cover.FIT_WIDTH
        assert y <= line.y + top - 2 and line.y + bottom + 4 <= y + h


def test_cover_box_image_layout_font_and_number_invalidate(cfg, tmp_path, monkeypatch):
    ident = IDS[0] + ".kt"
    kt.build_episode(cfg, ident, pid=PID)
    before = kt.valid_files(cfg, ident)
    entries = cover.current(cfg, PID)
    image = cover.directory(cfg, PID) / entries["kt_vertical"]["file"]
    box = list(entries["kt_vertical"]["box"])
    box[1] += 8
    cover.install(cfg, PID, "kt_vertical", image, box)
    assert all(set(files) == {"landscape"} for files in kt.valid_files(cfg, ident).values())
    kt.build_episode(cfg, ident, pid=PID)
    cover.install(cfg, PID, "kt_vertical", source_image(tmp_path, color="0x311d50"), box)
    assert all(set(files) == {"landscape"} for files in kt.valid_files(cfg, ident).values())
    kt.build_episode(cfg, ident, pid=PID)
    monkeypatch.setattr(kt, "LAYOUT_VERSION", 999)
    assert not kt.valid_files(cfg, ident)
    monkeypatch.setattr(kt, "LAYOUT_VERSION", 1)
    assert kt.valid_files(cfg, ident)
    monkeypatch.setitem(thumbnail.EPISODE_FONTS, cover.FONT_NAME, thumbnail.EPISODE_FONTS["sans"])
    assert not kt.valid_files(cfg, ident)
    monkeypatch.undo()
    fields = dict(episode.header(cfg, IDS[0]), episode="777")
    atomic_write_json(cfg.workspace.dir / IDS[0] / "titles.json", dict(header=dict(fields=fields)))
    assert not kt.valid_files(cfg, ident)


@pytest.mark.parametrize("damage", ["bytes", "symlink", "title", "record"])
def test_kt_download_validation_fails_closed(cfg, tmp_path, damage):
    ident = IDS[0] + ".kt"
    kt.build_episode(cfg, ident, pid=PID)
    doc = kt.read(cfg, ident)
    path = kt.directory(cfg, ident) / doc["clips"]["k01"]["vertical"]["file"]
    if damage == "bytes":
        path.write_bytes(b"tampered")
    elif damage == "symlink":
        path.unlink()
        path.symlink_to(tmp_path)
    elif damage == "title":
        (cfg.workspace.dir / ident / "titles.json").write_text("{}")
    else:
        doc["clips"]["k01"]["vertical"]["file"] = "../secret.jpg"
        atomic_write_json(kt.directory(cfg, ident) / "thumbs.json", doc)
    files = kt.valid_files(cfg, ident)
    assert "vertical" not in files.get("k01", {})


def test_no_kt_cover_skipped_with_reason_and_playlist_build(cfg):
    for shape in ("kt_vertical", "kt_landscape"):
        cover.remove(cfg, PID, shape)
    result = kt.build_episode(cfg, IDS[0] + ".kt", pid=PID)
    assert not result["built"] and "chưa có ảnh bìa khai thị" in result["skipped_reason"]
    summary = episode.build_playlist(cfg, PID)
    assert summary["built"] == 2
    assert summary["khaithi"]["skipped"][0]["reason"] == result["skipped_reason"]


def test_playlist_build_contains_kt_and_episode_bytes_unchanged(cfg, tmp_path):
    for shape, size in thumbnail.EPISODE_SIZES.items():
        cover.install(cfg, PID, shape, source_image(tmp_path, size), [200, size[1] - 300, 600, 150])
    episode.build_episode(cfg, IDS[0], pid=PID)
    old = episode.read(cfg, IDS[0])
    hashes = {s: sha256_file(episode.directory(cfg, IDS[0]) / e["file"]) for s, e in old["files"].items()}
    summary = episode.build_playlist(cfg, PID)
    assert summary["khaithi"] == dict(built=4, reused=0, skipped=[])
    assert hashes == {s: sha256_file(episode.directory(cfg, IDS[0]) / e["file"]) for s, e in episode.read(cfg, IDS[0])["files"].items()}
    assert old == episode.read(cfg, IDS[0])


def test_playlist_zip_includes_only_verified_kt_files(cfg):
    from types import SimpleNamespace
    from auto_short.web.episode_thumbs import EpisodeThumbs
    summary = episode.build_playlist(cfg, PID)
    assert summary["khaithi"]["built"] == 4
    service = EpisodeThumbs(SimpleNamespace(config=cfg, runner=SimpleNamespace(latest=lambda _: None)))
    data, _ = service.archive(PID)
    expected = {f"khai-thi/T101_KT{n:02d}_{shape}.jpg" for n in (1, 2) for shape in ("vertical", "landscape")}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert expected <= set(archive.namelist())
        assert {"T101_ngang.jpg", "T101_doc.jpg", "T102_ngang.jpg", "T102_doc.jpg"} <= set(archive.namelist())
    ident = IDS[0] + ".kt"
    entry = kt.valid_files(cfg, ident)["k01"]["vertical"]
    (kt.directory(cfg, ident) / entry["file"]).write_bytes(b"tampered")
    data, _ = service.archive(PID)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert "khai-thi/T101_KT01_vertical.jpg" not in archive.namelist()
        assert (expected - {"khai-thi/T101_KT01_vertical.jpg"}) <= set(archive.namelist())


def test_added_clip_keeps_distinct_video_number_in_zip(cfg):
    from types import SimpleNamespace
    from auto_short.review.logic import with_added
    from auto_short.web.episode_thumbs import EpisodeThumbs
    ident = IDS[0] + ".kt"
    added = dict(clip_id="m01", candidate_id="manual", start=0.0, end=240.0, source="transcript",
                 title="Học cách sống an vui", ai_title=None, alternatives=[])
    review = with_added(empty_review(ident), ["k01", "k02"], added)
    atomic_write_json(cfg.workspace.dir / ident / "review.json", review)
    assert kt.build_episode(cfg, ident, pid=PID)["built"] == 6
    assert kt.read(cfg, ident)["clip_numbers"] == dict(k01=1, k02=2, m01=3)
    service = EpisodeThumbs(SimpleNamespace(config=cfg, runner=SimpleNamespace(latest=lambda _: None)))
    data, _ = service.archive(PID)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert len(archive.namelist()) == 6
        assert {f"khai-thi/T101_KT{n:02d}_{shape}.jpg" for n in (1, 2, 3) for shape in ("vertical", "landscape")} == set(archive.namelist())
