"""THUMB2 AC4–5: socket-free service/routes/auth plus HTTP assertions for the ORCHESTRATOR."""
import asyncio
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

from auto_short import theme_plan as tp
from auto_short.compilation import Item, store
from auto_short.config import PackagingConfig
from auto_short.packaging import compilation_thumbs as ct, cover, episode, record, thumbnail
from auto_short.web import packaging as web
from auto_short.web.auth import COOKIE_NAME
from auto_short.web.jobs import RENDER
from auto_short.workspace import atomic_write_json
from test_packaging_cover import source_image
from test_packaging_thumbnail import fake_media
from test_theme_plan import Planner
from test_web_theme_index import fx
from test_web_theme_plan import PID, fake_output


@pytest.fixture
def service(tmp_path):
    cfg = replace(fx.seed(tmp_path / "scratch"), packaging=PackagingConfig(tmp_path / "assets"))
    app = fx.build_app(cfg, "pw", restrict=False)
    proposal = tp.propose(cfg, PID, client=Planner())["proposals"][0]
    plan = tp.create_plan(cfg, PID, proposal["proposal_id"])
    plan = tp.approve_plan(cfg, PID, plan["plan_id"], revision=plan["revision"], duration_override=True)
    s = SimpleNamespace(cfg=cfg, app=app, runner=app.state.runner, package=app.state.packages, plan=plan)
    s.package.media_runner = fake_media
    path, meta = fake_output(s, plan)
    # THUMB1 header / covers are local inputs, independent of the TC1 fixture's empty title header.
    ident = plan["clips"][0]["episode_id"]
    atomic_write_json(cfg.workspace.dir / ident.removesuffix(".kt") / "titles.json",
        dict(header=dict(fields=dict(series="Kinh Vô Lượng Thọ", speaker="HT. Tịnh Không", episode="23"))))
    for shape, size in thumbnail.EPISODE_SIZES.items():
        cover.install(cfg, PID, "kt_" + shape, source_image(tmp_path, size),
                      [int(size[0] * .1), int(size[1] * .4), int(size[0] * .8), int(size[1] * .45)])
    cid = "0123456789ab"
    folder = store.directory(cfg.render.output_dir, PID)
    doc = store.new_doc(PID, cid, "concat", (Item(ident, "k01"),), 1,
                       title="Học kinh để thực hành", download_name="Ghép.mp4", duration_estimate=350)
    doc.update(status=store.DONE)
    store.write_doc(folder, doc)
    (folder / (cid + ".mp4")).write_bytes(b"favourites video")
    s.cid, s.output = cid, (path, meta)
    return s


def endpoint(s, kind, method="GET", file=False):
    base = "/api/playlists/{pid}/" + ("compilations" if kind == "favorites" else "theme-plans") + "/{ident}/thumbs"
    return next(r.endpoint for r in s.app.routes if getattr(r, "path", None) == base + ("/{name}" if file else "") and method in r.methods)


@pytest.mark.parametrize("kind", ["favorites", "theme"])
def test_video_card_routes_job_lane_duplicate_cache_and_downloads(service, kind):
    s = service
    ident = s.cid if kind == "favorites" else s.plan["plan_id"]
    get, post, download = endpoint(s, kind), endpoint(s, kind, "POST"), endpoint(s, kind, file=True)
    assert json.loads(get(PID, ident).body)["state"] == "empty"
    assert post(PID, ident).status_code == 202
    assert post(PID, ident).status_code == 409
    job = s.runner.latest(web.render_key(PID, kind, ident))
    assert job.kind == web.KIND and [step.lane for step in job.steps] == [RENDER]
    job.target(job)  # real target, no server or sockets; job remains queued to exercise duplicate behaviour
    view = json.loads(get(PID, ident).body)
    assert view["state"] == "ready" and len(view["files"]) == 2
    assert get(PID, ident).headers["cache-control"] == "no-store"
    for shape, entry in view["files"].items():
        assert entry["preview_url"].endswith("?inline=1") and entry["download_url"].endswith(entry["file"])
        response = download(PID, ident, entry["file"], 0)
        assert response.media_type == "image/jpeg" and "attachment" in response.headers["content-disposition"]
        assert "content-disposition" not in download(PID, ident, entry["file"], 1).headers
    assert "dùng lại 0" in job.summary
    job.target(job)
    assert "dùng lại 2" in job.summary
    source = s.package.source(PID, kind, ident)
    entry = view["files"]["vertical"]
    (source.folder / entry["file"]).write_bytes(b"tampered")
    assert download(PID, ident, entry["file"], 0).status_code == 404
    assert json.loads(get(PID, ident).body)["state"] == "stale"
    for bad in ("../secret", "bad.jpg", "A-landscape-" + "a" * 64 + ".jpg", "vertical-" + "b" * 64 + ".jpg"):
        assert download(PID, ident, bad, 1).status_code == 404
    assert get("bad!", ident).status_code == 404
    assert get(PID, "../../secret").status_code in (400, 404, 422)


