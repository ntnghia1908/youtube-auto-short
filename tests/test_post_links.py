"""LNK1 matching + web service; fake Data API GET / OAuth refresh, no socket required."""
from __future__ import annotations

import asyncio
import json
import socket
import stat
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from auto_short.config import Config, PostConfig, RenderConfig, WorkspaceConfig, load, ConfigError
from auto_short.post import links, store
from auto_short.publish import PublishError, youtube
from auto_short.web.playlists import PlaylistStore
from auto_short.web.post_links import PostLinks, playlist_id_from_url
from auto_short.workspace import atomic_write_json, read_json_dict
from web_helpers import write_episode

PID, PID2 = "PLsource00001", "PLsource00002"
SHORTS, KT = "PLshorts00001", "PLkhaithi0001"
EID, EID2 = "source00001", "source00002"
NOW = "2026-11-01T00:00:00Z"
SECRETS = ("private-access-a", "private-refresh", "private-client")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("LNK1 tests must inject a transport")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def video(ident="youtube0001", filename="T1_S01_title.mp4", title="T1 S01 Tựa đề"):
    return dict(id=ident, fileDetails=dict(fileName=filename), snippet=dict(title=title),
                status=dict(privacyStatus="private", publishAt="2026-12-01T00:00:00Z"))


def target(code="T1_S01", eid=EID, cid="k01", kt=False):
    return dict(code=code, episode_id=eid, clip_id=cid, khaithi=kt)


@pytest.mark.parametrize("text,expected", [
    ("T1 S10 Tựa đề", "T1_S10"), ("  T7_S07_Tựa", "T7_S07"), ("T1_S10_x.mp4", "T1_S10"),
    ("T29_KT01.mp4", "T29_KT01"), ("T29_S010", "T29_S010"), ("T1_KT100_", "T1_KT100"),
    ("T1_S01", "T1_S01"), ("T1_S1_x", None), ("T1_S0001", None), ("T1_S01x", None),
    ("prefix T1_S01", None), ("t1_s01", None), ("", None), (None, None), ("T1_S00", None),
])
def test_parse_code(text, expected):  # AC5
    assert links.parse_code(text) == expected


def test_plan_filename_fallback_exact_width_and_reasons():  # AC1,3,5,6
    entries = [video(), video("youtube0002", "", "T1 S02 Tiêu đề"),
               video("youtube0003", "plain.mp4", "plain title"), video("youtube0004", "T1_S010.mp4", ""),
               video("youtube0005", "T1_KT01.mp4", "T1 KT01"), video("youtube0006", "T1_S03.mp4", "")]
    targets = [target(), target("T1_S02", cid="k02"), target("T1_KT01", EID + ".kt", kt=True),
               target("T1_S03", cid="k03")]
    current = {(EID, "k01"): None, (EID, "k02"): "https://youtube.com/shorts/manual00001",
               (EID + ".kt", "k01"): None}
    result = links.plan(entries, targets, current)
    assert [r["reason"] for r in result["rows"]] == ["filled", "different", "no_code", "unmatched", "filled", "waiting"]
    assert [u["link"] for u in result["updates"]] == ["https://youtube.com/shorts/youtube0001",
                                                        "https://youtube.com/watch?v=youtube0005"]
    current[(EID, "k03")] = None
    assert links.plan(entries, targets, current)["counts"]["filled"] == 3


@pytest.mark.parametrize("current,expected", [
    pytest.param({(EID, "k02"): "https://youtube.com/shorts/youtube0001"}, "unchanged", id="short-link"),
    pytest.param({(EID + ".kt", "k02"): "https://youtube.com/watch?v=youtube0001"}, "unchanged", id="watch-link"),
    pytest.param({}, "no_code", id="no-link"),
    pytest.param({(EID, "k02"): "https://youtube.com/shorts/youtube0002"}, "no_code", id="other-video"),
    pytest.param({(EID, "k02"): None}, "no_code", id="none-link"),
    pytest.param({(EID, "k01"): None, (EID, "k02"): "https://youtube.com/watch?v=youtube0001"},
                 "unchanged", id="none-and-matching-link"),
])
def test_plan_no_code_existing_links(current, expected):  # AC5a, L3a
    result = links.plan([video(filename="plain.mp4", title="Không mã")], [target()], current)
    assert result["updates"] == []
    assert result["rows"][0]["reason"] == expected
    assert result["counts"][expected] == 1
    assert sum(result["counts"].values()) == 1


