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


def endpoint(app, path="/api/playlists/{playlist_id}/listen"):
    # Same nested router traversal as test_web_watch_party / test_store_download.
    routes = list(app.routes)
    while routes:
        route = routes.pop(0)
        if hasattr(route, "original_router"):
            routes[0:0] = route.original_router.routes
        elif getattr(route, "path", None) == path:
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


@pytest.mark.parametrize("mode,next_index", [
    ("unwatched", 0), ("gap", 3), ("shorts-done", 2), ("episode-done", 4),
    ("finished", None), ("broken", 0), ("bad-schema", 0), ("broken-earlier", 4), ("empty", None),
])
def test_next_listen_route_uses_last_watched_in_full_queue(library, mode, next_index):  # PST2 AC8, no sockets
    from auto_short.review.watched import set_watched

    items = playlist_listen(library, document(), [])["items"]
    marked = {"gap": [2], "shorts-done": [0, 1], "episode-done": [3], "finished": [4],
              "broken-earlier": [3]}.get(mode, [])
    for index in marked:
        item = items[index]
        set_watched(item["episode_id"], library, item["clip_id"], True)
    if mode in {"broken", "bad-schema", "broken-earlier"}:
        (Path(library.workspace.dir) / FIRST / "watched.json").write_text(
            '{"schema_version": 9}' if mode == "bad-schema" else "{broken", encoding="utf-8")
    if mode == "empty":
        for eid in (FIRST, FIRST + ".kt", SECOND):
            (Path(library.render.output_dir) / eid / "render_manifest.json").unlink()
    app = make_app(library)
    get = endpoint(app, "/api/playlists/{playlist_id}/next-listen")
    before = {p: p.read_bytes() for p in Path(library.workspace.dir).rglob("watched.json")}
    expected = {key: items[next_index][key] for key in ("episode_id", "clip_id", "code")} if next_index is not None else None
    response = {"item": expected}
    if expected is None:
        response["next_unprocessed"] = {"episode_id": FIRST if mode == "empty" else THIRD,
                                        "label": "T1" if mode == "empty" else "T3"}
    assert get(PID) == response
    assert get("PLmissing001").status_code == 404 and get("invalid!").status_code == 404
    assert before == {p: p.read_bytes() for p in Path(library.workspace.dir).rglob("watched.json")}


@pytest.mark.parametrize("mode,label", [("entry", "T51"), ("numeric-id", "T51"), ("header", "T052"), ("title", "T51"),
                                       ("index", "T7"), ("skipped", "T51"), ("broken", "T51"),
                                       ("kt-last", "T52"), ("no-content", "T1"), ("finished", None)])
def test_next_unprocessed_follows_last_content_and_reuses_episode_numbers(library, mode, label):  # PST2 AC11
    from auto_short.web.listen import next_unprocessed

    doc = {"entries": [
        {"index": 7, "video_id": THIRD, "available": True, "episode": "51", "title": "Không nhận số"},
        {"index": 6, "video_id": "youtube0042", "available": False},
        {"index": 5, "video_id": "bad!", "available": True},
        {"index": 4, "video_id": SECOND, "available": True},
        {"index": 2, "video_id": "youtube0040", "available": True},  # earlier gap must not be selected
        {"index": 1, "video_id": FIRST, "available": True},
    ]}
    write_episode(library, "youtube0042")  # unavailable content must not move the last-content boundary
    if mode == "numeric-id":
        doc["entries"][0]["video_id"] = "12345678901"
    if mode == "header":
        folder = Path(library.workspace.dir) / THIRD
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "titles.json").write_text(json.dumps({"header": {"fields": {"episode": "052"}}}))
    if mode in {"title", "index"}:
        doc["entries"][0]["episode"] = None
        doc["entries"][0]["title"] = "Kinh Vô Lượng Thọ tập 51" if mode == "title" else "Không nhận số"
    if mode == "skipped":
        write_episode(library, THIRD, clips=(), extra_shorts=[{"clip_id": "k01", "status": "skipped"}])
    if mode == "broken":
        folder = Path(library.render.output_dir) / THIRD
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "render_manifest.json").write_text("{broken")
    if mode == "kt-last":
        write_episode(library, THIRD + ".kt")
        doc["entries"].append({"index": 8, "video_id": "youtube0052", "available": True, "episode": "52"})
    if mode == "no-content":
        for eid in (FIRST, FIRST + ".kt", SECOND):
            (Path(library.render.output_dir) / eid / "render_manifest.json").unlink()
    if mode == "finished":
        doc["entries"] = [e for e in doc["entries"] if e["video_id"] != THIRD]
    eid = (FIRST if mode == "no-content" else "youtube0052" if mode == "kt-last" else
           "12345678901" if mode == "numeric-id" else THIRD)
    assert next_unprocessed(library, doc) == ({"episode_id": eid, "label": label} if label else None)


@pytest.mark.parametrize("kind", ["post", "listen"])
@pytest.mark.parametrize("mode", ["unprocessed", "finished", "has-item"])
def test_next_routes_add_unprocessed_only_when_no_item(library, monkeypatch, kind, mode):  # PST2 AC11, no sockets
    from auto_short.review.watched import set_watched
    from auto_short.web import listen

    if mode == "finished":
        file = Path(library.workspace.dir) / "_playlists" / (PID + ".json")
        doc = json.loads(file.read_text())
        doc["entries"] = [e for e in doc["entries"] if e["video_id"] != THIRD]
        file.write_text(json.dumps(doc))
    if mode != "has-item":
        set_watched(SECOND, library, "k05", True)
    app = make_app(library)
    if mode == "has-item":
        monkeypatch.setattr(app.state.post_links, "next_post", lambda *args: {"episode_id": FIRST, "clip_id": "k09", "code": "T1_S01"})
        def unexpected(*args):
            pytest.fail("fallback must not be computed while a next item exists")
        monkeypatch.setattr(listen, "next_unprocessed", unexpected)
    get = endpoint(app, f"/api/playlists/{{playlist_id}}/next-{kind}")
    response = get(PID)
    key = "post" if kind == "post" else "item"
    if mode == "has-item":
        assert response[key] and "next_unprocessed" not in response
    else:
        assert response == {key: None, "next_unprocessed":
                            {"episode_id": THIRD, "label": "T3"} if mode == "unprocessed" else None}


@pytest.mark.parametrize("saved_mode,position", [("same", 23.5), ("other-clip", 0), ("other-episode", 0),
                                                 ("missing", 0), ("broken", 0), ("negative", 0)])
def test_player_js_resume_clip_uses_episode_identity_and_only_its_saved_position(run_player_js, saved_mode, position):  # PST2 AC8
    run_player_js(r'''
location.pathname = "/episodes/ep2.kt";
location.search = "?keep=1&resume=1&clip=k2";
location.hash = "#retained";
const replaced = [];
global.history = {state: null, replaceState: (...args) => replaced.push(args)};
sourceItems = [item(1, 1), item(2, 2), item(2, 1, "khaithi"), item(2, 2, "khaithi")];
const mode = SAVED_MODE;
const saved = {episode_id: mode === "other-episode" ? "ep2" : "ep2.kt",
  clip_id: mode === "other-clip" ? "k1" : "k2", position: mode === "negative" ? -1 : 23.5};
if (mode !== "missing") storage.set("auto-short-listen-position:PLtest", mode === "broken" ? "{" : JSON.stringify(saved));
storage.set("auto-short-listen-filter", '"short"');
await boot(); tick(5000); await metadata();
assert.equal(activePlayer.state.episode_id, "ep2.kt"); assert.equal(activePlayer.state.clip_id, "k2");
assert.equal(activePlayer.position(), POSITION);
assert.equal(storage.get("auto-short-listen-filter"), '"both"');
assert.ok(!activePlayer.media().paused); assert.ok($("resume").hidden);
assert.ok(scrolls.some(([node]) => node === $("video")));
assert.deepEqual(replaced, [[null, "", "/episodes/ep2.kt?keep=1#retained"]]);
'''.replace("SAVED_MODE", json.dumps(saved_mode)).replace("POSITION", json.dumps(position)))


@pytest.mark.parametrize("mode", ["solo", "hidden", "error", "pending", "fake", "seek", "skip", "favorites"])
def test_player_js_solo_real_ended_ticks_completed_identity_without_waiting(run_player_js, mode):  # PST2 AC8
    run_player_js(r'''
const mode = MODE_VALUE;
location.pathname = mode === "favorites" ? "/playlists/PLtest/favorites" : "/episodes/ep1";
sourceItems = [item(1, 1), item(1, 2), item(2, 1)];
const watched = [];
respond = async (path, options) => {
  if (!path.endsWith("/watched")) return null;
  watched.push({path, method: options.method, body: JSON.parse(options.body)});
  if (mode === "pending") return new Promise(() => {});
  if (mode === "error") throw Error("write failed");
  return {ok: true, json: async () => ({watched: true})};
};
await boot(); await metadata(); await $("play").fire("click"); await settled();
const audio = activePlayer.media();
if (mode === "hidden") await visibility(true);
if (mode === "fake") {
  audio.ended = true; await audio.fire("ended", {isTrusted: false});
} else if (mode === "seek") {
  audio.seeking = true; await end(audio);
} else if (mode === "skip") {
  await $("next").fire("click"); await metadata();
  await audio.fire("ended");  // stale notification after the source changed
} else await end(audio);
await settled();
const eligible = ["solo", "hidden", "error", "pending"].includes(mode);
assert.deepEqual(watched, eligible ? [{path: "/api/episodes/ep1/shorts/k1/watched", method: "POST", body: {value: true}}] : []);
if (eligible) {
  if (mode !== "hidden") tick(3001);
  await settled(); await metadata();
  assert.equal(activePlayer.state.clip_id, "k2"); assert.ok(!activePlayer.media().paused);
}
'''.replace("MODE_VALUE", json.dumps(mode)))


@pytest.mark.parametrize("mode", ["ended", "hidden", "shell", "error", "pending", "fake", "seek", "skip",
                                  "inactive-media", "unknown", "mismatch", "favorites"])
