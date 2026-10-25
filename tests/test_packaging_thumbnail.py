"""PKG1 assets / CLI + PKG3 theme thumbnails (styles A/B/C): real single-frame ffmpeg, otherwise injected runners."""
import hashlib
import json
import subprocess
import unicodedata
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short.config import Config, PackagingConfig, PostConfig, RenderConfig, WorkspaceConfig, from_dict
from auto_short.hashing import sha256_file
from auto_short.packaging import PackageError, assets, record, thumbnail
from auto_short.packaging.__main__ import main
from auto_short.render.stage import RenderError, _run, probe_media
from auto_short.render.text import Font, TextError
from auto_short.workspace import atomic_write_json

PID = "PLeligible"
STYLES, SHAPES = record.STYLES, record.SHAPES


@pytest.fixture
def package(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(tmp_path / "work"), packaging=PackagingConfig(tmp_path / "assets"),
                 render=RenderConfig(output_dir=tmp_path / "output"))
    plan = dict(plan_id="abcdef123456", revision=1, title="Niệm Phật vãng sanh", title_options=["Buông xả để niệm Phật"],
                theme={"label": "Niệm Phật vãng sanh — buông xả"}, clips=[])
    meta = {"sha256": "a" * 64, "duration": 1260.4}
    folder = record.directory(cfg.render.output_dir, PID, plan["plan_id"], 1)
    return cfg, plan, meta, folder, record.new(cfg, plan, meta)


def fake_media(cmd):
    if cmd[0] == "ffprobe":
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"streams": [
            {"codec_type": "video", "width": 800, "height": 800}], "format": {}}), "")
    Path(cmd[-1]).write_bytes(b"jpeg:" + Path(cmd[-1]).name.encode())
    return subprocess.CompletedProcess(cmd, 0, "", "")


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "speaker.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=0x3b5670:s=800x1000,drawbox=x=250:y=150:w=300:h=700:color=0x987654:t=fill",
                    "-frames:v", "1", "-threads", "1", str(path)], check=True)
    return path


def with_image(cfg, doc, photo, styles=STYLES):
    entry = assets.add(cfg.packaging.asset_dir, photo, kind="image", source="local:test", license="CC0")
    assets.approve(cfg.packaging.asset_dir, entry["id"])
    for t in doc["thumbnails"]:
        if t["style"] in styles:
            t["asset_ids"] = [entry["id"]]
    return entry


def look(doc, style):
    return thumbnail.theme_look(doc, next(t for t in doc["thumbnails"] if t["style"] == style))


# --- AC3: episode thumbnails are unchanged by the shared-drawing refactor ---------------------------------

