"""PUB2K: real KT records/titles, injected valid_files and HTTP; no rendering or network."""
import json
from pathlib import Path
from types import SimpleNamespace
import unicodedata
from urllib.parse import parse_qs, urlparse

import pytest

from auto_short.config import Config, RenderConfig, WorkspaceConfig
from auto_short.hashing import sha256_file
from auto_short.khaithi import KhaiThi, write
from auto_short.packaging import khaithi_thumbs
from auto_short.publish import PublishError, kt, thumbs, youtube
from auto_short.publish.__main__ import main
from auto_short.workspace import atomic_write_json, read_json_dict

PID, YT_PID = "PLsourceKT1", "SELECTED_KT"
IDS = ("lecture0011", "lecture0007")
TITLE = "Giữ tâm thanh tịnh"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    cfg = Config(workspace=WorkspaceConfig(tmp_path / "work"),
                 render=RenderConfig(output_dir=tmp_path / "output"))
    entries = []
    for base, number in zip(IDS, (11, 7)):
        fields = dict(series="Bộ kinh", episode=str(number), speaker="HT. Tịnh Không")
        atomic_write_json(cfg.workspace.dir / base / "titles.json", dict(header=dict(fields=fields)))
        ident = base + ".kt"
        write(cfg.workspace.dir / ident, KhaiThi(base, 4, 7))
        numbers = dict(k01=1, k02=3, m01=5)  # web numbering, not the digits in clip_id
        atomic_write_json(cfg.workspace.dir / ident / "titles.json", dict(titles=[
            dict(clip_id=cid, candidate_id=f"c{n:02d}", title=TITLE, status="titled")
            for cid, n in numbers.items()]))
        folder = khaithi_thumbs.directory(cfg, ident)
        folder.mkdir(parents=True)
        clips = {}
        for cid in numbers:
            key = ("a" if cid == "k01" else "b" if cid == "k02" else "c") * 64
            clips[cid] = {}
            for shape in ("vertical", "landscape"):
                path = folder / f"{cid}-{shape}-{key}.jpg"
                path.write_bytes(b"\xff\xd8jpeg:" + cid.encode() + shape.encode())
                clips[cid][shape] = dict(file=path.name, key=key, sha256=sha256_file(path))
        atomic_write_json(folder / "thumbs.json", dict(schema_version=1, video_id=ident,
                          playlist_id=PID, clip_numbers=numbers, clips=clips))
        entries.append(dict(video_id=base, episode="999"))  # header is the number authority
    atomic_write_json(cfg.workspace.dir / "_playlists" / f"{PID}.json", dict(playlist_id=PID, entries=entries))
    # Leave read(), directory() and title/review resolution real; omit cover/font rendering setup.
    monkeypatch.setattr(khaithi_thumbs, "valid_files",
                        lambda config, ident, *, pid: (khaithi_thumbs.read(config, ident) or {}).get("clips", {}))
    return cfg


@pytest.fixture
def wire():
    state = SimpleNamespace(replies=[], calls=[])

    def send(method, url, headers, body):
        state.calls.append((method, url, body))
        assert state.replies, f"unexpected request: {method} {url}"
        reply = state.replies.pop(0)
        status, doc = reply if isinstance(reply, tuple) else (200, reply)
        return status, {}, json.dumps(doc).encode()

    state.send = send
    return state


@pytest.fixture
def cli(workspace, tmp_path):
    path, client, token = (tmp_path / name for name in ("config.toml", "client.json", "token.json"))
    path.write_text(f'[workspace]\ndir = "{workspace.workspace.dir}"\n'
                    f'[render]\noutput_dir = "{workspace.render.output_dir}"\n')
    atomic_write_json(client, dict(client_id="fake-client", client_secret="fake-secret"))
    atomic_write_json(token, dict(access_token="fake-token", refresh_token="fake-refresh", expires_at=9999999999))
    return ["kt-thumbs", "--playlist", PID, "--yt-playlist", YT_PID,
            "--config", str(path), "--client", str(client), "--token", str(token)]


