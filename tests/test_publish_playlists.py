"""Amendment B: owned playlist matching, insertion and per-token OAuth clients."""
from copy import deepcopy
import json
from pathlib import Path
import unicodedata
from urllib.parse import parse_qs, urlparse

import pytest

from auto_short.publish import PublishError, playlists, schedule, youtube
from auto_short.publish.__main__ import main
from auto_short.workspace import atomic_write_json, read_json_dict
from test_publish_schedule import NOW, local, video  # noqa: F401
from test_publish_thumbs import Clock, DEVICE, TOKEN, Wire, listing, no_sockets, oauth  # noqa: F401

SOURCE = "PLsourceB123"
KT = dict(id="kt-target", snippet=dict(title="[Tập 01-20] Khai thị Ngắn Thái Thượng Cảm Ứng Thiên"))
SHORT = dict(id="short-target", snippet=dict(title="[Tập 01-20] Short - Kinh Đại Thừa Vô Lượng Thọ"))
VERTICAL = dict(id="vertical-target", snippet=dict(title="[HD Moblie] Thái Thượng Cảm Ứng Thiên - Pháp Sư Tịnh Không"))


def channel_listing(*sources):
    replies = listing(*sources)
    replies[0]["items"][0]["id"] = "UCamendmentB"
    return replies if sources else replies[:2]


def members(*ids):
    return dict(items=[dict(contentDetails=dict(videoId=ident)) for ident in ids])


def source_playlist(cfg):
    atomic_write_json(cfg.workspace.dir / "_playlists" / f"{SOURCE}.json",
                      dict(playlist_id=SOURCE, entries=[]))


@pytest.mark.parametrize("title,kind,episode", [
    (KT["snippet"]["title"], "kt", 1), (KT["snippet"]["title"], "kt", 20),
    ("[ Tập 01-20] Khai Thị Ngắn - Kinh Địa Tạng Bồ Tát Bổn Nguyện", "kt", 11),
    ("[Tập 01-20] Khại Thi Ngan - Bộ kinh", "kt", 11),
    ("[Tập 21-40] Short - Kinh Đại Thừa Vô Lượng Thọ", "short", 21),
    ("[Tập 121-128] Short - Thái Thượng Cảm Ứng Thiên", "short", 128),
    (VERTICAL["snippet"]["title"], "vertical", 25),
    ("[HD - Mobile] Kinh Vô Lượng Thọ Giảng Ký - Pháp Sư Tịnh Không", "vertical", 25),
    ("[HD Mobile] Kinh Địa Tạng Bồ Tát Bổn Nguyện - PS.Tịnh Không", "vertical", 25),
    ("[ HD  -  Mobile ] Bộ kinh", "vertical", 25),
])
def test_select_real_playlist_titles_nfc_case_and_range(title, kind, episode):
    catalog = [dict(id="target", snippet=dict(title=unicodedata.normalize("NFD", title.swapcase())))]
    before = deepcopy(catalog)
    assert playlists.select(catalog, kind, episode) == dict(
        playlist_id="target", playlist_title=catalog[0]["snippet"]["title"], playlist_warning="")
    assert catalog == before


@pytest.mark.parametrize("catalog,kind,episode,warning", [
    ([KT], "kt", 21, "thiếu danh sách phát"),
    ([KT], "short", 11, "thiếu danh sách phát"),
    ([dict(id="x", snippet=dict(title="Short - Thập Thiện Nghiệp Đạo Kinh"))], "short", 11, "thiếu danh sách phát"),
    ([dict(id="x", snippet=dict(title="A Di Đà Phật"))], "vertical", 11, "thiếu danh sách phát"),
    ([dict(id="x", snippet=dict(title="[Tập 20-01] Short"))], "short", 11, "thiếu danh sách phát"),
    ([KT, dict(KT, id="other")], "kt", 11, "nhiều danh sách phát khớp"),
    ([VERTICAL, dict(VERTICAL, id="other")], "vertical", 25, "nhiều danh sách phát khớp"),
])
def test_select_missing_and_ambiguous_never_guesses(catalog, kind, episode, warning):
    assert playlists.select(catalog, kind, episode) == dict(
        playlist_id="", playlist_title="", playlist_warning=warning)


