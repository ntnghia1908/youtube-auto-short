import hashlib
import json
import os

import pytest

from auto_short import hashing
from auto_short.ingest import IngestError, run_ingest
from auto_short.workspace import Workspace


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(result) -> dict:
    return json.loads((result.workspace / "manifest.json").read_text())


def test_local_ingest_creates_artifacts(video, cfg):
    result = run_ingest(str(video), cfg)
    sha = _sha(video)

    assert result.ran
    assert result.episode_id == f"bai-giang-tap-9-{sha[:12]}"
    assert result.workspace == cfg.workspace.dir / result.episode_id
    # D4: local source is referenced, never copied into the workspace.
    assert sorted(p.name for p in result.workspace.iterdir()) == ["manifest.json", "metadata.json"]

    meta = json.loads((result.workspace / "metadata.json").read_text())
    assert meta["episode_id"] == result.episode_id
    assert meta["source"] == {"kind": "local", "uri": str(video), "path": str(video),
                              "sha256": sha, "size": video.stat().st_size}
    assert meta["duration"] == pytest.approx(2.0, abs=0.1)
    assert (meta["width"], meta["height"], meta["fps"]) == (320, 240, 25.0)
    assert (meta["video_codec"], meta["audio_codec"]) == ("h264", "aac")
    assert "youtube" not in meta

    m = _manifest(result)
    assert m["schema_version"] == 1
    assert m["episode_id"] == result.episode_id
    assert m["source"]["mtime_ns"] == video.stat().st_mtime_ns
    ingest = m["stages"]["ingest"]
    assert ingest["status"] == "done"
    assert ingest["artifacts"] == ["metadata.json"]
    assert ingest["inputs"] == [{"path": str(video), "sha256": sha}]
    assert ingest["config_hash"] == hashing.config_hash({})
    assert ingest["error"] is None and ingest["started_at"] and ingest["finished_at"]


def test_second_run_skips_without_rehash(video, cfg, monkeypatch, caplog):
    first = run_ingest(str(video), cfg)
    meta_before = _sha(first.workspace / "metadata.json")
    manifest_before = (first.workspace / "manifest.json").read_bytes()

    calls = []
    real = hashing.sha256_file
    monkeypatch.setattr(hashing, "sha256_file", lambda p: calls.append(p) or real(p))
    probes = []
    monkeypatch.setattr("auto_short.ingest.probe.probe", lambda p, **k: probes.append(p))

    with caplog.at_level("INFO", logger="auto_short"):
        second = run_ingest(str(video), cfg)

    assert not second.ran
    assert second.episode_id == first.episode_id
    assert "ingest: skip (up to date)" in caplog.text
    assert calls == [] and probes == []
    assert _sha(first.workspace / "metadata.json") == meta_before
    assert (first.workspace / "manifest.json").read_bytes() == manifest_before


