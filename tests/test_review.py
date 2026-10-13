"""CP8.2 review module: review.json v1 (T1), manual title validation (T2), override key (T3), precedence (T4),
episode functions shared by CLI and web, CLI ``auto-short title`` (without --render). No ffmpeg needed."""

import json
from dataclasses import replace

import pytest

from auto_short.cli import main
from auto_short.config import Config, RenderConfig, WorkspaceConfig
from auto_short.review import (ReviewError, list_titles, load_overrides, preview_title, reset_title,
                               set_alternative, set_title)
from auto_short.review.logic import (check_review, empty_review, manual_title_error, resolve_titles,
                                     with_override, without_override)
from render_helpers import EID, TITLES, make_render_episode, write_docs

ALTS = {"k01": ["Tâm từ bi hiện ra nơi tướng mạo", "Tướng do tâm sinh"], "k02": []}
NEW = "Tướng mạo đổi theo tâm thiện"


@pytest.fixture
def rcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=replace(RenderConfig(), output_dir=tmp_path / "output"))


@pytest.fixture
def ws(rcfg, tmp_path):
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"not a video")
    ws = make_render_episode(rcfg.workspace.dir, src)
    write_docs(ws, alternatives=ALTS)
    return ws


def _review(ws):
    return json.loads((ws.dir / "review.json").read_text(encoding="utf-8"))


# --- T2 form rules --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, reason", [
    ("Tâm thiện", None), ("A b", None), ("  Tâm   thiện  ", None), ("x" * 60, None),
    ("x" * 61, "too long (61 > 60 chars)"), ("", "empty title"), ("   ", "empty title"),
    ("Tâm\nthiện", "multi-line title"), ("Tâm thiện 🙏", "emoji/pictograph"), ("TÂM THIỆN", "all caps"),
    ("Tâm thiện #phật", "hashtag"), ("Tâm thiện!", "exclamation mark"), ('"Tâm thiện"', "wrapped in quotes"),
    ("xem www.abc.com", "URL"),
])
def test_manual_title_form_rules(text, reason):
    # CP6 G5 rules 1-8 with min_chars 1; no evidence rule (a human wrote it)
    assert manual_title_error(text, max_chars=60) == reason


# --- T1 schema, T3/T4 resolution ------------------------------------------------------------------------------

def _entry(clip="k01", cand="c00001", title="Tâm", origin="manual"):
    return {"clip_id": clip, "candidate_id": cand, "title": title, "origin": origin}


@pytest.mark.parametrize("doc, msg", [
    ([], "must be an object"),
    ({"schema_version": 2, "episode_id": EID, "titles": []}, "unsupported schema_version"),
    ({"schema_version": 1, "episode_id": "other", "titles": []}, "episode_id"),
    ({"schema_version": 1, "episode_id": EID, "titles": [], "x": 1}, "must be an object with keys"),
    ({"schema_version": 1, "episode_id": EID, "titles": [_entry(origin="ai")]}, "origin 'ai'"),
    ({"schema_version": 1, "episode_id": EID, "titles": [_entry(title=" Tâm")]}, "not normalized"),
    ({"schema_version": 1, "episode_id": EID, "titles": [_entry(title="")]}, "non-empty string"),
    ({"schema_version": 1, "episode_id": EID, "titles": [_entry(), _entry()]}, "duplicate clip_id"),
])
def test_check_review_rejects(doc, msg):
    with pytest.raises(ReviewError, match=msg):
        check_review(doc, EID)


def test_resolve_titles_precedence_and_mismatch():
    titles = [{"clip_id": "k01", "candidate_id": "c00001", "title": "AI 1", "status": "titled"},
              {"clip_id": "k02", "candidate_id": "c00002", "title": "AI 2", "status": "titled"},
              {"clip_id": "k03", "candidate_id": "c00003", "title": None, "status": "untitled"},
              {"clip_id": "k04", "candidate_id": "c00004", "title": None, "status": "untitled"}]
    review = {"schema_version": 1, "episode_id": EID, "titles": [
        _entry("k01", "c00001", "Tay 1"), _entry("k02", "c00099", "Tay 2"), _entry("k03", "c00003", "Tay 3",
                                                                                   "alternative"),
        _entry("k09", "c00009", "Tay 9")]}
    resolved, warnings = resolve_titles(titles, review)
    assert [(r.clip_id, r.title, r.origin) for r in resolved] == [
        ("k01", "Tay 1", "manual"), ("k02", "AI 2", "ai"), ("k03", "Tay 3", "alternative"), ("k04", None, None)]
    assert warnings == [
        "title override for clip k02 ignored: made for candidate c00099, the clip is now candidate c00002 "
        "(selection re-run)",
        "title override for clip k09 ignored: no such clip in clips.json"]


