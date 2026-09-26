"""Content window, cut points, units, candidates and trims (AC2–AC5), pure functions."""

from dataclasses import replace

import pytest

from auto_short.analysis import AnalysisError
from auto_short.analysis.candidates import (
    build_units,
    detect_content_window,
    find_cut_points,
    generate_candidates,
    plan_trims,
    validate,
)
from auto_short.analysis.detect import normalize_silences
from auto_short.analysis.stage import analyze, shots_document
from auto_short.config import AnalysisConfig
from analysis_helpers import REAL, lecture, real_segments, real_silences, seg

CFG = AnalysisConfig()
DUR = REAL["duration"]


def real_run(cfg=CFG, segments=None, silences=None, changes=None, duration=DUR):
    segments = real_segments() if segments is None else segments
    silences = normalize_silences(real_silences() if silences is None else silences, duration)
    changes = REAL["shot_changes"] if changes is None else changes
    transcript = {"segments": segments, "transcript_sha256": "t" * 64}
    metadata = {"duration": duration, "source": {"sha256": "ab" * 32}}
    return analyze("rbjfCfFq3Dk", transcript, metadata, changes, silences, cfg)


def independent_check(doc: dict, segments: list[dict], silences: list[tuple[float, float]],
                      changes: list[float], cfg: AnalysisConfig = CFG) -> None:
    """AC3–AC4 from first principles (does not reuse the module's validation)."""
    cs, ce = doc["content"]["start"], doc["content"]["end"]
    labels = [(s["start"], s["end"]) for s in segments if s["kind"] == "non_speech"]
    starts = [s["start"] for s in segments if s["kind"] == "speech"]
    eps = 1e-6

    def aligned(a, b):
        return any(a - cfg.align_tolerance - eps <= t <= b + cfg.align_tolerance + eps for t in starts)

    for c in doc["candidates"]:
        ss, se = c["source_start"], c["source_end"]
        assert cs <= ss < se <= ce, c["id"]
        for side, t, attr in (("start", ss, 1), ("end", se, 0)):
            brk = c["boundary"][side]
            edge = t + cfg.boundary_pad if side == "start" else t - cfg.boundary_pad
            if brk["kind"] == "silence":
                sil = [s for s in silences if abs(s[attr] - edge) < eps]
                assert sil, (c["id"], side, "edge not at a silence edge + boundary_pad")
                a, b = sil[0]
                assert b - a >= cfg.min_boundary_silence - eps and aligned(a, b), (c["id"], side)
                assert abs(brk["seconds"] - (b - a)) < 1e-3
            else:
                assert brk["kind"] in ("hard_break", "content_edge")
            # never starts/ends inside a short (< min_boundary_silence) silence, unless at a hard/content edge
            inside = [s for s in silences if s[0] + eps < t < s[1] - eps]
            if brk["kind"] == "silence":
                assert all(b - a >= cfg.min_boundary_silence - eps for a, b in inside), (c["id"], side)
        # no hard break inside
        assert not any(a < se and b > ss for a, b in labels), (c["id"], "contains non_speech")
        # a hard-break silence may only be touched by the boundary_pad at an edge
        assert not any(b - a >= cfg.hard_break_silence - eps and min(b, se) - max(a, ss) > cfg.boundary_pad + eps
                       for a, b in silences), c["id"]
        # shot guard
        assert not any(ss < x < ss + cfg.shot_guard or se - cfg.shot_guard < x < se for x in changes), c["id"]
        # trims: every silence part inside the clip longer than max_pause keeps exactly max_pause
        expected = []
        for a, b in silences:
            a2, b2 = max(a, ss), min(b, se)
            if b2 - a2 > cfg.max_pause + eps:
                expected.append([round(a2 + cfg.max_pause / 2, 3), round(b2 - cfg.max_pause / 2, 3)])
        assert c["trims"] == expected, c["id"]
        dur = round(se - ss - sum(b - a for a, b in c["trims"]), 3)
        assert abs(c["duration"] - dur) < eps and abs(c["source_duration"] - round(se - ss, 3)) < eps
        assert cfg.min_duration <= c["duration"] <= cfg.max_duration, c["id"]
        assert c["in_target"] == (cfg.target_min <= c["duration"] <= cfg.target_max)


# --- AC2: content window --------------------------------------------------------------------------