def test_duplicates_and_conflicting_codes_block_all_involved():  # AC4, L2a
    entries = [video(), video("youtube0002"), video("youtube0003", "T1_S02.mp4", "T1_S03 title"),
               video("youtube0004", "T1_S03.mp4", ""), video("youtube0005", "T1_S04.mp4", "")]
    targets = [target(), target("T1_S02", cid="k02"), target("T1_S03", cid="k03"),
               target("T1_S04", cid="k04"), target("T1_S04", EID2, "k04")]
    result = links.plan(entries, targets, {(EID, "k01"): None})
    assert result["counts"]["duplicate"] == 5 and not result["updates"]
    assert links.plan([video(), video()], [target()], {(EID, "k01"): None})["counts"]["filled"] == 1
    assert links.plan([video()], [target()], {(EID, "k01"): links.link_for("youtube0001", False)})["counts"]["unchanged"] == 1


class Wire:
    def __init__(self):
        self.calls, self.videos = [], {SHORTS: [video()], KT: [video("youtube0002", "T1_KT01.mp4", "T1 KT01")]}
        self.owners = {SHORTS: "channel-a", KT: "channel-b"}
        self.fail = set()
        self.private = set()
        self.before_videos = None

    def __call__(self, method, url, headers, body):
        assert method == "GET" and body is None, "web Data API calls must be GET"
        self.calls.append((url, headers["Authorization"]))
        q, resource = parse_qs(urlsplit(url).query), urlsplit(url).path.rsplit("/", 1)[-1]
        channel = "channel-a" if headers["Authorization"] == "Bearer " + SECRETS[0] else "channel-b"
        status = 200
        if resource == "channels":
            doc = dict(items=[dict(id=channel)])
        elif resource == "playlists":
            ident = q["id"][0]
            if ident not in self.owners or (ident in self.private and self.owners[ident] != channel):
                doc = dict(items=[])
            else:
                doc = dict(items=[dict(snippet=dict(channelId=self.owners[ident], channelTitle="Kênh " + self.owners[ident]))])
        elif resource == "playlistItems":
            ident = q["playlistId"][0]
            assert self.owners[ident] == channel
            if ident in self.fail:
                status, doc = 403, dict(error=dict(message=" ".join(SECRETS), errors=[dict(reason="quotaExceeded")]))
            else:
                assert q["maxResults"] == ["50"]
                doc = dict(items=[dict(contentDetails=dict(videoId=v["id"])) for v in self.videos[ident]])
        elif resource == "videos":
            assert q["part"] == ["fileDetails,snippet,status"]
            if self.before_videos:
                self.before_videos()
            ids = q["id"][0].split(",")
            doc = dict(items=[v for vs in self.videos.values() for v in vs if v["id"] in ids])
        else:
            pytest.fail(resource)
        return status, {}, json.dumps(doc).encode()


def seed(ctx, eid=EID, cid="k01", link=None, posted=True):
    path = ctx.posts_path(eid)
    doc = store.with_compose(store.read_posts(path, eid), ["k01", "k02"], clip_id=cid, candidate_id="c00001",
                             source_sha256="a" * 64, paragraphs=["Nội dung gốc."], origin="manual", image="01.jpg", now=NOW)
    doc = store.with_fields(doc, ["k01", "k02"], cid, {"link": link, "posted_at": NOW if posted else None}, now=NOW)
    store.write(path, doc)


