"""THUMB2 AC1–3: offline source adapters, real JPEGs, atomic publication and legacy bytes."""
import subprocess
import unicodedata

import pytest

from auto_short import theme_plan
from auto_short.compilation import Item, store
from auto_short.hashing import config_hash, sha256_file
from auto_short.packaging import PackageError, compilation_thumbs as ct, cover, episode, khaithi_thumbs as kt, thumbnail
from auto_short.render.stage import RenderError, _run, probe_media
from auto_short.render.text import Font, TextError
from auto_short.workspace import atomic_write_json
from test_khaithi_thumbs import cfg, portrait_manifest  # noqa: F401 — approved covers / source fixtures
from test_packaging_cover import source_image
from test_packaging_episode import IDS, PID
from test_packaging_thumbnail import fake_media

CID = "0123456789ab"
TITLE = "Học kinh không chỉ hiểu mà phải thực hành"


@pytest.fixture(params=["favorites", "theme"])
def compilation(cfg, request, monkeypatch):
    # First segment is episode 23, deliberately followed by an earlier episode.
    fields = dict(episode.header(cfg, IDS[0]), episode="23")
    atomic_write_json(cfg.workspace.dir / IDS[0] / "titles.json", dict(header=dict(fields=fields)))
    items = [dict(episode_id=IDS[0] + ".kt", clip="k01"), dict(episode_id=IDS[1], clip="s01")]
    folder = store.directory(cfg.render.output_dir, PID)
    doc = store.new_doc(PID, CID, "concat", tuple(Item(i["episode_id"], i["clip"]) for i in items), 1,
                        download_name="video.mp4", title=TITLE, duration_estimate=100)
    doc["status"] = store.DONE
    store.write_doc(folder, doc)
    (folder / f"{CID}.mp4").write_bytes(b"original compilation")
    plan = dict(plan_id="abcdefgh", revision=1, title=TITLE, clips=items)
    def approved(config, pid, ident):
        assert config == cfg and pid == PID and ident == plan["plan_id"]
        return dict(plan)
    monkeypatch.setattr(theme_plan, "approved_plan", approved)
    def current():
        return ct.favorite(cfg, PID, CID) if request.param == "favorites" else ct.theme(cfg, PID, plan["plan_id"])
    def title(value):
        plan["title"] = doc["title"] = value
        store.write_doc(folder, doc)
    return cfg, current, title, plan


def test_two_real_shapes_text_and_cache(compilation, monkeypatch):
    cfg, current, _, _ = compilation
    source = current()
    atomic_write_json(cfg.packaging.asset_dir / "khaithi_from.json", dict(schema_version=1, playlists={PID: 500}))
    seen = []
    real = kt.draw
    def draw(*args, **kwargs):
        lines, styles = kt.layout(args[1], args[2], args[3]["box"], label=kwargs["label"], series_line=kwargs["series_line"])
        assert lines[0].text == ct.LABEL
        assert lines[-1].text == source.fields["series"] and "Tập " not in lines[-1].text
        assert lines[-2].text == source.fields["speaker"].upper()
        assert 1 <= len(lines[1:-2]) <= 3 and " ".join(l.text for l in lines[1:-2]) == TITLE
        x, y, w, h = args[3]["box"]
        for line, style in zip(lines, styles):
            font = Font(thumbnail.EPISODE_FONTS[line.font])
            top, bottom = font.ink_bounds(line.text, line.size)
            assert font.width(line.text, line.size) <= w * kt.FIT_WIDTH
            assert y <= line.y + top - 2 and line.y + bottom + (4 if style["shadow"] else 2) <= y + h
        seen.append(args[4])
        return real(*args, **kwargs)
    monkeypatch.setattr(kt, "draw", draw)
    assert ct.build(cfg, source, current=current) == dict(built=2, reused=0)
    assert set(seen) == set(thumbnail.EPISODE_SIZES)
    doc = ct.read(source)
    assert len(doc["files"]) == 2
    for shape, entry in doc["files"].items():
        path = source.folder / entry["file"]
        stream = probe_media(path, _run)["video"]
        assert (stream["width"], stream["height"]) == thumbnail.EPISODE_SIZES[shape]
        assert sha256_file(path) == entry["sha256"] and entry["key"] in path.name
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in source.folder.iterdir()}
    assert ct.build(cfg, current(), run=lambda _: pytest.fail("cache called ffmpeg")) == dict(built=0, reused=2)
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in source.folder.iterdir()}


