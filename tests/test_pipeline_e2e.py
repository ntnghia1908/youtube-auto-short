"""End-to-end ``auto-short run`` without network (CP8 AC1, AC3/AC4 on real stages, AC6, AC7).

Source: 30 s lavfi video whose audio is a tone 4.5 s / silence 1.5 s, with a Vietnamese ``.srt`` sidecar
aligned to the tones; ``[analysis]`` lowered so the 5 units give short candidates. Selection and titling use
fake Ollama chat clients; render runs the real ``ffmpeg`` (preset ultrafast).
"""

import json
import re
import shutil
import subprocess

import pytest

from auto_short import cli, pipeline
from auto_short.pipeline import StageDeps
from auto_short.render.stage import _run as ffmpeg_run
from auto_short.selection.client import ChatError, ChatResult

PERIOD, SPEECH, UNITS = 6.0, 4.5, 5
TEXTS = ["hôm nay chúng ta học về lòng biết ơn cha mẹ",
         "người con hiếu thảo luôn nhớ ơn sinh thành dưỡng dục",
         "khi còn trẻ ta thường không để ý điều này",
         "đến lúc lớn lên mới hiểu được công lao ấy",
         "hãy sống tốt mỗi ngày để cha mẹ an lòng"]
EXPECTED_STATES = ["ingested", "transcribed (local_subtitle/subtitle_srt)", "analyzed (12 candidates)",
                   "selected (2 clips)", "titled (2/2 clips)", "rendered (2/2 clips)"]


