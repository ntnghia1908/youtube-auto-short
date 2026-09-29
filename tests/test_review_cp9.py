"""CP9: ``review.json`` ``cuts`` / ``added`` (C1), range from caption lines + nudges (C3), validity (C4), trims
(C5) and the per-episode functions (transcript, proposals, preview, set / reset cut, add Short, titles of an
added Short). No media, no AI."""

import json
import pytest

from auto_short.config import Config, RenderConfig, WorkspaceConfig
from auto_short.review import (ArchivedError, ReviewError, list_titles, reject_clip, reset_title, restore_clip,
                               set_alternative, set_title)
from auto_short.review import cuts as C
from auto_short.review import shorts as S
from auto_short.review.logic import (added_entries, added_origin, check_review, empty_review, next_added_id,
                                     resolve_cuts, resolve_titles, with_added, with_cut, without_added, without_cut)
from cp9_helpers import CONTENT, EID, PARAMS, make_cp9_episode, seg, timeline

ORDER = ["k01", "k02"]


def _added(clip="m01", cand="manual", source="transcript", start=10.0, end=50.0, title=None, ai=None, alts=()):
    return {"clip_id": clip, "candidate_id": cand, "start": start, "end": end, "source": source, "title": title,
            "ai_title": ai, "alternatives": [{"title": a, "evidence": "e"} for a in alts]}


def _dump(doc) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False)


# --- C1 schema ---------------------------------------------------------------------------------------------------

def test_check_review_accepts_cuts_and_added_in_order():
    base = empty_review(EID)
    doc = {**base, "rejected": [{"clip_id": "m01", "candidate_id": "manual"}],
           "cuts": [{"clip_id": "k01", "candidate_id": "c1", "start": 1.5, "end": 40.25}],
           "added": [_added(title="Tâm", ai="Tâm", alts=["Khác"])]}
    assert check_review(doc, EID) is doc
    assert check_review({**base, "added": [_added()]}, EID)  # untitled added Short
    assert check_review({**base, "cuts": doc["cuts"]}, EID)


@pytest.mark.parametrize("extra, msg", [
    ({"added": [], }, "non-empty array"),
    ({"cuts": []}, "non-empty array"),
    ({"added": [_added()], "cuts": [{"clip_id": "k01", "candidate_id": "c1", "start": 1, "end": 2}]}, "in this order"),
    ({"cuts": [{"clip_id": "k01", "candidate_id": "c1", "start": 2.0, "end": 2.0}]}, "start < end"),
    ({"cuts": [{"clip_id": "k01", "candidate_id": "c1", "start": 1.2345, "end": 3.0}]}, "3 decimals"),
    ({"cuts": [{"clip_id": "k01", "candidate_id": "c1", "start": True, "end": 3.0}]}, "seconds"),
    ({"cuts": [{"clip_id": "k01", "candidate_id": "c1", "start": 1.0}]}, r"cuts\[0\] must be an object"),
    ({"cuts": [{"clip_id": "k01", "candidate_id": "c1", "start": 1, "end": 2}] * 2}, "duplicate cut"),
    ({"added": [_added(clip="k99")]}, "m01, m02"),
    ({"added": [_added(cand="c00003")]}, "goes with source"),
    ({"added": [_added(cand="manual", source="proposal")]}, "goes with source"),
    ({"added": [_added(source="ai")]}, "source 'ai'"),
    ({"added": [_added(title=" Tâm ")]}, "normalized"),
    ({"added": [_added(title="")]}, "normalized"),
    ({"added": [{**_added(), "alternatives": ["x"]}]}, "alternatives"),
    ({"added": [_added(), _added()]}, "duplicate added"),
])
def test_check_review_rejects_bad_cuts_added(extra, msg):
    with pytest.raises(ReviewError, match=msg):
        check_review({**empty_review(EID), **extra}, EID)