@pytest.mark.parametrize("change", ["title", "cover", "portrait", "speaker", "series"])
def test_changed_inputs_stale_rebuild_and_scoped_cleanup(compilation, tmp_path, change):
    cfg, current, title, _ = compilation
    ct.build(cfg, current(), run=fake_media)
    source = current()
    before = ct.read(source)["files"]
    legacy = source.folder / ("A-landscape-" + "a" * 64 + ".jpg")
    legacy.write_bytes(b"legacy thumbnail kept")
    (source.folder / "variant-old.mp4").write_bytes(b"old music / visual kept")
    if change == "title":
        title("Buông bỏ để được an vui")
    elif change == "cover":
        for shape in thumbnail.EPISODE_SIZES:
            entry = cover.current(cfg, PID)["kt_" + shape]
            cover.install(cfg, PID, "kt_" + shape, source_image(tmp_path, thumbnail.EPISODE_SIZES[shape], color="0x311650"), entry["box"])
    elif change == "portrait":
        portrait_manifest(cfg)
    elif change == "speaker":
        fields = dict(source.fields, speaker="Pháp Sư Tịnh Không")
        atomic_write_json(cfg.workspace.dir / IDS[0] / "titles.json", dict(header=dict(fields=fields)))
    else:
        doc = episode.playlist(cfg, PID)
        atomic_write_json(cfg.workspace.dir / "_playlists" / f"{PID}.json", dict(doc, series="Kinh Vô Lượng Thọ"))
    assert not ct.valid_files(cfg, current())
    # fake_media does not need portrait probing except for its dimensions.
    def media(cmd):
        if cmd[0] == "ffprobe":
            return _run(cmd)
        return fake_media(cmd)
    assert ct.build(cfg, current(), run=media)["built"] == 2
    assert len(ct.valid_files(cfg, current())) == 2
    assert all(not (source.folder / entry["file"]).exists() for entry in before.values())
    assert legacy.read_bytes() == b"legacy thumbnail kept" and (source.folder / "variant-old.mp4").is_file()


@pytest.mark.parametrize("facing", ["left", "right", "front"])
def test_first_segment_episode_23_portrait_and_landscape_flip(compilation, monkeypatch, facing):
    cfg, current, _, _ = compilation
    folder, entries = portrait_manifest(cfg, count=3)
    entries[1]["facing"] = facing
    atomic_write_json(folder / "portraits.json", dict(schema_version=1, portraits=entries))
    seen = []
    real = kt.draw
    def draw(*args, **kwargs):
        assert kwargs["portrait"] == folder / entries[1]["file"]
        assert kwargs["facing"] == facing
        output = real(*args, **kwargs)
        graph = (args[0] / "graph.txt").read_text()
        assert (",hflip" in graph) == (args[4] == "landscape" and facing == "left")
        seen.append(args[4])
        return output
    monkeypatch.setattr(kt, "draw", draw)
    ct.build(cfg, current(), run=lambda cmd: _run(cmd) if cmd[0] == "ffprobe" else fake_media(cmd))
    assert len(seen) == 2


@pytest.mark.parametrize("problem", ["covers", "one_cover", "empty", "overflow"])
def test_missing_cover_or_bad_title_writes_nothing(compilation, problem):
    cfg, current, title, _ = compilation
    source = current()
    if problem in ("covers", "one_cover"):
        for shape in (["kt_vertical", "kt_landscape"] if problem == "covers" else ["kt_landscape"]):
            cover.remove(cfg, PID, shape)
        expected, text = PackageError, ct.MISSING_COVER
    else:
        title("" if problem == "empty" else "W" * 1000)
        expected, text = TextError, "rỗng" if problem == "empty" else "không vừa"
    with pytest.raises(expected, match=text):
        ct.build(cfg, current(), run=lambda _: pytest.fail("invalid input ran ffmpeg"))
    assert not source.folder.exists()


