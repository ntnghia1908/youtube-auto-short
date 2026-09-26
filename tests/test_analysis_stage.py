"""Analysis stage: artifacts/schema, manifest inputs, resume/stale/force, failures (AC1, AC5, AC6)."""

import hashlib
import json
import shutil
from dataclasses import replace

import pytest

from auto_short.analysis import AnalysisError, run_analysis
from auto_short.analysis.stage import used_config
from auto_short.cli import main
from auto_short.hashing import canonical_json, config_hash, sha256_file
from analysis_helpers import REAL, FakeAnalyzer, lecture, make_analysis_episode, write_transcript
from transcript_helpers import manifest_of

ARTIFACTS = ["shots.json", "silences.json", "candidates.json"]


def _load(ws, name):
    return json.loads((ws.dir / name).read_text(encoding="utf-8"))


def _bytes(ws):
    return {n: (ws.dir / n).read_bytes() for n in ARTIFACTS}


def _cfg(cfg, **analysis):
    return replace(cfg, analysis=replace(cfg.analysis, **analysis))


# --- AC1 / A10: artifacts and schema ----------------------------------------------------------------

def test_run_writes_three_artifacts_with_schema(cfg):
    ws = make_analysis_episode(cfg.workspace.dir)
    fake = FakeAnalyzer()
    result = run_analysis("rbjfCfFq3Dk", cfg, analyzer=fake)
    assert result.ran and result.path == ws.dir / "candidates.json"
    assert fake.calls == ["shots", "silences"]

    shots = _load(ws, "shots.json")
    assert list(shots) == ["schema_version", "episode_id", "media_sha256", "method", "duration", "changes", "shots"]
    assert shots["media_sha256"] == "ab" * 32 and shots["duration"] == 3622.001
    assert shots["method"] == {"tool": "ffmpeg", "filter": "scene", "threshold": 0.3, "scale_width": 320}
    assert shots["changes"] == REAL["shot_changes"] and len(shots["shots"]) == 15
    assert shots["shots"][0] == {"id": "h0001", "start": 0.0, "end": 21.321}
    assert shots["shots"][-1]["end"] == 3622.001

    sil = _load(ws, "silences.json")
    assert list(sil) == ["schema_version", "episode_id", "media_sha256", "method", "stats", "silences"]
    assert sil["method"] == {"tool": "ffmpeg", "filter": "silencedetect", "noise_db": -45.0, "min_seconds": 0.3}
    assert {"start": 19.667, "end": 22.875} in sil["silences"]
    assert {"start": 65.148, "end": 77.672} in sil["silences"]  # merged in the stage
    assert sil["stats"]["count"] == len(sil["silences"])
    assert sil["stats"]["total_seconds"] == round(sum(s["end"] - s["start"] for s in sil["silences"]), 3)

    doc = _load(ws, "candidates.json")
    assert list(doc) == ["schema_version", "episode_id", "transcript_sha256", "shots_sha256", "silences_sha256",
                         "params", "content", "stats", "units", "candidates"]
    assert doc["transcript_sha256"] == _load(ws, "transcript.json")["transcript_sha256"]
    assert doc["shots_sha256"] == hashlib.sha256(canonical_json(shots).encode()).hexdigest()
    assert doc["silences_sha256"] == hashlib.sha256(canonical_json(sil).encode()).hexdigest()
    assert list(doc["params"]) == ["min_boundary_silence", "align_tolerance", "hard_break_silence", "max_pause",
                                   "boundary_pad", "min_duration", "max_duration", "target_min", "target_max",
                                   "shot_guard", "intro_window", "intro_min_silence", "outro_window"]
    assert doc["params"]["max_pause"] == 1.0 and doc["params"]["min_boundary_silence"] == 3.0
    assert doc["content"] == {"start": 22.875, "end": 3554.6,
                              "start_reason": "intro: non_speech s00001 + silence 19.667-22.875",
                              "end_reason": "outro: non_speech s00815"}
    assert list(doc["stats"]) == ["units", "candidates", "in_target", "content_seconds", "content_seconds_trimmed"]
    assert doc["stats"]["content_seconds"] == 3531.725
    assert doc["stats"]["candidates"] == len(doc["candidates"]) == result.candidates > 0
    assert list(doc["units"][0]) == ["id", "start", "end", "segment_ids", "text", "words", "break_before",
                                     "break_after"]
    assert list(doc["candidates"][0]) == ["id", "source_start", "source_end", "source_duration", "duration",
                                          "in_target", "unit_ids", "segment_ids", "words", "trims", "boundary",
                                          "shot_ids", "shot_changes"]

    entry = manifest_of(ws)["stages"]["analysis"]
    assert entry["status"] == "done" and entry["error"] is None and entry["artifacts"] == ARTIFACTS
    assert entry["inputs"] == [
        {"path": "metadata.json", "sha256": sha256_file(ws.dir / "metadata.json")},
        {"path": "transcript.json", "sha256": sha256_file(ws.dir / "transcript.json")},
        {"path": "source.mp4", "sha256": sha256_file(ws.dir / "source.mp4")},
    ]
    assert entry["config_hash"] == config_hash(used_config(cfg))
    assert set(used_config(cfg)) == {f"analysis.{k}" for k in cfg.analysis.__dataclass_fields__}


