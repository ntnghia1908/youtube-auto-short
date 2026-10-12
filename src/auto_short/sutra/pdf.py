"""Sutra PDF import S5a: PDF text layer -> S2 sutra text (+ warnings). No Auto Short imports.

The layout logic is pure functions over :class:`Page` / :class:`Line` (testable without a PDF); only
:func:`page_runs` / :func:`extract` touch ``pypdf``. The parse is meant to run in a child process
(``python -I -m auto_short.sutra.pdf <file>`` prints JSON ``{text, warnings}`` or ``{error, status}``; see
``importer.import_pdf``), because a broken PDF can make pypdf loop or eat memory.

The result is a *suggestion*: the editor (S5) is where the user fixes it. Contract:
docs/decisions/SR1-sutra-reader-contract.md S5a.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .importer import _escape

MAX_PAGES = 1000
Y_TOL = 2.5  # pt: runs within this y distance are one line
CELL_GAP = 40.0  # pt: gap between Vietnamese and Chinese runs that starts a separate cell
SIZE_JUMP = 1.4  # a footer glued to a heading on one line differs this much in size: separate cells
SMALL = 0.85  # footnote / superscript: size below this share of the body size
MAX_LINE = 4000  # S2 allows 5 000 chars per content line; longer logical lines are split
DEFAULT_TITLE = "Bộ kinh mới"

_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_LETTER = re.compile(r"[^\W\d_]")
_DIGIT = re.compile(r"\d")
_NUM_ITEM = re.compile(r"^\d+\. ")
_NOTE_MARK = re.compile(r"\[\^(\d{1,3})\]")
_MARK = re.compile(r"\x00(\d+):(\d+)\x00")
_HEADING_WORDS = frozenset({"CHƯƠNG", "PHẨM", "ĐỆ", "HỒI", "QUYỂN", "PHẦN", "BÀI"})
_VOWELS = "aăâeêioôơuưyàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ"
_INITIAL = r"(?:ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdđghklmnpqrstvx])"
_SYLLABLE = re.compile(rf"^{_INITIAL}?[{_VOWELS}]{{1,3}}(?:ch|ng|nh|[cmnpt])?$")
_CONS_ONLY = re.compile(rf"^{_INITIAL}$")
_VOWEL_START = re.compile(rf"^[{_VOWELS}]")
_NARROW = frozenset("iìíỉĩịltfjr")


class PdfError(Exception):
    """Unusable PDF; ``str(e)`` is a Vietnamese message, ``status`` the HTTP status (422)."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass
class Run:
    """One text piece with its position (pdf points, y up) as the pypdf visitor reports it."""

    x: float
    y: float
    text: str
    size: float
    bold: bool = False


@dataclass
class Line:
    text: str
    x: float
    y: float
    size: float = 12.0
    bold: bool = False
    col: int = 0


@dataclass
class Page:
    lines: list[Line]
    height: float = 800.0
    width: float = 600.0


# --- text helpers ---------------------------------------------------------------------------------------


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def is_cjk_text(s: str) -> bool:
    letters = _LETTER.findall(s)
    return bool(letters) and sum(1 for ch in letters if _CJK.match(ch)) / len(letters) >= 0.5


def is_upper_heading(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters) and len(s) <= 80 and not _CJK.search(s)


def is_syllable(word: str) -> bool:
    return bool(_SYLLABLE.match(unicodedata.normalize("NFC", word).lower()))


def fix_split_words(s: str) -> str:
    """Fallback for "h ữu" -> "hữu": a lower-case consonant-only token (never a word) followed by a token that
    starts with a vowel, when both together are a valid Vietnamese syllable."""
    out: list[str] = []
    for tok in s.split(" "):
        if out and _CONS_ONLY.match(out[-1]) and _VOWEL_START.match(tok.lower()) and is_syllable(out[-1] + tok):
            out[-1] += tok
        else:
            out.append(tok)
    return " ".join(out)


# --- runs -> lines ------------------------------------------------------------------------------------


def _est_width(text: str, size: float) -> float:
    return sum((0.25 if c == " " else 0.3 if c in _NARROW else 0.5) for c in text) * size


