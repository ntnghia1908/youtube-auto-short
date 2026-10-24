"""PKG1: authenticated HTTP routes plus socket-free service/job verification."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from auto_short import theme_plan as tp
from auto_short.config import PackagingConfig
from auto_short.packaging import PackageError, record, thumbnail
from auto_short.web import packaging as web
from auto_short.web.jobs import RENDER
from auto_short.workspace import atomic_write_json

from test_packaging_thumbnail import fake_media
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