def test_cut_and_added_round_trip_byte_identical():
    """AC1: removing the last cut / added Short gives back the file of before (CP8.2 shape)."""
    before = empty_review(EID)
    doc = with_cut(before, ORDER, clip_id="k02", candidate_id="c2", start=1.0, end=40.0)
    doc = with_cut(doc, ORDER, clip_id="k01", candidate_id="c1", start=2.0, end=30.0)
    assert list(doc) == ["schema_version", "episode_id", "titles", "cuts"]
    assert [e["clip_id"] for e in doc["cuts"]] == ["k01", "k02"]
    doc = with_added(doc, ORDER + ["m02"], _added(clip="m02"))
    doc = with_added(doc, ORDER + ["m01", "m02"], _added(clip="m01"))
    assert list(doc)[-1] == "added" and [e["clip_id"] for e in doc["added"]] == ["m01", "m02"]
    doc = with_cut(doc, ORDER + ["m01", "m02"], clip_id="m02", candidate_id="manual", start=3.0, end=45.0)
    assert [e["clip_id"] for e in doc["cuts"]] == ["k01", "k02", "m02"]
    check_review(doc, EID)
    for cid in ("m01", "m02"):
        doc, removed = without_added(doc, ORDER, cid)
        assert removed
    for cid in ("k01", "k02"):
        doc, removed = without_cut(doc, ORDER, cid)
        assert removed
    assert _dump(doc) == _dump(before)
    assert without_cut(doc, ORDER, "k01")[1] is False


def test_next_added_id_never_reuses():
    assert next_added_id([]) == "m01"
    assert next_added_id(["k01", "m01", "m03"]) == "m04"
    assert next_added_id({"m09"}) == "m10" and next_added_id({"m99"}) == "m100"


def test_added_origin_and_resolve():
    assert added_origin(_added()) is None
    assert added_origin(_added(title="A", ai="A", alts=["B"])) == "ai"
    assert added_origin(_added(title="B", ai="A", alts=["B"])) == "alternative"
    assert added_origin(_added(title="C", ai="A", alts=["B"])) == "manual"
    assert added_origin(_added(title="C")) == "manual"  # AI failed, typed by hand
    review = {**empty_review(EID), "added": [_added(title="C", ai="A"), _added(clip="m02")]}
    titles = [{"clip_id": "k01", "candidate_id": "c1", "title": "T", "status": "titled"}]
    resolved, warnings = resolve_titles(titles + added_entries(review), review)
    assert [(r.clip_id, r.title, r.origin) for r in resolved] == [("k01", "T", "ai"), ("m01", "C", "manual"),
                                                                  ("m02", None, None)]
    assert warnings == []


def test_resolve_cuts_key_rule():
    """C1 / AC6: a cut made for another candidate (selection re-run) is ignored with a warning."""
    review = {**empty_review(EID), "cuts": [{"clip_id": "k01", "candidate_id": "c1", "start": 1.0, "end": 2.0},
                                            {"clip_id": "k02", "candidate_id": "cOLD", "start": 3.0, "end": 4.0},
                                            {"clip_id": "k09", "candidate_id": "c9", "start": 3.0, "end": 4.0}]}
    cuts, warnings = resolve_cuts([("k01", "c1"), ("k02", "cNEW")], review)
    assert cuts == {"k01": (1.0, 2.0)}
    assert warnings == ["cut of clip k02 ignored: made for candidate cOLD, the clip is now candidate cNEW "
                        "(selection re-run)", "cut of clip k09 ignored: no such clip"]


# --- C3 / C4 / C5 pure range rules ----------------------------------------------------------------------------

def _ep(params=None, shots=()):
    segments, silences = timeline()
    return C.Episode(segments, [tuple(x) for x in silences], params or dict(PARAMS), CONTENT, list(shots))


def test_base_points_follow_a6():
    ep = _ep()
    segs = ep.segments
    n1 = ep.index(seg(segs, 2)["id"])  # line 2 starts 14.5, silence [14.0, 14.5] before it
    assert C.base_start(ep, n1) == 14200  # silence end 14.5 - pad 0.3
    n8 = ep.index(seg(segs, 8)["id"])  # line 8 ends 47.0, silence [47.0, 47.5] after it
    assert C.base_end(ep, n8) == 47300
    assert C.base_start(ep, 0) == 10000  # line 1 at the content start: no silence, clamped to the window
    # captions that touch (no silence): the edge is the caption time, never into the neighbour line
    contiguous = C.Episode([{"id": "a", "start": 20.0, "end": 24.0, "kind": "speech", "text": "a"},
                            {"id": "b", "start": 24.0, "end": 28.0, "kind": "speech", "text": "b"}],
                           [], dict(PARAMS), (0.0, 100.0))
    assert C.base_start(contiguous, 1) == 24000 and C.base_end(contiguous, 0) == 24000


