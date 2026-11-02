"""PUB2 AC1–AC6: injected HTTP and clocks, with real packaging validation."""
import json
import socket
import stat
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from auto_short.config import Config, PackagingConfig, RenderConfig, WorkspaceConfig
from auto_short.hashing import sha256_file
from auto_short.packaging import episode, thumbnail
from auto_short.publish import PublishError, thumbs, youtube
from auto_short.publish.__main__ import main
from auto_short.workspace import atomic_write_json, read_json_dict

PID = "PLepisodes1"
IDS = ("lecture0001", "lecture0002")
SERIES = "Kinh Địa Tạng Bồ Tát Bổn Nguyện"
SECRETS = ("ACCESS-private", "REFRESH-private", "CLIENT-private", "DEVICE-private")
DEVICE = dict(device_code=SECRETS[3], user_code="ABCD-EFGH", verification_url="https://google.com/device",
              interval=2, expires_in=60)
TOKEN = dict(access_token=SECRETS[0], refresh_token=SECRETS[1], expires_in=3600)


class Clock:
    def __init__(self):
        self.time = 1000
        self.sleeps = []

    def now(self):
        return self.time

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.time += delay


class Wire:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        assert self.responses, f"unexpected request: {method} {urlparse(url).path}"
        response = self.responses.pop(0)
        status, doc = response if isinstance(response, tuple) else (200, response)
        return status, {}, json.dumps(doc).encode()


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("PUB2 tests must use the injected transport")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def oauth(tmp_path):
    client, token = tmp_path / "client.json", tmp_path / "private" / "token.json"
    atomic_write_json(client, dict(installed=dict(client_id="client-id", client_secret=SECRETS[2])))
    atomic_write_json(token, dict(access_token=SECRETS[0], refresh_token=SECRETS[1], expires_at=9999999999,
                                 scope=youtube.SCOPES))
    return client, token


@pytest.fixture
def episodes(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(tmp_path / "work"), packaging=PackagingConfig(tmp_path / "assets"),
                 render=RenderConfig(output_dir=tmp_path / "output"))
    entries = []
    for number, ident in enumerate(IDS, 101):
        root = cfg.workspace.dir / ident
        root.mkdir(parents=True)
        (root / "source.mp4").write_bytes(b"source")
        atomic_write_json(root / "manifest.json", dict(source=dict(kind="youtube", path="source.mp4", sha256="a" * 64)))
        atomic_write_json(root / "metadata.json", dict(title="Bài giảng", height=1080))
        fields = dict(series=SERIES, episode=str(number), speaker="HT. Tịnh Không")
        atomic_write_json(root / "titles.json", dict(header=dict(fields=fields)))
        entries.append(dict(video_id=ident, episode=str(number), index=number))
    atomic_write_json(cfg.workspace.dir / "_playlists" / f"{PID}.json",
                      dict(playlist_id=PID, series=SERIES, entries=entries))
    vertical = cfg.render.output_dir / IDS[0] / "full"
    vertical.mkdir(parents=True)
    (vertical / "vertical.mp4").write_bytes(b"vertical")
    atomic_write_json(vertical / "vertical.json", dict(size=8))
    settings = episode.read_settings(cfg, PID)
    for ident in IDS:
        fields = episode.header(cfg, ident)
        folder = episode.directory(cfg, ident)
        folder.mkdir(parents=True)
        files = {}
        for shape in thumbnail.EPISODE_SIZES:
            key = episode.cache_key(fields, settings, shape)
            image = folder / f"{shape}-{key}.jpg"
            image.write_bytes(b"\xff\xd8jpeg:" + shape.encode())
            files[shape] = dict(file=image.name, key=key, sha256=sha256_file(image))
        atomic_write_json(folder / "thumbs.json", dict(schema_version=1, video_id=ident, playlist_id=PID,
                          header=fields, asset_id=None, files=files, skipped_reason=None))
    return cfg


def video(ident="uploaded001", *, number=101, shape="HD", series=SERIES):
    return dict(id=ident, fileDetails=dict(fileName=f"[{shape}] {series} - Tập {number}.mp4"),
                snippet=dict(title="Không dùng tiêu đề để ghép"))


