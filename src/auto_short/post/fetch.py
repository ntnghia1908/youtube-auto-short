"""P5b "tìm ảnh từ link" + P13 security: a URL is either an image (one candidate) or an HTML page (candidate image
URLs from it). Every candidate is downloaded and checked like an upload (P5a) and goes straight into the library.

P13: only after login (checked by the caller / web route); only ``http``/``https``; the host's resolved
address(es) must all be public (no loopback / private / link-link-local / multicast), checked again on every
redirect (at most 3); 20 s timeout per request; body capped at the given limit even without ``Content-Length``; no
cookies are sent (a fresh :mod:`urllib.request` call, never the web session); HTML is parsed for URLs only, never
served back.

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P5b, P13.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse, urlsplit, urlunsplit

from . import images
from .images import ImageError

REQUEST_TIMEOUT = 20.0
MAX_REDIRECTS = 3
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = images.MAX_BYTES  # 15 MB
MAX_CANDIDATES = 40
ALLOWED_SCHEMES = ("http", "https")
USER_AGENT = "auto-short-post-image-fetch/1.0 (+local tool, no cookies)"

Opener = Callable[[], "urllib.request.OpenerDirector"]
Resolver = Callable[..., list[tuple]]  # like socket.getaddrinfo


class FetchError(Exception):
    """The URL is disallowed (P13), unreachable, or the response exceeds a security limit."""


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
                or addr.is_reserved or addr.is_unspecified)


def check_url(url: str, *, resolver: Resolver | None = None) -> str:
    """P13: scheme http/https and every address the host resolves to is public. Returns ``url`` unchanged; raises
    :class:`FetchError`. ``resolver`` (default :func:`socket.getaddrinfo`) is a test seam only: it decides whether
    the URL's host is *allowed*, it is never used for the actual connection (:mod:`urllib.request` resolves and
    connects to the real host itself) — tests can point a URL at a local HTTP server while a fake resolver reports
    a public address for it, without weakening the real default."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise FetchError(f"chỉ nhận link http/https: {url!r}")
    if not parsed.hostname:
        raise FetchError(f"link không hợp lệ: {url!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    resolve = resolver or socket.getaddrinfo
    try:
        infos = resolve(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise FetchError(f"không phân giải được {parsed.hostname}: {exc}") from exc
    if not infos or not all(_is_public(info[4][0]) for info in infos):
        raise FetchError(f"địa chỉ của {parsed.hostname} không được phép (mạng riêng / loopback / multicast)")
    return url


def _redirect_handler(resolver: Resolver | None) -> type:
    class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
        max_redirections = MAX_REDIRECTS

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            check_url(newurl, resolver=resolver)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return _SafeRedirectHandler


def _default_opener(resolver: Resolver | None = None) -> "urllib.request.OpenerDirector":
    return urllib.request.build_opener(_redirect_handler(resolver))


def _read_limited(resp, limit: int) -> bytes:
    data = resp.read(limit + 1)
    if len(data) > limit:
        raise FetchError(f"vượt quá {limit} byte")
    return data


def _iri_to_uri(url: str) -> str:
    """Percent-encode any non-ASCII / unsafe character of the path, query and fragment (a link copied from a
    page can contain literal Unicode, e.g. a Chinese file name); ``urllib.request`` otherwise raises
    ``UnicodeEncodeError`` when it tries to send the request line. Already-percent-encoded sequences are left
    alone (``%`` is in the safe set)."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%"), quote(parts.query, safe="=&%"),
                       quote(parts.fragment, safe="%")))


def fetch(url: str, *, limit: int, opener: Opener | None = None, resolver: Resolver | None = None
         ) -> tuple[bytes, str]:
    """GET ``url`` (P13: scheme/host checked, redirects re-checked, no cookies), body capped at ``limit`` bytes
    even without ``Content-Length``. Returns ``(body, content_type)``; raises :class:`FetchError`."""
    check_url(url, resolver=resolver)
    build = opener or (lambda: _default_opener(resolver))
    req = urllib.request.Request(_iri_to_uri(url), headers={"User-Agent": USER_AGENT})
    try:
        with build().open(req, timeout=REQUEST_TIMEOUT) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = _read_limited(resp, limit)
    except FetchError:
        raise
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} khi tải {url}") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise FetchError(f"quá thời gian ({REQUEST_TIMEOUT:g} s) khi tải {url}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"không tải được {url}: {exc.reason}") from exc
    except OSError as exc:
        raise FetchError(f"lỗi khi tải {url}: {exc}") from exc
    return body, content_type


def _content_kind(content_type: str) -> str:
    return content_type.split(";")[0].strip().lower()


def is_html(content_type: str) -> bool:
    return _content_kind(content_type) in ("text/html", "application/xhtml+xml")


def is_image_content_type(content_type: str) -> bool:
    return _content_kind(content_type) in ("image/jpeg", "image/jpg", "image/png")


def _largest_srcset(value: str) -> str | None:
    """The URL with the largest width descriptor (``foo.jpg 800w``); the last one when none has a descriptor."""
    best_url, best_w, last = None, -1, None
    for part in value.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url = bits[0]
        last = url
        w = 0
        if len(bits) > 1 and bits[1].endswith("w") and bits[1][:-1].isdigit():
            w = int(bits[1][:-1])
        if w >= best_w:
            best_url, best_w = url, w
    return best_url or last


class _ImgParser(HTMLParser):
    """Best-effort, tolerant of malformed HTML: never raises, collects raw (unresolved) candidate URLs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = {k: v for k, v in attrs if v}
        if tag == "img":
            for key in ("data-src", "src"):
                if d.get(key):
                    self.urls.append(d[key])
                    break
            if d.get("srcset"):
                best = _largest_srcset(d["srcset"])
                if best:
                    self.urls.append(best)
        elif tag == "meta" and d.get("content") and (d.get("property") == "og:image" or d.get("name") == "og:image"):
            self.urls.append(d["content"])

    def error(self, message: str) -> None:  # legacy hook on some parser states; never fatal
        pass


def image_urls(html_text: str, base_url: str, *, limit: int = MAX_CANDIDATES) -> list[str]:
    """P5b: candidate image URLs from an HTML page (``<img src/data-src/srcset>``, ``<meta property="og:image">``),
    resolved against ``base_url``, de-duplicated, at most ``limit``."""
    parser = _ImgParser()
    try:
        parser.feed(html_text)
    except Exception:  # tolerant: best-effort extraction from possibly malformed HTML (never fatal)
        pass
    out: list[str] = []
    seen: set[str] = set()
    for raw in parser.urls:
        try:
            url = urljoin(base_url, raw.strip())
        except ValueError:
            continue
        if url and url not in seen:
            seen.add(url)
            out.append(url)
        if len(out) >= limit:
            break
    return out


@dataclass
class SearchResult:
    added: list[str] = field(default_factory=list)
    duplicate: list[str] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)


def _append_source(path: Path, name: str, url: str) -> None:
    """P5b: ``<image_dir>/sources.tsv`` (``name<TAB>url``), appended."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{name}\t{url}\n")


def _skip(skipped: dict[str, int], reason: str) -> None:
    skipped[reason] = skipped.get(reason, 0) + 1


def search_images(url: str, image_dir: Path, sources_path: Path, *, opener: Opener | None = None,
                  resolver: Resolver | None = None) -> SearchResult:
    """P5b: fetch ``url``; an image -> one candidate, an HTML page (≤ 5 MB) -> its candidate image URLs. Every
    candidate downloaded and checked like an upload (P5a); images that pass go straight into the library +
    ``sources.tsv``. Raises :class:`FetchError` only for the initial fetch of ``url`` itself; a candidate that
    fails is counted in ``skipped`` and the search continues."""
    body, content_type = fetch(url, limit=MAX_IMAGE_BYTES, opener=opener, resolver=resolver)
    first_body: dict[str, bytes] = {}
    if is_image_content_type(content_type) or (not is_html(content_type) and images.sniff(body) is not None):
        candidates = [url]
        first_body[url] = body
    else:
        if len(body) > MAX_PAGE_BYTES:
            raise FetchError(f"trang lớn hơn {MAX_PAGE_BYTES // (1024 * 1024)} MB")
        text = body.decode("utf-8", errors="replace")
        candidates = image_urls(text, url)
    result = SearchResult()
    for cand in candidates:
        try:
            data = first_body.get(cand)
            if data is None:
                data, _ct = fetch(cand, limit=MAX_IMAGE_BYTES, opener=opener, resolver=resolver)
            name, duplicate = images.save_image(image_dir, data, original_name=Path(urlparse(cand).path).name)
        except FetchError as exc:
            _skip(result.skipped, str(exc) if "byte" in str(exc) or "MB" in str(exc) else "không tải được")
            continue
        except ImageError as exc:
            _skip(result.skipped, str(exc))
            continue
        if duplicate:
            result.duplicate.append(name)
        else:
            result.added.append(name)
            _append_source(sources_path, name, cand)
    return result