def test_real_content_window_excludes_intro_announcement_and_outro():
    w = detect_content_window(real_segments(), normalize_silences(real_silences(), DUR), DUR, CFG)
    assert (w.start, w.end) == (22.875, 3554.6)
    assert w.start_reason == "intro: non_speech s00001 + silence 19.667-22.875"
    assert w.end_reason == "outro: non_speech s00815"


def test_mid_non_speech_labels_do_not_move_the_content_window():
    _, _, doc = real_run()
    assert (doc["content"]["start"], doc["content"]["end"]) == (22.875, 3554.6)
    # ... they are hard breaks instead
    kinds = {(u["break_after"]["kind"], u["break_after"]["seconds"]) for u in doc["units"]}
    assert ("hard_break", None) in kinds


def test_no_intro_or_outro_label_gives_zero_and_duration():
    segments, silences, duration = lecture(6)
    w = detect_content_window(segments, silences, duration, CFG)
    assert (w.start, w.end) == (0.0, duration)
    assert (w.start_reason, w.end_reason) == ("no intro detected", "no outro detected")


def test_intro_label_without_following_silence_starts_at_label_end():
    segments = [seg(1, 0.5, 3.0, kind="non_speech"), seg(2, 3.0, 20.0), seg(3, 20.0, 40.0)]
    w = detect_content_window(segments, [(10.0, 10.5)], 100.0, CFG)  # only a 0.5 s silence
    assert w.start == 3.0 and w.start_reason.startswith("intro: non_speech s00001 (no silence")


def test_intro_label_after_intro_window_is_not_intro():
    segments = [seg(1, 0.0, 61.0), seg(2, 61.0, 64.0, kind="non_speech"), seg(3, 64.0, 90.0)]
    w = detect_content_window(segments, [(64.0, 66.0)], 1000.0, CFG)
    assert (w.start, w.start_reason) == (0.0, "no intro detected")


# --- AC3: cut points ------------------------------------------------------------------------------

def test_cut_points_need_long_aligned_silence():
    segments = [seg(1, 0.0, 10.0), seg(2, 13.2, 20.0), seg(3, 20.0, 30.0), seg(4, 34.0, 40.0),
                seg(5, 40.0, 50.0)]
    silences = [
        (10.0, 13.0),  # 3.0 s, next segment starts 0.2 s later -> cut
        (21.0, 23.9),  # 2.9 s -> not a cut
        (24.5, 28.0),  # 3.5 s, no segment starts within +-0.5 s -> not a cut (caption spans it)
        (30.0, 33.5),  # 3.5 s, aligned (34.0 within 0.5 of end) -> cut
        (45.0, 56.0),  # 11 s -> hard break, alignment not required
    ]
    w = detect_content_window(segments, silences, 60.0, CFG)
    cuts = find_cut_points(segments, silences, w, CFG)
    assert [(c.kind, c.lo, c.hi) for c in cuts] == [
        ("content_edge", 0, 0), ("silence", 10000, 13000), ("silence", 30000, 33500),
        ("hard_break", 45000, 56000), ("content_edge", 60000, 60000)]


def test_units_edges_segments_and_breaks():
    _, _, doc = real_run()
    u1 = doc["units"][0]
    assert u1["id"] == "u0001" and u1["start"] == 22.875 and u1["end"] == 25.8
    assert u1["segment_ids"] == ["s00007", "s00007"] and u1["text"] == "các vị đồng tu Xin chào mọi người"
    assert u1["words"] == 8
    assert u1["break_before"] == {"kind": "content_edge", "seconds": None}
    assert u1["break_after"] == {"kind": "silence", "seconds": 5.125}  # 25.8-28.186 + 28.186-30.925 merged
    # the 12.5 s silence at 65-77 is a hard break between u0002 and u0003
    u2, u3 = doc["units"][1:3]
    assert u2["end"] == 65.148 and u2["break_after"] == {"kind": "hard_break", "seconds": 12.524}
    assert u3["start"] == 77.672 and u3["break_before"] == u2["break_after"]
    last = doc["units"][-1]
    assert last["segment_ids"][1] == "s00814" and last["break_after"]["kind"] == "content_edge"
    assert last["end"] <= 3554.6


