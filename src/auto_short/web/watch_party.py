"""One in-memory watch room. No I/O; all reads and commands share one lock."""

from __future__ import annotations

import math
import threading
import time
import unicodedata


class WatchConflict(ValueError):
    """Another viewer has already changed the playback version."""


def validate_url(value) -> str:
    if (not isinstance(value, str) or not value.startswith("/") or value.startswith("//")
            or "\\" in value or len(value) > 2048
            or any(unicodedata.category(c) == "Cc" for c in value)):
        raise ValueError("URL phải là đường dẫn cùng origin, tối đa 2048 ký tự")
    return value


def _number(value, name, minimum=0, maximum=None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} không hợp lệ")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{name} không hợp lệ") from None
    if not math.isfinite(number) or number < minimum or (maximum is not None and number > maximum):
        raise ValueError(f"{name} không hợp lệ")
    return number


def _index(value, size) -> int:
    if type(value) is not int or not 0 <= value < size:
        raise ValueError("index không hợp lệ")
    return value


def _client(value) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError("client không hợp lệ")
    return value


class WatchRoom:
    def __init__(self, *, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._queue = []
        self._index = 0
        self._paused = True
        self._auto = True
        self._position = 0.0
        self._rate = 1.0
        self._updated_at = clock()
        self._version = 0
        self._by = None
        self._viewers = {}

    def _snapshot(self, now):
        self._viewers = {c: t for c, t in self._viewers.items() if now - t < 10}
        current = self._queue[self._index] if self._queue else None
        return dict(queue=[dict(e) for e in self._queue], index=self._index,
                    video_url=current["url"] if current else None, title=current["title"] if current else "",
                    paused=self._paused, auto=self._auto, position=self._position, rate=self._rate,
                    updated_at=self._updated_at, version=self._version, by=self._by,
                    viewers=dict(self._viewers), server_time=now)

    def snapshot(self, client=None):
        if client is not None:
            _client(client)
        with self._lock:
            now = self._clock()
            if client is not None and self._queue:
                self._viewers[client] = now
            return self._snapshot(now)

    def command(self, client, action, **data):
        """Validate before mutation, then atomically anchor playback and advance its version."""
        _client(client)
        with self._lock:
            now = self._clock()
            if action == "leave":
                self._viewers.pop(client, None)
                return self._snapshot(now)
            queue = None
            index = self._index
            position = self._position + (0 if self._paused else (now - self._updated_at) * self._rate)
            rate, paused = self._rate, self._paused
            auto = self._auto
            if action == "set":
                queue = data.get("queue")
                if queue is None and "video_url" in data:
                    queue = [dict(url=data["video_url"], title=data.get("title", ""))]
                if not isinstance(queue, list) or not 1 <= len(queue) <= 300:
                    raise ValueError("Danh sách phải có từ 1 đến 300 video")
                clean = []
                for entry in queue:
                    if not isinstance(entry, dict):
                        raise ValueError("Video không hợp lệ")
                    url = validate_url(entry.get("url"))
                    title = entry.get("title", "")
                    if not isinstance(title, str) or len(title) > 200:
                        raise ValueError("Tiêu đề tối đa 200 ký tự")
                    clean.append(dict(url=url, title=title))
                queue = clean
                index = _index(data.get("index", 0), len(queue))
                position = _number(data.get("position", 0), "position")
                rate = _number(data.get("rate", 1), "rate", .25, 4)
                paused = data.get("paused", False)
                if type(paused) is not bool:
                    raise ValueError("paused không hợp lệ")
            elif action == "end":
                queue, index, position, rate, paused = [], 0, 0.0, 1.0, True
                auto = True
            elif action == "auto":
                auto = data.get("auto")
                if type(auto) is not bool:
                    raise ValueError("auto phải là boolean")
                if not self._queue:
                    raise ValueError("Chưa có phòng xem chung")
            elif action in ("play", "pause", "seek", "rate", "goto", "next", "prev"):
                if not self._queue:
                    raise ValueError("Chưa có phòng xem chung")
                if action in ("next", "prev"):
                    expected = data.get("expect_version")
                    if type(expected) is not int:
                        raise ValueError("Cần expect_version")
                    if expected != self._version:
                        raise WatchConflict("Video đã được thay đổi; tải lại trạng thái")
                    index = max(0, min(len(self._queue) - 1, index + (1 if action == "next" else -1)))
                    if action == "next" and self._index == len(self._queue) - 1:
                        paused = True
                    else:
                        position = 0.0
                elif action == "goto":
                    index = _index(data.get("index"), len(self._queue))
                    position = 0.0
                elif action == "seek":
                    position = _number(data.get("position"), "position")
                elif action == "rate":
                    rate = _number(data.get("rate"), "rate", .25, 4)
                else:
                    paused = action == "pause"
                if action in ("play", "pause", "rate") and "position" in data:
                    position = _number(data["position"], "position")
            else:
                raise ValueError("Lệnh xem chung không hợp lệ")
            if queue is not None:
                self._queue = queue
                if action == "end":
                    self._viewers.clear()
            self._index, self._position, self._rate, self._paused = index, position, rate, paused
            self._auto = auto
            self._updated_at, self._by = now, client
            self._version += 1
            if self._queue:
                self._viewers[client] = now
            return self._snapshot(now)
