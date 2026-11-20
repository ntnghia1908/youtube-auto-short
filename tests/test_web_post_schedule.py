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
from test_web_listen import run_player_js
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
    assert [p["slot_label"] for p in data["posts"]] == ["19/11 9:00 AM", "19/11 8:30 PM"]
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
context.location = {pathname: "/episodes/source00001/posts", hash: ""};
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
    nextVisible: !select("#posts-next").hidden,
    scrolledNextUnposted: scrolled.at(-1) === ui.postsPage.nodes.get("source00001|k02").node,
    remaining: ui.postsPage.groups[0].posts.filter(p => !p.posted).map(p => p.clip_id).sort()}));
})().catch(e => { console.error(e); process.exit(1); });
"""
    result = subprocess.run([NODE, "-e", script, str(APP_JS), "success", "true"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["headings"][-2:] == ["Shorts · Chưa có lịch video", "Shorts · Bài cũ chưa đăng"]
    assert out["legacyLabel"] == "Bài cũ chưa đăng"
    # PST2 Q4: no timed post left -> scroll to the next unposted post in display order (was "Tập kế tiếp").
    assert out["firstScroll"] and out["scrolledNextUnposted"] and out["nextVisible"]
    assert out["remaining"] == ["k02", "k03"] and out["calls"] == 2


def test_anchor_api_roundtrip_tick_and_channel_isolation(web):  # PST2 AC1–3
    client, svc = web
    url = f"/api/episodes/{EID}/posts"
    anchor_url = url + "/anchor"
    payload = {"code": "T1_S01", "slot_at": "2027-05-30T20:30:00+07:00"}
    assert client.post(anchor_url, json=payload).status_code == 401
    login(client)
    other = {"other-playlist": {"code": "T99_KT01", "slot_at": "2027-06-30T13:30:00Z"}}
    schedule.write(svc.times_path, schedule.read(svc.times_path), other)
    before_posts = svc.ctx.posts_path(EID).read_bytes()
    response = client.post(anchor_url, json=payload)
    assert response.status_code == 200
    anchor = response.json()["anchor"]
    assert anchor == {"code": "T1_S01", "slot_at": "2027-05-30T13:30:00Z",
                      "slot_label": "30/05 8:30 PM"}
    data = client.get(url).json()
    assert data["anchor"] == anchor and data["next_episode"] == EID2
    assert [(p["code"], p["slot_group"], p["slot_at"]) for p in data["posts"]] == [
        ("T1_S01", "manual", None), ("T1_S02", "scheduled", "2027-05-31T02:00:00Z")]
    kt = client.get(f"/api/episodes/{EID}.kt/posts").json()
    assert kt["anchor"] == anchor and kt["posts"][0]["slot_at"] == "2027-05-31T08:00:00Z"
    assert svc.ctx.posts_path(EID).read_bytes() == before_posts
    assert client.post(url + "/k02/posted", json={"value": True}).status_code == 200
    assert schedule.read(svc.times_path)[f"{EID}/k02"]["slot_at"] == "2027-05-31T02:00:00Z"
    assert client.post(url + "/k01/posted", json={"value": True}).status_code == 200
    assert "slot_at" not in schedule.read(svc.times_path)[f"{EID}/k01"]
    assert client.post(url + "/k02/posted", json={"value": False}).status_code == 200
    assert client.post(url + "/k01/posted", json={"value": False}).status_code == 200
    assert schedule.read_anchors(svc.times_path)[PID]["code"] == "T1_S01"
    assert client.post(f"/api/episodes/{EID}.kt/posts/anchor", json={}).json() == {"anchor": None}
    assert schedule.read_anchors(svc.times_path) == other
    assert client.get(url).json()["anchor"] is None
    assert client.get(url).json()["posts"][0]["slot_at"] == "2026-11-19T02:00:00Z"


@pytest.mark.parametrize("body", [
    None, [], "wrong", {"code": "T1_S01"}, {"slot_at": "2027-05-30T13:30:00Z"},
    {"code": "bad", "slot_at": "2027-05-30T13:30:00Z"},
    {"code": "T1_S00", "slot_at": "2027-05-30T13:30:00Z"},
    {"code": "T1_S01", "slot_at": "2027-05-30T20:30:00"},
    {"code": "T1_S01", "slot_at": "2027-02-30T20:30:00+07:00"},
    {"code": "T1_S01", "slot_at": None},
    {"code": "T1_S01", "slot_at": 123},
    {"code": "T1_S01", "slot_at": "2027-05-30T13:30:00Z", "extra": True},
])
def test_anchor_api_invalid_payload_is_400_and_does_not_write(web, body):  # PST2 AC1
    client, svc = web
    login(client)
    before = svc.times_path.read_bytes()
    assert client.post(f"/api/episodes/{EID}/posts/anchor", json=body).status_code == 400
    assert svc.times_path.read_bytes() == before


def test_anchor_api_requires_website_playlist_and_manual_posts_are_never_next(web):  # PST2 AC1,3
    client, svc = web
    login(client)
    url = f"/api/episodes/{EID}/posts"
    anchor = {"code": "T99_KT07", "slot_at": "2027-05-30T13:30:00Z"}
    assert client.post(url + "/anchor", json=anchor).status_code == 200
    assert client.get(url).json()["next_episode"] is None
    assert all(p["slot_group"] == "manual" for p in client.get(url).json()["posts"])
    for doc in svc.ctx.playlists.all():
        svc.ctx.playlists.path(doc["playlist_id"]).unlink()
    before = svc.times_path.read_bytes()
    assert client.post(url + "/anchor", json=anchor).status_code == 400
    assert svc.times_path.read_bytes() == before


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("action", ["copy", "tick"])
def test_anchor_ui_scroll_by_time_then_display_order_then_next(action):  # PST2 AC3–4
    script = SCHEDULE_HARNESS.split("(async () => {")[0].replace(
        '{posts: group.posts, next_episode:', '{posts: group.posts, anchor: group.anchor, next_episode:',
    ) + r"""
