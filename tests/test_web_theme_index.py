"""TC-WEB1: GET-only web preview of the TC1 theme index (offline, synthetic fixtures, no AI / network / media)."""
import hashlib
import importlib.util
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auto_short import config as config_mod
from auto_short import theme_index as tc1
from auto_short.review import logic
from auto_short.selection.client import OllamaClient
from auto_short.web import app as app_mod
from auto_short.web import theme_index as web
from auto_short.web.auth import COOKIE_NAME
from auto_short.workspace import atomic_write_json

SPEC = importlib.util.spec_from_file_location(
    "theme_index_preview_fixture", Path(__file__).parent.parent / "scripts" / "theme_index_preview_fixture.py")
fx = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fx)
PW = "pw-test"
STATIC = Path(app_mod.__file__).parent / "static"


@pytest.fixture(autouse=True)
def _fast_login(monkeypatch):
    monkeypatch.setattr(app_mod, "LOGIN_DELAY", 0.0)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "scratch"


@pytest.fixture
def seeded(root):
    return fx.seed(root)


@pytest.fixture
def client(seeded):
    c = TestClient(fx.build_app(seeded, PW), follow_redirects=False)
    r = c.post("/login", json={"password": PW})
    assert r.status_code == 200
    c.cookies.set(COOKIE_NAME, r.cookies[COOKIE_NAME])
    return c


def get(client, pid):
    return client.get(f"/api/playlists/{pid}/theme-index")


def snapshot(root):
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p)] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
        else:
            out[str(p)] = "dir"
    return out


# --- auth / routing ---------------------------------------------------------------------------------------

def test_auth_required(seeded):
    c = TestClient(fx.build_app(seeded, PW), follow_redirects=False)
    page = c.get("/playlists/PLeligible/theme-index")
    assert page.status_code == 303 and page.headers["location"].startswith("/login")
    assert c.get("/api/playlists/PLeligible/theme-index").status_code == 401


def test_page_served_and_ids_validated(client):
    page = client.get("/playlists/PLeligible/theme-index")
    assert page.status_code == 200 and "Dữ liệu kiểm thử tổng hợp" in page.text
    assert client.get("/playlists/bad id/theme-index").status_code == 404
    assert get(client, "bad$id").status_code == 404
    assert get(client, "PLnonexistent").status_code == 404
    assert client.get("/playlists/PLnonexistent/theme-index").status_code == 404
    assert client.get("/playlists/PLmalformed/theme-index").status_code == 200  # playlist ok; favorites 422 is the API's
    assert get(client, "..%2f..%2fetc").status_code == 404


def test_only_get_routes(client):
    routes = [r for r in client.app.routes if "theme-index" in getattr(r, "path", "")]
    assert len(routes) == 2 and all(set(r.methods) == {"GET"} for r in routes)
    for method in ("post", "put", "delete", "patch"):  # sandbox allowlist answers 404 before the app
        assert getattr(client, method)("/api/playlists/PLeligible/theme-index").status_code == 404


def test_app_itself_rejects_non_get(seeded):
    c = TestClient(fx.build_app(seeded, PW, restrict=False), follow_redirects=False)
    c.cookies.set(COOKIE_NAME, c.post("/login", json={"password": PW}).cookies[COOKIE_NAME])
    for method in ("post", "put", "delete", "patch"):
        assert getattr(c, method)("/api/playlists/PLeligible/theme-index").status_code == 405


def test_static_has_no_html_injection_or_media():
    js = (STATIC / "theme_index.js").read_text(encoding="utf-8")
    html = (STATIC / "theme_index.html").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "eval(" not in js
    assert "<video" not in html and "<audio" not in html and "download" not in js.lower().replace("downloaded", "")
    assert "method:" not in js  # fetch is GET only


# --- content ----------------------------------------------------------------------------------------------

