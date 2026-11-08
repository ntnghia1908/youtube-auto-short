"""One in-memory watch room. No I/O; all reads and commands share one lock."""

from __future__ import annotations

import math
import re
import secrets
import threading
import time
import unicodedata
from copy import deepcopy


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


MAX_QUEUE = 1000  # whole sutra series (AG 35); the listen API itself has no cap
_FILE_URL = re.compile(r"^/files/([^/]+)/[^/]+\.mp4$")


def episode_of(entry) -> str | None:
    """Episode id from a /files/<id>/x.mp4 url (a .kt khai thi belongs to its base episode)."""
    match = _FILE_URL.match(entry["url"].split("?")[0])
    return match.group(1).removesuffix(".kt") if match else None


class WatchRoom:
    def __init__(self, *, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._queue = []
        self._queue_version = 0
        self._epoch = secrets.token_hex(4)  # a restarted server never matches a stale client cache
        self._index = 0
        self._paused = True
        self._auto = True
        self._continuous = False
        self._advance_at = None
        self._ended_version = None
        self._finished = False
        self._position = 0.0
        self._rate = 1.0
        self._updated_at = clock()
        self._version = 0
        self._by = None
        self._viewers = {}

    def _group_of(self, entry):
        # Explicit parts take precedence over the legacy continuous-room flag.
        if "group" in entry:
            return ("group", entry["group"]["id"])
        return ("legacy", None) if self._continuous else ("episode", episode_of(entry))

    def _same_group_next(self, index):
        """Auto-advance stays within the playing group (episode or favorites part)."""
        nxt = index + 1
        return nxt < len(self._queue) and self._group_of(self._queue[nxt]) == self._group_of(self._queue[index])

    def _apply_advance(self, now):
        if self._advance_at is None or now < self._advance_at:
            return
        at, self._advance_at = self._advance_at, None
        if self._auto and self._same_group_next(self._index):
            self._index += 1
            self._position, self._paused = 0.0, False
            self._finished = False
        else:
            self._paused = True
        self._updated_at, self._by = at, None
        self._version += 1

    def _snapshot(self, now):
        self._viewers = {c: t for c, t in self._viewers.items() if now - t < 10}
        current = self._queue[self._index] if self._queue else None
        return dict(queue=deepcopy(self._queue), queue_version=f"{self._epoch}.{self._queue_version}", index=self._index,
                    video_url=current["url"] if current else None, title=current["title"] if current else "",
                    paused=self._paused, auto=self._auto, continuous=self._continuous, finished=self._finished, advance_at=self._advance_at,
                    position=self._position, rate=self._rate,
                    updated_at=self._updated_at, version=self._version, by=self._by,
                    viewers=dict(self._viewers), server_time=now)

    def snapshot(self, client=None):
        if client is not None:
            _client(client)
        with self._lock:
            now = self._clock()
            self._apply_advance(now)
            if client is not None and self._queue:
                self._viewers[client] = now
            return self._snapshot(now)

    def command(self, client, action, **data):
        """Apply a due deadline, then validate and atomically anchor the requested control."""
        _client(client)
        with self._lock:
            now = self._clock()
            self._apply_advance(now)
            if action == "leave":
                self._viewers.pop(client, None)
                return self._snapshot(now)
            queue = None
            index = self._index
            position = self._position + (0 if self._paused else (now - self._updated_at) * self._rate)
            rate, paused = self._rate, self._paused
            auto, advance_at = self._auto, self._advance_at
            continuous = self._continuous
            ended_version = self._ended_version
            finished = self._finished
            if action == "ended":
                expected = data.get("expect_version")
                if type(expected) is not int:
                    raise ValueError("Cần expect_version")
                end_position = _number(data.get("position", position), "position")
                if expected == self._ended_version:
                    return self._snapshot(now)
                if expected != self._version:
                    raise WatchConflict("Video đã được thay đổi; tải lại trạng thái")
                if self._finished:
                    return self._snapshot(now)
                if not self._queue:
                    raise ValueError("Chưa có phòng xem chung")
                ended_version, position, paused = expected, end_position, True
                finished = True
                advance_at = now + 3 if auto and self._same_group_next(index) else None
            elif action in ("advance_now", "cancel_advance"):
                if "expect_version" in data:
                    if type(data["expect_version"]) is not int:
                        raise ValueError("Cần expect_version")
                    if data["expect_version"] != self._version:
                        raise WatchConflict("Video đã được thay đổi; tải lại trạng thái")
                if advance_at is None:
                    return self._snapshot(now)
                advance_at = None
                if action == "advance_now" and auto and self._same_group_next(index):
                    index, position, paused = index + 1, 0.0, False
                    finished = False
                else:
                    paused = True
            elif action == "set":
                queue = data.get("queue")
                if queue is None and "video_url" in data:
                    queue = [dict(url=data["video_url"], title=data.get("title", ""))]
                if not isinstance(queue, list) or not 1 <= len(queue) <= MAX_QUEUE:
                    raise ValueError(f"Danh sách phải có từ 1 đến {MAX_QUEUE} video")
                clean = []
                for entry in queue:
                    if not isinstance(entry, dict):
                        raise ValueError("Video không hợp lệ")
                    url = validate_url(entry.get("url"))
                    title = entry.get("title", "")
                    if not isinstance(title, str) or len(title) > 200:
                        raise ValueError("Tiêu đề tối đa 200 ký tự")
                    item = dict(url=url, title=title)
                    label = entry.get("ep_label")
                    if label is not None:
                        if not isinstance(label, str) or len(label) > 40:
                            raise ValueError("Nhãn tập tối đa 40 ký tự")
                        item["ep_label"] = label
                    if "group" in entry:
                        group = entry["group"]
                        if not isinstance(group, dict) or set(group) - {"id", "label", "choice", "kind"}:
                            raise ValueError("Nhóm không hợp lệ")
                        for field, limit in (("id", 100), ("label", 80), ("choice", 160)):
                            value = group.get(field)
                            if field == "choice" and value is None:
                                continue
                            if (not isinstance(value, str) or not value.strip() or len(value) > limit
                                    or any(unicodedata.category(c).startswith("C") for c in value)):
                                raise ValueError("Nhãn / mã nhóm không hợp lệ")
                        if group.get("kind", "part") not in ("part", "episode"):
                            raise ValueError("Loại nhóm không hợp lệ")
                        item["group"] = {**group, "kind": group.get("kind", "part")}
                    clean.append(item)
                queue = clean
                index = _index(data.get("index", 0), len(queue))
                position = _number(data.get("position", 0), "position")
                rate = _number(data.get("rate", 1), "rate", .25, 4)
                paused = data.get("paused", False)
                if type(paused) is not bool:
                    raise ValueError("paused không hợp lệ")
                continuous = data.get("continuous", False)
                if type(continuous) is not bool:
                    raise ValueError("continuous phải là boolean")
                advance_at, ended_version = None, None
                finished = False
            elif action == "end":
                queue, index, position, rate, paused = [], 0, 0.0, 1.0, True
                auto, continuous = True, False
                advance_at, ended_version = None, None
                finished = False
            elif action == "auto":
                auto = data.get("auto")
                if type(auto) is not bool:
                    raise ValueError("auto phải là boolean")
                if not self._queue:
                    raise ValueError("Chưa có phòng xem chung")
                if not auto:
                    advance_at = None
            elif action in ("play", "pause", "seek", "rate", "goto", "episode", "group", "next", "prev"):
                advance_at = None
                if action in ("play", "seek", "goto", "episode", "group", "next", "prev"):
                    finished = False
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
                        position, paused = 0.0, False
                elif action == "goto":
                    index = _index(data.get("index"), len(self._queue))
                    position, paused = 0.0, False
                elif action in ("episode", "group"):
                    # Keep the old episode command for old clients / invitations.
                    wanted = data.get(action)
                    if not isinstance(wanted, str):
                        raise ValueError(f"{action} không hợp lệ")
                    found = [n for n, e in enumerate(self._queue)
                             if (e.get("group", {}).get("id") if action == "group" else episode_of(e)) == wanted]
                    if not found:
                        raise ValueError("Không có nhóm này trong danh sách")
                    index, position, paused = found[0], 0.0, False
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
                self._queue_version += 1
                if action == "end":
                    self._viewers.clear()
            self._index, self._position, self._rate, self._paused = index, position, rate, paused
            self._auto, self._advance_at, self._ended_version = auto, advance_at, ended_version
            self._continuous = continuous
            self._finished = finished
            self._updated_at, self._by = now, client
            self._version += 1
            if self._queue:
                self._viewers[client] = now
            return self._snapshot(now)
