"""CP8.2 render with title overrides (T4) and per-Short reuse (T5), lavfi source: only the changed Short is
encoded, the others are reused byte-identical; --force / config change encode all; deleting one mp4 re-encodes
only it; overrides with a stale candidate are ignored; untitled clips with an override are rendered; CLI --render."""

import json
import logging
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short.cli import main
from auto_short.config import Config, RenderConfig, WorkspaceConfig
from auto_short.hashing import sha256_file
from auto_short.render import RenderError, plan, run_render
from auto_short.review import reject_clip, reset_title, restore_clip, set_alternative, set_title
from render_helpers import CANDIDATES, CLIPS, EID, TITLES, make_render_episode, make_source, write_docs

pytestmark = pytest.mark.usefixtures("_ffmpeg")
NEW = "Tướng mạo đổi theo tâm thiện"


@pytest.fixture(scope="session")
def _ffmpeg(_video_template):  # skips when ffmpeg is missing (conftest)
    return None


@pytest.fixture(scope="session")
def source_template(tmp_path_factory, _ffmpeg) -> Path:
    return make_source(tmp_path_factory.mktemp("reuse") / "src.mp4")


@pytest.fixture
def rcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=replace(RenderConfig(), output_dir=tmp_path / "output", preset="ultrafast"))


@pytest.fixture
def ws(rcfg, source_template):
    ws = make_render_episode(rcfg.workspace.dir, source_template)
    write_docs(ws, alternatives={"k02": ["Suy nghĩ nào cũng thành tội?"]})
    return ws


class Recorder:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=False)

    @property
    def encoded(self) -> list[str]:
        """Clip ids encoded (from the .part output path of each ffmpeg call)."""
        return [Path(c[-1]).name.split(".")[1] for c in self.calls if c[0] == "ffmpeg"]


def _out(rcfg):
    return (rcfg.render.output_dir / EID).resolve()


def _rm(rcfg):
    return json.loads((_out(rcfg) / "render_manifest.json").read_text(encoding="utf-8"))


def _shas(rcfg):
    return {p.name: sha256_file(p) for p in sorted((_out(rcfg) / "shorts").glob("*.mp4"))}


def _render(rcfg, **kw):
    rec = Recorder()
    result = run_render(EID, rcfg, run=rec, **kw)
    return result, rec.encoded


def test_override_reencodes_only_that_short(ws, rcfg, caplog):
    caplog.set_level(logging.INFO, logger="auto_short")
    r, enc = _render(rcfg)
    assert r.ran and enc == ["k01", "k02"] and (r.encoded, r.reused) == (2, 0)
    base, base_doc = _shas(rcfg), _rm(rcfg)

    set_title(EID, rcfg, "k01", NEW)
    r, enc = _render(rcfg)
    assert r.ran and enc == ["k01"] and (r.rendered, r.encoded, r.reused) == (2, 1, 1)
    doc, shas = _rm(rcfg), _shas(rcfg)
    k01, k02 = doc["shorts"]
    assert (k01["title"], k01["title_origin"]) == (NEW, "manual") and " ".join(k01["title_display_lines"]) == NEW
    assert shas["k02.mp4"] == base["k02.mp4"] and shas["k01.mp4"] != base["k01.mp4"]
    assert k02 == base_doc["shorts"][1]  # reused entry identical (render_key, sha256, ...)
    assert k01["render_key"] != base_doc["shorts"][0]["render_key"] and k01["sha256"] == shas["k01.mp4"]
    assert "clip k02: reuse (render_key unchanged)" in caplog.text
    inputs = json.loads(ws.manifest_path.read_text(encoding="utf-8"))["stages"]["render"]["inputs"]
    assert [i["path"] for i in inputs] == ["clips.json", "titles.json", "candidates.json", "metadata.json",
                                           "review.json", "source.mp4"]
    assert not list(_out(rcfg).glob("shorts/.*"))

    # AC5: nothing changed -> stage skip; deleting one mp4 -> only that one is encoded again
    r, enc = _render(rcfg)
    assert not r.ran and enc == []
    (_out(rcfg) / "shorts/k02.mp4").unlink()
    r, enc = _render(rcfg)
    assert r.ran and enc == ["k02"] and _shas(rcfg) == shas  # deterministic re-encode

    # alternative -> k02 encoded; reset -> k01 back to the AI title, byte-identical to the first render
    set_alternative(EID, rcfg, "k02", 1)
    r, enc = _render(rcfg)
    assert enc == ["k02"] and _rm(rcfg)["shorts"][1]["title_origin"] == "alternative"
    reset_title(EID, rcfg, "k01")
    reset_title(EID, rcfg, "k02")
    r, enc = _render(rcfg)
    assert enc == ["k01", "k02"] and _shas(rcfg) == base
    assert [s["title_origin"] for s in _rm(rcfg)["shorts"]] == ["ai", "ai"]


