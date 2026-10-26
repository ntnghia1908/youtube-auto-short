"""HD2a AC1: real handler and streamed disk I/O, with no socket/network calls."""
import csv
import hashlib
import importlib.util
import io
import json
import os
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

SPEC = importlib.util.spec_from_file_location("hd2_store", Path(__file__).parents[1] / "tools/store/store.py")
store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(store)

VIDEO = "abcDEF12_-3"
PLAYLIST = "PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4"
NAME = "[HD] Kinh Địa Tạng - Tập 1.mp4"
TOKEN = "a1" * 32
DATA = b"0123456789"
SHA = hashlib.sha256(DATA).hexdigest()


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "root"
    series = tmp_path / "old-backup"
    root.mkdir()
    series.mkdir()
    (tmp_path / "token.txt").write_text(TOKEN + "\n")
    config = tmp_path / "config.json"
    config.write_text(json.dumps(dict(root="root", token_file="token.txt", series={PLAYLIST: str(series)})))
    return store.Store(store.load_config(config)), series, config


def seed(folder, filename="index.csv", rows=None):
    if rows is None:
        rows = [dict(tap="001", loai="HD", file=NAME, video_id=VIDEO, tieu_de="Địa Tạng, tập 1")]
    with (folder / filename).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=store.COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    (folder / NAME).write_bytes(DATA)
    (folder / "SHA256SUMS.txt").write_text(f"{SHA.upper()}  {NAME}\n", encoding="utf-8-sig")


class MemoryConnection:
    """BaseHTTPRequestHandler uses its normal parser, response writer and dispatch."""
    def __init__(self, request):
        self.request = request
        self.response = bytearray()

    def makefile(self, *args):
        return io.BytesIO(self.request)

    def sendall(self, data):
        self.response.extend(data)


def request(archive_store, method="GET", path="/index", headers=None, body=b"", auth=TOKEN):
    fields = [] if auth is None else [("Authorization", "Bearer " + auth)]
    fields += list((headers or {}).items())
    raw = f"{method} {path} HTTP/1.0\r\n".encode()
    raw += b"".join(f"{key}: {value}\r\n".encode() for key, value in fields)
    connection = MemoryConnection(raw + b"\r\n" + body)
    store.StoreHandler(connection, ("127.0.0.1", 12345), SimpleNamespace(store=archive_store))
    head, _, result = bytes(connection.response).partition(b"\r\n\r\n")
    status, _, header_bytes = head.partition(b"\r\n")
    parsed = BytesParser().parsebytes(header_bytes + b"\r\n\r\n")
    return int(status.split()[1]), parsed, result


def test_source_put_index_head_get_and_bad_sha(archive):
    service, folder, _ = archive
    name = "[Goc] Kinh Địa Tạng - Tập 1.mp4"
    route = f"/files/{VIDEO}/source"
    query = "?" + urlencode(dict(series=PLAYLIST, name=name))
    headers = {"Content-Length": str(len(DATA)), "X-Sha256": SHA}
    assert request(service, "PUT", route + query, headers, DATA)[0] == 201
    assert service.index() == [dict(video_id=VIDEO, kind="source", series=PLAYLIST, file=name,
                                    size=len(DATA), sha256=SHA)]
    code, fields, result = request(service, "HEAD", route)
    assert code == 200 and fields["X-Sha256"] == SHA and int(fields["Content-Length"]) == len(DATA)
    assert result == b"" and request(service, "GET", route)[2] == DATA
    assert request(service, "PUT", route + query, headers, DATA)[0] == 200
    with (folder / "index.csv").open(encoding="utf-8-sig") as stream:
        assert list(csv.DictReader(stream))[0]["loai"] == "Goc"
    bad = f"/files/zyxWVUT9876/source?" + urlencode(dict(series=PLAYLIST, name="[Goc] bad.mp4"))
    assert request(service, "PUT", bad, {**headers, "X-Sha256": "0" * 64}, DATA)[0] == 422
    assert not (folder / "[Goc] bad.mp4").exists()
    assert len(service.index()) == 1


