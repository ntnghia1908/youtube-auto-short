#!/usr/bin/env python3
"""CP13.3 - so sanh ket qua enhance_quality_bench.py: chi so + video canh nhau + anh crop + montage.

Chay trong env `enhance-bench` (VM). Du lieu: ~/.cache/auto-short-cp133-test/ (doc BASE de doi).
  metrics                 -> results/metrics.json + results/metrics.md
  compose                 -> compare/<clip>_<nhom>.mp4, <clip>_<nhom>_face.jpg, <clip>_text.jpg
  montage "<clip>:<spec>,<spec>,...;<clip>:..."  -> results/best_candidates.mp4 (<= 30 s, < 50 MB)
Ten file ket qua: out/<clip>__<spec>.(mkv|mp4); doan goc: clips/<clip>.mkv; dich: clips/A_target.mkv.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

BASE = Path(os.environ.get("BASE", Path.home() / ".cache/auto-short-cp133-test"))
OUT, CLIPS, CMP, RES = BASE / "out", BASE / "clips", BASE / "compare", BASE / "results"
FPS = 30000 / 1001
NF = int(os.environ.get("NF", "90"))
SIZE = {"A": (1454, 1080), "D": (1440, 1080), "E": (1440, 1080)}
# vung mat / chu (ti le x0,y0,x1,y1) - nhu CP13
FACE = {"A": (0.42, 0.10, 0.66, 0.40), "D": (0.38, 0.12, 0.62, 0.40), "E": (0.36, 0.12, 0.64, 0.42)}
TEXT = {"A": (0.28, 0.70, 0.72, 0.93), "D": (0.15, 0.82, 0.85, 0.94), "E": (0.15, 0.82, 0.85, 0.94)}
GROUPS = {
    "size_denoise": ["lanczos", "cur", "g100_p0", "g075_p0", "g050_p0"],
    "color": ["cur", "cur+col1", "cur+col2", "cur+col3", "g100_p0+col2"],
    "face": ["cur", "cur+gfp", "cur+cf50", "cur+cf80", "cur+cf50s", "g100_p0+cf50"],
    "video": ["cur", "g100_p0", "rbvsr_p360", "rbvsr_p0"],
}


def sh(*a):
    subprocess.run([str(x) for x in a], check=True)


def read_all(path, n=NF):
    cap = cv2.VideoCapture(str(path))
    fr = []
    while len(fr) < n:
        ok, f = cap.read()
        if not ok:
            break
        fr.append(f)
    cap.release()
    return fr


def spec_path(clip, spec):
    for ext in ("mkv", "mp4"):
        p = OUT / f"{clip}__{spec}.{ext}"
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def specs_of(clip):
    out = []
    for p in sorted(OUT.glob(f"{clip}__*")):
        m = re.fullmatch(rf"{clip}__(.+)\.(mkv|mp4)", p.name)
        if m and "." not in m.group(1) and not p.name.endswith(".base.json"):
            out.append(m.group(1))
    return out


def lanczos(clip):
    W, H = SIZE[clip]
    return [cv2.resize(f, (W, H), interpolation=cv2.INTER_LANCZOS4) for f in read_all(CLIPS / f"{clip}.mkv")]


def static_mask(frames):
    arr = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]).astype(np.float32)
    return cv2.erode((arr.std(axis=0) < 2.0).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)


def box_mask(clip, kind="face"):
    W, H = SIZE[clip]
    x0, y0, x1, y1 = (FACE if kind == "face" else TEXT)[clip]
    m = np.zeros((H, W), bool)
    m[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)] = True
    return m


def flicker(frames, mask):
    g = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in frames]
    return float(np.mean([np.abs(g[i + 1] - g[i])[mask].mean() for i in range(len(g) - 1)]))


def sharp(frames, mask=None):
    v = []
    for f in frames[::10]:
        lap = cv2.Laplacian(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), cv2.CV_64F)
        v.append(lap[mask].var() if mask is not None else lap.var())
    return float(np.mean(v))


def crop(f, clip, kind):
    W, H = SIZE[clip]
    x0, y0, x1, y1 = (FACE if kind == "face" else TEXT)[clip]
    return f[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]


def metrics():
    import lpips
    lp = lpips.LPIPS(net="alex", verbose=False)

    def t(x):
        return torch.from_numpy(cv2.cvtColor(np.ascontiguousarray(x), cv2.COLOR_BGR2RGB)).permute(2, 0, 1)[None].float() / 127.5 - 1

    def lpv(a, b):
        with torch.no_grad():
            return float(lp(t(a), t(b)))

    RES.mkdir(exist_ok=True)
    res = {}
    for clip in SIZE:
        specs = specs_of(clip)
        if not specs:
            continue
        lz = lanczos(clip)
        smask, fmask = static_mask(lz), box_mask(clip, "face")
        tgt = read_all(CLIPS / "A_target.mkv") if clip == "A" else None
        cur = read_all(spec_path(clip, "cur")) if spec_path(clip, "cur") else None
        res[clip] = {}
        base_s, base_f = {}, {}
        for spec in ["lanczos"] + specs:
            fr = lz if spec == "lanczos" else read_all(spec_path(clip, spec))
            n = len(fr)
            if n < 10:
                continue
            fl_s, fl_f = flicker(fr, smask), flicker(fr, fmask)
            ref_s, ref_f = flicker(lz[:n], smask), flicker(lz[:n], fmask)
            m = dict(frames=n, flicker_static=fl_s, flicker_static_rel=fl_s / ref_s, flicker_face=fl_f,
                     flicker_face_rel=fl_f / ref_f, sharp_face=sharp(fr, fmask))
            idx = list(range(0, n, 10))
            if tgt is not None:
                m["lpips_target"] = float(np.mean([lpv(tgt[i], fr[i]) for i in idx]))
                m["lpips_target_face"] = float(np.mean([lpv(crop(tgt[i], clip, "face"), crop(fr[i], clip, "face")) for i in idx]))
            if cur is not None and spec != "cur":
                m["lpips_vs_cur_face"] = float(np.mean([lpv(crop(cur[i], clip, "face"), crop(fr[i], clip, "face")) for i in idx if i < len(cur)]))
            jp = OUT / f"{clip}__{spec}.mkv.json"
            if not jp.exists():
                jp = OUT / f"{clip}__{spec}.mp4.json"
            if jp.exists():
                j = json.loads(jp.read_text())
                m.update(cpu_s_per_frame=j["sec_per_frame"], cpu_s_base=j["sec_per_frame_base"], cpu_s_post=j["sec_per_frame_post"],
                         threads=j.get("threads"), loadavg=j.get("loadavg"))
            res[clip][spec] = m
            print(clip, spec, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()}, flush=True)
        if tgt is not None:
            n = len(tgt)
            res[clip]["TARGET_HD"] = dict(frames=n, flicker_static=flicker(tgt, smask), flicker_static_rel=flicker(tgt, smask) / flicker(lz[:n], smask),
                                         flicker_face=flicker(tgt, fmask), flicker_face_rel=flicker(tgt, fmask) / flicker(lz[:n], fmask),
                                         sharp_face=sharp(tgt, fmask))
    (RES / "metrics.json").write_text(json.dumps(res, indent=1))
    lines = []
    for clip, d in res.items():
        lines += [f"### {clip}", "", "| spec | nhap nhay tinh (x Lanczos) | nhap nhay mat (x Lanczos) | do net mat | LPIPS dich | LPIPS dich (mat) | LPIPS mat vs cur | CPU s/khung (nen+hau ky) |",
                  "|---|---|---|---|---|---|---|---|"]
        for spec, m in d.items():
            f = lambda k, p=3: ("" if m.get(k) is None else f"{m[k]:.{p}f}")  # noqa: E731
            lines.append(f"| `{spec}` | {f('flicker_static_rel', 2)} | {f('flicker_face_rel', 2)} | {f('sharp_face', 0)} | {f('lpips_target')} | "
                         f"{f('lpips_target_face')} | {f('lpips_vs_cur_face')} | {f('cpu_s_per_frame', 2)} ({f('cpu_s_base', 2)}+{f('cpu_s_post', 2)}) |")
        lines.append("")
    (RES / "metrics.md").write_text("\n".join(lines))


def label(img, text):
    img = img.copy()
    cv2.rectangle(img, (0, 0), (min(img.shape[1], 12 + 10 * len(text)), 24), (0, 0, 0), -1)
    cv2.putText(img, text, (5, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def variants(clip, names, with_target=True):
    v = []
    lz = None
    for s in names:
        if s == "lanczos":
            lz = lz or lanczos(clip)
            v.append((s, lz))
        else:
            p = spec_path(clip, s)
            if p:
                v.append((s, read_all(p)))
    if clip == "A" and with_target:
        v.append(("TARGET_HD_kenh", read_all(CLIPS / "A_target.mkv")))
    return v


def grid(tiles, cols):
    rows = []
    for i in range(0, len(tiles), cols):
        r = tiles[i:i + cols]
        r += [np.zeros_like(tiles[0])] * (cols - len(r))
        rows.append(np.hstack(r))
    return np.vstack(rows)


class Writer:
    def __init__(self, path, w, h, fps=FPS, crf=22):
        self.p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-",
                                   "-threads", "4", "-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)],
                                  stdin=subprocess.PIPE)

    def write(self, f):
        self.p.stdin.write(np.ascontiguousarray(f).tobytes())

    def close(self):
        self.p.stdin.close()
        self.p.wait()


def compose():
    CMP.mkdir(exist_ok=True)
    for clip in SIZE:
        if not specs_of(clip):
            continue
        W, H = SIZE[clip]
        for gname, names in GROUPS.items():
            vs = variants(clip, names)
            if len(vs) < 3:
                continue
            n = min(len(f) for _, f in vs)
            pw = 640
            ph = int(pw * H / W)
            cols = 3
            wr = Writer(CMP / f"{clip}_{gname}.mp4", pw * cols, ph * (-(-len(vs) // cols)))
            for i in range(n):
                wr.write(grid([label(cv2.resize(f[i], (pw, ph), interpolation=cv2.INTER_AREA), s) for s, f in vs], cols))
            wr.close()
            # anh crop sat mat (khung 30), phong x1.5
            if 30 < n:
                tiles = []
                for s, f in vs:
                    c = crop(f[30], clip, "face")
                    tiles.append(label(cv2.resize(c, (560, int(560 * c.shape[0] / c.shape[1])), interpolation=cv2.INTER_CUBIC), s))
                cv2.imwrite(str(CMP / f"{clip}_{gname}_crop.jpg"), grid(tiles, 3), [cv2.IMWRITE_JPEG_QUALITY, 92])
        # chu: cac cau hinh chinh
        vs = variants(clip, ["lanczos", "cur", "g100_p0", "cur+col2"])
        if len(vs) >= 3 and len(vs[0][1]) > 30:
            tiles = []
            for s, f in vs:
                c = crop(f[30], clip, "text")
                tiles.append(label(cv2.resize(c, (900, int(900 * c.shape[0] / c.shape[1])), interpolation=cv2.INTER_CUBIC), s))
            cv2.imwrite(str(CMP / f"{clip}_text.jpg"), grid(tiles, 2), [cv2.IMWRITE_JPEG_QUALITY, 92])


def card(lines, w, h):
    img = np.zeros((h, w, 3), np.uint8)
    y = 60
    for i, t in enumerate(lines):
        cv2.putText(img, t, (30, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9 if i == 0 else 0.7, (255, 255, 255), 2 if i == 0 else 1, cv2.LINE_AA)
        y += 48 if i == 0 else 40
    return img


LEGEND = ["CP13.3 best candidates (face close-up, 4 tiles / clip)",
          "cur = current (g10, down to 360p, then x4)",
          "g100_p0 = no 360p downscale (x4 from source)",
          "gfp = + GFPGAN v1.4 face restore (Apache-2.0)",
          "cf50 = + CodeFormer w=0.5 (NON-commercial licence)",
          "TARGET_HD_kenh = channel HD version (clip A only)",
          "Faces are re-generated: judge likeness, not only sharpness"]


def montage(arg, loops=2):
    """arg: 'D:cur,g100_p0,cur+cf50;E:...' - luoi 2x2 cat sat mat, moi doan lap `loops` lan; the tieu de 3 s; crf 26, < 30 s."""
    RES.mkdir(exist_ok=True)
    tw, th = 640, 400  # mot o
    segs = []
    for part in arg.split(";"):
        clip, names = part.split(":")
        segs.append((clip, variants(clip, names.split(","), with_target=True)))
    wr = Writer(RES / "best_candidates.mp4", tw * 2, th * 2, crf=26)
    c = card(LEGEND, tw * 2, th * 2)
    for _ in range(90):
        wr.write(c)
    for clip, vs in segs:
        n = min(len(f) for _, f in vs)
        W, H = SIZE[clip]
        x0, y0, x1, y1 = FACE[clip]
        cx0, cy0, cx1, cy1 = max(0, x0 - 0.08), y0, min(1, x1 + 0.08), min(1, y1 + 0.14)
        for _ in range(loops):
            for i in range(n):
                tiles = []
                for s, f in vs[:4]:
                    cr = f[i][int(cy0 * H):int(cy1 * H), int(cx0 * W):int(cx1 * W)]
                    cr = cv2.resize(cr, (tw, th), interpolation=cv2.INTER_AREA if cr.shape[1] > tw else cv2.INTER_CUBIC)
                    tiles.append(label(cr, f"{clip} {s}"))
                wr.write(grid(tiles, 2))
    wr.close()
    p = RES / "best_candidates.mp4"
    print(p, p.stat().st_size / 1e6, "MB")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "metrics":
        metrics()
    elif cmd == "compose":
        compose()
    elif cmd == "montage":
        montage(sys.argv[2])
    else:
        sys.exit(__doc__)
