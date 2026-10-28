"""VERT1: deterministic vertical headers before titling, reuse afterwards, and playlist eligibility."""

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short.hashing import config_hash
from auto_short.render import full
from auto_short.render.stage import RenderError
from auto_short.titling.logic import TitlingError, resolve_header
from auto_short.titling.playlist import playlist_header
from auto_short.titling.stage import resolve_workspace_header, run_titling, used_config
from auto_short.web import episodes, prepared
from auto_short.workspace import Workspace, atomic_write_json

from render_helpers import HEADER
from test_web_vertical_cp832 import (PL, VID, make_ep, seed_playlist_for, seed_playlist_many,
                                     tcfg, write_hd)  # noqa: F401 (shared fixture)
from titling_helpers import FakeClient, VIDEO_TITLE, make_titling_episode
from web_helpers import login, web_client


@pytest.fixture
def prepared_episode(tcfg):
    d = make_ep(tcfg, height=480, with_titles=False, render_status="pending")
    write_hd(tcfg, VID)
    ws = Workspace(tcfg.workspace.dir, VID)
    manifest = ws.load_manifest()
    for stage in ("selection", "titling", "render"):
        manifest["stages"][stage]["status"] = "pending"
    ws.save_manifest(manifest)
    shutil.rmtree(Path(tcfg.render.output_dir) / VID)
    atomic_write_json(d / "metadata.json", {"title": VIDEO_TITLE, "youtube": {"id": VID}, "height": 480})
    prepared.mark(tcfg, VID)
    return d


@pytest.fixture
def media_runner():
    """Fake ffprobe/ffmpeg while exercising the real layout, key, file publication and output checks."""
    encodes = []

    def run(cmd):
        path = Path(cmd[-1])
        if cmd[0] == "ffprobe":
            output = path.name.endswith(".part")
            doc = {"format": {"duration": "2"}, "streams": [
                {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p",
                 "width": 1080 if output else 1280, "height": 1920 if output else 720,
                 "r_frame_rate": "25/1", "avg_frame_rate": "25/1", "duration": "2", "nb_frames": "50"},
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000",
                 "channels": 2, "duration": "2"}]}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(doc), "")
        assert cmd[0] == "ffmpeg"
        encodes.append(cmd)
        path.write_bytes(b"vertical")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return run, encodes


@pytest.mark.parametrize("source", ["patterns", "playlist"])
def test_ac1_vertical_without_titles(tcfg, prepared_episode, media_runner, source):
    d = prepared_episode
    if source == "playlist":
        seed_playlist_for(tcfg, VID)
        pl_path = Path(tcfg.workspace.dir) / "_playlists" / f"{PL}.json"
        doc = json.loads(pl_path.read_text())
        doc["series"] = "Thập Thiện Nghiệp Đạo Kinh"
        doc["entries"][0]["episode"] = "9"
        atomic_write_json(pl_path, doc)
        atomic_write_json(d / "metadata.json", {"title": "Không khớp mẫu", "youtube": {"id": VID}})
    metadata = json.loads((d / "metadata.json").read_text())
    expected = resolve_header(tcfg.titling.header, metadata["title"],
                              playlist=lambda: playlist_header(tcfg.workspace.dir, VID))
    before = (d / "manifest.json").read_bytes()
    run, encodes = media_runner
    result = full.run_vertical(VID, tcfg, run=run)
    assert result.ran and result.path.is_file() and len(encodes) == 1
    meta = full.read_meta(tcfg, VID)
    top, speaker = full.split_header(expected["lines"], expected["fields"]["speaker"])
    # vertical.json stores fitted display lines; fitting may wrap the deterministic top text.
    assert " ".join(meta["header"]) == " ".join(top) and meta["speaker"] == [speaker]
    assert full.current(tcfg, VID)
    assert not (d / "titles.json").exists() and not (d / "titling_log.json").exists()
    assert (d / "manifest.json").read_bytes() == before
    assert expected["fields"]["series"]  # AC4, both sources: series prefix + episode number like a titled episode
    assert episodes.video_download_name(tcfg, VID, "Doc") == episodes.video_name(
        expected["fields"]["episode"], VID, "Doc", series=expected["fields"]["series"])
    assert "Tập9_Doc.mp4" in episodes.video_download_name(tcfg, VID, "Doc")


def test_ac2_titling_keeps_header_hash_and_vertical_key(tcfg, media_runner):
    ws = make_titling_episode(tcfg.workspace.dir)
    write_hd(tcfg, ws.episode_id)
    run, encodes = media_runner
    full.run_vertical(ws.episode_id, tcfg, run=run)
    before = full.read_meta(tcfg, ws.episode_id)
    client = FakeClient()
    assert run_titling(ws.episode_id, tcfg, client=client).ran
    titles = json.loads((ws.dir / "titles.json").read_text())
    assert titles["header"] == resolve_header(tcfg.titling.header, VIDEO_TITLE)
    assert titles["header"]["lines"] == HEADER
    assert ws.load_manifest()["stages"]["titling"]["config_hash"] == config_hash(used_config(tcfg, HEADER))
    assert full.current(tcfg, ws.episode_id)
    assert not full.run_vertical(ws.episode_id, tcfg, run=run).ran
    assert full.read_meta(tcfg, ws.episode_id) == before and len(encodes) == 1