def test_player_js_room_real_ended_ticks_room_identity_before_advancing(run_player_js, mode):  # PST2 AC9
    run_player_js(r'''
const mode = MODE_VALUE, watched = [], order = [];
location.pathname = mode === "favorites" ? "/playlists/PLtest/favorites" : mode === "shell" ? "/watch" : "/episodes/ep1";
sourceItems = [item(1, 1), item(2, 2), item(3, 7, "khaithi"), item(4, 8)];
storage.set("auto-short-listen-filter", '"short"');  // Room's KT item is absent from the solo filtered queue.
respond = async (path, options) => {
  if (!path.endsWith("/watched")) return null;
  order.push("watched");
  watched.push({path, method: options.method, body: JSON.parse(options.body)});
  if (mode === "pending") return new Promise(() => {});
  if (mode === "error") throw Error("write failed");
  return {ok: true, json: async () => ({watched: true})};
};
await boot(); await metadata();
if (mode !== "shell") { await $("play").fire("click"); await settled(); }
useRoom();
if (mode !== "shell") { await $("watch").fire("click"); await settled(); await metadata(); }
const queue = sourceItems.map(i => ({url: i.video_url, title: i.title, group: {id: "shared", label: "Bộ"}}));
if (mode === "shell") queue.forEach((entry, i) => Object.assign(entry, {
  episode_id: sourceItems[i].episode_id, clip_id: sourceItems[i].clip_id,
}));  // The watch API decorates queue entries even for /watch clients without a solo list.
if (mode === "unknown") queue[2].url = "/files/unmapped/k1.mp4";
await AutoShortWatch.command("set", {queue, index: 2, position: 0, rate: 1, paused: false});
await settled(); await metadata();
const command = AutoShortWatch.command;
AutoShortWatch.command = async (action, ...args) => {order.push(action); return command(action, ...args);};
const audio = activePlayer.media();
if (mode === "hidden") await visibility(true);
if (mode === "fake") {
  audio.ended = true; await audio.fire("ended", {isTrusted: false});
} else if (mode === "seek") {
  audio.seeking = true; await end(audio);
} else if (mode === "skip") {
  await AutoShortWatch.command("next", {expect_version: serverRoom.version}); await settled(); await metadata();
  await audio.fire("ended");  // The previous item has already been replaced.
} else if (mode === "inactive-media") {
  const other = activePlayer.audios.find(m => m !== audio);
  other.ended = true; await other.fire("ended");
} else {
  if (mode === "mismatch") activePlayer.state.queue[2].url = sourceItems[0].video_url;
  await end(audio);
}
await settled();
const eligible = ["ended", "hidden", "shell", "error", "pending"].includes(mode);
assert.deepEqual(watched, eligible ? [{path: "/api/episodes/ep3.kt/shorts/k7/watched", method: "POST", body: {value: true}}] : []);
if (eligible) {
  const nextAction = mode === "hidden" ? "next" : "ended";
  assert.ok(order.indexOf("watched") < order.indexOf(nextAction));
  assert.ok(commands.some(c => c.action === nextAction));
  if (mode === "hidden") assert.equal(activePlayer.state.video_url, sourceItems[3].video_url);
  else assert.ok(serverRoom.finished);
}
'''.replace("MODE_VALUE", json.dumps(mode)))


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
    assert 'id="listen-title-editor"' not in (static / "watch.html").read_text()
    for page in ("episode.html", "favorites.html"):
        html = (static / page).read_text()
        assert html.count('id="listen-title-editor"') == 1
        assert html.index('/static/app.js') < html.index('/static/title_editor.js') < html.index('/static/listen.js')
    assert 'function titleEditor(' not in (static / "app.js").read_text()
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
    this.style = {}; this.hidden = false; this.value = ""; this._text = ""; this.loads = 0; this.plays = 0; this.pauses = 0; this.networkState = 2;
    this.classList = {toggle() {}}; this.paused = true; this.currentTime = 0; this.duration = tag === "audio" ? 61.5 : 60; this.playbackRate = 1;
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(e => e.textContent).join(""); }
  get firstChild() { return this.children[0]; }
  append(...nodes) { for (let n of nodes) { if (typeof n !== "object") { const t = new Element("text"); t.textContent = n; n = t; } n.parentElement = this; this.children.push(n); } }
  prepend(...nodes) { const tail = this.children; this.children = []; this.append(...nodes); this.children.push(...tail); }
  replaceChildren(...nodes) { this._text = ""; this.children = []; this.append(...nodes); }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "hidden") this.hidden = true; if (k === "value") this.value = String(v); }
  getAttribute(k) { return k === "src" ? this.src || null : this.attrs[k] ?? null; }
  removeAttribute(k) { delete this.attrs[k]; if (k === "src") this.src = ""; }
  addEventListener(name, fn, options) {
    const listeners = this.events[name] ||= [];
    // At-target capture handlers run before ordinary handlers, as in the browser.
    if (options === true || options?.capture) listeners.unshift(fn); else listeners.push(fn);
  }
  async fire(name, extra = {}) { if (name === "click" && this.disabled) return; await Promise.all((this.events[name] || []).map(fn => fn({target: this, isTrusted: true, ...extra}))); }
  focus() {}
  querySelectorAll(selector) {
    const matches = (e) => selector === "[data-kind]" ? !!e.dataset.kind
      : selector === "button[data-index]" ? e.tagName === "button" && e.dataset.index !== undefined
      : selector.startsWith(".") ? (e.className || "").split(" ").includes(selector.slice(1)) : e.tagName === selector;
    return this.children.flatMap(e => [...(matches(e) ? [e] : []), ...e.querySelectorAll(selector)]);
  }
  getBoundingClientRect() { return {top: 0, bottom: 10, height: 10}; }
  scrollIntoView(options) { scrolls.push([this, options]); }
  load() { this.error = null; this.loads++; const wasPlaying = !this.paused; this.readyState = 0; this.currentTime = 0; this.paused = true; this.ended = false; if (wasPlaying) queueMicrotask(() => this.fire("pause")); }
  pause() { this.pauses++; const changed = !this.paused; this.paused = true; if (changed) queueMicrotask(() => this.fire("pause")); }
  play() { this.plays++; const changed = this.paused; this.paused = false; if (changed) queueMicrotask(() => this.fire("play")); return Promise.resolve(); }
}
const elements = new Map();
const $ = (name) => {
  if (!elements.has(name)) elements.set(name, new Element(name === "video" ? "video" : "div"));
  return elements.get(name);
};
const documentEvents = {};
global.document = {visibilityState: "visible", pictureInPictureEnabled: false,
  getElementById: id => id === "listen-title-editor" && location.pathname === "/watch" ? null : $(id.replace(/^listen-/, "")),
  createElement: tag => new Element(tag),
  createTextNode: text => {const e = new Element("text"); e.textContent = text; return e;},
  addEventListener: (name, fn) => (documentEvents[name] ||= []).push(fn),
  dispatchEvent: event => {for (const fn of documentEvents[event.type] || []) fn(event); return true;},
  querySelectorAll: () => []};
const windowEvents = {};
global.addEventListener = (name, fn) => (windowEvents[name] ||= []).push(fn);
global.dispatchEvent = event => { for (const fn of windowEvents[event.type] || []) fn(event); return true; };
const sessionActions = {}, logBatches = [], beacons = [];
Object.defineProperty(global, "navigator", {configurable: true, value: {
  userActivation: {isActive: true},
  mediaSession: {setActionHandler: (name, fn) => sessionActions[name] = fn}, sendBeacon: (path, body) => {beacons.push(body); return true;}}});
global.MediaMetadata = class { constructor(data) { Object.assign(this, data); } };
const storage = new Map();
global.localStorage = {getItem: k => storage.get(k) || null, setItem: (k, v) => storage.set(k, v)};
const jumpLabel = new Element("label"); jumpLabel.append(document.createTextNode("Tới tập "), $("jump"));
for (const kind of ["short", "khaithi", "both"]) { const b = new Element("button"); b.dataset.kind = kind; $("filter").append(b); }
$("resume").hidden = true;
let sourceItems = [], commands = [], requests = [], titleCalls = [], respond = null;
const episodeViews = new Map();
global.location = {pathname: "/playlists/PLtest/favorites", origin: "http://test"};
global.fetch = async (path, options = {}) => {
  requests.push(path);
  if (path === "/api/watch/log") { logBatches.push(JSON.parse(options.body)); return {ok: true, json: async () => ({ok: true})}; }
  if (path.includes("/title")) titleCalls.push({path, body: JSON.parse(options.body)});
  const custom = respond && await respond(path, options);
  if (custom) return custom;
  if (options.method === "POST" && path.endsWith("/favorites")) {
    const body = JSON.parse(options.body);
    const found = sourceItems.find(item => item.episode_id === body.episode_id && item.clip_id === body.clip);
    if (found) found.fav.favorite = body.favorite;
  }
  return {ok: true, json: async () => structuredClone(path.includes("/listen")
    ? {playlist_id: "PLtest", title: "Bộ kinh", items: sourceItems.filter(item => !path.includes("favorites=1") || item.fav.favorite)}
    : path.endsWith("/title/preview") ? {display_lines: [JSON.parse(options.body).text], font_size: 50}
    : path.endsWith("/title") ? {preview: {title: JSON.parse(options.body).set?.trim() || "Tiêu đề AI"}}
    : episodeViews.get(path.split("/").at(-1)) || {id: "ep1", base_episode_id: "ep1", favorites: {playlist_id: "PLtest"}})};
};
global.AutoShortWatch = {client: "a", room: {}, sent: async () => {}, poll() {}, command: async (action, data) => {commands.push({action, ...data});}};
eval(fs.readFileSync("src/auto_short/web/static/player.js", "utf8"));
const Player = AutoShortPlayer;
let activePlayer;
global.AutoShortPlayer = class extends Player { constructor(...args) { super(...args); activePlayer = this; } };
eval(fs.readFileSync("src/auto_short/web/static/app.js", "utf8"));
eval(fs.readFileSync("src/auto_short/web/static/title_editor.js", "utf8"));
function item(ep, n, kind = "short") {
  return {episode_id: `ep${ep}${kind === "khaithi" ? ".kt" : ""}`, base_episode_id: `ep${ep}`, ep_index: ep,
    kind, clip_id: `k${n}`, title: `Bài ${n}`, video_url: `/files/ep${ep}${kind === "khaithi" ? ".kt" : ""}/k${n}.mp4`,
    fav: {playlist_id: "PLtest", episode_id: `ep${ep}`, clip: `k${n}`, favorite: true}};
}
// Stateful transport double: set preserves the previous room's auto, as WatchRoom does.
let serverRoom;
function useRoom(oldAuto = false) {
  serverRoom = {auto: oldAuto, queue: [], index: 0, position: 0, rate: 1, paused: true, version: 0, updated_at: now / 1000};
  let queueVersion = 0;
  function snapshot() {
    const entry = serverRoom.queue[serverRoom.index];
    const original = sourceItems.find(item => item.video_url === entry?.url);
    return structuredClone({...serverRoom, queue_version: String(queueVersion), video_url: entry?.url || null, title: entry?.title,
      fav: original?.fav, server_time: now / 1000, by: serverRoom.by || "a"});
  }
  function publish(data = snapshot()) {
    AutoShortWatch.room.handler(data, true);
    return data;
  }
  function apply(action, data, by = "a") {
    if (["next", "prev"].includes(action) && data.expect_version !== serverRoom.version) {
      throw Object.assign(new Error("conflict"), {status: 409});
    }
    if (!serverRoom.paused) serverRoom.position += (now / 1000 - serverRoom.updated_at) * serverRoom.rate;
    serverRoom.updated_at = now / 1000;
    if (action === "set") { Object.assign(serverRoom, structuredClone(data)); queueVersion++; }
    else if (action === "auto") serverRoom.auto = data.auto;
    else if (["next", "prev"].includes(action)) {
      serverRoom.index += action === "next" ? 1 : -1; serverRoom.position = 0; serverRoom.paused = false;
    }
    else if (action === "goto") {serverRoom.index = data.index; serverRoom.position = 0; serverRoom.paused = false;}
    else if (["play", "pause", "rate", "seek"].includes(action)) {
      if (data.position != null) serverRoom.position = data.position;
      if (action === "rate") serverRoom.rate = data.rate;
      if (["play", "pause"].includes(action)) serverRoom.paused = action === "pause";
    } else if (action === "ended") {
      serverRoom.position = data.position; serverRoom.paused = true; serverRoom.finished = true;
      const next = serverRoom.queue[serverRoom.index + 1], current = serverRoom.queue[serverRoom.index];
      serverRoom.advance_at = serverRoom.auto && next && next.group?.id === current.group?.id ? now / 1000 + 3 : null;
    }
    if (["next", "prev", "goto", "play"].includes(action)) {serverRoom.finished = false; serverRoom.advance_at = null;}
    serverRoom.by = by;
    serverRoom.version++;
    return snapshot();
  }
  AutoShortWatch.command = async (action, data) => {
    commands.push(structuredClone({action, ...data}));
    return publish(apply(action, data));
  };
  AutoShortWatch.poll = async () => publish();
  return {snapshot, apply};
}
// Opt into the real watch.js command serialization, conflict poll and queue cache, with an in-memory server.
let roomReads = [], interceptRoom = null;
function useRoomTransport(auto = true, initial = {}) {
  const backend = useRoom(auto); Object.assign(serverRoom, initial);
  document.body = new Element("body");
  global.sessionStorage = {getItem: () => "a", setItem() {}};
  global.MutationObserver = class { observe() {} };
  const fallback = global.fetch;
  global.fetch = async (path, options = {}) => {
    if (!path.startsWith("/api/watch") || path === "/api/watch/log") return fallback(path, options);
    const body = options.body ? JSON.parse(options.body) : null;
    if (body) commands.push(structuredClone(body)); else roomReads.push(path);
    const custom = interceptRoom && await interceptRoom(body, backend);
    if (custom) return custom;
    try {
      const data = body ? backend.apply(body.action, body, body.client) : backend.snapshot();
      return {ok: true, json: async () => data};
    } catch (error) { return {ok: false, status: error.status, json: async () => ({detail: error.message})}; }
  };
  eval(fs.readFileSync("src/auto_short/web/static/watch.js", "utf8"));
  return backend;
}
async function settled() { for (let i = 0; i < 8; i++) await new Promise(setImmediate); }
async function boot() { eval(fs.readFileSync("src/auto_short/web/static/listen.js", "utf8")); await settled(); }
async function metadata(media) {
  for (const current of media ? [media] : [activePlayer.audio, $("video")]) {
    current.readyState = 1; await current.fire("loadedmetadata");
    if (current === $("video")) { current.readyState = 4; await current.fire("canplay"); }
  }
  await settled();
}
async function end(media = activePlayer.media()) { media.ended = true; media.paused = true; media.currentTime = media.duration; await media.fire("ended"); }
async function visibility(hidden) { document.visibilityState = hidden ? "hidden" : "visible"; document.dispatchEvent(new Event("visibilitychange")); await settled(); }
function titleView(eid, shorts = sourceItems.filter(i => i.episode_id === eid)) {
  const view = {id: eid, base_episode_id: eid.replace(/\.kt$/, ""), favorites: {playlist_id: "PLtest"}, max_title_chars: 60,
    shorts: shorts.map(i => ({clip_id: i.clip_id, editable: true, deleted: false, title: {text: i.title},
      ai_title: "Tiêu đề AI", alternatives: [{n: 1, title: "Phương án khác"}], override: {title: i.title}}))};
  episodeViews.set(eid, view); return view;
}
const editorInput = () => $("title-editor").querySelectorAll("input")[0];
const editorButton = text => $("title-editor").querySelectorAll("button").find(e => e.textContent === text);
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
activePlayer.seek(17, activePlayer.audio); await activePlayer.audio.fire("timeupdate");
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
await $("play").fire("click"); activePlayer.seek(29, activePlayer.audio);
tick(4000); await activePlayer.audio.fire("timeupdate");
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
activePlayer.seek(17, activePlayer.audio); await activePlayer.audio.fire("timeupdate");
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


