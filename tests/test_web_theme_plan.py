"""TC2 phase C: offline HTTP / queue integration and the Favorites JS card."""
import json
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from auto_short import hashing, theme_plan as tp
from auto_short.config import Config, WorkspaceConfig
from auto_short.ingest.youtube import DownloadError, YoutubeBlocked
from auto_short.pipeline import OllamaUnavailable, PreflightError
from auto_short.render.full import SourceBlocked
from auto_short.selection.client import ChatError, ChatUnavailable
from auto_short.store import index_cache
from auto_short.web import theme_plan as web
from auto_short.web.auth import COOKIE_NAME
from auto_short.web.jobs import AI, PREPARE, RENDER, GpuUnavailable, JobFailed, JobRunner, YoutubeWait
from auto_short.workspace import atomic_write_json

from test_theme_plan import Planner
from test_web_theme_index import STATIC, fx, snapshot
from wait_helpers import wait_for

PID = "PLeligible"
BASE = f"/api/playlists/{PID}"
PW = "pw"


@pytest.fixture(autouse=True)
def isolated_index_cache():
    index_cache.invalidate()
    yield
    wait_for(lambda: index_cache._REFRESHING is None, what="store refresh finished")
    index_cache.invalidate()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    cfg = fx.seed(tmp_path / "scratch")
    # The preview fixture predates shared originals: give prepare the ingest owner.
    for episode in cfg.workspace.dir.glob("*.kt"):
        if (episode / "source.mp4").is_file():
            owner = cfg.workspace.dir / episode.name.removesuffix(".kt")
            owner.mkdir(exist_ok=True)
            for name in ("manifest.json", "source.mp4"):
                shutil.copyfile(episode / name, owner / name)
    app = fx.build_app(cfg, PW, restrict=False)
    c = TestClient(app, follow_redirects=False)
    c.cookies.set(COOKIE_NAME, c.post("/login", json={"password": PW}).cookies[COOKIE_NAME])
    original = tp.propose
    calls = []

    def propose(config, pid):
        calls.append(pid)
        return original(config, pid, client=Planner())

    monkeypatch.setattr(tp, "propose", propose)
    return SimpleNamespace(cfg=cfg, app=app, c=c, service=app.state.theme_plans,
                           runner=app.state.runner, calls=calls, root=tmp_path / "scratch")


def create(s):
    generated = tp.propose(s.cfg, PID)
    result = s.c.post(BASE + "/theme-plans", json={"proposal_id": generated["proposals"][0]["proposal_id"]})
    assert result.status_code == 201, result.text
    return result.json()


def plan_path(plan):
    return BASE + "/theme-plans/" + plan["plan_id"]


def approve(s, plan):
    r = s.c.post(plan_path(plan) + "/approve", json={"revision": plan["revision"], "duration_override": True})
    assert r.status_code == 200, r.text
    return r.json()


def fake_output(s, plan):
    path = s.cfg.render.output_dir / "_compilations" / PID / "theme" / f"{plan['plan_id']}-r{plan['revision']}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"completed-mp4")
    meta = dict(schema_version=1, plan_id=plan["plan_id"], revision=plan["revision"],
                plan_fingerprint=tp.plan_fingerprint(plan), encode_key="encoding", sha256=hashing.sha256_file(path),
                duration=350, chapters=[{"start": 0, "title": "Tu học"}], description="00:00 Tu học\n\nMô tả",
                download_name="Tu học.mp4")
    atomic_write_json(path.with_suffix(".json"), meta)
    return path, meta


def test_auth_and_missing_pid(setup):
    s = setup
    anon = TestClient(s.app, follow_redirects=False)
    assert anon.get(f"/playlists/{PID}/favorites").status_code == 303
    for method, route, body in [("get", "/theme-plan", None), ("post", "/theme-plan/generate", None),
                                ("post", "/theme-plans", {}), ("put", "/theme-plans/12345678", {}),
                                ("post", "/theme-plans/12345678/approve", {}),
                                ("delete", "/theme-plans/12345678", None),
                                ("post", "/theme-plans/12345678/render", None)]:
        assert anon.request(method, BASE + route, json=body).status_code == 401
    assert anon.get(f"/files/playlists/{PID}/theme/12345678-r1.mp4").status_code == 401
    for pid in ("bad!", "PLunknown"):
        for method, route, body in [("get", "/theme-plan", None), ("post", "/theme-plan/generate", None),
                                    ("post", "/theme-plans", {"proposal_id": "x"}),
                                    ("delete", "/theme-plans/12345678", None),
                                    ("post", "/theme-plans/12345678/render", None)]:
            r = s.c.request(method, f"/api/playlists/{pid}" + route, json=body)
            assert r.status_code == 404
            assert r.headers["cache-control"] == "no-store"


def test_generate_dedup_lane_and_result(setup):
    s = setup
    first = s.c.post(BASE + "/theme-plan/generate")
    second = s.c.post(BASE + "/theme-plan/generate")
    assert first.status_code == 202 and second.status_code == 200
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    assert not s.calls
    job = s.runner.latest(web.generate_key(PID))
    assert job.kind == web.KIND_GENERATE and [step.lane for step in job.steps] == [AI]
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        assert job.status == "done", job.error
        assert s.calls == [PID]
        view = s.c.get(BASE + "/theme-plan").json()
        assert view["generate_job"]["status"] == "done" and view["proposals"]["proposals"]
    finally:
        s.runner.stop()


def test_get_is_read_only_without_ai_and_redacts(setup, monkeypatch):
    s = setup
    create(s)
    monkeypatch.setattr(tp, "propose", lambda *a, **kw: pytest.fail("GET called propose"))
    monkeypatch.setattr(hashing, "sha256_file", lambda *a: pytest.fail("warm GET hashed media"))
    before = snapshot(s.root)
    r = s.c.get(BASE + "/theme-plan")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["index_summary"]["usable"] == 1
    assert body["clips_available"][0]["duration"] == 350
    assert "Tập" in body["clips_available"][0]["label"]
    assert body["plans"][0]["check"]["state"] == "draft"
    assert body["plans"][0]["sources"] == {"total": 1, "ready": 1, "store": 0, "youtube": 0}
    assert str(s.root) not in r.text and str(s.root.parent) not in r.text
    assert before == snapshot(s.root)


def test_index_summary_and_plans_share_one_audit(setup, monkeypatch):
    s = setup
    plan = create(s)
    original = web.theme_index.audit_playlist
    calls = []
    def audited(*args, **kwargs):
        calls.append(args[1])
        result = original(*args, **kwargs)
        for rec in result:
            if rec.get("status") == "eligible":
                rec["source_status"] = "missing"
        return result
    monkeypatch.setattr(web.theme_index, "audit_playlist", audited)
    result = s.c.get(BASE + "/theme-plan")
    assert result.status_code == 200
    assert result.json()["index_summary"]["source_missing"] == 1
    assert calls == [PID]
    s.c.delete(plan_path(plan))
    calls.clear()
    s.c.get(BASE + "/theme-plan")
    assert calls == [PID]


def test_index_summary_separates_pending_from_unusable(setup, monkeypatch):
    s = setup
    original = web.theme_index.build_index
    disabled = web.GENERATION_DISABLED

    def with_extra(*args, **kwargs):
        index = original(*args, **kwargs)
        def rec(n, status, reason):
            return {"status": status, "reason": reason, "identity": {"episode_id": f"x{n}", "clip": f"c{n}"}}
        index["records"] = list(index["records"]) + [
            rec(1, "ai_error", disabled), rec(2, "ai_error", disabled),
            rec(3, "ai_error", "model timeout"),
            rec(4, "ineligible", "not a khai thi episode"), rec(5, "ineligible", "not a khai thi episode")]
        return index

    monkeypatch.setattr(web.theme_index, "build_index", with_extra)
    summary = s.c.get(BASE + "/theme-plan").json()["index_summary"]
    assert summary["total"] == 6 and summary["usable"] == 1
    assert summary["pending"] == 2 and summary["unusable"] == 3
    assert summary["by_status"]["ai_error"] == 3 and "source_missing" in summary
    reasons = {r["reason"]: r["count"] for r in summary["common_reasons"]}
    assert reasons == {"not a khai thi episode": 2, "model timeout": 1}


def test_get_and_download_do_not_take_service_write_lock(setup, monkeypatch):
    s = setup
    plan = approve(s, create(s))
    path, _ = fake_output(s, plan)
    class NoReadLock:
        def __enter__(self):
            pytest.fail('read route took the service write lock')
        def __exit__(self, *_args):
            pass
    monkeypatch.setattr(s.service, 'lock', NoReadLock())
    assert s.c.get(BASE + '/theme-plan').status_code == 200
    result = s.c.get(f'/files/playlists/{PID}/theme/{path.name}')
    assert result.status_code == 200 and result.content == b'completed-mp4'


def test_create_edit_conflict_approve_override_and_delete(setup):
    s = setup
    plan = create(s)
    path = plan_path(plan)
    assert s.c.post(path + "/approve", json={"revision": 1}).status_code == 409  # only 350 seconds
    plan = approve(s, plan)
    assert plan["approval"]["duration_override"] is True
    ids = [c["id"] for c in plan["clips"]]
    r = s.c.put(path, json={"revision": 1, "title": "Tiêu đề mới", "clip_ids": ids})
    assert r.status_code == 200
    plan = r.json()
    assert plan["revision"] == 2 and plan["approval"] is None
    conflict = s.c.put(path, json={"revision": 1, "title": "Cũ", "clip_ids": ids})
    assert conflict.status_code == 409 and "đã có thay đổi khác, tải lại" in conflict.json()["detail"]
    assert s.c.post(path + "/approve", json={"revision": 1, "duration_override": True}).status_code == 409
    assert s.c.post(path + "/approve", json={"revision": 2, "duration_override": "yes"}).status_code == 422
    assert s.c.post(path + "/approve", json={"revision": True}).headers["cache-control"] == "no-store"
    assert s.c.put(path, json={"revision": 2, "title": "x", "clip_ids": ["fake"]}).status_code == 400
    assert s.c.delete(path).status_code == 200
    assert s.c.delete(path).status_code == 404
    assert s.c.post(path + "/render").status_code == 404
    assert s.c.get(BASE + "/theme-plan").json()["plans"] == []