def listing(*videos):
    return [dict(items=[dict(contentDetails=dict(relatedPlaylists=dict(uploads="UPLOADS")))]),
            dict(items=[dict(contentDetails=dict(videoId=v["id"])) for v in videos]), dict(items=list(videos))]


def cli_args(cfg, oauth, *extra):
    path = cfg.workspace.dir.parent / "config.toml"
    path.write_text(f'[workspace]\ndir = "{cfg.workspace.dir}"\n[render]\noutput_dir = "{cfg.render.output_dir}"\n')
    return ["--config", str(path), "--client", str(oauth[0]), "--token", str(oauth[1]),
            "thumbs", "--playlist", PID, *extra]


@pytest.mark.parametrize("fallback", ["device", "poll"])
@pytest.mark.parametrize("wrapped", [True, False])
def test_auth_device_flow_scope_fallback_and_private_token(tmp_path, capsys, caplog, monkeypatch, fallback, wrapped):
    client, token = tmp_path / "client.json", tmp_path / "new" / "nested" / "token.json"
    credentials = dict(client_id="client-id", client_secret=SECRETS[2])
    atomic_write_json(client, dict(installed=credentials) if wrapped else credentials)
    invalid = (400, dict(error="invalid_scope", error_description=" ".join(SECRETS)))
    responses = [invalid] if fallback == "device" else [DEVICE, invalid]
    wire = Wire(*responses, DEVICE, (400, dict(error="authorization_pending")),
                (400, dict(error="slow_down")), (400, dict(error="authorization_pending")), TOKEN)
    clock = Clock()
    replace = youtube.os.replace
    replacements = []

    def checked_replace(src, dest):
        if Path(dest) == token:
            replacements.append(dest)
            assert stat.S_IMODE(Path(src).stat().st_mode) == 0o600
            assert stat.S_IMODE(Path(src).parent.stat().st_mode) == 0o700
        return replace(src, dest)

    monkeypatch.setattr(youtube.os, "replace", checked_replace)
    assert main(["auth", "--client", str(client), "--token", str(token)], transport=wire,
                sleep=clock.sleep, now=clock.now) == 0
    assert replacements == [token] and stat.S_IMODE(token.stat().st_mode) == 0o600
    assert read_json_dict(token)["scope"] == youtube.FULL_SCOPE
    assert clock.sleeps == ([2, 2, 7, 7] if fallback == "device" else [2, 2, 2, 7, 7])
    device_calls = [c for c in wire.calls if c[1] == youtube.DEVICE_URL]
    assert [parse_qs(c[3].decode())["scope"][0] for c in device_calls] == [youtube.SCOPES, youtube.FULL_SCOPE]
    poll = next(c for c in wire.calls if c[1] == youtube.TOKEN_URL)
    assert parse_qs(poll[3].decode())["grant_type"] == ["urn:ietf:params:oauth:grant-type:device_code"]
    captured = capsys.readouterr()
    assert "https://google.com/device" in captured.out and "ABCD-EFGH" in captured.out
    assert youtube.FULL_SCOPE in captured.out and not captured.err
    assert not any(s in captured.out + captured.err + caplog.text for s in SECRETS)
    assert not wire.responses


@pytest.mark.parametrize("failure", ["pending", "slow_down", "access_denied", "expired_token"])
def test_auth_expiry_and_denial(oauth, capsys, failure):
    clock = Clock()
    device = dict(DEVICE, expires_in=5)
    errors = ([dict(error="authorization_pending")] * 2 if failure == "pending"
              else [dict(error=failure, error_description=" ".join(SECRETS))])
    wire = Wire(device, *((400, error) for error in errors))
    before = oauth[1].read_bytes()
    assert main(["auth", "--client", str(oauth[0]), "--token", str(oauth[1])], transport=wire,
                sleep=clock.sleep, now=clock.now) == 1
    captured = capsys.readouterr()
    assert "chạy lại auth" in captured.err and oauth[1].read_bytes() == before
    assert not any(s in captured.out + captured.err for s in SECRETS)
    if failure in ("pending", "slow_down"):
        assert clock.time == 1005


