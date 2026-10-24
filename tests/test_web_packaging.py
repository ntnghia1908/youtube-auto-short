"""PKG1: authenticated HTTP routes plus socket-free service/job verification."""
import json
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from auto_short import hashing, theme_plan as tp
from auto_short.config import PackagingConfig
from auto_short.packaging import PackageError, record, thumbnail, variant, visual
from auto_short.web import packaging as web
from auto_short.web.jobs import RENDER
from auto_short.workspace import atomic_write_json

from test_packaging_thumbnail import fake_media
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
    s.package.edit(PID, pid, web.EditIn(title="Chuyên tâm tu học", headline="Niệm Phật vãng sanh — buông xả"))
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
        assert s.package.view(PID, pid)["package"]["download_url"].endswith(".jpg")
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
    assert all(t["preview_url"] is None for t in view["package"]["thumbnails"])
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
    assert s.c.put(url, json={"title": "Chuyên tâm tu học", "headline": "Niệm Phật"}).status_code == 200
    assert s.c.put(url, json={"headline": "niệm Phật " * 80}).status_code == 422
    assert s.c.put(url, json={"selected": "../../bad"}).status_code == 400


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
        preview = view["thumbnails"][0]["preview_url"]
        download = preview.split("?")[0]
        assert s.c.get(preview).status_code == 200
        assert s.c.get(download).status_code == 404
        assert s.c.post(url + "/approve").status_code == 200
        result = s.c.get(download)
        assert result.status_code == 200 and result.headers["content-type"] == "image/jpeg"
        assert "filename*=UTF-8" in result.headers["content-disposition"]
        if changed == "revision":
            assert s.c.put(plan_path(plan), json={"revision": plan["revision"], "title": "Tu học mỗi ngày",
                        "clip_ids": [c["id"] for c in plan["clips"]]}).status_code == 200
        elif changed == "tc3":
            path.write_bytes(b"changed")
        else:
            folder = record.directory(s.cfg.render.output_dir, PID, plan["plan_id"], plan["revision"])
            (folder / view["thumbnails"][0]["file"]).write_bytes(b"changed")
        assert s.c.get(download).status_code == 404
        assert s.c.get(url).json()["package"]["state"] == "stale"
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
    file = f"/files/playlists/{PID}/theme-pkg/{plan['plan_id']}-r1/classic-{'a' * 64}.jpg"
    assert anon.get(file).status_code == 401
    assert s.c.get(f"/playlists/{PID}/theme-plans/{plan['plan_id']}/package").status_code == 200
    for pid, ident in [("bad!", plan["plan_id"]), ("PLunknown", plan["plan_id"]), (PID, "bad!"), (PID, "12345678")]:
        result = s.c.get(f"/api/playlists/{pid}/theme-plans/{ident}/package")
        assert result.status_code == 404 and result.headers["cache-control"] == "no-store"
    for suffix in ("classic-invalid.jpg", "package.json", "..%5Csecret.jpg"):
        assert s.c.get(file.rsplit("/", 1)[0] + "/" + suffix).status_code == 404
    _, _, folder, doc = s.package.context(PID, plan["plan_id"])
    doc = thumbnail.build(folder, doc, s.package.config.packaging.asset_dir, run=fake_media)
    record.write(folder, doc)
    selected = folder / doc["thumbnails"][0]["file"]
    selected.unlink()
    selected.symlink_to(folder.parent.parent / f"{plan['plan_id']}-r1.mp4")
    assert s.c.get(file.rsplit("/", 1)[0] + "/" + selected.name + "?inline=1").status_code == 404
    assert "Đóng gói" in s.c.get("/static/theme_plan.js").text
    assert "pkg-approve" in s.c.get("/static/package.html").text


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
