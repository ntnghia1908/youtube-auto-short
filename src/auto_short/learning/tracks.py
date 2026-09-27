"""Chinese caption track listing and selection (CL1 contract C5).

Every attribute of a track comes from the query of its caption URL (``lang``, ``kind``,
``tlang``): the yt-dlp key is not reliable (it may carry an id suffix such as
``zh-Hans-abc123``, and ``automatic_captions`` keys such as ``zh-Hans`` on a
non-Chinese video are machine translations, ``tlang=zh-Hans``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, urlparse

from ..transcript.youtube import YtDlpCaptionFetcher

# Manual and auto tracks: preferred ``lang`` order, then other ``zh-*`` alphabetically.
LANG_ORDER = ("zh-Hans", "zh-CN", "zh-SG", "zh", "zh-Hant", "zh-TW", "zh-HK")
_LANG_RANK = {lang.casefold(): i for i, lang in enumerate(LANG_ORDER)}
VIDEO_KEYS = ("id", "title", "channel", "duration", "webpage_url")


@dataclass(frozen=True)
class Track:
    key: str  # yt-dlp key in ``subtitles`` / ``automatic_captions``
    auto: bool  # True: from ``automatic_captions``
    lang: str  # URL ``lang`` (source language); the key when the URL has none
    kind: str | None  # URL ``kind`` ("asr" = speech recognition)
    tlang: str | None  # URL ``tlang``: present = machine translation
    json3: bool  # a json3 format with a URL is offered

    def to_dict(self) -> dict:
        return {"key": self.key, "auto": self.auto, "lang": self.lang, "kind": self.kind,
                "tlang": self.tlang, "json3": self.json3}


@dataclass(frozen=True)
class Listing:
    video: dict  # VIDEO_KEYS
    tracks: tuple[Track, ...]  # every track (all languages), manual first


@dataclass(frozen=True)
class Selection:
    track: Track
    reason: str


class TrackLister(Protocol):
    def listing(self, url: str) -> Listing: ...

    def download(self, url: str, lang: str, auto: bool) -> bytes: ...


def primary_subtag(tag: str | None) -> str:
    return re.split(r"[-_]", tag or "", maxsplit=1)[0].casefold()


def is_chinese_related(track: Track) -> bool:
    """Tracks worth recording in ``source.json``: key, ``lang`` or ``tlang`` is ``zh*``."""
    return "zh" in (primary_subtag(track.key), primary_subtag(track.lang), primary_subtag(track.tlang))


def _lang_rank(track: Track) -> tuple:
    rank = _LANG_RANK.get(track.lang.casefold())
    lang_key = (0, rank, "") if rank is not None else (1, 0, track.lang)
    # Same ``lang``: the plain key before a key with an id suffix, then alphabetical.
    return (*lang_key, track.key != track.lang, track.key)


def _is_original_chinese(track: Track) -> bool:
    return track.json3 and track.tlang is None and primary_subtag(track.lang) == "zh"


def pick_chinese_track(tracks: tuple[Track, ...] | list[Track]) -> Selection | None:
    """C5: manual zh by ``lang`` order, then auto ASR zh (``-orig`` first); never a translation."""
    manual = sorted((t for t in tracks if not t.auto and _is_original_chinese(t)), key=_lang_rank)
    if manual:
        t = manual[0]
        return Selection(t, f"manual {t.lang} (key {t.key}): first manual Chinese track in lang order")
    auto = sorted((t for t in tracks if t.auto and t.kind == "asr" and _is_original_chinese(t)),
                  key=lambda t: (not t.key.endswith("-orig"), *_lang_rank(t)))
    if auto:
        t = auto[0]
        return Selection(t, f"auto ASR {t.lang} (key {t.key}): no manual Chinese track")
    return None


def describe(track: Track) -> str:
    origin = "auto" if track.auto else "manual"
    if track.tlang is not None:
        return f"machine-translated {origin} {track.key} (lang={track.lang}, tlang={track.tlang})"
    if not track.json3:
        return f"{origin} {track.key} (no json3)"
    if primary_subtag(track.lang) != "zh":
        return f"{origin} {track.key} (lang={track.lang})"
    if track.auto and track.kind != "asr":
        return f"auto {track.key} (kind={track.kind})"
    return f"{origin} {track.key}"


def no_track_message(tracks: tuple[Track, ...] | list[Track]) -> str:
    related = [describe(t) for t in tracks if is_chinese_related(t)]
    return ("no Chinese subtitle track (manual zh*, auto zh ASR); found: "
            + (", ".join(related) if related else "no zh track"))


def _url_query(formats: list) -> tuple[dict, bool]:
    """Query of the json3 URL (else of the first format URL) and whether json3 exists."""
    json3 = next((f for f in formats if f.get("ext") == "json3" and f.get("url")), None)
    fmt = json3 or next((f for f in formats if f.get("url")), None)
    query = parse_qs(urlparse(fmt["url"]).query) if fmt else {}
    return {k: v[0] for k, v in query.items() if v}, json3 is not None


def tracks_from_info(info: dict) -> tuple[Track, ...]:
    out = []
    for auto, field in ((False, "subtitles"), (True, "automatic_captions")):
        for key, formats in (info.get(field) or {}).items():
            query, has_json3 = _url_query(formats or [])
            out.append(Track(key=key, auto=auto, lang=query.get("lang") or key, kind=query.get("kind"),
                             tlang=query.get("tlang"), json3=has_json3))
    return tuple(out)


def video_from_info(info: dict) -> dict:
    video = {k: info.get(k) for k in VIDEO_KEYS}
    if video["channel"] is None:
        video["channel"] = info.get("uploader")
    return video


class YtDlpChineseFetcher(YtDlpCaptionFetcher):
    """``YtDlpCaptionFetcher`` + ``listing()`` from the same cached ``extract_info``."""

    def listing(self, url: str) -> Listing:
        info = self._extract(url)
        return Listing(video_from_info(info), tracks_from_info(info))
