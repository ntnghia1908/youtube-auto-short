"""Authenticated PKG1 service; TC3 verification stays at the web adapter boundary."""
from __future__ import annotations

import re
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, StrictStr

from .. import theme_index, theme_plan
from ..hashing import config_hash
from ..packaging import PackageError, assets, record, thumbnail
from ..render.stage import RenderError
from ..render.text import TextError, nfc
from ..review.names import clean_part, content_disposition, truncate_utf8
from ..workspace import utc_now
from .jobs import RENDER, JobFailed, Step
from .theme_plan import BrokenArtifact, MissingPlan, job_view, response, safe

KIND = "theme_package"


def render_key(pid, plan_id):
    return f"theme-package:{pid}:{plan_id}:thumbnails"


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
        job.summary = "Đã dựng 3 thumbnail"

    def lane_steps(self):
        return [Step(RENDER, self)]

    def spec(self):
        return {"playlist_id": self.pid, "plan_id": self.plan["plan_id"], "revision": self.plan["revision"]}


class Packages:
    def __init__(self, plans, *, media_runner=None):
        self.plans, self.config, self.runner = plans, plans.config, plans.runner
        self.lock = threading.RLock()
        self.media_runner = media_runner

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
            doc = record.new(self.config, plan, meta)
        if require_output and meta is None:
            raise Unavailable("Video TC3 không còn hợp lệ; hãy xuất lại video trước khi đóng gói")
        if doc is None:
            raise Unavailable("Kế hoạch chưa có video TC3 hợp lệ")
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
        download = None
        if doc["state"] == "approved":
            folder = record.directory(self.config.render.output_dir, pid, plan_id, doc["revision"])
            try:
                download = base + thumbnail.ready(folder, doc, self.config.packaging.asset_dir)["file"]
            except PackageError:
                doc.update(state="stale", approved_at=None)
        # Redact artifact strings first, then add the local URLs (safe() would hide them like paths, as in TC2).
        view = safe(doc)
        for entry, raw in zip(view["thumbnails"], doc["thumbnails"]):
            entry["preview_url"] = base + raw["file"] + "?inline=1" if raw["file"] and doc["state"] != "stale" else None
        view["download_url"] = download
        return {"package": view, "description": safe(meta["description"]) if meta else "", "assets": safe(images),
                "job": job_view(self.runner.latest(render_key(pid, plan_id)))}

    def edit(self, pid, plan_id, body):
        self.mutable(pid, plan_id)
        plan, meta, folder, doc = self.context(pid, plan_id)
        if doc["state"] == "stale":
            doc = record.new(self.config, plan, meta)
        for name in ("title", "headline", "selected"):
            value = getattr(body, name)
            if value is not None:
                doc[name] = nfc(value).strip()
        problem = theme_plan._title_problem(doc["title"])
        if problem:
            raise PackageError(problem)
        if doc["selected"] not in thumbnail.TEMPLATES:
            raise PackageError("unknown thumbnail template")
        for template in thumbnail.TEMPLATES.values():
            thumbnail.fit(doc["headline"], template)
        if body.asset_ids is not None:
            if any(t not in thumbnail.TEMPLATES for t in body.asset_ids):
                raise PackageError("unknown asset template")
            for entry in doc["thumbnails"]:
                if entry["template"] in body.asset_ids:
                    ids = body.asset_ids[entry["template"]]
                    if len(ids) > 1:
                        raise PackageError("mỗi thumbnail dùng tối đa một ảnh")
                    for ident in ids:
                        assets.usable(self.config.packaging.asset_dir, ident, kind="image")
                    entry["asset_ids"] = ids
        doc.update(state="draft", approved_at=None, updated_at=utc_now())
        record.write(folder, doc)
        return doc

    def render(self, pid, plan_id):
        job = self.runner.latest(render_key(pid, plan_id))
        if job is not None and job.active:
            return job, False
        plan, meta, folder, doc = self.context(pid, plan_id)
        if doc["state"] == "stale":
            doc = record.new(self.config, plan, meta)
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
    title: StrictStr | None = Field(default=None, max_length=120)
    headline: StrictStr | None = Field(default=None, max_length=300)
    selected: StrictStr | None = Field(default=None, max_length=20)
    asset_ids: dict[StrictStr, list[StrictStr]] | None = None


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

    @app.get("/files/playlists/{pid}/theme-pkg/{plan_rev}/{name}")
    def download(pid: str, plan_rev: str, name: str, inline: int = 0):
        missing = lambda: response({"detail": "không có file này"}, 404)
        match = record.REVISION.fullmatch(plan_rev)
        if match is None or record.FILE_NAME.fullmatch(name) is None or service.checked(pid) is not None:
            return missing()
        try:
            _, _, folder, doc = service.context(pid, match[1])
            if doc["state"] == "stale" or doc["revision"] != int(match[2]):
                return missing()
            entry = next((e for e in doc["thumbnails"] if e["file"] == name), None)
            if entry is None:
                return missing()
            if inline != 1 and (doc["state"] != "approved" or entry["template"] != doc["selected"]):
                return missing()
            for ident in entry["asset_ids"]:
                assets.usable(service.config.packaging.asset_dir, ident, kind="image")
            if not thumbnail.reusable(folder, entry, thumbnail.key(doc, entry)):
                return missing()
            headers = {"Cache-Control": "no-store"}
            if inline != 1:
                headers["Content-Disposition"] = content_disposition(truncate_utf8(clean_part(doc["title"])) + ".jpg")
            return FileResponse(folder / name, media_type="image/jpeg", headers=headers)
        except (PackageError, Unavailable, MissingPlan, BrokenArtifact, theme_plan.PlanError,
                theme_index.IndexError, OSError, ValueError, KeyError, TypeError):
            return missing()