def test_missing_cover_new_revision_and_preserve_retired_files(service):
    s = service
    ident = s.plan["plan_id"]
    source = s.package.source(PID, "theme", ident)
    source.folder.mkdir(parents=True)
    legacy = {"package.json": b"legacy approval", "A-landscape-" + "a" * 64 + ".jpg": b"old A/B/C",
              "variant-abcdef123456.mp4": b"old ambient + music"}
    for name, value in legacy.items():
        (source.folder / name).write_bytes(value)
    ct.build(s.cfg, source, run=fake_media)
    assert all((source.folder / name).read_bytes() == value for name, value in legacy.items())
    # Revision r+1 is an independent output directory; TC3 sidecar remains the download authority.
    assert record.directory(s.cfg.render.output_dir, PID, ident, 2) != source.folder
    before = {p.name: p.read_bytes() for p in source.folder.iterdir()}
    cover.remove(s.cfg, PID, "kt_vertical")
    view = json.loads(endpoint(s, "theme")(PID, ident).body)
    assert view["reason"] == ct.MISSING_COVER and view["cover_url"] == f"/playlists/{PID}/thumbs"
    assert endpoint(s, "theme", "POST")(PID, ident).status_code == 400
    assert before == {p.name: p.read_bytes() for p in source.folder.iterdir()}
    assert s.app.state.theme_plans.output(PID, s.app.state.theme_plans.find(PID, ident), verify=True) == s.output


@pytest.mark.parametrize("kind", ["favorites", "theme"])
@pytest.mark.parametrize("location", ["file", "sidecar", "folder", "source"])
def test_symlinks_are_blocked(service, tmp_path, kind, location):
    s = service
    ident = s.cid if kind == "favorites" else s.plan["plan_id"]
    source = s.package.source(PID, kind, ident)
    ct.build(s.cfg, source, run=fake_media)
    name = ct.read(source)["files"]["vertical"]["file"]
    path = source.folder / name
    if location == "sidecar":
        path = source.folder / "thumbs.json"
    elif location == "folder":
        path = source.folder
    elif location == "source":
        path = store.directory(s.cfg.render.output_dir, PID) / (s.cid + ".json") if kind == "favorites" else s.output[0]
    target = tmp_path / "outside"
    path.rename(target)
    path.symlink_to(target, target_is_directory=location == "folder")
    assert endpoint(s, kind, file=True)(PID, ident, name, 1).status_code in (400, 404, 422)


def test_retired_package_routes_are_404_and_new_routes_require_auth(service):
    s = service
    old = [f"/playlists/{PID}/theme-plans/abcdefgh/package", f"/api/playlists/{PID}/theme-plans/abcdefgh/package",
           f"/api/playlists/{PID}/theme-plans/abcdefgh/package/thumbnails", f"/api/playlists/{PID}/theme-plans/abcdefgh/package/approve",
           f"/api/playlists/{PID}/theme-plans/abcdefgh/package/variants", f"/api/playlists/{PID}/theme-plans/abcdefgh/package/preview",
           f"/files/playlists/{PID}/theme-pkg/abcdefgh-r1/A-landscape-{'a' * 64}.jpg",
           f"/files/playlists/{PID}/theme-pkg/abcdefgh-r1/variant-abcdef123456.mp4"]
    # Resolve through the real route table, including the /files catch-all.
    for path in old:
        scope = dict(type="http", path=path, method="POST" if "/api/" in path else "GET", root_path="")
        matches = [r for r in s.app.routes if r.matches(scope)[0] == Match.FULL]
        assert not matches or all("files_catchall" in r.endpoint.__module__ for r in matches)
    dispatch = next(m.kwargs["dispatch"] for m in s.app.user_middleware if getattr(m.kwargs.get("dispatch"), "__name__", "") == "auth_middleware")
    async def check():
        for kind in ("favorites", "theme"):
            base = f"/api/playlists/{PID}/" + (f"compilations/{s.cid}" if kind == "favorites" else f"theme-plans/{s.plan['plan_id']}") + "/thumbs"
            for method, path in (("GET", base), ("POST", base), ("GET", base + "/vertical-" + "a" * 64 + ".jpg")):
                for signed_in in (False, True):
                    called = False
                    async def downstream(request):
                        nonlocal called
                        called = True
                        return Response(status_code=204)
                    headers = [(b"cookie", f"{COOKIE_NAME}={s.app.state.signer.issue()}".encode())] if signed_in else []
                    response = await dispatch(Request(dict(type="http", method=method, path=path, headers=headers, query_string=b"")), downstream)
                    assert response.status_code == (204 if signed_in else 401) and called is signed_in
    asyncio.run(check())
    static = Path(web.__file__).parent / "static"
    assert not (static / "package.html").exists() and not (static / "package.js").exists()
    assert "Đóng gói" not in (static / "theme_plan.js").read_text()


