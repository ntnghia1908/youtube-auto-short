"""YouTube caption access (T2) through ``yt-dlp`` (no video download)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# Track preference: manual vi -> auto vi-orig -> auto vi.
TRACK_PREFERENCE = (("vi", False), ("vi-orig", True), ("vi", True))


class CaptionFetchError(Exception):
    """yt-dlp could not list or download captions (network, YouTube...)."""


@dataclass(frozen=True)
class CaptionTracks:
    manual: frozenset[str]  # languages with a manual subtitle offering json3
    auto: frozenset[str]  # languages with an automatic caption offering json3


class CaptionFetcher(Protocol):
    def tracks(self, url: str) -> CaptionTracks: ...

    def download(self, url: str, lang: str, auto: bool) -> bytes: ...


def pick_track(tracks: CaptionTracks) -> tuple[str, bool] | None:
    for lang, auto in TRACK_PREFERENCE:
        if lang in (tracks.auto if auto else tracks.manual):
            return lang, auto
    return None


class YtDlpCaptionFetcher:
    """Real fetcher: one ``extract_info(download=False)`` per URL, then the json3 URL."""

    def __init__(self, js_runtimes: tuple[str, ...] = ("node",)):
        self.js_runtimes = js_runtimes
        self._info: dict[str, dict] = {}

    def _ydl_opts(self) -> dict:
        return {
            "skip_download": True,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "js_runtimes": {name: {} for name in self.js_runtimes},
        }

    def _extract(self, url: str) -> dict:
        if url not in self._info:
            import yt_dlp

            try:
                with yt_dlp.YoutubeDL(self._ydl_opts()) as ydl:
                    self._info[url] = ydl.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError as exc:
                raise CaptionFetchError(f"yt-dlp cannot read {url}: {exc}") from exc
        return self._info[url]

    @staticmethod
    def _json3(entries: dict, lang: str) -> dict | None:
        return next((f for f in entries.get(lang) or [] if f.get("ext") == "json3" and f.get("url")), None)

    def tracks(self, url: str) -> CaptionTracks:
        info = self._extract(url)
        manual, auto = info.get("subtitles") or {}, info.get("automatic_captions") or {}
        return CaptionTracks(
            manual=frozenset(lang for lang in manual if self._json3(manual, lang)),
            auto=frozenset(lang for lang in auto if self._json3(auto, lang)),
        )

    def download(self, url: str, lang: str, auto: bool) -> bytes:
        import yt_dlp

        info = self._extract(url)
        fmt = self._json3(info.get("automatic_captions" if auto else "subtitles") or {}, lang)
        if fmt is None:
            raise CaptionFetchError(f"no json3 caption track {lang!r} (auto={auto})")
        try:
            with yt_dlp.YoutubeDL(self._ydl_opts()) as ydl:
                return ydl.urlopen(fmt["url"]).read()
        except Exception as exc:  # network errors come in many types
            raise CaptionFetchError(f"caption download failed ({lang}, auto={auto}): {exc}") from exc
