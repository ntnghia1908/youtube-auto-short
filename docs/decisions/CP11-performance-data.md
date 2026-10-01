# CP11 — Số liệu đo hiệu năng pipeline (dữ liệu thô)

| Metadata | Value |
|---|---|
| Status | PROPOSED (số liệu đo; không phải authority, không đổi hành vi nào) |
| Task contract | `docs/tasks/CP11-performance-measure.md` |
| Script | `scripts/cp11_bench.py` (chạy lại từng thí nghiệm bằng một lệnh; chỉ ghi vào thư mục bench) |
| Người đo | IMPLEMENTER, 2026-09-30 |
| Phần khuyến nghị | Không có ở file này. `CP11-performance-report.md` do ORCHESTRATOR viết từ số liệu dưới đây. |

## 0. Điều kiện đo

- Máy: VM 48 vCPU (Intel Xeon Silver 4216 @ 2.10 GHz; `lscpu` báo 48 socket × 1 core × 1 thread), 125 GB RAM, không GPU, ffmpeg 6.1.1, `faster-whisper` 1.2.1 / `ctranslate2` 4.8.2, Whisper `large-v3-turbo`. Ollama `127.0.0.1:11437` (`qwen3:30b`, `qwen3:14b`).
- Dữ liệu đo: **bản sao** ở `~/.cache/auto-short-cp11-bench/` (nguồn hard-link, JSON copy thật; manifest bản sao đã bỏ stage `render` vì artifact của nó là đường dẫn tuyệt đối vào `output/` chính). Script từ chối chạy nếu `workspace.dir` / `render.output_dir` không nằm trong thư mục bench.
  - `4oOZz2CBz3g` — Short, nguồn AV1 960x720 29.97 fps, 3671.9 s; Whisper; 7 Short, tổng 518.6 s (k01 50.9 s, k02 72.4, k03 75.8, k04 56.2, k05 156.9, k06 51.4, k07 55.0).
  - `4oOZz2CBz3g.kt` — khai thị cùng nguồn; 6 video (k01 243.1 s, k02 397.4, k03 245.4, k04 377.7, k05 337.5, k06 299.5).
  - `E4QhRRXFbIM` — caption YouTube, nguồn h264 960x720 29.97 fps, 3400.6 s (chỉ dùng cho E4).
- Config bench = mặc định production (`config.example.toml`): `render.preset=medium`, `crf=22`, `threads=0`, `dissolve=0.15`; `whisper.cpu_threads=0` (=48), `int8`; `selection` `qwen3:30b`, `think=true`, `num_ctx=32768`.
- **Nhiễu do production 8080.** E1, E4, E6 (lần 1) chạy xong trước khi HUMAN LEAD gửi job (job đầu ghi ở manifest lúc 16:28 UTC); số đo nhất quán giữa các lần lặp (chênh < 1%). Từ E3 / E5 / E1 "cả tập" / E2: script chờ máy rảnh (`wait_quiet`, < 1.5 lõi bận trong 3 × 5 s) trước mỗi phép đo và ghi `foreign_cores` = lõi bận toàn máy trừ phần CPU của chính phép đo (wait4 / `os.times`); lượt vượt 2 lõi bị bỏ và đo lại. Mọi số ở E3 / E5 / epar có `foreign_cores` ≤ 0.22. Một lần chạy E3 đầu bị nhiễu (Whisper của 8080) đã bị hủy, không dùng.
- E2 (D5): chỉ chạy khi không stage nào ở `work/` chính ở trạng thái `running` và `expires_at` của model đang nạp không đổi trong 90 s; kiểm lại `running` trước mỗi variant. Không đổi cấu hình Ollama, không đụng tới 8080.
- Số liệu thô JSON: `~/.cache/auto-short-cp11-bench/raw/` (`e1-*`, `e1-capture-*`, `e2-*`, `e3-*`, `e3-extra-*`, `e4-*`, `e5-*`, `e6-*`, `hashes-*`; các file `e1-…145412Z`, `e2-…194633Z`, `e3-…215832Z`, `e4-…220107Z`, `e5-…182809Z`, `e1-capture-…220418Z` là lượt `--quick` / kiểm lại).
- Mỗi ô ≥ 2 lượt chạy (cột "từng lượt"), trừ chỗ ghi khác.

