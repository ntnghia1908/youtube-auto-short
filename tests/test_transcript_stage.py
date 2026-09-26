"""Transcript stage: provider order, fallback, artifacts, resume/stale, failures (AC1–AC6)."""

import json
from dataclasses import replace

import pytest

from auto_short.hashing import sha256_file
from auto_short.transcript import TranscriptError, run_transcript
from auto_short.transcript.parsers import RawSegment
from auto_short.transcript.stage import used_config
from transcript_helpers import (
    JSON3_HEAD,
    JSON3_HEAD_DURATION,
    SRT_VI,
    VTT_ROLLUP,
    FakeFetcher,
    FakeWhisper,
    make_episode,
    manifest_of,
)

ENGLISH_JSON3 = json.dumps({"events": [
    {"tStartMs": 0, "dDurationMs": 9000, "segs": [{"utf8": "hello everyone today we continue the lesson"}]},
]}).encode()


def _cfg(cfg, **transcript):
    return replace(cfg, transcript=replace(cfg.transcript, **transcript))


def _doc(ws):
    return json.loads((ws.dir / "transcript.json").read_text(encoding="utf-8"))


# --- AC1: YouTube caption wins, Whisper never called --------------------------------------

def test_youtube_caption_accepted_whisper_not_called(cfg):
    ws, _ = make_episode(cfg.workspace.dir, episode_id="rbjfCfFq3Dk", kind="youtube", duration=JSON3_HEAD_DURATION)
    data = JSON3_HEAD.read_bytes()
    fetcher = FakeFetcher({("vi-orig", True): data, ("vi", True): b"{}"})
    whisper = FakeWhisper()

    result = run_transcript("rbjfCfFq3Dk", cfg, fetcher=fetcher, backend=whisper)

    assert result.ran and (result.source, result.method) == ("youtube", "youtube_auto_caption")
    assert whisper.calls == []  # AC1
    assert fetcher.downloads == [("vi-orig", True)]
    doc = _doc(ws)
    assert list(doc) == ["schema_version", "episode_id", "source", "method", "language", "media_sha256", "raw",
                         "provider", "attempts", "stats", "transcript_sha256", "segments"]
    assert doc["schema_version"] == 1 and doc["episode_id"] == "rbjfCfFq3Dk" and doc["language"] == "vi"
    assert doc["media_sha256"] == "ab" * 32
    assert doc["provider"] == {"track": "vi-orig", "auto": True}
    assert doc["raw"]["path"] == "transcript/youtube.vi-orig.json3"
    assert (ws.dir / doc["raw"]["path"]).read_bytes() == data
    assert doc["raw"]["sha256"] == sha256_file(ws.dir / doc["raw"]["path"])
    assert doc["attempts"] == [{"provider": "youtube", "status": "accepted", "reason": None}]
    assert doc["segments"][1]["words"][0] == {"start": 3.08, "end": 4.08, "text": "Phật"}

    entry = manifest_of(ws)["stages"]["transcript"]
    assert entry["status"] == "done" and entry["error"] is None
    assert entry["artifacts"] == ["transcript.json", "transcript/youtube.vi-orig.json3"]
    assert entry["inputs"] == [{"path": "metadata.json", "sha256": sha256_file(ws.dir / "metadata.json")}]


@pytest.mark.parametrize("available,expected", [
    ({("vi", False), ("vi-orig", True), ("vi", True)}, ("vi", False)),
    ({("vi-orig", True), ("vi", True)}, ("vi-orig", True)),
    ({("vi", True), ("en", False)}, ("vi", True)),
])
def test_youtube_track_preference(cfg, available, expected):
    ws, _ = make_episode(cfg.workspace.dir, kind="youtube", duration=JSON3_HEAD_DURATION)
    data = JSON3_HEAD.read_bytes()
    fetcher = FakeFetcher({t: data for t in available})
    run_transcript("ep", cfg, fetcher=fetcher, backend=FakeWhisper())
    assert fetcher.downloads == [expected]
    doc = _doc(ws)
    assert doc["method"] == ("youtube_auto_caption" if expected[1] else "youtube_manual_caption")


# --- AC2: fallback with reasons -------------------------------------------------------------

