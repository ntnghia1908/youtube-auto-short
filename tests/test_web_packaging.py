"""PKG1: authenticated HTTP routes plus socket-free service/job verification."""
import asyncio
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from auto_short import hashing, theme_plan as tp
from auto_short.config import PackagingConfig
from auto_short.packaging import PackageError, assets, music, record, thumbnail, variant, visual
from auto_short.web import packaging as web
from auto_short.web.jobs import RENDER
from auto_short.workspace import atomic_write_json

from test_packaging_thumbnail import fake_media
from test_packaging_music import synthetic  # noqa: F401 — shared synthetic media fixture
from test_packaging_visual import Media, SPEC
from test_theme_plan import Planner
from test_web_theme_index import fx, snapshot
from test_web_theme_plan import PID, approve, create, fake_output, plan_path, setup as theme_setup  # noqa: F401


@pytest.fixture
def setup(theme_setup, tmp_path):
    s = theme_setup
    s.app.state.packages.config = replace(s.cfg, packaging=PackagingConfig(tmp_path / "assets"))
    s.app.state.packages.media_runner = fake_media
    s.package = s.app.state.packages
    return s


@pytest.fixture
def photo_asset(setup, tmp_path):
    path = tmp_path / "speaker.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x3b5670:s=800x1000",
                    "-frames:v", "1", "-threads", "1", str(path)], check=True)
    asset_dir = setup.package.config.packaging.asset_dir
    entry = assets.add(asset_dir, path, kind="image", source="local:test", license="CC0")
    assets.approve(asset_dir, entry["id"])
    return entry["id"]


@pytest.fixture
def service(tmp_path):
    """Reuse the TC2 synthetic source without starting TestClient or any socket."""
    cfg = replace(fx.seed(tmp_path / "scratch"), packaging=PackagingConfig(tmp_path / "assets"))
    app = fx.build_app(cfg, "pw", restrict=False)
    proposal = tp.propose(cfg, PID, client=Planner())["proposals"][0]
    plan = tp.create_plan(cfg, PID, proposal["proposal_id"])
    plan = tp.approve_plan(cfg, PID, plan["plan_id"], revision=plan["revision"], duration_override=True)
    s = SimpleNamespace(cfg=cfg, app=app, runner=app.state.runner, package=app.state.packages, plan=plan)
    s.package.media_runner = fake_media
    fake_output(s, plan)
    return s


def test_service_title_validation_job_lane_dedup_cache_and_approval(service):
    s, pid = service, service.plan["plan_id"]
    view = s.package.view(PID, pid)
    assert view["package"]["title_options"][:-1] == s.plan["title_options"]
    assert "Tu học" in view["package"]["title_options"][-1]
    speaker = tp.speaker_for_clips(s.cfg, s.plan["clips"])
    assert speaker is None  # TC2 fixture has no speaker metadata; traditional fallback is the theme label.
    assert view["package"]["title_options"][-1] == s.plan["theme"]["label"]
    for title in ("SỐC! Bí mật", "Tu học 😀", "“Tu học”"):
        with pytest.raises(PackageError):
            s.package.edit(PID, pid, web.EditIn(title=title))
    assert view["package"]["settings"]["title_lines"][0] == "Tuyển tập khai thị" and view["package"]["settings"]["minutes"] == 6
    s.package.edit(PID, pid, web.EditIn(title="Chuyên tâm tu học", title_lines=["Tuyển tập khai thị", "Niệm Phật vãng sanh", ""]))
    first, created = s.package.render(PID, pid)
    duplicate, again = s.package.render(PID, pid)
    assert created and not again and duplicate.id == first.id and first.kind == "theme_package"
    assert [step.lane for step in first.steps] == [RENDER]
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        assert first.status == "done", first.error
        doc = s.package.approve(PID, pid)
        assert doc["state"] == "approved" and doc["approved_at"]
        urls = s.package.view(PID, pid)["package"]["download_urls"]
        assert set(urls) == {"landscape", "vertical"} and all(u.endswith(".jpg") for u in urls.values())
        assert s.package.view(PID, pid)["package"]["download_url"] == urls["landscape"]
        s.package.media_runner = lambda _: pytest.fail("cache called media runner")
        second, _ = s.package.render(PID, pid)
        assert s.runner.wait_idle(5)
        assert second.status == "done", second.error
        assert s.package.view(PID, pid)["package"]["state"] == "approved"
    finally:
        s.runner.stop()


