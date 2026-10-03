"""Mang SRVGGNetCompact + nap trong so `realesr-general-x4v3` (CP13.1a E4).

Sao chep co rut gon tu `scripts/enhance_bench_win.py` (CP13), vốn rút gọn từ
Real-ESRGAN / basicsr; giữ tên tham số để nạp được `.pth` chính thức.
Chi can torch (khong can `realesrgan` / `basicsr`).
"""
from __future__ import annotations

from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

MODEL_NAME = "realesr-general-x4v3"
MODEL_FILE = "realesr-general-x4v3.pth"
MODEL_WDN_FILE = "realesr-general-wdn-x4v3.pth"
SCALE = 4


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


def _state(path: Path):
    sd = torch.load(path, map_location="cpu", weights_only=True)
    for k in ("params_ema", "params"):
        if k in sd:
            return sd[k]
    return sd


def load_net(models_dir: Path, denoise: float = 1.0) -> SRVGGNetCompact:
    """Nap model (CPU, fp32, eval). denoise 0..1: tron voi ban wdn (1.0 = chi ban chinh)."""
    net = SRVGGNetCompact(num_conv=32, upscale=SCALE)
    sd = _state(Path(models_dir) / MODEL_FILE)
    if denoise != 1.0:
        wdn = _state(Path(models_dir) / MODEL_WDN_FILE)
        sd = {k: sd[k] * denoise + wdn[k] * (1 - denoise) for k in sd}
    net.load_state_dict(sd, strict=True)
    return net.eval()