@pytest.mark.parametrize("failure", ["renderer", "changed_input"])
def test_failed_build_preserves_previous_sidecar_files_and_video(compilation, failure):
    cfg, current, title, _ = compilation
    source = current()
    ct.build(cfg, source, run=fake_media)
    title("Buông bỏ để được an vui")
    before = {p.name: p.read_bytes() for p in source.folder.iterdir()}
    calls = []
    def run(cmd):
        calls.append(cmd)
        if len(calls) == 2:
            if failure == "renderer":
                return subprocess.CompletedProcess(cmd, 1, "", "simulated failure")
            title("Niệm Phật để được an vui")
        return fake_media(cmd)
    with pytest.raises((RenderError, PackageError)):
        ct.build(cfg, current(), run=run, current=current)
    assert before == {p.name: p.read_bytes() for p in source.folder.iterdir()}
    assert (store.directory(cfg.render.output_dir, PID) / f"{CID}.mp4").read_bytes() == b"original compilation"


def test_new_theme_revision_has_no_thumbnails_and_keeps_old(compilation):
    cfg, current, _, plan = compilation
    if current().identity == CID:
        return  # the other adapter has no plan revisions
    source = current()
    ct.build(cfg, source, run=fake_media)
    before = {p.name: p.read_bytes() for p in source.folder.iterdir()}
    plan["revision"] += 1
    assert current().folder != source.folder and ct.read(current()) is None
    assert ct.valid_files(cfg, current()) == {}
    ct.build(cfg, current(), run=fake_media)
    assert before == {p.name: p.read_bytes() for p in source.folder.iterdir()}


@pytest.mark.parametrize("damage", ["sha", "symlink", "manifest", "folder", "traversal"])
def test_tampered_thumbnails_fail_closed(compilation, tmp_path, damage):
    cfg, current, _, _ = compilation
    source = current()
    ct.build(cfg, source, run=fake_media)
    doc = ct.read(source)
    path = source.folder / doc["files"]["vertical"]["file"]
    if damage == "sha":
        path.write_bytes(b"tampered")
    elif damage == "symlink":
        target = tmp_path / "outside.jpg"
        path.replace(target)
        path.symlink_to(target)
    elif damage == "manifest":
        path = source.folder / "thumbs.json"
        target = tmp_path / "outside.json"
        path.replace(target)
        path.symlink_to(target)
    elif damage == "folder":
        source.folder.rename(tmp_path / "outside")
        source.folder.symlink_to(tmp_path / "outside", target_is_directory=True)
    else:
        doc["files"]["vertical"]["file"] = "../outside.jpg"
        atomic_write_json(source.folder / "thumbs.json", doc)
    try:
        assert "vertical" not in ct.valid_files(cfg, source)
    except PackageError:
        assert damage in ("manifest", "folder", "traversal")


