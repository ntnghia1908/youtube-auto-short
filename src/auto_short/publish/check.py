"""Read the website inventory and compare it with all owned channel videos."""
from collections import defaultdict
from datetime import datetime, timezone

from ..packaging import khaithi_thumbs
from ..render.full import vertical_path
from ..review.backup import released_vertical
from . import kt, playlists, schedule


def inventory(config, pid):
    """Return (kind, episode, clip) keys using source headers and resolved titles."""
    result = set()
    for number, identifiers in kt._episodes(config, pid).items():
        for ident in identifiers:
            if vertical_path(config, ident).exists() or released_vertical(config, ident) is not None:
                result.add(("vertical", number, 0))
            for kind, owner, short in (("kt", ident + ".kt", False), ("short", ident, True)):
                for clip, _ in enumerate(khaithi_thumbs.titles(config, owner, short=short), 1):
                    result.add((kind, number, clip))
    return result


def _code(key):
    kind, number, clip = key
    return f"T{number}" if kind == "vertical" else f"T{number}_{'KT' if kind == 'kt' else 'S'}{clip:02d}"


def _keep_order(video):
    """PUB3 S4: existing publication/schedule wins, otherwise earliest upload."""
    status = video.get("status") or {}
    occupied = status.get("privacyStatus") in ("public", "unlisted") or bool(status.get("publishAt"))
    uploaded = schedule._timestamp((video.get("snippet") or {}).get("publishedAt"))
    return (not occupied, uploaded or datetime.max.replace(tzinfo=timezone.utc), video.get("id", ""))


def _video_row(video):
    status, snippet = video.get("status") or {}, video.get("snippet") or {}
    return dict(youtube_id=video.get("id", ""), uploaded_at=snippet.get("publishedAt", ""),
                privacy=status.get("privacyStatus", ""), publish_at=status.get("publishAt", ""),
                title=snippet.get("title", ""))


def compare(videos, inventory):
    """Pure comparison; vertical series names do not participate in channel keys."""
    expected, grouped, rows = set(inventory), defaultdict(list), []
    for video in videos:
        fields = schedule.classify(video)
        if fields is None:
            rows.append(dict(_video_row(video), group="unexpected", kind="", key="",
                             reason="không nhận ra loại"))
            continue
        key = fields["kind"], fields["episode"], fields["clip_number"]
        grouped[key].append(video)
    summary = {}
    for kind in schedule.KINDS:
        keys = sorted(key for key in grouped if key[0] == kind)
        maximum = max((key[1] for key in keys), default=0)
        missing = sorted(key for key in expected - grouped.keys() if key[0] == kind)
        holes = [key for key in missing if key[1] <= maximum]
        future = [key for key in missing if key[1] > maximum]
        duplicates = 0
        for key in keys:
            copies = sorted(grouped[key], key=_keep_order)
            if len(copies) > 1:
                duplicates += 1
                for index, video in enumerate(copies):
                    rows.append(dict(_video_row(video), group="duplicate", kind=kind,
                                     key=_code(key), keep=index == 0))
            if key not in expected:
                for video in copies:
                    rows.append(dict(_video_row(video), group="unexpected", kind=kind,
                                     key=_code(key), reason="website không có"))
        rows.extend(dict(group="missing", kind=kind, key=_code(key)) for key in holes)
        summary[kind] = dict(website=sum(key[0] == kind for key in expected),
                             channel=sum(len(grouped[key]) for key in keys), duplicates=duplicates,
                             missing=len(holes), unexpected=sum(len(grouped[key]) for key in keys if key not in expected),
                             pending=len(future), pending_episodes=sorted({key[1] for key in future}))
    return dict(rows=rows, summary=summary)


def missing_playlists(videos, catalog, memberships):
    """B3 includes recognized public/unlisted/scheduled videos, never unassigned drafts."""
    rows = []
    for video in videos:
        fields = schedule.classify(video)
        status = video.get("status") or {}
        if fields is None or not video.get("id") or not (
                status.get("privacyStatus") in ("public", "unlisted") or status.get("publishAt")):
            continue
        selection = playlists.select(catalog, fields["kind"], fields["episode"])
        pid = selection["playlist_id"]
        if pid and memberships.contains(pid, video["id"]):
            continue
        key = fields["kind"], fields["episode"], fields["clip_number"]
        rows.append(dict(_video_row(video), **fields, **selection, group="playlist_missing",
                         reason=selection["playlist_warning"] or "chưa vào danh sách phát"))
        rows[-1]["key"] = _code(key)
    return sorted(rows, key=lambda row: (row["episode"], row["clip_number"], row["kind"], row["youtube_id"]))


def report(result, *, output=print):
    """Compact grouped table, followed by one summary line per product kind."""
    for group, label in (("duplicate", "Trùng"), ("missing", "Thiếu"), ("unexpected", "Lạ"),
                         ("playlist_missing", "Chưa vào danh sách phát")):
        rows = [row for row in result["rows"] if row["group"] == group]
        output(f"{label}: {len(rows)} video / mục")
        if rows:
            output("Loại\tKhóa\tVideo YouTube\tNgày upload\tTrạng thái / lịch\tGhi chú\tDanh sách phát")
        for row in rows:
            state = " ".join(filter(None, (row.get("privacy"), row.get("publish_at"))))
            note = "giữ" if row.get("keep") else row.get("reason", "")
            output(f"{schedule.KINDS.get(row['kind'], '')}\t{row['key']}\t{row.get('youtube_id', '')}\t"
                   f"{row.get('uploaded_at', '')}\t{state}\t{note}\t{row.get('playlist_title', '')}")
    for kind, label in schedule.KINDS.items():
        counts = result["summary"][kind]
        episodes = counts["pending_episodes"]
        pending = (f"chưa đăng T{episodes[0]}–T{episodes[-1]} ({counts['pending']} video)"
                   if episodes else "chưa đăng: 0")
        output(f"Tổng {label}: website {counts['website']}, kênh {counts['channel']}, "
               f"trùng {counts['duplicates']} khóa, thiếu {counts['missing']}, lạ {counts['unexpected']}; {pending}")