@pytest.mark.parametrize("changed", ["revision", "fingerprint", "tc3", "tamper"])
def test_service_stale_preserves_old_record(service, changed):
    s, pid = service, service.plan["plan_id"]
    plan, meta, folder, doc = s.package.context(PID, pid)
    doc = thumbnail.build(folder, doc, s.cfg.packaging.asset_dir, run=fake_media)
    record.write(folder, doc)
    s.package.approve(PID, pid)
    before = (folder / "package.json").read_bytes()
    path, meta = fake_output(s, s.plan)
    if changed in ("revision", "fingerprint"):
        # Update only via the plan API; revision and fingerprint change together.
        updated = tp.update_plan(s.cfg, PID, pid, revision=plan["revision"], title="Chuyên tâm tu học",
                                 clip_ids=[c["id"] for c in plan["clips"]])
        tp.approve_plan(s.cfg, PID, pid, revision=updated["revision"], duration_override=True)
        if changed == "fingerprint":
            # Corrupt metadata fingerprint on an otherwise valid TC3 file.
            fake_output(s, updated)
            path = path.with_name(f"{pid}-r{updated['revision']}.mp4")
            new_meta = json.loads(path.with_suffix(".json").read_text())
            new_meta["plan_fingerprint"] = "c" * 64
            atomic_write_json(path.with_suffix(".json"), new_meta)
    elif changed == "tc3":
        from auto_short.hashing import sha256_file
        path.write_bytes(b"new valid TC3")
        meta["sha256"] = sha256_file(path)
        atomic_write_json(path.with_suffix(".json"), meta)
    else:
        path.write_bytes(b"tampered without updating metadata")
    view = s.package.view(PID, pid)
    assert view["package"]["state"] == "stale" and view["package"]["download_url"] is None
    assert all(u is None for t in view["package"]["thumbnails"] for u in t["preview_urls"].values())
    assert (folder / "package.json").read_bytes() == before
    with pytest.raises(web.Unavailable):
        s.package.approve(PID, pid)


def test_service_job_rechecks_input_and_reports_failure(service, monkeypatch):
    s, pid = service, service.plan["plan_id"]
    job, _ = s.package.render(PID, pid)
    path, _ = fake_output(s, s.plan)
    path.write_bytes(b"changed while queued")
    monkeypatch.setattr(thumbnail, "build", lambda *a, **kw: pytest.fail("rendered invalid TC3"))
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        assert job.status == "failed" and "TC3" in job.error
        assert str(s.cfg.render.output_dir) not in job.error
    finally:
        s.runner.stop()


@pytest.mark.parametrize("title", ["SỐC! Bí mật", "Tu học 😀", "“Tu học”"])
def test_http_titles_and_validation(setup, title):
    s = setup
    plan = approve(s, create(s))
    fake_output(s, plan)
    url = plan_path(plan) + "/package"
    before = snapshot(s.root)
    result = s.c.get(url)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    doc = result.json()["package"]
    assert doc["title_options"][:-1] == plan["title_options"] and "Tu học" in doc["title_options"][-1]
    assert result.json()["description"] == "00:00 Tu học\n\nMô tả"
    assert before == snapshot(s.root)
    assert s.c.put(url, json={"title": title}).status_code == 400
    assert s.c.put(url, json={"title": "Chuyên tâm tu học", "title_lines": ["Tuyển tập khai thị", "Niệm Phật", ""]}).status_code == 200
    assert s.c.put(url, json={"title_lines": ["a", "b", "c", "d"]}).status_code == 422
    assert s.c.put(url, json={"headline": "Niệm Phật"}).status_code == 422  # PKG1 field is gone
    assert s.c.put(url, json={"selected": "../../bad"}).status_code == 400
    assert s.c.put(url, json={"selected": "classic"}).status_code == 400


