"""W3: YouTube URLs from the web form: a single video (normalised) or, from CP8.7, a playlist (bộ kinh)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from ..youtube_url import (MAX_URL_LENGTH, UrlError, _SHORT_HOST, _VIDEO_ID_RE, _WATCH_HOSTS,
                           canonical_url, parse_youtube_url)


# --- CP8.7 playlists (L2) ------------------------------------------------------------------------------------

PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
# Mix / radio (RD…), Watch later, Liked videos (+ YouTube Music likes): personal or generated, not a bộ kinh.
_REFUSED_EXACT = {"WL", "LL", "LM"}
_REFUSED_PREFIX = ("RD",)
VIDEO, PLAYLIST, ASK = "video", "playlist", "ask"


@dataclass(frozen=True)
class ParsedUrl:
    kind: str  # video | playlist | ask (watch?v=…&list=… : the user chooses)
    video_id: str | None = None
    playlist_id: str | None = None

    @property
    def video_url(self) -> str | None:
        return canonical_url(self.video_id) if self.video_id else None

    @property
    def playlist_url(self) -> str | None:
        return playlist_url(self.playlist_id) if self.playlist_id else None


def playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def valid_playlist_id(value: str) -> bool:
    return bool(PLAYLIST_ID_RE.match(value or "")) and value not in _REFUSED_EXACT \
        and not value.startswith(_REFUSED_PREFIX)


def _playlist_id(raw_values: list[str]) -> str:
    if len(raw_values) != 1:
        raise UrlError("URL playlist không hợp lệ (cần đúng một tham số list)")
    value = raw_values[0]
    if value in _REFUSED_EXACT or value.startswith(_REFUSED_PREFIX):
        raise UrlError("không nhận danh sách Mix / Xem sau / Đã thích — dán link playlist của bộ kinh")
    if not PLAYLIST_ID_RE.match(value):
        raise UrlError("playlist id không hợp lệ")
    return value


def classify_url(raw: str) -> ParsedUrl:
    """L2: ``youtube.com/playlist?list=ID`` -> playlist; ``watch?v=VID&list=ID`` -> ask (video or playlist);
    other single-video URLs -> video (as :func:`parse_youtube_url`). Mix / Watch later / Liked lists -> UrlError
    for the playlist part (a ``watch?v=…&list=RD…`` URL is just the video)."""
    text = (raw or "").strip()
    if text and len(text) <= MAX_URL_LENGTH and not any(c.isspace() for c in text):
        full = text if "://" in text else "https://" + text
        try:
            u = urlsplit(full)
            host = (u.hostname or "").lower()
        except ValueError:
            host, u = "", None
        if u is not None and host in _WATCH_HOSTS and u.scheme.lower() in ("http", "https") \
                and not u.username and not u.password:
            lists = parse_qs(u.query).get("list")
            if u.path.rstrip("/") == "/playlist":
                if u.port is not None:
                    raise UrlError("chỉ nhận URL http(s) của YouTube")
                return ParsedUrl(PLAYLIST, playlist_id=_playlist_id(lists or []))
            if lists and u.path.rstrip("/") == "/watch":
                video_id, _ = parse_youtube_url(raw)
                try:
                    return ParsedUrl(ASK, video_id=video_id, playlist_id=_playlist_id(lists))
                except UrlError:
                    return ParsedUrl(VIDEO, video_id=video_id)  # Mix / WL list next to a video: the video
    video_id, _ = parse_youtube_url(raw)
    return ParsedUrl(VIDEO, video_id=video_id)
