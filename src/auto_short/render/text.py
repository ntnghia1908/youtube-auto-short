"""Text measurement, line breaking and fit (docs/decisions/CP7-render-contract.md R5).

Widths come from the font file itself (``cmap`` + ``hmtx`` + ``head.unitsPerEm``, read with ``struct``)
so layout never depends on fontconfig or system fonts. Line breaking works in integer font units, which
makes ties exact and the result independent of float rounding.
"""

from __future__ import annotations

import itertools
import math
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MAX_LINES = 3

# ffmpeg drawtext shapes text with HarfBuzz (kerning), the width model here is the plain hmtx sum.
# Lines are broken against an inner width reduced by this fraction as a safety margin (R5, CP7).
WIDTH_SAFETY = 0.01


class TextError(Exception):
    """Font unreadable, glyph missing or text does not fit (stage fails, R5)."""


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


class Font:
    """Minimal TrueType/OpenType reader: character map, advance widths and vertical metrics."""

    def __init__(self, path: Path):
        self.path = path
        try:
            data = path.read_bytes()
            self._data = data
            tables = {}
            (num,) = struct.unpack_from(">H", data, 4)
            for i in range(num):
                tag, _, off, length = struct.unpack_from(">4sIII", data, 12 + 16 * i)
                tables[tag.decode("latin-1")] = (off, length)
            self._tables = tables
            (self.units_per_em,) = struct.unpack_from(">H", data, self._off("head") + 18)
            hhea = self._off("hhea")
            self.ascender, self.descender = struct.unpack_from(">hh", data, hhea + 4)
            (self._num_hmetrics,) = struct.unpack_from(">H", data, hhea + 34)
            os2 = self._off("OS/2")
            (version,) = struct.unpack_from(">H", data, os2)
            if version < 2:
                raise TextError(f"{path}: OS/2 table version {version} has no sCapHeight")
            self.x_height, self.cap_height = struct.unpack_from(">hh", data, os2 + 86)
            hmtx = self._off("hmtx")
            self._advances = [struct.unpack_from(">H", data, hmtx + 4 * i)[0] for i in range(self._num_hmetrics)]
            self._cmap = self._read_cmap()
            self.family = self._read_name(1) or path.stem
        except (OSError, struct.error, KeyError, UnicodeDecodeError) as exc:
            raise TextError(f"cannot read font {path}: {exc}") from exc

    def _off(self, tag: str) -> int:
        if tag not in self._tables:
            raise TextError(f"{self.path}: font has no {tag!r} table")
        return self._tables[tag][0]

    def _read_cmap(self) -> dict[int, int]:
        data, base = self._data, self._off("cmap")
        (num,) = struct.unpack_from(">H", data, base + 2)
        subtables = {}
        for i in range(num):
            platform, encoding, off = struct.unpack_from(">HHI", data, base + 4 + 8 * i)
            subtables[(platform, encoding)] = base + off
        for key in ((3, 10), (0, 4), (0, 6), (3, 1), (0, 3)):
            if key not in subtables:
                continue
            sub = subtables[key]
            (fmt,) = struct.unpack_from(">H", data, sub)
            if fmt == 12:
                return self._cmap12(sub)
            if fmt == 4:
                return self._cmap4(sub)
        raise TextError(f"{self.path}: no Unicode cmap subtable (format 4 or 12)")

    def _cmap12(self, sub: int) -> dict[int, int]:
        (groups,) = struct.unpack_from(">I", self._data, sub + 12)
        cmap = {}
        for g in range(groups):
            start, end, glyph = struct.unpack_from(">III", self._data, sub + 16 + 12 * g)
            for code in range(start, end + 1):
                cmap[code] = glyph + code - start
        return cmap

    def _cmap4(self, sub: int) -> dict[int, int]:
        data = self._data
        seg = struct.unpack_from(">H", data, sub + 6)[0] // 2
        ends = struct.unpack_from(f">{seg}H", data, sub + 14)
        starts = struct.unpack_from(f">{seg}H", data, sub + 16 + 2 * seg)
        deltas = struct.unpack_from(f">{seg}h", data, sub + 16 + 4 * seg)
        ro_base = sub + 16 + 6 * seg
        range_offsets = struct.unpack_from(f">{seg}H", data, ro_base)
        cmap = {}
        for k in range(seg):
            for code in range(starts[k], ends[k] + 1):
                if code == 0xFFFF:
                    continue
                if range_offsets[k] == 0:
                    glyph = (code + deltas[k]) & 0xFFFF
                else:
                    addr = ro_base + 2 * k + range_offsets[k] + 2 * (code - starts[k])
                    (glyph,) = struct.unpack_from(">H", data, addr)
                    if glyph:
                        glyph = (glyph + deltas[k]) & 0xFFFF
                if glyph:
                    cmap[code] = glyph
        return cmap

    def _read_name(self, name_id: int) -> str | None:
        if "name" not in self._tables:
            return None
        data, base = self._data, self._off("name")
        _, count, strings = struct.unpack_from(">HHH", data, base)
        for i in range(count):
            platform, encoding, _, nid, length, off = struct.unpack_from(">6H", data, base + 6 + 12 * i)
            if nid == name_id and platform == 3 and encoding in (1, 10):
                start = base + strings + off
                return data[start:start + length].decode("utf-16-be")
        return None

    def missing(self, text: str) -> list[str]:
        """Characters of ``text`` (NFC) without a glyph, in order of first appearance."""
        out = []
        for ch in nfc(text):
            if ord(ch) not in self._cmap and ch not in out:
                out.append(ch)
        return out

    def width_units(self, text: str) -> int:
        """Advance width of ``text`` (NFC) in font units (no kerning)."""
        total = 0
        for ch in nfc(text):
            glyph = self._cmap.get(ord(ch))
            if glyph is None:
                raise TextError(f"font {self.path.name} has no glyph for {ch!r} (U+{ord(ch):04X})")
            total += self._advances[min(glyph, self._num_hmetrics - 1)]
        return total

    def width(self, text: str, size: float) -> float:
        return self.width_units(text) * size / self.units_per_em