const anchor = {code: "T1_S01", slot_at: "2027-05-30T13:30:00Z", slot_label: "Chủ nhật 30/05 20:30"};
for (const g of groups) g.anchor = anchor;
shortPosts.unshift({...makePost("k03", null, null), slot_group: "manual"});
shortPosts.unshift({...makePost("k04", null, null), slot_group: "legacy"});
groups[0].view.shorts = shortPosts.map(p => ({clip_id: p.clip_id, status: "rendered"}));
async function tick(key) {
  const card = ui.postsPage.nodes.get(key).node;
  if (process.argv[4] === "copy") await findButton(card, "Sao chép bài").click();
  else {
    const input = card.querySelector(".publish-label").children[0];
    input.checked = true;
    await Promise.all(input.listeners.change.map(f => f()));
  }
  await settle();
}
(async () => {
  ui.renderPostsPage();
  const headings = select("#post-groups").children.slice(1).map(s => s.children[0].children[0].textContent);
  const manualLabel = ui.postsPage.nodes.get("source00001|k03").node.querySelector(".post-slot").textContent;
  await tick("source00001.kt|k01");
  const byTime = scrolled.at(-1) === ui.postsPage.nodes.get("source00001|k01").node;
  await tick("source00001|k01");
  const byDisplay = scrolled.at(-1) === ui.postsPage.nodes.get("source00001|k02").node;
  const visibleWithUnknown = !select("#posts-next").hidden;  // PST1 rule kept: no timed post left
  await tick("source00001|k02");
  const legacyFallback = scrolled.at(-1) === ui.postsPage.nodes.get("source00001|k04").node;
  await tick("source00001|k04");
  console.log(JSON.stringify({headings, manualLabel, byTime, byDisplay, visibleWithUnknown, legacyFallback,
    nextVisible: !select("#posts-next").hidden, nextScroll: scrolled.at(-1) === select("#posts-next"),
    manualUnticked: !ui.postsPage.groups[0].posts.find(p => p.clip_id === "k03").posted, calls: posted.length}));
})().catch(e => { console.error(e); process.exit(1); });
"""
    result = subprocess.run([NODE, "-e", script, str(APP_JS), "success", "true", action],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["headings"][-1] == "Shorts · Đã lên lịch tay (≤ T1_S01)"
    assert out["manualLabel"] == "Đã lên lịch tay"
    assert all(out[key] for key in ("byTime", "byDisplay", "visibleWithUnknown", "legacyFallback",
                                    "nextVisible", "nextScroll", "manualUnticked"))
    assert out["calls"] == 4


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_anchor_ui_set_vietnam_time_clear_and_error_paths():  # PST2 AC1
    script = SCHEDULE_HARNESS.split("(async () => {")[0].replace(
        '{posts: group.posts, next_episode:', '{posts: group.posts, anchor: group.anchor, next_episode:',
    ).replace('if (url.endsWith("/posted")) {', r"""