def _ts(x: float) -> str:
    ms = round(x * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


@pytest.fixture
def lecture(tmp_path):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    video = tmp_path / "src" / "Bài Giảng Tập 9.mp4"
    video.parent.mkdir()
    dur = PERIOD * UNITS
    tone = f"if(lt(mod(t\\,{PERIOD})\\,{SPEECH})\\,0.3*sin(2*PI*440*t)\\,0)"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=25:duration={dur}",
                    "-f", "lavfi", "-i", f"aevalsrc=exprs='{tone}':s=48000:d={dur}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(video)], check=True)
    srt = "".join(f"{n + 1}\n{_ts(n * PERIOD)} --> {_ts(n * PERIOD + SPEECH)}\n{text}\n\n"
                  for n, text in enumerate(TEXTS))
    video.with_name(video.stem + ".vi.srt").write_text(srt, encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text(f'''[workspace]
dir = "{(tmp_path / 'work').as_posix()}"
[analysis]
min_boundary_silence = 1.0
hard_break_silence = 5.0
min_duration = 4.0
max_duration = 20.0
target_min = 5.0
target_max = 10.0
[selection]
retries = 0
[titling]
retries = 0
[render]
output_dir = "{(tmp_path / 'output').as_posix()}"
preset = "ultrafast"
''', encoding="utf-8")
    return video, config


class SelectionClient:
    """Proposes u0001 and u0004 (one-unit candidates, ~5 s); ``fail`` raises ChatError instead."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def chat(self, *, model, messages, format, options, think):
        self.calls += 1
        if self.fail:
            raise ChatError("cannot reach Ollama at fake: down")
        clips = [{"first_unit": a, "last_unit": b, "topic": "chủ đề", "reason": "trọn ý", "start_complete": True,
                  "end_complete": True, "score": 8} for a, b in (("u0001", "u0001"), ("u0004", "u0004"))]
        return ChatResult(content=json.dumps({"clips": clips}, ensure_ascii=False), thinking="nghĩ")


_TEXT_RE = re.compile(r"Lời nói của đoạn:\n(.+)", re.S)


class TitlingClient:
    """Three options quoting the first four words of the clip text."""

    def __init__(self):
        self.calls = 0

    def chat(self, *, model, messages, format, options, think):
        self.calls += 1
        words = _TEXT_RE.search(messages[-1]["content"]).group(1).split()
        ev = " ".join(words[:4])
        opts = [{"evidence": ev, "title": f"Bài học số {k}: {ev}"} for k in (1, 2, 3)]
        return ChatResult(content=json.dumps({"options": opts}, ensure_ascii=False))


class InterruptingRunner:
    """Render runner: Ctrl-C on the first ffmpeg encode."""

    def __call__(self, cmd):
        if cmd[0] == "ffmpeg":
            raise KeyboardInterrupt
        return ffmpeg_run(cmd)


@pytest.fixture
def inject(monkeypatch):
    """Set the StageDeps the CLI's run_pipeline gets."""
    holder = {}
    real = pipeline.run_pipeline

    def wrapper(*args, **kw):
        return real(*args, deps=holder["deps"], **kw)

    monkeypatch.setattr(cli, "run_pipeline", wrapper)

    def set_deps(**deps):
        holder["deps"] = StageDeps(**deps)

    return set_deps


def _run(video, config, *extra):
    return cli.main(["run", str(video), "--no-preflight", "--series", "Bài giảng", "--episode", "9",
                     "--config", str(config), *extra])


def _states(out: str) -> list[str]:
    return [line.split("\t")[1] for line in out.splitlines()]


def _manifest(tmp_path, eid) -> dict:
    return json.loads((tmp_path / "work" / eid / "manifest.json").read_text(encoding="utf-8"))


def test_run_end_to_end(lecture, tmp_path, inject, capsys):
    video, config = lecture

    # 1. selection fails (Ollama down) -> exit 1, later stages not run, earlier stages stay done (E4).
    inject(selection_client=SelectionClient(fail=True), titling_client=TitlingClient())
    assert _run(video, config) == 1
    out = capsys.readouterr()
    assert _states(out.out) == EXPECTED_STATES[:3]
    eid = out.out.split("\t")[0]
    assert re.search(r"auto-short: error: selection failed: .*cannot reach Ollama at fake", out.err)
    assert "re-run the same command to resume" in out.err
    stages = _manifest(tmp_path, eid)["stages"]
    assert [stages[s]["status"] for s in ("ingest", "transcript", "analysis", "selection")] == \
        ["done", "done", "done", "failed"]
    assert "titling" not in stages and "render" not in stages

    # 2. same command after the error -> resume from selection (E3), Shorts rendered (AC1).
    sel, ti = SelectionClient(), TitlingClient()
    inject(selection_client=sel, titling_client=ti)
    assert _run(video, config) == 0
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert _states(out.out) == ["skipped (up to date)"] * 3 + EXPECTED_STATES[3:] + ["done (2/2 Shorts)"]
    out_dir = (tmp_path / "output" / eid).resolve()
    assert lines[-1] == f"{eid}\tdone (2/2 Shorts)\t{out_dir}"
    assert "AI titles are auto-approved" in out.err
    assert (sel.calls, ti.calls) == (1, 2)
    for name in ("metadata.json", "transcript.json", "shots.json", "silences.json", "candidates.json",
                 "clips.json", "selection_log.json", "titles.json", "titling_log.json"):
        assert (tmp_path / "work" / eid / name).is_file(), name
    rm = json.loads((out_dir / "render_manifest.json").read_text(encoding="utf-8"))
    assert rm["stats"]["rendered"] == 2
    shorts = sorted(p.name for p in (out_dir / "shorts").iterdir())
    assert shorts == ["k01.mp4", "k02.mp4"]
    sums = {p: (out_dir / "shorts" / p).read_bytes() for p in shorts}
    assert cli.main(["status", eid, "--config", str(config)]) == 0
    status = capsys.readouterr().out
    for stage in pipeline.PIPELINE_STAGES:
        assert re.search(rf"^  {stage} +done ", status, re.M), stage
    assert re.search(r"^  review +pending$", status, re.M)

    # 3. again -> all six stages skip, no AI call, no render; single commands print the same lines (AC7).
    assert _run(video, config) == 0
    out = capsys.readouterr()
    run_lines = out.out.splitlines()
    assert _states(out.out) == ["skipped (up to date)"] * 6 + ["done (2/2 Shorts)"]
    assert (sel.calls, ti.calls) == (1, 2)
    assert {p: (out_dir / "shorts" / p).read_bytes() for p in shorts} == sums
    single = [["ingest", str(video)], ["transcript", eid], ["analysis", eid], ["selection", eid],
              ["titling", eid, "--series", "Bài giảng", "--episode", "9"], ["render", eid]]
    for argv, expected in zip(single, run_lines[:6]):
        assert cli.main([*argv, "--config", str(config)]) == 0
        assert capsys.readouterr().out == expected + "\n"

    # 4. --force-from titling -> ingest..selection skip, titling + render re-run (AC6).
    assert _run(video, config, "--force-from", "titling") == 0
    assert _states(capsys.readouterr().out) == ["skipped (up to date)"] * 4 + EXPECTED_STATES[4:] + \
        ["done (2/2 Shorts)"]
    assert (sel.calls, ti.calls) == (1, 4)

    # 5. --force-from render + Ctrl-C during the encode -> exit 130, render failed "interrupted" (AC3).
    inject(selection_client=sel, titling_client=ti, render_runner=InterruptingRunner())
    assert _run(video, config, "--force-from", "render") == 130
    out = capsys.readouterr()
    assert "auto-short: interrupted during render; re-run the same command to resume" in out.err
    assert "Traceback" not in out.err
    render = _manifest(tmp_path, eid)["stages"]["render"]
    assert (render["status"], render["error"]) == ("failed", "interrupted")

    # 6. same command without --force-from -> earlier stages skip, render runs again.
    inject(selection_client=sel, titling_client=ti)
    assert _run(video, config) == 0
    assert _states(capsys.readouterr().out) == ["skipped (up to date)"] * 5 + ["rendered (2/2 clips)",
                                                                             "done (2/2 Shorts)"]
    assert {p: (out_dir / "shorts" / p).read_bytes() for p in shorts} == sums  # bitexact render (CP7)
