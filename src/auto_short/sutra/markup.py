"""Sutra text format S2 -> reading structure S3 (pure, SR1 contract). No Auto Short imports."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

SCHEMA_VERSION = 1
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_LINE_CHARS = 5000
MAX_SECTIONS = 2000
HAN_RATIO = 0.5

_MARKER = re.compile(r"^([=~@#])(?:[ \t]+(.*))?$")
_NOTE_DEF = re.compile(r"^\[\^(\d{1,3})\]:[ \t]*(.*)$")
_NOTE_REF = re.compile(r"\[\^(\d{1,3})\]")


class MarkupError(ValueError):
    """Every S2 error of a text: ``errors`` = ``[(line, message)]`` (line 0 = whole text)."""

    def __init__(self, errors: list[tuple[int, str]]):
        self.errors = errors
        super().__init__("; ".join(f"dòng {n}: {m}" if n else m for n, m in errors[:5]))

    def to_json(self) -> list[dict]:
        return [{"line": n, "message": m} for n, m in self.errors]


@dataclass
class Line:
    text: str
    kind: str  # "text" | "inst" | "han" | "strong"


@dataclass
class Section:
    id: str
    title: str
    paragraphs: list[list[Line]] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)


@dataclass
class Group:
    title: str | None
    sections: list[Section] = field(default_factory=list)


@dataclass
class Sutra:
    title: str
    intro: list[str]
    groups: list[Group]

    @property
    def section_count(self) -> int:
        return sum(len(g.sections) for g in self.groups)

    def to_json(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "title": self.title, "intro": list(self.intro),
                "groups": [{"title": g.title,
                            "sections": [{"id": s.id, "title": s.title,
                                          "paragraphs": [[{"text": ln.text, "kind": ln.kind} for ln in p]
                                                         for p in s.paragraphs],
                                          "notes": dict(s.notes)} for s in g.sections]}
                           for g in self.groups]}


def normalize(text: str) -> str:
    """BOM off, ``\\n`` line ends, NFC (what is stored)."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text)


def _is_han(ch: str) -> bool:
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿"


def line_kind(text: str) -> str:
    if len(text) >= 2 and ((text[0] == "(" and text[-1] == ")") or (text[0] == "（" and text[-1] == "）")):
        return "inst"
    letters = [c for c in text if c.isalpha()]
    if letters and sum(1 for c in letters if _is_han(c)) / len(letters) >= HAN_RATIO:
        return "han"
    return "text"


def parse(text: str) -> Sutra:
    """Parse S2 text; raises :class:`MarkupError` carrying all errors."""
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise MarkupError([(0, "văn bản quá lớn (tối đa 2 MB)")])
    errors: list[tuple[int, str]] = []
    title: str | None = None
    intro: list[str] = []
    groups: list[Group] = []
    pending_group: str | None = None
    has_group_marker = False
    section: Section | None = None
    sec_line = 0
    para: list[Line] | None = None
    refs: dict[str, int] = {}  # note id -> first line using it (current section)
    defs: dict[str, int] = {}  # note id -> definition line
    seen_content = False
    n_sections = 0

    def close_section() -> None:
        nonlocal section, para, refs, defs
        if section is None:
            return
        if not section.paragraphs:
            errors.append((sec_line, f"mục '{section.title}' rỗng"))
        for k, ln in refs.items():
            if k not in section.notes:
                errors.append((ln, f"chú thích [^{k}] chưa có định nghĩa trong mục"))
        for k, ln in defs.items():
            if k not in refs:
                errors.append((ln, f"chú thích [^{k}] được định nghĩa nhưng không dùng"))
        section, para, refs, defs = None, None, {}, {}

    for no, raw in enumerate(normalize(text).split("\n"), start=1):
        line = raw.rstrip()
        if not line.strip():
            para = None
            continue
        line = line.lstrip() if line[0] in " \t" else line
        body: str | None = None  # content text, when the line is content
        strong = False
        m = _MARKER.match(line)
        if line.startswith("\\"):
            body = line[1:].strip()
            if not body:
                continue
        elif m:
            mark, name = m.group(1), (m.group(2) or "").strip()
            if mark == "=":
                if title is not None:
                    errors.append((no, "chỉ được có một dòng '='"))
                elif seen_content:
                    errors.append((no, "dòng '=' phải là dòng không trống đầu tiên"))
                elif not name:
                    errors.append((no, "tên bộ kinh rỗng"))
                else:
                    title = name
                seen_content = True
                continue
            if title is None and not seen_content:
                errors.append((no, "thiếu dòng '= <tên>' ở đầu văn bản"))
                seen_content = True
            if mark == "~":
                if has_group_marker or section is not None or n_sections:
                    errors.append((no, "dòng '~' chỉ được đặt giữa '=' và '@' / '#' đầu tiên"))
                elif name:
                    intro.append(name)
                continue
            if mark == "@":
                if not name:
                    errors.append((no, "tên nhóm rỗng"))
                close_section()
                pending_group, has_group_marker = name or None, True
                if groups and not groups[-1].sections:
                    groups.pop()
                groups.append(Group(pending_group))
                continue
            # mark == "#"
            close_section()
            if not name:
                errors.append((no, "tên mục rỗng"))
            n_sections += 1
            if n_sections == MAX_SECTIONS + 1:
                errors.append((no, f"quá {MAX_SECTIONS} mục"))
            if not groups:
                groups.append(Group(None))
            section = Section(f"s{n_sections}", name)
            groups[-1].sections.append(section)
            sec_line, para = no, None
            continue
        else:
            d = _NOTE_DEF.match(line)
            if d:
                if title is None and not seen_content:
                    errors.append((no, "thiếu dòng '= <tên>' ở đầu văn bản"))
                    seen_content = True
                if section is None:
                    errors.append((no, "chú thích nằm ngoài mục"))
                elif d.group(1) in section.notes:
                    errors.append((no, f"chú thích [^{d.group(1)}] bị trùng"))
                elif not d.group(2).strip():
                    errors.append((no, f"chú thích [^{d.group(1)}] rỗng"))
                else:
                    section.notes[d.group(1)] = d.group(2).strip()
                    defs[d.group(1)] = no
                continue
            body = line.strip()
            if line == "*" or line.startswith("* "):  # emphasis line: bold, no han / inst detection
                body, strong = line[1:].strip(), True
                if not body:
                    continue
        # content line
        if title is None and not seen_content:
            errors.append((no, "thiếu dòng '= <tên>' ở đầu văn bản"))
        seen_content = True
        if section is None:
            errors.append((no, "nội dung nằm ngoài mục (cần dòng '# <tên mục>' trước)"))
            continue
        if len(body) > MAX_LINE_CHARS:
            errors.append((no, f"dòng quá dài (> {MAX_LINE_CHARS} ký tự)"))
            continue
        for r in _NOTE_REF.finditer(body):
            refs.setdefault(r.group(1), no)
        if para is None:
            para = []
            section.paragraphs.append(para)
        para.append(Line(body, "strong" if strong else line_kind(body)))
    close_section()
    if title is None and not seen_content:
        errors.append((0, "văn bản rỗng (thiếu dòng '= <tên>')"))
    if errors:
        raise MarkupError(sorted(errors, key=lambda e: e[0]))
    groups = [g for g in groups if g.sections]
    return Sutra(title or "", intro, groups)
