"""Shared helpers for selection tests: small synthetic candidates.json, fake chat client, episode setup."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from auto_short.analysis import run_analysis
from auto_short.analysis.stage import analyze
from auto_short.config import AnalysisConfig
from auto_short.hashing import canonical_json
from auto_short.selection.client import ChatError, ChatResult
from analysis_helpers import REAL, FakeAnalyzer, make_analysis_episode, real_segments, real_silences, seg

# Analysis config for the synthetic lecture: no outro detection (music label is mid-lecture).
SYN_ANALYSIS = AnalysisConfig(outro_window=5.0)


def synthetic_lecture() -> tuple[list[dict], list[tuple[float, float]], list[float], float]:
    """Two windows separated by a ``[âm nhạc]`` hard break: 6 + 5 units of 20 s speech
    (two segments with a 2 s inner pause) separated by 4 s silences. One shot change right
    after the start of u0003 so candidates starting at u0003 are removed by the shot guard.
    Returns (segments, silences, shot_changes, duration)."""
    segments, silences, n = [], [], 1
    starts = []

    def block(t: float, count: int) -> float:
        nonlocal n
        for k in range(count):
            starts.append(t)
            segments.append(seg(n, t, t + 9.0, f"ý thứ {len(starts)} phần đầu chúng ta học kinh")); n += 1
            silences.append((t + 9.0, t + 11.0))
            segments.append(seg(n, t + 11.0, t + 20.0, f"ý thứ {len(starts)} phần cuối xin nhớ kỹ")); n += 1
            silences.append((t + 20.0, t + 24.0))
            t += 24.0
        return t

    t = block(5.0, 6)  # 149.0
    segments.append(seg(n, t + 1.0, t + 11.0, kind="non_speech")); n += 1  # hard break 150-160
    t = block(t + 16.0, 5)
    duration = round(t + 5.0, 3)
    return segments, silences, [round(starts[2] + 0.5, 3)], duration


def transcript_doc(segments: list[dict]) -> dict:
    return {"transcript_sha256": hashlib.sha256(canonical_json(segments).encode()).hexdigest(),
            "segments": segments}


def synthetic_docs() -> tuple[dict, dict, dict]:
    """(candidates doc, silences doc, metadata) for the synthetic lecture."""
    segments, silences, changes, duration = synthetic_lecture()
    metadata = {"duration": duration, "source": {"sha256": "ab" * 32}, "title": "Bài giảng thử"}
    _, sil_doc, cand_doc = analyze("syn", transcript_doc(segments), metadata, changes, silences, SYN_ANALYSIS)
    return cand_doc, sil_doc, metadata


def real_docs() -> tuple[dict, dict, dict]:
    """Candidates of the real test video (fixture extract of rbjfCfFq3Dk)."""
    metadata = {"duration": REAL["duration"], "source": {"sha256": "ab" * 32}, "title": "Thập Thiện Nghiệp Đạo"}
    _, sil_doc, cand_doc = analyze("rbjfCfFq3Dk", transcript_doc(real_segments()), metadata,
                                   list(REAL["shot_changes"]), real_silences(), AnalysisConfig())
    return cand_doc, sil_doc, metadata


def proposal(first: str, last: str, score: int = 8, start: bool = True, end: bool = True,
             topic: str = "chủ đề", reason: str = "trọn ý") -> dict:
    return {"first_unit": first, "last_unit": last, "topic": topic, "reason": reason,
            "start_complete": start, "end_complete": end, "score": score}


def response(*proposals: dict) -> str:
    return json.dumps({"clips": list(proposals)}, ensure_ascii=False)


_WINDOW_RE = re.compile(r"^Đoạn (\S+):", re.M)


class FakeClient:
    """Chat client double. ``replies`` maps window id -> list of replies consumed per call
    (a str is the content; an Exception is raised). Missing window -> ``{"clips": []}``."""

    def __init__(self, replies: dict | None = None):
        self.replies = {k: list(v) for k, v in (replies or {}).items()}
        self.calls: list[dict] = []

    def chat(self, *, model, messages, format, options, think):
        wid = _WINDOW_RE.search(messages[-1]["content"]).group(1)
        self.calls.append({"window": wid, "model": model, "messages": messages, "format": format,
                           "options": options, "think": think})
        queue = self.replies.get(wid)
        reply = (queue.pop(0) if len(queue) > 1 else queue[0]) if queue else response()
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(content=reply, thinking="nghĩ" if think else None, eval_count=10,
                          prompt_eval_count=100, total_duration=123)


def http_error() -> ChatError:
    return ChatError("HTTP 500 from fake: boom")


def make_selection_episode(root: Path, *, analysis_status: str = "done"):
    """Workspace with ingest + transcript + analysis done on the synthetic lecture."""
    segments, silences, changes, duration = synthetic_lecture()
    ws = make_analysis_episode(root, segments=segments, duration=duration)
    from auto_short.config import Config, WorkspaceConfig
    cfg = Config(workspace=WorkspaceConfig(dir=root), analysis=SYN_ANALYSIS)
    run_analysis(ws.episode_id, cfg, analyzer=FakeAnalyzer(changes=changes, silences=silences))
    if analysis_status != "done":
        manifest = ws.load_manifest()
        manifest["stages"]["analysis"]["status"] = analysis_status
        ws.save_manifest(manifest)
    return ws
