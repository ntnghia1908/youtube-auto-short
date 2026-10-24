"""Authenticated packaging service; TC3 verification stays at the web adapter boundary."""
from __future__ import annotations

import re
import threading
from copy import deepcopy
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from .. import theme_index, theme_plan
from ..hashing import config_hash, sha256_file
from ..packaging import PackageError, assets, music, record, thumbnail, variant, visual
from ..render.stage import RenderError
from ..render.text import TextError, nfc
from ..review.names import clean_part, content_disposition, truncate_utf8
from ..workspace import utc_now
from .jobs import RENDER, JobFailed, Step
from .theme_plan import BrokenArtifact, MissingPlan, job_view, response, safe

KIND = "theme_package"


def render_key(pid, plan_id):
    return f"theme-package:{pid}:{plan_id}:thumbnails"


def visual_key(pid, plan_id, revision, ident=None):
    return f"theme-package:{pid}:{plan_id}:r{revision}:" + (f"variant:{ident}" if ident else "preview")


class Unavailable(Exception):
    pass


class ThumbnailTarget:
    def __init__(self, service, pid, plan, doc):
        self.service, self.pid, self.plan, self.doc = service, pid, plan, doc

    def __call__(self, job):
        job.stage = KIND
        s = self.service
        try:
            plan, meta, folder, current = s.context(self.pid, self.plan["plan_id"])
            if config_hash(current) != config_hash(self.doc):
                raise Unavailable("đóng gói đã đổi; hãy dựng lại")
            result = thumbnail.build(folder, current, s.config.packaging.asset_dir, run=s.media_runner)
            with s.lock:
                _, _, checked_folder, checked_doc = s.context(self.pid, self.plan["plan_id"])
                if checked_folder != folder or config_hash(checked_doc) != config_hash(current):
                    raise Unavailable("đầu vào đã đổi; hãy dựng lại")
                result.update(updated_at=utc_now())
                record.write(folder, result)
        except (PackageError, Unavailable, TextError, RenderError, theme_plan.PlanError,
                theme_index.IndexError, MissingPlan, BrokenArtifact, OSError) as exc:
            raise JobFailed(safe(str(exc))) from exc
        job.stage = None
        job.summary = "Đã dựng thumbnail kiểu A / B / C (ngang và dọc)"

    def lane_steps(self):
        return [Step(RENDER, self)]

    def spec(self):
        return {"playlist_id": self.pid, "plan_id": self.plan["plan_id"], "revision": self.plan["revision"]}


class VisualTarget:
    def __init__(self, service, pid, plan, meta, spec, preview):
        self.service, self.pid, self.plan = service, pid, plan
        self.meta, self.visual, self.preview = meta, spec, preview

    def __call__(self, job):
        job.stage = KIND
        s, pid, plan_id = self.service, self.pid, self.plan["plan_id"]
        try:
            plan, meta, folder, _ = s.context(pid, plan_id)
            path, _ = s.plans.output(pid, plan, verify=True)
            expected = variant.reference(path, self.meta)

            def check():
                _, checked_meta, checked_folder, _ = s.context(pid, plan_id)
                if checked_folder != folder or variant.reference(path, checked_meta) != expected:
                    raise Unavailable("TC3 đã đổi; hãy dựng lại")
                variant.source(self.visual, s.config.packaging.asset_dir)

            check()
            builder = music.build if "music" in self.visual else visual.build
            options = dict(audio_bitrate=s.config.render.audio_bitrate) if "music" in self.visual else {}
            result = builder(folder, path, meta, self.visual, s.config.packaging.asset_dir,
                             run=s.media_runner, preview=self.preview, before_publish=check, publish_lock=s.lock, **options)
            if self.preview:
                with s.lock:
                    s.previews[(pid, plan_id)] = result
        except (PackageError, Unavailable, RenderError, theme_plan.PlanError, theme_index.IndexError,
                MissingPlan, BrokenArtifact, OSError, ValueError, TypeError, KeyError) as exc:
            raise JobFailed(safe(str(exc))) from exc
        job.stage = None
        job.summary = ("Đã dựng 3 đoạn nghe thử" if self.preview else "Đã dựng bản có nhạc") if "music" in self.visual else (
            "Đã dựng xem thử 20 giây" if self.preview else "Đã dựng hình ambient")

    def lane_steps(self):
        return [Step(RENDER, self)]

    def spec(self):
        return dict(playlist_id=self.pid, plan_id=self.plan["plan_id"], revision=self.plan["revision"],
                    visual=self.visual, preview=self.preview)


