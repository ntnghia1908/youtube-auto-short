"""CP8.18 unit tests: extract (D2), record, apply_tokens / apply_lines (D3), apply_paragraphs (D4), validation (D5),
edit log + stats (D6), file IO (D1), compose integration (AC 4, 5, 9). No Ollama, nothing outside tmp_path."""

from __future__ import annotations

import json

import pytest

from auto_short.config import Config, PostConfig, RenderConfig, WorkspaceConfig
from auto_short.post import corrections as C
from auto_short.post import source as post_source
from auto_short.selection.client import ChatResult
from auto_short.post import stage as post_stage
from auto_short.post import store as post_store
from post_helpers import EID, make_post_episode

NOW = "2026-10-02T08:00:00Z"


def rule(frm, to, rid="r0001", status=C.APPROVED):
    return {"id": rid, "from": frm, "to": to, "status": status, "count": 1, "examples": [],
            "created_at": NOW, "updated_at": NOW}


# --- D2 ---------------------------------------------------------------------------------------------------------

def test_extract_context_pair():  # AC1
    old = ["Pháp và suốt thế gian Pháp."]
    new = ["Pháp và xuất thế gian Pháp."]
    props, words, changed = C.extract(old, new)
    assert props == [("và suốt thế", "và xuất thế")]
    assert (words, changed) == (6, 1)


def test_extract_ignores_case_punct_insert_delete_and_big_blocks():  # AC2
    assert C.extract(["Hết thầy tất cả."], ["hết thầy, tất cả"])[0] == []
    assert C.extract(["a b c d"], ["a b x c d"])[0] == []  # insert
    assert C.extract(["a b x c d"], ["a b c d"])[0] == []  # delete
    big_old, big_new = ["a b c d e f g"], ["a p q r s t g"]
    assert C.extract(big_old, big_new)[0] == []  # 5 tokens rewritten


def test_extract_no_context_when_neighbour_changed():
    props, _w, changed = C.extract(["x a b y"], ["x c d y"])
    assert props == [("x a b y", "x c d y")]
    assert changed == 2
    props, _w, _c = C.extract(["a"], ["b"])  # no neighbour at all
    assert props == [("a", "b")]


def test_extract_edge_of_text_context_one_side():
    assert C.extract(["suốt thế gian"], ["xuất thế gian"])[0] == [("suốt thế", "xuất thế")]


def test_record_dedupe_count_and_rejected():  # AC1, AC3
    doc = C.empty_doc()
    C.record(doc, [("và suốt thế", "và xuất thế")], "e1", "k01", NOW)
    assert len(doc["rules"]) == 1
    r = doc["rules"][0]
    assert (r["id"], r["status"], r["count"]) == ("r0001", "proposed", 1)
    C.record(doc, [("và suốt thế", "và xuất thế")], "e2", "k02", "2026-10-03T00:00:00Z")
    assert len(doc["rules"]) == 1 and r["count"] == 2 and len(r["examples"]) == 2
    r["status"] = C.REJECTED
    C.record(doc, [("và suốt thế", "và xuất thế")], "e3", "k03", NOW)
    assert r["status"] == C.REJECTED and r["count"] == 3
    for n in range(10):
        C.record(doc, [("và suốt thế", "và xuất thế")], "e", f"k{n}", NOW)
    assert len(r["examples"]) == C.MAX_EXAMPLES
    C.record(doc, [("a", "b")], "e", "k", NOW)
    assert doc["rules"][1]["id"] == "r0002"


# --- D3 ---------------------------------------------------------------------------------------------------------

def test_apply_tokens_case_longest_first_non_overlapping():
    rules = [rule("hết thầy", "hết thảy", "r1"), rule("hết thầy tất cả", "hết thảy mọi thứ", "r2"),
             rule("suốt", "xuất", "r3")]
    toks = "Hết thầy tất cả suốt thế gian".split()
    new, applied, origin = C.apply_tokens(toks, rules)
    assert new == "Hết thảy mọi thứ xuất thế gian".split()
    assert applied == [{"rule_id": "r2", "at_token": 0}, {"rule_id": "r3", "at_token": 4}]
    assert origin[:3] == [0, 0, 0]


