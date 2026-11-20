"""PST1/PST2: local community-post times, manual anchors and deterministic daily slots."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..workspace import atomic_write_json, read_json_dict
from . import links

ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
SLOTS = (time(9), time(15), time(20, 30))
LEGACY_BEFORE = datetime(2026, 11, 19, tzinfo=ZONE)


def timestamp(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("post times must include a timezone")
    return result


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def path(workspace: Path) -> Path:
    return Path(workspace) / "_publish/post_times.json"


def code_order(code: str) -> tuple[int, int, int]:
    """Numeric episode order, with every Short before the episode's khai thị."""
    if not isinstance(code, str) or links.parse_code(code) != code:
        raise ValueError("mã bài không hợp lệ")
    episode, kind, clip = re.fullmatch(r"T(\d+)_(S|KT)(\d+)", code).groups()
    return int(episode), int(kind == "KT"), int(clip)


def validate_anchor(anchor: dict) -> dict:
    if not isinstance(anchor, dict):
        raise ValueError("mốc phải có code và slot_at")
    code_order(anchor.get("code"))
    return {"code": anchor["code"], "slot_at": _iso(timestamp(anchor.get("slot_at")))}


def _read_document(file: Path) -> dict:
    doc = read_json_dict(file)
    if doc is None:
        if file.exists():
            raise ValueError("post_times.json: invalid JSON")
        return {"times": {}, "anchors": {}}
    if doc.get("schema_version") != 1 or not isinstance(doc.get("times"), dict):
        raise ValueError("post_times.json: invalid schema")
    for key, entry in doc["times"].items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise ValueError("post_times.json: invalid entry")
        for field in ("video_at", "slot_at"):
            if entry.get(field) is not None:
                timestamp(entry[field])
    anchors = doc.get("anchors", {})
    if not isinstance(anchors, dict):
        raise ValueError("post_times.json: invalid anchors")
    for key, anchor in anchors.items():
        if not isinstance(key, str) or not key:
            raise ValueError("post_times.json: invalid anchor key")
        validate_anchor(anchor)
    return doc


def read(file: Path) -> dict:
    return _read_document(file)["times"]


def read_anchors(file: Path) -> dict:
    return _read_document(file).get("anchors", {})


def write(file: Path, times: dict, anchors: dict | None = None) -> None:
    if anchors is None:
        anchors = read_anchors(file)
    anchors = {key: validate_anchor(anchor) for key, anchor in anchors.items()}
    atomic_write_json(file, {"schema_version": 1, "times": times, "anchors": anchors})


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


def plan(posts: list[dict], times: dict, now: datetime, anchor: dict | None = None) -> dict[str, str | None]:
    """One website playlist per call. Posts carry episode_id, clip_id, code, posted_at.

    Without an anchor, retain PST1 video-time order and P3a legacy exclusion.
    An anchor replaces P3a: skip codes through it and schedule later codes in numeric order.
    Saved ticked slots always reserve capacity.
    """
    floor = timestamp(now) + timedelta(minutes=10)
    if anchor is not None:
        anchor = validate_anchor(anchor)
        # slots_after includes an exact boundary; an anchor's own slot is excluded.
        floor = max(floor, timestamp(anchor["slot_at"]) + timedelta(seconds=1))
    occupied, planned, pending = set(), {}, []
    for post in posts:
        key = f'{post["episode_id"]}/{post["clip_id"]}'
        saved = times.get(key, {})
        if post.get("posted_at"):
            planned[key] = saved.get("slot_at")
            if saved.get("slot_at"):
                occupied.add(timestamp(saved["slot_at"]))
        else:
            if slot_group(post, saved, None, anchor) in {"legacy", "manual"}:
                planned[key] = None
                continue
            at = timestamp(saved["video_at"]) if saved.get("video_at") else None
            numbers = (code_order(post["code"]) if anchor else
                       tuple(int(n) for n in re.findall(r"\d+", post["code"])))
            if anchor and at is None:
                at = floor
            pending.append((at, numbers, post["code"], key))
    pending.sort(key=(lambda row: row[1:]) if anchor else
                 (lambda row: (row[0] is None, row[0] or floor, *row[1:])))
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


def slot_group(post: dict, saved: dict, slot_at: str | None, anchor: dict | None = None) -> str:
    if slot_at:
        return "scheduled"
    if anchor:
        if (not post.get("posted_at") and links.parse_code(post.get("code"))
                and code_order(post["code"]) <= code_order(anchor["code"])):
            return "manual"
        return "unscheduled"
    # Ticked legacy posts stay in the legacy section (they never get a saved slot).
    if saved.get("video_at") and timestamp(saved["video_at"]) < LEGACY_BEFORE:
        return "legacy"
    return "unscheduled"


def slot_fields(slot_at: str | None) -> dict:
    label = None
    if slot_at:
        local = timestamp(slot_at).astimezone(ZONE)
        # PST2: HUMAN LEAD 2026-11-20 bỏ thứ, giờ AM / PM như app YouTube.
        label = f"{local:%d/%m} {local.hour % 12 or 12}:{local:%M} {'AM' if local.hour < 12 else 'PM'}"
    return {"slot_at": slot_at, "slot_label": label}