@pytest.mark.parametrize("resource,damage", [(r, d) for r in ("playlists", "playlistItems")
                                          for d in (None, "items", "id", "page")])
def test_playlist_api_pagination_membership_fields_and_validation(oauth, resource, damage):
    item = KT if resource == "playlists" else dict(contentDetails=dict(videoId="v1"))
    item2 = SHORT if resource == "playlists" else dict(snippet=dict(resourceId=dict(videoId="v2")))
    if damage == "items":
        replies = [dict(items=None)]
    elif damage == "id":
        replies = [dict(items=[dict(id=None)])]
    elif damage == "page":
        replies = [dict(items=[item], nextPageToken="again"), dict(items=[], nextPageToken="again")]
    else:
        replies = [dict(items=[item], nextPageToken="p2"), dict(items=[item, item2])]
    wire = Wire(*replies)
    client = youtube.YouTube(*oauth, transport=wire)
    read = client.owned_playlists if resource == "playlists" else lambda: client.playlist_ids("target")
    if damage:
        with pytest.raises(PublishError, match="không hợp lệ"):
            read()
    else:
        assert read() == ([KT, SHORT] if resource == "playlists" else ["v1", "v2"])
        assert parse_qs(urlparse(wire.calls[1][1]).query)["pageToken"] == ["p2"]
    first = parse_qs(urlparse(wire.calls[0][1]).query)
    assert first["maxResults"] == ["50"]
    assert first.get("mine") == (["true"] if resource == "playlists" else None)
    assert first["part"] == (["snippet"] if resource == "playlists" else ["contentDetails"])
    assert all(call[0] == "GET" for call in wire.calls) and not wire.responses


@pytest.mark.parametrize("do_apply", [False, True])
def test_schedule_dry_run_and_apply_add_only_absent_members_after_journal(local, capsys, do_apply):
    cfg, args = local
    sources = [video("v1", "T11_KT01_a.mp4"), video("v2", "T11_KT02_b.mp4")]
    replies = [*channel_listing(*sources), dict(items=[]), dict(items=[KT])]
    if do_apply:
        replies += [dict(id="v1"), members("v1"), dict(id="v2"), dict(id="inserted")]
    wire = Wire(*replies)
    path = cfg.workspace.dir / "_publish" / "schedule.json"

    def send(method, url, headers, body):
        parsed = urlparse(url)
        if parsed.path.endswith("/playlistItems") and (
                method == "POST" or parse_qs(parsed.query).get("playlistId") == [KT["id"]]):
            recorded = [r["youtube_id"] for r in read_json_dict(path)["records"]]
            assert recorded == (["v1", "v2"] if method == "POST" else ["v1"])
        return wire(method, url, headers, body)

    assert main(args + (["--apply"] if do_apply else []), transport=send, now=NOW.timestamp) == 0
    output = capsys.readouterr().out
    result = json.loads(output[output.index('{\n  "mode"'):])
    assert "Danh sách phát" in output and KT["snippet"]["title"] in output
    assert [r["publish_at"] for r in result["rows"]] == [r["publish_at"] for r in schedule.plan(sources, NOW)]
    if do_apply:
        assert [call[0] for call in wire.calls[-4:]] == ["PUT", "GET", "PUT", "POST"]
        post = wire.calls[-1]
        assert parse_qs(urlparse(post[1]).query) == dict(part=["snippet"])
        assert post[2]["Content-Type"] == "application/json"
        assert json.loads(post[3]) == dict(snippet=dict(playlistId=KT["id"],
                                                       resourceId=dict(kind="youtube#video", videoId="v2")))
        assert [r["playlist_added"] for r in result["rows"]] == [False, True]
        assert all(json.loads(call[3])["status"]["selfDeclaredMadeForKids"] is False
                   for call in wire.calls if call[0] == "PUT")
    else:
        assert all(call[0] == "GET" for call in wire.calls) and not path.exists()
    assert not wire.responses