def video(name="T11_KT01_tên file.mp4", title=f"T11 KT01 {TITLE} #Phật_pháp", ident="uploaded001"):
    return dict(id=ident, fileDetails=dict(fileName=name), snippet=dict(title=title))


def listing(*videos):
    return [dict(items=[dict(contentDetails=dict(videoId=v["id"])) for v in videos]), dict(items=list(videos))]


@pytest.mark.parametrize("name,title,number,clip", [
    ("T11_KT01_tên file.mp4", "tiêu đề không mã", 11, "k01"),
    ("", f" T7_KT05_{TITLE} #tag", 7, "m01"),
    ("  t011_kt03_tên file.mp4  ", f"t11 KT03 {TITLE}", 11, "k02"),
    (None, f"T7 KT01 {TITLE}", 7, "k01"),
    ("T11_KT1_tên file.mp4", f"T11 KT001 {TITLE}", 11, "k01"),
    ("không có mã.mp4", f"T11_KT03_{TITLE}", 11, "k02"),
    ("T9_ không mã.mp4", "T9_ không mã", None, None),
    ("T11_KT0100_không cắt ngắn mã.mp4", "", None, None),
    ("prefix T11_KT01_title.mp4", "", None, None),
])
def test_code_matching(workspace, name, title, number, clip):
    row = kt.plan(workspace, [video(name, unicodedata.normalize("NFD", title))], pid=PID)[0]
    if number is None:
        assert row["status"] == "bỏ qua" and row["reason"] == "không có mã KT"
    else:
        assert (row["episode"], row["clip_id"], row["shape"], row["status"]) == (number, clip, "landscape", "sẵn sàng")
        assert row["video_id"] == IDS[0 if number == 11 else 1] + ".kt"
        doc = khaithi_thumbs.read(workspace, row["video_id"])
        assert doc["clip_numbers"][clip] == row["clip_number"]
        assert Path(row["file"]).parent == khaithi_thumbs.directory(workspace, row["video_id"])
    assert not (workspace.workspace.dir / "_publish").exists()


@pytest.mark.parametrize("number", [1, 4, 123])
def test_clip_number_widths_without_filename(workspace, number):
    path = workspace.workspace.dir / IDS[0] / "titles.json"
    header = read_json_dict(path)
    header["header"]["fields"]["episode"] = "8"
    atomic_write_json(path, header)
    path = khaithi_thumbs.directory(workspace, IDS[0] + ".kt") / "thumbs.json"
    doc = read_json_dict(path)
    doc["clip_numbers"]["k01"] = number
    atomic_write_json(path, doc)
    source = dict(id="uploaded001", snippet=dict(title=f"T8_KT{number}_{TITLE}"))
    row = kt.plan(workspace, [source], pid=PID)[0]
    assert row["status"] == "sẵn sàng" and not row["reason"] and not row["warning"]
    assert row["episode"] == 8 and row["clip_number"] == number and row["clip_id"] == "k01"


@pytest.mark.parametrize("title", ["T7 KT01 khác tập", "T11_KT03_khác clip"])
def test_code_conflict(workspace, title):
    row = kt.plan(workspace, [video(title=title)], pid=PID)[0]
    assert row["status"] == "bỏ qua" and row["reason"] == "tên file và tiêu đề lệch mã"


