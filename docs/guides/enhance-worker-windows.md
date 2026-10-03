# Cài Enhance Worker trên máy Windows có GPU (CP13.1a)

Worker nhận việc "enhance video" từ VM, chạy trên GPU của máy này và gửi kết quả về. Tài liệu này là hướng dẫn thao tác, không phải authority. Giao thức và hợp đồng: `docs/decisions/CP13.1-enhance-worker-contract.md`; task: `docs/tasks/CP13.1a-enhance-worker-win.md`.

Áp dụng cho hai máy: RTX 3090 (cùng máy với Ollama, `-YieldToOllama`) và RTX 3050 (chạy liên tục, không nhường).

Quy ước: dòng bắt đầu bằng `>` là lệnh gõ trong **PowerShell** (không gõ ký tự `>`).

## Điều kiện trước

- Đã chạy `setup-gpu-node-v4.ps1` (tunnel Ollama v4): `~\.ssh\config` có `Host gpu-jump-v4` và `Host gpu-server-v4`, đăng nhập SSH không mật khẩu vào VM được. Worker dùng lại jump, khóa và địa chỉ VM đó; **không sửa** block / task Ollama v4.
- **Miniconda** đã cài (bản Windows 64-bit, "Just Me"). Script tìm `conda.exe` trên PATH, `%USERPROFILE%\miniconda3`, `%LOCALAPPDATA%\miniconda3`, `%ProgramData%\miniconda3`; nếu ở chỗ khác dùng `-CondaPath`. Script **không** tự cài Python. Nếu thiếu Miniconda, script báo lỗi rõ và dừng.
- Driver NVIDIA (`nvidia-smi` chạy được). Ổ đĩa còn ≥ 20 GB trống cho PyTorch, ffmpeg, mô hình và đoạn video tạm (giới hạn `-MaxDiskGb`, mặc định 100).
- Token của worker do VM cấp (CP13.1b; biến `AUTO_SHORT_ENHANCE_TOKENS` ở VM, dạng `tên=token`). Chưa có token vẫn cài được: bỏ trống khi script hỏi, điền sau vào `config.json` (xem "Đổi token").

## Bước 1 — Chép thư mục worker sang máy Windows

Chép cả thư mục `tools/enhance_worker` của repo (có `worker.py`, `srvgg.py`, `windows\*.ps1`) sang máy, ví dụ `C:\enhance_worker_src`. Dùng `scp` (thay `USER`, `VM_ADDRESS` bằng cái bạn vẫn dùng để SSH vào VM; repo ở `youtube-auto-short` hoặc worktree đang chứa nhánh `feature/cp13.1-enhance-worker`):

```
> scp -r USER@VM_ADDRESS:youtube-auto-short-enhw/tools/enhance_worker C:\enhance_worker_src
```

(Hoặc WinSCP / thư mục chia sẻ; miễn là cả thư mục được chép.)

## Bước 2 — Cài

Mở PowerShell, vào thư mục script:

```
> cd C:\enhance_worker_src\windows
> Set-ExecutionPolicy -Scope Process Bypass
```

Máy RTX 3090 (nhường Ollama):

```
> .\setup-enhance-worker.ps1 -WorkerName rtx3090 -YieldToOllama
```

Máy RTX 3050:

```
> .\setup-enhance-worker.ps1 -WorkerName rtx3050
```

Script làm lần lượt (an toàn chạy lại nhiều lần):

1. tìm Miniconda; tạo env conda `enhance-worker` (Python 3.11) nếu chưa có; cài vào env đó bằng pip: PyTorch CUDA (cu121), `numpy`, `opencv-python-headless` (khoảng 2,5–3 GB, 10–20 phút);
2. kiểm ffmpeg có `h264_nvenc`; nếu thiếu thì tải bản build (gyan.dev) vào `%USERPROFILE%\enhance-worker\ffmpeg`;
3. tải trọng số `realesr-general-x4v3.pth` (+ bản wdn) từ GitHub Real-ESRGAN, kiểm sha256;
4. chép worker vào `%USERPROFILE%\enhance-worker\app`; ghi `config.json` (token, quyền chỉ user hiện tại);
5. thêm block `# >>> Enhance Worker v1 >>>` (`Host gpu-worker-v4`, chuyển cổng `127.0.0.1:18080` → VM `127.0.0.1:8080`) vào `~\.ssh\config`;
6. tạo hai task Task Scheduler (khi đăng nhập, tự nối lại / tự khởi động lại): `EnhanceWorker-Tunnel` và `EnhanceWorker-Worker`;
7. chạy `worker.py --self-test` rồi bật worker.

