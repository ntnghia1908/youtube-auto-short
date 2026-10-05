"""CP8.30 P5c: find images by keyword -> candidates (not yet in the library) -> HUMAN LEAD picks -> library.

Two sources behind one shape (``find(keyword, limit) -> list[Found]``):

* :class:`SiteSource` (B): known sites, matched by keyword against collection slugs / tags (``search-sources.tsv`` in
  ``image_dir`` or the built-in defaults);
* :class:`GoogleImageSource` (A): Google Custom Search JSON API (``searchType=image``), enabled only when both
  ``AUTO_SHORT_GOOGLE_CSE_KEY`` and ``AUTO_SHORT_GOOGLE_CSE_CX`` are set in the environment. The key is never
  logged, never put in an error message, never returned to the UI.

Every candidate is downloaded under the P13 rules (:mod:`auto_short.post.fetch`), checked like an upload (P5a), and
dropped when it duplicates the library or the batch (sha256, then perceptual hash). Survivors are stored outside the
library (``<image_dir>-candidates/<search_id>/``) until picked or until they expire.

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P5c.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

from ..workspace import atomic_write_bytes, atomic_write_json
from . import dhash as dhash_mod
from . import fetch, images
from .fetch import FetchError

ENV_KEY = "AUTO_SHORT_GOOGLE_CSE_KEY"
ENV_CX = "AUTO_SHORT_GOOGLE_CSE_CX"
GOOGLE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
SOURCES_FILE = "search-sources.tsv"
MAX_DOWNLOAD_ATTEMPTS = 160
SERIES_MAX_MISSES = 3
SEARCH_ID_RE = re.compile(r"^\d{14}-[0-9a-f]{6}$")
CAND_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_VARIANT_RE = re.compile(r"-p-\d+(\.[A-Za-z0-9]+)$")  # Webflow responsive variant: ``name-p-800.jpg``
_NOISE_NAME_RE = re.compile(r"banner|logo|icon|avatar|sprite", re.I)
# CMS-derived previews of another picture (``name--thumb.jpg``, ``--cover-thumb``, ``--og``): never the picture itself
_DERIVED_NAME_RE = re.compile(r"--(?:cover-)?thumb\.[A-Za-z]+$|--og\.[A-Za-z]+$", re.I)
CHROME_MIN_PAGES = 3  # an image on >= 60 % of at least this many fetched pages is site chrome (nav / banner), not a result
CHROME_SHARE = 0.6

# kind <TAB> keywords <TAB> url / template <TAB> extra... (see :func:`parse_sources`)
DEFAULT_SOURCES = """\
index\t*\thttps://www.niemphatanvui.vn/hinh-phat-chat-luong-cao\t/bo-suu-tap-hinh-phat-chat-luong-cao/\t/hinh-phat-chat-luong-cao/
page\ttinh khong hoa thuong\thttps://www.hwadzan.com/venmaster
series\ttinh khong hoa thuong ky niem 60 nam hoang phap\thttps://ph.tinhtong.vn/images/LoatAnhKyNiemChangDuong60NamHoangPhap/Image{n:03d}.jpg\t1-80
series\ttinh khong hoa thuong amtb\thttps://www.amtb-m.org.my/wp-content/uploads/2024/01/淨空法師_{n:02d}.jpg\t1-40
series\ttinh khong hoa thuong amtb\thttps://www.amtb-m.org.my/wp-content/uploads/2024/01/淨空法師_{n:02d}-scaled.jpg\t1-40
series\ttinh khong hoa thuong sach phat\thttps://sachphat.net/wp-content/hinh-anh/kho-nho/20-HT-Tinh-Khong/HT-Tinh-Khong-{n:02d}.jpg\t1-40
"""


class SearchError(Exception):
    """The whole search cannot run (nothing matched, every source failed)."""


class GoogleError(Exception):
    """Google API problem; the message is safe to show (never contains the key)."""


# --- keyword matching ----------------------------------------------------------------------------------------------

def tokens(text: str) -> list[str]:
    """Lower-case words without diacritics (``đ`` -> ``d``): "Tây Phương Tam Thánh" -> tay phuong tam thanh."""
    text = unicodedata.normalize("NFKD", (text or "").replace("đ", "d").replace("Đ", "D"))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.findall(r"[a-z0-9]+", text)


def matches(query: list[str], haystack: list[str]) -> bool:
    """Every query word is in ``haystack`` (as a word)."""
    return bool(query) and set(query) <= set(haystack)


# --- found image / sources -----------------------------------------------------------------------------------------

@dataclass
class Found:
    url: str
    origin: str  # "site:<host>" | "google"
    page: str | None = None
    width: int | None = None  # only when the source already says it (Google)
    height: int | None = None


@dataclass
class SourceEntry:
    kind: str  # index | page | series
    keywords: list[str]
    url: str
    extra: list[str]


def parse_sources(text: str) -> list[SourceEntry]:
    out = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3 or parts[0] not in ("index", "page", "series"):
            continue
        out.append(SourceEntry(parts[0], tokens(parts[1]), parts[2].strip(), [p.strip() for p in parts[3:]]))
    return out


def load_sources(image_dir: Path) -> list[SourceEntry]:
    """``<image_dir>/search-sources.tsv`` when present, else the built-in defaults."""
    try:
        text = (image_dir / SOURCES_FILE).read_text(encoding="utf-8")
    except OSError:
        text = DEFAULT_SOURCES
    return parse_sources(text)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.hrefs.append(v)


def page_links(html_text: str, base_url: str) -> list[str]:
    parser = _LinkParser()
    try:
        parser.feed(html_text)
    except Exception:  # tolerant, like fetch.image_urls
        pass
    seen, out = set(), []
    for raw in parser.hrefs:
        try:
            url = urljoin(base_url, raw.strip()).split("#")[0]
        except ValueError:
            continue
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def usable_image_url(url: str) -> str | None:
    """JPEG/PNG file URL, with a Webflow responsive variant (``-p-800``) mapped back to its original; else None."""
    path = urlparse(url).path
    if Path(path).suffix.lower() not in images.EXTS:
        return None
    return _VARIANT_RE.sub(r"\1", url) if _VARIANT_RE.search(path) else url


class SiteSource:
    """B: the known sites. Few, polite requests: at most ``max_pages`` HTML pages and ``max_series`` series files."""

    def __init__(self, entries: list[SourceEntry], *, opener=None, resolver=None, max_pages: int = 12,
                 progress: Callable[[str], None] | None = None):
        self.entries, self.opener, self.resolver = entries, opener, resolver
        self.max_pages = max_pages
        self.progress = progress or (lambda _msg: None)
        self.notes: list[str] = []
        self.dropped: dict[str, int] = {}
        self._pages = 0
        self._seen_on: dict[str, set[str]] = {}
        self._derived: set[str] = set()

    def _get_page(self, url: str) -> str | None:
        if self._pages >= self.max_pages:
            return None
        self._pages += 1
        self.progress(f"trang {self._pages}")
        try:
            body, _ct = fetch.fetch(url, limit=fetch.MAX_PAGE_BYTES, opener=self.opener, resolver=self.resolver)
        except FetchError as exc:
            self.notes.append(f"không mở được trang: {exc}")
            return None
        return body.decode("utf-8", errors="replace")

    def _page_images(self, url: str, html_text: str) -> list[Found]:
        out = []
        for u in fetch.image_urls(html_text, url, limit=300):
            good = usable_image_url(u)
            if not good:
                continue
            if _DERIVED_NAME_RE.search(urlparse(good).path):
                if good not in self._derived:
                    self._derived.add(good)
                    _skip(self.dropped, "ảnh xem trước / bìa của trang khác")
                continue
            self._seen_on.setdefault(good, set()).add(url)
            out.append(Found(good, f"site:{urlparse(url).netloc}", page=url))
        return out

    def _drop_chrome(self, found: list[Found]) -> list[Found]:
        """Images repeated on most fetched pages are the sites' own nav / banner / logo: not results."""
        if self._pages < CHROME_MIN_PAGES:
            return found
        out, counted = [], set()
        for f in found:
            if f.page and len(self._seen_on.get(f.url, ())) >= max(CHROME_MIN_PAGES, CHROME_SHARE * self._pages):
                if f.url not in counted:
                    counted.add(f.url)
                    _skip(self.dropped, "ảnh chung của trang (banner / logo)")
            else:
                out.append(f)
        return out

    def find(self, keyword: str, limit: int) -> list[Found]:
        query = tokens(keyword)
        found: list[Found] = []
        for entry in self.entries:
            if len(found) >= limit * 3:
                break
            if entry.kind == "index":
                found += self._from_index(entry, query)
            elif entry.kind == "page" and matches(query, entry.keywords):
                text = self._get_page(entry.url)
                found += self._page_images(entry.url, text) if text else []
            elif entry.kind == "series" and matches(query, entry.keywords):
                found += self._from_series(entry, limit)
        seen, out = set(), []
        for f in self._drop_chrome(found):
            if f.url not in seen:
                seen.add(f.url)
                out.append(f)
        return out

    def _from_index(self, entry: SourceEntry, query: list[str]) -> list[Found]:
        coll_prefix = entry.extra[0] if entry.extra else ""
        sub_prefix = entry.extra[1] if len(entry.extra) > 1 else ""
        text = self._get_page(entry.url)
        if text is None:
            return []
        for u in fetch.image_urls(text, entry.url, limit=300):  # the listing's own images only count as "chrome" evidence
            if (good := usable_image_url(u)) and not _DERIVED_NAME_RE.search(urlparse(good).path):
                self._seen_on.setdefault(good, set()).add(entry.url)
        colls = []
        for link in page_links(text, entry.url):
            path = urlparse(link).path
            if coll_prefix and path.startswith(coll_prefix) and matches(query, tokens(path[len(coll_prefix):])):
                colls.append(link)
        if not colls:
            self.notes.append(f"{urlparse(entry.url).netloc}: không có bộ sưu tập khớp từ khóa")
        found: list[Found] = []
        for coll in colls[:3]:
            ctext = self._get_page(coll)
            if ctext is None:
                break
            found += self._page_images(coll, ctext)
            slug = urlparse(coll).path.rstrip("/").rsplit("/", 1)[-1]
            for link in page_links(ctext, coll):
                path = urlparse(link).path
                if sub_prefix and path.startswith(sub_prefix + slug) and link != coll:
                    stext = self._get_page(link)
                    if stext is None:
                        break
                    found += self._page_images(link, stext)
        return found

    def _from_series(self, entry: SourceEntry, limit: int) -> list[Found]:
        lo, hi = 1, 60
        if entry.extra and re.fullmatch(r"\d+-\d+", entry.extra[0]):
            lo, hi = (int(x) for x in entry.extra[0].split("-"))
        out, misses = [], 0
        for n in range(lo, hi + 1):
            if len(out) >= limit or misses >= SERIES_MAX_MISSES:
                break
            try:
                url = entry.url.format(n=n)
            except (KeyError, ValueError, IndexError):
                break
            try:
                fetch.fetch(url, limit=1024, opener=self.opener, resolver=self.resolver)  # probe: first KB only
            except FetchError as exc:
                if "byte" in str(exc):  # larger than the probe limit = it exists
                    out.append(Found(url, f"site:{urlparse(url).netloc}"))
                    misses = 0
                else:
                    misses += 1
                continue
            out.append(Found(url, f"site:{urlparse(url).netloc}"))
            misses = 0
        return out


