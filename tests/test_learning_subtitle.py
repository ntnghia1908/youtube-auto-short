"""CL1.1 stage ``subtitle``: unavailable/malformed captions, window, timestamps, artifact schema (AC3–AC7)."""

import hashlib
import json
import shutil

import pytest
from learning_helpers import (REAL_JSON3, URL, VIDEO_ID, ZH_EVENTS, FakeClipDownloader, FakeLister, json3,
                              learning_config, make_clip, track)
from learning_helpers import no_real_ollama  # noqa: F401  (autouse: no test reaches a real Ollama)

from auto_short.learning import LearningError, run_learning
from auto_short.learning.subtitle import han_ratio, in_window, validate
from auto_short.transcript.normalize import normalize
from auto_short.transcript.parsers import parse_json3
from auto_short.workspace import FAILED


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    return make_clip(tmp_path_factory.mktemp("learning-clip") / "clip3.mp4")


def _ws(cfg):
    return cfg.workspace.dir / "_learning" / VIDEO_ID


def _manifest(cfg):
    return json.loads((_ws(cfg) / "manifest.json").read_text(encoding="utf-8"))


def _fail(tmp_path, lister, **learning):
    """Run with a downloader that must never be called; return (error, manifest, workspace files)."""
    cfg = learning_config(tmp_path, **learning)
    downloader = FakeClipDownloader(tmp_path / "never.mp4")
    with pytest.raises(LearningError) as exc:
        run_learning(URL, cfg, lister=lister, downloader=downloader)
    assert downloader.calls == []  # media does not run
    files = sorted(p.name for p in _ws(cfg).iterdir())
    return str(exc.value), _manifest(cfg), files


# --- AC3: no Chinese subtitle ------------------------------------------------------------

def test_no_chinese_track_fails_without_media(tmp_path):
    lister = FakeLister(tracks=[track("vi-orig", auto=True, lang="vi", kind="asr"),
                                track("zh-Hans", auto=True, lang="vi", kind="asr", tlang="zh-Hans"),
                                track("zh-Hant", auto=True, lang="vi", kind="asr", tlang="zh-Hant")])
    err, manifest, files = _fail(tmp_path, lister)
    assert "no Chinese subtitle track (manual zh*, auto zh ASR)" in err
    assert "machine-translated auto zh-Hans" in err and "machine-translated auto zh-Hant" in err
    assert lister.downloads == []  # nothing downloaded
    entry = manifest["stages"]["subtitle"]
    assert entry["status"] == FAILED and "no Chinese subtitle track" in entry["error"]
    assert "media" not in manifest["stages"]
    assert files == ["manifest.json"]


# --- AC4: malformed captions --------------------------------------------------------------

@pytest.mark.parametrize("data, reason", [
    (b"not json", "parse error: invalid json3"),
    (b'{"events": 3}', "parse error"),
    (json3([(500, 1000, "大家好"), (400, 1000, "我是老师")]), "before previous start"),  # decreasing start
    (json3([(500, 1000, "大家好"), (1600, 9000, "我是老师")]), "beyond video duration"),  # end > duration + 1
    (json3([(1500, 0, "大家好")]), "invalid timestamp"),  # start == end
    (json3([(500, 1000, "hello everyone"), (1600, 1000, "this is English")]), "not Chinese"),
    (json3([(500, 1000, "[音乐]")]), "no speech segment"),  # only a non-speech label
])
def test_malformed_caption_fails(tmp_path, data, reason):
    err, manifest, files = _fail(tmp_path, FakeLister(data))
    assert "subtitle zh-Hans rejected" in err and reason in err
    assert manifest["stages"]["subtitle"]["status"] == FAILED
    assert reason in manifest["stages"]["subtitle"]["error"]
    assert files == ["manifest.json"]


def test_no_segment_in_window_fails(tmp_path):
    lister = FakeLister(json3([(310_000, 1000, "大家好")]), duration=400)
    err, _, files = _fail(tmp_path, lister)
    assert "no speech segment starts before 300.0 s" in err
    assert files == ["manifest.json"]