@pytest.mark.parametrize("page", ["/episodes/ep1", "/playlists/PLtest/favorites"])
@pytest.mark.parametrize("background", [False, True])
def test_player_js_shared_title_editor_saves_without_reloading(run_player_js, page, background):  # LISTEN2 AC 1–3
    run_player_js(r'''
location.pathname = PAGE;
sourceItems = [item(1, 1), item(1, 2)];
titleView("ep1");
await boot(); await metadata(); await $("play").fire("click");
assert.equal(titleCalls.length, 0);
assert.equal(requests.filter(p => p === "/api/episodes/ep1").length, PAGE.startsWith("/episodes") ? 1 : 0);
await $("title-editor").firstChild.fire("click"); await settled();
assert.equal(editorInput().value, "Bài 1");
assert.match($("title-editor").textContent, /5\/60/);
assert.match($("title-editor").textContent, /1 dòng, chữ 50 px/);
if (BACKGROUND) { await visibility(true); await metadata(activePlayer.audio); }
const media = activePlayer.media(); activePlayer.seek(19.25, media);
const before = [media.src, activePlayer.position(media), media.loads, media.plays, media.pauses, activePlayer.sourceKey];
editorInput().value = "  Chữ mới  "; await editorInput().fire("input"); tick(350); await settled();
await editorButton("Lưu & render lại").fire("click"); await settled();
assert.deepEqual(titleCalls.at(-1), {path: "/api/episodes/ep1/shorts/k1/title", body: {set: "  Chữ mới  "}});
assert.deepEqual([media.src, activePlayer.position(media), media.loads, media.plays, media.pauses, activePlayer.sourceKey], before);
assert.equal(activePlayer.state.title, "Chữ mới"); assert.equal(navigator.mediaSession.metadata.title, "Chữ mới");
// A new draft must remain locked while the accepted render job runs.
editorInput().value = "Chờ job xong"; await editorInput().fire("input"); tick(350); await settled();
assert.ok(editorButton("Lưu & render lại").disabled);
assert.ok(!$("title-editor").querySelectorAll(".lock-note")[0].hidden);
if (BACKGROUND) await visibility(false);
assert.match($("title").textContent, /Chữ mới/); assert.match($("queue").textContent, /Chữ mới/);
// Regrouping favorites creates copies: both the source list and visible list must retain the edit.
await $("filter").children[0].fire("click"); await settled();
assert.match($("queue").textContent, /Chữ mới/);
await editorButton("Đóng").fire("click");
await $("title-editor").firstChild.fire("click"); await settled();
const select = $("title-editor").querySelectorAll("select")[0];
select.value = "1"; await select.fire("change"); tick(350); await settled();
assert.equal(editorInput().value, "Phương án khác");
respond = async path => path.endsWith("/title") ? {ok: true, json: async () => ({preview: {title: "Phương án khác"}})} : null;
await editorButton("Lưu & render lại").fire("click"); await settled();
assert.deepEqual(titleCalls.at(-1).body, {alternative: 1}); assert.match($("title").textContent, /Phương án khác/);
await editorButton("Đóng").fire("click"); await $("title-editor").firstChild.fire("click"); await settled();
respond = null;
await editorButton("Khôi phục title AI").fire("click"); await settled();
assert.deepEqual(titleCalls.at(-1).body, {reset: true}); assert.match($("title").textContent, /Tiêu đề AI/);
// Management and listening use the single exported implementation; its lock can change while open.
let locked = true, saved = 0;
const box = AutoShort.titleEditor(episodeViews.get("ep1").shorts[0], {
  episodeId: "ep1", locked: () => locked, maxChars: 60, onSaved: () => saved++,
});
await box.firstChild.fire("click"); await settled();
const buttons = box.querySelectorAll("button"), save = buttons.find(b => b.textContent === "Lưu & render lại");
assert.ok(save.disabled); assert.ok(buttons.find(b => b.textContent === "Khôi phục title AI").disabled);
locked = false; const input = box.querySelectorAll("input")[0]; input.value = "Quản lý";
await input.fire("input"); tick(350); await settled(); await save.fire("click"); await settled();
assert.equal(saved, 1);
'''.replace("PAGE", json.dumps(page)).replace("BACKGROUND", json.dumps(background)))


@pytest.mark.parametrize("condition", ["uneditable", "deleted", "job", "restore_job", "errors"])
def test_player_js_title_eligibility_locks_errors_and_restore(run_player_js, condition):  # LISTEN2 AC 1,2
    run_player_js(r'''
sourceItems = [item(1, 1)]; const view = titleView("ep1"), condition = CONDITION;
if (condition === "uneditable") view.shorts[0].editable = false;
if (condition === "deleted") view.shorts[0].deleted = true;
if (["job", "restore_job"].includes(condition)) view[condition] = {status: "running"};
await boot(); await metadata();
await $("title-editor").firstChild.fire("click"); await settled();
if (["uneditable", "deleted"].includes(condition)) {
  assert.ok($("title-editor").hidden); assert.equal(editorInput(), undefined); assert.equal(titleCalls.length, 0); return;
}
const save = editorButton("Lưu & render lại"), reset = editorButton("Khôi phục title AI");
if (condition !== "errors") {
  assert.ok(save.disabled); assert.ok(reset.disabled);
  assert.ok(!$("title-editor").querySelectorAll(".lock-note")[0].hidden);
  await save.fire("click"); await reset.fire("click"); assert.ok(titleCalls.every(c => c.path.endsWith("/preview")));
  // Close/open fetches fresh job state, so a finished job does not leave the editor locked forever.
  await editorButton("Đóng").fire("click"); view[condition].status = "done";
  await $("title-editor").firstChild.fire("click"); await settled(); assert.ok(!editorButton("Lưu & render lại").disabled); return;
}
respond = async path => path.endsWith("/preview") ? {ok: false, status: 422, json: async () => ({detail: "Tiêu đề quá dài"})} : null;
editorInput().value = "x".repeat(61); await editorInput().fire("input"); tick(350); await settled();
assert.match($("title-editor").textContent, /61\/60/); assert.match($("title-editor").textContent, /Tiêu đề quá dài/); assert.ok(save.disabled);
respond = null; editorInput().value = "Tiêu đề hợp lệ"; await editorInput().fire("input"); tick(350); await settled();
for (const status of [409, 422]) {
  respond = async path => path.endsWith("/title") ? {ok: false, status, json: async () => ({detail: `Lỗi ${status}`})} : null;
  await save.fire("click"); await settled(); assert.match($("title-editor").textContent, new RegExp(`Lỗi ${status}`)); assert.ok(!save.disabled);
}
respond = async path => path.endsWith("/title") ? {ok: true, json: async () => ({queued: "restore"})} : null;
await save.fire("click"); await settled();
assert.match($("title-editor").textContent, /Đang lấy lại nguồn từ 3090/);
assert.match($("title").textContent, /Tiêu đề hợp lệ/); assert.match($("queue").textContent, /Tiêu đề hợp lệ/);
'''.replace("CONDITION", json.dumps(condition)))