def test_render_approved_only_dedup_and_delete_busy(setup, monkeypatch):
    s = setup
    plan = create(s)
    path = plan_path(plan)
    assert s.c.post(path + "/render").status_code == 409
    plan = approve(s, plan)
    calls = []

    def render(config, pid, plan_id, *, hashtags):
        calls.append((config, pid, plan_id, hashtags))
        out, meta = fake_output(s, plan)
        return SimpleNamespace(path=out, metadata=meta, ran=True)

    monkeypatch.setattr(web.theme_render, "render_landscape", render)
    r = s.c.post(path + "/render")
    assert r.status_code == 202
    assert s.c.post(path + "/render").json()["job"]["id"] == r.json()["job"]["id"]
    assert s.c.post(path + "/render").status_code == 200
    job = s.runner.latest(web.render_key(PID, plan["plan_id"]))
    assert [step.lane for step in job.steps] == [PREPARE, RENDER]
    assert s.c.delete(path).status_code == 409
    assert s.c.put(path, json={"revision": 1, "title": "x", "clip_ids": [c["id"] for c in plan["clips"]]}).status_code == 409
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        assert job.status == "done", job.error
    finally:
        s.runner.stop()
    assert len(calls) == 1
    assert calls[0][3] == s.service.playlists.effective_hashtags(s.service.playlists.load(PID))[0]
    view = s.c.get(BASE + "/theme-plan").json()["plans"][0]
    assert view["render_job"]["status"] == "done"
    assert view["output"]["description"].startswith("00:00")
    dl = s.c.get(view["output"]["download_url"])
    assert dl.status_code == 200 and dl.content == b"completed-mp4"
    assert unquote(dl.headers["content-disposition"].split("filename*=UTF-8''")[1]) == "Tu học.mp4"


def test_inline_file_range_and_hash_policy(setup, monkeypatch):
    s = setup
    plan = approve(s, create(s))
    path, meta = fake_output(s, plan)
    url = f"/files/playlists/{PID}/theme/{path.name}"
    original_hash = hashing.sha256_file
    video_hashes = []

    def track_hash(file):
        if file == path:
            video_hashes.append(file)
        return original_hash(file)

    monkeypatch.setattr(hashing, "sha256_file", track_hash)
    full = s.c.get(url + "?inline=1")
    assert full.status_code == 200 and full.content == b"completed-mp4"
    assert full.headers["content-type"] == "video/mp4"
    assert "attachment" not in full.headers.get("content-disposition", "")
    for byte_range, expected, content_range in [
        ("bytes=0-3", b"comp", "bytes 0-3/13"),
        ("bytes=4-", b"leted-mp4", "bytes 4-12/13"),
    ]:
        part = s.c.get(url + "?inline=1", headers={"Range": byte_range})
        assert part.status_code == 206 and part.content == expected
        assert part.headers["content-range"] == content_range
        assert part.headers["content-type"] == "video/mp4"
        assert "attachment" not in part.headers.get("content-disposition", "")
    assert not video_hashes
    download = s.c.get(url)
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")
    assert video_hashes == [path]
    path.write_bytes(b"changed video")
    assert s.c.get(url).status_code == 404
    path.write_bytes(b"")
    assert s.c.get(url + "?inline=1").status_code == 404
    path.write_bytes(b"completed-mp4")
    meta["plan_fingerprint"] = "bad"
    atomic_write_json(path.with_suffix(".json"), meta)
    assert s.c.get(url + "?inline=1").status_code == 404


@pytest.mark.parametrize("damage", ["no-file", "no-meta", "revision", "fingerprint", "hash", "schema", "symlink"])
def test_file_fail_closed(setup, damage):
    s = setup
    plan = approve(s, create(s))
    path, meta = fake_output(s, plan)
    url = f"/files/playlists/{PID}/theme/{path.name}"
    assert s.c.get(url).status_code == 200
    if damage == "no-file":
        path.unlink()
    elif damage == "no-meta":
        path.with_suffix(".json").unlink()
    elif damage == "hash":
        path.write_bytes(b"partial or changed")
    elif damage == "symlink":
        elsewhere = s.root / "elsewhere.mp4"
        path.rename(elsewhere)
        path.symlink_to(elsewhere)
    else:
        meta[{"revision": "revision", "fingerprint": "plan_fingerprint", "schema": "schema_version"}[damage]] = "bad"
        atomic_write_json(path.with_suffix(".json"), meta)
    assert s.c.get(url).status_code == 404
    for name in ["bad.mp4", f"{plan['plan_id']}-r0.mp4", f"{plan['plan_id']}-r01.mp4", f"{plan['plan_id']}-r2.mp4"]:
        assert s.c.get(f"/files/playlists/{PID}/theme/{name}").status_code == 404


def test_stale_plan_cannot_render_or_download(setup):
    s = setup
    plan = approve(s, create(s))
    path, _ = fake_output(s, plan)
    # Tamper with the rendered Short; TC1 re-audit invalidates the approval.
    rec = web.theme_index.build_index(s.cfg, PID, write=False, client=web.RefusingClient())["records"][0]
    rendered = s.cfg.render.output_dir / rec["identity"]["episode_id"] / "render_manifest.json"
    doc = json.loads(rendered.read_text())
    doc["shorts"][0]["origin"] = "changed"
    atomic_write_json(rendered, doc)
    view = s.c.get(BASE + "/theme-plan").json()
    assert view["plans"][0]["check"]["state"] == "stale" and view["plans"][0]["output"] is None
    assert s.c.post(plan_path(plan) + "/render").status_code == 409
    assert s.c.get(f"/files/playlists/{PID}/theme/{path.name}").status_code == 404


@pytest.mark.parametrize("where", ["preflight", "chat", "legacy-chat", "index"])
def test_ollama_down_waits_in_ai_lane(setup, monkeypatch, where):
    s = setup
    if where == "preflight":
        def preflight(config):
            raise OllamaUnavailable("offline /private/server/model")
        s.service.preflight = preflight
    elif where == "index":
        monkeypatch.setattr(tp, "propose", lambda *a: dict(index_counts={"by_status": {"ai_error": 1}},
                           shortfall="no indexed clips: connection refused", proposals=[], rejected_themes=[]))
    else:
        def down(*args):
            raise (ChatUnavailable if where == "chat" else ChatError)("connection refused /private/server/model")
        monkeypatch.setattr(tp, "propose", down)
    s.c.post(BASE + "/theme-plan/generate")
    job = s.runner.latest(web.generate_key(PID))
    s.runner.start()
    try:
        deadline = time.monotonic() + 3
        while not job.gpu_wait and time.monotonic() < deadline:
            time.sleep(.01)
        assert job.gpu_wait and job.active and job.status != "failed"
        r = s.c.get(BASE + "/theme-plan")
        assert r.json()["generate_job"]["gpu_wait"] is True
        assert "/private/server" not in r.text
    finally:
        s.runner.stop()


def test_other_ai_errors_fail_and_latest_error_stays_visible(setup, monkeypatch):
    s = setup
    create(s)  # previous valid proposals
    result = dict(proposals=[], rejected_themes=[{"position": 0, "reason": "bad /private/server/data"}],
                  ai_error="AI malformed /private/server/data")
    monkeypatch.setattr(tp, "propose", lambda *a: result)
    s.c.post(BASE + "/theme-plan/generate")
    job = s.runner.latest(web.generate_key(PID))
    with pytest.raises(JobFailed, match="AI malformed"):
        job.target(job)
    view = s.c.get(BASE + "/theme-plan")
    assert view.json()["proposals"]["ai_error"] and "/private/server" not in view.text
    s.service.preflight = lambda c: (_ for _ in ()).throw(PreflightError("missing model"))
    with pytest.raises(JobFailed, match="missing model") as exc:
        job.target(job)
    assert not isinstance(exc.value, GpuUnavailable)


def test_youtube_blocked_has_retry_message(setup, monkeypatch):
    s = setup
    plan = approve(s, create(s))
    def blocked(*args, **kwargs):
        raise SourceBlocked("blocked /private/server")
    monkeypatch.setattr(web.theme_render, "render_landscape", blocked)
    s.c.post(plan_path(plan) + "/render")
    job = s.runner.latest(web.render_key(PID, plan["plan_id"]))
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        assert job.status == "failed" and job.error == "Nguồn chưa sẵn sàng, bấm Ghép lại"
        view = s.c.get(BASE + "/theme-plan").json()["plans"][0]
        assert view["render_job"]["error"] == job.error
    finally:
        s.runner.stop()


