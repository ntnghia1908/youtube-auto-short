"""LNK1 HTTP/auth/UI integration. Run outside the socket-restricted implementer sandbox."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from auto_short.post import store
from auto_short.web.app import STATIC_DIR
from test_post_links import (EID, EID2, KT, PID, PID2, SHORTS, SECRETS, seed, service, video)
from web_helpers import login, make_app


@pytest.fixture
def web(service):
    svc, ctx, wire = service
    app = make_app(ctx.config, playlist_lister=lambda url, cfg: dict(title="Bộ kinh", entries=[
        dict(id=EID, title="Bộ kinh tập 1")]))
    app.state.post_links.api_factory = svc.api_factory
    with TestClient(app, follow_redirects=False) as client:
        yield client, app, ctx, wire


def base(pid=PID):
    return f"/api/playlists/{pid}/link-playlists"


def test_all_routes_require_login_and_missing_playlist(web):  # AC9,10
    c, _, _, _ = web
    calls = [("GET", base(), None), ("POST", base(), {"url": f"https://youtube.com/playlist?list={SHORTS}"}),
             ("DELETE", base() + "/" + SHORTS, None), ("POST", base() + "/sync", None)]
    for method, url, body in calls:
        assert c.request(method, url, json=body).status_code == 401
    login(c)
    for method, url, body in calls:
        assert c.request(method, url.replace(PID, "PLmissing0001"), json=body).status_code == 404


@pytest.mark.parametrize("url", ["", "not-url", "https://evil.example/playlist?list=PLshorts00001",
    "https://youtube.com/playlist?list=RDabc01234567", "https://youtube.com/playlist?list=WL",
    "https://youtube.com/playlist?list=LL", "https://youtube.com/watch?v=youtube0001&list=RDabcdefghijk",
    "https://youtube.com/playlist?list=short", "https://youtube.com/watch?v=youtube0001"])
def test_invalid_and_mix_urls_are_422(web, url):  # AC9
    c, _, ctx, wire = web
    login(c)
    assert c.post(base(), json={"url": url}).status_code == 422
    assert not ctx.playlists.load(PID).get("link_playlists") and not wire.calls


def test_add_sync_read_refresh_remove_and_copy_text(web):  # AC1,3,4,7,9,10
    c, app, ctx, wire = web
    seed(ctx)
    seed(ctx, EID + ".kt")
    seed(ctx, EID2)
    login(c)
    wire.private.add(KT)
    r = c.post(base(), json={"url": f"https://youtube.com/playlist?list={KT}&si=tracking"})
    assert r.status_code == 200 and r.json()["last_scan"]["counts"]["filled"] == 1
    r = c.post(base(), json={"url": f"https://youtube.com/watch?v=youtube0001&list={SHORTS}"})
    assert r.status_code == 200 and r.json()["last_scan"]["counts"]["filled"] == 1
    assert c.get(base()).json()["link_playlists"] == [KT, SHORTS]
    assert c.get(base(PID2)).json()["link_playlists"] == []
    assert store.read_posts(ctx.posts_path(EID2), EID2)["posts"][0]["link"] is None
    assert c.post(base() + "/sync").json()["last_scan"]["counts"]["unchanged"] == 2
    # Existing user fields and attachments survive refresh and other edits.
    assert c.post(f"/api/playlists/{PID}/refresh").status_code == 200
    assert c.put(f"/api/playlists/{PID}/hashtags", json={"hashtags": ["Kinh"]}).status_code == 200
    assert c.get(base()).json()["link_playlists"] == [KT, SHORTS]
    view = c.get(f"/api/playlists/{PID}").json()
    assert view["post_links"]["last_scan"]["scanned_at"]
    assert view["post_links"]["link_sync_hours"] == 0
    assert c.delete(base() + "/" + SHORTS).status_code == 200
    assert c.get(base()).json()["link_playlists"] == [KT]
    post = store.read_posts(ctx.posts_path(EID), EID)["posts"][0]
    assert post["link"] == "https://youtube.com/shorts/youtube0001" and post["posted_at"]
    from auto_short.post.logic import compose_copy_text
    assert "▶ Xem video: https://youtube.com/shorts/youtube0001" in compose_copy_text(
        title="Tiêu đề", paragraphs=post["paragraphs"], header_fields=None, link=post["link"], hashtags=[])
    assert not app.state.runner.jobs()  # scans never enter the job lanes


def test_errors_preserve_links_and_report_unmatched_titles(web, caplog):  # AC2,3,5,6,7a
    c, _, ctx, wire = web
    seed(ctx, link="https://youtube.com/shorts/manual00001")
    wire.videos[SHORTS] += [video("youtube0003", "", "Video không mã"),
                            video("youtube0004", "T99_S01.mp4", "T99 S01 Chưa khớp")]
    login(c)
    r = c.post(base(), json={"url": f"https://youtube.com/playlist?list={SHORTS}"}).json()["last_scan"]
    assert r["counts"]["different"] == 1 and r["counts"]["no_code"] == 1 and r["counts"]["unmatched"] == 1
    assert {row["title"] for row in r["rows"]} >= {"Video không mã", "T99 S01 Chưa khớp"}
    wire.fail.add(SHORTS)
    r = c.post(base() + "/sync").json()
    assert "quota" in r["last_scan"]["errors"][0]["error"]
    assert store.read_posts(ctx.posts_path(EID), EID)["posts"][0]["link"].endswith("manual00001")
    assert not any(secret in json.dumps(r) + caplog.text for secret in SECRETS)
    wire.fail.clear()
    assert not c.post(base() + "/sync").json()["last_scan"]["errors"]


def test_ui_hooks_vietnamese_result_and_safe_dom():  # AC9
    html = (STATIC_DIR / "playlist.html").read_text()
    js = (STATIC_DIR / "app.js").read_text()
    for ident in ("lp-input", "lp-add", "lp-sync", "lp-list", "lp-result", "lp-errors", "lp-unmatched"):
        assert f'id="{ident}"' in html
    assert "Link bài đăng từ YouTube" in html and "Cập nhật ngay" in html
    assert "khác link" in js and "chờ soạn" in js and "scanned_at" in js
    assert "/link-playlists${suffix}" in js and "linkPlaylistsLoad(d.post_links)" in js
    assert 'text: r.title' in js  # external video titles go through textContent
