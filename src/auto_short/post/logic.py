"""Pure post logic with no I/O: link normalization (P6), chunk boundaries for the AI call (P3) and the copied post
text layout (P4).

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P3, P4, P6.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_WATCH_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_SHORT_HOST = "youtu.be"
_SPEAKER_DOT_RE = re.compile(r"\.(?=[^\W\d_])")
MAX_LINK_LENGTH = 2000


class LinkError(ValueError):
    """Not a recognised single-video YouTube link (P6)."""


def normalize_link(raw: str | None) -> str | None:
    """P6: empty (``None`` or blank) -> ``None`` (xóa link); a recognised ``youtube.com/watch?v=``,
    ``youtu.be/`` or ``youtube.com/shorts/`` link (with/without ``www.``/``m.``; other query parameters dropped) ->
    ``"https://youtube.com/shorts/<id>"``; anything else raises :class:`LinkError`."""
    text = (raw or "").strip()
    if not text:
        return None
    if len(text) > MAX_LINK_LENGTH or any(c.isspace() for c in text):
        raise LinkError("link không hợp lệ")
    full = text if "://" in text else "https://" + text
    try:
        u = urlsplit(full)
        host = (u.hostname or "").lower()
    except ValueError as exc:
        raise LinkError("link không hợp lệ") from exc
    if u.scheme.lower() not in ("http", "https") or u.username or u.password or u.port is not None:
        raise LinkError("chỉ nhận link http(s) của YouTube")
    path = u.path
    candidate = None
    if host == _SHORT_HOST:
        parts = [p for p in path.split("/") if p]
        candidate = parts[0] if len(parts) == 1 else None
    elif host in _WATCH_HOSTS:
        if path.rstrip("/") == "/watch":
            values = parse_qs(u.query).get("v") or []
            candidate = values[0] if len(values) == 1 else None
        elif path.startswith("/shorts/"):
            parts = [p for p in path[len("/shorts/"):].split("/") if p]
            candidate = parts[0] if len(parts) == 1 else None
    if candidate is None or not _VIDEO_ID_RE.match(candidate):
        raise LinkError('link phải là youtube.com/shorts/…, youtu.be/… hoặc youtube.com/watch?v=…')
    return f"https://youtube.com/shorts/{candidate}"


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
