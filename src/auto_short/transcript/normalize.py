"""Normalization (T6) and acceptance validation (T5), shared by every provider."""

from __future__ import annotations

import math
import re
import unicodedata

from ..config import TranscriptConfig
from .parsers import RawSegment

SPEECH, NON_SPEECH = "speech", "non_speech"

_LABEL_RE = re.compile(r"\[[^\]]*\]")
_ONLY_LABELS_RE = re.compile(r"^(?:\s*\[[^\]]*\]\s*)+$")
# Letters that only occur in Vietnamese orthography (lowercase, NFC).
_VIETNAMESE_CHARS = frozenset(
    "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
)


def _r(x: float) -> float:
    return round(x, 3) if math.isfinite(x) else x


def normalize(raw: list[RawSegment]) -> list[dict]:
    """Raw segments -> ``transcript.json`` segments.

    - text: whitespace collapsed, otherwise unchanged; empty segments dropped;
    - a segment made only of ``[...]`` labels is ``non_speech`` (no words);
    - overlap removed: ``end = min(end, next.start)`` when the next segment does not
      start earlier (a decreasing start is left for validation to reject);
    - words clamped to the segment; a missing word end = next word start / segment end;
    - seconds rounded to 3 decimals; ids ``s00001``… in order.
    """
    items = [(s, " ".join(s.text.split())) for s in raw]
    items = [(s, t) for s, t in items if t]
    out = []
    for i, (seg, text) in enumerate(items):
        start, end = float(seg.start), float(seg.end)
        if i + 1 < len(items):
            nxt = float(items[i + 1][0].start)
            if start <= nxt < end:
                end = nxt
        kind = NON_SPEECH if _ONLY_LABELS_RE.match(text) else SPEECH
        words = []
        if kind == SPEECH and all(math.isfinite(x) for x in (start, end)) and start < end:
            ws = [w for w in seg.words if w.text.strip()]
            for j, w in enumerate(ws):
                w_start = min(max(float(w.start), start), end)
                if words:
                    w_start = max(w_start, words[-1]["start"])
                nxt_start = ws[j + 1].start if j + 1 < len(ws) else end
                w_end = float(w.end) if w.end is not None else float(nxt_start)
                w_end = min(max(w_end, w_start), end)
                words.append({"start": _r(w_start), "end": _r(w_end), "text": w.text.strip()})
            # Rounding can break ordering only by ties; enforce monotonic ends.
            for w in words:
                w["end"] = max(w["end"], w["start"])
        out.append({
            "id": f"s{len(out) + 1:05d}",
            "start": _r(start),
            "end": _r(end),
            "kind": kind,
            "text": text,
            "words": words,
        })
    return out


def speech_tokens(segments: list[dict]) -> list[str]:
    """Words of speech segments, with ``[...]`` labels removed."""
    tokens = []
    for s in segments:
        if s["kind"] == SPEECH:
            tokens.extend(_LABEL_RE.sub(" ", s["text"]).split())
    return tokens


def speech_seconds(segments: list[dict]) -> float:
    """Total speech time with overlaps merged."""
    spans = sorted((s["start"], s["end"]) for s in segments if s["kind"] == SPEECH and s["end"] > s["start"])
    total, cur_start, cur_end = 0.0, None, None
    for a, b in spans:
        if cur_end is None or a > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = a, b
        else:
            cur_end = max(cur_end, b)
    if cur_end is not None:
        total += cur_end - cur_start
    return total


def vietnamese_ratio(tokens: list[str]) -> float:
    words = [t for t in tokens if any(c.isalpha() for c in t)]
    if not words:
        return 0.0
    vi = sum(1 for w in words if _VIETNAMESE_CHARS.intersection(unicodedata.normalize("NFC", w.lower())))
    return vi / len(words)


def stats(segments: list[dict], duration: float) -> dict:
    speech = speech_seconds(segments)
    return {
        "segments": len(segments),
        "words": len(speech_tokens(segments)),
        "speech_seconds": round(speech, 3),
        "coverage": round(speech / duration, 3) if duration > 0 else 0.0,
    }


def _is_vietnamese_tag(language: str | None) -> bool:
    return bool(language) and re.split(r"[-_]", language.lower())[0] == "vi"


def validate(segments: list[dict], *, duration: float, language: str | None, cfg: TranscriptConfig) -> str | None:
    """Return None when the transcript is acceptable (T5), else the rejection reason."""
    if not segments:
        return "empty transcript"
    prev_start = -math.inf
    for s in segments:
        start, end = s["start"], s["end"]
        if not (math.isfinite(start) and math.isfinite(end)):
            return f"invalid timestamp in {s['id']}: non-finite"
        if not 0 <= start < end:
            return f"invalid timestamp in {s['id']}: start={start} end={end}"
        if start < prev_start:
            return f"invalid timestamp in {s['id']}: start {start} before previous start {prev_start}"
        if end > duration + 1:
            return f"invalid timestamp in {s['id']}: end {end} beyond media duration {duration}"
        prev_start = start
        for w in s["words"]:
            if not (math.isfinite(w["start"]) and math.isfinite(w["end"])):
                return f"invalid word timestamp in {s['id']}"

    tokens = speech_tokens(segments)
    if not tokens:
        return "no speech text (only non-speech labels)"
    if not _is_vietnamese_tag(language):
        return f"language is {language!r}, expected 'vi'"
    ratio = vietnamese_ratio(tokens)
    if ratio < cfg.min_vietnamese_ratio:
        return f"not Vietnamese: {ratio:.3f} of words have Vietnamese letters (< {cfg.min_vietnamese_ratio})"
    minutes = duration / 60
    coverage = speech_seconds(segments) / duration if duration > 0 else 0.0
    if coverage < cfg.min_coverage:
        return f"coverage {coverage:.3f} < {cfg.min_coverage}"
    wpm = len(tokens) / minutes if minutes > 0 else 0.0
    if wpm < cfg.min_words_per_minute:
        return f"{wpm:.1f} words/minute < {cfg.min_words_per_minute}"
    return None
