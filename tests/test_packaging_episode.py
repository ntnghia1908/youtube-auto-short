"""PKG2 AC1–4/6: real JPEG compositions, otherwise offline injected runners."""
import json
import subprocess
import shutil
import struct
import zlib
import unicodedata
from pathlib import Path

import pytest

from auto_short.config import Config, PackagingConfig, RenderConfig, WorkspaceConfig
from auto_short.hashing import sha256_file
from auto_short.packaging import PackageError, assets, episode, thumbnail
from auto_short.render.stage import RenderError, _run, probe_media
from auto_short.render.text import Font, TextError
from auto_short.workspace import atomic_write_json

from test_packaging_thumbnail import fake_media

PID = "PLepisodes1"
IDS = ("lecture0001", "lecture0002")
SERIES = "Kinh Địa Tạng Bồ Tát Bổn Nguyện"


def seed_episodes(tmp_path):
    """Shared offline source for core and web tests; no source video decoding is needed."""
    cfg = Config(workspace=WorkspaceConfig(tmp_path / "work"), packaging=PackagingConfig(tmp_path / "assets"),
                 render=RenderConfig(output_dir=tmp_path / "output"))
    entries = []
    for number, ident in enumerate(IDS, 101):
        folder = cfg.workspace.dir / ident
        folder.mkdir(parents=True)
        (folder / "source.mp4").write_bytes(b"source")
        atomic_write_json(folder / "manifest.json", dict(source=dict(kind="youtube", path="source.mp4", sha256="a" * 64)))
        atomic_write_json(folder / "metadata.json", dict(title="Bài giảng", height=1080))
        fields = dict(series=SERIES, episode=str(number), speaker="HT. Tịnh Không")
        atomic_write_json(folder / "titles.json", dict(header=dict(fields=fields)))
        entries.append(dict(video_id=ident, episode=str(number), index=number))
    atomic_write_json(cfg.workspace.dir / "_playlists" / f"{PID}.json",
                      dict(playlist_id=PID, series=SERIES, entries=entries))
    vertical = cfg.render.output_dir / IDS[0] / "full"
    vertical.mkdir(parents=True)
    (vertical / "vertical.mp4").write_bytes(b"vertical")
    atomic_write_json(vertical / "vertical.json", dict(size=8))
    return cfg


@pytest.fixture
def episodes(tmp_path):
    return seed_episodes(tmp_path)


def add_images(cfg, tmp_path):
    result = []
    for n in range(2):
        file = tmp_path / f"speaker{n}.jpg"
        file.write_bytes(f"speaker{n}".encode())
        asset = assets.add(cfg.packaging.asset_dir, file, kind="image", source="local:test", license="CC0", run=fake_media)
        assets.approve(cfg.packaging.asset_dir, asset["id"])
        result.append(asset["id"])
    return sorted(result)


def episode_media(cmd):
    if "rawvideo" in cmd:
        Path(cmd[-1]).write_bytes(bytes([32] * 12))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return fake_media(cmd)