def test_resolve_range_nudges_and_limits():
    ep = _ep()
    a, b = seg(ep.segments, 2)["id"], seg(ep.segments, 9)["id"]
    assert C.resolve_range(ep, a, b) == (14200, 51800)
    assert C.resolve_range(ep, a, b, 0.4, -0.2) == (14600, 51600)
    assert C.resolve_range(ep, a, b, -2.0, 2.0) == (12200, 53800)
    for bad in (0.3, 2.2, "0.2", True, None):
        with pytest.raises(ReviewError, match="bội của 0.2|số giây"):
            C.resolve_range(ep, a, b, bad)
    with pytest.raises(ReviewError, match="ngoài phần nội dung"):  # line 1 at 10.0 = content start
        C.resolve_range(ep, seg(ep.segments, 1)["id"], b, -0.2)
    with pytest.raises(ReviewError, match="trước dòng đầu"):
        C.resolve_range(ep, b, a)
    with pytest.raises(ReviewError, match="không phải lời nói"):
        C.resolve_range(ep, ep.segments[ep.index(seg(ep.segments, 40)["id"]) + 1]["id"], b)


def test_resolve_range_keeps_current_point_of_unchanged_line():
    """Editing a Short: its first / last line unchanged -> its current start / end is the base (C3)."""
    ep = _ep()
    a, b = seg(ep.segments, 2)["id"], seg(ep.segments, 9)["id"]
    current = (14.05, 51.95)  # e.g. a head cut / an earlier nudge, not the C3 point
    assert C.resolve_range(ep, a, b, 0.2, 0, current=current) == (14250, 51950)
    c = seg(ep.segments, 3)["id"]  # new first line -> C3 point of that line
    assert C.resolve_range(ep, c, b, 0, 0, current=current)[0] == C.base_start(ep, ep.index(c))


def test_nudge_into_neighbour_line_limit():
    ep = _ep()
    segs = ep.segments
    # line 12 starts right after a 0.5 s silence: base = start - 0.3; -2.0 s stays within 2 s of line 11's end
    a, b = seg(segs, 12)["id"], seg(segs, 20)["id"]
    assert C.resolve_range(ep, a, b, -2.0)[0] == C.ms(seg(segs, 12)["start"]) - 2300
    fake = C.Episode([{"id": "p", "start": 20.0, "end": 24.0, "kind": "speech", "text": "p"},
                      {"id": "q", "start": 24.5, "end": 28.0, "kind": "speech", "text": "q"}],
                     [(24.0, 24.5)], {**PARAMS, "boundary_pad": 0.0}, (0.0, 100.0))
    assert C.resolve_range(fake, "q", "q", -2.0, 0, current=(26.0, 28.0))[0] == 24000
    # a current start already 1 s into line p, then -2.0 s: 3 s into p -> refused (add the line instead)
    with pytest.raises(ReviewError, match="lấn vào dòng trước quá 2 s"):
        C.resolve_range(fake, "q", "q", -2.0, 0, current=(23.0, 28.0))
    with pytest.raises(ReviewError, match="điểm cuối phải sau"):
        C.resolve_range(fake, "q", "q", 2.0, -2.0)


def test_evaluate_c4_rules_and_c5_trims():
    ep = _ep()
    segs = ep.segments
    r = C.evaluate(ep, 14200, 51800)  # lines 2..9
    assert r.error is None and r.start_segment == seg(segs, 2)["id"] and r.end_segment == seg(segs, 9)["id"]
    # the 2.0 s pause after line 5 is trimmed to 1.0 s (CP4 A8), 0.5 s pauses are kept
    assert r.trims == [[32.5, 33.5]] and r.duration == round(51.8 - 14.2 - 1.0, 3) and r.source_duration == 37.6
    short = C.evaluate(ep, 14200, 30000)
    assert "cần 30–180 s" in short.error and "sau khi rút khoảng lặng" in short.error
    # the [âm nhạc] label after line 40 is a hard break for a Short episode
    lab = C.evaluate(ep, C.ms(seg(segs, 35)["start"]), C.ms(seg(segs, 45)["end"]))
    assert "không phải lời nói [âm nhạc]" in lab.error
    # ... but a pause for a khai thị episode (CP8.9 A3.1 soft label)
    kt = _ep({**PARAMS, "soft_label_max_seconds": 5.0, "min_duration": 30.0, "max_duration": 600.0})
    assert C.evaluate(kt, C.ms(seg(segs, 35)["start"]), C.ms(seg(segs, 45)["end"])).error is None
    hard = C.evaluate(ep, C.ms(seg(segs, 55)["start"]), C.ms(seg(segs, 66)["end"]))
    assert "khoảng lặng dài 12 s" in hard.error
    outside = C.evaluate(ep, 5000, 51800)
    assert "ngoài phần nội dung" in outside.error


