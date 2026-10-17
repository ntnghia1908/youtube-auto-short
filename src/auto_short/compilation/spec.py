"""CP8.33: compilation spec (G1, G2, G4, G10): which khai thị clips, in which order, how many times. Pure functions,
no I/O. A spec is the *expanded* list of items (a loop repeats its item ``repeat`` times, ``auto`` round-robins the
usable favourites until the total reaches the requested length), so every mode is assembled the same way.

Canonical contract: docs/tasks/CP8.33-khaithi-compilation.md G1-G10.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field

from ..hashing import canonical_json

MODES = ("concat", "loop", "auto")
CID_RE = re.compile(r"^[0-9a-f]{12}$")
MAX_ITEMS = 10000  # sanity bound of the expanded list (720 min of 1 s clips would be 43200; khai thị are minutes long)
MIN_CONCAT = 2


class CompilationError(Exception):
    """User-facing problem (Vietnamese message): bad request, unusable item, ffmpeg failure."""


@dataclass(frozen=True)
class Item:
    """One khai thị clip: ``episode_id`` is the khai thị episode (``<video_id>.kt``), ``clip`` its clip id."""

    episode_id: str
    clip: str
    # G11: snapshot of a favourite whose episode was deleted (see ``store.kept_snapshot``); not part of the identity
    kept: dict | None = field(default=None, compare=False, hash=False)

    def to_json(self) -> dict:
        """Identity only (specs, ``<cid>.json``)."""
        return {"episode_id": self.episode_id, "clip": self.clip}

    def favorite_json(self) -> dict:
        """``favorites.json`` entry: identity + the ``kept`` snapshot when there is one."""
        out = self.to_json()
        if self.kept is not None:
            out["kept"] = self.kept
        return out


@dataclass(frozen=True)
class Spec:
    mode: str  # concat | loop | auto (G10: auto is stored as such but identified like concat)
    items: tuple[Item, ...]  # expanded, in playback order
    repeat: int = 1  # loop: how many times the single item is played; otherwise 1

    @property
    def cid(self) -> str:
        """G4: first 12 hex characters of sha256 of (mode, items, repeat); ``auto`` is a ``concat`` spec (G10)."""
        doc = {"mode": "loop" if self.mode == "loop" else "concat",
               "items": [[i.episode_id, i.clip] for i in self.items], "repeat": self.repeat}
        return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()[:12]


def item_from_json(value: object) -> Item:
    if not isinstance(value, dict) or not isinstance(value.get("episode_id"), str) \
            or not isinstance(value.get("clip"), str) or not value["episode_id"] or not value["clip"]:
        raise CompilationError("mục khai thị không hợp lệ")
    kept = value.get("kept")
    return Item(value["episode_id"], value["clip"], valid_kept(kept) if kept is not None else None)


def valid_kept(value: object) -> dict:
    """G11 snapshot: ``path`` (relative, inside the bộ kinh folder), ``title``, ``duration``, ``episode_number``
    (tập), ``clip_number`` (KT), ``clip_total`` (width of ``NN``), ``saved_at``."""
    if not isinstance(value, dict) or not isinstance(value.get("path"), str) or not value["path"] \
            or value["path"].startswith("/") or ".." in value["path"].split("/"):
        raise CompilationError("bản lưu khai thị không hợp lệ")
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)  # noqa: E731
    if not (value.get("title") is None or isinstance(value["title"], str)) or not num(value.get("duration")) \
            or not isinstance(value.get("episode_number"), str) or not isinstance(value.get("clip_number"), int) \
            or not isinstance(value.get("clip_total"), int) or not isinstance(value.get("saved_at"), str):
        raise CompilationError("bản lưu khai thị không hợp lệ")
    return {k: value[k] for k in ("path", "title", "duration", "episode_number", "clip_number", "clip_total", "saved_at")}


def check_minutes(minutes: object, max_minutes: int) -> int:
    """G2: total length asked for, an integer >= 1 and <= ``[compilation] max_minutes``."""
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1:
        raise CompilationError("tổng thời lượng phải là số phút nguyên ≥ 1")
    if minutes > max_minutes:
        raise CompilationError(f"tổng thời lượng tối đa {max_minutes} phút")
    return minutes


def check_total(seconds: float, max_minutes: int) -> None:
    if seconds > max_minutes * 60:
        raise CompilationError(f"video ghép dài {seconds / 60:.0f} phút, vượt giới hạn {max_minutes} phút")


def loop_count(duration: float, minutes: int) -> int:
    """G2: ``n = ceil(60 * minutes / d)`` so that ``n * d >= minutes``."""
    if duration <= 0:
        raise CompilationError("khai thị không có thời lượng")
    return max(1, math.ceil(60 * minutes / duration - 1e-9))


def build_concat(items: list[Item], durations: dict[Item, float], max_minutes: int) -> Spec:
    """G2 ``concat``: at least two distinct items, already in G1 order (the caller sorts)."""
    if len(set(items)) != len(items):
        raise CompilationError("mục khai thị bị trùng")
    if len(items) < MIN_CONCAT:
        raise CompilationError(f"cần chọn ít nhất {MIN_CONCAT} khai thị để ghép")
    check_total(sum(durations[i] for i in items), max_minutes)
    return Spec("concat", tuple(items))


def build_loop(item: Item, duration: float, minutes: int, max_minutes: int) -> Spec:
    """G2 ``loop``: ``item`` repeated ``n`` times; refused when ``n * d`` exceeds the maximum."""
    check_minutes(minutes, max_minutes)
    n = loop_count(duration, minutes)
    check_total(n * duration, max_minutes)
    return Spec("loop", (item,) * n, n)


def auto_plan(items: list[Item], durations: dict[Item, float], minutes: int, max_minutes: int) -> tuple[list[Item], int]:
    """G10: ``items`` (usable favourites, G1 order) played one after the other, starting again from the first when
    the list ends, until the total is >= ``60 * minutes`` (the last clip is never cut). Returns (expanded items,
    rounds started)."""
    check_minutes(minutes, max_minutes)
    if not items:
        raise CompilationError("chưa có khai thị yêu thích dùng được để tự ghép")
    target, total, out = 60 * minutes, 0.0, []
    while total < target:
        for item in items:
            if durations[item] <= 0:
                raise CompilationError("khai thị không có thời lượng")
            out.append(item)
            total += durations[item]
            if total >= target:
                break
        if len(out) > MAX_ITEMS:
            raise CompilationError("quá nhiều đoạn để ghép")
    check_total(total, max_minutes)
    return out, math.ceil(len(out) / len(items))


def build_auto(items: list[Item], durations: dict[Item, float], minutes: int, max_minutes: int) -> tuple[Spec, int]:
    expanded, rounds = auto_plan(items, durations, minutes, max_minutes)
    return Spec("auto", tuple(expanded)), rounds