def _fix_diacritic_spaces(rs: list[Run]) -> list[Run]:
    """Word emits a lone vowel with its mark as a run ``' ữ'`` whose leading space has no advance: decide the
    space by the x distance to the next run (the run's real width), not by the space character in the text."""
    out = list(rs)
    for i, r in enumerate(out[:-1]):
        body = nfc(r.text.strip())
        if r.text[:1].isspace() and len(body) == 1 and body.isalpha() and ord(body) > 127 and i > 0:
            width = out[i + 1].x - r.x
            # some producers do not advance x inside one text object: no usable width, keep the space
            if width > 0.1 * r.size and abs(width - _est_width(body, r.size)) < abs(width - _est_width(r.text, r.size)):
                out[i] = Run(r.x, r.y, r.text.lstrip(), r.size, r.bold)
    return out


def attach_superscripts(runs: list[Run], col_of=lambda r: 0) -> list[Run]:
    """A small number just above-and-after a word on the same line -> ``[^n]`` run on that line's y."""
    sizes = [r.size for r in runs if r.text.strip() and r.size > 0]
    if not sizes:
        return runs
    med = statistics.median(sizes)
    out: list[Run] = []
    for r in runs:
        if re.fullmatch(r"\d{1,3}", r.text.strip()) and 0 < r.size < med * SMALL:
            cands = [s for s in runs if s is not r and s.text.strip() and s.size >= med * SMALL
                     and col_of(s) == col_of(r) and s.x <= r.x and 0 < r.y - s.y <= max(8.0, 0.6 * s.size)]
            if cands:
                base = min(cands, key=lambda s: (round(r.y - s.y, 1), -s.x))
                out.append(Run(r.x, base.y, f"[^{r.text.strip()}]", base.size, base.bold))
                continue
        out.append(r)
    return out


def group_runs(runs: list[Run], width: float, height: float) -> Page:
    """Runs -> lines: landscape pages are two columns (left, then right half), runs within ``Y_TOL`` of the same
    y form a line, a big horizontal gap between Vietnamese and Chinese text starts a separate cell."""
    two_up = width > height

    def col_of(r: Run) -> int:
        return 1 if two_up and r.x >= width / 2 else 0

    runs = attach_superscripts([r for r in runs if r.text], col_of)
    lines: list[Line] = []
    for col in sorted({col_of(r) for r in runs}):
        groups: list[tuple[float, list[Run]]] = []
        for r in sorted((r for r in runs if col_of(r) == col), key=lambda r: -r.y):
            if groups and abs(groups[-1][0] - r.y) <= Y_TOL:
                groups[-1][1].append(r)
            else:
                groups.append((r.y, [r]))
        for y, rs in groups:
            rs = _fix_diacritic_spaces(sorted(rs, key=lambda r: r.x))
            cells: list[list[Run]] = [[rs[0]]]
            for r in rs[1:]:
                prev = cells[-1][-1]
                gap = r.x - (prev.x + len(prev.text) * prev.size * 0.5)
                last_real = next((c for c in reversed(cells[-1]) if c.text.strip()), None)
                jump = (r.text.strip() and last_real is not None and last_real.size > 0 and r.size > 0
                        and max(r.size, last_real.size) / min(r.size, last_real.size) > SIZE_JUMP)
                if r.text.strip() and (jump or (gap > CELL_GAP and is_cjk_text(r.text)
                                                != is_cjk_text("".join(c.text for c in cells[-1])))):
                    cells.append([r])
                else:
                    cells[-1].append(r)
            for cell in cells:
                text = " ".join(nfc("".join(c.text for c in cell)).split())
                real = [c for c in cell if c.text.strip()]
                if not text or not real:
                    continue
                lines.append(Line(text, real[0].x, y, statistics.median(c.size for c in real),
                                  all(c.bold for c in real), col))
    return Page(lines, height, width)


# --- pypdf ----------------------------------------------------------------------------------------------


def page_runs(page) -> tuple[list[Run], float, float]:
    """Text pieces of a pypdf page (position from tm x cm, size, bold from ``/BaseFont``)."""
    box = page.mediabox
    left, bottom = float(box.left), float(box.bottom)
    width, height = float(box.width), float(box.height)
    runs: list[Run] = []

    def visit(text, cm, tm, font_dict, font_size):
        if not text or text == "\n":
            return
        x = tm[4] * cm[0] + cm[4] - left
        y = tm[5] * cm[3] + cm[5] - bottom
        size = abs(font_size * (tm[3] or 1) * (cm[3] or 1))
        bold = "bold" in str((font_dict or {}).get("/BaseFont", "")).lower()
        runs.append(Run(x, y, text.replace("\n", " "), size, bold))

    page.extract_text(visitor_text=visit)
    return runs, width, height


