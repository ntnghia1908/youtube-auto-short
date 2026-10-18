"""TC3 speech-equivalence gate, using only the standard library.

Both encoded clips are decoded through the injected runner, so tests never need a
second subprocess boundary. PCM stays on disk; only the 20 ms RMS envelope is kept.
"""
from __future__ import annotations

import math
import sys
import wave
from array import array
from pathlib import Path

from ..render.stage import RenderError, Runner, _last_line

SAMPLE_RATE = 16000
WINDOW_SECONDS = 0.02
SEARCH_SECONDS = 0.5
MAX_LAG = 0.04
MIN_CORRELATION = 0.9
MAX_DURATION_DIFF = 0.1


def envelope(path: Path, pcm: Path, runner: Runner) -> tuple[list[float], float]:
    proc = runner(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(path),
                   "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
                   "-c:a", "pcm_s16le", "-f", "wav", str(pcm)])
    if proc.returncode != 0 or not pcm.is_file():
        raise RenderError(f"không giải mã được audio {path.name}: {_last_line(proc.stderr)}")
    try:
        with wave.open(str(pcm), "rb") as stream:
            duration = stream.getnframes() / SAMPLE_RATE
            values = []
            window = round(SAMPLE_RATE * WINDOW_SECONDS)
            while raw := stream.readframes(window):
                samples = array("h", raw)
                if sys.byteorder != "little":
                    samples.byteswap()
                if len(samples) == window:
                    values.append(math.sqrt(sum(x * x for x in samples) / window))
    except (OSError, wave.Error, EOFError) as exc:
        raise RenderError(f"audio PCM không hợp lệ: {exc}") from exc
    finally:
        pcm.unlink(missing_ok=True)
    return values, duration


def _correlation(a: list[float], b: list[float]) -> float:
    if len(a) < 3:
        return 0.0
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 1e-12 or vb <= 1e-12:
        return 0.0  # silence / constant envelopes cannot establish equivalence
    return max(-1.0, min(1.0, sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)))


def compare(new: Path, reference: Path, tmp: Path, runner: Runner) -> dict:
    a, da = envelope(new, tmp / "new.wav", runner)
    b, db = envelope(reference, tmp / "reference.wav", runner)
    best_corr, best_shift = -1.0, 0
    radius = round(SEARCH_SECONDS / WINDOW_SECONDS)
    for shift in range(-radius, radius + 1):
        start_a, start_b = max(0, shift), max(0, -shift)
        count = min(len(a) - start_a, len(b) - start_b)
        if count < max(3, min(len(a), len(b)) // 2):
            continue
        corr = _correlation(a[start_a:start_a + count], b[start_b:start_b + count])
        if corr > best_corr or (corr == best_corr and abs(shift) < abs(best_shift)):
            best_corr, best_shift = corr, shift
    lag, diff = best_shift * WINDOW_SECONDS, abs(da - db)
    facts = {"corr": best_corr, "lag": lag, "duration_diff": diff}
    problems = []
    if abs(lag) > MAX_LAG + 1e-9:
        problems.append(f"lệch audio {lag:+.3f} s > {MAX_LAG:.2f} s")
    if best_corr < MIN_CORRELATION:
        problems.append(f"tương quan audio {best_corr:.3f} < {MIN_CORRELATION}")
    if diff > MAX_DURATION_DIFF + 1e-9:
        problems.append(f"chênh thời lượng audio {diff:.3f} s > {MAX_DURATION_DIFF}")
    if problems:
        raise RenderError("không xác minh được phần lời: " + "; ".join(problems))
    return facts