def test_index_backup_formats_cache_and_missing_files(archive, monkeypatch):
    service, folder, _ = archive
    seed(folder, "danh-sach.csv")
    expected = dict(video_id=VIDEO, kind="hd", series=PLAYLIST, file=NAME, size=10, sha256=SHA)
    assert service.index() == [expected]
    # Cache must avoid parsing CSV until metadata changes.
    with monkeypatch.context() as patch:
        patch.setattr(store.csv, "DictReader", lambda *a, **kw: pytest.fail("CSV parsed again"))
        assert service.index() == [expected]
    new_sha = "f" * 64
    sums = folder / "SHA256SUMS.txt"
    old_time = sums.stat().st_mtime_ns
    sums.write_text(f"{new_sha}  {NAME}\n", encoding="utf-8")
    os.utime(sums, ns=(old_time + 10_000, old_time + 10_000))
    assert service.index()[0]["sha256"] == new_sha
    # index.csv overrides legacy rows; the .kt suffix and Doc mapping are retained.
    rows = [dict(tap="", loai="Doc", file=NAME, video_id=VIDEO + ".kt", tieu_de="")]
    seed(folder, rows=rows)
    assert {r["kind"] for r in service.index()} == {"hd", "vertical"}
    (folder / NAME).unlink()
    assert service.index() == []
    (folder / NAME).write_bytes(DATA)
    assert len(service.index()) == 2
    # Rewrite the CSV (not the sums): its mtime must invalidate the cache too.
    with (folder / "index.csv").open("a", encoding="utf-8", newline="") as stream:
        csv.DictWriter(stream, fieldnames=store.COLUMNS).writerow(
            dict(tap="", loai="HD", file=NAME, video_id="zyxWVUT9876", tieu_de=""))
    assert len(service.index()) == 3
    rows += [dict(tap="", loai="HD", file="../escape.mp4", video_id=VIDEO, tieu_de="")]
    rows += [dict(tap="", loai="HD", file="no-sha.mp4", video_id="zyxWVUT9876", tieu_de="")]
    seed(folder, rows=rows)
    assert len(service.index()) == 2


@pytest.mark.parametrize("value,size,expected", [
    ("bytes=0-0", 10, (0, 0)), ("bytes=3-6", 10, (3, 6)),
    ("bytes=3-", 10, (3, 9)), ("bytes=-3", 10, (7, 9)),
    ("bytes=-100", 10, (0, 9)), ("bytes=2-100", 10, (2, 9)),
    ("bytes=10-", 10, None), ("bytes=5-3", 10, None), ("bytes=-0", 10, None),
    ("bytes=-", 10, None), ("bytes=0-1,4-5", 10, None), ("bytes=0-0", 0, None),
    ("items=0-1", 10, None), ("bytes=+1-2", 10, None), ("garbage", 10, None),
])
def test_range_parser(value, size, expected):
    if expected is None:
        with pytest.raises(store.StoreError) as error:
            store.parse_range(value, size)
        assert error.value.status == 416
    else:
        assert store.parse_range(value, size) == expected


@pytest.mark.parametrize("name", ["../x.mp4", "x..mp4", "a/b.mp4", "a\\b.mp4", "C:x.mp4",
                                     "NUL.mp4", "CON.mp4", "a.mp4:secret", "a\n.mp4", "x.txt", "a.mp4 "])
def test_path_validation(archive, name):
    service, folder, _ = archive
    with pytest.raises(store.StoreError) as error:
        service.put(VIDEO, "hd", PLAYLIST, name, SHA, io.BytesIO(DATA), len(DATA))
    assert error.value.status == 400
    assert list(folder.iterdir()) == []


@pytest.mark.parametrize("target", ["file", "part", "index", "sums", "folder", "root", "reparse"])
def test_symlinks_and_reparse_points_refused(archive, tmp_path, monkeypatch, target):
    service, folder, _ = archive
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_bytes(b"keep")
    if target == "reparse":
        lstat = Path.lstat

        def fake_lstat(path, *args, **kwargs):
            info = lstat(path, *args, **kwargs)
            if path == folder:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        monkeypatch.setattr(Path, "lstat", fake_lstat)
    elif target in ("folder", "root"):
        link = folder if target == "folder" else service.root
        link.rmdir()
        link.symlink_to(outside, target_is_directory=True)
    else:
        leaf = {"file": NAME, "part": NAME + ".part", "index": "index.csv", "sums": "SHA256SUMS.txt"}[target]
        (folder / leaf).symlink_to(outside / "keep")
    with pytest.raises(store.StoreError) as error:
        service.put(VIDEO, "hd", PLAYLIST, NAME, SHA, io.BytesIO(DATA), len(DATA))
    assert error.value.status == 400
    assert (outside / "keep").read_bytes() == b"keep"
    assert sorted(p.name for p in outside.iterdir()) == ["keep"]