Tham số hay dùng: `-EnvName <tên>` (dùng env conda khác, ví dụ env bench đã có `torch` CUDA), `-CondaPath <conda.exe hoặc thư mục Miniconda>`, `-Token <token>`, `-BatchSize 8` (3090 còn dư VRAM), `-MaxDiskGb 200`, `-CudaDevice 1` (máy có nhiều card), `-FfmpegPath <ffmpeg.exe có NVENC>`, `-SkipTorch`, `-NoTask`.

Worker luôn chạy bằng đường dẫn tuyệt đối tới `python.exe` của env (không dựa vào `conda activate`).

## Kiểm tra

Dòng cuối của self-test:

```
SELF-TEST OK voi canh bao: gpu=NVIDIA GeForce RTX 3090 encoder=h264_nvenc vm=reachable-unauthorized: VM tra 401: chua co token (VM cap o CP13.1b) - tunnel OK
```

- Trước khi VM có API (CP13.1b chưa merge): kết quả mong đợi là `[WARN] VM: reachable-unauthorized ... 401` (đăng nhập web của VM chặn mọi `/api/*`); đây là **đạt** (tunnel thông, exit 0). Worker không thoát: cứ 10 phút (`auth_retry_seconds`) hỏi lại và đọc lại `config.json`, nên sửa token xong không cần khởi động lại task. (Nếu VM trả `404` cũng là đạt.)
- Có token mà vẫn 401: token sai, hoặc VM chưa có API enhance (xem "Đổi token").
- `khong noi duoc ... tunnel`: tunnel chưa lên. Chạy `.\auto-fix-enhance-worker.ps1`.
- `WARN khong co NVENC`: worker vẫn chạy bằng libx264 (CPU, chậm hơn); dùng `-FfmpegPath` trỏ ffmpeg có NVENC.
- Tunnel Ollama v4 vẫn phải chạy: `Get-ScheduledTask Ollama-GPU-Tunnel-*`.

Xem log: `%USERPROFILE%\enhance-worker\logs\worker.log` (xoay vòng), `tunnel.log`, `wrapper.log`. Xem trạng thái nhanh: `.\auto-fix-enhance-worker.ps1` (dừng và chạy lại đúng hai task + tiến trình của worker, kiểm cổng 18080, chạy self-test, in trạng thái).

Khởi động lại máy rồi đăng nhập: hai task tự chạy (kiểm bằng `Get-ScheduledTask EnhanceWorker-*`).

## Đổi token / cấu hình

Sửa `%USERPROFILE%\enhance-worker\config.json`; worker tự đọc lại sau tối đa `auth_retry_seconds` khi gặp 401 (muốn áp dụng ngay: `.\auto-fix-enhance-worker.ps1`; hoặc chạy lại `setup-enhance-worker.ps1 -WorkerName ... -Token <token mới>`). Các khóa: `worker_name`, `token`, `yield_to_ollama`, `batch_size`, `max_disk_gb`, `work_dir`, `device`, `ffmpeg`. Mẫu: `config.example.json`. Không gửi token qua chat / commit vào repo.

## Gỡ

```
> .\setup-enhance-worker.ps1 -Uninstall
```

Dừng và xoá hai task, tiến trình của worker, block SSH `Enhance Worker v1`, thư mục `%USERPROFILE%\enhance-worker`. Thêm `-KeepData` để giữ `models\` và `work\`; thêm `-RemoveEnv` để xoá env conda. Không đụng tới task / block Ollama v4.

## Chạy tay (gỡ lỗi)

```
> & "$env:USERPROFILE\miniconda3\envs\enhance-worker\python.exe" "$env:USERPROFILE\enhance-worker\app\worker.py" --config "$env:USERPROFILE\enhance-worker\config.json" --self-test
```

`--once` (làm xong một việc rồi thoát), `--max-segments N` (dừng sau N đoạn, giữ trạng thái), `--device cpu`.