@pytest.mark.parametrize("style", ["A", "B", "C"])
@pytest.mark.parametrize("shape", ["landscape", "vertical"])
def test_real_styles_dimensions_fonts_fit_and_portrait_masks(episodes, tmp_path, style, shape):
    cfg = episodes
    work = tmp_path / "render with spaces"
    work.mkdir()
    white = (style == "C") or (style == "A" and shape == "landscape")
    image = tmp_path / "portrait.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=" + ("white" if white else "0x3b5670") + ":s=800x1000,drawbox=x=250:y=150:w=300:h=700:color=0x987654:t=fill",
                    "-frames:v", "1", "-threads", "1", str(image)], check=True)
    settings = dict(episode.read_settings(cfg, PID), style=style)
    header = episode.header(cfg, IDS[1])
    settings["title_lines"][2] = unicodedata.normalize("NFD", settings["title_lines"][2])
    path = thumbnail.build_episode(work, header, shape, image, "test.jpg", settings=settings)
    assert path.read_bytes().startswith(b"\xff\xd8") and path.stat().st_size <= thumbnail.MAX_BYTES
    stream = probe_media(path, _run)["video"]
    assert (stream["width"], stream["height"]) == thumbnail.EPISODE_SIZES[shape]
    graph = (work / "graph.txt").read_text()
    assert ("colorkey=" in graph) == white
    assert ("hypot(" in graph) == (not white)
    assert ("alphamerge" in graph) == (style != "C")
    assert "expansion=none" in graph
    for line in thumbnail.episode_text(header, shape, settings):
        assert Font(thumbnail.EPISODE_FONTS[line.font]).width(line.text, line.size) <= line.width
        assert not Font(thumbnail.EPISODE_FONTS[line.font]).missing(line.text)
        assert line.x + line.width <= (640 if shape == "landscape" and style in ("A", "B") else thumbnail.EPISODE_SIZES[shape][0])
    assert thumbnail.episode_text(header, shape, settings)[-1].text.upper() == "TẬP 102"
    assert graph.count("y_align=baseline") == graph.count("drawtext=")
    third = thumbnail.episode_text(header, shape, settings)[2]
    if style == "C":
        ribbon_x, ribbon_width = (70, 940) if shape == "vertical" else (540, 660)
        text_width = Font(thumbnail.EPISODE_FONTS[third.font]).width(third.text, third.size)
        assert third.centered and third.width == ribbon_width - 48
        left = third.x + (third.width - text_width) / 2
        assert left >= ribbon_x + 24
        assert left + text_width <= ribbon_x + ribbon_width - 24
        assert left + text_width / 2 == pytest.approx(ribbon_x + ribbon_width / 2)


@pytest.mark.parametrize("style", ["A", "B", "C"])
@pytest.mark.parametrize("shape", ["landscape", "vertical"])
@pytest.mark.parametrize("middle", ["Địa Tạng", "Niệm", "Ỗ Ộ"])
def test_episode_baselines_and_ink_bounds_do_not_overlap(episodes, style, shape, middle):
    cfg = episodes
    settings = dict(episode.read_settings(cfg, PID), style=style)
    header = episode.header(cfg, IDS[0])
    default = thumbnail.episode_text(header, shape, settings)
    if middle != "Địa Tạng":
        settings["title_lines"] = ["Kinh", middle, "Phật vãng sanh"]
    lines = thumbnail.episode_text(header, shape, settings)
    assert [line.y for line in lines] == [line.y for line in default]
    boxes = []
    for line in lines:
        font = Font(thumbnail.EPISODE_FONTS[line.font])
        top, bottom = font.ink_bounds(line.text, line.size)
        assert font.width(line.text, line.size) <= line.width
        # Include the actual gold stroke and offset shadow, or B's 4px shadow.
        boxes.append((line.y + top - (3 if line.gold else 0),
                      line.y + bottom + (7 if line.gold else 4 if style == "B" else 0)))
    bx, by, bw, bh = thumbnail.episode_badge(style, shape)
    assert by + 2 <= boxes[-1][0] and boxes[-1][1] <= by + bh - 2
    regions = sorted([*boxes[:-1], (by, by + bh)])
    assert all(bottom + 2 <= next_top for (_, bottom), (next_top, _) in zip(regions, regions[1:]))
    if style == "C":
        ribbon_top, ribbon_height = (480, 110) if shape == "vertical" else (268, 78)
        assert ribbon_top + 2 <= boxes[2][0] and boxes[2][1] <= ribbon_top + ribbon_height - 2
    if middle == "Địa Tạng":
        tops = (130, 270, 494) if shape == "vertical" else {"A": (70, 150, 305), "B": (100, 180, 318), "C": (70, 150, 280)}[style]
        for line, top in zip(lines[:3], tops):
            assert abs(line.y + Font(thumbnail.EPISODE_FONTS[line.font]).ink_bounds(line.text, line.size)[0] - top) <= 2


