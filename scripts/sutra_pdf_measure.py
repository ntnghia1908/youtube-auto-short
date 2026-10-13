"""SR1.3 measurement (not a test): run the sutra PDF import on real PDFs and print numbers, never sutra text.

usage: python scripts/sutra_pdf_measure.py [--out DIR] [--expect-phams N] FILE.pdf [FILE.pdf ...]

Goes through ``importer.import_pdf`` (the same child process ``python -I`` as the web route), then
``markup.parse`` (AC 4). Real PDFs are copyrighted: pass them by path, do not commit them or their text.
Reported per file: sections, section list sanity, ``markup.parse`` result, leftover running-header lines
(whole ALL-CAPS lines whose digit-less form repeats >= 4 times) and glued_header_lines (a line with ALL-CAPS words + page number inside it), fragment lines (< 45 chars, no final punctuation,
inside prose sections, i.e. sections whose mean line length >= 45), vow labels ("N. ..." lines), warnings count.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auto_short.sutra import importer, markup  # noqa: E402

END_PUNCT = tuple(".,;:!?…。，；：！？)”\"'’»]")


def measure(path: Path, tmp: Path, expect_phams: int | None) -> tuple[dict, str]:
    t0 = time.time()
    try:
        text, warnings = importer.import_pdf(path.name, path.read_bytes(), tmp)
    except importer.ImportFileError as e:
        return {"file": path.name, "error": str(e), "status": e.status}, ""
    secs: list[tuple[str, list[str]]] = []
    for ln in text.split("\n"):
        if ln.startswith("# "):
            secs.append((ln[2:], []))
        elif secs and ln.strip() and not ln.startswith("[^") or (secs and ln.strip() and ln.startswith("[^") and not re.match(r"^\[\^\d+\]:", ln)):
            secs[-1][1].append(ln)
    parse_ok, parse_err = True, ""
    try:
        sutra = markup.parse(text)
        n_sections = sutra.section_count
    except markup.MarkupError as e:
        parse_ok, parse_err, n_sections = False, str(e), len(secs)
    keys = Counter(" ".join(re.sub(r"\d+", " ", ln).split()) for _, ls in secs for ln in ls)
    leftovers = {k: n for k, n in keys.items() if n >= 4 and k and re.search(r"[A-ZÀ-Ỹ]{3}", k) and k == k.upper()}
    glued = sum(1 for _, ls in secs for x in ls if re.search(r"[A-ZÀ-Ỹ]{2,}(?: [A-ZÀ-Ỹ]{2,})+ \d{1,4}(?: |$)", x))
    frags = 0
    for _, ls in secs:
        if ls and sum(len(x) for x in ls) / len(ls) >= 45:
            frags += sum(1 for x in ls if len(x) < 45 and not x.rstrip().endswith(END_PUNCT) and not x.startswith("[^"))
    # vow labels may share a line ("1. ... nguyện. 2. ... nguyện."): collect every "N. Capital" inside a line
    labels = sorted({int(m.group(1)) for _, ls in secs for x in ls
                     for m in re.finditer(r"(?:^|[\s*])(\d{1,2})\. [A-ZĐÀ-Ỹ]", x)})
    out = {
        "file": path.name, "seconds": round(time.time() - t0, 1), "chars": len(text),
        "sections": n_sections, "markup_parse_ok": parse_ok, "markup_error": parse_err[:200],
        "leftover_header_lines": sum(leftovers.values()), "leftover_distinct": len(leftovers), "glued_header_lines": glued,
        "fragment_lines": frags, "numbered_labels": len(labels), "labels_in_1_48": len([n for n in labels if 1 <= n <= 48]),
        "warnings": len(warnings),
        "lines_per_section_median": sorted(len(ls) for _, ls in secs)[len(secs) // 2] if secs else 0,
    }
    if expect_phams is not None:
        out["de_headings"] = sum(1 for t, _ in secs if re.search(r"\bĐỆ (NHẤT|NHỊ|TAM|TỨ|NGŨ|LỤC|THẤT|BÁT|CỬU|THẬP)( [A-ZÀ-Ỹ]+)*$", t))
        out["expect_de_headings"] = expect_phams
    return out, text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="write each converted text here (for hand comparison; do not commit)")
    ap.add_argument("--expect-phams", type=int)
    ap.add_argument("pdfs", nargs="+")
    a = ap.parse_args()
    with TemporaryDirectory() as td:
        for f in a.pdfs:
            res, text = measure(Path(f), Path(td), a.expect_phams)
            print(json.dumps(res, ensure_ascii=False))
            if a.out and text:
                Path(a.out).mkdir(parents=True, exist_ok=True)
                (Path(a.out) / (Path(f).stem[:40] + ".txt")).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
