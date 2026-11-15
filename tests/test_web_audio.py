"""LISTEN2 F: real AAC extraction and ASGI file responses, without sockets/TestClient."""

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from array import array
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.requests import Request

from auto_short.store.client import StoreMismatch, StoreUnavailable
from auto_short.web import audio_cache, episodes as ep
from auto_short.web.routes import files_catchall
from web_helpers import make_app, write_episode

EID = "youtube0001.kt"


def forbidden(*args, **kwargs):
    pytest.fail("audio playback must never mark_downloaded or tracked")


def audio_route(cfg):
    router = files_catchall.build(SimpleNamespace(config=cfg, mark_downloaded=forbidden, tracked=forbidden))
    return next(r.endpoint for r in router.routes if r.path == "/files/{episode_id}/{name}")


def serve(response, range_header=None):
    """Real Range handling; inline file I/O avoids AnyIO's socket-based worker wakeup here."""
    async def inline_io(func, *args, **kwargs):
        return func(*args)

    async def invoke():
        messages = []

        async def send(message):
            messages.append(message)

        scope = {"type": "http", "method": "GET", "path": f"/files/{EID}/k01.m4a",
                 "headers": [(b"range", range_header.encode())] if range_header else [],
                 "extensions": {}, "asgi": {"spec_version": "2.4"}}
        await response(scope, None, send)
        start = messages[0]
        return start["status"], dict(start["headers"]), b"".join(m.get("body", b"") for m in messages)

    with patch("anyio.to_thread.run_sync", inline_io):
        return asyncio.run(invoke())


@pytest.fixture
def short(cfg, video):
    write_episode(cfg, EID, clips=("k01",))
    path = Path(cfg.render.output_dir) / EID / "shorts/k01.mp4"
    shutil.copy2(video, path)
    return path


