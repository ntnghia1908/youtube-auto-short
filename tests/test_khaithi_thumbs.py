"""THUMB1 AC4–5: title precedence, measured wrapping, cache and shared playlist output."""
import io
import subprocess
import zipfile

import pytest

from auto_short.hashing import sha256_file
from auto_short.packaging import PackageError, cover, episode, khaithi_thumbs as kt, thumbnail
from auto_short.render.stage import _run, probe_media
from auto_short.render.text import Font, TextError
from auto_short.review.logic import empty_review
from auto_short.workspace import atomic_write_json
from test_packaging_cover import source_image
from test_packaging_episode import IDS, PID, seed_episodes

TITLE = "Giữ tâm thanh tịnh trong cuộc sống để được an lạc mỗi ngày"


def portrait_manifest(cfg, *, count=2, color="red@0.8", episode_index=None):
    folder = cfg.packaging.asset_dir / "portraits"
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for n in range(count):
        path = folder / f"{n:02d}-{n:012x}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c={color}:s={64 + n * 2}x100,format=rgba", "-frames:v", "1", "-threads", "1", str(path)],
                       check=True, timeout=30)
        entries.append(dict(file=path.name, sha256=sha256_file(path)))
    doc = dict(schema_version=1, portraits=entries)
    if episode_index is not None:
        doc["episode"] = entries[episode_index]["file"]
    atomic_write_json(folder / "portraits.json", doc)
    return folder, entries


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
    monkeypatch.setattr(kt, "LAYOUT_VERSION", 2)
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


@pytest.mark.parametrize("damage", ["missing", "sha", "name", "symlink", "manifest_link", "directory_link", "schema", "corrupt", "empty"])
def test_portraits_reject_bad_records_without_losing_good_ones(cfg, tmp_path, damage):
    folder, entries = portrait_manifest(cfg)
    manifest = folder / "portraits.json"
    expected = entries[1:]
    if damage == "missing":
        (folder / entries[0]["file"]).unlink()
    elif damage == "sha":
        entries[0]["sha256"] = "f" * 64
    elif damage == "name":
        entries[0]["file"] = "../outside.png"
    elif damage == "symlink":
        path = folder / entries[0]["file"]
        target = tmp_path / "portrait.png"
        path.replace(target)
        path.symlink_to(target)
    elif damage == "corrupt":
        path = folder / entries[0]["file"]
        path.write_bytes(b"\x89PNG\r\n\x1a\ninvalid")
        entries[0]["sha256"] = sha256_file(path)
    if damage in ("sha", "name", "corrupt"):
        atomic_write_json(manifest, dict(schema_version=1, portraits=entries))
    if damage in ("manifest_link", "schema", "directory_link", "empty"):
        expected = []
        if damage == "manifest_link":
            target = tmp_path / "manifest.json"
            manifest.replace(target)
            manifest.symlink_to(target)
        elif damage == "directory_link":
            target = tmp_path / "linked-portraits"
            folder.rename(target)
            folder.symlink_to(target, target_is_directory=True)
        else:
            atomic_write_json(manifest, dict(schema_version=2 if damage == "schema" else 1, portraits=[]))
    assert kt.portraits(cfg) == [(folder / e["file"], e["sha256"]) for e in expected]


def test_portrait_rotation_twenty_episodes_per_portrait(cfg):
    assert kt.portraits(cfg) == []
    folder, entries = portrait_manifest(cfg, count=3)
    items = kt.portraits(cfg)
    assert items == [(folder / e["file"], e["sha256"]) for e in entries]
    expected = {1: 0, 20: 0, 21: 1, 40: 1, 41: 2, 60: 2, 61: 0, 101: 2, 374: 0}
    for number, index in expected.items():
        assert kt.choose_portrait(items, str(number)) == items[index]
    assert kt.choose_portrait([], 101) == (None, None)


def test_portraits_cached_until_folder_changes(cfg, monkeypatch):
    folder, entries = portrait_manifest(cfg, count=2)
    assert len(kt.portraits(cfg)) == 2
    calls = []
    real = kt._read_portraits
    monkeypatch.setattr(kt, "_read_portraits", lambda f: calls.append(f) or real(f))
    assert len(kt.portraits(cfg)) == 2 and calls == []  # per-episode listing must not re-decode PNGs
    path = folder / entries[0]["file"]
    data = path.read_bytes()
    path.unlink()
    path.write_bytes(data[:-16])  # new inode / size: the damaged portrait is dropped
    assert kt.portraits(cfg) == [(folder / entries[1]["file"], entries[1]["sha256"])] and len(calls) == 1


