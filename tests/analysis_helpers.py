"""Shared helpers for analysis tests: real-data fixture, synthetic transcripts, fake detector."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from auto_short.hashing import canonical_json, sha256_file
from auto_short.workspace import Workspace, atomic_write_json
from transcript_helpers import make_episode

FIXTURES = Path(__file__).parent / "fixtures"
REAL = json.loads((FIXTURES / "rbjfCfFq3Dk.analysis.json").read_text(encoding="utf-8"))
SHOWINFO_LOG = (FIXTURES / "showinfo.log").read_text(encoding="utf-8")
SILENCEDETECT_LOG = (FIXTURES / "silencedetect.log").read_text(encoding="utf-8")


def real_segments() -> list[dict]:
    return [dict(s, words=[]) for s in REAL["segments"]]


def real_silences() -> list[tuple[float, float]]:
    return [tuple(x) for x in REAL["silences"]]


def seg(n: int, start: float, end: float, text: str = "chúng ta học kinh", kind: str = "speech") -> dict:
    return {"id": f"s{n:05d}", "start": start, "end": end, "kind": kind,
            "text": "[âm nhạc]" if kind == "non_speech" else text, "words": []}


def lecture(n_units: int, *, unit: float = 20.0, gap: float = 4.0, start: float = 5.0,
            inner_pause: float = 2.0) -> tuple[list[dict], list[tuple[float, float]], float]:
    """Synthetic lecture: ``n_units`` speech blocks of two caption segments each, separated by
    ``gap`` s silences (aligned with the next segment start) and one ``inner_pause`` s silence
    in the middle of each block. Returns (segments, silences, duration)."""
    segments, silences = [], []
    t, n = start, 1
    for _ in range(n_units):
        half = (unit - inner_pause) / 2
        segments.append(seg(n, t, t + half)); n += 1
        silences.append((t + half, t + half + inner_pause))
        segments.append(seg(n, t + half + inner_pause, t + unit)); n += 1
        silences.append((t + unit, t + unit + gap))
        t += unit + gap
    return segments, silences, round(t + 5.0, 3)


class FakeAnalyzer:
    """Stands in for ffmpeg: returns fixed shot changes / silences and records calls."""

    def __init__(self, changes=None, silences=None, fail: str | None = None):
        self.changes = list(REAL["shot_changes"]) if changes is None else changes
        self.silence_list = real_silences() if silences is None else silences
        self.fail = fail
        self.calls: list[str] = []

    def shot_changes(self, media, *, threshold, scale_width):
        self.calls.append("shots")
        if self.fail:
            from auto_short.analysis import AnalysisError
            raise AnalysisError(self.fail)
        return list(self.changes)

    def silences(self, media, *, noise_db, min_seconds, duration):
        self.calls.append("silences")
        return list(self.silence_list)


def write_transcript(ws: Workspace, segments: list[dict]) -> None:
    doc = {
        "schema_version": 1, "episode_id": ws.episode_id, "source": "youtube",
        "method": "youtube_auto_caption", "language": "vi", "media_sha256": "ab" * 32,
        "raw": None, "provider": {}, "attempts": [], "stats": {},
        "transcript_sha256": hashlib.sha256(canonical_json(segments).encode("utf-8")).hexdigest(),
        "segments": segments,
    }
    atomic_write_json(ws.dir / "transcript.json", doc)


def make_analysis_episode(root: Path, *, episode_id: str = "rbjfCfFq3Dk", segments: list[dict] | None = None,
                          duration: float | None = None, audio: bool = True,
                          transcript_status: str = "done") -> Workspace:
    """Workspace with ingest + transcript done (no media processing)."""
    ws, _ = make_episode(root, episode_id=episode_id, kind="youtube",
                         duration=REAL["duration"] if duration is None else duration)
    if not audio:
        meta = json.loads((ws.dir / "metadata.json").read_text(encoding="utf-8"))
        atomic_write_json(ws.dir / "metadata.json", dict(meta, audio_codec=None))
    write_transcript(ws, real_segments() if segments is None else segments)
    manifest = ws.load_manifest()
    manifest["stages"]["transcript"] = {
        "status": transcript_status, "artifacts": ["transcript.json"],
        "inputs": [{"path": "metadata.json", "sha256": sha256_file(ws.dir / "metadata.json")}],
        "config_hash": "t", "started_at": "2026-09-26T00:00:00Z", "finished_at": "2026-09-26T00:00:00Z",
        "error": None,
    }
    ws.save_manifest(manifest)
    return ws
