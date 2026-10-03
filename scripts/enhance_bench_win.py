#!/usr/bin/env python3
"""Do toc do enhance (Real-ESRGAN) tren CPU hoac GPU CUDA - CP13 E2.

Script doc lap: chi can Python + PyTorch + numpy + opencv-python-headless.
Khong can cai `realesrgan` / `basicsr` (kien truc mang duoc nap trong file nay,
nap truc tiep trong so chinh thuc `.pth`). Khong phu thuoc code cua project.
Khong mo cong / dich vu mang.

Vi du:
  python enhance_bench_win.py --device cuda --model realesr-general-x4v3 \
      --clip sample1.mp4 --frames 60 --tile 0 --fp16
  python enhance_bench_win.py --device cpu --model realesr-general-x4v3 \
      --clip sample1.mp4 --frames 4 --scale-to 720

Xem huong dan: docs/guides/enhance-gpu-windows.md
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# --------------------------------------------------------------------------
# Kien truc mang (rut gon tu Real-ESRGAN / basicsr, giu ten tham so de nap .pth)
# --------------------------------------------------------------------------


class SRVGGNetCompact(nn.Module):
    def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=16, upscale=4):
        super().__init__()
        self.upscale = upscale
        self.body = nn.ModuleList()
        self.body.append(nn.Conv2d(num_in_ch, num_feat, 3, 1, 1))
        self.body.append(nn.PReLU(num_parameters=num_feat))
        for _ in range(num_conv):
            self.body.append(nn.Conv2d(num_feat, num_feat, 3, 1, 1))
            self.body.append(nn.PReLU(num_parameters=num_feat))
        self.body.append(nn.Conv2d(num_feat, num_out_ch * upscale * upscale, 3, 1, 1))
        self.upsampler = nn.PixelShuffle(upscale)

    def forward(self, x):
        out = x
        for layer in self.body:
            out = layer(out)
        out = self.upsampler(out)
        return out + F.interpolate(x, scale_factor=self.upscale, mode="nearest")


class _RDB(nn.Module):
    def __init__(self, nf=64, gc=32):
        super().__init__()
        self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1)
        self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1)
        self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1)
        self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1)
        self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x):
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class _RRDB(nn.Module):
    def __init__(self, nf, gc=32):
        super().__init__()
        self.rdb1 = _RDB(nf, gc)
        self.rdb2 = _RDB(nf, gc)
        self.rdb3 = _RDB(nf, gc)

    def forward(self, x):
        return self.rdb3(self.rdb2(self.rdb1(x))) * 0.2 + x


class RRDBNet(nn.Module):
    def __init__(self, num_in_ch=3, num_out_ch=3, scale=4, num_feat=64, num_block=23, num_grow_ch=32):
        super().__init__()
        self.scale = scale
        if scale == 2:
            num_in_ch = num_in_ch * 4
        elif scale == 1:
            num_in_ch = num_in_ch * 16
        self.conv_first = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
        self.body = nn.Sequential(*[_RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
        self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x):
        if self.scale == 2:
            feat = F.pixel_unshuffle(x, 2)
        elif self.scale == 1:
            feat = F.pixel_unshuffle(x, 4)
        else:
            feat = x
        feat = self.conv_first(feat)
        feat = feat + self.conv_body(self.body(feat))
        feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
        feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
        return self.conv_last(self.lrelu(self.conv_hr(feat)))


# --------------------------------------------------------------------------
# Model registry + loader
# --------------------------------------------------------------------------

MODELS = {
    # ten: (file trong so, builder, scale)
    "realesr-general-x4v3": ("realesr-general-x4v3.pth", lambda: SRVGGNetCompact(num_conv=32, upscale=4), 4),
    "RealESRGAN_x4plus": ("RealESRGAN_x4plus.pth", lambda: RRDBNet(scale=4), 4),
    "RealESRGAN_x2plus": ("RealESRGAN_x2plus.pth", lambda: RRDBNet(scale=2), 2),
}


def _state(path: Path):
    sd = torch.load(path, map_location="cpu", weights_only=True)
    for k in ("params_ema", "params"):
        if k in sd:
            return sd[k]
    return sd


def load_model(name: str, models_dir: Path, device: torch.device, denoise: float | None = None):
    """Nap model. denoise (0..1) chi cho realesr-general-x4v3: tron voi ban wdn (0 = khu nhieu manh)."""
    fname, builder, scale = MODELS[name]
    net = builder()
    sd = _state(models_dir / fname)
    if name == "realesr-general-x4v3" and denoise is not None and denoise != 1.0:
        wdn = _state(models_dir / "realesr-general-wdn-x4v3.pth")
        sd = {k: sd[k] * denoise + wdn[k] * (1 - denoise) for k in sd}
    net.load_state_dict(sd, strict=True)
    return net.eval().to(device), scale


@torch.no_grad()
def enhance_tensor(net, scale: int, x: torch.Tensor, tile: int = 0, pad: int = 10, half: bool = False):
    """x: (1,3,H,W) float 0..1 tren dung device cua net. tile=0: ca khung."""
    if half:
        x = x.half()
    if tile <= 0:
        return net(x).float().clamp_(0, 1)
    _, c, h, w = x.shape
    out = torch.zeros((1, c, h * scale, w * scale), dtype=torch.float32, device=x.device)
    for y0 in range(0, h, tile):
        for x0 in range(0, w, tile):
            y1, x1 = min(y0 + tile, h), min(x0 + tile, w)
            ya, xa = max(y0 - pad, 0), max(x0 - pad, 0)
            yb, xb = min(y1 + pad, h), min(x1 + pad, w)
            o = net(x[:, :, ya:yb, xa:xb]).float()
            oy, ox = (y0 - ya) * scale, (x0 - xa) * scale
            out[:, :, y0 * scale:y1 * scale, x0 * scale:x1 * scale] = o[
                :, :, oy:oy + (y1 - y0) * scale, ox:ox + (x1 - x0) * scale
            ]
    return out.clamp_(0, 1)


def enhance_bgr(net, scale, img_bgr: np.ndarray, device, tile=0, half=False) -> np.ndarray:
    t = torch.from_numpy(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)).permute(2, 0, 1).float().div_(255).unsqueeze(0)
    out = enhance_tensor(net, scale, t.to(device), tile=tile, half=half)
    arr = (out[0].permute(1, 2, 0).cpu().numpy() * 255.0).round().astype(np.uint8)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def process_frame(net, scale, frame, device, pre_h: int, out_h: int, tile=0, half=False):
    """Ha khung ve cao pre_h (neu >0), enhance, dua ve cao out_h (Lanczos/Area)."""
    h, w = frame.shape[:2]
    if pre_h > 0 and pre_h != h:
        nw = int(round(w * pre_h / h / 2) * 2)
        frame = cv2.resize(frame, (nw, pre_h), interpolation=cv2.INTER_AREA if pre_h < h else cv2.INTER_CUBIC)
    up = enhance_bgr(net, scale, frame, device, tile=tile, half=half)
    uh, uw = up.shape[:2]
    if out_h > 0 and uh != out_h:
        nw = int(round(uw * out_h / uh / 2) * 2)
        up = cv2.resize(up, (nw, out_h), interpolation=cv2.INTER_AREA if out_h < uh else cv2.INTER_LANCZOS4)
    return up


# --------------------------------------------------------------------------
# Do thong so
# --------------------------------------------------------------------------


class _GpuPoll(threading.Thread):
    """Lay nhiet do / cong suat dinh qua nvidia-smi (neu co)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop = False
        self.temp_max = None
        self.power_max = None
        self.util_max = None

    def run(self):
        while not self.stop:
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=temperature.gpu,power.draw,utilization.gpu",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                ).stdout.strip().splitlines()[0]
                t, p, u = [float(v) for v in out.split(",")]
                self.temp_max = max(self.temp_max or t, t)
                self.power_max = max(self.power_max or p, p)
                self.util_max = max(self.util_max or u, u)
            except Exception:
                return
            time.sleep(1.0)