def test_audio_route_only_audio_range_cache_and_render_version(cfg, short, monkeypatch):  # AC13
    calls, run = [], audio_cache._run

    def counted(cmd):
        calls.append(cmd)
        return run(cmd)

    monkeypatch.setattr(audio_cache, "_run", counted)
    route = audio_route(cfg)
    first = route(EID, "k01.m4a", download="1", dl="ignored")
    assert first.media_type == "audio/mp4"
    status, headers, body = serve(first)
    assert status == 200 and headers[b"content-type"] == b"audio/mp4"
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(first.path)],
                           check=True, capture_output=True, text=True)
    streams = json.loads(probe.stdout)["streams"]
    assert [(s["codec_type"], s["codec_name"]) for s in streams] == [("audio", "aac")]
    def duration(path):
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                     "default=nw=1:nk=1", str(path)], check=True, capture_output=True, text=True).stdout)
    assert duration(first.path) - duration(short) == pytest.approx(audio_cache.AUDIO_PAD, abs=.08)
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(first.path), "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], check=True, capture_output=True).stdout
    samples = array("h", pcm)
    assert max(abs(v) for v in samples[:int(1.4 * 16000)]) < 30
    assert max(abs(v) for v in samples[int(1.6 * 16000):int(2 * 16000)]) > 1000
    second = route(EID, "k01.m4a")
    assert first.path == second.path and len(calls) == 1
    status, headers, chunk = serve(second, "bytes=10-29")
    assert status == 206 and chunk == body[10:30]
    assert headers[b"content-range"] == f"bytes 10-29/{len(body)}".encode()
    assert serve(route(EID, "k01.m4a"), f"bytes={len(body)}-")[0] == 416
    stat = short.stat()
    os.utime(short, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    third = route(EID, "k01.m4a")
    assert third.path != first.path and len(calls) == 2
    monkeypatch.setattr(audio_cache, "AUDIO_PAD", 2.0)
    fourth = route(EID, "k01.m4a")
    assert fourth.path != third.path and len(calls) == 3
    assert duration(fourth.path) - duration(third.path) == pytest.approx(.5, abs=.08)
    assert list((Path(cfg.workspace.dir) / "_audio_cache").glob(".extract-*")) == []


@pytest.mark.parametrize("eid,name", [("../bad", "k01.m4a"), (EID, "../k01.m4a"),
                                     (EID, "k999.m4a"), ("youtube9999", "k01.m4a")])
def test_audio_route_invalid_or_missing_is_404(cfg, short, eid, name):  # AC13
    assert audio_route(cfg)(eid, name, download="1", dl="ignored").status_code == 404


def released_short(cfg, short):
    out = Path(cfg.render.output_dir) / EID
    record = {"sha256": hashlib.sha256(short.read_bytes()).hexdigest(), "size": short.stat().st_size,
              "mtime_ns": short.stat().st_mtime_ns}
    manifest = json.loads((out / "render_manifest.json").read_text())
    manifest["shorts"][0]["sha256"] = record["sha256"]
    (out / "render_manifest.json").write_text(json.dumps(manifest))
    (out / "store.json").write_text(json.dumps({"released": {"k01": record}}))
    data = short.read_bytes()
    short.unlink()
    assert isinstance(ep.short_locations(cfg, EID)[0][1], ep.StoredShort)
    return data


@pytest.mark.parametrize("failure", [None, "disabled", "offline", "mismatch", "truncated", "corrupt"])
def test_audio_route_released_short_stream_and_failures(cfg, short, monkeypatch, failure):  # AC13
    data = released_short(cfg, short)
    cfg = replace(cfg, store=replace(cfg.store, enabled=failure != "disabled"))
    calls, streams = [], []

    class Stream:
        closed = False

        def __iter__(self):
            yield data[:100]
            if failure == "truncated":
                yield data[100:-10]
            elif failure == "corrupt":
                yield data[100:-1] + bytes([data[-1] ^ 1])
            else:
                yield data[100:]

        def close(self):
            self.closed = True

    def open_stream(eid, kind, range_header=None, *, clip):
        calls.append((eid, kind, range_header, clip))
        if failure == "disabled":
            pytest.fail("disabled store must never be contacted")
        if failure == "offline":
            raise StoreUnavailable("offline")
        if failure == "mismatch":
            raise StoreMismatch("missing")
        streams.append(Stream())
        return 200, {}, streams[-1]

    monkeypatch.setattr(audio_cache.StoreClient, "from_config", lambda _: SimpleNamespace(open_stream=open_stream))
    route = audio_route(cfg)
    response = route(EID, "k01.m4a", request=Request({"type": "http", "headers": [(b"range", b"bytes=0-9")]}))
    expected = {None: 200, "disabled": 503, "offline": 503, "mismatch": 404, "truncated": 404, "corrupt": 404}[failure]
    assert response.status_code == expected
    if failure is None:
        assert serve(response, "bytes=0-9")[0] == 206
        assert route(EID, "k01.m4a").path == response.path
        assert calls == [(EID, "short", None, "k01.mp4")]  # Fetch whole mp4 once, then Range local m4a.
    else:
        assert not list((Path(cfg.workspace.dir) / "_audio_cache").glob("*.m4a"))
    assert all(stream.closed for stream in streams)
    assert not list((Path(cfg.workspace.dir) / "_audio_cache").glob(".extract-*"))


def test_audio_cache_serializes_same_key_and_evicts_oldest(cfg, short, monkeypatch):  # AC13
    calls, run = [], audio_cache._run

    def counted(cmd):
        calls.append(cmd)
        return run(cmd)

    monkeypatch.setattr(audio_cache, "_run", counted)
    route = audio_route(cfg)
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _: route(EID, "k01.m4a").path, range(4)))
    assert len(set(paths)) == len(calls) == 1
    first = paths[0]
    monkeypatch.setattr(audio_cache, "MAX_BYTES", first.stat().st_size + 100)
    stat = short.stat()
    os.utime(short, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    second = route(EID, "k01.m4a").path
    assert second != first and second.exists() and not first.exists()


def test_audio_cache_failed_extraction_leaves_no_partial(cfg, short):
    short.write_bytes(b"not a video")
    assert audio_route(cfg)(EID, "k01.m4a").status_code == 500
    assert list((Path(cfg.workspace.dir) / "_audio_cache").iterdir()) == []


def test_audio_route_uses_existing_files_login_boundary(cfg):
    from auto_short.web.auth import COOKIE_NAME
    app = make_app(cfg)
    dispatch = next(m.kwargs["dispatch"] for m in app.user_middleware
                    if getattr(m.kwargs.get("dispatch"), "__name__", "") == "auth_middleware")

    async def exercise():
        for signed_in in (False, True):
            reached = False

            async def downstream(request):
                nonlocal reached
                reached = True
                from starlette.responses import Response
                return Response(status_code=204)

            headers = [(b"cookie", f"{COOKIE_NAME}={app.state.signer.issue()}".encode())] if signed_in else []
            response = await dispatch(Request({"type": "http", "method": "GET", "path": f"/files/{EID}/k01.m4a",
                                               "headers": headers, "query_string": b"v=abc"}), downstream)
            assert reached is signed_in
            assert response.status_code == (204 if signed_in else 401)

    asyncio.run(exercise())


def test_http_audio_route_login_and_range(cfg, short, monkeypatch):
    """ORCHESTRATOR runs this integration case where TestClient worker wakeups work."""
    from auto_short.web.context import WebContext
    from web_helpers import login, web_client
    monkeypatch.setattr(WebContext, "mark_downloaded", forbidden)
    monkeypatch.setattr(WebContext, "tracked", forbidden)
    with web_client(cfg) as client:
        url = f"/files/{EID}/k01.m4a?v=render-version&download=1&dl=ignored"
        assert client.get(url).status_code == 401
        login(client)
        response = client.get(url)
        assert response.status_code == 200 and response.headers["content-type"] == "audio/mp4"
        partial = client.get(url, headers={"Range": "bytes=10-29"})
        assert partial.status_code == 206 and partial.content == response.content[10:30]