def test_music_label_edges_use_nearest_silence_and_never_enter_the_music():
    _, _, doc = real_run()
    by_seg = {u["segment_ids"][0]: u for u in doc["units"]}
    # speech resumes after the 131-173 s music interlude at the end of the silence around s00029
    after = by_seg["s00029"]
    assert after["start"] == 173.7 and after["break_before"] == {"kind": "hard_break", "seconds": None}
    # s00275 [âm nhạc] 1248.15-1249.76: unit before is clamped to the label start
    before = next(u for u in doc["units"] if u["segment_ids"][1] == "s00274")
    assert before["end"] == 1248.15 and before["break_after"]["kind"] == "hard_break"
    labels = [(s["start"], s["end"]) for s in real_segments() if s["kind"] == "non_speech"]
    for c in doc["candidates"]:
        assert not any(a < c["source_end"] and b > c["source_start"] for a, b in labels)


def test_stretch_without_speech_between_cuts_is_merged_or_skipped():
    # 2 music labels with no speech in between -> nothing between them becomes a unit
    segments = [seg(1, 0.0, 80.0), seg(2, 80.0, 82.0, kind="non_speech"), seg(3, 90.0, 92.0, kind="non_speech"),
                seg(4, 92.0, 300.0)]
    w = detect_content_window(segments, [], 300.0, CFG)
    assert (w.start, w.end) == (0.0, 300.0)
    units = build_units(segments, [], find_cut_points(segments, [], w, CFG), CFG)
    assert [(u.segments[0]["id"], u.before.kind, u.after.kind) for u in units] == [
        ("s00001", "content_edge", "hard_break"), ("s00004", "hard_break", "content_edge")]
    # two aligned silences with no caption midpoint between them -> the shorter cut is dropped
    segments = [seg(1, 0.0, 20.0), seg(2, 24.0, 60.0)]  # s00002 start aligns with both silences
    silences = [(20.0, 24.0), (24.4, 28.0)]
    w = detect_content_window(segments, silences, 60.0, CFG)
    cuts = find_cut_points(segments, silences, w, CFG)
    assert [c.kind for c in cuts] == ["content_edge", "silence", "silence", "content_edge"]
    units = build_units(segments, silences, cuts, CFG)
    assert [(u.segments[0]["id"], u.start, u.end) for u in units] == [("s00001", 0, 20000), ("s00002", 24000, 60000)]
    assert units[0].after.seconds == 4.0 and units[0].after is units[1].before


# --- AC3/AC4: candidates ----------------------------------------------------------------------------

def test_real_candidates_satisfy_ac3_ac4_independently():
    shots, sil_doc, doc = real_run()
    silences = [(s["start"], s["end"]) for s in sil_doc["silences"]]
    assert doc["stats"]["candidates"] == len(doc["candidates"]) > 50
    independent_check(doc, real_segments(), silences, shots["changes"])
    assert any(c["trims"] for c in doc["candidates"]) and any(c["in_target"] for c in doc["candidates"])
    assert doc["stats"]["in_target"] == sum(c["in_target"] for c in doc["candidates"])


def test_plan_trims_keeps_exactly_max_pause():
    silences = [(10.0, 12.0), (20.0, 21.0), (30.0, 31.001), (40.0, 45.0), (58.0, 62.0)]
    assert plan_trims(5.0, 60.0, silences, 1.0) == [
        [10.5, 11.5],  # 2.0 s -> 1.0 s kept
        # 1.0 s silence: not trimmed
        [30.5, 30.501],  # 1.001 s -> 1.0 s kept
        [40.5, 44.5],
        [58.5, 59.5],  # only the part inside the clip counts
    ]
    assert plan_trims(0.0, 100.0, [(10.0, 11.0)], 1.0) == []


def test_duration_is_after_trims_and_bounds_apply():
    segments, silences, duration = lecture(12)  # 20 s units, 4 s gaps, 2 s pause inside each unit
    shots = shots_document("x", "s", [], duration, CFG)["shots"]
    w = detect_content_window(segments, silences, duration, CFG)
    units = build_units(segments, silences, find_cut_points(segments, silences, w, CFG), CFG)
    assert len(units) == 12
    cands = generate_candidates(units, silences, [], shots, CFG)
    validate(cands, units, w, silences, [], shots, CFG)
    by_len = {}
    for c in cands:
        n = int(c["unit_ids"][1][1:]) - int(c["unit_ids"][0][1:]) + 1
        by_len.setdefault(n, c)
    # one unit: 20 s speech (pause 2 s -> 1 s) + pads = 19.6 s < 30 -> not a candidate
    assert 1 not in by_len
    two = by_len[2]  # 2 units: 44 s source + 0.6 pad; trims: 2x1 s inner + 3 s of the 4 s gap
    assert two["source_duration"] == 44.6 and two["duration"] == 39.6 and not two["in_target"]
    assert (two["source_start"], two["source_end"]) == (4.7, 49.3)
    assert two["trims"] == [[14.5, 15.5], [25.5, 28.5], [38.5, 39.5]]
    assert max(by_len) == 9  # 9 units = 179.6 s after trims; 10 units would exceed 180
    assert all(30 <= c["duration"] <= 180 for c in cands)
    assert [c["id"] for c in cands] == [f"c{n:05d}" for n in range(1, len(cands) + 1)]
    assert [(c["source_start"], c["source_end"]) for c in cands] == sorted(
        (c["source_start"], c["source_end"]) for c in cands)