@pytest.mark.parametrize("ambiguous", [False, True])
def test_schedule_missing_or_ambiguous_playlist_still_schedules_with_warning(local, capsys, ambiguous):
    cfg, args = local
    catalog = [KT, dict(KT, id="other")] if ambiguous else []
    warning = "nhiều danh sách phát khớp" if ambiguous else "thiếu danh sách phát"
    wire = Wire(*channel_listing(video("v1", "T11_KT01_a")), dict(items=[]), dict(items=catalog), dict(id="v1"))
    assert main(args + ["--apply"], transport=wire, now=NOW.timestamp) == 0
    output = capsys.readouterr().out
    result = json.loads(output[output.index('{\n  "mode"'):])
    assert result["rows"][0]["reason"] == warning
    assert result["rows"][0]["status"] == "đã đặt lịch" and not result["rows"][0]["playlist_added"]
    assert [r["youtube_id"] for r in read_json_dict(cfg.workspace.dir / "_publish" / "schedule.json")["records"]] == ["v1"]
    assert not [call for call in wire.calls if call[0] == "POST"] and not wire.responses


def test_schedule_playlist_error_stops_with_journal_then_check_repairs(local, capsys):
    cfg, args = local
    sources = [video("v1", "T11_KT01_a"), video("v2", "T11_KT02_b")]
    error = (403, dict(error=dict(errors=[dict(reason="quotaExceeded")])))
    wire = Wire(*channel_listing(*sources), dict(items=[]), dict(items=[KT]), dict(id="v1"), members(), error)
    assert main(args + ["--apply"], transport=wire, now=NOW.timestamp) == 1
    assert "quotaExceeded" in capsys.readouterr().err
    puts = [json.loads(c[3])["id"] for c in wire.calls if c[0] == "PUT"]
    path = cfg.workspace.dir / "_publish" / "schedule.json"
    journal = read_json_dict(path)
    assert puts == ["v1"] and [r["youtube_id"] for r in journal["records"]] == ["v1"] and not wire.responses
    sources[0]["status"]["publishAt"] = journal["records"][0]["publish_at"]
    source_playlist(cfg)
    wire = Wire(*channel_listing(*sources), dict(items=[]), dict(items=[KT]), members(), dict(id="repaired"))
    assert main(["check", *args[1:], "--playlist", SOURCE, "--add-playlists"], transport=wire, now=NOW.timestamp) == 0
    assert [json.loads(c[3])["snippet"]["resourceId"]["videoId"] for c in wire.calls if c[0] == "POST"] == ["v1"]
    assert read_json_dict(path) == journal and not wire.responses


@pytest.mark.parametrize("do_add", [False, True])
def test_check_read_only_or_adds_missing_sorted_and_idempotently(local, capsys, do_add):
    cfg, args = local
    source_playlist(cfg)
    sources = [video("kt2", "T11_KT02_b", privacy="public"), video("kt1", "T11_KT01_a", privacy="unlisted"),
               video("short", "T7_S01_a", privacy="unlisted"),
               video("vertical", "Thái Thượng Cảm Ứng Thiên_Tập3_Doc.mp4", publish_at="2026-11-25T00:00:00Z"),
               video("draft", "T1_KT01_a"), video("unknown", None, title="Bình an", privacy="public"),
               video("present", "T11_KT03_c", privacy="public")]
    command = ["check", *args[1:], "--playlist", SOURCE, *(["--add-playlists"] if do_add else [])]
    wire = Wire(*channel_listing(*sources), dict(items=[]), dict(items=[KT, SHORT, VERTICAL]),
                members("present"), members(), members(), *([dict(id="inserted")] * 4 if do_add else []))
    assert main(command, transport=wire, now=NOW.timestamp) == 0
    output = capsys.readouterr().out
    result = json.loads(output[output.index('{\n  "rows"'):])
    missing = [r for r in result["rows"] if r["group"] == "playlist_missing"]
    assert [r["youtube_id"] for r in missing] == ["vertical", "short", "kt1", "kt2"]
    assert "Chưa vào danh sách phát: 4" in output
    assert [json.loads(c[3])["snippet"]["resourceId"]["videoId"] for c in wire.calls if c[0] == "POST"] == (
        ["vertical", "short", "kt1", "kt2"] if do_add else [])
    assert not [c for c in wire.calls if c[0] == "PUT"] and not wire.responses
    if do_add:
        wire = Wire(*channel_listing(*sources), dict(items=[]), dict(items=[KT, SHORT, VERTICAL]),
                    members("present", "kt1", "kt2"), members("short"), members("vertical"))
        assert main(command, transport=wire, now=NOW.timestamp) == 0
        assert all(c[0] == "GET" for c in wire.calls) and not wire.responses
        assert "Chưa vào danh sách phát: 0" in capsys.readouterr().out