## 1. E1 — Render (ffmpeg, libx264)

### 1.1 Nền: render thật qua `run_render` (force, 1 lần, tuần tự)

| Tập | Tổng | Từng video (s wall) |
|---|---|---|
| `4oOZz2CBz3g` (7 Short, 518.6 s video) | 191.0 s (lượt 2 khi kiểm `--quick`: 190.8 s) | k01 17.5, k02 26.2, k03 25.7, k04 21.1, k05 57.3, k06 19.6, k07 21.8 |
| `4oOZz2CBz3g.kt` (6 video, 1901 s) | 699.4 s | k01 86.1, k02 143.5, k03 86.4, k04 143.8, k05 127.9, k06 107.4 |

Khớp khoảng 190–542 s (Short) và 337–865 s (khai thị) ở manifest. Một ffmpeg dùng trung bình ≈ 9.3 lõi / 48 (CPU ≈ 9–10 lõi × wall). Hệ số thời gian thực (giây video / giây render) ≈ 2.7–2.8.

### 1.2 Tách decode / filter / encode (cùng lệnh ffmpeg, thay phần đầu ra)

| Tập / video đo | decode-only (seek + giải mã video) | + filter graph (không encode) | đầy đủ (x264 medium) | suy ra: decode / filter / encode+ghi |
|---|---|---|---|---|
| Short k01+k02+k05 (280 s video) | 11.9 s (11.9, 11.9) | 44.9 s (45.1, 44.6) | 100.9 s (100.3, 101.5) | 12% / 33% / 55% |
| khai thị k01 (243 s) | 10.8 s (10.8, 10.8) | 39.9 s (39.8, 39.9) | 85.9 s (85.3, 86.5) | 13% / 34% / 53% |

CPU trung bình: decode-only ≈ 4.9 lõi, decode+filter ≈ 4.7 lõi, đầy đủ ≈ 9.3 lõi.

### 1.3 `render.threads` (execution-only) — tổng wall 3 Short k01+k02+k05 (Short) / k01 (khai thị)

| Tập | threads=0 (mặc định) | threads=8 | threads=16 |
|---|---|---|---|
| Short | 101.0 s (100.7, 101.3); 938 CPU-s | 135.0 s (134.9, 135.0); 875 CPU-s | 100.8 s (101.0, 100.6); 903 CPU-s |
| khai thị | 86.8 s (86.9, 86.7); 799 CPU-s | 115.4 s (115.5, 115.3); 749 CPU-s | 87.0 s (87.0, 87.1); 774 CPU-s |

`threads=16` không khác `0`; `threads=8` chậm hơn ≈ 34%.

### 1.4 Preset x264 (crf 22 giữ nguyên) — cùng tập như 1.3

| Tập | preset | wall (từng lượt) | CPU-s | dung lượng tổng |
|---|---|---|---|---|
| Short | medium | 100.4 s (100.7, 100.2) | 938 | 63.04 MB |
| Short | fast | 97.8 s (97.6, 98.1) | 811 | 62.83 MB |
| Short | veryfast | 97.2 s (97.2, 97.3) | 532 | 46.90 MB |
| khai thị | medium | 86.3 s (86.3, 86.3) | 798 | 54.00 MB |
| khai thị | fast | 83.6 s (84.5, 82.6) | 687 | 53.19 MB |
| khai thị | veryfast | 83.7 s (83.6, 83.9) | 457 | 39.65 MB |

Chất lượng (Short `k02`, so với bản `medium`, ffmpeg `ssim`/`psnr`; **không phải so với nguồn**):

| preset | dung lượng | SSIM | PSNR trung bình |
|---|---|---|---|
| medium | 17.92 MB | (mốc) | (mốc) |
| fast | 17.74 MB (−1.0%) | 0.9944 | 45.75 dB |
| veryfast | 13.29 MB (−25.9%) | 0.9913 | 43.18 dB |

