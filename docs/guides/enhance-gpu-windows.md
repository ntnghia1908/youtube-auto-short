# Hướng dẫn đo tốc độ enhance video trên GPU Windows (CP13 E2)

Mục đích: đo xem card đồ họa (RTX 3060 12 GB, RTX 3090 24 GB) enhance (phục hồi chi tiết) video nhanh cỡ nào. Chỉ **đo**; không mở cổng mạng, không cài dịch vụ nào chạy nền, không đụng tới Ollama. Làm xong có thể xóa cả thư mục.

Tài liệu này là hướng dẫn thao tác, không phải authority. Task: `docs/tasks/CP13-enhance-measure.md`.

Thời gian làm: khoảng 30–45 phút (phần lớn là chờ tải). Cần khoảng 8 GB trống trên ổ đĩa (PyTorch CUDA ≈ 3 GB, trọng số model ≈ 160 MB, mẫu ≈ 50 MB).

Quy ước: dòng bắt đầu bằng `>` là lệnh gõ trong **PowerShell** (bấm Start, gõ `PowerShell`, Enter). Không gõ ký tự `>`.

## Bước 0 — Kiểm tra driver NVIDIA

```
> nvidia-smi
```

Phải hiện tên card (RTX 3060 / 3090) và dòng `CUDA Version: 12.x`. Nếu báo lệnh không tồn tại: cài driver NVIDIA mới nhất từ trang nvidia.com (mục Drivers), khởi động lại máy rồi thử lại.

Nếu máy có **cả hai card**, lệnh chạy bench mặc định dùng card số 0. Để chọn card, đặt biến trước khi chạy (trong cùng cửa sổ PowerShell):

```
> $env:CUDA_VISIBLE_DEVICES = "0"      # hoặc "1"
```

`nvidia-smi -L` liệt kê card theo số thứ tự. Dòng đầu của kết quả bench (`gpu:`) in tên card thật; kiểm tra đúng card trước khi dán.

## Bước 1 — Cài Python 3.11

1. Mở https://www.python.org/downloads/windows/ và tải **Python 3.11.x** (Windows installer 64-bit). Không dùng 3.13 trở lên (PyTorch có thể chưa hỗ trợ).
2. Khi cài, **tick "Add python.exe to PATH"** ở màn hình đầu, rồi Install Now.
3. Mở PowerShell mới và kiểm tra:

```
> py -3.11 --version
```

Phải hiện `Python 3.11.x`.

## Bước 2 — Tạo thư mục làm việc và môi trường ảo

```
> mkdir C:\enhance-bench
> cd C:\enhance-bench
> py -3.11 -m venv venv
> .\venv\Scripts\Activate.ps1
```

Nếu báo lỗi "running scripts is disabled": chạy `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, trả lời `Y`, rồi chạy lại dòng `Activate.ps1`.

Thành công khi đầu dòng lệnh có `(venv)`. Từ đây **luôn dùng cửa sổ có `(venv)`**; nếu mở cửa sổ mới thì `cd C:\enhance-bench` rồi chạy lại dòng `Activate.ps1`.

## Bước 3 — Cài PyTorch (bản CUDA) và thư viện phụ

```
> python -m pip install --upgrade pip
> pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
> pip install numpy opencv-python-headless
```

Dòng thứ hai tải khoảng 2.5–3 GB, có thể mất 10–20 phút. Kiểm tra PyTorch thấy card:

```
> python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Phải in `True` và tên card. Nếu in `False`: kiểm tra lại Bước 0, và chắc chắn lệnh `pip install` ở trên có `--index-url ...cu121` (nếu không sẽ cài bản chỉ chạy CPU; gỡ bằng `pip uninstall torch torchvision` rồi cài lại).

## Bước 4 — Tải trọng số model (chính thức, từ GitHub của Real-ESRGAN)

```
> mkdir models
> cd models
> curl.exe -L -O https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth
> curl.exe -L -O https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-wdn-x4v3.pth
> curl.exe -L -O https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth
> curl.exe -L -O https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth
> cd ..
```

Kiểm tra: `dir models` phải có 4 file `.pth` (kích thước ≈ 4.9 MB, 4.9 MB, 67 MB, 67 MB).

## Bước 5 — Lấy script và đoạn mẫu từ máy ảo (VM)

Cần hai thứ, đều ở trên VM:

- script: `scripts/enhance_bench_win.py` trong repo (nhánh `feature/cp13-enhance-measure`, hoặc `main` sau khi merge);
- 3 đoạn mẫu (khoảng 10 s mỗi đoạn, vài MB): `~/.cache/auto-short-cp13-test/samples/`.

Cách dễ nhất là `scp` (có sẵn trong Windows 10/11). Thay `USER` và `VM_ADDRESS` bằng tên đăng nhập và địa chỉ bạn vẫn dùng để SSH vào VM (nếu SSH vào VM bằng cổng khác thì thêm `-P <cổng>` ngay sau `scp`):

