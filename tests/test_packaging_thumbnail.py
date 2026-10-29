"""PKG2 byte-identical graph baselines and the retained local asset CLI."""
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short.config import Config, PackagingConfig, PostConfig, from_dict
from auto_short.packaging import PackageError, assets, thumbnail
from auto_short.packaging.__main__ import main


def fake_media(cmd):
    if cmd[0] == "ffprobe":
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"streams": [
            {"codec_type": "video", "width": 800, "height": 800}], "format": {}}), "")
    Path(cmd[-1]).write_bytes(b"jpeg:" + Path(cmd[-1]).name.encode())
    return subprocess.CompletedProcess(cmd, 0, "", "")


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