@pytest.mark.parametrize("expired", [True, False])
def test_refresh_expired_token_or_retry_401(oauth, expired):
    client, token = oauth
    if expired:
        doc = read_json_dict(token)
        atomic_write_json(token, dict(doc, expires_at=1))
    wire = Wire(*([] if expired else [(401, dict(error={}))]),
                dict(access_token="NEW-private", expires_in=120), dict(items=[]))
    api = youtube.YouTube(client, token, transport=wire, now=lambda: 1000)
    assert api._list("channels", part="contentDetails", mine="true") == {"items": []}
    refreshed = read_json_dict(token)
    assert refreshed["refresh_token"] == SECRETS[1] and refreshed["expires_at"] == 1120
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    refresh_call = next(c for c in wire.calls if c[1] == youtube.TOKEN_URL)
    assert parse_qs(refresh_call[3].decode())["grant_type"] == ["refresh_token"]
    assert wire.calls[-1][2]["Authorization"] == "Bearer NEW-private" and not wire.responses


@pytest.mark.parametrize("failure", ["invalid_grant", "401"])
def test_refresh_failures_exit_without_secrets(episodes, oauth, capsys, caplog, failure):
    error = dict(error="invalid_grant", error_description=" ".join(SECRETS))
    wire = Wire((401, dict(error={})), (400, error)) if failure == "invalid_grant" else Wire(
        (401, dict(error={})), TOKEN, (401, dict(error=dict(message=" ".join(SECRETS)))))
    assert main(cli_args(episodes, oauth), transport=wire) == 1
    captured = capsys.readouterr()
    assert "chạy lại auth" in captured.err
    assert not any(s in captured.out + captured.err + caplog.text for s in SECRETS)
    assert not (episodes.workspace.dir / "_publish").exists() and not wire.responses


def test_upload_pagination_and_video_batches(oauth):
    ids = [f"uploaded{i:03}" for i in range(103)]
    pages = []
    for offset in range(0, len(ids), 50):
        doc = dict(items=[dict(contentDetails=dict(videoId=i)) for i in ids[offset:offset + 50]])
        if offset < 100:
            doc["nextPageToken"] = f"page-{offset + 50}"
        pages.append(doc)
    batches = [dict(items=[dict(id=i) for i in ids[offset:offset + 50]]) for offset in range(0, len(ids), 50)]
    wire = Wire(listing()[0], *pages, *batches)
    result = youtube.YouTube(*oauth, transport=wire).videos()
    assert [v["id"] for v in result] == ids
    queries = [parse_qs(urlparse(c[1]).query) for c in wire.calls]
    assert queries[0] == dict(part=["contentDetails"], mine=["true"])
    assert [q.get("pageToken") for q in queries[1:4]] == [None, ["page-50"], ["page-100"]]
    assert all(q["maxResults"] == ["50"] for q in queries[1:4])
    assert [len(q["id"][0].split(",")) for q in queries[4:]] == [50, 50, 3]
    assert all(q["part"] == ["fileDetails,snippet"] for q in queries[4:]) and not wire.responses


def test_match_shapes_normalization_skips_and_duplicates(episodes):
    landscape = video()
    landscape["fileDetails"]["fileName"] = unicodedata.normalize("NFD", f"[HD] {SERIES.upper()} - Tập 0101.Mp4")
    videos = [landscape, video("vertical001", shape="HD Dọc"), video("duplicate01"),
              video("other000001", series="Bộ kinh khác"), dict(id="wrong000001", snippet=dict(title=SERIES)),
              video("missing0001", number=999), video("missingvert", number=102, shape="HD Dọc")]
    rows = thumbs.plan(episodes, videos, pid=PID)
    assert [r["shape"] for r in rows[:3]] == ["landscape", "vertical", "landscape"]
    assert all(r["status"] == "sẵn sàng" and r["video_id"] == IDS[0] for r in rows[:3])
    assert all(rows[i]["warning"] for i in (0, 2)) and not rows[1]["warning"]
    assert all(r["status"] == "bỏ qua" and r["reason"] for r in rows[3:6])
    assert "bộ kinh khác" in rows[3]["reason"] and "tên file" in rows[4]["reason"]
    # G8: a vertical thumbnail exists even when the episode has no vertical video.
    assert rows[6]["status"] == "sẵn sàng" and rows[6]["video_id"] == IDS[1]
    assert rows[6]["shape"] == "vertical" and not rows[6]["reason"]
    assert not (episodes.workspace.dir / "_publish").exists()