def test_player_js_title_ignores_late_reads_previews_and_saves(run_player_js):  # LISTEN2 AC 4
    run_player_js(r'''
sourceItems = [item(1, 1), item(2, 1), item(2, 2), item(3, 1)];
for (const eid of ["ep1", "ep2", "ep3"]) titleView(eid);
let releaseRead;
respond = path => path === "/api/episodes/ep1" ? new Promise(resolve => releaseRead = () => resolve({ok: true, json: async () => episodeViews.get("ep1")})) : null;
await boot(); await metadata();
const opening = $("title-editor").firstChild.fire("click"); await settled();
await $("next").fire("click"); await metadata();
assert.equal(editorInput().value, "Bài 1");
releaseRead(); await opening; await settled();
assert.equal(activePlayer.state.episode_id, "ep2"); assert.equal(editorInput().value, "Bài 1");
assert.ok(titleCalls.every(c => !c.path.includes("/ep1/")));
const reads = requests.filter(p => p === "/api/episodes/ep2").length;
editorInput().value = "Bản nháp cũ"; await editorInput().fire("input");
await $("next").fire("click"); await metadata(); tick(350); await settled();
assert.equal(editorInput().value, "Bài 2");
assert.equal(requests.filter(p => p === "/api/episodes/ep2").length, reads); // episode cache
assert.ok(!titleCalls.some(c => c.body.text === "Bản nháp cũ")); // disposed debounce never submits
let releasePreview;
respond = (path, options) => path.endsWith("/preview") && JSON.parse(options.body).text === "Chờ kiểm tra"
  ? new Promise(resolve => releasePreview = () => resolve({ok: true, json: async () => ({display_lines: ["LATE"], font_size: 10})})) : null;
editorInput().value = "Chờ kiểm tra"; await editorInput().fire("input"); tick(350); await settled();
await $("next").fire("click"); await metadata();
releasePreview(); await settled();
assert.equal(editorInput().value, "Bài 1"); assert.ok(!$("title-editor").textContent.includes("LATE"));
respond = null; editorInput().value = "Lưu bài tập ba"; await editorInput().fire("input"); tick(350); await settled();
let releaseSave;
respond = path => path.endsWith("/title") ? new Promise(resolve => releaseSave = () => resolve({ok: true, json: async () => ({preview: {title: "Lưu bài tập ba"}})})) : null;
const saving = editorButton("Lưu & render lại").fire("click"); await settled();
await $("prev").fire("click"); await metadata();
const input = editorInput(); input.value = "Đang sửa bài khác";
releaseSave(); await saving; await settled();
assert.equal(editorInput(), input); assert.equal(input.value, "Đang sửa bài khác");
assert.equal(activePlayer.state.episode_id, "ep2"); assert.match($("title").textContent, /Bài 2/);
assert.equal(titleCalls.filter(c => c.path.endsWith("/title")).at(-1).path, "/api/episodes/ep3/shorts/k1/title");
await $("next").fire("click"); await metadata(); assert.match($("title").textContent, /Lưu bài tập ba/);
// Joining a room resets the old draft while awaiting room state, then offers the lazy room editor (Amendment B).
useRoom(); const count = requests.filter(p => p.startsWith("/api/episodes/")).length;
await $("watch").fire("click"); await settled();
assert.ok(!$("title-editor").hidden); assert.equal($("title-editor").firstChild.textContent, "Sửa tiêu đề");
assert.equal(editorInput(), undefined);
assert.equal(requests.filter(p => p.startsWith("/api/episodes/")).length, count);
''')


@pytest.mark.parametrize("room", [False, True])
@pytest.mark.parametrize("mode", ["seeking", "canplay", "seeked", "ready"])
def test_player_js_video_drift_waits_for_seek_and_data(run_player_js, room, mode):  # FIX-listen-video-seek-loop AC1–3
    run_player_js(r'''
sourceItems = [item(1, 1)];
if (ROOM) useRoomTransport();
await boot(); await metadata(); await $("play").fire("click"); await settled();
if (ROOM) { await $("watch").fire("click"); await settled(); await metadata(); }
const video = $("video"), audio = activePlayer.audio;
const controls = ROOM ? commands.length : activePlayer.state.version;
let position = video.currentTime, seeks = 0;
Object.defineProperty(video, "currentTime", {
  get: () => position,
  set: value => { position = value; seeks++; video.seeking = true; }
});
video.readyState = MODE === "canplay" || MODE === "seeked" ? 2 : 4;
video.seeking = false; video.paused = true;
const plays = video.plays;
activePlayer.seek(10, audio); audio.playbackRate = 1.25;
await audio.fire("timeupdate"); await settled();
assert.equal(video.plays, plays + 1); assert.ok(!audio.paused); assert.ok(!video.paused);
assert.equal(video.playbackRate, 1.25); assert.ok(video.muted);
if (MODE === "canplay" || MODE === "seeked") {
  assert.equal(seeks, 0);
  for (let n = 0; n < 5; n++) await audio.fire("timeupdate");
  assert.equal(seeks, 0);
  video.readyState = 4; await video.fire(MODE); await settled();
}
assert.equal(seeks, 1); assert.equal(video.currentTime, 10);
if (MODE === "seeking") {
  for (let n = 1; n <= 8; n++) {
    activePlayer.seek(10 + n, audio); await audio.fire("timeupdate");
  }
  activePlayer.syncVideo(true); // Force cannot interrupt an outstanding seek either.
  assert.equal(seeks, 1);
  video.seeking = false; await video.fire("seeked"); await settled();
  assert.equal(seeks, 2); assert.equal(video.currentTime, 18);
}
video.seeking = false; await video.fire("seeked"); await audio.fire("timeupdate"); await settled();
assert.equal(seeks, MODE === "seeking" ? 2 : 1);
assert.equal(ROOM ? commands.length : activePlayer.state.version, controls);
const events = [...logBatches.flatMap(b => b.events), ...activePlayer.events];
assert.equal(events.filter(e => e.type === "video_resync").length, 1);
'''.replace("ROOM", json.dumps(room)).replace("MODE", json.dumps(mode)))


@pytest.mark.parametrize("event", ["loadedmetadata", "visibilitychange"])
def test_player_js_video_force_seeks_before_canplay(run_player_js, event):  # FIX-listen-video-seek-loop preserved force
    run_player_js(r'''
sourceItems = [item(1, 1)];
await boot(); await metadata();
const video = $("video"), audio = activePlayer.audio;
video.readyState = 2; video.seeking = false;
activePlayer.seek(12, audio);
if (EVENT === "loadedmetadata") await video.fire(EVENT);
else await visibility(false);
assert.equal(video.currentTime, 12);
video.seeking = true; activePlayer.seek(20, audio);
if (EVENT === "loadedmetadata") await video.fire(EVENT);
else await visibility(false);
assert.equal(video.currentTime, 12);
'''.replace("EVENT", json.dumps(event)))


@pytest.mark.parametrize("room", [False, True])
def test_player_js_audio_clock_survives_visibility_and_video_controls(run_player_js, room):  # Amendment C AC5',7,9
    run_player_js(r'''
sourceItems = [item(1, 1), item(1, 2)];
if (ROOM) useRoomTransport();
await boot(); await metadata($("video")); // Audio metadata has deliberately not arrived yet.
if (ROOM) { await $("watch").fire("click"); await settled(); }
const video = $("video"), audio = activePlayer.audio;
assert.equal(activePlayer.media(), audio); assert.ok(video.muted); assert.equal(audio.plays, 0);
await video.play(); await settled(); // The first native video Play starts audio while the page is visible.
assert.ok(audio.plays > 0); assert.equal(audio.readyState, 0);
sessionActions.pause(); await settled(); assert.ok(audio.paused); assert.ok(video.paused);
await video.play(); await settled(); await metadata(audio);
assert.ok(!audio.paused); assert.ok(!activePlayer.state.paused);
video.currentTime = 17.25; await video.fire("seeked"); await settled();
video.playbackRate = 1.5; await video.fire("ratechange"); await settled();
assert.equal(activePlayer.position(audio), 17.25); assert.equal(audio.playbackRate, 1.5);
// Mirroring the clock / rate cannot echo another action back to the audio / room.
const controls = ROOM ? commands.length : activePlayer.state.version;
video.currentTime = 2; video.playbackRate = 1; await audio.fire("timeupdate");
await video.fire("seeked"); await video.fire("ratechange"); await settled();
assert.equal(video.currentTime, 17.25); assert.equal(ROOM ? commands.length : activePlayer.state.version, controls);
for (let n = 0; n < 10; n++) { video.currentTime = 0; await audio.fire("timeupdate"); await video.fire("seeked"); }
assert.equal([...logBatches.flatMap(b => b.events), ...activePlayer.events].filter(e => e.type === "video_resync").length, 1);
const before = [audio.src, activePlayer.position(audio), audio.plays, audio.pauses, audio.loads];
await visibility(true); video.paused = true; await video.fire("pause"); await visibility(true);
assert.deepEqual([audio.src, activePlayer.position(audio), audio.plays, audio.pauses, audio.loads], before);
assert.ok(!audio.paused); assert.ok(!activePlayer.state.paused); assert.ok(video.paused);
activePlayer.seek(31.5, audio); tick(4000); await audio.fire("timeupdate");
if (!ROOM) assert.equal(JSON.parse(storage.get("auto-short-listen-position:PLtest:fav")).position, 31.5);
video.currentTime = 2; await video.fire("timeupdate");
if (!ROOM) assert.equal(JSON.parse(storage.get("auto-short-listen-position:PLtest:fav")).position, 31.5);
sessionActions.nexttrack(); await settled();
assert.equal(audio.src, sourceItems[1].video_url.replace(".mp4", ".m4a")); assert.equal(video.src, audio.src.replace(".m4a", ".mp4")); assert.ok(!audio.paused);
await metadata(); sessionActions.pause(); await settled(); assert.ok(audio.paused); assert.ok(activePlayer.state.paused);
sessionActions.play(); await settled(); assert.ok(!audio.paused); assert.ok(!activePlayer.state.paused);
sessionActions.previoustrack(); await settled(); await metadata();
assert.equal(audio.src, sourceItems[0].video_url.replace(".mp4", ".m4a")); assert.equal(video.src, audio.src.replace(".m4a", ".mp4"));
activePlayer.seek(44.75, audio); audio.playbackRate = 1.25; await audio.fire("ratechange"); await settled();
const playing = [activePlayer.position(audio), audio.plays, audio.pauses, audio.loads];
await visibility(false);
assert.equal(activePlayer.media(), audio); assert.deepEqual([activePlayer.position(audio), audio.plays, audio.pauses, audio.loads], playing);
assert.ok(!audio.paused); assert.ok(!video.paused); assert.ok(video.muted);
assert.equal(video.currentTime, 44.75); assert.equal(video.playbackRate, 1.25);
assert.equal(navigator.mediaSession.playbackState, "playing");
video.muted = false; await video.fire("volumechange"); assert.ok(video.muted);
// Native visible Pause is forwarded once; audio Pause is programmed so it cannot echo.
if (ROOM) { tick(1600); await settled(); } // Outside WATCH1's existing visibility transition grace.
await video.pause(); await settled();
if (ROOM) { assert.ok(activePlayer.syncBlocked); tick(1500); await settled(); }
assert.ok(audio.paused); assert.ok(activePlayer.state.paused);
await video.play(); await settled(); assert.ok(!audio.paused); assert.ok(!activePlayer.state.paused);
const events = [...logBatches.flatMap(b => b.events), ...activePlayer.events];
assert.ok(events.some(e => e.type === "video_resync")); assert.ok(!events.some(e => ["to_audio", "to_video"].includes(e.type)));
assert.ok(!events.some(e => e.type === "pause_hidden")); // The browser's muted-video pause never starts audio recovery.
'''.replace("ROOM", json.dumps(room)))


