"""SCH1 AC2–4: HTTP/auth/local data and DOM rendering; ORCHESTRATOR runs these."""
from datetime import datetime, timedelta
import json
import shutil
import subprocess

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from auto_short.post import schedule as post_schedule
from auto_short.publish import overview, youtube
from auto_short.web.app import STATIC_DIR
from auto_short.web.routes import status
from auto_short.workspace import atomic_write_json, read_json_dict
from test_post_links import EID, EID2, PID, PID2, seed, service
from test_publish_schedule import NOW
from web_helpers import login, make_app


def snapshot(config, ident="UC1", title="Kênh 1", pid=PID, age=0):
    doc = dict(schema_version=1, channel_id=ident, channel_title=title, playlist_id=pid,
               updated_at=overview._iso(NOW - timedelta(hours=age)),
               kinds=overview.summarize([], NOW), missing={kind: [] for kind in ("vertical", "kt", "short")},
               duplicates=[], unrecognized_count=0,
               pending={kind: dict(count=0, episodes=[]) for kind in ("vertical", "kt", "short")})
    overview.write(config, doc)
    return doc


@pytest.fixture
def web(service, monkeypatch):
    _, ctx, wire = service

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(status, "datetime", FrozenDatetime)

    def blocked(*args, **kwargs):
        pytest.fail("schedule overview must never call YouTube")

    monkeypatch.setattr(youtube.YouTube, "_request", blocked)
    with TestClient(make_app(ctx.config), follow_redirects=False) as client:
        yield client, ctx, wire


def test_auth_empty_and_page(web):  # AC4
    client, ctx, wire = web
    assert client.get("/api/schedule-overview").status_code == 401
    assert client.get("/schedule").status_code == 303
    login(client)
    response = client.get("/api/schedule-overview")
    assert response.status_code == 200 and response.json()["channels"] == []
    assert response.headers["cache-control"] == "no-store"
    response = client.get("/schedule")
    assert response.status_code == 200 and "Lịch YouTube" in response.text
    assert response.headers["cache-control"] == "no-cache"
    assert client.get("/static/schedule.js").status_code == 200 and not wire.calls
    assert not (ctx.config.workspace.dir / "_publish/channels").exists()


def test_four_channels_sorted_local_posts_isolated_and_read_does_not_write(web):  # AC2–4
    client, ctx, wire = web
    for eid in (EID, EID + ".kt", EID2):
        seed(ctx, eid)
    seed(ctx, EID, cid="k02", posted=False)
    for ident, title, pid, age in (("UCb", "B", PID2, 37), ("UCa", "A", PID, 36),
                                   ("UCd", "D", "PLmissing0001", 0), ("UCc", "C", PID, 0)):
        doc = snapshot(ctx.config, ident, title, pid, age)
        doc["kinds"]["short"]["last_scheduled"] = dict(key="T23_S01", publish_at=overview._iso(NOW + timedelta(days=6)))
        doc["missing"]["kt"] = ["T9_KT06"]
        doc["duplicates"] = [dict(kind="short", key="T17_S09", copies=[
            dict(youtube_id="keep", keep=True), dict(youtube_id="b8Ep79QKIk4", keep=False)])]
        overview.write(ctx.config, doc)
    file = post_schedule.path(ctx.config.workspace.dir)
    post_schedule.write(file, {
        f"{EID}/k01": dict(slot_at=overview._iso(NOW)),
        f"{EID}.kt/k01": dict(slot_at=overview._iso(NOW + timedelta(days=8))),
        f"{EID}/k02": dict(slot_at=overview._iso(NOW + timedelta(days=100))),  # unticked
        f"{EID2}/k01": dict(slot_at=overview._iso(NOW + timedelta(days=2))),
        "outside0001/k01": dict(slot_at="2099-01-01T00:00:00Z"),
    })
    files = [file, *file.parent.joinpath("channels").glob("*.json")]
    before = {p: p.read_bytes() for p in files}
    login(client)
    response = client.get("/api/schedule-overview")
    assert response.status_code == 200
    a, b, c, d = response.json()["channels"]
    assert [row["channel_title"] for row in (a, b, c, d)] == list("ABCD")
    assert not a["stale"] and b["stale"]
    assert a["kinds"]["post"] == dict(
        last_scheduled=dict(key="T1_KT01", publish_at=overview._iso(NOW + timedelta(days=8))),
        last_public=dict(key="T1_S01", published_at=overview._iso(NOW)),
        scheduled_count=1, days_remaining=8, warning=False)
    assert b["kinds"]["post"]["last_scheduled"]["key"] == "T1_S01"
    assert b["kinds"]["post"]["days_remaining"] == 2
    assert a["kinds"]["short"]["warning"] and a["kinds"]["short"]["days_remaining"] == 6
    assert a["missing"]["kt"] == ["T9_KT06"] and a["duplicates"][0]["copies"][1]["youtube_id"] == "b8Ep79QKIk4"
    assert c["kinds"]["post"] == a["kinds"]["post"]
    assert d["kinds"]["post"]["last_scheduled"] is None and d["post_error"]
    assert {p: p.read_bytes() for p in files} == before and not wire.calls


def test_bad_snapshot_and_bad_times_keep_healthy_video_data(web):  # AC3–4
    client, ctx, _ = web
    snapshot(ctx.config)
    folder = ctx.config.workspace.dir / "_publish/channels"
    (folder / "broken.json").write_text("{")
    atomic_write_json(folder / "unknown.json", dict(schema_version=2))
    file = post_schedule.path(ctx.config.workspace.dir)
    file.write_text('{"schema_version": 9}')
    login(client)
    result = client.get("/api/schedule-overview").json()["channels"]
    assert len(result) == 1 and result[0]["post_error"]
    assert result[0]["kinds"]["post"]["days_remaining"] == 0
    assert file.read_text() == '{"schema_version": 9}'


