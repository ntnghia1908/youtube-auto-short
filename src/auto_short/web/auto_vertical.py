"""CP8.35: per-video wish "tự tạo bản dọc cả tập" (set by "Xử lý" with the ``Bản dọc`` box ticked), kept on disk next
to ``.web_priority.json`` so it survives a server restart. The key is the video id (``<id>.kt`` shares the wish of
``<id>``). Thread-safe (the lane workers read / clear it while the web handlers set it)."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from ..workspace import atomic_write_json
from .priority import base_id

log = logging.getLogger(__name__)

WISH_FILE = ".web_auto_vertical.json"


class AutoVertical:
    def __init__(self, path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._path: Path | None = None
        self._videos: set[str] = set()
        if path is not None:
            self.attach(path)

    def attach(self, path: Path) -> None:
        with self._lock:
            self._path = Path(path)
            self._videos = set()
            try:
                items = json.loads(self._path.read_text(encoding="utf-8"))["videos"]
                if not isinstance(items, list):
                    raise ValueError("videos is not a list")
                self._videos = {i for i in items if isinstance(i, str) and i}
            except FileNotFoundError:
                pass
            except (OSError, ValueError, KeyError, TypeError) as exc:
                log.warning("web: ý muốn tự tạo bản dọc %s không đọc được, bỏ qua: %s", self._path, exc)

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            atomic_write_json(self._path, {"version": 1, "videos": sorted(self._videos)})
        except Exception as exc:  # the wish keeps working in memory
            log.warning("web: không ghi được ý muốn tự tạo bản dọc %s: %s", self._path, exc)

    def wanted(self, episode_id: str) -> bool:
        with self._lock:
            return base_id(episode_id) in self._videos

    def videos(self) -> list[str]:
        with self._lock:
            return sorted(self._videos)

    def set(self, episode_id: str, value: bool) -> bool:
        """Set / clear the wish of the video; True when it changed."""
        vid = base_id(episode_id)
        with self._lock:
            if (vid in self._videos) == value:
                return False
            (self._videos.add if value else self._videos.discard)(vid)
            self._save()
            return True