@pytest.mark.parametrize("changed", ["revision", "tc3", "thumbnail"])
def test_http_approve_download_and_stale(setup, changed):
    s = setup
    plan = approve(s, create(s))
    path, _ = fake_output(s, plan)
    url = plan_path(plan) + "/package"
    assert s.c.post(url + "/thumbnails").status_code == 202
    assert s.c.post(url + "/thumbnails").status_code == 200
    assert s.c.put(url, json={"title": "Chuyên tâm tu học"}).status_code == 409
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        view = s.c.get(url).json()["package"]
        assert [t["style"] for t in view["thumbnails"]] == ["A", "B", "C"]
        assert all(u for t in view["thumbnails"] for u in t["preview_urls"].values())  # both shapes of every style
        previews = view["thumbnails"][0]["preview_urls"]
        preview = previews["landscape"]
        download = preview.split("?")[0]
        assert s.c.get(preview).status_code == 200
        assert s.c.get(download).status_code == 404
        assert view["download_urls"] is None
        assert s.c.post(url + "/approve").status_code == 200
        urls = s.c.get(url).json()["package"]["download_urls"]
        assert set(urls) == {"landscape", "vertical"}
        for shape, link in urls.items():
            result = s.c.get(link)
            assert result.status_code == 200 and result.headers["content-type"] == "image/jpeg"
            assert "filename*=UTF-8" in result.headers["content-disposition"]
            assert ("%20-%20ngang" if shape == "landscape" else "%20-%20d%E1%BB%8Dc") in result.headers["content-disposition"]
        # only the approved style downloads; the others stay preview-only
        other = view["thumbnails"][1]["preview_urls"]["landscape"].split("?")[0]
        assert s.c.get(other).status_code == 404 and s.c.get(other + "?inline=1").status_code == 200
        if changed == "revision":
            assert s.c.put(plan_path(plan), json={"revision": plan["revision"], "title": "Tu học mỗi ngày",
                        "clip_ids": [c["id"] for c in plan["clips"]]}).status_code == 200
        elif changed == "tc3":
            path.write_bytes(b"changed")
        else:
            folder = record.directory(s.cfg.render.output_dir, PID, plan["plan_id"], plan["revision"])
            (folder / view["thumbnails"][0]["files"]["vertical"]["file"]).write_bytes(b"changed")
        assert s.c.get(download).status_code == 404 and s.c.get(urls["vertical"]).status_code == 404
        assert s.c.get(url).json()["package"]["state"] == "stale"
    finally:
        s.runner.stop()


def test_http_edit_style_settings_rebuild_only_what_changed_and_reject_before_ffmpeg(setup, photo_asset):
    s = setup
    plan = approve(s, create(s))
    fake_output(s, plan)
    url = plan_path(plan) + "/package"
    calls = []
    def counted(cmd):
        calls.append(cmd)
        if "-filter_complex" in cmd:
            Path(cmd[-1]).write_bytes(bytes([20] * 12))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return fake_media(cmd)
    s.package.media_runner = counted
    graphs = lambda: [c for c in calls if "-filter_complex_script" in c]
    body = {"title_lines": ["Tuyển tập khai thị", "Tu hành", "không phải hình thức"], "series": "Thái Thượng Cảm Ứng Thiên",
            "speaker": "Pháp Sư Tịnh Không", "selected": "B", "palette": "xanh-ngoc", "focus_x": 0.25,
            "asset_ids": {"A": [photo_asset], "B": [photo_asset], "C": []}}
    result = s.c.put(url, json=body)
    assert result.status_code == 200 and result.json()["selected"] == "B"
    assert result.json()["settings"]["title_lines"] == body["title_lines"] and result.json()["settings"]["palette"] == "xanh-ngoc"
    s.runner.start()
    try:
        assert s.c.post(url + "/thumbnails").status_code == 202 and s.runner.wait_idle(5)
        assert len(graphs()) == 6
        view = s.c.get(url).json()["package"]
        assert view["thumbnails"][0]["asset_ids"] == [photo_asset] and view["thumbnails"][2]["asset_ids"] == []
        # a palette / background change touches style A only
        calls.clear()
        assert s.c.put(url, json={"palette": "do-son", "background": "blur"}).status_code == 200
        unchanged = s.c.get(url).json()["package"]["thumbnails"]
        assert unchanged[0]["preview_urls"] == {"landscape": None, "vertical": None}
        assert all(all(t["preview_urls"].values()) for t in unchanged[1:])
        assert s.c.post(url + "/thumbnails").status_code == 202 and s.runner.wait_idle(5)
        assert len(graphs()) == 2
        # identical rebuild: no ffmpeg at all
        calls.clear()
        assert s.c.post(url + "/thumbnails").status_code == 202 and s.runner.wait_idle(5)
        assert calls == []
        # invalid settings never reach ffmpeg
        calls.clear()
        for bad in ({"palette": "khong-co"}, {"background": "gradient"}, {"title_lines": ["x" * 41]},
                    {"title_lines": ["Thiền 🧘"]}, {"title_lines": ["W" * 40]}, {"series": "Đ" * 101},
                    {"focus_x": 2}, {"title_lines": ["", " "]}, {"asset_ids": {"A": ["a" * 64]}},
                    {"asset_ids": {"classic": []}}, {"asset_ids": {"A": [photo_asset, photo_asset]}}):
            assert s.c.put(url, json=bad).status_code == 400, bad
        assert s.c.put(url, json={"asset_ids": {"A": []}}).status_code == 400  # blur needs an image
        assert s.c.put(url, json={"background": "plain", "asset_ids": {"A": []}}).status_code == 200
        assert calls == []
    finally:
        s.runner.stop()


