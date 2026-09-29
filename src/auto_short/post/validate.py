"""P3 validation: the AI may only add punctuation / paragraph breaks and change case, never add, drop, change or
reorder a word. Two checks on the AI's ``paragraphs`` joined by one space against the source text:

1. Word content: every token (whitespace-split), normalized like :func:`auto_short.selection.logic.normalize_word`
   (NFC, lowercase, surrounding punctuation stripped), must equal the source's tokens in the same order and count.
2. Added punctuation: characters present in the (lower-cased) joined text but not in the source may only be one of
   ``ALLOWED_ADDED_PUNCT`` (``. , ? ! : ; …`` and double quotes) — a bag-of-characters check, order independent.

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P3.
"""

from __future__ import annotations

import json
import unicodedata
from collections import Counter

from ..selection.logic import normalize_word

ALLOWED_ADDED_PUNCT = frozenset('.,?!:;…"“”')


class ResponseError(ValueError):
    """The AI response is not JSON or does not match the response schema (retry)."""


def parse_response(content: str) -> list[str]:
    """Parse ``{"paragraphs": [...]}"``; any deviation from the response schema raises :class:`ResponseError`."""
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise ResponseError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("paragraphs"), list) or not data["paragraphs"]:
        raise ResponseError('response must be an object with a non-empty "paragraphs" array')
    if not all(isinstance(p, str) for p in data["paragraphs"]):
        raise ResponseError('response "paragraphs" must be an array of strings')
    return list(data["paragraphs"])


def normalized_tokens(text: str) -> list[str]:
    return [normalize_word(t) for t in text.split()]


def _extra_chars(joined: str, source: str) -> set[str]:
    """Characters whose count in ``joined`` (NFC, lower) exceeds their count in ``source``."""
    a = Counter(unicodedata.normalize("NFC", joined).lower())
    b = Counter(unicodedata.normalize("NFC", source).lower())
    return set((a - b).elements())


def validate_paragraphs(paragraphs: object, source_text: str) -> str | None:
    """None when ``paragraphs`` is a valid P3 rewrite of ``source_text``, else the (Vietnamese) reason."""
    if not isinstance(paragraphs, list) or not paragraphs:
        return "paragraphs rỗng"
    if not all(isinstance(p, str) for p in paragraphs):
        return "paragraphs phải là chuỗi"
    if any(not p.strip() for p in paragraphs):
        return "có đoạn rỗng"
    joined = " ".join(p.strip() for p in paragraphs)
    got, want = normalized_tokens(joined), normalized_tokens(source_text)
    if got != want:
        return "nội dung từ không khớp text nguồn (thêm/bớt/đổi/đảo chữ)"
    extra = _extra_chars(joined, source_text) - ALLOWED_ADDED_PUNCT
    if extra:
        return "dấu câu không cho phép: " + ", ".join(repr(c) for c in sorted(extra))
    return None


def raw_fallback(source_text: str) -> list[str]:
    """P3 fallback when every AI attempt fails validation: one paragraph, first letter capitalised, a period
    added at the end when there is no sentence-ending punctuation already."""
    text = " ".join(source_text.split())
    if not text:
        return [text]
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?…":
        text += "."
    return [text]