NODE_CARDS = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
class El {
 constructor(tag='div') { this.tagName=tag.toUpperCase(); this.children=[]; this.listeners={}; this.dataset={}; this.isConnected=true; this._text=''; this.classList={toggle:()=>{}}; }
 setAttribute(k,v) { this[k]=v; }
 append(...nodes) { this.children.push(...nodes.filter(n=>n!=null)); }
 replaceChildren(...nodes) { this._text=''; this.children=[]; this.append(...nodes); }
 addEventListener(k,f) { this.listeners[k]=f; }
 contains(node) { return this===node || this.children.some(n=>n instanceof El && n.contains(node)); }
 set textContent(v) {this._text=String(v);this.children=[];}
 get textContent() {return this._text+this.children.map(n=>n instanceof El?n.textContent:String(n)).join('');}
}
const els={}, get=id=>els[id] ||= new El(), timers=[], calls=[], copies=[];
const mode=process.argv[2], jobs=new Map();
const document={querySelector:s=>get(s.slice(1)),getElementById:get,querySelectorAll:()=>[],activeElement:null};
function el(tag, attrs={}, ...children) {const n=new El(tag);for(const [k,v] of Object.entries(attrs)) {if(k==='text')n.textContent=v;else n.setAttribute(k,v);}n.append(...children);return n;}
async function api(path, options={}) {
 calls.push([path,options.method || 'GET']);
 if(path.endsWith('/thumbs')) {
  if(options.method==='POST') {jobs.set(path,'busy');return {created:true};}
  const state=jobs.get(path)||mode;
  if(state==='ready'||state==='stale') return {state,reason:state==='stale'?'Thumbnail cũ — dựng lại':null,
   files:{vertical:{preview_url:'/vertical.jpg?inline=1',download_url:'/vertical.jpg'},landscape:{preview_url:'/landscape.jpg?inline=1',download_url:'/landscape.jpg'}}};
  return {state:'empty',reason:state==='missing'?'Bộ kinh chưa có ảnh bìa khai thị':null,
   cover_url:'/playlists/PLeligible/thumbs',files:{},job:state==='busy'?{active:true}:null};
 }
 if(path.endsWith('/compilations')) return {series:'Kinh',favorites:[],max_minutes:720,compilations:[{
  cid:'0123456789ab',state:'done',mode:'concat',title:'Tiêu đề ghép',download_name:'Ghép.mp4',download_url:'/files/favorites.mp4',description:'Mô tả ghép'}]};
 if(path.endsWith('/theme-plan')) return {index_summary:{usable:1},generate_job:null,proposals:null,plans:[{
  plan_id:'abcdefgh',revision:1,title:'Tiêu đề plan',clips:[],total_duration:2000,check:{state:'approved'},
  output:{download_name:'Tiêu đề render.mp4',description:'Mô tả render',download_url:'/files/theme.mp4'}}]};
 throw Error('unexpected request '+path);
}
const ctx={document,AutoShort:{el,api,copyText:async t=>{copies.push(t);return true;}},location:{pathname:'/playlists/PLeligible/favorites'},
 window:{addEventListener:()=>{},dispatchEvent:()=>{}},localStorage:{getItem:()=>null,setItem:()=>{}},
 setTimeout:(f,ms)=>{timers.push({f,ms});return timers.length;},clearTimeout:()=>{},confirm:()=>true};