@pytest.mark.slow
def test_force_config_and_plan_version_encode_all(ws, rcfg, monkeypatch):
    _render(rcfg)
    base = _shas(rcfg)
    r, enc = _render(rcfg, force=True)
    assert enc == ["k01", "k02"] and (r.encoded, r.reused) == (2, 0) and _shas(rcfg) == base
    crf = replace(rcfg, render=replace(rcfg.render, crf=30))
    r, enc = _render(crf)
    assert enc == ["k01", "k02"]
    monkeypatch.setattr(plan, "RENDER_PLAN_VERSION", plan.RENDER_PLAN_VERSION + 1)
    r, enc = _render(crf)  # stage up to date: skip
    assert not r.ran
    set_title(EID, rcfg, "k01", NEW)
    r, enc = _render(crf)
    assert enc == ["k01", "k02"]  # new plan version: no Short is reused


# pre-CP8.14 default sizes (the old layout also had gap_video_title and vertical centring, which no longer exist)
PRE_CP814 = dict(header_panel_width=0.79, header_panel_height=0.27, header_font_size=0.062, video_height=1.12,
                 title_panel_width=0.81, title_panel_height=0.27, title_font_size=0.0815)


def _files(rcfg):
    return {p.relative_to(_out(rcfg)).as_posix(): p.read_bytes() for p in _out(rcfg).rglob("*") if p.is_file()}


def test_layout_change_rerenders_whole_episode_only_when_rerun(ws, rcfg, caplog):
    """CP8.14 AC4 / L5: an episode rendered with the old layout keeps its files byte for byte until it runs
    again; the next run (here after a title edit of one Short) encodes every Short with the new layout."""
    caplog.set_level(logging.INFO, logger="auto_short")
    old = replace(rcfg, render=replace(rcfg.render, **PRE_CP814))
    r, enc = _render(old)
    assert enc == ["k01", "k02"]
    before, old_doc = _files(rcfg), _rm(rcfg)
    assert old_doc["layout"]["header_panel"]["h"] == 292

    set_title(EID, rcfg, "k01", NEW)  # writes review.json only
    assert _files(rcfg) == before
    r, enc = _render(rcfg)
    assert "render: run (config changed)" in caplog.text
    assert r.ran and enc == ["k01", "k02"] and (r.encoded, r.reused) == (2, 0)
    doc = _rm(rcfg)
    assert doc["layout"]["header_panel"] == {"x": 81, "y": 22, "w": 918, "h": 184, "radius": 59}
    assert all(s["title_font_size"] == 70 and s["layout"]["title_panel"]["y"] + s["layout"]["title_panel"]["h"] == 1600
               for s in doc["shorts"])
    assert [s["render_key"] for s in doc["shorts"]] != [s["render_key"] for s in old_doc["shorts"]]
    assert doc["shorts"][0]["title"] == NEW


def test_reuse_requires_matching_file(ws, rcfg):
    _render(rcfg)
    k02 = _out(rcfg) / "shorts/k02.mp4"
    k02.write_bytes(k02.read_bytes()[:-1] + b"\0")  # tampered: sha256 no longer matches
    set_title(EID, rcfg, "k01", NEW)
    r, enc = _render(rcfg)
    assert enc == ["k01", "k02"]
    assert sha256_file(k02) == _rm(rcfg)["shorts"][1]["sha256"]


