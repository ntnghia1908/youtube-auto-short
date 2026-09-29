"""Shared helpers for render tests: a synthetic episode with titling done (no AI), built directly.

Source: lavfi ``testsrc2`` 1440x1080 at 29.97 fps + ``sine``, 8 s (like the 4:3 test lecture).
Clip k01 has a head cut whose ``source_start`` falls inside a trim of its candidate (B11 "Cho CP7");
clip k02 is a plain clip with one trim.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from auto_short.hashing import canonical_json, fingerprint
from auto_short.workspace import DONE, Workspace

EID = "rbjfCfFq3Dk"
HEADER = ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"]
TITLES = {"k01": "Tâm thiện thì tướng mạo cũng từ bi", "k02": "Mỗi suy nghĩ đều là tội lỗi?"}

CANDIDATES = [
    {"id": "c00001", "source_start": 0.2, "source_end": 4.0, "source_duration": 3.8, "duration": 2.5,
     "trims": [[0.3, 1.1], [2.0, 2.5]]},
    {"id": "c00002", "source_start": 4.5, "source_end": 7.8, "source_duration": 3.3, "duration": 2.7,
     "trims": [[5.0, 5.6]]},
    {"id": "c00003", "source_start": 0.0, "source_end": 7.9, "source_duration": 7.9, "duration": 7.9, "trims": []},
]
# k01: head cut 0.2 -> 0.6, inside trim [0.3, 1.1]: segments [1.1, 2.0] + [2.5, 4.0] = 2.4 s
CLIPS = [
    {"id": "k01", "candidate_id": "c00001", "source_start": 0.6, "source_end": 4.0, "source_duration": 3.4,
     "duration": 2.4, "head_cut": {"words": "thì", "original_start": 0.2}},
    {"id": "k02", "candidate_id": "c00002", "source_start": 4.5, "source_end": 7.8, "source_duration": 3.3,
     "duration": 2.7, "head_cut": None},
]
SEGMENTS = {"k01": [[1.1, 2.0], [2.5, 4.0]], "k02": [[4.5, 5.0], [5.6, 7.8]]}


def sha(doc: dict) -> str:
    return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()


def make_source(path: Path, size: str = "1440x1080", rate: str = "30000/1001", seconds: int = 8) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate=48000",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2",
                    "-shortest", str(path)], check=True)
    return path


def write_docs(ws: Workspace, *, clips: list[dict] | None = None, titles: dict | None = None,
               candidates: list[dict] | None = None, header: list[str] | None = None,
               alternatives: dict | None = None, cand_extra: dict | None = None) -> None:
    """(Re)write candidates.json, clips.json and titles.json with consistent sha256 links.
    ``titles`` maps clip id -> title (None = untitled); default TITLES. ``alternatives`` maps clip id -> list of
    alternative titles (default none). ``cand_extra`` = more candidates.json keys (CP9: ``params``,
    ``silences_sha256``)."""
    cand_doc = {"schema_version": 1, "episode_id": ws.episode_id, "params": {},
                "candidates": CANDIDATES if candidates is None else candidates, **(cand_extra or {})}
    clips = CLIPS if clips is None else clips
    clips_doc = {"schema_version": 1, "episode_id": ws.episode_id, "candidates_sha256": sha(cand_doc),
                 "clips": clips}
    titles = TITLES if titles is None else titles
    entries = [{"clip_id": c["id"], "candidate_id": c["candidate_id"], "title": titles.get(c["id"]),
                "evidence": None,
                "alternatives": [{"title": a, "evidence": "x"} for a in (alternatives or {}).get(c["id"], [])],
                "status": "titled" if titles.get(c["id"]) else "untitled"}
               for c in clips]
    titles_doc = {"schema_version": 1, "episode_id": ws.episode_id, "clips_sha256": sha(clips_doc),
                  "candidates_sha256": sha(cand_doc), "header": {"lines": HEADER if header is None else header},
                  "titles": entries}
    for name, doc in (("candidates.json", cand_doc), ("clips.json", clips_doc), ("titles.json", titles_doc)):
        (ws.dir / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def make_render_episode(root: Path, template: Path, **docs) -> Workspace:
    ws = Workspace(root, EID)
    ws.dir.mkdir(parents=True)
    src = ws.dir / "source.mp4"
    shutil.copy2(template, src)
    fp = fingerprint(src)
    (ws.dir / "metadata.json").write_text(json.dumps({"schema_version": 1, "episode_id": EID, "title": "x"}),
                                          encoding="utf-8")
    write_docs(ws, **docs)
    manifest = ws.new_manifest({"kind": "local", "uri": str(src), "path": "source.mp4", "sha256": fp.sha256,
                                "size": fp.size, "mtime_ns": fp.mtime_ns})
    for stage in ("ingest", "transcript", "analysis", "selection", "titling"):
        manifest["stages"][stage] = {"status": DONE, "artifacts": [], "inputs": [], "config_hash": "x",
                                     "started_at": None, "finished_at": None, "error": None}
    ws.save_manifest(manifest)
    return ws
