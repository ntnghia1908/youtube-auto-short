"""SRC2: slowly back up archived originals and unprocessed playlist videos."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from ..config import Config, ConfigError, load
from ..enhance.state import owner_for
from ..ingest.youtube import DownloadError, YoutubeBlocked, is_blocked_message, ytdlp_download
from ..review.archive import is_archived
from ..theme_render.sources import _owner, _positive, cache_dir, cached_source, download_verified, favorite_videos
from ..workspace import WorkspaceError, atomic_write_json, iter_manifests, read_json_dict
from ..youtube_url import canonical_url
from .backup import _destination, _local_source, _matches, _source
from . import index_cache
from .client import StoreClient, StoreError, StoreMismatch, StoreUnavailable

MIN_FREE_BYTES = 20 * 10**9


def unprocessed_entries(config: Config) -> dict[str, dict]:
    """Available playlist references with neither a Short nor khai thị workspace; never create either."""
    root = Path(config.workspace.dir)
    found = {}
    for path in sorted((root / "_playlists").glob("*.json")):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", path.stem):
            continue
        entries = (read_json_dict(path) or {}).get("entries") or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("available") is False:
                continue
            vid = entry.get("video_id")
            if not isinstance(vid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) \
                    or (root / owner_for(config, vid)).is_dir():
                continue
            found.setdefault(vid, {**entry, "uri": canonical_url(vid), "playlist_id": path.stem})
    return found


def local_groups(config: Config, *, entries: dict | None = None) -> dict[str, list[str]]:
    """Local inventory only: archived first, then unprocessed playlists. No writes or store access."""
    archived = {_owner(ws.episode_id) for ws, manifest in iter_manifests(Path(config.workspace.dir))
                if (manifest.get("source") or {}).get("kind") == "youtube" and is_archived(ws.dir)}
    favorites = set(favorite_videos(config))
    entries = unprocessed_entries(config) if entries is None else entries

    def order(vid):
        series, name = _destination(config, vid)
        number = re.search(r" - Tập (\d+)\.mp4$", name)
        return (series, int(number[1]) if number else float("inf"), vid)

    return {
        "archived": sorted((vid for vid in archived if _local_source(config, vid) is None),
                           key=lambda vid: (vid not in favorites, *order(vid))),
        "unprocessed": sorted((vid for vid, ref in entries.items()
                               if cached_source(config, vid, reference=ref) is None), key=order),
    }


def local_pending(config: Config) -> list[str]:
    return [vid for videos in local_groups(config).values() for vid in videos]


def pending(config: Config, *, client=None, groups: dict | None = None) -> list[str]:
    """One index request per inventory; optionally return each group's pending IDs for background counters."""
    if not config.store.enabled:
        raise StoreUnavailable("kho 3090 đang tắt")
    inventory = local_groups(config)
    client = client or StoreClient.from_config(config.store)
    remote = {row.get("video_id") for row in client.index() if row.get("kind") == "source"}
    filtered = {group: [vid for vid in videos if vid not in remote] for group, videos in inventory.items()}
    if groups is not None:
        groups.update(filtered)
    return [vid for videos in filtered.values() for vid in videos]


def free_bytes(config: Config, disk_usage=shutil.disk_usage) -> int:
    """Measure the filesystem holding work/, even before the workspace exists."""
    folder = Path(config.workspace.dir).absolute()
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    return disk_usage(folder)[2]


def _publish_cache(config: Config, video_id: str, path: Path, meta: dict) -> Path:
    """Publish the complete directory together; roll back an invalid older cache if rename fails."""
    final = cache_dir(config) / video_id
    with tempfile.TemporaryDirectory(dir=final.parent, prefix=f".{video_id}-publish-") as staging, \
            tempfile.TemporaryDirectory(dir=final.parent, prefix=f".{video_id}-old-") as retired:
        ready = Path(staging)
        os.replace(path, ready / meta["file"])
        atomic_write_json(ready / "meta.json", meta)
        old = Path(retired) / "cache"
        if final.exists():
            os.replace(final, old)
        try:
            os.replace(ready, final)
        except BaseException:
            if old.exists():
                os.replace(old, final)
            raise
    return final / meta["file"]


