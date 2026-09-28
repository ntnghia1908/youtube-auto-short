"""CP8.11: series / episode from the video title (title_patterns) and the "Tên bộ kinh" fallback."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short import config as config_mod
from auto_short.config import DEFAULT_TITLE_PATTERN, DEFAULT_TITLE_PATTERNS, Config, ConfigError, \
    TitlingHeaderConfig, WorkspaceConfig
from auto_short.hashing import config_hash
from auto_short.titling import TitlingError, run_titling
from auto_short.titling.logic import match_title, resolve_header
from auto_short.titling.playlist import normalize_series, playlist_header, stored_series
from auto_short.titling.stage import used_config
from selection_helpers import SYN_ANALYSIS
from titling_helpers import FakeClient, make_titling_episode
from transcript_helpers import manifest_of

H = TitlingHeaderConfig()
FIXTURE = Path(__file__).parent / "fixtures" / "cp811_titles.json"
TT = "Tập 11/128: Giảng \"Thái Thượng Cảm Ứng Thiên\" | Tịnh Không Lão Pháp sư chủ giảng"
EID = "rbjfCfFq3Dk"


# --- AC1 new pattern ----------------------------------------------------------------------------------

def test_new_title_form():
    h = resolve_header(H, TT)
    assert h == {"lines": ["HT.Tịnh Không", "Thái Thượng Cảm Ứng Thiên (tập 11)"],
                 "fields": {"speaker": "HT.Tịnh Không", "series": "Thái Thượng Cảm Ứng Thiên", "episode": "11"},
                 "sources": {"speaker": "config", "series": "metadata", "episode": "metadata"}}


@pytest.mark.parametrize("title", [
    "Tập 11/128: Giảng “Thái Thượng Cảm Ứng Thiên” | Tịnh Không",
    "Tập 11 / 128 : Giảng \"Thái Thượng Cảm Ứng Thiên\"",
    "Tập 11: Giảng \"Thái Thượng Cảm Ứng Thiên\" | x",
    "Tập 11/128: \"Thái Thượng Cảm Ứng Thiên\"",
    "Tập  11/128:Giảng  \"Thái Thượng Cảm Ứng Thiên \" | x",
    "Tập 11/128: Giảng “Thái Thượng  Cảm Ứng Thiên\"",
])
def test_new_title_variants(title):
    h = resolve_header(H, title)
    assert h["lines"] == ["HT.Tịnh Không", "Thái Thượng Cảm Ứng Thiên (tập 11)"]
    assert h["sources"]["series"] == h["sources"]["episode"] == "metadata"


def test_new_title_nfd_input():
    import unicodedata
    assert resolve_header(H, unicodedata.normalize("NFD", TT))["fields"]["series"] == "Thái Thượng Cảm Ứng Thiên"


# --- AC2 real titles of both saved bộ kinh --------------------------------------------------------------

def test_real_titles_of_both_playlists():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))["titles"]
    assert len(data) == 208
    old = [t for t in data if t["main"] is not None]
    new = [t for t in data if t["main"] is None]
    assert len(old) == 80 and len(new) == 128
    for t in old:  # matched by the CP6 pattern on main: identical result
        assert resolve_header(H, t["title"]) == t["main"], t["title"]
    for t in new:  # failed on main: now recognized, episode = the number in the title (= playlist index here)
        h = resolve_header(H, t["title"])
        assert h["lines"] == ["HT.Tịnh Không", f"Thái Thượng Cảm Ứng Thiên (tập {t['index']})"], t["title"]
        assert h["sources"] == {"speaker": "config", "series": "metadata", "episode": "metadata"}


def test_old_pattern_is_first_and_unchanged():
    assert DEFAULT_TITLE_PATTERNS[0] == DEFAULT_TITLE_PATTERN == \
        r"^(?:Phật Thuyết\s+)?(?P<series>.+?)\s+tập\s+(?P<episode>\d+)\b"
    assert H.title_patterns == DEFAULT_TITLE_PATTERNS and len(DEFAULT_TITLE_PATTERNS) == 2


# --- AC4 config -----------------------------------------------------------------------------------------

def _hdr(header):
    return config_mod.from_dict({"titling": {"header": header}}).titling.header


def test_config_title_patterns_and_legacy_key():
    assert _hdr({"title_patterns": ["a(?P<series>b)", "c"]}).title_patterns == ("a(?P<series>b)", "c")
    assert _hdr({"title_patterns": []}).title_patterns == ()
    assert _hdr({"title_pattern": "x(?P<episode>\\d+)"}).title_patterns == ("x(?P<episode>\\d+)",)
    assert _hdr({"title_pattern": ""}).title_patterns == ()
    assert _hdr({}).title_patterns == DEFAULT_TITLE_PATTERNS
    # legacy key: the old single pattern runs as before
    h = resolve_header(_hdr({"title_pattern": DEFAULT_TITLE_PATTERN}), "Kinh A tập 3 - x")
    assert h["lines"] == ["HT.Tịnh Không", "Kinh A (tập 3)"]
    with pytest.raises(TitlingError, match="title_patterns"):
        resolve_header(_hdr({"title_pattern": DEFAULT_TITLE_PATTERN}), TT)
    for off in ({"title_pattern": ""}, {"title_patterns": []}):
        with pytest.raises(TitlingError, match="--series"):
            resolve_header(_hdr(off), "Kinh A tập 3")


@pytest.mark.parametrize("header, needle", [
    ({"title_patterns": ["a"], "title_pattern": "a"}, "not both"),
    ({"title_patterns": "a"}, "title_patterns must be a list"),
    ({"title_patterns": ["a", 1]}, r"title_patterns\[1\]"),
    ({"title_patterns": ["a", ""]}, r"title_patterns\[1\]"),
    ({"title_patterns": ["a", "b", "("]}, r"title_patterns\[2\] is not a valid regex"),
    ({"title_pattern": 1}, "title_pattern must be a string"),
    ({"title_pattern": "("}, "title_pattern is not a valid regex"),
])
def test_config_title_patterns_invalid(header, needle):
    with pytest.raises(ConfigError, match=needle):
        config_mod.from_dict({"titling": {"header": header}})


def test_first_matching_pattern_wins_without_group_mixing():
    hcfg = replace(H, title_patterns=(r"^(?P<series>Kinh \w+)", r"tập (?P<episode>\d+)", r"^(?P<series>.+) tập"))
    # the first pattern matches (series only): no episode from the second one -> unresolved
    assert match_title(hcfg.title_patterns, "Kinh A tập 3").re.pattern == r"^(?P<series>Kinh \w+)"
    with pytest.raises(TitlingError, match="--episode"):
        resolve_header(hcfg, "Kinh A tập 3")
    # neither: the second pattern gives the episode
    h = resolve_header(hcfg, "Bài giảng tập 4", {"series": "S"})
    assert h["fields"]["episode"] == "4" and h["sources"]["series"] == "cli"
    assert match_title(hcfg.title_patterns, None) is None and match_title((), "x") is None


# --- AC5 no pattern matches ---------------------------------------------------------------------------

def test_unmatched_title_message():
    with pytest.raises(TitlingError) as exc:
        resolve_header(H, "Một bài giảng không theo mẫu")
    msg = str(exc.value)
    assert msg.startswith("header field(s) not resolved: series (pass --series or set [titling.header] series), "
                          "episode (pass --episode or set [titling.header] episode); metadata title ")
    assert "does not match [titling.header] title_patterns" in msg and "Tên bộ kinh" in msg


# --- AC6 W10 L1 entry episode ------------------------------------------------------------------------------

def test_playlist_entry_episode_new_form(tmp_path):
    from auto_short.web.playlists import build_document, episode_number, title_series
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path))
    assert episode_number(TT, cfg) == "11"
    assert episode_number("Phật Thuyết Thập Thiện Nghiệp Đạo Kinh tập 7 - x", cfg) == "7"
    assert title_series(TT, cfg) == "Thái Thượng Cảm Ứng Thiên"
    info = {"id": "PLx", "title": "T", "entries": [{"id": "c_6QuBGFzY4", "title": TT, "duration": 1.0}]}
    assert build_document(info, "PLxxxxxxxxxxxx", cfg)["entries"][0]["episode"] == "11"
    off = replace(cfg, titling=replace(cfg.titling, header=replace(cfg.titling.header, title_patterns=())))
    assert episode_number(TT, off) is None


# --- AC7 "Tên bộ kinh" fallback -------------------------------------------------------------------------------

def _write_playlist(root: Path, pid: str, entries, series=None, **extra) -> Path:
    d = Path(root) / "_playlists"
    d.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "playlist_id": pid, "title": pid, "url": "u", "fetched_at": "x", "entries": entries}
    if series is not None:
        doc["series"] = series
    doc.update(extra)
    (d / f"{pid}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return d / f"{pid}.json"


def _entry(vid, index, episode=None, title="Bài lạ"):
    return {"index": index, "video_id": vid, "title": title, "duration": 1.0, "episode": episode, "available": True}


def test_normalize_series():
    assert normalize_series("  Kinh   Vô  Lượng Thọ ") == "Kinh Vô Lượng Thọ"
    assert normalize_series("a" * 100) == "a" * 100
    for bad in ("", "   ", "a" * 101, None, 5, ["x"]):
        with pytest.raises(ValueError):
            normalize_series(bad)
    assert stored_series({"series": " X "}) == "X"
    assert stored_series({}) is None and stored_series({"series": 1}) is None and stored_series({"series": ""}) is None


def test_playlist_header_lookup(tmp_path):
    assert playlist_header(tmp_path, "vid00000001") is None  # no _playlists dir
    _write_playlist(tmp_path, "PLcccccccccccc", [_entry("vid00000001", 5, "9")], series="Kinh C")
    _write_playlist(tmp_path, "PLbbbbbbbbbbbb", [_entry("vid00000001", 3)], series="Kinh B")
    _write_playlist(tmp_path, "PLaaaaaaaaaaaa", [_entry("vid00000001", 1, "1")])  # no name: skipped
    (tmp_path / "_playlists" / "PLbroken000000.json").write_text("{", encoding="utf-8")
    _write_playlist(tmp_path, "PLdddddddddddd", [_entry("vid00000002", 2, "7")], series="Kinh D")
    assert playlist_header(tmp_path, "vid00000001") == ("Kinh B", "3")  # smallest id with a name; index fallback
    assert playlist_header(tmp_path, "vid00000002") == ("Kinh D", "7")  # entry.episode
    assert playlist_header(tmp_path, "vid00000009") is None and playlist_header(tmp_path, None) is None


def test_resolve_header_playlist_fallback_order():
    calls = []

    def lookup():
        calls.append(1)
        return ("Kinh  Riêng", "4")

    h = resolve_header(H, "Bài lạ", playlist=lookup)
    assert h["lines"] == ["HT.Tịnh Không", "Kinh Riêng (tập 4)"]
    assert h["sources"] == {"speaker": "config", "series": "playlist", "episode": "playlist"}
    # CLI > config > playlist, per field
    h = resolve_header(replace(H, series="Kinh Cfg"), "Bài lạ", {"episode": "8"}, playlist=lookup)
    assert h["fields"] == {"speaker": "HT.Tịnh Không", "series": "Kinh Cfg", "episode": "8"}
    assert h["sources"] == {"speaker": "config", "series": "config", "episode": "cli"}
    # a title a pattern matches never reads the bộ kinh (not even called)
    calls.clear()
    for title in (TT, "Phật Thuyết Thập Thiện Nghiệp Đạo Kinh tập 9 - x"):
        assert resolve_header(H, title, playlist=lookup) == resolve_header(H, title)
    assert calls == []
    # a pattern matched without an episode group: no fallback for the missing field
    hcfg = replace(H, title_patterns=(r"^(?P<series>Bài) lạ",))
    with pytest.raises(TitlingError, match="--episode"):
        resolve_header(hcfg, "Bài lạ", playlist=lookup)
    # not set -> failed like AC5
    with pytest.raises(TitlingError, match="Tên bộ kinh"):
        resolve_header(H, "Bài lạ", playlist=lambda: None)


def _meta(ws, **kw):
    p = ws.dir / "metadata.json"
    meta = json.loads(p.read_text(encoding="utf-8"))
    meta.update(kw)
    p.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def test_stage_uses_playlist_name_and_rehashes(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), analysis=SYN_ANALYSIS)
    root = cfg.workspace.dir
    ws = make_titling_episode(root, title="Bài giảng đặc biệt")
    _meta(ws, youtube={"id": EID, "title": "Bài giảng đặc biệt"})
    fake = FakeClient()
    with pytest.raises(TitlingError, match="Tên bộ kinh"):
        run_titling(EID, cfg, client=fake)
    entry = manifest_of(ws)["stages"]["titling"]
    assert entry["status"] == "failed" and "title_patterns" in entry["error"] and fake.calls == []

    path = _write_playlist(root, "PLbbbbbbbbbbbb", [_entry(EID, 12)], series="Kinh Hoa Nghiêm")
    assert run_titling(EID, cfg, client=fake).ran
    doc = json.loads((ws.dir / "titles.json").read_text(encoding="utf-8"))
    assert doc["header"]["lines"] == ["HT.Tịnh Không", "Kinh Hoa Nghiêm (tập 12)"]
    assert doc["header"]["sources"] == {"speaker": "config", "series": "playlist", "episode": "playlist"}
    assert not run_titling(EID, cfg, client=fake).ran  # same name -> skip
    # renaming the bộ kinh re-runs titling (G9, like a CLI flag)
    path.write_text(path.read_text(encoding="utf-8").replace("Kinh Hoa Nghiêm", "Kinh Pháp Hoa"), encoding="utf-8")
    assert run_titling(EID, cfg, client=fake).ran
    # CLI still wins per field
    assert run_titling(EID, cfg, episode="99", client=fake).ran
    assert json.loads((ws.dir / "titles.json").read_text())["header"]["lines"][1] == "Kinh Pháp Hoa (tập 99)"
    # removing the name -> failed again
    path.unlink()
    with pytest.raises(TitlingError):
        run_titling(EID, cfg, client=fake)


def test_stage_khaithi_uses_base_video_id(tmp_path):
    """A .kt episode has its own id but metadata.youtube.id is the base video: the bộ kinh entry is found."""
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), analysis=SYN_ANALYSIS)
    ws = make_titling_episode(cfg.workspace.dir, title="Bài lạ")
    _meta(ws, youtube={"id": "baseVideo01"})
    _write_playlist(cfg.workspace.dir, "PLbbbbbbbbbbbb", [_entry("baseVideo01", 2, "5")], series="Kinh K")
    run_titling(EID, cfg, client=FakeClient())
    assert json.loads((ws.dir / "titles.json").read_text())["header"]["lines"][1] == "Kinh K (tập 5)"


def test_stage_pattern_match_ignores_playlist_name(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), analysis=SYN_ANALYSIS)
    ws = make_titling_episode(cfg.workspace.dir)  # Thập Thiện title (pattern 1)
    _meta(ws, youtube={"id": EID})
    fake = FakeClient()
    assert run_titling(EID, cfg, client=fake).ran
    h = json.loads((ws.dir / "titles.json").read_text())["header"]
    hash0 = manifest_of(ws)["stages"]["titling"]["config_hash"]
    assert hash0 == config_hash(used_config(cfg, h["lines"]))
    n = len(fake.calls)
    for series in ("Tên khác", "Tên thứ ba", None):
        _write_playlist(cfg.workspace.dir, "PLbbbbbbbbbbbb", [_entry(EID, 40, "40")], series=series)
        assert not run_titling(EID, cfg, client=fake).ran
    assert len(fake.calls) == n and manifest_of(ws)["stages"]["titling"]["config_hash"] == hash0
