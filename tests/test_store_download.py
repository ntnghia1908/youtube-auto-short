"""HD2b G5: exercise authenticated ASGI routes in process; fake upstream, no loopback socket."""
import asyncio
import io
import inspect
from dataclasses import replace
from urllib.parse import urlsplit

import httpx
import pytest
from starlette.requests import Request
from starlette.routing import Match

from auto_short.config import StoreConfig
from auto_short.render import full
from auto_short.review import backup, content_disposition
from auto_short.store.client import StoreClient, StoreMismatch, StoreUnavailable
from auto_short.web import episodes as ep
from auto_short.web.app import create_app
from auto_short.web.auth import COOKIE_NAME
from auto_short.web.routes.episodes import _StoreResponse
from auto_short.workspace import atomic_write_json

from test_store_offload import VID, HD, VERTICAL, digest, seed


class DownloadStore:
    def __init__(self):
        self.calls, self.streams = [], []
        self.error = None

    def open_stream(self, owner, kind, range_header=None):
        self.calls.append((owner, kind, range_header))
        if self.error:
            raise self.error
        data = HD if kind == "hd" else VERTICAL
        headers = {"Accept-Ranges": "bytes", "Authorization": "secret-must-not-escape"}
        status = 200
        if range_header:
            assert range_header == "bytes=2-7"
            headers["Content-Range"] = f"bytes 2-7/{len(data)}"
            data, status = data[2:8], 206
        headers["Content-Length"] = str(len(data))
        stream = io.BytesIO(data)
        # BytesIO iterates by line; these short test bytes are intentionally one chunk.
        self.streams.append(stream)
        return status, headers, stream


def setup_download(cfg, monkeypatch, *, hd=True, enabled=True):
    cfg = replace(cfg, store=StoreConfig(enabled=enabled))
    d, path = seed(cfg, hd=hd)
    if hd:
        backup.confirm(cfg, VID, "hd", digest(HD))
    backup.confirm(cfg, VID, "vertical", digest(VERTICAL))
    backup.release(cfg, VID)
    app = create_app(cfg, "pw", preflight=None, post_preflight=None)
    store = DownloadStore()
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: store)
    return cfg, app, store


@pytest.fixture(params=["direct", "asgi"])
def transport(request):
    return request.param


def request(app, method, url, *, transport="asgi", **kwargs):
    if transport == "direct":
        # The same route assertions can run in a sandbox whose event-loop wakeup socket is blocked.
        scope = {"type": "http", "method": method, "path": urlsplit(url).path,
                 "headers": [(k.lower().encode(), v.encode()) for k, v in kwargs.get("headers", {}).items()]}
        routes = list(app.router.routes)
        while routes:
            route = routes.pop(0)
            if hasattr(route, "original_router"):
                routes[0:0] = route.original_router.routes
                continue
            match, child = route.matches(scope)
            if match != Match.FULL:
                continue
            params = child["path_params"]
            if "request" in inspect.signature(route.endpoint).parameters:
                params["request"] = Request(scope)
            response = route.endpoint(**params)
            if isinstance(response, dict):
                return httpx.Response(200, json=response)
            if isinstance(response, _StoreResponse):
                try:
                    body = b"".join(response.stream)
                finally:
                    response.stream.close()
            else:
                body = response.body
            return httpx.Response(response.status_code, headers=response.headers, content=body)
        raise AssertionError(f"no route: {method} {url}")
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                    cookies={COOKIE_NAME: app.state.signer.issue()}) as client:
            return await client.request(method, url, **kwargs)
    return asyncio.run(run())


@pytest.mark.parametrize("kind,range_header", [("hd", None), ("vertical", None),
                                               ("hd", "bytes=2-7"), ("vertical", "bytes=2-7")])
def test_released_download_exact_bytes_range_and_name(cfg, monkeypatch, kind, range_header, transport):
    cfg, app, store = setup_download(cfg, monkeypatch)
    route = "source-hd" if kind == "hd" else "vertical"
    response = request(app, "GET", f"/api/episodes/{VID}/{route}",
                       headers={"Range": range_header} if range_header else {}, transport=transport)
    data = HD if kind == "hd" else VERTICAL
    assert response.status_code == (206 if range_header else 200)
    assert response.content == (data[2:8] if range_header else data)
    assert response.headers["Content-Length"] == str(6 if range_header else len(data))
    if range_header:
        assert response.headers["Content-Range"] == f"bytes 2-7/{len(data)}"
    assert response.headers["Accept-Ranges"] == "bytes"
    assert response.headers["Content-Type"] == "video/mp4"
    name = ep.hd_download_name(cfg, VID) if kind == "hd" else ep.video_download_name(cfg, VID, "Doc")
    assert response.headers["Content-Disposition"] == content_disposition(name)
    assert "authorization" not in response.headers and b"secret-must-not-escape" not in response.content
    assert store.calls == [(VID, kind, range_header)] and store.streams[0].closed


