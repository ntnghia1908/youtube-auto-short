"""Shared state and helpers for the web route factories; no web framework imports."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import khaithi
from ..config import Config
from ..enhance import state as enh_state
from ..enhance.service import EnhanceService
from ..enhance.state import EnhanceError
from ..post import images as post_images
from ..post import logic as post_logic
from ..post import source as post_source
from ..post import stage as post_stage
from ..post import store as post_store
from ..post import validate as post_validate
from ..review import ArchivedError, ReviewError, is_archived, mark_downloaded, list_titles
from ..review.names import hashtags as review_hashtags
from ..review.names import posts_docx_name
from ..titling.playlist import stored_series as playlist_series
from ..workspace import WorkspaceError, validate_episode_id
from . import compilations as comp_web
from . import downloads as dl_mod
from . import episodes as ep
from . import monitor as monitor_mod
from .auth import SessionSigner
from .auto_vertical import AutoVertical
from .jobs import KIND_PIPELINE, JobRunner, pipeline_target, vertical_target
from .playlists import PlaylistError, PlaylistStore
from .storage import BLOCK_MESSAGE, StorageCache
from .urls import canonical_url, valid_playlist_id

log = logging.getLogger("auto_short")

SOURCE_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
                ".mov": "video/quicktime"}
KIND_RESTORE_SOURCE = "restore_source"  # Uses the owner's episode key and a single prepare step; no jobs.py change.
KINDS = ("short", "khaithi")  # CP8.9 A1.1, in job order
RANGE_SIZE = 10  # CP8.31 A1: episodes per posts file


@dataclass
class WebContext:
    """State needed by the route factories and their shared helpers."""

    config: Config
    runner: JobRunner
    tokens: dict[str, str]
    storage: StorageCache
    playlists: PlaylistStore
    publish_lock: Any
    post_lock: Any
    signer: SessionSigner
    svc: EnhanceService
    sampler: monitor_mod.Sampler
    ollama_view: monitor_mod.OllamaView
    compilations: comp_web.Compilations
    download_table: dl_mod.DownloadTable
    static_dir: Path
    submit_lock: Any
    auto_vertical: AutoVertical
    pipeline: Callable
    preflight: Callable | None
    vertical: Callable | None
    vertical_downloader: Callable | None
    post_compose: Callable | None
    post_preflight: Callable | None
    post_search: Callable | None
    keyword_search: Callable | None
    doc_prepare: Callable | None

    def tracked(self, dl: str | None, response: Any) -> Any:
        """CP8.34: a download with a valid ``?dl=<token>`` reports its progress to the table; without one (or with a
        malformed token) the response is returned untouched. An error response ends the token as ``aborted``."""
        if dl is None or not dl_mod.TOKEN_RE.match(dl):
            return response
        if response.status_code >= 400:
            self.download_table.fail(dl)
            return response
        return dl_mod.TrackedResponse(response, self.download_table, dl)

    def playlist_or_404(self, playlist_id: str):
        if not valid_playlist_id(playlist_id):
            return None
        try:
            return self.playlists.load(playlist_id)
        except PlaylistError:
            return None

    def playlist_docx_series(self, doc: dict) -> str | None:
        """CP8.31 P16: stored bộ kinh series, else the ``series`` of the first episode (by episode number) whose
        titles.json has one; None -> the file name falls back to the playlist id."""
        stored = playlist_series(doc)
        if stored:
            return stored
        for e in self.by_episode_order([e for e in doc["entries"] if e.get("video_id") and e.get("available")]):
            for eid in (e["video_id"], e["video_id"] + khaithi.SUFFIX):
                series = (self.post_header_fields(eid) or {}).get("series")
                if isinstance(series, str) and series.strip():
                    return series
        return None

    def post_stats(self, episode_id: str) -> tuple[int, int, int]:
        """Cheap numbers for the playlist page (one ``posts.json`` read): ``(posts, posted, rendered)`` = stored posts
        whose Short is still rendered, how many of them are ticked "Đã đăng bài", rendered Shorts (CP8.31 A2)."""
        order = [cid for cid, _ in post_stage.rendered_clip_ids(self.config, episode_id)]
        if not order or not self.posts_path(episode_id).is_file():
            return 0, 0, len(order)
        with self.post_lock:
            try:
                entries = post_store.read_posts(self.posts_path(episode_id), episode_id)["posts"]
            except post_store.PostsError:
                return 0, 0, len(order)
        live = [e for e in entries if e["clip_id"] in set(order)]
        return len(live), sum(1 for e in live if e["posted_at"] is not None), len(order)

    def by_episode_order(self, entries: list[dict]) -> list[dict]:
        """H2: episode number order (the numbered first), then playlist order."""
        return comp_web.by_episode_order(entries)

    def posts_path(self, episode_id: str) -> Path:
        return Path(self.config.workspace.dir) / episode_id / post_store.POSTS_NAME

    def post_header_fields(self, episode_id: str) -> dict | None:
        try:
            doc = json.loads((Path(self.config.workspace.dir) / episode_id / "titles.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        fields = (doc.get("header") or {}).get("fields")
        return fields if isinstance(fields, dict) else None

    def post_series_and_tags(self, episode_id: str) -> tuple[str | None, tuple[str, ...]]:
        """Like ``episode_view``'s per-Short hashtags (CP8.7/CP8.8): custom bộ kinh hashtags, else ``#<series>`` +
        ``[web] hashtags``."""
        kf = ep.kind_fields(self.config, episode_id)
        custom = self.playlists.hashtags_for(kf["base_episode_id"] or episode_id)
        if custom is not None:
            return None, tuple(custom)
        fields = self.post_header_fields(episode_id)
        return (fields.get("series") if fields else None), tuple(self.config.web.hashtags)

    def post_entry_view(self, entry: dict, *, ep_src, title: str | None, header_fields: dict | None,
                         hashtags_list: list[str]) -> dict:
        stale = post_stage.compute_stale(ep_src, entry) if ep_src is not None else True
        image = entry["image"]
        image_missing = image is not None and post_images.resolve(self.config.post.image_dir, image) is None
        text = post_logic.compose_copy_text(title=title, paragraphs=entry["paragraphs"], header_fields=header_fields,
                                            link=entry["link"], hashtags=hashtags_list)
        # P3 amendment: "ít dấu câu" label (Q4) — an "ai" post whose punctuation is too sparse to be useful,
        # even though the projection matched the source words well enough to not fall back to "raw".
        low_punctuation = entry["origin"] == post_store.AI \
            and post_validate.marks_per_100_words(entry["paragraphs"]) < 4
        return {"clip_id": entry["clip_id"], "paragraphs": list(entry["paragraphs"]), "origin": entry["origin"],
                "stale": stale, "image": image, "image_missing": image_missing, "link": entry["link"],
                "posted": entry["posted_at"] is not None, "posted_at": entry["posted_at"], "text": text,
                "chars": len(text), "low_punctuation": low_punctuation}

    def mark_downloaded(self, episode_id: str, clip_ids: list[str]) -> None:
        """CP8.7 (bổ sung HUMAN LEAD 2026-09-27): a download ticks "Đã đăng" (current file); never blocks it."""
        with self.publish_lock:
            try:
                changed = mark_downloaded(episode_id, self.config, clip_ids)
            except (ReviewError, OSError) as exc:
                log.warning("web: download of %s [%s]: not marked as published: %s", ",".join(clip_ids),
                            episode_id, exc)
                return
        if changed:
            self.playlists.invalidate(episode_id)
            self.storage.invalidate()
            log.info("web: download marked %s [%s] as published", ",".join(changed), episode_id)

    def export_items(self, episode_id: str, views: bool = False) -> list[dict]:
        """Posts of one episode that still have a rendered Short, in render-manifest order; [] when none. Each item:
        ``clip_id, head (title upper-case), paras, source, image`` and, with ``views`` (SR2 K2), ``episode_id, code,
        copy_text, posted, stale`` (the fields of the Posts tab). ``name`` is only for the caller's group label."""
        order = [cid for cid, _ in post_stage.rendered_clip_ids(self.config, episode_id)]
        if not order or not (Path(self.config.workspace.dir) / episode_id).is_dir():
            return []
        with self.post_lock:
            try:
                doc = post_store.read_posts(self.posts_path(episode_id), episode_id)
            except post_store.PostsError:
                return []
        titles_by_clip: dict[str, str | None] = {}
        tab_titles = True  # the Posts tab (api_posts) only knows the titling titles, not the rendered-file fallback
        try:
            titles_by_clip = {c["clip_id"]: c["title"] for c in list_titles(episode_id, self.config)["clips"]}
        except ReviewError:  # titling not readable: the title burnt into the rendered file
            tab_titles = False
            rendered = ep.render_manifest(self.config, episode_id) or {}
            titles_by_clip = {sh.get("clip_id"): sh.get("title") for sh in rendered.get("shorts", [])
                              if isinstance(sh, dict)}
        fields = self.post_header_fields(episode_id)
        by_clip = {e["clip_id"]: e for e in doc["posts"]}
        if views:
            try:
                ep_src = post_source.load(episode_id, self.config)
            except post_source.PostSourceError:
                ep_src = None
            series, tags = self.post_series_and_tags(episode_id)
            hashtags_list = review_hashtags(series, tags)
            prefixes = ep.copy_prefixes(self.config, episode_id, ep.render_manifest(self.config, episode_id) or {})
        items = []
        for cid in order:
            entry = by_clip.get(cid)
            if entry is None:
                continue
            head, paras, source = post_logic.text_parts(title=titles_by_clip.get(cid), paragraphs=entry["paragraphs"],
                                                        header_fields=fields)
            item = {"clip_id": cid, "head": head, "paras": paras, "source": source, "image": entry["image"]}
            if views:
                view = self.post_entry_view(entry, ep_src=ep_src, title=titles_by_clip.get(cid) if tab_titles else None,
                                        header_fields=fields,
                                        hashtags_list=hashtags_list)
                item.update(episode_id=episode_id, code=prefixes.get(cid, "").rstrip("_"), copy_text=view["text"],
                            posted=view["posted"], stale=view["stale"])
            items.append(item)
        return items

    def export_data(self, video_id: str, views: bool = False) -> tuple[str, list[tuple[str, list[dict]]]] | None:
        """Heading + groups "Shorts" then "Khai thị" (name, items) of ``video_id`` (a Short episode); None when it
        has no post."""
        groups = [(n, items) for n, eid in (("Shorts", video_id), ("Khai thị", video_id + khaithi.SUFFIX))
                  if (items := self.export_items(eid, views))]
        if not groups:
            return None
        fields = self.post_header_fields(video_id) or self.post_header_fields(video_id + khaithi.SUFFIX) or {}
        series, number = fields.get("series"), fields.get("episode") or video_id
        heading = f"{series} tập {number}" if series else f"Tập {number}"
        try:
            meta = json.loads((Path(self.config.workspace.dir) / video_id / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        vtitle = meta.get("title") if isinstance(meta, dict) else None
        if isinstance(vtitle, str) and vtitle.strip() and not (series and str(series).casefold() in vtitle.casefold()):
            heading += f" — {vtitle.strip()}"  # not when the video title already carries the series name
        return heading, groups

    def docx_name_of(self, video_id: str, images: bool = True) -> str:
        kf = ep.kind_fields(self.config, video_id)
        return posts_docx_name(ep.label(self.config, video_id, kf), series=ep.zip_series(self.config, video_id, kf),
                               images=images)

    def is_numbered(self, e: dict) -> bool:
        return isinstance(e.get("episode"), str) and e["episode"].isdigit() and int(e["episode"]) >= 1

    def pick_range(self, doc: dict, range_from: int | None, range_to: int | None,
                    other: str | None, *, error_response: Callable) -> Any:
        """CP8.31 A1 (shared with SR2 K2): the available entries of a bộ kinh in episode order within ``from``..``to``
        (at most ``RANGE_SIZE`` numbers) or the unnumbered ones (``other=1``) + the file-name span; 422 otherwise."""
        entries = self.by_episode_order([e for e in doc["entries"] if e.get("video_id") and e.get("available")])
        if other is not None:
            if other != "1" or range_from is not None or range_to is not None:
                return error_response({"detail": "dùng other=1 một mình hoặc from + to"}, status_code=422)
            return [e for e in entries if not self.is_numbered(e)], "chưa rõ"
        if range_from is None or range_to is None or range_to < range_from or range_to - range_from >= RANGE_SIZE:
            return error_response({"detail": f"cần from, to (to ≥ from, tối đa {RANGE_SIZE} tập)"}, status_code=422)
        return [e for e in entries if self.is_numbered(e) and range_from <= int(e["episode"]) <= range_to], \
            f"{range_from}-{range_to}"

    def vertical_target(self, owner: str):
        """CP8.32: the vertical job target of a video (an archived original is downloaded again in the prepare lane)."""
        return vertical_target(self.config, vertical=self.vertical, episode_id=owner, downloader=self.vertical_downloader,
                               disk_blocked=self.storage.block_message)

    def restore_job(self, eid: str):
        job = self.runner.latest(ep.hd_owner(eid))
        return job if job is not None and job.kind == KIND_RESTORE_SOURCE else None

    def auto_vertical_waiting(self, vid: str) -> bool:
        """CP8.35 D6: the video has the wish and its vertical job waits for the HD source (enhance on, HD not done)."""
        if not self.auto_vertical.wanted(vid):
            return False
        return any(enh_state.is_pending(enh_state.read(Path(self.config.workspace.dir) / p)) for p in (vid, vid + khaithi.SUFFIX))

    def job_view(self, job, *, logs: bool = True) -> dict | None:
        if job is None:
            return None
        out = job.to_dict(logs=logs)
        out["queue_position"] = self.runner.queue_position(job)  # CP8.10: in the queue of the lane it waits for
        return out

    def queue_video(self, video_id: str, kinds: list[str], lo, hi, series: str | None, episode: str | None, *,
                     prepare_only: bool = False, vertical_wish: bool | None = None) -> list[dict]:
        """Queue the pipeline job of each of ``kinds`` for a video (W4 per kind on its own episode: duplicate job,
        archived, low disk) and return one item per kind: ``{kind, episode_id, created, job}`` or
        ``{kind, episode_id, error, status}``. ``prepare_only`` (CP13.2 H1, Short only): the "Chuẩn bị + HD" job."""
        url = canonical_url(video_id)

        # W4 per kind on its own episode (A1.1): duplicate job, archived (CP8.6 S3), low disk (CP8.6 S4)
        items: list[dict] = []
        for kind in kinds:
            try:  # FIX-youtube-id-dash I4: a bad id is a 4xx, never a 500
                eid = validate_episode_id(video_id) if kind == "short" else khaithi.episode_id_for(video_id)
            except WorkspaceError:
                items.append({"kind": kind, "episode_id": video_id, "status": 422,
                              "error": f"id video không hợp lệ: {video_id!r}"})
                continue
            except khaithi.KhaithiError as exc:
                items.append({"kind": kind, "episode_id": video_id, "status": 422, "error": exc.vi})
                continue
            item: dict = {"kind": kind, "episode_id": eid}
            current = self.runner.latest(eid)
            if current is not None and current.active:
                item.update(created=False, job=current)
            elif is_archived(Path(self.config.workspace.dir) / eid):
                item.update(error=str(ArchivedError(eid)), status=409)
            elif self.storage.status()["block"]:
                item.update(error=BLOCK_MESSAGE, status=507)
            items.append(item)
        todo = [i for i in items if "job" not in i and "error" not in i]
        previous = self.auto_vertical.wanted(video_id)
        if vertical_wish is not None and any("error" not in i for i in items):
            self.auto_vertical.set(video_id, vertical_wish)  # CP8.35 D3: before the jobs, so a fast job still sees it
        # FIX-ollama-wait O4: no Ollama preflight here - the ai lane checks it and waits for the GPU
        with self.submit_lock:
            for i in todo:  # Short first, then khai thị (K5 reuses the Short's source + transcript)
                current = self.runner.latest(i["episode_id"])
                if current is not None and current.active:
                    i.update(created=False, job=current)
                    continue
                if i["kind"] == khaithi.KIND:
                    try:  # written just before its job is queued; changed minutes -> re-run from analysis
                        _, changed = khaithi.prepare(self.config, video_id, lo, hi)
                    except khaithi.KhaithiError as exc:
                        i.update(error=exc.vi, status=409)
                        continue
                    log.info("web: khai thi %s %d-%d minutes (%s)", i["episode_id"], lo, hi,
                             "parameters changed" if changed else "parameters unchanged")
                job, created = self.runner.submit(
                    i["episode_id"], KIND_PIPELINE,
                    pipeline_target(url, self.config, series=series, episode=episode, pipeline=self.pipeline,
                                    preflight=self.preflight,
                                    episode_id=i["episode_id"] if i["kind"] == khaithi.KIND else None,
                                    disk_blocked=self.storage.block_message, enhance=self.svc,
                                    prepare_only=prepare_only))
                i.update(created=created, job=job)
        if vertical_wish and all("error" in i for i in items):
            self.auto_vertical.set(video_id, previous)  # nothing was queued: keep the earlier wish
        self.playlists.invalidate(video_id)
        self.storage.invalidate()
        return items

    def post_now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def enh_error(self, exc: EnhanceError, *, error_response: Callable) -> Any:
        return error_response({"detail": str(exc)}, status_code=exc.status)