def test_http_auth_ids_and_static_page(setup):
    s = setup
    plan = approve(s, create(s))
    fake_output(s, plan)
    url = plan_path(plan) + "/package"
    anon = TestClient(s.app, follow_redirects=False)
    assert anon.get(f"/playlists/{PID}/theme-plans/{plan['plan_id']}/package").status_code == 303
    for method, suffix, body in [("GET", "", None), ("PUT", "", {}), ("POST", "/thumbnails", None), ("POST", "/approve", None)]:
        result = anon.request(method, url + suffix, json=body)
        assert result.status_code == 401 and result.headers["cache-control"] == "no-store"
    file = f"/files/playlists/{PID}/theme-pkg/{plan['plan_id']}-r1/A-landscape-{'a' * 64}.jpg"
    assert anon.get(file).status_code == 401
    for suffix in ("/variants", "/preview"):
        assert anon.post(url + suffix, json={"visual": None, "music": {"asset_id": "a" * 64}}).status_code == 401
    preview_file = file.rsplit("/", 1)[0] + "/preview-" + "a" * 12 + "-1.m4a?inline=1"
    assert anon.get(preview_file).status_code == 401
    assert s.c.get(f"/playlists/{PID}/theme-plans/{plan['plan_id']}/package").status_code == 200
    for pid, ident in [("bad!", plan["plan_id"]), ("PLunknown", plan["plan_id"]), (PID, "bad!"), (PID, "12345678")]:
        result = s.c.get(f"/api/playlists/{pid}/theme-plans/{ident}/package")
        assert result.status_code == 404 and result.headers["cache-control"] == "no-store"
    for suffix in ("A-landscape-invalid.jpg", "classic-" + "a" * 64 + ".jpg", "A-diagonal-" + "a" * 64 + ".jpg", "package.json", "..%5Csecret.jpg"):
        assert s.c.get(file.rsplit("/", 1)[0] + "/" + suffix).status_code == 404
    _, _, folder, doc = s.package.context(PID, plan["plan_id"])
    doc = thumbnail.build(folder, doc, s.package.config.packaging.asset_dir, run=fake_media)
    record.write(folder, doc)
    selected = folder / doc["thumbnails"][0]["files"]["landscape"]["file"]
    selected.unlink()
    selected.symlink_to(folder.parent.parent / f"{plan['plan_id']}-r1.mp4")
    assert s.c.get(file.rsplit("/", 1)[0] + "/" + selected.name + "?inline=1").status_code == 404
    assert "Đóng gói" in s.c.get("/static/theme_plan.js").text
    page = s.c.get("/static/package.html").text
    for control in ("pkg-approve", "pkg-line-0", "pkg-line-2", "pkg-palette", "pkg-background", "pkg-download-landscape",
                    "pkg-download-vertical"):
        assert f'id="{control}"' in page
    script = s.c.get("/static/package.js").text
    assert 'name: "style"' in script and "preview_urls" in script and "download_urls" in script and "classic" not in script


def test_visual_service_job_cache_approve_preview_stale_and_delete(service):
    s, ident = service, service.plan["plan_id"]
    s.package.media_runner = Media()
    body, code = s.package.render_visual(PID, ident, SPEC)
    assert code == 202 and body["job"]["kind"] == web.KIND
    duplicate, code = s.package.render_visual(PID, ident, SPEC)
    assert code == 200 and duplicate["job"]["id"] == body["job"]["id"]
    job = s.runner.job(body["job"]["id"])
    assert [step.lane for step in job.steps] == [RENDER]
    rows = s.package.view(PID, ident)["variants"]
    key12 = rows[0]["key12"]
    assert rows[0]["state"] == "building"
    s.runner.start()
    try:
        assert s.runner.wait_idle(5) and job.status == "done", job.error
        row = s.package.view(PID, ident)["variants"][0]
        assert row["state"] == "draft" and row["inline_url"] and row["download_url"] is None
        s.package.change_variant(PID, ident, s.plan["revision"], key12)
        assert s.package.view(PID, ident)["variants"][0]["download_url"]
        s.package.media_runner = lambda _: pytest.fail("cache used ffmpeg")
        cached, code = s.package.render_visual(PID, ident, SPEC)
        assert code == 200 and cached["variant"]["state"] == "approved"
        s.package.media_runner = Media()
        preview, code = s.package.render_visual(PID, ident, SPEC, preview=True)
        assert code == 202 and s.runner.wait_idle(5)
        assert s.runner.job(preview["job"]["id"]).status == "done"
        assert s.package.view(PID, ident)["preview"]["url"]
        plan = tp.update_plan(s.cfg, PID, ident, revision=s.plan["revision"], title="Tu học mỗi ngày",
                              clip_ids=[c["id"] for c in s.plan["clips"]])
        tp.approve_plan(s.cfg, PID, ident, revision=plan["revision"], duration_override=True)
        row = s.package.view(PID, ident)["variants"][0]
        assert row["state"] == "stale" and row["inline_url"] is None and row["download_url"] is None
        with pytest.raises(web.Unavailable):
            s.package.change_variant(PID, ident, s.plan["revision"], key12)
        s.package.change_variant(PID, ident, s.plan["revision"], key12, delete=True)
        assert s.package.view(PID, ident)["variants"] == []
    finally:
        s.runner.stop()


