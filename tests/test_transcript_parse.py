"""Parsers + normalization + validation (T5, T6; AC2 reject reasons, AC3, AC4)."""

import json

import pytest

from auto_short.config import TranscriptConfig
from auto_short.transcript.normalize import normalize, stats, validate
from auto_short.transcript.parsers import ParseError, RawSegment, parse, parse_json3, parse_srt, parse_vtt
from transcript_helpers import JSON3_HEAD, JSON3_HEAD_DURATION, SRT_VI, SUB_DURATION, VTT_ROLLUP

CFG = TranscriptConfig()


def _decimals_ok(x: float) -> bool:
    return round(x, 3) == x


def assert_normalized(segments):
    """AC4: no overlap, start non-decreasing, 3-decimal timestamps, words inside segments."""
    for i, s in enumerate(segments):
        assert s["id"] == f"s{i + 1:05d}"
        assert 0 <= s["start"] < s["end"]
        assert _decimals_ok(s["start"]) and _decimals_ok(s["end"])
        if i:
            prev = segments[i - 1]
            assert prev["start"] <= s["start"] and prev["end"] <= s["start"]
        for w in s["words"]:
            assert s["start"] <= w["start"] <= w["end"] <= s["end"]
            assert _decimals_ok(w["start"]) and _decimals_ok(w["end"])
        starts = [w["start"] for w in s["words"]]
        assert starts == sorted(starts)


def test_json3_fixture_normalizes_rollup_and_keeps_word_timing():
    raw = parse_json3(JSON3_HEAD.read_bytes())
    doc = json.loads(JSON3_HEAD.read_text())
    text_events = [e for e in doc["events"] if "".join(s.get("utf8", "") for s in e.get("segs", [])).strip()]
    assert len(raw) == len(text_events)  # newline-only / window events dropped

    segs = normalize(raw)
    assert_normalized(segs)
    first, second = segs[0], segs[1]
    assert first == {"id": "s00001", "start": 0.57, "end": 2.97, "kind": "non_speech",
                     "text": "[âm nhạc]", "words": []}
    assert second["kind"] == "speech" and second["text"] == "Phật thuyết thập thiện nghiệp đạo Kinh"
    # Roll-up: raw event lasts 3.08 + 7.2 s but the next text event starts at 7.639.
    assert (second["start"], second["end"]) == (3.08, 7.639)
    assert second["words"][:2] == [{"start": 3.08, "end": 4.08, "text": "Phật"},
                                   {"start": 4.08, "end": 4.44, "text": "thuyết"}]
    assert second["words"][-1]["end"] == 7.639
    assert validate(segs, duration=JSON3_HEAD_DURATION, language="vi-orig", cfg=CFG) is None
    st = stats(segs, JSON3_HEAD_DURATION)
    assert st["segments"] == len(segs) and st["words"] == 75 and 0.5 < st["coverage"] <= 1


def test_json3_manual_line_has_no_word_timing():
    data = json.dumps({"events": [
        {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "xin chào các bạn"}]},
        {"tStartMs": 3000, "dDurationMs": 1000, "segs": [{"utf8": "\n"}]},
    ]})
    segs = normalize(parse_json3(data))
    assert segs == [{"id": "s00001", "start": 1.0, "end": 3.0, "kind": "speech",
                     "text": "xin chào các bạn", "words": []}]


def test_srt_rollup_tags_and_overlap():
    segs = normalize(parse_srt(SRT_VI))
    assert [s["text"] for s in segs] == [
        "Phật thuyết thập thiện nghiệp đạo kinh",
        "người giảng lão pháp sư Tịnh Không",
        "tại Tịnh Tông Học Hội Singapore",
    ]
    assert segs[0]["end"] == 2.8  # trimmed to the next cue start
    assert all(s["words"] == [] for s in segs)
    assert_normalized(segs)
    assert validate(segs, duration=SUB_DURATION, language="vi", cfg=CFG) is None