def test_han_ratio_threshold_is_config(tmp_path):
    data = json3([(500, 1000, "我爱ABC")])  # 2 Han of 5 letters = 0.4
    err, _, _ = _fail(tmp_path, FakeLister(data))
    assert "0.400 of letters" in err and "(< 0.5)" in err
    cfg = learning_config(tmp_path / "b", min_han_ratio=0.4)
    assert run_learning(URL, cfg, lister=FakeLister(data), downloader=_ok_downloader(tmp_path)) is not None


def _ok_downloader(tmp_path):
    dst = tmp_path / "ok.mp4"
    if not dst.exists():
        make_clip(dst)
    return FakeClipDownloader(dst)


def test_validate_rejects_non_zh_tag():
    segs = normalize(parse_json3(json3(ZH_EVENTS)))
    reason = validate(segs, in_window(segs, 300.0), duration=3.0, lang="ja", window=300.0, min_han_ratio=0.5)
    assert reason == "language is 'ja', expected 'zh*'"
    assert validate(segs, in_window(segs, 300.0), duration=3.0, lang="zh-TW", window=300.0,
                    min_han_ratio=0.5) is None


def test_han_ratio_counts_letters_only():
    assert han_ratio(["大家好！ 123 ..."]) == 1.0
    assert han_ratio(["abc", "中"]) == 0.25
    assert han_ratio(["㐀"]) == 1.0  # Extension A
    assert han_ratio(["!!!"]) == 0.0


def test_download_error_fails_stage(tmp_path):
    from auto_short.transcript.youtube import CaptionFetchError
    err, manifest, files = _fail(tmp_path, FakeLister(fail=CaptionFetchError("caption download failed (zh-Hans)")))
    assert "caption download failed" in err and files == ["manifest.json"]


# --- AC5 / AC6: window boundary and timestamps ----------------------------------------------

BOUNDARY = [
    (1_234, 1_000, "第一句"),
    (299_000, 999, "前一句"),
    (299_999, 2_501, "跨过窗口的一句"),  # start 299.999 < 300 kept, end 302.5 untouched
    (305_000, 1_000, "更后面"),
]


def test_window_boundary_and_timestamps_preserved(tmp_path, clip):
    cfg = learning_config(tmp_path)
    data = json3(BOUNDARY)
    run_learning(URL, cfg, lister=FakeLister(data, duration=400),
                 downloader=FakeClipDownloader(clip, video_duration=3.0))
    ws = _ws(cfg)
    stored = (ws / "subtitle.json3").read_bytes()
    assert stored == data
    window = in_window(normalize(parse_json3(stored)), 300.0)
    assert [(s["start"], s["end"], s["text"]) for s in window] == [
        (1.234, 2.234, "第一句"), (299.0, 299.999, "前一句"), (299.999, 302.5, "跨过窗口的一句")]
    stats = json.loads((ws / "source.json").read_text(encoding="utf-8"))["stats"]
    assert stats == {"segments_in_window": 3, "han_ratio": 1.0, "first_start": 1.234, "last_end": 302.5}


def test_segment_starting_at_window_end_is_dropped(tmp_path, clip):
    cfg = learning_config(tmp_path)
    data = json3([(1_000, 1_000, "第一句"), (299_999, 1, "最后一句"), (300_000, 1_000, "窗口外")])
    run_learning(URL, cfg, lister=FakeLister(data, duration=400), downloader=FakeClipDownloader(clip))
    stats = json.loads((_ws(cfg) / "source.json").read_text(encoding="utf-8"))["stats"]
    assert stats == {"segments_in_window": 2, "han_ratio": 1.0, "first_start": 1.0, "last_end": 300.0}


def test_video_shorter_than_window_keeps_every_segment(tmp_path, clip):
    cfg = learning_config(tmp_path)
    run_learning(URL, cfg, lister=FakeLister(), downloader=FakeClipDownloader(clip))
    source = json.loads((_ws(cfg) / "source.json").read_text(encoding="utf-8"))
    assert source["stats"]["segments_in_window"] == len(ZH_EVENTS)
    assert source["stats"]["first_start"] == 0.5 and source["stats"]["last_end"] == 3.8


def test_window_is_config(tmp_path, clip):
    cfg = learning_config(tmp_path, window_seconds=2.0)
    run_learning(URL, cfg, lister=FakeLister(), downloader=FakeClipDownloader(clip))
    source = json.loads((_ws(cfg) / "source.json").read_text(encoding="utf-8"))
    assert source["window"] == {"start": 0.0, "end": 2.0}
    assert source["stats"]["segments_in_window"] == 2  # starts 0.5 and 1.6; 2.9 is outside