def test_eligible_hit_full_record_and_no_absolute_paths(client, root):
    r = get(client, "PLeligible")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["schema_version"] == 1 and body["data_mode"] == "synthetic_preview"
    assert body["generation_enabled"] is False and body["counts"]["indexed"] == 1 and body["total"] == 1
    rec = body["records"][0]
    assert rec["status"] == "indexed" and rec["cached"] is True and rec["duration"] == 350
    assert rec["final_segments"] == [[0, 100], [110, 360]]
    assert [e["evidence_id"] for e in rec["evidence"]] == ["s1"]
    assert rec["uncertainty"] and any("cross" in u for u in rec["uncertainty"])
    assert rec["metadata"]["uncertainty"] == [] and rec["metadata"]["synopsis"]["evidence_id"] == "s1"
    assert rec["provenance"]["model"] == fx.FAKE_MODEL and rec["input_fingerprint"] and rec["indexed_at"]
    assert rec["source_reference"]["reference"].endswith("source.mp4") and not rec["source_reference"]["path_hidden"]
    assert "path" not in rec["source_reference"] and rec["source_reference"]["sha256"]
    text = r.text
    assert str(root.parent) not in text and str(root) not in text
    evidence_text = json.dumps(rec["evidence"], ensure_ascii=False)
    assert all(word not in evidence_text for word in ("OUTSIDE", "REMOVED", "CROSSING"))


def test_mixed_playlist_keeps_every_favorite_with_reasons(client, root):
    body = get(client, "PLmixedcases").json()
    recs = body["records"]
    assert [x["favorite_position"] for x in recs] == list(range(7)) and body["total"] == 7
    reasons = [x.get("reason", "") for x in recs]
    assert recs[0]["status"] == "indexed"
    assert all(x["status"] == "ineligible" for x in recs[1:])
    assert any("duration" in s for s in reasons) and any(s == "rejected" for s in reasons)
    assert any("not a khai thi" in s for s in reasons) and any("kept" in s for s in reasons)
    assert reasons[1]  # lost original source: reason kept (path redacted below)
    assert body["counts"] == {"indexed": 1, "eligible": 0, "ineligible": 6, "ai_error": 0}
    assert str(root) not in json.dumps(body)
    lost = recs[1]["reason"]
    assert web.HIDDEN in lost  # the OSError text contained an absolute path
    assert recs[2].get("duration") is None  # nothing inferred for ineligible records
    assert recs[-1]["favorite"] == {"episode_id": "", "clip": 3}


def test_cache_miss_and_corrupt_cache_report_generation_disabled(client):
    for pid in ("PLmissingcache", "PLcorruptcache"):
        body = get(client, pid).json()
        rec = body["records"][0]
        assert rec["status"] == "ai_error" and rec["reason"] == web.GENERATION_DISABLED, pid
        assert "metadata" not in rec and "indexed_at" not in rec
        assert "invented" not in json.dumps(body)
        assert body["counts"]["ai_error"] == 1 and rec["evidence"] and rec["input_fingerprint"]


def test_empty_zero_eligible_and_malformed_are_distinguished(client):
    empty = get(client, "PLemptyfavs")
    assert empty.status_code == 200 and empty.json()["records"] == [] and empty.json()["total"] == 0
    bad = get(client, "PLmalformed")
    assert bad.status_code == 422 and "Traceback" not in bad.text and "records" not in bad.json()
    assert bad.headers["cache-control"] == "no-store"


def test_malformed_playlist_artifact_is_422(client, seeded):
    (Path(seeded.workspace.dir) / "_playlists" / "PLbrokenjson.json").write_text("{not json", encoding="utf-8")
    r = get(client, "PLbrokenjson")
    assert r.status_code == 422 and str(seeded.workspace.dir) not in r.text
    page = client.get("/playlists/PLbrokenjson/theme-index")
    assert page.status_code == 422 and str(seeded.workspace.dir) not in page.text


# --- GET has no side effects / no external services -------------------------------------------------------

def test_get_has_no_side_effects_and_no_external_calls(client, seeded, root, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(("Popen", a)))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(("run", a)))
    monkeypatch.setattr(OllamaClient, "chat", lambda *a, **k: calls.append(("ollama", a)))
    writes = []
    monkeypatch.setattr(tc1, "atomic_write_json", lambda *a, **k: writes.append(a))
    before = snapshot(root)
    for pid in ("PLeligible", "PLmissingcache", "PLmixedcases", "PLemptyfavs", "PLmalformed", "PLcorruptcache"):
        get(client, pid)
        client.get(f"/playlists/{pid}/theme-index")
    assert snapshot(root) == before
    assert calls == [] and writes == []
    assert client.app.state.runner.jobs() == []


def test_preview_never_reaches_a_real_client(seeded, monkeypatch):
    monkeypatch.setattr(tc1, "OllamaClient", lambda *a, **k: pytest.fail("OllamaClient created"))
    cfg_miss = replace(seeded, selection=replace(seeded.selection, model="other-model"))
    rec = web.preview(cfg_miss, "PLeligible")["records"][0]
    assert rec["status"] == "ai_error" and rec["reason"] == web.GENERATION_DISABLED


