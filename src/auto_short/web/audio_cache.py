"""Bounded, versioned audio-only copies for the listening player."""

from __future__ import annotations

import hashlib
import tempfile
import threading
from pathlib import Path

from ..config import Config
from ..render.stage import RenderError, _run
from ..store.client import StoreClient, StoreMismatch
from .episodes import StoredShort

MAX_BYTES = 2 * 1024**3
AUDIO_PAD = 1.5
# Fixed stripes bound lock memory while serializing extraction of the same cache key.
_locks = [threading.Lock() for _ in range(64)]
_prune_lock = threading.Lock()


def _prune(root: Path, keep: Path) -> None:
    files = [(p, p.stat()) for p in root.glob("*.m4a")]
    total = sum(st.st_size for _, st in files)
    for path, stat in sorted(files, key=lambda item: item[1].st_mtime_ns):
        if total <= MAX_BYTES:
            break
        if path != keep:
            path.unlink(missing_ok=True)
            total -= stat.st_size


def cached_audio(config: Config, episode_id: str, clip_id: str, source: Path | StoredShort) -> Path:
    """Encode AAC with leading silence; only complete files become visible to FileResponse."""
    if isinstance(source, StoredShort):
        version = f"{source.sha256}:{source.size}"
    else:
        stat = source.stat()
        version = f"{source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"
    key = hashlib.sha256(f"{episode_id}:{clip_id}:{version}:aac128-pad{AUDIO_PAD}".encode()).hexdigest()
    root = Path(config.workspace.dir) / "_audio_cache"
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{episode_id}.{clip_id}.{key}.m4a"
    with _locks[int(key[:8], 16) % len(_locks)]:
        if target.is_file():
            return target
        with tempfile.TemporaryDirectory(prefix=".extract-", dir=root) as tmp:
            tmp = Path(tmp)
            media = source
            if isinstance(source, StoredShort):
                media = tmp / "source.mp4"
                client = StoreClient.from_config(config.store)
                _status, _headers, stream = client.open_stream(source.episode_id, "short", clip=source.clip)
                digest, size = hashlib.sha256(), 0
                try:
                    with media.open("wb") as dst:
                        for chunk in stream:
                            size += len(chunk)
                            if size > source.size:
                                raise StoreMismatch("Short trên kho thừa byte")
                            digest.update(chunk)
                            dst.write(chunk)
                    if size != source.size or digest.hexdigest() != source.sha256:
                        raise StoreMismatch("Short trên kho thiếu byte / khác sha256")
                finally:
                    stream.close()
            audio = tmp / "audio.m4a"
            proc = _run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(media),
                         "-map", "0:a:0", "-vn", "-af", f"adelay={round(AUDIO_PAD * 1000)}:all=1",
                         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(audio)])
            if proc.returncode or not audio.is_file() or not 0 < audio.stat().st_size <= MAX_BYTES:
                raise RenderError("không tách được audio của Short")
            with _prune_lock:
                audio.replace(target)
                _prune(root, target)
        return target
