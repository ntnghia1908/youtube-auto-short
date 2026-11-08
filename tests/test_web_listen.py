"""LISTEN1: file-only queue assembly and authenticated read endpoint."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_short.compilation import Item, store
from auto_short.review.logic import empty_review
from auto_short.web.listen import playlist_listen
from web_helpers import login, make_app, write_episode

PID = "PLlisten0001"
FIRST, SECOND, THIRD = "youtube0001", "youtube0002", "youtube0003"


def document():
    return {"playlist_id": PID, "title": "Kinh thử", "entries": [
        {"index": 2, "video_id": SECOND, "title": "Tập hai", "available": True},
        {"index": 1, "video_id": FIRST, "title": "Tập một", "available": True},
        {"index": 3, "video_id": THIRD, "title": "Chưa render", "available": True},
        {"index": 4, "video_id": "unavailable", "title": "Ẩn", "available": False},
    ]}


@pytest.fixture
def library(cfg):
    # Clip ids deliberately oppose manifest order; never sort them lexically.
    write_episode(cfg, FIRST, clips=("k09", "k01"), titles={"k09": "Chữ trong file"}, extra_shorts=[
        {"clip_id": "k10", "status": "skipped", "skip_reason": "rejected"},
        {"clip_id": "k11", "status": "skipped", "skip_reason": "untitled"},
    ])
    write_episode(cfg, FIRST + ".kt", clips=("k03", "k02"))
    write_episode(cfg, SECOND, clips=("k05",))
    write_episode(cfg, "unavailable", clips=("k01",))
    folder = Path(cfg.workspace.dir) / "_playlists"
    folder.mkdir(parents=True)
    (folder / (PID + ".json")).write_text(json.dumps(document()), encoding="utf-8")
    return cfg


def test_queue_order_fields_favorites_and_no_khaithi(library):  # AC1,2
    result = playlist_listen(library, document(), [Item(FIRST, "k09"), Item(FIRST + ".kt", "k02")])
    assert result["playlist_id"] == PID and result["title"] == "Kinh thử"
    items = result["items"]
    assert [(i["episode_id"], i["clip_id"]) for i in items] == [
        (FIRST, "k09"), (FIRST, "k01"), (FIRST + ".kt", "k03"), (FIRST + ".kt", "k02"), (SECOND, "k05")]
    assert [i["kind"] for i in items] == ["short", "short", "khaithi", "khaithi", "short"]
    assert [i["ep_index"] for i in items] == [1, 1, 1, 1, 2]
    assert items[2]["base_episode_id"] == FIRST and items[2]["ep_title"] == "Tập một"
    assert items[0]["title"] == "Chữ trong file" and items[0]["duration"] == 60.0
    assert items[0]["video_url"] == f"/files/{FIRST}/k09.mp4?v={'0' * 12}"
    assert all("audio_url" not in item for item in items)
    assert items[0]["fav"] == dict(playlist_id=PID, episode_id=FIRST, clip="k09", favorite=True)
    assert [i["fav"]["favorite"] for i in items] == [True, False, False, True, False]


def test_review_rejected_current_candidate_only(library):  # AC1: deletion before render commits
    review = empty_review(FIRST)
    review["rejected"] = [{"clip_id": "k09", "candidate_id": "c00001"},
                          {"clip_id": "k01", "candidate_id": "stale-candidate"}]
    (Path(library.workspace.dir) / FIRST / "review.json").write_text(json.dumps(review))
    items = playlist_listen(library, document(), [])["items"]
    assert [(i["episode_id"], i["clip_id"]) for i in items][:1] == [(FIRST, "k01")]
    assert not any(i["episode_id"] == FIRST and i["clip_id"] == "k09" for i in items)
    review = empty_review(FIRST + ".kt")
    review["rejected"] = [{"clip_id": "k03", "candidate_id": "c00001"},
                          {"clip_id": "k02", "candidate_id": "c00002"}]
    (Path(library.workspace.dir) / (FIRST + ".kt") / "review.json").write_text(json.dumps(review))
    assert all(i["kind"] == "short" for i in playlist_listen(library, document(), [])["items"])


def test_released_short_uses_episode_url_without_resolving_storage(library, monkeypatch):
    from auto_short.web import episodes
    (Path(library.render.output_dir) / FIRST / "shorts/k09.mp4").unlink()
    # The view is manifest-based, just like episode_view: no file probing or store calls.
    monkeypatch.setattr(episodes, "short_locations", lambda *a: pytest.fail("unnecessary locations read"))
    monkeypatch.setattr(episodes, "episode_view", lambda *a: pytest.fail("full episode view is too expensive"))
    assert playlist_listen(library, document(), [])["items"][0]["video_url"].endswith("?v=" + "0" * 12)


def test_unrendered_episode_and_khaithi_are_omitted(library):  # AC1,2
    write_episode(library, SECOND + ".kt")
    (Path(library.render.output_dir) / (SECOND + ".kt") / "render_manifest.json").unlink()
    (Path(library.workspace.dir) / THIRD).mkdir()
    items = playlist_listen(library, document(), [])["items"]
    assert items[-1]["episode_id"] == SECOND
    assert all(i["episode_id"] not in (THIRD, SECOND + ".kt") for i in items)
    assert playlist_listen(library, {**document(), "entries": []}, [])["items"] == []


def test_codes_use_download_labels_positions_and_width_including_skipped(library):  # AC24
    from auto_short.khaithi import KhaiThi
    from auto_short.web import episodes as ep
    for eid in (FIRST, FIRST + ".kt"):
        (Path(library.workspace.dir) / eid / "titles.json").write_text(json.dumps({"header": {"fields": {"episode": "20"}}}))
    (Path(library.workspace.dir) / (FIRST + ".kt") / "khaithi.json").write_text(json.dumps(KhaiThi(FIRST, 4, 7).to_json()))
    path = Path(library.render.output_dir) / FIRST / "render_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["shorts"].insert(0, {"clip_id": "gone", "status": "skipped", "skip_reason": "rejected"})
    manifest["shorts"] += [{"clip_id": f"skip{n}", "status": "skipped"} for n in range(95)]
    path.write_text(json.dumps(manifest))
    items = playlist_listen(library, document(), [])["items"]
    assert [i["code"] for i in items[:4]] == ["T20_S002", "T20_S003", "T20_KT01", "T20_KT02"]
    assert items[0]["number"] == 2 and items[0]["total"] == 100 and items[0]["ep_label"] == "20"
    for item in items:
        eid = item["episode_id"]
        name = ep._names(library, eid, ep.render_manifest(library, eid))[item["clip_id"]]
        assert name.startswith(item["code"] + "_")


def endpoint(app):
    # Same nested router traversal as test_web_watch_party / test_store_download.
    routes = list(app.routes)
    while routes:
        route = routes.pop(0)
        if hasattr(route, "original_router"):
            routes[0:0] = route.original_router.routes
        elif getattr(route, "path", None) == "/api/playlists/{playlist_id}/listen":
            return route.endpoint
    raise AssertionError("missing listen route")


def test_route_fresh_favorites_and_404(library):
    app = make_app(library)
    get = endpoint(app)
    assert get("invalid!").status_code == 404
    assert get("PLmissing001").status_code == 404
    assert get(PID)["items"][0]["fav"]["favorite"] is False
    store.write_favorites(app.state.compilations.folder(PID), [Item(FIRST, "k09")])
    assert get(PID)["items"][0]["fav"]["favorite"] is True


def test_http_listen_auth_404_and_queue(library):  # AC1,2: full middleware path
    from fastapi.testclient import TestClient
    with TestClient(make_app(library), follow_redirects=False) as client:
        path = f"/api/playlists/{PID}/listen"
        assert client.get(path).status_code == 401
        login(client)
        assert client.get("/api/playlists/PLmissing001/listen").status_code == 404
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == playlist_listen(library, document(), [])


def test_auto_advance_never_scrolls_page_to_list():  # AC 28 / 29 (static guard)
    static = Path(__file__).parents[1] / "src/auto_short/web/static"
    listen, player = (static / "listen.js").read_text(), (static / "player.js").read_text()
    css = (static / "style.css").read_text()
    # The list scrolls only inside its own box; the page moves only up to the video.
    assert "button.scrollIntoView" not in listen and "AutoShortPlayer.scrollWithin(container, current)" in player
    assert ".listen-queue { max-height: 28rem; overflow: auto; }" in css
    assert player.count("scrollIntoView") == 1 and "focus()" not in player
    # The countdown card is brought into view when a track ends, and the page returns to the video after the switch.
    assert "this.renderAdvance(); this.scrollToVideo();" in player
    assert "this.endedKey = null; this.scrollToVideo();" in player


def test_favorites_only_keeps_order_and_marks_all_hearted(library):  # AC 39
    hearts = [Item(FIRST, "k09"), Item(FIRST + ".kt", "k02")]
    full = playlist_listen(library, document(), hearts)["items"]
    only = playlist_listen(library, document(), hearts, favorites_only=True)["items"]
    assert [i["clip_id"] for i in only] == [i["clip_id"] for i in full if i["fav"]["favorite"]] and len(only) == 2
    assert all(i["fav"]["favorite"] for i in only)
    assert playlist_listen(library, document(), [], favorites_only=True)["items"] == []


def test_http_listen_favorites_query(library):  # AC 39 (route)
    from fastapi.testclient import TestClient
    app = make_app(library)
    with TestClient(app, follow_redirects=False) as client:
        login(client)
        assert client.get(f"/api/playlists/{PID}/listen?favorites=true").json()["items"] == []
        store.write_favorites(app.state.compilations.folder(PID), [Item(FIRST, "k09")])
        got = client.get(f"/api/playlists/{PID}/listen?favorites=true").json()["items"]
        assert [i["clip_id"] for i in got] == ["k09"] and got[0]["fav"]["favorite"] is True


def test_listen_and_watch_share_one_module():  # AC 30 / 31 / 34 (static guard)
    static = Path(__file__).parents[1] / "src/auto_short/web/static"
    listen, watch, player = [(static / n).read_text() for n in ("listen.js", "watch.js", "player.js")]
    assert "<details" not in listen and "createElement(\"details\")" not in listen
    # The room UI exists once (listen.js); watch.js is only transport + invitation bar.
    assert "new AutoShortPlayer" in listen and "new AutoShortPlayer" not in watch and "renderGroupList" not in watch
    assert "nextInGroup()" in player and "onGroup" in listen and 'explicit ? "group" : "episode"' in listen
    for page in ("episode.html", "watch.html", "favorites.html"):
        html = (static / page).read_text()
        assert 'id="listen-video"' in html and "/static/listen.js" in html and "/static/player.js" in html
    assert 'id="watch-video"' not in (static / "watch.html").read_text()
    # Favorites use parts (AC 43); keep an un-hearted playing item until it changes (AC 40).
    assert "groupFavorites" in listen and "favorites=1" in listen and "same(item, currentItem)" in listen


def test_countdown_card_overlays_the_video_on_all_pages():  # AC 28
    import re
    static = Path(__file__).parents[1] / "src/auto_short/web/static"
    for page in ("episode.html", "watch.html", "favorites.html"):
        html = (static / page).read_text()
        stage = re.search(r'<div class="player-stage">(.*?)</div>\s*</div>|<div class="player-stage">(.*?)\n\s*</div>', html, re.S)
        assert stage and 'id="listen-video"' in stage.group(0) and 'id="listen-notice"' in stage.group(0), page
        assert html.count('id="listen-notice"') == 1
    css = (static / "style.css").read_text()
    assert ".player-stage { position: relative; }" in css and ".player-stage .player-notice { position: absolute;" in css


@pytest.fixture
def run_player_js():
    """Run the real browser modules with a small event DOM; no server or browser dependency."""
    import subprocess
    root = Path(__file__).parents[1]
    harness = r'''
const assert = require("node:assert/strict"), fs = require("node:fs");
global.window = globalThis;
let now = 0, timerId = 0;
const timers = new Map(), scrolls = [];
global.performance = {now: () => now};
global.setTimeout = (fn, delay) => { timers.set(++timerId, {fn, at: now + delay}); return timerId; };
global.clearTimeout = (id) => timers.delete(id);
function tick(ms) {
  const end = now + ms;
  while (true) {
    const due = [...timers].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
    if (!due) break;
    now = due[1].at; timers.delete(due[0]); due[1].fn();
  }
  now = end;
}
class Element {
  constructor(tag = "div") {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attrs = {}; this.events = {};
    this.style = {}; this.hidden = false; this.value = ""; this._text = "";
    this.classList = {toggle() {}}; this.paused = true; this.currentTime = 0; this.duration = 60; this.playbackRate = 1;
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(e => e.textContent).join(""); }
  get firstChild() { return this.children[0]; }
  append(...nodes) { for (const n of nodes) { n.parentElement = this; this.children.push(n); } }
  replaceChildren(...nodes) { this._text = ""; this.children = []; this.append(...nodes); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(name, fn) { (this.events[name] ||= []).push(fn); }
  async fire(name) { await Promise.all((this.events[name] || []).map(fn => fn({target: this}))); }
  querySelectorAll(selector) {
    const matches = (e) => selector === "[data-kind]" ? !!e.dataset.kind
      : selector === "button[data-index]" ? e.tagName === "button" && e.dataset.index !== undefined : false;
    return this.children.flatMap(e => [...(matches(e) ? [e] : []), ...e.querySelectorAll(selector)]);
  }
  getBoundingClientRect() { return {top: 0, bottom: 10, height: 10}; }
  scrollIntoView(options) { scrolls.push([this, options]); }
  load() { this.readyState = 0; this.currentTime = 0; this.paused = true; this.ended = false; }
  pause() { this.paused = true; }
  play() { this.paused = false; return Promise.resolve(); }
}
const elements = new Map();
const $ = (name) => {
  if (!elements.has(name)) elements.set(name, new Element(name === "video" ? "video" : "div"));
  return elements.get(name);
};
const documentEvents = {};
global.document = {visibilityState: "visible", pictureInPictureEnabled: false,
  getElementById: id => $(id.replace(/^listen-/, "")), createElement: tag => new Element(tag),
  createTextNode: text => {const e = new Element("text"); e.textContent = text; return e;},
  addEventListener: (name, fn) => (documentEvents[name] ||= []).push(fn),
  dispatchEvent: event => {for (const fn of documentEvents[event.type] || []) fn(event); return true;},
  querySelectorAll: () => []};
const windowEvents = {};
global.addEventListener = (name, fn) => (windowEvents[name] ||= []).push(fn);
global.dispatchEvent = event => { for (const fn of windowEvents[event.type] || []) fn(event); return true; };
global.navigator = {};
const storage = new Map();
global.localStorage = {getItem: k => storage.get(k) || null, setItem: (k, v) => storage.set(k, v)};
const jumpLabel = new Element("label"); jumpLabel.append(document.createTextNode("Tới tập "), $("jump"));
for (const kind of ["short", "khaithi", "both"]) { const b = new Element("button"); b.dataset.kind = kind; $("filter").append(b); }
$("resume").hidden = true;
let sourceItems = [], commands = [], requests = [];
global.location = {pathname: "/playlists/PLtest/favorites", origin: "http://test"};
global.fetch = async (path, options = {}) => {
  requests.push(path);
  if (options.method === "POST" && path.endsWith("/favorites")) {
    const body = JSON.parse(options.body);
    const found = sourceItems.find(item => item.episode_id === body.episode_id && item.clip_id === body.clip);
    if (found) found.fav.favorite = body.favorite;
  }
  return {ok: true, json: async () => structuredClone(path.includes("/listen")
    ? {playlist_id: "PLtest", title: "Bộ kinh", items: sourceItems.filter(item => !path.includes("favorites=1") || item.fav.favorite)}
    : {id: "ep1", base_episode_id: "ep1", favorites: {playlist_id: "PLtest"}})};
};
global.AutoShortWatch = {client: "a", room: {}, poll() {}, command: async (action, data) => {commands.push({action, ...data});}};
eval(fs.readFileSync("src/auto_short/web/static/player.js", "utf8"));
const Player = AutoShortPlayer;
function item(ep, n, kind = "short") {
  return {episode_id: `ep${ep}${kind === "khaithi" ? ".kt" : ""}`, base_episode_id: `ep${ep}`, ep_index: ep,
    kind, clip_id: `k${n}`, title: `Bài ${n}`, video_url: `/files/ep${ep}${kind === "khaithi" ? ".kt" : ""}/k${n}.mp4`,
    fav: {playlist_id: "PLtest", episode_id: `ep${ep}`, clip: `k${n}`, favorite: true}};
}
// Stateful transport double: set preserves the previous room's auto, as WatchRoom does.
let serverRoom;
function useRoom(oldAuto = false) {
  serverRoom = {auto: oldAuto, queue: [], index: 0, position: 0, rate: 1, paused: true, version: 0, updated_at: now / 1000};
  function publish() {
    const entry = serverRoom.queue[serverRoom.index];
    const original = sourceItems.find(item => item.video_url === entry?.url);
    const data = structuredClone({...serverRoom, video_url: entry?.url || null, title: entry?.title,
      fav: original?.fav, server_time: now / 1000, by: "a"});
    AutoShortWatch.room.handler(data, true);
    return data;
  }
  AutoShortWatch.command = async (action, data) => {
    commands.push(structuredClone({action, ...data}));
    if (!serverRoom.paused) serverRoom.position += (now / 1000 - serverRoom.updated_at) * serverRoom.rate;
    serverRoom.updated_at = now / 1000;
    if (action === "set") Object.assign(serverRoom, structuredClone(data));
    else if (action === "auto") serverRoom.auto = data.auto;
    else if (action === "next") {serverRoom.index++; serverRoom.position = 0; serverRoom.paused = false;}
    else if (action === "goto") {serverRoom.index = data.index; serverRoom.position = 0; serverRoom.paused = false;}
    serverRoom.version++;
    return publish();
  };
  AutoShortWatch.poll = async () => publish();
}
async function settled() { for (let i = 0; i < 8; i++) await new Promise(setImmediate); }
async function boot() { eval(fs.readFileSync("src/auto_short/web/static/listen.js", "utf8")); await settled(); }
async function metadata() { $("video").readyState = 1; await $("video").fire("loadedmetadata"); await settled(); }
async function end() { $("video").ended = true; $("video").paused = true; $("video").currentTime = 60; await $("video").fire("ended"); }
'''

    def run(body):
        script = harness + "\n(async () => {\n" + body + "\n})().catch(e => { console.error(e); process.exitCode = 1; });"
        result = subprocess.run(["node", "-e", script], cwd=root, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stdout + result.stderr
    return run


@pytest.mark.parametrize("kind,size", [("khaithi", 15), ("short", 35), ("both", 4)])
def test_favorites_part_sizes_and_sparse_episode_groups(run_player_js, kind, size):  # AC 43
    run_player_js(f'''
const kind = {json.dumps(kind)}, size = {size};
// Four episodes with favorites means four existing episodes, even if episode numbers have gaps.
const source = kind === "both" ? [1, 3, 7, 10, 20].flatMap(ep => [item(ep, 1), item(ep, 1, "khaithi")])
  : Array.from({{length: size * 2 + 1}}, (_, n) => item(1, n, kind));
const grouped = Player.groupFavorites(source, kind);
const player = Object.create(Player.prototype); player.getItems = () => grouped;
assert.equal(player.groups().length, kind === "both" ? 2 : 3);
assert.equal(grouped.filter(e => e.group.id === grouped[0].group.id).length, kind === "both" ? 8 : size);
assert.equal(grouped.at(-1).group.label, kind === "both" ? "Phần 2" : "Phần 3");
assert.equal(grouped[0].group.choice, kind === "both" ? "Phần 1 (Tập 1–10)" : `Phần 1 (bài 1–${{size}})`);
assert.ok(source.every(e => !e.group)); // pure grouping; identities/heart records stay reusable
assert.deepEqual(Player.groupFavorites([], kind), []);
''')


def test_favorites_click_filter_end_card_and_unheart(run_player_js):  # AC 23 / 28–31 / 40 / 43
    run_player_js(r'''
sourceItems = Array.from({length: 38}, (_, n) => item(1, n));
storage.set("auto-short-listen-filter", '"short"');
await boot(); await metadata();
assert.equal($("queue").firstChild.textContent, "Phần 1 · 35 bài");
assert.equal($("jump").children.length, 2);
await $("queue").querySelectorAll("button[data-index]")[34].fire("click"); await metadata();
assert.equal($("video").src, sourceItems[34].video_url); assert.ok(!$("video").paused);
assert.equal(scrolls.at(-1)[0], $("video"));
await end();
assert.ok(!$("notice").hidden); assert.match($("notice").textContent, /Đã hết Phần 1/);
assert.match($("notice").textContent, /Nghe Phần 2/);
tick(10000); assert.equal($("video").src, sourceItems[34].video_url);
const actions = $("notice").children.find(e => e.className === "actions");
await actions.firstChild.fire("click"); await metadata();
assert.equal($("video").src, sourceItems[35].video_url);
assert.equal($("queue").firstChild.textContent, "Phần 2 · 3 bài");
await end(); assert.match($("notice").textContent, /Sau 3 s/);
tick(3000); await metadata(); assert.equal($("video").src, sourceItems[36].video_url);
// Filter changes regroup, retaining the same playable item and time.
$("video").currentTime = 17;
await $("filter").children[2].fire("click"); await metadata();
assert.equal($("video").src, sourceItems[36].video_url); assert.equal($("video").currentTime, 17);
assert.equal($("queue").firstChild.textContent, "Phần 1 · 38 bài");
await $("favorite").fire("click");
assert.equal($("queue").querySelectorAll("button[data-index]").length, 38); // playing item finishes
await $("next").fire("click"); await metadata();
assert.equal($("queue").querySelectorAll("button[data-index]").length, 37);
assert.ok(!$("queue").querySelectorAll("button[data-index]").some(b => b.textContent.includes("Bài 36")));
// No page scroll ever targets a row.
assert.ok(scrolls.every(([e, opts]) => e === $("video") && opts.behavior === "smooth"));
''')


def test_favorites_resume_identity_and_room_group_payload(run_player_js):  # AC 43 / 44
    run_player_js(r'''
sourceItems = Array.from({length: 50}, (_, n) => item(1, n));
storage.set("auto-short-listen-filter", '"short"');
const key = "auto-short-listen-position:PLtest:fav";
storage.set(key, JSON.stringify({episode_id: "ep1", clip_id: "k43", position: 23}));
// Reordering/removing preceding items changes the index/part; resume must still find k43.
sourceItems.splice(0, 10);
await boot(); await metadata();
assert.equal($("video").src, "/files/ep1/k43.mp4"); assert.equal($("video").currentTime, 23);
assert.equal($("queue").firstChild.textContent, "Phần 1 · 35 bài"); assert.ok($("video").paused);
await $("play").fire("click"); $("video").currentTime = 29;
tick(4000); await $("video").fire("timeupdate");
assert.deepEqual(JSON.parse(storage.get(key)), {episode_id: "ep1", clip_id: "k43", position: 29});
await $("watch").fire("click");
const sent = commands.find(c => c.action === "set");
assert.equal(sent.position, 29); assert.equal(sent.index, 33); assert.equal(sent.queue.length, 40);
assert.equal(sent.queue[33].group.label, "Phần 1"); assert.equal(sent.queue[35].group.label, "Phần 2");
// Another participant receives the groups from the room, even via the old /watch invite URL.
await AutoShortWatch.room.handler({queue: sent.queue, index: 35, video_url: sent.queue[35].url,
  title: sent.queue[35].title, paused: true, position: 0, rate: 1, auto: true,
  finished: false, version: 2, by: "b", server_time: 0, updated_at: 0});
assert.equal($("queue").firstChild.textContent, "Phần 2 · 5 bài");
$("jump").value = sent.queue[0].group.id; await $("jump").fire("change");
assert.deepEqual(commands.at(-1), {action: "group", group: sent.queue[0].group.id});
''')


def test_overlay_action_text_has_contrast():  # AC 42: dark glyphs on light/yellow button and select surfaces
    css = (Path(__file__).parents[1] / "src/auto_short/web/static/style.css").read_text()
    assert ".player-stage .player-notice .btn, .player-stage .player-notice .btn.primary { color: #1d1d1b; }" in css
    assert ".player-stage .player-notice select, .player-stage .player-notice option { color: #1d1d1b; background: #fff; }" in css
    # The override follows the .small rule which used to make small buttons unreadable.
    assert css.index(".player-stage .player-notice .btn,") > css.index(".player-stage .player-notice .small { color: #ddd; }")


def test_episode_groups_keep_end_boundary_and_manual_next(run_player_js):  # AC 23 / 28–31
    run_player_js(r'''
location.pathname = "/episodes/ep1";
sourceItems = [item(1, 1), item(1, 2, "khaithi"), item(2, 1)];
await boot(); await metadata();
assert.equal($("queue").firstChild.textContent, "Tập 1 · 2 bài");
await end(); tick(3000); await metadata();
assert.equal($("video").src, sourceItems[1].video_url); // Short -> khai thị in the same episode
await end(); assert.match($("notice").textContent, /Đã hết Tập 1/);
tick(10000); assert.equal($("video").src, sourceItems[1].video_url);
await $("next").fire("click"); await metadata();
assert.equal($("video").src, sourceItems[2].video_url);
assert.equal($("queue").firstChild.textContent, "Tập 2 · 1 bài");
assert.ok(scrolls.every(([e]) => e === $("video")));
// Old continuous rooms still render as a single group.
const old = Object.create(Player.prototype); old.state = {continuous: true, index: 0};
old.getItems = () => sourceItems; old.getNext = () => sourceItems[2];
assert.equal(old.groups().length, 1); assert.equal(old.nextInGroup(), sourceItems[2]);
''')


@pytest.mark.parametrize("saved_episode", ["ep1.kt", "removed"])
def test_favorites_resume_hidden_kind_or_missing_identity(run_player_js, saved_episode):  # AC 44
    run_player_js(r'''
sourceItems = [item(1, 1), item(1, 1, "khaithi")]; // identical clip ids in two different episodes
storage.set("auto-short-listen-filter", '"short"');
const savedEpisode = SAVED_EPISODE;
storage.set("auto-short-listen-position:PLtest:fav", JSON.stringify({episode_id: savedEpisode, clip_id: "k1", position: 19}));
await boot(); await metadata();
if (savedEpisode === "ep1.kt") {
  assert.equal($("video").src, sourceItems[1].video_url); assert.equal($("video").currentTime, 19);
  assert.equal(storage.get("auto-short-listen-filter"), '"both"');
} else {
  assert.equal($("video").src, sourceItems[0].video_url); assert.equal($("video").currentTime, 0);
  assert.ok($("resume").hidden);
}
'''.replace("SAVED_EPISODE", json.dumps(saved_episode)))


@pytest.mark.parametrize("auto", [True, False])
def test_start_room_always_transfers_solo_auto(run_player_js, auto):  # finding 1 / AC 36
    run_player_js(r'''
sourceItems = [item(1, 1), item(1, 2)];
const auto = AUTO;
storage.set("auto-short-listen-auto", JSON.stringify(auto));
useRoom(!auto); // a previously existing room has the opposite setting
await boot(); await metadata();
await $("watch").fire("click"); await settled();
assert.equal(serverRoom.auto, auto);
assert.deepEqual(commands.at(-1), {action: "auto", auto});
assert.equal($("auto").checked, auto);
'''.replace("AUTO", json.dumps(auto)))


def test_room_unheart_prunes_after_navigation_and_keeps_parts(run_player_js):  # finding 2 / AC 40,43
    run_player_js(r'''
sourceItems = Array.from({length: 38}, (_, n) => item(1, n));
storage.set("auto-short-listen-filter", '"short"');
useRoom(); await boot(); await metadata();
await $("watch").fire("click"); await settled(); await metadata();
await $("favorite").fire("click"); await settled();
assert.equal(serverRoom.queue.length, 38); // keep the playing item so it can finish
assert.equal($("favorite").textContent, "♡");
const reads = requests.filter(p => p.includes("/listen")).length;
assert.equal(reads, 1); // our own event must not trigger an external refresh
await $("next").fire("click"); await settled(); await metadata();
assert.equal(serverRoom.queue.length, 37);
assert.ok(!serverRoom.queue.some(e => e.url === sourceItems[0].video_url));
assert.equal(serverRoom.queue[serverRoom.index].url, sourceItems[1].video_url);
assert.equal(serverRoom.position, 0); assert.equal(serverRoom.paused, false); assert.equal(serverRoom.auto, true);
assert.equal(serverRoom.queue.filter(e => e.group.label === "Phần 1").length, 35);
assert.equal(serverRoom.queue.filter(e => e.group.label === "Phần 2").length, 2);
assert.equal($("queue").querySelectorAll("button[data-index]").length, 35);
// A later poll must not issue another identical set; returning to solo must also keep the item removed.
const sets = commands.filter(c => c.action === "set").length;
await AutoShortWatch.poll(true); await settled();
assert.equal(commands.filter(c => c.action === "set").length, sets);
AutoShortWatch.end = async () => AutoShortWatch.room.handler({video_url: null}, true);
await $("end").fire("click"); await settled(); await metadata();
assert.equal($("video").src, sourceItems[1].video_url);
assert.ok(!$("queue").querySelectorAll("button[data-index]").some(b => b.textContent.includes("Bài 0")));
''')


@pytest.mark.parametrize("room", [False, True])
def test_favorites_tab_suspends_and_can_resume_same_track(run_player_js, room):  # AC 47
    run_player_js(r'''
sourceItems = Array.from({length: 17}, (_, n) => item(1, n, "khaithi"));
storage.set("auto-short-listen-filter", '"khaithi"');
const room = ROOM;
if (room) useRoom();
await boot(); await metadata(); await $("play").fire("click");
if (room) {await $("watch").fire("click"); await settled(); await metadata();}
if (room) tick(17000); // the room clock and the media have both progressed 17 seconds
$("video").currentTime = 17;
assert.equal($("queue").firstChild.textContent, "Phần 1 · 15 bài");
window.addEventListener("favorites-changed", () => { globalThis.themeRefreshes = (globalThis.themeRefreshes || 0) + 1; });
await $("favorite").fire("click"); await settled();
assert.equal(themeRefreshes, 1); // theme planner still hears heart changes
assert.equal(requests.filter(p => p.includes("/listen")).length, 1); // manual-pane refresh is gone
const count = commands.length;
document.dispatchEvent(new CustomEvent("favorites-tab", {detail: "ai"}));
assert.equal($("video").paused, true);
if (room) {await AutoShortWatch.poll(true); await settled(); assert.equal($("video").paused, true);}
// Suspend blocks media controls and does not pause the whole room for other participants.
await $("play").fire("click");
assert.equal(commands.length, count); assert.equal($("video").paused, true);
document.dispatchEvent(new CustomEvent("favorites-tab", {detail: "listen"}));
await settled(); await metadata();
if (!room) await $("play").fire("click");
assert.equal($("video").src, sourceItems[0].video_url);
assert.equal($("video").currentTime, 17); assert.equal($("video").paused, false);
'''.replace("ROOM", json.dumps(room)))
