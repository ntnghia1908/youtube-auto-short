"""CP8.33: spec (G2, G4, G10), ffmpeg assembly (G3), chapters / names / description (G7) with tiny lavfi clips."""

from __future__ import annotations

import json
import subprocess

import pytest

from auto_short import compilation as comp
from auto_short.compilation import CompilationError, Item, store
from auto_short.config import Config, from_dict

from compilation_helpers import duration_of, frame_color, make_clip, probe_json

A, B, C = Item("aaaaaaaaaa1.kt", "k01"), Item("bbbbbbbbbb2.kt", "k01"), Item("cccccccccc3.kt", "k01")


def test_config_default_and_limits():
    assert Config().compilation.max_minutes == 720
    assert from_dict({"compilation": {"max_minutes": 60}}).compilation.max_minutes == 60
    for bad in (0, 721, "x", True):
        with pytest.raises(Exception):
            from_dict({"compilation": {"max_minutes": bad}})


# --- AC2 / AC4 / AC10: spec -----------------------------------------------------------------------------------

def test_loop_count_and_limits():
    assert comp.loop_count(100, 30) == 18  # ceil(1800 / 100)
    assert comp.loop_count(90, 30) == 20
    spec = comp.build_loop(A, 100.0, 30, 720)
    assert spec.repeat == 18 and len(spec.items) == 18
    with pytest.raises(CompilationError):
        comp.build_loop(A, 100.0, 0, 720)
    with pytest.raises(CompilationError):
        comp.build_loop(A, 100.0, 721, 720)
    with pytest.raises(CompilationError):  # n * d beyond the maximum
        comp.build_loop(A, 700.0, 719, 720)  # n = 62, 62 * 700 s = 723 min


def test_cid_stable_and_distinct():
    s1 = comp.build_concat([A, B], {A: 5, B: 6}, 720)
    s2 = comp.build_concat([A, B], {A: 5, B: 6}, 720)
    s3 = comp.build_concat([A, C], {A: 5, C: 6}, 720)
    assert s1.cid == s2.cid and len(s1.cid) == 12 and s1.cid != s3.cid
    with pytest.raises(CompilationError):
        comp.build_concat([A], {A: 5}, 720)  # fewer than two
    with pytest.raises(CompilationError):
        comp.build_concat([A, A], {A: 5}, 720)  # duplicate


def test_auto_round_robin_stops_at_target_without_cutting():
    d = {A: 60.0, B: 60.0, C: 90.0}
    items, rounds = comp.auto_plan([A, B, C], d, 5, 720)  # 300 s: A B C A B C = 420 > ... stops at first >= 300
    assert items == [A, B, C, A, B] and rounds == 2  # 60 + 60 + 90 + 60 + 60 = 330
    one, rounds = comp.auto_plan([A], d, 3, 720)  # one favourite: repeated until >= 180 s
    assert one == [A, A, A] and rounds == 3
    longer, rounds = comp.auto_plan([C, A, B], d, 1, 720)  # the list alone is longer than T: no wrap, last not cut
    assert longer == [C] and rounds == 1
    with pytest.raises(CompilationError):
        comp.auto_plan([], d, 5, 720)
    spec, _ = comp.build_auto([A, B], {A: 60.0, B: 60.0}, 2, 720)
    assert spec.mode == "auto" and spec.items == (A, B) and spec.cid == comp.Spec("concat", (A, B)).cid


# --- AC1 / AC2 / AC3: assembly ----------------------------------------------------------------------------------

def test_concat_copy_order_duration_and_params(tmp_path):
    clips = [make_clip(tmp_path / "r.mp4", "red", 2), make_clip(tmp_path / "g.mp4", "green", 3),
             make_clip(tmp_path / "b.mp4", "blue", 2)]
    out = tmp_path / "out" / "x.mp4"
    res = comp.assemble(clips, out)
    assert not res.reencoded and out.is_file()
    total = sum(duration_of(c) for c in clips)
    assert abs(duration_of(out) - total) <= 0.1 and abs(res.duration - total) <= 0.1
    v = next(s for s in probe_json(out)["streams"] if s["codec_type"] == "video")
    src = next(s for s in probe_json(clips[0])["streams"] if s["codec_type"] == "video")
    assert (v["codec_name"], v["width"], v["height"], v["r_frame_rate"]) == \
        (src["codec_name"], src["width"], src["height"], src["r_frame_rate"])
    starts = [0.0, duration_of(clips[0]), duration_of(clips[0]) + duration_of(clips[1])]
    assert [frame_color(out, t + 0.5) for t in starts] == ["r", "g", "b"]
    assert list(out.parent.iterdir()) == [out]  # no temp left


def test_loop_repeats_same_file(tmp_path):
    clip = make_clip(tmp_path / "r.mp4", "red", 2)
    out = tmp_path / "loop.mp4"
    res = comp.assemble([clip] * 4, out)
    assert abs(duration_of(out) - 4 * duration_of(clip)) <= 0.1 and res.parts == (res.parts[0],) * 4