@pytest.mark.parametrize("damage", [None, "missing_key", "not_listed", "sha", "corrupt", "symlink", "bad_key", "missing_manifest"])
def test_episode_portrait_uses_only_verified_manifest_member(cfg, tmp_path, monkeypatch, damage):
    folder, entries = portrait_manifest(cfg, episode_index=1)
    doc = dict(schema_version=1, portraits=entries, episode=entries[1]["file"])
    selected = folder / entries[1]["file"]
    if damage == "missing_key":
        doc.pop("episode")
    elif damage == "not_listed":
        doc["portraits"] = entries[:1]  # selected PNG exists but is not an authorized member
    elif damage == "sha":
        entries[1]["sha256"] = "f" * 64
    elif damage == "corrupt":
        selected.write_bytes(b"broken PNG")
    elif damage == "symlink":
        target = tmp_path / "external.png"
        selected.rename(target)
        selected.symlink_to(target)
    elif damage == "bad_key":
        doc["episode"] = [entries[1]["file"]]
    atomic_write_json(folder / "portraits.json", doc)
    if damage == "missing_manifest":
        (folder / "portraits.json").unlink()
    expected = (selected, entries[1]["sha256"]) if damage is None else (None, None)
    items = kt.portraits(cfg)  # primes the shared cache, including the episode selection
    monkeypatch.setattr(kt, "_read_portraits", lambda _: pytest.fail("catalog read twice"))
    assert kt.episode_portrait(cfg) == expected
    if damage is None:
        assert kt.episode_portrait(cfg) == items[1]


@pytest.mark.parametrize("box", [[50, 80, 900, 730], [40, 50, 740, 570]])
def test_four_text_groups_fit_measured_ink_and_shadow(box):
    fields = dict(speaker="HT. Tịnh Không", series="Kinh Vô Lượng Thọ", episode="374")
    lines, styles = kt.layout(TITLE, fields, box)
    assert lines[0].text == "TRÍCH ĐOẠN KHAI THỊ" and lines[-2].text == "HT. TỊNH KHÔNG"
    assert lines[-1].text == "Kinh Vô Lượng Thọ · Tập 374"
    assert len(lines[1:-2]) == 3
    assert " ".join(l.text for l in lines[1:-2]) == TITLE
    assert not styles[0]["shadow"] and styles[1]["shadow"]
    heights = []
    for line, style in zip(lines, styles):
        font = Font(thumbnail.EPISODE_FONTS[line.font])
        top, bottom = font.ink_bounds(line.text, line.size)
        heights.append(bottom - top)
        assert font.width(line.text, line.size) <= box[2] * cover.FIT_WIDTH
        assert box[1] <= line.y + top - 2
        assert line.y + bottom + (4 if style["shadow"] else 2) <= box[1] + box[3]
    assert heights[-2] >= max(heights[1:-2]) * .55
    assert max(l.size for l in lines[1:-2]) > lines[-2].size
    with pytest.raises(TextError):
        kt.layout(TITLE, fields, [0, 0, 40, 30])


def test_portrait_cache_missing_reason_and_library_changes(cfg):
    ident = IDS[0] + ".kt"
    kt.build_episode(cfg, ident, pid=PID)
    assert kt.read(cfg, ident)["portrait_reason"] == "chưa có chân dung"
    folder, entries = portrait_manifest(cfg)
    assert not kt.valid_files(cfg, ident)
    assert kt.build_episode(cfg, ident, pid=PID)["built"] == 4
    before = kt.read(cfg, ident)
    assert before["portrait_reason"] is None and kt.valid_files(cfg, ident)
    assert kt.build_episode(cfg, ident, pid=PID)["reused"] == 4
    assert kt.read(cfg, ident) == before
    portrait_manifest(cfg, color="blue@0.8")
    assert not kt.valid_files(cfg, ident)
    assert kt.build_episode(cfg, ident, pid=PID)["built"] == 4
    portrait_manifest(cfg, count=3, color="blue@0.8")
    assert not kt.valid_files(cfg, ident)
    assert kt.build_episode(cfg, ident, pid=PID)["built"] == 4
    (folder / "portraits.json").unlink()
    assert not kt.valid_files(cfg, ident)