def test_corrupt_artifacts_and_redaction(setup):
    s = setup
    assert s.c.get("/api/playlists/PLmalformed/theme-plan").status_code == 422
    plan = create(s)
    folder = s.cfg.render.output_dir / "_compilations" / PID
    file = folder / "theme_plans" / f"{plan['plan_id']}.json"
    file.write_text('{"broken":')
    view = s.c.get(BASE + "/theme-plan")
    assert view.status_code == 200 and view.json()["plans"][0]["check"]["state"] == "invalid"
    assert str(s.root.parent) not in view.text
    assert s.c.post(plan_path(plan) + "/render").status_code == 422
    assert s.c.delete(plan_path(plan)).status_code == 200
    (folder / "theme_proposals.json").write_text("{")
    r = s.c.get(BASE + "/theme-plan")
    assert r.status_code == 422 and str(s.root.parent) not in r.text
    atomic_write_json(folder / "theme_proposals.json", dict(schema_version=1, playlist_id=PID, proposals="broken"))
    assert s.c.get(BASE + "/theme-plan").status_code == 422
    assert s.c.post(BASE + "/theme-plans", json={"proposal_id": "x"}).status_code == 422


def test_plain_ai_error_is_failure_and_redacted(setup, monkeypatch):
    s = setup
    def error(*args):
        raise ChatError("invalid envelope /private/server/response")
    monkeypatch.setattr(tp, "propose", error)
    s.c.post(BASE + "/theme-plan/generate")
    job = s.runner.latest(web.generate_key(PID))
    s.runner.start()
    try:
        assert s.runner.wait_idle(5)
        assert job.status == "failed" and not job.gpu_wait
        result = s.c.get(BASE + "/theme-plan")
        assert "invalid envelope" in result.json()["generate_job"]["error"]
        assert "/private/server" not in result.text
    finally:
        s.runner.stop()


def test_restart_skips_theme_jobs(setup):
    s = setup
    s.c.post(BASE + "/theme-plan/generate")
    # submit has already persisted the queued target.
    app = fx.build_app(s.cfg, PW, restrict=False)
    app.state.runner.restore()
    assert not app.state.runner.jobs()


def test_render_target_passes_playlist_hashtags_without_http(monkeypatch):
    plan = {'plan_id': '12345678', 'revision': 1}
    playlist = {'playlist_id': PID}
    calls = []
    monkeypatch.setattr(tp, 'approved_plan', lambda *args: plan)

    def render(config, pid, plan_id, *, hashtags):
        calls.append((config, pid, plan_id, hashtags))
        return SimpleNamespace(metadata={'duration': 120})

    monkeypatch.setattr(web.theme_render, 'render_landscape', render)
    service = SimpleNamespace(config=object(), playlists=SimpleNamespace(
        load=lambda pid: playlist, effective_hashtags=lambda doc: (['#DiaTang', '#PhatPhap'], True)))
    job = SimpleNamespace(stage=None, summary=None)
    web.RenderTarget(service, PID, plan)(job)
    assert calls == [(service.config, PID, plan['plan_id'], ['#DiaTang', '#PhatPhap'])]
    assert job.stage is None and '2.0' in job.summary


@pytest.fixture
def source_target(monkeypatch):
    plan = {"plan_id": "12345678", "revision": 1,
            "clips": [{"episode_id": "a.kt"}, {"episode_id": "a"}, {"episode_id": "b.kt"}]}
    cfg = Config()
    cfg = replace(cfg, store=replace(cfg.store, enabled=True))
    service = SimpleNamespace(config=cfg, playlists=SimpleNamespace(
        load=lambda pid: {}, effective_hashtags=lambda doc: ([], False)))
    target = web.RenderTarget(service, PID, plan)
    monkeypatch.setattr(tp, "approved_plan", lambda *args: plan)
    workspace, cached, remote, calls = set(), set(), set(), []

    def head(vid, kind):
        calls.append(("head", vid, kind))
        if vid not in remote:
            raise web.StoreError("store missing or down")
        return {"sha256": "a" * 64, "size": 10}

    def fetch(config, vid):
        calls.append(("youtube", vid))
        cached.add(vid)
        return "cached.mp4"

    monkeypatch.setattr(web.sources, "workspace_source", lambda cfg, vid: "source.mp4" if vid in workspace else None)
    monkeypatch.setattr(web.sources, "cached_source", lambda cfg, vid: "cached.mp4" if vid in cached else None)
    monkeypatch.setattr(web.sources, "fetch_to_cache", fetch)
    monkeypatch.setattr(web, "local_source_ready", lambda cfg, vid: vid in workspace or vid in cached)
    monkeypatch.setattr(web.StoreClient, "from_config", lambda cfg: SimpleNamespace(head=head))
    monkeypatch.setattr(index_cache, "source_ids", lambda cfg, *, blocking=False: frozenset())
    monkeypatch.setattr(web.theme_render, "render_landscape", lambda *args, **kw: SimpleNamespace(
        metadata={"duration": 120}))
    return SimpleNamespace(target=target, workspace=workspace, cached=cached, remote=remote, calls=calls)


def test_needs_download_store_snapshot_bypasses_youtube_backoff_without_http(source_target, monkeypatch):
    s = source_target
    store_videos = {"a", "b"}

    def source_ids(config, *, blocking):
        assert config is s.target.service.config and blocking is False
        return frozenset(store_videos)

    monkeypatch.setattr(index_cache, "source_ids", source_ids)
    runner = JobRunner()
    job, _ = runner.submit("theme-test", web.KIND_THEME_RENDER, s.target)
    with runner._lock:
        runner._set_yt_blocked_locked("HTTP Error 403")
    assert job.yt_wait
    assert s.target.needs_download() is False
    assert runner._no_download(job)
    store_videos.remove("b")
    assert s.target.needs_download() is True
    assert not runner._no_download(job)
    store_videos.add("b")
    s.target.youtube_wait = True
    assert s.target.needs_download() is True
    s.target.youtube_wait = False
    store_videos.clear()
    assert s.target.needs_download() is True
    assert not s.calls


@pytest.mark.parametrize("location", ["workspace", "cache", "store", "youtube", "store-disabled"])
def test_sources_prepare_order_and_dedup_without_http(source_target, location):
    s = source_target
    if location == "workspace":
        s.workspace.update(["a", "b"])
    elif location == "cache":
        s.cached.update(["a", "b"])
    elif location == "store":
        s.remote.update(["a", "b"])
    elif location == "store-disabled":
        cfg = s.target.service.config
        s.target.service.config = replace(cfg, store=replace(cfg.store, enabled=False))
    job = SimpleNamespace(stage=None, youtube_ok=lambda: s.calls.append(("ok",)))
    steps = s.target.lane_steps()
    assert [step.lane for step in steps] == [PREPARE, RENDER]
    steps[0].run(job)
    steps[1].run(job)
    assert job.stage is None and "2.0" in job.summary
    if location in ("workspace", "cache"):
        assert s.calls == []
        assert not s.target.needs_download()
    elif location == "store":
        assert s.calls == [("head", "a", "source"), ("head", "b", "source")]
    elif location == "youtube":
        assert s.calls == [("head", "a", "source"), ("youtube", "a"), ("ok",),
                           ("head", "b", "source"), ("youtube", "b"), ("ok",)]
    else:
        assert s.calls == [("youtube", "a"), ("ok",), ("youtube", "b"), ("ok",)]


@pytest.mark.parametrize("error", [
    YoutubeBlocked("bot-check"), SourceBlocked("blocked"),
    DownloadError("Sign in to confirm you’re not a bot"),
    DownloadError("HTTP Error 429"), DownloadError("HTTP Error 403: Forbidden"),
    web.RenderError("tải lại: HTTP 403"), web.RenderError("HTTP:403"),
    DownloadError("unavailable format"), web.RenderError("bad duration"), OSError("disk full"),
])
def test_sources_prepare_errors_without_http(source_target, monkeypatch, error):
    def fail(*args):
        raise error
    monkeypatch.setattr(web.sources, "fetch_to_cache", fail)
    wait = isinstance(error, (YoutubeBlocked, SourceBlocked)) or "HTTP" in str(error) or "bot" in str(error)
    with pytest.raises(YoutubeWait if wait else JobFailed) as raised:
        source_target.target.prepare(SimpleNamespace(stage=None))
    assert isinstance(raised.value, YoutubeWait) is wait


def test_sources_prepare_rejects_changed_plan_before_io_without_http(source_target, monkeypatch):
    plan = {**source_target.target.plan, "revision": 2}
    monkeypatch.setattr(tp, "approved_plan", lambda *args: plan)
    with pytest.raises(JobFailed, match="kế hoạch đã thay đổi"):
        source_target.target.prepare(SimpleNamespace(stage=None))
    assert not source_target.calls


@pytest.mark.parametrize("error", [SourceBlocked("bot"), DownloadError("HTTP Error 403"),
                                  web.RenderError("HTTP 403")])
def test_sources_render_race_requests_retry_without_http(source_target, monkeypatch, error):
    def fail(*args, **kw):
        raise error
    monkeypatch.setattr(web.theme_render, "render_landscape", fail)
    with pytest.raises(JobFailed, match="Nguồn chưa sẵn sàng, bấm Ghép lại") as raised:
        source_target.target(SimpleNamespace(stage=None))
    assert not isinstance(raised.value, YoutubeWait)


