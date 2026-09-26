"""Pure parsers: caption/subtitle text -> raw segments (T6).

Parsers do not validate; timestamps are kept as found so that validation (T5)
can reject broken input. Overlap trimming, rounding and ids are done by
:mod:`auto_short.transcript.normalize` for every provider.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field


class ParseError(Exception):
    """The caption/subtitle content cannot be parsed."""


@dataclass
class RawWord:
    start: float
    text: str
    end: float | None = None  # None: filled with the next word start / segment end


@dataclass
class RawSegment:
    start: float
    end: float
    text: str
    words: list[RawWord] = field(default_factory=list)


def _single_token(text: str) -> bool:
    return bool(text) and not re.search(r"\s", text)


# --- json3 (YouTube timed text) ---------------------------------------------

def parse_json3(data: bytes | str) -> list[RawSegment]:
    """One segment per event that carries text; events holding only newlines are dropped.

    Word timing: ``tStartMs + tOffsetMs`` of each seg, kept only when every seg is a
    single token (auto captions); a manual line in one seg has no word timing.
    """
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ParseError(f"invalid json3: {exc}") from exc
    events = doc.get("events") if isinstance(doc, dict) else None
    if not isinstance(events, list):
        raise ParseError("invalid json3: no 'events' list")

    out: list[RawSegment] = []
    for ev in events:
        segs = ev.get("segs") if isinstance(ev, dict) else None
        if not segs:
            continue
        try:
            pieces = [str(s.get("utf8", "")) for s in segs]
            text = " ".join("".join(pieces).split())
            if not text:
                continue
            start_ms = float(ev["tStartMs"])
            end = (start_ms + float(ev.get("dDurationMs", 0))) / 1000
            tokens = [p.strip() for p in pieces]
            words = []
            if all(_single_token(t) or not t for t in tokens) and any(tokens):
                words = [RawWord((start_ms + float(s.get("tOffsetMs", 0))) / 1000, t)
                         for s, t in zip(segs, tokens) if t]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ParseError(f"invalid json3 event {ev!r:.80}: {exc}") from exc
        out.append(RawSegment(start_ms / 1000, end, text, words))
    return out


# --- SRT / WebVTT -------------------------------------------------------------

_TS = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
_TIMING_RE = re.compile(rf"^\s*{_TS}\s*-->\s*{_TS}")
_INLINE_TS_RE = re.compile(r"<((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})>")
_TAG_RE = re.compile(r"<[^>]*>|\{\\[^}]*\}")


def _seconds(h: str | None, m: str, s: str, frac: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")) / 1000


def _parse_ts(text: str) -> float:
    m = re.fullmatch(_TS, text)
    if not m:
        raise ParseError(f"invalid timestamp {text!r}")
    return _seconds(*m.groups())


def _clean(line: str) -> str:
    return " ".join(html.unescape(_TAG_RE.sub("", line)).split())


def _line_words(raw_line: str, cue_start: float) -> list[RawWord] | None:
    """Word timing from WebVTT inline timestamps (``word<00:00:01.000><c> word</c>``)."""
    parts = _INLINE_TS_RE.split(raw_line)
    if len(parts) == 1:
        return None
    words, start = [], cue_start
    for i, chunk in enumerate(parts):
        if i % 2 == 1:
            start = _parse_ts(chunk)
            continue
        token = _clean(chunk)
        if not token:
            continue
        if not _single_token(token):
            return None
        words.append(RawWord(start, token))
    return words


def _cues(text: str, *, vtt: bool) -> list[tuple[float, float, list[str]]]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n[ \t]*\n", text.strip("\n"))
    if vtt:
        if not blocks or not blocks[0].startswith("WEBVTT"):
            raise ParseError("invalid WebVTT: missing 'WEBVTT' header")
        blocks = blocks[1:]
    cues = []
    for block in blocks:
        lines = block.split("\n")
        if vtt and lines[0].split(" ", 1)[0] in ("NOTE", "STYLE", "REGION"):
            continue
        idx = next((i for i, ln in enumerate(lines[:2]) if "-->" in ln), None)
        if idx is None:
            if not "".join(lines).strip():
                continue
            raise ParseError(f"cue without timing line: {block[:60]!r}")
        m = _TIMING_RE.match(lines[idx])
        if not m:
            raise ParseError(f"invalid timing line {lines[idx]!r}")
        g = m.groups()
        cues.append((_seconds(*g[:4]), _seconds(*g[4:]), lines[idx + 1:]))
    return cues


def _subtitle_segments(text: str, *, vtt: bool) -> list[RawSegment]:
    """Cues -> segments, dropping roll-up repeats.

    Leading lines of a cue that repeat the trailing lines of the previous cue were
    already emitted; only the new lines form the segment. Cues with no new line
    (pure repeats / transition cues) are dropped.
    """
    out: list[RawSegment] = []
    prev: list[str] = []
    for start, end, raw_lines in _cues(text, vtt=vtt):
        pairs = [(ln, _clean(ln)) for ln in raw_lines]
        pairs = [(raw, clean) for raw, clean in pairs if clean]
        clean = [c for _, c in pairs]
        k = next((k for k in range(min(len(prev), len(clean)), 0, -1) if prev[-k:] == clean[:k]), 0)
        new = pairs[k:]
        prev = clean
        if not new:
            continue
        words: list[RawWord] | None = []
        if vtt:
            for raw, _ in new:
                lw = _line_words(raw, start)
                if lw is None:
                    words = None
                    break
                words.extend(lw)
        out.append(RawSegment(start, end, " ".join(c for _, c in new), words or []))
    return out


def parse_srt(text: str) -> list[RawSegment]:
    return _subtitle_segments(text, vtt=False)


def parse_vtt(text: str) -> list[RawSegment]:
    return _subtitle_segments(text, vtt=True)


FORMATS = {".srt": "srt", ".vtt": "vtt", ".json3": "json3"}


def parse(data: bytes, fmt: str) -> list[RawSegment]:
    if fmt == "json3":
        return parse_json3(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError(f"subtitle is not UTF-8: {exc}") from exc
    if fmt == "srt":
        return parse_srt(text)
    if fmt == "vtt":
        return parse_vtt(text)
    raise ParseError(f"unsupported subtitle format {fmt!r}")
