"""PST1 API + real JS handlers. ORCHESTRATOR runs these outside the socket sandbox."""
from __future__ import annotations

import json
import subprocess
from dataclasses import replace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from auto_short.post import schedule, store
from auto_short.web.app import STATIC_DIR
from auto_short.workspace import atomic_write_json
from test_post_links import EID, EID2, PID, SHORTS, seed, service
from test_web_post_doc_gate import APP_JS, HARNESS as COPY_HARNESS, NODE
from web_helpers import login, make_app

NOW = "2026-11-19T01:50:00Z"


@pytest.fixture
def web(service, monkeypatch):
    _, ctx, _ = service
    cfg = replace(ctx.config, post=replace(ctx.config.post, codex_auto=False))
    app = make_app(cfg, post_preflight=lambda c: None, post_compose=lambda *a, **kw: None)
    svc = app.state.post_links
    monkeypatch.setattr(svc.ctx, "post_now", lambda: NOW)
    for eid, cid in ((EID, "k01"), (EID, "k02"), (EID + ".kt", "k01"), (EID2, "k01")):
        seed(ctx, eid, cid, posted=False)
    playlist = ctx.playlists.load(PID)
    playlist["entries"].append({"video_id": EID2})
    atomic_write_json(ctx.playlists.path(PID), playlist)
    ctx.playlists.set_link_playlist(PID, SHORTS)
    for eid in (EID2, EID2 + ".kt"):
        atomic_write_json(cfg.workspace.dir / eid / "titles.json", {"header": {"fields": {"episode": "2"}}})
    times = {f"{EID}/k01": {"video_id": "youtube0001", "video_at": "2026-11-19T00:00:00Z"},
             f"{EID}/k02": {"video_id": "youtube0002", "video_at": "2026-11-19T02:00:01Z"},
             f"{EID}.kt/k01": {"video_id": "youtube0003", "video_at": "2026-11-19T01:00:00Z"},
             f"{EID2}/k01": {"video_id": "youtube0004", "video_at": "2026-11-20T00:00:00Z"}}
    schedule.write(svc.times_path, times)
    with TestClient(app, follow_redirects=False) as client:
        yield client, svc


def test_posts_api_adds_slots_and_next_episode_preserving_old_fields(web):  # AC4–5
    client, svc = web
    url = f"/api/episodes/{EID}/posts"
    assert client.get(url).status_code == 401
    assert client.post(url + "/k01/posted", json={"value": True}).status_code == 401
    login(client)
    before = store.read_posts(svc.ctx.posts_path(EID), EID)
    response = client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert data["post_error"] is None and data["next_episode"] == EID2
    assert [p["slot_at"] for p in data["posts"]] == ["2026-11-19T02:00:00Z", "2026-11-19T13:30:00Z"]
    assert [p["slot_label"] for p in data["posts"]] == ["Thứ 5 19/11 09:00", "Thứ 5 19/11 20:30"]
    for raw, view in zip(before["posts"], data["posts"]):
        for field in ("clip_id", "paragraphs", "origin", "image", "link", "posted_at"):
            assert view[field] == raw[field]
        assert view["posted"] is False and view["chars"] == len(view["text"]) and "stale" in view
    assert store.read_posts(svc.ctx.posts_path(EID), EID) == before
    kt = client.get(f"/api/episodes/{EID}.kt/posts").json()
    assert kt["posts"][0]["slot_at"] == "2026-11-19T08:00:00Z" and kt["next_episode"] == EID2


