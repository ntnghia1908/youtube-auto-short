"""CP8.19: community post text taken from the edited lecture text (the "văn bản gốc") of ``ph.tinhtong.vn``.

A bộ kinh may carry a link to one page of that site (``doc_url`` in ``<workspace>/_playlists/<id>.json``). The link of
episode N is derived from it (D1); the page (+ the gzip continuation it points to) is downloaded with the P13 rules of
:mod:`auto_short.post.fetch`, parsed into paragraphs (D2) and cached as ``work/<id>/doc.json`` with a ``match`` score
against the episode's transcript (D3). A Short's source text is then aligned into that text (D4) and the matching span,
widened to whole sentences, is the post (D5).

Pure functions (link template, parse, align, expand) are kept apart from IO (lookup, fetch, cache). This module never
imports ``auto_short.web``: the bộ kinh files are read directly like :mod:`auto_short.titling.playlist`.

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P15; docs/tasks/CP8.19-post-doc-source.md.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from ..selection.logic import normalize_word
from ..titling.playlist import PLAYLISTS_DIR
from ..workspace import atomic_write_json
from . import fetch

DOC_HOST = "ph.tinhtong.vn"
DOC_NAME = "doc.json"
SCHEMA_VERSION = 1
MAX_BYTES = fetch.MAX_PAGE_BYTES  # page, gzip body and its decompressed size: 5 MB each
MIN_MATCH = 0.5  # D3: transcript tokens found in the text / transcript tokens
MIN_RATIO = 0.6  # D4: Short source vs aligned region
MIN_BLOCK = 4  # D4: smallest matching block used
MAX_GAP = 30  # D4: text tokens between two blocks of the same cluster
MAX_EXPAND = 60  # D5: tokens added at each end

_LINK_RE = re.compile(r"^https://ph\.tinhtong\.vn/Home/([A-Za-z0-9]+)\?d=\1_(\d+)\.html$")
_NUM_RE = re.compile(r"_(\d+)(\.html)$")
_GZ_RE = re.compile(r"(https?://[A-Za-z0-9.-]+)?(/html-end/[\w./-]+\.gz\.z(?:\?[\w=&.%-]*)?)")
_CLOSERS = "”’\"')）】»]"
_END_MARKS = (".", "?", "!", "…")
_KT_SUFFIX = ".kt"

Loader = Callable[..., "DocText | None"]


class DocError(Exception):
    """The link is not an allowed one (D1), or the text cannot be downloaded / read (D2)."""


# --- D1: link ---------------------------------------------------------------------------------------------------

def normalize_url(value: object) -> str:
    """The pasted link, stripped, when it is ``https://ph.tinhtong.vn/Home/<Code>?d=<Code>_<digits>.html``."""
    if not isinstance(value, str):
        raise DocError("link văn bản gốc phải là chuỗi")
    url = value.strip()
    if not _LINK_RE.match(url):
        raise DocError("chỉ nhận link dạng https://ph.tinhtong.vn/Home/<Mã>?d=<Mã>_<số>.html")
    return url


MAX_VIDEOS_PER_PAGE = 10  # CP8.24 P1