def test_real_accent_masks_match_baseline_metrics(episodes, tmp_path):
    cfg = episodes
    settings = dict(episode.read_settings(cfg, PID), title_lines=["Kinh", "Niệm", "Phật vãng sanh"])
    lines = thumbnail.episode_text(episode.header(cfg, IDS[0]), "landscape", settings)[:3]
    work = tmp_path / "ink"
    work.mkdir()
    shutil.copyfile(thumbnail.EPISODE_FONTS["serif"], work / "serif.ttf")
    g = thumbnail._EpisodeGraph(work, 640, 420)
    outputs = []
    for line in lines:
        base = g.add("color=c=black:s=640x420")
        label = g.text(base, line, color="white")
        outputs.extend(["-map", f"[{label}]", "-frames:v", "1", "-threads", "1", "-pix_fmt", "gray", "-f", "rawvideo", str(work / f"{len(outputs)}.gray")])
    script = work / "graph.txt"
    script.write_text(";".join(g.parts))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex_threads", "1", "-filter_complex_script", str(script), *outputs], check=True)
    actual = []
    for path, line in zip(sorted(work.glob("*.gray"), key=lambda p: int(p.stem)), lines):
        data = path.read_bytes()
        rows = [y for y in range(420) if max(data[y*640:(y+1)*640]) > 32]
        assert rows
        top, bottom = Font(thumbnail.EPISODE_FONTS[line.font]).ink_bounds(line.text, line.size)
        assert abs(min(rows) - (line.y + top)) <= 2
        assert abs(max(rows) + 1 - (line.y + bottom)) <= 2
        actual.append((min(rows), max(rows) + 1))
    assert all(bottom + 8 <= next_top for (_, bottom), (next_top, _) in zip(actual, actual[1:]))