@pytest.mark.parametrize("room", [False, True])
def test_player_js_padded_audio_keeps_external_content_clock(run_player_js, room):  # Amendment G AC15
    run_player_js(r'''
sourceItems = [item(1, 1), item(1, 2)];
if (ROOM) useRoomTransport();
await boot(); await metadata(); await $("play").fire("click");
if (ROOM) { await $("watch").fire("click"); await settled(); await metadata(); }
const audio = activePlayer.media(), video = $("video");
assert.equal(audio.currentTime, 1.5); assert.equal(activePlayer.position(), 0);
audio.currentTime = 21.5; tick(4000); await audio.fire("timeupdate"); await settled();
assert.equal(video.currentTime, 20);
if (!ROOM) assert.equal(JSON.parse(storage.get("auto-short-listen-position:PLtest:fav")).position, 20);
video.currentTime = 7.25; await video.fire("seeked"); await settled();
assert.equal(audio.currentTime, 8.75);
if (ROOM) assert.equal(commands.filter(c => c.action === "seek").at(-1).position, 7.25);
sessionActions.pause(); await settled();
assert.equal(activePlayer.state.position, 7.25); assert.ok(audio.paused);
sessionActions.play(); await settled();
audio.currentTime = 23.5; await audio.fire("timeupdate"); await visibility(true);
assert.equal([...logBatches.flatMap(b => b.events), ...activePlayer.events].filter(e => e.type === "visibility").at(-1).t, 22);
audio.error = {code: 3}; await audio.fire("error"); await settled(); await metadata(audio);
assert.equal(activePlayer.pad(), 0); assert.equal(audio.currentTime, 22); assert.equal(activePlayer.position(), 22);
if (ROOM) { serverRoom.position = 22; serverRoom.updated_at = now / 1000; }
await visibility(false); assert.equal(video.currentTime, 22);
video.currentTime = 9; await video.fire("seeked"); await settled(); assert.equal(audio.currentTime, 9);
'''.replace("ROOM", json.dumps(room)))


@pytest.mark.parametrize("page,room", [("/episodes/ep1", False), ("/playlists/PLtest/favorites", False),
                                      ("/playlists/PLtest/favorites", True), ("/watch", True)])
def test_player_js_hidden_early_start_reuses_preloaded_audio(run_player_js, page, room):  # Amendment G AC15
    run_player_js(r'''
location.pathname = PAGE;
sourceItems = [item(1, 1), item(2, 1), item(3, 1)]; // Cross episode / favorites part boundaries.
const queue = sourceItems.map(i => ({url: i.video_url, title: i.title}));
if (ROOM) useRoomTransport(true, PAGE === "/watch" ? {queue, paused: false} : {});
await boot(); await metadata();
if (PAGE !== "/watch") {
  await $("play").fire("click");
  if (ROOM) { await $("watch").fire("click"); await settled(); await metadata(); }
}
await visibility(true);
let old = activePlayer.media(), next = activePlayer.audios.find(a => a !== old);
assert.equal(next.src, "/files/ep2/k1.m4a"); assert.equal(next.preload, "auto"); assert.ok(next.paused);
await metadata(next); assert.equal(activePlayer.media(), old); // Preload events cannot change the active player.
const loads = next.loads, plays = next.plays, oldPauses = old.pauses, version = activePlayer.state.version;
let release;
const nativePlay = next.play.bind(next);
next.play = () => { nativePlay(); return new Promise(resolve => release = resolve); };
old.currentTime = old.duration - .51; await old.fire("timeupdate"); assert.equal(next.plays, plays);
old.currentTime = old.duration - .5; await old.fire("timeupdate");
assert.equal(next.currentTime, 0); assert.equal(next.volume, 1); assert.equal(next.plays, plays + 1);
assert.equal(next.loads, loads); assert.equal(old.pauses, oldPauses); assert.ok(!old.paused);
assert.equal(activePlayer.state.index, 0);
await old.fire("timeupdate"); assert.equal(next.plays, plays + 1); // One pending attempt.
release(); await settled(); next.play = nativePlay;
assert.equal(activePlayer.media(), next); assert.equal(activePlayer.state.index, 1);
assert.equal(activePlayer.sourceKey, JSON.stringify([1, sourceItems[1].video_url]));
assert.equal(next.loads, loads); assert.equal(next.currentTime, 0); assert.equal(next.volume, 1);
assert.ok(!next.paused); assert.ok(old.paused); assert.ok(old.pauses > oldPauses);
assert.equal($("video").src, sourceItems[1].video_url); assert.ok($("video").muted);
if (ROOM) {
  assert.deepEqual(commands.filter(c => c.action === "next").map(c => c.expect_version), [version]);
  assert.ok(!commands.some(c => c.action === "ended"));
  await AutoShortWatch.poll(true); assert.equal(next.loads, loads);
}
await metadata(next); assert.equal(next.currentTime, 0); // Metadata must preserve the leading silence.
next.currentTime = 3.75; tick(4000); await next.fire("timeupdate");
if (!ROOM) assert.equal(JSON.parse(storage.get(`auto-short-listen-position:PLtest${PAGE.includes("favorites") ? ":fav" : ""}`)).position, 2.25);
const events = [...logBatches.flatMap(b => b.events), ...activePlayer.events];
assert.equal(events.filter(e => e.type === "early_start").length, 1);
assert.equal(events.filter(e => e.type === "hidden_advance").length, 1);
// The former active element is now preloaded for the third track; its listeners also work after reuse.
assert.equal(old.src, "/files/ep3/k1.m4a"); const oldLoads = old.loads;
next.currentTime = next.duration - .5; await next.fire("timeupdate"); await settled();
assert.equal(activePlayer.media(), old); assert.equal(activePlayer.state.index, 2); assert.equal(old.loads, oldLoads);
await metadata(old); old.currentTime = 5.5; await old.fire("timeupdate");
if (ROOM) {
  serverRoom.position = 4; serverRoom.updated_at = now / 1000; await AutoShortWatch.poll(true);
}
await visibility(false); await metadata($("video"));
assert.equal($("video").currentTime, 4); assert.ok(!old.paused); assert.ok(!$("video").paused);
'''.replace("PAGE", json.dumps(page)).replace("ROOM", json.dumps(room)))


@pytest.mark.parametrize("mode", ["rejected", "ended_first", "ended_blocked", "pending_ended", "pause", "auto_off", "visible", "next", "suspend", "seek", "visible_after_end", "auto_off_after_end"])
def test_player_js_early_start_failure_end_and_cancellation(run_player_js, mode):  # Amendment G AC15
    run_player_js(r'''
sourceItems = [item(1, 1), item(1, 2), item(1, 3)];
await boot(); await metadata(); await $("play").fire("click"); await visibility(true);
const old = activePlayer.media(), next = activePlayer.audios.find(a => a !== old), loads = next.loads;
const mode = MODE;
if (["ended_first", "ended_blocked"].includes(mode)) {
  if (mode === "ended_blocked") {
    const nativePlay = next.play.bind(next); let calls = 0;
    next.play = () => ++calls === 1 ? Promise.reject(Object.assign(new Error("blocked"), {name: "NotAllowedError"})) : nativePlay();
  }
  const ending = end(old); // No early timeupdate: play the preloaded element synchronously inside ended.
  assert.equal(activePlayer.media(), next); assert.equal(activePlayer.state.index, 1);
  assert.equal(next.loads, loads); assert.equal(next.currentTime, 0);
  if (mode === "ended_first") assert.ok(!next.paused);
  await ending; await settled();
  if (mode === "ended_blocked") { assert.ok(next.paused); tick(1000); await settled(); assert.ok(!next.paused); }
} else if (mode === "rejected") {
  next.play = () => Promise.reject(Object.assign(new Error("blocked"), {name: "NotAllowedError"}));
  old.currentTime = old.duration - .5; await old.fire("timeupdate"); await settled();
  assert.equal(activePlayer.media(), old); assert.ok(!old.paused); assert.equal(activePlayer.state.index, 0);
  assert.ok([...logBatches.flatMap(b => b.events), ...activePlayer.events].some(e => e.type === "early_blocked" && e.err === "NotAllowedError"));
  await end(old); await settled(); // Failed early start keeps the previous load + play path.
  assert.equal(activePlayer.state.index, 1); assert.equal(activePlayer.media(), old); assert.ok(!old.paused);
  await metadata(old); old.pause(); await settled(); tick(1000); await settled(); assert.ok(!old.paused);
} else {
  let release;
  const nativePlay = next.play.bind(next);
  next.play = () => { nativePlay(); return new Promise(resolve => release = resolve); };
  old.currentTime = old.duration - .5; await old.fire("timeupdate");
  if (["pending_ended", "visible_after_end", "auto_off_after_end"].includes(mode)) { await end(old); assert.equal(activePlayer.state.index, 0); }
  if (mode === "pause") { sessionActions.pause(); await settled(); }
  if (["auto_off", "auto_off_after_end"].includes(mode)) { $("auto").checked = false; await $("auto").fire("change"); }
  if (["visible", "visible_after_end"].includes(mode)) await visibility(false);
  if (mode === "seek") { $("video").currentTime = 10; await $("video").fire("seeked"); }
  if (mode === "next") { sessionActions.nexttrack(); await settled(); }
  if (mode === "suspend") activePlayer.suspend();
  release(); await settled();
  assert.equal(activePlayer.state.index, ["next", "pending_ended"].includes(mode) ? 1 : 0);
  if (mode !== "pending_ended") { assert.equal(activePlayer.media(), old); assert.ok(next.paused); }
  else { assert.equal(activePlayer.media(), next); assert.equal(next.loads, loads); }
  if (["visible_after_end", "auto_off_after_end"].includes(mode)) assert.ok(activePlayer.state.paused);
  if (mode === "visible_after_end") {
    assert.ok(activePlayer.localAdvanceAt != null); tick(3000); await settled(); assert.equal(activePlayer.state.index, 1);
  }
}
'''.replace("MODE", json.dumps(mode)))


@pytest.mark.parametrize("room", [False, True])
@pytest.mark.parametrize("failure", ["404", "503", "decode"])
def test_player_js_audio_only_source_and_one_fallback_per_track(run_player_js, room, failure):  # Amendment F AC14
    run_player_js(r'''
sourceItems = [item(1, 1), item(1, 2)];
sourceItems[0].video_url += "?v=abc123";
if (ROOM) useRoom();
await boot();
if (ROOM) { await $("watch").fire("click"); await settled(); }
const audio = activePlayer.audio, video = $("video");
assert.equal(audio.src, "/files/ep1/k1.m4a?v=abc123");
assert.equal(video.src, "/files/ep1/k1.mp4?v=abc123"); assert.ok(video.muted);
await metadata(); await $("play").fire("click"); await settled();
activePlayer.seek(27.25, audio); audio.playbackRate = 1.5;
await audio.fire("ratechange"); await settled(); await visibility(true);
const key = activePlayer.sourceKey, videoLoads = video.loads, audioLoads = audio.loads;
// The media element reports HTTP failures as MEDIA_ERR_SRC_NOT_SUPPORTED (4).
audio.error = {code: FAILURE === "decode" ? 3 : 4};
await audio.fire("error"); await settled();
assert.equal(audio.src, "/files/ep1/k1.mp4?v=abc123");
assert.equal(audio.loads, audioLoads + 1); assert.equal(video.loads, videoLoads);
assert.equal(activePlayer.sourceKey, key); assert.ok(!audio.paused);
await metadata(audio); assert.equal(activePlayer.position(audio), 27.25); assert.equal(audio.playbackRate, 1.5);
await visibility(false); assert.equal(video.currentTime, 27.25);
audio.error = {code: 3}; await audio.fire("error"); assert.equal(audio.loads, audioLoads + 1);
if (ROOM) { await AutoShortWatch.poll(); assert.equal(audio.loads, audioLoads + 1); }
const events = [...logBatches.flatMap(b => b.events), ...activePlayer.events];
assert.equal(events.filter(e => e.type === "audio_fallback").length, 1);
sessionActions.nexttrack(); await settled();
assert.equal(audio.src, "/files/ep1/k2.m4a"); assert.equal(video.src, "/files/ep1/k2.mp4");
const loads = audio.loads;
await audio.fire("error"); assert.equal(audio.loads, loads); // A queued error from the old source has been cleared by load().
await metadata(); sessionActions.pause(); await settled();
if (ROOM) { tick(1500); await settled(); }
audio.error = {code: 4}; await audio.fire("error"); await settled();
assert.equal(audio.src, "/files/ep1/k2.mp4"); assert.ok(audio.paused); // Paused fallback never autoplays.
await metadata(audio); assert.ok(audio.paused);
'''.replace("ROOM", json.dumps(room)).replace("FAILURE", json.dumps(failure)))