def test_hd_mobile_store_name_is_vertical(episodes):
    # HD1 G6: "[HD Mobile] …" (3090 store name) = vertical like the older "[HD Dọc] …"; the tag is case-sensitive.
    rows = thumbs.plan(episodes, [video("mobile00001", shape="HD Mobile"), video("mobilecase1", number=102,
                                                                                  shape="hd mobile")], pid=PID)
    assert rows[0]["status"] == "sẵn sàng" and rows[0]["shape"] == "vertical" and rows[0]["video_id"] == IDS[0]
    assert not rows[0]["warning"] and not rows[0]["reason"]
    assert rows[1]["status"] == "bỏ qua" and "[HD Mobile]" in rows[1]["reason"]


def test_series_override_and_header_number_authority(episodes):
    path = episodes.workspace.dir / IDS[0] / "titles.json"
    doc = read_json_dict(path)
    doc["header"]["fields"]["episode"] = "222"
    atomic_write_json(path, doc)
    row = thumbs.plan(episodes, [video(series="  Bộ   Kinh Mới ", number=222)], pid=PID, series="bộ kinh mới")[0]
    assert row["video_id"] == IDS[0] and row["episode"] == 222
    assert row["status"] == "bỏ qua"  # the old thumbnail header is now stale
    assert "ảnh" in row["reason"]


@pytest.mark.parametrize("stored", ["missing", "invalid", "normalized"])
@pytest.mark.parametrize("override", [None, "Bộ kinh khác"])
def test_series_fallback_and_override_match_episode_one(episodes, oauth, capsys, stored, override):
    playlist_path = episodes.workspace.dir / "_playlists" / f"{PID}.json"
    playlist = read_json_dict(playlist_path)
    playlist.pop("series")
    if stored == "invalid":
        playlist["series"] = "x" * 101
    elif stored == "normalized":
        playlist["series"] = unicodedata.normalize("NFD", "  Bộ   kinh riêng  ")
    playlist["entries"] = [None, {}, dict(video_id="missing0001"), *playlist["entries"]]
    atomic_write_json(playlist_path, playlist)
    title_path = episodes.workspace.dir / IDS[0] / "titles.json"
    title = read_json_dict(title_path)
    title["header"]["fields"]["episode"] = "1"
    atomic_write_json(title_path, title)
    folder = episode.directory(episodes, IDS[0])
    record = read_json_dict(folder / "thumbs.json")
    record["header"] = episode.header(episodes, IDS[0])
    settings = episode.read_settings(episodes, PID)
    for shape, entry in record["files"].items():
        key = episode.cache_key(record["header"], settings, shape)
        name = f"{shape}-{key}.jpg"
        (folder / entry["file"]).rename(folder / name)
        entry.update(key=key, file=name)
    atomic_write_json(folder / "thumbs.json", record)
    expected = override or ("Bộ kinh riêng" if stored == "normalized" else SERIES)
    source = video(number=1, series=expected)
    row = thumbs.plan(episodes, [source], pid=PID, series=override)[0]
    assert row["status"] == "sẵn sàng" and row["video_id"] == IDS[0] and row["episode"] == 1
    wire = Wire(*listing(source))
    args = cli_args(episodes, oauth, *(["--series", override] if override else []))
    assert main(args, transport=wire) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines()[0] == f"Bộ kinh: {expected}"
    assert captured.out.splitlines()[1].startswith("Video YouTube\t")
    assert not captured.err and not wire.responses
    assert not (episodes.workspace.dir / "_publish").exists()