# Frozen from HEAD 48c7677 before parameterisation: actual VLT KT frames, fonts and old key formula.
@pytest.mark.parametrize("shape,box,sizes,ys", [
    ("vertical", [107, 129, 865, 597], [35, 80, 80, 80, 52, 34], [212, 301, 410, 512, 605, 669]),
    ("landscape", [560, 112, 623, 475], [27, 62, 62, 62, 40, 26], [179, 249, 335, 416, 488, 539]),
])
def test_default_kt_bytes_and_key_equal_pre_thumb2(tmp_path, shape, box, sizes, ys):
    fields = dict(speaker="HT. Tịnh Không", series="Kinh Vô Lượng Thọ", episode="23")
    image = source_image(tmp_path, thumbnail.EPISODE_SIZES[shape])
    entry = dict(box=box, sha256=sha256_file(image))
    texts = ["TRÍCH ĐOẠN KHAI THỊ", "Học kinh", "không chỉ hiểu", "mà phải thực hành", "HT. TỊNH KHÔNG", "Kinh Vô Lượng Thọ · Tập 23"]
    fonts = ["sans", "old", "old", "old", "sans", "sans"]
    lines = [thumbnail.EpisodeLine(t, f, s, box[0], y, box[2], centered=True) for t, f, s, y in zip(texts, fonts, sizes, ys)]
    styles = [dict(color=c, shadow=v) for c, v in [("0xf2c66d", False), *([("0xe8bf62", True)] * 3), ("0xfff3d6", True), ("0xe9d9b0", False)]]
    reference, actual = tmp_path / "reference", tmp_path / "actual"
    reference.mkdir()
    actual.mkdir()
    before = cover.draw_lines(reference, lines, image, "baseline.jpg", styles=styles)
    after = kt.draw(actual, TITLE, fields, entry, shape, image, "baseline.jpg")
    assert before.read_bytes() == after.read_bytes()
    old_key = config_hash(dict(title=TITLE, episode="23", cover_sha256=entry["sha256"], box=box,
        layout_version=6, font_sha256=sha256_file(thumbnail.EPISODE_FONTS[cover.FONT_NAME]),
        sans_sha256=sha256_file(thumbnail.EPISODE_FONTS["sans"]), speaker=fields["speaker"], series=fields["series"],
        portrait_sha256=None, portrait_library=(), compounds_sha256=sha256_file(kt.COMPOUNDS), shape=shape, hflip=False))
    assert kt.cache_key(TITLE, "23", entry, shape, speaker=fields["speaker"], series=fields["series"]) == old_key
    assert kt.cache_key(TITLE, "23", entry, shape, speaker=fields["speaker"], series=fields["series"],
                        label=kt.DEFAULT_LABEL, series_line=texts[-1]) == old_key
    assert kt.cache_key(TITLE, "23", entry, shape, speaker=fields["speaker"], series=fields["series"],
                        label=unicodedata.normalize("NFD", kt.DEFAULT_LABEL)) == old_key
    for override in (dict(label=ct.LABEL), dict(series_line=fields["series"])):
        assert kt.cache_key(TITLE, "23", entry, shape, speaker=fields["speaker"], series=fields["series"], **override) != old_key


@pytest.mark.parametrize("shape,box,size,baseline", [
    ("vertical", [305, 1630, 470, 125], 87, 1723),  # VLT episode cover
    ("landscape", [133, 484, 354, 79], 53, 542),
    ("vertical", [248, 1632, 584, 146], 103, 1741),  # Địa Tạng episode cover
    ("landscape", [107, 503, 444, 76], 50, 558),
])
def test_thumb1_episode_bytes_and_key_unchanged(cfg, tmp_path, shape, box, size, baseline):
    fields = dict(episode.header(cfg, IDS[0]), episode="23")
    image = source_image(tmp_path, thumbnail.EPISODE_SIZES[shape])
    entry = dict(box=box, sha256=sha256_file(image))
    reference, actual = tmp_path / "reference", tmp_path / "actual"
    reference.mkdir()
    actual.mkdir()
    frozen = thumbnail.EpisodeLine("TẬP 23", "old", size, box[0], baseline, box[2], centered=True)
    before = cover.draw_lines(reference, [frozen], image, "before.jpg")
    after = cover.build_episode(actual, fields, shape, image, "after.jpg", entry=entry)
    assert before.read_bytes() == after.read_bytes()
    old_key = config_hash(dict(cover_sha256=entry["sha256"], box=box, episode="23", layout_version=3,
                              font_sha256=sha256_file(thumbnail.EPISODE_FONTS[cover.FONT_NAME]), shape=shape))
    assert episode.cache_key(fields, episode.read_settings(cfg, PID), shape, cover_entry=entry) == old_key


@pytest.mark.parametrize("title, expected", [
    ("Hòa Thượng Tịnh Không - Chuyển hóa tâm niệm", "Chuyển hóa tâm niệm"),
    ("HT. Tịnh Không - Phước đức và công đức", "Phước đức và công đức"),
    (unicodedata.normalize("NFD", "Hòa Thượng Tịnh Không - Niệm Phật"), "Niệm Phật"),
    ("Tịnh độ - Niệm Phật vãng sanh", "Tịnh độ - Niệm Phật vãng sanh"),  # not the speaker: kept
    ("Hòa Thượng Tịnh Không - ", "Hòa Thượng Tịnh Không - "),  # nothing after the dash: kept (empty-title rule applies)
    ("Buông bỏ để được an vui", "Buông bỏ để được an vui"),
])
def test_thumb_title_drops_leading_speaker(title, expected):
    assert unicodedata.normalize("NFC", ct.thumb_title(title, "HT.Tịnh Không")) == unicodedata.normalize("NFC", expected)
