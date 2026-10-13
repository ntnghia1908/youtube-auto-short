"""Builders for the SR1.3 tests: a minimal hand-written PDF (Helvetica, ASCII only; no real sutra text)."""


def u(i, k):
    """Distinct letters-only tag, so that body lines do not repeat after digits are stripped."""
    n = i * 10 + k
    return chr(97 + n // 26) + chr(97 + n % 26) + "x"


def make_pdf(pages, *, width=595, height=842):
    """Minimal PDF: standard Helvetica (ASCII), ``pages`` = list of lists of (x, y, size, text)."""
    objs = {}
    n_pages = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n_pages))
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode()
    objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for i, items in enumerate(pages):
        ops = []
        for x, y, size, text in items:
            esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"BT /F1 {size} Tf {x} {y} Td ({esc}) Tj ET")
        stream = "\n".join(ops).encode("latin-1")
        objs[4 + 2 * i] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
                           f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>").encode()
        objs[5 + 2 * i] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for num in sorted(objs):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def sample_pdf():
    pages = []
    for i in range(4):
        items = [(260, 800, 10, f"RUNNING HEADER {i + 1}")]
        if i == 0:
            items.append((150, 740, 12, "CHAPTER ONE"))
        for k in range(6):
            items.append((72, 700 - 18 * k, 12, f"Body line {u(i, k)} of the sample text for testing."))
        items.append((90, 560, 12, "Indented start of a new paragraph that wraps"))
        items.append((72, 546, 12, "around to a second line."))
        items.append((290, 30, 10, str(i + 1)))
        pages.append(items)
    return make_pdf(pages)