# --- invalidation matrix ----------------------------------------------------------------------------------

def _status(cfg, pid="PLeligible"):
    return web.preview(cfg, pid)["records"]


def _assert_not_usable(records):
    assert all(r["status"] != "indexed" and "metadata" not in r for r in records), records


def _ws(cfg, base="eligible"):
    return Path(cfg.workspace.dir) / f"{base}.kt"


def _out(cfg, base="eligible"):
    return Path(cfg.render.output_dir) / f"{base}.kt"


def _edit(path, mutate):
    doc = json.loads(path.read_text(encoding="utf-8"))
    mutate(doc)
    atomic_write_json(path, doc)


def test_baseline_is_a_hit(seeded):
    assert _status(seeded)[0]["status"] == "indexed"


def test_invalidation_source_render_transcript_cut(seeded):
    ws, out = _ws(seeded), _out(seeded)
    (ws / "source.mp4").write_bytes(b"changed")
    r = _status(seeded)
    _assert_not_usable(r)
    assert r[0]["status"] == "ineligible" and "stale" in r[0]["reason"]


def test_invalidation_render_bytes(seeded):
    (_out(seeded) / "shorts" / "k01.mp4").write_bytes(b"other")
    r = _status(seeded)
    _assert_not_usable(r)
    assert "stale content" in r[0]["reason"]


def test_invalidation_manual_cut(seeded):
    ws = _ws(seeded)
    review = logic.with_cut(logic.empty_review("eligible.kt"), ["k01"], clip_id="k01", candidate_id="c1", start=1, end=360)
    atomic_write_json(ws / "review.json", review)
    silences = dict(silences=[])
    atomic_write_json(ws / "silences.json", silences)
    _edit(ws / "candidates.json", lambda d: d.update(silences_sha256=fx.hashing.config_hash(silences)))
    r = _status(seeded)
    _assert_not_usable(r)
    assert r[0]["status"] == "ineligible"


def test_invalidation_transcript_content_and_linkage(seeded):
    ws = _ws(seeded)
    _edit(ws / "transcript.json", lambda d: d["segments"][1].update(text="Nội dung khác."))
    r = _status(seeded)
    _assert_not_usable(r)
    assert r[0]["status"] == "ineligible" and "linkage" in r[0]["reason"]


def test_invalidation_transcript_source_link(seeded):
    _edit(_ws(seeded) / "transcript.json", lambda d: d.update(media_sha256="0" * 64))
    r = _status(seeded)
    _assert_not_usable(r)
    assert "stale transcript" in r[0]["reason"]


def test_invalidation_rejection_and_unheart(seeded):
    ws = _ws(seeded)
    atomic_write_json(ws / "review.json", logic.with_rejected(logic.empty_review("eligible.kt"), ["k01"],
                                                              clip_id="k01", candidate_id="c1"))
    r = _status(seeded)
    _assert_not_usable(r)
    assert r[0]["reason"] == "rejected"
    fav = Path(seeded.render.output_dir) / "_compilations" / "PLeligible" / "favorites.json"
    _edit(fav, lambda d: d.update(items=[]))
    assert _status(seeded) == []  # unhearted -> gone from current records; the old cache is not shown


@pytest.mark.parametrize("change", ["model", "temperature", "seed", "num_ctx", "think"])
def test_invalidation_model_and_options(seeded, change):
    sel = seeded.selection
    new = {"model": "m2", "temperature": sel.temperature + 0.5, "seed": sel.seed + 1, "num_ctx": sel.num_ctx + 1,
           "think": not sel.think if isinstance(sel.think, bool) else True}[change]
    r = _status(replace(seeded, selection=replace(sel, **{change: new})))
    _assert_not_usable(r)
    assert r[0]["status"] == "ai_error" and r[0]["reason"] == web.GENERATION_DISABLED


def test_invalidation_prompt_schema_and_corrupt_timestamp(seeded, monkeypatch):
    folder = Path(seeded.render.output_dir) / "_compilations" / "PLeligible"
    _edit(folder / "theme_index.json", lambda d: d["records"][0].update(indexed_at=None))
    r = _status(seeded)
    _assert_not_usable(r)
    assert r[0]["reason"] == web.GENERATION_DISABLED


def test_invalidation_prompt_change(seeded, monkeypatch):
    monkeypatch.setattr(tc1, "SYSTEM", tc1.SYSTEM + " changed")
    _assert_not_usable(_status(seeded))