class Packages:
    def __init__(self, plans, *, media_runner=None):
        self.plans, self.config, self.runner = plans, plans.config, plans.runner
        self.lock = threading.RLock()
        self.media_runner = media_runner
        self.previews = {}
        self.variant_cache = {}  # FileFingerprint entries, accessed under self.lock

    def checked(self, pid):
        return self.plans.checked(pid)

    def context(self, pid, plan_id, *, require_output=True):
        plan = self.plans.find(pid, plan_id)
        output = self.plans.output(pid, plan, verify=True)
        meta = output[1] if output is not None else None
        folder = record.directory(self.config.render.output_dir, pid, plan_id, plan["revision"])
        doc = record.read(folder)
        if doc is None:
            # Retain the previous revision visibly as stale; no deletion or silent approval.
            candidates = []
            if folder.parent.is_dir():
                for p in folder.parent.glob(plan_id + "-r*"):
                    match = record.REVISION.fullmatch(p.name)
                    if match and int(match[2]) < plan["revision"]:
                        candidates.append(int(match[2]))
            if candidates:
                old = record.directory(self.config.render.output_dir, pid, plan_id, max(candidates))
                doc = record.read(old)
        if doc is not None:
            doc = record.status(doc, plan, meta)
        elif meta is not None:
            doc = record.new(self.config, plan, meta, pid)
        if require_output and meta is None:
            raise Unavailable("Video TC3 không còn hợp lệ; hãy xuất lại video trước khi đóng gói")
        if doc is None:
            previous = variant.listing(folder, plan, meta)
            digest = previous[-1][1]["tc3"]["sha256"] if previous else "0" * 64
            doc = record.new(self.config, plan, {"sha256": digest}, pid)
            doc.update(state="stale", approved_at=None)
        return plan, meta, folder, doc

    def busy(self, pid, plan_id):
        job = self.runner.latest(render_key(pid, plan_id))
        return job is not None and job.active

    def mutable(self, pid, plan_id):
        if self.busy(pid, plan_id):
            raise Unavailable("đang dựng thumbnail; chờ hoàn tất")

    def view(self, pid, plan_id):
        _, meta, _, doc = self.context(pid, plan_id, require_output=False)
        images = []
        for asset in assets.list_assets(self.config.packaging.asset_dir):
            if asset["kind"] == "image" and asset["approved"] and asset["license"].strip() and asset["source"].strip():
                images.append({k: asset[k] for k in ("id", "kind", "tags", "source", "license", "width", "height")})
        base = f"/files/playlists/{pid}/theme-pkg/{doc['plan_id']}-r{doc['revision']}/"
        folder = record.directory(self.config.render.output_dir, pid, plan_id, doc["revision"])
        downloads = None
        if doc["state"] == "approved":
            try:
                chosen = thumbnail.ready(folder, doc, self.config.packaging.asset_dir)
                downloads = {shape: base + chosen["files"][shape]["file"] for shape in record.SHAPES}
            except PackageError:
                doc.update(state="stale", approved_at=None)
        # Redact artifact strings first, then add the local URLs (safe() would hide them like paths, as in TC2).
        view = safe(doc)
        for entry, raw in zip(view["thumbnails"], doc["thumbnails"]):
            # Only files that match the current settings are shown; an edited style waits for a rebuild.
            entry["preview_urls"] = {
                shape: base + f["file"] + "?inline=1"
                if f and doc["state"] != "stale" and thumbnail.reusable(folder, f, thumbnail.key(doc, raw, shape)) else None
                for shape, f in raw["files"].items()}
        view["download_urls"] = downloads
        view["download_url"] = downloads["landscape"] if downloads else None
        return {"package": view, "description": safe(meta["description"]) if meta else "", "assets": safe(images),
                "job": job_view(self.runner.latest(render_key(pid, plan_id))), **self.visual_view(pid, plan_id)}

    def visual_view(self, pid, plan_id):
        plan, meta, folder, _ = self.context(pid, plan_id, require_output=False)
        rows = []
        with self.lock:
            entries = variant.listing(folder, plan, meta, cache=self.variant_cache, asset_dir=self.config.packaging.asset_dir)
        for location, doc, state in entries:
            ident = doc["key"][:12]
            revision = int(record.REVISION.fullmatch(location.name)[2])
            try:
                variant.source(doc["spec"], self.config.packaging.asset_dir)
            except PackageError:
                state = "stale"
            url = f"/files/playlists/{pid}/theme-pkg/{location.name}/variant-{ident}.mp4"
            job = self.runner.latest(visual_key(pid, plan_id, revision, ident))
            rows.append(dict(revision=revision, key12=ident, spec=doc["spec"], state=state, size=doc["size"], duration=doc["duration"],
                             method=doc["checks"]["method"], build_seconds=doc["build_seconds"],
                             inline_url=url + "?inline=1" if state != "stale" else None,
                             download_url=url if state == "approved" else None, job=job_view(job)))
        for job in self.runner.jobs():
            target = job.target
            if job.kind != KIND or not isinstance(target, VisualTarget) or target.preview \
                    or target.pid != pid or target.plan["plan_id"] != plan_id \
                    or self.runner.latest(job.key) is not job or (not job.active and job.status != "failed"):
                continue
            ident = self.variant_key(target.visual, target.meta)[:12]
            revision = target.plan["revision"]
            if not job.active and any((r["revision"], r["key12"]) == (revision, ident) for r in rows):
                continue
            rows = [r for r in rows if (r["revision"], r["key12"]) != (revision, ident)]
            rows.append(dict(revision=revision, key12=ident, spec=target.visual,
                             state="building" if job.active else "draft", size=None, duration=None,
                             method=None, build_seconds=None, inline_url=None, download_url=None, job=job_view(job)))
        sources = [dict(id="generated:" + p, kind="generated", tags=[p], license="Nền tạo sẵn · license-free")
                   for p in variant.PRESETS]
        for asset in assets.list_assets(self.config.packaging.asset_dir):
            if asset["kind"] not in ("image", "loop"):
                continue
            try:
                assets.usable(self.config.packaging.asset_dir, asset["id"], kind=asset["kind"])
                sources.append({k: asset[k] for k in ("id", "kind", "tags", "license")})
            except PackageError:
                continue
        preview = self.previews.get((pid, plan_id))
        url, ident, audio_urls = None, None, []
        if preview is not None and meta is not None:
            ident = preview["key"][:12]
            path = folder / f"preview-{ident}.mp4"
            if "previews" in preview:
                path = folder / preview["previews"][0]["file"]
            if preview["tc3"] == variant.reference(path.with_name(f"{plan_id}-r{plan['revision']}.mp4"), meta) \
                    and path.is_file() and not path.is_symlink():
                try:
                    variant.source(preview["spec"], self.config.packaging.asset_dir)
                    base = f"/files/playlists/{pid}/theme-pkg/{folder.name}/"
                    if "previews" in preview:
                        if all((folder / p["file"]).is_file() and not (folder / p["file"]).is_symlink()
                               for p in preview["previews"]):
                            audio_urls = [base + p["file"] + "?inline=1" for p in preview["previews"]]
                    else:
                        url = base + path.name + "?inline=1"
                except PackageError:
                    pass
        music_sources = []
        for asset in assets.list_assets(self.config.packaging.asset_dir):
            if asset["kind"] == "music":
                try:
                    assets.usable(self.config.packaging.asset_dir, asset["id"], kind="music")
                    music_sources.append({k: asset[k] for k in ("id", "tags", "license", "duration")})
                except PackageError:
                    pass
        return dict(variants=rows, visual_sources=safe(sources), music_sources=safe(music_sources),
                    preview=dict(url=url, audio_urls=audio_urls, key12=ident, revision=plan["revision"],
                    job=job_view(self.runner.latest(visual_key(pid, plan_id, plan["revision"])))))

    def variant_key(self, spec, meta):
        settings = music.encoding(self.config.render.audio_bitrate) if "music" in spec else None
        return variant.key(spec, meta["sha256"], settings=settings)

    def render_visual(self, pid, plan_id, spec, *, preview=False):
        spec = variant.normalize(spec)
        plan, meta, folder, _ = self.context(pid, plan_id)
        variant.source(spec, self.config.packaging.asset_dir)
        if "music" in spec and not preview:
            path, _ = self.plans.output(pid, plan, verify=True)
            music.video_source(folder, path, meta, spec)
        ident = self.variant_key(spec, meta)[:12]
        key = visual_key(pid, plan_id, plan["revision"], None if preview else ident)
        job = self.runner.latest(key)
        if job is not None and job.active:
            return dict(job=job_view(job), created=False), 200
        if not preview:
            try:
                cached = variant.read(folder, ident)
            except PackageError:
                cached = None
            with self.lock:
                state = variant.status(folder, cached, plan, meta, cache=self.variant_cache, asset_dir=self.config.packaging.asset_dir) if cached else "stale"
            if state != "stale":
                return dict(variant=next(v for v in self.visual_view(pid, plan_id)["variants"]
                                         if (v["revision"], v["key12"]) == (plan["revision"], ident)), created=False), 200
        job, created = self.runner.submit(key, KIND, VisualTarget(self, pid, plan, meta, spec, preview))
        return dict(job=job_view(job), created=created), 202 if created else 200

    def find_variant(self, pid, plan_id, revision, ident):
        if not variant.KEY12.fullmatch(ident):
            raise PackageError("invalid variant key")
        plan, meta, _, _ = self.context(pid, plan_id, require_output=False)
        folder = record.directory(self.config.render.output_dir, pid, plan_id, revision)
        doc = variant.read(folder, ident)
        if doc is None:
            raise MissingPlan()
        with self.lock:
            state = variant.status(folder, doc, plan, meta, cache=self.variant_cache, asset_dir=self.config.packaging.asset_dir) \
                if revision == plan["revision"] else "stale"
        return folder, doc, state

    def change_variant(self, pid, plan_id, revision, ident, *, delete=False):
        folder, doc, state = self.find_variant(pid, plan_id, revision, ident)
        for job in self.runner.jobs():
            target = job.target
            if job.active and job.kind == KIND and isinstance(target, VisualTarget) and target.pid == pid \
                    and target.plan["plan_id"] == plan_id and target.plan["revision"] == revision \
                    and (self.variant_key(target.visual, target.meta) == doc["key"]
                         or (doc.get("loop_key") and target.visual["visual"] == doc["spec"]["visual"])):
                raise Unavailable("đang dựng variant; hãy hủy hoặc chờ hoàn tất")
        if delete:
            variant.delete(folder, doc)
            with self.lock:
                self.variant_cache.pop((folder / f"variant-{ident}.mp4").resolve(), None)
            return {"deleted": True}
        if state == "stale":
            raise Unavailable("cũ — dựng lại")
        variant.source(doc["spec"], self.config.packaging.asset_dir)
        doc["approved_at"] = utc_now()
        variant.write(folder, doc)
        return {"approved": True}

    def edit(self, pid, plan_id, body):
        self.mutable(pid, plan_id)
        plan, meta, folder, doc = self.context(pid, plan_id)
        if doc["state"] == "stale":
            doc = record.new(self.config, plan, meta, pid)
        doc = deepcopy(doc)
        for name in ("title", "selected"):
            value = getattr(body, name)
            if value is not None:
                doc[name] = nfc(value).strip()
        problem = theme_plan._title_problem(doc["title"])
        if problem:
            raise PackageError(problem)
        if doc["selected"] not in record.STYLES:
            raise PackageError("unknown thumbnail style")
        settings = dict(doc["settings"])
        for name in ("title_lines", "series", "speaker", "palette", "background", "focus_x"):
            value = getattr(body, name)
            if value is not None:
                settings[name] = value
        doc["settings"] = record.normalize_settings(settings)
        if body.asset_ids is not None:
            if any(t not in record.STYLES for t in body.asset_ids):
                raise PackageError("unknown asset style")
            for entry in doc["thumbnails"]:
                if entry["style"] in body.asset_ids:
                    ids = body.asset_ids[entry["style"]]
                    if len(ids) > 1:
                        raise PackageError("mỗi thumbnail dùng tối đa một ảnh")
                    for ident in ids:
                        assets.usable(self.config.packaging.asset_dir, ident, kind="image")
                    entry["asset_ids"] = ids
        thumbnail.check(doc, self.config.packaging.asset_dir)  # fit / palette / blur: rejected before any ffmpeg
        doc.update(state="draft", approved_at=None, updated_at=utc_now())
        record.write(folder, doc)
        return doc

    def render(self, pid, plan_id):
        job = self.runner.latest(render_key(pid, plan_id))
        if job is not None and job.active:
            return job, False
        plan, meta, folder, doc = self.context(pid, plan_id)
        if doc["state"] == "stale":
            doc = record.new(self.config, plan, meta, pid)
        thumbnail.check(doc, self.config.packaging.asset_dir)
        # A cache hit preserves explicit approval; a changed record becomes draft via edit().
        record.write(folder, doc)
        return self.runner.submit(render_key(pid, plan_id), KIND, ThumbnailTarget(self, pid, plan, doc))

    def approve(self, pid, plan_id):
        self.mutable(pid, plan_id)
        _, _, folder, doc = self.context(pid, plan_id)
        if doc["state"] == "stale":
            raise Unavailable("cũ — dựng lại")
        problem = theme_plan._title_problem(doc["title"])
        if problem:
            raise PackageError(problem)
        thumbnail.ready(folder, doc, self.config.packaging.asset_dir)
        doc.update(state="approved", approved_at=utc_now(), updated_at=utc_now())
        record.write(folder, doc)
        return doc


class EditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: StrictStr | None = Field(default=None, max_length=120)
    selected: StrictStr | None = Field(default=None, max_length=20)
    title_lines: list[StrictStr] | None = Field(default=None, max_length=3)
    series: StrictStr | None = Field(default=None, max_length=record.MAX_SERIES * 2)
    speaker: StrictStr | None = Field(default=None, max_length=record.MAX_SPEAKER * 2)
    palette: StrictStr | None = Field(default=None, max_length=20)
    background: StrictStr | None = Field(default=None, max_length=10)
    focus_x: StrictFloat | StrictInt | None = None
    asset_ids: dict[StrictStr, list[StrictStr]] | None = None


class VisualIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: StrictStr = Field(default="ambient", max_length=16)
    asset_id: StrictStr = Field(default="generated:warm", max_length=80)
    motion: StrictStr = Field(default="none", max_length=16)
    fit: StrictStr = Field(default="cover", max_length=16)
    loop_seconds: StrictInt = Field(default=40, ge=2, le=120)
    crossfade: StrictFloat | StrictInt = Field(default=2, ge=.5, le=5)


class MusicIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: StrictStr = Field(max_length=64)
    level_lu: StrictFloat | StrictInt = Field(default=-20, ge=-30, le=-12)
    fade_in: StrictFloat | StrictInt = Field(default=3, ge=0, le=10)
    fade_out: StrictFloat | StrictInt = Field(default=5, ge=0, le=15)
    loop_crossfade: StrictFloat | StrictInt = Field(default=3, ge=.5, le=8)


class VariantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visual: VisualIn | None
    music: MusicIn | None = None


def register(app: FastAPI, service: Packages):
    @app.middleware("http")
    async def no_store(request: Request, call_next):
        result = await call_next(request)
        if re.fullmatch(r"/api/playlists/[^/]+/theme-plans/[^/]+/package(?:/.*)?", request.url.path):
            result.headers["Cache-Control"] = "no-store"
        return result

    def invoke(pid, action, *, write=False):
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
        except Unavailable as exc:
            return response({"detail": str(exc)}, 409)
        except (PackageError, TextError) as exc:
            return response({"detail": str(exc)}, 400)
        except (BrokenArtifact, theme_plan.PlanError, theme_index.IndexError, OSError, ValueError, KeyError, TypeError):
            return response({"detail": "dữ liệu đóng gói không hợp lệ"}, 422)

    base = "/api/playlists/{pid}/theme-plans/{plan_id}/package"

    @app.get("/playlists/{pid}/theme-plans/{plan_id}/package")
    def page(pid: str, plan_id: str):
        def action():
            service.plans.find(pid, plan_id)
            return FileResponse(Path(__file__).parent / "static" / "package.html", headers={"Cache-Control": "no-store"})
        return invoke(pid, action)

    @app.get(base)
    def get(pid: str, plan_id: str):
        return invoke(pid, lambda: JSONResponse(service.view(pid, plan_id), headers={"Cache-Control": "no-store"}))

    @app.put(base)
    def put(pid: str, plan_id: str, body: EditIn):
        return invoke(pid, lambda: response(service.edit(pid, plan_id, body)), write=True)

    @app.post(base + "/thumbnails")
    def render(pid: str, plan_id: str):
        def action():
            job, created = service.render(pid, plan_id)
            return response({"job": job_view(job), "created": created}, 202 if created else 200)
        return invoke(pid, action, write=True)

    @app.post(base + "/approve")
    def approve(pid: str, plan_id: str):
        return invoke(pid, lambda: response(service.approve(pid, plan_id)), write=True)

    @app.post(base + "/variants")
    def render_variant(pid: str, plan_id: str, body: VariantIn):
        return invoke(pid, lambda: response(*service.render_visual(pid, plan_id, body.model_dump())), write=True)

    @app.post(base + "/preview")
    def preview(pid: str, plan_id: str, body: VariantIn):
        return invoke(pid, lambda: response(*service.render_visual(pid, plan_id, body.model_dump(), preview=True)), write=True)

    @app.post(base + "/variants/r{revision}/{key12}/approve")
    def approve_variant(pid: str, plan_id: str, revision: int, key12: str):
        return invoke(pid, lambda: response(service.change_variant(pid, plan_id, revision, key12)), write=True)

    @app.post(base + "/variants/r{revision}/{key12}/cancel")
    def cancel_variant(pid: str, plan_id: str, revision: int, key12: str):
        def action():
            service.plans.find(pid, plan_id)
            record.directory(service.config.render.output_dir, pid, plan_id, revision)
            if key12 != "preview" and not variant.KEY12.fullmatch(key12):
                raise PackageError("invalid variant key")
            jobs = service.runner.cancel(KIND, {visual_key(pid, plan_id, revision, None if key12 == "preview" else key12)})
            return response({"jobs": [job_view(j) for j in jobs]})
        return invoke(pid, action, write=True)

    @app.delete(base + "/variants/r{revision}/{key12}")
    def delete_variant(pid: str, plan_id: str, revision: int, key12: str):
        def action():
            # A running build does not have a sidecar yet.
            job = service.runner.latest(visual_key(pid, plan_id, revision, key12))
            if job is not None and job.active:
                raise Unavailable("đang dựng variant; hãy hủy hoặc chờ hoàn tất")
            return response(service.change_variant(pid, plan_id, revision, key12, delete=True))
        return invoke(pid, action, write=True)

    @app.get("/files/playlists/{pid}/theme-pkg/{plan_rev}/{name}")
    def download(pid: str, plan_rev: str, name: str, inline: int = 0):
        missing = lambda: response({"detail": "không có file này"}, 404)
        match = record.REVISION.fullmatch(plan_rev)
        media = variant.MEDIA_NAME.fullmatch(name)
        music_preview = variant.MUSIC_PREVIEW.fullmatch(name)
        if match is None or (record.FILE_NAME.fullmatch(name) is None and
                             (music_preview is None and (media is None or media[1] == "loop"))) or service.checked(pid) is not None:
            return missing()
        try:
            if media or music_preview:
                plan, meta, folder, _ = service.context(pid, match[1])
                if folder.name != plan_rev:
                    return missing()
                if media and media[1] == "variant":
                    doc = variant.read(folder, media[2])
                    if doc is None or variant.status(folder, doc, plan, meta, asset_dir=service.config.packaging.asset_dir) == "stale" \
                            or (inline != 1 and not doc["approved_at"]):
                        return missing()
                else:
                    doc = service.previews.get((pid, match[1]))
                    path = folder / name
                    preview_key = music_preview[1] if music_preview else media[2]
                    entry = next((p for p in doc.get("previews", []) if p["file"] == name), None) if doc else None
                    digest = entry["sha256"] if entry else doc.get("sha256") if doc and not music_preview else None
                    if inline != 1 or doc is None or doc["key"][:12] != preview_key \
                            or any(doc["tc3"][k] != meta[k] for k in ("sha256", "revision", "plan_fingerprint")) \
                            or not path.is_file() or path.is_symlink() or sha256_file(path) != digest:
                        return missing()
                variant.source(doc["spec"], service.config.packaging.asset_dir)
                headers = {"Cache-Control": "no-store"}
                if inline != 1:
                    title = meta["download_name"].removesuffix(".mp4")
                    headers["Content-Disposition"] = content_disposition(truncate_utf8(clean_part(title)) + ".mp4")
                return FileResponse(folder / name, media_type="audio/mp4" if music_preview else "video/mp4", headers=headers)
            _, _, folder, doc = service.context(pid, match[1])
            if doc["state"] == "stale" or doc["revision"] != int(match[2]):
                return missing()
            found = next(((e, shape) for e in doc["thumbnails"] for shape, f in e["files"].items()
                          if f and f["file"] == name), None)
            if found is None:
                return missing()
            entry, shape = found
            if inline != 1 and (doc["state"] != "approved" or entry["style"] != doc["selected"]):
                return missing()
            for ident in entry["asset_ids"]:
                assets.usable(service.config.packaging.asset_dir, ident, kind="image")
            if not thumbnail.reusable(folder, entry["files"][shape], thumbnail.key(doc, entry, shape)):
                return missing()
            headers = {"Cache-Control": "no-store"}
            if inline != 1:
                thumbnail.ready(folder, doc, service.config.packaging.asset_dir)  # both shapes of the approved style
                suffix = " - ngang" if shape == "landscape" else " - dọc"
                headers["Content-Disposition"] = content_disposition(truncate_utf8(clean_part(doc["title"])) + suffix + ".jpg")
            return FileResponse(folder / name, media_type="image/jpeg", headers=headers)
        except (PackageError, Unavailable, MissingPlan, BrokenArtifact, theme_plan.PlanError,
                theme_index.IndexError, OSError, ValueError, KeyError, TypeError):
            return missing()
