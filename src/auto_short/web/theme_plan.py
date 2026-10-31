"""TC2 phase C: thematic plans, lane targets and authenticated web routes.

Read views share one TC1 audit with TC2 list_plans. Reads and video hashing do
not hold the service write/submit lock.
"""
from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr

from .. import hashing, theme_index, theme_plan, theme_render
from ..compilation import store
from ..config import Config
from ..ingest.youtube import DownloadError, YoutubeBlocked, is_blocked_message
from ..pipeline import OllamaUnavailable, PreflightError
from ..render import RenderError
from ..render.full import SourceBlocked
from ..review import content_disposition
from ..selection.client import ChatError, ChatUnavailable
from ..store import index_cache
from ..store.client import StoreClient, StoreError
from ..theme_render import sources
from .jobs import AI, PREPARE, RENDER, GpuUnavailable, JobFailed, JobRunner, Step, YoutubeWait, run_preflight
from .playlists import PlaylistError, PlaylistStore
from .theme_index import GENERATION_DISABLED, RefusingClient, project_record, redact
from .urls import valid_playlist_id

KIND_GENERATE, KIND_THEME_RENDER = "theme_plan", "theme_render"
PLAN_ID = re.compile(r"[a-z0-9]{8,32}")
FILE_NAME = re.compile(r"([a-z0-9]{8,32})-r([1-9][0-9]{0,9})\.mp4")
SHA = re.compile(r"[a-f0-9]{64}")


def source_videos(plan):
    """Count/download each original once, even when several clips use it."""
    return sorted({sources._owner(c["episode_id"]) for c in plan.get("clips", [])})


def youtube_blocked(exc):
    # Match SRC2's signed-media 403 policy without changing ingest globally.
    return isinstance(exc, (YoutubeBlocked, SourceBlocked)) or is_blocked_message(str(exc)) or bool(
        re.search(r"\b(?:HTTP(?: Error)?\s*:?\s*)403\b", str(exc), re.I))


def local_source_ready(config, video_id):
    """Display hint only: stat + provenance/size metadata; render still verifies sha256."""
    try:
        folder = (Path(config.workspace.dir) / video_id).resolve()
        source = sources._source(config, video_id)
        name = source.get("path")
        if isinstance(name, str):
            path = (folder / name).resolve()
            if path.is_relative_to(folder) and path.is_file() and path.stat().st_size > 0 \
                    and isinstance(source.get("sha256"), str) and SHA.fullmatch(source["sha256"]):
                return True
    except (RenderError, OSError, TypeError, ValueError):
        pass
    try:
        source = sources._source(config, video_id)
        expected = sources._duration(config, video_id)
        folder = (sources.cache_dir(config) / video_id).resolve()
        meta = sources._read(folder / "meta.json")
        name = meta.get("file")
        if not isinstance(name, str) or not re.fullmatch(r"source\.[A-Za-z0-9]+", name):
            return False
        path = (folder / name).resolve()
        if meta.get("schema_version") != 1 or meta.get("video_id") != video_id \
                or not isinstance(meta.get("uri"), str) or not meta["uri"] or meta["uri"] != source.get("uri") \
                or not isinstance(meta.get("ingest_sha256"), str) or not meta["ingest_sha256"] \
                or meta["ingest_sha256"] != source.get("sha256") \
                or not isinstance(meta.get("sha256"), str) or not SHA.fullmatch(meta["sha256"]) \
                or not isinstance(meta.get("differs_from_ingest"), bool) \
                or meta["differs_from_ingest"] != (meta["sha256"] != source.get("sha256")) \
                or not sources._positive(meta.get("height")) or not sources._positive(meta.get("size")) \
                or not sources._matches_duration(meta.get("duration"), expected):
            return False
        datetime.strptime(meta["downloaded_at"], "%Y-%m-%dT%H:%M:%SZ")
        return path.parent == folder and path.is_file() and path.stat().st_size == meta["size"]
    except (RenderError, OSError, KeyError, TypeError, ValueError):
        return False


