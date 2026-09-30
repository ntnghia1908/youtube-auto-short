"""CP8.15 P5b "tìm ảnh từ link" + P13 security. Uses a real local HTTP server (127.0.0.1) with a fake ``resolver``
that reports a public address for it (the actual TCP connection still goes to the local server: ``resolver`` only
decides whether the URL is *allowed*, never where urllib connects) — no real Internet access."""

from __future__ import annotations

import http.server
import socket
import threading

import pytest

from auto_short.post import fetch, images
from image_fixtures import make_jpeg, make_png


def _public_resolver(_host, port, **_kw):
    """Always reports a public address: for tests that only call :func:`fetch.check_url` (no real connection)."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def _private_resolver(_host, port, **_kw):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]


def _local_server_resolver(host, port, **kw):
    """For tests that make a real request to the local ``server`` fixture: ``127.0.0.1`` (the test server) is
    reported public so the request is allowed (the real, unmodified TCP connection still goes to 127.0.0.1 —
    ``resolver`` only decides whether the URL is *allowed*); any other host (e.g. a redirect target) goes through
    the real resolver, so a redirect to a private/loopback IP literal is correctly rejected without ever dialing
    it (IP literals resolve instantly, offline)."""
    if host == "127.0.0.1":
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
    return socket.getaddrinfo(host, port, **kw)


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, str, bytes]] = {}  # path -> (status, content_type, body)

    def _serve(self):
        status, ctype, body = self.routes.get(self.path, (404, "text/plain", b"not found"))
        self.send_response(status)
        if ctype:
            self.send_header("Content-Type", ctype)
        if self.path == "/redirect":
            self.send_header("Location", self.routes["__redirect_to__"])
        self.end_headers()
        if self.command == "GET":
            self.wfile.write(body)

    def do_GET(self):
        self._serve()

    def do_HEAD(self):
        self._serve()

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def base_url(server) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


# --- P13 security ------------------------------------------------------------------------------------------------


def test_check_url_rejects_bad_scheme():
    with pytest.raises(fetch.FetchError):
        fetch.check_url("ftp://example.com/a.png")


def test_check_url_rejects_private_and_loopback_addresses():
    with pytest.raises(fetch.FetchError):
        fetch.check_url("http://internal.example/x", resolver=_private_resolver)
    with pytest.raises(fetch.FetchError):
        fetch.check_url("http://127.0.0.1/x")  # real resolver: loopback


def test_check_url_accepts_public_address_via_fake_resolver():
    assert fetch.check_url("http://example.com/x", resolver=_public_resolver) == "http://example.com/x"


def test_fetch_enforces_byte_limit_even_without_content_length(server):
    _Handler.routes = {"/big": (200, "image/png", b"x" * 1000)}
    with pytest.raises(fetch.FetchError):
        fetch.fetch(base_url(server) + "/big", limit=100, resolver=_local_server_resolver)


def test_fetch_rejects_redirect_to_private_address(server):
    _Handler.routes = {"/redirect": (302, "text/plain", b""), "__redirect_to__": "http://10.1.2.3/evil"}
    with pytest.raises(fetch.FetchError):
        fetch.fetch(base_url(server) + "/redirect", limit=1000, resolver=_local_server_resolver)


def test_fetch_encodes_non_ascii_path(server):
    """A link copied from a page can contain literal Unicode (e.g. a Chinese file name); this must not crash
    urllib with UnicodeEncodeError (found running the real verification against hwadzan.com, P13/P5b)."""
    from urllib.parse import quote

    png = make_png(700, 900)
    raw_path = "/淨空老法師01.jpg"
    _Handler.routes = {quote(raw_path): (200, "image/png", png)}
    body, ctype = fetch.fetch(base_url(server) + raw_path, limit=fetch.MAX_IMAGE_BYTES,
                              resolver=_local_server_resolver)
    assert body == png and ctype == "image/png"


def test_fetch_follows_a_safe_redirect(server):
    png = make_png(700, 900)
    _Handler.routes = {"/redirect": (302, "text/plain", b""),
                       "__redirect_to__": base_url(server) + "/img.png",
                       "/img.png": (200, "image/png", png)}
    body, ctype = fetch.fetch(base_url(server) + "/redirect", limit=fetch.MAX_IMAGE_BYTES, resolver=_local_server_resolver)
    assert body == png and ctype == "image/png"


# --- P5b: image URL extraction -------------------------------------------------------------------------------------


def test_image_urls_from_img_srcset_and_og_image():
    html = """
    <html><head><meta property="og:image" content="/og.jpg"></head>
    <body>
      <img src="/a.jpg">
      <img data-src="/b.jpg" src="/placeholder.gif">
      <img srcset="/small.jpg 200w, /large.jpg 800w">
      <img src="/a.jpg">
    </body></html>
    """
    urls = fetch.image_urls(html, "https://site.example/page")
    assert urls == ["https://site.example/og.jpg", "https://site.example/a.jpg", "https://site.example/b.jpg",
                    "https://site.example/large.jpg"]


def test_largest_srcset_picks_widest():
    assert fetch._largest_srcset("a.jpg 200w, b.jpg 800w, c.jpg 400w") == "b.jpg"
    assert fetch._largest_srcset("a.jpg, b.jpg") == "b.jpg"  # no descriptor: last one


# --- P5b: end-to-end search_images (local server, no Internet) -----------------------------------------------------


def test_search_images_direct_image_link(server, tmp_path):
    png = make_png(700, 900)
    _Handler.routes = {"/photo.png": (200, "image/png", png)}
    lib, sources = tmp_path / "lib", tmp_path / "lib" / "sources.tsv"
    result = fetch.search_images(base_url(server) + "/photo.png", lib, sources, resolver=_local_server_resolver)
    assert len(result.added) == 1 and not result.duplicate and not result.skipped
    assert (lib / result.added[0]).read_bytes() == png
    assert result.added[0] in sources.read_text(encoding="utf-8")


def test_search_images_html_page_with_candidates(server, tmp_path):
    good = make_jpeg(700, 900)
    bad_small = make_png(100, 100)  # too small: skipped
    html = f'<img src="{base_url(server)}/good.jpg"><img src="{base_url(server)}/small.png">' \
          f'<img src="{base_url(server)}/missing.jpg">'
    _Handler.routes = {"/page.html": (200, "text/html", html.encode()),
                       "/good.jpg": (200, "image/jpeg", good), "/small.png": (200, "image/png", bad_small)}
    lib, sources = tmp_path / "lib", tmp_path / "lib" / "sources.tsv"
    result = fetch.search_images(base_url(server) + "/page.html", lib, sources, resolver=_local_server_resolver)
    assert result.added == [images.clean_name("good", ".jpg")]
    assert sum(result.skipped.values()) == 2  # too small + 404


def test_search_images_deduplicates_by_content(server, tmp_path):
    png = make_png(700, 900)
    _Handler.routes = {"/a.png": (200, "image/png", png), "/b.png": (200, "image/png", png)}
    lib, sources = tmp_path / "lib", tmp_path / "lib" / "sources.tsv"
    r1 = fetch.search_images(base_url(server) + "/a.png", lib, sources, resolver=_local_server_resolver)
    r2 = fetch.search_images(base_url(server) + "/b.png", lib, sources, resolver=_local_server_resolver)
    assert len(r1.added) == 1 and not r1.duplicate
    assert not r2.added and r2.duplicate == [r1.added[0]]
    assert len(images.list_images(lib)) == 1


def test_search_images_page_too_large_is_rejected(server, tmp_path):
    huge_html = ("<html>" + "x" * (fetch.MAX_PAGE_BYTES + 1000) + "</html>").encode()
    _Handler.routes = {"/huge.html": (200, "text/html", huge_html)}
    lib, sources = tmp_path / "lib", tmp_path / "lib" / "sources.tsv"
    with pytest.raises(fetch.FetchError):
        fetch.search_images(base_url(server) + "/huge.html", lib, sources, resolver=_local_server_resolver)
    assert not lib.exists() or not images.list_images(lib)
