"""CP9 render (lavfi source, real ffmpeg): manual cut of one Short -> only it is encoded, the others reused
byte-identical, ``render_manifest`` records ``cut``; "Về như AI chọn" -> byte-identical to the original (AC2).
Shorts added by hand come after the clips.json clips (C2), untitled ones are skipped, deleted / restored like AI
Shorts; trims of a manual range come from silences.json (C5); stale cuts are ignored (AC6)."""

import json
import logging
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short.config import Config, RenderConfig, WorkspaceConfig
from auto_short.hashing import sha256_file
from auto_short.render import RenderError, plan, run_render
from auto_short.review import reject_clip, restore_clip
from auto_short.review.logic import empty_review, with_added, with_cut, without_cut
from render_helpers import EID, make_render_episode, make_source, sha, write_docs

pytestmark = pytest.mark.usefixtures("_ffmpeg")
SILENCES = [[0.25, 1.15], [1.9, 2.6], [4.9, 5.7]]  # >= 0.5 s max_pause below -> trimmed
PARAMS = {"max_pause": 0.5}
ORDER = ["k01", "k02"]


@pytest.fixture(scope="session")
def _ffmpeg(_video_template):  # skips when ffmpeg is missing (conftest)
    return None


@pytest.fixture(scope="session")
def source_template(tmp_path_factory, _ffmpeg) -> Path:
    return make_source(tmp_path_factory.mktemp("cp9") / "src.mp4")


@pytest.fixture
def rcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=replace(RenderConfig(), output_dir=tmp_path / "output", preset="ultrafast"))


def _silences_doc():
    return {"schema_version": 1, "episode_id": EID, "silences": [{"start": a, "end": b} for a, b in SILENCES]}


@pytest.fixture
def ws(rcfg, source_template):
    ws = make_render_episode(rcfg.workspace.dir, source_template)
    (ws.dir / "silences.json").write_text(json.dumps(_silences_doc()), encoding="utf-8")
    write_docs(ws, cand_extra={"params": PARAMS, "silences_sha256": sha(_silences_doc())})
    return ws


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=False)

    @property
    def encoded(self):
        return [Path(c[-1]).name.split(".")[1] for c in self.calls if c[0] == "ffmpeg"]


def _render(rcfg, **kw):
    rec = Recorder()
    return run_render(EID, rcfg, run=rec, **kw), rec.encoded


def _out(rcfg):
    return (rcfg.render.output_dir / EID).resolve()


def _rm(rcfg):
    return json.loads((_out(rcfg) / "render_manifest.json").read_text(encoding="utf-8"))


def _shas(rcfg):
    return {p.name: sha256_file(p) for p in sorted((_out(rcfg) / "shorts").glob("*.mp4"))}


def _review(ws):
    p = ws.dir / "review.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else empty_review(EID)


def _write(ws, doc):
    (ws.dir / "review.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _added(clip, start, end, title="Short thêm tay từ phụ đề", source="transcript", cand="manual"):
    return {"clip_id": clip, "candidate_id": cand, "start": start, "end": end, "source": source, "title": title,
            "ai_title": title, "alternatives": []}


def test_cut_reencodes_only_that_short_and_reset_is_byte_identical(ws, rcfg, caplog):
    caplog.set_level(logging.INFO, logger="auto_short")
    r, enc = _render(rcfg)
    assert enc == ["k01", "k02"]
    base, base_doc = _shas(rcfg), _rm(rcfg)

    _write(ws, with_cut(_review(ws), ORDER, clip_id="k02", candidate_id="c00002", start=4.2, end=7.6))
    r, enc = _render(rcfg)
    assert r.ran and enc == ["k02"] and (r.encoded, r.reused) == (1, 1)
    doc, shas = _rm(rcfg), _shas(rcfg)
    k01, k02 = doc["shorts"]
    assert k01 == base_doc["shorts"][0] and shas["k01.mp4"] == base["k01.mp4"]  # reused byte-identical
    # C5: trims of the manual range from silences.json (CP4 A8, max_pause 0.5): [4.9, 5.7] -> [5.15, 5.45]
    assert k02["segments"] == [[4.2, 5.15], [5.45, 7.6]] and k02["duration"] == 3.1
    assert (k02["source_start"], k02["source_end"]) == (4.2, 7.6)
    assert (k02["origin"], k02["cut"]) == ("ai", {"start": 4.2, "end": 7.6})
    assert shas["k02.mp4"] != base["k02.mp4"] and doc["stats"]["seconds"] == round(2.4 + 3.1, 3)
    assert "clip k02: manual cut range 4.200-7.600" in caplog.text
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                                       str(_out(rcfg) / "shorts/k02.mp4")], capture_output=True, text=True).stdout)
    assert abs(float(probe["format"]["duration"]) - 3.1) < 0.1

    doc, removed = without_cut(_review(ws), ORDER, "k02")
    assert removed
    _write(ws, doc)
    r, enc = _render(rcfg)
    assert enc == ["k02"] and _shas(rcfg) == base  # AC2: "Về như AI chọn" -> byte-identical
    assert _rm(rcfg)["shorts"] == base_doc["shorts"]


