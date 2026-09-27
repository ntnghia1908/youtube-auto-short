"""CL1 C5: Chinese track listing (URL query) and selection (AC2)."""

from learning_helpers import track

from auto_short.learning.tracks import (YtDlpChineseFetcher, is_chinese_related, no_track_message, pick_chinese_track,
                                        tracks_from_info)


def _pick(*tracks):
    sel = pick_chinese_track(tracks)
    return None if sel is None else (sel.track.key, sel.track.auto)


def test_manual_zh_hans_before_zh():
    assert _pick(track("zh"), track("zh-Hans")) == ("zh-Hans", False)


def test_manual_zh_cn_before_zh_hant():
    assert _pick(track("zh-Hant"), track("zh-CN")) == ("zh-CN", False)


def test_manual_full_lang_order():
    order = ["zh-Hans", "zh-CN", "zh-SG", "zh", "zh-Hant", "zh-TW", "zh-HK", "zh-MO", "zh-yue"]
    tracks = [track(k) for k in reversed(order)]
    picked = []
    while tracks:
        key, _ = _pick(*tracks)
        picked.append(key)
        tracks = [t for t in tracks if t.key != key]
    assert picked == order  # listed order, then other zh-* alphabetically


def test_manual_three_zh_like_qcq():
    # qcqQbMj4s-w: manual zh, zh-CN, zh-Hant -> zh-CN
    assert _pick(track("zh"), track("zh-CN"), track("zh-Hant")) == ("zh-CN", False)


def test_manual_key_with_id_suffix_uses_url_lang():
    sel = pick_chinese_track([track("zh-Hans-abc123", lang="zh-Hans"), track("zh")])
    assert (sel.track.key, sel.track.lang) == ("zh-Hans-abc123", "zh-Hans")
    # same lang: the plain key first
    assert _pick(track("zh-Hans-abc123", lang="zh-Hans"), track("zh-Hans")) == ("zh-Hans", False)


def test_manual_key_with_suffix_but_other_lang_is_not_chinese():
    assert _pick(track("zh-e4D66FZAwWw", lang="vi")) is None


def test_auto_asr_chinese_without_manual():
    assert _pick(track("zh", auto=True, kind="asr"), track("en")) == ("zh", True)


def test_auto_orig_first():
    assert _pick(track("zh-Hans", auto=True, lang="zh-Hans", kind="asr"),
                 track("zh-orig", auto=True, lang="zh", kind="asr")) == ("zh-orig", True)


def test_auto_translation_never_accepted():
    # rbjfCfFq3Dk: auto zh-Hans / zh-Hant = lang=vi&kind=asr&tlang=zh-*
    tracks = [track("zh-Hans", auto=True, lang="vi", kind="asr", tlang="zh-Hans"),
              track("zh-Hant", auto=True, lang="vi", kind="asr", tlang="zh-Hant"),
              track("vi-orig", auto=True, lang="vi", kind="asr")]
    assert _pick(*tracks) is None
    # even a zh source translated to zh-Hans is a translation
    assert _pick(track("zh-Hans", auto=True, lang="zh", kind="asr", tlang="zh-Hans")) is None
    assert _pick(track("zh-Hans", lang="zh", tlang="zh-Hans")) is None  # manual + tlang


def test_auto_without_asr_kind_not_accepted():
    assert _pick(track("zh", auto=True, kind=None)) is None


def test_track_without_json3_skipped():
    # gnCXffOg7T8: auto zh-Hans without json3
    assert _pick(track("zh-Hans", json3=False), track("zh-Hant")) == ("zh-Hant", False)
    assert _pick(track("zh", auto=True, kind="asr", json3=False)) is None


def test_manual_before_auto():
    assert _pick(track("zh-orig", auto=True, lang="zh", kind="asr"), track("zh-Hant")) == ("zh-Hant", False)


def test_no_track_message_lists_what_was_seen():
    tracks = [track("zh-Hans", auto=True, lang="vi", kind="asr", tlang="zh-Hans"),
              track("zh-Hant", auto=True, lang="vi", kind="asr", tlang="zh-Hant"),
              track("zh", json3=False), track("vi")]
    msg = no_track_message(tracks)
    assert msg.startswith("no Chinese subtitle track (manual zh*, auto zh ASR); found: ")
    assert "machine-translated auto zh-Hans (lang=vi, tlang=zh-Hans)" in msg
    assert "machine-translated auto zh-Hant" in msg and "manual zh (no json3)" in msg
    assert "manual vi" not in msg  # only zh-related tracks are summarized
    assert no_track_message([track("en")]).endswith("found: no zh track")


def _fmt(ext, query):
    return {"ext": ext, "url": f"https://www.youtube.com/api/timedtext?v=x&{query}&fmt={ext}"}


INFO = {
    "id": "vid00000001", "title": "T", "channel": None, "uploader": "Up", "duration": 414,
    "webpage_url": "https://www.youtube.com/watch?v=vid00000001",
    "subtitles": {
        "zh-Hans-abc123": [_fmt("json3", "lang=zh-Hans&name=x"), _fmt("vtt", "lang=zh-Hans")],
        "zh": [_fmt("vtt", "lang=zh")],  # no json3
        "live_chat": [{"ext": "json", "url": None}],
    },
    "automatic_captions": {
        "zh-Hans": [_fmt("json3", "lang=vi&kind=asr&tlang=zh-Hans")],
        "vi-orig": [_fmt("json3", "lang=vi&kind=asr")],
        "zh-orig": [_fmt("json3", "kind=asr")],  # no lang in the URL -> the key
    },
}


def test_tracks_from_info_reads_url_query():
    tracks = {(t.key, t.auto): t for t in tracks_from_info(INFO)}
    t = tracks[("zh-Hans-abc123", False)]
    assert (t.lang, t.kind, t.tlang, t.json3) == ("zh-Hans", None, None, True)
    t = tracks[("zh", False)]
    assert (t.lang, t.json3) == ("zh", False)
    t = tracks[("zh-Hans", True)]
    assert (t.lang, t.kind, t.tlang) == ("vi", "asr", "zh-Hans")
    assert tracks[("zh-orig", True)].lang == "zh-orig"
    assert tracks[("live_chat", False)].json3 is False
    assert [t.key for t in tracks_from_info(INFO) if is_chinese_related(t)] == [
        "zh-Hans-abc123", "zh", "zh-Hans", "zh-orig"]


def test_fetcher_listing_uses_cached_info_without_network():
    f = YtDlpChineseFetcher()
    f._info["u"] = INFO  # the parent's extract_info cache: no yt-dlp call
    listing = f.listing("u")
    assert listing.video == {"id": "vid00000001", "title": "T", "channel": "Up", "duration": 414,
                             "webpage_url": "https://www.youtube.com/watch?v=vid00000001"}
    sel = pick_chinese_track(listing.tracks)
    assert (sel.track.key, sel.track.auto) == ("zh-Hans-abc123", False)
    assert "manual zh-Hans" in sel.reason