def test_player_js_video_follows_new_source_and_ignores_late_play(run_player_js):  # Amendment C AC5'
    run_player_js(r'''
sourceItems = [item(1, 1), item(2, 1)];
await boot(); await metadata(); await $("play").fire("click");
const video = $("video"); let audio = activePlayer.audio;
activePlayer.seek(7, audio); await audio.fire("timeupdate"); await visibility(true);
await end(audio); audio = activePlayer.media();
assert.equal(video.src, sourceItems[1].video_url); assert.equal(video.src, audio.src.replace(".m4a", ".mp4")); assert.ok(video.muted);
await metadata(audio); activePlayer.seek(23.25, audio); audio.playbackRate = 1.75; await audio.fire("ratechange");
await metadata(video); assert.ok(video.paused); assert.ok(!audio.paused);
const nativePlay = video.play.bind(video); let releaseVideo;
video.play = () => { nativePlay(); return new Promise(resolve => releaseVideo = resolve); };
const before = [audio.src, activePlayer.position(audio), audio.plays, audio.pauses, audio.loads];
await visibility(false);
assert.equal(video.currentTime, 23.25); assert.equal(video.playbackRate, 1.75); assert.ok(!video.paused);
await visibility(true); video.paused = false; releaseVideo(); await settled();
assert.equal(activePlayer.media(), audio); assert.ok(!audio.paused); assert.ok(video.paused);
assert.deepEqual([audio.src, activePlayer.position(audio), audio.plays, audio.pauses, audio.loads], before);
await video.fire("loadedmetadata"); await video.fire("pause"); assert.ok(!activePlayer.state.paused);
video.play = nativePlay; await visibility(false);
assert.equal(video.currentTime, 23.25); assert.ok(!video.paused); assert.ok(!audio.paused);
''')


@pytest.mark.parametrize("cause", ["hide", "active", "inactive"])
def test_player_js_video_pause_requires_activation_or_visible_grace(run_player_js, cause):  # Amendment E AC12
    run_player_js(r'''
sourceItems = [item(1, 1), item(1, 2)]; await boot(); await metadata(); await $("play").fire("click");
const video = $("video"), audio = activePlayer.audio, actions = [], original = activePlayer.onAction, cause = CAUSE;
activePlayer.onAction = (action, ...args) => { actions.push(action); return original(action, ...args); };
navigator.userActivation = cause === "inactive" ? undefined : {isActive: cause === "active"};
video.pause(); await settled();
if (cause === "active") {
  assert.ok(audio.paused); assert.deepEqual(actions, ["pause"]);
  tick(2000); await settled(); assert.deepEqual(actions, ["pause"]); return;
}
assert.ok(!audio.paused); assert.deepEqual(actions, []);
tick(100); await audio.fire("timeupdate"); assert.ok(video.paused); // The mirror must preserve the grace window.
if (cause === "hide") {
  const plays = audio.plays, pauses = audio.pauses;
  await visibility(true); tick(2000); await settled();
  assert.ok(!audio.paused); assert.deepEqual(actions, []); assert.equal(audio.plays, plays); assert.equal(audio.pauses, pauses);
  await visibility(false); assert.ok(!video.paused); return;
}
tick(1399); await settled(); assert.ok(!audio.paused); assert.deepEqual(actions, []);
tick(1); await settled(); assert.ok(audio.paused); assert.deepEqual(actions, ["pause"]);
// A new track or explicit Play cancels an older deferred pause, including when audio is already playing.
await $("play").fire("click"); await settled(); video.pause(); await settled();
sessionActions.nexttrack(); await settled(); await metadata(); const pauses = actions.filter(a => a === "pause").length;
tick(2000); await settled(); assert.ok(!audio.paused); assert.equal(actions.filter(a => a === "pause").length, pauses);
video.pause(); await settled(); sessionActions.play(); await settled();
tick(2000); await settled(); assert.ok(!audio.paused); assert.ok(!video.paused);
assert.equal(actions.filter(a => a === "pause").length, pauses);
'''.replace("CAUSE", json.dumps(cause)))


@pytest.mark.parametrize("pause_at", ["before_hide", "while_hidden", "suspended", "suspended_audio"])
def test_player_js_paused_audio_never_starts_from_visibility(run_player_js, pause_at):  # Amendment C AC5'
    run_player_js(r'''
sourceItems = [item(1, 1)]; const when = PAUSE_AT;
await boot(); await metadata();
const video = $("video"), audio = activePlayer.audio;
if (when !== "before_hide") await $("play").fire("click");
activePlayer.seek(12, audio); await audio.fire("timeupdate");
if (when === "suspended") document.dispatchEvent(new CustomEvent("favorites-tab", {detail: "ai"}));
await visibility(true);
if (["suspended_audio", "while_hidden"].includes(when)) {
  activePlayer.seek(27, audio);
  if (when === "suspended_audio") document.dispatchEvent(new CustomEvent("favorites-tab", {detail: "ai"}));
  else { sessionActions.pause(); await settled(); }
}
const plays = audio.plays;
await visibility(false);
if (when === "suspended_audio") document.dispatchEvent(new CustomEvent("favorites-tab", {detail: "listen"}));
await settled(); assert.equal(audio.plays, plays); assert.ok(video.paused); assert.ok(audio.paused);
assert.equal(activePlayer.media(), audio);
if (["while_hidden", "suspended_audio"].includes(when)) assert.equal(video.currentTime, 27);
if (when === "suspended_audio") {
  await video.play(); await settled(); assert.ok(!audio.paused);
  video.pause(); await settled(); assert.ok(audio.paused); assert.ok(activePlayer.state.paused);
}
'''.replace("PAUSE_AT", json.dumps(pause_at)))


@pytest.mark.parametrize("page", ["/episodes/ep1", "/playlists/PLtest/favorites"])
@pytest.mark.parametrize("auto", [True, False])
def test_player_js_hidden_advance_is_synchronous_across_groups(run_player_js, page, auto):  # LISTEN2 AC 6,9
    run_player_js(r'''
location.pathname = PAGE; storage.set("auto-short-listen-auto", JSON.stringify(AUTO));
storage.set("auto-short-listen-filter", '"short"');
sourceItems = PAGE.startsWith("/episodes") ? [item(1, 1), item(2, 1), item(3, 1)]
  : Array.from({length: 37}, (_, n) => item(1, n));
await boot(); await metadata();
const start = PAGE.startsWith("/episodes") ? 0 : 34;
await $("queue").querySelectorAll("button[data-index]")[start].fire("click"); await metadata();
await visibility(true); let audio = activePlayer.audio;
await metadata(audio);
const oldQueue = $("queue").firstChild, oldTitle = $("title").textContent, oldScrolls = scrolls.length;
for (let n = start; n < sourceItems.length; n++) {
  const nextAudio = activePlayer.audios.find(a => a !== audio), plays = nextAudio.plays, loads = nextAudio.loads;
  const oldPlays = audio.plays;
  activePlayer.seek(60, audio); audio.ended = true; audio.paused = true;
  const ended = audio.fire("ended");
  if (AUTO && n + 1 < sourceItems.length) {
    audio = activePlayer.media(); assert.equal(audio, nextAudio); assert.equal(audio.loads, loads);
    assert.equal(audio.src, sourceItems[n + 1].video_url.replace(".mp4", ".m4a"));
    assert.ok(audio.plays > plays); assert.ok(!audio.paused); assert.ok(activePlayer.loading);
    assert.ok(!timers.has(activePlayer.advanceTimer));
  } else {
    assert.equal(audio.src, sourceItems[n].video_url.replace(".mp4", ".m4a")); assert.equal(audio.plays, oldPlays);
    assert.ok(activePlayer.state.paused); assert.equal(activePlayer.localAdvanceAt, null);
  }
  await ended;
  assert.equal($("queue").firstChild, oldQueue); assert.equal($("title").textContent, oldTitle);
  assert.equal(scrolls.length, oldScrolls);
  if (!AUTO) break;
  if (n + 1 < sourceItems.length) await metadata(audio);
}
const events = [...logBatches.flatMap(b => b.events), ...activePlayer.events];
assert.equal(events.filter(e => e.type === "hidden_advance").length, AUTO ? 2 : 0);
assert.ok(events.filter(e => e.type === "hidden_advance").every(e => e.hidden && e.t === 60));
await visibility(false); await metadata();
assert.equal(activePlayer.media(), audio); assert.ok(audio.paused);
assert.equal($("video").src, sourceItems[AUTO ? sourceItems.length - 1 : start].video_url);
assert.equal($("video").currentTime, 60); assert.ok($("video").paused);
'''.replace("PAGE", json.dumps(page)).replace("AUTO", json.dumps(auto)))


@pytest.mark.parametrize("mode", ["room", "pip"])
def test_player_js_visible_room_and_pip_follow_audio(run_player_js, mode):  # Amendment C AC8 / AC5'
    run_player_js(r'''
sourceItems = [item(1, 1), item(1, 2)]; const mode = MODE;
if (mode === "room") useRoom(true);
await boot(); await metadata(); await $("play").fire("click");
if (mode === "room") { await $("watch").fire("click"); await settled(); await metadata(); }
else await $("video").fire("enterpictureinpicture");
const video = $("video"), audio = activePlayer.audio;
const plays = audio.plays;
if (mode === "pip") await visibility(true);
assert.equal(activePlayer.media(), audio); assert.ok(video.muted); assert.ok(!audio.paused); assert.ok(!video.paused);
video.ended = true; await video.fire("ended"); assert.ok(!audio.paused); assert.ok(!activePlayer.state.paused);
await end(); await settled();
if (mode === "room") { assert.ok(commands.some(c => c.action === "ended")); assert.ok(!$("title-editor").hidden); }
else assert.ok(activePlayer.localAdvanceAt != null);
assert.equal(audio.plays, plays); assert.ok(audio.paused);
await visibility(false); assert.equal(activePlayer.media(), audio);
if (mode === "pip") {
  await $("next").fire("click"); await metadata();
  const before = audio.plays; await visibility(true); await video.fire("leavepictureinpicture");
  assert.ok(video.paused); assert.ok(!audio.paused); assert.equal(audio.plays, before);
  await video.fire("enterpictureinpicture"); assert.ok(!video.paused); assert.ok(!audio.paused); assert.equal(audio.plays, before);
}
'''.replace("MODE", json.dumps(mode)))


