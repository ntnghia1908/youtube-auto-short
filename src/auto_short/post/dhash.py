"""CP8.30 S3: perceptual hash (dHash, 64 bit) of an image, no dependency: ffmpeg decodes to a 64x64 gray thumbnail,
the rest is plain Python. A uniform border (padding / letterbox) is trimmed first, so the same picture at another size
or on a padded background gets the same hash; Hamming distance <= :data:`NEAR_DUPLICATE_BITS` = "near duplicate".

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P5c.
"""

from __future__ import annotations

import subprocess

GRID = 64
NEAR_DUPLICATE_BITS = 8  # measured on the real library, see docs/tasks/CP8.30-image-search.md Result
_BORDER_FLAT = 14  # a border row / column is "uniform" when its gray range is at most this (of 255)
_MIN_CORE = 16


def decode_gray(data: bytes, size: int = GRID, *, timeout: float = 30.0) -> list[list[int]] | None:
    """``size`` x ``size`` gray pixels (aspect ratio ignored) of a JPEG/PNG, or None when ffmpeg cannot decode it."""
    cmd = ["ffmpeg", "-v", "error", "-i", "pipe:0", "-frames:v", "1", "-vf", f"scale={size}:{size}:flags=area,format=gray",
           "-f", "rawvideo", "pipe:1"]
    try:
        proc = subprocess.run(cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or len(proc.stdout) != size * size:
        return None
    raw = proc.stdout
    return [list(raw[r * size:(r + 1) * size]) for r in range(size)]


def _flat(values: list[int]) -> bool:
    return max(values) - min(values) <= _BORDER_FLAT


def trim_border(grid: list[list[int]]) -> list[list[int]]:
    top, bottom, left, right = 0, len(grid), 0, len(grid[0])
    changed = True
    while changed:
        changed = False
        if bottom - top > _MIN_CORE and _flat(grid[top][left:right]):
            top += 1
            changed = True
        if bottom - top > _MIN_CORE and _flat(grid[bottom - 1][left:right]):
            bottom -= 1
            changed = True
        if right - left > _MIN_CORE and _flat([grid[r][left] for r in range(top, bottom)]):
            left += 1
            changed = True
        if right - left > _MIN_CORE and _flat([grid[r][right - 1] for r in range(top, bottom)]):
            right -= 1
            changed = True
    return [row[left:right] for row in grid[top:bottom]]


def _resample(grid: list[list[int]], rows: int, cols: int) -> list[list[float]]:
    h, w = len(grid), len(grid[0])
    out = []
    for i in range(rows):
        r0, r1 = i * h // rows, max(i * h // rows + 1, (i + 1) * h // rows)
        line = []
        for j in range(cols):
            c0, c1 = j * w // cols, max(j * w // cols + 1, (j + 1) * w // cols)
            cells = [grid[r][c] for r in range(r0, r1) for c in range(c0, c1)]
            line.append(sum(cells) / len(cells))
        out.append(line)
    return out


def dhash_from_grid(grid: list[list[int]]) -> int:
    small = _resample(trim_border(grid), 8, 9)
    bits = 0
    for row in small:
        for j in range(8):
            bits = (bits << 1) | (1 if row[j] > row[j + 1] else 0)
    return bits


def dhash(data: bytes) -> int | None:
    """64-bit dHash of a JPEG/PNG; None when the image cannot be decoded."""
    grid = decode_gray(data)
    return None if grid is None else dhash_from_grid(grid)


def distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def thumbnail(data: bytes, width: int = 320, *, timeout: float = 30.0) -> bytes | None:
    """A small JPEG preview (``width`` px wide) of the image, or None when ffmpeg cannot decode it."""
    cmd = ["ffmpeg", "-v", "error", "-i", "pipe:0", "-frames:v", "1", "-vf", f"scale='min({width},iw)':-2",
           "-q:v", "5", "-f", "mjpeg", "pipe:1"]
    try:
        proc = subprocess.run(cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 and proc.stdout else None
