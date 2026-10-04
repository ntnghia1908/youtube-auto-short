"""CP8.26: per-video priority mark of the job queue (P1) — ordered, kept on disk next to ``.web_queue.json``.

The key is the *base video id* (the Short episode id): the khai thị episode ``<id>.kt`` shares the mark of ``<id>``.
``rank`` is the position in mark order (smaller = earlier), None = not marked. Thread-safe (the lane workers and the
enhance lease read it while the web handlers change it)."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from ..workspace import atomic_write_json

log = logging.getLogger(__name__)

PRIORITY_FILE = ".web_priority.json"
_KT = ".kt"


def base_id(episode_id: str) -> str:
    """``<id>.kt`` -> ``<id>``; a ``#post`` / ``#hd`` runner key -> its episode id."""
    eid = episode_id.split("#", 1)[0]
    return eid[:-len(_KT)] if eid.endswith(_KT) else eid


class Priority:
    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._order: list[str] = []
        self._rank: dict[str, int] = {}
        self.on_change = None  # called (no lock held) after a change, e.g. to wake the lane workers
        self._load()

    def attach(self, path: Path) -> None:
        """Keep the marks in ``path`` from now on, starting with what it holds."""
        with self._lock:
            self._path = Path(path)
            self._load()

    def _load(self) -> None:
        if self._path is None:
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            items = data["videos"]
            if not isinstance(items, list):
                raise ValueError("videos is not a list")
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("web: đánh dấu ưu tiên %s không đọc được, bỏ qua: %s", self._path, exc)
            return
        self._set([i for i in items if isinstance(i, str) and i])

    def _set(self, order: list[str]) -> None:
        seen: list[str] = []
        for i in order:
            if i not in seen:
                seen.append(i)
        self._order = seen
        self._rank = {v: n for n, v in enumerate(seen)}

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            atomic_write_json(self._path, {"version": 1, "videos": list(self._order)})
        except Exception as exc:  # the mark keeps working in memory
            log.warning("web: không ghi được đánh dấu ưu tiên %s: %s", self._path, exc)

    def rank(self, episode_id: str) -> int | None:
        with self._lock:
            return self._rank.get(base_id(episode_id))

    def marked(self, episode_id: str) -> bool:
        return self.rank(episode_id) is not None

    def videos(self) -> list[str]:
        with self._lock:
            return list(self._order)

    def mark(self, video_ids: list[str]) -> list[str]:
        """Add ``video_ids`` (in the given order, after the existing marks); returns the ones newly marked."""
        with self._lock:
            new = [v for v in dict.fromkeys(base_id(v) for v in video_ids) if v not in self._rank]
            if new:
                self._set(self._order + new)
                self._save()
        self._changed(new)
        return new

    def unmark(self, video_ids: list[str]) -> list[str]:
        with self._lock:
            drop = {base_id(v) for v in video_ids} & set(self._rank)
            if drop:
                self._set([v for v in self._order if v not in drop])
                self._save()
        self._changed(drop)
        return sorted(drop)

    def _changed(self, changed) -> None:
        cb = self.on_change
        if changed and cb is not None:
            cb()