# sha256 of (filtergraph with the work dir masked, every drawtext textfile) captured on the pre-PKG3 code
# (base commit 5bbe51a) for style x shape x portrait (none / white-corner / dark-corner).
EPISODE_GRAPH_BASELINE = {
    ("A", "landscape", "none"): "6191e9a67d4739695329b3e98565e895ca1b144dbfa45496de4437228295b74a",
    ("A", "landscape", "white"): "944fe4f5fe177cefe17b3ea03802b94a5b2407c3b178544cda3da61fb99f4e78",
    ("A", "landscape", "dark"): "0d11d4f88b99b409ecf654d8ef4cf09f59082d7f2338e9614e3190d2c56313e0",
    ("A", "vertical", "none"): "4a66b6d2d0e2b118b8ddad608bb6a6dfb4ee8095c6729746f72ca3643c598240",
    ("A", "vertical", "white"): "401cc893c7a81015d8451aa4de1ad9732f5073264d8ad1c84855627787e14fb8",
    ("A", "vertical", "dark"): "8ef4c7c7dbee990347917d6808b6ac6569b971608e60a81f1aa48df096a5b5f7",
    ("B", "landscape", "none"): "ce5cae044d8db718906246f0b3c4bd36ebf22c63406b7b43e35a1cbdf31100cc",
    ("B", "landscape", "white"): "158521d68cc6052cf1c6a9e8108cf8127de0f1e633cb37100d503be74d6a77a7",
    ("B", "landscape", "dark"): "22e89875a12bb85885a8adf4b8ae74dcc4825fe0919b29d0ebbba26cac50f0fe",
    ("B", "vertical", "none"): "c6bbca809bc138b47340f3be3b3a154447fad99ea6c0d7cb195d4a7cd1cf9a2e",
    ("B", "vertical", "white"): "15808a79e384510f8ef3a312d1ae9e8482f7edd7750e65604c79be491068c0c5",
    ("B", "vertical", "dark"): "a3957a61d252119ad49b88fd2d750ab45bcc8921419fdf285bd13831527f1f3b",
    ("C", "landscape", "none"): "6b21c1e58424e76a623421eaa180da5b2b84852634671f7db963f7f6e73453b8",
    ("C", "landscape", "white"): "5a6cc17c6719de7fbd277d929091a549e6fda06b6061d337339f86be232a807a",
    ("C", "landscape", "dark"): "aabf4a1852abf39a6516c27be12c56421e6f73f1faf1710c6be946021ac44f80",
    ("C", "vertical", "none"): "e93e7672029aecdeea57a37ba04273e0c52e9ae3a4a75c8e8a7f04c8a104f3fe",
    ("C", "vertical", "white"): "30b092fc60a00c4d78a38d5fde2939b540ef5b69b3294027c5346ac44a0e9473",
    ("C", "vertical", "dark"): "35ccfa8a8e4c2c93269af5cf31277fc9ba81fcb971f38ca794078eb9a787bae9",
}


