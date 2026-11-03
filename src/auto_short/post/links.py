"""Pure playlist-to-post matching. Authority: LNK1 L2–L7 (including L2a)."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from ..review.names import short_code
from .logic import normalize_link

_CODE = re.compile(r"^T([0-9]+)[ _]+(KT|S)([0-9]{2,3})(?=[ _.]|$)")


def parse_code(text: str | None) -> str | None:
    """Keep the code's width: S01 and S010 are distinct, just like download names."""
    if not isinstance(text, str):
        return None
    match = _CODE.match(unicodedata.normalize("NFC", text).lstrip())
    if not match or int(match[3]) == 0:
        return None
    return short_code(match[1], int(match[3]), 100 if len(match[3]) == 3 else 99,
                      khaithi=match[2] == "KT")


def link_for(video_id: str, khaithi: bool) -> str:
    return (f"https://youtube.com/watch?v={video_id}" if khaithi
            else normalize_link(f"https://youtube.com/shorts/{video_id}"))


def plan(entries: list[dict], targets: list[dict], current_links: dict) -> dict:
    """Targets carry code/episode_id/clip_id/khaithi; current_links maps (episode, clip) to link.

    A missing key means no post yet. Rows expose every skipped video's title for manual matching.
    The same YouTube id in several playlists is one video; conflicts block both implicated codes.
    Codeless videos already linked in either URL form count as unchanged without updates.
    """
    by_code, by_target, conflicts = defaultdict(list), defaultdict(list), set()
    for target in targets:
        by_target[target["code"]].append(target)
    videos = {e["id"]: e for e in entries}
    codes = {}
    for ident, entry in videos.items():
        file_code = parse_code((entry.get("fileDetails") or {}).get("fileName"))
        title_code = parse_code((entry.get("snippet") or {}).get("title"))
        codes[ident] = file_code or title_code
        if file_code and title_code and file_code != title_code:
            conflicts.update((file_code, title_code))
        if codes[ident]:
            by_code[codes[ident]].append(ident)
    conflicts.update(code for code, ids in by_code.items() if len(ids) > 1)
    conflicts.update(code for code, items in by_target.items() if len(items) > 1)
    counts = dict.fromkeys(("filled", "no_code", "unmatched", "duplicate", "different", "waiting", "unchanged"), 0)
    updates, rows = [], []
    for ident, entry in videos.items():
        code = codes[ident]
        row = {"video_id": ident, "title": (entry.get("snippet") or {}).get("title") or ident, "code": code}
        if not code:
            reason = ("unchanged" if any(link_for(ident, kt) in current_links.values()
                                         for kt in (False, True)) else "no_code")
        elif code in conflicts:
            reason = "duplicate"
        elif code not in by_target:
            reason = "unmatched"
        else:
            target = by_target[code][0]
            key = (target["episode_id"], target["clip_id"])
            link = link_for(ident, target["khaithi"])
            if key not in current_links:
                reason = "waiting"
            elif current_links[key]:
                reason = "unchanged" if current_links[key] == link else "different"
            else:
                reason = "filled"
                updates.append({**target, "link": link})
        counts[reason] += 1
        rows.append({**row, "reason": reason})
    return {"updates": updates, "counts": counts, "rows": rows}