@pytest.mark.parametrize("case,reason", [
    ("no_episode", "không có tập khai thị trong playlist nguồn"),
    ("no_marker", "không có tập khai thị trong playlist nguồn"),
    ("outside_playlist", "không có tập khai thị trong playlist nguồn"),
    ("duplicate", "nhiều tập khai thị cùng số trong playlist nguồn"),
    ("no_clip", "không có clip số KT trong hồ sơ thumbnail khai thị"),
    ("no_record", "không có clip số KT trong hồ sơ thumbnail khai thị"),
    ("no_vertical", "chưa có ảnh dọc khai thị hợp lệ hoặc ảnh đã cũ"),
    ("stale", "chưa có ảnh dọc khai thị hợp lệ hoặc ảnh đã cũ"),
])
def test_local_resolution_skips(workspace, monkeypatch, case, reason):
    source = video()
    root = workspace.workspace.dir
    record_path = khaithi_thumbs.directory(workspace, IDS[0] + ".kt") / "thumbs.json"
    if case == "no_episode":
        source = video("T99_KT01_title.mp4", "")
    elif case == "no_marker":
        (root / (IDS[0] + ".kt") / "khaithi.json").unlink()
    elif case == "outside_playlist":
        path = root / "_playlists" / f"{PID}.json"
        doc = read_json_dict(path)
        doc["entries"] = [doc["entries"][1]]
        atomic_write_json(path, doc)
    elif case == "duplicate":
        path = root / IDS[1] / "titles.json"
        doc = read_json_dict(path)
        doc["header"]["fields"]["episode"] = "11"
        atomic_write_json(path, doc)
    elif case == "no_clip":
        source = video("T11_KT99_title.mp4", "")
    elif case == "no_record":
        record_path.unlink()
    elif case == "no_vertical":
        doc = read_json_dict(record_path)
        doc["clips"]["k01"] = {}
        atomic_write_json(record_path, doc)
    elif case == "stale":
        monkeypatch.setattr(khaithi_thumbs, "valid_files", lambda *a, **kw: {})
    row = kt.plan(workspace, [source], pid=PID, shape="vertical")[0]
    assert row["status"] == "bỏ qua" and row["reason"] == reason


@pytest.mark.parametrize("title,web_title,warning", [
    (f" T11_KT01_  {TITLE.upper()}   #tag #Phật_pháp ", TITLE, ""),
    (f"{TITLE} #tag", TITLE, ""),
    ("T11 KT01 Lời giảng khác #tag", TITLE, "tiêu đề YouTube khác tiêu đề web"),
    ("T11 KT01 Giáo dục đạo đức nhờ Thích Đạo là gì", "Giáo dục đạo đức nhờ Thích Đạo là gì?", ""),
    ("T11 KT01 Tại sao làm việc vất vả Vì quá khứ…", "Tại sao làm việc vất vả? Vì quá khứ…", ""),
    ("T11 KT01 GIỮ TÂM 123 thanh tịnh #tag", "“Giữ tâm” (123)—thanh tịnh!", ""),
    ("T11 KT01 vi tín", "vi tính", "tiêu đề YouTube khác tiêu đề web"),
    ("T11 KT01 vi tinh", "vi tính", "tiêu đề YouTube khác tiêu đề web"),
    ("T11 KT01 Giữ tâm 123", "Giữ tâm 124", "tiêu đề YouTube khác tiêu đề web"),
])
def test_title_warning_only(workspace, title, web_title, warning):
    path = workspace.workspace.dir / (IDS[0] + ".kt") / "titles.json"
    doc = read_json_dict(path)
    doc["titles"][0]["title"] = unicodedata.normalize("NFD", web_title)
    atomic_write_json(path, doc)
    row = kt.plan(workspace, [video(title=unicodedata.normalize("NFD", title))], pid=PID)[0]
    assert row["status"] == "sẵn sàng" and not row["reason"] and row["warning"] == warning


@pytest.mark.parametrize("missing", ["--playlist", "--yt-playlist"])
def test_cli_requires_both_playlists(missing, wire):
    other = "--yt-playlist" if missing == "--playlist" else "--playlist"
    with pytest.raises(SystemExit) as exc:
        main(["kt-thumbs", other, PID], transport=wire.send)
    assert exc.value.code == 2 and not wire.calls


