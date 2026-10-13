"""SR2 K2: pure helpers of the "Khai thị" reading library (ranges of episodes, S3 book). No FastAPI, no I/O.

Canonical contract: docs/decisions/SR2-khaithi-library-contract.md K1-K2. The data itself (posts, titles, copy text)
is built by ``web/app.py`` next to the CP8.31 ``.docx`` export, so the two never differ.
"""

from __future__ import annotations

import unicodedata

SINGLE_ID = "_single"  # K2: pseudo-playlist of the episodes that belong to no bộ kinh
SINGLE_TITLE = "Video lẻ"


def sort_key(title: str) -> tuple[str, str]:
    """Order of the library lists: by name without diacritics (``đ`` -> ``d``), like the sutra library (SR1.4)."""
    s = unicodedata.normalize("NFD", title.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if not unicodedata.combining(c)).casefold(), title.casefold()


def range_label(lo: int, hi: int) -> str:
    return f"Tập {lo}–{hi}"


def ranges_of(counts: list[tuple[int | None, int]], size: int) -> tuple[list[dict], dict | None]:
    """``counts``: (episode number or None, posts) of the episodes holding at least one post. Returns the fixed
    ranges of ``size`` numbers (1-10, 11-20, ...) that hold a post as ``{from, to, label, posts}`` and the
    unnumbered bucket ``{posts}`` (None when empty), like CP8.31 A1."""
    buckets: dict[int, int] = {}
    other = 0
    for number, posts in counts:
        if posts <= 0:
            continue
        if number is None:
            other += posts
        else:
            key = (number - 1) // size
            buckets[key] = buckets.get(key, 0) + posts
    out = [{"from": k * size + 1, "to": (k + 1) * size, "label": range_label(k * size + 1, (k + 1) * size),
            "posts": buckets[k]} for k in sorted(buckets)]
    return out, ({"posts": other} if other else None)


def single_ranges(count: int, size: int, posts_by_pos: list[int]) -> list[dict]:
    """"Video lẻ": positions 1..count (newest first) in groups of ``size``; ``posts_by_pos[i]`` = posts of position i+1."""
    out = []
    for lo in range(1, count + 1, size):
        hi = min(count, lo + size - 1)
        out.append({"from": lo, "to": lo + size - 1, "label": range_label(lo, lo + size - 1),
                    "posts": sum(posts_by_pos[lo - 1:hi])})
    return out


def book(title: str, episodes: list[tuple[str, list[dict]]]) -> dict:
    """S3 book of ``episodes`` = ``[(heading, items)]``. Each item: ``{code, head, paras, episode_id, clip_id,
    copy_text, posted, stale}``; a section id is ``s<n>`` over the whole book."""
    n = 0
    groups = []
    for heading, items in episodes:
        sections = []
        for it in items:
            n += 1
            label = " · ".join(x for x in (it["code"], it["head"]) if x)
            sections.append({"id": f"s{n}", "title": label or f"Bài {n}",
                             "paragraphs": [[{"text": p, "kind": "text"}] for p in it["paras"]], "notes": {},
                             "episode_id": it["episode_id"], "clip_id": it["clip_id"], "copy_text": it["copy_text"],
                             "posted": it["posted"], "stale": it["stale"]})
        groups.append({"title": heading, "sections": sections})
    return {"schema_version": 1, "title": title, "intro": [], "groups": groups}