def test_stale_override_ignored_and_untitled_override_rendered(ws, rcfg, caplog):
    write_docs(ws, titles={"k01": None, "k02": TITLES["k02"]})
    _render(rcfg)
    assert _rm(rcfg)["shorts"][0]["status"] == "skipped"
    set_title(EID, rcfg, "k01", NEW)
    set_title(EID, rcfg, "k02", "Một câu khác")
    r, enc = _render(rcfg)
    assert enc == ["k01", "k02"]
    k01, k02 = _rm(rcfg)["shorts"]
    assert (k01["status"], k01["title"], k01["title_origin"]) == ("rendered", NEW, "manual")

    # selection re-run: k02 is now another candidate (same range) -> override ignored with a warning, AI title
    cands = CANDIDATES + [dict(CANDIDATES[1], id="c00007")]
    write_docs(ws, titles={"k01": None, "k02": TITLES["k02"]}, clips=[CLIPS[0], dict(CLIPS[1], candidate_id="c00007")],
               candidates=cands)
    r, enc = _render(rcfg)
    assert "title override for clip k02 ignored: made for candidate c00002" in caplog.text
    k01, k02 = _rm(rcfg)["shorts"]
    assert (k02["candidate_id"], k02["title"], k02["title_origin"]) == ("c00007", TITLES["k02"], "ai")
    assert enc == ["k02"]  # k01 (override still valid) reused

    # reset the untitled clip -> skipped again, its old mp4 removed
    reset_title(EID, rcfg, "k01")
    r, enc = _render(rcfg)
    assert enc == [] and r.reused == 1
    assert _rm(rcfg)["shorts"][0]["status"] == "skipped" and not (_out(rcfg) / "shorts/k01.mp4").exists()


def test_failed_render_keeps_reusable_shorts(ws, rcfg):
    _render(rcfg)
    base = _shas(rcfg)
    set_title(EID, rcfg, "k01", NEW)

    def failing(cmd):
        if cmd[0] == "ffmpeg":
            return subprocess.CompletedProcess(cmd, 1, "", "boom\n")
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=False)

    with pytest.raises(RenderError, match="clip k01: ffmpeg failed: boom"):
        run_render(EID, rcfg, run=failing)
    assert _shas(rcfg) == base and not list(_out(rcfg).glob("shorts/.*"))
    r, enc = _render(rcfg)  # previous manifest still indexes the files: k02 reused
    assert enc == ["k01"]


def test_invalid_review_json_fails_render(ws, rcfg):
    (ws.dir / "review.json").write_text('{"schema_version": 1, "episode_id": "x", "titles": []}', encoding="utf-8")
    with pytest.raises(RenderError, match="review.json: episode_id"):
        run_render(EID, rcfg)


@pytest.mark.slow
def test_cli_title_render(ws, rcfg, tmp_path, capsys):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(f'[workspace]\ndir = "{rcfg.workspace.dir.as_posix()}"\n'
                        f'[render]\noutput_dir = "{rcfg.render.output_dir.as_posix()}"\npreset = "ultrafast"\n',
                        encoding="utf-8")
    assert main(["render", EID, "--config", str(cfg_file)]) == 0
    capsys.readouterr()
    assert main(["title", EID, "k02", "--set", "Một câu khác", "--render", "--config", str(cfg_file)]) == 0
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert lines[0] == f"{EID}\tk02\tmanual\tMột câu khác"
    assert lines[2] == f"{EID}\trendered (2/2 clips)\t{_out(rcfg) / 'render_manifest.json'}"
    assert "render: clip k01: reuse" in out.err and "(1 encoded, 1 reused)" in out.err