def check_glyphs(font: Font, texts: list[str]) -> None:
    missing: list[str] = []
    for t in texts:
        missing += [c for c in font.missing(t) if c not in missing]
    if missing:
        shown = ", ".join(f"{c!r} (U+{ord(c):04X})" for c in missing)
        raise TextError(f"font {font.path.name} has no glyph for {shown}; the font must cover all Vietnamese "
                        "characters (config render.font_file)")


def _limit_units(font: Font, size: int, max_width: float) -> float:
    return max_width * (1 - WIDTH_SAFETY) * font.units_per_em / size


def wrap_greedy(font: Font, text: str, size: int, max_width: float) -> list[str] | None:
    """Fill each line as far as possible (header, like the reference). None if a word does not fit."""
    limit = _limit_units(font, size, max_width)
    words = nfc(text).split()
    lines: list[str] = []
    for word in words:
        candidate = f"{lines[-1]} {word}" if lines else word
        if lines and font.width_units(candidate) <= limit:
            lines[-1] = candidate
        elif font.width_units(word) <= limit:
            lines.append(word)
        else:
            return None
    return lines


def wrap_balanced(font: Font, text: str, size: int, max_width: float,
                  max_lines: int = MAX_LINES) -> list[str] | None:
    """Fewest lines; then the shortest longest line; then the smallest sum of squared shortfall
    against the inner width (avoids a very short first line). None if no split into <= max_lines fits."""
    limit = _limit_units(font, size, max_width)
    words = nfc(text).split()
    n = len(words)
    if n == 0:
        return None
    for k in range(1, min(max_lines, n) + 1):
        best: tuple | None = None
        for cuts in itertools.combinations(range(1, n), k - 1):
            bounds = (0, *cuts, n)
            lines = [" ".join(words[bounds[i]:bounds[i + 1]]) for i in range(k)]
            widths = [font.width_units(line) for line in lines]
            longest = max(widths)
            if longest > limit:
                continue
            key = (longest, sum((limit - w) ** 2 for w in widths))
            if best is None or key < best[0]:
                best = (key, lines)
        if best is not None:
            return best[1]
    return None


@dataclass(frozen=True)
class TextFit:
    lines: list[str]
    font_size: int
    line_pitch: float  # px between baselines
    panel_height: int  # px


def block_height(n_lines: int, pitch: float, padding_y: float) -> float:
    """Height a text block of ``n_lines`` needs inside a panel (line boxes + vertical padding)."""
    return n_lines * pitch + 2 * padding_y


def min_size(size0: int, min_font_scale: float) -> int:
    return math.ceil(size0 * min_font_scale - 1e-9)


def fit_header(font: Font, lines: list[str], *, size0: int, line_spacing: float, inner_width: float,
               panel_height: int, padding_y: float, min_font_scale: float) -> TextFit:
    """Fixed panel; shrink the font 1 px at a time until the greedy-wrapped lines are <= 3 and fit."""
    check_glyphs(font, lines)
    for size in range(size0, min_size(size0, min_font_scale) - 1, -1):
        out: list[str] | None = []
        for line in lines:
            wrapped = wrap_greedy(font, line, size, inner_width)
            if wrapped is None:
                out = None
                break
            out += wrapped
        pitch = size * line_spacing
        if out and len(out) <= MAX_LINES and block_height(len(out), pitch, padding_y) <= panel_height:
            return TextFit(out, size, pitch, panel_height)
    raise TextError(f"header {' | '.join(lines)!r} does not fit its panel in {MAX_LINES} lines at "
                    f">= {min_font_scale:g} x font size {size0} px")


def fit_title(font: Font, title: str, *, size0: int, line_spacing: float, inner_width: float,
              panel_height: int, max_panel_height: int, padding_y: float, min_font_scale: float) -> TextFit:
    """P3: at the reference size the panel grows (up to ``max_panel_height``) for a 3rd line; only when
    that is not enough does the font shrink (panel = ``max_panel_height``)."""
    check_glyphs(font, [title])
    pitch = size0 * line_spacing
    lines = wrap_balanced(font, title, size0, inner_width)
    if lines is not None:
        need = block_height(len(lines), pitch, padding_y)
        if need <= max_panel_height:
            return TextFit(lines, size0, pitch, max(panel_height, math.ceil(need - 1e-9)))
    for size in range(size0 - 1, min_size(size0, min_font_scale) - 1, -1):
        pitch = size * line_spacing
        lines = wrap_balanced(font, title, size, inner_width)
        if lines is not None and block_height(len(lines), pitch, padding_y) <= max_panel_height:
            return TextFit(lines, size, pitch, max_panel_height)
    raise TextError(f"title {title!r} does not fit in {MAX_LINES} lines within a {max_panel_height} px panel at "
                    f">= {min_font_scale:g} x font size {size0} px")


def baselines(n_lines: int, *, font: Font, size: int, pitch: float, panel_height: int) -> list[int]:
    """Baseline y (px from the panel top) of each line: the cap-height block (cap top of the first line to
    the last baseline, OS/2 sCapHeight) is centred vertically in the panel, like the reference."""
    cap = size * font.cap_height / font.units_per_em
    first = (panel_height - (cap + (n_lines - 1) * pitch)) / 2 + cap
    return [round(first + i * pitch) for i in range(n_lines)]