def test_ticked_legacy_without_slot_is_ignored_and_skipped_render_keeps_code(web):  # AC3
    client, ctx, _ = web
    snapshot(ctx.config)
    seed(ctx, EID)
    seed(ctx, EID, cid="k02")  # legacy tick, no saved slot
    path = ctx.config.render.output_dir / EID / "render_manifest.json"
    doc = read_json_dict(path)
    doc["shorts"][0]["status"] = "skipped"
    atomic_write_json(path, doc)
    post_schedule.write(post_schedule.path(ctx.config.workspace.dir), {
        f"{EID}/k01": dict(slot_at=overview._iso(NOW - timedelta(days=1))),
        f"{EID}/k02": dict(video_at="2099-01-01T00:00:00Z"),
    })
    login(client)
    post = client.get("/api/schedule-overview").json()["channels"][0]["kinds"]["post"]
    assert post["last_scheduled"]["key"] == post["last_public"]["key"] == "T1_S01"
    assert post["days_remaining"] == 0 and post["warning"]


def test_topnav_link_all_existing_pages_and_mobile_layout():  # AC4
    for file in STATIC_DIR.glob("*.html"):
        html = file.read_text()
        if 'class="topnav"' in html:
            assert '<a href="/schedule"' in html, file.name
    html = (STATIC_DIR / "schedule.html").read_text()
    assert 'name="viewport"' in html and "table-wrap" in (STATIC_DIR / "schedule.js").read_text()
    assert 'timeZone: "Asia/Ho_Chi_Minh"' in (STATIC_DIR / "schedule.js").read_text()


# A small DOM harness executes the actual page script (no browser/socket needed).
DOM_SCRIPT = r"""
const fs = require('fs'), vm = require('vm');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
class Node {
  constructor(tag, attrs = {}, children = []) { this.tag = tag; this.attrs = attrs; this.childNodes = []; this.append(...children); }
  append(...items) { this.childNodes.push(...items.filter(x => x !== null && x !== undefined)); }
  replaceChildren(...items) { this.childNodes = []; this.append(...items); }
  addEventListener() {}
  set textContent(value) { this.attrs.text = value; }
  get textContent() { return (this.attrs.text || '') + this.childNodes.map(x => typeof x === 'string' ? x : x.textContent).join(''); }
  set className(value) { this.attrs.class = value; }
}
const nodes = Object.fromEntries(['schedule-refresh', 'schedule-message', 'schedule-channels'].map(id => [id, new Node('div')]));
vm.runInNewContext(fs.readFileSync(payload.script, 'utf8'), {
  AutoShort: { el: (tag, attrs, ...children) => new Node(tag, attrs, children), api: async path => {
    if (path !== '/api/schedule-overview') throw Error('unexpected URL'); return { channels: payload.channels };
  } }, document: { querySelector: selector => nodes[selector.slice(1)] }, Intl, Date,
});
setImmediate(() => process.stdout.write(JSON.stringify({ text: nodes['schedule-channels'].textContent,
  message: nodes['schedule-message'].textContent, tree: nodes['schedule-channels'] })));
"""


def dom(channels):
    if not shutil.which("node"):
        pytest.skip("node required for page DOM verification")
    result = subprocess.run(["node", "-e", DOM_SCRIPT], input=json.dumps(dict(
        script=str(STATIC_DIR / "schedule.js"), channels=channels)), text=True, capture_output=True,
        timeout=10, check=True)
    return json.loads(result.stdout)


def walk(node):
    if isinstance(node, dict):
        yield node
        for child in node["childNodes"]:
            yield from walk(child)


def test_page_renders_warning_limit_studio_links_vietnam_time_and_no_empty_warnings(service):  # AC2–4
    _, ctx, _ = service
    doc = snapshot(ctx.config, title="<img src=x onerror=alert(1)>")
    doc["stale"] = True
    doc["missing"]["vertical"] = [f"T{n}" for n in range(1, 13)]
    doc["duplicates"] = [dict(kind="short", key=f"T17_S{n:02d}", copies=[
        dict(youtube_id="keep", keep=True), dict(youtube_id="b8Ep79QKIk4", keep=False)]) for n in range(1, 12)]
    doc["kinds"] = {kind: overview.coverage(group, NOW) for kind, group in doc["kinds"].items()}
    doc["kinds"]["post"] = overview.coverage({}, NOW)
    result = dom([doc])
    assert "Thiếu:" in result["text"] and "upload bổ sung" in result["text"]
    assert "T1 (Bản dọc)" in result["text"] and "và 2 mã khác" in result["text"]
    assert "và 1 mã khác" in result["text"] and "xóa bản" in result["text"]
    assert "Số liệu cũ (cập nhật" in result["text"] and "10:00" in result["text"]
    assert "hết lịch" in result["text"]
    nodes = list(walk(result["tree"]))
    assert len([n for n in nodes if n["tag"] == "details"]) == 2
    assert len([n for n in nodes if n["tag"] == "td" and n["attrs"].get("class") == "note"]) == 4
    assert any(n["attrs"].get("href") == "https://studio.youtube.com/video/b8Ep79QKIk4/edit" for n in nodes)
    assert not any(n["tag"] == "img" for n in nodes)  # title stays text
    doc["missing"], doc["duplicates"] = {}, []
    assert not any(n["attrs"].get("class") == "schedule-warnings" for n in walk(dom([doc])["tree"]))
    assert dom([])["message"] == "Chưa có số liệu"
