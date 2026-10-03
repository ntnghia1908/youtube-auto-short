#!/usr/bin/env python3
"""CP13 E1 - thi nghiem chat luong enhance tren CPU (VM), chay trong env `enhance-bench`.

Khong thuoc runtime project; chi la script do (nhu cp11_bench.py). Du lieu o
~/.cache/auto-short-cp13-test/ (khong ghi work/ / output/ chinh).

Lenh con:
  prep                     cat doan mau 10 s (lossless) + can chinh thoi gian ban cu / ban HD
  run <clip> <cfg>         enhance (so khung theo cfg) -> out/<clip>__<cfg>.mkv + <...>.json (thoi gian)
  metrics                  PSNR/SSIM/LPIPS (neu co dich), nhap nhay vung tinh, do net -> out/metrics.json
  compose                  video so sanh + anh crop mat / chu Han -> out/compare/
Doc BASE de doi thu muc.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enhance_bench_win as eb  # noqa: E402

BASE = Path(os.environ.get("BASE", Path.home() / ".cache/auto-short-cp13-test"))
WORK = Path("/home/ntnghia/youtube-auto-short/work")  # chi doc
CLIPS_DIR, OUT = BASE / "clips", BASE / "out"
FPS = 30000 / 1001
NF = 300

# ten: nguon, bat dau (s), dich (HD) neu co, kich thuoc ra, crop (x0,y0,x1,y1 theo ti le)
CLIPS = {
    "A": dict(src=BASE / "src/AH5jLu40RMs.mp4", start=None, hd=WORK / "2mVA5If4M3w/source.mp4", hd_start=1200.0,
              size=(1454, 1080), face=(0.42, 0.10, 0.66, 0.40), text=(0.28, 0.70, 0.72, 0.93),
              desc="AH5jLu40RMs 352x262 (ban cu) -> dich 2mVA5If4M3w 1454x1080 (HD kenh goc)"),
    "B": dict(src=WORK / "By0ZVJTPW3Y/source.mp4", start=600.0, size=(1440, 1080),
              face=(0.33, 0.08, 0.68, 0.55), text=(0.25, 0.82, 0.72, 0.93), desc="By0ZVJTPW3Y 960x720"),
    "C": dict(src=WORK / "6R3GE2On7Yc/source.mp4", start=600.0, size=(1440, 1080),
              face=(0.33, 0.12, 0.62, 0.50), text=(0.10, 0.80, 0.88, 0.94), desc="6R3GE2On7Yc 1440x1080 mo"),
    # E1b (Amendment 1): video cu chua xu ly, 640x480 (playlist Kinh Dia Tang, tap 1 va tap 100)
    "D": dict(src=BASE / "src/D_raw.mp4", start=0.0, size=(1440, 1080),
              face=(0.38, 0.12, 0.62, 0.40), text=(0.15, 0.82, 0.85, 0.94), desc="9NQFsvecC04 (tap 1) 640x480, 600 s"),
    "E": dict(src=BASE / "src/E_raw.mp4", start=0.0, size=(1440, 1080),
              face=(0.36, 0.12, 0.64, 0.42), text=(0.15, 0.82, 0.85, 0.94), desc="gXFNw1YTLmE (tap 100) 640x480, 1200 s"),
}
if os.environ.get("CLIPS_ONLY"):
    CLIPS = {k: v for k, v in CLIPS.items() if k in os.environ["CLIPS_ONLY"].split(",")}
# cfg: model, denoise, pre_h (0 = nguyen), so khung
CFGS = {
    "g10_p360": ("realesr-general-x4v3", 1.0, 360, 300),
    "g05_p360": ("realesr-general-x4v3", 0.5, 360, 300),
    "g10_p540": ("realesr-general-x4v3", 1.0, 540, 60),
    "x4p_p270": ("RealESRGAN_x4plus", None, 270, 60),
    "x2p_p540": ("RealESRGAN_x2plus", None, 540, 60),
}
# A (nguon 262p): khong ha khung
A_CFGS = {
    "g10": ("realesr-general-x4v3", 1.0, 0, 300),
    "g05": ("realesr-general-x4v3", 0.5, 0, 300),
    "x4p": ("RealESRGAN_x4plus", None, 0, 60),
    "x2p": ("RealESRGAN_x2plus", None, 0, 60),
}


# E1b: 640x480, khong ha (p0) va ha 360p; khong RRDB
DE_CFGS = {
    "g10_p0": ("realesr-general-x4v3", 1.0, 0, 300),
    "g10_p360": ("realesr-general-x4v3", 1.0, 360, 300),
    "g05_p360": ("realesr-general-x4v3", 0.5, 360, 300),
}


def cfgs_of(clip):
    return A_CFGS if clip == "A" else DE_CFGS if clip in ("D", "E") else CFGS


def sh(*a):
    subprocess.run([str(x) for x in a], check=True)


def read_all(path, n=None):
    cap = cv2.VideoCapture(str(path))
    fr = []
    while n is None or len(fr) < n:
        ok, f = cap.read()
        if not ok:
            break
        fr.append(f)
    cap.release()
    return fr


class Writer:
    def __init__(self, path, w, h):
        self.p = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
             "-r", f"{FPS}", "-i", "-", "-c:v", "ffv1", str(path)], stdin=subprocess.PIPE)

    def write(self, f):
        self.p.stdin.write(np.ascontiguousarray(f).tobytes())

    def close(self):
        self.p.stdin.close()
        self.p.wait()


def idle_wait(min_idle=0.8):
    """Cho CPU nhan roi (hang doi 8080 trong - khong co job nang khac) truoc moi luot."""
    def snap():
        v = [int(x) for x in open("/proc/stat").readline().split()[1:]]
        return v[3] + v[4], sum(v)
    while True:
        a = snap(); time.sleep(3); b = snap()
        idle = (b[0] - a[0]) / max(1, b[1] - a[1])
        if idle >= min_idle:
            return
        print(f"CPU ban (idle {idle:.2f}), cho 30 s...", flush=True)
        time.sleep(30)


def prep():
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    for name, c in CLIPS.items():
        if name == "A":
            hd_t = c["hd_start"]
            # lech ban cu - HD: ~0.55 s theo tuong quan am thanh (troi 0.55 -> 0.95 s qua ca tap),
            # khop khung (so khung HD da ha 176x131 voi ban cu, 300 khung) cho ~0.57 s
            old_t = hd_t + 0.57
            best = (None, None, old_t)
            sh("ffmpeg", "-v", "error", "-y", "-ss", f"{best[2]:.4f}", "-i", c["src"], "-an", "-frames:v", f"{NF}",
               "-c:v", "ffv1", CLIPS_DIR / "A.mkv")
            sh("ffmpeg", "-v", "error", "-y", "-ss", f"{hd_t}", "-i", c["hd"], "-an", "-frames:v", f"{NF}",
               "-c:v", "ffv1", CLIPS_DIR / "A_target.mkv")
            (CLIPS_DIR / "A_align.json").write_text(json.dumps(dict(hd_start=hd_t, old_start=best[2], offset_s=0.57)))
        else:
            sh("ffmpeg", "-v", "error", "-y", "-ss", f"{c['start']}", "-i", c["src"], "-an", "-frames:v", f"{NF}",
               "-c:v", "ffv1", CLIPS_DIR / f"{name}.mkv")
    (CLIPS_DIR / "tmp.png").unlink(missing_ok=True)


def run(clip, cfg):
    OUT.mkdir(parents=True, exist_ok=True)
    model, dn, pre_h, nf = cfgs_of(clip)[cfg]
    W, H = CLIPS[clip]["size"]
    torch.set_num_threads(int(os.environ.get("THREADS", "16")))
    net, scale = eb.load_model(model, BASE / "models", torch.device("cpu"), dn)
    frames = read_all(CLIPS_DIR / f"{clip}.mkv", nf)
    out = OUT / f"{clip}__{cfg}.mkv"
    w = Writer(out, W, H)
    idle_wait()
    t0 = time.perf_counter()
    for i, f in enumerate(frames):
        up = eb.process_frame(net, scale, f, torch.device("cpu"), pre_h, 0)
        if up.shape[1] != W or up.shape[0] != H:
            up = cv2.resize(up, (W, H), interpolation=cv2.INTER_AREA)
        w.write(up)
        if i % 10 == 0:
            print(f"{clip} {cfg} {i}/{len(frames)} {(time.perf_counter()-t0)/(i+1):.2f}s/f", flush=True)
    dt = time.perf_counter() - t0
    w.close()
    info = dict(clip=clip, cfg=cfg, model=model, denoise=dn, pre_h=pre_h, frames=len(frames), threads=torch.get_num_threads(),
                sec_per_frame=dt / len(frames), total_s=dt, in_size=f"{frames[0].shape[1]}x{frames[0].shape[0]}")
    (OUT / f"{clip}__{cfg}.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info), flush=True)


def baseline(clip):
    """Lanczos phong to thang ban goc len khung dich (doi chung)."""
    W, H = CLIPS[clip]["size"]
    p = OUT / f"{clip}__lanczos.mkv"
    if not p.exists():
        w = Writer(p, W, H)
        for f in read_all(CLIPS_DIR / f"{clip}.mkv"):
            w.write(cv2.resize(f, (W, H), interpolation=cv2.INTER_LANCZOS4))
        w.close()
    return p


def variants(clip):
    """[(nhan, duong dan, so khung)]"""
    v = [("Lanczos (goc)", baseline(clip), NF)]
    for cfg, (model, dn, pre, nf) in cfgs_of(clip).items():
        p = OUT / f"{clip}__{cfg}.mkv"
        if p.exists():
            v.append((cfg, p, nf))
    if clip == "A":
        v.append(("DICH HD kenh goc", CLIPS_DIR / "A_target.mkv", NF))
    return v


def _static_mask(frames):
    arr = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]).astype(np.float32)
    std = arr.std(axis=0)
    return cv2.erode((std < 2.0).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)


def flicker(frames, mask):
    g = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in frames]
    d = [np.abs(g[i + 1] - g[i])[mask].mean() for i in range(len(g) - 1)]
    return float(np.mean(d))


def sharp(frames):
    return float(np.mean([cv2.Laplacian(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() for f in frames[::10]]))


def metrics():
    from skimage.metrics import peak_signal_noise_ratio as psnr, structural_similarity as ssim
    try:
        import lpips
        lp = lpips.LPIPS(net="alex", verbose=False)
    except Exception as e:  # noqa: BLE001
        print("LPIPS khong co:", e)
        lp = None
    res = {}
    for clip in CLIPS:
        base_frames = read_all(baseline(clip))
        mask = _static_mask(base_frames)
        tgt = read_all(CLIPS_DIR / "A_target.mkv") if clip == "A" else None
        res[clip] = {"static_mask_frac": float(mask.mean())}
        for label, p, nf in variants(clip):
            fr = read_all(p, nf)
            n = len(fr)
            fl = flicker(fr, mask) if n > 1 else None
            fl_base = flicker(base_frames[:n], mask) if n > 1 else None  # cung doan khung de so cong bang
            m = dict(frames=n, flicker=fl, flicker_rel_lanczos=(fl / fl_base if fl_base else None), sharp_lap_var=sharp(fr))
            if tgt is not None and label != "DICH HD kenh goc":
                idx = list(range(0, n, 10))
                ps, ss, ls = [], [], []
                for i in idx:
                    ps.append(psnr(tgt[i], fr[i]))
                    ss.append(ssim(cv2.cvtColor(tgt[i], cv2.COLOR_BGR2GRAY), cv2.cvtColor(fr[i], cv2.COLOR_BGR2GRAY)))
                    if lp is not None:
                        t = lambda x: torch.from_numpy(cv2.cvtColor(x, cv2.COLOR_BGR2RGB)).permute(2, 0, 1)[None].float() / 127.5 - 1
                        with torch.no_grad():
                            ls.append(float(lp(t(tgt[i]), t(fr[i]))))
                m.update(psnr=float(np.mean(ps)), ssim=float(np.mean(ss)), lpips=float(np.mean(ls)) if ls else None)
            res[clip][label] = m
            print(clip, label, m, flush=True)
    for clip in CLIPS:  # them thoi gian CPU
        for cfg in cfgs_of(clip):
            j = OUT / f"{clip}__{cfg}.json"
            if j.exists():
                res[clip].setdefault(cfg, {})["sec_per_frame_cpu16"] = json.loads(j.read_text())["sec_per_frame"]
    (OUT / "metrics.json").write_text(json.dumps(res, indent=1))


def label(img, text):
    img = img.copy()
    cv2.rectangle(img, (0, 0), (min(img.shape[1], 14 + 11 * len(text)), 26), (0, 0, 0), -1)
    cv2.putText(img, text, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def compose():
    cmp_dir = OUT / "compare"
    cmp_dir.mkdir(exist_ok=True)
    for clip, c in CLIPS.items():
        W, H = c["size"]
        vs = [(l, read_all(p, nf)) for l, p, nf in variants(clip)]
        # anh crop khung 30: mat + chu Han
        for kind in ("face", "text"):
            x0, y0, x1, y1 = c[kind]
            tiles = []
            for l, fr in vs:
                f = fr[30]
                crop = f[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]
                tiles.append(label(cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST) if kind == "face" and crop.shape[0] < 400 else crop, l))
            hh = min(t.shape[0] for t in tiles)
            tiles = [cv2.resize(t, (int(t.shape[1] * hh / t.shape[0]), hh)) for t in tiles]
            cols = 2 if kind == "face" else 1
            rows = [np.hstack(tiles[i:i + cols]) if len(tiles[i:i + cols]) == cols else np.hstack(tiles[i:i + cols] + [np.zeros_like(tiles[0])] * (cols - len(tiles[i:i + cols]))) for i in range(0, len(tiles), cols)]
            wmax = max(r.shape[1] for r in rows)
            rows = [np.pad(r, ((0, 0), (0, wmax - r.shape[1]), (0, 0))) for r in rows]
            cv2.imwrite(str(cmp_dir / f"{clip}_{kind}.jpg"), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 92])
        # video so sanh: 10 s (cac cfg du 300 khung) va 2 s (tat ca)
        for tag, need in (("10s", NF), ("2s", 60)):
            sel = [(l, fr) for l, fr in vs if len(fr) >= need]
            if len(sel) < 2:
                continue
            cols = 2 if len(sel) <= 4 else 3
            pw, ph = 720, int(720 * H / W)
            nrows = -(-len(sel) // cols)
            tmp = cmp_dir / f"{clip}_{tag}.raw.mkv"
            wr = Writer(tmp, pw * cols, ph * nrows)
            for i in range(need):
                tiles = [label(cv2.resize(fr[i], (pw, ph), interpolation=cv2.INTER_AREA), l) for l, fr in sel]
                tiles += [np.zeros_like(tiles[0])] * (cols * nrows - len(tiles))
                wr.write(np.vstack([np.hstack(tiles[r * cols:(r + 1) * cols]) for r in range(nrows)]))
            wr.close()
            sh("ffmpeg", "-v", "error", "-y", "-i", tmp, "-c:v", "libx264", "-crf", "20", "-preset", "medium",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", cmp_dir / f"{clip}_compare_{tag}.mp4")
            tmp.unlink()


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "prep":
        prep()
    elif cmd == "run":
        run(sys.argv[2], sys.argv[3])
    elif cmd == "metrics":
        metrics()
    elif cmd == "compose":
        compose()
    else:
        sys.exit(__doc__)