def episode_digest(style, shape, kind, tmp_path):
    work = tmp_path / f"{style}-{shape}-{kind}"
    work.mkdir()
    graphs = []
    def run(cmd):
        out = Path(cmd[-1])
        if "-filter_complex_script" in cmd:
            graphs.append(Path(cmd[cmd.index("-filter_complex_script") + 1]).read_text())
            out.write_bytes(b"jpeg")
        else:  # four-corner sample: white background or dark
            out.write_bytes(bytes([255] * 12) if kind == "white" else bytes([20] * 12))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    image = None
    if kind != "none":
        image = tmp_path / "portrait.jpg"
        image.write_bytes(b"x")
    settings = dict(style=style, asset_id=None, focus_x=0.5, credit="THÁI THƯỢNG CẢM ỨNG THIÊN",
                    title_lines=["Kinh", "Địa Tạng", "Bồ Tát Bổn Nguyện"])
    thumbnail.build_episode(work, dict(series="Kinh Địa Tạng", episode="102", speaker=""), shape, image, "t.jpg",
                            settings=settings, run=run)
    texts = [(p.name, p.read_text()) for p in sorted(work.glob("line*.txt"))]
    blob = json.dumps([graphs[0].replace(str(work), "<W>"), texts], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


@pytest.mark.parametrize("combo", sorted(EPISODE_GRAPH_BASELINE))
def test_episode_filtergraph_identical_to_pre_refactor(combo, tmp_path):
    assert episode_digest(*combo, tmp_path) == EPISODE_GRAPH_BASELINE[combo]


# --- AC1: three styles x two shapes, measured text boxes ---------------------------------------------------

def boxes(style, lines):
    """Vertical ink box of every line, including the gold stroke / drop shadow (as the PKG2 baseline tests)."""
    out = []
    for line in lines:
        top, bottom = Font(thumbnail.EPISODE_FONTS[line.font]).ink_bounds(line.text, line.size)
        out.append((line.y + top - (3 if line.gold else 0), line.y + bottom + (7 if line.gold else 4 if style == "B" else 0)))
    return out


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("variant", [
    dict(),
    dict(title_lines=["Kinh", "Ỗ Ộ", "Phật vãng sanh"], series="Thái Thượng Cảm Ứng Thiên", minutes=120),
    dict(title_lines=["Tuyển tập khai thị", "Niệm Phật"], series="Kinh Vô Lượng Thọ", speaker="Pháp Sư Tịnh Không"),
    dict(title_lines=["Một dòng"], series="", minutes=1),
    dict(series="Đại Phương Quảng Phật Hoa Nghiêm Kinh Chú Giải", speaker="Hòa Thượng Tịnh Không Thượng Nhân"),
])
def test_two_credit_lines_badge_and_titles_do_not_overlap(package, style, shape, variant):
    doc = package[4]
    doc["settings"]["series"] = "Thái Thượng Cảm Ứng Thiên"
    doc["settings"].update(variant)
    lines = thumbnail.theme_text(shape, look(doc, style))
    w, h = thumbnail.EPISODE_SIZES[shape]
    badge = thumbnail.theme_badge(style, shape)
    bx, by, bw, bh = badge
    expected_credits = [t for t in (doc["settings"]["series"], doc["settings"]["speaker"]) if t]
    assert len(lines) == len(doc["settings"]["title_lines"]) + len(expected_credits) + 1
    span = boxes(style, lines)
    # the duration text sits inside its frame, which holds nothing else
    assert lines[-1].text == f"{doc['settings']['minutes']} " + ("phút" if style == "C" else "PHÚT")
    assert by + 2 <= span[-1][0] and span[-1][1] <= by + bh - 2
    regions = sorted([*span[:-1], (by, by + bh)])
    assert all(bottom + 2 <= next_top for (_, bottom), (next_top, _) in zip(regions, regions[1:]))
    for line, (top, bottom) in zip(lines, span):
        font = Font(thumbnail.EPISODE_FONTS[line.font])
        assert font.width(line.text, line.size) <= line.width and not font.missing(line.text)
        assert 0 <= line.x and line.x + line.width <= w and 0 <= top and bottom <= h
        if style == "B":  # gold bars at the top and bottom edges
            assert top >= 80 and bottom <= h - 80
        if shape == "landscape" and style in ("A", "B"):
            assert line.x + line.width <= 640  # the portrait starts at x=640
    assert 0 <= bx and bx + bw <= w and by + bh <= h
    credits = lines[len(doc["settings"]["title_lines"]):-1]
    assert [c.text for c in credits] == [t.upper() if style != "C" else t for t in expected_credits]
    if len(credits) == 2:
        assert credits[0].size == credits[1].size and credits[1].y > credits[0].y


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("shape", SHAPES)
def test_real_render_six_combinations(package, photo, tmp_path, style, shape):
    cfg, _, _, folder, doc = package
    work = tmp_path / "work with spaces"
    work.mkdir()
    path = thumbnail.build_theme(work, shape, photo, "t.jpg", look=look(doc, style))
    assert path.read_bytes().startswith(b"\xff\xd8") and 0 < path.stat().st_size <= thumbnail.MAX_BYTES
    stream = probe_media(path, _run)["video"]
    assert (stream["width"], stream["height"]) == thumbnail.EPISODE_SIZES[shape]
    graph = (work / "graph.txt").read_text()
    assert "expansion=none" in graph and graph.count("y_align=baseline") == graph.count("drawtext=")
    # all user text lives in textfiles, never in the filtergraph
    assert "Tuyển" not in graph and "PHÚT" not in graph and "phút" not in graph


# --- AC2: palette / background, partial rebuild, no ffmpeg on an identical rebuild -----------------------------

def test_palettes_and_blur_render_differently_and_ids_match_record(package, photo, tmp_path):
    cfg, _, _, folder, doc = package
    assert set(record.PALETTES) == set(thumbnail.PALETTES)
    digests = {}
    for palette in record.PALETTES:
        for background in record.BACKGROUNDS:
            work = tmp_path / f"{palette}-{background}"
            work.mkdir()
            variant = dict(look(doc, "A"), palette=palette, background=background)
            digests[palette, background] = sha256_file(
                thumbnail.build_theme(work, "landscape", photo, "t.jpg", look=variant))
    assert len(set(digests.values())) == len(digests) == 8
    # the default palette with a plain background is exactly the episode look (same graph as an episode)
    assert thumbnail.PALETTES["nau-vang"]["base"] == (22, 16, 11) and thumbnail.PALETTES["nau-vang"]["glow"] == (70, 45, 18)


def test_changing_palette_rebuilds_only_style_a_and_identical_rebuild_skips_ffmpeg(package, photo):
    cfg, _, _, folder, doc = package
    with_image(cfg, doc, photo)
    calls = []
    def counted(cmd):
        calls.append(cmd)
        if "-filter_complex" in cmd:  # four-corner sample of the portrait
            Path(cmd[-1]).write_bytes(bytes([20] * 12))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return fake_media(cmd)
    first = thumbnail.build(folder, doc, cfg.packaging.asset_dir, run=counted)
    assert len([c for c in calls if "-filter_complex_script" in c]) == 6
    calls.clear()
    assert thumbnail.build(folder, first, cfg.packaging.asset_dir, run=lambda _: pytest.fail("rebuild called ffmpeg")) == first
    changed = deepcopy(first)
    changed["settings"]["palette"] = "do-son"
    keys = {(t["style"], s): thumbnail.key(changed, t, s) for t in changed["thumbnails"] for s in SHAPES}
    old = {(t["style"], s): thumbnail.key(first, t, s) for t in first["thumbnails"] for s in SHAPES}
    assert {k for k in keys if keys[k] != old[k]} == {("A", "landscape"), ("A", "vertical")}
    rebuilt = thumbnail.build(folder, changed, cfg.packaging.asset_dir, run=counted)
    assert len([c for c in calls if "-filter_complex_script" in c]) == 2
    for t, before in zip(rebuilt["thumbnails"], first["thumbnails"]):
        assert (t["files"] == before["files"]) == (t["style"] != "A")
    changed["settings"]["background"] = "blur"
    calls.clear()
    thumbnail.build(folder, changed, cfg.packaging.asset_dir, run=counted)
    assert len([c for c in calls if "-filter_complex_script" in c]) == 2


def test_cache_checks_key_and_file_sha(package):
    cfg, _, _, folder, doc = package
    first = thumbnail.build(folder, doc, cfg.packaging.asset_dir, run=fake_media)
    assert len({f["file"] for t in first["thumbnails"] for f in t["files"].values()}) == 6
    assert all(record.FILE_NAME.fullmatch(f["file"]) for t in first["thumbnails"] for f in t["files"].values())
    cached = thumbnail.build(folder, first, cfg.packaging.asset_dir, run=lambda _: pytest.fail("cache called runner"))
    assert cached == first
    (folder / first["thumbnails"][0]["files"]["vertical"]["file"]).write_bytes(b"corrupt")
    calls = []
    def counted(cmd):
        calls.append(cmd)
        return fake_media(cmd)
    repaired = thumbnail.build(folder, first, cfg.packaging.asset_dir, run=counted)
    assert len(calls) == 1 and repaired == first
    repaired["settings"]["title_lines"] = ["Tuyển tập khai thị", "Buông xả để niệm Phật"]
    calls.clear()
    changed = thumbnail.build(folder, repaired, cfg.packaging.asset_dir, run=counted)
    assert len(calls) == 6
    assert changed["thumbnails"][0]["files"]["landscape"]["file"] != first["thumbnails"][0]["files"]["landscape"]["file"]


@pytest.mark.parametrize("failure_at", [1, 4, 6])
def test_ffmpeg_failure_rolls_back_all_files_and_keeps_tc3(package, failure_at):
    cfg, _, _, folder, doc = package
    tc3 = folder.parent.parent / "abcdef123456-r1.mp4"
    tc3.parent.mkdir(parents=True, exist_ok=True)
    tc3.write_bytes(b"original TC3")
    before = sha256_file(tc3)
    old = thumbnail.build(folder, doc, cfg.packaging.asset_dir, run=fake_media)
    record.write(folder, old)
    snapshot = {p.name: p.read_bytes() for p in folder.iterdir()}
    changed = deepcopy(old)
    changed["settings"]["speaker"] = "Pháp Sư Tịnh Không"
    calls = []
    def failing(cmd):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"partial")
        return subprocess.CompletedProcess(cmd, 1, "", "simulated failure") if len(calls) == failure_at else fake_media(cmd)
    with pytest.raises(RenderError, match="simulated failure"):
        thumbnail.build(folder, changed, cfg.packaging.asset_dir, run=failing)
    assert snapshot == {p.name: p.read_bytes() for p in folder.iterdir()}
    assert sha256_file(tc3) == before