def test_real_transparent_portrait_preserves_original_alpha(episodes, tmp_path):
    cfg = episodes
    settings = dict(episode.read_settings(cfg, PID), style="C")
    header = episode.header(cfg, IDS[0])
    # Fully transparent black RGB around an opaque subject: the ellipse must not expose RGB black.
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\0" + b"".join(bytes((200, 40, 20, 255)) if 120 <= x < 260 and 150 <= y < 600
                                   else bytes(4) for x in range(640)) for y in range(720))
    image = tmp_path / "cutout.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 640, 720, 8, 6, 0, 0, 0))
                      + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    pixels = []
    for name, portrait in (("background", None), ("portrait", image)):
        work = tmp_path / name
        work.mkdir()
        path = thumbnail.build_episode(work, header, "landscape", portrait, "test.jpg", settings=settings)
        pixels.append(subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-threads", "1",
                                      "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout)
    at = (360 * 1280 + 300) * 3
    background, portrait = [data[at:at+3] for data in pixels]
    assert all(c > 180 for c in portrait)  # paper color, not the PNG's hidden black RGB
    assert all(abs(a-b) <= 5 for a, b in zip(background, portrait))
    at = (360 * 1280 + 150) * 3
    red, green, blue = pixels[1][at:at+3]
    assert red > green + 20 and red > blue + 20  # opaque subject still survives the mask


def test_default_settings_truncates_long_series_at_word_boundary(episodes):
    cfg = episodes
    series = "Kinh Vô Lượng Thọ Bồ Tát Quảng Đại Viên Mãn Vô Ngại Đại Bi Tâm Đà La Ni Kinh"
    doc = episode.playlist(cfg, PID)
    doc["series"] = series
    atomic_write_json(cfg.workspace.dir / "_playlists" / f"{PID}.json", doc)
    settings = episode.read_settings(cfg, PID)
    assert settings["title_lines"][:2] == ["Kinh", "Vô Lượng"]
    assert len(settings["title_lines"]) == 3
    assert all(0 < len(line) <= 40 for line in settings["title_lines"])
    words = " ".join(settings["title_lines"]).split()
    assert words == series.split()[:len(words)] and len(words) < len(series.split())
    assert episode.validate_settings(cfg, settings) == settings


@pytest.mark.parametrize("missing", ["header", "number", "media"])
def test_skips_missing_input_and_continues(episodes, missing):
    cfg = episodes
    if missing == "header":
        (cfg.workspace.dir / IDS[0] / "titles.json").unlink()
        doc = episode.playlist(cfg, PID)
        doc.pop("series")
        atomic_write_json(cfg.workspace.dir / "_playlists" / f"{PID}.json", doc)
    elif missing == "number":
        atomic_write_json(cfg.workspace.dir / IDS[0] / "titles.json", dict(header=dict(fields=dict(series=SERIES))))
    else:
        (cfg.workspace.dir / IDS[0] / "source.mp4").unlink()
        (cfg.render.output_dir / IDS[0] / "full" / "vertical.mp4").unlink()
    result = episode.build_playlist(cfg, PID, run=fake_media)
    assert result["built"] == 1 and len(result["skipped"]) == 1 and result["skipped"][0]["episode"] == IDS[0]
    doc = episode.read(cfg, IDS[0])
    assert doc["skipped_reason"] and not doc["files"]
    assert episode.valid_files(cfg, IDS[1])


def test_header_kt_and_playlist_fallback_and_vertical_without_source(episodes):
    cfg = episodes
    path = cfg.workspace.dir / IDS[0] / "titles.json"
    dest = cfg.workspace.dir / (IDS[0] + ".kt") / "titles.json"
    dest.parent.mkdir()
    path.replace(dest)
    assert episode.header(cfg, IDS[0])["episode"] == "101"
    dest.unlink()
    assert episode.header(cfg, IDS[0])["series"] == SERIES
    assert episode.header(cfg, IDS[0])["episode"] == "101"
    (cfg.workspace.dir / IDS[0] / "source.mp4").unlink()
    assert episode.shapes(cfg, IDS[0]) == ["landscape", "vertical"]
    (cfg.render.output_dir / IDS[0] / "full" / "vertical.mp4").write_bytes(b"incomplete")
    assert episode.shapes(cfg, IDS[0]) == []


@pytest.mark.parametrize("field,value", [("style", "B"), ("asset_id", "image"), ("focus_x", 0.8),
                                       ("title_lines", ["Kinh", "Hoa Nghiêm"]), ("credit", "CHỦ GIẢNG: TỊNH KHÔNG")])
def test_playlist_settings_rebuild_all_and_cache(episodes, tmp_path, field, value):
    cfg = episodes
    pool = add_images(cfg, tmp_path)
    defaults = episode.read_settings(cfg, PID)
    assert defaults["asset_id"] is None and defaults["title_lines"] == ["Kinh", "Địa Tạng", "Bồ Tát Bổn Nguyện"]
    episode.build_playlist(cfg, PID, run=episode_media)
    settings = dict(defaults, **{field: pool[0] if value == "image" else value})
    assert episode.write_settings(cfg, PID, settings) == settings
    assert episode.read_settings(cfg, PID) == settings
    assert not episode.valid_files(cfg, IDS[0])
    calls = []
    def counted(cmd):
        calls.append(cmd)
        return episode_media(cmd)
    assert episode.build_playlist(cfg, PID, run=counted) == dict(built=2, reused=0, skipped=[])
    assert len([cmd for cmd in calls if "mjpeg" in cmd]) == 3
    assert all(episode.read(cfg, ident)["asset_id"] == settings["asset_id"] for ident in IDS)
    assert episode.build_playlist(cfg, PID, run=lambda _: pytest.fail("cached settings ran ffmpeg"))["reused"] == 2
    episode.write_settings(cfg, PID, dict(settings, asset_id=None))
    episode.build_playlist(cfg, PID, run=episode_media)
    assert all(episode.read(cfg, ident)["asset_id"] is None for ident in IDS)


@pytest.mark.parametrize("field,value", [("style", "D"), ("asset_id", "x"*64), ("focus_x", -0.1),
    ("focus_x", 1.1), ("focus_x", float("nan")), ("focus_x", True), ("title_lines", []),
    ("title_lines", [" "]), ("title_lines", ["A"]*4), ("title_lines", ["A"*41]),
    ("title_lines", ["a\nb"]), ("credit", "a"*61)])
def test_settings_validation_and_asset_approval(episodes, tmp_path, field, value):
    cfg = episodes
    settings = episode.read_settings(cfg, PID)
    with pytest.raises(PackageError):
        episode.write_settings(cfg, PID, dict(settings, **{field: value}))
    assert not episode.settings_path(cfg, PID).exists()
    pool = add_images(cfg, tmp_path)
    library = assets.list_assets(cfg.packaging.asset_dir)
    for asset in library:
        asset["approved"] = False
    atomic_write_json(cfg.packaging.asset_dir / "library.json", dict(schema_version=1, assets=library))
    assert episode.images(cfg) == []
    with pytest.raises(PackageError):
        episode.write_settings(cfg, PID, dict(settings, asset_id=pool[0]))


def test_preview_is_temporary_and_text_is_not_filter_syntax(episodes, tmp_path):
    cfg = episodes
    settings = episode.read_settings(cfg, PID)
    settings["title_lines"] = ["Kinh %{pts}: 'Niệm Phật'"]
    before = {str(p): p.read_bytes() for p in cfg.render.output_dir.rglob("*") if p.is_file()}
    scripts, folders = [], []
    def inspect(cmd):
        script = Path(cmd[cmd.index("-filter_complex_script") + 1])
        scripts.append(script.read_text())
        folders.append(script.parent)
        assert settings["title_lines"][0].upper() in " ".join(p.read_text() for p in script.parent.glob("line*.txt"))
        return episode_media(cmd)
    result = episode.preview(cfg, PID, settings=settings, run=inspect)
    assert set(result) == {"landscape", "vertical"}
    assert all(data.startswith(b"jpeg:") for data in result.values())
    assert all("%{pts}" not in graph and "Niệm Phật" not in graph and "expansion=none" in graph for graph in scripts)
    assert all(not folder.exists() for folder in folders)
    assert before == {str(p): p.read_bytes() for p in cfg.render.output_dir.rglob("*") if p.is_file()}
    assert not episode.settings_path(cfg, PID).exists()
    partial_folders = []
    def failed(cmd):
        path = Path(cmd[-1])
        partial_folders.append(path.parent)
        path.write_bytes(b"partial")
        return subprocess.CompletedProcess(cmd, 1, "", "preview failed")
    with pytest.raises(RenderError, match="preview failed"):
        episode.preview(cfg, PID, settings=settings, run=failed)
    assert all(not folder.exists() for folder in partial_folders)
    assert before == {str(p): p.read_bytes() for p in cfg.render.output_dir.rglob("*") if p.is_file()}
    work = tmp_path / "glyph"
    work.mkdir()
    with pytest.raises(TextError, match="glyph|missing"):
        thumbnail.build_episode(work, episode.header(cfg, IDS[0]), "landscape", None, "test.jpg",
                                settings=dict(settings, title_lines=["Kinh 🧘"]),
                                run=lambda _: pytest.fail("missing glyph ran ffmpeg"))


def test_cache_sha_header_key_and_removal_of_old_files(episodes, tmp_path, monkeypatch):
    cfg = episodes
    episode.build_playlist(cfg, PID, run=fake_media)
    unchanged = {ident: (episode.directory(cfg, ident) / "thumbs.json").read_bytes() for ident in IDS}
    monkeypatch.setattr(episode, "utc_now", lambda: "2099-01-01T00:00:00Z")
    assert episode.build_playlist(cfg, PID, run=lambda _: pytest.fail("cache called ffmpeg")) == dict(built=0, reused=2, skipped=[])
    assert unchanged == {ident: (episode.directory(cfg, ident) / "thumbs.json").read_bytes() for ident in IDS}
    folder = episode.directory(cfg, IDS[0])
    old = episode.read(cfg, IDS[0])
    (folder / old["files"]["landscape"]["file"]).write_bytes(b"corrupt")
    calls = []
    def counted(cmd):
        calls.append(cmd)
        return fake_media(cmd)
    episode.build_playlist(cfg, PID, run=counted)
    assert len(calls) == 1
    doc = json.loads((cfg.workspace.dir / IDS[0] / "titles.json").read_text())
    doc["header"]["fields"]["episode"] = "102"
    atomic_write_json(cfg.workspace.dir / IDS[0] / "titles.json", doc)
    assert not episode.valid_files(cfg, IDS[0])
    calls.clear()
    episode.build_playlist(cfg, PID, run=counted)
    assert len(calls) == 2
    assert all(not (folder / entry["file"]).exists() for entry in old["files"].values())
    assert len(episode.valid_files(cfg, IDS[0])) == 2
    font = tmp_path / "changed-serif.ttf"
    font.write_bytes(thumbnail.EPISODE_FONTS["serif"].read_bytes() + b"font revision")
    monkeypatch.setitem(thumbnail.EPISODE_FONTS, "serif", font)
    assert not episode.valid_files(cfg, IDS[0])
    calls.clear()
    assert episode.build_playlist(cfg, PID, run=counted)["built"] == 2
    assert len(calls) == 3


@pytest.mark.parametrize("failure_at", [1, 2])
def test_failure_keeps_previous_files_and_other_episode_and_no_partial_files(episodes, failure_at):
    cfg = episodes
    episode.build_playlist(cfg, PID, run=fake_media)
    first = episode.directory(cfg, IDS[0])
    second = episode.directory(cfg, IDS[1])
    before = {p.name: p.read_bytes() for p in first.glob("*.jpg")}
    unchanged = {p.name: p.read_bytes() for p in second.iterdir()}
    title = cfg.workspace.dir / IDS[0] / "titles.json"
    doc = json.loads(title.read_text())
    doc["header"]["fields"]["series"] = "Kinh Vô Lượng Thọ"
    atomic_write_json(title, doc)
    calls = []
    def failing(cmd):
        calls.append(cmd)
        if len(calls) == failure_at:
            Path(cmd[-1]).write_bytes(b"partial")
            return subprocess.CompletedProcess(cmd, 1, "", "simulated failure")
        return fake_media(cmd)
    result = episode.build_playlist(cfg, PID, run=failing)
    assert result["reused"] == 1 and len(result["skipped"]) == 1
    assert "simulated failure" in episode.read(cfg, IDS[0])["skipped_reason"]
    assert before == {p.name: p.read_bytes() for p in first.glob("*.jpg")}
    assert unchanged == {p.name: p.read_bytes() for p in second.iterdir()}
    assert {p.name for p in first.iterdir()} == {*before, "thumbs.json"}
    assert len(episode.valid_files(cfg, IDS[1])) == 1
    assert episode.build_playlist(cfg, PID, run=fake_media)["built"] == 1


@pytest.mark.parametrize("attack", ["id", "name", "directory_symlink", "file_symlink"])
def test_rejects_traversal_and_symlink_artifacts(episodes, tmp_path, attack):
    cfg = episodes
    if attack == "id":
        with pytest.raises(PackageError):
            episode.directory(cfg, "../outside")
        with pytest.raises(PackageError):
            episode.playlist(cfg, "../outside")
        return
    folder = episode.directory(cfg, IDS[0])
    if attack == "directory_symlink":
        folder.symlink_to(tmp_path)
        with pytest.raises(PackageError):
            episode.build_episode(cfg, IDS[0], pid=PID, run=episode_media)
        return
    episode.build_playlist(cfg, PID, run=fake_media)
    doc = episode.read(cfg, IDS[0])
    entry = doc["files"]["landscape"]
    if attack == "file_symlink":
        path = folder / entry["file"]
        path.unlink()
        path.symlink_to(cfg.workspace.dir / IDS[0] / "source.mp4")
        assert "landscape" not in episode.valid_files(cfg, IDS[0])
    else:
        entry["file"] = "../secret.jpg"
        atomic_write_json(folder / "thumbs.json", doc)
        with pytest.raises(PackageError):
            episode.read(cfg, IDS[0])


@pytest.mark.parametrize("height,state,changed,expected", [(1080, None, False, True), (480, None, False, False),
                                                         (480, "pending", False, False), (480, "done", False, True),
                                                         (480, "done", True, False)])
def test_hd_eligibility_uses_completed_enhance_or_high_resolution_original(episodes, height, state, changed, expected):
    cfg = episodes
    ident = IDS[1]  # no vertical file to independently qualify it
    folder = cfg.workspace.dir / ident
    atomic_write_json(folder / "metadata.json", dict(title="Bài giảng", height=height))
    if state:
        path = folder / "source_hd.mp4"
        path.write_bytes(b"finished HD")
        atomic_write_json(folder / "enhance.json", dict(schema_version=1, state=state,
                          source_hd_sha256=sha256_file(path), source_hd_size=path.stat().st_size,
                          source_hd_mtime_ns=path.stat().st_mtime_ns))
        if changed:
            path.write_bytes(b"changed HD")
    assert episode.shapes(cfg, ident) == (["landscape"] if expected else [])