@pytest.mark.parametrize("optimistic_stat", [False, True])
def test_sources_queue_backoff_retains_cache_and_frees_render_without_http(source_target, monkeypatch, optimistic_stat):
    s = source_target
    if optimistic_stat:
        monkeypatch.setattr(web, "local_source_ready", lambda *a: True)
    clock = [0.0]
    runner = JobRunner(monotonic=lambda: clock[0], wall=lambda: 1_800_000_000 + clock[0],
                       youtube_retry_seconds=60, youtube_retry_max_seconds=120)
    attempts = []
    failures = [2]
    rendered = []

    def fetch(config, vid):
        attempts.append(vid)
        if vid == "b" and failures[0]:
            failures[0] -= 1
            raise DownloadError("HTTP Error 403: Forbidden")
        s.cached.add(vid)
        return "cached.mp4"

    monkeypatch.setattr(web.sources, "fetch_to_cache", fetch)
    monkeypatch.setattr(web.theme_render, "render_landscape", lambda *args, **kw:
                        (rendered.append("theme") or SimpleNamespace(metadata={"duration": 120})))
    job, _ = runner.submit("theme-test", web.KIND_THEME_RENDER, s.target)
    runner.start()
    try:
        wait_for(lambda: job.yt_wait, timeout=3)
        assert job.status == "queued" and job.step == 0 and not rendered
        assert attempts == ["a", "b"] and s.cached == {"a"}
        other, _ = runner.submit("other", "render", lambda job: rendered.append("other"))
        wait_for(lambda: other.status == "done", timeout=3)
        assert attempts == ["a", "b"] and rendered == ["other"]
        for moment, count in [(60, 3), (179, 3), (180, 4)]:
            with runner._lock:
                clock[0] = moment
                runner._lock.notify_all()
            if moment != 179:
                wait_for(lambda: len(attempts) == count, timeout=3)
                wait_for(lambda: job.yt_wait if moment == 60 else job.status == "done", timeout=3)
            assert len(attempts) == count
        assert runner.wait_idle(3)
        assert attempts == ["a", "b", "b", "b"] and rendered == ["other", "theme"]
    finally:
        runner.stop(timeout=3)


def test_sources_other_error_fails_queue_without_http(source_target, monkeypatch):
    def fail(*args):
        raise DownloadError("format missing")
    monkeypatch.setattr(web.sources, "fetch_to_cache", fail)
    runner = JobRunner()
    job, _ = runner.submit("theme-test", web.KIND_THEME_RENDER, source_target.target)
    runner.start()
    try:
        assert runner.wait_idle(3)
        assert job.status == "failed" and "format missing" in job.error and not job.yt_wait
        assert job.step == 0
    finally:
        runner.stop(timeout=3)


def source_fixture(tmp_path, vid, *, workspace=False):
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"))
    folder = cfg.workspace.dir / vid
    source = {"path": "source.mp4", "sha256": "a" * 64, "uri": f"https://youtube.test/{vid}"}
    atomic_write_json(folder / "manifest.json", {"source": source})
    atomic_write_json(folder / "metadata.json", {"duration": 360})
    if workspace:
        (folder / "source.mp4").write_bytes(b"video")
    cached = web.sources.cache_dir(cfg) / vid
    meta = {"schema_version": 1, "video_id": vid, "uri": source["uri"], "file": "source.mp4",
            "sha256": "b" * 64, "ingest_sha256": source["sha256"], "differs_from_ingest": True,
            "height": 720, "size": 5, "duration": 360, "downloaded_at": "2026-10-25T00:00:00Z"}
    atomic_write_json(cached / "meta.json", meta)
    (cached / "source.mp4").write_bytes(b"video")
    return cfg, cached, meta


@pytest.mark.parametrize("damage", [None, "size", "duration", "ingest_sha256", "sha256", "uri", "file",
                                    "height", "differs_from_ingest", "downloaded_at", "missing", "symlink"])
def test_sources_light_cache_validation_without_hash(tmp_path, monkeypatch, damage):
    cfg, folder, meta = source_fixture(tmp_path, "a")
    if damage == "missing":
        (folder / "source.mp4").unlink()
    elif damage == "symlink":
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"video")
        (folder / "source.mp4").unlink()
        (folder / "source.mp4").symlink_to(outside)
    elif damage is not None:
        meta[damage] = {"size": 9, "duration": 20, "height": False, "differs_from_ingest": False}.get(damage, "bad")
        atomic_write_json(folder / "meta.json", meta)
    monkeypatch.setattr(hashing, "sha256_file", lambda *a: pytest.fail("display hashed media"))
    assert web.local_source_ready(cfg, "a") is (damage is None)


def test_sources_view_counts_distinct_owners_without_io(tmp_path, monkeypatch):
    cfg, _, _ = source_fixture(tmp_path, "a", workspace=True)
    source_fixture(tmp_path, "b")
    plan = {"plan_id": "12345678", "revision": 1, "check": {"state": "draft"},
            "clips": [{"episode_id": vid} for vid in ["a.kt", "a", "b.kt", "c.kt", "d.kt"]]}
    service = web.ThemePlans(cfg, None, SimpleNamespace(latest=lambda *a: None))
    service.plans = lambda *a, **kw: [plan]

    def source_ids(config, *, blocking):
        assert config is cfg and blocking is False
        return frozenset({"a", "b", "c"})

    monkeypatch.setattr(index_cache, "source_ids", source_ids)
    monkeypatch.setattr(web.theme_index, "build_index", lambda *a, **kw: {"records": []})
    monkeypatch.setattr(tp, "read_proposals", lambda *a: None)
    monkeypatch.setattr(hashing, "sha256_file", lambda *a: pytest.fail("display hashed media"))
    monkeypatch.setattr(web.StoreClient, "from_config", lambda *a: pytest.fail("request contacted store"))
    result = service.view(PID)
    assert result["plans"][0]["sources"] == {"total": 4, "ready": 3, "store": 1, "youtube": 1}
    plan.update(check={"state": "invalid"}, clips="broken")
    assert service.view(PID)["plans"][0]["sources"] == {"total": 0, "ready": 0, "store": 0, "youtube": 0}


def test_sources_real_view_without_http(tmp_path, monkeypatch):
    cfg = fx.seed(tmp_path / "scratch")
    proposal = tp.propose(cfg, PID, client=Planner())["proposals"][0]
    plan = tp.create_plan(cfg, PID, proposal["proposal_id"])
    tp.approve_plan(cfg, PID, plan["plan_id"], revision=1, duration_override=True)
    for clip in plan["clips"]:
        episode = cfg.workspace.dir / clip["episode_id"]
        owner = cfg.workspace.dir / clip["episode_id"].removesuffix(".kt")
        owner.mkdir(exist_ok=True)
        for name in ("manifest.json", "source.mp4"):
            shutil.copyfile(episode / name, owner / name)
    service = web.ThemePlans(cfg, None, SimpleNamespace(latest=lambda *a: None))
    monkeypatch.setattr(hashing, "sha256_file", lambda *a: pytest.fail("warm view hashed media"))
    monkeypatch.setattr(web.StoreClient, "from_config", lambda *a: pytest.fail("view contacted store"))
    result = service.view(PID)["plans"][0]
    assert result["check"]["state"] == "approved"
    assert result["sources"] == {"total": 1, "ready": 1, "store": 0, "youtube": 0}


def test_sources_store_snapshot_async_ttl_and_failure_without_http(monkeypatch):
    cfg = Config()
    cfg = replace(cfg, store=replace(cfg.store, enabled=True))
    clock = [1.0]
    monkeypatch.setattr(index_cache, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    entered, release = threading.Event(), threading.Event()
    calls = []
    error = [False]
    request_thread = threading.get_ident()

    def index():
        assert threading.get_ident() != request_thread
        calls.append("index")
        entered.set()
        assert release.wait(3)
        if error[0]:
            raise web.StoreError("offline")
        return [{"video_id": "a", "kind": "source", "sha256": "a" * 64},
                {"video_id": "hd", "kind": "hd", "sha256": "a" * 64}, {"kind": "source"},
                *({"video_id": f"bad{i}", "kind": "source", "sha256": sha}
                  for i, sha in enumerate([None, 123, "A" * 64, "g" * 64, "a" * 63, "a" * 65])),
                {"video_id": "missing", "kind": "source"}]

    monkeypatch.setattr(web.StoreClient, "from_config", lambda cfg: SimpleNamespace(index=index))
    try:
        with ThreadPoolExecutor(max_workers=1) as reader:
            assert reader.submit(index_cache.source_ids, cfg).result(timeout=1) == frozenset()
        assert entered.wait(3)
        assert index_cache.source_ids(cfg) == frozenset() and len(calls) == 1
    finally:
        release.set()
    wait_for(lambda: index_cache._REFRESHING is None, timeout=3)
    clock[0] = 300
    assert index_cache.source_ids(cfg) == {"a"} and len(calls) == 1
    assert index_cache.has_source(cfg, "missing")  # SRC4 keeps rows without SHA.
    assert index_cache.source_entry(cfg, "a")["sha256"] == "a" * 64
    assert len(calls) == 1  # all readers share the same snapshot
    assert index_cache.TTL_SECONDS == 300
    error[0] = True
    clock[0] = 301
    assert index_cache.source_ids(cfg) == {"a"}  # stale snapshot during refresh
    wait_for(lambda: index_cache._REFRESHING is None, timeout=3)
    assert index_cache.source_ids(cfg) == frozenset() and len(calls) == 2
    clock[0] = 600.9
    assert index_cache.source_ids(cfg) == frozenset() and len(calls) == 2
    assert index_cache.source_ids(Config()) == frozenset() and len(calls) == 2


NODE = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.value = ''; this.type = ''; this._text = ''; this.disabled = false; this.paused = true; this.ended = false; this.currentTime = 0; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map(c => typeof c === 'string' ? c : c.textContent).join(''); }
  append(...cs) { this.children.push(...cs.filter(c=>c!=null)); }
  replaceChildren(...cs) { this.children = cs; this._text = ''; }
  addEventListener(k, f) { this.listeners[k] = f; }
  setAttribute(k, v) { this[k] = v; }
  pause() { this.paused = true; this.listeners.pause?.(); }
  contains(node) { return this === node || this.children.some(c => typeof c !== 'string' && c.contains(node)); }
}
const all = n => [n,...n.children.filter(c=>typeof c!=='string').flatMap(all)];
const clone = x => JSON.parse(JSON.stringify(x));
const clips = [{id:'ep/k1', label:'<script>x</script> · Tập 1', duration:350},
 {id:'ep/k2', label:'Tập 2', duration:350}, {id:'ep/k3', label:'Tập 3', duration:350}];
