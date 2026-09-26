"""Classify an ingest target (YouTube URL or local file) and derive episode ids."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

LOCAL, YOUTUBE = "local", "youtube"

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
                  "youtube-nocookie.com", "www.youtube-nocookie.com"}
_PATH_PREFIXES = ("/shorts/", "/embed/", "/live/", "/v/")


class SourceError(Exception):
    """The ingest target is not a supported source."""


@dataclass(frozen=True)
class SourceSpec:
    kind: str
    uri: str  # original URL, or absolute local path
    youtube_id: str | None = None
    path: Path | None = None  # absolute local path


def youtube_video_id(url: str) -> str | None:
    """Extract the 11-char video id from a single-video YouTube URL, else None."""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    candidate = None
    if host == "youtu.be":
        candidate = u.path.lstrip("/").split("/")[0]
    elif host in _YOUTUBE_HOSTS:
        if u.path == "/watch":
            candidate = (parse_qs(u.query).get("v") or [None])[0]
        else:
            for prefix in _PATH_PREFIXES:
                if u.path.startswith(prefix):
                    candidate = u.path[len(prefix):].split("/")[0]
    return candidate if candidate and _VIDEO_ID_RE.match(candidate) else None


def classify(target: str) -> SourceSpec:
    if re.match(r"^[a-z][a-z0-9+.-]*://", target, re.IGNORECASE):
        vid = youtube_video_id(target)
        if vid is None:
            raise SourceError(f"unsupported URL (expected a single YouTube video URL): {target}")
        return SourceSpec(YOUTUBE, target, youtube_id=vid)
    path = Path(target).expanduser().absolute()
    return SourceSpec(LOCAL, str(path), path=path)


def slugify(text: str, max_len: int = 48) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "video"


def local_episode_id(path: Path, sha256: str) -> str:
    """``<slug of file stem>-<first 12 hex chars of sha256>`` (D3)."""
    return f"{slugify(path.stem)}-{sha256[:12]}"