def test_series_missing_without_resolvable_header_still_errors(episodes):
    path = episodes.workspace.dir / "_playlists" / f"{PID}.json"
    playlist = read_json_dict(path)
    playlist.pop("series")
    playlist["entries"] = [None, {}, dict(video_id="missing0001")]
    atomic_write_json(path, playlist)
    with pytest.raises(PublishError, match="thiếu tên bộ kinh"):
        thumbs.plan(episodes, [video(number=1)], pid=PID)


@pytest.mark.parametrize("damage", ["hash", "oversize", "missing"])
def test_invalid_images_skipped_without_upload(episodes, oauth, damage):
    row = thumbs.plan(episodes, [video()], pid=PID)[0]
    image = Path(row["file"])
    if damage == "missing":
        image.unlink()
    else:
        image.write_bytes(b"changed" if damage == "hash" else b"x" * (thumbs.MAX_BYTES + 1))
    wire = Wire()
    api = youtube.YouTube(*oauth, transport=wire)
    planned = thumbs.plan(episodes, [video()], pid=PID)[0]
    assert planned["status"] == "bỏ qua" and planned["reason"]
    result = thumbs.apply(episodes, [row], api)
    assert result[0]["status"] == "bỏ qua" and not wire.calls
    if damage == "oversize":
        assert "2 MB" in planned["reason"]
    assert not (episodes.workspace.dir / "_publish").exists()


def test_cli_dry_run_apply_skip_and_force(episodes, oauth, capsys):
    source = [video(), video("vertical001", shape="HD Dọc"), video("duplicate01")]
    wire = Wire(*listing(*source))
    args = cli_args(episodes, oauth)
    before = {p: p.read_bytes() for p in episodes.workspace.dir.rglob("*.json")}
    assert main(args, transport=wire) == 0
    assert all(c[0] == "GET" for c in wire.calls) and not wire.responses
    assert "chạy thử" in capsys.readouterr().out
    assert {p: p.read_bytes() for p in episodes.workspace.dir.rglob("*.json")} == before
    rows = thumbs.plan(episodes, source, pid=PID)
    for extra, count in [(["--apply"], 3), (["--apply"], 0), (["--apply", "--force"], 3)]:
        wire = Wire(*listing(*source), *([dict(items=[])] * count))
        assert main([*args, *extra], transport=wire) == 0
        uploads = [c for c in wire.calls if c[0] == "POST"]
        assert len(uploads) == count and not wire.responses
        for call, row in zip(uploads, rows):
            assert call[1] == youtube.UPLOAD_URL + f"?videoId={row['youtube_id']}&uploadType=media"
            assert call[2] == {"Authorization": "Bearer " + SECRETS[0], "Content-Type": "image/jpeg"}
            assert call[3] == Path(row["file"]).read_bytes()
    # Replacing a valid JPEG must trigger an update even without --force.
    image = Path(rows[0]["file"])
    image.write_bytes(b"\xff\xd8updated JPEG")
    record_path = image.parent / "thumbs.json"
    record = read_json_dict(record_path)
    record["files"]["landscape"]["sha256"] = sha256_file(image)
    atomic_write_json(record_path, record)
    wire = Wire(*listing(*source), dict(items=[]), dict(items=[]))
    assert main([*args, "--apply"], transport=wire) == 0
    assert len([c for c in wire.calls if c[0] == "POST"]) == 2 and not wire.responses
    journal = read_json_dict(episodes.workspace.dir / "_publish" / "thumbs.json")
    assert len(journal["records"]) == 3
    assert all(set(r) == {"youtube_id", "video_id", "playlist_id", "shape", "sha256", "set_at"}
               for r in journal["records"])


@pytest.mark.parametrize("reason,status", [("quotaExceeded", 403), ("forbidden", 403), ("unauthorized", 401)])
def test_api_failure_stops_and_keeps_success_journal(episodes, oauth, capsys, caplog, reason, status):
    source = [video("uploaded001"), video("uploaded002", number=102), video("uploaded003")]
    error = (status, dict(error=dict(message=" ".join(SECRETS), errors=[dict(reason=reason)])))
    wire = Wire(*listing(*source), dict(items=[]), error, *([TOKEN, error] if status == 401 else []))
    assert main(cli_args(episodes, oauth, "--apply"), transport=wire) == 1
    journal_path = episodes.workspace.dir / "_publish" / "thumbs.json"
    records = read_json_dict(journal_path)["records"]
    assert [r["youtube_id"] for r in records] == ["uploaded001"]
    uploads = [c for c in wire.calls if c[1].startswith(youtube.UPLOAD_URL)]
    assert len(uploads) == (3 if status == 401 else 2) and not wire.responses
    assert all("uploaded003" not in c[1] for c in uploads)
    captured = capsys.readouterr()
    assert (reason if status == 403 else "chạy lại auth") in captured.err
    assert not any(s in captured.out + captured.err + journal_path.read_text() + caplog.text for s in SECRETS)