def test_visual_job_rechecks_tc3_and_cancelled_terminal(service):
    s, ident = service, service.plan["plan_id"]
    body, _ = s.package.render_visual(PID, ident, SPEC)
    job = s.runner.job(body["job"]["id"])
    assert s.runner.cancel(web.KIND, {job.key}) == [job]
    assert job.status == "cancelled" and not job.active
    assert all(entry["kind"] != web.KIND for entries in s.runner._snapshot_locked()["lanes"].values() for entry in entries)
    body, _ = s.package.render_visual(PID, ident, SPEC)
    job = s.runner.job(body["job"]["id"])
    path, _ = fake_output(s, s.plan)
    path.write_bytes(b"changed while waiting")
    s.package.media_runner = lambda _: pytest.fail("rendered changed TC3")
    s.runner.start()
    try:
        assert s.runner.wait_idle(5) and job.status == "failed" and "TC3" in job.error
    finally:
        s.runner.stop()


def test_http_visual_lifecycle_and_strict_routes(setup):
    s = setup
    plan = approve(s, create(s))
    tc3, _ = fake_output(s, plan)
    url = plan_path(plan) + "/package"
    s.package.media_runner = Media()
    assert s.c.post(url + "/variants", json={"visual": {"loop_seconds": "2"}}).status_code == 422
    assert s.c.post(url + "/variants", json={"visual": {"extra": 1}}).status_code == 422
    assert s.c.post(url + "/variants", json={"visual": {"loop_seconds": 3}}).status_code == 400
    assert s.c.post(url + "/variants", json=SPEC).status_code == 202
    assert s.c.post(url + "/variants", json=SPEC).status_code == 200
    row = s.c.get(url).json()["variants"][0]
    path = f"/variants/r{row['revision']}/{row['key12']}"
    assert s.c.delete(url + path).status_code == 409
    assert s.c.post(url + path + "/cancel").status_code == 200
    assert s.c.post(url + "/variants", json=SPEC).status_code == 202
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        row = s.c.get(url).json()["variants"][0]
        inline = row["inline_url"]
        download = inline.split("?")[0]
        assert s.c.get(inline).status_code == 200
        ranged = s.c.get(inline, headers={"Range": "bytes=0-9"})
        assert ranged.status_code == 206 and len(ranged.content) == 10
        assert s.c.get(download).status_code == 404
        assert s.c.post(url + path + "/approve").status_code == 200
        result = s.c.get(download)
        assert result.status_code == 200 and result.headers["content-type"] == "video/mp4"
        assert "attachment" in result.headers["content-disposition"]
        assert s.c.post(url + "/variants", json=SPEC).json()["variant"]["state"] == "approved"
        assert s.c.post(url + "/preview", json=SPEC).status_code == 202
        assert s.runner.wait_idle(5)
        preview = s.c.get(url).json()["preview"]["url"]
        assert s.c.get(preview).status_code == 200
        assert s.c.get(preview.split("?")[0]).status_code == 404
        root = download.rsplit("/", 1)[0]
        for name in ("loop-" + row["key12"] + ".mp4", "variant-" + "a" * 64 + ".mp4", "variant-" + row["key12"] + ".json", "bad.mp4"):
            assert s.c.get(root + "/" + name + "?inline=1").status_code == 404
        tc3.write_bytes(b"tampered TC3")
        assert s.c.get(inline).status_code == 404 and s.c.get(download).status_code == 404
        assert s.c.get(preview).status_code == 404
        assert s.c.delete(url + path).status_code == 200
    finally:
        s.runner.stop()


