"""PKG1 AC1–6: real single-frame ffmpeg, otherwise offline injected runners."""
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


@pytest.fixture
def package(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(tmp_path / "work"), packaging=PackagingConfig(tmp_path / "assets"),
                 render=RenderConfig(output_dir=tmp_path / "output"))
    plan = dict(plan_id="abcdef123456", revision=1, title="Niệm Phật vãng sanh", title_options=["Buông xả để niệm Phật"],
                theme={"label": "Niệm Phật vãng sanh — buông xả"}, clips=[])
    meta = {"sha256": "a" * 64}
    folder = record.directory(cfg.render.output_dir, PID, plan["plan_id"], 1)
    return cfg, plan, meta, folder, record.new(cfg, plan, meta)


def fake_media(cmd):
    if cmd[0] == "ffprobe":
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"streams": [
            {"codec_type": "video", "width": 800, "height": 800}], "format": {}}), "")
    Path(cmd[-1]).write_bytes(b"jpeg:" + Path(cmd[-1]).name.encode())
    return subprocess.CompletedProcess(cmd, 0, "", "")


@pytest.mark.parametrize("with_image", [False, True])
def test_vietnamese_three_real_templates_and_safe_area(package, with_image, tmp_path):
    cfg, _, _, folder, doc = package
    if with_image:
        image = tmp_path / "speaker.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x3b5670:s=800x800",
                        "-frames:v", "1", "-threads", "1", str(image)], check=True)
        entry = assets.add(cfg.packaging.asset_dir, image, kind="image", source="local:test", license="CC0")
        assets.approve(cfg.packaging.asset_dir, entry["id"])
        for t in doc["thumbnails"]:
            t["asset_ids"] = [entry["id"]]
    doc["headline"] = unicodedata.normalize("NFD", doc["headline"])
    assert not Font(thumbnail.FONT).missing(doc["headline"])
    result = thumbnail.build(folder, doc, cfg.packaging.asset_dir)
    assert len({t["sha256"] for t in result["thumbnails"]}) == 3
    samples = []
    for t in result["thumbnails"]:
        path = folder / t["file"]
        assert path.read_bytes().startswith(b"\xff\xd8")
        assert 0 < path.stat().st_size <= thumbnail.MAX_BYTES
        stream = probe_media(path, _run)["video"]
        assert (stream["width"], stream["height"]) == (1280, 720)
        data = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24",
                               "-threads", "1", "-"], capture_output=True, check=True).stdout
        # Text contrast appears in its intended region; duration corner stays background-only.
        color = (41, 25, 14) if t["template"] == "classic" else (255, 255, 255)
        def ink(x0, y0, x1, y1):
            return sum(all(abs(data[(y * 1280 + x) * 3 + c] - color[c]) < 25 for c in range(3))
                       for y in range(y0, y1, 3) for x in range(x0, x1, 3))
        assert ink(60, 100, 1190, 610) > 50
        assert ink(1060, 640, 1280, 720) == 0
        samples.append(data[(680 * 1280 + 30) * 3:(680 * 1280 + 30) * 3 + 3])
        fitted = thumbnail.fit(doc["headline"], thumbnail.TEMPLATES[t["template"]])
        assert len(fitted.lines) <= 3 and unicodedata.is_normalized("NFC", " ".join(fitted.lines))
    assert len(set(samples)) == 3


@pytest.mark.parametrize("headline", ["niệm Phật " * 80, "x" * 250, "Thiền 🧘"])
def test_headline_rejected_without_partial_files(package, headline):
    cfg, _, _, folder, doc = package
    doc["headline"] = headline
    with pytest.raises(TextError):
        thumbnail.build(folder, doc, cfg.packaging.asset_dir, run=lambda _: pytest.fail("ran ffmpeg"))
    assert not list(folder.iterdir())


def test_cache_checks_key_and_file_sha(package):
    cfg, _, _, folder, doc = package
    first = thumbnail.build(folder, doc, cfg.packaging.asset_dir, run=fake_media)
    cached = thumbnail.build(folder, first, cfg.packaging.asset_dir, run=lambda _: pytest.fail("cache called runner"))
    assert cached == first
    (folder / first["thumbnails"][0]["file"]).write_bytes(b"corrupt")
    calls = []
    def counted(cmd):
        calls.append(cmd)
        return fake_media(cmd)
    repaired = thumbnail.build(folder, first, cfg.packaging.asset_dir, run=counted)
    assert len(calls) == 1
    assert repaired == first
    repaired["headline"] = "Buông xả để niệm Phật"
    calls.clear()
    changed = thumbnail.build(folder, repaired, cfg.packaging.asset_dir, run=counted)
    assert len(calls) == 3
    assert changed["thumbnails"][0]["file"] != first["thumbnails"][0]["file"]


@pytest.mark.parametrize("failure_at", [1, 2, 3])
def test_ffmpeg_failure_rolls_back_all_templates_and_keeps_tc3(package, failure_at):
    cfg, _, _, folder, doc = package
    tc3 = folder.parent.parent / "abcdef123456-r1.mp4"
    tc3.parent.mkdir(parents=True, exist_ok=True)
    tc3.write_bytes(b"original TC3")
    before = sha256_file(tc3)
    old = thumbnail.build(folder, doc, cfg.packaging.asset_dir, run=fake_media)
    record.write(folder, old)
    snapshot = {p.name: p.read_bytes() for p in folder.iterdir()}
    changed = deepcopy(old)
    changed["headline"] = "Buông xả để niệm Phật"
    calls = []
    def failing(cmd):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"partial")
        return subprocess.CompletedProcess(cmd, 1, "", "simulated failure") if len(calls) == failure_at else fake_media(cmd)
    with pytest.raises(RenderError, match="simulated failure"):
        thumbnail.build(folder, changed, cfg.packaging.asset_dir, run=failing)
    assert snapshot == {p.name: p.read_bytes() for p in folder.iterdir()}
    assert sha256_file(tc3) == before


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
    broken = deepcopy(doc)
    broken["thumbnails"][0].update(file="../../tc3.mp4", key="a" * 64, sha256="a" * 64)
    atomic_write_json(folder / "package.json", broken)
    with pytest.raises(PackageError):
        record.read(folder)


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