def test_incompatible_inputs_reencode(tmp_path):
    a = make_clip(tmp_path / "a.mp4", "red", 2)
    b = make_clip(tmp_path / "b.mp4", "green", 2, size="200x356", rate="30")
    out = tmp_path / "o" / "mix.mp4"
    res = comp.assemble([a, b], out, comp.Encode(crf=30, preset="ultrafast"))
    assert res.reencoded
    streams = probe_json(out)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    au = next(s for s in streams if s["codec_type"] == "audio")
    assert (v["codec_name"], v["pix_fmt"], v["width"], v["height"]) == ("h264", "yuv420p", 160, 284)
    assert (au["codec_name"], au["sample_rate"], au["channels"]) == ("aac", "48000", 2)
    assert abs(duration_of(out) - 4.0) <= 0.3
    assert frame_color(out, 0.5) == "r" and frame_color(out, 3.5) == "g"
    assert list(out.parent.iterdir()) == [out]


def test_failure_leaves_no_temp_and_no_output(tmp_path):
    a = make_clip(tmp_path / "a.mp4", "red", 1)
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    out = tmp_path / "o" / "x.mp4"
    with pytest.raises(CompilationError):
        comp.assemble([a, bad], out)
    assert list(out.parent.iterdir()) == []

    def boom(cmd):
        if cmd[0] == "ffmpeg":
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        return comp.run_command(cmd)

    with pytest.raises(CompilationError, match="boom"):
        comp.assemble([a, a], out, runner=boom)
    assert list(out.parent.iterdir()) == []


def test_concat_list_escaping(tmp_path):
    from auto_short.compilation.assemble import list_line
    assert list_line(tmp_path / "it's.mp4") == f"file '{tmp_path}/it'\\''s.mp4'\n"
    with pytest.raises(CompilationError):
        list_line(tmp_path / "a\nb.mp4")


# --- AC7: chapters, names, description -------------------------------------------------------------------------------

def test_timecode_chapters_description_and_names():
    assert comp.meta.timecode(0) == "00:00" and comp.meta.timecode(65.9) == "01:05"
    assert comp.meta.timecode(3600) == "1:00:00" and comp.meta.timecode(3725) == "1:02:05"
    ch = comp.meta.chapters(["Một", "Hai", "Ba"], [60.0, 125.5, 10])
    assert [c["start"] for c in ch] == [0.0, 60.0, 185.5]
    text = comp.meta.description("concat", ch, None, ["#A", "#B"])
    assert text == "00:00 Một\n01:00 Hai\n03:05 Ba\n\n#A #B"
    assert comp.meta.description("loop", [], "Tiêu đề", ["#A"]) == "Tiêu đề\n\n#A"
    assert comp.meta.description("concat", ch[:1], None, []) == "00:00 Một"
    assert comp.meta.concat_name("Địa Tạng", "3", "9", 4) == "Địa Tạng - Khai thị T3-T9 (4 đoạn).mp4"
    assert comp.meta.concat_name("Địa Tạng", "5", "5", 2) == "Địa Tạng - Khai thị T5 (2 đoạn).mp4"
    assert comp.meta.concat_name("Địa Tạng", "3", "9", 4, kinds={"short"}) == "Địa Tạng - Short T3-T9 (4 đoạn).mp4"
    assert comp.meta.concat_name("Địa Tạng", "3", "9", 4, kinds={"short", "khaithi"}) == "Địa Tạng - Short + Khai thị T3-T9 (4 đoạn).mp4"
    assert comp.meta.loop_name("Địa Tạng", "T3_KT02", 12) == "Địa Tạng - T3_KT02 lặp 12 lần.mp4"
    assert comp.meta.loop_name(None, "T3_KT02", 2, fallback="PLx") == "PLx - T3_KT02 lặp 2 lần.mp4"


def test_store_favorites_and_docs(tmp_path):
    folder = store.directory(tmp_path, "PLx1234567")
    assert store.read_favorites(folder) == []
    store.write_favorites(folder, [A, B])
    assert store.read_favorites(folder) == [A, B]
    doc = store.new_doc("PLx1234567", "0123456789ab", "concat", (A, B), 1, download_name="n.mp4", title=None,
                        duration_estimate=4.0)
    store.write_doc(folder, doc)
    assert store.read_doc(folder, "0123456789ab")["status"] == "queued"
    assert store.read_doc(folder, "../x") is None
    store.video_path(folder, "0123456789ab").write_bytes(b"x")
    assert store.delete(folder, "0123456789ab") and not store.delete(folder, "0123456789ab")
    (folder / "favorites.json").write_text("{", encoding="utf-8")
    with pytest.raises(CompilationError):
        store.read_favorites(folder)