def test_cli_dry_run_apply_skip_force(workspace, cli, wire, capsys):
    source = [video(), video("T9_ không mã.mp4", "T9_ không mã", "uploaded002")]
    journal_path = workspace.workspace.dir / "_publish" / "thumbs.json"
    for extra, posts, status in [((), 0, "sẵn sàng"), (("--apply",), 1, "đã gắn"),
                                  (("--apply",), 0, "bỏ qua"), (("--apply", "--force"), 1, "đã gắn")]:
        before = {p: p.read_bytes() for p in workspace.workspace.dir.rglob("*.json")}
        wire.calls.clear()
        wire.replies.extend([*listing(*source), *[dict(items=[]) for _ in range(posts)]])
        assert main([*cli, *extra], transport=wire.send) == 0
        captured = capsys.readouterr()
        assert captured.out.splitlines()[0] == "Video YouTube\tMã\tClip\tẢnh thumbnail\tTrạng thái / lý do\tCảnh báo"
        result = json.loads(captured.out[captured.out.index("{\n"):])
        assert result["mode"] == ("apply" if extra else "chạy thử")
        assert result["rows"][0]["status"] == status and result["rows"][1]["reason"] == "không có mã KT"
        queries = [parse_qs(urlparse(c[1]).query) for c in wire.calls if c[0] == "GET"]
        assert queries[0]["playlistId"] == [YT_PID] and queries[1]["part"] == ["fileDetails,snippet"]
        uploads = [c for c in wire.calls if c[0] == "POST"]
        assert len(uploads) == posts and not wire.replies and not captured.err
        if posts:
            assert uploads[0][2] == Path(result["rows"][0]["file"]).read_bytes()
        if not extra:
            assert {p: p.read_bytes() for p in workspace.workspace.dir.rglob("*.json")} == before
        else:
            journal = thumbs._journal(workspace)[1]
            assert journal["schema_version"] == 1 and len(journal["records"]) == 1
            record = journal["records"][0]
            assert record["video_id"] == IDS[0] + ".kt" and record["clip_id"] == "k01"
            assert record["shape"] == "landscape" and record["sha256"] == result["rows"][0]["sha256"]
            assert read_json_dict(journal_path) == journal


@pytest.mark.parametrize("damage,reason", [
    ("hash", "sha256"), ("oversize", "2 MB"), ("missing", "không đọc được thumbnail"),
    ("stale", "ảnh đã cũ"), ("regenerated", "thumbnail đã thay đổi"),
])
def test_apply_revalidates_kt_image(workspace, monkeypatch, wire, damage, reason):
    row = kt.plan(workspace, [video()], pid=PID, shape="vertical")[0]
    path = Path(row["file"])
    if damage == "missing":
        path.unlink()
    elif damage == "stale":
        monkeypatch.setattr(khaithi_thumbs, "valid_files", lambda *a, **kw: {})
    else:
        path.write_bytes(b"x" * (thumbs.MAX_BYTES + 1) if damage == "oversize" else b"changed")
        if damage == "regenerated":
            doc = read_json_dict(path.parent / "thumbs.json")
            doc["clips"]["k01"]["vertical"]["sha256"] = sha256_file(path)
            atomic_write_json(path.parent / "thumbs.json", doc)
    result = thumbs.apply(workspace, [row], youtube.YouTube(transport=wire.send))
    assert result[0]["status"] == "bỏ qua" and reason in result[0]["reason"]
    assert not wire.calls and not (workspace.workspace.dir / "_publish").exists()


def test_kt_api_failure_stops_after_journaled_success(workspace, cli, wire, capsys):
    source = [video(ident=f"uploaded00{i}") for i in range(1, 4)]
    wire.replies.extend([*listing(*source), dict(items=[]),
                         (403, dict(error=dict(errors=[dict(reason="quotaExceeded")])))])
    assert main([*cli, "--apply"], transport=wire.send) == 1
    assert "quotaExceeded" in capsys.readouterr().err and not wire.replies
    assert len([c for c in wire.calls if c[0] == "POST"]) == 2
    records = thumbs._journal(workspace)[1]["records"]
    assert len(records) == 1 and records[0]["youtube_id"] == "uploaded001" and records[0]["clip_id"] == "k01"