def extract(path: str) -> tuple[str, list[str]]:
    """Read a PDF file -> ``(S2 text, warnings)``. Raises :class:`PdfError`."""
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover - dependency missing
        raise PdfError("máy chủ chưa cài pypdf, không đọc được PDF", 500) from e
    import logging

    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise PdfError("PDF có mật khẩu, không đọc được")
        n = len(reader.pages)
    except PdfError:
        raise
    except Exception as e:  # noqa: BLE001 - pypdf raises many types on broken input
        raise PdfError("file PDF hỏng (không mở được)") from e
    if n > MAX_PAGES:
        raise PdfError(f"PDF quá {MAX_PAGES} trang ({n} trang)")
    pages: list[Page] = []
    warnings: list[str] = []
    for i in range(n):
        try:
            runs, w, h = page_runs(reader.pages[i])
        except Exception:  # noqa: BLE001
            warnings.append(f"trang {i + 1}: không đọc được chữ")
            pages.append(Page([]))
            continue
        pages.append(group_runs(runs, w, h))
    return layout(pages, warnings)


# --- layout (pure) --------------------------------------------------------------------------------------


def _zone(line: Line, page: Page, frac: float) -> bool:
    return line.y > page.height * (1 - frac) or line.y < page.height * frac


def _norm_key(t: str) -> str:
    return " ".join(re.sub(r"\d+", " ", t).split())


def _header_regexes(core: str) -> tuple[re.Pattern, re.Pattern]:
    body = r"\s*(?:\d+\s*)?".join(re.escape(w) for w in core.split())
    end = re.compile(r"(?:^|\s)(?:\d+\s*)?" + body + r"(?:\s*\d+)?\s*$")
    start = re.compile(r"^\s*(?:\d+\s*)?" + body + r"(?:\s*\d+)?(?=\s|$)")
    return end, start


def strip_running(pages: list[Page]) -> list[str]:
    """Drop headers / footers: text (digits removed) repeated on >= 15 % of pages (>= 3), in the top / bottom 20 %
    of the page, or at ANY position when the line carries a number (page numbers; Google Docs puts the footer
    right after the last text line). Also removes it when glued to the start / end of another line. A phrase
    without digits must also repeat at the same height, so a refrain repeated in a chant is kept."""
    n = len(pages)
    if n < 3:
        return []
    per_key: dict[str, Counter] = defaultdict(Counter)
    for pg in pages:
        seen = set()
        for l in pg.lines:
            has_digit = bool(_DIGIT.search(l.text))
            if not (has_digit or _zone(l, pg, 0.2)):
                continue
            k = _norm_key(l.text)
            if k and any(c.isalpha() for c in k):
                seen.add((k, None if has_digit else round(l.y / 4)))
        for k, bucket in seen:
            per_key[k][bucket] += 1
    thresh = max(3, 0.15 * n)
    cores = sorted((k for k, c in per_key.items() if max(c.values()) >= thresh), key=len, reverse=True)
    pats = [(c, *_header_regexes(c)) for c in cores[:60]]
    for pg in pages:
        for l in pg.lines:
            if not (_DIGIT.search(l.text) or _zone(l, pg, 0.2)):
                continue
            glued = bool(_DIGIT.search(l.text))  # without a number only a whole-line match counts
            for core, end, start in pats:
                if not glued:
                    if " ".join(l.text.split()) == core:
                        l.text = ""
                        break
                    continue
                m = end.search(l.text)
                if m:
                    l.text = l.text[: m.start()].strip()
                else:
                    m = start.match(l.text)
                    if m and _DIGIT.search(m.group(0)):
                        l.text = l.text[m.end():].strip()
                if not l.text:
                    break
        pg.lines[:] = [l for l in pg.lines if l.text]
    return cores


def _page_body(pg: Page, default: float = 12.0) -> float:
    sizes = [l.size for l in pg.lines if l.size]
    return statistics.median(sizes) if sizes else default


