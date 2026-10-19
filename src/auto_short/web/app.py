"""FastAPI app factory (W2, W4, W6, W7). Contract: docs/decisions/CP8.3-web-contract.md."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import shutil
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool

from .. import khaithi
from ..compilation import CompilationError
from ..config import Config, whisper_threads_per_job
from ..enhance import state as enh_state
from ..enhance.service import EnhanceService
from ..enhance.state import EnhanceError
from ..enhance.tokens import tokens_from_env
from ..pipeline import PIPELINE_STAGES, PreflightError, ollama_preflight, run_pipeline
from ..sutra import web as sutra_web
from ..sutra.store import SutraStore
from ..post import (
    corrections as post_corrections,
    images as post_images,
    logic as post_logic,
    source as post_source,
    stage as post_stage,
    store as post_store,
)
from ..render import run_render, full as render_full
from ..selection.client import resolve_host
from ..review import (
    ArchivedError,
    EpisodeNotFound,
    ReviewError,
    TitlePreview,
    archive_source,
    content_disposition,
    delete_episode,
    is_archived,
    list_titles,
    preview_title,
    reject_archived_clip,
    reject_clip,
    reset_title,
    restore_clip,
    set_alternative,
    set_published,
    set_title,
    set_watched,
    shorts as review_shorts,
)
from ..review.archive import restore_parts, restore_source
from ..review.names import hashtags as review_hashtags
from ..workspace import read_json_dict
from .context import WebContext, KIND_RESTORE_SOURCE, KINDS
from .routes import (
    auth,
    pages,
    status,
    reading_api,
    files,
    files_catchall,
    playlists as playlist_routes,
    enhance,
    post_images as post_images_routes,
    post_corrections as post_corrections_routes,
)
from .routes.models import PublishedIn
from . import (
    episodes as ep,
    compilations as comp_web,
    downloads as dl_mod,
    monitor as monitor_mod,
    theme_index as theme_index_web,
    theme_plan as theme_plan_web,
)
from .auth import COOKIE_NAME, SessionSigner, load_or_create_secret
from .storage import StorageCache, auto_archive_plan, episode_sizes, parse_time, video_id
from .jobs import (
    EPISODE_KINDS,
    KIND_ADD,
    KIND_COMPILATION,
    KIND_ENHANCE,
    KIND_IMAGE_SEARCH,
    KIND_PIPELINE,
    KIND_POST,
    KIND_POST_SEARCH,
    KIND_RENDER,
    KIND_VERTICAL,
    PREPARE,
    JobFailed,
    JobRunner,
    Step,
    YoutubeWait,
    add_short_target,
    enhance_assemble_target,
    image_search_target,
    keyword_search_target,
    pipeline_target,
    post_compose_target,
    render_target,
)
from .auto_vertical import WISH_FILE, AutoVertical
from .priority import PRIORITY_FILE
from .playlists import LIST_TIMEOUT, PlaylistError, PlaylistStore, ytdlp_list
from .urls import ASK, PLAYLIST, UrlError, classify_url

log = logging.getLogger("auto_short")


class RestoreSourceTarget:
    """CP8.37: exact source restoration; download work stays outside the submit/publication lock."""

    def __init__(self, config, episode_id, *, downloader=None, lock=None, disk_blocked=None,
                 clock=time.time, after=None):
        self.config, self.episode_id = config, episode_id
        self.downloader, self.lock, self.disk_blocked = downloader, lock, disk_blocked
        self.clock, self.after = clock, after

    def needs_download(self):
        from ..theme_render.sources import cached_source
        return cached_source(self.config, self.episode_id) is None

    def __call__(self, job):
        from ..ingest.youtube import YoutubeBlocked
        job.stage = "ingest"
        if self.disk_blocked is not None and (message := self.disk_blocked()):
            raise JobFailed(message)
        t0 = time.monotonic()
        try:
            result = restore_source(self.episode_id, self.config, downloader=self.downloader, lock=self.lock,
                                    clock=self.clock)
        except YoutubeBlocked as exc:
            raise YoutubeWait(f"khôi phục nguồn: {exc}") from exc
        except (ReviewError, OSError) as exc:
            raise JobFailed(f"khôi phục nguồn: {exc}") from exc
        if result.downloaded:
            job.youtube_ok()
        if self.after is not None:
            self.after(result.episodes)
        job.stages.append({"stage": "ingest", "ran": result.downloaded, "seconds": round(time.monotonic() - t0, 3)})
        job.stage = None
        job.summary = "Đã khôi phục nguồn: " + ", ".join(result.episodes)

    def lane_steps(self):
        return [Step(PREPARE, self)]

    def spec(self):
        return {"episode_id": self.episode_id}

STATIC_DIR = Path(__file__).parent / "static"
# Reachable without a session: the login page and its stylesheet only.
PUBLIC_PATHS = {"/login", "/static/style.css"}
MAX_FIELD = 100
AUTO_ARCHIVE_INTERVAL = 300.0  # seconds between auto clean-up passes (W9 S5)
QUEUE_FILE = ".web_queue.json"  # CP8.22 Q2: saved job queue, in the workspace dir next to ``.web_secret``
ENHANCE_PREFIX = "/api/enhance/"  # CP13.1 E8: worker routes, token auth (no cookie); the one exception is below
ENHANCE_UI_PATHS = {"/api/enhance/status"}  # read-only status for the UI: cookie, like every other web route


class SubmitIn(BaseModel):
    url: str = Field(max_length=2000)
    series: str | None = Field(default=None, max_length=MAX_FIELD)
    episode: str | None = Field(default=None, max_length=MAX_FIELD)
    # CP8.7 L2: for ``watch?v=…&list=…`` the user chooses the single video or the whole playlist
    mode: Literal["video", "playlist"] | None = None
    # CP8.9 A1.1: ["short", "khaithi"] (absent = both) + khai thị minutes; checked in the handler (Vietnamese 422)
    kinds: Any = None
    min_minutes: Any = None
    max_minutes: Any = None
    # CP8.35 D3: also make the vertical full-episode version once the Shorts and the best HD source are ready
    vertical: bool = False


class EnhanceSwitchIn(BaseModel):
    enabled: StrictBool


class PreviewIn(BaseModel):
    text: str = Field(max_length=1000)


class TitleIn(BaseModel):
    """Exactly one action: ``set`` (manual text), ``alternative`` (1-based AI alternative) or ``reset: true``."""

    set: str | None = Field(default=None, max_length=1000)
    alternative: int | None = None
    reset: bool = False


SEGMENT_ID = Field(default=None, max_length=32)


class CutPreviewIn(BaseModel):
    """CP9 C7: range of caption lines ``start_segment`` .. ``end_segment`` + nudges (s, ±0.2 steps, ≤ ±2.0);
    ``clip_id`` = the Short being edited (its current range is the base), absent = a new Short."""

    clip_id: str | None = Field(default=None, max_length=32)
    start_segment: str = Field(max_length=32)
    end_segment: str = Field(max_length=32)
    start_nudge: Any = 0
    end_nudge: Any = 0


class CutIn(BaseModel):
    """``{start_segment, end_segment, start_nudge, end_nudge}`` or ``{reset: true}`` ("Về như AI chọn")."""

    start_segment: str | None = SEGMENT_ID
    end_segment: str | None = SEGMENT_ID
    start_nudge: Any = 0
    end_nudge: Any = 0
    reset: bool = False


class AddIn(BaseModel):
    """A new Short: ``{candidate_id}`` (remaining AI proposal) or ``{start_segment, end_segment[, nudges]}``."""

    candidate_id: str | None = Field(default=None, max_length=32)
    start_segment: str | None = SEGMENT_ID
    end_segment: str | None = SEGMENT_ID
    start_nudge: Any = 0
    end_nudge: Any = 0


class PostComposeIn(BaseModel):
    """CP8.15 P9: ``{"clips": [...]}`` (1-based clip ids) or ``{"clips": "all"}`` ("Soạn bài cho mọi Short")."""

    clips: Any = None


class PostEditIn(BaseModel):
    """CP8.15 P9 ``PUT``: any non-empty subset of ``paragraphs`` / ``image`` / ``link``."""

    paragraphs: list[str] | None = Field(default=None, max_length=200)
    image: str | None = Field(default=None, max_length=100)
    link: str | None = Field(default=None, max_length=2000)


def _preview_dict(p: TitlePreview | None) -> dict | None:
    if p is None:
        return None
    return {"clip_id": p.clip_id, "title": p.title, "origin": p.origin, "display_lines": list(p.display_lines),
            "font_size": p.font_size, "panel_height": p.panel_height, "chars": len(p.title)}


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def create_app(config: Config, password: str, *, runner: JobRunner | None = None,
               preflight: Callable[[Config], None] | None = ollama_preflight,
               pipeline: Callable = run_pipeline, render: Callable = run_render,
               secret: bytes | None = None, disk_usage: Callable = shutil.disk_usage,
               clock: Callable[[], float] = time.time, playlist_lister: Callable = ytdlp_list,
               playlist_timeout: float = LIST_TIMEOUT, titler: Callable | None = None,
               post_compose: Callable | None = None,
               post_preflight: Callable[[Config], None] | None = post_stage.preflight,
               post_search: Callable | None = None, keyword_search: Callable | None = None, doc_prepare: Callable | None = None,
               auto_archive_interval: float = AUTO_ARCHIVE_INTERVAL,
               enhance_tokens: dict[str, str] | None = None, enhance_service: EnhanceService | None = None,
               proc_dir: str = "/proc", ollama_ps: Callable[[], dict] | None = None,
               monitor_interval: float = monitor_mod.SAMPLE_SECONDS, vertical: Callable | None = None,
               vertical_downloader: Callable | None = None, restore_downloader: Callable | None = None) -> FastAPI:
    """``preflight`` / ``pipeline`` / ``render`` are injectable for tests (defaults: CP8 ``ollama_preflight`` /
    ``run_pipeline``, CP7/CP8.2 ``run_render``); so are ``disk_usage`` (``shutil.disk_usage``) and ``clock`` (epoch
    seconds, ages of the storage recommendations) for CP8.6; ``playlist_lister`` (yt-dlp flat listing) and
    ``playlist_timeout`` for CP8.7; ``titler`` (AI title of an added Short, default
    :func:`auto_short.titling.added.title_added`) for CP9; ``post_compose`` / ``post_preflight`` (default
    :func:`auto_short.post.stage.compose_posts` / ``.preflight``) and ``post_search`` (default
    :func:`auto_short.post.fetch.search_images`) for CP8.15; ``keyword_search`` (default
    :func:`auto_short.post.imgsearch.search_for_config`) for CP8.30; ``doc_prepare`` (default
    :func:`auto_short.post.doc.prepare`, the "Văn bản gốc" check of ``PUT /api/playlists/{id}/doc``) for CP8.19;
    ``auto_archive_interval`` (seconds between auto clean-up passes, W9 S5; 0 = only at start-up); for CP13.1
    ``enhance_tokens`` (``name -> token`` of the enhance workers, default: env ``AUTO_SHORT_ENHANCE_TOKENS``, E8) and
    ``enhance_service`` (default: an :class:`EnhanceService` on ``config``); for CP8.28 ``proc_dir`` (``/proc``),
    ``ollama_ps`` (default: ``GET <ollama host>/api/ps``) and ``monitor_interval`` (seconds between CPU samples)."""
    workers = config.web.prepare_workers if config.web.queue_mode == "lanes" else 1
    wh = config.transcript.whisper
    threads = whisper_threads_per_job(wh, workers)  # CP8.29 P1: Whisper threads of each prepare job
    if threads != wh.cpu_threads:
        config = replace(config, transcript=replace(config.transcript, whisper=replace(wh, cpu_threads=threads)))
    runner = runner or JobRunner(config.web.queue_mode,
                                 youtube_retry_seconds=config.web.youtube_retry_minutes * 60.0,
                                 youtube_retry_max_seconds=config.web.youtube_retry_max_minutes * 60.0,
                                 prepare_workers=workers, worker_nice=config.web.worker_nice,
                                 render_workers=config.web.render_workers, render_max_cpu=config.web.render_max_cpu)
    tokens = dict(enhance_tokens) if enhance_tokens is not None else tokens_from_env()
    storage = StorageCache(config, disk_usage=disk_usage, clock=clock)
    playlists = PlaylistStore(config, lister=playlist_lister, timeout=playlist_timeout)
    # Serialises "no active job for the episode?" + review.json write + job submit (W5: no title write while a
    # pipeline / render job of the episode is queued or running).
    submit_lock = threading.Lock()
    auto_vertical = AutoVertical()  # CP8.35 D3: videos whose vertical full-episode version is made by itself
    publish_lock = threading.Lock()  # publish.json read-modify-write (no job check: allowed while a job runs)
    post_lock = threading.Lock()  # posts.json read-modify-write (CP8.15 P7: allowed even while a job runs)
    signer = SessionSigner(secret if secret is not None else load_or_create_secret(Path(config.workspace.dir)),
                           password, config.web.session_days)

    # --- CP13.1b: enhance (HD source) -------------------------------------------------------------------------

    svc = enhance_service or EnhanceService(config, ai_busy=runner.ai_busy)
    svc.ai_busy = runner.ai_busy
    svc.priority_rank = runner.priority.rank  # CP8.26 P3

    # --- CP8.28: monitor tab ---------------------------------------------------------------------------------

    def _lane_jobs() -> dict[str, dict]:
        return {lane: {"id": job.id, "episode_id": job.episode_id, "kind": job.kind, "stage": job.stage}
                for lane, job in runner.running_slots().items()}

    sampler = monitor_mod.Sampler(proc=proc_dir, workdir=config.workspace.dir, interval=monitor_interval,
                                  clock=clock, disk_usage=disk_usage, lane_tids=runner.lane_tids,
                                  lane_jobs=_lane_jobs)
    ollama_view = monitor_mod.OllamaView(
        ollama_ps or (lambda: monitor_mod.fetch_ollama_ps(resolve_host(config.selection.ollama_host))))

    def _enhance_complete(eid: str) -> None:
        """All segments of ``eid`` arrived (or a restart / retry): queue the assembly job (render lane)."""
        job, created = runner.submit(eid, KIND_ENHANCE, enhance_assemble_target(svc, after=_hd_ready))
        log.info("web: ghép HD [%s] -> job %s%s", eid, job.id, "" if created else " (đã có)")

    def _hd_ready(eid: str) -> None:
        """The HD source of the video is ready: its parts leave "đợi HD" / re-render (E6)."""
        for part in enh_state.video_parts(config, eid):
            _release_hd(part)
        _auto_vertical_check(eid)  # CP8.35 D4

    def _hd_published(eid: str, rm: dict | None) -> bool:
        """Is any rendered Short of the episode ticked "Đã đăng" for its current file? (then no auto re-render)"""
        if rm is None:
            return False
        return any(v.get("published") and not v.get("stale") for v in ep.publish(config, eid, rm)[0].values())

    def _release_hd(eid: str, *, force_render: bool = False) -> str:
        """Let ``eid`` carry on without waiting: unpark its job (render queue); no job + it was waiting -> a render job;
        an episode rendered earlier from the original source is re-rendered when none of its Shorts is ticked "Đã
        đăng" (E6). Returns what was done: ``unparked`` | ``render`` | ``busy`` | ``kept`` | ``none``."""
        with submit_lock:
            if runner.unpark(eid) is not None:
                svc.clear_waiting(eid)
                return "unparked"
            doc = enh_state.read(Path(config.workspace.dir) / eid)
            waiting = bool(doc and doc.get("waiting_hd"))
            current = runner.latest(eid)
            if current is not None and current.active:
                return "busy"  # its own render step will read the HD source
            rm = ep.render_manifest(config, eid)
            hd = doc.get("source_hd_sha256") if doc and doc.get("state") == enh_state.DONE else None
            if not waiting and not force_render:
                if rm is None or hd is None or rm.get("source_sha256") == hd:
                    return "none"
                if _hd_published(eid, rm):
                    return "kept"
            if not (Path(config.workspace.dir) / eid / "manifest.json").is_file():
                return "none"
            svc.clear_waiting(eid)
            runner.submit(eid, KIND_RENDER, render_target(config, render=render))
            return "render"

    def _recheck_parked(job) -> None:
        """A job just parked (or was restored parked): carry on at once when its HD is already there / not wanted."""
        if not svc.hold(job.episode_id):
            _release_hd(job.episode_id)

    svc.on_complete = _enhance_complete
    runner.on_parked = _recheck_parked

    def auto_archive_pass() -> list[str]:
        """W9 S5 / D4: remove the source video of every video whose parts are all "Xong" for at least the grace
        period (``[storage] auto_archive``). A video with a queued / running job on any part waits. Returns the
        episode ids archived."""
        if not config.storage.auto_archive:
            return []
        done: list[str] = []
        rows = episode_sizes(config, {j.episode_id for j in runner.jobs() if j.active})
        for item in auto_archive_plan(rows, clock(), config.storage.auto_archive_grace_minutes * 60):
            with submit_lock:
                parts = [r["id"] for r in rows if r["state"] != "orphan" and video_id(r["id"]) == item["video_id"]]
                if any((j := runner.latest(eid)) is not None and j.active for eid in parts) \
                        or any((j := runner.latest_vertical(ep.hd_owner(eid))) is not None and j.active for eid in parts):
                    continue  # CP8.32: a queued vertical job still needs the original
                # A restore may have finished since the rows were measured. Recheck its grace under the same lock.
                restored_times = [parse_time((read_json_dict(Path(config.workspace.dir) / eid / "restored.json")
                                              or {}).get("restored_at")) for eid in parts]
                if any(t is not None and clock() - t < config.storage.auto_archive_grace_minutes * 60
                       for t in restored_times):
                    continue
                for eid in item["episodes"]:
                    if enh_state.has_hd(Path(config.workspace.dir) / eid) \
                            or enh_state.is_pending(enh_state.read(Path(config.workspace.dir) / eid)):
                        continue  # CP13.1 E5: an enhanced / enhancing video keeps its source (never automatic)
                    try:
                        result = archive_source(eid, config, auto=True)
                    except ReviewError as exc:
                        log.warning("web: tự dọn nguồn %s: bỏ qua: %s", eid, exc)
                        continue
                    if result.changed:
                        done.append(eid)
                        log.warning("web: tự dọn nguồn %s: removed %s (%d bytes), video đã đăng hết từ %s", eid,
                                    ", ".join(result.removed) or "-", result.freed,
                                    datetime.fromtimestamp(item["since"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        if done:
            storage.invalidate()
        return done

    async def _auto_archive_loop() -> None:
        while True:
            try:
                await asyncio.to_thread(auto_archive_pass)
            except Exception:  # never stop the loop (disk errors, a half-written workspace)
                log.exception("web: tự dọn nguồn: lỗi")
            if auto_archive_interval <= 0:
                return
            await asyncio.sleep(auto_archive_interval)

    def _restored(episodes):
        storage.invalidate()
        for eid in episodes:
            playlists.invalidate(eid)

    def _restore_target(eid: str):
        return RestoreSourceTarget(config, eid, downloader=restore_downloader, lock=submit_lock,
                                   disk_blocked=storage.block_message, clock=clock, after=_restored)

    def _auto_vertical_check(eid: str) -> None:
        """CP8.35 D4: the wish "tự tạo bản dọc" of the video is met when its Shorts are rendered and the best HD source is
        ready -> queue the vertical job (the "Tạo bản dọc" submit); not yet -> keep the wish; no HD source -> drop it."""
        owner = ep.hd_owner(eid)
        if not auto_vertical.wanted(owner):
            return
        with submit_lock:
            if not auto_vertical.wanted(owner):
                return
            parts = (owner, owner + khaithi.SUFFIX)  # a part may still be before its first manifest
            if not any(post_stage.rendered_clip_ids(config, p) for p in parts):
                return  # the Shorts are not rendered (yet)
            if any((j := runner.latest(p)) is not None and j.active
                   and j.kind in (*EPISODE_KINDS, KIND_RESTORE_SOURCE) for p in parts):
                return  # a job of the video still runs the render step: its end checks again
            if ctx.auto_vertical_waiting(owner):
                return  # enhance on, HD not done: _hd_ready checks again
            if render_full.current(config, owner):
                auto_vertical.set(owner, False)
                return
            if ep.hd_source(config, owner) is None:
                auto_vertical.set(owner, False)
                log.info("web: bản dọc tự động [%s]: bỏ qua, không có bản HD / video gốc < %sp", owner,
                         config.enhance.min_height)
                return
            job, created = runner.submit(owner, KIND_VERTICAL, ctx.vertical_target(owner))
            auto_vertical.set(owner, False)
        log.info("web: bản dọc tự động [%s] -> job %s%s", owner, job.id, "" if created else " (đã có)")

    def _rebuild_job(kind: str, eid: str, spec: dict, clip_ids: list[str]):
        """CP8.22 Q2: the target of a job saved in the queue file, built like at submit time; None = cannot be
        recreated (bad id / parameters, workspace gone, episode archived) -> the runner skips it with a log line."""
        ws = Path(config.workspace.dir)
        if kind == KIND_IMAGE_SEARCH:
            kw = spec.get("keyword")
            return keyword_search_target(config, kw, search=keyword_search) if isinstance(kw, str) and kw else None
        if kind == KIND_POST_SEARCH:
            url = spec.get("url")
            return image_search_target(config, url, search=post_search) if isinstance(url, str) and url else None
        if kind == KIND_COMPILATION:  # CP8.33 G5: the key is ``compilation:<playlist_id>:<cid>``, not an episode
            return compilations.rebuild(eid, spec)
        if kind in (theme_plan_web.KIND_GENERATE, theme_plan_web.KIND_THEME_RENDER):
            return None  # TC2: restart requires a fresh user request and plan audit
        if not ep.valid_episode_id(eid):
            return None
        if kind == KIND_RESTORE_SOURCE:
            target_id = spec.get("episode_id")
            if not isinstance(target_id, str) or not ep.valid_episode_id(target_id) or ep.hd_owner(target_id) != eid:
                return None
            try:
                restore_parts(target_id, config)
            except (ReviewError, OSError):
                return None
            return _restore_target(target_id)
        if is_archived(ws / eid) and kind != KIND_VERTICAL:
            return None
        if kind == KIND_PIPELINE:
            url, kt = spec.get("url"), spec.get("episode_id")
            if not isinstance(url, str) or not url or (kt is not None and (kt != eid or not (ws / eid).is_dir())):
                return None
            series, episode = spec.get("series"), spec.get("episode")
            return pipeline_target(url, config, series=series if isinstance(series, str) else None,
                                   episode=episode if isinstance(episode, str) else None, pipeline=pipeline,
                                   preflight=preflight, episode_id=kt, disk_blocked=storage.block_message,
                                   enhance=svc, prepare_only=bool(spec.get("prepare_only")) and kt is None)
        if not (ws / eid).is_dir():
            return None
        if kind == KIND_RENDER:
            return render_target(config, render=render)
        if kind == KIND_ENHANCE:
            return enhance_assemble_target(svc, after=_hd_ready)
        if kind == KIND_VERTICAL:
            return ctx.vertical_target(eid)
        if kind == KIND_ADD:
            clip = spec.get("clip_id")
            return add_short_target(config, clip, render=render, preflight=preflight, titler=titler) \
                if isinstance(clip, str) and clip else None
        if kind == KIND_POST:
            clips = spec.get("clips")
            if not (isinstance(clips, str) or (isinstance(clips, list) and all(isinstance(c, str) for c in clips))):
                return None
            return post_compose_target(config, clips, compose=post_compose, preflight=post_preflight, lock=post_lock)
        return None

    def _vertical_failed(job) -> None:
        """K2: the vertical job of an archived episode ended failed / interrupted: remove the original it re-downloaded
        (unless another vertical job of the video is still active)."""
        with submit_lock:
            latest = runner.latest_vertical(ep.hd_owner(job.episode_id))
            restoring = ctx.restore_job(job.episode_id)
            if (latest is not None and latest is not job and latest.active) \
                    or (restoring is not None and restoring.active):
                return
            render_full.remove_refetched_source(config, job.episode_id)

    runner.on_vertical_failed = _vertical_failed

    def _sweep_refetched() -> int:
        with submit_lock:
            active = {ep.hd_owner(j.episode_id) for j in runner.jobs()
                      if j.kind in (KIND_VERTICAL, KIND_RESTORE_SOURCE) and j.active}
            return render_full.sweep_refetched_sources(config, active)

    app_sweep = _sweep_refetched

    compilations = comp_web.Compilations(config, playlists, runner, lambda doc: ctx.playlist_docx_series(doc))
    theme_plans = theme_plan_web.ThemePlans(config, playlists, runner, preflight=preflight)
    runner.configure_persistence(Path(config.workspace.dir) / QUEUE_FILE, _rebuild_job)
    runner.priority.attach(Path(config.workspace.dir) / PRIORITY_FILE)  # CP8.26 P1
    auto_vertical.attach(Path(config.workspace.dir) / WISH_FILE)  # CP8.35 D3

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runner.restore()  # CP8.22 Q2: before the lanes start and before the auto clean-up sweeps
        await asyncio.to_thread(app_sweep)  # CP8.32 K2: re-downloaded originals left by jobs that no longer exist
        runner.start()
        for eid in svc.resume_assembly():  # CP13.1b: segments all there but never assembled (restart)
            _enhance_complete(eid)
        runner.recheck_parked()  # CP13.1b: "đợi HD" jobs whose HD is ready by now
        sampler.start()
        sweeper = asyncio.create_task(_auto_archive_loop())
        try:
            yield
        finally:
            sweeper.cancel()
            await asyncio.to_thread(sampler.stop)
            await asyncio.to_thread(runner.stop)

    app = FastAPI(title="auto-short web", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runner = runner
    app.state.auto_vertical = auto_vertical  # CP8.35
    app.state.hd_ready = _hd_ready
    app.state.monitor_sampler = sampler
    app.state.storage = storage
    app.state.auto_archive_pass = auto_archive_pass
    app.state.sweep_refetched = _sweep_refetched
    app.state.playlists = playlists
    app.state.compilations = compilations
    app.state.theme_plans = theme_plans
    app.state.signer = signer
    download_table = dl_mod.DownloadTable()  # CP8.34 D3: progress of ``?dl=<token>`` downloads (memory only)
    app.state.downloads = download_table

    ctx = WebContext(
        config=config,
        runner=runner,
        tokens=tokens,
        storage=storage,
        playlists=playlists,
        publish_lock=publish_lock,
        post_lock=post_lock,
        signer=signer,
        svc=svc,
        sampler=sampler,
        ollama_view=ollama_view,
        compilations=compilations,
        download_table=download_table,
        static_dir=STATIC_DIR,
        submit_lock=submit_lock,
        auto_vertical=auto_vertical,
        pipeline=pipeline,
        preflight=preflight,
        vertical=vertical,
        vertical_downloader=vertical_downloader,
        post_compose=post_compose,
        post_preflight=post_preflight,
        post_search=post_search,
        keyword_search=keyword_search,
        doc_prepare=doc_prepare,
    )
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        worker_route = path.startswith(ENHANCE_PREFIX) and path not in ENHANCE_UI_PATHS
        if worker_route:  # CP13.1 E8: the route checks the worker token itself; the web cookie never opens it
            response = await call_next(request)
        elif path not in PUBLIC_PATHS and not signer.verify(request.cookies.get(COOKIE_NAME)):
            if path.startswith("/api/") or path.startswith("/files/") or request.method != "GET":
                response = JSONResponse({"detail": "chưa đăng nhập"}, status_code=401)
            else:
                target = path + (f"?{request.url.query}" if request.url.query else "")
                response = RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
        else:
            response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        elif path.startswith("/static/") or path == "/login":
            # CP8.31: without it mobile browsers cache style.css / app.js heuristically (Last-Modified only) and keep
            # an old layout; no-cache = revalidate with the ETag (304, cheap)
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # --- API ---------------------------------------------------------------------------------------

    @app.get("/api/episodes")
    def api_list():
        items = ep.list_episodes(config)
        known = {i["id"] for i in items}
        for job in runner.jobs():  # queued jobs whose workspace does not exist yet
            if job.active and job.episode_id not in known and job.kind != KIND_COMPILATION:
                known.add(job.episode_id)
                items.insert(0, {**ep.kind_fields(config, job.episode_id), "id": job.episode_id, "title": None,
                                 "stages_done": 0, "stages_total": len(PIPELINE_STAGES), "running": None,
                                 "failed": None, "shorts": 0})
        in_playlists = playlists.video_ids()
        for item in items:
            job = runner.latest(item["id"])
            item["job"] = ctx.job_view(job, logs=False)
            item["priority"] = runner.priority.marked(item["id"])  # CP8.26
            item.setdefault("published", 0)
            item.setdefault("complete", False)
            item["publish_group"] = ep.publish_group(item)
            # CP8.7: home page "Tập lẻ" = not in a bộ kinh; CP8.9 K8: a khai thị episode follows its base video
            item["in_playlist"] = (item.get("base_episode_id") or item["id"]) in in_playlists
        return {"episodes": items, "gpu": runner.gpu_status(), "youtube": runner.youtube_status(), "queue": runner.queue_state()}  # O7, CP8.22

    def _kinds(body: SubmitIn) -> list[str] | JSONResponse:
        """CP8.9 A1.1: ``kinds`` (absent = Short + khai thị), always in the order Short then khai thị."""
        raw = body.kinds
        if raw is None:
            kinds = list(KINDS)
        else:
            if not isinstance(raw, list) or not raw or not all(isinstance(k, str) and k in KINDS for k in raw):
                return JSONResponse({"detail": "kinds phải là danh sách không rỗng gồm \"short\" và / hoặc "
                                               "\"khaithi\""}, status_code=422)
            if len(set(raw)) != len(raw):
                return JSONResponse({"detail": "kinds bị trùng"}, status_code=422)
            kinds = [k for k in KINDS if k in raw]
        if khaithi.KIND not in kinds and (body.min_minutes is not None or body.max_minutes is not None):
            return JSONResponse({"detail": "Số phút chỉ dùng khi có video khai thị"}, status_code=422)
        return kinds

    @app.post("/api/episodes")
    def api_submit(body: SubmitIn):
        kinds = _kinds(body)
        if isinstance(kinds, JSONResponse):
            return kinds
        try:
            parsed = classify_url(body.url)
        except UrlError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        if parsed.kind == ASK and body.mode is None:  # CP8.7 L2: the UI asks "tập lẻ" or "cả bộ kinh"
            return JSONResponse({"kind": ASK, "video_id": parsed.video_id, "playlist_id": parsed.playlist_id})
        if parsed.kind == PLAYLIST or (parsed.kind == ASK and body.mode == "playlist"):
            return _import_playlist(parsed.playlist_id)  # A1.3: kinds / minutes do not apply to a bộ kinh
        if body.mode == "playlist":
            return JSONResponse({"detail": "URL không có playlist"}, status_code=422)
        lo = hi = None
        if khaithi.KIND in kinds:  # K2 minutes (absent = [khaithi] defaults)
            kc = config.khaithi
            try:
                lo, hi = khaithi.check_minutes(
                    kc.default_min_minutes if body.min_minutes is None else body.min_minutes,
                    kc.default_max_minutes if body.max_minutes is None else body.max_minutes, kc.max_minutes_limit)
            except khaithi.KhaithiError as exc:
                return JSONResponse({"detail": exc.vi}, status_code=422)
        video_id = parsed.video_id
        series, episode = _clean(body.series), _clean(body.episode)
        items = ctx.queue_video(video_id, kinds, lo, hi, series, episode, vertical_wish=body.vertical)
        out = [{k: (ctx.job_view(v) if k == "job" else v) for k, v in i.items()} for i in items]
        ok = [i for i in out if "error" not in i]
        if not ok:
            return JSONResponse({"detail": out[0]["error"], "kind": "video", "episodes": out},
                                status_code=out[0]["status"])
        first = ok[0]  # UI before A1: created / episode_id / job of the first accepted episode
        return JSONResponse({"kind": "video", "episodes": out, "created": first["created"],
                             "episode_id": first["episode_id"], "job": first["job"]},
                            status_code=202 if any(i.get("created") for i in ok) else 200)

    # --- playlists (CP8.7) ---------------------------------------------------------------------------

    def _import_playlist(playlist_id: str) -> JSONResponse:
        try:
            doc, created = playlists.add(playlist_id)
        except PlaylistError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=502)
        log.info("web: playlist %s %s (%d entries)", playlist_id, "imported" if created else "already stored",
                 len(doc["entries"]))
        return JSONResponse({"kind": PLAYLIST, "created": created, "playlist_id": playlist_id,
                             "title": doc.get("title"), "count": len(doc["entries"])},
                            status_code=201 if created else 200)

    @app.get("/api/episodes/{episode_id}")
    def api_episode(episode_id: str):
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        kf = ep.kind_fields(config, episode_id)
        # CP8.9 K8: a khai thị episode copies with the hashtags of the bộ kinh of its base video
        view = ep.episode_view(config, episode_id,
                               hashtags=playlists.hashtags_for(kf["base_episode_id"] or episode_id))
        job = runner.latest(episode_id)
        if view is None:
            if job is None:
                return JSONResponse({"detail": "không có episode này"}, status_code=404)
            view = {**kf, "id": episode_id, "title": None, "channel": None, "duration": None, "source_url": None,
                    "stages": [], "header": None, "shorts": [], "rendered": 0, "deleted": 0, "published": 0,
                    "zip_url": None, "zip_name": None, "zip_all_url": None, "zip_all_name": None,
                    "archived": None}
        view["job"] = ctx.job_view(job)
        view["restore_job"] = ctx.job_view(ctx.restore_job(episode_id))
        view["priority"] = runner.priority.marked(episode_id)  # CP8.26
        view["gpu"] = runner.gpu_status()  # FIX-ollama-wait O7
        view["youtube"] = runner.youtube_status()  # FIX-youtube-botcheck-wait Y3
        view["post_job"] = ctx.job_view(runner.latest_post(episode_id))  # CP8.16 R3 (job stays the episode's own job)
        view["enhance"] = _enhance_view(episode_id)  # CP13.1 E10
        view["hd_video"] = _hd_video_view(episode_id)  # CP8.27
        # CP8.33 G9 / G11: heart state of a khai thị episode (its bộ kinh + hearted clips), favourites that a delete loses
        fav = compilations.episode_favorites(episode_id)
        view["favorites"] = fav
        view["favorites_count"] = compilations.keep_count(episode_id)
        hearted = set(fav["clips"]) if fav else set()
        for short in view["shorts"]:
            short["favorite"] = short["clip_id"] in hearted
        if job is not None and job.active and job.kind in (KIND_RENDER, KIND_ADD):
            for short in view["shorts"]:
                short["rendering"] = short["clip_id"] in job.clip_ids
        return view

    def _size_or_none(path: Path | None) -> int | None:
        """A re-downloaded original can vanish between the view's checks (the vertical job cleans it up): no 500."""
        try:
            return path.stat().st_size if path is not None else None
        except OSError:
            return None

    def _hd_video_view(episode_id: str) -> dict | None:
        """CP8.27 H2 / H4 + CP8.32: the HD download (landscape) and the vertical full-episode file of the video, None
        while there is no effective HD source (``source``: ``hd`` | ``original`` | ``archived``; an archived original
        has no landscape download, ``url`` is None, and its vertical job downloads it again)."""
        src = ep.hd_source(config, episode_id)
        if src is None:
            return None
        hd = src.path
        owner = ep.hd_owner(episode_id)
        ready = render_full.ready_file(config, owner) if render_full.current(config, owner) else None
        job = runner.latest_vertical(owner)
        return {"url": f"/api/episodes/{episode_id}/source-hd" if hd is not None else None,
                "name": ep.hd_download_name(config, episode_id) if hd is not None else None,
                "size": _size_or_none(hd), "source": src.kind,
                "vertical": {"ready": ready is not None, "url": f"/api/episodes/{episode_id}/vertical",
                             "name": ep.video_download_name(config, episode_id, "Doc"),
                             "size": ready.stat().st_size if ready is not None else None,
                             "job": ctx.job_view(job, logs=False)}}

    @app.post("/api/episodes/{episode_id}/priority")
    def api_episode_priority(episode_id: str, body: PublishedIn):
        """CP8.26 P1 "Ưu tiên" / "Bỏ ưu tiên": the mark is per video (the Short and its khai thị episode share it)."""
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        if body.value:
            runner.priority.mark([episode_id])
        else:
            runner.priority.unmark([episode_id])
        return {"episode_id": episode_id, "priority": runner.priority.marked(episode_id)}

    def _check_clip(episode_id: str, clip_id: str) -> JSONResponse | None:
        if not ep.valid_episode_id(episode_id) or not ep.valid_clip_id(clip_id):
            return JSONResponse({"detail": "không có Short này"}, status_code=404)
        return None

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/title/preview")
    def api_title_preview(episode_id: str, clip_id: str, body: PreviewIn):
        if (bad := _check_clip(episode_id, clip_id)) is not None:
            return bad
        try:
            return _preview_dict(preview_title(episode_id, config, clip_id, body.text))
        except ReviewError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/title")
    def api_title(episode_id: str, clip_id: str, body: TitleIn):
        if (bad := _check_clip(episode_id, clip_id)) is not None:
            return bad
        actions = (body.set is not None) + (body.alternative is not None) + bool(body.reset)
        if actions != 1:
            return JSONResponse({"detail": "cần đúng một trong: set, alternative, reset"}, status_code=422)
        with submit_lock:
            current = runner.latest(episode_id)
            if current is not None and current.active:
                return JSONResponse({"detail": "episode đang có job chạy/đợi; sửa title sau khi job xong",
                                     "job": ctx.job_view(current)}, status_code=409)
            try:
                if body.set is not None:
                    preview = set_title(episode_id, config, clip_id, body.set)
                elif body.alternative is not None:
                    preview = set_alternative(episode_id, config, clip_id, body.alternative)
                else:
                    preview = reset_title(episode_id, config, clip_id)
            except ArchivedError as exc:  # CP8.6 S3
                return JSONResponse({"detail": str(exc)}, status_code=409)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, _ = runner.submit(episode_id, KIND_RENDER, render_target(config, render=render),
                                   clip_ids=[clip_id])
        log.info("web: title %s [%s]: %s -> render job %s", clip_id, episode_id,
                 f"{preview.origin} {preview.title!r}" if preview else "reset (untitled)", job.id)
        return JSONResponse({"preview": _preview_dict(preview), "job": ctx.job_view(job)}, status_code=202)

    def _review_render(episode_id: str, clip_id: str, action: Callable, what: str) -> JSONResponse:
        """CP8.5 X2: delete / restore one Short = write review.json + render job, same rules as a title write
        (409 while a job of the episode is queued/running, all under the submit lock)."""
        if (bad := _check_clip(episode_id, clip_id)) is not None:
            return bad
        with submit_lock:
            current = runner.latest(episode_id)
            if current is not None and current.active:
                return JSONResponse({"detail": "episode đang có job chạy/đợi; thử lại sau khi job xong",
                                     "job": ctx.job_view(current)}, status_code=409)
            archived = is_archived(Path(config.workspace.dir) / episode_id)
            try:
                if archived and action is reject_clip:
                    # CP8.6 S3: no render possible; the deletion is applied to the last render directly.
                    changed = reject_archived_clip(episode_id, config, clip_id)
                    storage.invalidate()
                    log.info("web: %s %s [%s] (archived, no render)", what, clip_id, episode_id)
                    return JSONResponse({"changed": changed, "job": None})
                changed = action(episode_id, config, clip_id)
            except ArchivedError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=409)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, _ = runner.submit(episode_id, KIND_RENDER, render_target(config, render=render),
                                   clip_ids=[clip_id])
        log.info("web: %s %s [%s]%s -> render job %s", what, clip_id, episode_id, "" if changed else " (no change)",
                 job.id)
        return JSONResponse({"changed": changed, "job": ctx.job_view(job)}, status_code=202)

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/delete")
    def api_short_delete(episode_id: str, clip_id: str):
        response = _review_render(episode_id, clip_id, reject_clip, "delete Short")
        if response.status_code < 300:
            compilations.drop_hearts(episode_id, clip_id)  # CP8.33 G11 (c): a hand-deleted khai thị loses its heart
        return response

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/restore")
    def api_short_restore(episode_id: str, clip_id: str):
        return _review_render(episode_id, clip_id, restore_clip, "restore Short")

    # --- CP9: cut points + added Shorts ---------------------------------------------------------------

    def _episode_or_404(episode_id: str) -> JSONResponse | None:
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        return None

    def _busy(episode_id: str) -> JSONResponse | None:
        current = runner.latest(episode_id)
        if current is not None and current.active:
            return JSONResponse({"detail": "episode đang có job chạy/đợi; thử lại sau khi job xong",
                                 "job": ctx.job_view(current)}, status_code=409)
        return None

    @app.get("/api/episodes/{episode_id}/transcript")
    def api_transcript(episode_id: str):
        """C7: caption lines + the current range of every Short (read-only, allowed while a job runs)."""
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        try:
            return review_shorts.transcript_view(episode_id, config)
        except ReviewError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/episodes/{episode_id}/proposals")
    def api_proposals(episode_id: str):
        """C7: AI proposals not selected (overlapped / over_limit / ineligible) that map to a candidate."""
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        try:
            return review_shorts.list_proposals(episode_id, config)
        except ReviewError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.post("/api/episodes/{episode_id}/cut/preview")
    def api_cut_preview(episode_id: str, body: CutPreviewIn):
        """C7: range + duration + C4 error / warnings of lines + nudges; nothing written, allowed during a job."""
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        if body.clip_id is not None and not ep.valid_clip_id(body.clip_id):
            return JSONResponse({"detail": "không có Short này"}, status_code=404)
        try:
            return review_shorts.preview_cut(episode_id, config, clip_id=body.clip_id,
                                             start_segment=body.start_segment, end_segment=body.end_segment,
                                             start_nudge=body.start_nudge, end_nudge=body.end_nudge)
        except ReviewError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/cut")
    def api_cut(episode_id: str, clip_id: str, body: CutIn):
        """C7: save the cut points of one Short (or ``reset``) + render job for it; 409 while a job runs or when
        the source video was cleaned up; 422 invalid range (review.json unchanged)."""
        if (bad := _check_clip(episode_id, clip_id)) is not None:
            return bad
        has_range = body.start_segment is not None and body.end_segment is not None
        if body.reset == has_range or (not has_range and (body.start_segment or body.end_segment)):
            return JSONResponse({"detail": "cần start_segment + end_segment, hoặc reset: true"}, status_code=422)
        with submit_lock:
            if (busy := _busy(episode_id)) is not None:
                return busy
            try:
                if body.reset:
                    preview = review_shorts.reset_cut(episode_id, config, clip_id)
                else:
                    preview = review_shorts.set_cut(episode_id, config, clip_id, start_segment=body.start_segment,
                                                    end_segment=body.end_segment, start_nudge=body.start_nudge,
                                                    end_nudge=body.end_nudge)
            except ArchivedError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=409)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, _ = runner.submit(episode_id, KIND_RENDER, render_target(config, render=render),
                                   clip_ids=[clip_id])
        log.info("web: cut %s [%s]: %s %.3f-%.3f (%.1f s) -> render job %s", clip_id, episode_id,
                 "reset" if body.reset else "set", preview["start"], preview["end"], preview["duration"], job.id)
        return JSONResponse({"preview": preview, "job": ctx.job_view(job)}, status_code=202)

    @app.post("/api/episodes/{episode_id}/shorts")
    def api_add_short(episode_id: str, body: AddIn):
        """C7: add a Short (C1) -> job: AI title (lane ai, C6) then render. 409 while a job runs / archived;
        503 Ollama preflight (W4); 422 invalid range or proposal (nothing written)."""
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        if (busy := _busy(episode_id)) is not None:
            return busy
        if is_archived(Path(config.workspace.dir) / episode_id):
            return JSONResponse({"detail": str(ArchivedError(episode_id))}, status_code=409)
        if preflight is not None:
            try:
                preflight(config)
            except PreflightError as exc:
                return JSONResponse({"detail": f"ollama preflight: {exc}"}, status_code=503)
        with submit_lock:
            if (busy := _busy(episode_id)) is not None:
                return busy
            try:
                added = review_shorts.add_short(episode_id, config, candidate_id=body.candidate_id,
                                                start_segment=body.start_segment, end_segment=body.end_segment,
                                                start_nudge=body.start_nudge, end_nudge=body.end_nudge)
            except ArchivedError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=409)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, _ = runner.submit(episode_id, KIND_ADD,
                                   add_short_target(config, added.clip_id, render=render, preflight=preflight,
                                                    titler=titler),
                                   clip_ids=[added.clip_id])
        log.info("web: added Short %s [%s] %.3f-%.3f (%.1f s, %s) -> job %s", added.clip_id, episode_id,
                 added.preview["start"], added.preview["end"], added.preview["duration"],
                 body.candidate_id or "transcript", job.id)
        return JSONResponse({"clip_id": added.clip_id, "preview": added.preview, "job": ctx.job_view(job)},
                            status_code=202)

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/published")
    def api_short_published(episode_id: str, clip_id: str, body: PublishedIn):
        """X4: tick / untick "Đã đăng" — user state only: no job, allowed while a job runs, render not stale."""
        if (bad := _check_clip(episode_id, clip_id)) is not None:
            return bad
        with publish_lock:
            try:
                result = set_published(episode_id, config, clip_id, body.value)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
        playlists.invalidate(episode_id)
        storage.invalidate()
        return result

    @app.post("/api/episodes/{episode_id}/shorts/{clip_id}/watched")
    def api_short_watched(episode_id: str, clip_id: str, body: PublishedIn):
        """CP8.21 D4: tick / untick "Đã xem" (``watched.json``) — user state only: no job, allowed while a job runs,
        render not stale."""
        if (bad := _check_clip(episode_id, clip_id)) is not None:
            return bad
        with publish_lock:
            try:
                return set_watched(episode_id, config, clip_id, body.value)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)

    # --- CP8.15: community post text ------------------------------------------------------------------------

    def _auto_post(job) -> None:
        """CP8.16 R2a: an episode job that ran the render step has ended (done / failed) → queue the ``auto``
        compose job of the episode when R4 selects at least one Short (empty set = no job)."""
        eid = job.episode_id
        order = [cid for cid, _ in post_stage.rendered_clip_ids(config, eid)]
        if not order:
            return
        try:
            ep_src = post_source.load(eid, config)
            with post_lock:
                doc = post_store.read_posts(ctx.posts_path(eid), eid)
        except (post_source.PostSourceError, post_store.PostsError):
            return
        if not post_stage.auto_clips(ep_src, doc, order):
            return
        posted, created = runner.submit(eid, KIND_POST,
                                        post_compose_target(config, "auto", compose=post_compose,
                                                            preflight=post_preflight, lock=post_lock))
        log.info("web: tự soạn bài [%s] sau job %s -> job %s%s", eid, job.id, posted.id,
                 "" if created else " (đã có)")

    def _on_episode_finished(job) -> None:
        """The one ``on_finished`` hook: CP8.16 R2a (auto post) then CP8.35 D4 (auto vertical); one failing does not
        stop the other."""
        for hook in (_auto_post, lambda j: _auto_vertical_check(j.episode_id)):
            try:
                hook(job)
            except Exception:
                log.exception("web: hook sau job %s [%s] lỗi", job.id, job.episode_id)

    runner.on_finished = _on_episode_finished

    @app.get("/api/episodes/{episode_id}/posts")
    def api_posts(episode_id: str):
        """P7/P9: every stored post of the episode (read-only, allowed while a job runs); ``post_error`` when
        ``posts.json`` is broken (not overwritten)."""
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        with post_lock:
            try:
                doc = post_store.read_posts(ctx.posts_path(episode_id), episode_id)
                post_error = None
            except post_store.PostsError as exc:
                doc, post_error = post_store.empty_posts(episode_id), str(exc)
        try:
            ep_src = post_source.load(episode_id, config)
        except post_source.PostSourceError:
            ep_src = None
        titles_by_clip: dict[str, str | None] = {}
        try:
            titles_by_clip = {c["clip_id"]: c["title"] for c in list_titles(episode_id, config)["clips"]}
        except ReviewError:
            pass
        header_fields = ctx.post_header_fields(episode_id)
        series, tags = ctx.post_series_and_tags(episode_id)
        hashtags_list = review_hashtags(series, tags)
        posts = [ctx.post_entry_view(e, ep_src=ep_src, title=titles_by_clip.get(e["clip_id"]),
                                  header_fields=header_fields, hashtags_list=hashtags_list) for e in doc["posts"]]
        return {"posts": posts, "post_error": post_error}

    def _post_clips(body: PostComposeIn) -> "list[str] | str | JSONResponse":
        raw = body.clips
        if raw in ("all", "auto"):  # "auto": CP8.16 R4
            return raw
        if not isinstance(raw, list) or not raw or not all(isinstance(c, str) and ep.valid_clip_id(c) for c in raw):
            return JSONResponse({"detail": 'clips phải là "all", "auto" hoặc một danh sách clip_id không rỗng'},
                                status_code=422)
        return raw

    @app.post("/api/episodes/{episode_id}/posts")
    def api_posts_compose(episode_id: str, body: PostComposeIn):
        """P1 (CP8.16 R3): soạn / soạn lại bài (lane ai) -> 202 job (job soạn bài đang đợi -> trả job đó); 409 khi
        episode đang có job ``pipeline`` (không còn 503 Ollama, FIX-ollama-wait O4). Không bị khóa bởi job render / add."""
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        clips = _post_clips(body)
        if isinstance(clips, JSONResponse):
            return clips
        with submit_lock:  # FIX-ollama-wait O4: no preflight in the request; the ai lane waits for the GPU
            current = runner.latest(episode_id)
            if current is not None and current.active and current.kind == KIND_PIPELINE:
                return JSONResponse({"detail": "episode đang chạy pipeline; soạn bài sau khi job xong",
                                     "job": ctx.job_view(current)}, status_code=409)
            job, _created = runner.submit(episode_id, KIND_POST,
                                          post_compose_target(config, clips, compose=post_compose,
                                                              preflight=post_preflight, lock=post_lock))
        log.info("web: soạn bài %s [%s] -> job %s", clips if isinstance(clips, str) else ",".join(clips), episode_id,
                 job.id)
        return JSONResponse({"job": ctx.job_view(job)}, status_code=202)

    def _learn_corrections(episode_id: str, clip: str, old: list[str], new: list[str], now: str) -> int | None:
        """CP8.18 D2/D6 (caller holds ``post_lock``): log the edit and record the proposals; any dictionary / IO
        failure is a warning and ``None``, never a failure of the post save."""
        path = config.post.corrections_path
        try:
            proposals, words, changed = post_corrections.extract(old, new)
            post_corrections.append_edit_log(path, at=now, episode_id=episode_id, clip_id=clip, words=words,
                                             changed_words=changed)
            if not proposals:
                return 0
            cdoc = post_corrections.load(path)
            post_corrections.record(cdoc, proposals, episode_id, clip, now)
            post_corrections.save(path, cdoc)
            return len(proposals)
        except (post_corrections.CorrectionsError, OSError) as exc:
            log.warning("web: từ điển sửa lỗi: %s", exc)
            return None

    @app.put("/api/episodes/{episode_id}/posts/{clip}")
    def api_posts_edit(episode_id: str, clip: str, body: PostEditIn):
        """P9: sửa tay ``paragraphs`` (-> ``origin: manual``) / đổi ``image`` / sửa ``link`` (P6); được cả khi job
        đang chạy (P7); cần đã có bài (bấm "Soạn bài" trước)."""
        if (bad := _check_clip(episode_id, clip)) is not None:
            return bad
        given = body.model_fields_set & {"paragraphs", "image", "link"}
        if not given:
            return JSONResponse({"detail": "cần ít nhất một trong: paragraphs, image, link"}, status_code=422)
        changes: dict = {}
        if "paragraphs" in given:
            paragraphs = body.paragraphs
            if not isinstance(paragraphs, list) or not paragraphs \
                    or not all(isinstance(p, str) and p.strip() for p in paragraphs):
                return JSONResponse({"detail": "paragraphs phải là mảng chuỗi không rỗng"}, status_code=422)
            changes["paragraphs"] = [p.strip() for p in paragraphs]
            changes["origin"] = post_store.MANUAL
        if "image" in given:
            if body.image is None or post_images.resolve(config.post.image_dir, body.image) is None:
                return JSONResponse({"detail": "không có ảnh này trong thư viện"}, status_code=404)
            changes["image"] = body.image
        if "link" in given:
            try:
                changes["link"] = post_logic.normalize_link(body.link)
            except post_logic.LinkError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
        order = [cid for cid, _ in post_stage.rendered_clip_ids(config, episode_id)]
        proposed: int | None = None
        with post_lock:
            try:
                doc = post_store.read_posts(ctx.posts_path(episode_id), episode_id)
                old_paragraphs = post_store.find(doc, clip)["paragraphs"] if post_store.find(doc, clip) else None
                now = ctx.post_now()
                doc = post_store.with_fields(doc, order, clip, changes, now=now)
            except post_store.PostsError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            post_store.write(ctx.posts_path(episode_id), doc)
            if "paragraphs" in given and old_paragraphs is not None:
                proposed = _learn_corrections(episode_id, clip, old_paragraphs, changes["paragraphs"], now)
        entry = post_store.find(doc, clip)
        try:
            ep_src = post_source.load(episode_id, config)
        except post_source.PostSourceError:
            ep_src = None
        title = None
        try:
            title = next((c["title"] for c in list_titles(episode_id, config)["clips"] if c["clip_id"] == clip), None)
        except ReviewError:
            pass
        header_fields = ctx.post_header_fields(episode_id)
        series, tags = ctx.post_series_and_tags(episode_id)
        log.info("web: post %s [%s] sửa %s", clip, episode_id, ", ".join(sorted(given)))
        view = ctx.post_entry_view(entry, ep_src=ep_src, title=title, header_fields=header_fields,
                                hashtags_list=review_hashtags(series, tags))
        if "paragraphs" in given:
            view["proposed"] = proposed  # CP8.18 D5 (null: the dictionary failed, the post was still saved)
        return view

    @app.post("/api/episodes/{episode_id}/posts/{clip}/posted")
    def api_posts_posted(episode_id: str, clip: str, body: PublishedIn):
        """P8: tick / untick "Đã đăng bài" — độc lập với "Đã đăng" Short (``publish.json``); được cả khi job
        đang chạy."""
        if (bad := _check_clip(episode_id, clip)) is not None:
            return bad
        order = [cid for cid, _ in post_stage.rendered_clip_ids(config, episode_id)]
        with post_lock:
            try:
                doc = post_store.read_posts(ctx.posts_path(episode_id), episode_id)
                doc = post_store.with_posted(doc, order, clip, body.value, now=ctx.post_now())
            except post_store.PostsError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            post_store.write(ctx.posts_path(episode_id), doc)
        entry = post_store.find(doc, clip)
        log.info("web: post %s [%s] %s \"Đã đăng bài\"", clip, episode_id, "tick" if body.value else "untick")
        return {"clip_id": clip, "posted": entry["posted_at"] is not None, "posted_at": entry["posted_at"]}

    @app.delete("/api/episodes/{episode_id}")
    def api_episode_delete(episode_id: str):
        """X3: delete work/<id>/ and output/<id>/ (cannot be undone); 409 while a job of the episode is
        queued/running; unknown / invalid id -> 404."""
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        with submit_lock:
            runner.drop_parked(episode_id)  # CP13.1b: a job only waiting for its HD source does not block the deletion
            current = ctx.restore_job(episode_id)
            if current is None or not current.active:
                current = runner.latest(episode_id)
            if current is None or not current.active:
                current = runner.latest_post(episode_id)  # CP8.16 R3: a compose job also blocks the deletion
            if current is None or not current.active:
                current = runner.latest_enhance(episode_id)  # CP13.1b: so does the assembly of the HD source
            if current is not None and current.active:
                return JSONResponse({"detail": "episode đang có job chạy/đợi; xóa sau khi job xong",
                                     "job": ctx.job_view(current)}, status_code=409)
            try:  # CP8.33 G11: the hearted clips of a khai thị episode are kept; a failure here deletes nothing
                undo_keep = compilations.keep_favorites(episode_id)
            except CompilationError as exc:
                log.error("web: delete episode %s: %s", episode_id, exc)
                return JSONResponse({"detail": str(exc)}, status_code=500)
            try:
                removed = delete_episode(episode_id, config)
            except EpisodeNotFound:
                undo_keep()
                return JSONResponse({"detail": "không có episode này"}, status_code=404)
            except (ReviewError, OSError) as exc:
                undo_keep()
                log.error("web: delete episode %s failed: %s", episode_id, exc)
                return JSONResponse({"detail": f"không xóa được: {exc}"}, status_code=500)
            runner.forget(episode_id)
            storage.invalidate()
            playlists.invalidate(episode_id)
        log.warning("web: deleted episode %s (%s)", episode_id, ", ".join(str(p) for p in removed))
        return {"deleted": episode_id}

    # --- CP13.1b: enhance, web side (cookie) ------------------------------------------------------------------

    def _enhance_view(episode_id: str) -> dict:
        view = svc.episode_view(episode_id)
        if view.get("exists"):
            rm = ep.render_manifest(config, episode_id)
            doc = enh_state.read(Path(config.workspace.dir) / episode_id) or {}
            view["rendered"] = rm is not None
            view["rendered_from_hd"] = bool(rm and doc.get("source_hd_sha256")
                                            and rm.get("source_sha256") == doc.get("source_hd_sha256"))
            view["can_rerender"] = bool(view.get("hd_ready") and rm is not None and not view["rendered_from_hd"])
            view["can_redo"] = bool(view.get("state") == "done" and view.get("hd_old_config"))  # CP13.4 G3
        job = runner.latest_enhance(episode_id)
        view["assembling_job"] = job.status if job is not None and job.active else None
        return view

    def _enhance_episode(episode_id: str) -> JSONResponse | None:
        if (bad := _episode_or_404(episode_id)) is not None:
            return bad
        if not (Path(config.workspace.dir) / episode_id / "manifest.json").is_file():
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        return None

    @app.post("/api/episodes/{episode_id}/enhance")
    def api_episode_enhance(episode_id: str, body: EnhanceSwitchIn):
        """E1 / E10 "Bật / Tắt enhance" (the whole video: Short + khai thị). Off while waiting for HD -> the render runs at
        once from the original source."""
        if (bad := _enhance_episode(episode_id)) is not None:
            return bad
        try:
            doc = svc.set_wanted(episode_id, body.enabled)
        except EnhanceError as exc:
            return ctx.enh_error(exc, error_response=JSONResponse)
        owner = doc.get("follows") or episode_id
        done = None
        if not body.enabled:
            done = {part: _release_hd(part) for part in enh_state.video_parts(config, owner)}
        elif doc.get("state") == enh_state.ASSEMBLING:
            _enhance_complete(owner)
        elif doc.get("state") == enh_state.DONE:
            _hd_ready(owner)
        log.info("web: enhance %s [%s]%s", "on" if body.enabled else "off", episode_id,
                 f" -> {done}" if done else "")
        return {"enhance": _enhance_view(episode_id)}

    @app.post("/api/episodes/{episode_id}/enhance/render-original")
    def api_episode_render_original(episode_id: str):
        """E6 "Render bằng bản gốc": turn enhance off for the video and render now from the original source."""
        if (bad := _enhance_episode(episode_id)) is not None:
            return bad
        try:
            doc = svc.set_wanted(episode_id, False)
        except EnhanceError as exc:
            return ctx.enh_error(exc, error_response=JSONResponse)
        outcome = {part: _release_hd(part, force_render=part == episode_id)
                   for part in enh_state.video_parts(config, doc.get("follows") or episode_id)}
        log.info("web: render bằng bản gốc [%s]: %s", episode_id, outcome)
        return {"enhance": _enhance_view(episode_id), "outcome": outcome}

    @app.post("/api/episodes/{episode_id}/enhance/redo")
    def api_episode_enhance_redo(episode_id: str):
        """CP13.4 G3 "Enhance lại": queue the video again with the current ``[enhance]`` configuration (the previous HD
        source stays in use until the new one is assembled; no render until then)."""
        if (bad := _enhance_episode(episode_id)) is not None:
            return bad
        try:
            svc.redo(episode_id)
        except EnhanceError as exc:
            return ctx.enh_error(exc, error_response=JSONResponse)
        log.info("web: enhance lại [%s]", episode_id)
        return {"enhance": _enhance_view(episode_id)}

    @app.post("/api/episodes/{episode_id}/vertical/cancel")
    def api_episode_vertical_cancel(episode_id: str):
        """CP8.32 V4: cancel the queued / running vertical job of this video (a ``.kt`` id means its video)."""
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        owner = ep.hd_owner(episode_id)
        cancelled = runner.cancel_vertical({owner})
        if not cancelled:
            return JSONResponse({"detail": "tập này không có bản dọc đang chờ / đang chạy"}, status_code=409)
        log.info("web: hủy bản dọc [%s]", owner)
        return {"episode_id": owner, "cancelled": len(cancelled)}

    @app.post("/api/episodes/{episode_id}/enhance/rerender")
    def api_episode_rerender_hd(episode_id: str):
        """E6 "Render lại bản HD" (Shorts already ticked "Đã đăng" were kept): render job from the HD source."""
        if (bad := _enhance_episode(episode_id)) is not None:
            return bad
        view = _enhance_view(episode_id)
        if not view.get("hd_ready"):
            return JSONResponse({"detail": "chưa có bản HD"}, status_code=409)
        with submit_lock:
            if (busy := _busy(episode_id)) is not None:
                return busy
            if is_archived(Path(config.workspace.dir) / episode_id):
                return JSONResponse({"detail": str(ArchivedError(episode_id))}, status_code=409)
            job, _ = runner.submit(episode_id, KIND_RENDER, render_target(config, render=render))
        log.info("web: render lại bản HD [%s] -> job %s", episode_id, job.id)
        return JSONResponse({"job": ctx.job_view(job), "enhance": _enhance_view(episode_id)}, status_code=202)

    # --- CP8.27: HD video download + vertical full-episode version ---------------------------------------------

    def _hd_or_404(episode_id: str, *, archived_ok: bool = False) -> tuple[Path | None, JSONResponse | None]:
        """The landscape file (``source_hd.mp4`` or, CP8.32 V1, the original >= 720p) or a 404. ``archived_ok`` (the
        vertical routes, V2): an archived original that can be fetched again also passes (the path is then None)."""
        if not ep.valid_episode_id(episode_id):
            return None, JSONResponse({"detail": "không có episode này"}, status_code=404)
        src = ep.hd_source(config, episode_id)
        if src is None or (src.path is None and not archived_ok):
            return None, JSONResponse({"detail": "chưa có bản HD của video này"}, status_code=404)
        return src.path, None

    @app.get("/api/episodes/{episode_id}/source-hd")
    def api_episode_source_hd(episode_id: str, dl: str | None = None):
        """H1: the landscape HD video (``source_hd.mp4``, no banner); Range supported (FileResponse). A download never
        ticks "Đã đăng" / "Đã xem" (H3)."""
        hd, bad = _hd_or_404(episode_id)
        if bad is not None:
            return ctx.tracked(dl, bad)
        return ctx.tracked(dl, FileResponse(hd, media_type=mimetypes.guess_type(hd.name)[0] or "video/mp4", headers={
            "Content-Disposition": content_disposition(ep.hd_download_name(config, episode_id)),
            "Cache-Control": "private, no-cache"}))

    @app.get("/api/episodes/{episode_id}/vertical")
    def api_episode_vertical(episode_id: str, dl: str | None = None):
        """H4: the vertical full-episode file, once made from the current HD source."""
        _hd, bad = _hd_or_404(episode_id, archived_ok=True)
        if bad is not None:
            return ctx.tracked(dl, bad)
        owner = ep.hd_owner(episode_id)
        path = render_full.ready_file(config, owner) if render_full.current(config, owner) else None
        if path is None:
            return ctx.tracked(dl, JSONResponse({"detail": "chưa có bản dọc (bấm \"Tạo bản dọc\")"}, status_code=404))
        return ctx.tracked(dl, FileResponse(path, media_type="video/mp4", headers={
            "Content-Disposition": content_disposition(ep.video_download_name(config, episode_id, "Doc")),
            "Cache-Control": "private, no-cache"}))

    @app.post("/api/episodes/{episode_id}/vertical")
    def api_episode_vertical_make(episode_id: str):
        """H4 "Tạo bản dọc": queue a render-lane job (reuses the file when nothing changed); 404 without an HD source
        (CP8.32: ``source_hd.mp4`` or the original >= 720p; an archived original is downloaded again by the job)."""
        _hd, bad = _hd_or_404(episode_id, archived_ok=True)
        if bad is not None:
            return bad
        owner = ep.hd_owner(episode_id)
        with submit_lock:
            restoring = ctx.restore_job(owner)
            if restoring is not None and restoring.active:
                return JSONResponse({"detail": "đang khôi phục nguồn; tạo bản dọc sau khi xong",
                                     "job": ctx.job_view(restoring)}, status_code=409)
            job, created = runner.submit(owner, KIND_VERTICAL, ctx.vertical_target(owner))
        log.info("web: bản dọc [%s] -> job %s%s", owner, job.id, "" if created else " (đã có)")
        return JSONResponse({"job": ctx.job_view(job, logs=False), "hd_video": _hd_video_view(episode_id)},
                            status_code=202 if created else 200)

    # --- Đọc Kinh (SR1): router of the sutra application, protected by the auth middleware above ---

    app.include_router(sutra_web.router(SutraStore(Path(config.workspace.dir) / "_sutras"), STATIC_DIR))

    @app.post("/api/episodes/{episode_id}/restore-source")
    def api_restore_source(episode_id: str):
        if not ep.valid_episode_id(episode_id) or not (Path(config.workspace.dir) / episode_id).is_dir():
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        owner = ep.hd_owner(episode_id)
        with submit_lock:
            current = ctx.restore_job(owner)
            if current is not None and current.active:
                return JSONResponse({"job": ctx.job_view(current), "created": False}, status_code=200)
            if not is_archived(Path(config.workspace.dir) / episode_id):
                return JSONResponse({"detail": "tập chưa dọn video nguồn"}, status_code=409)
            busy = next((j for j in runner.jobs() if j.active and ep.hd_owner(j.episode_id) == owner), None)
            if busy is not None:
                return JSONResponse({"detail": "video đang có job chạy/đợi; khôi phục sau khi xong",
                                     "job": ctx.job_view(busy)}, status_code=409)
            try:
                restore_parts(episode_id, config)
            except (ReviewError, OSError) as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            job, created = runner.submit(owner, KIND_RESTORE_SOURCE, _restore_target(episode_id))
        return JSONResponse({"job": ctx.job_view(job), "created": created}, status_code=202 if created else 200)

    @app.post("/api/episodes/{episode_id}/archive")
    def api_archive(episode_id: str):
        """S3: delete the downloaded source video, keep the Shorts; 409 while a job of the episode is
        queued/running; 422 local source / render not done; 404 unknown id."""
        if not ep.valid_episode_id(episode_id) or not (Path(config.workspace.dir) / episode_id).is_dir():
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        with submit_lock:
            current = ctx.restore_job(episode_id)
            if current is None or not current.active:
                current = runner.latest(episode_id)
            if current is not None and current.active:
                return JSONResponse({"detail": "episode đang có job chạy/đợi; dọn sau khi job xong",
                                     "job": ctx.job_view(current)}, status_code=409)
            try:
                result = archive_source(episode_id, config)
            except ReviewError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=422)
            storage.invalidate()
        log.warning("web: archived %s: removed %s (%d bytes)", episode_id, ", ".join(result.removed) or "-",
                    result.freed)
        return {"archived": episode_id, "changed": result.changed, "freed": result.freed, "removed": result.removed}

    app.include_router(auth.build(ctx))
    app.include_router(pages.build(ctx))
    app.include_router(status.build(ctx))
    app.include_router(reading_api.build(ctx))
    app.include_router(files.build(ctx))
    app.include_router(playlist_routes.build(ctx))
    app.include_router(enhance.build(ctx))
    app.include_router(post_images_routes.build(ctx))
    app.include_router(post_corrections_routes.build(ctx))

    theme_index_web.register(app, config, playlists, STATIC_DIR)  # TC-WEB1: GET-only TC1 preview
    theme_plan_web.register(app, theme_plans)  # TC2 phase C: planner and TC3 landscape jobs

    app.include_router(files_catchall.build(ctx))  # D4: catch-all is always registered last.

    return app