@pytest.mark.parametrize("duration,eligible", [(299, False), (300, True), (420, True), (421, False)])
def test_duration_boundaries(root, duration, eligible):
    root.mkdir()
    cfg = config_mod.load(fx.write_config(root))
    e = fx.make_episode(cfg, "PLboundary1", "bound", duration=duration)
    fx.make_playlist(cfg, "PLboundary1", ["bound"], [dict(episode_id=e["episode_id"], clip="k01")])
    rec = web.preview(cfg, "PLboundary1")["records"][0]
    if eligible:
        assert rec["status"] == "ai_error" and rec["duration"] == duration  # eligible, but nothing cached
    else:
        assert rec["status"] == "ineligible" and "duration" in rec["reason"]


# --- sandbox isolation ------------------------------------------------------------------------------------

def test_startup_is_isolated(seeded, root, tmp_path, monkeypatch):
    canary = tmp_path / "canary"
    home = canary / "home"
    cwd = canary / "cwd"
    home.mkdir(parents=True)
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd)
    spawned = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: spawned.append(a))
    monkeypatch.setattr(OllamaClient, "chat", lambda *a, **k: spawned.append("ollama"))
    app = fx.build_app(seeded, PW)
    before = snapshot(canary)
    with TestClient(app) as c:  # runs the lifespan: runner.restore / lanes / sampler / auto-archive pass
        c.post("/login", json={"password": PW})
        assert c.get("/api/playlists/PLeligible/theme-index").status_code == 200
    assert snapshot(canary) == before
    assert spawned == []
    created = [p for p in Path(seeded.workspace.dir).iterdir() if p.name.startswith(".") or p.suffix == ".json"]
    assert all(p.resolve().is_relative_to(root.resolve()) for p in created)


def test_seed_refuses_non_empty_root(root):
    root.mkdir()
    (root / "x").write_text("data")
    with pytest.raises(SystemExit):
        fx.seed(root)
    assert [p.name for p in root.iterdir()] == ["x"]


def test_assert_sandbox_rejects_unmarked_or_foreign_config(seeded, root, tmp_path):
    fx.assert_sandbox(seeded, root)
    with pytest.raises(SystemExit):
        fx.assert_sandbox(seeded, tmp_path / "elsewhere")
    foreign = replace(seeded, render=replace(seeded.render, output_dir=tmp_path / "prod-output"))
    with pytest.raises(SystemExit):
        fx.assert_sandbox(foreign, root)
    (Path(seeded.workspace.dir) / fx.MARKER).unlink()
    with pytest.raises(SystemExit):
        fx.assert_sandbox(seeded, root)


def test_service_stubs_refuse(seeded):
    stubs = fx._refuse("render")
    with pytest.raises(RuntimeError):
        stubs()


def test_redact_helper():
    assert web.redact("cannot read /home/u/work/x.json: boom") == f"cannot read {web.HIDDEN}: boom"
    assert web.redact("duration outside 300-420 seconds") == "duration outside 300-420 seconds"
    assert web.redact("a/b relative") == "a/b relative"


# --- R1: no absolute path anywhere in the response ------------------------------------------------------------

LEAK = "/home/private-secret/example"


def test_nested_and_invalid_favorite_paths_are_redacted(client, seeded):
    fav = Path(seeded.render.output_dir) / "_compilations" / "PLeligible" / "favorites.json"
    _edit(fav, lambda d: (d["items"][0].update(note=LEAK, nested={"a": [LEAK, {"b": f"x {LEAK}/y"}]}),
                          d["items"].append({"episode_id": LEAK, "clip": 1, LEAK: "k"})))
    body = get(client, "PLeligible")
    assert body.status_code == 200 and "private-secret" not in body.text
    recs = body.json()["records"]
    assert [r["favorite_position"] for r in recs] == [0, 1]
    assert web.HIDDEN in json.dumps(recs[0]["favorite"], ensure_ascii=False) and web.HIDDEN in json.dumps(recs[0]["inputs"]["favorite"], ensure_ascii=False)
    assert recs[0]["evidence"] and recs[0]["status"] != "indexed"  # changed favorite -> fingerprint miss, evidence kept
    assert recs[1]["status"] == "ineligible"


