"""CP8.12 episode page: sticky [Shorts | Khai thị] bar (U1), collapsible stages box (U2), a missing target / a
missing episode (U4). No JS test framework in the repo: the static files served are checked, plus the API data
the page reads (AC 1, 2, 4, 5, 6)."""

import json
import re
import threading
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short import khaithi  # noqa: E402
from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.khaithi import KhaiThi  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402

from render_helpers import EID  # noqa: E402
from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
KT = EID + ".kt"


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


def make_pair(cfg):
    write_episode(cfg, EID)
    write_episode(cfg, KT, titles={"k01": "Khai thị một", "k02": "Khai thị hai"})
    khaithi.write(Path(cfg.workspace.dir) / KT, KhaiThi(EID, 4, 7))


def _rule(css: str, selector: str) -> str:
    m = re.search(r"(?m)^" + re.escape(selector) + r" \{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


def test_episode_page_html_kind_bar_and_stages_box(tcfg):  # AC1
    with client(tcfg) as c:
        html = c.get(f"/episodes/{EID}").text
    assert 'id="kind-links"' not in html
    bar = html.index('<nav id="kind-bar" class="kind-bar"')
    assert bar < html.index('<section class="card">')  # above the first card of main
    nav = html[bar:html.index("</nav>", bar)]
    assert ">Shorts<" in nav and ">Khai thị<" in nav
    assert html.index('id="kind-note"') < html.index('<section class="card">')  # U4 message under the bar
    box = html[html.index('<details id="stages-box"'):]
    box = box[:box.index("</details>")]
    summary = box[box.index("<summary>"):box.index("</summary>")]
    assert 'id="job-status"' in summary
    assert '<ol id="stages" class="stages">' in box
    # outside the collapsible box: archived note, resubmit / delete buttons, khai thị box, log
    rest = html[html.index('<details id="stages-box"') + len(box):]
    for needle in ('id="archived-note"', 'id="resubmit"', 'id="delete-episode"', 'id="kt-box"', 'id="log-box"'):
        assert needle in rest, needle


def test_episode_js_kind_bar_stages_and_gone(tcfg):  # AC2, AC3, AC5, AC6 (static)
    with client(tcfg) as c:
        js = c.get("/static/app.js").text
    assert "renderKindLinks" not in js and "#kind-links" not in js
    for needle in ("function renderKindBar(d)", "renderKindBar(d);", '"aria-current": "page"',
                   "d.khaithi_episode_id", "d.base_episode_id", "Không có link video nguồn",
                   "kb.open = true", 'kb.scrollIntoView(', '$("#kt-min").focus(',
                   "function checkBaseEpisode(id)", 'e.status === 404 ? "gone" : "error"',
                   "Tập Short của video này đã bị xóa. Muốn có lại Short: gửi lại link video ở trang chủ (chọn Short).",
                   "function stagesShouldOpen(d)", "function applyStagesOpen(d)", "applyStagesOpen(d);",
                   "if (want === stagesOpenApplied) return;", "Các bước xử lý: ",
                   "err.status = res.status;", "if (e.status === 404) { showEpisodeGone(); return; }",
                   "Tập này không còn (đã bị xóa hoặc chưa từng xử lý).", 'href: "/"'):
        assert needle in js, needle
    # the U4 message is shown on the page, never as an alert
    gone = js[js.index("function showEpisodeGone()"):]
    gone = gone[:gone.index("\n  }\n")]
    assert "clearTimeout(pollTimer)" in gone and "alert(" not in gone
    assert "alert(" not in js[js.index("function renderKindBar(d)"):js.index("function stagesShouldOpen(d)")]


def test_episode_css_sticky_bar_and_touch_targets(tcfg):  # AC4
    with client(tcfg) as c:
        css = c.get("/static/style.css").text
    bar = _rule(css, ".kind-bar")
    for needle in ("position: sticky;", "top: 0;", "z-index:", "background: var(--card);", "box-shadow:"):
        assert needle in bar, needle
    btn = _rule(css, ".kind-btn")
    assert "min-height: 44px;" in btn and "flex: 1 1 0;" in btn and "min-width: 0;" in btn
    assert "background: var(--accent-bg);" in _rule(css, ".kind-btn.current")
    assert "opacity:" in _rule(css, ".kind-btn.dim")
    assert "min-height: 44px;" in _rule(css, ".stages-box > summary")
    # the job line keeps its colours inside the summary
    assert ".job-status.ok { color: var(--ok); } .job-status.error { color: var(--err); }" in css


def test_episode_api_data_for_kind_bar(tcfg):  # AC2: the links come from the CP8.9 fields (no new field)
    make_pair(tcfg)
    with client(tcfg) as c:
        short = c.get(f"/api/episodes/{EID}").json()
        kt = c.get(f"/api/episodes/{KT}").json()
    assert (short["kind"], short["khaithi_episode_id"], short["base_episode_id"]) == ("short", KT, None)
    assert (kt["kind"], kt["base_episode_id"], kt["khaithi_episode_id"]) == ("khaithi", EID, None)
    assert all(s["status"] == "done" for s in short["stages"]) and len(short["stages"]) == 6


def test_deleted_short_and_unknown_episode(tcfg):  # AC6: data behind U4
    make_pair(tcfg)
    with client(tcfg) as c:
        assert c.delete(f"/api/episodes/{EID}").status_code == 200
        assert c.get(f"/api/episodes/{EID}").status_code == 404  # base check → "gone"
        kt = c.get(f"/api/episodes/{KT}")
        assert kt.status_code == 200 and kt.json()["base_episode_id"] == EID
        # a page of a missing episode is still the HTML page (the JS shows "Tập này không còn …")
        page = c.get("/episodes/zzzzzzzzzzz")
        assert page.status_code == 200 and 'id="kind-bar"' in page.text
        assert c.get("/api/episodes/zzzzzzzzzzz").status_code == 404


# --- A1: bộ kinh page "Đang xử lý" filter ---------------------------------------------------------------------

PL = "PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp"


def _playlist(cfg):
    pl_dir = Path(cfg.workspace.dir) / "_playlists"
    pl_dir.mkdir(parents=True, exist_ok=True)
    (pl_dir / f"{PL}.json").write_text(json.dumps({
        "schema_version": 1, "playlist_id": PL, "title": "Bộ kinh", "url": "u", "fetched_at": "t",
        "entries": [{"index": 1, "video_id": EID, "title": "t", "duration": 1.0, "episode": "9",
                     "available": True}]}), encoding="utf-8")


def test_playlist_page_running_filter_static(tcfg):
    _playlist(tcfg)
    with client(tcfg) as c:
        html = c.get(f"/playlists/{PL}").text
        js = c.get("/static/app.js").text
    filters = html[html.index('<div id="pl-filters"'):html.index("</div>", html.index('<div id="pl-filters"'))]
    order = [m.group(1) for m in re.finditer(r'data-filter="(\w+)"', filters)]
    assert order == ["all", "todo", "running", "doing", "done"]  # between "Chưa xử lý" and "Đang làm"
    assert '>Đang xử lý (<span class="n">0</span>)</button>' in filters
    assert '<p id="pl-running-empty" class="muted small" hidden>Không có tập nào đang xử lý</p>' in html
    for needle in ('const RUNNING_STATES = ["queued", "processing"];',
                   "RUNNING_STATES.includes(e.state) || RUNNING_STATES.includes(e.khaithi_state)",
                   '["all", "todo", "running", "doing", "done"].includes(savedFilter)',
                   'let plFilter = "doing";',  # default tab unchanged
                   'plFilter === "running" ? li.dataset.running !== "1"',
                   '"data-running": entryRunning(e) ? "1" : null',
                   "running: d.entries.filter(entryRunning).length",
                   '$("#pl-running-empty").hidden = !(plFilter === "running" && shown === 0);'):
        assert needle in js, needle


def test_playlist_running_states_short_and_khaithi(tcfg):
    """The data behind "Đang xử lý": a khai thị job of the video (Short done) shows as khaithi_state queued /
    processing; the server groups are unchanged ("Đang làm")."""
    write_episode(tcfg, EID)
    _playlist(tcfg)
    gate = threading.Event()
    app = app_mod.create_app(tcfg, PW, preflight=lambda c: None, render=lambda *a, **k: None,
                             pipeline=fake_pipeline([], gate=gate),
                             disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9))
    with TestClient(app, follow_redirects=False) as c:
        assert c.post("/login", data={"password": PW}).status_code == 303
        e = c.get(f"/api/playlists/{PL}").json()["entries"][0]
        assert e["state"] not in ("queued", "processing") and e["khaithi_state"] is None
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", "kinds": ["khaithi"]})
        assert r.status_code == 202
        try:
            v = c.get(f"/api/playlists/{PL}").json()
            e = v["entries"][0]
            assert e["khaithi_state"] in ("queued", "processing") and e["state"] in ("queued", "processing")
            assert v["counts"]["doing"] == 1
        finally:
            gate.set()
        assert c.app.state.runner.wait_idle(10)