const p = {proposal_id:'p1', label:'Tu học', titles:['HT A - Chuyên tâm tu học', 'Vì sao tu học? | HT A', '<script>gợi ý</script>'],
 rationale:'Cùng chủ đề', clips:clips.slice(0,2), total_duration:700, shortfall_seconds:1100, dropped_for_length:1};
const fixture = {index_summary:{usable:3, unusable:2, source_missing:1, common_reasons:[]},
 generate_job:{active:true, status:'queued', gpu_wait:true}, clips_available:clips,
 proposals:{ai_error:'lỗi AI', shortfall:'thiếu clip', rejected_themes:[{position:0, reason:'bịa'}], proposals:[p]}, plans:[]};
let requests = [], fail = null, lostResponse = false, hold = null, copies = [];
const mutations = () => requests.filter(r=>r.method !== 'GET');
async function api(path, opts = {}) {
 const method = opts.method || 'GET', body = opts.body && JSON.parse(opts.body);
 requests.push({path, method, body});
 if (hold) { const wait = hold; hold = null; await wait; }
 if (fail && method === fail.method && path.endsWith(fail.suffix)) {
  fail = null; throw Object.assign(Error('fixture failure'), {status:409});
 }
 if (method === 'GET') return clone(fixture);
 if (path.endsWith('/generate')) { fixture.generate_job = {active:true,status:'queued'}; return {}; }
 if (method === 'POST' && path.endsWith('/theme-plans')) {
  const plan = {plan_id:'12345678', revision:1, title:p.titles[0], title_options:p.titles, clips:clone(p.clips),
   total_duration:p.total_duration, proposal:{proposal_id:'p1'}, check:{state:'draft',problems:[]}, render_job:null};
  fixture.plans.push(plan);
  if (lostResponse) { lostResponse = false; throw Error('response lost'); }
  const response = clone(plan); delete response.check; return response;
 }
 const plan = fixture.plans[0];
 if (method === 'PUT') {
  assert.equal(body.revision, plan.revision);
  plan.revision++; plan.title = body.title; plan.clips = body.clip_ids.map(id=>clone(clips.find(c=>c.id===id)));
  plan.check.state = 'draft'; plan.output = null;
 } else if (path.endsWith('/approve')) {
  assert.equal(body.revision, plan.revision); assert.equal(body.duration_override, true);
  plan.check.state = 'approved';
 } else if (path.endsWith('/render')) {
  assert.equal(plan.check.state, 'approved'); plan.render_job = {active:true,status:'queued'};
  return {job:clone(plan.render_job),created:true};
 } else if (method === 'DELETE') { fixture.plans = fixture.plans.filter(p=>p.plan_id!==path.split('/').at(-1)); return {}; }
 const response = clone(plan); delete response.check; return response;
}
function boot() {
 const els = {}, timers = [], events = {};
 const document = {getElementById:id=>els[id] ||= new El('div'), createElement:tag=>new El(tag), activeElement:null};
 function el(tag, attrs = {}, ...children) { const n = document.createElement(tag); for (const [k,v] of Object.entries(attrs)) {
  if (k === 'text') n.textContent = v; else n.setAttribute(k,v); } n.append(...children); return n; }
 const players = new Map(), idle = [], navigation = [], counts = {};
 const busy = () => [...players.values()].some(v=>(!v.paused && !v.ended) || document.fullscreenElement===v);
 const flush = () => {if(!busy())idle.forEach(fn=>fn());};
 const player = (src,cls) => {
  if(!players.has(src)) {
   const v=el('video',{src,class:cls,controls:'',playsinline:'',preload:'metadata'});
   v.addEventListener('pause',flush);v.addEventListener('ended',flush);players.set(src,v);
  }
  return players.get(src);
 };
 const thumbnailBlock = (endpoint,intro,onChanged) => {
  const block=el('div',{class:'fv-thumbnails'});
  block.reveal=()=>{const detail=all(els['tp-plans']).find(n=>n.tagName==='DETAILS' && n.contains(block));detail.open=true;onChanged();};
  return block;
 };
 const ctx = {Favorites:{el, api, fmtDur:x=>x+' s', copyText:async text=>{copies.push(text);return true;},
  player,busy,thumbnailBlock,onIdle:fn=>idle.push(fn),pauseAll:()=>{for(const v of players.values())v.pause();},setVideoCount:(source,n)=>counts[source]=n,
  showTab:name=>navigation.push(name),scrollToVideo:id=>navigation.push(id)},
  document, window:{addEventListener:(k,f)=>events[k]=f}, location:{pathname:'/playlists/PLeligible/favorites'},
  setTimeout:(f,ms)=>{timers.push({f,ms});return timers.length;}, clearTimeout:()=>{}, confirm:()=>true};
 vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8')+'\nThemePlan.init();', ctx);
 return {els,timers,events,document,navigation,counts,flush};
}
const tick = () => new Promise(r=>setImmediate(r));
let app;
const nodes = id => all(app.els[id]);
const btn = (id,text) => {const n=nodes(id).find(n=>n.tagName==='BUTTON' && n.textContent===text);assert.ok(n, text);return n;};
const click = (id,text) => btn(id,text).listeners.click();
const refresh = () => app.els['tp-refresh'].listeners.click();
const input = id => nodes(id).find(n=>n.type==='text');
function setTitle(id, text) {const n=input(id);n.value=text;n.listeners.input();}
function ready() {fixture.plans[0].render_job = {active:false,status:'done'};}
async function made() {await click('tp-proposals','Ghép video');ready();await refresh();}
if (process.argv[2] === 'summary') fixture.index_summary = {usable:0, pending:52, unusable:82, source_missing:28,
 common_reasons:[{reason:'not a khai thi episode', count:70}, {reason:'rejected', count:10}, {reason:'lý do lạ', count:2}]};