```
> scp USER@VM_ADDRESS:youtube-auto-short-enh/scripts/enhance_bench_win.py .
> scp "USER@VM_ADDRESS:.cache/auto-short-cp13-test/samples/*.mp4" .
```

(Nếu repo/đường dẫn khác, nhờ ORCHESTRATOR chép hai thứ trên sang chỗ bạn truy cập được; hoặc dùng WinSCP / thư mục chia sẻ — miễn cuối cùng thư mục `C:\enhance-bench` có `enhance_bench_win.py` và 3 file `.mp4`.)

Kiểm tra: `dir` thấy `enhance_bench_win.py`, `A_old_352x262.mp4`, `B_960x720.mp4`, `C_1440x1080.mp4`, thư mục `models`, `venv`.

## Bước 6 — Chạy thử (khoảng 1 phút)

```
> python enhance_bench_win.py --device cuda --model realesr-general-x4v3 --clip A_old_352x262.mp4 --frames 30 --fp16
```

Kết quả dạng:

```
=== KET QUA ===
device: cuda
gpu: NVIDIA GeForce RTX 3060
...
sec_per_frame: 0.0xx
fps: xx.xx
vram_peak_mb: ...
```

Nếu hiện lỗi `CUDA out of memory`: thêm `--tile 256` vào cuối lệnh (chia khung thành mảnh nhỏ, chậm hơn một chút) rồi ghi lại là có dùng tile.

Lỗi `Khong mo duoc video`: sai tên/đường dẫn file mẫu (chạy lệnh trong thư mục `C:\enhance-bench`).

## Bước 7 — Chạy bộ đo đầy đủ

Chạy lần lượt các lệnh dưới đây (mỗi lệnh 0.5–5 phút), **mỗi lệnh thêm `--json`** để có một dòng kết quả dễ dán. Không chạy việc nặng khác trên máy (game, trình duyệt nhiều tab video…) trong lúc đo, vì sẽ làm số đo chậm đi.

```
> python enhance_bench_win.py --model realesr-general-x4v3 --clip A_old_352x262.mp4 --frames 60 --fp16 --json
> python enhance_bench_win.py --model realesr-general-x4v3 --clip B_960x720.mp4 --scale-to 360 --frames 60 --fp16 --json
> python enhance_bench_win.py --model realesr-general-x4v3 --clip B_960x720.mp4 --scale-to 540 --frames 60 --fp16 --json
> python enhance_bench_win.py --model RealESRGAN_x4plus --clip A_old_352x262.mp4 --frames 30 --fp16 --json
> python enhance_bench_win.py --model RealESRGAN_x4plus --clip B_960x720.mp4 --scale-to 270 --frames 30 --fp16 --json
> python enhance_bench_win.py --model RealESRGAN_x2plus --clip B_960x720.mp4 --scale-to 540 --frames 30 --fp16 --json
> python enhance_bench_win.py --model realesr-general-x4v3 --clip C_1440x1080.mp4 --scale-to 540 --frames 60 --fp16 --json
```

Giải thích nhanh: `--scale-to N` hạ khung xuống cao N px trước khi enhance (đúng cách dự kiến dùng thật: hạ rồi phóng lên 1080p); `--frames` là số khung đo; `--fp16` dùng số thực nửa độ chính xác (nhanh hơn, ít VRAM hơn trên card RTX).

Nếu muốn so fp16 với fp32 (tùy chọn): chạy lại một lệnh bất kỳ ở trên **bỏ** `--fp16`.

Nếu một lệnh báo hết VRAM: thêm `--tile 256` và ghi chú.

## Bước 8 — Gửi kết quả

Với mỗi lệnh, dán vào chat (cho ORCHESTRATOR) **dòng bắt đầu bằng `JSON `** và ghi kèm:

- tên card (đã có trong dòng JSON, trường `gpu`),
- lệnh đã chạy nếu khác bản trên (ví dụ có thêm `--tile`),
- nhiệt độ/tiếng quạt nếu bất thường (không bắt buộc; script tự ghi `temp_max_c` nếu `nvidia-smi` có).

Bảng ORCHESTRATOR sẽ điền vào `docs/decisions/CP13-enhance-report.md` (mục E2):

| Card | Model / cấu hình | Đoạn mẫu | s/khung | fps | VRAM đỉnh (MB) | Nhiệt độ max | Ghi chú |
|---|---|---|---|---|---|---|---|
| (chưa đo) | | | | | | | |

## Dọn dẹp

Xong thì xóa cả thư mục: `cd C:\ ; Remove-Item -Recurse -Force C:\enhance-bench`. Không có gì được cài ngoài thư mục này, ngoại trừ Python 3.11 (gỡ trong Settings → Apps nếu muốn).
