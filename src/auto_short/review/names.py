"""Download file names of Shorts (CP8.5 X1, CP8.21 D3): ``T<episode>_S<NN>_<title>.mp4`` (khai thị: ``KT<NN>``) and ``[<series>_]Tập<episode>_Shorts.zip``,
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


def short_code(episode: str, number: int, total: int, *, khaithi: bool = False) -> str:
    """``T<episode>_S<NN>`` (CP8.21 D3); a khai thị episode (CP8.9 K8) uses ``KT<NN>``."""
    return f"T{episode}_{'KT' if khaithi else 'S'}{number:0{index_width(total)}d}"


def download_name(episode: str, number: int, total: int, title: str | None, *, khaithi: bool = False) -> str:
    """``T<episode>_S<NN>_<title>.mp4``: ``number`` = 1-based position of the clip in clips.json (kept when
    other Shorts are deleted), ``total`` = number of clips (width of ``NN``), ``title`` = the title in the file.
    No title left after cleaning -> ``T<episode>_S<NN>.mp4``. A khai thị episode uses ``KT<NN>``."""
    head = short_code(episode, number, total, khaithi=khaithi)
    t = truncate_utf8(clean_part(title))
    return f"{head}_{t}.mp4" if t else f"{head}.mp4"


def copy_prefix(episode: str, number: int, total: int, *, khaithi: bool = False) -> str:
    """Start of the copy text (CP8.21 D3): ``T29_S01_``; khai thị: ``T29_KT01_`` (no extra prefix)."""
    return short_code(episode, number, total, khaithi=khaithi) + "_"


MAX_SERIES_BYTES = 80  # UTF-8 bytes of the bộ kinh part of a zip name (CP8.17 D4)


def zip_name(episode: str, *, khaithi: bool = False, series: str | None = None, both: bool = False) -> str:
    """``[<series>_]Tập<episode>_Shorts.zip``; a khai thị episode (CP8.9 K8): ``…_KhaiThị.zip``; ``both`` (CP8.17
    D5): ``…_Shorts+KhaiThị.zip``. ``series`` (titles.json ``header.fields.series``) is cleaned like a title part
    and cut to 80 UTF-8 bytes at a word boundary; empty after cleaning -> no series prefix."""
    kind = "Shorts+KhaiThị" if both else ("KhaiThị" if khaithi else "Shorts")
    head = truncate_utf8(clean_part(series), MAX_SERIES_BYTES)
    return f"{head}_Tập{episode}_{kind}.zip" if head else f"Tập{episode}_{kind}.zip"


def posts_docx_name(episode: str | None, *, series: str | None = None, fallback: str = "bai-dang") -> str:
    """CP8.31 P16: ``[<series>_]Tập<episode>_BaiDang.docx`` (one video); without an episode label
    ``<series>_BaiDang.docx`` (a whole bộ kinh), else ``<fallback>_BaiDang.docx`` (``fallback`` = playlist id)."""
    head = truncate_utf8(clean_part(series), MAX_SERIES_BYTES)
    label = clean_part(episode) if episode else ""
    if label:
        return f"{head}_Tập{label}_BaiDang.docx" if head else f"Tập{label}_BaiDang.docx"
    return f"{head or clean_part(fallback) or 'bai-dang'}_BaiDang.docx"


def video_name(episode: str | None, video_id: str, suffix: str, *, series: str | None = None) -> str:
    """CP8.27: ``[<series>_]Tập<episode>_<suffix>.mp4`` (suffix ``HD`` landscape, ``Doc`` vertical); a video with no
    episode number (titles.json ``header.fields.episode``) -> ``<video id>_<suffix>.mp4``."""
    label = clean_part(episode) if episode else ""
    if not label:
        return f"{clean_part(video_id) or 'video'}_{suffix}.mp4"
    head = truncate_utf8(clean_part(series), MAX_SERIES_BYTES)
    return f"{head}_Tập{label}_{suffix}.mp4" if head else f"Tập{label}_{suffix}.mp4"


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


# --- CP8.7: copy text = title + hashtags (bổ sung HUMAN LEAD 2026-09-27) ----------------------------------------

MAX_COPY_CHARS = 100  # YouTube title limit


def hashtag(text: str | None) -> str | None:
    """``#`` + the letters and digits of ``text`` (NFC, Vietnamese diacritics kept; spaces, punctuation and a
    leading ``#`` dropped), e.g. "Thập Thiện Nghiệp Đạo Kinh" -> "#ThậpThiệnNghiệpĐạoKinh"; None when empty."""
    body = "".join(c for c in unicodedata.normalize("NFC", text or "") if c.isalnum())
    return f"#{body}" if body else None


def hashtags(series: str | None, tags: tuple[str, ...] | list[str]) -> list[str]:
    """``#<series>`` then the configured tags, order kept, duplicates (case-insensitive) and empty ones dropped."""
    out, seen = [], set()
    for raw in [series, *tags]:
        tag = hashtag(raw)
        if tag is not None and tag.casefold() not in seen:
            seen.add(tag.casefold())
            out.append(tag)
    return out


def copy_text(title: str | None, series: str | None, tags: tuple[str, ...] | list[str], *,
              max_chars: int = MAX_COPY_CHARS, prefix: str = "") -> tuple[str, list[str]]:
    """``"<prefix><title> #tag1 #tag2 …"`` within ``max_chars`` characters (``prefix`` = :func:`copy_prefix`, CP8.21
    D3): hashtags are dropped from the end until it fits; the title is never cut. Returns (text, hashtags kept)."""
    title = prefix + unicodedata.normalize("NFC", title or "").strip()
    kept = hashtags(series, tags)
    while kept and len(" ".join([title, *kept]).strip()) > max_chars:
        kept.pop()
    return " ".join([title, *kept]).strip(), kept