def test_tick_saves_proposal_untick_removes_it_and_legacy_ticks_reserve_nothing(web, monkeypatch):  # AC3
    client, svc = web
    login(client)
    url = f"/api/episodes/{EID}/posts"
    proposal = client.get(url).json()["posts"][0]["slot_at"]
    assert client.post(url + "/k01/posted", json={"value": True}).json() == {
        "clip_id": "k01", "posted": True, "posted_at": NOW}
    assert schedule.read(svc.times_path)[f"{EID}/k01"]["slot_at"] == proposal
    monkeypatch.setattr(svc.ctx, "post_now", lambda: "2026-11-20T10:00:00Z")
    assert client.get(url).json()["posts"][0]["slot_at"] == proposal
    assert client.post(url + "/k01/posted", json={"value": True}).status_code == 200
    assert schedule.read(svc.times_path)[f"{EID}/k01"]["slot_at"] == proposal
    assert client.post(url + "/k01/posted", json={"value": False}).status_code == 200
    saved = schedule.read(svc.times_path)[f"{EID}/k01"]
    assert "slot_at" not in saved and saved["video_at"] == "2026-11-19T00:00:00Z"
    assert client.get(url).json()["posts"][0]["slot_at"] == "2026-11-20T13:30:00Z"
    # A tick made before PST1 has no saved slot, including after an idempotent tick.
    doc = store.read_posts(svc.ctx.posts_path(EID), EID)
    store.write(svc.ctx.posts_path(EID), store.with_posted(doc, ["k01", "k02"], "k01", True, now=NOW))
    monkeypatch.setattr(svc.ctx, "post_now", lambda: NOW)
    assert client.post(url + "/k01/posted", json={"value": True}).status_code == 200
    assert client.get(url).json()["posts"][0]["slot_at"] is None
    assert "slot_at" not in schedule.read(svc.times_path)[f"{EID}/k01"]
    assert client.get(f"/api/episodes/{EID}.kt/posts").json()["posts"][0]["slot_at"] == proposal


@pytest.mark.parametrize("without_playlist", [False, True])
def test_posts_without_video_time_or_playlist_have_no_slot(web, without_playlist):  # AC3–4
    client, svc = web
    login(client)
    if without_playlist:
        for doc in svc.ctx.playlists.all():
            svc.ctx.playlists.path(doc["playlist_id"]).unlink()
    else:
        times = schedule.read(svc.times_path)
        times[f"{EID}/k01"]["video_at"] = None
        schedule.write(svc.times_path, times)
    url = f"/api/episodes/{EID}/posts"
    post = client.get(url).json()["posts"][0]
    assert post["slot_at"] is None and post["slot_label"] is None
    assert client.post(url + "/k01/posted", json={"value": True}).status_code == 200
    assert "slot_at" not in schedule.read(svc.times_path)[f"{EID}/k01"]
    if without_playlist:
        assert client.get(url).json()["next_episode"] is None
        svc.ctx.posts_path(EID).unlink()
        assert client.get(url).json() == {"posts": [], "post_error": None}  # CP8.15 empty response


@pytest.mark.parametrize("already_posted", [False, True])
def test_legacy_api_groups_next_episode_and_tick(web, already_posted):  # AC6
    client, svc = web
    login(client)
    seed(svc.ctx, EID2, "k01", posted=already_posted)
    seed(svc.ctx, EID2, "k02", posted=False)
    times = schedule.read(svc.times_path)
    for eid in (EID, EID + ".kt", EID2):
        times[f"{eid}/k01"]["video_at"] = "2026-11-18T16:59:59Z"
    times[f"{EID}/k01"]["slot_at"] = "2026-11-24T13:30:00Z"  # stale unticked state
    times[f"{EID}/k02"]["video_at"] = None
    if already_posted:
        times[f"{EID2}/k01"]["slot_at"] = "2026-11-19T02:00:00Z"
    times[f"{EID2}/k02"] = {"video_id": "youtube0005", "video_at": "2026-11-24T13:30:00Z"}
    schedule.write(svc.times_path, times)
    before = svc.ctx.posts_path(EID).read_bytes(), svc.times_path.read_bytes()
    url = f"/api/episodes/{EID}/posts"
    data = client.get(url).json()
    assert data["next_episode"] == EID2
    assert [(p["slot_group"], p["slot_at"], p["slot_label"]) for p in data["posts"]] == [
        ("legacy", None, None), ("unscheduled", None, None)]
    other = client.get(f"/api/episodes/{EID2}/posts").json()["posts"]
    assert other[0]["slot_group"] == ("scheduled" if already_posted else "legacy")
    assert other[0]["slot_at"] == ("2026-11-19T02:00:00Z" if already_posted else None)
    assert other[1]["slot_group"] == "scheduled" and other[1]["slot_at"] == "2026-11-24T13:30:00Z"
    assert (svc.ctx.posts_path(EID).read_bytes(), svc.times_path.read_bytes()) == before
    assert client.post(url + "/k01/posted", json={"value": True}).status_code == 200
    assert "slot_at" not in schedule.read(svc.times_path)[f"{EID}/k01"]
    assert client.get(url).json()["posts"][0]["slot_at"] is None
    times = schedule.read(svc.times_path)
    times[f"{EID2}/k02"]["video_at"] = None
    schedule.write(svc.times_path, times)
    assert client.get(url).json()["next_episode"] is None  # an unticked old episode is never next