def test_rejected_short_skipped_removed_and_restored(ws, rcfg, caplog):
    """CP8.5 X2: a deleted Short is skipped (skip_reason rejected), its mp4 removed at the commit, the others
    reused; restore re-encodes it byte-identical (with its title override)."""
    caplog.set_level(logging.INFO, logger="auto_short")
    set_title(EID, rcfg, "k01", NEW)
    _render(rcfg)
    base, base_doc = _shas(rcfg), _rm(rcfg)
    reject_clip(EID, rcfg, "k01")
    r, enc = _render(rcfg)
    assert r.ran and enc == [] and (r.rendered, r.clips, r.encoded, r.reused) == (1, 2, 0, 1)
    k01, k02 = _rm(rcfg)["shorts"]
    assert (k01["status"], k01["skip_reason"], k01["file"], k01["render_key"], k01["dissolves"]) == \
        ("skipped", "rejected", None, None, None)
    assert (k01["title"], k01["title_origin"]) == (NEW, "manual")  # the title it will be restored with
    assert k02 == base_doc["shorts"][1] and _shas(rcfg) == {"k02.mp4": base["k02.mp4"]}
    assert _rm(rcfg)["stats"]["skipped"] == 1
    assert "clip k01 skipped: rejected" in caplog.text and "WARNING: 1 clip(s) skipped" not in caplog.text
    assert not list(_out(rcfg).glob("shorts/.*"))
    r, enc = _render(rcfg)
    assert not r.ran  # up to date
    restore_clip(EID, rcfg, "k01")
    r, enc = _render(rcfg)
    assert enc == ["k01"] and _shas(rcfg) == base and _rm(rcfg) == base_doc


def test_rejected_untitled_and_every_short_deleted(ws, rcfg):
    write_docs(ws, titles={"k01": None, "k02": TITLES["k02"]})
    reject_clip(EID, rcfg, "k01")
    reject_clip(EID, rcfg, "k02")
    r, enc = _render(rcfg)
    assert r.ran and enc == [] and r.rendered == 0
    assert [s["skip_reason"] for s in _rm(rcfg)["shorts"]] == ["rejected", "rejected"]
    assert not list(_out(rcfg).glob("shorts/*.mp4"))


# --- CP8.21 D1: khai thị episode renders with the pre-CP8.14 layout, a Short is unchanged ----------------------

SHORT_CONFIG_HASH_C2007C6 = "de0b688d5755f64bf5e1bf2483081492f4e91fdbcfe1bceccbca49631d795cfb"  # at c2007c6


def test_short_config_hash_unchanged_and_khaithi_differs():
    from auto_short.hashing import config_hash
    from auto_short.render.stage import used_config
    assert config_hash(used_config(RenderConfig(), "f" * 64)) == SHORT_CONFIG_HASH_C2007C6
    kt_cfg = plan.render_config_for(RenderConfig(), True)
    assert plan.render_config_for(RenderConfig(), False) == RenderConfig()
    assert config_hash(used_config(kt_cfg, "f" * 64, True)) != SHORT_CONFIG_HASH_C2007C6


def test_khaithi_layout_is_the_pre_cp814_one():
    g = plan.geometry(plan.render_config_for(RenderConfig(), True), khaithi=True)
    assert (g.header_w, g.header_h, g.video_h, g.title_w, g.title_h) == (853, 292, 1210, 875, 292)
    assert g.title_max_h == 358
    lay = plan.layout(g, g.title_h, 1440, 1080)
    assert lay.header.as_dict() == {"x": 113, "y": 55, "w": 853, "h": 292, "radius": 59}
    assert lay.video.y == 347 + 5 and lay.title.y == lay.video.y + 1210 + 11
    # block centred vertically
    assert lay.title.y + lay.title.h + lay.header.y == plan.HEIGHT
    # a Short (V16) is not affected
    s = plan.layout(plan.geometry(RenderConfig()), 227, 1440, 1080)
    assert s.title.y + s.title.h == 1600 and s.header.y == 22


def _make_khaithi(ws):
    from auto_short import khaithi
    khaithi.write(ws.dir, khaithi.KhaiThi("base", 5, 15))


def test_khaithi_episode_renders_old_layout_short_keeps_v16(ws, rcfg):
    r, enc = _render(rcfg)
    short_doc = _rm(rcfg)
    short_keys = [s["render_key"] for s in short_doc["shorts"]]
    assert short_doc["layout"]["header_panel"] == {"x": 81, "y": 22, "w": 918, "h": 184, "radius": 59}
    _make_khaithi(ws)
    r, enc = _render(rcfg)  # config hash changed -> whole episode encoded again
    assert enc == ["k01", "k02"]
    doc = _rm(rcfg)
    assert doc["layout"]["header_panel"] == {"x": 113, "y": 55, "w": 853, "h": 292, "radius": 59}
    assert all(s["title_font_size"] <= 88 for s in doc["shorts"])
    assert [s["render_key"] for s in doc["shorts"]] != short_keys
    r, enc = _render(rcfg)
    assert not r.ran