if (url.endsWith("/anchor")) {
  const payload = JSON.parse(opts.body);
  anchorCalls.push({url, payload});
  if (rejectAnchor) return {ok: false, status: 400, json: async () => ({detail: "invalid anchor"})};
  for (const g of groups) g.anchor = payload.code ? {...payload, slot_label: "Chủ nhật 30/05 20:30"} : null;
  data = {anchor: groups[0].anchor};
} else if (url.endsWith("/posted")) {""") + r"""
const anchorCalls = [];
let rejectAnchor = false;
shortPosts[0].code = "T1_S01";
process.env.TZ = "America/New_York";
(async () => {
  ui.renderPostsPage();
  let card = ui.postsPage.nodes.get("source00001|k01").node;
  await findButton(card, "Đặt mốc").click();
  const editor = card.querySelector(".post-anchor-editor");
  const input = editor.children[1], defaultTime = input.value;
  input.value = "";
  await findButton(editor, "Lưu mốc").click();
  const emptyRejected = anchorCalls.length === 0 && !!editor.children.at(-1).textContent;
  input.value = "2027-05-30T20:30";
  rejectAnchor = true;
  await findButton(editor, "Lưu mốc").click();
  const failed = !editor.hidden && editor.children.at(-1).textContent === "invalid anchor"
    && !findButton(editor, "Lưu mốc").disabled;
  rejectAnchor = false;
  await findButton(editor, "Lưu mốc").click(); await settle();
  const summary = select("#post-groups").children[0];
  const summaryText = summary.children[0].textContent;
  const clear = findButton(summary, "Xóa mốc");
  rejectAnchor = true;
  await clear.click(); await settle();
  const clearFailed = !clear.disabled && select("#posts-msg").textContent === "invalid anchor";
  rejectAnchor = false;
  await clear.click(); await settle();
  console.log(JSON.stringify({defaultTime, emptyRejected, failed, clearFailed, summaryText, anchorCalls,
    cleared: ui.postsPage.groups.every(g => !g.anchor), editorHidden: editor.hidden}));
})().catch(e => { console.error(e); process.exit(1); });
"""
    result = subprocess.run([NODE, "-e", script, str(APP_JS), "success", "true"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["defaultTime"] == "2026-11-19T20:30"
    assert all(out[key] for key in ("emptyRejected", "failed", "clearFailed", "cleared", "editorHidden"))
    assert "T1_S01" in out["summaryText"] and "20:30 (giờ VN)" in out["summaryText"]
    assert out["anchorCalls"] == [
        {"url": f"/api/episodes/{EID}/posts/anchor", "payload":
         {"code": "T1_S01", "slot_at": "2027-05-30T20:30:00+07:00"}} for _ in range(2)] + [
        {"url": f"/api/episodes/{EID}/posts/anchor", "payload": {}} for _ in range(2)]


@pytest.mark.parametrize("anchor_code,expected", [(None, "T1_S01"), ("T1_S01", "T1_S02"), ("T99_KT07", None)])
def test_playlist_next_post_api(web, anchor_code, expected):  # PST2 AC6; ORCHESTRATOR / TestClient
    client, svc = web
    url = f"/api/playlists/{PID}/next-post"
    assert client.get(url).status_code == 401
    login(client)
    if anchor_code:
        schedule.write(svc.times_path, schedule.read(svc.times_path), {
            PID: {"code": anchor_code, "slot_at": "2027-05-30T13:30:00Z"}})
    response = client.get(url)
    assert response.status_code == 200
    post = response.json()["post"]
    if expected is None:
        assert post is None
    else:
        assert post["code"] == expected
        assert post == {"episode_id": EID, "clip_id": "k01" if not anchor_code else "k02", "code": expected,
                        **schedule.slot_fields("2026-11-19T02:00:00Z" if not anchor_code else "2027-05-31T02:00:00Z")}
    assert client.get("/api/playlists/PLunknown001/next-post").status_code == 404


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("mode", ["target", "empty", "error"])
def test_next_post_buttons_prefetch_labels_then_refetch_exact_post_on_click(mode):  # PST2 AC6,10
    # Stub unrelated playlist initializers only in the VM; run the real initPlaylist button binding.
    script = SCHEDULE_HARNESS.split("(async () => {")[0].replace(
        "return { postCard, postBadges, copyTitleButton, postsPage, renderPostsPage, initIndex,",
        "initPlKinds = initHashtags = initSeries = initDoc = initLinkPlaylists = initDownloadQueue = "
        "loadPlaylist = checkDisk = () => {}; "
        "return { postCard, postBadges, copyTitleButton, postsPage, renderPostsPage, loadPlaylists, initIndex,",
    ) + r"""
const requests = [], busy = [];
let phase = "labels";
context.document.querySelectorAll = () => [];
context.fetch = async url => {
  requests.push(url);
  if (url === "/api/playlists") return {ok: true, status: 200, json: async () => ({playlists: [
    {id: "PLsource00001", title: "Bộ một", processed: 1, count: 2},
    {id: "PLsource00002", title: "Bộ hai", processed: 0, count: 1},
  ]})};
  if (phase === "labels") return {ok: true, status: 200, json: async () => ({
    [url.endsWith("next-listen") ? "item" : "post"]: {episode_id: "stale000001", clip_id: "k99", code: "T99_S99"},
  })};
  busy.push(activeButton.disabled);
  return {ok: mode !== "error", status: mode === "error" ? 422 : 200, json: async () =>
    mode === "error" ? {detail: "Không đọc được giờ bài đăng"} : {post: mode === "empty" ? null :
      {episode_id: "source00001.kt", clip_id: "k02", code: "T1_KT02", slot_at: null, slot_label: null}}};
};
let activeButton;
(async () => {
  await ui.loadPlaylists();
  const rows = select("#playlists").children;
  const buttons = rows.map(row => row.children[1]);
  const outsideLinks = buttons.every((b, i) => b.parent === rows[i] && b.parent.tag === "li"
    && rows[i].children[0].tag === "a");
  context.location = {pathname: "/playlists/PLsource00002", hash: "", href: "/playlists/PLsource00002"};
  ui.initPlaylist();
  await settle();
  const backgroundRequests = requests.slice();
  const labels = [buttons[0].textContent, select("#pl-next-post").textContent];
  phase = "click";
  activeButton = buttons[0];
  await activeButton.click();
  const homeHref = context.location.href, homeEnabled = !activeButton.disabled;
  context.location.href = "/playlists/PLsource00002";
  activeButton = select("#pl-next-post");
  await activeButton.click();
  console.log(JSON.stringify({outsideLinks, backgroundRequests, labels, requests, busy, homeHref,
    playlistHref: context.location.href, enabled: homeEnabled && !activeButton.disabled, alerts}));
})().catch(e => { console.error(e); process.exit(1); });
"""
    result = subprocess.run([NODE, "-e", script, str(APP_JS), mode, "true"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["outsideLinks"] and out["enabled"] and out["busy"] == [True, True]
    background = ["/api/playlists", f"/api/playlists/{PID}/next-post", f"/api/playlists/{PID}/next-listen",
                  "/api/playlists/PLsource00002/next-post", "/api/playlists/PLsource00002/next-listen"]
    background += background[-2:]
    assert out["backgroundRequests"] == background
    assert out["labels"] == ["Bài đăng tiếp T99_S99 →"] * 2
    assert out["requests"] == background + [f"/api/playlists/{PID}/next-post", "/api/playlists/PLsource00002/next-post"]
    assert out["homeHref"] == out["playlistHref"] == (
        "/episodes/source00001.kt/posts#post-k02" if mode == "target" else "/playlists/PLsource00002")
    assert out["alerts"] == ([] if mode == "target" else
                             ["Hết bài cần đăng" if mode == "empty" else "Không đọc được giờ bài đăng"] * 2)
    assert 'id="pl-next-post" class="btn small"' in (STATIC_DIR / "playlist.html").read_text()


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("episode,hash_value,target", [
    (EID, "#post-k01", EID + "|k01"), (EID, "#post-k02", EID + "|k02"),
    (EID + ".kt", "#post-k01", EID + ".kt|k01"),
    (EID + ".kt", "#post-k02", EID + "|k01"),  # hash exists only in the other episode
    (EID, "#post-missing", EID + "|k01"), (EID, "", EID + "|k01"),
])
def test_posts_initial_hash_scroll_is_scoped_and_runs_once(episode, hash_value, target):  # PST2 AC6
    script = SCHEDULE_HARNESS.split("(async () => {")[0].replace(
        "postsPage, renderPostsPage, initIndex,",
        "postsPage, renderPostsPage, loadPostsPage, setEpisodeForTest: id => { episodeId = id; }, initIndex,",
    ) + r"""
context.location.hash = process.argv[4];
ui.setEpisodeForTest(process.argv[5]);
ktPosts[0].slot_at = "2026-11-20T08:00:00Z";  // earliest slot is Short k01; KT hash must still win
(async () => {
  await ui.loadPostsPage();
  const expected = ui.postsPage.nodes.get(process.argv[6]).node;
  const exact = scrolled.length === 1 && scrolled[0] === expected;
  context.location.hash = "#post-k02";
  ui.renderPostsPage();
  await ui.loadPostsPage();
  console.log(JSON.stringify({exact, count: scrolled.length}));
})().catch(e => { console.error(e); process.exit(1); });
"""
    result = subprocess.run([NODE, "-e", script, str(APP_JS), "success", "true", hash_value, episode, target],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"exact": True, "count": 1}


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("mode", ["target", "empty", "error"])
def test_listen_resume_buttons_prefetch_labels_then_refetch_without_reading_position(mode):  # PST2 AC8,10
    script = SCHEDULE_HARNESS.split("(async () => {")[0].replace(
        "return { postCard, postBadges, copyTitleButton, postsPage, renderPostsPage, initIndex,",
        "initPlKinds = initHashtags = initSeries = initDoc = initLinkPlaylists = initDownloadQueue = "
        "loadPlaylist = checkDisk = () => {}; "
        "return { postCard, postBadges, copyTitleButton, postsPage, renderPostsPage, loadPlaylists, initIndex,",
    ) + r"""
const requests = [], positionReads = [];
let phase = "labels";
context.document.querySelectorAll = () => [];
context.fetch = async url => {
  requests.push(url);
  if (url === "/api/playlists") return {ok: true, status: 200, json: async () => ({playlists: [
    {id: "PLsource00001", title: "Bộ một", count: 2}, {id: "PLsource00002", title: "Bộ hai", count: 1},
  ]})};
  if (phase === "labels") return {ok: true, status: 200, json: async () => ({
    [url.endsWith("next-listen") ? "item" : "post"]: {episode_id: "stale000001", clip_id: "k99", code: "T99_KT99"},
  })};
  return {ok: mode !== "error", status: mode === "error" ? 422 : 200, json: async () => mode === "error"
    ? {detail: "Không đọc được bài nghe"} : {item: mode === "empty" ? null :
      {episode_id: url.includes("PLsource00001") ? "source00001.kt" : "source00002", clip_id: "k02", code: "T2_S02"}}};
};
const get = context.localStorage.getItem;
context.localStorage.getItem = key => {
  if (key.startsWith("auto-short-listen-position:")) {
    positionReads.push(key); throw Error("button must use the server's watched state");
  }
  return get(key);
};
(async () => {
  await ui.loadPlaylists();
  const row = select("#playlists").children[0];
  const listen = row.children[2];
  const outsideLink = listen.parent === row && row.children[1].tag === "button";
  context.location = {pathname: "/playlists/PLsource00002", href: "/playlists/PLsource00002", hash: ""};
  ui.initPlaylist();
  await settle();
  const beforeClick = requests.slice();
  const labels = [listen.textContent, select("#pl-listen-resume").textContent];
  phase = "click";
  await listen.click();
  const homeHref = context.location.href;
  context.location.href = "/playlists/PLsource00002";
  await select("#pl-listen-resume").click();
  console.log(JSON.stringify({outsideLink, beforeClick, labels, requests, positionReads, homeHref, playlistHref: context.location.href, alerts}));
})().catch(e => { console.error(e); process.exit(1); });
"""
    result = subprocess.run([NODE, "-e", script, str(APP_JS), mode, "true"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    background = ["/api/playlists", f"/api/playlists/{PID}/next-post", f"/api/playlists/{PID}/next-listen",
                  "/api/playlists/PLsource00002/next-post", "/api/playlists/PLsource00002/next-listen"]
    background += background[-2:]
    assert out["outsideLink"] and out["beforeClick"] == background
    assert out["labels"] == ["Nghe tiếp T99_KT99 →"] * 2
    assert out["positionReads"] == []
    assert out["requests"] == background + [f"/api/playlists/{PID}/next-listen", "/api/playlists/PLsource00002/next-listen"]
    if mode == "target":
        assert out["homeHref"] == "/episodes/source00001.kt?resume=1&clip=k02"
        assert out["playlistHref"] == "/episodes/source00002?resume=1&clip=k02" and out["alerts"] == []
    else:
        assert out["homeHref"] == out["playlistHref"] == "/playlists/PLsource00002"
        assert out["alerts"] == ["Đã nghe hết bộ này" if mode == "empty" else "Không đọc được bài nghe"] * 2
    assert 'id="pl-listen-resume" class="btn small"' in (STATIC_DIR / "playlist.html").read_text()


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("mode", ["target", "empty", "error"])
def test_next_button_labels_load_in_parallel_after_render_without_blocking(mode):  # PST2 AC10
    script = SCHEDULE_HARNESS.split("(async () => {")[0].replace(
        "return { postCard, postBadges, copyTitleButton, postsPage, renderPostsPage, initIndex,",
        "initPlKinds = initHashtags = initSeries = initDoc = initLinkPlaylists = initDownloadQueue = "
        "loadPlaylist = checkDisk = () => {}; "
        "return { postCard, postBadges, copyTitleButton, postsPage, renderPostsPage, loadPlaylists, initIndex,",
    ) + r"""
const pending = [];
context.document.querySelectorAll = () => [];
context.fetch = async url => {
  if (url === "/api/playlists") return {ok: true, status: 200, json: async () => ({playlists: [
    {id: "PLsource00001", title: "Bộ một", count: 2}, {id: "PLsource00002", title: "Bộ hai", count: 1},
  ]})};
  return new Promise(resolve => pending.push({url, resolve, renderedRows: select("#playlists").children.length}));
};
(async () => {
  let rendered = false;
  ui.loadPlaylists().then(() => {rendered = true;});
  await settle();
  const rows = select("#playlists").children;
  const homeButtons = rows.flatMap(row => row.children.slice(1));
  const post = select("#pl-next-post"), listen = select("#pl-listen-resume");
  post.textContent = "Bài đăng tiếp →"; listen.textContent = "Nghe tiếp →"; // server-rendered HTML
  context.location = {pathname: "/playlists/PLsource00002", href: "/playlists/PLsource00002", hash: ""};
  ui.initPlaylist();
  const buttons = [...homeButtons, post, listen];
  const defaults = buttons.map(b => ({text: b.textContent, disabled: !!b.disabled}));
  const parallel = pending.length === 6;
  for (const call of pending) call.resolve({ok: mode !== "error", status: mode === "error" ? 422 : 200,
    json: async () => mode === "error" ? {detail: "Không tải được nhãn"} : {
      [call.url.endsWith("next-listen") ? "item" : "post"]: mode === "empty" ? null :
        {code: call.url.endsWith("next-listen") ? "T36_KT04" : "T35_S11"},
    }});
  await settle();
  console.log(JSON.stringify({rendered, rows: rows.length, parallel, defaults, alerts,
    renderedBeforeFetch: pending.every(call => call.renderedRows === 2),
    results: buttons.map(b => ({text: b.textContent, disabled: !!b.disabled}))}));
})().catch(e => { console.error(e); process.exit(1); });
"""
    result = subprocess.run([NODE, "-e", script, str(APP_JS), mode, "true"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["rendered"] and out["rows"] == 2 and out["parallel"] and out["renderedBeforeFetch"]
    assert out["alerts"] == []
    defaults = [{"text": text, "disabled": False} for text in ("Bài đăng tiếp →", "Nghe tiếp →")] * 3
    assert out["defaults"] == defaults
    if mode == "error":
        assert out["results"] == defaults
    else:
        labels = ("Bài đăng tiếp T35_S11 →", "Nghe tiếp T36_KT04 →") if mode == "target" else ("Hết bài đăng", "Đã nghe hết")
        assert out["results"] == [{"text": text, "disabled": mode == "empty"} for text in labels] * 3


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("mode", ["play", "blocked", "normal", "missing", "broken", "negative", "stale", "favorites", "room"])
def test_listen_url_resume_selects_saved_identity_and_keeps_old_modes(run_player_js, mode):  # PST2 AC7
    run_player_js(r'''
const mode = MODE_VALUE, replaced = [];
location.pathname = mode === "favorites" ? "/playlists/PLtest/favorites" : mode === "room" ? "/watch" : "/episodes/ep1";
location.search = mode === "normal" ? "?keep=1" : "?keep=1&resume=1";
location.hash = "#retained";
global.history = {state: {keep: true}, replaceState: (...args) => replaced.push(args)};
sourceItems = [item(1, 1), item(2, 1), item(2, 2, "khaithi")];
storage.set("auto-short-listen-filter", '"short"');
const saved = {episode_id: mode === "stale" ? "deleted" : "ep2.kt", clip_id: "k2", position: mode === "negative" ? -1 : 23.5};
const key = "auto-short-listen-position:PLtest" + (mode === "favorites" ? ":fav" : "");
if (mode !== "missing") storage.set(key, mode === "broken" ? "{" : JSON.stringify(saved));
const originalPlay = Element.prototype.play;
if (mode === "blocked") Element.prototype.play = function() {
  this.plays++; return Promise.reject(Object.assign(new Error("autoplay blocked"), {name: "NotAllowedError"}));
};
await boot();
tick(5000);  // metadata may arrive late; resume must seek to the saved second, without advancing its clock
await metadata();
const automatic = ["play", "blocked"].includes(mode);
if (automatic || mode === "favorites") {
  assert.equal(activePlayer.state.episode_id, "ep2.kt"); assert.equal(activePlayer.state.clip_id, "k2");
  assert.equal(activePlayer.position(), 23.5);
  assert.equal(storage.get("auto-short-listen-filter"), '"both"');
  assert.equal(activePlayer.media().paused, mode !== "play");
  if (mode === "blocked") {
    assert.ok(!$("play").hidden); assert.ok(activePlayer.state.paused);
    tick(10000); await visibility(true); await visibility(false);
    assert.equal(activePlayer.position(), 23.5);
    Element.prototype.play = originalPlay;
    await $("play").fire("click"); await settled();
    assert.ok(!activePlayer.media().paused); assert.equal(activePlayer.position(), 23.5);
  }
} else if (mode !== "room") {
  assert.equal(activePlayer.state.episode_id, "ep1"); assert.equal(activePlayer.position(), 0);
  assert.ok(activePlayer.media().paused);
}
if (!["normal", "favorites", "room"].includes(mode)) {
  assert.ok($("resume").hidden);
  assert.deepEqual(replaced, [[{keep: true}, "", "/episodes/ep1?keep=1#retained"]]);
  if (automatic) assert.ok(scrolls.some(([node]) => node === $("video")));
} else {
  assert.equal(replaced.length, 0);
  if (mode !== "room") assert.ok(!$("resume").hidden);
  if (mode === "normal") {
    await $("resume").fire("click"); await metadata();
    assert.equal(activePlayer.state.episode_id, "ep2.kt"); assert.equal(activePlayer.position(), 23.5);
    assert.ok(!activePlayer.media().paused); assert.ok($("resume").hidden);
  }
}
'''.replace("MODE_VALUE", json.dumps(mode)))


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("query,tab", [("?resume=1", "listen"), ("?resume=0", "manage"), ("", "manage")])
def test_listen_url_resume_opens_listen_tab_without_changing_normal_preference(query, tab):  # PST2 AC7
    script = SCHEDULE_HARNESS.split("(async () => {")[0].replace(
        "return { postCard, postBadges, copyTitleButton, postsPage, renderPostsPage, initIndex,",
        "initAddDialog = refreshEpisode = checkDisk = () => {}; loadUi = () => Promise.resolve(); "
        "return { postCard, postBadges, copyTitleButton, postsPage, renderPostsPage, initIndex,",
    ) + r"""
context.document.querySelectorAll = () => [];
context.document.dispatchEvent = () => {};
context.CustomEvent = class {constructor(type, value) {this.type = type; this.detail = value.detail;}};
context.URLSearchParams = URLSearchParams;
context.location.search = process.argv[4];
storage.set("auto-short-episode-tab", "manage");
for (const name of ["listen", "manage"]) select("#episode-tab-" + name).classList = {toggle() {}};
ui.initEpisode();
console.log(JSON.stringify({listenHidden: select("#episode-listen").hidden,
  manageHidden: select("#episode-manage").hidden, savedTab: storage.get("auto-short-episode-tab")}));
"""
    result = subprocess.run([NODE, "-e", script, str(APP_JS), "success", "true", query],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"listenHidden": tab != "listen", "manageHidden": tab == "listen", "savedTab": tab}