def test_player_js_audio_retry_progress_giveup_and_log_batches(run_player_js):  # LISTEN2 AC 7,9
    run_player_js(r'''
sourceItems = [item(1, 1)]; await boot(); await metadata(); await $("play").fire("click");
activePlayer.seek(10, activePlayer.audio); await activePlayer.audio.fire("timeupdate"); await visibility(true);
const audio = activePlayer.audio; await metadata(audio);
audio.pause(); await settled(); tick(1000); await settled();
activePlayer.seek(13, audio); tick(2000); await settled();
assert.equal(activePlayer.hiddenRun.since, null); assert.equal(activePlayer.hiddenRun.attempts, 0);
for (let n = 0; n < 8; n++) {
  audio.pause(); await settled(); tick(1000); await settled(); tick(2000); await settled();
}
assert.ok(!activePlayer.hiddenRun.gaveUp); // Flat retries no longer give up after 2 checks / 6 attempts.
const deadline = activePlayer.hiddenRun.since + 300000;
while (now < deadline) { tick(Math.min(15000, deadline - now)); await settled(); }
assert.ok(activePlayer.hiddenRun.gaveUp); const plays = audio.plays;
audio.pause(); await settled(); tick(10000); await settled(); assert.equal(audio.plays, plays);
const events = [...logBatches.flatMap(b => b.events), ...activePlayer.events];
assert.ok(events.some(e => e.type === "retry_ok" && e.t === 13));
assert.ok(events.some(e => e.type === "retry_gave_up" && e.t === 13));
await visibility(false); await visibility(true); await metadata(audio);
audio.play = () => { audio.plays++; return Promise.reject(Object.assign(new Error("blocked"), {name: "NotAllowedError"})); };
audio.pause(); await settled(); tick(1000); await settled();
assert.ok(activePlayer.events.some(e => e.type === "retry_blocked" && e.err === "NotAllowedError"));
for (let i = 0; i < 30; i++) activePlayer.record("visibility");
assert.equal(activePlayer.events.length, 20); tick(5000); await settled();
assert.ok(logBatches.every(batch => batch.events.length <= 20 && new TextEncoder().encode(JSON.stringify(batch)).length <= 2048));
''')


@pytest.mark.parametrize("mode", ["rejected", "spurious", "pending"])
@pytest.mark.parametrize("room", [False, True])
def test_player_js_background_retry_five_minute_limit_and_lock_screen_restart(run_player_js, mode, room):  # Amendment D AC11
    run_player_js(r'''
sourceItems = [item(1, 1)]; if (ROOM) useRoomTransport();
await boot(); await metadata(); await $("play").fire("click");
if (ROOM) { await $("watch").fire("click"); await settled(); await metadata(); }
await visibility(true);
const audio = activePlayer.audio, nativePlay = audio.play.bind(audio), calls = [], mode = MODE;
audio.play = () => {
  calls.push(now);
  if (mode === "pending") return new Promise(() => {});
  if (mode === "rejected") return Promise.reject(Object.assign(new Error("blocked"), {name: "NotAllowedError"}));
  const result = nativePlay(); queueMicrotask(() => audio.pause()); return result;
};
audio.pause(); await settled(); const start = now;
for (const delay of [1000, 2000, 7000, 15000]) { tick(delay); await settled(); }
assert.deepEqual(calls, (mode === "pending" ? [1000] : [1000, 3000, 10000, 25000]).map(t => start + t));
while (now < start + 295000) { tick(15000); await settled(); assert.ok(!activePlayer.hiddenRun.gaveUp); }
if (mode !== "pending") assert.ok(calls.length > 6);
tick(4999); await settled(); assert.ok(!activePlayer.hiddenRun.gaveUp);
tick(1); await settled(); assert.ok(activePlayer.hiddenRun.gaveUp);
const count = calls.length; tick(30000); await settled(); assert.equal(calls.length, count);
document.dispatchEvent(new Event("freeze")); await settled();
document.dispatchEvent(new Event("resume")); tick(5000); await settled();
// An unresolved previous play promise must not prevent the lock-screen Play from starting audio.
audio.play = nativePlay; sessionActions.play(); await settled();
assert.ok(!audio.paused); assert.ok(!activePlayer.hiddenRun.gaveUp);
assert.equal(activePlayer.hiddenRun.since, null); assert.equal(activePlayer.hiddenRun.attempts, 0);
audio.pause(); await settled(); tick(1000); await settled(); activePlayer.seek(activePlayer.position(audio) + 1, audio); await audio.fire("timeupdate");
assert.equal(activePlayer.hiddenRun.since, null); assert.equal(activePlayer.hiddenRun.attempts, 0);
const events = [...logBatches.flatMap(b => b.events), ...activePlayer.events,
  ...(await Promise.all(beacons.map(b => b.text()))).flatMap(b => JSON.parse(b).events)];
assert.equal(events.filter(e => e.type === "retry_gave_up").length, 1);
assert.ok(events.some(e => e.type === "freeze")); assert.ok(events.some(e => e.type === "resume"));
assert.ok(events.some(e => e.type === "pause_hidden" && e.rs === 1 && e.ns === 2));
'''.replace("MODE", json.dumps(mode)).replace("ROOM", json.dumps(room)))


@pytest.mark.parametrize("stop", ["progress", "pause", "visible", "next"])
def test_player_js_background_retry_resets_on_progress_and_cancels_on_controls(run_player_js, stop):  # Amendment D AC11
    run_player_js(r'''
sourceItems = [item(1, 1), item(1, 2)]; await boot(); await metadata(); await $("play").fire("click"); await visibility(true);
const audio = activePlayer.audio, nativePlay = audio.play.bind(audio), stop = STOP;
audio.play = () => Promise.reject(new Error("blocked"));
audio.pause(); await settled(); const start = now;
while (now < start + 295000) { tick(Math.min(15000, start + 295000 - now)); await settled(); }
assert.ok(!activePlayer.hiddenRun.gaveUp);
audio.play = nativePlay;
if (stop === "progress") {
  // Progress just before the old deadline buys a fresh five-minute window for a subsequent stall.
  activePlayer.seek(activePlayer.position(audio) + 1, audio); await audio.fire("timeupdate");
  assert.equal(activePlayer.hiddenRun.since, null); assert.equal(activePlayer.hiddenRun.attempts, 0);
  activePlayer.recover(); tick(6000); await settled(); assert.ok(!activePlayer.hiddenRun.gaveUp);
} else {
  if (stop === "pause") { sessionActions.pause(); await settled(); }
  if (stop === "visible") await visibility(false);
  if (stop === "next") { sessionActions.nexttrack(); await settled(); }
  const plays = audio.plays;
  tick(400000); await settled();
  assert.equal(audio.plays, plays); assert.ok(!activePlayer.hiddenRun?.gaveUp);
  if (stop === "pause") assert.ok(audio.paused);
  if (stop === "next") assert.equal(audio.src, sourceItems[1].video_url.replace(".mp4", ".m4a"));
}
'''.replace("STOP", json.dumps(stop)))


@pytest.mark.parametrize("page", ["/episodes/ep1", "/playlists/PLtest/favorites", "/watch"])
@pytest.mark.parametrize("reply", ["success", "conflict_same", "conflict_other"])
def test_player_js_room_hidden_advance_reconciles_without_double_skip(run_player_js, page, reply):  # Amendment A AC10
    run_player_js(r'''
location.pathname = PAGE;
sourceItems = Array.from({length: 7}, (_, n) => item(n + 1, 1));
const queue = Player.groupFavorites(sourceItems, "both").map(i => ({url: i.video_url, title: i.title, group: i.group}));
const start = PAGE.includes("favorites") ? 3 : 0;
const backend = useRoomTransport(true, PAGE === "/watch" ? {queue, index: start, paused: false} : {});
await boot(); await metadata();
if (PAGE !== "/watch") {
  await $("play").fire("click"); await $("watch").fire("click"); await settled(); await metadata();
  if (start) { await AutoShortWatch.command("goto", {index: start}, true); await metadata(); }
}
activePlayer.seek(17.25, activePlayer.audio);
await visibility(true); let audio = activePlayer.audio; await metadata(audio);
assert.equal(activePlayer.media(), audio); assert.ok($("video").paused); assert.ok(!audio.paused);
const oldRow = $("queue").firstChild, oldHeading = $("title").textContent, oldScrolls = scrolls.length;
let releaseNext;
interceptRoom = body => body?.action === "next" ? new Promise(resolve => releaseNext = resolve) : null;
const nextAudio = activePlayer.audios.find(a => a !== audio);
const version = activePlayer.state.version, plays = nextAudio.plays, loads = nextAudio.loads;
activePlayer.seek(60, audio); audio.ended = true; audio.paused = true;
const ending = audio.fire("ended"); // Assertions before any network microtask / timer / metadata.
audio = activePlayer.media(); assert.equal(audio, nextAudio);
assert.equal(audio.src, sourceItems[start + 1].video_url.replace(".mp4", ".m4a")); assert.ok(audio.plays > plays); assert.ok(!audio.paused);
assert.equal(activePlayer.sourceKey, JSON.stringify([start + 1, sourceItems[start + 1].video_url]));
assert.equal(audio.loads, loads); assert.ok(activePlayer.loading);
assert.equal(commands.filter(c => c.action === "next").length, 0); assert.ok(!timers.has(activePlayer.advanceTimer));
await ending; await settled(); await metadata(audio); activePlayer.seek(4.5, audio);
assert.deepEqual(commands.filter(c => c.action === "next").map(c => c.expect_version), [version]);
assert.ok(!commands.some(c => c.action === "ended"));
const optimisticLoads = audio.loads, reads = roomReads.length;
if (REPLY === "success") {
  releaseNext({ok: true, json: async () => backend.apply("next", {expect_version: version})});
} else {
  backend.apply("goto", {index: REPLY === "conflict_same" ? start + 1 : start + 2}, "b");
  releaseNext({ok: false, status: 409, json: async () => ({detail: "Một người khác đã chuyển"})});
}
await settled(); await AutoShortWatch.sent(); await settled();
assert.equal(commands.filter(c => c.action === "next").length, 1); // Never retry next after 409.
const expected = REPLY === "conflict_other" ? start + 2 : start + 1;
assert.equal(serverRoom.index, expected); assert.equal(activePlayer.state.index, expected);
assert.equal(audio.src, sourceItems[expected].video_url.replace(".mp4", ".m4a")); assert.ok(!audio.paused);
assert.equal(audio.loads, optimisticLoads + (REPLY === "conflict_other" ? 1 : 0));
if (REPLY !== "conflict_other") assert.equal(activePlayer.position(audio), 4.5);
else await metadata(audio);
if (REPLY.startsWith("conflict")) assert.ok(roomReads.length >= reads + 2); // command's pending poll + accepted recovery poll
assert.equal($("queue").firstChild, oldRow); assert.equal($("title").textContent, oldHeading); assert.equal(scrolls.length, oldScrolls);
assert.ok([...logBatches.flatMap(b => b.events), ...activePlayer.events].some(e => e.type === "hidden_advance" && e.hidden && e.t === 60));
// A second end uses the new queue index and the acknowledged server version.
interceptRoom = null; const newVersion = activePlayer.state.version;
await end(audio); audio = activePlayer.media(); await settled();
assert.deepEqual(commands.filter(c => c.action === "next").map(c => c.expect_version), [version, newVersion]);
assert.equal(audio.src, sourceItems[expected + 1].video_url.replace(".mp4", ".m4a")); assert.equal(serverRoom.index, expected + 1);
await metadata(audio); activePlayer.seek(2.25, audio);
// Align the room clock for the visible sync; verify video returns to the acknowledged current source.
serverRoom.position = 2.25; serverRoom.updated_at = now / 1000; await AutoShortWatch.poll(true);
await visibility(false); await metadata();
assert.equal($("video").src, sourceItems[expected + 1].video_url); assert.equal($("video").currentTime, 2.25);
assert.ok(!$("video").paused); assert.ok(!audio.paused);
'''.replace("PAGE", json.dumps(page)).replace("REPLY", json.dumps(reply)))


