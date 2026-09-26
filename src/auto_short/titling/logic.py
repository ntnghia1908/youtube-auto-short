"""Pure titling logic: header (G2), clip text (G3), response parsing (G4/G6), option
validation and choice (G5), artifact validation (G8).

Canonical contract: docs/decisions/CP6-titling-contract.md.
"""

from __future__ import annotations

import json
import re
import string
import unicodedata

from ..config import HEADER_FIELDS, TitlingHeaderConfig
from ..selection.logic import normalize_word

VALID, INVALID = "valid", "invalid"
TITLED, UNTITLED = "titled", "untitled"
MIN_EVIDENCE_WORDS = 3


class TitlingError(Exception):
    """The titling stage cannot complete (bad input, AI failure, validation error)."""


class ResponseError(ValueError):
    """The AI response is not JSON or does not match the response schema (G6: retry)."""


# --- G2 header ------------------------------------------------------------------------------

_FLAGS = {"speaker": "--speaker", "series": "--series", "episode": "--episode"}


def _clean(value) -> str | None:
    if value is None:
        return None
    value = " ".join(unicodedata.normalize("NFC", str(value)).split())
    return value or None


def resolve_header(hcfg: TitlingHeaderConfig, metadata_title: str | None,
                   cli: dict[str, str | None] | None = None) -> dict:
    """Resolve ``speaker``/``series``/``episode`` (CLI > config > ``title_pattern`` group) and
    render ``hcfg.lines``. Returns ``{"lines", "fields", "sources"}``; unresolved fields are null.
    A template field that cannot be resolved, or a line that renders empty, raises TitlingError."""
    cli = cli or {}
    match = None
    if hcfg.title_pattern and metadata_title:
        match = re.search(hcfg.title_pattern, unicodedata.normalize("NFC", metadata_title))
    fields, sources = {}, {}
    for key in HEADER_FIELDS:
        value, source = _clean(cli.get(key)), "cli"
        if value is None:
            value, source = _clean(getattr(hcfg, key)), "config"
        if value is None and match is not None and key in match.re.groupindex:
            value, source = _clean(match.group(key)), "metadata"
        fields[key], sources[key] = value, (source if value is not None else None)

    needed = [name for line in hcfg.lines for _, name, _, _ in string.Formatter().parse(line) if name]
    missing = [k for k in HEADER_FIELDS if k in needed and fields[k] is None]
    if missing:
        hint = ", ".join(f"{k} (pass {_FLAGS[k]} or set [titling.header] {k})" for k in missing)
        where = f"metadata title {metadata_title!r}" if metadata_title else "no metadata title"
        raise TitlingError(f"header field(s) not resolved: {hint}; {where} does not match "
                           "[titling.header] title_pattern")
    lines = []
    for n, tpl in enumerate(hcfg.lines, 1):
        line = " ".join(tpl.format(**{k: v or "" for k, v in fields.items()}).split())
        if not line:
            raise TitlingError(f"header line {n} ({tpl!r}) renders empty")
        lines.append(line)
    if not 1 <= len(lines) <= 3:
        raise TitlingError(f"header must have 1-3 lines, got {len(lines)}")
    return {"lines": lines, "fields": fields, "sources": sources}


# --- G3 clip text ---------------------------------------------------------------------------

def clip_text(clip: dict, units: list[dict], index: dict[str, int] | None = None) -> str:
    """Text of the clip's units ``unit_ids[0]..unit_ids[1]`` joined by one space, without the
    leading ``head_cut.words`` tokens (matched after the CP5 B11 word normalization)."""
    index = index if index is not None else {u["id"]: n for n, u in enumerate(units)}
    first, last = clip["unit_ids"]
    if first not in index or last not in index or index[first] > index[last]:
        raise TitlingError(f"clip {clip['id']}: unit_ids {clip['unit_ids']} not found in candidates.json")
    text = " ".join(u["text"] for u in units[index[first]:index[last] + 1])
    tokens = text.split()
    cut = clip.get("head_cut")
    if cut:
        dropped = cut["words"].split()
        if [normalize_word(t) for t in tokens[:len(dropped)]] != [normalize_word(w) for w in dropped]:
            raise TitlingError(f"clip {clip['id']}: head_cut words {cut['words']!r} do not match the start of its "
                               f"text {' '.join(tokens[:len(dropped) + 3])!r}; re-run 'auto-short selection'")
        tokens = tokens[len(dropped):]
    if not tokens:
        raise TitlingError(f"clip {clip['id']}: empty text")
    return " ".join(tokens)


# --- G4/G6 response parsing -----------------------------------------------------------------

def parse_response(content: str, n_options: int) -> list[dict]:
    """Parse ``{"options": [{"evidence", "title"}]}`` with exactly ``n_options`` items; any deviation
    from the response schema raises ResponseError."""
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise ResponseError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("options"), list):
        raise ResponseError('response must be an object with an "options" array')
    items = data["options"]
    if len(items) != n_options:
        raise ResponseError(f"expected {n_options} options, got {len(items)}")
    out = []
    for n, item in enumerate(items):
        if not isinstance(item, dict):
            raise ResponseError(f"options[{n}] is not an object")
        for key in ("evidence", "title"):
            if not isinstance(item.get(key), str):
                raise ResponseError(f"options[{n}].{key} missing or not a string")
        out.append({"title": item["title"], "evidence": item["evidence"]})
    return out


# --- G5 option validation -------------------------------------------------------------------