@pytest.mark.parametrize("scenario,status", [
    ("new", 201), ("same", 200), ("conflict", 409), ("bad_sha", 422),
    ("truncated", 400), ("limit", 413), ("stale_part", 409), ("interrupted", None),
    ("unindexed_same", 200), ("unindexed_conflict", 409), ("alias", 409),
    ("other_owner", 409), ("new_series", 201), ("bad_series", 400),
])
def test_put_stream_hash_atomic_publish(archive, monkeypatch, scenario, status):
    service, folder, _ = archive
    monkeypatch.setattr(store, "CHUNK", 3)
    video_id = VIDEO
    name, series, sha, payload, length = NAME, PLAYLIST, SHA, DATA, len(DATA)
    if scenario in ("same", "conflict", "alias", "other_owner"):
        seed(folder)
    if scenario == "conflict":
        sha = "0" * 64
    if scenario == "bad_sha":
        sha = "1" * 64
    if scenario == "truncated":
        payload = DATA[:-1]
    if scenario == "limit":
        length = store.MAX_BODY + 1
    if scenario == "stale_part":
        (folder / (name + ".part")).write_bytes(b"previous upload")
    if scenario == "unindexed_same":
        (folder / name).write_bytes(DATA)
    if scenario == "unindexed_conflict":
        (folder / name).write_bytes(b"keep original")
    if scenario == "alias":
        name = "other.mp4"
    if scenario == "other_owner":
        video_id = "zyxWVUT9876"
    if scenario == "new_series":
        series = "new_playlist"
        folder = service.root / series
    if scenario == "bad_series":
        series = "../escape"

    class Interrupted:
        def read(self, count):
            raise OSError("connection lost")

    class ChunkedStream(io.BytesIO):
        def read(self, count):
            assert 0 < count <= 3
            return super().read(count)

    stream = Interrupted() if scenario == "interrupted" else ChunkedStream(payload)
    if scenario == "interrupted":
        with pytest.raises(OSError):
            service.put(video_id, "hd", series, name, sha, stream, length)
    elif status >= 400:
        with pytest.raises(store.StoreError) as error:
            service.put(video_id, "hd", series, name, sha, stream, length)
        assert error.value.status == status
    else:
        before = {p: p.read_bytes() for p in folder.iterdir()} if folder.exists() else {}
        assert service.put(video_id, "hd", series, name, sha, stream, length) == status
        assert (folder / name).read_bytes() == DATA
        assert service.index()[0]["sha256"] == SHA
        if scenario == "same":
            assert stream.tell() == 0
            assert before == {p: p.read_bytes() for p in folder.iterdir()}
        else:
            with (folder / "index.csv").open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                assert reader.fieldnames == list(store.COLUMNS)
                assert list(reader)[0]["file"] == name
    part = folder / (name + ".part")
    if scenario == "stale_part":
        assert part.read_bytes() == b"previous upload"
    else:
        assert not part.exists()
    if scenario == "unindexed_conflict":
        assert (folder / name).read_bytes() == b"keep original"
    if scenario in ("bad_sha", "truncated", "limit", "interrupted", "bad_series"):
        assert not (folder / name).exists()
        assert not (folder / "index.csv").exists()
        assert not (folder / "SHA256SUMS.txt").exists()