def _footnote_defs(pg: Page, pi: int, notes: dict[tuple[int, int], str]) -> None:
    """Small-print numbered lines in the bottom 20 % -> ``notes[(page, n)]``; their lines leave the page. Small
    ``1. text`` lines are a numbered list of the body (kept). Continuation lines extend the last note."""
    pbody = _page_body(pg)
    low = [l for l in pg.lines if l.y < pg.height * 0.2 and l.size < pbody * SMALL]
    starters = [l for l in low if l.text[:1].isdigit()]
    if not starters:
        return
    top = max(l.y for l in starters)
    region = sorted((l for l in low if l.y <= top + 1), key=lambda l: (l.col, -l.y, l.x))
    used: set[int] = set()
    drop: set[int] = set()
    current: int | None = None
    for l in region:
        if id(l) in used:
            continue
        if re.match(r"^\d{1,3}\.", l.text):
            current = None  # `1. text` small-print list item: body text
            continue
        m = re.match(r"^(\d{1,3})(?:\s+(.*))?$", l.text)
        if m is None:
            if current is not None:
                notes[(pi, current)] += " " + l.text
                drop.add(id(l))
            continue
        n, rest = int(m.group(1)), m.group(2)
        if rest:
            current = n
            notes.setdefault((pi, n), rest)
            drop.add(id(l))
            continue
        # a lone number: its text is the next piece on (almost) the same line
        nxt = next((k for k in region if k is not l and id(k) not in used and abs(k.y - l.y) < 6 and k.col == l.col
                    and k.x > l.x), None)
        if nxt is not None and nxt.text.lstrip().startswith("."):
            nxt.text = l.text + nxt.text.lstrip()  # numbered list item in small print
            nxt.x = l.x
            drop.add(id(l))
            current = None
        elif nxt is not None:
            notes.setdefault((pi, n), nxt.text)
            current = n
            used.add(id(nxt))
            drop.update((id(l), id(nxt)))
    pg.lines[:] = [l for l in pg.lines if id(l) not in drop]


def _is_chapter_header(text: str) -> bool:
    """ALL-CAPS words with a page number (at the start, end or between two chapter titles): a per-chapter header."""
    toks = text.split()
    nums = [i for i, t in enumerate(toks) if re.fullmatch(r"\d{1,4}", t)]
    words = [t for i, t in enumerate(toks) if i not in nums]
    if len(nums) != 1 or not words:
        return False
    core = " ".join(words)
    letters = [c for c in core if c.isalpha()]
    if not letters or not all(c.isupper() for c in letters) or _DIGIT.search(core) or _CJK.search(core):
        return False
    return not (nums[0] == len(toks) - 1 and words[0] in _HEADING_WORDS and len(words) <= 2)  # "PHẨM 12": a heading


def clean_page(pg: Page, pi: int, notes: dict[tuple[int, int], str], warnings: list[str]) -> None:
    """Footnote definitions out (-> ``notes``), then chapter running headers ("ALLCAPS + page number" in the top /
    bottom 12 %), then bare page numbers; a footnote number left over without a word before it is a warning."""
    _footnote_defs(pg, pi, notes)
    pbody = _page_body(pg)
    keep = []
    for l in pg.lines:
        if (_zone(l, pg, 0.12) or l.size <= pbody * 0.6) and _is_chapter_header(l.text):
            continue
        if re.fullmatch(r"\d{1,4}", l.text) and _zone(l, pg, 0.15) and (l.size >= pbody * 0.7 or _zone(l, pg, 0.08)):
            continue
        if re.fullmatch(r"\d{1,3}", l.text) and l.size < pbody * SMALL:
            warnings.append(f"trang {pi + 1}: số chú thích {l.text} không gắn được vào chữ nào, đã bỏ")
            continue
        keep.append(l)
    pg.lines[:] = keep


@dataclass
class _Phys:
    text: str
    indent: float
    gap: bool
    full: bool
    bold: bool
    loose: bool


@dataclass
class _Sec:
    title: str | None
    lines: list[_Phys] = field(default_factory=list)
    side: list[str] = field(default_factory=list)


