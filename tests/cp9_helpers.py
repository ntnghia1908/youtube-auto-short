"""CP9 helpers: a synthetic episode with titling done plus the artifacts the cut / add-Short rules read
(transcript.json, silences.json, candidates.json params + content, shots.json, selection_log.json). No media.

Timeline (seconds): content window 10.0 – 500.0. Speech lines of 4 s ``s00001`` … each followed by a pause:
0.5 s, or 2.0 s after every 5th line (trimmed to 1.0 s by ``max_pause``). After line 40 a 3 s ``[âm nhạc]`` label
(a hard break for a Short, a pause for a khai thị episode, CP8.9 A3.1); after line 60 a 12 s silence (hard
break). Captions stop at the end of speech (the silence lies between two lines).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from auto_short.hashing import canonical_json
from auto_short.workspace import DONE, Workspace

EID = "cp9TestEpi1"
CONTENT = (10.0, 500.0)
PARAMS = {"min_boundary_silence": 3.0, "align_tolerance": 0.5, "hard_break_silence": 10.0, "max_pause": 1.0,
          "boundary_pad": 0.3, "min_duration": 30.0, "max_duration": 180.0, "target_min": 60.0, "target_max": 90.0,
          "shot_guard": 1.0, "intro_window": 60.0, "intro_min_silence": 1.0, "outro_window": 180.0}
LABEL_AFTER, LONG_SILENCE_AFTER = 40, 60


def sha(doc: dict) -> str:
    return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()


def timeline(n_lines: int = 90) -> tuple[list[dict], list[list[float]]]:
    segments, silences, t, k = [], [], CONTENT[0], 0
    for i in range(1, n_lines + 1):
        k += 1
        segments.append({"id": f"s{k:05d}", "start": round(t, 3), "end": round(t + 4, 3), "kind": "speech",
                         "text": f"dòng {i} lời giảng thứ {i} về tâm", "words": []})
        t += 4
        if i == LABEL_AFTER:
            silences.append([round(t, 3), round(t + 0.5, 3)])
            k += 1
            segments.append({"id": f"s{k:05d}", "start": round(t + 0.5, 3), "end": round(t + 3.5, 3),
                             "kind": "non_speech", "text": "[âm nhạc]", "words": []})
            silences.append([round(t + 3.5, 3), round(t + 4.0, 3)])
            t += 4.0
            continue
        gap = 12.0 if i == LONG_SILENCE_AFTER else (2.0 if i % 5 == 0 else 0.5)
        silences.append([round(t, 3), round(t + gap, 3)])
        t += gap
    return segments, silences


def seg(segments: list[dict], line: int) -> dict:
    """Speech line number ``line`` (1-based)."""
    return [s for s in segments if s["kind"] == "speech"][line - 1]


def trims(start: float, end: float, silences: list[list[float]], max_pause: float = 1.0) -> list[list[float]]:
    out = []
    for a, b in silences:
        a, b = max(a, start), min(b, end)
        if b - a > max_pause:
            out.append([round(a + max_pause / 2, 3), round(b - max_pause / 2, 3)])
    return out


def candidate(cid: str, start: float, end: float, silences) -> dict:
    tr = trims(start, end, silences)
    dur = round(end - start - sum(b - a for a, b in tr), 3)
    return {"id": cid, "source_start": start, "source_end": end, "source_duration": round(end - start, 3),
            "duration": dur, "in_target": 60 <= dur <= 90, "unit_ids": ["u0001", "u0001"],
            "segment_ids": ["s00001", "s00001"], "words": 10, "trims": tr,
            "boundary": {"start": None, "end": None}, "shot_ids": [], "shot_changes": []}


def make_cp9_episode(root: Path, *, episode_id: str = EID, params: dict | None = None,
                     source_kind: str = "youtube", proposals: list[dict] | None = None,
                     shot_changes: list[float] | None = None) -> Workspace:
    """Episode with ingest .. titling done: k01 = lines 1–8, k02 = lines 21–28; proposals (selection_log):
    c00003 lines 23–32 (overlapped k02), c00004 lines 45–47 (ineligible, too short), c00005 lines 50–58
    (over_limit)."""
    segments, silences = timeline()
    ws = Workspace(root, episode_id)
    ws.dir.mkdir(parents=True)
    (ws.dir / "source.mp4").write_bytes(b"\x00" * 4096 + b"fake source video")

    def rng(a: int, b: int) -> tuple[float, float]:
        return max(round(seg(segments, a)["start"] - 0.3, 3), CONTENT[0]), round(seg(segments, b)["end"] + 0.3, 3)

    cands = [candidate("c00001", *rng(1, 8), silences), candidate("c00002", *rng(21, 28), silences),
             candidate("c00003", *rng(23, 32), silences), candidate("c00004", *rng(45, 47), silences),
             candidate("c00005", *rng(50, 58), silences)]
    transcript = {"schema_version": 1, "episode_id": episode_id, "transcript_sha256": "t" * 64,
                  "segments": segments}
    sil_doc = {"schema_version": 1, "episode_id": episode_id, "silences": [{"start": a, "end": b} for a, b in silences]}
    cand_doc = {"schema_version": 1, "episode_id": episode_id, "transcript_sha256": "t" * 64,
                "silences_sha256": sha(sil_doc), "params": params or dict(PARAMS),
                "content": {"start": CONTENT[0], "end": CONTENT[1]}, "candidates": cands}
    clips = [{"id": f"k0{n}", "candidate_id": c["id"], "source_start": c["source_start"],
              "source_end": c["source_end"], "source_duration": c["source_duration"], "duration": c["duration"],
              "unit_ids": ["u0001", "u0001"], "segment_ids": ["s00001", "s00001"], "head_cut": None}
             for n, c in enumerate(cands[:2], 1)]
    clips_doc = {"schema_version": 1, "episode_id": episode_id, "candidates_sha256": sha(cand_doc), "clips": clips}
    titles_doc = {"schema_version": 1, "episode_id": episode_id, "clips_sha256": sha(clips_doc),
                  "candidates_sha256": sha(cand_doc), "header": {"lines": ["HT.Tịnh Không", "Kinh (tập 1)"]},
                  "titles": [{"clip_id": c["id"], "candidate_id": c["candidate_id"], "title": f"Tiêu đề {c['id']}",
                              "evidence": "x", "alternatives": [{"title": f"Phương án {c['id']}", "evidence": "y"}],
                              "status": "titled"} for c in clips]}
    props = proposals if proposals is not None else [
        {"topic": "Tâm và cảnh", "reason": "trọn ý", "score": 8, "status": "overlapped", "candidate_id": "c00003",
         "reject_reason": "overlaps selected c00002", "head_cut": None},
        {"topic": "Ngắn", "reason": "ngắn", "score": 6, "status": "ineligible", "candidate_id": "c00004",
         "reject_reason": "score < 7", "head_cut": None},
        {"topic": "Vượt", "reason": "hay", "score": 7, "status": "over_limit", "candidate_id": "c00005",
         "reject_reason": None, "head_cut": {"words": "thì", "original_start": cands[4]["source_start"],
                                             "source_start": round(cands[4]["source_start"] + 1.0, 3)}},
        {"topic": "Không map", "reason": "", "score": 9, "status": "rejected", "candidate_id": None,
         "reject_reason": "no candidate", "head_cut": None},
        {"topic": "Đã chọn", "reason": "", "score": 9, "status": "selected", "candidate_id": "c00001",
         "reject_reason": None, "head_cut": None}]
    log_doc = {"schema_version": 1, "episode_id": episode_id, "candidates_sha256": sha(cand_doc),
               "windows": [{"id": "w01", "proposals": props}]}
    shots = {"schema_version": 1, "episode_id": episode_id, "changes": shot_changes or [], "shots": []}
    meta = {"schema_version": 1, "episode_id": episode_id, "title": "Kinh tập 1", "duration": 520.0}
    for name, doc in (("transcript.json", transcript), ("silences.json", sil_doc), ("candidates.json", cand_doc),
                      ("clips.json", clips_doc), ("titles.json", titles_doc), ("selection_log.json", log_doc),
                      ("shots.json", shots), ("metadata.json", meta)):
        (ws.dir / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = ws.new_manifest({"kind": source_kind, "uri": f"https://youtu.be/{episode_id}", "path": "source.mp4",
                                "sha256": "0" * 64, "size": 4113, "mtime_ns": 0})
    for stage in ("ingest", "transcript", "analysis", "selection", "titling"):
        manifest["stages"][stage] = {"status": DONE, "artifacts": [], "inputs": [], "config_hash": "x",
                                     "started_at": None, "finished_at": None, "error": None}
    ws.save_manifest(manifest)
    return ws