def step(config: Config, video_id: str, *, downloader=ytdlp_download, client=None, clock=time.time,
         disk_usage=shutil.disk_usage) -> dict:
    """Download one verified file, PUT those exact bytes, HEAD them, then retain only favorites."""
    video_id = _owner(video_id)
    result = {"video_id": video_id, "status": "paused"}
    try:
        if not config.store.enabled:
            return {**result, "reason": "kho 3090 đang tắt"}
        if free_bytes(config, disk_usage) < MIN_FREE_BYTES:
            return {**result, "reason": "work/ còn dưới 20 GB trống"}
        reference = None
        if (Path(config.workspace.dir) / owner_for(config, video_id)).is_dir():
            if _source(config, video_id).get("kind") != "youtube":
                raise StoreMismatch("nguồn không phải YouTube")
        else:
            reference = unprocessed_entries(config).get(video_id)
            if reference is None:
                raise StoreMismatch("video chưa xử lý không có playlist entry khả dụng")
        client = client or StoreClient.from_config(config.store)
        # Ensure the store answers before spending a YouTube download.
        client.index()
        root = cache_dir(config)
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root, prefix=f".{video_id}-redownload-") as tmp:
            dest = Path(tmp)
            path, meta = download_verified(config, video_id, dest, downloader, clock=clock, reference=reference)
            series, name = _destination(config, video_id)
            client.put(video_id, "source", series, name, path, meta["sha256"])
            if not _matches(client.head(video_id, "source"), meta["sha256"], meta["size"]):
                raise StoreMismatch("kho chưa xác nhận đúng sha256 / kích thước sau khi gửi")
            index_cache.invalidate()
            cached = reference is None and video_id in favorite_videos(config)
            if cached:
                _publish_cache(config, video_id, path, meta)
            return {**result, "status": "done", "cached": cached, "sha256": meta["sha256"],
                    "size": meta["size"], **({"differs_from_ingest": meta["differs_from_ingest"]}
                                           if "differs_from_ingest" in meta else {})}
    except YoutubeBlocked as exc:
        return {**result, "status": "blocked", "reason": str(exc)}
    except DownloadError as exc:
        # SRC2 alone treats signed-media HTTP 403 as temporary blocking.
        blocked = is_blocked_message(str(exc)) or bool(re.search(r"\b(?:HTTP(?: Error)?\s*:?\s*)403\b", str(exc), re.I))
        return {**result, "status": "blocked" if blocked else "failed", "reason": str(exc)}
    except StoreUnavailable as exc:
        return {**result, "status": "store_unavailable", "reason": str(exc)}
    except Exception as exc:
        return {**result, "status": "failed", "reason": str(exc)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", required=True,
                        help="chỉ kiểm kê cục bộ; vòng tải thực chạy trong web")
    args = parser.parse_args(argv)
    try:
        config = load(args.config)
        entries = unprocessed_entries(config)
        groups = local_groups(config, entries=entries)
        videos = [vid for group in groups.values() for vid in group]
        favorites = set(favorite_videos(config))
        print("Kiểm kê cục bộ — chưa đối chiếu kho 3090 (không mạng, không ghi file).")
        sizes, total_duration = [], 0.0
        for group, label in (("archived", "Đã dọn"), ("unprocessed", "Chưa xử lý")):
            durations = []
            for vid in groups[group]:
                ref = entries.get(vid) if group == "unprocessed" else read_json_dict(
                    Path(config.workspace.dir) / owner_for(config, vid) / "metadata.json")
                duration = (ref or {}).get("duration")
                if _positive(duration):
                    durations.append(duration)
            hours = sum(durations) / 3600
            total_duration += sum(durations)
            print(f"{label}: {len(groups[group])} video, {hours:.2f} giờ ({len(durations)} có duration)")
            for vid in groups[group]:
                size = _source(config, vid).get("size") if group == "archived" else None
                if isinstance(size, int) and not isinstance(size, bool) and size > 0:
                    sizes.append(size)
                print(f"{'♥ ' if vid in favorites and group == 'archived' else '  '}{vid}")
        estimate = f"{sum(sizes) / 10**9:.2f} GB ước tính ({len(sizes)}/{len(videos)} có size)" if sizes else "chưa có size"
        hearts = len(set(groups["archived"]) & favorites)
        print(f"Tổng: {len(videos)} video, {hearts} ♥; {total_duration / 3600:.2f} giờ; {estimate}")
        return 0
    except (ConfigError, WorkspaceError, StoreError, OSError, ValueError) as exc:
        print(f"lỗi: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
