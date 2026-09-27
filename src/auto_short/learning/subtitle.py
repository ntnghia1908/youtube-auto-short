"""Stage ``subtitle`` (CL1 C5, C6): Chinese caption -> ``subtitle.json3`` + ``source.json``.

Only decides whether the selected track is acceptable for the window ``[0, window_seconds)``;
CL1.1 writes no per-line artifact. Timestamps and text are those of
``normalize(parse_json3(subtitle.json3))`` (CP3 T6, import only), never rewritten.
"""

from __future__ import annotations

import hashlib
import logging
import math

from ..config import Config
from ..transcript.normalize import SPEECH, normalize
from ..transcript.parsers import ParseError, parse_json3
from ..workspace import Workspace, atomic_write_bytes, atomic_write_json
from .tracks import Listing, Selection, TrackLister, is_chinese_related, no_track_message, pick_chinese_track, \
    primary_subtag

log = logging.getLogger("auto_short")

STAGE = "subtitle"
SUBTITLE_NAME = "subtitle.json3"
SOURCE_NAME = "source.json"
SOURCE_SCHEMA_VERSION = 1
TRACK_RULE = "v1"  # C5 selection rule version (part of the config hash)
DOWNSTREAM = ("lesson",)


class SubtitleRejected(Exception):
    """No acceptable Chinese subtitle; the message is user-facing."""


def used_config(config: Config) -> dict:
    return {
        "learning.window_seconds": config.learning.window_seconds,
        "learning.min_han_ratio": config.learning.min_han_ratio,
        "learning.track_rule": TRACK_RULE,
    }


def is_han(ch: str) -> bool:
    """CJK Unified Ideographs + Extension A."""
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿"


def han_ratio(texts: list[str]) -> float:
    letters = [c for text in texts for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if is_han(c)) / len(letters)


def in_window(segments: list[dict], window: float) -> list[dict]:
    """Speech segments with ``start < window``; ``end`` is kept even past the window."""
    return [s for s in segments if s["kind"] == SPEECH and s["start"] < window]


def check_timestamps(segments: list[dict], duration: float | None) -> str | None:
    """CP3 T5 #2 over every segment of the track."""
    prev_start = -math.inf
    for s in segments:
        start, end = s["start"], s["end"]
        if not (math.isfinite(start) and math.isfinite(end)):
            return f"invalid timestamp in {s['id']}: non-finite"
        if not 0 <= start < end:
            return f"invalid timestamp in {s['id']}: start={start} end={end}"
        if start < prev_start:
            return f"invalid timestamp in {s['id']}: start {start} before previous start {prev_start}"
        if duration is not None and end > duration + 1:
            return f"invalid timestamp in {s['id']}: end {end} beyond video duration {duration}"
        prev_start = start
        for w in s["words"]:
            if not (math.isfinite(w["start"]) and math.isfinite(w["end"])):
                return f"invalid word timestamp in {s['id']}"
    return None


def validate(segments: list[dict], window_segments: list[dict], *, duration: float | None, lang: str,
             window: float, min_han_ratio: float) -> str | None:
    """C6 acceptance; the first failing reason, else None."""
    if not window_segments:
        return f"no speech segment starts before {window} s"
    reason = check_timestamps(segments, duration)
    if reason is not None:
        return reason
    if primary_subtag(lang) != "zh":
        return f"language is {lang!r}, expected 'zh*'"
    ratio = han_ratio([s["text"] for s in window_segments])
    if ratio < min_han_ratio:
        return f"not Chinese: Han characters are {ratio:.3f} of letters in the window (< {min_han_ratio})"
    return None


def source_document(episode_id: str, listing: Listing, selection: Selection, subtitle_sha256: str,
                    window: float, window_segments: list[dict]) -> dict:
    t = selection.track
    return {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "episode_id": episode_id,
        "video": dict(listing.video),
        "tracks": [x.to_dict() for x in listing.tracks if is_chinese_related(x)],
        "selected": {"key": t.key, "auto": t.auto, "lang": t.lang, "reason": selection.reason},
        "subtitle": {"path": SUBTITLE_NAME, "sha256": subtitle_sha256},
        "window": {"start": 0.0, "end": window},
        "stats": {
            "segments_in_window": len(window_segments),
            "han_ratio": round(han_ratio([s["text"] for s in window_segments]), 3),
            "first_start": window_segments[0]["start"],
            "last_end": window_segments[-1]["end"],
        },
    }


def remove_outputs(ws: Workspace) -> None:
    for name in (SUBTITLE_NAME, SOURCE_NAME):
        (ws.dir / name).unlink(missing_ok=True)


def produce(ws: Workspace, url: str, config: Config, lister: TrackLister) -> list[str]:
    """The stage action: select, download, validate and write; returns the artifacts."""
    window, min_ratio = config.learning.window_seconds, config.learning.min_han_ratio
    listing = lister.listing(url)
    selection = pick_chinese_track(listing.tracks)
    if selection is None:
        raise SubtitleRejected(no_track_message(listing.tracks))
    t = selection.track
    log.info("%s: selected %s", STAGE, selection.reason)
    data = lister.download(url, t.key, t.auto)
    try:
        segments = normalize(parse_json3(data))
    except ParseError as exc:
        raise SubtitleRejected(f"subtitle {t.key} rejected: parse error: {exc}") from exc
    window_segments = in_window(segments, window)
    duration = listing.video.get("duration")
    reason = validate(segments, window_segments, duration=float(duration) if duration is not None else None,
                      lang=t.lang, window=window, min_han_ratio=min_ratio)
    if reason is not None:
        raise SubtitleRejected(f"subtitle {t.key} rejected: {reason}")

    doc = source_document(ws.episode_id, listing, selection, hashlib.sha256(data).hexdigest(), window,
                          window_segments)
    try:
        remove_outputs(ws)
        atomic_write_bytes(ws.dir / SUBTITLE_NAME, data)
        atomic_write_json(ws.dir / SOURCE_NAME, doc)
    except BaseException:
        remove_outputs(ws)
        raise
    log.info("%s: %s segments in [0, %s) s, han_ratio=%s", STAGE, doc["stats"]["segments_in_window"], window,
             doc["stats"]["han_ratio"])
    return [SUBTITLE_NAME, SOURCE_NAME]
