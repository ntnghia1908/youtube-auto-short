"""Selection pure logic: windows (AC1), prompt (AC2), mapping (AC3), final choice (AC4), validation."""

import json

import pytest

from auto_short.selection.logic import (
    SelectionError,
    _split,
    ResponseError,
    build_windows,
    dedupe,
    map_proposals,
    parse_response,
    select_clips,
    unit_durations,
    validate_clips,
)
from auto_short.selection.prompt import (
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    cumulative_marks,
    prompt_sha256,
    prompt_texts,
    render_user_prompt,
)
from selection_helpers import proposal, real_docs, response, synthetic_docs


@pytest.fixture(scope="module")
def syn():
    return synthetic_docs()


@pytest.fixture(scope="module")
def real():
    return real_docs()


def _durations(cand_doc, sil_doc):
    return unit_durations(cand_doc["units"], [(s["start"], s["end"]) for s in sil_doc["silences"]],
                          cand_doc["params"]["max_pause"])


def _by_units(cand_doc):
    return {tuple(c["unit_ids"]): c for c in cand_doc["candidates"]}


# --- AC1 / B2: windows --------------------------------------------------------------------------------

def test_windows_split_at_hard_breaks_and_content_edges(syn):
    cand_doc, _, _ = syn
    windows = build_windows(cand_doc["units"], cand_doc["candidates"], 2500)
    assert [(w.id, w.unit_ids) for w in windows] == [("w01", ["u0001", "u0006"]), ("w02", ["u0007", "u0011"])]
    assert sum(len(w.candidates) for w in windows) == len(cand_doc["candidates"])
    assert all(c["unit_ids"][0] >= "u0007" for c in windows[1].candidates)


def test_real_video_extract_windows(real):
    # Fixture extract of rbjfCfFq3Dk (0-420 s, 1230-1360 s, 3530-end); the full video gives
    # 11 windows [2, 4, 19, 40, 4, 2, 13, 27, 9, 26, 49] (checked on the real run).
    cand_doc, _, _ = real
    windows = build_windows(cand_doc["units"], cand_doc["candidates"], 2500)
    assert [len(w.units) for w in windows] == [2, 4, 17, 4, 2, 2]
    assert [w.id for w in windows] == [f"w{k:02d}" for k in range(1, 7)]
    assert [len(w.candidates) for w in windows][-2:] == [0, 0]  # no candidate -> no AI call
    assert sum(len(w.candidates) for w in windows) == len(cand_doc["candidates"])
    for w in windows:  # every window starts at a non-silence boundary and ends before one
        assert w.units[0]["break_before"]["kind"] != "silence"
        assert w.units[-1]["break_after"]["kind"] != "silence"
        assert all(u["break_before"]["kind"] == "silence" for u in w.units[1:])


def test_long_windows_split_overlapping_without_losing_candidates(real):
    cand_doc, _, _ = real
    windows = build_windows(cand_doc["units"], cand_doc["candidates"], 380)
    assert {w.parent for w in windows} == {f"w{k:02d}" for k in range(1, 7)}
    subs = [w for w in windows if w.id != w.parent]
    assert subs and all(w.words <= 380 for w in subs) and all(w.parent == "w03" for w in subs)
    covered = {c["id"] for w in windows for c in w.candidates}
    assert covered == {c["id"] for c in cand_doc["candidates"]}
    for w in windows:  # candidates listed for a window lie inside it
        ids = [u["id"] for u in w.units]
        assert all(c["unit_ids"][0] in ids and c["unit_ids"][1] in ids for c in w.candidates)
    assert [w.id for w in subs] == ["w03.1", "w03.2"]


def test_split_overlaps_so_every_candidate_fits_one_range():
    spans = [(0, 3), (2, 5), (4, 8), (7, 9)]
    ranges = _split(0, 10, spans, [10] * 10, 50, "w01")
    assert ranges == [(0, 4), (2, 6), (4, 8), (7, 9)]
    assert all(any(a <= i and j <= b for a, b in ranges) for i, j in spans)
    assert _split(0, 10, [(0, 2)], [10] * 10, 50, "w01") == [(0, 4), (5, 9)]  # nothing pending: no overlap