def generate_key(pid):
    return f"theme:{pid}"


def render_key(pid, plan_id):
    return f"theme-render:{pid}:{plan_id}"


def safe(value):
    """Use TC-WEB1 redaction for every artifact/error string, including nested data."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [safe(v) for v in value]
    if isinstance(value, dict):
        return {redact(k): safe(v) for k, v in value.items()}
    return value


def job_view(job):
    if job is None:
        return None
    return safe({**job.to_dict(logs=False), "active": job.active})


class GenerateTarget:
    def __init__(self, service, pid):
        self.service, self.pid, self.result = service, pid, None

    def __call__(self, job):
        job.stage = "theme_plan"
        try:
            if self.service.preflight is not None:
                run_preflight(job, self.service.preflight, self.service.config)
            self.result = theme_plan.propose(self.service.config, self.pid)
            if self.result.get("shortfall") and self.result.get("index_counts", {}).get("by_status", {}).get("ai_error"):
                if self.service.preflight is not None:
                    run_preflight(job, self.service.preflight, self.service.config)
                if re.search(r"connection|cannot reach|refused|unreachable", self.result["shortfall"], re.I):
                    raise GpuUnavailable("Đang chờ GPU / Ollama kết nối lại")
            if self.result.get("ai_error"):
                raise JobFailed(redact(self.result["ai_error"]))
        except (OllamaUnavailable, ChatUnavailable) as exc:
            raise GpuUnavailable(redact(f"Đang chờ Ollama: {exc}")) from exc
        except ChatError as exc:
            # Older/injected clients can report a connection failure as plain ChatError.
            if re.search(r"connection|cannot reach|refused|unreachable", str(exc), re.I):
                raise GpuUnavailable(redact(f"Đang chờ Ollama: {exc}")) from exc
            raise JobFailed(redact(f"AI gợi ý lỗi: {exc}")) from exc
        except (PreflightError, theme_plan.PlanError, theme_index.IndexError, OSError) as exc:
            raise JobFailed(redact(f"AI gợi ý lỗi: {exc}")) from exc
        job.stage = None
        job.summary = redact(self.result.get("shortfall") or f"{len(self.result['proposals'])} chủ đề")

    def lane_steps(self):
        return [Step(AI, self)]

    def spec(self):
        return {"playlist_id": self.pid}


class RenderTarget:
    def __init__(self, service, pid, plan):
        self.service, self.pid, self.plan = service, pid, plan
        self.youtube_wait = False

    def needs_download(self):
        # Called with the scheduler lock held: no network or media hashing here.
        # The store snapshot lets store-only sources bypass YouTube backoff; HEAD belongs to prepare.
        # A stat hint may look ready while the prepare hash rejects corrupt bytes.
        if self.youtube_wait:
            return True
        store_videos = index_cache.source_ids(self.service.config, blocking=False)
        return any(not local_source_ready(self.service.config, vid) and vid not in store_videos
                   for vid in source_videos(self.plan))

    def current_plan(self):
        current = theme_plan.approved_plan(self.service.config, self.pid, self.plan["plan_id"])
        if theme_plan.plan_fingerprint(current) != theme_plan.plan_fingerprint(self.plan):
            raise theme_plan.PlanConflict("kế hoạch đã thay đổi, cần xuất lại")
        return current

    def prepare(self, job):
        job.stage = "theme_sources"
        self.youtube_wait = False
        config = self.service.config
        try:
            for video_id in source_videos(self.current_plan()):
                if sources.workspace_source(config, video_id) or sources.cached_source(config, video_id):
                    continue
                if config.store.enabled:
                    try:
                        StoreClient.from_config(config.store).head(video_id, "source")
                        continue  # SRC1 borrows into the render job's temporary directory.
                    except (StoreError, OSError):
                        pass
                sources.fetch_to_cache(config, video_id)
                if getattr(job, "youtube_ok", None) is not None:
                    job.youtube_ok()
        except (DownloadError, SourceBlocked, RenderError) as exc:
            if youtube_blocked(exc):
                self.youtube_wait = True
                raise YoutubeWait(redact(f"Chuẩn bị nguồn: {exc}")) from exc
            raise JobFailed(redact(f"Chuẩn bị nguồn lỗi: {exc}")) from exc
        except (theme_plan.PlanError, theme_index.IndexError, OSError) as exc:
            raise JobFailed(redact(f"Chuẩn bị nguồn lỗi: {exc}")) from exc
        job.stage = None

    def __call__(self, job):
        job.stage = "theme_render"
        try:
            self.current_plan()
            doc = self.service.playlists.load(self.pid)
            hashtags = self.service.playlists.effective_hashtags(doc)[0]
            result = theme_render.render_landscape(self.service.config, self.pid, self.plan["plan_id"],
                                                   hashtags=hashtags)
        except (SourceBlocked, DownloadError, RenderError) as exc:
            if youtube_blocked(exc):
                raise JobFailed("Nguồn chưa sẵn sàng, bấm Ghép lại") from exc
            raise JobFailed(redact(f"Xuất video lỗi: {exc}")) from exc
        except (theme_plan.PlanError, theme_index.IndexError, OSError) as exc:
            raise JobFailed(redact(f"Xuất video lỗi: {exc}")) from exc
        job.stage = None
        job.summary = f"Video ngang {result.metadata['duration'] / 60:.1f} phút"

    def lane_steps(self):
        return [Step(PREPARE, self.prepare), Step(RENDER, self)]

    def spec(self):
        return {"playlist_id": self.pid, "plan_id": self.plan["plan_id"], "revision": self.plan["revision"]}


class ThemePlans:
    def __init__(self, config: Config, playlists: PlaylistStore, runner: JobRunner, *, preflight=None):
        self.config, self.playlists, self.runner, self.preflight = config, playlists, runner, preflight
        self.lock = threading.RLock()

    def source_counts(self, plan, store_videos):
        if plan.get("check", {}).get("state") == "invalid":
            return {"total": 0, "ready": 0, "store": 0, "youtube": 0}
        videos = source_videos(plan)
        local = {vid for vid in videos if local_source_ready(self.config, vid)}
        remote = (set(videos) - local) & store_videos
        ready = len(local) + len(remote)
        return {"total": len(videos), "ready": ready, "store": len(remote), "youtube": len(videos) - ready}

    def checked(self, pid):
        if not valid_playlist_id(pid):
            return response({"detail": "không có bộ kinh này"}, 404)
        try:
            if self.playlists.load(pid) is None:
                return response({"detail": "không có bộ kinh này"}, 404)
        except PlaylistError:
            return response({"detail": "dữ liệu bộ kinh không hợp lệ"}, 422)
        return None

    def busy(self, pid, plan_id):
        job = self.runner.latest(render_key(pid, plan_id))
        return job is not None and job.active

    def plans(self, pid, *, index=None):
        return theme_plan.list_plans(self.config, pid, index=index)

    def find(self, pid, plan_id):
        if not PLAN_ID.fullmatch(plan_id):
            raise MissingPlan()
        plan = next((p for p in self.plans(pid) if p.get("plan_id") == plan_id), None)
        if plan is None:
            raise MissingPlan()
        if plan["check"]["state"] == "invalid":
            raise BrokenArtifact()
        return plan

    def output(self, pid, plan, *, verify=False):
        """Only the completed file for this approved revision and fingerprint is exposed.

        Hash media at download time; status polling reads metadata only.
        """
        if plan.get("check", {}).get("state") != "approved":
            return None
        name = f"{plan['plan_id']}-r{plan['revision']}.mp4"
        if not FILE_NAME.fullmatch(name):
            return None
        folder = store.directory(self.config.render.output_dir, pid) / "theme"
        path = folder / name
        if not path.is_file() or path.is_symlink() or path.with_suffix(".json").is_symlink():
            return None
        try:
            doc = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or doc.get("schema_version") != theme_render.SCHEMA_VERSION \
                    or doc.get("plan_id") != plan["plan_id"] or doc.get("revision") != plan["revision"] \
                    or doc.get("plan_fingerprint") != theme_plan.plan_fingerprint(
                        {k: v for k, v in plan.items() if k != "check"}) \
                    or not isinstance(doc.get("sha256"), str) or not SHA.fullmatch(doc["sha256"]) \
                    or not isinstance(doc.get("encode_key"), str) or not doc["encode_key"] \
                    or not isinstance(doc.get("download_name"), str) or not doc["download_name"] \
                    or not isinstance(doc.get("description"), str) \
                    or isinstance(doc.get("duration"), bool) or not isinstance(doc.get("duration"), (int, float)) \
                    or not math.isfinite(doc["duration"]) or doc["duration"] <= 0:
                return None
            if verify and hashing.sha256_file(path) != doc["sha256"]:
                return None
        except (OSError, ValueError, TypeError):
            return None
        return path, doc

    def labels(self, records):
        """Titles are display-only; record identities have already passed TC1 validation."""
        manifests, titles, labels = {}, {}, {}
        for r in records:
            if r.get("status") != "indexed":
                continue
            ident = r["identity"]
            eid, clip = ident["episode_id"], ident["clip"]
            if eid not in manifests:
                for cache, path in ((manifests, Path(self.config.render.output_dir) / eid / "render_manifest.json"),
                                    (titles, Path(self.config.workspace.dir) / eid / "titles.json")):
                    try:
                        doc = json.loads(path.read_text(encoding="utf-8"))
                        cache[eid] = doc if isinstance(doc, dict) else {}
                    except (OSError, ValueError):
                        cache[eid] = {}
            short = next((s for s in manifests[eid].get("shorts", []) if s.get("clip_id") == clip), {})
            episode = ((titles[eid].get("header") or {}).get("fields") or {}).get("episode") or eid
            labels[f"{eid}/{clip}"] = f"{short.get('title') or clip} · Tập {episode}"
        return labels

    def view(self, pid):
        index = theme_index.build_index(self.config, pid, write=False, client=RefusingClient())
        records = [project_record(self.config, r) for r in index["records"]]
        counts = Counter(r.get("status") for r in records)
        # Preview never calls AI: valid khai thi clips that only await indexing are "pending", not unusable.
        awaiting = [r for r in records if r.get("status") == "ai_error" and r.get("reason") == GENERATION_DISABLED]
        reasons = Counter(r.get("reason") or r.get("status") for r in records
                          if r.get("status") != "indexed" and r not in awaiting)
        labels = self.labels(records)
        durations = {f"{r['identity']['episode_id']}/{r['identity']['clip']}": r["duration"]
                     for r in records if r.get("status") == "indexed"}
        generate = self.runner.latest(generate_key(pid))
        proposals = theme_plan.read_proposals(self.config, pid)
        # Failed AI validation deliberately leaves the last good artifact untouched.
        # Keep the latest attempt visible without writing it from GET.
        if generate is not None and getattr(generate.target, "result", None) is not None:
            proposals = generate.target.result
        if proposals is not None:
            if not isinstance(proposals.get("proposals"), list) or not isinstance(proposals.get("rejected_themes"), list):
                raise BrokenArtifact()
            for proposal in proposals["proposals"]:
                if not isinstance(proposal, dict) or not all(isinstance(proposal.get(k), str) for k in
                        ("proposal_id", "label", "rationale")) or not isinstance(proposal.get("clips"), list) \
                        or not isinstance(proposal.get("total_duration"), (int, float)):
                    raise BrokenArtifact()
        out_plans = []
        store_videos = index_cache.source_ids(self.config, blocking=False)
        for plan in self.plans(pid, index=index):
            view = safe(plan)
            view.update(store.published_status(store.directory(self.config.render.output_dir, pid),
                                               "theme", plan.get("plan_id", ""), plan.get("revision")))
            output = self.output(pid, plan)
            view["render_job"] = job_view(self.runner.latest(render_key(pid, plan.get("plan_id"))))
            view["output"] = None
            view["sources"] = self.source_counts(plan, store_videos)
            if output is not None:
                _, meta = output
                view["output"] = {**safe(meta), "download_url":
                    f"/files/playlists/{pid}/theme/{plan['plan_id']}-r{plan['revision']}.mp4"}
            out_plans.append(view)
        return {"index_summary": safe({"total": len(records), "usable": counts["indexed"],
                    "pending": len(awaiting), "unusable": len(records) - counts["indexed"] - len(awaiting),
                    "by_status": dict(counts),
                    "source_missing": sum(r.get("source_status") == "missing" for r in records),
                    "common_reasons": [{"reason": why, "count": n} for why, n in reasons.most_common(3)]}),
                "generate_job": job_view(generate), "proposals": safe(proposals), "plans": out_plans,
                "clips_available": safe([{"id": cid, "label": label,
                    "duration": durations[cid]} for cid, label in labels.items()])}

    def generate(self, pid):
        with self.lock:
            return self.runner.submit(generate_key(pid), KIND_GENERATE, GenerateTarget(self, pid))

    def render(self, pid, plan_id):
        with self.lock:
            job = self.runner.latest(render_key(pid, plan_id))
            if job is not None and job.active:
                return job, False
            self.find(pid, plan_id)
            plan = theme_plan.approved_plan(self.config, pid, plan_id)
            return self.runner.submit(render_key(pid, plan_id), KIND_THEME_RENDER, RenderTarget(self, pid, plan))


class MissingPlan(Exception):
    pass


class BrokenArtifact(Exception):
    pass


class CreateIn(BaseModel):
    proposal_id: StrictStr = Field(max_length=200)


class EditIn(BaseModel):
    revision: StrictInt = Field(ge=1)
    title: StrictStr = Field(max_length=120)
    clip_ids: list[StrictStr] = Field(min_length=1, max_length=500)


class ApproveIn(BaseModel):
    revision: StrictInt = Field(ge=1)
    duration_override: StrictBool = False


class VideoPublishedIn(BaseModel):
    kind: Literal["compilation", "theme"]
    id: StrictStr
    published: StrictBool


def response(data, status=200):
    return JSONResponse(safe(data), status_code=status, headers={"Cache-Control": "no-store"})


def register(app: FastAPI, service: ThemePlans):
    # Include validation failures (handled by FastAPI) in the API no-store policy.
    @app.middleware("http")
    async def no_store(request: Request, call_next):
        result = await call_next(request)
        if re.fullmatch(r"/api/playlists/[^/]+/theme-(?:plan|plans)(?:/.*)?", request.url.path):
            result.headers["Cache-Control"] = "no-store"
        return result

    def invoke(pid, action, *, conflict=False, write=True):
        error = service.checked(pid)
        if error is not None:
            return error
        try:
            if write:
                with service.lock:
                    return action()
            return action()
        except MissingPlan:
            return response({"detail": "không có kế hoạch này"}, 404)
        except BrokenArtifact:
            return response({"detail": "dữ liệu kế hoạch bị hỏng"}, 422)
        except theme_plan.PlanConflict:
            return response({"detail": "đã có thay đổi khác, tải lại"}, 409)
        except theme_plan.PlanError as exc:
            msg = str(exc)
            status = 422 if msg.startswith(("cannot read", "invalid theme_proposals")) else (409 if conflict else 400)
            return response({"detail": msg}, status)
        except (store.CompilationError, theme_index.IndexError, OSError, ValueError, KeyError, TypeError):
            return response({"detail": "dữ liệu chủ đề không hợp lệ; không thể kiểm tra"}, 422)

    base = "/api/playlists/{pid}"

    @app.post(base + "/videos/published")
    def published(pid: str, body: VideoPublishedIn):
        def action():
            folder = store.directory(service.config.render.output_dir, pid)
            with store.publish_lock:
                revision = None
                if body.kind == "compilation":
                    if store.read_doc(folder, body.id) is None:
                        return response({"detail": "không có video ghép này"}, 404)
                else:
                    revision = service.find(pid, body.id)["revision"]
                return response(store.set_published(folder, body.kind, body.id, body.published, revision))
        return invoke(pid, action)

    @app.get(base + "/theme-plan")
    def get(pid: str):
        return invoke(pid, lambda: JSONResponse(service.view(pid), headers={"Cache-Control": "no-store"}), write=False)

    @app.post(base + "/theme-plan/generate")
    def generate(pid: str):
        def action():
            job, created = service.generate(pid)
            return response({"job": job_view(job), "created": created}, 202 if created else 200)
        return invoke(pid, action)

    @app.post(base + "/theme-plans")
    def create(pid: str, body: CreateIn):
        def action():
            proposal = theme_plan.read_proposals(service.config, pid)
            if proposal is not None and not isinstance(proposal.get("proposals"), list):
                raise BrokenArtifact()
            return response(theme_plan.create_plan(service.config, pid, body.proposal_id), 201)
        return invoke(pid, action)

    def mutable(pid, plan_id):
        service.find(pid, plan_id)
        if service.busy(pid, plan_id):
            raise theme_plan.PlanConflict("đang xuất video")

    @app.put(base + "/theme-plans/{plan_id}")
    def edit(pid: str, plan_id: str, body: EditIn):
        def action():
            mutable(pid, plan_id)
            return response(theme_plan.update_plan(service.config, pid, plan_id, **body.model_dump()))
        return invoke(pid, action)

    @app.post(base + "/theme-plans/{plan_id}/approve")
    def approve(pid: str, plan_id: str, body: ApproveIn):
        def action():
            mutable(pid, plan_id)
            return response(theme_plan.approve_plan(service.config, pid, plan_id, **body.model_dump()))
        return invoke(pid, action, conflict=True)

    @app.delete(base + "/theme-plans/{plan_id}")
    def delete(pid: str, plan_id: str):
        def action():
            # A corrupt plan remains deletable, using only a validated id.
            if not PLAN_ID.fullmatch(plan_id):
                raise MissingPlan()
            if service.busy(pid, plan_id):
                return response({"detail": "đang xuất video, chưa thể xóa kế hoạch"}, 409)
            if not any(p.get("plan_id") == plan_id for p in service.plans(pid)):
                raise MissingPlan()
            with store.publish_lock:
                theme_plan.delete_plan(service.config, pid, plan_id)
                store.set_published(store.directory(service.config.render.output_dir, pid), "theme", plan_id, False)
            return response({"deleted": plan_id})
        return invoke(pid, action)

    @app.post(base + "/theme-plans/{plan_id}/render")
    def render(pid: str, plan_id: str):
        def action():
            job, created = service.render(pid, plan_id)
            return response({"job": job_view(job), "created": created}, 202 if created else 200)
        return invoke(pid, action, conflict=True)

    @app.get("/files/playlists/{pid}/theme/{name}")
    def download(pid: str, name: str, inline: int = 0):
        missing = lambda: response({"detail": "không có file này"}, 404)
        match = FILE_NAME.fullmatch(name)
        if match is None or service.checked(pid) is not None:
            return missing()
        try:
            plan = service.find(pid, match[1])
            if str(plan.get("revision")) != match[2]:
                return missing()
            output = service.output(pid, plan, verify=inline != 1)
            if output is None:
                return missing()
            path, meta = output
            # Metadata has no stored byte count; reject empty files and let
            # FileResponse stat the file for Content-Length and Range handling.
            if inline == 1 and path.stat().st_size <= 0:
                return missing()
            headers = {"Cache-Control": "private, no-cache"}
            if inline != 1:
                headers["Content-Disposition"] = content_disposition(redact(meta["download_name"]))
            return FileResponse(path, media_type="video/mp4", headers=headers)
        except (MissingPlan, BrokenArtifact, theme_plan.PlanError, theme_index.IndexError, OSError, ValueError):
            return missing()