if (process.argv[2] === 'summary-zero') fixture.index_summary = {usable:4, pending:0, unusable:0, source_missing:0, common_reasons:[]};
(async () => {
 app = boot(); await tick();
 const scenario = process.argv[2];
 if (scenario === 'summary') {
  assert.equal(app.els['tp-summary'].textContent, '0 clip sẵn sàng · 52 clip khai thị chờ AI đọc nội dung (bấm "AI gợi ý chủ đề") · ' +
   '82 không dùng cho ghép chủ đề (70 × Short thường, không phải khai thị; 10 × clip đã bị loại khi duyệt; 2 × lý do lạ) · ' +
   '28 clip phải tải lại nguồn khi ghép');
 } else if (scenario === 'summary-zero') {
  assert.equal(app.els['tp-summary'].textContent, '4 clip sẵn sàng');
 } else if (scenario === 'display') {
  assert.ok(app.els['tp-summary'].textContent.includes('3 clip'));
  assert.ok(app.els['tp-job'].textContent.includes('Ollama'));
  assert.ok(app.els['tp-proposals'].textContent.includes('thiếu'));
  assert.ok(app.els['tp-proposals'].textContent.includes('<script>x</script>'));
  assert.ok(app.els['tp-proposals'].textContent.includes('Tu học · Cùng chủ đề'));
  assert.ok(app.els['tp-proposals'].textContent.includes('ngắn hơn 30 phút'));
  assert.ok(app.timers.some(t=>t.ms===5000));
  const ns=nodes('tp-proposals'), radios=ns.filter(n=>n.type==='radio');
  assert.equal(ns.find(n=>n.tagName==='H4').textContent,p.titles[0]);
  assert.equal(radios.length,3);assert.equal(radios[0].checked,true);
  assert.ok(ns.find(n=>n.tagName==='LABEL').textContent.startsWith('★ '));
  assert.ok(ns.filter(n=>n.tagName==='DETAILS').every(n=>!n.open));
  assert.ok(!ns.some(n=>n.type==='checkbox' || n.tagName==='SCRIPT'));
  assert.equal(btn('tp-proposals','Ghép video').disabled,false);
 } else if (scenario === 'sources' || scenario === 'sources-ready') {
  await made();
  fixture.plans[0].sources=scenario==='sources'?{total:7,ready:6,store:2,youtube:1}:{total:7,ready:7,store:0,youtube:0};
  fixture.plans[0].render_job={active:true,status:'queued',yt_wait:true};await refresh();
  for(const id of ['tp-proposals','tp-plans']) {
   const text=app.els[id].textContent;
   assert.ok(text.includes(scenario==='sources'?'Video gốc: 6 / 7 sẵn sàng (3090: 2) · 1 cần tải YouTube':'Video gốc: 7 / 7 sẵn sàng'));
   if(scenario==='sources-ready')assert.ok(!text.includes('3090:') && !text.includes('cần tải YouTube'));
  }
  assert.ok(app.els['tp-plans'].textContent.includes('đang chờ YouTube'));
 } else if (scenario === 'one-click' || scenario === 'radio' || scenario === 'custom') {
  if (scenario === 'radio') nodes('tp-proposals').filter(n=>n.type==='radio')[1].listeners.change();
  if (scenario === 'custom') setTitle('tp-proposals','Tựa tự sửa');
  await click('tp-proposals','Ghép video');
  assert.deepEqual(mutations().map(r=>r.method),scenario==='one-click'?['POST','POST','POST']:['POST','PUT','POST','POST']);
  const create=mutations()[0], approve=mutations().find(r=>r.path.endsWith('/approve'));
  assert.deepEqual(create.body,{proposal_id:'p1'});
  assert.deepEqual(approve.body,{revision:scenario==='one-click'?1:2,duration_override:true});
  assert.equal(fixture.plans[0].title,scenario==='radio'?p.titles[1]:scenario==='custom'?'Tựa tự sửa':p.titles[0]);
  assert.ok(app.els['tp-plans'].textContent.includes('đang chờ'));
  assert.ok(!nodes('tp-plans').some(n=>n.tagName==='VIDEO'));
  assert.equal(btn('tp-proposals','Đang ghép…').disabled,true);
  assert.equal(btn('tp-plans','Xóa').disabled,true);
  const count=mutations().length;await click('tp-proposals','Đang ghép…');await click('tp-plans','Ghép lại');assert.equal(mutations().length,count);
  fixture.plans[0].render_job={active:true,status:'running',stage:'theme_render'};await refresh();
  assert.ok(app.els['tp-plans'].textContent.includes('đang ghép'));
  assert.ok(!app.els['tp-plans'].textContent.includes('theme_render'));
  ready();fixture.plans[0].output={download_url:'/files/ready.mp4',download_name:'ready.mp4',description:'00:00 Tu học'};await refresh();
  assert.ok(nodes('tp-plans').some(n=>n.tagName==='A' && n.href==='/files/ready.mp4'));
  await click('tp-plans','Copy mô tả');assert.deepEqual(copies,['00:00 Tu học']);
  assert.ok(!nodes('tp-plans').some(n=>n.type==='checkbox'));
  fixture.generate_job.active=false;
  const before=app.timers.length;await refresh();assert.equal(app.timers.length,before);
 } else if (scenario === 'card-poll' || scenario === 'card-reload' || scenario === 'card-retitle') {
  // Hold the first GET: the card must show progress before any response arrives.
  fixture.generate_job.active=false;
  let release;hold=new Promise(r=>release=r);
  const started=click('tp-proposals','Ghép video');
  assert.equal(btn('tp-proposals','Đang ghép…').disabled,true);
  assert.ok(!nodes('tp-proposals').some(n=>n.tagName==='BUTTON' && n.textContent==='Ghép video'));
  release();await started;
  assert.equal(btn('tp-proposals','Đang ghép…').disabled,true);
  const poll=app.timers.filter(t=>t.ms===5000).at(-1);assert.ok(poll);
  fixture.plans[0].render_job={active:true,status:'running'};await poll.f();
  assert.equal(btn('tp-proposals','Đang ghép…').disabled,true);
  ready();fixture.plans[0].output={download_url:'/files/ready.mp4',download_name:'Tu học.mp4',description:'00:00 Tu học'};
  await app.timers.filter(t=>t.ms===5000).at(-1).f();
  if (scenario === 'card-reload') {
   fixture.plans[0].title='Tiêu đề đã lưu';fixture.plans[0].render_job=null;
   // A completed output is sufficient even after job history has gone away.
   app=boot();await tick();assert.equal(input('tp-proposals').value,'Tiêu đề đã lưu');
  }
  const card=app.els['tp-proposals'];
  assert.ok(card.textContent.includes('✓ Đã ghép · 11,7 phút'));
  assert.ok(!nodes('tp-proposals').some(n=>n.tagName==='BUTTON' && /Ghép video|Ghép lại/.test(n.textContent)));
  assert.ok(!nodes('tp-proposals').some(n=>n.tagName==='A' || n.tagName==='VIDEO'));
  await click('tp-proposals','Xem video');assert.deepEqual(app.navigation,['videos',fixture.plans[0].plan_id]);
  const link=nodes('tp-plans').find(n=>n.tagName==='A');
  assert.equal(link.href,'/files/ready.mp4');assert.equal(link.download,'Tu học.mp4');
  await click('tp-plans','Copy mô tả');assert.deepEqual(copies,['00:00 Tu học']);
  const video=nodes('tp-plans').find(n=>n.tagName==='VIDEO');assert.ok(video);
  assert.equal(video.src,'/files/ready.mp4?inline=1');
  assert.equal(video.preload,'metadata');assert.ok('controls' in video && 'playsinline' in video);
  assert.equal(app.els['tp-plans'].children[0].children[0],video);
  assert.equal(app.els['tp-plans'].children[0].id,'vd-plan-'+fixture.plans[0].plan_id);
  const detail=nodes('tp-plans').find(n=>n.tagName==='DETAILS');
  assert.ok(detail.textContent.includes('Sửa video & thumbnail'));assert.ok(detail.contains(btn('tp-plans','Ghép lại')));
  for(const text of ['Tải video','Copy tiêu đề','Copy mô tả','Xóa'])
   assert.ok(!detail.textContent.includes(text));
  assert.equal(app.counts.plans,1);
  if (scenario === 'card-retitle') {
   nodes('tp-proposals').filter(n=>n.type==='radio')[1].listeners.change();
   assert.equal(btn('tp-proposals','Ghép lại với tiêu đề này').disabled,false);
   setTitle('tp-proposals',fixture.plans[0].title);
   assert.ok(!nodes('tp-proposals').some(n=>n.tagName==='BUTTON' && n.textContent==='Ghép lại với tiêu đề này'));
   setTitle('tp-proposals','Tựa mới');
   const before=mutations().length;await click('tp-proposals','Ghép lại với tiêu đề này');
   assert.deepEqual(mutations().slice(before).map(r=>r.method),['PUT','POST','POST']);
   assert.equal(mutations()[before].body.title,'Tựa mới');
   assert.equal(mutations()[before+1].body.revision,2);
   assert.equal(fixture.plans.length,1);
   assert.equal(btn('tp-proposals','Đang ghép…').disabled,true);
  }
 } else if (scenario === 'thumbnail-open') {
  await made();fixture.plans[0].output={download_url:'/files/ready.mp4',intro:{sha256:'old'}};await refresh();
  const detail=nodes('tp-plans').find(n=>n.tagName==='DETAILS');assert.equal(detail.open,false);
  nodes('tp-plans').find(n=>n.class==='fv-thumbnails').reveal();assert.equal(detail.open,true);
  await refresh();assert.equal(nodes('tp-plans').find(n=>n.tagName==='DETAILS').open,true);
  fixture.plans[0].render_job={active:false,status:'failed',error:'Lỗi ghép lại'};await refresh();
  const failedDetails=nodes('tp-plans').find(n=>n.tagName==='DETAILS');
  assert.ok(!failedDetails.contains(btn('tp-plans','Ghép lại')));
 } else if (scenario === 'delete-playing' || scenario === 'delete-playing-late-pause') {
  await made();fixture.plans[0].output={download_url:'/files/delete.mp4'};
  const other=clone(fixture.plans[0]);other.plan_id='87654321';other.proposal=null;
  other.output={download_url:'/files/other.mp4'};fixture.plans.push(other);await refresh();
  const video=nodes('tp-plans').filter(n=>n.tagName==='VIDEO')[1];video.paused=false;
  const old=app.els['tp-plans'].children[0];await refresh();assert.equal(app.els['tp-plans'].children[0],old);
  // Browser pause events may arrive before or after DELETE and its final refresh.
  const onPause=video.listeners.pause;
  if(scenario==='delete-playing-late-pause')video.listeners.pause=()=>{};
  let release;hold=new Promise(r=>release=r);
  const started=click('tp-plans','Xóa');assert.equal(video.paused,true);
  assert.equal(fixture.plans.length,2);release();await started;
  assert.deepEqual(fixture.plans.map(p=>p.plan_id),['87654321']);
  assert.ok(!nodes('tp-plans').some(n=>n.id==='vd-plan-12345678'));
  assert.ok(nodes('tp-plans').some(n=>n.id==='vd-plan-87654321'));
  assert.equal(app.counts.plans,1);
  assert.equal(mutations().filter(r=>r.method==='DELETE').length,1);
  if(scenario==='delete-playing-late-pause')onPause();
  assert.ok(!nodes('tp-plans').some(n=>n.id==='vd-plan-12345678'));
 } else if (scenario.startsWith('video-')) {
  await made();fixture.plans[0].output={download_url:'/files/ready.mp4',download_name:'Ready.mp4'};await refresh();
  const old=app.els['tp-plans'].children[0], video=nodes('tp-plans').find(n=>n.tagName==='VIDEO');
  assert.ok(video);video.currentTime=42;
  const oldProposal=app.els['tp-proposals'].children[0];
  if(scenario==='video-paused') {
   await refresh();assert.notEqual(app.els['tp-plans'].children[0],old);
  } else {
   if(scenario==='video-fullscreen') app.document.fullscreenElement=video;
   else video.paused=false;
   fixture.plans[0].title='Cập nhật khi dừng';
   const poll=app.timers.filter(t=>t.ms===5000).at(-1);await poll.f();
   assert.equal(app.els['tp-plans'].children[0],old);
   assert.notEqual(app.els['tp-proposals'].children[0],oldProposal);
   app.els['tp-plans'].listeners.focusout();await app.timers.filter(t=>t.ms===0).at(-1).f();
   assert.equal(app.els['tp-plans'].children[0],old);
   if(scenario==='video-lock') {
    const controls=nodes('tp-plans').filter(n=>['BUTTON','INPUT','SELECT'].includes(n.tagName));
    let release;hold=new Promise(r=>release=r);
    const started=app.els['tp-generate'].listeners.click();
    assert.ok(controls.every(n=>n.disabled));assert.equal(app.els['tp-plans'].children[0],old);
    release();await started;assert.equal(app.els['tp-plans'].children[0],old);
    assert.equal(input('tp-plans').disabled,false);
   }
   if(scenario==='video-fullscreen') {app.document.fullscreenElement=null;app.flush();}
   else video.pause();
   assert.notEqual(app.els['tp-plans'].children[0],old);
   assert.ok(app.els['tp-plans'].textContent.includes('Cập nhật khi dừng'));
  }
  assert.equal(nodes('tp-plans').find(n=>n.tagName==='VIDEO'),video);assert.equal(video.currentTime,42);
 } else if (scenario === 'double-reload') {
  let release;hold=new Promise(r=>release=r);
  const first=click('tp-proposals','Ghép video'), second=click('tp-proposals','Đang ghép…');
  assert.equal(btn('tp-proposals','Đang ghép…').disabled,true);
  release();await Promise.all([first,second]);assert.equal(fixture.plans.length,1);
  ready(); app=boot();await tick();
  await click('tp-proposals','Ghép video');assert.equal(fixture.plans.length,1);
  assert.equal(mutations().filter(r=>r.path.endsWith('/theme-plans')).length,1);
 } else if (scenario.startsWith('failure-')) {
  const stage=scenario.slice(8);
  const failures={create:['POST','/theme-plans','Tạo video từ chủ đề'],edit:['PUT','/12345678','Lưu tiêu đề và danh sách clip'],
   approve:['POST','/approve','Duyệt video'],render:['POST','/render','Xếp hàng ghép video']};
  const [method,suffix,label]=failures[stage];fail={method,suffix};
  if(stage==='edit')setTitle('tp-proposals','Sửa tựa');
  await click('tp-proposals','Ghép video');assert.ok(app.els['tp-msg'].textContent.startsWith(label+':'),app.els['tp-msg'].textContent);
  assert.ok(app.els['tp-msg'].textContent.includes('fixture failure'));
  assert.equal(btn('tp-proposals','Ghép video').disabled,false);
  await click('tp-proposals','Ghép video');assert.equal(fixture.plans.length,1);
  assert.equal(fixture.plans[0].render_job.status,'queued');
  assert.equal(mutations().filter(r=>r.path.endsWith('/theme-plans')).length,stage==='create'?2:1);
 } else if (scenario === 'lost-create-response') {
  lostResponse=true;await click('tp-proposals','Ghép video');
  assert.ok(app.els['tp-msg'].textContent.includes('response lost'));
  app=boot();await tick();await click('tp-proposals','Ghép video');
  assert.equal(mutations().filter(r=>r.path.endsWith('/theme-plans')).length,1);
  assert.equal(fixture.plans[0].render_job.status,'queued');
 } else if (scenario === 'edit-clips') {
  await made();
  const detail=nodes('tp-plans').find(n=>n.tagName==='DETAILS');detail.open=true;detail.listeners.toggle();
  await click('tp-plans','↓');await click('tp-plans','✕');
  const select=nodes('tp-plans').find(n=>n.tagName==='SELECT');select.value='ep/k3';await click('tp-plans','Thêm clip');
  setTitle('tp-plans','Sửa chưa lưu');await refresh();
  assert.equal(input('tp-plans').value,'Sửa chưa lưu');assert.equal(nodes('tp-plans').find(n=>n.tagName==='DETAILS').open,true);
  assert.ok(app.els['tp-plans'].textContent.includes('chưa lưu'));
  await click('tp-plans','Ghép lại');
  const put=mutations().find(r=>r.method==='PUT');assert.deepEqual(put.body,{revision:1,title:'Sửa chưa lưu',clip_ids:['ep/k1','ep/k3']});
  assert.equal(mutations().at(-2).body.revision,2);
 } else if (scenario === 'edit-retry-failure') {
  await made();setTitle('tp-plans','Sửa rồi thử lại');fail={method:'POST',suffix:'/approve'};
  await click('tp-plans','Ghép lại');
  assert.ok(app.els['tp-msg'].textContent.startsWith('Duyệt video:'));
  assert.equal(btn('tp-plans','Ghép lại').disabled,false);
  await click('tp-plans','Ghép lại');
  assert.equal(fixture.plans[0].render_job.status,'queued');
  assert.equal(mutations().filter(r=>r.method==='PUT').length,1);
  assert.equal(mutations().filter(r=>r.path.endsWith('/theme-plans')).length,1);
 } else if (scenario === 'failed-job') {
  await made();fixture.plans[0].render_job={active:false,status:'failed',error:'không đọc được nguồn'};await refresh();
  assert.ok(app.els['tp-plans'].textContent.includes('lỗi: không đọc được nguồn'));
  assert.ok(app.els['tp-proposals'].textContent.includes('lỗi: không đọc được nguồn'));
  assert.equal(btn('tp-proposals','Ghép lại').disabled,false);
  assert.equal(btn('tp-plans','Ghép lại').disabled,false);
  const approvals=mutations().filter(r=>r.path.endsWith('/approve')).length;
  await click('tp-proposals','Ghép lại');
  assert.equal(btn('tp-proposals','Đang ghép…').disabled,true);
  assert.equal(mutations().filter(r=>r.path.endsWith('/approve')).length,approvals);
  assert.equal(fixture.plans[0].render_job.status,'queued');
 } else if (scenario === 'read-failure') {
  fail={method:'GET',suffix:'/theme-plan'};
  await click('tp-proposals','Ghép video');
  assert.ok(app.els['tp-msg'].textContent.startsWith('Tải trạng thái:'));
  assert.equal(mutations().length,0);
  await click('tp-proposals','Ghép video');assert.equal(fixture.plans.length,1);
 } else if (scenario === 'conflict') {
  await made();setTitle('tp-plans','Sửa chưa lưu');fixture.plans[0].revision++;
  await click('tp-plans','Ghép lại');assert.ok(app.els['tp-msg'].textContent.includes('đã có thay đổi khác'));
  assert.ok(!mutations().some(r=>r.method==='PUT'));
  assert.equal(input('tp-plans').value,'Sửa chưa lưu');
  await click('tp-plans','Tải lại bản đã lưu');assert.equal(input('tp-plans').value,p.titles[0]);
 } else if (scenario === 'stale') {
  await made();fixture.plans[0].check={state:'stale',problems:['input changed']};await refresh();
  assert.ok(app.els['tp-plans'].textContent.includes('Nội dung clip đã đổi'));
  assert.ok(!nodes('tp-plans').some(n=>n.textContent==='Ghép lại'));
  const before=mutations().length;await click('tp-proposals','Ghép video');assert.equal(mutations().length,before);
  assert.ok(app.els['tp-msg'].textContent.includes('Gợi ý lại'));
  fixture.generate_job.active=false;await refresh();await click('tp-plans','Gợi ý lại');
  assert.ok(mutations().at(-1).path.endsWith('/generate'));
  await click('tp-plans','Xóa');assert.equal(fixture.plans.length,0);
 } else if (scenario === 'focus-long') {
  p.total_duration=2600;await refresh();assert.ok(app.els['tp-proposals'].textContent.includes('dài hơn 40 phút'));
  setTitle('tp-proposals','Giữ con trỏ');const old=input('tp-proposals');app.document.activeElement=old;
  await refresh();assert.equal(input('tp-proposals'),old);
  app.document.activeElement=null;await refresh();assert.equal(input('tp-proposals').value,'Giữ con trỏ');
  await click('tp-proposals','Ghép video');assert.equal(fixture.plans[0].render_job.status,'queued');
 } else {throw Error('unknown scenario '+scenario);}
 console.log('ok');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""


@pytest.mark.parametrize("scenario", [
    "display", "summary", "summary-zero", "sources", "sources-ready", "one-click", "radio", "custom", "double-reload",
    "card-poll", "card-reload", "card-retitle",
    "video-busy", "video-paused", "video-fullscreen", "video-lock", "thumbnail-open",
    "delete-playing", "delete-playing-late-pause",
    "failure-create", "failure-edit", "failure-approve", "failure-render",
    "lost-create-response", "edit-clips", "edit-retry-failure", "failed-job", "read-failure",
    "conflict", "stale", "focus-long",
])
def test_js_smoke_and_text_only(scenario):
    if shutil.which("node") is None:
        pytest.skip("node unavailable")
    js = STATIC / "theme_plan.js"
    text = js.read_text()
    assert "innerHTML" not in text and "insertAdjacentHTML" not in text
    assert 'type: "checkbox"' not in text
    assert "theme_plan.js" in (STATIC / "favorites.html").read_text()
    result = subprocess.run(["node", "-e", NODE, str(js), scenario], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


NODE_TABS = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
class El {
 constructor(tag='div') {this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.dataset={};this.classes=new Set();this.paused=true;this.ended=false;this.currentTime=0;this._text='';this.classList={toggle:(c,on)=>on?this.classes.add(c):this.classes.delete(c)};}
 set textContent(v) {this.replaceChildren();this._text=String(v);}
 get textContent() {return this._text+this.children.map(c=>typeof c==='string'?c:c.textContent).join('');}
 setAttribute(k,v) {this[k]=v;}
 append(...nodes) {for(const n of nodes) {if(n==null)continue;if(typeof n!=='string'){if(n.parent)n.parent.children=n.parent.children.filter(c=>c!==n);n.parent=this;}this.children.push(n);}}
 replaceChildren(...nodes) {for(const n of this.children)if(typeof n!=='string')n.parent=null;this.children=[];this._text='';this.append(...nodes);}
 get isConnected() {return !!this.root || !!this.parent?.isConnected;}
 contains(n) {return n===this || this.children.some(c=>typeof c!=='string' && c.contains(n));}
 closest(tag) {return this.tagName===tag.toUpperCase()?this:this.parent?.closest(tag);}
 addEventListener(k,f) {this.listeners[k]=f;}
 pause() {if(!this.paused){this.paused=true;this.listeners.pause?.();}}
 play() {this.paused=false;this.ended=false;this.listeners.play?.();}
 focus() {this.focused=true;}
 scrollIntoView(opts) {this.scrolled=opts;}
}
const mode=process.argv[2],els={},values=new Map(),calls=[],timers=[],events={};
if(mode==='saved')values.set('autoShort.fvTab','manual');
if(mode==='saved-videos')values.set('autoShort.fvTab','videos');
if(mode==='invalid')values.set('autoShort.fvTab','unknown');
const get=id=>{if(!els[id]){els[id]=new El();els[id].root=true;}return els[id];};
const tabs=['ai','manual','videos'].map(name=>{const n=get('fv-tab-'+name);n.dataset.fvTab=name;return n;});
const filters=['all','short','khaithi'].map(kind=>{const n=new El('button');n.dataset.kind=kind;return n;});
get('fv-auto-min').value='60';
const favorites=[{episode_id:'ep1',clip:'k1',code:'KT01',kind:'khaithi',usable:true,duration:350},
 {episode_id:'ep2',clip:'s1',code:'S01',kind:'short',usable:true,duration:50}];
let compilations=mode==='players'?[{cid:'c1',mode:'concat',state:'done',download_url:'/files/manual.mp4',duration:600,segments:2},
 {cid:'c2',mode:'loop',state:'done',download_url:'/files/loop.mp4',duration:600,repeat:2}]:[];
const document={querySelector:s=>get(s.slice(1)),getElementById:get,createElement:tag=>new El(tag),
 querySelectorAll:s=>s==='[data-fv-tab]'?tabs:filters,addEventListener:(k,f)=>events[k]=f,activeElement:null};
const ctx={document,location:{pathname:'/playlists/PLeligible/favorites'},localStorage:{getItem:k=>{if(mode==='blocked')throw Error('denied');return values.get(k);},setItem:(k,v)=>{if(mode==='blocked')throw Error('denied');values.set(k,v);}},
 fetch:async(path,opts)=>{calls.push({path,opts});return {ok:true,status:200,json:async()=>path.endsWith('/thumbs')?{state:'ready',files:{}}:opts.method==='POST'?{created:true}:{series:'Bộ kinh',max_minutes:720,favorites,compilations}};},
 window:{dispatchEvent:()=>{}},setTimeout:(f,ms)=>{timers.push({f,ms});return timers.length;},clearTimeout:()=>{},confirm:()=>true};
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 vm.createContext(ctx);  // favorites.html loads app.js (AutoShort helpers) before favorites.js
 vm.runInContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[1]),'app.js'),'utf8'),ctx);
 vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+'\nFavorites.init();globalThis.fv=Favorites;',ctx);await tick();
 const initial=mode==='saved'?'manual':mode==='saved-videos'?'videos':'ai';
 for(const name of ['ai','manual','videos'])assert.equal(get('fv-pane-'+name).hidden,name!==initial);
 assert.equal(tabs[['ai','manual','videos'].indexOf(initial)]['aria-selected'],'true');
 tabs[1].listeners.click();assert.equal(get('fv-pane-manual').hidden,false);
 if(mode!=='blocked')assert.equal(values.get('autoShort.fvTab'),'manual');
 let prevented=false;tabs[1].listeners.keydown({key:'ArrowRight',preventDefault:()=>prevented=true});
 assert.ok(prevented);assert.equal(get('fv-pane-videos').hidden,false);assert.ok(tabs[2].focused);
 if(mode!=='blocked')assert.equal(values.get('autoShort.fvTab'),'videos');
 tabs[2].listeners.keydown({key:'ArrowRight',preventDefault:()=>{}});assert.equal(get('fv-pane-ai').hidden,false);
 assert.equal(get('fv-count').textContent,'2');
 // Existing manual concat and duration-based creation still use their CP8.33 payloads.
 get('fv-all').listeners.change({target:{checked:true}});
 get('fv-concat').listeners.click({target:get('fv-concat')});await tick();
 const concat=calls.find(c=>c.opts.method==='POST');
 assert.deepEqual(JSON.parse(concat.opts.body),{mode:'concat',items:[{episode_id:'ep1',clip:'k1'},{episode_id:'ep2',clip:'s1'}]});
 filters[2].listeners.click();get('fv-auto').listeners.click({target:get('fv-auto')});await tick();
 assert.deepEqual(JSON.parse(calls.filter(c=>c.opts.method==='POST').at(-1).opts.body),{mode:'auto',minutes:60,kinds:['khaithi']});
 const all=n=>[n,...n.children.filter(c=>typeof c!=='string').flatMap(all)];
 await all(get('fv-list')).find(n=>n.textContent==='Lặp').listeners.click();
 const loop=all(get('fv-list')).find(n=>n.type==='number');loop.value='30';
 all(get('fv-list')).find(n=>n.textContent==='Tạo').listeners.click();await tick();
 assert.deepEqual(JSON.parse(calls.filter(c=>c.opts.method==='POST').at(-1).opts.body),{mode:'loop',item:{episode_id:'ep1',clip:'k1'},minutes:30});
 if(mode==='players') {
  const fv=ctx.fv, videos=()=>all(get('fv-comps')).filter(n=>n.tagName==='VIDEO');
  const [v,other]=videos();assert.ok(v && other);
  assert.equal(v.src,'/files/manual.mp4?inline=1');assert.equal(v.preload,'metadata');
  assert.ok('controls' in v && 'playsinline' in v);assert.equal(v.className,'vd-vertical');
  assert.equal(get('fv-comps').children[0].children[0],v);
  assert.ok(!all(get('fv-comps')).some(n=>n.tagName==='A' && n.textContent==='Xem'));
  fv.setVideoCount('plans',3);assert.equal(get('fv-videos-count').textContent,'5');
  const reload=async()=>{await get('fv-auto').listeners.click({target:get('fv-auto')});await tick();};
  fv.showTab('videos');v.currentTime=23;await reload();assert.equal(videos()[0],v);assert.equal(v.currentTime,23);
  v.play();assert.equal(fv.busy(),true);
  const old=get('fv-comps').children[0];compilations[0].download_name='Updated';
  document.activeElement=new El('input');document.activeElement.type='number';
  await reload();assert.equal(get('fv-comps').children[0],old);assert.equal(videos()[0],v);
  // Render paths triggered by manual controls must also defer the video list.
  filters[0].listeners.click();assert.equal(get('fv-comps').children[0],old);
  v.pause();assert.notEqual(get('fv-comps').children[0],old);assert.ok(get('fv-comps').textContent.includes('Updated'));
  assert.equal(videos()[0],v);assert.equal(v.currentTime,23);document.activeElement=null;
  document.fullscreenElement=v;const fullCard=get('fv-comps').children[0];await reload();
  assert.equal(fv.busy(),true);assert.equal(get('fv-comps').children[0],fullCard);
  document.fullscreenElement=null;events.fullscreenchange();assert.notEqual(get('fv-comps').children[0],fullCard);
  v.play();other.play();assert.equal(v.paused,true);assert.equal(other.paused,false);
  const playingCard=get('fv-comps').children[0];await reload();other.ended=true;other.listeners.ended();
  assert.notEqual(get('fv-comps').children[0],playingCard);other.pause();
  v.play();fv.showTab('manual');assert.equal(v.paused,true);assert.equal(fv.busy(),false);
  fv.scrollToVideo('123');assert.equal(get('vd-plan-123').scrolled.block,'start');
  // Thumbnail warnings reveal the nearest details immediately.
  let warned=false;
  const thumb=fv.thumbnailBlock('/thumbs',{shape:'landscape',intro:{sha256:'old'}},()=>warned=true);
  const detail=new El('details');detail.append(thumb);get('thumb-test').append(detail);
  await timers.filter(t=>t.ms===0).at(-1).f();assert.equal(detail.open,true);assert.equal(warned,true);
  assert.ok(detail.textContent.includes('Thumbnail intro đã đổi'));
  compilations=[];await reload();assert.equal(get('fv-videos-count').textContent,'3');
  const fresh=fv.player(v.src);assert.notEqual(fresh,v);assert.equal(fv.busy(),false);
 }
 console.log('ok');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""