def test_window_split_fails_when_a_candidate_cannot_fit(syn):
    cand_doc, _, _ = syn
    with pytest.raises(SelectionError, match="max_window_words"):
        build_windows(cand_doc["units"], cand_doc["candidates"], 12)


# --- AC2 / B3: prompt -----------------------------------------------------------------------------------

def test_unit_durations_use_cp4_trims(syn, real):
    cand_doc, sil_doc, _ = syn
    d = _durations(cand_doc, sil_doc)
    assert d["u0002"] == 19.0  # 20 s with a 2 s inner pause shortened to 1 s
    # consistent with candidate duration: 2 units + 1 trimmed boundary + 2 * pad
    c = _by_units(cand_doc)[("u0002", "u0003")]
    assert c["duration"] == round(d["u0002"] + d["u0003"] + 1.0 + 0.6, 3)
    rc, rs, _ = real
    rd = _durations(rc, rs)
    assert all(0 < rd[u["id"]] <= u["end"] - u["start"] + 1e-9 for u in rc["units"])


def test_user_prompt_lists_units_with_trimmed_duration_and_boundary(syn):
    cand_doc, sil_doc, meta = syn
    windows = build_windows(cand_doc["units"], cand_doc["candidates"], 2500)
    text = render_user_prompt("v1", title=meta["title"], window_id="w01", units=windows[0].units,
                              durations=_durations(cand_doc, sil_doc))
    lines = text.splitlines()
    assert lines[0] == "Video: Bài giảng thử"
    assert lines[1].startswith("Đoạn w01: 6 unit,") and "Trước đoạn: đầu nội dung" in lines[1]
    assert "Sau đoạn: ngắt cứng" in lines[1]
    assert "u0001 | 19.0 | đầu nội dung | ý thứ 1 phần đầu chúng ta học kinh ý thứ 1 phần cuối xin nhớ kỹ" in lines
    assert any(line.startswith("u0002 | 19.0 | lặng 4.0 s | ý thứ 2") for line in lines)


def test_v2_prompt_cumulative_marks_match_candidate_durations(syn, real):
    cand_doc, sil_doc, meta = syn
    windows = build_windows(cand_doc["units"], cand_doc["candidates"], 2500)
    text = render_user_prompt("v2", title=meta["title"], window_id="w02", units=windows[1].units,
                              durations=_durations(cand_doc, sil_doc), max_pause=1.0, pad=0.3)
    assert "thời lượng đoạn = đến(last_unit) − từ(first_unit)" in text
    assert "u0007 | từ 0.0 | đến 19.6 | ngắt cứng (nhạc/nhãn hoặc lặng dài) | ý thứ 7" in text
    assert "u0011 | từ 80.0 | đến 99.6 | lặng 4.0 s | ý thứ 11" in text  # c00016 u0007-u0011 = 99.6 s
    # on the real extract: to(b) - from(a) == estimate, within 0.4 s of every candidate duration
    for doc, sil in (syn[:2], real[:2]):
        durs = _durations(doc, sil)
        for w in build_windows(doc["units"], doc["candidates"], 2500):
            marks = dict(zip([u["id"] for u in w.units], cumulative_marks(w.units, durs, 1.0, 0.3)))
            for c in w.candidates:
                a, b = c["unit_ids"]
                assert abs(marks[b][1] - marks[a][0] - c["duration"]) <= 0.4, c["id"]


