"""Shared fixture for CP8.15 post tests: an episode with titling done + a render_manifest.json (reuses the CP9
synthetic timeline: cp9_helpers). ``units`` are 1:1 with speech segments, so a clip's ``unit_ids`` and the caption
lines it covers are the same two lines (handy to compare the two P2 text paths)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from auto_short.hashing import canonical_json
from auto_short.workspace import DONE, Workspace
from cp9_helpers import CONTENT, PARAMS, seg, timeline, trims

EID = "post8TestEp1"
SERIES, EPISODE_N = "Kinh Test", "9"


def sha(doc: dict) -> str:
    return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()


def make_post_episode(root: Path, output_dir: Path, *, episode_id: str = EID,
                      titles: dict[str, str] | None = None, head_cut_words: str | None = None) -> Workspace:
    """clips: k01 = lines 1-8, k02 = lines 21-28 (both rendered). ``titles`` overrides a clip_id's rendered title
    text (default ``f"Tiêu đề {clip_id}"``). ``head_cut_words`` (P2, ORCHESTRATOR review round 1 B1): CP5 B11
    ``head_cut`` on k01, dropping these leading words of its own text (e.g. ``"dòng 1"``, the start of line 1)."""
    segments, silences = timeline()
    speech = [s for s in segments if s["kind"] == "speech"]
    units = [{"id": f"u{n:05d}", "start": s["start"], "end": s["end"], "segment_ids": [s["id"]], "text": s["text"],
              "words": len(s["text"].split()), "break_before": {"kind": "content_edge", "seconds": None},
              "break_after": {"kind": "silence", "seconds": 0.5}}
             for n, s in enumerate(speech, 1)]
    unit_of = {s["id"]: u["id"] for s, u in zip(speech, units)}

    ws = Workspace(root, episode_id)
    ws.dir.mkdir(parents=True)
    (ws.dir / "source.mp4").write_bytes(b"\x00" * 4096 + b"fake source video")

    def rng(a: int, b: int) -> tuple[float, float]:
        return max(round(seg(segments, a)["start"] - 0.3, 3), CONTENT[0]), round(seg(segments, b)["end"] + 0.3, 3)

    def cand(cid: str, a: int, b: int) -> dict:
        start, end = rng(a, b)
        tr = trims(start, end, silences)
        dur = round(end - start - sum(y - x for x, y in tr), 3)
        return {"id": cid, "source_start": start, "source_end": end, "source_duration": round(end - start, 3),
                "duration": dur, "in_target": True,
                "unit_ids": [unit_of[seg(segments, a)["id"]], unit_of[seg(segments, b)["id"]]],
                "segment_ids": [seg(segments, a)["id"], seg(segments, b)["id"]], "words": 10, "trims": tr,
                "boundary": {"start": None, "end": None}, "shot_ids": [], "shot_changes": []}

    cands = [cand("c00001", 1, 8), cand("c00002", 21, 28)]
    transcript = {"schema_version": 1, "episode_id": episode_id, "transcript_sha256": "t" * 64, "segments": segments}
    sil_doc = {"schema_version": 1, "episode_id": episode_id,
              "silences": [{"start": a, "end": b} for a, b in silences]}
    cand_doc = {"schema_version": 1, "episode_id": episode_id, "transcript_sha256": "t" * 64,
               "silences_sha256": sha(sil_doc), "params": dict(PARAMS),
               "content": {"start": CONTENT[0], "end": CONTENT[1]}, "units": units, "candidates": cands}
    def head_cut(n: int, c: dict) -> dict | None:
        if n != 1 or not head_cut_words:
            return None
        return {"words": head_cut_words, "original_start": c["source_start"]}

    clips = [{"id": f"k0{n}", "candidate_id": c["id"], "source_start": c["source_start"],
              "source_end": c["source_end"], "source_duration": c["source_duration"], "duration": c["duration"],
              "unit_ids": c["unit_ids"], "segment_ids": c["segment_ids"], "head_cut": head_cut(n, c)}
             for n, c in enumerate(cands, 1)]
    clips_doc = {"schema_version": 1, "episode_id": episode_id, "candidates_sha256": sha(cand_doc), "clips": clips}
    header = {"lines": ["HT.Tịnh Không", f"{SERIES} (tập {EPISODE_N})"],
              "fields": {"speaker": "HT.Tịnh Không", "series": SERIES, "episode": EPISODE_N},
              "sources": {"speaker": "config", "series": "metadata", "episode": "metadata"}}
    titles = titles or {}
    titles_doc = {"schema_version": 1, "episode_id": episode_id, "clips_sha256": sha(clips_doc),
                 "candidates_sha256": sha(cand_doc), "header": header,
                 "titles": [{"clip_id": c["id"], "candidate_id": c["candidate_id"],
                            "title": titles.get(c["id"], f"Tiêu đề {c['id']}"), "evidence": "x", "alternatives": [],
                            "status": "titled"} for c in clips]}
    meta = {"schema_version": 1, "episode_id": episode_id, "title": f"{SERIES} tập {EPISODE_N}", "duration": 520.0}
    for name, doc in (("transcript.json", transcript), ("silences.json", sil_doc), ("candidates.json", cand_doc),
                      ("clips.json", clips_doc), ("titles.json", titles_doc), ("metadata.json", meta)):
        (ws.dir / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = ws.new_manifest({"kind": "youtube", "uri": f"https://youtu.be/{episode_id}", "path": "source.mp4",
                               "sha256": "0" * 64, "size": 4113, "mtime_ns": 0})
    for stage in ("ingest", "transcript", "analysis", "selection", "titling", "render"):
        manifest["stages"][stage] = {"status": DONE, "artifacts": [], "inputs": [], "config_hash": "x",
                                     "started_at": None, "finished_at": None, "error": None}
    ws.save_manifest(manifest)

    out_dir = output_dir / episode_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "shorts").mkdir(exist_ok=True)
    for cid in ("k01", "k02"):
        (out_dir / "shorts" / f"{cid}.mp4").write_bytes(b"fake mp4")
    render_manifest = {
        "schema_version": 1, "episode_id": episode_id, "header": header,
        "stats": {"clips": 2, "rendered": 2, "skipped": 0, "seconds": 30.0},
        "shorts": [{"clip_id": c["id"], "candidate_id": c["candidate_id"], "status": "rendered",
                    "skip_reason": None, "file": f"shorts/{c['id']}.mp4", "sha256": "a" * 64,
                    "title": titles.get(c["id"], f"Tiêu đề {c['id']}"), "title_display_lines": [], "title_font_size": 70,
                    "source_start": c["source_start"], "source_end": c["source_end"], "segments": [], "duration": c["duration"],
                    "dissolves": [], "title_origin": "ai", "render_key": "b" * 64, "origin": "ai", "cut": None}
                   for c in clips],
    }
    (out_dir / "render_manifest.json").write_text(json.dumps(render_manifest, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")
    return ws