_LINE_BREAKS = re.compile(r"[\n\r\v\f\x1c-\x1e\x85  ]")
# Emoji / pictographs: Unicode emoji blocks, dingbats, misc symbols/technical/arrows, regional
# indicators, variation selector-16, ZWJ, keycap, tag characters.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF⌀-⏿☀-➿⬀-⯿←-⇿"
                    "️‍⃣〰〽㊗㊙\U000E0020-\U000E007F]")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)|\b[\w-]+\.(?:com|net|org|vn|info|io|me|tv|ly)\b")
_BANNED = (("#", "hashtag"), ("@", "@ mention"), ("!", "exclamation mark"), ("！", "exclamation mark"))
_QUOTES = {'"': '"', "“": "”", "'": "'", "‘": "’", "«": "»", "„": "“", "「": "」", "『": "』"}
_PUNCT = re.compile(r"[^\w\s]|_")


def normalize_title(title: str) -> str:
    """NFC, surrounding whitespace removed, inner whitespace collapsed."""
    return " ".join(unicodedata.normalize("NFC", title).split())


def normalize_match(text: str) -> str:
    """For evidence matching: NFC, lowercase, punctuation replaced by spaces, whitespace collapsed."""
    return " ".join(_PUNCT.sub(" ", unicodedata.normalize("NFC", text).lower()).split())


def evidence_in_text(evidence: str, text_norm: str) -> bool:
    """``evidence`` (normalized) is a whole-word substring of ``text_norm`` (already normalized)."""
    ev = normalize_match(evidence)
    return bool(ev) and f" {ev} " in f" {text_norm} "


def reject_reason(title: str, evidence: str, text_norm: str, *, min_chars: int, max_chars: int) -> str | None:
    """G5: None when the option is valid, else the first failed rule. ``title`` is the raw AI title."""
    if _LINE_BREAKS.search(title.strip()):
        return "multi-line title"
    t = normalize_title(title)
    if not t:
        return "empty title"
    if len(t) < min_chars:
        return f"too short ({len(t)} < {min_chars} chars)"
    if len(t) > max_chars:
        return f"too long ({len(t)} > {max_chars} chars)"
    if _EMOJI.search(t):
        return "emoji/pictograph"
    for ch, what in _BANNED:
        if ch in t:
            return what
    if _URL.search(t):
        return "URL"
    if len(t) >= 2 and _QUOTES.get(t[0]) == t[-1]:
        return "wrapped in quotes"
    if t.upper() == t and t.lower() != t:
        return "all caps"
    ev_words = normalize_match(evidence).split()
    if len(ev_words) < MIN_EVIDENCE_WORDS:
        return f"evidence too short ({len(ev_words)} < {MIN_EVIDENCE_WORDS} words)"
    if not evidence_in_text(evidence, text_norm):
        return "evidence not in clip text"
    return None


def validate_options(options: list[dict], text: str, *, min_chars: int, max_chars: int) -> list[dict]:
    """Option records ``{"title", "evidence", "status", "reject_reason"}``; titles/evidence normalized."""
    text_norm = normalize_match(text)
    out = []
    for opt in options:
        reason = reject_reason(opt["title"], opt["evidence"], text_norm, min_chars=min_chars, max_chars=max_chars)
        title = opt["title"] if reason == "multi-line title" else normalize_title(opt["title"])
        out.append({"title": title, "evidence": normalize_title(opt["evidence"]),
                    "status": VALID if reason is None else INVALID, "reject_reason": reason})
    return out


def choose_title(records: list[dict]) -> tuple[dict | None, list[dict]]:
    """First valid option in AI order, and the remaining valid ones as alternatives."""
    valid = [{"title": r["title"], "evidence": r["evidence"]} for r in records if r["status"] == VALID]
    return (valid[0] if valid else None), valid[1:]


# --- G8 validation --------------------------------------------------------------------------

def validate_titles(doc: dict, clips_doc: dict, texts: dict[str, str], *, clips_sha256: str,
                    candidates_sha256: str, min_chars: int, max_chars: int) -> None:
    """Invariants of ``titles.json`` before it is written; any violation raises TitlingError."""
    def fail(msg: str):
        raise TitlingError(f"titles.json validation: {msg}")

    if doc["clips_sha256"] != clips_sha256:
        fail("clips_sha256 does not match clips.json")
    if doc["candidates_sha256"] != candidates_sha256:
        fail("candidates_sha256 does not match candidates.json")
    lines = doc["header"]["lines"]
    if not 1 <= len(lines) <= 3 or not all(isinstance(x, str) and x.strip() for x in lines):
        fail(f"header must have 1-3 non-empty lines: {lines}")
    clips, titles = clips_doc["clips"], doc["titles"]
    if len(titles) != len(clips):
        fail(f"{len(titles)} titles for {len(clips)} clips")
    for clip, entry in zip(clips, titles):
        cid = clip["id"]
        if entry["clip_id"] != cid or entry["candidate_id"] != clip["candidate_id"]:
            fail(f"entry {entry['clip_id']}/{entry['candidate_id']} does not match clip {cid}/{clip['candidate_id']}")
        if entry["status"] == UNTITLED:
            if entry["title"] is not None or entry["evidence"] is not None or entry["alternatives"]:
                fail(f"clip {cid}: untitled entry must have null title/evidence and no alternatives")
            continue
        if entry["status"] != TITLED:
            fail(f"clip {cid}: unknown status {entry['status']!r}")
        text_norm = normalize_match(texts[cid])
        for opt in [entry] + entry["alternatives"]:
            reason = reject_reason(opt["title"], opt["evidence"], text_norm, min_chars=min_chars,
                                   max_chars=max_chars)
            if reason:
                fail(f"clip {cid}: title {opt['title']!r}: {reason}")