def test_no_shot_change_gives_one_shot(cfg):
    segments, silences, duration = lecture(8)
    ws = make_analysis_episode(cfg.workspace.dir, segments=segments, duration=duration)
    run_analysis("rbjfCfFq3Dk", cfg, analyzer=FakeAnalyzer(changes=[], silences=silences))
    shots = _load(ws, "shots.json")
    assert shots["changes"] == [] and shots["shots"] == [{"id": "h0001", "start": 0.0, "end": duration}]
    doc = _load(ws, "candidates.json")
    assert doc["content"]["start_reason"] == "no intro detected" and doc["content"]["end"] == duration
    assert doc["candidates"] and all(c["shot_ids"] == ["h0001"] for c in doc["candidates"])


# --- AC6: resume / stale / force --------------------------------------------------------------------

def test_rerun_skips_byte_identical_and_reruns_on_changes(cfg, caplog):
    ws = make_analysis_episode(cfg.workspace.dir)
    fake = FakeAnalyzer()
    assert run_analysis("rbjfCfFq3Dk", cfg, analyzer=fake).ran
    first, manifest_before = _bytes(ws), manifest_of(ws)

    caplog.set_level("INFO", logger="auto_short")
    again = run_analysis("rbjfCfFq3Dk", cfg, analyzer=fake)
    assert not again.ran and "analysis: skip (up to date)" in caplog.text
    assert _bytes(ws) == first and manifest_of(ws) == manifest_before
    assert fake.calls == ["shots", "silences"]  # detector not called on skip

    # any [analysis] key reruns (detection or candidate param)
    assert run_analysis("rbjfCfFq3Dk", _cfg(cfg, scene_threshold=0.4), analyzer=fake).ran
    assert run_analysis("rbjfCfFq3Dk", _cfg(cfg, max_pause=0.7), analyzer=fake).ran
    assert _load(ws, "candidates.json")["params"]["max_pause"] == 0.7
    assert run_analysis("rbjfCfFq3Dk", cfg, analyzer=fake).ran  # back to the default config
    assert _bytes(ws) == first

    # --force always reruns; output byte-identical
    assert run_analysis("rbjfCfFq3Dk", cfg, force=True, analyzer=fake).ran
    assert _bytes(ws) == first


def test_transcript_rerun_makes_analysis_stale_then_rerun(cfg):
    ws = make_analysis_episode(cfg.workspace.dir)
    assert run_analysis("rbjfCfFq3Dk", cfg, analyzer=FakeAnalyzer()).ran
    manifest = manifest_of(ws)
    manifest["stages"]["selection"] = dict(manifest["stages"]["analysis"], artifacts=[])
    ws.save_manifest(manifest)

    # a new transcript.json + analysis marked stale (as run_stage of transcript does)
    doc = _load(ws, "transcript.json")
    write_transcript(ws, [dict(s, text=s["text"] + " ạ") if s["id"] == "s00007" else s for s in doc["segments"]])
    manifest = manifest_of(ws)
    manifest["stages"]["analysis"]["status"] = "stale"
    ws.save_manifest(manifest)

    assert run_analysis("rbjfCfFq3Dk", cfg, analyzer=FakeAnalyzer()).ran
    stages = manifest_of(ws)["stages"]
    assert stages["analysis"]["status"] == "done" and stages["selection"]["status"] == "stale"
    assert _load(ws, "candidates.json")["units"][0]["text"].endswith(" ạ")

    # transcript content change alone (input hash) also reruns
    write_transcript(ws, doc["segments"])
    assert run_analysis("rbjfCfFq3Dk", cfg, analyzer=FakeAnalyzer()).ran


