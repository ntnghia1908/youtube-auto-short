"""Phuc hoi mat GFPGAN v1.4 cho worker enhance (CP13.4 G2).

Chay SAU mang SRVGG, tren khung da enhance (BGR uint8, kich thuoc dich): do mat (facexlib RetinaFace) -> can 512 ->
GFPGAN v1.4 -> tron voi mat goc theo `weight` -> dan lai co mat na parsing. Cung thuat toan voi `FaceRestorer(kind="gfp")`
cua `scripts/enhance_quality_bench.py` (CP13.3, mau `cur+gfp`).

Dependency (chi trong env cua worker, KHONG vao project): gfpgan, facexlib (+ basicsr do gfpgan keo vao). Trong so
khong bao gio tai luc chay: `setup-enhance-worker.ps1` tai + kiem sha256 vao `models/`.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

FACE_MODEL = "gfpgan_v1.4"
CAPABILITY = f"face:{FACE_MODEL}"
# ten file -> duong dan trong models_dir (facexlib doc `models/facexlib/weights/`)
WEIGHTS = {
    "GFPGANv1.4.pth": "GFPGANv1.4.pth",
    "detection_Resnet50_Final.pth": "facexlib/weights/detection_Resnet50_Final.pth",
    "parsing_parsenet.pth": "facexlib/weights/parsing_parsenet.pth",
}
DET_MAX = 640  # do mat tren ban thu nho (nhanh), roi nhan toa do len


def missing_weights(models_dir: Path) -> list[str]:
    return [rel for rel in WEIGHTS.values() if not (Path(models_dir) / rel).is_file()]


def support_problem(models_dir: Path) -> str:
    """'' khi may nay lam duoc buoc mat (goi pip + trong so co du), nguoc lai ly do (tieng Viet, ngan)."""
    for mod in ("gfpgan", "facexlib", "basicsr"):
        try:
            if importlib.util.find_spec(mod) is None:
                return f"thieu goi Python '{mod}' (chay lai setup-enhance-worker.ps1)"
        except (ImportError, ValueError):
            return f"khong nap duoc goi '{mod}'"
    miss = missing_weights(models_dir)
    if miss:
        return "thieu trong so: " + ", ".join(miss) + " (chay lai setup-enhance-worker.ps1)"
    return ""


def shim_basicsr() -> None:
    """basicsr 1.4.2 import `torchvision.transforms.functional_tensor` (da bi go) va op CUDA DCN (khong build duoc tren
    Windows): thay bang ban tuong duong. Chi nhung ten gfpgan / facexlib can de import."""
    import torch
    import torch.nn as nn
    try:
        import torchvision.transforms.functional_tensor  # noqa: F401
    except ImportError:
        import torchvision.transforms.functional as F
        m = types.ModuleType("torchvision.transforms.functional_tensor")
        m.rgb_to_grayscale = F.rgb_to_grayscale
        sys.modules["torchvision.transforms.functional_tensor"] = m
    if "basicsr.ops.dcn" not in sys.modules:
        class ModulatedDeformConvPack(nn.Module):
            def __init__(self, in_channels, out_channels, kernel_size, stride=1, padding=0, dilation=1,
                         groups=1, deformable_groups=1, bias=True, **_):
                super().__init__()
                k = (kernel_size, kernel_size) if isinstance(kernel_size, int) else tuple(kernel_size)
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


def np_stack(arrs):
    import numpy as np
    return np.stack(arrs)


class SparseFace:
    """G5: do mat thua. Do moc o khung 0, N, 2N.. cua doan; khung giua noi suy tuyen tinh moc giua hai lan do (khi ca hai
    lan do deu co mat; thieu mat o mot dau -> do tung khung nhu cu); gom batch GFPGAN. `every` = 1 -> do moi khung.
    Dung mot ban moi doan: `push(frame)` tra cac khung da xong (dung thu tu, co the tre toi N-1 khung), `flush()` tra not."""

    def __init__(self, restorer: FaceRestorer, every: int = 1, batch: int = 8):
        self.r, self.every, self.batch = restorer, max(1, int(every)), batch
        self.n = 0
        self.last = None        # moc lan do truoc (None = khong co mat) hoac chua co lan do nao
        self.have_last = False
        self.pending = []       # khung giua hai lan do

    def _detect_each(self, frames):
        return [self.r.landmarks(f) for f in frames]

    def push(self, frame):
        i = self.n
        self.n += 1
        if self.every == 1:
            return self.r.restore_frames([frame], [self.r.landmarks(frame)], 1)
        if i % self.every != 0:
            self.pending.append(frame)
            return []
        lm = self.r.landmarks(frame)
        frames = self.pending + [frame]
        if self.pending and self.have_last and self.last is not None and lm is not None:
            m = len(self.pending) + 1
            lms = [self.last + (lm - self.last) * ((k + 1) / m) for k in range(len(self.pending))] + [lm]
        else:
            lms = self._detect_each(self.pending) + [lm]
        self.pending, self.last, self.have_last = [], lm, True
        return self.r.restore_frames(frames, lms, self.batch)

    def flush(self):
        frames, self.pending = self.pending, []
        if not frames:
            return []
        return self.r.restore_frames(frames, self._detect_each(frames), self.batch)


class FaceRestorer:
    """Mot lan nap, goi tren tung khung: `restorer(frame_bgr) -> frame_bgr` (cung kich thuoc). Khong thread-safe (moi
    luong mot ban)."""

    def __init__(self, models_dir: Path, device: str, weight: float = 1.0, half: bool = False):
        import torch
        shim_basicsr()
        from facexlib.utils.face_restoration_helper import FaceRestoreHelper
        from gfpgan.archs.gfpganv1_clean_arch import GFPGANv1Clean
        miss = missing_weights(models_dir)
        if miss:
            raise RuntimeError("thieu trong so mat: " + ", ".join(miss))
        self.torch = torch
        self.device = torch.device(device)
        self.weight = float(weight)
        self.half = bool(half) and self.device.type == "cuda"
        self.helper = FaceRestoreHelper(1, face_size=512, crop_ratio=(1, 1), det_model="retinaface_resnet50",
                                        save_ext="png", use_parse=True, device=self.device,
                                        model_rootpath=str(models_dir))
        net = GFPGANv1Clean(out_size=512, num_style_feat=512, channel_multiplier=2, decoder_load_path=None,
                            fix_decoder=False, num_mlp=8, input_is_latent=True, different_w=True,
                            narrow=1, sft_half=True)
        sd = torch.load(Path(models_dir) / "GFPGANv1.4.pth", map_location="cpu", weights_only=True)
        net.load_state_dict(sd.get("params_ema", sd), strict=True)
        self.net = net.eval().to(self.device)
        if self.half:
            self.net = self.net.half()
        self.on_device = True
        self.frames = 0
        self.faces_found = 0

    # -- E7: nhuong VRAM cho Ollama (giong mang SRVGG) --
    def _modules(self):
        return [m for m in (self.net, getattr(self.helper, "face_det", None), getattr(self.helper, "face_parse", None))
                if m is not None]

    def offload(self) -> None:
        if self.device.type != "cuda" or not self.on_device:
            return
        for m in self._modules():
            m.to("cpu")
        self.on_device = False

    def reload(self) -> None:
        if self.device.type != "cuda" or self.on_device:
            return
        for m in self._modules():
            m.to(self.device)
        self.on_device = True

    def _detect(self, img):
        import cv2
        import numpy as np
        h, w = img.shape[:2]
        k = min(1.0, DET_MAX / max(h, w))
        small = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA) if k < 1 else img
        helper = self.helper
        helper.clean_all()
        helper.read_image(small)
        n = helper.get_face_landmarks_5(only_keep_largest=True, eye_dist_threshold=5)
        if not n or not helper.all_landmarks_5:
            return None
        return np.asarray(helper.all_landmarks_5[0], dtype=np.float32) / k

    # -- cac buoc tach roi (G5: do thua + gom batch) --
    def landmarks(self, img):
        """5 diem moc cua mat lon nhat (float32 (5,2)) hoac None."""
        with self.torch.no_grad():
            lm = self._detect(img)
        self.helper.clean_all()
        return lm

    def _crop(self, img, lm):
        helper = self.helper
        helper.clean_all()
        helper.read_image(img)
        helper.all_landmarks_5 = [lm]
        helper.align_warp_face()
        face = helper.cropped_faces[0]
        helper.clean_all()
        return face

    def restore_faces(self, crops, batch: int = 8):
        """GFPGAN tren cac mat cat 512x512 (BGR uint8), gom batch; tra danh sach mat da phuc hoi (BGR uint8)."""
        import cv2
        torch = self.torch
        out = []
        with torch.no_grad():
            for k in range(0, len(crops), max(1, batch)):
                part = crops[k:k + batch]
                t = torch.from_numpy(np_stack([cv2.cvtColor(c, cv2.COLOR_BGR2RGB) for c in part])).permute(0, 3, 1, 2)
                t = t.float().div_(127.5).sub_(1).contiguous().to(self.device)
                if self.half:
                    t = t.half()
                y = self.net(t, return_rgb=False)[0]
                y = ((y.float().clamp_(-1, 1) + 1) * 127.5).round().byte().permute(0, 2, 3, 1).cpu().numpy()
                for r, c in zip(y, part):
                    r = cv2.cvtColor(r, cv2.COLOR_RGB2BGR)
                    out.append(cv2.addWeighted(r, self.weight, c, 1 - self.weight, 0) if self.weight < 1.0 else r)
        return out

    def _paste(self, img, lm, restored):
        helper = self.helper
        helper.clean_all()
        helper.read_image(img)
        helper.all_landmarks_5 = [lm]
        helper.align_warp_face()
        helper.add_restored_face(restored)
        helper.get_inverse_affine(None)
        result = helper.paste_faces_to_input_image()
        helper.clean_all()
        return result

    def restore_frames(self, frames, lms, batch: int = 8):
        """Phuc hoi mat cho `frames` voi moc `lms` (None = khong co mat: giu nguyen khung)."""
        idx = [k for k, lm in enumerate(lms) if lm is not None]
        self.frames += len(frames)
        self.faces_found += len(idx)
        out = list(frames)
        for k0 in range(0, len(idx), max(1, batch)):
            part = idx[k0:k0 + batch]
            with self.torch.no_grad():
                crops = [self._crop(frames[k], lms[k]) for k in part]
                restored = self.restore_faces(crops, batch)
                for k, r in zip(part, restored):
                    out[k] = self._paste(frames[k], lms[k], r)
        return out

    def __call__(self, img):
        """Mot khung, do mat moi khung (= `FaceRestorer(kind="gfp")` cua CP13.3)."""
        return self.restore_frames([img], [self.landmarks(img)], 1)[0]

    def selftest(self) -> str:
        """Kiem mang thuc su chay: GFPGAN tren khung xam 512x512 + bo do mat tren khung trong. Tra mo ta ngan; nem loi."""
        import numpy as np
        torch = self.torch
        with torch.no_grad():
            t = torch.zeros(1, 3, 512, 512, device=self.device)
            if self.half:
                t = t.half()
            out = self.net(t, return_rgb=False)[0]
            if tuple(out.shape) != (1, 3, 512, 512):
                raise RuntimeError(f"GFPGAN tra kich thuoc la: {tuple(out.shape)}")
        blank = np.full((480, 640, 3), 127, np.uint8)
        same = self(blank)
        if same.shape != blank.shape:
            raise RuntimeError("buoc mat doi kich thuoc khung")
        return f"GFPGAN v1.4 + do mat chay duoc tren {self.device}"