# --- Google (A) ----------------------------------------------------------------------------------------------------

class GoogleImageSource:
    """A: Custom Search JSON API, image search. Counts every API call in ``state_path`` per local day."""

    def __init__(self, key: str, cx: str, *, state_path: Path, daily_limit: int = 100, opener=None,
                 resolver=None, today: Callable[[], str] | None = None):
        self._key, self._cx = key, cx
        self.state_path, self.daily_limit = state_path, daily_limit
        self.opener, self.resolver = opener, resolver
        self._today = today or (lambda: datetime.now().strftime("%Y-%m-%d"))

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, **kw) -> "GoogleImageSource | None":
        env = os.environ if environ is None else environ
        key, cx = (env.get(ENV_KEY) or "").strip(), (env.get(ENV_CX) or "").strip()
        return cls(key, cx, **kw) if key and cx else None

    def used_today(self) -> int:
        try:
            doc = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        return int(doc.get("count", 0)) if doc.get("date") == self._today() else 0

    def _count_call(self) -> None:
        n = self.used_today() + 1
        atomic_write_json(self.state_path, {"date": self._today(), "count": n})

    def status(self) -> dict:
        return {"enabled": True, "used_today": self.used_today(), "daily_limit": self.daily_limit}

    def find(self, keyword: str, limit: int) -> list[Found]:
        out: list[Found] = []
        for start in range(1, min(limit, 30) + 1, 10):
            if self.used_today() >= self.daily_limit:
                raise GoogleError(f"đã dùng hết {self.daily_limit} lượt tìm Google hôm nay")
            self._count_call()
            items = self._call(keyword, start)
            if not items:
                break
            for it in items:
                link = it.get("link")
                meta = it.get("image") if isinstance(it.get("image"), dict) else {}
                if isinstance(link, str) and link:
                    out.append(Found(link, "google", page=meta.get("contextLink"), width=meta.get("width"),
                                     height=meta.get("height")))
            if len(items) < 10:
                break
        return out

    def _call(self, keyword: str, start: int) -> list[dict]:
        params = {"key": self._key, "cx": self._cx, "q": keyword, "searchType": "image", "num": 10, "start": start,
                  "safe": "active"}
        try:
            fetch.check_url(GOOGLE_ENDPOINT, resolver=self.resolver)
        except FetchError as exc:
            raise GoogleError(f"Google: {exc}") from None
        build = self.opener or (lambda: fetch._default_opener(self.resolver))
        req = urllib.request.Request(f"{GOOGLE_ENDPOINT}?{urlencode(params)}", headers={"User-Agent": fetch.USER_AGENT})
        try:
            with build().open(req, timeout=fetch.REQUEST_TIMEOUT) as resp:
                body = resp.read(fetch.MAX_PAGE_BYTES)
        except urllib.error.HTTPError as exc:  # never echo the URL (it carries the key)
            detail = ""
            try:
                detail = json.loads(exc.read(20000).decode("utf-8", "replace")).get("error", {}).get("message", "")
            except Exception:
                pass
            raise GoogleError(f"Google trả HTTP {exc.code}" + (f": {detail}" if detail else "")) from None
        except Exception as exc:
            raise GoogleError(f"không gọi được Google ({type(exc).__name__})") from None
        try:
            items = json.loads(body.decode("utf-8", "replace")).get("items") or []
        except ValueError:
            raise GoogleError("Google trả dữ liệu không đọc được") from None
        return [i for i in items if isinstance(i, dict)]