def test_real_fixture_normalizes_as_expected():
    """Guards the CP3 parse_json3/normalize behaviour learning relies on (import only)."""
    segs = normalize(parse_json3(REAL_JSON3.read_bytes()))
    assert [(s["id"], s["start"], s["end"], s["text"]) for s in segs] == [
        ("s00001", 0.566, 2.566, "我现在要出门去上班啦"),
        ("s00002", 2.566, 3.933, "跟我一起去看看吧"),
        ("s00003", 4.8, 5.833, "拜拜"),
        ("s00004", 6.533, 9.8, "今天路上的车特别的少"),
        ("s00005", 11.066, 14.166, "这样的话就能省很多时间"),
        ("s00006", 15.933, 17.766, "天气也不错"),
        ("s00007", 18.4, 20.666, "我现在在车站等车"),
    ]
    assert validate(segs, in_window(segs, 300.0), duration=414, lang="zh-CN", window=300.0,
                    min_han_ratio=0.5) is None


# --- AC7: artifact schema and byte stability -------------------------------------------------

def test_artifacts_schema_and_force_byte_stable(tmp_path, clip):
    cfg = learning_config(tmp_path)
    lister = FakeLister(REAL_JSON3.read_bytes(), duration=414,
                        tracks=[track("zh"), track("zh-CN"), track("zh-Hant"),
                                track("zh", auto=True, json3=False), track("en", auto=True, lang="en", kind="asr")])
    result = run_learning(URL, cfg, lister=lister, downloader=FakeClipDownloader(clip))
    assert result.stages == [("subtitle", True), ("media", True), ("lesson", True)]
    ws = _ws(cfg)
    assert (ws / "subtitle.json3").read_bytes() == REAL_JSON3.read_bytes()
    source_bytes = (ws / "source.json").read_bytes()
    source = json.loads(source_bytes)
    assert list(source) == ["schema_version", "episode_id", "video", "tracks", "selected", "subtitle", "window",
                            "stats"]
    assert source["schema_version"] == 1 and source["episode_id"] == VIDEO_ID
    assert list(source["video"]) == ["id", "title", "channel", "duration", "webpage_url"]
    assert source["tracks"] == [
        {"key": "zh", "auto": False, "lang": "zh", "kind": None, "tlang": None, "json3": True},
        {"key": "zh-CN", "auto": False, "lang": "zh-CN", "kind": None, "tlang": None, "json3": True},
        {"key": "zh-Hant", "auto": False, "lang": "zh-Hant", "kind": None, "tlang": None, "json3": True},
        {"key": "zh", "auto": True, "lang": "zh", "kind": None, "tlang": None, "json3": False},
    ]
    assert list(source["selected"]) == ["key", "auto", "lang", "reason"]
    assert source["selected"]["key"] == "zh-CN" and source["selected"]["auto"] is False
    assert source["subtitle"] == {"path": "subtitle.json3",
                                  "sha256": hashlib.sha256(REAL_JSON3.read_bytes()).hexdigest()}
    assert source["window"] == {"start": 0.0, "end": 300.0}
    assert list(source["stats"]) == ["segments_in_window", "han_ratio", "first_start", "last_end"]
    assert lister.downloads == [(f"https://youtu.be/{VIDEO_ID}", "zh-CN", False)]
    assert "_at" not in source_bytes.decode("utf-8")  # no creation time

    manifest = _manifest(cfg)
    assert list(manifest) == ["schema_version", "episode_id", "source", "stages"]
    assert manifest["source"] == {"kind": "youtube", "uri": f"https://youtu.be/{VIDEO_ID}", "path": None,
                                  "sha256": None, "size": None, "mtime_ns": None}
    sub = manifest["stages"]["subtitle"]
    assert sub["status"] == "done" and sub["artifacts"] == ["subtitle.json3", "source.json"] and sub["inputs"] == []

    result = run_learning(URL, cfg, force=True, lister=lister, downloader=FakeClipDownloader(clip))
    assert result.stages == [("subtitle", True), ("media", True), ("lesson", True)]
    assert (ws / "source.json").read_bytes() == source_bytes