def test_system_prompt_and_schema():
    assert PROMPT_VERSION == "v2"
    for version in ("v1", "v2"):
        system, _ = prompt_texts(version)
        for needle in ("TRỌN MỘT Ý", "30–180 giây", "60–90 giây", "không có dấu câu", "Thà không đề xuất"):
            assert needle in system
    v2 = prompt_texts("v2")[0]
    assert '"đến" của last_unit − "từ" của first_unit' in v2 and "start_complete PHẢI là false" in v2
    assert '"thế là", "do đó", "còn"' in v2
    # v1 is kept verbatim for comparison
    assert prompt_sha256("v1") == "0ff963d1f415c0a74c7b320d772ab8400d282ecc848f4903bfd05141e4bf4d7c"
    assert prompt_sha256("v2") != prompt_sha256("v1")
    item = RESPONSE_SCHEMA["properties"]["clips"]["items"]
    assert set(item["required"]) == {"first_unit", "last_unit", "score", "start_complete", "end_complete",
                                     "topic", "reason"}
    assert len(prompt_sha256("v1")) == 64
    with pytest.raises(ValueError, match="unknown prompt_version"):
        prompt_texts("v9")


# --- response parsing ------------------------------------------------------------------------------------

def test_parse_response_ok_and_errors():
    assert parse_response(response(proposal("u0001", "u0002"))) == [proposal("u0001", "u0002")]
    assert parse_response('{"clips": []}') == []
    for bad in ("not json", "[]", '{"clip": []}', '{"clips": [1]}',
                response(dict(proposal("u1", "u2"), score="8")),
                response(dict(proposal("u1", "u2"), score=True)),
                response(dict(proposal("u1", "u2"), score=11)),
                response({k: v for k, v in proposal("u1", "u2").items() if k != "reason"})):
        with pytest.raises(ResponseError):
            parse_response(bad)


# --- AC3 / B4: mapping ---------------------------------------------------------------------------------

def test_map_proposals_valid_and_rejected(syn):
    cand_doc, sil_doc, _ = syn
    w01 = build_windows(cand_doc["units"], cand_doc["candidates"], 2500)[0]
    props = [proposal("u0002", "u0005"), proposal("u0005", "u0007"), proposal("u0005", "u0002"),
             proposal("u0003", "u0005"), proposal("u0001", "u0001"), proposal("u0099", "u0002")]
    recs = map_proposals(props, w01, _by_units(cand_doc), _durations(cand_doc, sil_doc), cand_doc["params"])
    assert [r["status"] for r in recs] == ["valid"] + ["rejected"] * 5
    assert recs[0]["candidate_id"] == "c00008" and recs[0]["reject_reason"] is None
    assert recs[0]["window"] == "w01"
    reasons = [r["reject_reason"] for r in recs[1:]]
    assert reasons[0] == "unit not in window w01: u0007"
    assert reasons[1] == "last_unit before first_unit"
    assert reasons[2].startswith("no candidate with unit_ids [u0003, u0005]")  # shot guard
    assert "~19.6 s" in reasons[3] and "30-180 s" in reasons[3]
    assert reasons[4] == "unit not in window w01: u0099"
    assert all(r["candidate_id"] is None for r in recs[1:])


def test_dedupe_keeps_best_score_then_first():
    recs = [dict(proposal("a", "b", 7), status="valid", candidate_id="c1", window="w01.1"),
            dict(proposal("a", "b", 9), status="valid", candidate_id="c1", window="w01.2"),
            dict(proposal("a", "b", 9), status="valid", candidate_id="c1", window="w01.3")]
    dedupe(recs)
    assert [r["status"] for r in recs] == ["rejected", "valid", "rejected"]
    assert recs[0]["reject_reason"] == "duplicate of proposal in w01.2"
    assert recs[2]["reject_reason"] == "duplicate of proposal in w01.2"


# --- AC4 / B6: final choice --------------------------------------------------------------------------

def _records(cand_doc, *items):
    by_id = {c["id"]: c for c in cand_doc["candidates"]}
    out = []
    for cid, score, start, end in items:
        c = by_id[cid]
        out.append(dict(proposal(*c["unit_ids"], score, start, end), window="w01", status="valid",
                        candidate_id=cid, reject_reason=None))
    return out