def test_srt_repeated_lines_are_merged():
    srt = ("1\n00:00:01,000 --> 00:00:03,000\ndòng một\n\n"
           "2\n00:00:03,000 --> 00:00:05,000\ndòng một\ndòng hai\n\n"
           "3\n00:00:05,000 --> 00:00:07,000\ndòng hai\ndòng ba\n")
    assert [s.text for s in parse_srt(srt)] == ["dòng một", "dòng hai", "dòng ba"]


def test_vtt_rollup_dedupe_and_inline_word_timing():
    segs = normalize(parse_vtt(VTT_ROLLUP))
    assert [s["text"] for s in segs] == [
        "Phật thuyết thập thiện",
        "nghiệp đạo kinh tập chín",
        "người giảng lão pháp sư",
    ]
    assert [(s["start"], s["end"]) for s in segs] == [(0.5, 3.0), (3.01, 6.0), (6.01, 9.5)]
    assert segs[0]["words"] == [
        {"start": 0.5, "end": 1.0, "text": "Phật"},
        {"start": 1.0, "end": 1.5, "text": "thuyết"},
        {"start": 1.5, "end": 2.0, "text": "thập"},
        {"start": 2.0, "end": 3.0, "text": "thiện"},
    ]
    # First word of a continued line starts at the cue start.
    assert segs[1]["words"][0] == {"start": 3.01, "end": 3.5, "text": "nghiệp"}
    assert_normalized(segs)


def test_vtt_plain_cues_without_word_timing():
    vtt = "WEBVTT\n\n1\n00:01.000 --> 00:04.000\n<v Thầy>Nam mô A Di Đà Phật</v>\n"
    segs = normalize(parse_vtt(vtt))
    assert segs[0]["text"] == "Nam mô A Di Đà Phật" and segs[0]["words"] == []
    assert (segs[0]["start"], segs[0]["end"]) == (1.0, 4.0)


@pytest.mark.parametrize("data,fmt", [
    (b"{not json", "json3"),
    (b'{"no_events": []}', "json3"),
    (b"1\n00:00:01,000 --> 00:00:02,000\nok\n", "vtt"),  # missing WEBVTT header
    (b"1\nnot a timing\ntext\n", "srt"),
    (b"\xff\xfe\x00bad", "srt"),
])
def test_parse_errors(data, fmt):
    with pytest.raises(ParseError):
        parse(data, fmt)


def _segs(*items):
    return normalize([RawSegment(a, b, t) for a, b, t in items])


VI_LINE = "xin chào quý vị hôm nay chúng ta học tiếp bài kinh"


@pytest.mark.parametrize("segments,language,reason", [
    ([], "vi", "empty transcript"),
    ([(0, 9, "[âm nhạc]")], "vi", "no speech text"),
    ([(0, 9, VI_LINE)], "en", "language is 'en'"),
    ([(0, 9, "hello everyone today we continue the lesson on the sutra")], "vi", "not Vietnamese"),
    ([(0, 2, VI_LINE)], "vi", "coverage"),
    ([(0, 9, "xin chào")], "vi", "words/minute"),
    ([(5, 9, VI_LINE), (1, 4, VI_LINE)], "vi", "before previous start"),
    ([(0, 12, VI_LINE)], "vi", "beyond media duration"),
    ([(-1, 9, VI_LINE)], "vi", "invalid timestamp"),
    ([(3, 3, VI_LINE), (3, 9, VI_LINE)], "vi", "invalid timestamp"),
    ([(float("nan"), 9, VI_LINE)], "vi", "non-finite"),
])
def test_validation_rejects(segments, language, reason):
    got = validate(_segs(*segments), duration=SUB_DURATION, language=language, cfg=CFG)
    assert got is not None and reason in got


def test_validation_accepts_label_inside_speech_and_vi_orig():
    segs = _segs((0, 1, "[âm nhạc]"), (1, 9, f"[vỗ tay] {VI_LINE}"))
    assert [s["kind"] for s in segs] == ["non_speech", "speech"]
    assert validate(segs, duration=SUB_DURATION, language="vi-orig", cfg=CFG) is None
    assert stats(segs, SUB_DURATION) == {"segments": 2, "words": 12, "speech_seconds": 8.0, "coverage": 0.8}
