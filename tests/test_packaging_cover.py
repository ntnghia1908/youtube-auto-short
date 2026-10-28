"""COV1 AC1–5: synthetic local covers, actual ffmpeg pixels and PKG2 fallback."""
import json
import subprocess

import pytest

from auto_short.hashing import sha256_file
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
    line = cover.number_line(str(number), box)
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
        monkeypatch.setattr(cover, "COVER_LAYOUT_VERSION", cover.COVER_LAYOUT_VERSION + 1)
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
