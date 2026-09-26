"""Shared helpers for titling tests: an episode with selection done (synthetic lecture), fake chat client."""

from __future__ import annotations

import json
import re
from pathlib import Path

from auto_short.config import Config, WorkspaceConfig
from auto_short.selection import run_selection
from auto_short.selection.client import ChatError, ChatResult
from selection_helpers import SYN_ANALYSIS, FakeClient as SelectionClient, make_selection_episode, proposal, response

VIDEO_TITLE = "Phật Thuyết Thập Thiện Nghiệp Đạo Kinh tập 9 - Lão Pháp Sư Tịnh Không"

# Selection replies giving two clips: k01 = c00008 (u0002..u0005), k02 = c00015 (u0007..u0010).
SELECTION = {"w01": [response(proposal("u0002", "u0005", 9))],
             "w02": [response(proposal("u0007", "u0010", 8))]}


def make_titling_episode(root: Path, *, prefix: dict[int, str] | None = None, title: str | None = VIDEO_TITLE,
                         selection: dict | None = None):
    """Workspace with ingest .. selection done; ``title`` is written to metadata.json first."""
    ws = make_selection_episode(root, prefix=prefix)
    meta_path = ws.dir / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if title is not None:
        meta["title"] = title
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    cfg = Config(workspace=WorkspaceConfig(dir=root), analysis=SYN_ANALYSIS)
    run_selection(ws.episode_id, cfg, client=SelectionClient(SELECTION if selection is None else selection))
    return ws


def option(title: str, evidence: str) -> dict:
    return {"evidence": evidence, "title": title}


def reply(*options: dict) -> str:
    return json.dumps({"options": list(options)}, ensure_ascii=False)


def good_reply(n: int) -> str:
    """Three valid options for the synthetic clip whose text starts with "ý thứ <n>"."""
    return reply(option(f"Ý thứ {n} khi học kinh", f"ý thứ {n} phần đầu chúng ta học kinh"),
                 option(f"Nhớ kỹ ý thứ {n}", f"ý thứ {n} phần cuối xin nhớ kỹ"),
                 option(f"Học kinh phần đầu ý {n}", f"phần đầu chúng ta học kinh"))


_CLIP_RE = re.compile(r"Lời nói của đoạn:\n(?:\S+ )*?ý thứ (\d+)")


class FakeClient:
    """Chat client double. ``replies`` maps the clip's first unit number (from its text "ý thứ <n>")
    to a list of replies consumed per call (a str is the content; an Exception is raised).
    Missing -> ``good_reply(n)``."""

    def __init__(self, replies: dict | None = None):
        self.replies = {k: list(v) for k, v in (replies or {}).items()}
        self.calls: list[dict] = []

    def chat(self, *, model, messages, format, options, think):
        n = int(_CLIP_RE.search(messages[-1]["content"]).group(1))
        self.calls.append({"clip": n, "model": model, "messages": messages, "format": format,
                           "options": options, "think": think})
        queue = self.replies.get(n)
        item = (queue.pop(0) if len(queue) > 1 else queue[0]) if queue else good_reply(n)
        if isinstance(item, Exception):
            raise item
        return ChatResult(content=item, thinking="nghĩ" if think else None, eval_count=10,
                          prompt_eval_count=100, total_duration=123, extra={"done_reason": "stop"})


def http_error() -> ChatError:
    return ChatError("HTTP 500 from fake: boom")
