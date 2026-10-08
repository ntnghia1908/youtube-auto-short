# Hướng dẫn đo chất lượng enhance trên GPU Windows (CP13.3)

Mục đích: chạy các phương án nâng chất lượng enhance (hạ khung / denoise, chỉnh màu, phục hồi mặt GFPGAN / CodeFormer, model video RealBasicVSR) trên card 3090, xuất video mẫu và đo tốc độ + VRAM. Chỉ **đo**; không đổi worker enhance đang chạy.

Tài liệu này là hướng dẫn thao tác, không phải authority. Task: `docs/tasks/CP13.3-enhance-quality.md`; kết quả: `docs/decisions/CP13.3-enhance-quality-report.md`.

**Không đụng tới worker đã cài.** Hướng dẫn này tạo env conda riêng tại `%USERPROFILE%\enhance-quality\env` (không phải `enhance-worker`) và dữ liệu trong `%USERPROFILE%\enhance-quality`. Không sửa `~\.ssh\config`, task Ollama / enhance, `%USERPROFILE%\enhance-worker`. Chạy được khi worker đang chạy, nhưng số đo tốc độ chính xác hơn nếu tạm dừng worker enhance và Ollama không có job (cùng GPU).

Thời gian: cài đặt 20–40 phút (PyTorch CUDA ≈ 3 GB, trọng số ≈ 1 GB); chạy bộ đo 15–40 phút tùy card. Cần ≈ 10 GB trống.

Quy ước: dòng bắt đầu bằng `>` là lệnh trong **PowerShell** (bấm Start, gõ `PowerShell`, Enter). Không gõ ký tự `>`.

## Hai lưu ý Windows (đã gặp ở CP14 / enhance worker)

