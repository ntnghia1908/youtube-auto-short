"""W3: accept only a single YouTube video URL from the web form and normalise it."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_WATCH_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_SHORT_HOST = "youtu.be"
MAX_URL_LENGTH = 2000


class UrlError(ValueError):
    """Not a single YouTube video URL (user-facing message)."""


def canonical_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"


def parse_youtube_url(raw: str) -> tuple[str, str]:
    """Return ``(video_id, canonical_url)`` for ``youtube.com/watch?v=ID``, ``youtu.be/ID`` or
    ``youtube.com/shorts/ID`` (http/https; a missing scheme means https). Every query parameter other than
    ``v`` (``si``, ``t``, ``list``, ``feature`` ...) is dropped. Raises :class:`UrlError`."""
    text = (raw or "").strip()
    if not text:
        raise UrlError("URL trống")
    if len(text) > MAX_URL_LENGTH or any(c.isspace() for c in text):
        raise UrlError("URL không hợp lệ")
    if "://" not in text:
        text = "https://" + text
    try:
        u = urlsplit(text)
        host = (u.hostname or "").lower()
        port = u.port
    except ValueError as exc:
        raise UrlError("URL không hợp lệ") from exc
    if u.scheme.lower() not in ("http", "https") or u.username or u.password or port is not None:
        raise UrlError("chỉ nhận URL http(s) của YouTube")
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
        elif path.rstrip("/") == "/playlist":
            raise UrlError("không nhận playlist — dán link của một video")
    else:
        raise UrlError("chỉ nhận URL YouTube (youtube.com, youtu.be)")
    if candidate is None or not _VIDEO_ID_RE.match(candidate):
        raise UrlError("không tìm thấy video id trong URL (dạng youtube.com/watch?v=…, youtu.be/…, "
                       "youtube.com/shorts/…)")
    return candidate, canonical_url(candidate)