const tick=()=>new Promise(r=>setImmediate(r)), all=n=>[n,...n.children.filter(n=>n instanceof El).flatMap(all)];
function button(root,text) {const b=all(root).find(n=>n.tagName==='BUTTON' && n.textContent===text);assert.ok(b,text);return b;}
(async()=>{
 get('fv-auto-min').value='60';vm.createContext(ctx);
 for(const name of ['favorites.js','theme_plan.js'])vm.runInContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'),ctx);
 vm.runInContext('Favorites.init(); ThemePlan.init();',ctx);await tick();
 for(const t of timers.filter(t=>t.ms===0))await t.f();await tick();
 const blocks=[get('fv-comps'),get('tp-plans')].map(root=>{
  const texts=all(root).map(n=>n.textContent);
  for(const label of ['Xem','Tải video','Copy tiêu đề','Copy mô tả'])assert.ok(texts.includes(label),label);
  assert.ok(!texts.includes('Đóng gói'));
  return all(root).find(n=>n.class==='fv-thumbnails');
 });
 assert.ok(blocks.every(Boolean));assert.equal(calls.filter(([p])=>p.endsWith('/thumbs')).length,2);
 await button(get('fv-comps'),'Copy tiêu đề').listeners.click();await button(get('tp-plans'),'Copy tiêu đề').listeners.click();
 assert.deepEqual(copies,['Tiêu đề ghép','Tiêu đề render']);
 if(mode==='missing') {
  for(const b of blocks) {assert.ok(b.textContent.includes('chưa có ảnh bìa khai thị'));assert.ok(button(b,'Dựng thumbnail').disabled);
   assert.ok(all(b).some(n=>n.tagName==='A' && n.href==='/playlists/PLeligible/thumbs'));}
 } else {
  for(const b of blocks) {
   if(mode==='stale')assert.ok(button(b,'Dựng lại'));
   else {await button(b,'Dựng thumbnail').listeners.click();assert.ok(button(b,'Dựng thumbnail').disabled);}
  }
  for(const key of jobs.keys())jobs.set(key,'ready');
  for(const t of timers.filter(t=>t.ms===3000))await t.f();
  for(const b of blocks) {
   assert.equal(all(b).filter(n=>n.tagName==='IMG').length,2);
   assert.ok(all(b).some(n=>n.tagName==='A' && n.textContent==='Tải ảnh dọc'));
   assert.ok(all(b).some(n=>n.tagName==='A' && n.textContent==='Tải ảnh ngang'));
  }
 }
 console.log('ok');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""


@pytest.mark.parametrize("state", ["empty", "stale", "missing"])
def test_both_video_cards_thumbnail_actions_and_polling(state):
    static = Path(web.__file__).parent / "static"
    result = subprocess.run(["node", "-e", NODE_CARDS, str(static), state], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


@pytest.mark.parametrize('case', ['intro_stale', 'intro_current', 'missing_cover'])
def test_kti2_intro_status_and_cover_links_on_both_cards(case):
    script = NODE_CARDS
    if case == 'missing_cover':
        message = 'Bộ kinh chưa có ảnh bìa khai thị — /playlists/PLeligible/thumbs'
        script = script.replace("cid:'0123456789ab',state:", f"error:'{message}',cid:'0123456789ab',state:")
        script = script.replace("output:{download_name:", f"render_job:{{status:'failed',error:'{message}'}},output:{{download_name:")
        assertion = """for (const id of ['fv-comps','tp-plans']) assert.ok(all(get(id)).some(n=>
          n.tagName==='A' && n.textContent==='Thiết kế bìa khai thị' && n.href==='/playlists/PLeligible/thumbs'));"""
    else:
        digest = 'old' if case == 'intro_stale' else 'new'
        script = script.replace('output:{download_name:', f"output:{{intro:{{sha256:'{digest}'}},download_name:")
        script = script.replace('landscape:{preview_url:', "landscape:{sha256:'new',preview_url:")
        assertion = f"assert.equal(get('tp-plans').textContent.includes('Thumbnail intro đã đổi'), {str(case == 'intro_stale').lower()});"
    script = script.replace("console.log('ok');", assertion + "\nconsole.log('ok');")
    static = Path(web.__file__).parent / 'static'
    result = subprocess.run(['node', '-e', script, str(static), 'stale'], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
