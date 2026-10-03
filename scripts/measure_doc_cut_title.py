#!/usr/bin/env python3
"""CP8.20 - measure the official lecture text (``post/doc.py``) as the source of Short titles and sentence cuts.

Task contract: docs/tasks/CP8.20-doc-cut-title-measure.md. Read-only on the artifacts of the episodes; every result is
written under the results directory next to the working copy (default ``~/.cache/auto-short-cp820-test``). The script
refuses to run when the config's workspace / output would point into the main repository, and never edits ``src/``.

    export PYTHONPATH=src
    python scripts/measure_doc_cut_title.py --config ~/.cache/auto-short-cp820-test/config.toml m1m2   # no GPU
    python scripts/measure_doc_cut_title.py --config ... m3        # selection variants (Ollama, idle queue only)
    python scripts/measure_doc_cut_title.py --config ... m4        # titles from the official text (Ollama)
    python scripts/measure_doc_cut_title.py --config ... tables    # markdown tables for the report

Method (all token alignments use :mod:`auto_short.post.doc` word normalisation and sentence rule D5):

* the whole transcript (speech words) is aligned to the document words with ``difflib.SequenceMatcher`` (the same
  matcher as D3); a transcript word inside a matching block maps to a document word exactly, a word in a gap between
  two blocks is interpolated (flagged "not exact");
* a position is "at a sentence start" when its document token is the first of its paragraph or follows a token that
  ends a sentence (``doc.ends_sentence``); "at a sentence end" when it ends a sentence or ends its paragraph;
* a unit / Short covers the words of its transcript segments (``segment_ids``; a unit is a run of whole segments; a
  CP5 head cut moves the first word on by the dropped words). Time rules are not used: unit / ``source_start`` times
  carry boundary pads and word end times are stretched over the following pause.
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

REPO_MAIN = Path("/home/ntnghia/youtube-auto-short").resolve()
DEFAULT_ROOT = Path.home() / ".cache" / "auto-short-cp820-test"
SHORT_EPISODES = ("Bi7kVGbnPfE", "4oOZz2CBz3g", "yzR1eCK_iV0")
EPISODES = SHORT_EPISODES + tuple(e + ".kt" for e in SHORT_EPISODES)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auto_short import config as config_mod  # noqa: E402
from auto_short.post import doc as D  # noqa: E402
from auto_short.post import source as S  # noqa: E402


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# --- setup ----------------------------------------------------------------------------------------------------

def load_cfg(path: Path):
    cfg = config_mod.load(path)
    for what, p in (("workspace.dir", cfg.workspace.dir), ("render.output_dir", cfg.render.output_dir)):
        rp = Path(p).resolve()
        if rp == REPO_MAIN or REPO_MAIN in rp.parents:
            sys.exit(f"refusing to run: {what} = {rp} is inside the main repository")
    return cfg


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def results_dir(cfg) -> Path:
    d = Path(cfg.workspace.dir).resolve().parent / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(cfg, name: str, doc) -> Path:
    p = results_dir(cfg) / f"{name}.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


class Episode:
    """Artifacts + document alignment of one episode."""

    def __init__(self, cfg, eid: str):
        self.cfg, self.eid = cfg, eid
        self.dir = Path(cfg.workspace.dir) / eid
        self.transcript = read_json(self.dir / "transcript.json")
        self.cand = read_json(self.dir / "candidates.json")
        self.clips = read_json(self.dir / "clips.json")["clips"]
        self.titles = {t["clip_id"]: t for t in read_json(self.dir / "titles.json")["titles"]}
        self.metadata = read_json(self.dir / "metadata.json")
        self.silences = read_json(self.dir / "silences.json")
        self.src = S.load(eid, cfg)
        self.text = D.prepare(eid, cfg.workspace.dir, self.src.rng.segments)  # cached doc.json: no download
        if self.text is None or not self.text.usable:
            raise SystemExit(f"{eid}: no usable lecture text")
        self._words()
        self._align()

    # transcript words
    def _words(self) -> None:
        tw = []
        for si, seg in enumerate(self.transcript["segments"]):
            if seg.get("kind", "speech") != "speech":
                continue
            for w in seg.get("words") or []:
                n = D.normalize_word(w["text"])
                if n:
                    tw.append({"n": n, "start": w["start"], "end": w["end"], "seg": si})
        self.tw = tw
        seg_pos = {seg["id"]: n for n, seg in enumerate(self.transcript["segments"])}
        self.seg_pos = seg_pos
        self.seg_words: dict[int, list[int]] = {}
        for wi, w in enumerate(tw):
            self.seg_words.setdefault(w["seg"], []).append(wi)
        self.tw_start = [w["start"] for w in tw]  # word end times are stretched over pauses: place words by start

    def _align(self) -> None:
        sm = SequenceMatcher(None, [w["n"] for w in self.tw], self.text.words, autojunk=False)
        self.blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
        self.a_starts = [b.a for b in self.blocks]
        self.b_starts = [b.b for b in self.blocks]
        self.exact_t = set()
        for b in self.blocks:
            self.exact_t.update(range(b.a, b.a + b.size))
        t = self.text
        self.raw_to_word = [bisect.bisect_left(t.word_pos, k) for k in range(len(t.tokens))]

    @staticmethod
    def _map(i: int, src_starts: list[int], dst_starts: list[int], sizes: list[int], n_dst: int) -> tuple[int, bool]:
        k = bisect.bisect_right(src_starts, i) - 1
        if k >= 0 and i < src_starts[k] + sizes[k]:
            return dst_starts[k] + (i - src_starts[k]), True
        if k < 0:
            nxt = dst_starts[0] - (src_starts[0] - i) if src_starts else 0
            return max(0, min(nxt, n_dst - 1)), False
        end_s, end_d = src_starts[k] + sizes[k], dst_starts[k] + sizes[k]
        if k + 1 >= len(src_starts):
            return max(0, min(end_d + (i - end_s), n_dst - 1)), False
        gap_s = src_starts[k + 1] - end_s
        if i - end_s <= gap_s / 2:
            j = end_d + (i - end_s)
        else:
            j = dst_starts[k + 1] - (src_starts[k + 1] - i)
        return max(0, min(j, n_dst - 1)), False

    def t2d(self, i: int) -> tuple[int, bool]:
        return self._map(i, self.a_starts, self.b_starts, [b.size for b in self.blocks], len(self.text.words))

    def d2t(self, j: int) -> tuple[int, bool]:
        return self._map(j, self.b_starts, self.a_starts, [b.size for b in self.blocks], len(self.tw))

    # sentence geometry on document tokens
    def start_info(self, i: int) -> dict:
        """Is transcript word ``i`` the first word of a sentence; how many tokens / seconds earlier does it start."""
        t = self.text
        j, exact = self.t2d(i)
        k = t.word_pos[j]
        ks = k
        while ks > 0 and t.para_of[ks - 1] == t.para_of[ks] and not D.ends_sentence(t, ks - 1):
            ks -= 1
        ok = ks == k
        sec = None
        if not ok:
            ws = self.raw_to_word[ks]
            ti, _ = self.d2t(min(ws, len(t.words) - 1))
            sec = max(0.0, self.tw[i]["start"] - self.tw[min(ti, i)]["start"])
        return {"ok": ok, "tokens": k - ks, "seconds": sec, "exact": exact}

    def end_info(self, i: int) -> dict:
        t, n = self.text, len(self.text.tokens)
        j, exact = self.t2d(i)
        k = t.word_pos[j]
        ke = k
        while ke + 1 < n and t.para_of[ke + 1] == t.para_of[ke] and not D.ends_sentence(t, ke):
            ke += 1
        ok = ke == k or D.ends_sentence(t, k)
        sec = None
        if not ok:
            we = self.raw_to_word[min(ke, n - 1)]
            ti, _ = self.d2t(min(we, len(t.words) - 1))
            sec = max(0.0, self.tw[max(ti, i)]["end"] - self.tw[i]["end"])
        return {"ok": ok, "tokens": ke - k, "seconds": sec, "exact": exact}

    def segs_words(self, first_seg: str, last_seg: str) -> tuple[int, int] | None:
        """Word range of the whole transcript segments ``first_seg .. last_seg`` (a unit is a run of segments)."""
        idx = [wi for n in range(self.seg_pos[first_seg], self.seg_pos[last_seg] + 1)
               for wi in self.seg_words.get(n, [])]
        return (idx[0], idx[-1]) if idx else None

    def words_in(self, start: float, end: float) -> tuple[int, int] | None:
        lo = bisect.bisect_left(self.tw_start, start - 0.02)
        hi = bisect.bisect_left(self.tw_start, end - 0.02)  # words that start before the end
        return (lo, hi - 1) if hi > lo else None

    def clip_range(self, clip: dict) -> tuple[int, int] | None:
        """Transcript word range of a clip: first word of its first unit .. last word of its last unit (a CP5 B11 head
        cut moves the first word on by the dropped words). ``source_start`` includes the boundary pad, so it is not
        used to place words."""
        if not hasattr(self, "_unit_words"):
            self._unit_words = {u["id"]: self.segs_words(*u["segment_ids"]) for u in self.cand["units"]}
        a, b = self._unit_words[clip["unit_ids"][0]], self._unit_words[clip["unit_ids"][1]]
        if a is None or b is None:
            return None
        lo = a[0] + (len(clip["head_cut"]["words"].split()) if clip.get("head_cut") else 0)
        return (lo, b[1]) if b[1] >= lo else None

    def span_info(self, clip: dict) -> dict | None:
        r = self.clip_range(clip)
        if r is None:
            return None
        s, e = self.start_info(r[0]), self.end_info(r[1])
        return {"words": r[1] - r[0] + 1, "start": s, "end": e, "both": s["ok"] and e["ok"]}

    # units
    def unit_flags(self) -> list[dict]:
        out = []
        for u in self.cand["units"]:
            r = self.segs_words(*u["segment_ids"])
            if r is None:
                out.append({"id": u["id"], "start_ok": False, "end_ok": False, "words": None})
                continue
            out.append({"id": u["id"], "start_ok": self.start_info(r[0])["ok"], "end_ok": self.end_info(r[1])["ok"],
                        "words": r})
        return out


# --- M1 -------------------------------------------------------------------------------------------------------

def pct(a: int, b: int) -> float | None:
    return round(100 * a / b, 1) if b else None


def med(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def m1_episode(ep: Episode) -> dict:
    rows = []
    for c in ep.clips:
        info = ep.span_info(c)
        prod = None
        try:
            raw = S.source_text(ep.src, c["id"])
            dp = D.compose(ep.text, raw)
            prod = None if dp is None else {"head": dp.head, "tail": dp.tail, "ratio": dp.ratio,
                                            "head_ellipsis": dp.head_ellipsis, "tail_ellipsis": dp.tail_ellipsis}
        except S.PostSourceError as exc:
            prod = {"error": str(exc)}
        rows.append({"clip_id": c["id"], "candidate_id": c["candidate_id"], "start": c["source_start"],
                     "end": c["source_end"], "duration": c["duration"], "score": c["score"],
                     "ai_start_complete": c["start_complete"], "ai_end_complete": c["end_complete"],
                     "info": info, "production_compose": prod})
    return {"episode": ep.eid, "clips": rows, "summary": m1_summary(rows)}


def m1_summary(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["info"]]
    sbad = [r for r in ok if not r["info"]["start"]["ok"]]
    ebad = [r for r in ok if not r["info"]["end"]["ok"]]
    both = [r for r in ok if r["info"]["both"]]
    prod = [r["production_compose"] for r in rows if r["production_compose"] and "head" in r["production_compose"]]
    return {
        "shorts": len(rows), "measured": len(ok),
        "start_mid_sentence": len(sbad), "start_mid_pct": pct(len(sbad), len(ok)),
        "end_mid_sentence": len(ebad), "end_mid_pct": pct(len(ebad), len(ok)),
        "both_ok": len(both), "both_ok_pct": pct(len(both), len(ok)),
        "head_tokens_median_of_bad": med([r["info"]["start"]["tokens"] for r in sbad]),
        "head_seconds_median_of_bad": med([r["info"]["start"]["seconds"] for r in sbad]),
        "tail_tokens_median_of_bad": med([r["info"]["end"]["tokens"] for r in ebad]),
        "tail_seconds_median_of_bad": med([r["info"]["end"]["seconds"] for r in ebad]),
        "start_not_exact": sum(1 for r in ok if not r["info"]["start"]["exact"]),
        "end_not_exact": sum(1 for r in ok if not r["info"]["end"]["exact"]),
        "ai_start_complete_true": sum(1 for r in rows if r["ai_start_complete"]),
        "ai_end_complete_true": sum(1 for r in rows if r["ai_end_complete"]),
        "ai_says_complete_but_mid_start": sum(1 for r in sbad if r["ai_start_complete"]),
        "ai_says_complete_but_mid_end": sum(1 for r in ebad if r["ai_end_complete"]),
        "production_compose_aligned": len(prod),
        "production_head_gt0": sum(1 for p in prod if p["head"] > 0),
        "production_tail_gt0": sum(1 for p in prod if p["tail"] > 0),
        "production_head_median_of_gt0": med([p["head"] for p in prod if p["head"] > 0]),
    }


# --- M2 -------------------------------------------------------------------------------------------------------

def capacity(spans: list[tuple[float, float]]) -> int:
    """Largest number of non-overlapping spans (greedy by end time)."""
    n, last = 0, float("-inf")
    for s, e in sorted(spans, key=lambda x: x[1]):
        if s >= last:
            n, last = n + 1, e
    return n


def candidate_filter(ep: Episode, flags: list[dict] | None = None) -> set[str]:
    """Ids of candidates whose first unit starts and last unit ends at a sentence boundary."""
    flags = flags or ep.unit_flags()
    by_id = {f["id"]: f for f in flags}
    return {c["id"] for c in ep.cand["candidates"]
            if by_id[c["unit_ids"][0]]["start_ok"] and by_id[c["unit_ids"][1]]["end_ok"]}


def m2_episode(ep: Episode) -> dict:
    from auto_short.selection.logic import build_windows

    flags = ep.unit_flags()
    units, cands = ep.cand["units"], ep.cand["candidates"]
    n = len(units)
    s_ok = sum(f["start_ok"] for f in flags)
    e_ok = sum(f["end_ok"] for f in flags)
    both_units = sum(f["start_ok"] and f["end_ok"] for f in flags)

    # sentence ends of the document that fall inside a unit (exactly matched transcript words only)
    unit_of = {}
    for ui, f in enumerate(flags):
        if f["words"]:
            for wi in range(f["words"][0], f["words"][1] + 1):
                unit_of[wi] = ui
    t = ep.text
    ends_total = ends_at_unit_end = ends_mid = 0
    mid_gaps = []
    for wi, ui in unit_of.items():
        if wi not in ep.exact_t:
            continue
        j, _ = ep.t2d(wi)
        k = t.word_pos[j]
        is_end = D.ends_sentence(t, k) or k + 1 >= len(t.tokens) or t.para_of[k + 1] != t.para_of[k]
        if not is_end:
            continue
        ends_total += 1
        if wi == flags[ui]["words"][1]:
            ends_at_unit_end += 1
        else:
            ends_mid += 1
            if wi + 1 < len(ep.tw):
                mid_gaps.append(ep.tw[wi + 1]["start"] - ep.tw[wi]["end"])

    ok_ids = candidate_filter(ep, flags)
    params = ep.cand["params"]
    spans = lambda cs: [(c["source_start"], c["source_end"]) for c in cs]  # noqa: E731
    tgt = [c for c in cands if c["in_target"]]
    ok_c = [c for c in cands if c["id"] in ok_ids]
    ok_tgt = [c for c in tgt if c["id"] in ok_ids]
    win_all = build_windows(units, cands, ep.cfg.selection.max_window_words)
    win_ok = build_windows(units, [c for c in cands if c["id"] in ok_ids], ep.cfg.selection.max_window_words)
    wa = sum(1 for w in win_all if w.candidates)
    wo = sum(1 for w in win_ok if w.candidates)
    # windows with an in-target candidate before / after the filter
    ids_tgt = {c["id"] for c in tgt}
    wt_all = sum(1 for w in win_all if any(c["id"] in ids_tgt for c in w.candidates))
    wt_ok = sum(1 for w in win_ok if any(c["id"] in ids_tgt for c in w.candidates))
    return {
        "episode": ep.eid, "transcript_method": ep.transcript["method"], "params": {k: params[k] for k in ("min_duration", "max_duration", "target_min", "target_max")},
        "doc_match": ep.text.match, "transcript_words": len(ep.tw), "transcript_words_exact": len(ep.exact_t),
        "units": n, "unit_start_at_sentence": s_ok, "unit_start_pct": pct(s_ok, n),
        "unit_end_at_sentence": e_ok, "unit_end_pct": pct(e_ok, n),
        "unit_both": both_units, "unit_both_pct": pct(both_units, n),
        "doc_sentence_ends_in_units": ends_total, "doc_sentence_ends_at_unit_end": ends_at_unit_end,
        "doc_sentence_ends_inside_unit": ends_mid, "inside_unit_pct": pct(ends_mid, ends_total),
        "inside_gap_median_s": med(mid_gaps),
        "inside_gap_ge_0.3s": sum(1 for g in mid_gaps if g >= 0.3), "inside_gap_ge_0.15s": sum(1 for g in mid_gaps if g >= 0.15),
        "candidates": len(cands), "candidates_in_target": len(tgt),
        "candidates_sentence_both": len(ok_c), "candidates_sentence_both_pct": pct(len(ok_c), len(cands)),
        "candidates_in_target_sentence_both": len(ok_tgt),
        "candidates_in_target_sentence_both_pct": pct(len(ok_tgt), len(tgt)),
        "capacity_all": capacity(spans(cands)), "capacity_in_target": capacity(spans(tgt)),
        "capacity_sentence_both": capacity(spans(ok_c)), "capacity_in_target_sentence_both": capacity(spans(ok_tgt)),
        "windows_with_candidates": wa, "windows_with_candidates_after_filter": wo,
        "windows_with_in_target": wt_all, "windows_with_in_target_after_filter": wt_ok,
        "selected_baseline": len(ep.clips),
        "baseline_clips_candidates_sentence_both": sum(1 for c in ep.clips if c["candidate_id"] in ok_ids),
    }


def cmd_m1m2(args, cfg) -> None:
    t0 = time.monotonic()
    m1, m2 = {}, {}
    for eid in EPISODES:
        ep = Episode(cfg, eid)
        m1[eid], m2[eid] = m1_episode(ep), m2_episode(ep)
        print(eid, json.dumps(m1[eid]["summary"], ensure_ascii=False))
        print(eid, json.dumps(m2[eid], ensure_ascii=False))
    save(cfg, "m1", m1)
    save(cfg, "m2", m2)
    print(f"m1m2 done in {time.monotonic() - t0:.1f} s")


# --- M3 -------------------------------------------------------------------------------------------------------

LABEL_START, LABEL_END = "[ĐẦU CÂU]", "[CUỐI CÂU]"
LABEL_NOTE = (
    "\n\nNHÃN CÂU (lấy từ văn bản gốc của bài giảng): một số unit có nhãn [ĐẦU CÂU] ở đầu lời nói — unit mở đầu đúng "
    "đầu một câu — và/hoặc nhãn [CUỐI CÂU] ở cuối — unit kết thúc đúng cuối một câu. Unit không có nhãn [ĐẦU CÂU] "
    "bắt đầu giữa câu; unit không có nhãn [CUỐI CÂU] dừng giữa câu. Hãy chọn first_unit có nhãn [ĐẦU CÂU] và "
    "last_unit có nhãn [CUỐI CÂU]; start_complete / end_complete chỉ là true khi unit có nhãn tương ứng."
)


def run_variant(cfg, ep: Episode, variant: str, client) -> dict:
    from auto_short.selection import stage as ss

    cand_doc = ep.cand
    flags = ep.unit_flags()
    by_id = {f["id"]: f for f in flags}
    restore = []
    if variant == "a":
        keep = candidate_filter(ep, flags)
        cand_doc = dict(ep.cand, candidates=[c for c in ep.cand["candidates"] if c["id"] in keep])
    elif variant == "b":
        orig_render, orig_system = ss.render_user_prompt, ss.system_prompt

        def render(version, *, units, **kw):
            lab = []
            for u in units:
                f = by_id[u["id"]]
                text = (LABEL_START + " " if f["start_ok"] else "") + u["text"] + (" " + LABEL_END if f["end_ok"] else "")
                lab.append(dict(u, text=text))
            return orig_render(version, units=lab, **kw)

        ss.render_user_prompt = render
        ss.system_prompt = lambda *a, **k: orig_system(*a, **k) + LABEL_NOTE
        restore = [("render_user_prompt", orig_render), ("system_prompt", orig_system)]
    t0 = time.monotonic()
    try:
        clips_doc, log_doc = ss.select(ep.eid, cand_doc, ep.metadata, ep.silences, ep.transcript,
                                       cfg.selection, client)
    finally:
        for name, fn in restore:
            setattr(ss, name, fn)
    secs = time.monotonic() - t0
    rows = []
    for c in clips_doc["clips"]:
        info = ep.span_info(c)
        rows.append({"id": c["id"], "candidate_id": c["candidate_id"], "start": c["source_start"],
                     "end": c["source_end"], "duration": c["duration"], "score": c["score"],
                     "start_complete": c["start_complete"], "end_complete": c["end_complete"],
                     "in_target": c["in_target"], "topic": c["topic"], "head_cut": c["head_cut"], "info": info})
    return {"episode": ep.eid, "variant": variant, "seconds": round(secs, 1), "stats": clips_doc["stats"],
            "ai_seconds": round(sum(cl["seconds"] or 0 for w in log_doc["windows"] for cl in w["ai_calls"]), 1),
            "clips": rows, "summary": m3_summary(rows), "clips_doc": clips_doc}


def m3_summary(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["info"]]
    both = [r for r in ok if r["info"]["both"]]
    sok = [r for r in ok if r["info"]["start"]["ok"]]
    eok = [r for r in ok if r["info"]["end"]["ok"]]
    scores = [r["score"] for r in rows]
    return {"clips": len(rows), "both_ok": len(both), "both_ok_pct": pct(len(both), len(ok)),
            "start_ok": len(sok), "end_ok": len(eok),
            "score_mean": round(statistics.mean(scores), 2) if scores else None,
            "total_seconds": round(sum(r["duration"] for r in rows), 1),
            "in_target": sum(1 for r in rows if r["in_target"])}


def cmd_m3(args, cfg) -> None:
    from auto_short.selection.client import OllamaClient, resolve_host
    import cp11_bench as bench

    cfgs = cfg.selection
    client = OllamaClient(resolve_host(cfgs.ollama_host), timeout=cfgs.timeout)
    eps = args.episodes or list(SHORT_EPISODES)
    variants = args.variants.split(",")
    out_path = results_dir(cfg) / "m3.json"
    out = json.loads(out_path.read_text()) if out_path.exists() else {}
    for eid in eps:
        ep = Episode(cfg, eid)
        for v in variants:
            key = f"{eid}:{v}"
            if key in out and not args.redo:
                print("skip (done)", key)
                continue
            idle = bench.wait_ollama_idle(False)
            print(f"[{utc()}] M3 {key} start", flush=True)
            res = run_variant(cfg, ep, v, client)
            res["idle_check"] = idle
            out[key] = res
            out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[{utc()}] M3 {key}: {res['seconds']} s, ai {res['ai_seconds']} s, {json.dumps(res['summary'])}",
                  flush=True)


# --- M4 -------------------------------------------------------------------------------------------------------

def cmd_m4(args, cfg) -> None:
    from auto_short.selection.client import OllamaClient, resolve_host
    from auto_short.titling.logic import choose_title
    from auto_short.titling.prompt import render_user_prompt, system_prompt
    from auto_short.titling.stage import _title_clip
    import cp11_bench as bench

    tc = cfg.titling
    client = OllamaClient(resolve_host(tc.ollama_host), timeout=tc.timeout)
    system = system_prompt(tc.prompt_version, max_chars=tc.max_chars, n_options=tc.n_options)
    out_path = results_dir(cfg) / "m4.json"
    out = json.loads(out_path.read_text()) if out_path.exists() else {}
    for eid in (args.episodes or list(EPISODES)):
        ep = Episode(cfg, eid)
        title = ep.metadata.get("title") or ""
        bench.wait_ollama_idle(False)
        for c in ep.clips:
            key = f"{eid}:{c['id']}"
            if key in out and not args.redo:
                continue
            raw = S.source_text(ep.src, c["id"])
            dp = D.compose(ep.text, raw)
            old = ep.titles.get(c["id"], {})
            row = {"episode": eid, "clip_id": c["id"], "duration": c["duration"], "old_title": old.get("title"),
                   "old_evidence": old.get("evidence"), "caption_words": len(raw.split()), "new_title": None,
                   "status": "no_alignment"}
            if dp is not None:
                text = " ".join(dp.paragraphs)
                row.update(doc_words=len(text.split()), head=dp.head, tail=dp.tail, ratio=dp.ratio,
                           head_ellipsis=dp.head_ellipsis, tail_ellipsis=dp.tail_ellipsis, doc_text=text)
                while bench.production_running():  # quick re-check per Short; full idle check once per episode
                    time.sleep(30)
                msgs = [{"role": "system", "content": system},
                        {"role": "user", "content": render_user_prompt(tc.prompt_version, title=title,
                                                                       duration=c["duration"], text=text)}]
                clog = {"ai_calls": []}
                t0 = time.monotonic()
                try:
                    records = _title_clip(client, tc, msgs, c["id"], text, clog, lambda s: time.sleep(s))
                except Exception as exc:  # noqa: BLE001
                    records, row["error"] = None, str(exc)
                chosen, alts = choose_title(records) if records else (None, [])
                row.update(seconds=round(time.monotonic() - t0, 1), ai_calls=len(clog["ai_calls"]),
                           new_title=chosen["title"] if chosen else None,
                           new_evidence=chosen["evidence"] if chosen else None,
                           new_alternatives=[a["title"] for a in alts], status="titled" if chosen else "untitled")
            out[key] = row
            out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[{utc()}] M4 {key}: {row['old_title']!r} -> {row['new_title']!r} ({row['status']})", flush=True)



# --- M5 -------------------------------------------------------------------------------------------------------

# (baseline clip id of the M3 "base" rerun, clip id of the variant) overlapping Shorts, chosen after reading M3
M5_PAIRS = {"Bi7kVGbnPfE": [("k03", "k01"), ("k04", "k02"), ("k05", "k03"), ("k09", "k06")],
            "4oOZz2CBz3g": [("k02", "k02"), ("k06", "k08")]}


def cmd_m5(args, cfg) -> None:
    """Render the sample pairs: per episode two scratch workspaces (``<id>-m5base`` / ``<id>-m5<variant>``), each with
    only the chosen clips of the M3 run, titled by the production titling stage and rendered by the production render
    stage. Copies of the sample files are put in ``<root>/samples``."""
    import shutil
    import subprocess

    from auto_short import hashing
    from auto_short.render.stage import run_render
    from auto_short.titling.stage import run_titling
    import cp11_bench as bench

    m3 = read_json(results_dir(cfg) / "m3.json")
    ws_root, out_root = Path(cfg.workspace.dir), Path(cfg.render.output_dir)
    samples = ws_root.resolve().parent / "samples"
    samples.mkdir(exist_ok=True)
    listing = []
    for eid, pairs in M5_PAIRS.items():
        for role, vname, idx in (("base", "base", 0), (args.variant, args.variant, 1)):
            wid = f"{eid}-m5{role}"
            keep = [p[idx] for p in pairs]
            run = m3[f"{eid}:{vname}"]
            clips = [c for c in run["clips_doc"]["clips"] if c["id"] in keep]
            dst = ws_root / wid
            if not dst.exists():
                subprocess.run(["cp", "-a", "--reflink=auto", str(ws_root / eid), str(dst)], check=True)
            for name in ("clips.json", "titles.json", "selection_log.json", "titling_log.json", "posts.json",
                         "post_log.json", "publish.json"):
                (dst / name).unlink(missing_ok=True)
            man = read_json(dst / "manifest.json")
            man["episode_id"] = wid
            for st in ("selection", "titling", "render"):
                man["stages"].pop(st, None)
            (dst / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
            doc = dict(run["clips_doc"], episode_id=wid, clips=clips)
            (dst / "clips.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            # manifest "selection" entry: record it done for the new clips.json so the later stages accept it
            man = read_json(dst / "manifest.json")
            man["stages"]["selection"] = {"status": "done", "artifacts": ["clips.json"],
                                          "inputs": [], "config_hash": "m5", "started_at": utc(),
                                          "finished_at": utc(), "error": None}
            (dst / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
            bench.wait_ollama_idle(False)
            run_titling(wid, cfg)
            run_render(wid, cfg)
            for c in clips:
                pair = next(n for n, pr in enumerate(pairs, 1) if pr[idx] == c["id"])
                src = out_root / wid / "shorts" / f"{c['id']}.mp4"
                dest = samples / f"{eid}_pair{pair}_{role}_{c['id']}.mp4"
                subprocess.run(["cp", "--reflink=auto", str(src), str(dest)], check=True)
                listing.append({"episode": eid, "pair": pair, "role": role, "clip": c["id"], "path": str(dest),
                                "start": c["source_start"], "end": c["source_end"], "duration": c["duration"]})
    save(cfg, "m5", listing)
    for r in listing:
        print(r)


# --- tables ---------------------------------------------------------------------------------------------------

def unknown_words(title: str | None, vocab: set[str]) -> list[str]:
    """Title words that never occur in the official text of the episode (a hint of a misspelling / term error)."""
    if not title:
        return []
    return [w for w in (D.normalize_word(t) for t in title.split()) if w and w not in vocab]


def cmd_tables(args, cfg) -> None:
    rd = results_dir(cfg)
    lines = []
    m4 = read_json(rd / "m4.json") if (rd / "m4.json").exists() else {}
    for eid in EPISODES:
        ep = Episode(cfg, eid)
        vocab = set(ep.text.words)
        lines.append(f"\n#### {eid}\n")
        lines.append("| Short | s | Title cũ (caption) | Title mới (văn bản gốc) | Đầu/cuối thêm (token) | Từ lạ cũ | Từ lạ mới "
                     "| Lỗi cũ | Lỗi mới |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for c in ep.clips:
            r = m4.get(f"{eid}:{c['id']}")
            if r is None:
                continue
            ext = f"{r.get('head', '-')}/{r.get('tail', '-')}"
            uo, un = unknown_words(r["old_title"], vocab), unknown_words(r["new_title"], vocab)
            lines.append(f"| {c['id']} | {c['duration']:.0f} | {r['old_title'] or '-'} | {r['new_title'] or '-'} "
                         f"| {ext} | {', '.join(uo) or '-'} | {', '.join(un) or '-'} |  |  |")
    (rd / "titles_table.md").write_text("\n".join(lines), encoding="utf-8")
    # M1 per-Short table
    m1 = read_json(rd / "m1.json")
    l1 = ["| Tập | Short | s | AI đầu/cuối trọn | Đầu: đúng câu? (thiếu token / s) | Cuối: đúng câu? (thừa token / s) |",
          "|---|---|---|---|---|---|"]
    for eid, d in m1.items():
        for r in d["clips"]:
            i = r["info"]
            if not i:
                l1.append(f"| {eid} | {r['clip_id']} | {r['duration']:.0f} | - | không đo được | - |")
                continue
            sh = "đúng" if i["start"]["ok"] else f"giữa câu ({i['start']['tokens']} tok / {i['start']['seconds']:.1f} s)"
            eh = "đúng" if i["end"]["ok"] else f"giữa câu ({i['end']['tokens']} tok / {i['end']['seconds']:.1f} s)"
            l1.append(f"| {eid} | {r['clip_id']} | {r['duration']:.0f} | {'T' if r['ai_start_complete'] else 'F'}/"
                      f"{'T' if r['ai_end_complete'] else 'F'} | {sh} | {eh} |")
    (rd / "m1_table.md").write_text("\n".join(l1), encoding="utf-8")
    print("wrote", rd / "titles_table.md", rd / "m1_table.md")


# --- main -----------------------------------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=DEFAULT_ROOT / "config.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("m1m2", help="M1 + M2 (no GPU)").set_defaults(fn=cmd_m1m2)
    p3 = sub.add_parser("m3", help="M3 selection variants (Ollama)")
    p3.add_argument("--variants", default="base,a,b")
    p3.add_argument("--episodes", nargs="*")
    p3.add_argument("--redo", action="store_true")
    p3.set_defaults(fn=cmd_m3)
    p4 = sub.add_parser("m4", help="M4 titles from the official text (Ollama)")
    p4.add_argument("--episodes", nargs="*")
    p4.add_argument("--redo", action="store_true")
    p4.set_defaults(fn=cmd_m4)
    p5 = sub.add_parser("m5", help="M5 render sample pairs (Ollama for titles)")
    p5.add_argument("--variant", default="b")
    p5.set_defaults(fn=cmd_m5)
    sub.add_parser("tables", help="markdown tables").set_defaults(fn=cmd_tables)
    args = ap.parse_args()
    cfg = load_cfg(args.config.expanduser())
    args.fn(args, cfg)


if __name__ == "__main__":
    main()