def test_corrupt_journal_is_not_overwritten(episodes, oauth):
    path = episodes.workspace.dir / "_publish" / "thumbs.json"
    path.parent.mkdir()
    path.write_text("broken")
    wire = Wire()
    with pytest.raises(PublishError, match="nhật ký"):
        thumbs.apply(episodes, thumbs.plan(episodes, [video()], pid=PID), youtube.YouTube(*oauth, transport=wire))
    assert path.read_text() == "broken" and not wire.calls


@pytest.fixture
def playlist_episodes(episodes):
    """Use the operational series and episode numbers with real thumbnail checks."""
    series = "Thái Thượng Cảm Ứng Thiên"
    playlist_path = episodes.workspace.dir / "_playlists" / f"{PID}.json"
    playlist = read_json_dict(playlist_path)
    playlist["series"] = series
    atomic_write_json(playlist_path, playlist)
    for entry, number in zip(playlist["entries"], (12, 3)):
        ident = entry["video_id"]
        entry["episode"] = str(number)
        path = episodes.workspace.dir / ident / "titles.json"
        title = read_json_dict(path)
        title["header"]["fields"].update(series=series, episode=str(number))
        atomic_write_json(path, title)
        folder = episode.directory(episodes, ident)
        doc = read_json_dict(folder / "thumbs.json")
        doc["header"] = episode.header(episodes, ident)
        for shape, image in doc["files"].items():
            key = episode.cache_key(doc["header"], episode.read_settings(episodes, PID), shape)
            filename = f"{shape}-{key}.jpg"
            (folder / image["file"]).rename(folder / filename)
            image.update(key=key, file=filename)
        atomic_write_json(folder / "thumbs.json", doc)
    atomic_write_json(playlist_path, playlist)
    return episodes


def test_playlist_pagination_batches_and_deduplication(oauth):
    ids = [f"uploaded{i:03}" for i in range(103)]
    pages = [dict(items=[dict(contentDetails=dict(videoId=i)) for i in batch], **tokens)
             for batch, tokens in [(ids[:50], dict(nextPageToken="page-2")),
                                   (ids[49:100], dict(nextPageToken="page-3")), (ids[100:], {})]]
    batches = [dict(items=[dict(id=i) for i in ids[offset:offset + 50]]) for offset in (0, 50, 100)]
    wire = Wire(*pages, *batches)
    assert [v["id"] for v in youtube.YouTube(*oauth, transport=wire).playlist_videos("SELECTED")] == ids
    queries = [parse_qs(urlparse(c[1]).query) for c in wire.calls]
    assert all(urlparse(c[1]).path.endswith("/playlistItems") for c in wire.calls[:3])
    assert all(q["playlistId"] == ["SELECTED"] and q["maxResults"] == ["50"] for q in queries[:3])
    assert [q.get("pageToken") for q in queries[:3]] == [None, ["page-2"], ["page-3"]]
    assert [q["id"][0].split(",") for q in queries[3:]] == [ids[:50], ids[50:100], ids[100:]]
    assert all(q["part"] == ["fileDetails,snippet"] for q in queries[3:]) and not wire.responses