@pytest.mark.parametrize("method,path,headers,expected,body", [
    ("GET", "/index", {}, 200, None),
    ("HEAD", f"/files/{VIDEO}/hd", {}, 200, b""),
    ("GET", f"/files/{VIDEO}/hd", {}, 200, DATA),
    ("GET", f"/files/{VIDEO}/hd", {"Range": "bytes=2-5"}, 206, DATA[2:6]),
    ("GET", f"/files/{VIDEO}/hd", {"Range": "bytes=-2"}, 206, DATA[-2:]),
    ("GET", f"/files/{VIDEO}/hd", {"Range": "bytes=9-"}, 206, DATA[9:]),
    ("GET", f"/files/{VIDEO}/hd", {"Range": "bytes=99-"}, 416, b""),
    ("GET", f"/files/{VIDEO}/hd", {"Range": "bytes=0-1,3-4"}, 416, b""),
    ("HEAD", f"/files/{VIDEO}/hd", {"Range": "bad"}, 200, b""),
    ("GET", f"/files/{VIDEO}/vertical", {}, 404, None),
    ("HEAD", "/files/zyxWVUT9876/hd", {}, 404, b""),
    ("GET", "/files/../hd", {}, 400, None),
    ("GET", "/files/%2e%2e/hd", {}, 400, None),
    ("GET", f"/files/{VIDEO}/other", {}, 400, None),
    ("GET", "/not-an-endpoint", {}, 404, None),
    ("DELETE", f"/files/{VIDEO}/hd", {}, 404, None),
])
def test_http_read_routes(archive, method, path, headers, expected, body):
    service, folder, _ = archive
    seed(folder)
    status, result_headers, actual = request(service, method, path, headers)
    assert status == expected
    if body is not None:
        assert actual == body
    if expected in (200, 206) and path != "/index":
        assert result_headers["X-Sha256"] == SHA
        assert int(result_headers["Content-Length"]) == (len(DATA) if method == "HEAD" else len(body))
    if expected == 206:
        assert result_headers["Content-Range"].endswith("/10")
    if expected == 416:
        assert result_headers["Content-Range"] == "bytes */10"
    if path == "/index":
        assert json.loads(actual)[0]["video_id"] == VIDEO


@pytest.mark.parametrize("method", ["GET", "HEAD", "PUT", "DELETE"])
@pytest.mark.parametrize("auth", [None, "wrong", "nonascii-é"])
def test_http_auth_and_no_secret_logs(archive, capsys, method, auth):
    service, _, _ = archive
    status, headers, body = request(service, method, f"/files/{VIDEO}/hd?secret={TOKEN}", auth=auth)
    assert status == 401
    assert headers["WWW-Authenticate"] == "Bearer"
    if method == "HEAD":
        assert not body
    logs = capsys.readouterr()
    assert TOKEN not in logs.out + logs.err
    assert "wrong" not in logs.out + logs.err


@pytest.mark.parametrize("scenario,expected", [
    ("new", 201), ("missing_length", 411), ("bad_length", 400),
    ("too_large", 413), ("missing_sha", 400), ("bad_sha", 400),
    ("mismatch", 422), ("chunked", 400), ("duplicate_query", 400), ("bad_name", 400),
])
def test_http_put(archive, scenario, expected):
    service, folder, _ = archive
    headers = {"Content-Length": str(len(DATA)), "X-Sha256": SHA}
    query = urlencode(dict(series=PLAYLIST, name=NAME))
    if scenario == "missing_length":
        headers.pop("Content-Length")
    elif scenario == "bad_length":
        headers["Content-Length"] = "-2"
    elif scenario == "too_large":
        headers["Content-Length"] = str(store.MAX_BODY + 1)
    elif scenario == "missing_sha":
        headers.pop("X-Sha256")
    elif scenario == "bad_sha":
        headers["X-Sha256"] = "not-sha"
    elif scenario == "mismatch":
        headers["X-Sha256"] = "0" * 64
    elif scenario == "chunked":
        headers["Transfer-Encoding"] = "chunked"
    elif scenario == "duplicate_query":
        query += "&series=other"
    elif scenario == "bad_name":
        query = urlencode(dict(series=PLAYLIST, name="../outside.mp4"))
    status, _, _ = request(service, "PUT", f"/files/{VIDEO}/hd?{query}", headers, DATA)
    assert status == expected
    if scenario == "new":
        assert (folder / NAME).read_bytes() == DATA
        assert request(service, "GET", f"/files/{VIDEO}/hd")[2] == DATA
        # Repeat the exact request: no duplicate metadata.
        assert request(service, "PUT", f"/files/{VIDEO}/hd?{query}", headers, DATA)[0] == 200
        assert len(service.index()) == 1
    else:
        assert not (folder / NAME).exists()
        assert not (folder / (NAME + ".part")).exists()


