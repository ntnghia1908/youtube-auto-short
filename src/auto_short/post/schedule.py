"""PST1: local community-post times and deterministic daily slots (no YouTube writes)."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..workspace import atomic_write_json, read_json_dict

ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
SLOTS = (time(9), time(15), time(20, 30))


def timestamp(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("post times must include a timezone")
    return result


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def path(workspace: Path) -> Path:
    return Path(workspace) / "_publish/post_times.json"


def read(file: Path) -> dict:
    doc = read_json_dict(file)
    if doc is None:
        if file.exists():
            raise ValueError("post_times.json: invalid JSON")
        return {}
    if doc.get("schema_version") != 1 or not isinstance(doc.get("times"), dict):
        raise ValueError("post_times.json: invalid schema")
    for key, entry in doc["times"].items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise ValueError("post_times.json: invalid entry")
        for field in ("video_at", "slot_at"):
            if entry.get(field) is not None:
                timestamp(entry[field])
    return doc["times"]


def write(file: Path, times: dict) -> None:
    atomic_write_json(file, {"schema_version": 1, "times": times})


def video_at(entry: dict) -> str | None:
    status, snippet = entry.get("status") or {}, entry.get("snippet") or {}
    value = status.get("publishAt")
    if not value and status.get("privacyStatus") == "public":
        value = snippet.get("publishedAt")
    if value:
        timestamp(value)
    return value or None


def slots_after(t: datetime):
    """Yield VN slots at or after the aware instant t, including an exact boundary."""
    local = timestamp(t).astimezone(ZONE)
    day = local.date()
    while True:
        for clock in SLOTS:
            slot = datetime.combine(day, clock, ZONE)
            if slot >= local:
                yield slot
        day += timedelta(days=1)


def plan(posts: list[dict], times: dict, now: datetime) -> dict[str, str | None]:
    """One website playlist per call. Posts carry episode_id, clip_id, code, posted_at.

    Return key -> slot_at in video-time / numeric-code order, with unscheduled posts last.
    Only ticked posts with a saved slot reserve capacity; legacy ticks reserve nothing.
    """
    floor = timestamp(now) + timedelta(minutes=10)
    occupied, planned, pending = set(), {}, []
    for post in posts:
        key = f'{post["episode_id"]}/{post["clip_id"]}'
        saved = times.get(key, {})
        if post.get("posted_at"):
            planned[key] = saved.get("slot_at")
            if saved.get("slot_at"):
                occupied.add(timestamp(saved["slot_at"]))
        else:
            at = timestamp(saved["video_at"]) if saved.get("video_at") else None
            numbers = tuple(int(n) for n in re.findall(r"\d+", post["code"]))
            pending.append((at, numbers, post["code"], key))
    pending.sort(key=lambda row: (row[0] is None, row[0] or floor, *row[1:]))
    slots = slots_after(floor)
    slot = next(slots)
    for at, _, _, key in pending:
        if at is None:
            planned[key] = None
            continue
        while slot < at or slot in occupied:
            slot = next(slots)
        planned[key] = _iso(slot)
        slot = next(slots)
    return planned


def slot_fields(slot_at: str | None) -> dict:
    label = None
    if slot_at:
        local = timestamp(slot_at).astimezone(ZONE)
        weekday = "Chủ nhật" if local.weekday() == 6 else f"Thứ {local.weekday() + 2}"
        label = f"{weekday} {local:%d/%m %H:%M}"
    return {"slot_at": slot_at, "slot_label": label}