# --- library index (sha256 + dHash, cached) ------------------------------------------------------------------------

def cache_dir(image_dir: Path) -> Path:
    """Where candidates + caches live: a sibling of the library, never inside it."""
    return image_dir.parent / f"{image_dir.name}-candidates"


@dataclass
class LibraryEntry:
    name: str
    sha256: str
    dhash: int | None


def library_index(image_dir: Path, cdir: Path, hasher: Callable[[bytes], int | None]) -> list[LibraryEntry]:
    """sha256 + dHash of every library image; recomputed only for files whose size / mtime changed."""
    cache_path = cdir / "library-hashes.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    out, fresh, dirty = [], {}, False
    for info in images.list_images(image_dir):
        path = image_dir / info.name
        try:
            st = path.stat()
        except OSError:
            continue
        rec = cache.get(info.name)
        if not (isinstance(rec, dict) and rec.get("size") == st.st_size and rec.get("mtime_ns") == st.st_mtime_ns):
            data = path.read_bytes()
            h = hasher(data)
            rec = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": images.sha256_bytes(data),
                   "dhash": None if h is None else f"{h:016x}"}
            dirty = True
        fresh[info.name] = rec
        out.append(LibraryEntry(info.name, rec["sha256"], int(rec["dhash"], 16) if rec.get("dhash") else None))
    if dirty or set(fresh) != set(cache):
        try:
            atomic_write_json(cache_path, fresh)
        except OSError:
            pass
    return out