def test_shot_change_near_an_edge_is_rejected():
    segments, silences, duration = lecture(3)
    w = detect_content_window(segments, silences, duration, CFG)
    units = build_units(segments, silences, find_cut_points(segments, silences, w, CFG), CFG)
    start = units[0].start - 300  # ms; first candidate starts at unit start - pad
    first = lambda changes: [c for c in generate_candidates(
        units, silences, changes, shots_document("x", "s", changes, duration, CFG)["shots"], CFG)
        if c["unit_ids"][0] == "u0001"]
    base = first([])
    assert base
    near = first([round((start + 500) / 1000, 3)])  # 0.5 s after the clip start
    assert near == []
    far = first([round((start + 1500) / 1000, 3)])  # 1.5 s after the clip start: allowed
    assert [c["source_start"] for c in far] == [c["source_start"] for c in base]
    assert far[0]["shot_changes"] == [round((start + 1500) / 1000, 3)]
    assert far[0]["shot_ids"] == ["h0001", "h0002"]


def test_candidates_never_cross_a_hard_break():
    segments, silences, duration = lecture(10)
    silences[7] = (silences[7][0], silences[7][0] + 12.0)  # gap after unit 4 becomes 12 s
    for s in segments[8:]:
        s["start"] += 8.0
        s["end"] += 8.0
    silences = [silences[k] if k <= 7 else (silences[k][0] + 8, silences[k][1] + 8) for k in range(len(silences))]
    duration += 8
    w = detect_content_window(segments, silences, duration, CFG)
    units = build_units(segments, silences, find_cut_points(segments, silences, w, CFG), CFG)
    assert units[3].after.kind == "hard_break" and units[3].after.seconds == 12.0
    cands = generate_candidates(units, silences, [], shots_document("x", "s", [], duration, CFG)["shots"], CFG)
    for c in cands:
        a, b = int(c["unit_ids"][0][1:]), int(c["unit_ids"][1][1:])
        assert b <= 4 or a >= 5


# --- AC5: references / stable ids; validation catches bugs ---------------------------------------------

def test_references_are_valid_and_output_is_stable():
    shots, sil_doc, doc = real_run()
    again = real_run()
    assert again == (shots, sil_doc, doc)
    unit_ids = {u["id"] for u in doc["units"]}
    seg_ids = {s["id"] for s in real_segments() if s["kind"] == "speech"}
    shot_ids = {h["id"] for h in shots["shots"]}
    for c in doc["candidates"]:
        assert set(c["unit_ids"]) <= unit_ids and set(c["segment_ids"]) <= seg_ids
        assert c["shot_ids"] and set(c["shot_ids"]) <= shot_ids


def test_validation_rejects_a_tampered_candidate():
    segments, silences, duration = lecture(6)
    shots = shots_document("x", "s", [], duration, CFG)["shots"]
    w = detect_content_window(segments, silences, duration, CFG)
    units = build_units(segments, silences, find_cut_points(segments, silences, w, CFG), CFG)
    cands = generate_candidates(units, silences, [], shots, CFG)
    validate(cands, units, w, silences, [], shots, CFG)
    for mutate in (lambda c: c.update(duration=c["duration"] + 1),
                   lambda c: c.update(trims=[]),
                   lambda c: c.update(source_start=c["source_start"] - 1),
                   lambda c: c.update(in_target=not c["in_target"])):
        bad = [dict(c) for c in cands]
        mutate(bad[0])
        with pytest.raises(AnalysisError, match="candidate validation failed"):
            validate(bad, units, w, silences, [], shots, CFG)


def test_params_change_results():
    _, _, base = real_run()
    _, _, strict = real_run(replace(CFG, min_boundary_silence=5.0))
    assert strict["stats"]["units"] < base["stats"]["units"]
    assert strict["params"]["min_boundary_silence"] == 5.0