# Reuse the existing POSTCOPY1 DOM / clipboard harness; add a resolving local API and scrolling.
SCHEDULE_HARNESS = COPY_HARNESS.split("const ui = context.ui, origin =")[0].replace(
    "postCard, postBadges, copyTitleButton, initIndex,",
    "postCard, postBadges, copyTitleButton, postsPage, renderPostsPage, initIndex,",
) + r"""
const ui = context.ui, mode = process.argv[2], nodes = new Map(), scrolled = [];
El.prototype.scrollIntoView = function() { scrolled.push(this); };
function select(sel) {
  if (!nodes.has(sel)) { const n = new El("div"); n.dataset = {}; nodes.set(sel, n); }
  return nodes.get(sel);
}
context.document.querySelector = select;
context.clearTimeout = () => {};
const makePost = (clip, at, label) => ({ clip_id: clip, origin: "manual", text: "Bài đầy đủ",
  paragraphs: ["Nội dung."], image: "picture.png", chars: 11, posted: false,
  slot_at: at, slot_label: label });
const shortPosts = [makePost("k01", "2026-11-19T13:30:00Z", "Thứ 5 19/11 20:30"),
  makePost("k02", null, null)];
const ktPosts = [makePost("k01", "2026-11-19T08:00:00Z", "Thứ 5 19/11 15:00")];
const makeGroup = (id, label, posts) => ({ id, label, posts, nextEpisode: "next0000001",
  view: { title: "Tập 1", kind: id.endsWith(".kt") ? "khaithi" : "short", shorts:
    posts.map(p => ({clip_id: p.clip_id, status: "rendered", title: {text: "Tiêu đề"}})) } });
const groups = [makeGroup("source00001", "Shorts", shortPosts), makeGroup("source00001.kt", "Khai thị", ktPosts)];
ui.postsPage.vid = "source00001";
ui.postsPage.groups = groups;
ui.postsPage.autoTried = true;
context.fetch = async (url, opts = {}) => {
  let data;
  if (url.endsWith("/posted")) {
    posted.push({ url, body: JSON.parse(opts.body) });
    if (mode === "tick-fail") return {ok: false, status: 422, json: async () => ({detail: "tick failed"})};
    const parts = url.split("/"), group = groups.find(g => g.id === parts[3]);
    const p = group.posts.find(p => p.clip_id === parts[5]);
    p.posted = JSON.parse(opts.body).value; p.posted_at = p.posted ? "now" : null;
    data = {clip_id: p.clip_id, posted: p.posted, posted_at: p.posted_at};
  } else if (url === "/api/posts/codex") data = { remaining: 0, enabled: false };
  else {
    const parts = url.split("/"), group = groups.find(g => g.id === parts[3]);
    if (!group) throw Error("unexpected URL " + url);
    data = url.endsWith("/codex") ? {} : url.endsWith("/posts")
      ? {posts: group.posts, next_episode: group.nextEpisode, post_error: null} : group.view;
  }
  return {ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(data))};
};
let alerts = [];
context.alert = msg => alerts.push(msg);
const findButton = (node, label) => node.querySelectorAll(".btn").find(b => b.textContent === label);
async function settle() { for (let n = 0; n < 80; n++) await Promise.resolve(); }
(async () => {
  ui.renderPostsPage();
  const initial = ui.postsPage.nodes.get("source00001.kt|k01").node;
  const label = initial.querySelector(".post-slot").textContent;
  await findButton(initial, "Sao chép bài").click(); await settle();
  const after = ui.postsPage.nodes.get("source00001.kt|k01").node;
  const first = {dim: after.className.includes("post-posted"),
    scrolledNext: scrolled[0] === ui.postsPage.nodes.get("source00001|k01").node,
    nextHidden: select("#posts-next").hidden};
  if (mode === "success") {
    // Recopying a ticked card must not send another tick.
    await findButton(after, "Sao chép bài").click(); await settle();
    for (const key of ["source00001|k01", "source00001|k02"]) {
      await findButton(ui.postsPage.nodes.get(key).node, "Sao chép bài").click(); await settle();
    }
  }
  console.log(JSON.stringify({label, first, calls: posted.length, alerts,
    fallback: initial.querySelectorAll(".copy-fallback").length,
    nextHidden: select("#posts-next").hidden, nextHref: select("#posts-next").href,
    scrolledButton: scrolled.at(-1) === select("#posts-next"),
    unknownLast: select("#post-groups").children.at(-1).children[0].children[0].textContent}));
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("mode,copy_ok", [("success", True), ("copy-fail", False), ("tick-fail", True)])
def test_posts_ui_copy_dim_scroll_next_and_failure_paths(mode, copy_ok):  # AC4–5
    result = subprocess.run([NODE, "-e", SCHEDULE_HARNESS, str(APP_JS), mode, json.dumps(copy_ok)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["label"] == "Thứ 5 19/11 15:00 (giờ VN)"
    assert "Chưa có lịch video" in out["unknownLast"]
    assert out["first"] == {"dim": mode == "success", "scrolledNext": mode == "success", "nextHidden": True}
    assert out["calls"] == (3 if mode == "success" else int(mode == "tick-fail"))
    assert out["fallback"] == int(not copy_ok)
    assert out["alerts"] == (["tick failed"] if mode == "tick-fail" else [])
    assert out["nextHidden"] is (mode != "success")
    if mode == "success":
        assert out["nextHref"] == "/episodes/next0000001/posts" and out["scrolledButton"]
    assert 'id="posts-next"' in (STATIC_DIR / "posts.html").read_text()
    assert ".post-card.post-posted" in (STATIC_DIR / "style.css").read_text()


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_legacy_ui_group_last_and_copy_scroll_skips_backlog():  # AC6
    script = SCHEDULE_HARNESS.split("(async () => {")[0].replace(
        'const groups = [',
        'shortPosts.unshift({...makePost("k03", null, null), slot_group: "legacy"});\nconst groups = [',
    ) + r"""