def test_with_and_without_override_keep_clips_order():
    doc = empty_review(EID)
    doc = with_override(doc, ["k01", "k02"], clip_id="k02", candidate_id="c2", title="B", origin="manual")
    doc = with_override(doc, ["k01", "k02"], clip_id="k01", candidate_id="c1", title="A", origin="alternative")
    doc = with_override(doc, ["k01", "k02"], clip_id="k02", candidate_id="c2", title="C", origin="manual")
    assert [(e["clip_id"], e["title"]) for e in doc["titles"]] == [("k01", "A"), ("k02", "C")]
    doc, removed = without_override(doc, ["k01", "k02"], "k01")
    assert removed and [e["clip_id"] for e in doc["titles"]] == ["k02"]
    assert without_override(doc, ["k01", "k02"], "k01")[1] is False


# --- episode functions ----------------------------------------------------------------------------------------

def test_set_title_writes_review_and_previews(ws, rcfg):
    p = set_title(EID, rcfg, "k01", f"  {NEW}  ")
    assert (p.clip_id, p.title, p.origin, p.font_size) == ("k01", NEW, "manual", 70)
    assert 1 <= len(p.display_lines) <= 3 and " ".join(p.display_lines) == NEW and p.panel_height >= 227
    assert _review(ws) == {"schema_version": 1, "episode_id": EID,
                           "titles": [{"clip_id": "k01", "candidate_id": "c00001", "title": NEW, "origin": "manual"}]}
    assert (ws.dir / "review.json").read_text(encoding="utf-8").endswith("}\n")
    assert load_overrides(EID, rcfg) == _review(ws)["titles"]
    assert preview_title(EID, rcfg, "k02", "Một câu khác").origin == "manual"


@pytest.mark.parametrize("text, msg", [
    ("x" * 61, "too long"), ("", "empty title"), ("Tâm thiện 🙏", "emoji"), ("Tâm 心 thiện", "non-Latin script"),
    ("Tâm \ue000 thiện", "not in the font"),
    ("Nghiêngnghiêngnghiêngnghiêngnghiêngnghiêngnghiêng", "does not fit"),
])
def test_invalid_title_leaves_review_unchanged(ws, rcfg, text, msg):
    with pytest.raises(ReviewError, match=msg):
        set_title(EID, rcfg, "k01", text)
    assert not (ws.dir / "review.json").exists()
    set_title(EID, rcfg, "k02", "Một câu khác")
    before = (ws.dir / "review.json").read_bytes()
    with pytest.raises(ReviewError, match=msg):
        set_title(EID, rcfg, "k01", text)
    with pytest.raises(ReviewError, match=msg):
        preview_title(EID, rcfg, "k01", text)
    assert (ws.dir / "review.json").read_bytes() == before


def test_alternative_reset_and_list(ws, rcfg):
    p = set_alternative(EID, rcfg, "k01", 1)
    assert (p.title, p.origin) == (ALTS["k01"][0], "alternative")
    assert _review(ws)["titles"][0]["origin"] == "alternative"
    with pytest.raises(ReviewError, match="no alternative 3"):
        set_alternative(EID, rcfg, "k01", 3)
    with pytest.raises(ReviewError, match="has no alternatives"):
        set_alternative(EID, rcfg, "k02", 1)
    set_title(EID, rcfg, "k02", "Một câu khác")

    doc = list_titles(EID, rcfg)
    assert doc["episode_id"] == EID and doc["ignored"] == []
    k01, k02 = doc["clips"]
    assert k01 == {"clip_id": "k01", "candidate_id": "c00001", "status": "titled", "ai_title": TITLES["k01"],
                   "alternatives": [{"n": 1, "title": ALTS["k01"][0]}, {"n": 2, "title": ALTS["k01"][1]}],
                   "override": {"title": ALTS["k01"][0], "origin": "alternative"},
                   "title": ALTS["k01"][0], "origin": "alternative", "rejected": False,  # CP8.5: + rejected
                   "added": False}  # CP9: + added
    assert (k02["title"], k02["origin"]) == ("Một câu khác", "manual")

    p = reset_title(EID, rcfg, "k01")
    assert (p.title, p.origin) == (TITLES["k01"], "ai")
    assert [e["clip_id"] for e in _review(ws)["titles"]] == ["k02"]
    before = (ws.dir / "review.json").read_bytes()
    assert reset_title(EID, rcfg, "k01").origin == "ai"  # nothing to remove: file untouched
    assert (ws.dir / "review.json").read_bytes() == before


