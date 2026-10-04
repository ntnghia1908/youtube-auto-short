"""CP8.13 bộ kinh groups + "Lặp lại": server groups / counts (G1, AC1), the bộ kinh summary (G3, AC3), the tabs
(G2, AC2), no "Khai thị" link on an entry (G4, AC4), the loop button of a Short card (G5, AC5). No JS test framework
in the repo: the static files served are checked, plus the API data the pages read."""

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web.playlists import GROUPS, PlaylistStore, group_of  # noqa: E402
from auto_short.workspace import Workspace  # noqa: E402

from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
PL = "PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp"


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"))


def client(cfg):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, render=lambda *a, **k: None,
                             pipeline=fake_pipeline([]),
                             disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9))
    c = TestClient(app, follow_redirects=False)
    assert c.post("/login", data={"password": PW}).status_code == 303
    return c


def vid(n: int) -> str:
    return f"v{n:010d}"


# --- G1 group table (AC1) -----------------------------------------------------------------------------------

def test_group_table_g1():
    assert GROUPS == {"new": "todo", "queued": "running", "processing": "running", "failed": "failed",
                      "incomplete": "failed", "rendered": "doing", "complete": "done", "unavailable": None}
    assert group_of("deleted", True) == "done" and group_of("deleted", False) == "todo"  # unchanged (CP8.7)


def _st(state, *, complete=False, shorts=0, published=0, stage=None, error=None):
    return {"state": state, "stage": stage, "error": error, "shorts": shorts, "published": published,
            "archived": False, "complete": complete, "deleted_at": None}


# (Short state, khai thị state or None, live job of the Short, live job of the khai thị) -> expected state, group
CASES = [
    (_st("new"), None, None, None, "new", "todo"),
    (_st("new"), None, {"status": "queued"}, None, "queued", "running"),
    (_st("processing", stage="transcript"), None, None, None, "processing", "running"),
    (_st("failed", stage="render", error="x"), None, None, None, "failed", "failed"),
    (_st("incomplete"), None, None, None, "incomplete", "failed"),
    (_st("rendered", shorts=2), None, None, None, "rendered", "doing"),
    (_st("complete", complete=True, shorts=2, published=2), None, None, None, "complete", "done"),
    (_st("deleted", complete=True), None, None, None, "deleted", "done"),
    (_st("deleted"), None, None, None, "deleted", "todo"),
    # Short + khai thị (CP8.9 A1.4): one side failed -> failed, one side running -> running
    (_st("rendered", shorts=2), _st("failed", stage="selection", error="boom"), None, None, "failed", "failed"),
    (_st("complete", complete=True), _st("new"), None, {"status": "running", "stage": "selection"},
     "processing", "running"),
    (_st("complete", complete=True), _st("new"), None, {"status": "queued"}, "queued", "running"),
    (_st("rendered", shorts=2), _st("incomplete"), None, None, "incomplete", "failed"),
    (_st("complete", complete=True), _st("rendered", shorts=1), None, None, "rendered", "doing"),
    (_st("complete", complete=True), _st("complete", complete=True), None, None, "complete", "done"),
    (_st("failed", stage="render"), _st("processing", stage="transcript"), None, None, "processing", "running"),
]


def test_view_groups_counts_and_summary(tcfg, monkeypatch):
    store = PlaylistStore(tcfg)
    disk, jobs, kt_ids = {}, {}, {}
    entries = []
    for n, (short, kt, job, kjob, _, _) in enumerate(CASES):
        v = vid(n)
        entries.append({"index": n + 1, "video_id": v, "title": f"t{n}", "duration": 1.0, "episode": None,
                        "available": True})
        disk[v] = short
        if job is not None:
            jobs[v] = job
        if kt is not None:
            kt_ids[v] = v + ".kt"
            disk[v + ".kt"] = kt
            if kjob is not None:
                jobs[v + ".kt"] = kjob
    entries.append({"index": 99, "video_id": None, "title": "[Private video]", "duration": None, "episode": None,
                    "available": False})
    monkeypatch.setattr(store, "_disk_status", lambda eid: dict(disk[eid]))
    monkeypatch.setattr(store, "_khaithi_id", lambda v: kt_ids.get(v))
    doc = {"playlist_id": PL, "title": "Bộ kinh", "url": "u", "fetched_at": "t", "entries": entries}
    v = store.view(doc, jobs)
    got = [(e["state"], e["group"]) for e in v["entries"]]
    assert got == [(c[4], c[5]) for c in CASES] + [("unavailable", None)]
    want = {"all": len(CASES) + 1, "todo": 0, "running": 0, "failed": 0, "doing": 0, "done": 0}
    for c in CASES:
        want[c[5]] += 1
    assert v["counts"] == want
    assert want["running"] == 5 and want["failed"] == 4 and want["doing"] == 2  # every group populated
    s = store.summary(doc, jobs)
    assert (s["running"], s["failed"], s["doing"], s["complete"]) == (5, 4, 2, want["done"])
    assert list(s) == ["id", "title", "count", "fetched_at", "processed", "complete", "running", "failed",
                       "doing", "deleted"]


# --- G3 GET /api/playlists (AC3) ------------------------------------------------------------------------------

def _playlist(cfg, vids):
    pl_dir = Path(cfg.workspace.dir) / "_playlists"
    pl_dir.mkdir(parents=True, exist_ok=True)
    (pl_dir / f"{PL}.json").write_text(json.dumps({
        "schema_version": 1, "playlist_id": PL, "title": "Bộ kinh", "url": "u", "fetched_at": "t",
        "entries": [{"index": i + 1, "video_id": v, "title": f"t{i}", "duration": 1.0, "episode": None,
                     "available": True} for i, v in enumerate(vids)]}), encoding="utf-8")