def test_visual_registered_endpoints_socket_free(service):
    """Call registered endpoints directly so lifecycle checks also run without loopback sockets."""
    s, ident = service, service.plan["plan_id"]
    s.package.media_runner = Media()
    prefix = "/api/playlists/{pid}/theme-plans/{plan_id}/package"
    def endpoint(path, method="POST"):
        return next(r.endpoint for r in s.app.routes if getattr(r, "path", None) == path and method in r.methods)
    def call(path, method="POST", **kwargs):
        if "{revision}" in path:
            kwargs.setdefault("revision", s.plan["revision"])
        return endpoint(prefix + path, method)(PID, ident, **kwargs)
    def data(result):
        return json.loads(result.body)
    body = web.VariantIn(**SPEC)
    assert call("/variants", body=web.VariantIn(visual={"loop_seconds": 3})).status_code == 400
    assert call("/variants", body=body).status_code == 202
    row = s.package.visual_view(PID, ident)["variants"][0]
    key = row["key12"]
    assert call("/variants/r{revision}/{key12}", "DELETE", key12=key).status_code == 409
    assert call("/variants/r{revision}/{key12}/cancel", key12=key).status_code == 200
    assert call("/variants", body=body).status_code == 202
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        row = s.package.visual_view(PID, ident)["variants"][0]
        file_route = endpoint("/files/playlists/{pid}/theme-pkg/{plan_rev}/{name}", "GET")
        def file(name=None, inline=0):
            return file_route(PID, f"{ident}-r1", name or f"variant-{key}.mp4", inline)
        assert file().status_code == 404 and file(inline=1).status_code == 200
        assert call("/variants/r{revision}/{key12}/approve", key12=key).status_code == 200
        assert file().headers["content-type"] == "video/mp4"
        assert "attachment" in file().headers["content-disposition"]
        assert data(call("/variants", body=body))["variant"]["state"] == "approved"
        assert call("/preview", body=body).status_code == 202
        assert s.runner.wait_idle(5)
        assert file(f"preview-{key}.mp4", inline=1).status_code == 200
        assert file(f"preview-{key}.mp4").status_code == 404
        for bad in (f"loop-{key}.mp4", f"variant-{key}.json", "variant-../../etc.mp4", "variant-" + "a" * 64 + ".mp4"):
            assert file(bad, inline=1).status_code == 404
        tc3, _ = fake_output(s, s.plan)
        tc3.write_bytes(b"tampered")
        assert file().status_code == 404 and file(inline=1).status_code == 404
        assert call("/variants/r{revision}/{key12}/approve", key12=key).status_code == 409
        assert call("/variants/r{revision}/{key12}", "DELETE", key12=key).status_code == 200
    finally:
        s.runner.stop()


@pytest.mark.parametrize("body", [{"loop_seconds": "2"}, {"loop_seconds": True}, {"asset_id": "x" * 81},
                                  {"crossfade": True}, {"crossfade": "2"}, {"mode": "x" * 17}, {"extra": 1}])
def test_visual_body_is_strict_and_bounded(body):
    with pytest.raises(ValueError):
        web.VariantIn(visual=body)


def test_visual_mutations_are_scoped_to_revision(service):
    s, ident = service, service.plan["plan_id"]
    prefix = "/api/playlists/{pid}/theme-plans/{plan_id}/package/variants/r{revision}/{key12}"
    def mutate(revision, key12, action="", method="POST"):
        endpoint = next(r.endpoint for r in s.app.routes if getattr(r, "path", None) == prefix + action and method in r.methods)
        return endpoint(PID, ident, revision, key12)

    old_plan, old_meta, old_folder, _ = s.package.context(PID, ident)
    old_tc3, _ = s.package.plans.output(PID, old_plan, verify=True)
    old_doc = visual.build(old_folder, old_tc3, old_meta, SPEC, s.cfg.packaging.asset_dir, run=Media())
    key12 = old_doc["key"][:12]
    assert mutate(old_plan["revision"], key12, "/approve").status_code == 200
    current = tp.update_plan(s.cfg, PID, ident, revision=old_plan["revision"], title="Tu học mỗi ngày",
                             clip_ids=[c["id"] for c in old_plan["clips"]])
    current = tp.approve_plan(s.cfg, PID, ident, revision=current["revision"], duration_override=True)
    current_tc3, current_meta = fake_output(s, current)
    folder = record.directory(s.cfg.render.output_dir, PID, ident, current["revision"])
    doc = visual.build(folder, current_tc3, current_meta, SPEC, s.cfg.packaging.asset_dir, run=Media())
    assert doc["key"] == old_doc["key"] and current_tc3.read_bytes() == old_tc3.read_bytes()
    assert mutate(old_plan["revision"], key12, "/approve").status_code == 409
    assert mutate(current["revision"], key12, "/approve").status_code == 200
    rows = s.package.view(PID, ident)["variants"]
    assert {(r["revision"], r["state"]) for r in rows} == {(old_plan["revision"], "stale"), (current["revision"], "approved")}
    cached, code = s.package.render_visual(PID, ident, SPEC)
    assert code == 200 and cached["variant"]["revision"] == current["revision"]
    assert cached["variant"]["state"] == "approved"
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    jobs = {}
    for plan, meta in ((old_plan, old_meta), (current, current_meta)):
        for preview in (False, True):
            key = web.visual_key(PID, ident, plan["revision"], None if preview else key12)
            target = web.VisualTarget(s.package, PID, plan, meta, variant.normalize(SPEC), preview)
            jobs[plan["revision"], preview], _ = s.runner.submit(key, web.KIND, target)
    try:
        rows = s.package.view(PID, ident)["variants"]
        assert {(r["revision"], r["key12"]) for r in rows} == {(old_plan["revision"], key12), (current["revision"], key12)}
        assert mutate(old_plan["revision"], key12, "/cancel").status_code == 200
        assert jobs[old_plan["revision"], False].status == "cancelled"
        assert jobs[old_plan["revision"], True].active
        assert mutate(old_plan["revision"], "preview", "/cancel").status_code == 200
        assert jobs[old_plan["revision"], True].status == "cancelled"
        assert all(jobs[current["revision"], preview].active for preview in (False, True))
        assert mutate(current["revision"] + 1, key12, method="DELETE").status_code == 404
        assert mutate(old_plan["revision"], key12, method="DELETE").status_code == 200
        assert not list(old_folder.iterdir())
        assert before == {p.name: p.read_bytes() for p in folder.iterdir()}
        assert all(jobs[current["revision"], preview].active for preview in (False, True))
    finally:
        s.runner.cancel(web.KIND)


