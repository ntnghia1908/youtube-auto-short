"""CP8.33 G3, G4: join rendered khai thị clips into one vertical mp4.

Normal path: ffmpeg concat demuxer with ``-c copy`` (fast, lossless). Inputs that differ in codec / size / fps /
sample rate / channels (or a copy that fails) are first re-encoded once with the CP7 encode parameters, then joined by
stream copy. The result is written in a private temp directory next to ``out`` and renamed into place; the temp
directory is removed on any outcome.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..render.plan import ACODEC, CHANNELS, PIX_FMT, SAMPLE_RATE, VCODEC
from .probe import MediaInfo, Runner, compatible, last_line, probe, run
from .spec import CompilationError

DURATION_FLOOR = 0.9  # the result must be at least this share of the summed input lengths (catches a broken join)


@dataclass(frozen=True)
class Encode:
    """CP7 encode parameters (``[render] crf / preset / audio_bitrate / threads``) used by the re-encode branch."""

    crf: int = 22
    preset: str = "medium"
    audio_bitrate: str = "192k"
    threads: int = 0


@dataclass(frozen=True)
class Assembled:
    duration: float  # of the written file (ffprobe)
    parts: tuple[float, ...]  # length of each input, in playback order (chapters)
    reencoded: bool
    size: int


def list_line(path: Path) -> str:
    """One ``file '<abs path>'`` line of the concat list; ``'`` is written ``'\\''``."""
    text = str(path)
    if "\n" in text or "\r" in text:
        raise CompilationError("đường dẫn file có ký tự xuống dòng")
    return "file '" + text.replace("'", "'\\''") + "'\n"


def _ffmpeg(cmd: list[str], runner: Runner, what: str) -> None:
    proc = runner(cmd)
    if proc.returncode != 0:
        raise CompilationError(f"ffmpeg {what} lỗi: {last_line(proc.stderr) or f'exit {proc.returncode}'}")


def concat_command(listing: Path, output: Path) -> list[str]:
    return ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart", "-f", "mp4",
            str(output)]


def normalize_command(src: Path, dst: Path, ref: MediaInfo, enc: Encode) -> list[str]:
    """Re-encode one input to the size / fps of the first input and the CP7 codec parameters."""
    w, h = (ref.width or 0) // 2 * 2, (ref.height or 0) // 2 * 2
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
          f"fps={ref.fps}")
    return ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(src), "-vf", vf,
            "-c:v", VCODEC, "-preset", enc.preset, "-crf", str(enc.crf), "-pix_fmt", PIX_FMT,
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
            "-threads", str(enc.threads), "-c:a", ACODEC, "-b:a", enc.audio_bitrate, "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS), "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart",
            "-f", "mp4", str(dst)]


def _join(paths: list[Path], tmp: Path, runner: Runner) -> Path:
    listing, out = tmp / "list.txt", tmp / "joined.mp4"
    listing.write_text("".join(list_line(p) for p in paths), encoding="utf-8")
    _ffmpeg(concat_command(listing, out), runner, "ghép")
    return out


def _infos(paths: list[Path], runner: Runner) -> dict[Path, MediaInfo]:
    infos: dict[Path, MediaInfo] = {}
    for p in paths:
        if p not in infos:
            infos[p] = probe(p, runner)
            if not infos[p].complete:
                raise CompilationError(f"{p.name}: thiếu luồng video / audio hoặc không có thời lượng")
    return infos


def _reencode(paths: list[Path], infos: dict[Path, MediaInfo], tmp: Path, enc: Encode,
              runner: Runner) -> tuple[list[Path], dict[Path, MediaInfo]]:
    ref = infos[paths[0]]
    mapping: dict[Path, Path] = {}
    for n, p in enumerate(dict.fromkeys(paths)):
        dst = tmp / f"n{n:04d}.mp4"
        _ffmpeg(normalize_command(p, dst, ref, enc), runner, f"encode lại {p.name}")
        mapping[p] = dst
    out = [mapping[p] for p in paths]
    return out, _infos(out, runner)


def assemble(paths: list[Path], out: Path, enc: Encode = Encode(), *, runner: Runner = run) -> Assembled:
    """Write ``out`` (``.mp4``) from ``paths`` in order (a path may repeat). Raises :class:`CompilationError`."""
    if not paths:
        raise CompilationError("không có đoạn nào để ghép")
    for p in paths:
        if not Path(p).is_file():
            raise CompilationError(f"không tìm thấy file {Path(p).name}")
    out.parent.mkdir(parents=True, exist_ok=True)
    for stale in out.parent.glob(f".{out.stem}.*"):  # left by a crashed run of this very compilation
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        else:
            stale.unlink(missing_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=out.parent, prefix=f".{out.stem}."))
    try:
        paths = [Path(p).resolve() for p in paths]
        infos = _infos(paths, runner)
        reencoded = not compatible(list(infos.values()))
        sources = paths
        if reencoded:
            sources, infos = _reencode(paths, infos, tmp, enc, runner)
        try:
            joined = _join(sources, tmp, runner)
        except CompilationError:
            if reencoded:
                raise
            reencoded = True  # G3: a copy that fails is retried once, re-encoded
            for leftover in (tmp / "joined.mp4", tmp / "list.txt"):
                leftover.unlink(missing_ok=True)
            sources, infos = _reencode(paths, infos, tmp, enc, runner)
            joined = _join(sources, tmp, runner)
        parts = tuple(infos[p].duration for p in sources)
        result = probe(joined, runner)
        if not result.complete or result.duration < DURATION_FLOOR * sum(parts):
            raise CompilationError(f"video ghép không hợp lệ ({result.duration:.1f} s, mong đợi {sum(parts):.1f} s)")
        os.replace(joined, out)
        return Assembled(duration=result.duration, parts=parts, reencoded=reencoded, size=out.stat().st_size)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