def test_ready_needs_both_shapes_of_the_selected_style(package):
    cfg, _, _, folder, doc = package
    built = thumbnail.build(folder, doc, cfg.packaging.asset_dir, run=fake_media)
    assert thumbnail.ready(folder, built, cfg.packaging.asset_dir)["style"] == "A"
    built["selected"] = "B"
    (folder / built["thumbnails"][1]["files"]["vertical"]["file"]).unlink()
    with pytest.raises(PackageError, match="chưa dựng"):
        thumbnail.ready(folder, built, cfg.packaging.asset_dir)


# --- AC4 (library part): invalid settings are rejected before ffmpeg ----------------------------------------

def run_must_not_start(_):
    pytest.fail("ran ffmpeg")


@pytest.mark.parametrize("change,error", [
    (dict(title_lines=["x" * 41]), PackageError),
    (dict(title_lines=["a", "b", "c", "d"]), PackageError),
    (dict(title_lines=[]), PackageError),
    (dict(title_lines=["Thiền 🧘"]), TextError),
    (dict(title_lines=["W" * 40]), TextError),  # unreadably small even at the smallest accepted size
    (dict(series="Đ" * 100), TextError),
    (dict(palette="khong-co"), PackageError),
    (dict(background="gradient"), PackageError),
    (dict(background="blur"), PackageError),  # style A without an image
    (dict(minutes=0), PackageError),
    (dict(minutes=True), PackageError),
    (dict(focus_x=1.5), PackageError),
    (dict(series="a\nb"), PackageError),
    (dict(speaker="x" * 61), PackageError),
])
def test_invalid_settings_rejected_without_partial_files(package, change, error):
    cfg, _, _, folder, doc = package
    doc["settings"].update(change)
    with pytest.raises(error):
        thumbnail.build(folder, doc, cfg.packaging.asset_dir, run=run_must_not_start)
    assert not folder.exists()  # nothing was staged, not even the directory