(async () => {
  ui.renderPostsPage();
  const sections = select("#post-groups").children;
  const headings = sections.map(s => s.children[0].children[0].textContent);
  const oldCard = ui.postsPage.nodes.get("source00001|k03").node;
  const legacyLabel = oldCard.querySelector(".post-slot").textContent;
  await findButton(ui.postsPage.nodes.get("source00001.kt|k01").node, "Sao chép bài").click(); await settle();
  const firstScroll = scrolled.at(-1) === ui.postsPage.nodes.get("source00001|k01").node;
  await findButton(ui.postsPage.nodes.get("source00001|k01").node, "Sao chép bài").click(); await settle();
  console.log(JSON.stringify({headings, legacyLabel, firstScroll, calls: posted.length,
    nextVisible: !select("#posts-next").hidden, scrolledButton: scrolled.at(-1) === select("#posts-next"),
    remaining: ui.postsPage.groups[0].posts.filter(p => !p.posted).map(p => p.clip_id).sort()}));
})().catch(e => { console.error(e); process.exit(1); });
"""
    result = subprocess.run([NODE, "-e", script, str(APP_JS), "success", "true"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["headings"][-2:] == ["Shorts · Chưa có lịch video", "Shorts · Bài cũ chưa đăng"]
    assert out["legacyLabel"] == "Bài cũ chưa đăng"
    assert out["firstScroll"] and out["scrolledButton"] and out["nextVisible"]
    assert out["remaining"] == ["k02", "k03"] and out["calls"] == 2
