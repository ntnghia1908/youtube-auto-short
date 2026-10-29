"""COV1 AC1–5: synthetic local covers, actual ffmpeg pixels and PKG2 fallback."""
import json
import subprocess

import pytest

from auto_short.hashing import config_hash, sha256_file
from auto_short.packaging import PackageError, cover, episode, thumbnail
from auto_short.packaging.__main__ import main
from auto_short.render import full
from auto_short.render.stage import _run, probe_media
from auto_short.render.text import Font, TextError
from auto_short.workspace import atomic_write_json

from test_packaging_episode import IDS, PID, seed_episodes, episode_media


@pytest.fixture
def cfg(tmp_path):
    return seed_episodes(tmp_path)


def source_image(tmp_path, size=(1080, 1920), color="0x145b58"):
    path = tmp_path / f"cover {size[0]}x{size[1]} {color}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c={color}:s={size[0]}x{size[1]},drawbox=x=40:y=40:w=160:h=80:color=0xe8bf62:t=5",
                    "-frames:v", "1", "-threads", "1", str(path)], check=True, timeout=30)
    return path


def pre_d9_key(fields, entry, shape):
    return config_hash(dict(cover_sha256=entry["sha256"], box=entry["box"], episode=fields["episode"],
                            layout_version=3, font_sha256=sha256_file(thumbnail.EPISODE_FONTS[cover.FONT_NAME]), shape=shape))


def gray(path):
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-threads", "1",
                           "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"],
                          capture_output=True, check=True, timeout=30).stdout


@pytest.mark.parametrize("shape,size,box,expected", [
    ("vertical", (1080, 1920), [200, 1200, 600, 200], [200, 1200, 600, 200]),
    ("vertical", (540, 960), [100, 600, 300, 100], [200, 1200, 600, 200]),
    ("vertical", (1200, 1200), [400, 700, 400, 150], [220, 1120, 640, 240]),
    ("landscape", (1920, 1080), [300, 600, 900, 180], [200, 400, 600, 120]),
])
def test_install_normalizes_box_sha_and_prompt(cfg, tmp_path, shape, size, box, expected):
    entry = cover.install(cfg, PID, shape, source_image(tmp_path, size), box, prompt="Hoa sen vàng 🌼")
    path = cover.directory(cfg, PID) / entry["file"]
    stream = probe_media(path, _run)["video"]
    assert (stream["width"], stream["height"]) == thumbnail.EPISODE_SIZES[shape]
    assert entry == dict(file=f"{shape}.png", sha256=sha256_file(path), box=expected, prompt="Hoa sen vàng 🌼")
    assert cover.read(cfg, PID) == dict(schema_version=1, shapes={shape: entry})
    assert cover.current(cfg, PID) == {shape: entry}


@pytest.mark.parametrize("damage", ["outside", "negative", "empty", "float", "cropped", "corrupt", "decode", "write"])
def test_invalid_install_preserves_previous_cover(cfg, tmp_path, monkeypatch, damage):
    image = source_image(tmp_path)
    cover.install(cfg, PID, "vertical", image, [200, 1200, 600, 200])
    folder = cover.directory(cfg, PID)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    box = dict(outside=[1000, 1200, 600, 200], negative=[-1, 0, 600, 200],
               empty=[0, 0, 0, 100], float=[0, 0, 2.5, 100]).get(damage, [200, 1200, 600, 200])
    runner = None
    if damage == "cropped":
        image, box = source_image(tmp_path, (1200, 1200)), [0, 0, 400, 100]
    elif damage == "corrupt":
        image = tmp_path / "bad.png"
        image.write_bytes(b"not an image")
    elif damage == "decode":
        def runner(cmd):
            return _run(cmd) if cmd[0] == "ffprobe" else subprocess.CompletedProcess(cmd, 1, "", "decode failed")
    elif damage == "write":
        image = source_image(tmp_path, color="0x602255")
        def fail(*_):
            raise OSError("metadata failed")
        monkeypatch.setattr(cover, "atomic_write_json", fail)
    with pytest.raises((PackageError, OSError), match="box|ảnh|metadata"):
        cover.install(cfg, PID, "vertical", image, box, run=runner)
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}


