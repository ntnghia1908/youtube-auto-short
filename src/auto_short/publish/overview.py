"""SCH1: local channel snapshots and pure schedule coverage helpers."""
from datetime import timedelta, timezone
from math import ceil, isfinite
from pathlib import Path
import re

from ..workspace import atomic_write_json, read_json_dict
from . import PublishError, schedule, youtube


def _iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def summarize(videos, now):
    """Summarize recognized videos, counting distinct future private video ids."""
    if now.tzinfo is None:
        raise PublishError("thời điểm tóm tắt phải có múi giờ")
    kinds = {kind: dict(last_scheduled=None, scheduled_count=0, last_public=None)
             for kind in schedule.KINDS}
    seen = set()
    for video in videos:
        ident = video.get("id")
        if not ident or ident in seen:
            continue
        seen.add(ident)
        fields = schedule.classify(video)
        if fields is None:
            continue
        group = kinds[fields["kind"]]
        key = f'T{fields["episode"]}' if fields["kind"] == "vertical" else fields["key"]
        status, snippet = video.get("status") or {}, video.get("snippet") or {}
        scheduled = schedule._timestamp(status.get("publishAt"))
        public = schedule._timestamp(snippet.get("publishedAt"))
        if status.get("privacyStatus") == "private" and scheduled:
            group["scheduled_count"] += int(scheduled > now)
            _latest(group, "last_scheduled", key, "publish_at", scheduled)
        if status.get("privacyStatus") == "public" and public and public <= now:
            _latest(group, "last_public", key, "published_at", public)
    return kinds


def _latest(group, field, key, date_field, stamp):
    previous = group[field]
    if previous is None or (stamp, key) > (schedule._timestamp(previous[date_field]), previous["key"]):
        group[field] = {"key": key, date_field: _iso(stamp)}


def issues(checked):
    """Project check.compare's exact decisions without persisting video titles."""
    missing = {kind: [] for kind in schedule.KINDS}
    duplicates = {}
    unrecognized = 0
    for row in checked["rows"]:
        if row["group"] == "missing":
            missing[row["kind"]].append(row["key"])
        elif row["group"] == "duplicate":
            key = row["kind"], row["key"]
            group = duplicates.setdefault(key, dict(kind=row["kind"], key=row["key"], copies=[]))
            group["copies"].append(dict(youtube_id=row["youtube_id"], keep=row["keep"]))
        elif row["group"] == "unexpected" and not row["kind"]:
            unrecognized += 1
    pending = {kind: dict(count=checked["summary"][kind]["pending"],
                          episodes=list(checked["summary"][kind]["pending_episodes"]))
               for kind in schedule.KINDS}
    return dict(missing=missing, duplicates=list(duplicates.values()),
                unrecognized_count=unrecognized, pending=pending)


def write(config, doc):
    ident = doc.get("channel_id")
    if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", ident):
        raise PublishError("id kênh không hợp lệ; không ghi tóm tắt")
    atomic_write_json(Path(config.workspace.dir) / "_publish" / "channels" / f"{ident}.json", doc)


def check_error(config, stem, now, message=None):
    """Persist only a safe check failure summary, or clear it after a successful check."""
    if not isinstance(stem, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", stem):
        raise PublishError("tên token không hợp lệ")
    path = Path(config.workspace.dir) / "_publish" / "channels" / f"{stem}.error.json"
    if message is None:
        path.unlink(missing_ok=True)
        return
    if any(word in message for word in ("quotaExceeded", "hạn mức", "429")):
        safe = "hết hạn mức YouTube"
    elif any(word in message for word in ("OAuth", "auth", "đăng nhập", "token")):
        safe = "token hỏng hoặc hết hạn — lấy lại token"
    else:
        safe = "không đọc được YouTube / số liệu; hãy thử lại"
    atomic_write_json(path, dict(at=_iso(now), message=safe))


def read(config, *, include_errors=False):
    """Missing/broken snapshots do not hide healthy channels."""
    docs, errors = [], []
    for file in (Path(config.workspace.dir) / "_publish" / "channels").glob("*.json"):
        doc = read_json_dict(file)
        if file.name.endswith(".error.json"):
            stem = file.name[:-len(".error.json")]
            if doc and re.fullmatch(r"[A-Za-z0-9_-]+", stem) \
                    and schedule._timestamp(doc.get("at")) is not None and isinstance(doc.get("message"), str):
                errors.append(dict(token=stem, at=doc["at"], message=doc["message"]))
            continue
        if doc and doc.get("schema_version") == 1 and doc.get("channel_id") == file.stem \
                and isinstance(doc.get("channel_title"), str) and isinstance(doc.get("playlist_id"), str) \
                and schedule._timestamp(doc.get("updated_at")) is not None \
                and isinstance(doc.get("kinds"), dict) \
                and all(isinstance(doc["kinds"].get(kind), dict) for kind in schedule.KINDS):
            docs.append(doc)
    docs.sort(key=lambda doc: (doc["channel_title"].casefold(), doc["channel_id"]))
    return (docs, sorted(errors, key=lambda doc: (doc["at"], doc["token"]), reverse=True)) if include_errors else docs


def token_status(doc, now):
    """Testing refresh-token lifetime; deliberately project no credentials or client paths."""
    authorized = doc.get("authorized_at")
    if type(authorized) not in (int, float) or not isfinite(authorized) or authorized < 0:
        return dict(authorized_at=None, expires_at=None, days_left=None, warning=False, expired=False)
    expires = authorized + 7 * 86400
    days = max(0, ceil((expires - now.timestamp()) / 86400))
    return dict(authorized_at=authorized, expires_at=expires, days_left=days,
                warning=days <= 2, expired=expires <= now.timestamp())


def tokens(now):
    return {stem: token_status(read_json_dict(path) or {}, now) for stem, path in youtube.token_paths().items()}


def summarize_posts(posts, times, now):
    """Posts already belong to one website playlist; only ticked saved slots count."""
    group = dict(last_scheduled=None, scheduled_count=0, last_public=None)
    seen = set()
    for post in posts:
        ident = f'{post["episode_id"]}/{post["clip_id"]}'
        if ident in seen or not post.get("posted_at"):
            continue
        seen.add(ident)
        stamp = schedule._timestamp(times.get(ident, {}).get("slot_at"))
        if stamp is None:
            continue
        # Keep the final saved slot visible even after all slots have passed.
        _latest(group, "last_scheduled", post["code"], "publish_at", stamp)
        if stamp > now:
            group["scheduled_count"] += 1
        else:
            _latest(group, "last_public", post["code"], "published_at", stamp)
    return group


def coverage(group, now):
    """Evaluate remaining days on read, so midnight needs no new YouTube scan."""
    last = group.get("last_scheduled") or {}
    stamp = schedule._timestamp(last.get("publish_at"))
    days = max(0, ceil((stamp - now).total_seconds() / 86400)) if stamp else 0
    return dict(group, days_remaining=days, warning=days < 7)


def stale(doc, now):
    stamp = schedule._timestamp(doc.get("updated_at"))
    return stamp is None or now - stamp > timedelta(hours=36)