def test_evaluate_shot_warnings():
    ep = _ep(shots=[14.8, 51.2, 30.0])
    r = C.evaluate(ep, 14200, 51800)
    assert r.error is None and r.warnings == ["có chuyển cảnh trong 1 s đầu", "có chuyển cảnh trong 1 s cuối"]


def test_overlaps():
    assert C.overlaps(10.0, 20.0, [("k01", 0.0, 10.0), ("k02", 19.9, 30.0), ("k03", 12.0, 13.0)]) == ["k02", "k03"]


# --- episode functions ---------------------------------------------------------------------------------------------

@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "out"))


@pytest.fixture
def ws(cfg):
    return make_cp9_episode(cfg.workspace.dir)


def _review(ws):
    p = ws.dir / "review.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _bytes(ws):
    p = ws.dir / "review.json"
    return p.read_bytes() if p.is_file() else None


def test_transcript_view(ws, cfg):
    tv = S.transcript_view(EID, cfg)
    assert tv["content"] == {"start": 10.0, "end": 500.0} and (tv["min_duration"], tv["max_duration"]) == (30.0, 180.0)
    assert len(tv["segments"]) == 91 and list(tv["segments"][0]) == ["id", "start", "end", "kind", "text"]
    k01, k02 = tv["shorts"]
    assert (k01["clip_id"], k01["origin"], k01["cut"], k01["rejected"]) == ("k01", "ai", False, False)
    assert (k01["start_segment"], k01["end_segment"]) == ("s00001", "s00008")
    assert (k02["start_segment"], k02["end_segment"]) == ("s00021", "s00028")


def test_proposals_list(ws, cfg):
    props = S.list_proposals(EID, cfg)["proposals"]
    assert [p["candidate_id"] for p in props] == ["c00003", "c00004", "c00005"]  # selected / unmapped left out
    c3, c4, c5 = props
    assert c3["overlaps"] == ["k02"] and c3["warnings"] == ["chồng lấn k02"] and c3["error"] is None
    assert c3["topic"] == "Tâm và cảnh" and c3["score"] == 8 and c3["status"] == "overlapped"
    assert "cần 30–180 s" in c4["error"]
    # over_limit with a head cut: the range starts at the cut point (CP5 B11)
    assert c5["start"] == round(seg(timeline()[0], 50)["start"] - 0.3 + 1.0, 3) and c5["error"] is None
    assert all(p["added_as"] == [] for p in props)


def test_preview_and_set_cut_then_reset(ws, cfg):
    """AC1 / AC3: invalid -> ReviewError and review.json unchanged; reset -> byte-identical to before."""
    pv = S.preview_cut(EID, cfg, clip_id="k01", start_segment="s00001", end_segment="s00008")
    assert pv["original"] and not pv["changed"] and pv["error"] is None
    pv = S.preview_cut(EID, cfg, clip_id="k01", start_segment="s00002", end_segment="s00009", start_nudge=0.2)
    assert pv["changed"] and not pv["original"] and pv["start"] == 14.4 and pv["end"] == 51.8
    assert pv["start_text"].startswith("dòng 2 ") and pv["end_text"].startswith("dòng 9 ")
    bad = S.preview_cut(EID, cfg, clip_id="k01", start_segment="s00005", end_segment="s00009")
    assert "cần 30–180 s" in bad["error"]
    with pytest.raises(ReviewError, match="đoạn không hợp lệ: dài"):
        S.set_cut(EID, cfg, "k01", start_segment="s00005", end_segment="s00009")
    assert _bytes(ws) is None
    with pytest.raises(ReviewError, match="không có Short 'k09'"):
        S.set_cut(EID, cfg, "k09", start_segment="s00002", end_segment="s00009")

    got = S.set_cut(EID, cfg, "k01", start_segment="s00002", end_segment="s00009", start_nudge=0.2)
    assert (got["start"], got["end"]) == (14.4, 51.8)
    assert _review(ws)["cuts"] == [{"clip_id": "k01", "candidate_id": "c00001", "start": 14.4, "end": 51.8}]
    tv = S.transcript_view(EID, cfg)["shorts"][0]
    assert tv["cut"] and (tv["start"], tv["end"]) == (14.4, 51.8) and tv["start_segment"] == "s00002"
    # the current point is the base of a further nudge on the same line
    assert S.preview_cut(EID, cfg, clip_id="k01", start_segment="s00002", end_segment="s00009",
                         start_nudge=0.2)["start"] == 14.6
    # overlap with the other Short is allowed (warning only)
    wide = S.preview_cut(EID, cfg, clip_id="k01", start_segment="s00002", end_segment="s00024")
    assert wide["error"] is None and wide["overlaps"] == ["k02"]

    out = S.reset_cut(EID, cfg, "k01")
    assert out["changed"] and out["original"] and (out["start"], out["end"]) == (10.0, 47.3)
    assert _review(ws) == {"schema_version": 1, "episode_id": EID, "titles": []}
    assert S.reset_cut(EID, cfg, "k01")["changed"] is False