def _set_stage(cfg, episode_id, stage, status):
    ws = Workspace(Path(cfg.workspace.dir), episode_id)
    m = ws.load_manifest()
    m["stages"][stage]["status"] = status
    m["stages"][stage]["error"] = "boom" if status == "failed" else None
    ws.save_manifest(m)


def test_api_playlists_summary_and_entry_groups(tcfg):
    vids = [vid(n) for n in range(5)]
    write_episode(tcfg, vids[0])  # rendered, nothing ticked -> doing
    write_episode(tcfg, vids[1])
    _set_stage(tcfg, vids[1], "selection", "failed")  # -> failed
    write_episode(tcfg, vids[2])
    _set_stage(tcfg, vids[2], "render", "stale")  # render not done, nothing failed -> incomplete -> failed
    write_episode(tcfg, vids[3])
    _set_stage(tcfg, vids[3], "titling", "running")  # stage running on disk -> processing -> running
    _playlist(tcfg, vids)  # vids[4]: new -> todo
    with client(tcfg) as c:
        d = c.get(f"/api/playlists/{PL}").json()
        assert [(e["state"], e["group"], e["action"]) for e in d["entries"]] == [
            ("rendered", "doing", None), ("failed", "failed", "resume"), ("incomplete", "failed", "resume"),
            ("processing", "running", None), ("new", "todo", "process")]
        assert d["counts"] == {"all": 5, "todo": 1, "running": 1, "failed": 2, "doing": 1, "done": 0}
        s = c.get("/api/playlists").json()["playlists"][0]
        assert (s["running"], s["failed"], s["doing"], s["complete"], s["processed"]) == (1, 2, 1, 0, 4)
        js = c.get("/static/app.js").text
    # home line: "… · đang xử lý a · lỗi / dở dang b · đang làm c", a part equal to 0 left out
    assert 'text: playlistSummary(p)' in js
    assert '[["đang xử lý", p.running], ["lỗi / dở dang", p.failed], ["đang làm", p.doing]]' in js
    assert '.filter(([, n]) => n).map(([label, n]) => ` · ${label} ${n}`).join("")' in js


# --- G2 tabs (AC2), G4 no "Khai thị" link (AC4) ----------------------------------------------------------------

def test_playlist_page_seven_tabs_and_empty_notes(tcfg):
    _playlist(tcfg, [vid(0)])
    with client(tcfg) as c:
        html = c.get(f"/playlists/{PL}").text
        js = c.get("/static/app.js").text
    start = html.index('<div id="pl-filters"')
    filters = html[start:html.index("</div>", start)]
    tabs = re.findall(r'data-filter="(\w+)">([^(<]+) \(<span class="n">0</span>\)</button>', filters)
    assert tabs == [("all", "Tất cả"), ("todo", "Chưa xử lý"), ("running", "Đang xử lý"),
                    ("failed", "Lỗi / dở dang"), ("prepared", "Chờ cắt"), ("doing", "Đang làm"),
                    ("done", "Xong")]  # CP13.2: "Chờ cắt" added
    assert '<p id="pl-running-empty" class="muted small" hidden>Không có tập nào đang xử lý</p>' in html
    assert '<p id="pl-failed-empty" class="muted small" hidden>Không có tập nào lỗi / dở dang</p>' in html
    for needle in ('let plFilter = "doing";',
                   'const PL_FILTERS = ["all", "todo", "running", "failed", "prepared", "doing", "done"];',
                   "if (PL_FILTERS.includes(savedFilter)) plFilter = savedFilter;",
                   'li.hidden = plFilter !== "all" && li.dataset.group !== plFilter;',
                   '$("#pl-failed-empty").hidden = !(plFilter === "failed" && shown === 0);',
                   'b.querySelector(".n").textContent = d.counts[b.dataset.filter] || 0;',
                   '"data-group": e.group || "none" },'):
        assert needle in js, needle


def test_playlist_entry_has_no_khaithi_link(tcfg):
    with client(tcfg) as c:
        js = c.get("/static/app.js").text
    body = js[js.index("async function loadPlaylist()"):js.index("return { initIndex")]
    assert "khaithi_episode_id" not in body and '"Khai thị"' not in body and "kind-label" not in body
    # the count line of the khai thị videos stays (CP8.9 A1.4)
    assert "video khai thị, đã đăng ${e.khaithi_published}/${e.khaithi_videos}" in js


# --- G5 "Lặp lại" (AC5) -----------------------------------------------------------------------------------------

def test_loop_button_script_and_style(tcfg):
    with client(tcfg) as c:
        js = c.get("/static/app.js").text
        css = c.get("/static/style.css").text
    card = js[js.index("function shortCard(s)"):js.index("function legacyCopy(")]
    # only a card with a video gets the button, next to "Tải về"
    assert "video = el(\"video\"" in card
    assert "s.download_url ? downloadLink(s) : null,\n        video ? loopButton(s.clip_id, video) : null," in card
    loop = js[js.index("function loopButton("):js.index("function downloadLink(")]
    for needle in ("const on = loops.get(clipId) === true;", "video.loop = on;",
                   '"aria-pressed": on ? "true" : "false"', 'title: "Lặp lại", "aria-label": "Lặp lại"',
                   "loops.set(clipId, next);", "video.loop = next;",
                   'b.setAttribute("aria-pressed", next ? "true" : "false");'):
        assert needle in loop, needle
    assert "const loops = new Map();" in js
    assert "localStorage" not in loop and "store(" not in loop and "api(" not in loop  # not stored, no request
    assert '.loop-btn[aria-pressed="true"]' in css