@pytest.mark.parametrize("error,status", [(StoreUnavailable("token hidden"), 503), (StoreMismatch("absent"), 404)])
@pytest.mark.parametrize("route", ["source-hd", "vertical"])
def test_store_down_or_missing(cfg, monkeypatch, error, status, route, transport):
    cfg, app, store = setup_download(cfg, monkeypatch)
    store.error = error
    response = request(app, "GET", f"/api/episodes/{VID}/{route}", transport=transport)
    assert response.status_code == status
    if status == 503:
        assert response.json() == {"detail": "3090 đang tắt"}


def test_store_disabled_keeps_hd1_links_and_refusal(cfg, monkeypatch, transport):
    cfg, app, store = setup_download(cfg, monkeypatch, enabled=False)
    h = request(app, "GET", f"/api/episodes/{VID}", transport=transport).json()["hd_video"]
    assert h["released"] and h["url"] is None and h["vertical"] is None
    for route in ("source-hd", "vertical"):
        assert request(app, "GET", f"/api/episodes/{VID}/{route}", transport=transport).status_code == 404
    assert request(app, "POST", f"/api/episodes/{VID}/vertical", transport=transport).status_code == 404
    assert not store.calls


@pytest.mark.parametrize("hd", [False, True])
def test_views_offer_store_links_and_post_does_not_queue(cfg, monkeypatch, hd, transport):
    cfg, app, store = setup_download(cfg, monkeypatch, hd=hd)
    atomic_write_json(cfg.workspace.dir / "_playlists" / "PLtest123456.json",
                      {"schema_version": 1, "playlist_id": "PLtest123456", "title": "Bộ thử", "series": "Bộ thử",
                       "entries": [{"video_id": VID, "index": 1, "title": "Kinh Vô Lượng Thọ tập 3", "episode": "3"}]})
    h = request(app, "GET", f"/api/episodes/{VID}", transport=transport).json()["hd_video"]
    assert h["vertical"]["ready"] and h["vertical"]["store"]
    assert h["vertical"]["url"] == f"/api/episodes/{VID}/vertical"
    if hd:
        assert h["url"] == f"/api/episodes/{VID}/source-hd"
    response = request(app, "POST", f"/api/episodes/{VID}/vertical", transport=transport)
    assert response.status_code == 200 and response.json()["job"] is None
    assert not app.state.runner.jobs()
    e = request(app, "GET", "/api/playlists/PLtest123456", transport=transport).json()["entries"][0]
    assert e["vertical"]["store"] and e["vertical"]["ready"] and e["vertical"]["status"] == "skip"
    if hd:
        assert e["hd_store"] and e["hd_url"] == h["url"]
    assert request(app, "GET", f"/api/episodes/{VID}/vertical", transport=transport).content == VERTICAL
    app.state.auto_vertical.set(VID, True)
    app.state.hd_ready(VID)
    assert not app.state.runner.jobs() and not app.state.auto_vertical.wanted(VID)


def test_client_open_stream_is_lazy_range_and_closes(monkeypatch):
    class Upstream(io.BytesIO):
        status = 206
        headers = {"Content-Length": "6", "Content-Range": "bytes 2-7/10", "Accept-Ranges": "bytes",
                   "Authorization": "never-return-this"}
    upstream = Upstream(b"234567")
    calls = []
    client = StoreClient("http://unused", "private-token")
    monkeypatch.setattr(client, "_open", lambda *a, **kw: (calls.append((a, kw)), upstream)[1])
    status, headers, stream = client.open_stream(VID, "vertical", "bytes=2-7")
    assert status == 206 and upstream.tell() == 0
    assert calls == [((f"/files/{VID}/vertical",), {"headers": {"Range": "bytes=2-7"}})]
    assert "Authorization" not in headers
    assert b"".join(stream) == b"234567" and upstream.closed


@pytest.mark.parametrize("disconnect", [True, False])
def test_stream_closes_on_disconnect_or_send_error(disconnect):
    stream = iter([b"first", b"second"])
    class Chunks:
        closed = False
        def __iter__(self):
            return self
        def __next__(self):
            return next(stream)
        def close(self):
            self.closed = True
    chunks = Chunks()
    async def run():
        response = _StoreResponse(chunks, status_code=200, headers={})
        sent = asyncio.Event()
        async def receive():
            await sent.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.body":
                sent.set()
                if not disconnect:
                    raise RuntimeError("client send failed")
                await asyncio.sleep(0.01)
        scope = {"type": "http", "asgi": {"spec_version": "2.0"}, "method": "GET"}
        if disconnect:
            await response(scope, receive, send)
        else:
            with pytest.raises(Exception):
                await response(scope, receive, send)
    asyncio.run(run())
    assert chunks.closed