def test_set_cut_back_to_original_drops_entry(ws, cfg):
    S.set_cut(EID, cfg, "k02", start_segment="s00021", end_segment="s00028", end_nudge=0.4)
    assert _review(ws)["cuts"][0]["end"] == round(143.3 + 0.4, 3)
    S.set_cut(EID, cfg, "k02", start_segment="s00021", end_segment="s00028", end_nudge=-0.4)
    assert "cuts" not in _review(ws)


def test_add_short_from_proposal_and_transcript(ws, cfg):
    with pytest.raises(ReviewError, match="đoạn không hợp lệ"):
        S.add_short(EID, cfg, candidate_id="c00004")
    with pytest.raises(ReviewError, match="không có đề xuất AI 'c00001'"):
        S.add_short(EID, cfg, candidate_id="c00001")  # selected, not a remaining proposal
    with pytest.raises(ReviewError, match="cần candidate_id"):
        S.add_short(EID, cfg)
    assert _bytes(ws) is None

    a = S.add_short(EID, cfg, candidate_id="c00003")
    assert a.clip_id == "m01" and a.preview["overlaps"] == ["k02"]
    b = S.add_short(EID, cfg, start_segment="s00062", end_segment="s00070", end_nudge=-0.2)
    assert b.clip_id == "m02" and b.preview["error"] is None
    doc = _review(ws)
    assert [(e["clip_id"], e["candidate_id"], e["source"], e["title"]) for e in doc["added"]] == [
        ("m01", "c00003", "proposal", None), ("m02", "manual", "transcript", None)]
    assert doc["added"][0]["start"] == S.list_proposals(EID, cfg)["proposals"][0]["start"]
    assert S.list_proposals(EID, cfg)["proposals"][0]["added_as"] == ["m01"]
    tv = S.transcript_view(EID, cfg)["shorts"]
    assert [(x["clip_id"], x["origin"]) for x in tv] == [("k01", "ai"), ("k02", "ai"), ("m01", "added"),
                                                         ("m02", "added")]
    # an added Short can be cut and reset like an AI one (AC5)
    S.set_cut(EID, cfg, "m02", start_segment="s00062", end_segment="s00069")
    assert _review(ws)["cuts"][0]["clip_id"] == "m02"
    S.reset_cut(EID, cfg, "m02")
    assert "cuts" not in _review(ws)


def test_added_ids_never_reused(ws, cfg):
    """C1: an id seen anywhere (review.json, publish.json, render manifest) is never given again."""
    (ws.dir / "publish.json").write_text(json.dumps({"published": [{"clip_id": "m03"}]}), encoding="utf-8")
    assert S.add_short(EID, cfg, candidate_id="c00003").clip_id == "m04"


