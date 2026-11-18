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


@pytest.mark.parametrize("age", [None, 0, 5 * 86400, 7 * 86400])
def test_amendment_api_local_errors_and_testing_token_metadata_without_secrets(web, age):  # AC6–7
    client, ctx, wire = web
    path = youtube.default_token()
    token = dict(read_json_dict(path), client_path="private-client", client_secret="private-secret")
    if age is not None:
        token["authorized_at"] = NOW.timestamp() - age
    atomic_write_json(path, token)
    doc = dict(snapshot(ctx.config), token="default")
    overview.write(ctx.config, doc)
    overview.check_error(ctx.config, "default", NOW, "quotaExceeded private-secret")
    paths = [path, *ctx.config.workspace.dir.joinpath("_publish/channels").glob("*.json")]
    before = {path: path.read_bytes() for path in paths}
    login(client)
    response = client.get("/api/schedule-overview")
    data = response.json()
    assert data["channels"][0]["token"] == "default"
    assert data["errors"] == [dict(token="default", at=overview._iso(NOW), message="hết hạn mức YouTube")]
    assert data["tokens"]["default"] == overview.token_status(token, NOW)
    assert data["tokens"]["b"]["days_left"] is None
    assert not any(secret in response.text for secret in ("private-client", "private-secret", token["access_token"],
                                                         token["refresh_token"]))
    assert {path: path.read_bytes() for path in paths} == before and not wire.calls


def test_amendment_page_empty_errors_token_expiry_and_device_flow_dom(service):  # AC6–8
    if not shutil.which("node"):
        pytest.skip("node required for page DOM verification")
    _, ctx, _ = service
    doc = dict(snapshot(ctx.config), token="default")
    # Extend the existing DOM harness to exercise the actual click handler and queued 5s poll.
    script = DOM_SCRIPT.replace("addEventListener() {}", "addEventListener(kind, fn) { this[kind] = fn; }")
    script = script.replace("vm.runInNewContext", "const calls = [], timers = [];\nvm.runInNewContext")
    script = script.replace("api: async path =>", "api: async (path, options = {}) =>")
    script = script.replace("if (path !== '/api/schedule-overview') throw Error('unexpected URL'); return { channels: payload.channels };",
                            "if (path === '/api/schedule-overview') return payload; "
                            "calls.push({path, options}); return payload.auth.shift();")
    script = script.replace("}, Intl, Date,", "}, Intl, Date, setTimeout: (fn, ms) => { timers.push({fn, ms}); return 1; }, "
                            "clearTimeout: () => {},")
    script = script[:script.index("setImmediate(() => process.stdout.write")]+ r"""
function all(n) { return [n, ...(n.childNodes || []).flatMap(c => typeof c === 'object' ? all(c) : [])]; }
setImmediate(async () => {
  const button = all(nodes['schedule-channels']).find(n => n.tag === 'button');
  const initial = nodes['schedule-channels'].textContent;
  await button.click();
  const waiting = nodes['schedule-channels'].textContent;
  const link = all(nodes['schedule-channels']).find(n => n.attrs.href === 'https://www.google.com/device');
  const delay = timers[0].ms;
  await timers[0].fn();
  await Promise.resolve();
  process.stdout.write(JSON.stringify({initial, waiting, final: nodes['schedule-channels'].textContent,
    link: link.attrs.href, delay, calls}));
});
"""
    for channels, days in (([], None), ([doc], 2), ([doc], 0)):
        payload = dict(script=str(STATIC_DIR / "schedule.js"), channels=channels,
                       tokens={"default": dict(days_left=days, expires_at=NOW.timestamp(), warning=days is not None,
                                               expired=days == 0)},
                       errors=[dict(token="default", at=overview._iso(NOW), message="hết hạn mức YouTube")],
                       auth=[dict(status="waiting", user_code="ABCD-EFGH", verification_url="https://www.google.com/device",
                                  expires_in=60), dict(status="done", message="Đã lấy token mới")])
        result = subprocess.run(["node", "-e", script], input=json.dumps(payload), text=True,
                                capture_output=True, timeout=10, check=True)
        data = json.loads(result.stdout)
        assert "Lần đọc" in data["initial"] and "hết hạn mức YouTube — tự thử lại 15:30" in data["initial"]
        if not channels:
            assert "Chưa có số liệu. Số liệu cập nhật tự động lúc 15:30" in data["initial"]
        assert ("Token không rõ hạn" if days is None else "Token còn 2 ngày" if days else "Token hết hạn") in data["initial"]
        assert "ABCD-EFGH" in data["waiting"] and data["link"] == "https://www.google.com/device"
        assert data["delay"] == 5000 and "Đã lấy token mới" in data["final"]
        assert data["calls"] == [dict(path="/api/youtube-tokens/default/auth", options=dict(method="POST")),
                                  dict(path="/api/youtube-tokens/default/auth", options={})]
    assert "Chỉ đọc lại số liệu đã lưu, không gọi YouTube" in (STATIC_DIR / "schedule.html").read_text()