def test_helper_preserves_cli_precedence_and_metadata_video_id(tcfg, prepared_episode):
    # The workspace id differs from metadata.youtube.id (as for a .kt workspace).
    seed_playlist_for(tcfg, "bbbbbbbbbb2")
    path = Path(tcfg.workspace.dir) / "_playlists" / f"{PL}.json"
    doc = json.loads(path.read_text())
    doc["series"] = "Tên từ bộ kinh"
    atomic_write_json(path, doc)
    meta = {"title": "Không khớp mẫu", "youtube": {"id": "bbbbbbbbbb2"}}
    atomic_write_json(prepared_episode / "metadata.json", meta)
    assert resolve_workspace_header(tcfg, prepared_episode)["fields"]["series"] == doc["series"]
    cli = {"speaker": "Người giảng", "series": "Tên nhập tay", "episode": "37"}
    expected = resolve_header(tcfg.titling.header, meta["title"], cli,
                              playlist=lambda: playlist_header(tcfg.workspace.dir, "bbbbbbbbbb2"))
    assert resolve_workspace_header(tcfg, prepared_episode, cli=cli) == expected
    run_titling_ws = make_titling_episode(Path(tcfg.workspace.dir) / "cli")
    cfg = replace(tcfg, workspace=replace(tcfg.workspace, dir=run_titling_ws.dir.parent))
    run_titling(run_titling_ws.episode_id, cfg, client=FakeClient(), **cli)
    assert json.loads((run_titling_ws.dir / "titles.json").read_text())["header"] == expected


@pytest.mark.parametrize("metadata", [{"title": "Không khớp mẫu"}, None, []])
def test_ac3_unresolved_header_is_render_error_and_name_falls_back(tcfg, prepared_episode, media_runner, metadata):
    path = prepared_episode / "metadata.json"
    if metadata is None:
        path.unlink()
    else:
        atomic_write_json(path, metadata)
    run, encodes = media_runner
    with pytest.raises(RenderError, match="Tên bộ kinh.*mẫu tiêu đề") as exc:
        full.run_vertical(VID, tcfg, run=run)
    assert isinstance(exc.value.__cause__, TitlingError)
    assert not full.vertical_path(tcfg, VID).exists() and not encodes
    assert not (prepared_episode / "titles.json").exists()
    assert episodes.video_download_name(tcfg, VID, "Doc") == f"{VID}_Doc.mp4"


def test_existing_titles_keep_manual_header_and_download_name(tcfg, prepared_episode, media_runner):
    header = {"lines": ["Người giảng", "Tên nhập tay (tập 37)"],
              "fields": {"speaker": "Người giảng", "series": "Tên nhập tay", "episode": "37"}}
    atomic_write_json(prepared_episode / "titles.json", {"header": header})
    (prepared_episode / "metadata.json").unlink()  # existing titles never need the fallback
    run, _ = media_runner
    full.run_vertical(VID, tcfg, run=run)
    assert " ".join(full.read_meta(tcfg, VID)["header"]) == header["lines"][1]
    assert full.read_meta(tcfg, VID)["speaker"] == ["Người giảng"]
    assert episodes.video_download_name(tcfg, VID, "Doc") == "Tên nhập tay_Tập37_Doc.mp4"


def test_ac5_playlist_queues_prepared_and_rendered_skips_new_and_unfinished(tcfg, prepared_episode):
    new, rendered, incomplete, failed = "bbbbbbbbbb2", "cccccccccc3", "dddddddddd4", "eeeeeeeeee5"
    make_ep(tcfg, rendered)
    make_ep(tcfg, incomplete, render_status="pending")
    make_ep(tcfg, failed, render_status="failed")
    seed_playlist_many(tcfg, [VID, new, rendered, incomplete, failed])
    c = web_client(tcfg)  # no lifespan: queued jobs do not run
    login(c)
    entries = {e["video_id"]: e for e in c.get(f"/api/playlists/{PL}").json()["entries"]}
    assert entries[VID]["state"] == "prepared" and entries[VID]["vertical"]["status"] == "todo"
    assert entries[new]["state"] == "new"
    assert entries[rendered]["state"] == "rendered"
    assert entries[incomplete]["state"] == "incomplete" and entries[failed]["state"] == "failed"
    response = c.post(f"/api/playlists/{PL}/vertical")
    assert response.status_code == 202
    body = response.json()
    assert body["queued"] == 2 and body["queued_ids"] == [VID, rendered]
    reasons = {e["episode_id"]: e["reason"] for e in body["skipped"]}
    assert reasons == {new: "chưa tải — bấm Chuẩn bị + HD trước",
                       incomplete: "chưa xong Short", failed: "chưa xong Short"}
    assert c.post(f"/api/playlists/{PL}/vertical").json()["queued"] == 0