Mẫu cho HUMAN LEAD (cùng Short `4oOZz2CBz3g` / `k02`, crf 22): `~/.cache/auto-short-cp11-bench/samples/cp11_4oOZz2CBz3g_k02_preset-{medium,fast,veryfast}_crf22.mp4`.

### 1.5 Chạy song song nhiều ffmpeg (threads mặc định)

Bốn Short ngắn k01+k04+k06+k07 (213.5 s video) và hai video khai thị k01+k03:

| Tập | p | threads=0: wall tổng (từng lượt) | lõi TB | threads=8: wall |
|---|---|---|---|---|
| Short (4 clip) | 1 | 80.4 s (80.2, 80.6) | 8.9 | — |
| | 2 | 50.1 s (49.9, 50.3) | 15.0 | 60.5 s |
| | 3 | 47.6 s (47.7, 47.5) | 16.2 | 57.5 s |
| | 4 | 34.3 s (34.3, 34.3) | 24.1 | 37.1 s |
| khai thị (2 clip) | 1 | 171.8 s (171.7, 171.8) | 9.7 | — |
| | 2 | 106.0 s (105.8, 106.2) | 16.6 | 127.9 s |

Cả tập qua thread pool p tiến trình (mỗi tiến trình một video, threads mặc định; p=1 lấy từ 1.1, một lần đo):

| Tập | p=1 (1.1) | p=2 | p=3 | p=4 | p=6 / 7 |
|---|---|---|---|---|---|
| Short, 7 video | 191.0 s | 119.5 s (119.5, 119.5) | — | 99.4 s (99.5, 99.3) | p=7: 84.2 s (84.0, 84.5) |
| khai thị, 6 video | 699.4 s | 455.7 s (455.6, 455.8) | 347.7 s (347.8, 347.6) | — | p=6: 257.2 s (256.9, 257.5) |

Lõi TB: Short p=7 ≈ 25; khai thị p=6 ≈ 31. Số Short p=7 bị chặn bởi video dài nhất (k05, 57.3 s một mình). Bộ nhớ tối đa (`maxrss`) mỗi ffmpeg xem trong JSON.

Đầu ra của mọi cấu hình cùng kích thước (chỉ khác preset); `threads=8/16` đổi dung lượng vài chục KB (x264 không bit-exact giữa số luồng khác nhau).

## 2. E2 — Selection (Ollama, tập Short `4oOZz2CBz3g`, 4 cuộc gọi / lượt)

Mốc production (manifest `selection_log.json`): 4 cuộc gọi 68.3 + 39.9 + 74.9 + 66.8 = 249.8 s. Prompt 2204–6064 token; eval 8075–10996 token / cuộc gọi (phần lớn là `thinking`); 150–167 token/s; nạp model 5–6 s khi chưa nằm trong VRAM (0.06 s khi đã nạp); không retry ở mọi lượt chạy.

| Variant (đổi so với production) | wall (từng lượt) | eval token tổng | token/s | kết quả |
|---|---|---|---|---|
| `base` (qwen3:30b, think, ctx 32768) | lượt 1: 223.0 s; lượt 2: 253.3 s; thêm 2 lượt: 253.0, 253.4 | 35318 (lượt 1); 37653 (các lượt sau, giống hệt nhau) | 150–167 | lượt 1 ra 8 video, chỉ 4/7 video production trùng ≥ 50%; 3 lượt sau ra 7 video, **7/7 trùng khoảng thời gian chính xác** |
| `ctx24k` (`num_ctx` 24576) | 248.9, 252.8 | 37653 | 150–172 | 7/7 giống hệt production; **không nhanh hơn** |
| `ctx16k` (`num_ctx` 16384) | 711.5, 711.5 (**lỗi cả 2 lượt**) | — | — | cuộc gọi thứ 3 (prompt 6064 token; ở `base` cuộc gọi này sinh 10 996 token, tổng > 16384) timeout 600 s → `SelectionError` (suy luận: tràn context, Ollama không báo lỗi) |
| `nothink` (qwen3:30b, `think=false`) | 11.2, 11.2 | 28 | 95–130 | **0 video**: cả 4 cuộc gọi trả `{"clips": []}` (7 token) |
| `14b` (qwen3:14b, think) | 194.0, 194.9 | 12832 | 68–74 | 6/7 video production trùng ≥ 50% (0 giống hệt); chọn tổng 18 video (≥ score 7) |
| `14b-nothink` (qwen3:14b, `think=false`) | 70.1, 68.5 | 4801 | 71–75 | 4/7 trùng; chọn tổng 22 video |