def test_visual_view_caches_fingerprints_and_download_hashes_fully(service, monkeypatch):
    s, ident = service, service.plan["plan_id"]
    plan, meta, folder, _ = s.package.context(PID, ident)
    tc3, _ = s.package.plans.output(PID, plan, verify=True)
    docs = [visual.build(folder, tc3, meta, spec, s.cfg.packaging.asset_dir, run=Media())
            for spec in (SPEC, {"visual": {**SPEC["visual"], "asset_id": "generated:dawn"}})]
    counts, original = {}, hashing.sha256_file
    def sha(path):
        if path.name.startswith("variant-") and path.suffix == ".mp4":
            counts[path] = counts.get(path, 0) + 1
        return original(path)
    monkeypatch.setattr(hashing, "sha256_file", sha)
    monkeypatch.setattr(variant, "sha256_file", sha)
    files = [folder / f"variant-{d['key'][:12]}.mp4" for d in docs]
    for _ in range(2):
        assert all(v["state"] == "draft" for v in s.package.view(PID, ident)["variants"])
    assert counts == {path: 1 for path in files}
    st = files[0].stat()
    os.utime(files[0], ns=(st.st_atime_ns, st.st_mtime_ns + 1000000))
    assert all(v["state"] == "draft" for v in s.package.view(PID, ident)["variants"])
    assert counts == {files[0]: 2, files[1]: 1}
    files[0].write_bytes(files[0].read_bytes() + b"changed")
    rows = s.package.view(PID, ident)["variants"]
    assert next(v for v in rows if v["key12"] == docs[0]["key"][:12])["state"] == "stale"
    assert counts == {files[0]: 3, files[1]: 1}
    download = next(r.endpoint for r in s.app.routes if getattr(r, "path", None) ==
                    "/files/playlists/{pid}/theme-pkg/{plan_rev}/{name}")
    for _ in range(2):
        assert download(PID, folder.name, files[1].name, inline=1).status_code == 200
    assert counts[files[1]] == 3


