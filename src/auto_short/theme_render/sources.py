"""TC3.1: persistent originals and a sequential, resumable favorites prefetcher."""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import hashing
from ..compilation import store
from ..compilation.spec import CompilationError
from ..config import Config, ConfigError, load
from ..enhance.state import owner_id
from ..ingest import probe
from ..ingest.youtube import DownloadError, YoutubeBlocked, ytdlp_download
from ..render.stage import RenderError
from ..workspace import WorkspaceError, atomic_write_json, validate_episode_id


def cache_dir(config: Config) -> Path:
    return Path(config.workspace.dir) / "_theme_sources"


def _owner(video_id: str) -> str:
    return validate_episode_id(owner_id(validate_episode_id(video_id)))


def favorite_videos(config: Config) -> list[str]:
    """Sorted, distinct owners of both Short and khai thị favorites; no writes."""
    root = Path(config.render.output_dir) / store.NAMESPACE
    return sorted({_owner(item.episode_id) for path in root.glob(f"*/{store.FAVORITES_NAME}")
                   for item in store.read_favorites(path.parent)})


def _read(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("expected object")
        return doc
    except (OSError, ValueError) as exc:
        raise RenderError(f"không đọc được {path}: {exc}") from exc


def _source(config: Config, video_id: str) -> dict:
    source = _read(Path(config.workspace.dir) / _owner(video_id) / "manifest.json").get("source")
    if not isinstance(source, dict):
        raise RenderError("manifest không có nguồn ingest")
    return source


def _positive(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _duration(config: Config, video_id: str) -> float:
    value = _read(Path(config.workspace.dir) / _owner(video_id) / "metadata.json").get("duration")
    if not _positive(value):
        raise RenderError("metadata.json không có thời lượng nguồn hợp lệ")
    return float(value)


def _matches_duration(duration, expected: float) -> bool:
    return _positive(duration) and abs(duration - expected) <= max(2.0, expected * .01)


def workspace_source(config: Config, video_id: str) -> Path | None:
    """Only skip the original workspace file when its bytes match the ingest sha."""
    try:
        folder = (Path(config.workspace.dir) / _owner(video_id)).resolve()
        source = _source(config, video_id)
        path = (folder / source["path"]).resolve()
        if path.is_relative_to(folder) and path.is_file() and hashing.sha256_file(path) == source.get("sha256"):
            return path
    except (RenderError, OSError, KeyError, TypeError, ValueError):
        pass
    return None


def cached_source(config: Config, video_id: str) -> Path | None:
    """A committed cache entry with intact bytes and current ingest duration/provenance."""
    try:
        folder = (cache_dir(config) / _owner(video_id)).resolve()
        meta = _read(folder / "meta.json")
        source = _source(config, video_id)
        name = meta.get("file")
        if not isinstance(name, str) or not re.fullmatch(r"source\.[A-Za-z0-9]+", name):
            return None
        path = (folder / name).resolve()
        if meta.get("schema_version") != 1 or meta.get("video_id") != _owner(video_id) \
                or meta.get("uri") != source.get("uri") or not isinstance(meta.get("uri"), str) \
                or not meta["uri"] or not isinstance(meta.get("ingest_sha256"), str) \
                or not meta["ingest_sha256"] or meta["ingest_sha256"] != source.get("sha256") \
                or not isinstance(meta.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", meta["sha256"]) \
                or not isinstance(meta.get("differs_from_ingest"), bool) \
                or meta["differs_from_ingest"] != (meta["sha256"] != source.get("sha256")) \
                or not _positive(meta.get("height")) or not _positive(meta.get("size")) \
                or not _matches_duration(meta.get("duration"), _duration(config, video_id)):
            return None
        datetime.strptime(meta["downloaded_at"], "%Y-%m-%dT%H:%M:%SZ")
        if path.parent == folder and path.is_file() and path.stat().st_size == meta["size"] \
                and hashing.sha256_file(path) == meta["sha256"]:
            return path
    except (RenderError, OSError, KeyError, TypeError, ValueError):
        pass
    return None


def fetch_to_cache(config: Config, video_id: str, downloader=ytdlp_download, *, clock=time.time) -> Path:
    """Validate in a private temporary directory; publish metadata last. Never alter ingest."""
    video_id = _owner(video_id)
    if (cached := cached_source(config, video_id)) is not None:
        return cached
    source = _source(config, video_id)
    uri, ingest_sha = source.get("uri"), source.get("sha256")
    if not isinstance(uri, str) or not uri or not isinstance(ingest_sha, str) or not ingest_sha:
        raise RenderError("manifest không có URI / sha256 để tải lại video nguồn")
    expected = _duration(config, video_id)
    root = cache_dir(config)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix=f".{video_id}-") as tmp:
        dest = Path(tmp)
        try:
            got = downloader(uri, dest, config.ingest)
            path = Path(got.path).resolve()
            if not path.is_relative_to(dest.resolve()) or not path.is_file():
                raise RenderError("downloader không trả file trong thư mục tải tạm")
            if not re.fullmatch(r"\.[A-Za-z0-9]+", path.suffix):
                raise RenderError("đuôi file nguồn không hợp lệ")
            info = probe.probe(path)
            if not _matches_duration(info.get("duration"), expected):
                raise RenderError(f"video tải lại dài {info.get('duration')} s, bản gốc {expected} s; không dùng")
            if not _positive(info.get("height")) or path.stat().st_size <= 0:
                raise RenderError("video tải lại không có kích thước hợp lệ")
            sha = hashing.sha256_file(path)
            meta = {"schema_version": 1, "video_id": video_id, "file": f"source{path.suffix}", "uri": uri,
                    "downloaded_at": datetime.fromtimestamp(clock(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "size": path.stat().st_size, "sha256": sha, "duration": info["duration"], "height": info["height"],
                    "ingest_sha256": ingest_sha, "differs_from_ingest": sha != ingest_sha}
            atomic_write_json(dest / "meta.json", meta)
            folder = root / video_id
            folder.mkdir(exist_ok=True)
            final = folder / meta["file"]
            published = False
            try:
                os.replace(path, final)
                published = True
                os.replace(dest / "meta.json", folder / "meta.json")
            except BaseException:
                if published:
                    final.unlink(missing_ok=True)
                raise
            return final
        except YoutubeBlocked:
            raise
        except (DownloadError, probe.ProbeError) as exc:
            raise RenderError(f"tải lại video nguồn lỗi: {exc}") from exc


def run(config: Config, *, downloader=ytdlp_download, sleep=time.sleep, rng=random, clock=time.time, log=print,
        dry_run=False, min_gap=600, max_gap=1200, blocked_wait=3600, max_blocked_wait=21600) -> dict:
    for value in (min_gap, max_gap, blocked_wait, max_blocked_wait):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("thời gian chờ phải hữu hạn và không âm")
    if min_gap > max_gap or blocked_wait <= 0 or blocked_wait > max_blocked_wait:
        raise ValueError("cần min-gap ≤ max-gap và 0 < blocked-wait ≤ max-blocked-wait")
    stats = dict(total=0, skipped=0, downloaded=0, failed=0, pending=0, interrupted=False)

    def emit(message):
        stamp = datetime.fromtimestamp(clock(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log(f"{stamp} {message}")

    attempted = False
    try:
        videos = favorite_videos(config)
        stats["total"] = len(videos)
        for video_id in videos:
            state = "workspace" if workspace_source(config, video_id) else \
                    "cache" if cached_source(config, video_id) else "pending"
            emit(f"{video_id}: {state}")
            if state != "pending":
                stats["skipped"] += 1
                continue
            if dry_run:
                stats["pending"] += 1
                continue
            if not shutil.which("node"):
                raise RenderError("không tìm thấy node trên PATH; nạp nvm (source ~/.nvm/nvm.sh) hoặc cài Node.js")
            if attempted:
                gap = rng.uniform(min_gap, max_gap)
                emit(f"nghỉ {gap:.1f} s trước lần tải tiếp")
                sleep(gap)
            attempted = True
            wait = blocked_wait
            while True:
                try:
                    emit(f"{video_id}: tải nguồn")
                    path = fetch_to_cache(config, video_id, downloader, clock=clock)
                    stats["downloaded"] += 1
                    emit(f"{video_id}: đã lưu {path}")
                    break
                except YoutubeBlocked as exc:
                    emit(f"{video_id}: YouTube chặn ({exc}); chờ {wait:.1f} s rồi thử lại")
                    sleep(wait)
                    wait = min(wait * 2, max_blocked_wait)
                except Exception as exc:
                    stats["failed"] += 1
                    emit(f"{video_id}: lỗi {exc}")
                    break
    except KeyboardInterrupt:
        stats["interrupted"] = True
        emit("đã dừng an toàn; chạy lại để tiếp tục")
    finally:
        emit(f"tổng kết: {stats}")
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-gap", type=float, default=600)
    parser.add_argument("--max-gap", type=float, default=1200)
    parser.add_argument("--blocked-wait", type=float, default=3600)
    parser.add_argument("--max-blocked-wait", type=float, default=21600)
    args = parser.parse_args(argv)
    try:
        config = load(args.config)
        stats = run(config, **{k: v for k, v in vars(args).items() if k != "config"},
                    log=lambda message: print(message, flush=True))
        return 130 if stats["interrupted"] else 1 if stats["failed"] else 0
    except (ConfigError, CompilationError, WorkspaceError, RenderError, OSError, ValueError) as exc:
        print(f"lỗi: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