@pytest.mark.parametrize("storage", ["default", "saved", "saved-videos", "invalid", "blocked", "players"])
def test_js_favorites_tabs_and_manual_compilation(storage):
    if shutil.which("node") is None:
        pytest.skip("node unavailable")
    result = subprocess.run(["node", "-e", NODE_TABS, str(STATIC / "favorites.js"), storage],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_favorites_ui_tab_panel_ownership():
    from html.parser import HTMLParser

    class Panels(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.nodes = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "id" in attrs:
                self.nodes[attrs["id"]] = (attrs, [node.get("id") for node in self.stack])
            if tag not in {"meta", "link", "input", "br"}:
                self.stack.append(attrs)

        def handle_endtag(self, tag):
            self.stack.pop()

    html = (STATIC / "favorites.html").read_text()
    parser = Panels()
    parser.feed(html)
    nodes = parser.nodes
    assert "hidden" not in nodes["fv-pane-ai"][0]
    assert "hidden" in nodes["fv-pane-manual"][0]
    assert nodes["fv-tab-ai"][0]["aria-selected"] == "true"
    assert html.index('id="fv-pane-ai"') < html.index('id="fv-pane-manual"')
    for name in ("tp-generate", "tp-proposals"):
        assert "fv-pane-ai" in nodes[name][1]
    for name in ("fv-list", "fv-filters", "fv-concat", "fv-all", "fv-auto", "fv-max"):
        assert "fv-pane-manual" in nodes[name][1]

    assert "hidden" in nodes["fv-pane-videos"][0]
    assert nodes["fv-tab-videos"][0]["data-fv-tab"] == "videos"
    assert "fv-tab-videos" in nodes["fv-videos-count"][1]
    for name in ("tp-plans", "fv-comps"):
        assert "fv-pane-videos" in nodes[name][1]