def test_self_test_config_validation_and_loopback_binding(archive, capsys, monkeypatch):
    _, folder, config = archive
    seed(folder)
    assert store.main(["--config", str(config), "--self-test"]) == 0
    output = capsys.readouterr()
    assert "1 series, 1 files (hd=1, vertical=0)" in output.out
    assert TOKEN not in output.out + output.err

    class FakeServer:
        def __init__(self, address, handler):
            assert address == ("127.0.0.1", 18090)
            assert handler is store.StoreHandler

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def serve_forever(self):
            assert self.store.index()[0]["sha256"] == SHA
            raise KeyboardInterrupt

    monkeypatch.setattr(store, "ThreadingHTTPServer", FakeServer)
    assert store.main(["--config", str(config)]) == 0
    original = config.read_text()
    for change in ({"port": 0}, {"port": True}, {"root": "missing"}, {"series": []}):
        updated = json.loads(original)
        updated.update(change)
        config.write_text(json.dumps(updated))
        assert store.main(["--config", str(config), "--self-test"]) == 1
    config.write_text(original)
    (folder / "index.csv").write_text('"wrong","columns"\n')
    assert store.main(["--config", str(config), "--self-test"]) == 1
    (config.parent / "token.txt").write_text("")
    assert store.main(["--config", str(config), "--self-test"]) == 1


@pytest.mark.parametrize("video_id", [VIDEO, VIDEO + ".kt"])
def test_short_put_index_range_and_conflict(archive, video_id):
    service, folder, _ = archive
    seed(folder)
    original_index = (folder / "index.csv").read_bytes()
    headers = {"Content-Length": str(len(DATA)), "X-Sha256": SHA}
    clips = ("k01.mp4", "k100.mp4", "m01.mp4")
    for clip in clips:
        name = f"[Short] Tập 1 - {video_id} - {clip}"
        route = f"/files/{video_id}/short/{clip}"
        query = "?" + urlencode(dict(series=PLAYLIST, name=name))
        assert request(service, "PUT", route + query, headers, DATA)[0] == 201
        assert request(service, "PUT", route + query, headers, DATA)[0] == 200
        code, fields, body = request(service, "HEAD", route)
        assert (code, fields["X-Sha256"], fields["Content-Length"], body) == (200, SHA, "10", b"")
        code, fields, body = request(service, "GET", route, {"Range": "bytes=2-5"})
        assert code == 206 and body == DATA[2:6] and fields["Content-Range"] == "bytes 2-5/10"
        assert request(service, "GET", route)[2] == DATA
        assert request(service, "PUT", route + query, {**headers, "X-Sha256": "0" * 64}, DATA)[0] == 409
        different_name = "?" + urlencode(dict(series=PLAYLIST, name="different.mp4"))
        assert request(service, "PUT", route + different_name, headers, DATA)[0] == 409
    assert (folder / "index.csv").read_bytes() == original_index
    with (folder / "index-short.csv").open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert [r["clip"] for r in rows] == list(clips)
    index = json.loads(request(service)[2])
    assert len(index) == 4 and index[0]["kind"] == "hd"
    assert [(r["video_id"], r["clip"], r["sha256"]) for r in index[1:]] == [
        (video_id, clip, SHA) for clip in clips]
    assert len((folder / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines()) == 4
    # HEAD lookup does not stat every other Short in the index.
    service.index = lambda: pytest.fail("lookup must use the cached catalogue")
    assert request(service, "HEAD", f"/files/{video_id}/short/k01.mp4")[0] == 200


@pytest.mark.parametrize("suffix", ["short", "short/_k1.mp4", "short/" + "k" * 33 + ".mp4", "short/k01.txt",
                                    "short/k01%5Cmp4", "short/..mp4", "hd/k01.mp4"])
def test_short_rejects_invalid_clip_paths(archive, suffix):
    service, _, _ = archive
    assert request(service, "GET", f"/files/{VIDEO}/{suffix}")[0] == 400


@pytest.mark.parametrize("clip", ["..mp4", "m..01.mp4", "../m01.mp4", "m/01.mp4", "m\\01.mp4",
                                   "m:01.mp4", 'm"01.mp4', "m<01.mp4", "m>01.mp4", "m|01.mp4",
                                   "m?01.mp4", "m*01.mp4"])
def test_short_rejects_unsafe_clip_identity(archive, clip):
    service, _, _ = archive
    with pytest.raises(store.StoreError) as exc:
        service.put(VIDEO, "short", PLAYLIST, "[Short] m01.mp4", SHA, io.BytesIO(DATA), len(DATA), clip=clip)
    assert exc.value.status == 400
    assert service.index() == []