def test_projection_keeps_extractive_content_verbatim(seeded):
    rec = web.preview(seeded, "PLeligible")["records"][0]
    raw = tc1.build_index(seeded, "PLeligible", write=False, client=web.RefusingClient())["records"][0]
    assert rec["evidence"] == raw["evidence"] and rec["metadata"] == raw["metadata"]
    assert rec["provenance"] == raw["provenance"] and rec["input_fingerprint"] == raw["input_fingerprint"]


def test_evidence_text_that_looks_like_a_path_is_not_altered(seeded):
    rec = web.project_record(seeded, {"evidence": [{"text": "xem /etc/passwd"}], "reason": "bad /etc/passwd"})
    assert rec["evidence"][0]["text"] == "xem /etc/passwd" and rec["reason"] == f"bad {web.HIDDEN}"


# --- R2: sandbox exposes only login/logout + theme routes -------------------------------------------------------

def test_sandbox_config_paths_are_all_under_root(seeded, root):
    for p in (seeded.workspace.dir, seeded.render.output_dir, seeded.post.image_dir, seeded.post.corrections_path):
        assert Path(p).resolve().is_relative_to(root.resolve()), p
    assert not seeded.storage.auto_archive and not seeded.enhance.enabled
    fx.assert_sandbox(seeded, root)
    for field, value in (("image_dir", Path.home() / "x"), ("corrections_path", Path.home() / "y.json")):
        with pytest.raises(SystemExit):
            fx.assert_sandbox(replace(seeded, post=replace(seeded.post, **{field: value})), root)
    with pytest.raises(SystemExit):
        fx.assert_sandbox(replace(seeded, storage=replace(seeded.storage, auto_archive=True)), root)
    with pytest.raises(SystemExit):
        fx.assert_sandbox(replace(seeded, enhance=replace(seeded.enhance, enabled=True)), root)


MUTATING = [
    ("post", "/api/post-corrections", {"json": {"find": "a", "replace": "b"}}),
    ("put", "/api/post-corrections/r1", {"json": {"find": "a", "replace": "b"}}),
    ("delete", "/api/post-corrections/r1", {}),
    ("post", "/api/post-images", {"files": {"file": ("a.png", b"x", "image/png")}}),
    ("delete", "/api/post-images/a.png", {}),
    ("post", "/api/post-images/search", {"json": {"url": "https://example.com"}}),
    ("post", "/api/post-images/find", {"json": {"keyword": "x"}}),
    ("post", "/api/playlists", {"json": {"url": "https://www.youtube.com/playlist?list=PLxxxxxxxxxx"}}),
    ("post", "/api/playlists/PLeligible/favorites", {"json": {"episode_id": "eligible.kt", "clip": "k01"}}),
    ("post", "/api/episodes/eligible.kt/enhance/rerender", {"json": {}}),
    ("post", "/api/episodes/eligible.kt/process", {"json": {}}),
    ("put", "/api/playlists/PLeligible/doc", {"json": {}}),
    ("get", "/api/enhance/lease", {}), ("get", "/api/jobs", {}), ("get", "/monitor", {}), ("get", "/", {}),
    ("get", "/files/anything.mp4", {}), ("get", "/api/playlists/PLeligible/favorites", {}),
    ("post", "/api/playlists/PLeligible/theme-index", {"json": {}}),
]