def test_kt_cache_tracks_speaker_series_and_sans(cfg, monkeypatch):
    entry = cover.current(cfg, PID)["kt_vertical"]
    args = (TITLE, "1", entry, "vertical")
    key = kt.cache_key(*args, speaker="HT. Tịnh Không", series="Kinh")
    assert key != kt.cache_key(*args, speaker="Thầy", series="Kinh")
    assert key != kt.cache_key(*args, speaker="HT. Tịnh Không", series="Kinh khác")
    monkeypatch.setitem(thumbnail.EPISODE_FONTS, "sans", thumbnail.EPISODE_FONTS["old"])
    assert key != kt.cache_key(*args, speaker="HT. Tịnh Không", series="Kinh")


@pytest.mark.parametrize("shape,box", [("landscape", [40, 50, 740, 570]), ("vertical", [60, 120, 960, 740])])
def test_portrait_pixels_overlay_before_text(cfg, tmp_path, shape, box):
    folder, entries = portrait_manifest(cfg, count=1)
    portrait = folder / entries[0]["file"]
    image = source_image(tmp_path, thumbnail.EPISODE_SIZES[shape])
    fields = dict(speaker="HT. Tịnh Không", series="Kinh Vô Lượng Thọ", episode="1")
    outputs = []
    for index, cutout in enumerate((None, portrait)):
        work = tmp_path / f"pixel-{index}"
        work.mkdir()
        output = kt.draw(work, TITLE, fields, dict(box=box), shape, image, "test.jpg", portrait=cutout)
        outputs.append(output)
    graph = (tmp_path / "pixel-1" / "graph.txt").read_text()
    assert graph.index("overlay=") < graph.index("drawtext=")
    assert "format=rgba" in graph and "shadowx=2" in graph and "cover-sans.ttf" in graph
    def pixels(path):
        return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-threads", "1",
                               "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
                              capture_output=True, check=True, timeout=30).stdout
    plain, composed = map(pixels, outputs)
    w, h = thumbnail.EPISODE_SIZES[shape]
    pw, ph, px, py = cover.portrait_box(shape, box, (64, 100))
    offset = ((py + ph // 2) * w + px + pw // 2) * 3
    assert composed[offset] > plain[offset] + 40  # the synthetic red portrait is visible
    # Far from the overlay, the cover and all text remain the same (allow JPEG rounding).
    offset = (10 * w + 10) * 3
    assert all(abs(a - b) <= 3 for a, b in zip(plain[offset:offset + 3], composed[offset:offset + 3]))


def test_build_rotation_uses_clip_numbers_even_when_first_clip_hidden(cfg, monkeypatch):
    ident = IDS[0] + ".kt"
    folder, entries = portrait_manifest(cfg, count=3)
    review = empty_review(ident)
    review["rejected"] = [dict(clip_id="k01", candidate_id="c01")]
    atomic_write_json(cfg.workspace.dir / ident / "review.json", review)
    rendered = []
    draw = kt.draw
    def capture(*args, **kwargs):
        rendered.append(kwargs["portrait"])
        return draw(*args, **kwargs)
    monkeypatch.setattr(kt, "draw", capture)
    assert kt.build_episode(cfg, ident, pid=PID)["built"] == 2
    number = int(episode.header(cfg, IDS[0])["episode"])
    expected = folder / entries[(number - 1 + 2 - 1) % len(entries)]["file"]
    assert rendered == [expected, expected]
    assert kt.read(cfg, ident)["clip_numbers"] == {"k01": 1, "k02": 2}
    assert set(kt.valid_files(cfg, ident)) == {"k02"}


def test_playlist_series_name_wins_over_metadata_header(cfg):
    """Real VLT: titles.json header says "[HD] Kinh Vô Lượng Thọ"; the playlist's Tên bộ kinh is what viewers see."""
    folder = cfg.workspace.dir / IDS[0]
    header = dict(series="[HD] " + episode.playlist(cfg, PID)["series"], episode="101", speaker="HT. Tịnh Không")
    atomic_write_json(folder / "titles.json", dict(header=dict(fields=header)))
    ident = IDS[0] + ".kt"
    kt.build_episode(cfg, ident, pid=PID)
    assert kt.read(cfg, ident)["header"]["series"] == episode.playlist(cfg, PID)["series"]
    assert kt.valid_files(cfg, ident, pid=PID)
    path = cfg.workspace.dir / "_playlists" / f"{PID}.json"
    doc = episode.playlist(cfg, PID)
    doc.pop("series")
    atomic_write_json(path, doc)
    assert kt.display_fields(cfg, PID, header)["series"] == header["series"]  # no Tên bộ kinh: header as before