def test_youtube_missing_falls_back_to_local_subtitle(cfg, tmp_path):
    ws, _ = make_episode(cfg.workspace.dir, kind="youtube")
    sub = tmp_path / "given.srt"
    sub.write_text(SRT_VI, encoding="utf-8")
    whisper = FakeWhisper()
    result = run_transcript("ep", cfg, subtitle=sub, fetcher=FakeFetcher({("en", True): b"{}"}), backend=whisper)
    assert (result.source, result.method) == ("local_subtitle", "subtitle_srt")
    assert whisper.calls == []
    doc = _doc(ws)
    assert doc["attempts"] == [
        {"provider": "youtube", "status": "unavailable",
         "reason": "no Vietnamese caption track (manual vi, auto vi-orig, auto vi)"},
        {"provider": "local_subtitle", "status": "accepted", "reason": None},
    ]
    assert doc["raw"] == {"path": str(sub), "sha256": sha256_file(sub)}
    assert doc["provider"] == {"path": str(sub), "format": "srt"}
    assert not (ws.dir / "transcript").exists()  # local subtitles are referenced, not copied


@pytest.mark.parametrize("caption,reason", [
    (ENGLISH_JSON3, "not Vietnamese"),
    (b'{"events": []}', "empty transcript"),
    (b"<html>", "parse error"),
    (json.dumps({"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "xin chào quý vị"}]}]}).encode(),
     "coverage"),
    (json.dumps({"events": [
        {"tStartMs": 5000, "dDurationMs": 4000, "segs": [{"utf8": "xin chào quý vị hôm nay chúng ta học"}]},
        {"tStartMs": 1000, "dDurationMs": 3000, "segs": [{"utf8": "xin chào quý vị hôm nay chúng ta học"}]},
    ]}).encode(), "invalid timestamp"),
])
def test_youtube_rejected_falls_back_to_whisper(cfg, caption, reason):
    ws, media = make_episode(cfg.workspace.dir, kind="youtube")
    whisper = FakeWhisper()
    result = run_transcript("ep", cfg, fetcher=FakeFetcher({("vi-orig", True): caption}), backend=whisper)
    assert (result.source, result.method) == ("whisper", "faster_whisper")
    assert whisper.calls == [media.absolute()]
    doc = _doc(ws)
    yt, local, wh = doc["attempts"]
    assert yt["provider"] == "youtube" and yt["status"] == "rejected" and reason in yt["reason"]
    assert local == {"provider": "local_subtitle", "status": "unavailable",
                     "reason": "no subtitle file (--subtitle or sidecar next to the local video)"}
    assert wh == {"provider": "whisper", "status": "accepted", "reason": None}
    assert doc["raw"] is None
    assert doc["provider"] == {"model": "large-v3-turbo", "device": "cpu", "compute_type": "int8",
                               "vad_filter": True, "faster_whisper_version": "1.2.1-fake"}
    seg = doc["segments"][0]
    assert seg["text"] == "xin chào quý vị hôm nay chúng ta tiếp tục học kinh"
    assert seg["words"][0] == {"start": 0.0, "end": 0.667, "text": "xin"}
    # Rejected raw caption is not kept.
    assert manifest_of(ws)["stages"]["transcript"]["artifacts"] == ["transcript.json"]
    assert not (ws.dir / "transcript").exists()


def test_fetch_error_and_disabled_providers_are_recorded(cfg):
    ws, _ = make_episode(cfg.workspace.dir, kind="youtube")
    run_transcript("ep", cfg, fetcher=FakeFetcher(fail=True), backend=FakeWhisper())
    yt = _doc(ws)["attempts"][0]
    assert yt["status"] == "error" and "429" in yt["reason"]

    cfg2 = _cfg(cfg, providers=replace(cfg.transcript.providers, youtube=False, local_subtitle=False))
    fetcher = FakeFetcher({("vi-orig", True): JSON3_HEAD.read_bytes()})
    run_transcript("ep", cfg2, fetcher=fetcher, backend=FakeWhisper())
    assert fetcher.downloads == []
    assert [(a["provider"], a["status"], a["reason"]) for a in _doc(ws)["attempts"]] == [
        ("youtube", "unavailable", "disabled by config"),
        ("local_subtitle", "unavailable", "disabled by config"),
        ("whisper", "accepted", None),
    ]


# --- AC3: local subtitle formats, sidecar, --subtitle priority --------------------------------

@pytest.mark.parametrize("suffix,content,method", [
    (".vi.srt", SRT_VI, "subtitle_srt"),
    (".vtt", VTT_ROLLUP, "subtitle_vtt"),
    (".vi.json3", None, "subtitle_json3"),
])
def test_sidecar_formats_same_contract(cfg, suffix, content, method):
    duration = JSON3_HEAD_DURATION if content is None else 10.0
    ws, media = make_episode(cfg.workspace.dir, duration=duration)
    sidecar = media.with_name(media.stem + suffix)
    if content is None:
        sidecar.write_bytes(JSON3_HEAD.read_bytes())
    else:
        sidecar.write_text(content, encoding="utf-8")
    whisper = FakeWhisper()
    result = run_transcript("ep", cfg, fetcher=FakeFetcher(), backend=whisper)
    assert result.method == method and whisper.calls == []
    doc = _doc(ws)
    assert doc["source"] == "local_subtitle" and doc["provider"]["path"] == str(sidecar)
    assert doc["attempts"][0] == {"provider": "youtube", "status": "unavailable", "reason": "source is not YouTube"}
    assert manifest_of(ws)["stages"]["transcript"]["inputs"][1] == {"path": str(sidecar), "sha256": sha256_file(sidecar)}
    if method == "subtitle_vtt":
        assert doc["segments"][0]["words"][1] == {"start": 1.0, "end": 1.5, "text": "thuyết"}


def test_sidecar_priority_and_explicit_subtitle_wins(cfg, tmp_path):
    ws, media = make_episode(cfg.workspace.dir)
    media.with_name("lecture.srt").write_text(SRT_VI, encoding="utf-8")
    media.with_name("lecture.vi.vtt").write_text(VTT_ROLLUP, encoding="utf-8")
    run_transcript("ep", cfg, backend=FakeWhisper())
    assert _doc(ws)["provider"]["path"] == str(media.with_name("lecture.vi.vtt"))

    explicit = tmp_path / "other.srt"
    explicit.write_text(SRT_VI, encoding="utf-8")
    result = run_transcript("ep", cfg, subtitle=explicit, backend=FakeWhisper())
    assert result.ran  # different subtitle input
    assert _doc(ws)["provider"] == {"path": str(explicit), "format": "srt"}

    # --subtitle is not remembered: running without it is an input change back to the sidecar.
    result = run_transcript("ep", cfg, backend=FakeWhisper())
    assert result.ran and _doc(ws)["provider"]["path"] == str(media.with_name("lecture.vi.vtt"))


def test_bad_explicit_subtitle_is_a_clear_error(cfg, tmp_path):
    make_episode(cfg.workspace.dir)
    with pytest.raises(TranscriptError, match="subtitle file not found"):
        run_transcript("ep", cfg, subtitle=tmp_path / "missing.srt", backend=FakeWhisper())
    bad = tmp_path / "x.ass"
    bad.write_text("x")
    with pytest.raises(TranscriptError, match="unsupported subtitle format"):
        run_transcript("ep", cfg, subtitle=bad, backend=FakeWhisper())


# --- AC5: resume / stale / force ----------------------------------------------------------------

def test_rerun_skips_byte_identical_and_reruns_on_changes(cfg, caplog):
    ws, media = make_episode(cfg.workspace.dir)
    sidecar = media.with_name("lecture.vi.srt")
    sidecar.write_text(SRT_VI, encoding="utf-8")
    whisper = FakeWhisper()
    assert run_transcript("ep", cfg, backend=whisper).ran
    first = (ws.dir / "transcript.json").read_bytes()
    manifest_before = manifest_of(ws)

    caplog.set_level("INFO", logger="auto_short")
    again = run_transcript("ep", cfg, backend=whisper)
    assert not again.ran and "transcript: skip (up to date)" in caplog.text
    assert (ws.dir / "transcript.json").read_bytes() == first
    assert manifest_of(ws) == manifest_before

    # Execution-only settings do not invalidate.
    cfg_threads = _cfg(cfg, whisper=replace(cfg.transcript.whisper, cpu_threads=3, models_dir=cfg.workspace.dir))
    assert used_config(cfg_threads) == used_config(cfg)
    assert not run_transcript("ep", cfg_threads, backend=whisper).ran

    # Any [transcript] key that affects the artifact reruns.
    assert run_transcript("ep", _cfg(cfg, min_coverage=0.4), backend=whisper).ran
    assert run_transcript("ep", _cfg(cfg, whisper=replace(cfg.transcript.whisper, model="small")),
                          backend=whisper).ran
    assert run_transcript("ep", cfg, backend=whisper).ran  # back to the original config
    assert (ws.dir / "transcript.json").read_bytes() == first

    # Subtitle content change reruns.
    sidecar.write_text(SRT_VI.replace("Singapore", "Tân Gia Ba"), encoding="utf-8")
    assert run_transcript("ep", cfg, backend=whisper).ran
    assert "Tân Gia Ba" in _doc(ws)["segments"][-1]["text"]

    # --force always reruns, output unchanged.
    out = (ws.dir / "transcript.json").read_bytes()
    assert run_transcript("ep", cfg, force=True, backend=whisper).ran
    assert (ws.dir / "transcript.json").read_bytes() == out
    assert whisper.calls == []


def test_ingest_rerun_makes_transcript_stale_then_rerun(cfg, video):
    from auto_short.ingest import run_ingest

    video.with_name(video.stem + ".srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,900\nxin chào quý vị\n", encoding="utf-8")
    ep = run_ingest(str(video), cfg).episode_id
    assert run_transcript(ep, cfg, backend=FakeWhisper()).method == "subtitle_srt"
    ws_dir = cfg.workspace.dir / ep
    manifest = json.loads((ws_dir / "manifest.json").read_text())
    manifest["stages"]["analysis"] = dict(manifest["stages"]["transcript"], artifacts=[])
    (ws_dir / "manifest.json").write_text(json.dumps(manifest))

    run_ingest(str(video), cfg, force=True)
    stages = json.loads((ws_dir / "manifest.json").read_text())["stages"]
    assert stages["transcript"]["status"] == "stale" and stages["analysis"]["status"] == "stale"

    assert run_transcript(ep, cfg, backend=FakeWhisper()).ran
    stages = json.loads((ws_dir / "manifest.json").read_text())["stages"]
    assert stages["transcript"]["status"] == "done" and stages["analysis"]["status"] == "stale"


# --- AC6: failures -------------------------------------------------------------------------------

def test_all_providers_fail_leaves_no_artifacts(cfg):
    ws, media = make_episode(cfg.workspace.dir, kind="youtube", duration=JSON3_HEAD_DURATION)
    fetcher = FakeFetcher({("vi-orig", True): JSON3_HEAD.read_bytes()})
    assert run_transcript("ep", cfg, fetcher=fetcher, backend=FakeWhisper()).ran
    assert (ws.dir / "transcript" / "youtube.vi-orig.json3").is_file()

    silent = FakeWhisper([RawSegment(0.0, 1.0, "[âm nhạc]")])
    with pytest.raises(TranscriptError) as exc:
        run_transcript("ep", cfg, force=True, fetcher=FakeFetcher({("vi-orig", True): ENGLISH_JSON3}),
                       backend=silent)
    msg = str(exc.value)
    assert "youtube: rejected" in msg and "local_subtitle: unavailable" in msg and "whisper: rejected" in msg
    assert silent.calls == [media.absolute()]
    entry = manifest_of(ws)["stages"]["transcript"]
    assert entry["status"] == "failed" and "no acceptable transcript" in entry["error"]
    assert entry["artifacts"] == []
    assert sorted(p.name for p in ws.dir.iterdir()) == ["manifest.json", "metadata.json", "source.mp4"]


def test_whisper_exception_is_error_attempt_and_failure(cfg):
    ws, _ = make_episode(cfg.workspace.dir)

    class Broken(FakeWhisper):
        def transcribe(self, media, *, language, config):
            raise RuntimeError("model download failed")

    with pytest.raises(TranscriptError, match="whisper: error \\(model download failed\\)"):
        run_transcript("ep", cfg, backend=Broken())
    assert manifest_of(ws)["stages"]["transcript"]["status"] == "failed"
    assert not (ws.dir / "transcript.json").exists()


def test_ingest_not_done_is_refused(cfg):
    ws, _ = make_episode(cfg.workspace.dir)
    manifest = manifest_of(ws)
    manifest["stages"]["ingest"]["status"] = "failed"
    ws.save_manifest(manifest)
    whisper = FakeWhisper()
    with pytest.raises(TranscriptError, match="ingest is not done"):
        run_transcript("ep", cfg, backend=whisper)
    entry = manifest_of(ws)["stages"]["transcript"]
    assert entry["status"] == "failed" and "ingest is not done" in entry["error"]
    assert whisper.calls == [] and not (ws.dir / "transcript.json").exists()

    with pytest.raises(TranscriptError, match="no manifest"):
        run_transcript("nope", cfg, backend=whisper)


def test_local_subtitle_rejected_falls_back_to_whisper(cfg):
    ws, media = make_episode(cfg.workspace.dir)
    media.with_name("lecture.srt").write_text(
        "1\n00:00:00,000 --> 00:00:09,000\nhello everyone today we continue the lesson on the sutra\n",
        encoding="utf-8")
    whisper = FakeWhisper()
    assert run_transcript("ep", cfg, backend=whisper).source == "whisper"
    assert len(whisper.calls) == 1
    local = _doc(ws)["attempts"][1]
    assert local["provider"] == "local_subtitle" and local["status"] == "rejected"
    assert "not Vietnamese" in local["reason"]


def test_corrupt_metadata_is_a_clear_error(cfg):
    ws, _ = make_episode(cfg.workspace.dir)
    (ws.dir / "metadata.json").write_text("{broken")
    with pytest.raises(TranscriptError, match="cannot read .*metadata.json"):
        run_transcript("ep", cfg, backend=FakeWhisper())