def test_sandbox_blocks_every_other_route_before_handlers(client, seeded, root, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append("Popen"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append("run"))
    monkeypatch.setattr(OllamaClient, "chat", lambda *a, **k: calls.append("ollama"))
    before, home_before = snapshot(root), snapshot(home)
    for method, path, kw in MUTATING:
        r = getattr(client, method)(path, **kw)
        assert r.status_code == 404 and "sandbox" in r.text, (method, path, r.status_code)
    for method, path, kw in MUTATING:  # also without a session: still 404, never 401/redirect to a handler
        r = getattr(TestClient(client.app, follow_redirects=False), method)(path, **kw)
        assert r.status_code == 404
    assert snapshot(root) == before and snapshot(home) == home_before
    assert calls == [] and client.app.state.runner.jobs() == []
    assert not Path(seeded.post.corrections_path).exists() and not Path(seeded.post.image_dir).exists()


def test_allowlist_keeps_auth_and_allowed_routes(seeded):
    c = TestClient(fx.build_app(seeded, PW), follow_redirects=False)
    assert c.get("/static/style.css").status_code == 200  # public in the existing app
    assert c.get("/static/theme_index.js").status_code == 303  # behind auth like the rest
    assert c.get("/login").status_code == 200
    assert c.post("/login", json={"password": "wrong"}).status_code == 401
    assert c.get("/api/playlists/PLeligible/theme-index").status_code == 401  # auth middleware still applies
    ok = c.post("/login", json={"password": PW})
    c.cookies.set(COOKIE_NAME, ok.cookies[COOKIE_NAME])
    assert c.get("/static/theme_index.js").status_code == 200 and c.get("/static/app.js").status_code == 404
    assert c.post("/logout").status_code in (200, 303)


def test_startup_queue_and_state_stay_in_scratch(seeded, root, tmp_path, monkeypatch):
    stray = tmp_path / "stray"
    stray.mkdir()
    monkeypatch.chdir(stray)
    monkeypatch.setenv("HOME", str(stray))
    with TestClient(fx.build_app(seeded, PW)) as c:
        assert c.app.state.runner.jobs() == []
    assert list(stray.iterdir()) == []


# --- R4: UI never keeps a stale result as current ---------------------------------------------------------------

NODE_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
class El { constructor(t) { this.tag = t; this.children = []; this._t = ""; this.hidden = false; this.disabled = false; this.listeners = {}; }
  set textContent(v) { this._t = String(v); this.children = []; }
  get textContent() { return this._t + this.children.map(c => c.textContent).join(""); }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener(e, f) { this.listeners[e] = f; } }
const els = {};
const document = { getElementById: id => (els[id] = els[id] || new El(id)), createElement: t => new El(t) };
const record = { favorite_position: 0, identity: { episode_id: "ep.kt", clip: "k01" }, favorite: { episode_id: "ep.kt", clip: "k01" },
  status: "indexed", cached: true, evidence: [{ evidence_id: "s1", start: 1, end: 2, text: "Phải chuyên tâm" }],
  metadata: { topic: "T", subtopic: "S", synopsis: { evidence_id: "s1", text: "x" }, key_messages: [], uncertainty: [] } };
const ok = { ok: true, status: 200, json: async () => ({ data_mode: "synthetic_preview", generation_enabled: false, checked_at: "T1",
  total: 1, counts: { indexed: 1 }, records: [record] }) };
let next = ok;
const code = fs.readFileSync(process.argv[1], "utf8");
const tick = () => new Promise(r => setTimeout(r, 5));
const state = () => ({ list: els["ti-list"].textContent, counts: els["ti-counts"].textContent, checked: els["ti-checked"].textContent,
  mode: els["ti-mode"].textContent, total: els["ti-total"].textContent, msg: els["ti-msg"].textContent, disabled: els["ti-refresh"].disabled });
(async () => {
  const out = {};
  const fetch = () => (typeof next === "function" ? next() : Promise.resolve(next));
  vm.runInNewContext(code, { document, fetch, location: { pathname: "/playlists/PLeligible/theme-index", href: "" },
    encodeURIComponent, decodeURIComponent, JSON, Object, String, Promise, setTimeout });
  await tick(); out.success = state();
  const click = async (n) => { next = n; els["ti-refresh"].listeners.click(); out.during = state(); await tick(); return state(); };
  out.rejected = await click(() => Promise.reject(new Error("net")));
  await click(ok); out.restored = state();
  out.http500 = await click({ ok: false, status: 500, json: async () => ({ detail: "boom" }) });
  await click(ok);
  out.badjson = await click({ ok: true, status: 200, json: async () => { throw new Error("bad json"); } });
  await click(ok);
  out.rendererr = await click({ ok: true, status: 200, json: async () => ({ total: 1, counts: {}, records: [null] }) });
  console.log(JSON.stringify(out));
})();
"""


def test_ui_refresh_failure_never_keeps_stale_rows():
    import shutil
    if shutil.which("node") is None:
        pytest.skip("node not available")
    out = subprocess.run(["node", "-e", NODE_HARNESS, str(STATIC / "theme_index.js")], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout)
    assert "ep.kt" in res["success"]["list"] and "indexed: 1" in res["success"]["counts"] and res["success"]["checked"]
    assert res["during"]["list"] == "" and res["during"]["counts"] == "" and res["during"]["checked"] == ""  # cleared at once
    assert res["restored"]["list"]
    for key in ("rejected", "http500", "badjson", "rendererr"):
        r = res[key]
        assert "ep.kt" not in r["list"] and "Phải chuyên tâm" not in r["list"], key
        assert r["counts"] == "" and r["checked"] == "" and r["mode"] == "" and r["total"] == "0", key
        assert r["msg"] and r["disabled"] is False, key
    assert "500" in res["http500"]["msg"]
