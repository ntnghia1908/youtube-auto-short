"""CP8.18 correction dictionary of the community post: rules learned from hand edits (D2), applied
deterministically to the source words when composing (D3) and to the stored unposted posts when a rule is approved
(D4); edit log + "% words to fix" measure (D6).

Pure functions plus the small file IO of the rules file (D1) and the edit log. A broken rules file raises
:class:`CorrectionsError` and is never overwritten by a read.

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P14; task docs/tasks/CP8.18-post-corrections.md.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import AbstractContextManager
from difflib import SequenceMatcher
from pathlib import Path

from ..selection.logic import normalize_word
from ..workspace import atomic_write_json
from . import store

log = logging.getLogger("auto_short")

SCHEMA_VERSION = 1
PROPOSED, APPROVED, REJECTED = "proposed", "approved", "rejected"
STATUSES = (PROPOSED, APPROVED, REJECTED)
MAX_RULE_TOKENS = 8  # D5
MAX_BLOCK_TOKENS = 3  # D2
MAX_EXAMPLES = 5  # D1
STATS_WINDOW = 20  # D6
EDIT_LOG_NAME = "post-edit-log.jsonl"
RULE_KEYS = ("id", "from", "to", "status", "count", "examples", "created_at", "updated_at")

_LEAD_RE = re.compile(r"^\W+")
_TRAIL_RE = re.compile(r"\W+$")
_WORD_RE = re.compile(r"\S+")


class CorrectionsError(Exception):
    """The rules file is unreadable / invalid, or a rule violates D5 (the message is user-facing)."""


# --- D1: file ---------------------------------------------------------------------------------------------------

def empty_doc() -> dict:
    return {"schema_version": SCHEMA_VERSION, "rules": []}


def check_doc(doc: object) -> dict:
    def bad(msg: str) -> CorrectionsError:
        return CorrectionsError(f"từ điển sửa lỗi hỏng: {msg}")

    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION or not isinstance(doc.get("rules"), list):
        raise bad('cần {"schema_version": 1, "rules": [...]}')
    seen = set()
    for n, r in enumerate(doc["rules"]):
        where = f"rules[{n}]"
        if not isinstance(r, dict) or list(r) != list(RULE_KEYS):
            raise bad(f"{where} cần các khóa {list(RULE_KEYS)}")
        if not isinstance(r["id"], str) or not r["id"] or r["id"] in seen:
            raise bad(f"{where}.id không hợp lệ hoặc trùng")
        seen.add(r["id"])
        for key in ("from", "to"):
            if not isinstance(r[key], str) or not r[key].strip():
                raise bad(f"{where}.{key} phải là chuỗi không rỗng")
        if r["status"] not in STATUSES:
            raise bad(f"{where}.status không hợp lệ")
        if not isinstance(r["count"], int) or isinstance(r["count"], bool) or r["count"] < 0:
            raise bad(f"{where}.count không hợp lệ")
        if not isinstance(r["examples"], list) or not all(isinstance(e, dict) for e in r["examples"]):
            raise bad(f"{where}.examples không hợp lệ")
        for key in ("created_at", "updated_at"):
            if not isinstance(r[key], str):
                raise bad(f"{where}.{key} không hợp lệ")
    return doc


def load(path: Path) -> dict:
    """The rules document; a missing file is an empty dictionary; unreadable / invalid raises
    :class:`CorrectionsError`."""
    if not path.is_file():
        return empty_doc()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CorrectionsError(f"không đọc được từ điển sửa lỗi {path}: {exc}") from exc
    return check_doc(doc)


def save(path: Path, doc: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, doc)
    except OSError as exc:
        raise CorrectionsError(f"không ghi được từ điển sửa lỗi {path}: {exc}") from exc


def approved_rules(path: Path) -> list[dict]:
    """The ``approved`` rules for compose (D3): a missing / broken file gives no rules (warning logged)."""
    try:
        doc = load(path)
    except CorrectionsError as exc:
        log.warning("post: %s (soạn bài không dùng từ điển)", exc)
        return []
    return [r for r in doc["rules"] if r["status"] == APPROVED]


def find_rule(doc: dict, rule_id: str) -> dict | None:
    return next((r for r in doc["rules"] if r["id"] == rule_id), None)


# --- tokens -----------------------------------------------------------------------------------------------------

def normalize_phrase(text: str) -> str:
    """D1: normalized tokens (:func:`normalize_word`, empty ones dropped) joined by one space."""
    return " ".join(t for t in (normalize_word(w) for w in text.split()) if t)


def _norm_tokens(paragraphs: list[str]) -> list[str]:
    return [t for t in (normalize_word(w) for p in paragraphs for w in p.split()) if t]


def validate_phrases(src: str, dst: str) -> tuple[str, str]:
    """D5: normalized ``(from, to)`` (1..8 tokens each, different) or :class:`CorrectionsError`."""
    f, t = normalize_phrase(src or ""), normalize_phrase(dst or "")
    for name, value in (("from", f), ("to", t)):
        n = len(value.split())
        if not 1 <= n <= MAX_RULE_TOKENS:
            raise CorrectionsError(f'"{name}" phải có 1–{MAX_RULE_TOKENS} từ (hiện {n})')
    if f == t:
        raise CorrectionsError('"from" và "to" không được giống nhau')
    return f, t


def check_unique_approved(doc: dict, rule: dict) -> None:
    """D5: two ``approved`` rules never share ``from``."""
    if rule["status"] != APPROVED:
        return
    for other in doc["rules"]:
        if other["id"] != rule["id"] and other["status"] == APPROVED and other["from"] == rule["from"]:
            raise CorrectionsError(f'đã có luật đã duyệt cho "{rule["from"]}"')


# --- D2: extraction ---------------------------------------------------------------------------------------------

def extract(old_paragraphs: list[str], new_paragraphs: list[str]) -> tuple[list[tuple[str, str]], int, int]:
    """D2/D6: ``(proposals, words, changed_words)`` of an edit. ``proposals`` are unique ``(from, to)`` pairs from the
    ``replace`` blocks of at most 3 old and 3 new normalized tokens, each with one token of context on a side when
    that token sits in an ``equal`` block. ``words`` = old tokens; ``changed_words`` = old tokens outside ``equal``
    blocks."""
    old, new = _norm_tokens(old_paragraphs), _norm_tokens(new_paragraphs)
    ops = SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
    changed = sum(i2 - i1 for tag, i1, i2, _j1, _j2 in ops if tag != "equal")
    out: list[tuple[str, str]] = []
    for n, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag != "replace" or i2 - i1 > MAX_BLOCK_TOKENS or j2 - j1 > MAX_BLOCK_TOKENS:
            continue
        left_o: list[str] = []
        left_n: list[str] = []
        right_o: list[str] = []
        right_n: list[str] = []
        if n > 0 and ops[n - 1][0] == "equal":
            left_o, left_n = [old[i1 - 1]], [new[j1 - 1]]
        if n + 1 < len(ops) and ops[n + 1][0] == "equal":
            right_o, right_n = [old[i2]], [new[j2]]
        pair = (" ".join(left_o + old[i1:i2] + right_o), " ".join(left_n + new[j1:j2] + right_n))
        if pair[0] != pair[1] and pair not in out:
            out.append(pair)
    return out, len(old), changed


def record(doc: dict, proposals: list[tuple[str, str]], episode_id: str, clip_id: str, now: str) -> dict:
    """D2: add the proposals to ``doc`` (in place; also returned). An existing ``(from, to)`` (any status) gets
    ``count + 1`` and one more example, status unchanged; a new pair becomes ``proposed``."""
    for src, dst in proposals:
        example = {"episode_id": episode_id, "clip_id": clip_id, "at": now}
        rule = next((r for r in doc["rules"] if r["from"] == src and r["to"] == dst), None)
        if rule is None:
            nums = [int(m.group(1)) for r in doc["rules"] if (m := re.fullmatch(r"r(\d+)", r["id"]))]
            doc["rules"].append({"id": f"r{max(nums, default=0) + 1:04d}", "from": src, "to": dst,
                                 "status": PROPOSED, "count": 1, "examples": [example], "created_at": now,
                                 "updated_at": now})
        else:
            rule["count"] += 1
            rule["examples"] = (rule["examples"] + [example])[-MAX_EXAMPLES:]
            rule["updated_at"] = now
    return doc


# --- D3 / D4: applying rules ------------------------------------------------------------------------------------

def _match_spans(norm: list[str], rules: list[dict]) -> list[tuple[int, int, dict]]:
    """Left-to-right, non-overlapping ``(start, end, rule)``; at one position the longest ``from`` wins."""
    by_first: dict[str, list[tuple[list[str], dict]]] = {}
    for r in rules:
        toks = r["from"].split()
        if toks:
            by_first.setdefault(toks[0], []).append((toks, r))
    for lst in by_first.values():
        lst.sort(key=lambda x: -len(x[0]))
    spans: list[tuple[int, int, dict]] = []
    i = 0
    while i < len(norm):
        hit = next(((toks, r) for toks, r in by_first.get(norm[i], ()) if norm[i:i + len(toks)] == toks), None)
        if hit is None:
            i += 1
            continue
        spans.append((i, i + len(hit[0]), hit[1]))
        i += len(hit[0])
    return spans


def _replacement(orig: list[str], rule: dict) -> list[str]:
    """New tokens for ``orig`` (the matched raw tokens): the rule's ``to`` words, first letter upper-case where the
    original token at the same position (the last one when ``to`` is longer) is; leading punctuation of the first and
    trailing punctuation of the last original token kept (D3 / D4)."""
    new = rule["to"].split()
    out = []
    for j, word in enumerate(new):
        o = orig[min(j, len(orig) - 1)]
        core = _TRAIL_RE.sub("", _LEAD_RE.sub("", o))
        out.append(word[:1].upper() + word[1:] if core[:1].isupper() else word)
    lead = _LEAD_RE.match(orig[0])
    trail = _TRAIL_RE.search(orig[-1])
    out[0] = (lead.group(0) if lead else "") + out[0]
    out[-1] = out[-1] + (trail.group(0) if trail else "")
    return out


def apply_tokens(tokens: list[str], rules: list[dict]) -> tuple[list[str], list[dict], list[int]]:
    """D3: ``(new_tokens, applied, origin)`` — ``applied`` = ``[{rule_id, at_token}]`` (``at_token`` = index in
    ``tokens``); ``origin[k]`` = index in ``tokens`` of the original token new token ``k`` stands for (the first of
    the matched run for every token of a replacement)."""
    norm = [normalize_word(t) for t in tokens]
    out: list[str] = []
    origin: list[int] = []
    applied: list[dict] = []
    pos = 0
    for start, end, rule in _match_spans(norm, rules):
        out += tokens[pos:start]
        origin += range(pos, start)
        repl = _replacement(tokens[start:end], rule)
        out += repl
        origin += [start] * len(repl)
        applied.append({"rule_id": rule["id"], "at_token": start})
        pos = end
    out += tokens[pos:]
    origin += range(pos, len(tokens))
    return out, applied, origin


def apply_lines(lines: list[str], rules: list[dict]) -> tuple[list[str], list[dict]]:
    """D3: the same, on caption lines; a new token belongs to the line of the first original token of its run, so
    the line boundaries (P3 chunking) keep their positions. Returns ``(lines, applied)``."""
    if not rules:
        return list(lines), []
    tokens: list[str] = []
    line_of: list[int] = []
    for n, line in enumerate(lines):
        words = line.split()
        tokens += words
        line_of += [n] * len(words)
    new, applied, origin = apply_tokens(tokens, rules)
    if not applied:
        return list(lines), []
    buckets: list[list[str]] = [[] for _ in lines]
    for tok, o in zip(new, origin):
        buckets[line_of[o]].append(tok)
    return [line for line in (" ".join(b) for b in buckets) if line], applied


def apply_paragraphs(paragraphs: list[str], rule: dict) -> tuple[list[str], int]:
    """D4: ``(paragraphs, places)`` after applying ``rule``; a run never crosses a paragraph break; whitespace
    outside the replaced runs is untouched."""
    out: list[str] = []
    places = 0
    for para in paragraphs:
        words = list(_WORD_RE.finditer(para))
        spans = _match_spans([normalize_word(m.group(0)) for m in words], [rule])
        if not spans:
            out.append(para)
            continue
        pieces: list[str] = []
        pos = 0
        for start, end, r in spans:
            pieces.append(para[pos:words[start].start()])
            pieces.append(" ".join(_replacement([m.group(0) for m in words[start:end]], r)))
            pos = words[end - 1].end()
        pieces.append(para[pos:])
        out.append("".join(pieces))
        places += len(spans)
    return out, places


def apply_rule_to_posts(work_dir: Path, rule: dict, lock: AbstractContextManager, now: str) -> dict:
    """D4: apply ``rule`` to every ``ai`` / ``raw`` post not ticked "Đã đăng bài" of every episode under
    ``work_dir``; each ``posts.json`` is read-modified-written under ``lock``. Returns ``{posts, places}``."""
    posts = places = 0
    if not work_dir.is_dir():
        return {"posts": 0, "places": 0}
    for path in sorted(work_dir.glob(f"*/{store.POSTS_NAME}")):
        episode_id = path.parent.name
        with lock:
            try:
                doc = store.read_posts(path, episode_id)
            except store.PostsError as exc:
                log.warning("post: bỏ qua %s khi áp luật %s: %s", path, rule["id"], exc)
                continue
            changed = False
            entries = []
            for e in doc["posts"]:
                if e["origin"] in (store.AI, store.RAW) and e["posted_at"] is None:
                    new, n = apply_paragraphs(e["paragraphs"], rule)
                    if n:
                        e = {**e, "paragraphs": new, "updated_at": now}
                        posts += 1
                        places += n
                        changed = True
                entries.append(e)
            if changed:
                store.write(path, {**doc, "posts": entries})
    return {"posts": posts, "places": places}


# --- D6: edit log + stats ---------------------------------------------------------------------------------------

def edit_log_path(corrections_path: Path) -> Path:
    return Path(corrections_path).parent / EDIT_LOG_NAME


def append_edit_log(corrections_path: Path, *, at: str, episode_id: str, clip_id: str, words: int,
                    changed_words: int) -> None:
    path = edit_log_path(corrections_path)
    line = json.dumps({"at": at, "episode_id": episode_id, "clip_id": clip_id, "words": words,
                       "changed_words": changed_words}, ensure_ascii=False)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        raise CorrectionsError(f"không ghi được nhật ký sửa {path}: {exc}") from exc


def stats(corrections_path: Path) -> dict:
    """D6: ``{saves, avg_changed_pct}`` — number of logged saves and the mean ``changed_words / words`` (in %, one
    decimal) of the last :data:`STATS_WINDOW` saves with ``words > 0`` (``None`` when there are none)."""
    try:
        lines = edit_log_path(corrections_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"saves": 0, "avg_changed_pct": None}
    rows = []
    for line in lines:
        try:
            d = json.loads(line)
            rows.append((int(d["words"]), int(d["changed_words"])))
        except (ValueError, KeyError, TypeError):
            continue
    window = [c / w for w, c in rows[-STATS_WINDOW:] if w > 0]
    avg = round(100 * sum(window) / len(window), 1) if window else None
    return {"saves": len(rows), "avg_changed_pct": avg}
