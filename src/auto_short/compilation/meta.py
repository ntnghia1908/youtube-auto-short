"""CP8.33 G7: chapters, download names and the YouTube description of a compilation. Pure functions, no I/O."""

from __future__ import annotations

from ..review.names import MAX_SERIES_BYTES, clean_part, truncate_utf8


def timecode(seconds: float) -> str:
    """``MM:SS``, or ``H:MM:SS`` from one hour on (YouTube chapter format)."""
    s = max(0, int(seconds))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def chapters(titles: list[str], durations: list[float] | tuple[float, ...]) -> list[dict]:
    """One chapter per part: ``start`` = sum of the lengths of the parts before it (the first at 0)."""
    out, at = [], 0.0
    for title, d in zip(titles, durations):
        out.append({"start": round(at, 3), "title": title})
        at += d
    return out


def description(mode: str, chapter_list: list[dict], title: str | None, tags: list[str]) -> str:
    """G7 "Copy mô tả": concat / auto -> a ``MM:SS <title>`` line per part; loop -> the title; then the hashtags."""
    tag_line = " ".join(tags)
    if mode == "loop":
        body = (title or "").strip()
    else:
        body = "\n".join(f"{timecode(c['start'])} {c['title']}".rstrip() for c in chapter_list)
    return "\n\n".join(x for x in (body, tag_line) if x)


def _head(series: str | None, fallback: str) -> str:
    return truncate_utf8(clean_part(series), MAX_SERIES_BYTES) or clean_part(fallback) or "Khai thị"


def concat_name(series: str | None, first: str, last: str, count: int, *, fallback: str = "") -> str:
    """``<Tên bộ kinh> - Khai thị T<a>-T<b> (<n> đoạn).mp4``; ``T<a>`` when first == last."""
    a, b = clean_part(first), clean_part(last)
    span = f"T{a}" if a == b else f"T{a}-T{b}"  # one episode: "T5", not "T5-T5" (review fix 1)
    return f"{_head(series, fallback)} - Khai thị {span} ({count} đoạn).mp4"


def loop_name(series: str | None, code: str, count: int, *, fallback: str = "") -> str:
    """``<Tên bộ kinh> - T<tập>_KT<NN> lặp <n> lần.mp4`` (``code`` = ``review.names.short_code``)."""
    return f"{_head(series, fallback)} - {clean_part(code)} lặp {count} lần.mp4"