@pytest.mark.parametrize("case", ["missing", "ambiguous", "quota"])
def test_check_add_warns_without_guessing_and_stops_on_quota(local, capsys, case):
    cfg, args = local
    source_playlist(cfg)
    sources = [video("v2", "T11_KT02_b", privacy="public"), video("v1", "T11_KT01_a", privacy="public")]
    catalog = [] if case == "missing" else [KT, dict(KT, id="other")] if case == "ambiguous" else [KT]
    error = (403, dict(error=dict(errors=[dict(reason="quotaExceeded")])))
    wire = Wire(*channel_listing(*sources), dict(items=[]), dict(items=catalog),
                *([members(), dict(id="inserted"), error] if case == "quota" else []))
    assert main(["check", *args[1:], "--playlist", SOURCE, "--add-playlists"],
                transport=wire, now=NOW.timestamp) == (1 if case == "quota" else 0)
    output = capsys.readouterr()
    if case == "quota":
        assert "quotaExceeded" in output.err
        assert [json.loads(c[3])["snippet"]["resourceId"]["videoId"] for c in wire.calls if c[0] == "POST"] == ["v1", "v2"]
    else:
        assert ("thiếu danh sách phát" if case == "missing" else "nhiều danh sách phát khớp") in output.out
        assert all(c[0] == "GET" for c in wire.calls)
    assert not (cfg.workspace.dir / "_publish" / "schedule.json").exists() and not wire.responses


@pytest.mark.parametrize("explicit", [False, True])
def test_auth_saves_absolute_client_path_and_refresh_keeps_binding(oauth, monkeypatch, explicit):
    client_path, token_path = oauth
    monkeypatch.chdir(client_path.parent)
    monkeypatch.setattr(youtube, "default_client", lambda: client_path)
    clock = Clock()
    wire = Wire(DEVICE, TOKEN)
    youtube.auth(Path(client_path.name) if explicit else None, token_path, transport=wire,
                 sleep=clock.sleep, now=clock.now, output=lambda line: None)
    assert read_json_dict(token_path)["client_path"] == str(client_path.resolve()) and not wire.responses
    wire = Wire(dict(access_token="renewed", expires_in=120), dict(items=[dict(id="channel")]))
    api = youtube.YouTube(token_path=token_path, transport=wire, now=lambda: clock.time + 4000, read_only=True)
    assert api.client_path == client_path and api.channel_id() == "channel"
    assert read_json_dict(token_path)["client_path"] == str(client_path.resolve()) and not wire.responses


@pytest.mark.parametrize("mode", ["stored", "explicit", "legacy"])
def test_client_precedence_refresh_and_web_read_only_guard(oauth, tmp_path, monkeypatch, mode):
    explicit, token_path = oauth
    stored, default = tmp_path / "channel-client.json", tmp_path / "default-client.json"
    for path, ident in ((stored, "per-channel"), (default, "legacy-default")):
        atomic_write_json(path, dict(client_id=ident, client_secret="fake-secret"))
    doc = dict(read_json_dict(token_path), expires_at=0)
    if mode != "legacy":
        doc["client_path"] = str(stored)
    atomic_write_json(token_path, doc)
    monkeypatch.setattr(youtube, "default_client", lambda: default)
    wire = Wire(dict(access_token="new-token", expires_in=3600), dict(items=[dict(id="channel")]))
    api = youtube.YouTube(explicit if mode == "explicit" else None, token_path, transport=wire,
                          now=lambda: 1000, read_only=True)
    with pytest.raises(PublishError, match="GET"):
        api.add_to_playlist("target", "video")
    assert not wire.calls
    assert api.channel_id() == "channel"
    expected = {"stored": "per-channel", "explicit": "client-id", "legacy": "legacy-default"}[mode]
    assert parse_qs(wire.calls[0][3].decode())["client_id"] == [expected]
    assert read_json_dict(token_path).get("client_path") == (str(stored) if mode != "legacy" else None)
    assert not wire.responses