def read_frames(path: str, n: int, start: float = 0.0):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        sys.exit(f"Khong mo duoc video: {path}")
    if start > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    frames = []
    while len(frames) < n:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    if not frames:
        sys.exit("Video khong co khung hinh.")
    return frames


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="auto", help="cuda | cpu | auto (mac dinh: cuda neu co)")
    ap.add_argument("--model", default="realesr-general-x4v3", choices=sorted(MODELS))
    ap.add_argument("--models-dir", default="models", help="thu muc chua file .pth")
    ap.add_argument("--clip", required=True, help="video mau (mp4)")
    ap.add_argument("--start", type=float, default=0.0, help="giay bat dau doc")
    ap.add_argument("--frames", type=int, default=30, help="so khung do (khong tinh khung khoi dong)")
    ap.add_argument("--warmup", type=int, default=2, help="so khung khoi dong (khong tinh gio)")
    ap.add_argument("--scale-to", type=int, default=0, help="ha khung ve cao N px truoc khi enhance (0 = giu nguyen)")
    ap.add_argument("--out-height", type=int, default=1080, help="cao khung ket qua (0 = giu dau ra cua model)")
    ap.add_argument("--tile", type=int, default=0, help="kich thuoc tile (0 = ca khung; dat 256/400 neu het VRAM)")
    ap.add_argument("--fp16", action="store_true", help="dung half precision (chi cuda)")
    ap.add_argument("--denoise", type=float, default=None, help="0..1, chi realesr-general-x4v3")
    ap.add_argument("--threads", type=int, default=0, help="so luong CPU (mac dinh cpu: 16)")
    ap.add_argument("--save-frame", default="", help="luu khung cuoi ra file png de xem")
    ap.add_argument("--json", action="store_true", help="in them mot dong JSON de dan ve")
    a = ap.parse_args(argv)

    dev = a.device
    if dev == "auto":
        dev = "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cuda" and not torch.cuda.is_available():
        sys.exit("CUDA khong kha dung (cai PyTorch ban CUDA - xem huong dan).")
    device = torch.device(dev)
    if dev == "cpu":
        torch.set_num_threads(a.threads or min(16, os.cpu_count() or 1))
    half = a.fp16 and dev == "cuda"
    if a.fp16 and not half:
        print("Canh bao: --fp16 chi co tac dung tren cuda; bo qua.")
    torch.backends.cudnn.benchmark = dev == "cuda"

    info = {
        "python": platform.python_version(), "torch": torch.__version__, "os": platform.platform(),
        "device": dev, "gpu": torch.cuda.get_device_name(0) if dev == "cuda" else platform.processor() or "cpu",
        "model": a.model, "denoise": a.denoise, "tile": a.tile, "fp16": half, "scale_to": a.scale_to,
        "out_height": a.out_height, "clip": Path(a.clip).name,
    }
    t0 = time.time()
    net, scale = load_model(a.model, Path(a.models_dir), device, a.denoise)
    if half:
        net = net.half()
    info["load_s"] = round(time.time() - t0, 2)

    frames = read_frames(a.clip, a.frames + a.warmup, a.start)
    info["in_size"] = f"{frames[0].shape[1]}x{frames[0].shape[0]}"
    poll = None
    if dev == "cuda":
        torch.cuda.reset_peak_memory_stats()
        poll = _GpuPoll()
        poll.start()

    def sync():
        if dev == "cuda":
            torch.cuda.synchronize()

    out = None
    for f in frames[: a.warmup]:
        out = process_frame(net, scale, f, device, a.scale_to, a.out_height, a.tile, half)
    sync()
    meas = frames[a.warmup:] or frames[:1]
    t0 = time.perf_counter()
    for f in meas:
        out = process_frame(net, scale, f, device, a.scale_to, a.out_height, a.tile, half)
    sync()
    dt = time.perf_counter() - t0
    if poll:
        poll.stop = True
    n = len(meas)
    info.update(frames_measured=n, sec_per_frame=round(dt / n, 3), fps=round(n / dt, 3),
                out_size=f"{out.shape[1]}x{out.shape[0]}")
    if dev == "cuda":
        info["vram_peak_mb"] = round(torch.cuda.max_memory_allocated() / 2**20)
        info["vram_reserved_peak_mb"] = round(torch.cuda.max_memory_reserved() / 2**20)
        if poll:
            info.update(temp_max_c=poll.temp_max, power_max_w=poll.power_max, util_max_pct=poll.util_max)
    if a.save_frame:
        cv2.imwrite(a.save_frame, out)

    print("=== KET QUA ===")
    for k, v in info.items():
        print(f"{k}: {v}")
    # uoc luong: 1 tap 1 gio (30000/1001 fps)
    hour = 3600 * 30000 / 1001
    print(f"uoc luong 1 tap 1 gio ({hour:.0f} khung): {hour * dt / n / 3600:.1f} gio")
    if a.json:
        print("JSON " + json.dumps(info, ensure_ascii=False))
    return info


if __name__ == "__main__":
    main()