def test_apply_tokens_case_follows_original_position():
    new, _a, _o = C.apply_tokens(["Suốt", "thế"], [rule("suốt thế", "xuất thế")])
    assert new == ["Xuất", "thế"]
    new, _a, _o = C.apply_tokens(["suốt", "Thế"], [rule("suốt thế", "xuất thế")])
    assert new == ["xuất", "Thế"]
    new, _a, _o = C.apply_tokens(["Hết"], [rule("hết", "hết thảy")])  # `to` longer: reuse the last original token
    assert new == ["Hết", "Thảy"]


def test_apply_lines_keeps_line_membership_across_lines():  # AC5
    lines = ["hết thầy tất", "cả mọi người", "đều nghe"]
    new, applied = C.apply_lines(lines, [rule("tất cả", "tất thảy")])
    assert new == ["hết thầy tất thảy", "mọi người", "đều nghe"]
    assert applied == [{"rule_id": "r0001", "at_token": 2}]


def test_apply_lines_no_rules_or_no_match_unchanged():
    assert C.apply_lines(["a b"], []) == (["a b"], [])
    assert C.apply_lines(["a b"], [rule("x", "y")]) == (["a b"], [])


# --- D4 ---------------------------------------------------------------------------------------------------------

def test_apply_paragraphs_keeps_edge_punct_and_paragraph_break():
    r = rule("hết thầy tất cả", "hết thảy tất cả")
    paras = ["Ông nói: “Hết thầy tất cả, đều vậy.", "Hết thầy", "tất cả sai."]
    new, places = C.apply_paragraphs(paras, r)
    assert new[0] == "Ông nói: “Hết thảy tất cả, đều vậy."
    assert new[1:] == paras[1:] and places == 1  # no match across the paragraph break
    new, places = C.apply_paragraphs(["Hết thầy tất cả."], r)
    assert new == ["Hết thảy tất cả."] and places == 1
    new, places = C.apply_paragraphs(["x  hết thầy tất cả\ny"], r)
    assert new == ["x  hết thảy tất cả\ny"]  # whitespace untouched


# --- D5 ---------------------------------------------------------------------------------------------------------

def test_validate_phrases():
    assert C.validate_phrases("  Hết THẦY, tất cả ", "hết thảy tất cả") == ("hết thầy tất cả", "hết thảy tất cả")
    for bad in [("", "x"), ("x", ""), ("a b c d e f g h i", "x"), ("a", "A."), ("x", "a b c d e f g h i")]:
        with pytest.raises(C.CorrectionsError):
            C.validate_phrases(*bad)


def test_unique_approved_from():
    doc = {"rules": [rule("a", "b", "r1")]}
    with pytest.raises(C.CorrectionsError):
        C.check_unique_approved(doc, rule("a", "c", "r2"))
    C.check_unique_approved(doc, rule("a", "c", "r2", status=C.PROPOSED))
    C.check_unique_approved(doc, rule("a", "c", "r1"))  # itself


# --- D1 file ----------------------------------------------------------------------------------------------------

def test_load_save_missing_corrupt(tmp_path):  # AC9
    p = tmp_path / "sub" / "c.json"
    assert C.load(p) == C.empty_doc()
    assert C.approved_rules(p) == []
    doc = C.record(C.empty_doc(), [("a", "b")], "e", "k", NOW)
    C.save(p, doc)
    assert C.load(p) == doc
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(C.CorrectionsError):
        C.load(p)
    assert C.approved_rules(p) == []
    assert p.read_text(encoding="utf-8") == "{not json"  # untouched
    p.write_text(json.dumps({"schema_version": 2, "rules": []}), encoding="utf-8")
    with pytest.raises(C.CorrectionsError):
        C.load(p)