@pytest.fixture
def service(tmp_path, monkeypatch):
    cfg = Config(workspace=WorkspaceConfig(tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 post=PostConfig(link_sync_hours=0))
    tokens = tmp_path / "tokens"
    tokens.mkdir()
    default = tmp_path / "default-token.json"
    monkeypatch.setattr(youtube, "default_token", lambda: default)
    monkeypatch.setattr(youtube, "default_token_dir", lambda: tokens)
    for path, access in ((default, SECRETS[0]), (tokens / "b.json", "private-access-b")):
        atomic_write_json(path, dict(access_token=access, expires_at=9999999999, refresh_token=SECRETS[1]))
    ctx = SimpleNamespace(config=cfg, playlists=PlaylistStore(cfg), post_lock=threading.Lock(),
                          posts_path=lambda eid: cfg.workspace.dir / eid / store.POSTS_NAME)
    for pid, eid in ((PID, EID), (PID2, EID2)):
        atomic_write_json(ctx.playlists.path(pid), dict(playlist_id=pid, title="Bộ kinh", entries=[dict(video_id=eid)],
                                                     hashtags=["Kinh"], series="Bộ", doc_url="giữ nguyên"))
        for episode_id in (eid, eid + ".kt"):
            write_episode(cfg, episode_id)
            atomic_write_json(cfg.workspace.dir / episode_id / "titles.json", dict(header=dict(fields=dict(episode="1"))))
            if episode_id.endswith(".kt"):
                atomic_write_json(cfg.workspace.dir / episode_id / "khaithi.json", {})
    wire = Wire()
    svc = PostLinks(ctx, api_factory=lambda **kw: youtube.YouTube(transport=wire, **kw))
    return svc, ctx, wire


def test_service_add_private_scheduled_short_khaithi_scoped_and_locked(service, monkeypatch):  # AC1,3,4,7a,10
    svc, ctx, wire = service
    wire.private.add(KT)
    seed(ctx)
    seed(ctx, EID + ".kt")
    seed(ctx, EID2)
    before = store.read_posts(ctx.posts_path(EID), EID)["posts"][0]
    write = store.write
    def locked_write(*args):
        assert ctx.post_lock.locked()
        write(*args)
    monkeypatch.setattr(store, "write", locked_write)
    assert svc.add(PID, f"https://youtube.com/playlist?list={KT}&si=abc")["last_scan"]["counts"]["filled"] == 1
    result = svc.add(PID, f"https://youtube.com/watch?v=youtube0001&list={SHORTS}")
    assert result["last_scan"]["counts"]["filled"] == 1 and not result["last_scan"]["errors"]
    post = store.read_posts(ctx.posts_path(EID), EID)["posts"][0]
    assert {k: v for k, v in post.items() if k not in ("link", "updated_at")} == {
        k: v for k, v in before.items() if k not in ("link", "updated_at")}
    assert post["link"] == "https://youtube.com/shorts/youtube0001"
    assert store.read_posts(ctx.posts_path(EID + ".kt"), EID + ".kt")["posts"][0]["link"] == "https://youtube.com/watch?v=youtube0002"
    assert store.read_posts(ctx.posts_path(EID2), EID2)["posts"][0]["link"] is None
    assert read_json_dict(ctx.playlists.path(PID))["hashtags"] == ["Kinh"]
    svc.remove(PID, SHORTS)
    assert store.read_posts(ctx.posts_path(EID), EID)["posts"][0]["link"] == post["link"]


def test_missing_post_then_compose_and_manual_edit_during_network(service):  # AC3,6
    svc, ctx, wire = service
    assert svc.add(PID, f"https://youtube.com/playlist?list={SHORTS}")["last_scan"]["counts"]["waiting"] == 1
    assert not ctx.posts_path(EID).exists()
    seed(ctx)
    assert svc.sync(PID)["last_scan"]["counts"]["filled"] == 1
    wire.before_videos = lambda: seed(ctx, link="https://youtube.com/shorts/manual00001")
    assert svc.sync(PID)["last_scan"]["counts"]["different"] == 1
    assert store.read_posts(ctx.posts_path(EID), EID)["posts"][0]["link"].endswith("manual00001")


def test_cross_playlist_duplicates_and_no_match_titles(service):  # AC4,5,7
    svc, ctx, wire = service
    seed(ctx)
    wire.videos[KT] = [video("youtube0002"), video("youtube0003", "", "Không mã"),
                       video("youtube0004", "T99_S01.mp4", "T99 S01 Không có Short")]
    ctx.playlists.set_link_playlist(PID, KT)
    result = svc.add(PID, f"https://youtube.com/playlist?list={SHORTS}")["last_scan"]
    assert result["counts"]["duplicate"] == 2 and result["counts"]["no_code"] == result["counts"]["unmatched"] == 1
    assert result["rows"][1]["title"] == "Không mã"
    assert store.read_posts(ctx.posts_path(EID), EID)["posts"][0]["link"] is None


def test_quota_failure_bad_token_missing_owner_and_retry(service, caplog):  # AC2,7a,8
    svc, ctx, wire = service
    seed(ctx)
    seed(ctx, EID + ".kt")
    ctx.playlists.set_link_playlist(PID, SHORTS)
    ctx.playlists.set_link_playlist(PID, KT)
    wire.fail.add(SHORTS)
    result = svc.sync(PID)["last_scan"]
    assert result["counts"]["filled"] == 1 and "quota" in result["errors"][0]["error"]
    wire.fail.clear()
    assert svc.sync(PID)["last_scan"]["counts"]["filled"] == 1
    (youtube.default_token_dir() / "b.json").write_text("broken")
    result = svc.sync(PID)["last_scan"]
    assert "channel-b" in result["errors"][0]["error"] and "auth --token" in result["errors"][0]["error"]
    assert not any(s in svc.path.read_text() + caplog.text + json.dumps(result) for s in SECRETS)
    # Bad default token cannot stop the other channel.
    youtube.default_token().write_text("broken")
    atomic_write_json(youtube.default_token_dir() / "b.json", dict(access_token="b", expires_at=9999999999))
    result = svc.sync(PID)["last_scan"]
    assert len(result["errors"]) == 1 and result["errors"][0]["playlist_id"] == SHORTS


def test_timeout_and_unexpected_error_never_leak(service, caplog):
    svc, ctx, wire = service
    ctx.playlists.set_link_playlist(PID, SHORTS)
    class Broken:
        def channel_id(self): return "channel-a"
        def playlist_channel(self, ident): return dict(id="channel-a", title="Kênh")
        def playlist_videos(self, ident): raise TimeoutError(" ".join(SECRETS))
    svc.api_factory = lambda **kw: Broken()
    result = svc.sync(PID)
    assert "quá thời gian" in result["last_scan"]["errors"][0]["error"]
    assert not any(s in json.dumps(result) + svc.path.read_text() + caplog.text for s in SECRETS)


def test_manifest_position_header_number_and_duplicate_local_targets(service):
    svc, ctx, wire = service
    # Local playlist metadata is not the authority for the episode number.
    doc = ctx.playlists.load(PID)
    doc["entries"][0]["episode"] = "99"
    atomic_write_json(ctx.playlists.path(PID), doc)
    manifest_path = ctx.config.render.output_dir / EID / "render_manifest.json"
    manifest = read_json_dict(manifest_path)
    manifest["shorts"][0]["status"] = "skipped"
    atomic_write_json(manifest_path, manifest)
    seed(ctx, cid="k02")
    wire.videos[SHORTS] = [video(filename="T1_S02.mp4", title="T1 S02")]
    assert svc.add(PID, f"https://youtube.com/playlist?list={SHORTS}")["last_scan"]["counts"]["filled"] == 1
    doc = ctx.playlists.load(PID)
    doc["entries"].append(dict(video_id=EID2))
    atomic_write_json(ctx.playlists.path(PID), doc)
    assert svc.sync(PID)["last_scan"]["counts"]["duplicate"] == 1


@pytest.mark.parametrize("url", ["https://youtube.com/playlist?list=RDabcdefghijk", "https://youtube.com/playlist?list=WL",
    "https://youtube.com/playlist?list=LL", "https://youtube.com/watch?v=youtube0001&list=RDabcdefghijk",
    "https://evil.example/playlist?list=PLshorts00001", "https://youtube.com/watch?v=youtube0001", "bad"])
def test_reject_invalid_playlist(url):  # AC9
    with pytest.raises(ValueError):
        playlist_id_from_url(url)


def test_loop_interval_zero_and_continues_after_errors(monkeypatch):  # AC8
    from auto_short.web.app import _post_link_loop
    class Service:
        calls = 0
        def sync_all(self):
            self.calls += 1
            if self.calls == 1: raise TimeoutError("private")
    service = Service()
    with pytest.raises(StopIteration):
        _post_link_loop(service, 0).send(None)
    assert service.calls == 0
    sleeps, offloaded = [], []
    async def to_thread(fn):
        offloaded.append(fn)
        return fn()
    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2: raise asyncio.CancelledError
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(asyncio, "to_thread", to_thread)
    with pytest.raises(asyncio.CancelledError): _post_link_loop(service, 0.5).send(None)
    assert service.calls == len(offloaded) == 2 and sleeps == [1800, 1800]


def test_sync_all_isolates_failures(service, monkeypatch):
    svc, ctx, _ = service
    for pid in (PID, PID2): ctx.playlists.set_link_playlist(pid, SHORTS)
    calls = []
    def sync(pid):
        calls.append(pid)
        if pid == PID: raise OSError("disk")
    monkeypatch.setattr(svc, "sync", sync)
    svc.sync_all()
    assert calls == [PID, PID2]


@pytest.mark.parametrize("operation", ["view", "remove"])
def test_view_and_remove_do_not_wait_for_scan_network(service, operation):  # F2
    svc, ctx, _ = service
    ctx.playlists.set_link_playlist(PID, SHORTS)
    prior_scan = dict(scanned_at=NOW, counts={}, rows=[], errors=[])
    atomic_write_json(svc.path, {PID: prior_scan})
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    factory = svc.api_factory
    results, errors = [], []

    def blocked_factory(**kw):
        entered.set()
        assert release.wait(5), "test did not release the fake API"
        return factory(**kw)

    def scan():
        try:
            svc.sync(PID)
        except BaseException as exc:
            errors.append(exc)

    def read_or_remove():
        try:
            results.append(svc.view(PID) if operation == "view" else svc.remove(PID, SHORTS))
        except BaseException as exc:
            errors.append(exc)
        finally:
            returned.set()

    svc.api_factory = blocked_factory
    scanning = threading.Thread(target=scan, daemon=True)
    reading = threading.Thread(target=read_or_remove, daemon=True)
    scanning.start()
    try:
        assert entered.wait(2), "scan never entered the fake API"
        reading.start()
        assert returned.wait(2), f"{operation} waited for the network scan lock"
        assert not release.is_set() and scanning.is_alive()
        assert results[0]["last_scan"] == prior_scan
        assert results[0]["link_playlists"] == ([SHORTS] if operation == "view" else [])
    finally:
        release.set()
        scanning.join(2)
        if reading.ident is not None:
            reading.join(2)
    assert not errors and not scanning.is_alive() and not reading.is_alive()


@pytest.mark.parametrize("removed", [SHORTS, KT])
def test_sync_ignores_playlist_removed_while_reading_youtube(service, removed):  # reviewer P2
    svc, ctx, _ = service
    for ident in (SHORTS, KT):
        ctx.playlists.set_link_playlist(PID, ident)
    seed(ctx)
    seed(ctx, EID + ".kt")
    factory = svc.api_factory
    removals = []

    def removing_factory(**kw):
        api = factory(**kw)
        read_videos = api.playlist_videos
        def playlist_videos(ident):
            videos = read_videos(ident)
            if ident == removed:
                svc.remove(PID, ident)
                removals.append(ident)
            return videos
        api.playlist_videos = playlist_videos
        return api

    svc.api_factory = removing_factory
    result = svc.sync(PID)
    assert removals == [removed]
    assert result["link_playlists"] == [ident for ident in (SHORTS, KT) if ident != removed]
    assert result["last_scan"]["counts"]["filled"] == 1
    assert not result["last_scan"]["errors"]
    for ident, eid, vid in ((SHORTS, EID, "youtube0001"), (KT, EID + ".kt", "youtube0002")):
        post = store.read_posts(ctx.posts_path(eid), eid)["posts"][0]
        assert post["link"] == (None if ident == removed else links.link_for(vid, ident == KT))


def test_scan_journal_only_keeps_rows_needing_attention(service):  # F3
    svc, ctx, wire = service
    wire.videos[KT] = []  # the fake transport resolves ids across its playlists; keep this set disjoint
    write_episode(ctx.config, EID, clips=tuple(f"k{n:02}" for n in range(1, 6)))
    seed(ctx)
    seed(ctx, cid="k02", link=links.link_for("youtube0002", False))
    seed(ctx, cid="k03", link=links.link_for("manual00001", False))
    wire.videos[SHORTS] = [video(), video("youtube0002", "T1_S02.mp4", "T1 S02"),
        video("youtube0003", "T1_S03.mp4", "T1 S03"), video("youtube0004", "T1_S04.mp4", "T1 S04"),
        video("youtube0005", "T1_S05.mp4", "T1 S05"), video("youtube0006", "T1_S05.mp4", "T1 S05"),
        video("youtube0007", "", "Không mã"), video("youtube0008", "T99_S01.mp4", "T99 S01")]
    ctx.playlists.set_link_playlist(PID, SHORTS)
    targets, _ = svc._targets(ctx.playlists.load(PID))
    current = {(EID, p["clip_id"]): p["link"] for p in store.read_posts(ctx.posts_path(EID), EID)["posts"]}
    planned = links.plan(wire.videos[SHORTS], targets, current)
    assert len(planned["rows"]) == 8 and planned["counts"]["filled"] == planned["counts"]["unchanged"] == 1
    scan = svc.sync(PID)["last_scan"]
    expected = [row for row in planned["rows"] if row["reason"] not in {"filled", "unchanged"}]
    assert len(expected) == 6
    assert {row["reason"] for row in expected} == {"no_code", "unmatched", "duplicate", "different", "waiting"}
    assert scan["rows"] == expected and scan["counts"] == planned["counts"]
    assert read_json_dict(svc.path)[PID]["rows"] == svc.view(PID)["last_scan"]["rows"] == expected
    assert svc.sync(PID)["last_scan"]["rows"] == expected


def test_read_only_rejects_data_api_post_before_refresh(service):  # AC10, F1
    _, _, wire = service
    api = youtube.YouTube(transport=wire, read_only=True)
    api.token["expires_at"] = 0
    with pytest.raises(PublishError, match="GET"): api.set_thumbnail("youtube0001", b"image")
    assert not wire.calls


@pytest.mark.parametrize("expired", [True, False])
def test_read_only_refreshes_oauth_then_gets_and_saves_private_atomic_token(service, tmp_path, monkeypatch, expired):  # F1
    client = tmp_path / "client.json"
    atomic_write_json(client, dict(client_id="test-client", client_secret=SECRETS[2]))
    token_path = youtube.default_token()
    token = read_json_dict(token_path)
    if expired:
        atomic_write_json(token_path, dict(token, expires_at=0))
    replacements = []
    original_replace = youtube.os.replace
    def checked_replace(src, dest):
        if dest == token_path:
            assert stat.S_IMODE(src.stat().st_mode) == 0o600
            assert stat.S_IMODE(src.parent.stat().st_mode) == 0o700
            replacements.append(dest)
        original_replace(src, dest)
    monkeypatch.setattr(youtube.os, "replace", checked_replace)
    calls = []
    def wire(method, url, headers, body):
        calls.append((method, url))
        if url == youtube.TOKEN_URL:
            assert method == "POST" and "Authorization" not in headers
            assert parse_qs(body.decode())["grant_type"] == ["refresh_token"]
            return 200, {}, json.dumps(dict(access_token="refreshed-private-access", expires_in=3600)).encode()
        assert method == "GET" and url.startswith(youtube.API_URL) and body is None
        if not expired and len(calls) == 1:
            return 401, {}, json.dumps(dict(error={})).encode()
        assert headers["Authorization"] == "Bearer refreshed-private-access"
        return 200, {}, json.dumps(dict(items=[dict(id="channel-a")])).encode()
    api = youtube.YouTube(client_path=client, transport=wire, read_only=True, now=lambda: 1000)
    assert api.channel_id() == "channel-a"
    assert [method for method, _ in calls] == (["POST", "GET"] if expired else ["GET", "POST", "GET"])
    assert replacements == [token_path] and stat.S_IMODE(token_path.stat().st_mode) == 0o600
    saved = read_json_dict(token_path)
    assert saved["refresh_token"] == SECRETS[1] and saved["expires_at"] == 4600
    with pytest.raises(PublishError, match="GET"): api.set_thumbnail("youtube0001", b"image")
    assert len(calls) == (2 if expired else 3)


def test_read_only_refresh_failure_does_not_expose_secrets(service, tmp_path):
    client = tmp_path / "client.json"
    atomic_write_json(client, dict(client_id="test-client", client_secret=SECRETS[2]))
    calls = []
    def wire(method, url, headers, body):
        calls.append((method, url))
        if url == youtube.TOKEN_URL:
            assert method == "POST"
            return 400, {}, json.dumps(dict(error="invalid_grant", error_description=" ".join(SECRETS))).encode()
        assert method == "GET" and url.startswith(youtube.API_URL)
        return 401, {}, json.dumps(dict(error=dict(message=" ".join(SECRETS)))).encode()
    with pytest.raises(PublishError, match="auth") as error:
        youtube.YouTube(client_path=client, transport=wire, read_only=True).channel_id()
    assert [method for method, _ in calls] == ["GET", "POST"] and not any(s in str(error.value) for s in SECRETS)


def test_playlist_pagination_batches_and_repeated_items(service):  # AC1,10
    ids = [f"youtube{n:04d}" for n in range(103)]
    pages = [dict(items=[dict(contentDetails=dict(videoId=ident)) for ident in ids[:50]], nextPageToken="p2"),
             dict(items=[dict(contentDetails=dict(videoId=ident)) for ident in ids[49:100]], nextPageToken="p3"),
             dict(items=[dict(contentDetails=dict(videoId=ident)) for ident in ids[100:]])]
    batches = [dict(items=[dict(id=ident) for ident in ids[n:n + 50]]) for n in range(0, 103, 50)]
    responses, queries = iter(pages + batches), []
    def wire(method, url, headers, body):
        assert method == "GET" and body is None
        queries.append(parse_qs(urlsplit(url).query))
        return 200, {}, json.dumps(next(responses)).encode()
    result = youtube.YouTube(transport=wire, read_only=True).playlist_videos(SHORTS)
    assert [v["id"] for v in result] == ids
    assert [q.get("pageToken") for q in queries[:3]] == [None, ["p2"], ["p3"]]
    assert all(q["playlistId"] == [SHORTS] and q["maxResults"] == ["50"] for q in queries[:3])
    assert [len(q["id"][0].split(",")) for q in queries[3:]] == [50, 50, 3]
    assert all(q["part"] == ["fileDetails,snippet,status"] for q in queries[3:])


def test_all_tokens_quota_and_playlist_owner_quota_reported(service):
    svc, ctx, wire = service
    ctx.playlists.set_link_playlist(PID, SHORTS)
    def quota(method, url, headers, body):
        assert method == "GET"
        return 403, {}, json.dumps(dict(error=dict(errors=[dict(reason="quotaExceeded")]))).encode()
    svc.api_factory = lambda **kw: youtube.YouTube(transport=quota, **kw)
    assert "quota" in svc.sync(PID)["last_scan"]["errors"][0]["error"]
    class OwnerQuota:
        def channel_id(self): return "channel-a"
        def playlist_channel(self, ident): raise PublishError("quotaExceeded " + SECRETS[0])
    svc.api_factory = lambda **kw: OwnerQuota()
    assert "quota" in svc.sync(PID)["last_scan"]["errors"][0]["error"]


def test_config_link_sync_hours(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[post]\nlink_sync_hours = 0\n")
    assert load(path).post.link_sync_hours == 0
    path.write_text("[post]\nlink_sync_hours = 1.5\n")
    assert load(path).post.link_sync_hours == 1.5
    for bad in ("-1", "true", '"six"', "nan", "inf"):
        path.write_text(f"[post]\nlink_sync_hours = {bad}\n")
        with pytest.raises(ConfigError): load(path)
    assert PostConfig().link_sync_hours == 6