def _classify(pages: list[Page]) -> list[tuple]:
    """Pages -> ordered items ``("head", text)`` / ``("side", text)`` / ``("line", _Phys)``."""
    sizes = Counter(round(l.size, 1) for pg in pages for l in pg.lines if l.size)
    body = sizes.most_common(1)[0][0] if sizes else 12.0
    xs: dict[tuple[int, int], Counter] = defaultdict(Counter)
    lens: dict[int, list[int]] = defaultdict(list)
    for pi, pg in enumerate(pages):
        for l in pg.lines:
            if not is_upper_heading(l.text) and not is_cjk_text(l.text):
                xs[(l.col, pi % 2)][round(l.x)] += 1
                lens[l.col].append(len(l.text))
    margins = {}
    for k, c in xs.items():
        common = [x for x, n in c.items() if n >= max(3, 0.01 * sum(c.values()))]
        margins[k] = min(common) if common else min(c)
    full = {c: sorted(v)[int(len(v) * 0.9)] * 0.8 for c, v in lens.items()}
    gaps: list[float] = []
    for pg in pages:
        for c in {l.col for l in pg.lines}:
            ys = sorted((l.y for l in pg.lines if l.col == c), reverse=True)
            gaps += [a - b for a, b in zip(ys, ys[1:]) if 0 < a - b < 80]
    doc_step = statistics.median(gaps) if gaps else 20.0

    items: list[tuple] = []
    for pi, pg in enumerate(pages):
        for col in sorted({l.col for l in pg.lines}):
            cl = sorted((l for l in pg.lines if l.col == col), key=lambda l: (-l.y, l.x))
            margin = margins.get((col, pi % 2), min(l.x for l in cl))
            ys = [l.y for l in cl]
            pgaps = [a - b for a, b in zip(ys, ys[1:]) if 0 < a - b < 60]
            step = statistics.median(pgaps) if pgaps else 20.0
            prev_y = None
            for l in cl:
                t = _NOTE_MARK.sub(lambda m: f"\x00{pi}:{m.group(1)}\x00", l.text)
                dy = (prev_y - l.y) if prev_y is not None else step
                gap = prev_y is not None and dy > step * 1.5
                loose = dy > doc_step * 1.15
                prev_y = l.y
                indent = l.x - margin
                if is_upper_heading(l.text) and (indent > 6 or l.size > body * 1.03):
                    items.append(("head", _MARK.sub("", t)))
                elif is_cjk_text(l.text) and indent > 150:
                    items.append(("side", t))
                else:
                    items.append(("line", _Phys(t, indent, gap, len(l.text) >= full.get(col, 999), l.bold, loose)))
    return items


def _sections(items: list[tuple]) -> list[_Sec]:
    secs: list[_Sec] = []
    cur: _Sec | None = None
    i = 0
    while i < len(items):
        kind, val = items[i]
        if kind == "head":
            title = val
            i += 1
            while i < len(items) and items[i][0] == "head":
                title += " " + items[i][1]
                i += 1
            cur = _Sec(title)
            secs.append(cur)
            continue
        if cur is None:
            cur = _Sec(None)
            secs.append(cur)
        if kind == "side":
            cur.side.append(val)
        else:
            cur.lines.append(val)
        i += 1
    return secs


def _logical(sec: _Sec, use_bold: bool) -> list[tuple[str, bool]]:
    """Physical lines -> logical lines ``(text, blank_before)``."""
    has_indent = any(p.indent > 8 for p in sec.lines)
    logical: list[list] = []  # [text, gap, last_full, all_bold]
    for p in sec.lines:
        at_margin = abs(p.indent) <= 8
        t = p.text
        cont = bool(logical) and not _NUM_ITEM.match(t) and (
            t[:1].islower()
            or (has_indent and at_margin and not p.loose)
            or (logical[-1][2] and not p.loose and not (has_indent and not at_margin)))
        if cont:
            logical[-1][0] += " " + t
            logical[-1][2] = p.full
            logical[-1][3] = logical[-1][3] and p.bold
        else:
            logical.append([t, p.gap, p.full, p.bold])
    out = []
    for t, gap, _, bold in logical:
        out.append(((("\x01" if bold and use_bold else "") + fix_split_words(t)), gap))
    return out


def _split_long(text: str) -> list[str]:
    parts = []
    while len(text) > MAX_LINE:
        cut = max(text.rfind(sep, 0, MAX_LINE) for sep in (". ", "; ", "。", ", "))
        cut = cut + 1 if cut > 0 else text.rfind(" ", 0, MAX_LINE)
        if cut <= 0:
            cut = MAX_LINE
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    return parts + [text]