def test_amendment_b_api_filters_on_read_and_page_uses_visible_lists(web):  # AC9
    client, ctx, wire = web
    doc = snapshot(ctx.config)
    old, exact = "2026-10-31T16:59:59Z", "2026-10-31T17:00:00Z"
    doc.update(missing={"kt": [dict(key="T30_KT06", since=exact), dict(key="T2_KT02", since=old),
                               dict(key="T1_KT01", since=None)]},
               duplicates=[dict(kind="short", key=key, uploaded_at=stamp,
                                copies=[dict(youtube_id=key, keep=False)])
                           for key, stamp in (("T30_S01", exact), ("T2_S01", old))],
               unrecognized=[dict(youtube_id="new", uploaded_at=exact), dict(youtube_id="old", uploaded_at=old),
                             dict(youtube_id="undated", uploaded_at=None)], unrecognized_count=3)
    overview.write(ctx.config, doc)
    legacy = snapshot(ctx.config, "UClegacy", "Legacy")
    legacy.update(missing={"vertical": ["T1"]}, unrecognized_count=5,
                  duplicates=[dict(kind="kt", key="T1_KT01", copies=[])])
    overview.write(ctx.config, legacy)
    files = list(ctx.config.workspace.dir.joinpath("_publish/channels").glob("*.json"))
    before = {path: path.read_bytes() for path in files}
    login(client)
    rows = {row["channel_id"]: row for row in client.get("/api/schedule-overview").json()["channels"]}
    filtered = rows["UC1"]
    assert filtered["missing"]["kt"] == [dict(key="T30_KT06", since=exact)]
    assert [row["key"] for row in filtered["duplicates"]] == ["T30_S01"]
    assert filtered["unrecognized"] == [dict(youtube_id="new", uploaded_at=exact)]
    assert filtered["unrecognized_count"] == 1
    assert rows["UClegacy"]["missing"] == legacy["missing"]
    assert rows["UClegacy"]["duplicates"] == legacy["duplicates"]
    assert rows["UClegacy"]["unrecognized_count"] == 5
    rendered = dom([filtered])["text"]
    assert "T30_KT06" in rendered and "T30_S01" in rendered and "Không nhận ra loại: 1 video" in rendered
    assert "T2_KT02" not in rendered and "T2_S01" not in rendered and "T1_KT01" not in rendered
    assert "Chỉ cảnh báo từ 01/11/2026" in rendered
    # A changed cutoff takes effect without rewriting / regenerating the snapshot.
    from unittest.mock import patch
    with patch.object(overview, "ISSUES_SINCE", "2027-01-01T00:00:00+07:00"):
        rows = client.get("/api/schedule-overview").json()["channels"]
    filtered = next(row for row in rows if row["channel_id"] == "UC1")
    assert filtered["unrecognized_count"] == 0 and filtered["duplicates"] == []
    assert filtered["missing"]["kt"] == []
    assert not any(n["attrs"].get("class") == "schedule-warnings" for n in walk(dom([filtered])["tree"]))
    assert {path: path.read_bytes() for path in files} == before and not wire.calls