Ghi chú:

- Cùng `seed=42`, `temperature=0` nhưng lượt `base` đầu (model vừa được nạp lại sau lượt `--quick`) cho kết quả khác các lượt sau: đầu ra của Ollama phụ thuộc trạng thái model / lần nạp, không chỉ cấu hình. Các lượt sau (kể cả `ctx24k`) lặp lại chính xác.
- Thời gian mỗi cuộc gọi `base` (lượt ổn định): 71, 40, 75, 67 s; `14b`: 44, 26, 94, 29 s.
- Chất lượng video được chọn (nội dung, ý trọn vẹn) **không được đánh giá** (D4: HUMAN LEAD quyết bằng mắt / tai). File `selection_log.json` và `clips.json` của mọi variant: `~/.cache/auto-short-cp11-bench/raw/sel/`.
- Không đo: khai thị (`.kt`) và tập caption cho E2 (chỉ Short; lý do: Ollama chỉ dùng được khi hàng đợi 8080 rỗng, thời gian đo dài).
- Không đo được riêng "thời gian từng window" ngoài 4 cuộc gọi ở trên; thời gian nạp model = 5–6 s (`load_duration`).

## 3. E3 — Whisper CPU (đoạn 300 s của audio `4oOZz2CBz3g`, từ giây 600)

Đoạn cắt 5 phút (contract gợi ý 10 phút; đổi để mỗi ô ≥ 2 lượt kịp), mono 16 kHz WAV; chương trình chạy như production (`vad_filter`, `word_timestamps`, `language=vi`, beam mặc định) trong tiến trình riêng. RTF = giây transcribe / 300. Nạp model ≈ 3.3–3.7 s mọi cấu hình.

| Cấu hình | transcribe s (từng lượt) | RTF | CPU-s | text so với production* | text giữa các lượt |
|---|---|---|---|---|---|
| `cpu_threads=0` (48, mặc định) int8 | 144.4 (144.0, 144.8) | 0.481 | 1988 | 0.968 | giống nhau |
| 8 int8 | 146.8 (146.9, 146.7) | 0.489 | 1066 | 0.968 | giống nhau |
| 16 int8 | 103.6 (103.7, 103.5) | 0.345 | 1304 | 0.968 | giống nhau |
| 20 int8 | 88.0 (87.7, 88.3) | 0.293 | 1434 | 0.968 | giống nhau |
| **24 int8** | **85.0 (84.4, 85.5)** | **0.283** | 1560 | 0.968 | giống nhau |
| 28 int8 | 115.1 (109.2, 121.0) | 0.384 | 1361 | 0.968 | giống nhau |
| 32 int8 | 123.7 (123.5, 123.8) | 0.412 | 1463 | 0.968 | giống nhau |
| 24 `int8_float32` | 86.5 (85.2, 87.8) | 0.288 | 1583 | 0.968 | giống nhau |
| batched (`BatchedInferencePipeline`, batch 4) 24 int8 | 72.4 (72.9, 71.9) | 0.241 | 1216 | 0.970 | giống nhau |
| batched 8, 16 int8 | 75.4 (75.6, 75.3) | 0.251 | 983 | 0.970 | giống nhau |
| batched 8, 20 int8 | 69.9 (70.1, 69.6) | 0.233 | 1063 | 0.970 | giống nhau |
| batched 8, 24 int8 | 68.0 (66.8, 69.1) | 0.227 | 1163 | 0.970 | giống nhau |
| batched 16, 24 int8 | 68.6 (70.0, 67.2) | 0.229 | 1162 | 0.970 | giống nhau |
| batched 8, 28 int8 | **lỗi**: tiến trình chết bởi SIGSEGV (exit −11), cả 2 lượt | — | — | — | — |
| batched 8, 0 (48) int8 | **lỗi**: SIGSEGV, cả 2 lượt | — | — | — | — |