def layout(pages: list[Page], warnings: list[str] | None = None) -> tuple[str, list[str]]:
    """All pages -> ``(S2 text, warnings)``. Raises :class:`PdfError` when there is no text layer."""
    warnings = list(warnings or [])
    if sum(len(l.text) for pg in pages for l in pg.lines) < 20:
        raise PdfError("PDF không có lớp chữ (có thể là bản scan); chưa hỗ trợ OCR")
    empty = [i + 1 for i, pg in enumerate(pages) if not pg.lines]
    if empty:
        shown = ", ".join(map(str, empty[:10])) + (f" và {len(empty) - 10} trang khác" if len(empty) > 10 else "")
        warnings.append(f"trang không có chữ: {shown}")
    strip_running(pages)
    notes: dict[tuple[int, int], str] = {}
    for pi, pg in enumerate(pages):
        clean_page(pg, pi, notes, warnings)
    secs = _sections(_classify(pages))
    nbold = sum(1 for s in secs for p in s.lines if p.bold)
    ntot = sum(len(s.lines) for s in secs) or 1
    use_bold = nbold / ntot < 0.5

    out = [f"= {DEFAULT_TITLE}", ""]
    used_notes: set[tuple[int, int]] = set()
    counts: list[tuple[str, int]] = []
    for sec in secs:
        logical = _logical(sec, use_bold)
        if not logical and not sec.side:
            if sec.title:
                warnings.append(f"mục “{sec.title}” không có nội dung, đã bỏ")
            continue
        title = sec.title or "Mở đầu"
        body: list[str] = []
        prose = bool(logical) and statistics.mean(len(t) for t, _ in logical) > 70
        for k, (t, gap) in enumerate(logical):
            if k and (gap or prose):
                body.append("")
            body.append(t)
        if sec.side:
            body += [""] + sec.side
        # footnote markers -> [^1].. numbered per section, in order of appearance
        numbering: dict[tuple[int, int], int] = {}
        defs: list[str] = []

        def repl(m: re.Match) -> str:
            key = (int(m.group(1)), int(m.group(2)))
            if key not in notes:
                warnings.append(f"mục “{title}”: chú thích {key[1]} (trang {key[0] + 1}) không có nội dung, đã bỏ dấu")
                return ""
            if key not in numbering and len(numbering) < 999:
                numbering[key] = len(numbering) + 1
                defs.append(f"[^{numbering[key]}]: {notes[key]}")
                used_notes.add(key)
            return f"[^{numbering[key]}]" if key in numbering else ""

        lines: list[str] = []
        for t in body:
            t = _MARK.sub(repl, t) if "\x00" in t else t
            bold = t.startswith("\x01")
            t = t.lstrip("\x01")
            if not t.strip():
                lines.append("")
                continue
            for part in _split_long(t) if len(t) > MAX_LINE else [t]:
                lines.append(("* " + part) if bold else _escape(part))
            if len(t) > MAX_LINE:
                warnings.append(f"mục “{title}”: một dòng quá dài đã bị chia nhỏ")
        out.append("# " + title)
        out.append("")
        out += lines
        out.append("")
        if defs:
            out += defs + [""]
        counts.append((title, sum(1 for ln in lines if ln)))
    for (pi, n) in sorted(set(notes) - used_notes):
        warnings.append(f"trang {pi + 1}: chú thích {n} không có dấu tham chiếu, đã bỏ")
    _size_warnings(counts, warnings)
    while out and out[-1] == "":
        out.pop()
    text = "\n".join(out) + "\n"
    return text, warnings


def _size_warnings(counts: list[tuple[str, int]], warnings: list[str]) -> None:
    if len(counts) < 5:
        return
    med = statistics.median(c for _, c in counts)
    for title, c in counts:
        if c > max(400, med * 10):
            warnings.append(f"mục “{title}” dài bất thường ({c} dòng), có thể thiếu tiêu đề mục")
        elif c <= 1 and med >= 6:
            warnings.append(f"mục “{title}” ngắn bất thường ({c} dòng), có thể là tiêu đề nhầm")


# --- child process entry -----------------------------------------------------------------------------------


def _limit_memory() -> None:
    try:
        import resource

        limit = 3 * 1024 ** 3
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):  # pragma: no cover - platform without rlimit
        pass


def main(path: str) -> int:
    """Print ``{"text", "warnings"}`` or ``{"error", "status"}`` as one JSON line on stdout."""
    _limit_memory()
    try:
        text, warnings = extract(path)
        doc = {"text": text, "warnings": warnings}
        code = 0
    except PdfError as e:
        doc, code = {"error": str(e), "status": e.status}, 0
    except MemoryError:
        doc, code = {"error": "PDF quá phức tạp (hết bộ nhớ khi đọc)", "status": 422}, 0
    except Exception as e:  # noqa: BLE001
        doc, code = {"error": f"không đọc được PDF ({type(e).__name__})", "status": 422}, 0
    sys.stdout.write(json.dumps(doc, ensure_ascii=False))
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]) if len(sys.argv) == 2 else 2)