def test_touch_rehashes_but_skips_when_content_same(video, cfg, monkeypatch):
    first = run_ingest(str(video), cfg)
    st = video.stat()
    os.utime(video, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

    calls = []
    real = hashing.sha256_file
    monkeypatch.setattr(hashing, "sha256_file", lambda p: calls.append(p) or real(p))
    second = run_ingest(str(video), cfg, episode_id=first.episode_id)

    assert len(calls) == 1  # (size, mtime) changed -> hash again
    assert not second.ran   # same content -> still up to date

    calls.clear()
    assert not run_ingest(str(video), cfg).ran
    assert calls == []  # cache refreshed with the new mtime


def test_changed_content_reruns_and_marks_downstream_stale(video, cfg, _video_template, tmp_path):
    first = run_ingest(str(video), cfg, episode_id="ep1")
    ws = Workspace(cfg.workspace.dir, "ep1")
    # Simulate a later stage that completed on top of this ingest.
    m = ws.load_manifest()
    m["stages"]["transcript"] = {"status": "done", "artifacts": [], "inputs": [], "config_hash": "x",
                                 "started_at": None, "finished_at": None, "error": None}
    ws.save_manifest(m)

    from conftest import make_video
    make_video(video, seconds=3, freq=880)  # new content, same path
    second = run_ingest(str(video), cfg, episode_id="ep1")

    assert second.ran
    m = ws.load_manifest()
    assert m["stages"]["ingest"]["inputs"][0]["sha256"] == _sha(video)
    assert m["stages"]["transcript"]["status"] == "stale"
    meta = json.loads((first.workspace / "metadata.json").read_text())
    assert meta["duration"] == pytest.approx(3.0, abs=0.1)


def test_changed_content_without_explicit_id_gets_new_episode(video, cfg):
    first = run_ingest(str(video), cfg)
    from conftest import make_video
    make_video(video, seconds=3, freq=880)
    second = run_ingest(str(video), cfg)
    assert second.ran and second.episode_id != first.episode_id


def test_force_reruns(video, cfg, caplog):
    first = run_ingest(str(video), cfg)
    meta_before = _sha(first.workspace / "metadata.json")
    with caplog.at_level("INFO", logger="auto_short"):
        again = run_ingest(str(video), cfg, force=True)
    assert again.ran
    assert "ingest: run (--force)" in caplog.text
    assert _sha(first.workspace / "metadata.json") == meta_before  # deterministic output


def test_missing_artifact_reruns(video, cfg):
    first = run_ingest(str(video), cfg)
    (first.workspace / "metadata.json").unlink()
    assert run_ingest(str(video), cfg).ran
    assert (first.workspace / "metadata.json").is_file()


def test_missing_file_without_id_errors_without_workspace(tmp_path, cfg):
    with pytest.raises(IngestError, match="source file not found"):
        run_ingest(str(tmp_path / "nope.mp4"), cfg)
    assert not cfg.workspace.dir.exists()


def test_missing_file_with_id_records_failure(tmp_path, cfg):
    with pytest.raises(IngestError, match="source file not found"):
        run_ingest(str(tmp_path / "nope.mp4"), cfg, episode_id="ep-missing")
    m = Workspace(cfg.workspace.dir, "ep-missing").load_manifest()
    assert m["stages"]["ingest"]["status"] == "failed"
    assert "source file not found" in m["stages"]["ingest"]["error"]


def test_not_a_video_fails_cleanly(tmp_path, cfg):
    bogus = tmp_path / "notes.mp4"
    bogus.write_text("this is not a video\n")
    with pytest.raises(IngestError, match="ingest failed: ffprobe cannot read"):
        run_ingest(str(bogus), cfg)
    (ws_dir,) = cfg.workspace.dir.iterdir()
    assert sorted(p.name for p in ws_dir.iterdir()) == ["manifest.json"]  # no partial artifact
    m = json.loads((ws_dir / "manifest.json").read_text())
    assert m["stages"]["ingest"]["status"] == "failed"
    assert m["stages"]["ingest"]["artifacts"] == []
    assert "ffprobe" in m["stages"]["ingest"]["error"]


def test_audio_only_is_not_a_video(tmp_path, cfg):
    import subprocess
    audio = tmp_path / "talk.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", str(audio)], check=True)
    with pytest.raises(IngestError, match="no video stream"):
        run_ingest(str(audio), cfg)


def test_failed_rerun_removes_previous_artifacts(video, cfg):
    run_ingest(str(video), cfg, episode_id="ep2")
    video.write_text("corrupted\n")
    with pytest.raises(IngestError):
        run_ingest(str(video), cfg, episode_id="ep2")
    ws = Workspace(cfg.workspace.dir, "ep2")
    assert not (ws.dir / "metadata.json").exists()
    assert ws.load_manifest()["stages"]["ingest"]["status"] == "failed"
    assert video.exists()  # the referenced source is never deleted


def test_ffprobe_missing(video, cfg, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(IngestError, match="not found on PATH"):
        run_ingest(str(video), cfg)


def test_invalid_episode_id(video, cfg):
    with pytest.raises(IngestError, match="invalid episode id"):
        run_ingest(str(video), cfg, episode_id="../escape")