# --- search --------------------------------------------------------------------------------------------------------

@dataclass
class SearchOutcome:
    search_id: str
    keyword: str
    candidates: list[dict] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    sources: dict[str, int] = field(default_factory=dict)  # origin -> candidates found (before filtering)

    def to_dict(self) -> dict:
        return {"search_id": self.search_id, "keyword": self.keyword, "candidates": self.candidates,
                "skipped": self.skipped, "notes": self.notes, "sources": self.sources}


def _skip(skipped: dict[str, int], reason: str) -> None:
    skipped[reason] = skipped.get(reason, 0) + 1


def classify_image_error(exc: images.ImageError) -> str:
    msg = str(exc)
    if msg.startswith("ảnh nhỏ hơn"):
        return f"nhỏ hơn {images.MIN_SHORT_EDGE} px"
    if msg.startswith("ảnh lớn hơn"):
        return f"lớn hơn {images.MAX_BYTES // (1024 * 1024)} MB"
    return "không phải ảnh JPEG/PNG"


def suspicion(url: str, width: int, height: int) -> str | None:
    """Cheap "may be text / banner" label (never a reason to drop): extreme aspect ratio or a banner-ish file name."""
    if _NOISE_NAME_RE.search(Path(urlparse(url).path).name):
        return "nghi banner / logo (tên file)"
    ratio = width / height
    if ratio >= 2.6 or ratio <= 1 / 2.6:
        return "nghi banner (tỉ lệ khung)"
    return None