@pytest.mark.parametrize("uploads", [False, True])
@pytest.mark.parametrize("failure", ["repeat", "invalid_page", "invalid_items"])
def test_playlist_invalid_pagination(oauth, uploads, failure):
    pages = ([dict(items=[], nextPageToken="again")] * 2 if failure == "repeat" else
             [dict(items=[], nextPageToken=123)] if failure == "invalid_page" else [dict(items=[{}])])
    wire = Wire(*([listing()[0]] if uploads else []), *pages)
    api = youtube.YouTube(*oauth, transport=wire)
    with pytest.raises(PublishError, match=("phân trang" if failure != "invalid_items" else "danh sách") +
                             (" uploads" if uploads else " playlist")):
        api.videos() if uploads else api.playlist_videos("SELECTED")
    assert not wire.responses


@pytest.mark.parametrize("name,title,number,shape,source", [
    ("Thái Thượng Cảm Ứng Thiên_Tập12_Doc.mp4", "", 12, "vertical", "tên file"),
    ("[hD] thái thượng cảm ứng thiên_TẬP12_DOC.MP4", "", 12, "vertical", "tên file"),
    ("[HD Mobile] Thái Thượng Cảm Ứng Thiên - Tập 12.mp4", "", 12, "vertical", "tên file"),
    ("", "[HD mobile] Thái Thượng Cảm Ứng Thiên - PS. Tịnh Không - Tập 12", 12, "vertical", "tiêu đề"),
    ("", "[hd dỌc] Thái Thượng Cảm Ứng Thiên - Tập 12", 12, "vertical", "tiêu đề"),
    ("", "[HD] THÁI  THƯỢNG CẢM ỨNG THIÊN - Tập 3", 3, "landscape", "tiêu đề"),
])
def test_playlist_filename_and_title_matches(playlist_episodes, name, title, number, shape, source):
    source_video = dict(id="selected001", fileDetails=dict(fileName=unicodedata.normalize("NFD", name)),
                        snippet=dict(title=unicodedata.normalize("NFD", title)))
    row = thumbs.plan(playlist_episodes, [source_video], pid=PID, journal=dict(records=[]))[0]
    assert (row["episode"], row["shape"], row["matched_by"], row["status"]) == (number, shape, source, "sẵn sàng")
    assert row["video_id"] == IDS[0 if number == 12 else 1] and not row["reason"]


@pytest.mark.parametrize("case", ["journal", "journal_agreement", "filename_priority", "other_playlist", "wrong_series",
                                  "no_match", "episode_conflict", "shape_conflict", "title_conflict",
                                  "file_title_conflict", "invalid_journal"])
def test_playlist_journal_priority_and_conflicts(playlist_episodes, case):
    source = dict(id="selected001", snippet=dict(title="Tiêu đề đã sửa"))
    record = dict(youtube_id=source["id"], video_id=IDS[0], playlist_id=PID, shape="vertical",
                  sha256="old", set_at="before")
    records = [record]
    if case in ("journal_agreement", "filename_priority"):
        source["fileDetails"] = dict(fileName="Thái Thượng Cảm Ứng Thiên_Tập12_Doc.mp4")
        source["snippet"]["title"] = "[HD Mobile] Thái Thượng Cảm Ứng Thiên - Tập 12"
        if case == "filename_priority":
            records = []
    elif case == "other_playlist":
        record["playlist_id"] = "OTHER"
        source["snippet"]["title"] = "[HD] Thái Thượng Cảm Ứng Thiên - Tập 3"
    elif case == "invalid_journal":
        record["video_id"] = "not-in-source"
    elif case == "wrong_series":
        records = []
        source["snippet"]["title"] = "[HD Mobile] Bộ khác - Tập 12"
    elif case == "no_match":
        records = []
    elif case in ("episode_conflict", "shape_conflict", "file_title_conflict"):
        source["fileDetails"] = dict(fileName="[HD] Thái Thượng Cảm Ứng Thiên - Tập 12.mp4" if
                                     case == "shape_conflict" else "Thái Thượng Cảm Ứng Thiên_Tập3_Doc.mp4")
        if case == "file_title_conflict":
            records = []
            source["snippet"]["title"] = "[HD Mobile] Thái Thượng Cảm Ứng Thiên - Tập 12"
    elif case == "title_conflict":
        source["snippet"]["title"] = "[HD Mobile] Thái Thượng Cảm Ứng Thiên - Tập 3"
    row = thumbs.plan(playlist_episodes, [source], pid=PID, journal=dict(records=records))[0]
    if case in ("journal", "journal_agreement", "filename_priority", "other_playlist"):
        assert row["status"] == "sẵn sàng" and not row["reason"]
        assert row["matched_by"] == ("tiêu đề" if case == "other_playlist" else
                                      "tên file" if case == "filename_priority" else "nhật ký")
        assert row["video_id"] == IDS[1 if case == "other_playlist" else 0]
    else:
        assert row["status"] == "bỏ qua" and not row["matched_by"]
        assert row["reason"] == ("tên bộ kinh khác" if case == "wrong_series" else
                                 "nhật ký, tên file gốc và tiêu đề không ghép được tập / khuôn" if case == "no_match" else
                                 "nhật ký không trỏ tới tập / khuôn hợp lệ trong playlist nguồn" if case == "invalid_journal" else
                                 "nhật ký và tên / tiêu đề lệch nhau")


