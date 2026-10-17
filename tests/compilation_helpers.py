"""CP8.33 test helpers: tiny lavfi clips (no real data) and a bộ kinh whose khai thị episodes carry them."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from auto_short import khaithi
from auto_short.khaithi import KhaiThi
from auto_short.workspace import Workspace

from web_helpers import write_episode

PL = "PLcompilation001"
COLORS = {"red": "0xff0000", "green": "0x00ff00", "blue": "0x0000ff", "white": "0xffffff"}


def make_clip(path: Path, color: str = "red", seconds: float = 2.0, size: str = "160x284", rate: str = "25",
              freq: int = 440, ar: int = 48000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c={COLORS[color]}:size={size}:rate={rate}:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate={ar}:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-shortest", str(path)],
                   check=True)
    return path


def probe_json(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def duration_of(path: Path) -> float:
    return float(probe_json(path)["format"]["duration"])


def frame_color(path: Path, at: float) -> str:
    """Dominant channel (r / g / b / w) of the frame at ``at`` seconds."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1", "-vf",
                          "scale=2:2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    r, g, b = raw[0], raw[1], raw[2]
    if min(r, g, b) > 200:
        return "w"
    return "rgb"[max(range(3), key=lambda i: (r, g, b)[i])]


def make_series(cfg, tmp_path: Path, spec: list[tuple], *, series="Bộ thử", playlist_id: str = PL) -> None:
    """``spec`` = [(video_id, episode number, [(color, seconds), ...] khai thị clips[, [(color, seconds), ...] Short
    clips])]: a khai thị episode ``<video_id>.kt`` whose clips ``k01``, ... are real mp4 files, optionally a Short
    episode ``<video_id>`` (clips ``s01``, ...), plus the stored bộ kinh listing the videos."""
    entries = []
    for i, (vid, number, clips, *rest) in enumerate(spec, 1):
        kid = vid + khaithi.SUFFIX
        for eid, kind_clips, prefix, label, is_kt in ((kid, clips, "k", "Khai thị", True),
                                                      (vid, rest[0] if rest else [], "s", "Short", False)):
            if not kind_clips:
                continue
            names = tuple(f"{prefix}{n:02d}" for n in range(1, len(kind_clips) + 1))
            write_episode(cfg, eid, clips=names, titles={n: f"{label} {number}.{j}" for j, n in enumerate(names, 1)})
            ws = Workspace(Path(cfg.workspace.dir), eid)
            if is_kt:
                khaithi.write(ws.dir, KhaiThi(vid, 4, 7))
            (ws.dir / "titles.json").write_text(json.dumps({"header": {"fields": {"episode": number, "series": series}}}),
                                                encoding="utf-8")
            for name, (color, seconds) in zip(names, kind_clips):
                make_clip(Path(cfg.render.output_dir) / eid / "shorts" / f"{name}.mp4", color, seconds)
        entries.append({"index": i, "video_id": vid, "title": f"Tập {number}", "duration": 3000.0, "episode": number,
                        "available": True})
    root = Path(cfg.workspace.dir) / "_playlists"
    root.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "playlist_id": playlist_id, "title": "Danh sách thử",
           "url": f"https://www.youtube.com/playlist?list={playlist_id}", "fetched_at": "2026-10-01T00:00:00Z",
           "entries": entries, "series": series}
    (root / f"{playlist_id}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
