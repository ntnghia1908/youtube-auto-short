"""PKG2 AC1–4/6: real JPEG compositions, otherwise offline injected runners."""
import json
import subprocess
import unicodedata
from pathlib import Path

import pytest

from auto_short.config import Config, PackagingConfig, RenderConfig, WorkspaceConfig
from auto_short.hashing import sha256_file
from auto_short.packaging import PackageError, assets, episode, thumbnail
from auto_short.render.stage import _run, probe_media
from auto_short.render.text import Font
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


@pytest.mark.parametrize("with_image", [False, True])
def test_real_episode_jpegs_dimensions_vietnamese_and_two_line_series(episodes, tmp_path, with_image):
    cfg = episodes
    if with_image:
        image = tmp_path / "portrait.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x3b5670:s=800x800",
                        "-frames:v", "1", "-threads", "1", str(image)], check=True)
        asset = assets.add(cfg.packaging.asset_dir, image, kind="image", source="local:test", license="CC0")
        assets.approve(cfg.packaging.asset_dir, asset["id"])
    path = cfg.workspace.dir / IDS[0] / "titles.json"
    doc = json.loads(path.read_text())
    doc["header"]["fields"]["series"] = unicodedata.normalize("NFD", SERIES)
    atomic_write_json(path, doc)
    summary = episode.build_playlist(cfg, PID)
    assert summary == dict(built=2, reused=0, skipped=[])
    assert not Font(thumbnail.FONT).missing(SERIES + " TẬP 102 HT. Tịnh Không")
    for ident in IDS:
        doc = episode.read(cfg, ident)
        assert doc["schema_version"] == 1 and doc["header"]["series"] == SERIES
        assert set(doc["files"]) == ({"landscape", "vertical"} if ident == IDS[0] else {"landscape"})
        for shape, entry in doc["files"].items():
            image = episode.directory(cfg, ident) / entry["file"]
            assert image.read_bytes().startswith(b"\xff\xd8") and image.stat().st_size <= thumbnail.MAX_BYTES
            stream = probe_media(image, _run)["video"]
            assert (stream["width"], stream["height"]) == thumbnail.EPISODE_SIZES[shape]
            lines = thumbnail.episode_text(doc["header"], shape)
            assert 1 <= len(lines) - 2 <= 2
            assert lines[-2][0] == "TẬP " + doc["header"]["episode"]
            assert lines[-1][0] == "HT. Tịnh Không"
            assert sha256_file(image) == entry["sha256"]


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


def test_rotation_approved_assets_and_override_only_rebuilds_one_episode(episodes, tmp_path):
    cfg = episodes
    pool = add_images(cfg, tmp_path)
    episode.build_playlist(cfg, PID, run=fake_media)
    first, second = [episode.read(cfg, ident) for ident in IDS]
    assert first["asset_id"] == pool[101 % 2] and second["asset_id"] == pool[102 % 2]
    before = {p.name: p.read_bytes() for p in episode.directory(cfg, IDS[0]).iterdir()}
    episode.set_override(cfg, IDS[1], first["asset_id"])
    calls = []
    def counted(cmd):
        calls.append(cmd)
        return fake_media(cmd)
    assert episode.build_playlist(cfg, PID, video_id=IDS[1], run=counted)["built"] == 1
    assert len(calls) == 1
    assert before == {p.name: p.read_bytes() for p in episode.directory(cfg, IDS[0]).iterdir()}
    assert episode.read(cfg, IDS[1])["override"] == first["asset_id"]
    episode.set_override(cfg, IDS[1], None)
    episode.build_playlist(cfg, PID, run=fake_media)
    assert episode.read(cfg, IDS[1])["asset_id"] == second["asset_id"]
    library = assets.list_assets(cfg.packaging.asset_dir)
    library[0]["approved"] = False
    (cfg.packaging.asset_dir / library[1]["file"]).write_bytes(b"tamper")
    atomic_write_json(cfg.packaging.asset_dir / "library.json", dict(schema_version=1, assets=library))
    assert episode.images(cfg) == []
    with pytest.raises(PackageError):
        episode.set_override(cfg, IDS[1], library[0]["id"])


def test_cache_sha_header_key_and_removal_of_old_files(episodes):
    cfg = episodes
    episode.build_playlist(cfg, PID, run=fake_media)
    assert episode.build_playlist(cfg, PID, run=lambda _: pytest.fail("cache called ffmpeg")) == dict(built=0, reused=2, skipped=[])
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
            episode.build_episode(cfg, IDS[0], run=fake_media)
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