def normalize_videos_per_page(value: object) -> int:
    """CP8.24 P1: videos per text page, an integer 1..10 (``bool`` / text / other numbers are refused)."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_VIDEOS_PER_PAGE:
        raise DocError(f"số video mỗi trang phải là số nguyên từ 1 đến {MAX_VIDEOS_PER_PAGE}")
    return value


def stored_videos_per_page(value: object) -> int:
    """The stored ``doc_videos_per_page`` of a bộ kinh; absent or invalid -> 1 (one video per page, D1)."""
    try:
        return normalize_videos_per_page(value)
    except DocError:
        return 1


def url_for_episode(url: str, episode: object, videos_per_page: int = 1) -> str | None:
    """The link of episode ``episode`` (digits) keeping the zero padding width of ``url`` (``_001`` -> ``_007``,
    ``_1`` -> ``_7``, ``_07`` -> ``_12``); with ``videos_per_page`` k > 1 (CP8.24 P2) the page is ``ceil(N / k)``.
    None when ``episode`` is not a number."""
    text = str(episode).strip() if episode is not None else ""
    m = _NUM_RE.search(url)
    if m is None or not text.isdigit():
        return None
    page = -(-int(text) // max(stored_videos_per_page(videos_per_page), 1))
    return url[:m.start()] + "_" + str(page).zfill(len(m.group(1))) + m.group(2)


def base_episode_id(episode_id: str) -> str:
    return episode_id[:-len(_KT_SUFFIX)] if episode_id.endswith(_KT_SUFFIX) else episode_id


def lookup(workspace_dir: str | Path, episode_id: str) -> tuple[str, str] | None:
    """``(episode link, episode number)`` of a video from the first stored bộ kinh (by playlist id, like CP8.8 H4)
    that has a valid ``doc_url`` and lists the video (a ``<id>.kt`` khai thị episode uses its base video); None when
    there is none or the entry has no episode number."""
    vid = base_episode_id(episode_id)
    root = Path(workspace_dir) / PLAYLISTS_DIR
    if not root.is_dir():
        return None
    for path in sorted(root.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or doc.get("playlist_id") != path.stem \
                    or not isinstance(doc.get("entries"), list):
                continue
            base = normalize_url(doc.get("doc_url"))
        except (OSError, ValueError, DocError):
            continue
        for entry in doc["entries"]:
            if isinstance(entry, dict) and entry.get("video_id") == vid:
                number = entry.get("episode")
                url = url_for_episode(base, number, stored_videos_per_page(doc.get("doc_videos_per_page")))
                return (url, str(number).strip()) if url else None
    return None


# --- D2: download + parse -----------------------------------------------------------------------------------------

class _ParaParser(HTMLParser):
    """``<p>`` paragraphs of ``<div id="bodytext">`` (or of the whole fragment when ``whole``); ``text-center``
    paragraphs and paragraphs whose every word is inside ``<b>`` (headings) are dropped."""

    def __init__(self, whole: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.whole = whole
        self.depth = 0
        self.skip = 0
        self.paragraphs: list[str] = []
        self._cur: dict | None = None

    @property
    def _inside(self) -> bool:
        return self.whole or self.depth > 0

    def _finish(self) -> None:
        cur, self._cur = self._cur, None
        if cur is None or cur["center"] or cur["plain"] == 0:
            return
        text = " ".join(unicodedata.normalize("NFC", "".join(cur["text"])).split())
        if text:
            self.paragraphs.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        if tag == "div":
            if self.depth > 0:
                self.depth += 1
            elif d.get("id") == "bodytext":
                self.depth = 1
        elif tag in ("script", "style"):
            self.skip += 1
        elif tag == "p" and self._inside:
            self._finish()
            classes = (d.get("class") or "").split()
            self._cur = {"center": "text-center" in classes, "text": [], "plain": 0, "bold": 0}
        elif self._cur is not None:
            if tag in ("b", "strong"):
                self._cur["bold"] += 1
            elif tag == "br":
                self._cur["text"].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.depth > 0:
            self.depth -= 1
            if self.depth == 0:
                self._finish()
        elif tag in ("script", "style") and self.skip:
            self.skip -= 1
        elif tag == "p":
            self._finish()
        elif tag in ("b", "strong") and self._cur is not None and self._cur["bold"] > 0:
            self._cur["bold"] -= 1

    def handle_data(self, data: str) -> None:
        if self._cur is not None and not self.skip:
            self._cur["text"].append(data)
            if self._cur["bold"] == 0 and data.strip():
                self._cur["plain"] += 1

    def error(self, message: str) -> None:  # legacy hook; never fatal
        pass


def parse_paragraphs(html_text: str, *, whole: bool = False) -> list[str]:
    """D2: the body paragraphs of an HTML page (``whole`` False) or of an HTML fragment (the gzip part)."""
    parser = _ParaParser(whole)
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # tolerant of malformed HTML
        pass
    parser._finish()
    return parser.paragraphs


def gunzip_bounded(data: bytes, limit: int | None = None) -> bytes:
    """gzip decompression capped at ``limit`` bytes of output (more -> :class:`DocError`)."""
    limit = MAX_BYTES if limit is None else limit
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = d.decompress(data, limit + 1)
    except zlib.error as exc:
        raise DocError(f"không giải nén được phần còn lại của văn bản: {exc}") from exc
    if len(out) > limit or d.unconsumed_tail:
        raise DocError(f"phần còn lại của văn bản lớn hơn {limit // (1024 * 1024)} MB sau khi giải nén")
    if not d.eof:
        raise DocError("phần còn lại của văn bản bị cắt cụt")
    return out


def _host_redirect_handler(resolver: fetch.Resolver | None) -> type:
    class _DocRedirectHandler(urllib.request.HTTPRedirectHandler):
        max_redirections = fetch.MAX_REDIRECTS

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            fetch.check_url(newurl, resolver=resolver)
            if urlparse(newurl).hostname != DOC_HOST:
                raise fetch.FetchError(f"chuyển hướng sang {urlparse(newurl).hostname}: chỉ nhận {DOC_HOST}")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return _DocRedirectHandler


def _get(url: str, opener: fetch.Opener | None, resolver: fetch.Resolver | None) -> bytes:
    if urlparse(url).hostname != DOC_HOST:
        raise DocError(f"chỉ tải từ {DOC_HOST}: {url!r}")
    build = opener or (lambda: urllib.request.build_opener(_host_redirect_handler(resolver)))
    try:
        body, _ctype = fetch.fetch(url, limit=MAX_BYTES, opener=build, resolver=resolver)
    except fetch.FetchError as exc:
        raise DocError(str(exc)) from exc
    return body


def fetch_paragraphs(url: str, *, opener: fetch.Opener | None = None,
                     resolver: fetch.Resolver | None = None) -> list[str]:
    """D2: paragraphs of the page ``url`` followed by those of its gzip continuation (when it links one)."""
    page = _get(url, opener, resolver).decode("utf-8", errors="replace")
    paragraphs = parse_paragraphs(page)
    m = _GZ_RE.search(page)
    if m is not None:
        if m.group(1) and urlparse(m.group(1)).hostname != DOC_HOST:
            raise DocError(f"phần còn lại của văn bản ở host khác {urlparse(m.group(1)).hostname}")
        rest = gunzip_bounded(_get(urljoin(url, m.group(2)), opener, resolver))
        paragraphs += parse_paragraphs(rest.decode("utf-8", errors="replace"), whole=True)
    if not paragraphs:
        raise DocError("không đọc được đoạn văn nào từ trang")
    return paragraphs


# --- text model + D3 match -----------------------------------------------------------------------------------------

def words_of(text: str) -> list[str]:
    """Normalized, non-empty word tokens of ``text`` (:func:`normalize_word`)."""
    return [w for w in (normalize_word(t) for t in text.split()) if w]


@dataclass(frozen=True)
class DocText:
    url: str
    paragraphs: list[str]
    match: float | None
    tokens: list[str] = field(repr=False, default_factory=list)  # raw whitespace tokens, paragraphs concatenated
    para_of: list[int] = field(repr=False, default_factory=list)  # paragraph index of each raw token
    words: list[str] = field(repr=False, default_factory=list)  # normalized non-empty tokens
    word_pos: list[int] = field(repr=False, default_factory=list)  # raw token index of each word

    @property
    def usable(self) -> bool:
        return self.match is not None and self.match >= MIN_MATCH


def build_text(url: str, paragraphs: list[str], match: float | None) -> DocText:
    tokens: list[str] = []
    para_of: list[int] = []
    for n, p in enumerate(paragraphs):
        for tok in p.split():
            tokens.append(tok)
            para_of.append(n)
    words, pos = [], []
    for i, tok in enumerate(tokens):
        w = normalize_word(tok)
        if w:
            words.append(w)
            pos.append(i)
    return DocText(url, list(paragraphs), match, tokens, para_of, words, pos)


def match_ratio(transcript_words: list[str], doc_words: list[str]) -> float:
    """D3: transcript tokens inside matching blocks / transcript tokens."""
    if not transcript_words:
        return 0.0
    sm = SequenceMatcher(None, transcript_words, doc_words, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / len(transcript_words)


def transcript_words(segments: list[dict]) -> list[str]:
    out: list[str] = []
    for s in segments:
        if isinstance(s, dict) and s.get("kind", "speech") == "speech" and isinstance(s.get("text"), str):
            out += words_of(s["text"])
    return out


# --- D3: cache + prepare -------------------------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_cache(path: Path, url: str) -> DocText | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION or doc.get("url") != url:
        return None
    paragraphs, match = doc.get("paragraphs"), doc.get("match")
    if not isinstance(paragraphs, list) or not paragraphs or not all(isinstance(p, str) for p in paragraphs) \
            or isinstance(match, bool) or not isinstance(match, (int, float)):
        return None
    return build_text(url, paragraphs, float(match))


def prepare(episode_id: str, workspace_dir: str | Path, segments: list[dict], *,
            opener: fetch.Opener | None = None, resolver: fetch.Resolver | None = None,
            now: str | None = None) -> DocText | None:
    """D3: the text of the episode with its ``match`` (cache ``work/<id>/doc.json`` reused when its ``url`` is the
    current link); None when the episode has no link. A download failure raises :class:`DocError` (nothing cached)."""
    found = lookup(workspace_dir, episode_id)
    if found is None:
        return None
    url, _number = found
    path = Path(workspace_dir) / episode_id / DOC_NAME
    cached = read_cache(path, url)
    if cached is not None:
        return cached
    paragraphs = fetch_paragraphs(url, opener=opener, resolver=resolver)
    text = build_text(url, paragraphs, None)
    match = round(match_ratio(transcript_words(segments), text.words), 4)
    atomic_write_json(path, {"schema_version": SCHEMA_VERSION, "url": url, "fetched_at": now or _now(),
                             "paragraphs": paragraphs, "match": match})
    return build_text(url, paragraphs, match)


# --- D4: alignment ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Alignment:
    start: int  # word index in DocText.words (inclusive)
    end: int  # exclusive
    ratio: float


def align(src_words: list[str], doc_words: list[str]) -> Alignment | None:
    """D4: where in ``doc_words`` a Short's words are said. Blocks of at least :data:`MIN_BLOCK` equal words are
    chained (text gap <= :data:`MAX_GAP`); the densest chain gives the region, widened by the unmatched words at each
    end of the Short. None when no chain exists or the similarity is below :data:`MIN_RATIO`."""
    if len(src_words) < MIN_BLOCK or not doc_words:
        return None
    sm = SequenceMatcher(None, src_words, doc_words, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size >= MIN_BLOCK]
    if not blocks:
        return None
    clusters: list[list] = [[blocks[0]]]
    for b in blocks[1:]:
        prev = clusters[-1][-1]
        if b.b - (prev.b + prev.size) <= MAX_GAP:
            clusters[-1].append(b)
        else:
            clusters.append([b])
    best = max(clusters, key=lambda c: sum(b.size for b in c))
    first, last = best[0], best[-1]
    start = max(first.b - first.a, 0)
    end = min(last.b + last.size + (len(src_words) - (last.a + last.size)), len(doc_words))
    if end <= start:
        return None
    ratio = SequenceMatcher(None, src_words, doc_words[start:end], autojunk=False).ratio()
    if ratio < MIN_RATIO:
        return None
    return Alignment(start, end, round(ratio, 4))


# --- D5: sentences ---------------------------------------------------------------------------------------------------

def _closer_only(tok: str) -> bool:
    return bool(tok) and all(c in _CLOSERS for c in tok)


def ends_sentence(text: DocText, k: int) -> bool:
    """Token ``k`` ends a sentence: ``. ? ! …`` (closing quotes / brackets after it allowed; a token made only of
    closers takes the answer of the token before it in the same paragraph)."""
    tok = text.tokens[k]
    if _closer_only(tok):
        return k > 0 and text.para_of[k - 1] == text.para_of[k] and ends_sentence(text, k - 1)
    return tok.rstrip(_CLOSERS).endswith(_END_MARKS)


@dataclass(frozen=True)
class DocPost:
    paragraphs: list[str]
    ratio: float
    span: tuple[int, int]  # aligned word range [start, end) in DocText.words
    head: int  # tokens added before the aligned start to reach the sentence start
    tail: int  # tokens added after the aligned end to reach the sentence end
    head_ellipsis: bool
    tail_ellipsis: bool


def _clean_quotes(s: str) -> str:
    return re.sub(r"\s+”", "”", re.sub(r"“\s+", "“", s))


def expand(text: DocText, start: int, end: int) -> tuple[list[str], int, int, bool, bool]:
    """D5: the paragraphs of words ``[start, end)`` widened to whole sentences (at most :data:`MAX_EXPAND` tokens at
    each end; beyond that the end stays at the aligned word and gets ``…``). Returns
    ``(paragraphs, head, tail, head_ellipsis, tail_ellipsis)``."""
    n = len(text.tokens)
    first, last = text.word_pos[start], text.word_pos[end - 1]
    j = first
    while j > 0 and text.para_of[j - 1] == text.para_of[j] and not ends_sentence(text, j - 1):
        j -= 1
    head_ellipsis = first - j > MAX_EXPAND
    if head_ellipsis:
        j = first
    k = last
    while k + 1 < n and text.para_of[k + 1] == text.para_of[k] and not ends_sentence(text, k):
        k += 1
    tail_ellipsis = k - last > MAX_EXPAND
    if tail_ellipsis:
        k = last
    else:
        while k + 1 < n and text.para_of[k + 1] == text.para_of[k] and _closer_only(text.tokens[k + 1]):
            k += 1
    pieces: list[str] = []
    cur, cur_para = [], text.para_of[j]
    for i in range(j, k + 1):
        if text.para_of[i] != cur_para:
            pieces.append(" ".join(cur))
            cur, cur_para = [], text.para_of[i]
        cur.append(text.tokens[i])
    pieces.append(" ".join(cur))
    paragraphs = [_clean_quotes(p) for p in pieces]
    if head_ellipsis:
        paragraphs[0] = "…" + paragraphs[0]
    else:
        s = paragraphs[0]
        for idx, ch in enumerate(s):
            if ch.isalpha():
                paragraphs[0] = s[:idx] + ch.upper() + s[idx + 1:]
                break
    if tail_ellipsis:
        paragraphs[-1] += "…"
    return paragraphs, first - j, k - last, head_ellipsis, tail_ellipsis


def compose(text: DocText, source_text: str) -> DocPost | None:
    """D4 + D5: the post of one Short from its P2 source text (uncorrected), or None when it cannot be aligned."""
    al = align(words_of(source_text), text.words)
    if al is None:
        return None
    paragraphs, head, tail, he, te = expand(text, al.start, al.end)
    return DocPost(paragraphs, al.ratio, (al.start, al.end), head, tail, he, te)