\* Tỉ lệ `difflib.SequenceMatcher` trên từ chữ thường của `transcript.json` production cùng đoạn [600, 900) s (production chạy cả file 1 lần nên không bằng 1.0; mọi cấu hình không batch cho đúng cùng từng chữ, `int8_float32` cũng vậy). Chế độ batched khác nhẹ so với không batch (tỉ lệ 0.99 giữa hai chế độ).

Suy ra cho tập 1 giờ (3672 s, ngoại suy tuyến tính theo RTF của đoạn đo; thực tế có VAD bỏ đoạn im): mặc định ≈ 1766 s (khớp 1728–1862 s ở manifest); 24 luồng ≈ 1039 s; batched 8 / 24 luồng ≈ 834 s.

Quan sát: nhanh nhất ở 24 luồng (trên 24 chậm lại: 28 → 115 s, 32 → 124 s, 48 → 144 s); 8 luồng ≈ 48 luồng. `BatchedInferencePipeline` (có sẵn trong bản đã cài, không thêm dependency) nhanh thêm ≈ 20% nhưng **segfault khi `cpu_threads ≥ 28`** (đã thử 28 và 48), ổn ở ≤ 24 (đã thử 16, 20, 24).

## 4. E4 — Analysis (hai lượt ffmpeg, đúng lệnh của `FfmpegAnalyzer`)

| Tập | lượt shot (scale 320 + scene) | lượt silence | tuần tự (như stage) | song song 2 tiến trình | gộp 1 tiến trình 2 output |
|---|---|---|---|---|---|
| `4oOZz2CBz3g` (AV1) | 122.3 s (122.3, 122.3); 765 CPU-s | 20.8 s (20.8, 20.9) | 143.2 s (143.1, 143.2) | 122.5 s (122.5, 122.5) | 124.0 s (124.1, 124.0) |
| `E4QhRRXFbIM` (h264) | 38.6 s (39.2, 37.9); 359 CPU-s | 19.5 s (19.2, 19.8) | 58.0 s (58.4, 57.7) | 39.9 s (39.8, 40.1) | 56.9 s (58.3, 55.5) |

Kết quả (danh sách `changes` sau `normalize_changes` và `silences` sau `parse_silencedetect`) của cả ba cách **giống hệt** `shots.json` / `silences.json` của production ở cả hai tập (4 / 6 đổi cảnh, 813 / 772 khoảng lặng).

## 5. E5 — Chạy song song lẫn nhau (Short ngắn k01/k04/k06, render threads mặc định; Whisper = đoạn 300 s)

Mỗi dòng: trung bình hai lượt (số từng lượt trong ngoặc). Render khi Whisper / analysis chạy: vòng lặp render k01, k04, k06 cho tới khi tiến trình kia xong; chỉ tính render xong khi tiến trình kia còn chạy (nạp model Whisper không tính vào thời gian chồng).

| Tình huống | Tiến trình nền | Render mỗi video (mean) |
|---|---|---|
| chạy riêng | Whisper 48 luồng 142.7 s (142.9, 142.5); Whisper 24 luồng 83.9 s (84.6, 83.2); analysis 143.1 s | threads=0: 19.6 s; threads=8: 25.7 s |
| Whisper 48 + render threads=0 | Whisper 191.7 s (189.4, 193.9) = ×1.34 | 23.6 s (8 + 8 video) = ×1.20 |
| Whisper 24 + render threads=0 | Whisper 106.2 s (105.3, 107.1) = ×1.27 | 26.9 s (27.4 / 3 video, 26.3 / 4 video) = ×1.37 |
| Whisper 24 + render threads=8 | Whisper 97.8 s (96.9, 98.6) = ×1.17 | 32.0 s (31.8, 32.1) = ×1.24 |
| analysis (2 lượt) + render threads=0 | analysis 179.2 s (180.3, 178.0) = ×1.25 | 20.9 s (20.9, 20.8; 8 + 8 video) = ×1.07 |

## 6. E6 — Cache / tái dùng (bản sao, `run_render` thật, 2 lượt)