def test_music_registered_endpoints_socket_free(service, synthetic):
    """Real AUD1 jobs plus direct route calls keep this runnable without loopback."""
    s, ident = service, service.plan["plan_id"]
    tc3, track = synthetic
    path, meta = fake_output(s, s.plan)
    shutil.copyfile(tc3, path)
    meta.update(sha256=hashing.sha256_file(path))
    atomic_write_json(path.with_suffix(".json"), meta)
    entry = assets.add(s.cfg.packaging.asset_dir, track, kind="music", source="synthetic", license="CC0")
    assets.approve(s.cfg.packaging.asset_dir, entry["id"])
    s.package.config = replace(s.package.config, render=replace(s.cfg.render, audio_bitrate="128k"))
    s.package.media_runner = None
    prefix = "/api/playlists/{pid}/theme-plans/{plan_id}/package"
    def endpoint(path, method="POST"):
        return next(r.endpoint for r in s.app.routes if getattr(r, "path", None) == path and method in r.methods)
    def call(path, method="POST", **kwargs):
        if "{revision}" in path:
            kwargs.setdefault("revision", s.plan["revision"])
        return endpoint(prefix + path, method)(PID, ident, **kwargs)
    assert call("/variants", body=web.VariantIn(visual=None, music=None)).status_code == 400
    value = dict(asset_id=entry["id"], loop_crossfade=1)
    body = web.VariantIn(visual=None, music=value)
    missing = call("/variants", body=web.VariantIn(visual={}, music=value))
    assert missing.status_code == 400 and "hãy dựng hình ambient trước" in json.loads(missing.body)["detail"]
    assert call("/preview", body=web.VariantIn(visual={}, music=value)).status_code == 202
    assert call("/variants/r{revision}/{key12}/cancel", key12="preview").status_code == 200
    assert s.package.view(PID, ident)["music_sources"][0]["id"] == entry["id"]
    assert call("/variants", body=body).status_code == 202
    assert call("/variants", body=body).status_code == 200
    row = s.package.visual_view(PID, ident)["variants"][0]
    key = row["key12"]
    assert key == variant.key(body.model_dump(), meta["sha256"], settings=music.encoding("128k"))[:12]
    assert call("/variants/r{revision}/{key12}", "DELETE", key12=key).status_code == 409
    assert call("/variants/r{revision}/{key12}/cancel", key12=key).status_code == 200
    assert call("/variants", body=body).status_code == 202
    s.runner.start()
    try:
        assert s.runner.wait_idle(30)
        row = s.package.visual_view(PID, ident)["variants"][0]
        assert row["state"] == "draft", row
        download = endpoint("/files/playlists/{pid}/theme-pkg/{plan_rev}/{name}", "GET")
        def file(name=None, inline=0):
            return download(PID, f"{ident}-r1", name or f"variant-{key}.mp4", inline)
        assert file().status_code == 404 and file(inline=1).status_code == 200
        assert call("/variants/r{revision}/{key12}/approve", key12=key).status_code == 200
        assert file().headers["content-type"] == "video/mp4"
        assert json.loads(call("/variants", body=body).body)["variant"]["state"] == "approved"
        assert call("/preview", body=body).status_code == 202
        assert s.runner.wait_idle(30)
        preview = s.package.visual_view(PID, ident)["preview"]
        assert preview["url"] is None and len(preview["audio_urls"]) == 3
        for i in (1, 2, 3):
            response = file(f"preview-{key}-{i}.m4a", inline=1)
            assert response.status_code == 200 and response.headers["content-type"] == "audio/mp4"
            assert file(f"preview-{key}-{i}.m4a").status_code == 404
        for bad in (f"preview-{key}-0.m4a", f"preview-{key}-4.m4a", f"preview-{key}-1.mp4", "preview-../../etc.m4a"):
            assert file(bad, inline=1).status_code == 404
        folder = record.directory(s.cfg.render.output_dir, PID, ident, 1)
        preview_file = folder / f"preview-{key}-2.m4a"
        previous = preview_file.read_bytes()
        preview_file.write_bytes(b"tampered")
        assert file(preview_file.name, inline=1).status_code == 404
        preview_file.write_bytes(previous)
        library = json.loads((s.cfg.packaging.asset_dir / "library.json").read_text())
        library["assets"][0]["approved"] = False
        atomic_write_json(s.cfg.packaging.asset_dir / "library.json", library)
        assert s.package.visual_view(PID, ident)["variants"][0]["state"] == "stale"
        assert file(inline=1).status_code == 404 and file(f"preview-{key}-1.m4a", inline=1).status_code == 404
        assert call("/variants/r{revision}/{key12}/approve", key12=key).status_code == 409
        assert call("/variants/r{revision}/{key12}", "DELETE", key12=key).status_code == 200
    finally:
        s.runner.stop()


@pytest.mark.parametrize("value", [dict(level_lu=0), dict(level_lu=True), dict(fade_in="3"),
                                  dict(loop_crossfade=float("nan")), dict(extra=1)])
def test_music_body_is_strict(value):
    with pytest.raises(ValueError):
        web.VariantIn(visual=None, music=dict(asset_id="a" * 64) | value)


def test_music_routes_auth_middleware_socket_free(service):
    s = service
    dispatch = next(m.kwargs["dispatch"] for m in s.app.user_middleware
                    if getattr(m.kwargs.get("dispatch"), "__name__", None) == "auth_middleware")
    from auto_short.web.auth import COOKIE_NAME
    async def check():
        for method, path in (("POST", f"/api/playlists/{PID}/theme-plans/abcdefgh/package/variants"),
                             ("POST", f"/api/playlists/{PID}/theme-plans/abcdefgh/package/preview"),
                             ("GET", f"/files/playlists/{PID}/theme-pkg/abcdefgh-r1/preview-{'a' * 12}-1.m4a")):
            for signed_in in (False, True):
                called = False
                async def downstream(request):
                    nonlocal called
                    called = True
                    return Response(status_code=204)
                headers = [(b"cookie", f"{COOKIE_NAME}={s.app.state.signer.issue()}".encode())] if signed_in else []
                request = Request(dict(type="http", method=method, path=path, headers=headers, query_string=b""))
                response = await dispatch(request, downstream)
                assert response.status_code == (204 if signed_in else 401)
                assert called is signed_in
    asyncio.run(check())