def test_record_normalize_compacts_lines(package):
    settings = record.normalize_settings(dict(package[4]["settings"], title_lines=["  Tuyển   tập ", "", unicodedata.normalize("NFD", "Tu hành")]))
    assert settings["title_lines"] == ["Tuyển tập", "Tu hành"] and unicodedata.is_normalized("NFC", settings["title_lines"][1])
    with pytest.raises(PackageError):
        record.normalize_settings(dict(settings, title_lines=["", " "]))


# --- record ---------------------------------------------------------------------------------------------------

def test_new_record_defaults_follow_contract(package):
    cfg, plan, _, _, doc = package
    assert doc["schema_version"] == 2 and doc["selected"] == "A" and doc["state"] == "draft"
    assert [t["style"] for t in doc["thumbnails"]] == ["A", "B", "C"]
    assert all(t["files"] == {"landscape": None, "vertical": None} and t["asset_ids"] == [] for t in doc["thumbnails"])
    s = doc["settings"]
    assert s["title_lines"] == ["Tuyển tập khai thị", "Niệm Phật vãng sanh — buông xả"]
    assert (s["speaker"], s["minutes"], s["palette"], s["background"]) == ("Hòa Thượng Tịnh Không", 21, "nau-vang", "plain")
    assert s["series"] == "" and "headline" not in doc
    thumbnail.check(doc)
    # series = playlist "Tên bộ kinh" (else its title); duration rounds to whole minutes, at least 1
    atomic_write_json(cfg.workspace.dir / "_playlists" / f"{PID}.json",
                      dict(playlist_id=PID, title="Danh sách", series="Thái Thượng Cảm Ứng Thiên", entries=[]))
    assert record.new(cfg, plan, {"sha256": "a" * 64, "duration": 20}, PID)["settings"]["minutes"] == 1
    named = record.new(cfg, plan, {"sha256": "a" * 64, "duration": 29 * 60 + 40}, PID)
    assert named["settings"]["series"] == "Thái Thượng Cảm Ứng Thiên" and named["settings"]["minutes"] == 30
    atomic_write_json(cfg.workspace.dir / "_playlists" / f"{PID}.json", dict(playlist_id=PID, title="Danh sách", entries=[]))
    assert record.new(cfg, plan, {"sha256": "a" * 64}, PID)["settings"]["series"] == "Danh sách"
    # F1: no stored series + long playlist title -> series from a source video's titling header
    vid = "abcdefghijk"
    atomic_write_json(cfg.workspace.dir / "_playlists" / f"{PID}.json", dict(
        playlist_id=PID, entries=[], title="Thái Thượng Cảm Ứng Thiên (128 tập) - Pháp Sư Tịnh Không"))
    atomic_write_json(cfg.workspace.dir / vid / "titles.json",
                      dict(header=dict(fields=dict(series="Thái Thượng Cảm Ứng Thiên", episode="3", speaker="X"))))
    withclips = dict(plan, clips=[dict(episode_id="zzzzzzzzzzz"), dict(episode_id=vid)])
    fitted = record.new(cfg, withclips, {"sha256": "a" * 64}, PID)
    assert fitted["settings"]["series"] == "Thái Thượng Cảm Ứng Thiên"
    thumbnail.check(fitted)
    long = dict(plan, theme={"label": "Niệm Phật vãng sanh là con đường chắc chắn nhất của người tu"})
    label = record.new(cfg, long, {"sha256": "a" * 64})["settings"]["title_lines"][1]
    assert len(label) <= 40 and long["theme"]["label"].startswith(label)