| Phép thử | Kết quả |
|---|---|
| Chạy lại cả 5 stage của tập không đổi (Short) | cả 5 `ran=False`; tổng 0.05 s (khai thị: 0.10 s); không gọi Whisper / Ollama (stub báo lỗi nếu bị gọi) |
| Đổi `render.threads` 0 → 8 (execution-only) | `ran=False` (bỏ qua, 0.015 s) ở cả Short và khai thị |
| Sửa title một Short (`review.json`, k03) | `encoded=1`, `reused=6`; 26.9 s (26.9, 27.0); chỉ file `k03.mp4` đổi sha256 |
| Gỡ override (title về AI) | `encoded=1`, `reused=6`; 26.5 s |

Đổi preset / crf / bố cục: hash đổi → mọi Short encode lại (mục 7; không chạy thật vì kết quả suy ra từ code).

## 7. Đổi `config_hash` / `render_key` hay không (kiểm bằng code: `python scripts/cp11_bench.py hashes`)

`hashes` dựng `Config` biến thể và tính hash từng stage bằng chính `used_config()` của stage (hash đổi = True). `render_key` (`render/stage.py::render_key`) chứa `render_config_hash`, nên `render_key` đổi khi và chỉ khi hash render đổi (hoặc font, nguồn, fps, segments, layout, header, title, `RENDER_PLAN_VERSION`).

| Đổi | transcript | analysis | selection | render (→ `render_key`) |
|---|---|---|---|---|
| `render.threads` | không | không | không | **không** |
| `render.preset` (fast / veryfast) | không | không | không | **có** |
| `render.crf` | không | không | không | có |
| `transcript.whisper.cpu_threads` | không | không | không | không |
| `transcript.whisper.compute_type` (int8_float32) | **có** | không | không | không |
| `selection.think` / `model` / `num_ctx` | không | không | **có** | không |
| `selection.ollama_host` / `timeout` | không | không | không | không |
| `analysis.*` (vd `scale_width`) | không | **có** | không | không |

Thay đổi chỉ ở code (không có khóa config) và không đổi hash: render song song nhiều ffmpeg, Whisper batched, gộp / song song hai lượt analysis. Ràng buộc kèm theo (kiểm bằng số liệu trên): analysis gộp / song song cho kết quả giống hệt (mục 4) nên không làm stale artifact; Whisper batched cho text khác nhẹ so với không batch (mục 3) — nếu triển khai bằng khóa config nằm trong `used_config` thì hash transcript đổi, nếu không thì transcript chạy lại sau này có `transcript.json` khác; không đổi gì cho tập đã xong. `RENDER_PLAN_VERSION` (= 1) chỉ tăng khi cấu trúc lệnh ffmpeg / filter đổi; render song song không đổi lệnh nên không cần tăng.

## 8. Thí nghiệm không chạy / giới hạn

- E2 không chạy trên khai thị / tập caption; chỉ Short `4oOZz2CBz3g`; chất lượng clip không đánh giá.
- E3 đo trên đoạn 300 s (không phải cả giờ) và truyền WAV mono 16 kHz thay vì `source.mp4` (production truyền file media, phần giải mã audio nhỏ so với 85–144 s); số cả giờ là ngoại suy tuyến tính.
- E1 sweep `threads` / `preset` / tách decode trên 3 Short (Short) và 1 video (khai thị) thay vì cả tập; số cả tập chỉ có ở mục 1.1 (p=1) và 1.5 (p ≥ 2).
- E5 chỉ xét render + một tác vụ nền (Whisper hoặc analysis), đúng mô hình làn `prepare` + `render` (mỗi làn một job); chưa đo hai render song song cùng Whisper.
- "Tăng tốc Whisper trên máy GPU" nằm ngoài scope, không đo.
- Mẫu preset chỉ cho Short `k02` của `4oOZz2CBz3g`; không giữ mẫu khai thị (dung lượng).
- Thư mục bench ≈ 1.3 GB (hard-link nguồn + bản sao render) — giữ tới khi ORCHESTRATOR xong; xóa bằng `rm -rf ~/.cache/auto-short-cp11-bench` (ngoài mẫu preset nếu còn cần).
