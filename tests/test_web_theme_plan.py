"""TC2 phase C: offline HTTP / queue integration and the Favorites JS card."""
import json
import shutil
import subprocess
import time
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from auto_short import hashing, theme_plan as tp
from auto_short.pipeline import OllamaUnavailable, PreflightError
from auto_short.render.full import SourceBlocked
from auto_short.selection.client import ChatError, ChatUnavailable
from auto_short.web import theme_plan as web
from auto_short.web.auth import COOKIE_NAME
from auto_short.web.jobs import AI, RENDER, GpuUnavailable, JobFailed
from auto_short.workspace import atomic_write_json

from test_theme_plan import Planner
from test_web_theme_index import STATIC, fx, snapshot

PID = "PLeligible"
BASE = f"/api/playlists/{PID}"
PW = "pw"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    cfg = fx.seed(tmp_path / "scratch")
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
    before = snapshot(s.root)
    r = s.c.get(BASE + "/theme-plan")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["index_summary"]["usable"] == 1
    assert body["clips_available"][0]["duration"] == 350
    assert "Tập" in body["clips_available"][0]["label"]
    assert body["plans"][0]["check"]["state"] == "draft"
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
    assert job.steps[0].lane == RENDER
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
        assert job.status == "failed" and job.error == "YouTube đang chặn tải, thử lại sau"
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


NODE = r"""
const fs = require('fs'), vm = require('vm');
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.value = ''; this.type = ''; this._text = ''; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map(c => typeof c === 'string' ? c : c.textContent).join(''); }
  append(...cs) { this.children.push(...cs); }
  replaceChildren(...cs) { this.children = cs; this._text = ''; }
  addEventListener(k, f) { this.listeners[k] = f; }
  setAttribute(k, v) { this[k] = v; }
  contains() { return false; }
}
const els = {}, timers = [], events = {}, requests = [];
const document = { getElementById: id => els[id] ||= new El('div'), createElement: tag => new El(tag) };
const fixture = {index_summary: {usable: 1, unusable: 2, source_missing: 1, common_reasons: []},
 generate_job: {active: true, status: 'queued', gpu_wait: true},
 clips_available: [{id: 'ep/k1', label: '<script>x</script> · Tập 1', duration: 350}],
 proposals: {ai_error: 'lỗi AI', shortfall: 'thiếu clip', rejected_themes: [{position: 0, reason: 'bịa'}],
 proposals: [{proposal_id: 'p1', label: 'Tu học', titles: ['HT A - Chuyên tâm tu học'], rationale: 'Cùng chủ đề', clips: [{id: 'ep/k1', duration: 350}],
 total_duration: 350, shortfall_seconds: 1450, dropped_for_length: 1}]},
 plans: [{plan_id: '12345678', revision: 1, title: 'Kế hoạch', title_options: ['Kế hoạch', 'Vì sao tu học? | HT A', '<script>gợi ý</script>'], clips: [{id:'ep/k1', duration:350}],
 check: {state:'draft', problems:[]}, render_job: null}]};
let body = fixture;
function el(tag, attrs = {}, ...children) { const n = document.createElement(tag); for (const [k,v] of Object.entries(attrs)) {
 if (k === 'text') n.textContent = v; else n.setAttribute(k,v); } n.append(...children); return n; }
const tick = () => new Promise(r => setTimeout(r, 10));
const ctx = { Favorites: {el, api: async (path, opts) => {requests.push({path,opts}); return body;}, fmtDur: x => x + ' s', copyText: async () => true},
 document, window: {addEventListener: (k,f) => events[k] = f}, location: {pathname:'/playlists/PLeligible/favorites'},
 setTimeout: (f, ms) => {timers.push({f,ms}); return timers.length;}, clearTimeout: () => {}, confirm: () => true };
(async () => {
 vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8') + '\nThemePlan.init();', ctx);
 await tick();
 if (!els['tp-summary'].textContent.includes('1 clip') || !els['tp-job'].textContent.includes('Ollama')) throw Error('summary/job');
 if (!els['tp-proposals'].textContent.includes('thiếu') || !els['tp-proposals'].textContent.includes('<script>x</script>')) throw Error('proposal text');
 if (!timers.some(t => t.ms === 5000)) throw Error('active polling');
 const all = n => [n,...n.children.filter(c=>typeof c!=='string').flatMap(all)];
 if (all(els['tp-proposals']).find(n=>n.tagName==='H4').textContent !== 'HT A - Chuyên tâm tu học') throw Error('default proposal title');
 if (!els['tp-proposals'].textContent.includes('Tu học · Cùng chủ đề')) throw Error('label/rationale');
 let nodes = all(els['tp-plans']);
 let suggestions = nodes.filter(n=>n.tagName==='BUTTON' && n.textContent.startsWith('Gợi ý: '));
 if (suggestions.length !== 2 || !suggestions.some(n=>n.textContent.includes('<script>gợi ý</script>'))) throw Error('title suggestions/text only');
 const approve = nodes.find(n=>n.tagName==='BUTTON' && n.textContent==='Duyệt');
 if (!approve.disabled) throw Error('override required');
 const checkbox = nodes.find(n=>n.type==='checkbox'); checkbox.checked = true; checkbox.listeners.change();
 if (approve.disabled) throw Error('override approval');
 const firstInput = nodes.find(n=>n.type==='text');
 suggestions[0].listeners.click();
 if (firstInput.value !== 'Vì sao tu học? | HT A' || !els['tp-plans'].textContent.includes('chưa lưu') || !approve.disabled) throw Error('suggestion fills dirty draft');
 if (requests.some(r=>r.opts && r.opts.method==='PUT')) throw Error('suggestion must await save');
 const title = nodes.find(n=>n.type==='text'); title.value = 'Sửa chưa lưu'; title.listeners.input();
 const refresh = els['tp-refresh'].listeners.click; fixture.generate_job.active = false; await refresh();
 nodes = all(els['tp-plans']);
 if (nodes.find(n=>n.type==='text').value !== 'Sửa chưa lưu') throw Error('lost draft on poll');
 await nodes.find(n=>n.tagName==='BUTTON' && n.textContent==='Lưu sửa').listeners.click(); await tick();
 const req = requests.find(r=>r.opts && r.opts.method==='PUT');
 if (!req || JSON.parse(req.opts.body).title !== 'Sửa chưa lưu') throw Error('save revision');
 const nTimers = timers.filter(t=>t.ms===5000).length; await refresh();
 if (timers.filter(t=>t.ms===5000).length !== nTimers) throw Error('idle polling');
 console.log('ok');
})().catch(e => {console.error(e);process.exitCode=1;});
"""


def test_js_smoke_and_text_only():
    if shutil.which("node") is None:
        pytest.skip("node unavailable")
    js = STATIC / "theme_plan.js"
    text = js.read_text()
    assert "innerHTML" not in text and "insertAdjacentHTML" not in text
    assert "theme_plan.js" in (STATIC / "favorites.html").read_text()
    result = subprocess.run(["node", "-e", NODE, str(js)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
