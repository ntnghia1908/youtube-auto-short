"""Audio-only remux cache. Stdlib only; subprocess and remote fetch can be injected."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from weakref import WeakValueDictionary

MAX_BYTES = 2 * 1024 ** 3


class WatchAudioError(Exception):
    """The requested audio could not be prepared; the player may use its video source."""


class AudioCache:
    def __init__(self, root: Path, *, run=None, max_bytes=MAX_BYTES):
        self.root = Path(root)
        self._run = run or subprocess.run
        self._max_bytes = max_bytes
        self._guard = threading.Lock()
        self._locks = WeakValueDictionary()

    def _prune(self, *, reserve=0, protect=None):
        """Caller holds _guard. Temporary downloads/remuxes live in separate subdirectories."""
        entries = [(p.stat().st_mtime_ns, p.stat().st_size, p) for p in self.root.glob("*.m4a")]
        total = sum(size for _, size, _ in entries)
        for _, size, path in sorted(entries):
            if total + reserve <= self._max_bytes:
                break
            if path != protect:
                path.unlink(missing_ok=True)
                total -= size

    def get(self, sha256: str, source: Path | None, *, fetch=None) -> Path:
        """Publish one complete m4a per manifest hash; fetch(dest) verifies a remote input if needed."""
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise WatchAudioError("Video chưa có sha256 hợp lệ để tạo tiếng")
        with self._guard:
            lock = self._locks.get(sha256)
            if lock is None:
                lock = threading.Lock()
                self._locks[sha256] = lock
        with lock:
            self.root.mkdir(parents=True, exist_ok=True)
            target = self.root / (sha256 + ".m4a")
            with self._guard:
                if target.is_file() and 0 < target.stat().st_size <= self._max_bytes:
                    self._prune(protect=target)
                    return target
            with tempfile.TemporaryDirectory(prefix=".watch-", dir=self.root) as folder:
                temp = Path(folder)
                if source is None:
                    if fetch is None:
                        raise WatchAudioError("Không có nguồn để tách tiếng")
                    source = temp / "source.mp4"
                    fetch(source)
                output = temp / "audio.m4a"
                try:
                    self._run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
                               "-map", "0:a:0", "-vn", "-c:a", "copy", "-movflags", "+faststart",
                               "-f", "mp4", str(output)], check=True, capture_output=True, timeout=120)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise WatchAudioError("Không tách được tiếng của video") from exc
                if not output.is_file() or not 0 < output.stat().st_size <= self._max_bytes:
                    raise WatchAudioError("File tiếng rỗng hoặc vượt giới hạn cache 2 GB")
                with self._guard:
                    self._prune(reserve=output.stat().st_size, protect=target)
                    os.replace(output, target)
            return target