def test_speaker_comes_from_clip_titles(package):
    cfg, plan, meta, _, _ = package
    plan["clips"] = [{"episode_id": "lecture.kt"}]
    atomic_write_json(cfg.workspace.dir / "lecture.kt" / "titles.json", {"header": {"fields": {"speaker": "HT.Tịnh Không"}}})
    assert record.new(cfg, plan, meta)["settings"]["speaker"] == "Hòa Thượng Tịnh Không"


@pytest.mark.parametrize("changed", ["revision", "fingerprint", "tc3"])
def test_record_stale_and_schema_validation(package, changed):
    cfg, plan, meta, folder, doc = package
    doc.update(state="approved", approved_at="now")
    record.write(folder, doc)
    assert record.read(folder) == doc
    plan, meta = deepcopy(plan), deepcopy(meta)
    if changed == "revision":
        plan["revision"] += 1
    elif changed == "fingerprint":
        plan["theme"]["label"] = "Buông xả"
    else:
        meta["sha256"] = "b" * 64
    assert record.status(doc, plan, meta)["state"] == "stale"
    for mutate in (lambda d: d["thumbnails"][0]["files"].update(landscape=dict(file="../../tc3.mp4", key="a" * 64, sha256="a" * 64)),
                   lambda d: d["thumbnails"][0]["files"].update(vertical=dict(file=f"B-vertical-{'a' * 64}.jpg", key="a" * 64, sha256="a" * 64)),
                   lambda d: d["settings"].update(palette="x"), lambda d: d.update(selected="classic"),
                   lambda d: d["thumbnails"].pop()):
        broken = deepcopy(doc)
        mutate(broken)
        atomic_write_json(folder / "package.json", broken)
        with pytest.raises(PackageError):
            record.read(folder)