def new_search_id(now: datetime | None = None) -> str:
    return f"{(now or datetime.now()).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"


def purge_old(cdir: Path, ttl_hours: float, *, now: float | None = None) -> int:
    """Delete candidate folders older than ``ttl_hours`` (by mtime). Returns how many were removed."""
    if not cdir.is_dir():
        return 0
    limit, removed = (now if now is not None else time.time()) - ttl_hours * 3600, 0
    for d in cdir.iterdir():
        if d.is_dir() and SEARCH_ID_RE.match(d.name) and d.stat().st_mtime < limit:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed


def run_search(keyword: str, image_dir: Path, *, max_candidates: int = 60, max_pages: int = 12,
               google: GoogleImageSource | None = None, google_state_note: str | None = None,
               opener=None, resolver=None, hasher: Callable[[bytes], int | None] = dhash_mod.dhash,
               thumber: Callable[[bytes], bytes | None] = dhash_mod.thumbnail,
               progress: Callable[[str], None] | None = None, ttl_hours: float = 6.0,
               sources: list[SourceEntry] | None = None) -> SearchOutcome:
    """Find, download, filter. Raises :class:`SearchError` when the keyword is empty."""
    progress = progress or (lambda _m: None)
    if not tokens(keyword):
        raise SearchError("nhập từ khóa")
    cdir = cache_dir(image_dir)
    purge_old(cdir, ttl_hours)
    out = SearchOutcome(new_search_id(), keyword.strip())
    sdir = cdir / out.search_id
    progress("tìm trang")
    site = SiteSource(sources if sources is not None else load_sources(image_dir), opener=opener, resolver=resolver,
                      max_pages=max_pages, progress=progress)
    found = site.find(keyword, max_candidates)
    out.notes += site.notes
    for reason, n in site.dropped.items():
        out.skipped[reason] = out.skipped.get(reason, 0) + n
    out.sources["site"] = len(found)
    if google is None:
        out.notes.append(google_state_note or "Google: chưa cấu hình khóa → chỉ dùng các trang đã biết")
    else:
        progress("Google")
        try:
            g = google.find(keyword, max_candidates)
            out.sources["google"] = len(g)
            found += g
        except GoogleError as exc:
            out.notes.append(f"Google: {exc}")
    if not found:
        out.notes.append("không tìm thấy ảnh nào cho từ khóa này")
    library = library_index(image_dir, cdir, hasher)
    lib_sha = {e.sha256: e.name for e in library}
    lib_hash = [(e.name, e.dhash) for e in library if e.dhash is not None]
    kept: dict[str, dict] = {}  # sha -> candidate
    kept_data: dict[str, bytes] = {}
    seen_urls: set[str] = set()
    attempts = 0
    for n, f in enumerate(found, 1):
        if f.url in seen_urls:
            continue
        seen_urls.add(f.url)
        if len(kept) >= max_candidates or attempts >= MAX_DOWNLOAD_ATTEMPTS:
            break
        if f.width and f.height and min(f.width, f.height) < images.MIN_SHORT_EDGE:
            _skip(out.skipped, f"nhỏ hơn {images.MIN_SHORT_EDGE} px")
            continue
        attempts += 1
        progress(f"tải {n}/{len(found)}")
        try:
            data, _ct = fetch.fetch(f.url, limit=fetch.MAX_IMAGE_BYTES, opener=opener, resolver=resolver)
            ext, w, h = images.validate(data)
        except FetchError as exc:
            _skip(out.skipped, "lớn hơn 15 MB" if "byte" in str(exc) else "không tải được")
            continue
        except images.ImageError as exc:
            _skip(out.skipped, classify_image_error(exc))
            continue
        sha = images.sha256_bytes(data)
        if sha in lib_sha:
            _skip(out.skipped, "trùng ảnh có trong thư viện")
            continue
        if sha in kept:
            _skip(out.skipped, "trùng trong lô")
            continue
        dh = hasher(data)
        if dh is not None:
            hit = next((nm for nm, lh in lib_hash if dhash_mod.distance(dh, lh) <= dhash_mod.NEAR_DUPLICATE_BITS), None)
            if hit is not None:
                _skip(out.skipped, "gần giống ảnh trong thư viện")
                continue
            twin = next((s for s, c in kept.items() if c["_dhash"] is not None
                         and dhash_mod.distance(dh, c["_dhash"]) <= dhash_mod.NEAR_DUPLICATE_BITS), None)
            if twin is not None:
                _skip(out.skipped, "gần giống ảnh khác trong lô")
                if w * h > kept[twin]["width"] * kept[twin]["height"]:  # keep the larger one
                    del kept[twin], kept_data[twin]
                else:
                    continue
        cand = {"id": sha[:16], "ext": ext, "url": f.url, "page": f.page, "origin": f.origin, "width": w, "height": h,
                "bytes": len(data), "sha256": sha, "flag": suspicion(f.url, w, h), "_dhash": dh}
        kept[sha] = cand
        kept_data[sha] = data
    if kept:
        sdir.mkdir(parents=True, exist_ok=True)
        for sha, cand in kept.items():
            atomic_write_bytes(sdir / f"{cand['id']}{cand['ext']}", kept_data[sha])
            thumb = thumber(kept_data[sha])
            cand["thumb"] = thumb is not None
            if thumb:
                atomic_write_bytes(sdir / f"{cand['id']}.thumb.jpg", thumb)
        out.candidates = [{k: v for k, v in c.items() if k != "_dhash"} for c in kept.values()]
        atomic_write_json(sdir / "meta.json", out.to_dict())
    progress("xong")
    return out