def test_select_priority_overlap_limit_and_ids(syn):
    cand_doc, _, _ = syn
    by_id = {c["id"]: c for c in cand_doc["candidates"]}
    recs = _records(cand_doc,
                    ("c00001", 9, True, True),    # 4.7-49.3
                    ("c00008", 9, True, True),    # 28.7-121.3 in_target, overlaps c00001
                    ("c00012", 8, True, True),    # 100.7-145.3 overlaps c00008
                    ("c00017", 10, True, False),  # ineligible: end not complete
                    ("c00020", 6, True, True),    # ineligible: score
                    ("c00013", 7, True, True),    # 164.7-209.3
                    ("c00022", 7, True, True))    # 236.7-281.3
    clips = select_clips(recs, by_id, max_clips=25, min_score=7)
    # score 9 tie: in_target c00008 first -> c00001 overlaps; c00012 overlaps c00008
    assert [c["candidate_id"] for c in clips] == ["c00008", "c00013", "c00022"]
    assert [c["id"] for c in clips] == ["k01", "k02", "k03"]
    assert [r["status"] for r in recs] == ["overlapped", "selected", "overlapped", "ineligible", "ineligible",
                                           "selected", "selected"]
    assert recs[0]["reject_reason"] == "overlaps selected c00008"
    assert recs[3]["reject_reason"] == "end not complete" and recs[4]["reject_reason"] == "score < 7"
    clip = clips[0]
    assert list(clip) == ["id", "candidate_id", "source_start", "source_end", "source_duration", "duration",
                          "in_target", "unit_ids", "segment_ids", "score", "start_complete", "end_complete",
                          "topic", "reason", "window"]
    for k in ("source_start", "source_end", "source_duration", "duration", "in_target", "unit_ids", "segment_ids"):
        assert clip[k] == by_id["c00008"][k]
    validate_clips(clips, cand_doc, max_clips=25, min_score=7)

    # max_clips: the lower-priority eligible proposal is over_limit
    recs = _records(cand_doc, ("c00013", 7, True, True), ("c00001", 8, True, True))
    clips = select_clips(recs, by_id, max_clips=1, min_score=7)
    assert [c["candidate_id"] for c in clips] == ["c00001"]
    assert [r["status"] for r in recs] == ["over_limit", "selected"]

    # same score and in_target: earlier source_start wins
    recs = _records(cand_doc, ("c00006", 8, True, True), ("c00001", 8, True, True))
    assert [c["candidate_id"] for c in select_clips(recs, by_id, max_clips=25, min_score=7)] == ["c00001"]

    assert select_clips([], by_id, max_clips=25, min_score=7) == []


def test_touching_clips_do_not_overlap(syn):
    cand_doc, _, _ = syn
    by_id = {c["id"]: c for c in cand_doc["candidates"]}
    a = dict(by_id["c00001"])
    b = dict(by_id["c00006"], source_start=a["source_end"])
    recs = [dict(proposal("x", "y"), window="w01", status="valid", candidate_id=c["id"], reject_reason=None)
            for c in (a, b)]
    clips = select_clips(recs, {"c00001": a, "c00006": b}, max_clips=25, min_score=7)
    assert len(clips) == 2


# --- B8: validation ----------------------------------------------------------------------------------

def test_validate_clips_rejects_violations(syn):
    cand_doc, _, _ = syn
    by_id = {c["id"]: c for c in cand_doc["candidates"]}
    recs = _records(cand_doc, ("c00001", 8, True, True), ("c00013", 8, True, True))
    good = select_clips(recs, by_id, max_clips=25, min_score=7)
    validate_clips(good, cand_doc, max_clips=25, min_score=7)

    def bad(mutate, needle, **kw):
        clips = json.loads(json.dumps(good))
        mutate(clips)
        with pytest.raises(SelectionError, match=needle):
            validate_clips(clips, cand_doc, **({"max_clips": 25, "min_score": 7} | kw))

    bad(lambda c: c[0].update(candidate_id="c99999"), "does not exist")
    bad(lambda c: c[0].update(source_end=60.0), "source_end does not match")
    bad(lambda c: c[1].update(id="k05"), "id must be k02")
    bad(lambda c: c.reverse(), "id must be k01")
    bad(lambda c: c[0].update(score=5), "not eligible")
    bad(lambda c: None, "max_clips", max_clips=1)
    bad(lambda c: c.__setitem__(1, dict(c[0], id="k02")), "overlaps k01")