def test_untitled_clip_and_candidate_mismatch(ws, rcfg):
    write_docs(ws, titles={"k01": None, "k02": TITLES["k02"]})
    assert list_titles(EID, rcfg)["clips"][0]["origin"] is None
    set_title(EID, rcfg, "k01", NEW)
    assert list_titles(EID, rcfg)["clips"][0]["origin"] == "manual"
    assert reset_title(EID, rcfg, "k01") is None  # untitled again: not rendered

    set_title(EID, rcfg, "k02", "Một câu khác")
    # selection re-run: k02 now comes from another candidate -> the override no longer applies
    from render_helpers import CANDIDATES, CLIPS
    cands = CANDIDATES + [dict(CANDIDATES[1], id="c00007")]
    write_docs(ws, clips=[CLIPS[0], dict(CLIPS[1], candidate_id="c00007")], candidates=cands)
    doc = list_titles(EID, rcfg)
    assert (doc["clips"][1]["override"], doc["clips"][1]["origin"]) == (None, "ai")
    assert "k02 ignored: made for candidate c00002" in doc["ignored"][0]
    assert load_overrides(EID, rcfg)[0]["candidate_id"] == "c00002"  # kept in the file (T3)
    set_title(EID, rcfg, "k02", "Câu mới")  # replaces the stale override
    assert _review(ws)["titles"] == [{"clip_id": "k02", "candidate_id": "c00007", "title": "Câu mới",
                                      "origin": "manual"}]


def test_errors(ws, rcfg):
    with pytest.raises(ReviewError, match="no clip 'k09'"):
        set_title(EID, rcfg, "k09", NEW)
    with pytest.raises(ReviewError, match="no manifest"):
        list_titles("other", rcfg)
    (ws.dir / "review.json").write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(ReviewError, match="review.json: must be an object"):
        list_titles(EID, rcfg)
    manifest = json.loads(ws.manifest_path.read_text(encoding="utf-8"))
    manifest["stages"]["titling"]["status"] = "stale"
    ws.save_manifest(manifest)
    with pytest.raises(ReviewError, match="titling is not done"):
        set_title(EID, rcfg, "k01", NEW)


# --- CLI (T6) -------------------------------------------------------------------------------------------------

@pytest.fixture
def cfg_file(rcfg, tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(f'[workspace]\ndir = "{rcfg.workspace.dir.as_posix()}"\n'
                 f'[render]\noutput_dir = "{rcfg.render.output_dir.as_posix()}"\n', encoding="utf-8")
    return str(p)


def test_cli_title(ws, cfg_file, capsys):
    assert main(["title", EID, "k01", "--set", NEW, "--config", cfg_file]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"{EID}\tk01\tmanual\t{NEW}"
    assert out[1].startswith("  display (70 px, panel ") and NEW.split()[0] in out[1]

    assert main(["title", EID, "k01", "--alternative", "2", "--config", cfg_file]) == 0
    assert capsys.readouterr().out.startswith(f"{EID}\tk01\talternative\t{ALTS['k01'][1]}\n")

    assert main(["title", EID, "--list", "--config", cfg_file]) == 0
    out = capsys.readouterr().out
    assert f"k01\tc00001\talternative\t{ALTS['k01'][1]}\n  AI: {TITLES['k01']}\n  1: {ALTS['k01'][0]}\n" in out
    assert f"  override (alternative): {ALTS['k01'][1]}\n" in out
    assert f"k02\tc00002\tai\t{TITLES['k02']}\n  AI: {TITLES['k02']}\n" in out

    before = (ws.dir / "review.json").read_bytes()
    for bad in (["--set", "x" * 61], ["--set", ""], ["--set", "Tâm 🙏"], ["--set", "Tâm thiện 众生"], ["--alternative", "5"]):
        assert main(["title", EID, "k01", *bad, "--config", cfg_file]) == 1
        assert "auto-short: error: " in capsys.readouterr().err
        assert (ws.dir / "review.json").read_bytes() == before

    assert main(["title", EID, "k01", "--reset", "--config", cfg_file]) == 0
    assert capsys.readouterr().out.startswith(f"{EID}\tk01\tai\t{TITLES['k01']}\n")
    assert _review(ws)["titles"] == []

    assert main(["title", EID, "--reset", "--config", cfg_file]) == 1  # clip id required
    assert "clip id required" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["title", EID, "k01", "--config", cfg_file])  # one action required (argparse, exit 2)