def test_added_title_edits(ws, cfg):
    """AC5: title of an added Short: AI result, manual, alternative, reset; delete / restore by key."""
    S.add_short(EID, cfg, start_segment="s00062", end_segment="s00070")
    doc = list_titles(EID, cfg)
    m01 = doc["clips"][-1]
    assert (m01["clip_id"], m01["status"], m01["title"], m01["origin"], m01["added"]) == ("m01", "untitled", None,
                                                                                          None, True)
    assert reset_title(EID, cfg, "m01") is None  # untitled: nothing to go back to
    assert S.set_added_ai_title(EID, cfg, "m01", title="Tâm an thì cảnh an",
                                alternatives=[{"title": "Giữ tâm bình an", "evidence": "e"}])
    assert not S.set_added_ai_title(EID, cfg, "m01", title="Khác", alternatives=[])  # only once
    m = _review(ws)["added"][0]
    assert (m["title"], m["ai_title"], m["alternatives"]) == ("Tâm an thì cảnh an", "Tâm an thì cảnh an",
                                                              [{"title": "Giữ tâm bình an", "evidence": "e"}])
    p = set_title(EID, cfg, "m01", "  Tâm   an ")
    assert (p.title, p.origin) == ("Tâm an", "manual") and _review(ws)["titles"] == []
    assert list_titles(EID, cfg)["clips"][-1]["override"] == {"title": "Tâm an", "origin": "manual"}
    p = set_alternative(EID, cfg, "m01", 1)
    assert (p.title, p.origin) == ("Giữ tâm bình an", "alternative")
    assert list_titles(EID, cfg)["clips"][-1]["origin"] == "alternative"
    p = reset_title(EID, cfg, "m01")
    assert (p.title, p.origin) == ("Tâm an thì cảnh an", "ai") and list_titles(EID, cfg)["clips"][-1]["override"] is None
    with pytest.raises(ReviewError, match="invalid title"):
        set_title(EID, cfg, "m01", "TIÊU ĐỀ HOA")
    assert reject_clip(EID, cfg, "m01")
    assert _review(ws)["rejected"] == [{"clip_id": "m01", "candidate_id": "manual"}]
    assert list_titles(EID, cfg)["clips"][-1]["rejected"]
    assert restore_clip(EID, cfg, "m01") and "rejected" not in _review(ws)


def test_untitled_added_gets_manual_title(ws, cfg):
    """C6: the AI failed -> untitled; a manual title makes it renderable."""
    S.add_short(EID, cfg, candidate_id="c00003")
    assert not S.set_added_ai_title(EID, cfg, "m01", title=None, alternatives=[])
    set_title(EID, cfg, "m01", "Tựa gõ tay")
    m01 = list_titles(EID, cfg)["clips"][-1]
    assert (m01["title"], m01["origin"], m01["status"]) == ("Tựa gõ tay", "manual", "untitled")


def test_archived_episode_refuses_writes(ws, cfg):
    """AC8: source cleaned up -> ArchivedError (web 409); reading still works."""
    (ws.dir / "archive.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ArchivedError):
        S.set_cut(EID, cfg, "k01", start_segment="s00002", end_segment="s00009")
    with pytest.raises(ArchivedError):
        S.reset_cut(EID, cfg, "k01")
    with pytest.raises(ArchivedError):
        S.add_short(EID, cfg, candidate_id="c00003")
    assert _bytes(ws) is None
    assert S.transcript_view(EID, cfg)["shorts"] and S.list_proposals(EID, cfg)["proposals"]


def test_selection_rerun_ignores_cut_keeps_added(ws, cfg):
    """AC6: cuts are keyed (clip_id, candidate_id); added Shorts stay."""
    S.set_cut(EID, cfg, "k01", start_segment="s00002", end_segment="s00009")
    S.add_short(EID, cfg, candidate_id="c00003")
    doc = _review(ws)
    doc["cuts"][0]["candidate_id"] = "c00099"  # as if the clip were another candidate now
    (ws.dir / "review.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tv = S.transcript_view(EID, cfg)
    assert not tv["shorts"][0]["cut"] and tv["ignored"][0].startswith("cut of clip k01 ignored")
    assert tv["shorts"][-1]["clip_id"] == "m01"


def test_khai_thi_limits(tmp_path):
    """AC7: a khai thị episode uses its own duration range (candidates.json params) and soft labels."""
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "w"), render=RenderConfig(output_dir=tmp_path / "o"))
    make_cp9_episode(cfg.workspace.dir, episode_id="cp9TestEpi1.kt",
                     params={**PARAMS, "min_duration": 60.0, "max_duration": 120.0, "target_min": 60.0,
                             "target_max": 120.0, "soft_label_max_seconds": 5.0})
    eid = "cp9TestEpi1.kt"
    assert S.transcript_view(eid, cfg)["min_duration"] == 60.0
    assert "cần 60–120 s" in S.preview_cut(eid, cfg, clip_id=None, start_segment="s00002",
                                           end_segment="s00009")["error"]
    a = S.add_short(eid, cfg, start_segment="s00036", end_segment="s00050")  # across the 3 s label
    assert a.clip_id == "m01" and 60 <= a.preview["duration"] <= 120