@pytest.mark.parametrize("clip_id", ["k01", "", None, 1, False])
def test_journal_optional_clip_id_must_be_string(workspace, clip_id):
    path = workspace.workspace.dir / "_publish" / "thumbs.json"
    doc = dict(schema_version=1, records=[dict(youtube_id="uploaded001", video_id=IDS[0] + ".kt",
               playlist_id=PID, shape="vertical", sha256="a" * 64, set_at="before", clip_id=clip_id)])
    atomic_write_json(path, doc)
    if isinstance(clip_id, str):
        assert thumbs._journal(workspace)[1] == doc
    else:
        with pytest.raises(PublishError, match="nhật ký"):
            thumbs._journal(workspace)
        assert read_json_dict(path) == doc


@pytest.mark.parametrize("shape", [None, "landscape", "vertical"])
@pytest.mark.parametrize("missing", [False, True])
def test_shape_selection(workspace, shape, missing):
    selected = shape or "landscape"
    ident = IDS[0] + ".kt"
    path = khaithi_thumbs.directory(workspace, ident) / "thumbs.json"
    if missing:
        doc = read_json_dict(path)
        del doc["clips"]["k01"][selected]  # the other shape remains valid: no fallback
        atomic_write_json(path, doc)
    rows = kt.plan(workspace, [video()], pid=PID, **({} if shape is None else dict(shape=shape)))
    row = rows[0]
    assert row["shape"] == selected
    if missing:
        label = "ngang" if selected == "landscape" else "dọc"
        assert row["status"] == "bỏ qua" and row["reason"] == f"chưa có ảnh {label} khai thị hợp lệ hoặc ảnh đã cũ"
    else:
        image = khaithi_thumbs.read(workspace, ident)["clips"]["k01"][selected]
        assert row["status"] == "sẵn sàng" and not row["reason"]
        assert Path(row["file"]).name == image["file"] and row["sha256"] == image["sha256"]


@pytest.mark.parametrize("shape", [None, "landscape", "vertical"])
def test_cli_shape_selection(workspace, cli, wire, capsys, shape):
    selected = shape or "landscape"
    extra = ["--shape", shape] if shape is not None else []
    wire.replies.extend([*listing(video()), dict(items=[])])
    assert main([*cli, *extra, "--apply"], transport=wire.send) == 0
    output = capsys.readouterr()
    result = json.loads(output.out[output.out.index("{\n"):])
    row = result["rows"][0]
    assert row["status"] == "đã gắn" and row["shape"] == selected
    image = khaithi_thumbs.read(workspace, IDS[0] + ".kt")["clips"]["k01"][selected]
    path = khaithi_thumbs.directory(workspace, IDS[0] + ".kt") / image["file"]
    assert [c[2] for c in wire.calls if c[0] == "POST"] == [path.read_bytes()]
    record = thumbs._journal(workspace)[1]["records"][0]
    assert record["shape"] == selected and record["sha256"] == image["sha256"]
    assert not wire.replies and not output.err


def test_shape_change_reapplies_without_force(workspace, cli, wire, capsys):
    hashes = []
    for extra, posts, selected in [(["--shape", "vertical"], 1, "vertical"),
                                    ([], 1, "landscape"), ([], 0, "landscape")]:
        wire.calls.clear()
        wire.replies.extend([*listing(video()), *[dict(items=[]) for _ in range(posts)]])
        assert main([*cli, *extra, "--apply"], transport=wire.send) == 0
        assert len([c for c in wire.calls if c[0] == "POST"]) == posts and not wire.replies
        record = thumbs._journal(workspace)[1]["records"][0]
        assert record["shape"] == selected
        hashes.append(record["sha256"])
        assert not capsys.readouterr().err
    assert hashes[0] != hashes[1] == hashes[2]
