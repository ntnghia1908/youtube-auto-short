"""P3 (amended, ORCHESTRATOR review round 1): the AI is free-form; its plain-text reply is projected
deterministically onto the source words with stdlib :mod:`difflib` (``SequenceMatcher``, ``autojunk=False``) so the
post can never contain a word the AI did not see, however it rewords things.

:func:`project_response` aligns the (normalized) tokens of the AI's reply to the (normalized) tokens of the source
text. The result is **always exactly the source token sequence**: a source token inside a matched (``equal``)
block takes the leading/trailing punctuation, first-letter case and a following paragraph break (a blank line in
the AI reply) from its matched AI token; a source token with no match (the AI dropped, changed or reworded it)
keeps its original spelling with no punctuation; extra AI tokens are simply not used. ``match_ratio`` = matched
source tokens / total source tokens; the caller (``post/stage.py``) retries below 0.9 and falls back to
:func:`raw_fallback` when every attempt does.

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P3.
"""

from __future__ import annotations

import difflib
import unicodedata

from ..selection.logic import normalize_word

# What the projection may attach to a matched source token (P3); quotes are not "sentence marks" for Q4.
ALLOWED_ADDED_PUNCT = frozenset('.,?!:;…"“”')
# What counts towards the "≥ 4 marks / 100 words" measure (Q4, UI label "ít dấu câu").
SENTENCE_MARKS = frozenset(".,?!:;…")
TERMINAL_PUNCT = frozenset(".?!…")


def _is_punct(ch: str) -> bool:
    return unicodedata.category(ch).startswith("P")


def _edge_punct(token: str) -> tuple[str, str, str]:
    """(leading punctuation, core, trailing punctuation) of one AI-output token."""
    i, j = 0, len(token)
    while i < j and _is_punct(token[i]):
        i += 1
    while j > i and _is_punct(token[j - 1]):
        j -= 1
    return token[:i], token[i:j], token[j:]


def _allowed(chars: str) -> str:
    return "".join(c for c in chars if c in ALLOWED_ADDED_PUNCT)


def _first_letter_upper(core: str) -> bool | None:
    """Whether ``core``'s first alphabetic character is upper case; None when it has none (nothing to transfer)."""
    for ch in core:
        if ch.isalpha():
            return ch.isupper()
    return None


def _apply_case(word: str, upper: bool | None) -> str:
    if upper is None or not word or not word[0].isalpha():
        return word
    return (word[0].upper() if upper else word[0].lower()) + word[1:]


def _tokenize_ai(ai_text: str) -> tuple[list[str], set[int]]:
    """Flattened AI tokens + the set of indices that are the last token of their paragraph (blank-line
    separated; a line break alone, without a blank line, is not a paragraph break)."""
    tokens: list[str] = []
    para_end: set[int] = set()
    for para in ai_text.replace("\r\n", "\n").strip().split("\n\n"):
        para_tokens = para.split()
        if not para_tokens:
            continue
        tokens.extend(para_tokens)
        para_end.add(len(tokens) - 1)
    return tokens, para_end


def _capitalize_sentences(paragraph: str) -> str:
    """Upper-case the paragraph's first letter and the first letter after each terminal mark (``. ? ! …``)."""
    chars = list(paragraph)

    def cap_from(pos: int) -> None:
        for k in range(pos, len(chars)):
            if chars[k].isalpha():
                chars[k] = chars[k].upper()
                return
            if not chars[k].isspace() and chars[k] not in ALLOWED_ADDED_PUNCT:
                return  # a real word character that is not alphabetic (e.g. a digit): stop looking

    cap_from(0)
    for i, ch in enumerate(chars):
        if ch in TERMINAL_PUNCT:
            cap_from(i + 1)
    return "".join(chars)


def _ensure_terminal_punct(paragraphs: list[str]) -> list[str]:
    """P3: the final paragraph must end with a terminal mark; add ``.`` when it does not."""
    if not paragraphs:
        return paragraphs
    last = paragraphs[-1]
    if not last or last[-1] not in TERMINAL_PUNCT:
        last = last + "."
    return [*paragraphs[:-1], last]


def project_response(source_text: str, ai_text: str) -> tuple[list[str], float]:
    """P3: deterministic projection of ``ai_text`` (free-form) onto ``source_text``'s tokens. Returns
    ``(paragraphs, match_ratio)``; never raises — the caller decides retry / raw from ``match_ratio`` (< 0.9) and
    emptiness (P3)."""
    src_tokens = source_text.split()
    if not src_tokens:
        return [""], 0.0
    ai_tokens, para_end = _tokenize_ai(ai_text)

    norm_src = [normalize_word(t) for t in src_tokens]
    norm_ai = [normalize_word(t) for t in ai_tokens]
    matcher = difflib.SequenceMatcher(None, norm_src, norm_ai, autojunk=False)

    rendered = list(src_tokens)  # default per position: the original word, no punctuation
    breaks: set[int] = set()  # source index after which a paragraph break happens
    matched = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        matched += i2 - i1
        for offset in range(i2 - i1):
            si, aj = i1 + offset, j1 + offset
            lead, core, trail = _edge_punct(ai_tokens[aj])
            word = _apply_case(src_tokens[si], _first_letter_upper(core))
            rendered[si] = _allowed(lead) + word + _allowed(trail)
            if aj in para_end:
                breaks.add(si)

    ratio = matched / len(src_tokens)

    paragraphs: list[str] = []
    current: list[str] = []
    for idx, tok in enumerate(rendered):
        current.append(tok)
        if idx in breaks:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    if not paragraphs:
        paragraphs = [" ".join(rendered)]

    paragraphs = [_capitalize_sentences(p) for p in paragraphs]
    paragraphs = _ensure_terminal_punct(paragraphs)
    return paragraphs, ratio


def marks_per_100_words(paragraphs: list[str]) -> float:
    """Q4 / UI "ít dấu câu": sentence marks (``. , ? ! : ; …``, not quotes) per 100 words of ``paragraphs``."""
    text = " ".join(paragraphs)
    words = text.split()
    if not words:
        return 0.0
    marks = sum(1 for ch in text if ch in SENTENCE_MARKS)
    return marks * 100 / len(words)


def raw_fallback(source_text: str) -> list[str]:
    """P3 fallback when every AI attempt fails (low match ratio / empty output / HTTP error): one paragraph,
    first letter capitalised, a period added at the end when there is no sentence-ending punctuation already."""
    text = " ".join(source_text.split())
    if not text:
        return [text]
    text = text[0].upper() + text[1:]
    if text[-1] not in TERMINAL_PUNCT:
        text += "."
    return [text]