# --- D6 ---------------------------------------------------------------------------------------------------------

def test_edit_log_and_stats_window(tmp_path):  # AC8
    p = tmp_path / "post-corrections.json"
    assert C.stats(p) == {"saves": 0, "avg_changed_pct": None}
    for n in range(25):  # first 5: 100 %, last 20: 10 %
        C.append_edit_log(p, at=NOW, episode_id="e", clip_id="k", words=100, changed_words=100 if n < 5 else 10)
    lines = (tmp_path / "post-edit-log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 25 and json.loads(lines[0])["words"] == 100
    assert C.stats(p) == {"saves": 25, "avg_changed_pct": 10.0}


# --- D3 integration: compose ------------------------------------------------------------------------------------

class EchoClient:
    """Free-form reply = the chunk text, capitalised, with a final period (every word kept)."""

    def chat(self, *, model, messages, format, options, think):
        text = messages[-1]["content"].split("\n", 1)[1]
        return ChatResult(content=text[0].upper() + text[1:] + ".", thinking=None, eval_count=1,
                          prompt_eval_count=1, total_duration=1)


@pytest.fixture
def pcfg(tmp_path):
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                  post=PostConfig(image_dir=tmp_path / "images", corrections_path=tmp_path / "corr" / "c.json"))


def _compose(pcfg, clip):
    post_stage.compose_posts(EID, pcfg, [clip], client=EchoClient(), sleep=lambda s: None)
    return post_store.read_posts(pcfg.workspace.dir / EID / "posts.json", EID)


def test_compose_applies_only_approved_and_keeps_sha(pcfg):  # AC4, AC9
    make_post_episode(pcfg.workspace.dir, pcfg.render.output_dir)
    ep = post_source.load(EID, pcfg)
    lines = post_source.source_lines(ep, "k01")
    first = lines[0].split()
    assert len(first) >= 2
    frm = " ".join(first[:2])
    to = "zzx yyx"
    # no dictionary file at all
    base = post_store.find(_compose(pcfg, "k01"), "k01")
    assert to not in " ".join(base["paragraphs"]).lower()
    doc = C.empty_doc()
    C.record(doc, [(C.normalize_phrase(frm), to)], "e", "k", NOW)  # proposed
    doc["rules"].append({**rule(C.normalize_phrase(first[0]) + " zzzz", "q", "r0009", C.REJECTED)})
    C.save(pcfg.post.corrections_path, doc)
    assert to not in " ".join(post_store.find(_compose(pcfg, "k01"), "k01")["paragraphs"]).lower()
    doc["rules"][0]["status"] = C.APPROVED
    C.save(pcfg.post.corrections_path, doc)
    entry = post_store.find(_compose(pcfg, "k01"), "k01")
    text = " ".join(entry["paragraphs"])
    assert text.lower().startswith(to) or to in text.lower()
    assert entry["source_sha256"] == base["source_sha256"]
    assert not post_stage.compute_stale(post_source.load(EID, pcfg), entry)
    log = json.loads((pcfg.workspace.dir / EID / "post_log.json").read_text(encoding="utf-8"))
    assert log["entries"][-1]["corrections"] == [{"rule_id": "r0001", "at_token": 0}]
    assert log["entries"][0]["corrections"] == []


def test_compose_corrupt_dictionary_is_ignored(pcfg):  # AC9
    make_post_episode(pcfg.workspace.dir, pcfg.render.output_dir)
    pcfg.post.corrections_path.parent.mkdir(parents=True)
    pcfg.post.corrections_path.write_text("garbage", encoding="utf-8")
    entry = post_store.find(_compose(pcfg, "k01"), "k01")
    assert entry is not None
    assert pcfg.post.corrections_path.read_text(encoding="utf-8") == "garbage"
