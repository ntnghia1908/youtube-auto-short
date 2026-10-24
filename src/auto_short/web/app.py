"""FastAPI app factory (W2, W4, W6, W7). Contract: docs/decisions/CP8.3-web-contract.md."""

from __future__ import annotations

import asyncio
import logging
import shutil
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import khaithi
from ..config import Config, whisper_threads_per_job
from ..enhance import state as enh_state
from ..enhance.service import EnhanceService
from ..enhance.tokens import tokens_from_env
from ..pipeline import ollama_preflight, run_pipeline
from ..sutra import web as sutra_web
from ..sutra.store import SutraStore
from ..post import (
    source as post_source,
    stage as post_stage,
    store as post_store,
)
from ..render import run_render, full as render_full
from ..selection.client import resolve_host
from ..review import (
    ReviewError,
    archive_source,
    is_archived,
)
from ..review.archive import restore_parts, restore_source
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
    episodes as episode_routes,
    episode_edit,
)
from . import (
    episodes as ep,
    compilations as comp_web,
    downloads as dl_mod,
    monitor as monitor_mod,
    theme_index as theme_index_web,
    theme_plan as theme_plan_web,
    packaging as packaging_web,
    episode_thumbs as episode_thumbs_web,
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
from .playlists import LIST_TIMEOUT, PlaylistStore, ytdlp_list

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
AUTO_ARCHIVE_INTERVAL = 300.0  # seconds between auto clean-up passes (W9 S5)
QUEUE_FILE = ".web_queue.json"  # CP8.22 Q2: saved job queue, in the workspace dir next to ``.web_secret``
ENHANCE_PREFIX = "/api/enhance/"  # CP13.1 E8: worker routes, token auth (no cookie); the one exception is below
ENHANCE_UI_PATHS = {"/api/enhance/status"}  # read-only status for the UI: cookie, like every other web route


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
        if kind in (theme_plan_web.KIND_GENERATE, theme_plan_web.KIND_THEME_RENDER,
                    packaging_web.KIND, episode_thumbs_web.KIND):
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
    packages = packaging_web.Packages(theme_plans)
    episode_thumbs = episode_thumbs_web.EpisodeThumbs(theme_plans)
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
    app.state.packages = packages
    app.state.episode_thumbs = episode_thumbs
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
        render=render,
        titler=titler,
        enhance_complete=_enhance_complete,
        hd_ready=_hd_ready,
        release_hd=_release_hd,
        restore_target=_restore_target,
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

    # --- Đọc Kinh (SR1): router of the sutra application, protected by the auth middleware above ---

    app.include_router(sutra_web.router(SutraStore(Path(config.workspace.dir) / "_sutras"), STATIC_DIR))

    app.include_router(auth.build(ctx))
    app.include_router(pages.build(ctx))
    app.include_router(status.build(ctx))
    app.include_router(reading_api.build(ctx))
    app.include_router(files.build(ctx))
    app.include_router(playlist_routes.build(ctx))
    app.include_router(enhance.build(ctx))
    app.include_router(post_images_routes.build(ctx))
    app.include_router(post_corrections_routes.build(ctx))
    app.include_router(episode_routes.build(ctx))
    app.include_router(episode_edit.build(ctx))

    theme_index_web.register(app, config, playlists, STATIC_DIR)  # TC-WEB1: GET-only TC1 preview
    theme_plan_web.register(app, theme_plans)  # TC2 phase C: planner and TC3 landscape jobs

    packaging_web.register(app, packages)  # PKG1: offline thumbnails and manual approval
    episode_thumbs_web.register(app, episode_thumbs)

    app.include_router(files_catchall.build(ctx))  # D4: catch-all is always registered last.

    return app
