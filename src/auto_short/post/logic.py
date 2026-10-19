"""Pure post logic with no I/O: link normalization (P6), chunk boundaries for the AI call (P3) and the copied post
text layout (P4).

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P3, P4, P6.
"""

from __future__ import annotations

import re
from ..youtube_url import UrlError, parse_youtube_url

_SPEAKER_DOT_RE = re.compile(r"\.(?=[^\W\d_])")


class LinkError(ValueError):
    """Not a recognised single-video YouTube link (P6)."""


def normalize_link(raw: str | None) -> str | None:
    """P6: empty (``None`` or blank) -> ``None`` (xóa link); a recognised ``youtube.com/watch?v=``,
    ``youtu.be/`` or ``youtube.com/shorts/`` link (with/without ``www.``/``m.``; other query parameters dropped) ->
    ``"https://youtube.com/shorts/<id>"``; anything else raises :class:`LinkError`."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        vid, _ = parse_youtube_url(text)
    except UrlError as exc:
        raise LinkError(str(exc)) from exc
    return f"https://youtube.com/shorts/{vid}"


def chunk_lines(lines: list[str], max_words: int) -> list[list[str]]:
    """P3: group ``lines`` (already caption-line boundaries) into chunks of at most ``max_words`` words each — a
    single line longer than ``max_words`` becomes its own (over) chunk, never split mid-line."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    cur_words = 0
    for line in lines:
        n = len(line.split())
        if cur and cur_words + n > max_words:
            chunks.append(cur)
            cur, cur_words = [], 0
        cur.append(line)
        cur_words += n
    if cur:
        chunks.append(cur)
    return chunks


def header_line(fields: dict | None) -> str | None:
    """P4: ``"— <speaker>, <series> tập <episode>"`` from ``titles.json`` ``header.fields``; ``None`` when there is
    no header at all (the line is dropped)."""
    if not fields:
        return None
    speaker, series, episode = fields.get("speaker"), fields.get("series"), fields.get("episode")
    if series and episode:
        tail = f"{series} tập {episode}"
    else:
        tail = series or (f"tập {episode}" if episode else None)
    if isinstance(speaker, str):  # CP8.16 R5: "HT.Tịnh Không" -> "HT. Tịnh Không" (this post line only)
        speaker = _SPEAKER_DOT_RE.sub(". ", speaker)
    bits = [b for b in (speaker, tail) if b]
    return "— " + ", ".join(bits) if bits else None


def text_parts(*, title: str | None, paragraphs: list[str], header_fields: dict | None) -> tuple[str | None, list[str], str | None]:
    """P4 text of a post without link / hashtags: ``(TITLE upper-case or None, paragraphs, source line or None)``.
    Shared by the copied text (:func:`compose_copy_text`) and the P16 ``.docx`` export so the two never differ."""
    return (title.upper() if title else None,  # FIX-post-title-upper: tựa đề viết hoa toàn bộ, áp lúc đọc
            [p.strip() for p in paragraphs if p and p.strip()], header_line(header_fields))


def compose_copy_text(*, title: str | None, paragraphs: list[str], header_fields: dict | None, link: str | None,
                      hashtags: list[str]) -> str:
    """P4 bố cục bài đăng cộng đồng để sao chép: title đang dùng (VIẾT HOA), các đoạn văn, dòng nguồn (CP6 header), link
    (nếu có), hashtag (CP8.8) — mỗi phần cách nhau một dòng trống; phần thiếu bị bỏ dòng (không cắt phần khác)."""
    head, paras, hline = text_parts(title=title, paragraphs=paragraphs, header_fields=header_fields)
    parts: list[str] = [head] if head else []
    parts.extend(paras)
    if hline:
        parts.append(hline)
    if link:
        parts.append(f"▶ Xem video: {link}")
    if hashtags:
        parts.append(" ".join(hashtags))
    return "\n\n".join(parts)