def test_pkg1_record_reads_as_not_built(package):
    _, _, _, folder, doc = package
    folder.mkdir(parents=True)
    atomic_write_json(folder / "package.json", dict(doc, schema_version=1))
    assert record.read(folder) is None


@pytest.mark.parametrize("approved,license,source", [(False, "CC0", "local"), (True, "", "local"), (True, "CC0", "")])
def test_assets_require_approval_license_and_source(package, tmp_path, approved, license, source):
    cfg, _, _, folder, doc = package
    file = tmp_path / "image.jpg"
    file.write_bytes(b"image")
    entry = assets.add(cfg.packaging.asset_dir, file, kind="image", source="local", license=license, run=fake_media)
    entry.update(approved=approved, source=source)
    atomic_write_json(cfg.packaging.asset_dir / "library.json", {"schema_version": 1, "assets": [entry]})
    doc["thumbnails"][0]["asset_ids"] = [entry["id"]]
    with pytest.raises(PackageError, match="approved.*license"):
        thumbnail.build(folder, doc, cfg.packaging.asset_dir, run=lambda _: pytest.fail("unlicensed render"))


def test_cli_import_provenance_and_config(tmp_path, monkeypatch, capsys):
    images, library = tmp_path / "post-images", tmp_path / "library"
    images.mkdir()
    # Header sufficient for the existing post image sniffer; ffprobe is injected.
    image = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (800).to_bytes(4, "big") * 2
    (images / "speaker.png").write_bytes(image)
    (images / "sources.tsv").write_text("speaker.png\thttps://example.invalid/speaker\n")
    before = {p.name: p.read_bytes() for p in images.iterdir()}
    config = tmp_path / "config.toml"
    config.write_text(f'[post]\nimage_dir="{images}"\n[packaging]\nasset_dir="{library}"\n')
    monkeypatch.setattr(assets, "_run", fake_media)
    assert main(["--config", str(config), "assets", "import-post-images", "--license", "HUMAN LEAD confirmed"]) == 0
    entry = json.loads(capsys.readouterr().out)[0]
    assert entry["source"] == "https://example.invalid/speaker" and not entry["approved"]
    assert main(["--config", str(config), "assets", "approve", entry["id"]]) == 0
    assert assets.usable(library, entry["id"])[0]["approved"]
    assert main(["--config", str(config), "assets", "list"]) == 0
    assert before == {p.name: p.read_bytes() for p in images.iterdir()}
    assert from_dict({"packaging": {"asset_dir": str(library)}}).packaging.asset_dir == library
    assert from_dict({}).packaging.asset_dir == PackagingConfig().asset_dir
    with pytest.raises(PackageError):
        assets.import_post_images(replace(Config(), post=PostConfig(image_dir=images)), license="")


def test_import_post_images_tags_original_number(tmp_path):
    images = tmp_path / "post-images"
    images.mkdir()
    (images / "67.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (800).to_bytes(4, "big") * 2)
    cfg = replace(Config(), post=PostConfig(image_dir=images), packaging=PackagingConfig(tmp_path / "assets"))
    imported = assets.import_post_images(cfg, license="HUMAN LEAD confirmed", run=fake_media)
    assert len(imported) == 1 and imported[0]["tags"] == ["67"]
    assert assets.list_assets(cfg.packaging.asset_dir)[0]["tags"] == ["67"]


@pytest.mark.parametrize("speaker,expected", [(None, "Niệm Phật"), ("HT.Tịnh Không", "Niệm Phật | HT Tịnh Không")])
def test_traditional_title_uses_source_speaker_without_ai(package, speaker, expected):
    cfg, plan, _, _, _ = package
    plan["theme"]["label"] = "Niệm Phật"
    plan["clips"] = [{"episode_id": "lecture.kt"}]
    fields = {"speaker": speaker} if speaker else {}
    atomic_write_json(cfg.workspace.dir / "lecture.kt" / "titles.json", {"header": {"fields": fields}})
    assert record.title_options(cfg, plan) == [*plan["title_options"], expected]
