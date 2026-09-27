"""Download file names of Shorts (CP8.5 X1): ``Tập<episode>_S<NN>_<title>.mp4`` and ``Tập<episode>_Shorts.zip``,
plus the ``Content-Disposition`` header (RFC 6266 / RFC 5987). Pure functions, no I/O.

Files on disk keep their CP7 names (``shorts/<clip_id>.mp4``); only the name offered to the browser changes.
Canonical contract: docs/decisions/CP8.3-web-contract.md § Tên file tải về.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

MAX_TITLE_BYTES = 150  # UTF-8 bytes of the title part
FORBIDDEN = set('/\\:*?"<>|')  # not allowed in file names on Windows / Android / iOS
_SPACES = re.compile(r"\s+")


def clean_part(text: str | None) -> str:
    """NFC, drop forbidden characters (``/ \\ : * ? " < > |``) and control / format characters (tabs and other
    whitespace become a space), collapse runs of whitespace to one space, strip. Vietnamese letters and spaces
    are kept."""
    text = unicodedata.normalize("NFC", text or "")
    kept = "".join(" " if c.isspace() else c for c in text
                   if c not in FORBIDDEN and (c.isspace() or unicodedata.category(c) not in ("Cc", "Cf")))
    return _SPACES.sub(" ", kept).strip()


def truncate_utf8(text: str, max_bytes: int = MAX_TITLE_BYTES) -> str:
    """At most ``max_bytes`` UTF-8 bytes, cut at the last word boundary that fits (a single over-long word is cut
    at a character boundary)."""
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    cut = text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
    if text[len(cut):len(cut) + 1] != " " and " " in cut:  # cut fell inside a word: drop the partial word
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip()


def index_width(total: int) -> int:
    """Digits of the Short number: 2 (``S01``), 3 from 100 clips on."""
    return 3 if total >= 100 else 2


def episode_label(episode: str | None, episode_id: str) -> str:
    """``titles.json`` ``header.fields.episode`` (e.g. ``"29"``), else the episode id; cleaned like a title."""
    label = clean_part(episode) if episode else ""
    return label or clean_part(episode_id)


def download_name(episode: str, number: int, total: int, title: str | None) -> str:
    """``Tập<episode>_S<NN>_<title>.mp4``: ``number`` = 1-based position of the clip in clips.json (kept when
    other Shorts are deleted), ``total`` = number of clips (width of ``NN``), ``title`` = the title in the file.
    No title left after cleaning -> ``Tập<episode>_S<NN>.mp4``."""
    head = f"Tập{episode}_S{number:0{index_width(total)}d}"
    t = truncate_utf8(clean_part(title))
    return f"{head}_{t}.mp4" if t else f"{head}.mp4"


def zip_name(episode: str) -> str:
    return f"Tập{episode}_Shorts.zip"


def ascii_fallback(name: str) -> str:
    """Name without diacritics for the plain ``filename=`` parameter (``đ`` -> ``d``); other non-ASCII characters
    are dropped; ``"`` and ``\\`` cannot occur (removed by :func:`clean_part`)."""
    name = name.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFKD", name)
    out = "".join(c for c in decomposed if ord(c) < 128 and c not in '"\\' and (c.isprintable()))
    return _SPACES.sub(" ", out).strip() or "download"


def content_disposition(name: str) -> str:
    """``attachment; filename="<ascii>"; filename*=UTF-8''<percent-encoded UTF-8>`` (RFC 6266 + RFC 5987):
    browsers that know ``filename*`` save the Vietnamese name, others the ASCII fallback."""
    return f'attachment; filename="{ascii_fallback(name)}"; filename*=UTF-8\'\'{quote(name, safe="")}'