def test_added_shorts_after_clips_untitled_deleted_restored(ws, rcfg):
    _render(rcfg)
    base = _shas(rcfg)
    order = ORDER + ["m01"]
    _write(ws, with_added(_review(ws), order, _added("m01", 0.5, 3.5)))
    r, enc = _render(rcfg)
    assert enc == ["m01"] and (r.encoded, r.reused, r.rendered, r.clips) == (1, 2, 3, 3)
    doc, shas = _rm(rcfg), _shas(rcfg)
    assert [s["clip_id"] for s in doc["shorts"]] == ["k01", "k02", "m01"]  # C2: after clips.json
    m01 = doc["shorts"][2]
    assert (m01["candidate_id"], m01["origin"], m01["cut"], m01["title_origin"]) == ("manual", "added", None, "ai")
    # trims from silences.json: [0.25, 1.15] cut at 0.5 -> [0.5, 1.15] (0.65 > 0.5) -> [0.75, 0.9]; [1.9, 2.6]
    assert m01["segments"] == [[0.5, 0.75], [0.9, 2.15], [2.35, 3.5]] and m01["duration"] == 2.65
    assert {k: shas[k] for k in base} == base
    m01_sha = shas["m01.mp4"]

    # untitled added Short (AI failed): skipped, nothing encoded
    _write(ws, with_added(_review(ws), order + ["m02"], _added("m02", 4.0, 7.0, title=None) | {"ai_title": None}))
    r, enc = _render(rcfg)
    assert enc == [] and _rm(rcfg)["shorts"][3]["skip_reason"] == "untitled"

    # delete / restore by the (clip_id, candidate_id) key like an AI Short (AC5)
    reject_clip(EID, rcfg, "m01")
    r, enc = _render(rcfg)
    assert enc == [] and _rm(rcfg)["shorts"][2]["skip_reason"] == "rejected"
    assert not (_out(rcfg) / "shorts/m01.mp4").exists()
    restore_clip(EID, rcfg, "m01")
    r, enc = _render(rcfg)
    assert enc == ["m01"] and _shas(rcfg)["m01.mp4"] == m01_sha

    # a cut on an added Short: only it is encoded
    _write(ws, with_cut(_review(ws), order + ["m02"], clip_id="m01", candidate_id="manual", start=0.5, end=3.0))
    r, enc = _render(rcfg)
    assert enc == ["m01"] and _rm(rcfg)["shorts"][2]["cut"] == {"start": 0.5, "end": 3.0}


def test_stale_cut_ignored_added_kept(ws, rcfg, caplog):
    """AC6: selection re-run (clip is another candidate) -> the cut is ignored with a warning; added stays."""
    doc = with_cut(empty_review(EID), ORDER, clip_id="k02", candidate_id="c00099", start=4.2, end=7.6)
    doc = with_added(doc, ORDER + ["m01"], _added("m01", 0.5, 3.5))
    _write(ws, doc)
    caplog.set_level(logging.WARNING, logger="auto_short")
    r, enc = _render(rcfg)
    assert enc == ["k01", "k02", "m01"]
    k02 = _rm(rcfg)["shorts"][1]
    assert k02["cut"] is None and k02["source_start"] == 4.5
    assert "cut of clip k02 ignored: made for candidate c00099" in caplog.text


def test_manual_range_needs_matching_silences(ws, rcfg):
    _write(ws, with_added(_review(ws), ORDER + ["m01"], _added("m01", 0.5, 3.5)))
    (ws.dir / "silences.json").write_text(json.dumps({**_silences_doc(), "silences": []}), encoding="utf-8")
    with pytest.raises(RenderError, match="silences.json does not match candidates.json"):
        _render(rcfg)


def test_plan_version_unchanged():
    assert plan.RENDER_PLAN_VERSION == 1  # CP9 adds ranges, not a new way of building a Short
