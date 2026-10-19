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
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.value = ''; this.type = ''; this._text = ''; this.disabled = false; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map(c => typeof c === 'string' ? c : c.textContent).join(''); }
  append(...cs) { this.children.push(...cs); }
  replaceChildren(...cs) { this.children = cs; this._text = ''; }
  addEventListener(k, f) { this.listeners[k] = f; }
  setAttribute(k, v) { this[k] = v; }
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
 } else if (method === 'DELETE') { fixture.plans = []; return {}; }
 const response = clone(plan); delete response.check; return response;
}
function boot() {
 const els = {}, timers = [], events = {};
 const document = {getElementById:id=>els[id] ||= new El('div'), createElement:tag=>new El(tag), activeElement:null};
 function el(tag, attrs = {}, ...children) { const n = document.createElement(tag); for (const [k,v] of Object.entries(attrs)) {
  if (k === 'text') n.textContent = v; else n.setAttribute(k,v); } n.append(...children); return n; }
 const ctx = {Favorites:{el, api, fmtDur:x=>x+' s', copyText:async text=>{copies.push(text);return true;}},
  document, window:{addEventListener:(k,f)=>events[k]=f}, location:{pathname:'/playlists/PLeligible/favorites'},
  setTimeout:(f,ms)=>{timers.push({f,ms});return timers.length;}, clearTimeout:()=>{}, confirm:()=>true};
 vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8')+'\nThemePlan.init();', ctx);
 return {els,timers,events,document};
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
(async () => {
 app = boot(); await tick();
 const scenario = process.argv[2];
 if (scenario === 'display') {
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
  const link=nodes('tp-proposals').find(n=>n.tagName==='A');
  assert.equal(link.href,'/files/ready.mp4');assert.equal(link.download,'Tu học.mp4');
  await click('tp-proposals','Copy mô tả');assert.deepEqual(copies,['00:00 Tu học']);
  for (const id of ['tp-proposals','tp-plans']) {
   assert.ok(!nodes(id).some(n=>n.tagName==='VIDEO'));
   await click(id,'Xem');
   const video=nodes(id).find(n=>n.tagName==='VIDEO');assert.ok(video);
   assert.equal(video.src,'/files/ready.mp4?inline=1');
   assert.equal(video.preload,'metadata');assert.ok('controls' in video && 'playsinline' in video);
   await click(id,'Ẩn video');assert.ok(!nodes(id).some(n=>n.tagName==='VIDEO'));
   await click(id,'Xem');assert.notEqual(nodes(id).find(n=>n.tagName==='VIDEO'),video);
   await click(id,'Ẩn video');
  }
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
    "display", "one-click", "radio", "custom", "double-reload",
    "card-poll", "card-reload", "card-retitle",
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
 constructor(tag='div') {this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.dataset={};this.classes=new Set();this.classList={toggle:(c,on)=>on?this.classes.add(c):this.classes.delete(c)};}
 setAttribute(k,v) {this[k]=v;}
 append(...nodes) {this.children.push(...nodes);}
 replaceChildren(...nodes) {this.children=nodes;}
 addEventListener(k,f) {this.listeners[k]=f;}
 focus() {this.focused=true;}
}
const mode=process.argv[2],els={},values=new Map(),calls=[];
if(mode==='saved')values.set('autoShort.fvTab','manual');
if(mode==='invalid')values.set('autoShort.fvTab','unknown');
const get=id=>els[id] ||= new El();
const tabs=['ai','manual'].map(name=>{const n=get('fv-tab-'+name);n.dataset.fvTab=name;return n;});
const filters=['all','short','khaithi'].map(kind=>{const n=new El('button');n.dataset.kind=kind;return n;});
get('fv-auto-min').value='60';
const favorites=[{episode_id:'ep1',clip:'k1',code:'KT01',kind:'khaithi',usable:true,duration:350},
 {episode_id:'ep2',clip:'s1',code:'S01',kind:'short',usable:true,duration:50}];
const document={querySelector:s=>get(s.slice(1)),getElementById:get,createElement:tag=>new El(tag),
 querySelectorAll:s=>s==='[data-fv-tab]'?tabs:filters,addEventListener:()=>{},activeElement:null};
const ctx={document,location:{pathname:'/playlists/PLeligible/favorites'},localStorage:{getItem:k=>{if(mode==='blocked')throw Error('denied');return values.get(k);},setItem:(k,v)=>{if(mode==='blocked')throw Error('denied');values.set(k,v);}},
 fetch:async(path,opts)=>{calls.push({path,opts});return {ok:true,status:200,json:async()=>opts.method==='POST'?{created:true}:{series:'Bộ kinh',max_minutes:720,favorites,compilations:[]}};},
 window:{dispatchEvent:()=>{}},setTimeout:()=>1,clearTimeout:()=>{},confirm:()=>true};
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 vm.createContext(ctx);  // favorites.html loads app.js (AutoShort helpers) before favorites.js
 vm.runInContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[1]),'app.js'),'utf8'),ctx);
 vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+'\nFavorites.init();',ctx);await tick();
 assert.equal(get('fv-pane-ai').hidden,mode==='saved');
 assert.equal(get('fv-pane-manual').hidden,mode!=='saved');
 assert.equal(tabs[mode==='saved'?1:0]['aria-selected'],'true');
 tabs[1].listeners.click();assert.equal(get('fv-pane-manual').hidden,false);
 if(mode!=='blocked')assert.equal(values.get('autoShort.fvTab'),'manual');
 let prevented=false;tabs[1].listeners.keydown({key:'ArrowRight',preventDefault:()=>prevented=true});
 assert.ok(prevented);assert.equal(get('fv-pane-ai').hidden,false);assert.ok(tabs[0].focused);
 assert.equal(get('fv-count').textContent,2);
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
 console.log('ok');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""


@pytest.mark.parametrize("storage", ["default", "saved", "invalid", "blocked"])
def test_js_favorites_tabs_and_manual_compilation(storage):
    if shutil.which("node") is None:
        pytest.skip("node unavailable")
    result = subprocess.run(["node", "-e", NODE_TABS, str(STATIC / "favorites.js"), storage],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_favorites_tab_panel_ownership():
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
    for name in ("tp-generate", "tp-proposals", "tp-plans"):
        assert "fv-pane-ai" in nodes[name][1]
    for name in ("fv-list", "fv-filters", "fv-concat", "fv-all", "fv-auto", "fv-comps", "fv-max"):
        assert "fv-pane-manual" in nodes[name][1]