1. **Miniconda không nhất thiết ở `%USERPROFILE%\miniconda3`.** Script `enhance_quality_win.ps1` tự dò `conda.exe`: tham số `-CondaPath`, `PATH`, rồi `%USERPROFILE%`, `%LOCALAPPDATA%`, `%ProgramData%`, `C:\` với các tên `miniconda3` / `Miniconda3` / `anaconda3` / `Anaconda3` / `miniforge3`, cuối cùng là tìm `conda.exe` (tối đa 4 cấp thư mục). Nếu vẫn không thấy, script báo lỗi và bạn tìm tay:

   ```
   > Get-ChildItem -Path $env:USERPROFILE, $env:LOCALAPPDATA, $env:ProgramData, C:\ -Filter conda.exe -Recurse -Depth 4 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
   ```

   rồi chạy lại với `-CondaPath "<đường dẫn conda.exe hoặc thư mục Miniconda>"`. Script gọi python bằng đường dẫn tuyệt đối của env, **không cần `conda activate`**.
2. **Trong PowerShell, `curl` là `Invoke-WebRequest`** (không phải curl thật). Script tải trọng số bằng Python (`urllib`), nên không dùng `curl`. Nếu tự tải tay: dùng `curl.exe -L -O <url>` hoặc `Invoke-WebRequest -UseBasicParsing -Uri <url> -OutFile <file>`.

## Bước 0 — Kiểm tra card

```
> nvidia-smi -L
> nvidia-smi
```

Phải thấy RTX 3090 và `CUDA Version: 12.x`. Máy có hai card: dùng `-CudaDevice 0` hoặc `1` (số theo `nvidia-smi -L`) ở bước 2. Dòng `gpu:` trong kết quả in tên card thật; kiểm tra trước khi gửi.

## Bước 1 — Lấy gói từ VM

Gói `gpu-pack` (script + 3 đoạn mẫu 90 khung, ≈ 30 MB) nằm trên VM. `gpu-server-v4` là SSH host đã có sẵn trong `~\.ssh\config`:

```
> cd $env:USERPROFILE
> scp -r gpu-server-v4:.cache/auto-short-cp133-test/gpu-pack .\enhance-quality-pack
> cd .\enhance-quality-pack
> dir
```

Phải có `enhance_quality_win.ps1`, `enhance_quality_bench.py`, `enhance_bench_win.py`, thư mục `clips` (`A.mkv`, `D.mkv`, `E.mkv`).

## Bước 2 — Chạy (một lệnh)

```
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> .\enhance_quality_win.ps1 -Step All -CudaDevice 0
```

`-Step All` = `Setup` (tìm conda, tạo env, pip, tải trọng số) → `Run` (bộ đo) → `Pack` (bảng tốc độ + zip). Có thể chạy từng bước: `-Step Setup`, `-Step Run`, `-Step Pack`.

Tham số hay dùng:

| Tham số | Ý nghĩa |
|---|---|
| `-CondaPath <conda.exe hoặc thư mục>` | khi tự dò không thấy |
| `-Root <thư mục>` | nơi đặt env + kết quả (mặc định `%USERPROFILE%\enhance-quality`) |
| `-CudaDevice 1` | chọn card |
| `-SkipRbvsr` | bỏ model video (không tải 148 MB, không chạy) |
| `-RbvsrChunk 45` | xử lý model video theo lượt 45 khung nếu hết VRAM (card ≤ 12 GB) |
| `-Frames 30` | số khung mỗi đoạn (mặc định 90 = 3 s) |
| `-Specs "cur,cur+cf50"` | ghi đè danh sách phương án |

Các phương án mặc định (đã so với `cur` = `g100_p360`, cấu hình hiện hành):

- `cur`, `g100_p0` (không hạ 360p), `g075_p0`, `g050_p0` (denoise 0,75 / 0,5);
- `cur+col2`, `g100_p0+col2` (chỉnh màu mức 2);
- `cur+gfp` (GFPGAN v1.4), `cur+cf50`, `cur+cf80` (CodeFormer fidelity 0,5 / 0,8), `cur+cf50s` (làm mượt tọa độ mặt), `g100_p0+cf50`;
- `rbvsr_p360`, `rbvsr_p0` (RealBasicVSR sau khi hạ 360p / không hạ).

Thấy `[W ... NNPACK ...]` hoặc cảnh báo `UserWarning` là bình thường.

Lỗi thường gặp:

- `CUDA khong kha dung`: kiểm tra Bước 0; chạy lại `-Step Setup` (pip cài PyTorch từ `download.pytorch.org/whl/cu121`).
- `CUDA out of memory` ở `rbvsr_*`: thêm `-RbvsrChunk 30`; ghi chú đã dùng chunk.
- `pip install basicsr` báo lỗi build: chạy `& "$env:USERPROFILE\enhance-quality\env\python.exe" -m pip install basicsr-fixed gfpgan facexlib` rồi chạy tiếp `-Step Run`; nếu vẫn lỗi, gửi dòng lỗi cho ORCHESTRATOR.
- `running scripts is disabled`: chạy `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` rồi chạy lại.

## Bước 3 — Gửi kết quả về VM

`-Step Pack` in bảng tốc độ (`speed.csv`) và tạo `%USERPROFILE%\enhance-quality\cp133-results.zip`. Gửi về VM:

```
> scp "$env:USERPROFILE\enhance-quality\cp133-results.zip" gpu-server-v4:.cache/auto-short-cp133-test/results/
```

Rồi dán bảng (hoặc nội dung `speed.csv`) vào chat. Cột đáng chú ý: `sec_per_frame_base` (phần enhance), `sec_per_frame_post` (phần mặt / màu), `sec_per_frame` (tổng), `vram_peak_mb`. Video mẫu nằm trong zip (`<đoạn>__<phương án>.mp4`, x264 crf 12) để ORCHESTRATOR ghép so sánh.

## Thử ở chế độ CPU (không cần GPU; kiểm script)

```
> .\enhance_quality_win.ps1 -Step Setup -Device cpu -SkipRbvsr
> .\enhance_quality_win.ps1 -Step Run -Device cpu -Frames 3 -SkipRbvsr -Specs "cur,cur+col2,cur+cf50"
```

Trên VM (Linux), cùng script Python: `python scripts/enhance_quality_bench.py run --clip <doan.mkv> --name D --specs "cur,cur+col2" --out <thư mục> --frames 3 --device cpu --threads 16`.

## Tùy chọn E — Topaz Video AI (bản dùng thử)

Không bắt buộc, không mua. Nếu muốn đưa vào so sánh:

1. Tải bản dùng thử Topaz Video AI từ trang Topaz Labs (bản dùng thử xuất video có watermark; đủ để so mắt).
2. Mở `clips\D.mkv` (và `E.mkv`, `A.mkv`), model "Proteus" hoặc "Iris" hoặc "Gaia" (thử 1–2 cái), độ phân giải đích 1440×1080 (A: 1454×1080), xuất H.264 mp4, 90 khung đầu.
3. Đặt tên `D__topaz_<model>.mp4` rồi `scp` về `gpu-server-v4:.cache/auto-short-cp133-test/results/`.

Lưu ý: giấy phép Topaz là thương mại (cần mua để dùng thật); chỉ để so chất lượng.

## Giấy phép các model (ghi để cân nhắc khi dùng cho kênh)

| Thành phần | Giấy phép | Ghi chú |
|---|---|---|
| Real-ESRGAN `realesr-general-x4v3` | BSD-3-Clause | đang dùng |
| GFPGAN v1.4 | Apache-2.0 (mã + trọng số) | dùng thương mại được; trọng số huấn luyện trên FFHQ (điều khoản dữ liệu riêng) |
| CodeFormer | S-Lab License 1.0 (**phi thương mại**) | rủi ro với kênh có kiếm tiền; chỉ so mắt, không đưa vào sản phẩm khi chưa có giấy phép riêng |
| facexlib (dò mặt) | MIT; trọng số RetinaFace theo repo gốc | |
| RealBasicVSR | Apache-2.0 (OpenMMLab / MMEditing) | trọng số huấn luyện bằng bộ dữ liệu học thuật (REDS); kiểm lại khi dùng thương mại |
| BasicSR | Apache-2.0 | |
| Topaz Video AI | thương mại (trả phí) | chỉ bản dùng thử để so |

(Chi tiết và rủi ro: báo cáo CP13.3 §Giấy phép.)

## Dọn dẹp

```
> Remove-Item -Recurse -Force "$env:USERPROFILE\enhance-quality", "$env:USERPROFILE\enhance-quality-pack"
```

Chỉ xóa hai thư mục của hướng dẫn này. Không có gì được cài ngoài chúng (Miniconda có sẵn của bạn không bị sửa; conda chỉ tạo env tại `enhance-quality\env`).