# --- AC1 / AC6: failures -------------------------------------------------------------------------------

def _assert_failed(ws, needle):
    entry = manifest_of(ws)["stages"]["analysis"]
    assert entry["status"] == "failed" and needle in entry["error"] and entry["artifacts"] == []
    assert not any((ws.dir / n).exists() for n in ARTIFACTS)


def test_transcript_not_done_is_refused(cfg):
    ws = make_analysis_episode(cfg.workspace.dir, transcript_status="failed")
    fake = FakeAnalyzer()
    with pytest.raises(AnalysisError, match="transcript is not done"):
        run_analysis("rbjfCfFq3Dk", cfg, analyzer=fake)
    _assert_failed(ws, "transcript is not done")
    assert fake.calls == []


def test_no_audio_fails_without_artifacts(cfg):
    ws = make_analysis_episode(cfg.workspace.dir, audio=False)
    with pytest.raises(AnalysisError, match="no audio stream"):
        run_analysis("rbjfCfFq3Dk", cfg, analyzer=FakeAnalyzer())
    _assert_failed(ws, "no audio stream")


def test_ffmpeg_error_fails_and_removes_previous_artifacts(cfg):
    ws = make_analysis_episode(cfg.workspace.dir)
    assert run_analysis("rbjfCfFq3Dk", cfg, analyzer=FakeAnalyzer()).ran
    with pytest.raises(AnalysisError, match="ffmpeg failed"):
        run_analysis("rbjfCfFq3Dk", cfg, force=True, analyzer=FakeAnalyzer(fail="ffmpeg failed (exit 1): boom"))
    _assert_failed(ws, "ffmpeg failed (exit 1): boom")


def test_real_ffmpeg_on_invalid_media_fails(cfg):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    ws = make_analysis_episode(cfg.workspace.dir)  # source.mp4 is not a video
    with pytest.raises(AnalysisError, match="ffmpeg failed"):
        run_analysis("rbjfCfFq3Dk", cfg)
    _assert_failed(ws, "ffmpeg failed")


def test_missing_manifest_is_a_clear_error(cfg):
    with pytest.raises(AnalysisError, match="no manifest"):
        run_analysis("nope", cfg)


# --- CLI -------------------------------------------------------------------------------------------------

def test_cli_analysis_end_to_end_on_synthetic_video(video, config_file, capsys):
    video.with_name(video.stem + ".vi.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,900\nxin chào quý vị\n", encoding="utf-8")
    assert main(["ingest", str(video), "--config", str(config_file)]) == 0
    episode_id = capsys.readouterr().out.split("\t")[0]

    assert main(["analysis", episode_id, "--config", str(config_file)]) == 1
    assert "transcript is not done" in capsys.readouterr().err

    assert main(["transcript", episode_id, "--config", str(config_file)]) == 0
    capsys.readouterr()
    assert main(["analysis", episode_id, "--config", str(config_file)]) == 0
    out = capsys.readouterr()
    ep, state, path = out.out.rstrip("\n").split("\t")
    assert (ep, state) == (episode_id, "analyzed (0 candidates)")  # 2 s clip: shorter than min_duration
    assert path.endswith(f"{episode_id}/candidates.json")
    assert "analysis: content 0.0-" in out.err and "candidates=0" in out.err

    assert main(["analysis", episode_id, "--config", str(config_file)]) == 0
    out = capsys.readouterr()
    assert out.out.split("\t")[1] == "skipped (up to date)" and "analysis: skip (up to date)" in out.err
    assert main(["analysis", episode_id, "--force", "--config", str(config_file)]) == 0
    assert "analyzed" in capsys.readouterr().out

    assert main(["status", episode_id, "--config", str(config_file)]) == 0
    assert "analysis    done" in capsys.readouterr().out