def test_cli_install_show_remove_and_bad_box(cfg, tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text(f'[workspace]\ndir="{cfg.workspace.dir}"\n[render]\noutput_dir="{cfg.render.output_dir}"\n')
    image = source_image(tmp_path)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Hoa sen vàng", encoding="utf-8")
    base = ["--config", str(config), "cover"]
    install = [*base, "install", "--playlist", PID, "--shape", "vertical", "--image", str(image)]
    assert main([*install, "--box", "bad"]) == 1
    assert "bốn số nguyên" in capsys.readouterr().err
    assert not cover.directory(cfg, PID).exists()
    assert main([*install, "--box", "200,1200,600,200", "--prompt-file", str(prompt)]) == 0
    entry = json.loads(capsys.readouterr().out)
    assert entry["prompt"] == "Hoa sen vàng"
    assert main([*base, "show", "--playlist", PID]) == 0
    assert json.loads(capsys.readouterr().out)["shapes"] == {"vertical": entry}
    assert main([*base, "remove", "--playlist", PID, "--shape", "vertical"]) == 0
    assert json.loads(capsys.readouterr().out)["shapes"] == {}
    assert not (cover.directory(cfg, PID) / "vertical.png").exists()


@pytest.mark.parametrize("shape", thumbnail.EPISODE_SIZES)
def test_build_preview_and_other_shape_remains_byte_identical(cfg, tmp_path, shape):
    fields = dict(episode.header(cfg, IDS[0]), episode="51")
    atomic_write_json(cfg.workspace.dir / IDS[0] / "titles.json", dict(header=dict(fields=fields)))
    episode.build_episode(cfg, IDS[0], pid=PID)
    old = episode.read(cfg, IDS[0])
    folder = episode.directory(cfg, IDS[0])
    other = "landscape" if shape == "vertical" else "vertical"
    other_bytes = (folder / old["files"][other]["file"]).read_bytes()
    size = thumbnail.EPISODE_SIZES[shape]
    box = [200, size[1] - 400, 600, 200]
    entry = cover.install(cfg, PID, shape, source_image(tmp_path, size), box)
    assert set(episode.valid_files(cfg, IDS[0])) == {other}
    # A cover takes precedence over the now-unusable PKG2 portrait for its own shape.
    settings = episode.read_settings(cfg, PID)
    if shape == "vertical":
        settings["vertical"] = dict(style="A", asset_id="a" * 64, focus_x=0.5)
    episode.build_episode(cfg, IDS[0], pid=PID, settings=settings)
    doc = episode.read(cfg, IDS[0])
    assert doc["asset_ids"][shape] == episode.recorded_asset(doc, shape) == "cover:" + entry["sha256"]
    assert doc["files"][other] == old["files"][other]
    assert (folder / doc["files"][other]["file"]).read_bytes() == other_bytes
    assert set(episode.valid_files(cfg, IDS[0], settings=settings)) == set(thumbnail.EPISODE_SIZES)
    preview = episode.preview(cfg, PID)
    assert preview[shape] == (folder / doc["files"][shape]["file"]).read_bytes()
    assert preview[other] == other_bytes
    assert episode.build_episode(cfg, IDS[0], pid=PID, run=lambda _: pytest.fail("cache ran ffmpeg")) == "reused"


@pytest.mark.parametrize("shape", thumbnail.EPISODE_SIZES)
@pytest.mark.parametrize("number", [1, 51, 102])
def test_number_fits_and_pixels_change_only_inside_box(cfg, tmp_path, shape, number):
    size = thumbnail.EPISODE_SIZES[shape]
    box = [200, size[1] - 400, 600, 200]
    entry = cover.install(cfg, PID, shape, source_image(tmp_path, size), box)
    image = cover.directory(cfg, PID) / entry["file"]
    work = tmp_path / "render with spaces"
    work.mkdir()
    output = cover.build_episode(work, dict(episode=str(number)), shape, image, "test.jpg", entry=entry)
    assert output.read_bytes().startswith(b"\xff\xd8") and output.stat().st_size <= thumbnail.MAX_BYTES
    stream = probe_media(output, _run)["video"]
    assert (stream["width"], stream["height"]) == size
    assert (work / "line0.txt").read_text() == f"TẬP {number}"
    line = cover.number_line(str(number), box, shape)
    font = Font(thumbnail.EPISODE_FONTS[line.font])
    top, bottom = font.ink_bounds(line.text, line.size)
    assert font.width(line.text, line.size) <= box[2] * cover.FIT_WIDTH
    assert bottom - top + 2 <= box[3] * cover.FIT_HEIGHT
    assert line.y + (top + bottom + 2) / 2 == pytest.approx(box[1] + box[3] / 2, abs=1)
    before, after = gray(image), gray(output)
    x, y, w, h = box
    inside_changes, outside_error, outside_count, outside_peak = [], 0, 0, 0
    for row in range(size[1]):
        a, b = before[row*size[0]:(row+1)*size[0]], after[row*size[0]:(row+1)*size[0]]
        if y <= row < y + h:
            inside_changes.extend((col, row) for col in range(x, x + w) if abs(a[col] - b[col]) > 24)
            outside = zip(a[:x] + a[x+w:], b[:x] + b[x+w:])
        else:
            outside = zip(a, b)
        for left, right in outside:
            error = abs(left - right)
            outside_error += error
            outside_peak = max(outside_peak, error)
            outside_count += 1
    assert outside_error / outside_count < 2  # JPEG quantization; original art survives outside the number box
    assert outside_peak < 24  # no painted text can hide in the average of the untouched image
    assert len(inside_changes) > 500
    xs, ys = zip(*inside_changes)
    assert max(xs) - min(xs) <= w * cover.FIT_WIDTH and max(ys) - min(ys) <= h * cover.FIT_HEIGHT + 4
    assert (min(xs) + max(xs)) / 2 == pytest.approx(x + w / 2, abs=12)


@pytest.mark.parametrize("change", ["image", "box", "number", "layout", "font"])
def test_cache_invalidates_cover_only(cfg, tmp_path, monkeypatch, change):
    image = source_image(tmp_path)
    cover.install(cfg, PID, "vertical", image, [200, 1200, 600, 200])
    episode.build_episode(cfg, IDS[0], pid=PID, run=episode_media)
    old = episode.read(cfg, IDS[0])
    if change in ("image", "box"):
        image = source_image(tmp_path, color="0x602255") if change == "image" else image
        cover.install(cfg, PID, "vertical", image, [200, 1220 if change == "box" else 1200, 600, 200])
    elif change == "number":
        fields = dict(episode.header(cfg, IDS[0]), episode="102")
        atomic_write_json(cfg.workspace.dir / IDS[0] / "titles.json", dict(header=dict(fields=fields)))
    elif change == "layout":
        monkeypatch.setattr(cover, "COVER_LAYOUT_VERSION_NO_PORTRAIT", cover.COVER_LAYOUT_VERSION_NO_PORTRAIT + 1)
    else:
        font = tmp_path / "font.ttf"
        font.write_bytes(thumbnail.EPISODE_FONTS[cover.FONT_NAME].read_bytes() + b"changed")
        monkeypatch.setitem(thumbnail.EPISODE_FONTS, cover.FONT_NAME, font)
    current = episode.valid_files(cfg, IDS[0])
    assert "vertical" not in current
    if change in ("image", "box", "layout"):
        assert current == {"landscape": old["files"]["landscape"]}
    episode.build_episode(cfg, IDS[0], pid=PID, run=episode_media)
    rebuilt = episode.read(cfg, IDS[0])
    assert rebuilt["files"]["vertical"] != old["files"]["vertical"]
    assert set(episode.valid_files(cfg, IDS[0])) == set(thumbnail.EPISODE_SIZES)
    cover.remove(cfg, PID, "vertical")
    assert "vertical" not in episode.valid_files(cfg, IDS[0])
    episode.build_episode(cfg, IDS[0], pid=PID, run=episode_media)
    assert episode.recorded_asset(episode.read(cfg, IDS[0]), "vertical") is None


@pytest.mark.parametrize("damage", ["bytes", "missing", "symlink", "metadata", "jpeg"])
def test_tampered_cover_or_thumbnail_is_never_current(cfg, tmp_path, damage):
    cover.install(cfg, PID, "vertical", source_image(tmp_path), [200, 1200, 600, 200])
    episode.build_episode(cfg, IDS[0], pid=PID, run=episode_media)
    folder = cover.directory(cfg, PID)
    image = folder / "vertical.png"
    if damage == "bytes":
        image.write_bytes(b"corrupted")
    elif damage == "missing":
        image.unlink()
    elif damage == "symlink":
        other = tmp_path / "elsewhere.png"
        image.rename(other)
        image.symlink_to(other)
    elif damage == "metadata":
        doc = cover.read(cfg, PID)
        doc["shapes"]["vertical"]["file"] = "../elsewhere.png"
        atomic_write_json(folder / "cover.json", doc)
    else:
        doc = episode.read(cfg, IDS[0])
        (episode.directory(cfg, IDS[0]) / doc["files"]["vertical"]["file"]).write_bytes(b"corrupted")
    assert "vertical" not in episode.valid_files(cfg, IDS[0])


def test_vert2_intro_rebuilds_when_cover_changes(cfg, tmp_path, monkeypatch):
    image = source_image(tmp_path)
    cover.install(cfg, PID, "vertical", image, [200, 1200, 600, 200])
    monkeypatch.setattr(cover, "_run", episode_media)
    monkeypatch.setattr(thumbnail, "_run", episode_media)
    first = full.intro_image(cfg, IDS[0])
    assert first is not None
    digest = sha256_file(first)
    assert full.intro_image(cfg, IDS[0]) == first
    cover.install(cfg, PID, "vertical", image, [200, 1220, 600, 200], run=_run)
    assert "vertical" not in episode.valid_files(cfg, IDS[0])
    second = full.intro_image(cfg, IDS[0])
    assert second != first and sha256_file(second) != digest
    assert second.name == episode.valid_files(cfg, IDS[0])["vertical"]["file"]


def test_small_box_and_missing_glyph_fail_before_ffmpeg(tmp_path, monkeypatch):
    with pytest.raises(TextError):
        cover.number_line("102", [0, 0, 10, 10])
    monkeypatch.setattr(Font, "missing", lambda *_: ["Ậ"])
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(TextError, match="glyph"):
        cover.build_episode(work, dict(episode="51"), "vertical", None, "bad.jpg",
                            entry=dict(box=[200, 1200, 600, 200]), run=lambda _: pytest.fail("ffmpeg ran"))
    assert not list(work.iterdir())


def test_install_set_atomic_manifest_and_legacy_schema(cfg, tmp_path, monkeypatch):
    old = cover.install(cfg, PID, "vertical", source_image(tmp_path), [200, 1200, 600, 200])
    assert cover.read(cfg, PID)["schema_version"] == 1
    folder = cover.directory(cfg, PID)
    before = (folder / "cover.json").read_bytes()
    images = {}
    for shape, size in cover.SIZES.items():
        images[shape] = (source_image(tmp_path, size), [200, size[1] - 400, 600, 200])
    original = cover.atomic_write_json
    def fail_final(path, doc):
        if path == folder / "cover.json":
            raise OSError("final manifest failed")
        original(path, doc)
    monkeypatch.setattr(cover, "atomic_write_json", fail_final)
    with pytest.raises(OSError, match="final manifest"):
        cover.install_set(cfg, PID, images)
    assert (folder / "cover.json").read_bytes() == before
    assert cover.current(cfg, PID) == {"vertical": old}
    monkeypatch.setattr(cover, "atomic_write_json", original)
    entries = cover.install_set(cfg, PID, images)
    assert cover.current(cfg, PID) == entries and cover.read(cfg, PID)["schema_version"] == 2
    assert all(entry["sha256"] in entry["file"] for entry in entries.values())
    cover.remove(cfg, PID, "kt_vertical")
    assert "kt_vertical" not in cover.current(cfg, PID)


@pytest.mark.parametrize("shape,box,size,baseline", [
    ("vertical", [305, 1630, 470, 125], 87, 1723),
    ("landscape", [133, 484, 354, 79], 53, 542),
    ("vertical", [248, 1632, 584, 146], 103, 1741),
    ("landscape", [107, 503, 444, 76], 50, 558),
])
@pytest.mark.parametrize("number", [1, 51, 102])
def test_approved_vlt_dia_tang_number_line_unchanged(shape, box, size, baseline, number):
    # D-THUMB1-9 deliberately changes the cover cache/layout, retaining these text goldens.
    expected = thumbnail.EpisodeLine(f"TẬP {number}", cover.FONT_NAME, size,
                                     box[0], baseline, box[2], centered=True)
    assert cover.number_line(str(number), box, shape) == expected


@pytest.mark.parametrize("shape,source_size", [
    (shape, size) for shape in thumbnail.EPISODE_SIZES for size in ((64, 100), (1600, 300), (30, 1000))
])
def test_episode_portrait_geometry(shape, source_size):
    w, h = cover.SIZES[shape]
    pw, ph, px, py = cover.episode_portrait_box(shape, source_size)
    assert 0 <= px < px + pw <= w and 0 <= py < py + ph <= h
    assert pw / ph == pytest.approx(source_size[0] / source_size[1], rel=.03)
    if shape == "landscape":
        assert w - px - pw == pytest.approx(20, abs=1)
        assert py + ph == h and pw <= w * .5 and ph <= h * .92 + 1
    else:
        assert px + pw / 2 == pytest.approx(w / 2, abs=1)
        assert py + ph == pytest.approx(1010, abs=2)
        assert pw <= w * .84 + 1 and ph <= h * .46 + 1
    if source_size == (64, 100):
        assert ph == pytest.approx(660 if shape == "landscape" else 880, abs=3)


@pytest.mark.parametrize("shape,box", [
    ("vertical", [305, 1630, 470, 125]),  # VLT
    ("landscape", [133, 484, 354, 79]),
    ("vertical", [248, 1632, 584, 146]),  # Địa Tạng
    ("landscape", [107, 503, 444, 76]),
])
def test_approved_covers_episode_portrait_pixels_and_v3_cache_migration(cfg, tmp_path, monkeypatch, shape, box):
    from test_khaithi_thumbs import portrait_manifest
    # Seed the exact pre-D-THUMB1-9 cache format: no portrait SHA field and version 3.
    entry = cover.install(cfg, PID, shape, source_image(tmp_path, cover.SIZES[shape], color="0x101020"), box)
    settings = episode.read_settings(cfg, PID)
    fields = episode.header(cfg, IDS[0])
    old_key = pre_d9_key(fields, entry, shape)
    real_key = episode.cache_key
    with monkeypatch.context() as patch:
        patch.setattr(episode, "cache_key", lambda f, s, sh, **kw: old_key if sh == shape else real_key(f, s, sh, **kw))
        episode.build_episode(cfg, IDS[0], pid=PID)
    folder = episode.directory(cfg, IDS[0])
    old = episode.read(cfg, IDS[0])
    plain = gray(folder / old["files"][shape]["file"])
    # Without an enabled portrait, pre-D9 artifacts are valid again.
    assert shape in episode.valid_files(cfg, IDS[0])
    assert episode.cache_key(fields, settings, shape, cover_entry=entry) == old_key
    _, entries = portrait_manifest(cfg, count=1, episode_index=0, episode_playlists=[PID])
    graphs = []
    def runner(cmd):
        if "-filter_complex_script" in cmd:
            from pathlib import Path
            graphs.append(Path(cmd[cmd.index("-filter_complex_script") + 1]).read_text())
        return _run(cmd)
    assert episode.build_episode(cfg, IDS[0], pid=PID, run=runner) == "built"
    current = episode.read(cfg, IDS[0])
    composed = gray(folder / current["files"][shape]["file"])
    graph = graphs[0]
    assert graph.index("overlay=") < graph.index("drawtext=")
    assert ("alpha(X,Y)*min(1,(H-1-Y)/(H*0.18))" in graph) == (shape == "vertical")
    w, _ = cover.SIZES[shape]
    pw, ph, px, py = cover.episode_portrait_box(shape, (64, 100))
    x = px + pw // 2
    middle, fade, bottom = [(py + round((ph - 1) * fraction)) * w + x for fraction in (.5, .91, 1)]
    assert abs(composed[middle] - plain[middle]) > 20
    if shape == "vertical":
        assert 3 < abs(composed[fade] - plain[fade]) < abs(composed[middle] - plain[middle]) - 5
        assert abs(composed[bottom] - plain[bottom]) < 5
    # The golden number remains in its box, with identical pixels despite the portrait.
    bx, by, bw, bh = box
    assert max(abs(plain[y*w+x] - composed[y*w+x]) for y in range(by, by+bh) for x in range(bx, bx+bw)) < 5
    assert current["files"][shape]["key"] != old_key
    assert current["files"][shape]["key"] == episode.cache_key(fields, settings, shape, cover_entry=entry,
                                                                              portrait_sha256=entries[0]["sha256"])
    assert episode.preview(cfg, PID)[shape] == (folder / current["files"][shape]["file"]).read_bytes()
    assert episode.build_episode(cfg, IDS[0], pid=PID, run=lambda _: pytest.fail("cache ran ffmpeg")) == "reused"


@pytest.mark.parametrize("change", ["selection", "bytes", "missing_key"])
def test_episode_portrait_cache_changes_only_with_selected_sha(cfg, tmp_path, monkeypatch, change):
    from test_khaithi_thumbs import portrait_manifest
    from auto_short.packaging import khaithi_thumbs as kt
    for shape in thumbnail.EPISODE_SIZES:
        cover.install(cfg, PID, shape, source_image(tmp_path, cover.SIZES[shape]),
                      [200, cover.SIZES[shape][1] - 300, 600, 150])
    folder, entries = portrait_manifest(cfg, episode_index=1, episode_playlists=[PID])
    assert episode.build_episode(cfg, IDS[0], pid=PID, run=episode_media) == "built"
    before = episode.read(cfg, IDS[0])
    with monkeypatch.context() as patch:
        patch.setattr(kt, "_read_portraits", lambda _: pytest.fail("cached PNGs read again"))
        assert len(episode.valid_files(cfg, IDS[0])) == 2
        assert episode.build_episode(cfg, IDS[0], pid=PID, run=lambda _: pytest.fail("cache ran ffmpeg")) == "reused"
    # An unrelated manifest change must preserve the episode cache.
    atomic_write_json(folder / "portraits.json", dict(schema_version=1, portraits=entries, episode=entries[1]["file"], episode_playlists=[PID], note="updated"))
    assert episode.build_episode(cfg, IDS[0], pid=PID, run=lambda _: pytest.fail("metadata invalidated cache")) == "reused"
    if change == "bytes":
        portrait_manifest(cfg, color="blue@0.8", episode_index=1, episode_playlists=[PID])
    else:
        doc = dict(schema_version=1, portraits=entries, episode_playlists=[PID])
        if change == "selection":
            doc["episode"] = entries[0]["file"]
        atomic_write_json(folder / "portraits.json", doc)
    assert not episode.valid_files(cfg, IDS[0])
    assert episode.build_episode(cfg, IDS[0], pid=PID, run=episode_media) == "built"
    after = episode.read(cfg, IDS[0])
    assert all(after["files"][s]["key"] != before["files"][s]["key"] for s in thumbnail.EPISODE_SIZES)
    assert len(episode.valid_files(cfg, IDS[0])) == 2


@pytest.mark.parametrize("shape,box,ratio", [
    ("vertical", [40, 900, 1000, 900], .08),
    ("landscape", [40, 200, 1200, 450], .12),
])
def test_number_height_capped_in_large_box(shape, box, ratio):
    line = cover.number_line("1", box, shape)
    font = Font(thumbnail.EPISODE_FONTS[line.font])
    top, bottom = font.ink_bounds(line.text, line.size)
    assert bottom - top + 2 <= cover.SIZES[shape][1] * ratio
    assert line.y + (top + bottom + 2) / 2 == pytest.approx(box[1] + box[3] / 2, abs=1)
    assert bottom - top + 2 < box[3] * cover.FIT_HEIGHT


@pytest.mark.parametrize("shape,box,size", [
    ("landscape", [450, 50, 740, 570], (769, 879)),
    ("landscape", [450, 50, 740, 570], (1600, 300)),
    ("vertical", [60, 120, 960, 740], (769, 879)),
    ("vertical", [60, 120, 960, 740], (1600, 300)),
])
def test_kt_portrait_geometry_bottom_and_clear_text_box(shape, box, size):
    w, h = cover.SIZES[shape]
    pw, ph, px, py = cover.portrait_box(shape, box, size)
    assert py + ph == h and pw > 0 and ph > 0
    assert pw / ph == pytest.approx(size[0] / size[1], abs=.02)
    if shape == "landscape":
        assert px == 0
        assert pw - box[0] <= w * .04 + 1
        assert ph <= h * .92 + 1
    else:
        assert py >= box[1] + box[3]
        assert px + pw / 2 == pytest.approx(w * .42, abs=1)
        assert ph <= h * .48 + 1


def test_install_kt_schema_one_preserves_episode_entries_and_atomic_failure(cfg, tmp_path, monkeypatch):
    image = source_image(tmp_path)
    cover.install(cfg, PID, "vertical", image, [200, 1200, 600, 200])
    original = cover.current(cfg, PID)
    assert cover.read(cfg, PID)["schema_version"] == 1
    images = {"kt_vertical": (image, [60, 120, 960, 740]),
              "kt_landscape": (source_image(tmp_path, (1280, 720)), [40, 50, 740, 570])}
    entries = cover.install_kt(cfg, PID, images)
    assert entries["vertical"] == original["vertical"]
    assert cover.read(cfg, PID)["schema_version"] == 2
    folder = cover.directory(cfg, PID)
    before = (folder / "cover.json").read_bytes()
    actual = cover.atomic_write_json
    def fail(path, doc):
        if path == folder / "cover.json":
            raise OSError("manifest failed")
        return actual(path, doc)
    monkeypatch.setattr(cover, "atomic_write_json", fail)
    with pytest.raises(OSError, match="manifest failed"):
        cover.install_kt(cfg, PID, images)
    assert (folder / "cover.json").read_bytes() == before
    assert cover.current(cfg, PID) == entries
    with pytest.raises(PackageError, match="hai khổ"):
        cover.install_kt(cfg, PID, {"kt_vertical": images["kt_vertical"]})


@pytest.mark.parametrize("enabled", [False, True])
def test_episode_playlist_gate_preserves_pre_d9_keys_and_files(cfg, tmp_path, monkeypatch, enabled):
    from test_khaithi_thumbs import portrait_manifest
    for shape, box in (("vertical", [248, 1632, 584, 146]), ("landscape", [107, 503, 444, 76])):
        cover.install(cfg, PID, shape, source_image(tmp_path, cover.SIZES[shape]), box)
    covers = cover.current(cfg, PID)
    fields = episode.header(cfg, IDS[0])
    settings = episode.read_settings(cfg, PID)
    keys = {shape: pre_d9_key(fields, entry, shape) for shape, entry in covers.items()}
    # Write a thumbs.json fixture with the independent pre-D9 formula, as on disk before migration.
    with monkeypatch.context() as patch:
        patch.setattr(episode, "cache_key", lambda f, s, shape, **kw: keys[shape])
        episode.build_episode(cfg, IDS[0], pid=PID, run=episode_media)
    old = episode.read(cfg, IDS[0])
    _, entries = portrait_manifest(cfg, count=1, episode_index=0, episode_playlists=[PID] if enabled else ["other"])
    if enabled:
        assert not episode.valid_files(cfg, IDS[0])
        for shape, entry in covers.items():
            expected = config_hash(dict(cover_sha256=entry["sha256"], box=entry["box"], episode=fields["episode"],
                                        layout_version=4, portrait_sha256=entries[0]["sha256"],
                                        font_sha256=sha256_file(thumbnail.EPISODE_FONTS[cover.FONT_NAME]), shape=shape))
            assert episode.cache_key(fields, settings, shape, cover_entry=entry,
                                     portrait_sha256=entries[0]["sha256"]) == expected != keys[shape]
    else:
        assert set(episode.valid_files(cfg, IDS[0])) == {"vertical", "landscape"}
        for shape, entry in covers.items():
            assert episode.cache_key(fields, settings, shape, cover_entry=entry) == keys[shape]
        assert episode.build_episode(cfg, IDS[0], pid=PID, run=lambda _: pytest.fail("old cache rebuilt")) == "reused"
        assert episode.read(cfg, IDS[0]) == old
