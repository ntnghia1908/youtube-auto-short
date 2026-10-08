#!/usr/bin/env python3
"""CP13.3 - thi nghiem chat luong enhance: ha khung, mau, phuc hoi mat, model video.

Chay duoc tren CPU (VM) va GPU CUDA (Windows). Doc lap voi code project; chi can
`enhance_bench_win.py` nam cung thu muc (kien truc Real-ESRGAN / SRVGG) va cac goi pip
trong docs/guides/enhance-quality-gpu-windows.md (torch, opencv, numpy, gfpgan, facexlib,
basicsr). Khong mo cong / dich vu mang (chi `fetch` tai trong so tu GitHub / OpenMMLab).

Lenh con:
  fetch   --models-dir M                 tai trong so + file kien truc CodeFormer
  run     --clip C.mp4 --name D --specs "cur,g100_p0,cur+gfp" --out O [--frames 90]
  list                                    in cac spec mau

Spec = <nen>[+<hau ky>...]:
  nen:     lanczos | cur (= g100_p360, cau hinh dang chay that) | g<NNN>_p<H>
           (model realesr-general-x4v3, denoise NNN/100, ha khung cao H, H=0 giu nguyen)
           | rbvsr_p<H> (RealBasicVSR, model video; chay ca doan mot lan)
  hau ky:  col1 | col2 | col3      chinh mau (bao hoa / tuong phan / gamma, xem COLOR)
           gfp | gfp50             GFPGAN v1.4 (thay mat 100 % / tron 50 %)
           cf50 | cf80             CodeFormer fidelity 0.5 / 0.8
           (them chu `s` sau gfp/cf: lam muot toa do mat giua cac khung, vd cf50s)
Vi du: --specs "cur,g100_p0,g075_p0,cur+col2,cur+cf50,g100_p0+gfp50+col1"

Moi spec ghi <out>/<name>__<spec>.mkv (ffv1, mac dinh) hoac .mp4 (--codec x264) kem .json
(s/khung tung phan, VRAM dinh, thiet bi, loadavg). Cac spec cung nen dung chung phan enhance nen.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import types
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enhance_bench_win as eb  # noqa: E402

COLOR = {  # (bao hoa, tuong phan quanh 0.5, gamma)
    "col1": (1.15, 1.00, 1.00),
    "col2": (1.30, 1.05, 1.00),
    "col3": (1.50, 1.10, 0.95),
}

# ten file: (url, thu muc con trong models-dir)
WEIGHTS = {
    "realesr-general-x4v3.pth": ("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth", ""),
    "realesr-general-wdn-x4v3.pth": ("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-wdn-x4v3.pth", ""),
    "GFPGANv1.4.pth": ("https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth", ""),
    "codeformer.pth": ("https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth", ""),
    "detection_Resnet50_Final.pth": ("https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth", "facexlib/weights"),
    "parsing_parsenet.pth": ("https://github.com/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth", "facexlib/weights"),
    "realbasicvsr.pth": ("https://download.openmmlab.com/mmediting/restorers/real_basicvsr/realbasicvsr_c64b20_1x30x8_lr5e-5_150k_reds_20211104-52f77c2c.pth", ""),
}
# Kien truc CodeFormer (S-Lab License 1.0, phi thuong mai): chi tai ve may nguoi chay, khong dua vao repo
CF_ARCH = {
    "codeformer_arch.py": "https://raw.githubusercontent.com/sczhou/CodeFormer/master/basicsr/archs/codeformer_arch.py",
    "vqgan_arch.py": "https://raw.githubusercontent.com/sczhou/CodeFormer/master/basicsr/archs/vqgan_arch.py",
}


# --------------------------------------------------------------------------
# Tuong thich: basicsr moi cai ban torchvision moi
# --------------------------------------------------------------------------

def _shim_basicsr():
    """basicsr 1.4.2 import `torchvision.transforms.functional_tensor` (da bi go) va op CUDA DCN."""
    try:
        import torchvision.transforms.functional_tensor  # noqa: F401
    except ImportError:
        import torchvision.transforms.functional as F
        m = types.ModuleType("torchvision.transforms.functional_tensor")
        m.rgb_to_grayscale = F.rgb_to_grayscale
        sys.modules["torchvision.transforms.functional_tensor"] = m
    if "basicsr.ops.dcn" not in sys.modules:
        import torchvision

        class ModulatedDeformConvPack(nn.Module):
            """Thay the op CUDA cua basicsr bang torchvision.ops.deform_conv2d (chay ca CPU)."""

            def __init__(self, in_channels, out_channels, kernel_size, stride=1, padding=0, dilation=1,
                         groups=1, deformable_groups=1, bias=True, **_):
                super().__init__()
                k = (kernel_size, kernel_size) if isinstance(kernel_size, int) else tuple(kernel_size)
                self.in_channels, self.out_channels = in_channels, out_channels
                self.kernel_size, self.stride = k, (stride, stride) if isinstance(stride, int) else stride
                self.padding = (padding, padding) if isinstance(padding, int) else padding
                self.dilation = (dilation, dilation) if isinstance(dilation, int) else dilation
                self.groups, self.deformable_groups = groups, deformable_groups
                self.weight = nn.Parameter(torch.zeros(out_channels, in_channels // groups, *k))
                self.bias = nn.Parameter(torch.zeros(out_channels))

        pkg = types.ModuleType("basicsr.ops.dcn")
        pkg.ModulatedDeformConvPack = ModulatedDeformConvPack

        def _unused(name):  # cac ten khac chi duoc import, khong duoc dung
            if name.startswith("__"):
                raise AttributeError(name)
            return type(name, (nn.Module,), {})

        pkg.__getattr__ = _unused
        sys.modules["basicsr.ops.dcn"] = pkg
        _ = torchvision


# --------------------------------------------------------------------------
# ffmpeg / video I/O
# --------------------------------------------------------------------------

def ffmpeg_path() -> str:
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("Khong tim thay ffmpeg (cai: pip install imageio-ffmpeg, hoac dua ffmpeg vao PATH).")


class Writer:
    def __init__(self, path: Path, w: int, h: int, fps: float, codec: str):
        if codec == "ffv1":
            enc = ["-c:v", "ffv1"]
        else:  # x264 chat luong cao, du de so mat; khong dung cho do nhap nhay chinh xac
            enc = ["-c:v", "libx264", "-crf", "12", "-preset", "fast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        self.p = subprocess.Popen(
            [ffmpeg_path(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
             "-r", f"{fps}", "-i", "-", *enc, str(path)], stdin=subprocess.PIPE)

    def write(self, f):
        self.p.stdin.write(np.ascontiguousarray(f).tobytes())

    def close(self):
        self.p.stdin.close()
        self.p.wait()


def read_frames(path, start, n):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        sys.exit(f"Khong mo duoc video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30000 / 1001
    if start:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    out = []
    while len(out) < n:
        ok, f = cap.read()
        if not ok:
            break
        out.append(f)
    cap.release()
    if not out:
        sys.exit("Video khong co khung hinh.")
    return out, fps


# --------------------------------------------------------------------------
# Hau ky
# --------------------------------------------------------------------------

def color_grade(img: np.ndarray, sat: float, con: float, gam: float) -> np.ndarray:
    x = img.astype(np.float32) / 255.0
    gray = (0.114 * x[..., 0] + 0.587 * x[..., 1] + 0.299 * x[..., 2])[..., None]  # BGR
    x = gray + sat * (x - gray)
    x = (x - 0.5) * con + 0.5
    x = np.clip(x, 0, 1) ** gam
    return (np.clip(x, 0, 1) * 255.0 + 0.5).astype(np.uint8)


class FaceRestorer:
    """Phuc hoi mat GFPGAN v1.4 / CodeFormer; chi vung mat, dan lai vao khung enhance (facexlib)."""

    def __init__(self, kind: str, models_dir: Path, device, fidelity: float = 0.5, blend: float = 1.0,
                 smooth: bool = False, half: bool = False):
        _shim_basicsr()
        from facexlib.utils.face_restoration_helper import FaceRestoreHelper
        self.kind, self.device, self.blend, self.smooth, self.fid = kind, device, blend, smooth, fidelity
        self.helper = FaceRestoreHelper(1, face_size=512, crop_ratio=(1, 1), det_model="retinaface_resnet50",
                                        save_ext="png", use_parse=True, device=device,
                                        model_rootpath=str(models_dir))
        self.prev = None
        self.det_max = 640  # do mat tren ban thu nho (nhanh), roi nhan toa do len
        self.faces_found = 0
        self.frames = 0
        if kind == "gfp":
            from gfpgan.archs.gfpganv1_clean_arch import GFPGANv1Clean
            net = GFPGANv1Clean(out_size=512, num_style_feat=512, channel_multiplier=2, decoder_load_path=None,
                                fix_decoder=False, num_mlp=8, input_is_latent=True, different_w=True,
                                narrow=1, sft_half=True)
            sd = torch.load(models_dir / "GFPGANv1.4.pth", map_location="cpu", weights_only=True)
            net.load_state_dict(sd.get("params_ema", sd), strict=True)
        else:
            sys.path.insert(0, str(models_dir / "codeformer_arch"))
            from codeformer_arch import CodeFormer  # file tai bang `fetch`
            net = CodeFormer(dim_embd=512, codebook_size=1024, n_head=8, n_layers=9,
                             connect_list=["32", "64", "128", "256"])
            sd = torch.load(models_dir / "codeformer.pth", map_location="cpu", weights_only=True)
            net.load_state_dict(sd.get("params_ema", sd), strict=True)
        self.net = net.eval().to(device)
        self.half = half and device.type == "cuda"
        if self.half:
            self.net = self.net.half()

    def _detect(self, img):
        h, w = img.shape[:2]
        k = min(1.0, self.det_max / max(h, w))
        small = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA) if k < 1 else img
        helper = self.helper
        helper.clean_all()
        helper.read_image(small)
        n = helper.get_face_landmarks_5(only_keep_largest=True, eye_dist_threshold=5)
        if not n or not helper.all_landmarks_5:
            return None
        return np.asarray(helper.all_landmarks_5[0], dtype=np.float32) / k

    @torch.no_grad()
    def __call__(self, img: np.ndarray) -> np.ndarray:
        self.frames += 1
        lm = self._detect(img)
        if lm is None:
            self.prev = None
            return img
        if self.smooth and self.prev is not None:
            lm = 0.6 * self.prev + 0.4 * lm
        self.prev = lm
        self.faces_found += 1
        helper = self.helper
        helper.clean_all()
        helper.read_image(img)
        helper.all_landmarks_5 = [lm]
        helper.align_warp_face()
        face = helper.cropped_faces[0]
        t = torch.from_numpy(cv2.cvtColor(face, cv2.COLOR_BGR2RGB)).permute(2, 0, 1).float().div_(127.5).sub_(1)
        t = t.unsqueeze(0).to(self.device)
        if self.half:
            t = t.half()
        out = self.net(t, return_rgb=False)[0] if self.kind == "gfp" else self.net(t, w=self.fid, adain=True)[0]
        r = ((out.float().clamp_(-1, 1)[0] + 1) * 127.5).round().byte().permute(1, 2, 0).cpu().numpy()
        r = cv2.cvtColor(r, cv2.COLOR_RGB2BGR)
        if self.blend < 1.0:
            r = cv2.addWeighted(r, self.blend, face, 1 - self.blend, 0)
        helper.add_restored_face(r)
        helper.get_inverse_affine(None)
        return helper.paste_faces_to_input_image()


def make_post(tok: str, models_dir: Path, device, half: bool):
    """Tra ve ham BGR->BGR cho mot hau ky."""
    if tok in COLOR:
        s, c, g = COLOR[tok]
        return lambda f: color_grade(f, s, c, g)
    m = re.fullmatch(r"(gfp|cf)(\d*)(s?)", tok)
    if not m:
        sys.exit(f"hau ky khong hop le: {tok}")
    kind, num, smooth = m.groups()
    if kind == "gfp":
        return FaceRestorer("gfp", models_dir, device, blend=(int(num) / 100 if num else 1.0), smooth=bool(smooth), half=half)
    if not num:
        sys.exit("cf can fidelity: cf50 / cf80")
    return FaceRestorer("cf", models_dir, device, fidelity=int(num) / 100, smooth=bool(smooth), half=half)


# --------------------------------------------------------------------------
# Nen enhance
# --------------------------------------------------------------------------

def parse_base(base: str):
    if base == "cur":
        base = "g100_p360"
    if base == "lanczos":
        return ("lanczos", None, 0)
    m = re.fullmatch(r"g(\d{3})_p(\d+)", base)
    if m:
        return ("g", int(m.group(1)) / 100, int(m.group(2)))
    m = re.fullmatch(r"rbvsr_p(\d+)", base)
    if m:
        return ("rbvsr", None, int(m.group(1)))
    sys.exit(f"nen khong hop le: {base}")


def load_rbvsr(models_dir: Path, device):
    """RealBasicVSR = image_cleaning (20 khoi) + BasicVSR (20 khoi moi nhanh; basicsr, khong can DCN)."""
    _shim_basicsr()
    from basicsr.archs.basicvsr_arch import BasicVSR, ConvResidualBlocks
    sd = torch.load(models_dir / "realbasicvsr.pth", map_location="cpu", weights_only=False)["state_dict"]
    sd = {k[len("generator_ema."):]: v for k, v in sd.items() if k.startswith("generator_ema.")}

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.image_cleaning = nn.Sequential(ConvResidualBlocks(3, 64, 20), nn.Conv2d(64, 3, 3, 1, 1))
            self.vsr = BasicVSR(num_feat=64, num_block=20)

        @torch.no_grad()
        def forward(self, x):  # (1,T,3,h,w) 0..1 RGB
            n, t, c, h, w = x.shape
            flat = x.view(-1, c, h, w)
            flat = (flat + self.image_cleaning(flat)).clamp_(0, 1)  # mot luot lam sach (nguong tinh lai cua ban goc)
            return self.vsr(flat.view(n, t, c, h, w))

    mapped = {}
    for k, v in sd.items():
        if k.startswith("image_cleaning."):
            mapped[k] = v
            continue
        k = k[len("basicvsr."):]
        k = re.sub(r"^spynet\.basic_module\.(\d+)\.basic_module\.(\d+)\.conv\.",
                   lambda m: f"spynet.basic_module.{m.group(1)}.basic_module.{int(m.group(2)) * 2}.", k)
        k = (k.replace("backward_resblocks.", "backward_trunk.").replace("forward_resblocks.", "forward_trunk.")
             .replace("upsample1.upsample_conv.", "upconv1.").replace("upsample2.upsample_conv.", "upconv2."))
        mapped["vsr." + k] = v
    net = Net()
    net.load_state_dict(mapped, strict=True)
    return net.eval().to(device)


def resize_to(img, w, h):
    if img.shape[1] == w and img.shape[0] == h:
        return img
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA if img.shape[0] > h else cv2.INTER_LANCZOS4)


def pre_resize(f, pre_h):
    h, w = f.shape[:2]
    if pre_h and pre_h != h:
        nw = int(round(w * pre_h / h / 2) * 2)
        return cv2.resize(f, (nw, pre_h), interpolation=cv2.INTER_AREA if pre_h < h else cv2.INTER_CUBIC)
    return f


def sync(dev):
    if dev.type == "cuda":
        torch.cuda.synchronize()


def loadavg():
    try:
        return [round(x, 1) for x in os.getloadavg()]
    except (AttributeError, OSError):
        return None


def run(a):
    dev = torch.device("cuda" if (a.device == "auto" and torch.cuda.is_available()) or a.device == "cuda" else "cpu")
    if dev.type == "cuda" and not torch.cuda.is_available():
        sys.exit("CUDA khong kha dung.")
    if dev.type == "cpu":
        torch.set_num_threads(a.threads or min(16, os.cpu_count() or 1))
    half = dev.type == "cuda" and not a.no_fp16
    torch.backends.cudnn.benchmark = dev.type == "cuda"
    models_dir, out_dir = Path(a.models_dir), Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames, fps = read_frames(a.clip, a.start_frame, a.frames)
    H0, W0 = frames[0].shape[:2]
    if a.out_size:
        ow, oh = (int(v) for v in a.out_size.lower().split("x"))
    else:
        oh = a.out_height
        ow = int(round(W0 * oh / H0 / 2) * 2)
    ext = "mkv" if a.codec == "ffv1" else "mp4"
    print(f"clip {a.name}: {len(frames)} khung {W0}x{H0} -> {ow}x{oh}, thiet bi {dev}", flush=True)

    # nhom spec theo nen
    groups: dict[str, list[str]] = {}
    for spec in [s.strip() for s in a.specs.split(",") if s.strip()]:
        base = spec.split("+")[0]
        base = "g100_p360" if base == "cur" else base
        groups.setdefault(base, []).append(spec)

    gpu = torch.cuda.get_device_name(0) if dev.type == "cuda" else (platform.processor() or "cpu")
    for base, specs in groups.items():
        kind, dn, pre_h = parse_base(base)
        reuse = Path(a.reuse_base) / f"{a.name}__{base}.mkv" if a.reuse_base else None
        reuse_json = reuse.with_suffix(".json") if reuse else None
        if reuse and reuse.exists() and reuse.stat().st_size > 0:
            enhanced, _ = read_frames(reuse, 0, len(frames))
            base_spf = json.loads(reuse_json.read_text())["sec_per_frame"] if reuse_json.exists() else None
            base_note = f"nen doc lai tu {reuse.name}"
            enhanced = [resize_to(f, ow, oh) for f in enhanced]
        else:
            if dev.type == "cuda":
                torch.cuda.reset_peak_memory_stats()
            tb = []
            if kind == "lanczos":
                enhanced = []
                for f in frames:
                    t0 = time.perf_counter()
                    enhanced.append(cv2.resize(f, (ow, oh), interpolation=cv2.INTER_LANCZOS4))
                    tb.append(time.perf_counter() - t0)
            elif kind == "g":
                net, scale = eb.load_model("realesr-general-x4v3", models_dir, dev, dn)
                if half:
                    net = net.half()
                enhanced = []
                for i, f in enumerate(frames):
                    sync(dev)
                    t0 = time.perf_counter()
                    up = eb.process_frame(net, scale, f, dev, pre_h, oh, 0, half)
                    enhanced.append(resize_to(up, ow, oh))
                    sync(dev)
                    tb.append(time.perf_counter() - t0)
                    if i % 10 == 0:
                        print(f"  {base} {i}/{len(frames)} {np.mean(tb):.2f} s/khung", flush=True)
            else:  # rbvsr
                net = load_rbvsr(models_dir, dev)
                if half:
                    net = net.half()
                small = [pre_resize(f, pre_h) for f in frames]
                chunk = a.rbvsr_chunk or len(small)
                enhanced = []
                sync(dev)
                t0 = time.perf_counter()
                for c0 in range(0, len(small), chunk):
                    seg = small[c0:c0 + chunk]
                    x = torch.from_numpy(np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in seg])).permute(0, 3, 1, 2)
                    x = x.float().div_(255).unsqueeze(0).to(dev)
                    if half:
                        x = x.half()
                    y = net(x).float().clamp_(0, 1)[0]
                    for j in range(y.shape[0]):
                        arr = (y[j].permute(1, 2, 0).cpu().numpy() * 255 + 0.5).astype(np.uint8)
                        enhanced.append(resize_to(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), ow, oh))
                    print(f"  {base} {len(enhanced)}/{len(small)} khung ({time.perf_counter() - t0:.0f} s)", flush=True)
                sync(dev)
                tb = [(time.perf_counter() - t0) / len(frames)] * len(frames)
            base_spf = float(np.mean(tb[1:] if len(tb) > 1 and kind != "rbvsr" else tb))
            base_note = ""
        base_vram = round(torch.cuda.max_memory_allocated() / 2**20) if dev.type == "cuda" else None
        for spec in specs:
            posts = [make_post(t, models_dir, dev, half) for t in spec.split("+")[1:]]
            fname = out_dir / f"{a.name}__{spec}.{ext}"
            w = Writer(fname, ow, oh, fps, a.codec)
            tp = []
            if dev.type == "cuda":
                torch.cuda.reset_peak_memory_stats()
            for i, f in enumerate(enhanced):
                sync(dev)
                t0 = time.perf_counter()
                g = f
                for p in posts:
                    g = p(g)
                sync(dev)
                tp.append(time.perf_counter() - t0)
                w.write(g)
                if posts and i % 10 == 0:
                    print(f"  {spec} hau ky {i}/{len(enhanced)} {np.mean(tp):.2f} s/khung", flush=True)
            w.close()
            post_spf = float(np.mean(tp[1:] if len(tp) > 1 else tp)) if posts else 0.0
            info = dict(
                clip=a.name, spec=spec, base=base, frames=len(frames), start_frame=a.start_frame, in_size=f"{W0}x{H0}",
                out_size=f"{ow}x{oh}", device=dev.type, gpu=gpu, torch=torch.__version__, os=platform.platform(),
                threads=torch.get_num_threads() if dev.type == "cpu" else None, fp16=half, loadavg=loadavg(),
                sec_per_frame_base=base_spf, sec_per_frame_post=post_spf,
                sec_per_frame=(base_spf or 0) + post_spf, base_note=base_note,
                vram_peak_mb=max(base_vram or 0, round(torch.cuda.max_memory_allocated() / 2**20) if dev.type == "cuda" else 0) or None,
                faces_found=[getattr(p, "faces_found", None) for p in posts if isinstance(p, FaceRestorer)],
            )
            Path(str(fname) + ".json").write_text(json.dumps(info, indent=1))
            print("JSON " + json.dumps(info, ensure_ascii=False), flush=True)
            for p in posts:
                if isinstance(p, FaceRestorer):
                    p.helper.clean_all()
        if base_spf is not None and not base_note:
            Path(out_dir / f"{a.name}__{base}.base.json").write_text(json.dumps(dict(sec_per_frame=base_spf, base=base)))


def fetch(a):
    d = Path(a.models_dir)
    d.mkdir(parents=True, exist_ok=True)

    def get(url, dest):
        if dest.exists() and dest.stat().st_size > 1000:
            print("co san:", dest.name)
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        print("tai:", url, flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "enhance-quality-bench"})
        with urllib.request.urlopen(req, timeout=120) as r, open(str(dest) + ".part", "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        os.replace(str(dest) + ".part", dest)

    for name, (url, sub) in WEIGHTS.items():
        if a.skip_rbvsr and name == "realbasicvsr.pth":
            continue
        get(url, d / sub / name if sub else d / name)
    for name, url in CF_ARCH.items():
        dest = d / "codeformer_arch" / name
        get(url, dest)
        txt = dest.read_text(encoding="utf-8")
        txt = txt.replace("from basicsr.archs.vqgan_arch import *", "from vqgan_arch import *")
        dest.write_text(txt, encoding="utf-8")
    print("xong:", d)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--models-dir", default="models")
    f.add_argument("--skip-rbvsr", action="store_true", help="bo qua trong so RealBasicVSR (148 MB)")
    r = sub.add_parser("run")
    r.add_argument("--clip", required=True)
    r.add_argument("--name", required=True, help="nhan doan (A, D, E...)")
    r.add_argument("--specs", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--models-dir", default="models")
    r.add_argument("--start-frame", type=int, default=0)
    r.add_argument("--frames", type=int, default=90)
    r.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    r.add_argument("--threads", type=int, default=0, help="so luong CPU (mac dinh toi da 16)")
    r.add_argument("--no-fp16", action="store_true")
    r.add_argument("--out-height", type=int, default=1080)
    r.add_argument("--out-size", default="", help="WxH, vd 1454x1080 (de khop doan dich)")
    r.add_argument("--codec", default="ffv1", choices=["ffv1", "x264"])
    r.add_argument("--reuse-base", default="", help="thu muc chua <name>__<nen>.mkv da enhance (chi de bo qua tinh lai tren VM)")
    r.add_argument("--rbvsr-chunk", type=int, default=0, help="xu ly rbvsr theo luot N khung (0 = ca doan)")
    sub.add_parser("list")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        fetch(a)
    elif a.cmd == "run":
        run(a)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
