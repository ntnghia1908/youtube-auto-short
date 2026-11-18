"""PUB3: classify owned videos and append private uploads to fixed Vietnam slots."""
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from ..render.text import nfc
from ..workspace import atomic_write_json, read_json_dict, utc_now
from . import PublishError, kt, shorts

VN = ZoneInfo("Asia/Ho_Chi_Minh")
SLOTS = {"vertical": (time(6),), "kt": (time(12, 30), time(20, 30)),
         "short": (time(7), time(11), time(18, 45))}
KINDS = {"vertical": "bản dọc", "kt": "khai thị", "short": "Short"}
WRITABLE_STATUS = ("embeddable", "license", "publicStatsViewable", "selfDeclaredMadeForKids",
                   "containsSyntheticMedia")


def classify(video):
    """Use the original filename; fall back to title only when it is absent."""
    name = (video.get("fileDetails") or {}).get("fileName")
    if not isinstance(name, str) or not name.strip():
        name = (video.get("snippet") or {}).get("title", "")
    if not isinstance(name, str):
        return None
    name = nfc(name.strip())
    for kind, pattern in (("short", shorts.CODE), ("kt", kt.CODE)):
        match = kt._code(name, pattern)
        if match:
            number, clip = map(int, match.groups())
            code = "S" if kind == "short" else "KT"
            return dict(kind=kind, series="", episode=number, clip_number=clip,
                        key=f"T{number}_{code}{clip:02d}")
    name = re.sub(r"\.mp4$", "", name, flags=re.I).strip()
    match = re.search(r"Tập\s+([0-9]+)$", name, re.I)
    if match and re.search(r"HD (?:Mobile|Dọc)", name, re.I):
        series = re.sub(r"^hd (?:mobile|dọc)\b\s*", "", kt._title_key(name[:match.start()]))
        number = int(match[1])
        return dict(kind="vertical", series=series, episode=number, clip_number=0,
                    key=f"{series}:T{number}")
    return None


def _timestamp(value):
    """Ignore absent/invalid upload dates; scheduled dates are checked by plan."""
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _next_slot(kind, after, earliest):
    day = max(after.astimezone(VN).date(), earliest.astimezone(VN).date())
    while True:
        for slot in SLOTS[kind]:
            candidate = datetime.combine(day, slot, VN)
            if candidate > after and candidate >= earliest:
                return candidate
        day += timedelta(days=1)


def plan(videos, now):
    """Pure full-channel plan. Filtering must happen only after slots are assigned."""
    if now.tzinfo is None:
        raise PublishError("thời điểm lập lịch phải có múi giờ")
    last, occupied, candidates, rows = {}, {}, [], []
    for video in videos:
        status = dict(video.get("status") or {})
        row = dict(youtube_id=video.get("id", ""), kind="", key="", publish_at="",
                   status="bỏ qua", reason="", video_status=status)
        rows.append(row)
        fields = classify(video)
        if fields is None:
            row["reason"] = "không nhận ra loại"
            continue
        row.update(fields)
        if not row["youtube_id"]:
            row["reason"] = "thiếu id video YouTube"
            continue
        key = (row["kind"], row["key"])
        scheduled = status.get("publishAt")
        if scheduled:
            stamp = _timestamp(scheduled)
            if stamp is None:
                raise PublishError("ngày publishAt YouTube không hợp lệ; không thể nối lịch")
            last[row["kind"]] = max(last.get(row["kind"], stamp), stamp)
        if status.get("privacyStatus") in ("public", "unlisted") or scheduled:
            occupied.setdefault(key, row["youtube_id"])
        if status.get("privacyStatus") != "private":
            row["reason"] = "không phải video riêng tư"
        elif scheduled:
            row["reason"] = "đã có lịch"
        elif status.get("uploadStatus") != "processed":
            row["reason"] = "chưa xử lý xong"
        else:
            uploaded = _timestamp((video.get("snippet") or {}).get("publishedAt"))
            candidates.append((row, uploaded or datetime.max.replace(tzinfo=timezone.utc)))

    # Reserve existing public/unlisted/scheduled keys before resolving candidate duplicates.
    unique = []
    for row, uploaded in sorted(candidates, key=lambda item: (item[1], item[0]["youtube_id"])):
        key = (row["kind"], row["key"])
        if key in occupied:
            row["reason"] = f"đã có bản {occupied[key]}"
        else:
            occupied[key] = row["youtube_id"]
            unique.append((row, uploaded))
    unique.sort(key=lambda item: (list(SLOTS).index(item[0]["kind"]), item[0]["series"],
                                 item[0]["episode"], item[0]["clip_number"], item[1], item[0]["youtube_id"]))
    tomorrow = datetime.combine(now.astimezone(VN).date(), time(23, 59, 59), VN)
    for row, _ in unique:
        slot = _next_slot(row["kind"], last.get(row["kind"], tomorrow), now + timedelta(hours=1))
        last[row["kind"]] = slot
        row.update(status="sẵn sàng", publish_at=slot.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    # Keep ready rows in planning order, so --limit selects the first assigned videos.
    return [row for row in rows if row["status"] != "sẵn sàng"] + [row for row, _ in unique]


def _journal(config):
    path = Path(config.workspace.dir) / "_publish" / "schedule.json"
    if not path.exists():
        return path, dict(schema_version=1, records=[])
    doc = read_json_dict(path)
    if doc is None or doc.get("schema_version") != 1 or not isinstance(doc.get("records"), list) \
            or any(not isinstance(record, dict) or any(not isinstance(record.get(key), str) for key in
                   ("youtube_id", "kind", "key", "publish_at", "set_at")) for record in doc["records"]):
        raise PublishError("nhật ký lịch đăng không hợp lệ; không ghi đè")
    return path, doc


def apply(config, rows, client):
    """Save each successful update atomically; propagate API errors immediately."""
    path, journal = _journal(config)
    result = []
    for original in rows:
        row = dict(original)
        result.append(row)
        if row["status"] != "sẵn sàng":
            continue
        status = {key: row["video_status"][key] for key in WRITABLE_STATUS if key in row["video_status"]}
        # Amendment A (HUMAN LEAD 2026-11-18): every scheduled video is declared "not made for kids".
        status.update(privacyStatus="private", publishAt=row["publish_at"], selfDeclaredMadeForKids=False)
        client.update_status(row["youtube_id"], status)
        record = {key: row[key] for key in ("youtube_id", "kind", "key", "publish_at")}
        record["set_at"] = utc_now()
        journal["records"] = [r for r in journal["records"] if r["youtube_id"] != row["youtube_id"]] + [record]
        atomic_write_json(path, journal)
        row["status"] = "đã đặt lịch"
    return result