def load_search(image_dir: Path, search_id: str) -> dict | None:
    if not SEARCH_ID_RE.match(search_id or ""):
        return None
    try:
        doc = json.loads((cache_dir(image_dir) / search_id / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def candidate_file(image_dir: Path, search_id: str, cand_id: str, *, thumb: bool) -> Path | None:
    """Path of a stored candidate (or its thumbnail); None for unknown / malformed ids (no path traversal)."""
    if not SEARCH_ID_RE.match(search_id or "") or not CAND_ID_RE.match(cand_id or ""):
        return None
    doc = load_search(image_dir, search_id)
    cand = next((c for c in (doc or {}).get("candidates", []) if c.get("id") == cand_id), None)
    if cand is None:
        return None
    sdir = cache_dir(image_dir) / search_id
    path = sdir / (f"{cand_id}.thumb.jpg" if thumb and cand.get("thumb") else f"{cand_id}{cand['ext']}")
    return path if path.is_file() else None


_NUM_NAME_RE = re.compile(r"^(\d+)\.[A-Za-z]+$")


def next_name(image_dir: Path) -> str:
    """Next numbered library name: ``130.jpg`` after ``129.jpg`` (zero-padded like the existing ones, min 2)."""
    nums = [(int(m.group(1)), len(m.group(1))) for i in images.list_images(image_dir)
            if (m := _NUM_NAME_RE.match(i.name))]
    top = max((n for n, _w in nums), default=0)
    width = max([w for _n, w in nums] + [2])
    return f"{top + 1:0{width}d}"


def add_candidates(image_dir: Path, search_id: str, ids: list[str]) -> dict:
    """Move the picked candidates into the library under the next numbers; ``sources.tsv`` gets ``name<TAB>url``.
    Returns ``{"added": [name], "duplicate": [name], "missing": [id]}``; a candidate already in the library (sha256) is
    reported as ``duplicate`` and not added again, so pressing the button twice adds nothing twice."""
    doc = load_search(image_dir, search_id)
    result: dict = {"added": [], "duplicate": [], "missing": []}
    if doc is None:
        result["missing"] = list(ids)
        return result
    by_id = {c["id"]: c for c in doc.get("candidates", []) if isinstance(c, dict) and "id" in c}
    for cid in ids:
        cand = by_id.get(cid)
        path = candidate_file(image_dir, search_id, cid, thumb=False) if cand else None
        if cand is None or path is None:
            result["missing"].append(cid)
            continue
        name, duplicate = images.save_image(image_dir, path.read_bytes(), original_name=next_name(image_dir) + cand["ext"])
        if duplicate:
            result["duplicate"].append(name)
        else:
            result["added"].append(name)
            url = re.sub(r"\s+", "", cand.get("url") or "")
            fetch._append_source(image_dir / "sources.tsv", name, url)
    return result


def google_from_config(config, *, environ: Mapping[str, str] | None = None, **kw) -> GoogleImageSource | None:
    cfg = config.post
    return GoogleImageSource.from_env(environ, state_path=cache_dir(cfg.image_dir) / "google-usage.json",
                                      daily_limit=cfg.google_daily_limit, **kw)


def search_for_config(keyword: str, config, *, progress: Callable[[str], None] | None = None,
                      environ: Mapping[str, str] | None = None, opener=None, resolver=None) -> SearchOutcome:
    """The web job's search: settings from ``[post]``, Google only when the environment has the key + engine id."""
    cfg = config.post
    return run_search(keyword, cfg.image_dir, max_candidates=cfg.search_max_candidates, max_pages=cfg.search_max_pages,
                      google=google_from_config(config, environ=environ, opener=opener, resolver=resolver),
                      opener=opener, resolver=resolver, progress=progress, ttl_hours=cfg.candidate_ttl_hours)


def search_status(config, *, environ: Mapping[str, str] | None = None) -> dict:
    """What the UI may know: whether Google is on and today's usage. Never the key / engine id."""
    g = google_from_config(config, environ=environ)
    return {"google": g.status() if g is not None else {"enabled": False}}