@pytest.mark.parametrize("initially_paused", [False, True])
def test_player_js_room_audio_remote_controls_preserve_pause_and_seek_guards(run_player_js, initially_paused):  # Amendment A AC10 / WATCH1
    run_player_js(r'''
sourceItems = [item(1, 1), item(1, 2)]; const backend = useRoomTransport();
await boot(); await metadata(); await $("play").fire("click");
await $("watch").fire("click"); await settled(); await metadata();
await AutoShortWatch.command("rate", {rate: 1.5, position: 17.25}, true); await settled();
const video = $("video"), audio = activePlayer.audio;
video.currentTime = 17.25;
if (INITIALLY_PAUSED) { await AutoShortWatch.command("pause", {position: 17.25}, true); await settled(); }
else {
  video.pause(); await settled(); assert.ok(activePlayer.syncBlocked); // Existing 1500 ms native pause grace.
  await AutoShortWatch.poll(true); assert.ok(activePlayer.syncBlocked); assert.ok(video.paused);
}
const pauses = commands.filter(c => c.action === "pause").length;
await visibility(true);
if (!INITIALLY_PAUSED) { assert.equal(activePlayer.position(audio), 17.25); assert.equal(audio.playbackRate, 1.5); }
assert.ok(!activePlayer.syncBlocked); tick(1500); await settled();
assert.equal(commands.filter(c => c.action === "pause").length, pauses); // Hiding cancels the room-wide pause.
if (INITIALLY_PAUSED) {
  assert.equal(activePlayer.media(), audio); assert.ok(audio.paused);
  backend.apply("play", {position: 17.25}, "b"); await AutoShortWatch.poll(true); await settled();
}
assert.equal(activePlayer.media(), audio); await metadata(audio);
assert.ok(video.paused); assert.equal(audio.playbackRate, 1.5);
assert.ok(!audio.paused);
// Same-version poll drift still takes WATCH1's seek_skipped_hidden path.
activePlayer.seek(20, audio); tick(4000); await settled(); await AutoShortWatch.poll(true);
assert.equal(activePlayer.position(audio), 20);
assert.ok([...logBatches.flatMap(b => b.events), ...activePlayer.events].some(e => e.type === "seek_skipped_hidden"));
backend.apply("pause", {position: 20}, "b"); await AutoShortWatch.poll(true); await settled();
assert.ok(audio.paused); assert.ok(activePlayer.state.paused);
backend.apply("play", {position: 20}, "b"); await AutoShortWatch.poll(true); await settled();
assert.ok(!audio.paused); assert.ok(!activePlayer.state.paused);
backend.apply("seek", {position: 30}, "b"); await AutoShortWatch.poll(true); await settled();
assert.equal(activePlayer.position(audio), 30); // Explicit remote seek is still allowed.
backend.apply("next", {expect_version: serverRoom.version}, "b"); await AutoShortWatch.poll(true); await settled();
assert.equal(audio.src, sourceItems[1].video_url.replace(".mp4", ".m4a")); assert.ok(!audio.paused); await metadata(audio);
sessionActions.previoustrack(); await settled(); assert.equal(audio.src, sourceItems[0].video_url.replace(".mp4", ".m4a")); await metadata(audio);
sessionActions.nexttrack(); await settled(); assert.equal(audio.src, sourceItems[1].video_url.replace(".mp4", ".m4a")); await metadata(audio);
sessionActions.pause(); await settled(); assert.ok(audio.paused); assert.ok(activePlayer.state.paused);
sessionActions.play(); await settled(); assert.ok(!audio.paused); assert.ok(!activePlayer.state.paused);
const reads = roomReads.length; tick(10000); await settled(); // Include the initial inactive invitation poll interval.
assert.ok(roomReads.length > reads); // Real watch.js keeps polling a hidden page.
'''.replace("INITIALLY_PAUSED", json.dumps(initially_paused)))


@pytest.mark.parametrize("ending", ["auto_off", "last_track", "visible"])
def test_player_js_room_ended_fallbacks_keep_server_countdown(run_player_js, ending):  # Amendment A AC10 / AC8
    run_player_js(r'''
const ending = ENDING;
sourceItems = ending === "last_track" ? [item(1, 1)] : [item(1, 1), item(1, 2)];
storage.set("auto-short-listen-auto", JSON.stringify(ending !== "auto_off"));
useRoomTransport(ending !== "auto_off"); await boot(); await metadata();
await $("play").fire("click"); await $("watch").fire("click"); await settled(); await metadata();
if (ending !== "visible") { await visibility(true); await metadata(activePlayer.audio); }
const media = activePlayer.media(), plays = media.plays, version = activePlayer.state.version;
await end(media); await settled();
assert.deepEqual(commands.filter(c => c.action === "ended").map(c => [c.expect_version, c.position]), [[version, 60]]);
assert.equal(commands.filter(c => c.action === "next").length, 0);
assert.equal(media.plays, plays); assert.ok(media.paused); assert.ok(activePlayer.state.finished);
if (ending === "visible") {
  assert.equal(activePlayer.media(), activePlayer.audio); assert.ok($("video").muted);
  assert.equal(activePlayer.state.advance_at, now / 1000 + 3); assert.match($("notice").textContent, /Sau 3 s/);
} else { assert.equal(activePlayer.media(), activePlayer.audio); assert.equal(activePlayer.state.advance_at, null); }
'''.replace("ENDING", json.dumps(ending)))


@pytest.mark.parametrize("page", ["/episodes/ep1", "/playlists/PLtest/favorites"])
@pytest.mark.parametrize("background", [False, True])
def test_player_js_room_title_editor_keeps_saved_title_across_polls(run_player_js, page, background):  # Amendment B AC1,3,4
    run_player_js(r'''
location.pathname = PAGE;
sourceItems = [item(1, 1), {...item(2, 1, "khaithi"), title: "Tiêu đề KT gốc"}];
titleView("ep1"); titleView("ep2.kt");
storage.set("auto-short-listen-filter", '"short"'); // The room's playing item will be absent from solo items.
const backend = useRoomTransport(); await boot(); await metadata(); await $("play").fire("click");
await $("watch").fire("click"); await settled(); await metadata();
assert.ok(!$("title-editor").hidden);
const queue = sourceItems.map(i => ({url: i.video_url, title: i.title, group: {id: "both", label: "Cả hai"}}));
backend.apply("set", {queue, index: 1, position: 11.25, rate: 1.25, paused: false}, "b");
await AutoShortWatch.poll(true); await settled(); await metadata();
const reads = requests.filter(p => p === "/api/episodes/ep2.kt").length;
assert.ok(!$("title-editor").hidden); assert.equal(editorInput(), undefined);
await $("title-editor").firstChild.fire("click"); await settled();
assert.equal(editorInput().value, "Tiêu đề KT gốc");
assert.equal(requests.filter(p => p === "/api/episodes/ep2.kt").length, reads + 1);
if (BACKGROUND) { await visibility(true); await metadata(activePlayer.audio); }
const media = activePlayer.media(); activePlayer.seek(23.5, media);
editorInput().value = "Tiêu đề đã sửa trong phòng"; await editorInput().fire("input"); tick(350); await settled();
const before = [media.src, activePlayer.position(media), media.loads, media.plays, media.pauses, activePlayer.sourceKey,
  activePlayer.state.index, activePlayer.state.version, activePlayer.receivedAt];
const posts = commands.length, serverBefore = structuredClone(serverRoom);
await editorButton("Lưu & render lại").fire("click"); await settled();
assert.deepEqual(titleCalls.at(-1), {path: "/api/episodes/ep2.kt/shorts/k1/title", body: {set: "Tiêu đề đã sửa trong phòng"}});
assert.deepEqual([media.src, activePlayer.position(media), media.loads, media.plays, media.pauses, activePlayer.sourceKey,
  activePlayer.state.index, activePlayer.state.version, activePlayer.receivedAt], before);
assert.equal(activePlayer.state.title, "Tiêu đề đã sửa trong phòng");
assert.equal(activePlayer.state.queue[1].title, "Tiêu đề đã sửa trong phòng");
assert.equal(navigator.mediaSession.metadata.title, "Tiêu đề đã sửa trong phòng");
assert.equal(commands.length, posts); assert.deepEqual(serverRoom, serverBefore);
// Neither a full old snapshot nor an omitted queue (reused by watch.js) may undo the edit.
for (let i = 0; i < 2; i++) {
  if (i === 1) interceptRoom = body => {
    if (body) return null;
    const data = backend.snapshot(); delete data.queue;
    return {ok: true, json: async () => data};
  };
  await AutoShortWatch.poll(true); await settled();
  assert.equal(activePlayer.state.title, "Tiêu đề đã sửa trong phòng");
  assert.equal(activePlayer.state.queue[1].title, "Tiêu đề đã sửa trong phòng");
  assert.equal(serverRoom.queue[1].title, "Tiêu đề KT gốc");
}
interceptRoom = null;
assert.equal(commands.length, posts);
if (BACKGROUND) await visibility(false);
assert.match($("title").textContent, /Tiêu đề đã sửa trong phòng/);
assert.match($("queue").textContent, /Tiêu đề đã sửa trong phòng/);
// Another queue item with the same clip id keeps its own title; returning reapplies the URL override.
backend.apply("goto", {index: 0}, "b"); await AutoShortWatch.poll(true); await settled(); await metadata();
assert.equal(activePlayer.state.title, "Bài 1"); assert.equal(editorInput().value, "Bài 1");
backend.apply("goto", {index: 1}, "b"); await AutoShortWatch.poll(true); await settled(); await metadata();
assert.match($("title").textContent, /Tiêu đề đã sửa trong phòng/);
'''.replace("PAGE", json.dumps(page)).replace("BACKGROUND", json.dumps(background)))


@pytest.mark.parametrize("page", ["/episodes/ep1", "/playlists/PLtest/favorites", "/watch"])
def test_player_js_room_title_editor_needs_local_item_and_host(run_player_js, page):  # Amendment B AC1
    run_player_js(r'''
location.pathname = PAGE; sourceItems = [item(1, 1)]; titleView("ep1");
const foreign = {url: "/files/ep9/k1.mp4", title: "Bài ngoài danh sách"};
const backend = useRoomTransport(true, PAGE === "/watch" ? {queue: [foreign], index: 0, paused: true} : {});
await boot(); await metadata();
if (PAGE !== "/watch") {
  await $("watch").fire("click"); await settled();
  backend.apply("set", {queue: [foreign], index: 0, paused: true}, "b");
  await AutoShortWatch.poll(true); await settled();
  assert.ok($("title-editor").hidden); assert.equal($("title-editor").children.length, 0);
} else {
  assert.equal(document.getElementById("listen-title-editor"), null);
  assert.ok(!elements.has("title-editor")); // Match the real /watch DOM rather than manufacturing a host.
  assert.equal(requests.filter(p => p.startsWith("/api/episodes/")).length, 0);
}
assert.equal(requests.filter(p => p === "/api/episodes/ep9").length, 0); assert.equal(titleCalls.length, 0);
'''.replace("PAGE", json.dumps(page)))