def test_playlist_cli_journal_dry_run_apply_and_force(playlist_episodes, oauth, capsys):
    cfg = playlist_episodes
    selected = dict(id="selected001", fileDetails=dict(fileName="Thái Thượng Cảm Ứng Thiên_Tập12_Doc.mp4"))
    listing_responses = [dict(items=[dict(contentDetails=dict(videoId=selected["id"]))]), dict(items=[selected])]
    args = cli_args(cfg, oauth, "--yt-playlist", "SELECTED")
    journal_path = cfg.workspace.dir / "_publish" / "thumbs.json"
    for extra, posts in [((), 0), (("--apply",), 1), (("--apply",), 0), (("--apply", "--force"), 1)]:
        before = {p: p.read_bytes() for p in cfg.workspace.dir.rglob("*.json")}
        wire = Wire(*listing_responses, *([dict(items=[])] * posts))
        assert main([*args, *extra], transport=wire) == 0
        captured = capsys.readouterr()
        assert captured.out.splitlines()[1].endswith("\tghép theo") and not captured.err
        result = json.loads(captured.out[captured.out.index("{\n"):])
        assert [r["youtube_id"] for r in result["rows"]] == ["selected001"]
        assert result["rows"][0]["matched_by"] == ("nhật ký" if journal_path in before else "tên file")
        assert len([c for c in wire.calls if c[0] == "POST"]) == posts and not wire.responses
        if not extra:
            assert {p: p.read_bytes() for p in cfg.workspace.dir.rglob("*.json")} == before
    # An older journal hash still resolves identity; force sends the current image.
    journal = read_json_dict(journal_path)
    journal["records"][0]["sha256"] = "old"
    atomic_write_json(journal_path, journal)
    selected.pop("fileDetails")
    wire = Wire(*listing_responses, dict(items=[]))
    assert main([*args, "--apply", "--force"], transport=wire) == 0
    uploaded = [c for c in wire.calls if c[0] == "POST"]
    assert len(uploaded) == 1 and not wire.responses
    image = episode.directory(cfg, IDS[0]) / episode.read(cfg, IDS[0])["files"]["vertical"]["file"]
    assert uploaded[0][3] == image.read_bytes()
    assert read_json_dict(journal_path)["records"][0]["sha256"] == sha256_file(image)


def test_playlist_fallback_is_opt_in(playlist_episodes, oauth, capsys):
    source = dict(id="selected001", fileDetails=dict(fileName="Thái Thượng Cảm Ứng Thiên_Tập12_Doc.mp4"),
                  snippet=dict(title="[HD Mobile] Thái Thượng Cảm Ứng Thiên - Tập 12"))
    path = playlist_episodes.workspace.dir / "_publish" / "thumbs.json"
    path.parent.mkdir()
    path.write_text("broken journal must not be read by legacy dry run")
    wire = Wire(*listing(source))
    assert main(cli_args(playlist_episodes, oauth), transport=wire) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines()[1] == "Video YouTube\tTập / khuôn\tẢnh thumbnail\tTrạng thái / lý do"
    result = json.loads(captured.out[captured.out.index("{\n"):])
    assert result["rows"][0]["status"] == "bỏ qua" and "matched_by" not in result["rows"][0]
    assert not wire.responses
