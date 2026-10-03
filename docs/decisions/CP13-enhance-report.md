# CP13 — Báo cáo đo: enhance (phục hồi chi tiết) video nguồn

| Metadata | Value |
|---|---|
| Status | PROPOSED — số liệu E1 (CPU) có; E2 (GPU Windows) chờ HUMAN LEAD chạy; khuyến nghị §5 chờ HUMAN LEAD chọn |
| Task contract | `docs/tasks/CP13-enhance-measure.md` |
| Người viết | IMPLEMENTER (nháp), 2026-10-03 |
| Dữ liệu / video mẫu | `~/.cache/auto-short-cp13-test/` (ngoài repo): `out/compare/`, `out/metrics.json`, `out/*.json` |
| Script | `scripts/cp13_e1_bench.py` (E1), `scripts/enhance_bench_win.py` (E2), hướng dẫn `docs/guides/enhance-gpu-windows.md` |

## 1. Tóm tắt

- Model per-frame **`realesr-general-x4v3`** (rất nhẹ, 4.9 MB) cho hình ảnh sạch và nét hơn rõ rệt so với phóng thẳng (Lanczos), và **nét hơn chính bản "HD" của kênh gốc** trên đoạn đối chiếu. Chữ Hán trên màn hình rõ nét hơn hẳn. Mặt người không bị biến dạng ở mẫu đã xem (cần HUMAN LEAD kiểm bằng mắt).
- `RealESRGAN_x4plus` thêm hạt / họa tiết giả (trán, tóc) và nhấp nháy nhiều; `RealESRGAN_x2plus` gần như không hơn phóng thẳng nhưng nhấp nháy. Không đáng dùng so với `general-x4v3` (và chậm 3–14 lần).
- Nhấp nháy giữa khung ở vùng tĩnh: mọi model per-frame đều **cao hơn** Lanczos (xem §3). `general-x4v3` thấp nhất (1.2–1.7×); bản "HD" của kênh gốc cũng 1.9× Lanczos. Chỉ số này là rủi ro chính cần HUMAN LEAD xem video mẫu; chưa thử model video (RealBasicVSR…) vì không chạy được trên CPU/không có CUDA (§2).
- **CPU không dùng được cho cả tập** (≈ 36–160 giờ CPU cho 1 giờ video). GPU là bắt buộc; E2 để lấp số thật. Ước lượng FLOPs (chưa đo): `general-x4v3` hạ 360p/540p trên RTX 3060 ≈ 1–9 giờ / giờ video; RTX 3090 ≈ 0.4–3.4 giờ.
- Phát hiện quan trọng cho thiết kế: Short dùng crop 930×1080 của nguồn 1440×1080 và scale **1:1 về 1080 rộng** (CP7 R4), nên chi tiết phục hồi hiện nguyên vẹn trên Short. Nhưng chỉ ≈ vài phút / tập được dùng cho Short; **enhance theo từng đoạn (clip) thay vì cả tập** rẻ hơn ≈ 8–15 lần (§5). HUMAN LEAD đã chọn "cả video nguồn"; đây là lựa chọn cần cân nhắc lại.

## 2. E1 — Thí nghiệm chất lượng (CPU, VM 24 vCPU, PyTorch 2.14 CPU, 16 luồng)

### 2.1 Cấu hình đã chạy

Env `enhance-bench` (conda, Python 3.11, torch CPU, opencv, scikit-image, lpips) — tách khỏi `auto-short`. Kiến trúc nạp trực tiếp từ trọng số chính thức Real-ESRGAN (không cài `realesrgan` / `basicsr`).

| Nhãn | Model | Tiền xử lý → đầu ra | Số khung |
|---|---|---|---|
| `g10` / `g05` (A) | `realesr-general-x4v3`, denoise 1.0 / 0.5 | nguồn 352×262 giữ nguyên → ×4 → thu về 1454×1080 | 300 (10 s) |
| `g10_p360` / `g05_p360` (B, C) | như trên | hạ 360p → ×4 (1440p) → thu về 1080p | 300 |
| `g10_p540` (B, C) | `general-x4v3`, denoise 1.0 | hạ 540p → ×4 (2160p) → thu về 1080p | 60 (2 s) |
| `x4p` / `x4p_p270` | `RealESRGAN_x4plus` | A giữ nguyên; B, C hạ 270p → ×4 | 60 |
| `x2p` / `x2p_p540` | `RealESRGAN_x2plus` | A giữ nguyên; B, C hạ 540p → ×2 | 60 |

Model nặng (RRDB) chỉ chạy 2 s mỗi đoạn vì CPU ≈ 17 s/khung. Không chạy: GFPGAN (tùy chọn, bỏ để giữ phạm vi); model video RealBasicVSR hoặc tương đương: cần `mmcv` / `mmagic` + toán tử CUDA, nhiều GB, ≥ 1 phút/khung trên CPU — không khả thi trong CPU lab (khuyến nghị thử trên GPU nếu HUMAN LEAD thấy nhấp nháy là vấn đề).

### 2.2 Đoạn mẫu

| Đoạn | Nguồn | Ghi chú |
|---|---|---|
| A | bản cũ `AH5jLu40RMs` (**chỉ có 352×262**: định dạng video lớn nhất yt-dlp tải được là `134`, nhãn 360p) từ 1200.57 s | đích: `2mVA5If4M3w` (HD 1454×1080) từ 1200.0 s. Lệch thời gian bản cũ so với HD ≈ +0.55 s (tương quan âm thanh) trôi đến ≈ +0.95 s ở phút 50; khớp khung ở 1200.57 s (kiểm bằng mắt) |
| B | `By0ZVJTPW3Y` 960×720, từ 600 s | không có đích |
| C | `6R3GE2On7Yc` 1440×1080 (mờ), từ 600 s | không có đích |

Ghi chú: bản cũ chỉ 262p, tức là đoạn A là **tình huống khó nhất** (phóng ×4 từ video rất thấp); kênh gốc cũng làm từ nguồn như vậy.

### 2.3 Thời gian trên CPU (chỉ tham khảo; 16 luồng, một tiến trình)

| Đoạn / cấu hình | Đầu vào model | s/khung | Ghi chú |
|---|---|---|---|
| A `g10` / `g05` | 352×262 | 1.20 / 1.19 | 300 khung = 6 phút |
| B, C `g10_p360` / `g05_p360` | 480×360 | 2.42–2.47 | 300 khung = 12 phút |
| B, C `g10_p540` | 720×540 | 5.34–5.36 | |
| A `x2p` | 352×262 | 3.64 | |
| A `x4p` | 352×262 | 16.42 | |
| B, C `x2p_p540` | 720×540 | 16.8–17.2 | |
| B, C `x4p_p270` | 360×270 | 17.5–19.2 | |

Tốc độ hiệu dụng ≈ 170 GFLOP/s (xem §4). Model `general-x4v3` ≈ 1.17 M MAC / điểm ảnh đầu vào.

### 2.4 Chỉ số (E1) — nguồn `out/metrics.json`

Nhấp nháy = trung bình |chênh khung liền kề| (thang 0–255, xám) trên mặt nạ vùng tĩnh (độ lệch chuẩn theo thời gian của bản Lanczos < 2; ≈ vùng nền); cột "tương đối" chia cho Lanczos **cùng đoạn khung** (1.0 = không thêm nhấp nháy). Độ nét = phương sai Laplacian (cao ≠ tốt: nhiễu cũng làm tăng). PSNR / SSIM / LPIPS so với đích HD của kênh chỉ **tham khảo**: đích có màu / độ sáng khác bản cũ nên PSNR chỉ ≈ 17–18 dB cả với Lanczos; chỉ so sánh tương đối giữa các model, không nên xem là chất lượng.

| Đoạn | Cấu hình | Nhấp nháy | Tương đối Lanczos | Độ nét | PSNR | SSIM | LPIPS ↓ |
|---|---|---|---|---|---|---|---|
| A | Lanczos | 0.057 | 1.00 | 16 | 18.13 | 0.670 | 0.250 |
| A | `g10` | 0.068 | 1.18 | 116 | 16.90 | 0.659 | **0.227** |
| A | `g05` | 0.084 | 1.46 | 122 | 17.20 | 0.658 | 0.223 |
| A | `x4p` (60) | 0.117 | 2.38 | 151 | 17.59 | 0.665 | 0.239 |
| A | `x2p` (60) | 0.101 | 2.06 | 151 | 18.17 | 0.674 | 0.245 |
| A | đích HD của kênh | 0.106 | 1.86 | 80 | — | — | — |
| B | Lanczos | 0.049 | 1.00 | 92 | — | — | — |
| B | `g10_p360` | 0.073 | 1.49 | 196 | | | |
| B | `g05_p360` | 0.095 | 1.95 | 164 | | | |
| B | `g10_p540` (60) | 0.061 | 1.56 | 229 | | | |
| B | `x4p_p270` (60) | 0.199 | 5.07 | 131 | | | |
| B | `x2p_p540` (60) | 0.159 | 4.07 | 82 | | | |
| C | Lanczos | 0.037 | 1.00 | 165 | — | — | — |
| C | `g10_p360` | 0.065 | 1.73 | 442 | | | |
| C | `g05_p360` | 0.084 | 2.25 | 378 | | | |
| C | `g10_p540` (60) | 0.061 | 1.81 | 636 | | | |
| C | `x4p_p270` (60) | 0.171 | 5.09 | 343 | | | |
| C | `x2p_p540` (60) | 0.130 | 3.85 | 287 | | | |

Đọc nhanh: (1) `g10` thấp nhất trong các model về nhấp nháy ở mọi đoạn; hạ denoise (g05) làm nhấp nháy tăng; RRDB tăng 2–5×. (2) PSNR / SSIM không phân biệt được (so với đích đã khác màu); LPIPS ủng hộ `g10` / `g05` nhẹ. (3) Kết luận chất lượng cuối cùng do mắt HUMAN LEAD: xem `out/compare/`.

### 2.5 Quan sát bằng mắt (ảnh crop mặt / chữ Hán, khung 30; IMPLEMENTER xem một phần mẫu A, B_text, C_face)

- Lanczos: mờ, vuông khối nén (blocking) ở da và nền; chữ Hán mềm viền.
- `g10`: sạch, nét viền mắt / lông mày / chữ Hán; da mịn (hơi "nhựa"); nền không còn khối. Nét hơn đích HD của kênh gốc (đích mờ, bệt).
- `g05` (khử nhiễu mạnh hơn): mịn hơn, mất bớt chi tiết nhỏ, nhấp nháy cao hơn.
- `x4p`: hạt / họa tiết giả ở trán và nền, khung nhìn "bẩn"; chữ Hán có răng cưa nhẹ.
- `x2p`: gần như Lanczos, hơi nhòe; nháy nhiều.
- `g10_p540` so với `g10_p360`: chi tiết hơn chút (chữ Hán, nếp da), nhưng tốn ≈ 2.2× thời gian.

### 2.6 E1b — video cũ chưa xử lý 640×480 (Amendment 1)

Đối tượng thật: playlist "Kinh Địa Tạng Bồ Tát Bổn Nguyện" (`PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`, 102 tập ≈ 98 giờ, tối đa 640×480, định dạng `135` avc1 ≈ 361 kbps). Mẫu (tải bằng `yt-dlp --download-sections`, 10 s đầu của đoạn tải): **D** = tập 1 `9NQFsvecC04` từ 600 s; **E** = tập 100 `gXFNw1YTLmE` từ 1200 s. Cả hai 640×480, 29.97 fps, có mặt + chữ Hán. Không có đích HD. Cấu hình (không RRDB): `g10_p0` (không hạ, 480p → ×4 = 1920p → thu 1080p), `g10_p360` và `g05_p360` (hạ 360p). Không chạy `g05_p0` để tiết kiệm CPU (≈ 22 phút/đoạn).

| Đoạn | Cấu hình | s/khung (CPU 16 luồng) | Nhấp nháy | Tương đối Lanczos | Độ nét |
|---|---|---|---|---|---|
| D | Lanczos | — | 0.060 | 1.00 | 35 |
| D | `g10_p0` | 4.38 | 0.091 | 1.53 | 308 |
| D | `g10_p360` | 2.50 | 0.099 | 1.66 | 350 |
| D | `g05_p360` | 2.48 | 0.121 | 2.02 | 297 |
| E | Lanczos | — | 0.058 | 1.00 | 26 |
| E | `g10_p0` | 5.02 (4.4 lúc đầu; CPU có thể bị tranh) | 0.077 | 1.33 | 214 |
| E | `g10_p360` | 2.47 | 0.084 | 1.45 | 268 |
| E | `g05_p360` | 2.46 | 0.103 | 1.77 | 217 |

Quan sát bằng mắt (D_face, D_text, E_text; chưa xem toàn bộ video):
- Nguồn Lanczos rất mờ, mất mắt / chữ mềm. `g10_p0` giữ chi tiết mắt, lông mày, nét chữ Hán sắc nhất và **trung thành nhất** với hình gốc.
- Hạ 360p (`g10_p360`) làm mịn hơn, hình dạng mắt / môi bị "vẽ lại" nhiều hơn (cảm giác nhựa), nhiều nhấp nháy hơn `g10_p0`; chữ Hán vẫn rõ. `g05_p360` mịn hơn nữa, nhấp nháy cao nhất.
- Nghĩa là với nguồn 640×480 **không nên hạ khung** (ngược với 960×720 / 1440×1080 ở E1): `g10_p0`, chậm hơn ≈ 1.8× nhưng đẹp và ít nhấp nháy hơn. Nhấp nháy `g10_p0` 1.3–1.5× Lanczos, cùng cỡ các đoạn E1.
- Dung lượng `g10_p0` x264 `medium`, 1080p: crf 20 → 0.86–0.94 GiB/giờ; crf 23 → 0.59–0.64 GiB/giờ (nguồn gốc 640×480 ≈ 0.16 GiB/giờ).

Video / ảnh: `out/compare/D_compare_10s.mp4`, `E_compare_10s.mp4` (2×2: Lanczos, `g10_p0`, `g10_p360`, `g05_p360`), `D_face.jpg`, `D_text.jpg`, `E_face.jpg`, `E_text.jpg`. Mẫu Windows: `samples/D_640x480.mp4`, `E_640x480.mp4`; lệnh trong `docs/guides/enhance-gpu-windows.md` Bước 7.

**E3 cho 98 giờ (≈ 10.6 triệu khung; ước lượng FLOPs, chưa đo GPU; giả thiết như §4: 3060 3–10, 3090 8–25 TFLOP/s hiệu dụng).** `g10_p0`: 0.72 TFLOP/khung; `g10_p360`: 0.40 TFLOP/khung. Cả tập = 107 892 khung/giờ; chỉ đoạn dùng cho Short ≈ 7 phút/tập ≈ 12 590 khung (giả định như §5.2; 102 tập ≈ 1.28 triệu khung).

| Cấu hình | CPU (đo) / giờ video | RTX 3060 / giờ video | RTX 3090 / giờ video | 3060 cả 98 giờ | 3090 cả 98 giờ |
|---|---|---|---|---|---|
| `g10_p0` | 132–150 giờ | 2.2–7.2 giờ | 0.9–2.7 giờ | 215–705 giờ | 85–265 giờ |
| `g10_p360` | 74 giờ | 1.2–4.0 giờ | 0.5–1.5 giờ | 118–392 giờ | 46–148 giờ |

| Cấu hình | 3060 / tập (7 phút) | 3090 / tập | 3060 cả 102 tập | 3090 cả 102 tập |
|---|---|---|---|---|
| `g10_p0` | 0.25–0.84 giờ | 0.10–0.31 giờ | 26–86 giờ | 10–32 giờ |
| `g10_p360` | 0.14–0.47 giờ | 0.06–0.18 giờ | 14–48 giờ | 6–18 giờ |

Dung lượng nếu enhance cả 98 giờ (crf 23 → 20): ≈ 58–92 GiB (nguồn gốc ≈ 16 GiB); chỉ đoạn Short: ≈ 7–11 GiB. Khoảng GPU rất rộng — E2 trên RTX 3060 quyết định; nếu GPU gần cận dưới thì enhance cả 98 giờ chạy được trong vài tuần nền, nếu cận trên thì chỉ nên enhance đoạn dùng cho Short.

Gợi ý ngắn (không thay §5): với nguồn 640×480 dùng `g10` không hạ khung; chỉ đoạn Short tiết kiệm ≈ 8× so với cả tập; Short crop khoảng 418×480 rồi scale lên 1080 rộng (≈ 2.6×, CP7 R4) nên bản gốc rất mờ trên Short; đây là trường hợp enhance có lợi nhất.

## 3. E2 — Tốc độ GPU (chờ HUMAN LEAD)

Hướng dẫn: `docs/guides/enhance-gpu-windows.md`. Đoạn mẫu cho Windows: `~/.cache/auto-short-cp13-test/samples/` (3 file mp4 ≈ 0.25 / 1.1 / 2.3 MB). **Chưa đo GPU.** Bảng điền kết quả:

| Card | Model / cấu hình | Đoạn | s/khung | fps | VRAM đỉnh (MB) | Nhiệt độ max | fp16 / tile |
|---|---|---|---|---|---|---|---|
| RTX 3060 | `g10`, A | A_old_352x262 | | | | | |
| RTX 3060 | `g10_p360` | B_960x720 | | | | | |
| RTX 3060 | `g10_p540` | B_960x720 | | | | | |
| RTX 3060 | `g10_p540` | C_1440x1080 | | | | | |
| RTX 3060 | `x4p` / `x4p_p270` | A / B | | | | | |
| RTX 3060 | `x2p_p540` | B | | | | | |
| RTX 3060 | `g10` (không hạ) / `g10_p360` | D_640x480 | | | | | |
| RTX 3060 | `g10` (không hạ) | E_640x480 | | | | | |
| RTX 3090 | (cùng bộ trên) | | | | | | |

Script kiểm chạy được ở chế độ CPU trên VM (`--device cpu`, 3 khung A: 2.06 s/khung ở 8 luồng; tile 256 chạy được; `--device cuda` báo lỗi rõ khi không có CUDA). Chưa chạy được nhánh CUDA / fp16 / `nvidia-smi` — kiểm thật lần đầu khi HUMAN LEAD chạy.

## 4. E3 — Ước lượng

Ước lượng FLOPs (không phải số đo GPU). Hiệu dụng CPU đo được ≈ 170 GFLOP/s. Giả thiết GPU fp16: RTX 3060 3–10 TFLOP/s hiệu dụng, RTX 3090 8–25 TFLOP/s (khoảng rộng vì chưa đo; E2 sẽ thay). 1 giờ video = 107 892 khung (29.97 fps).

| Cấu hình | FLOP / khung | CPU 16 luồng (đo) | RTX 3060 (ước) | RTX 3090 (ước) |
|---|---|---|---|---|
| `g10`, nguồn 262p (như A) | 0.22 T | 36 giờ | 0.7–2.2 giờ | 0.3–0.8 giờ |
| `g10_p360` | 0.40 T | 72 giờ | 1.2–4.0 giờ | 0.5–1.5 giờ |
| `g10_p540` | 0.91 T | 160 giờ | 2.7–9 giờ | 1.1–3.4 giờ |
| `x2p_p540` / `x4p_p270` (RRDB) | ≈ 3× `g10_p540` | ≈ 500 giờ | ≈ 9–30 giờ | ≈ 3–10 giờ |

Cho **1 giờ video**. Thư viện hiện có trong `work/` (22 tập, 21.4 giờ video): nhân 21.4 (ví dụ `g10_p360` RTX 3060 ≈ 25–86 giờ; 3090 ≈ 11–32 giờ). Với 43 tập (≈ 42 giờ) nhân đôi. Dùng một GPU không luôn mở (tunnel) và chỉ khi hàng đợi rỗng → thời gian thực tế lâu hơn.

Dung lượng (đo trên mẫu, x264 `medium`, 1080p `g10_p360`): crf 20 → 0.75 (B) / 0.96 (C) GiB / giờ; crf 23 → 0.51 / 0.65 GiB / giờ. Nguồn hiện nay: 1440×1080 h264 1.46–1.93 Mbps (≈ 0.65–0.85 GiB/giờ), 960×720 0.85–0.98 Mbps, 1454×1080 vp9 1.2–1.36 Mbps (`work/` 22 tập = 12.9 GiB). Nghĩa là nguồn enhance ≈ cùng cỡ (crf 23) đến ≈ 1.3× (crf 20) nguồn hiện tại; thêm một bản nữa (không xóa nguồn gốc) ≈ +13 GiB / 22 tập. Số trên chỉ cho 10 s mẫu, chưa đại diện toàn tập.

Ảnh hưởng tới render (đọc contract CP7, chưa chạy thử): nguồn enhance cùng kích thước 1440×1080 / 1454×1080 → bước crop / scale giữ nguyên; giải mã h264 CFR nhẹ hơn vp9 / av1 nhưng encode/lưu thêm; `render_key` / hash nguồn: nếu nguồn đổi sha256 thì analysis / transcript / selection / titling stale — cần dùng "nguồn HD" chỉ cho bước render, không đổi nguồn của các stage trước (xem §5).

## 5. Khuyến nghị (PROPOSED — chờ HUMAN LEAD)

### 5.1 Model

- **Ứng viên duy nhất: `realesr-general-x4v3`** (nhẹ nhất: 1,2–5,4 s/khung CPU, nhanh hơn RRDB 3–15 lần). RRDB loại: `x4plus` thêm hạt / họa tiết giả, `x2plus` gần như không hơn Lanczos, cả hai nhấp nháy 2–5×.
- ORCHESTRATOR xem ảnh crop (A_face, C_face): `g10` sạch và nét nhất (lông mày, mắt, chữ Hán) nhưng **da bị "nhựa"** (mịn quá, mất nếp da) — rõ nhất ở C `g10_p360`; `g05` và `g10_p540` tự nhiên hơn một chút; bản HD của kênh gốc mềm hơn `g10` nhưng tự nhiên. Đây là đánh đổi cảm quan → **HUMAN LEAD chọn bằng mắt** trên video so sánh (`out/compare/*_compare_10s.mp4`, `*_compare_2s.mp4`): `g10` hay `g05`, hạ 360p hay 540p.
- Nhấp nháy: mọi cấu hình per-frame đều hơn Lanczos (`g10` 1,2–1,7×; bản HD kênh gốc 1,86×) → mức của `g10` không tệ hơn kênh gốc; chấp nhận nếu HUMAN LEAD xem video thấy ổn.

### 5.2 Phạm vi

HUMAN LEAD đã chọn **cả video nguồn**. Ước lượng `g10_p360` (chưa đo GPU): 1 giờ video ≈ 1,2–4 giờ RTX 3060; thư viện hiện có 21,4 giờ video → ≈ 1–3,5 ngày GPU liên tục. Phương án rẻ hơn 8–15 lần (chỉ đoạn dùng cho Short / khai thị) ghi lại để HUMAN LEAD cân nhắc nếu E2 cho thấy 3060 chậm; không đổi quyết định khi chưa có số GPU.

### 5.3 Kiến trúc S2 — worker **kéo việc** (pull), chịu được mất mạng

HUMAN LEAD 2026-10-03: máy RTX 3060 có thể đứt mạng → worker phải tự làm khi mất mạng và gửi kết quả khi có mạng lại. Vì vậy **đảo chiều** so với Ollama (VM gọi vào GPU): worker Windows là **client**, VM là server.

1. **Nhận việc** (khi online): worker gọi API VM `POST /api/enhance/lease` (token riêng) → nhận một tập + tham số (model, denoise, `pre_height`, `config_hash`) + lease ≈ 48 giờ. Tải video nguồn về ổ Windows bằng HTTP Range (đứt thì tải tiếp).
2. **Làm offline**: enhance theo đoạn ≈ 60 s, mỗi đoạn xong ghi xuống ổ (`seg_NNNN.mp4`, mã hóa NVENC) + file trạng thái → mất mạng / mất điện / khởi động lại máy vẫn làm tiếp từ đoạn dở.
3. **Gửi lên** (khi online lại): `PUT /api/enhance/<id>/seg/<n>` từng đoạn kèm sha256; VM kiểm và lưu `work/<id>/enhanced/<config_hash>/`; đoạn hỏng → gửi lại đúng đoạn đó. Gia hạn lease khi còn làm.
4. **Ghép**: đủ đoạn → VM ghép (concat, không mã hóa lại) thành `source_hd.mp4` (+ `enhance.json`: sha256 nguồn, model, tham số, danh sách đoạn). Bước ghép / render lại chạy ở làn VM khi hàng đợi rảnh.
5. **Hết lease** (worker mất tích > 48 giờ) → tập trả về hàng đợi (sau này có thể giao 3090). Đoạn đã nhận vẫn giữ (cùng `config_hash`).

- **Kết nối**: worker gọi API web của VM qua chính kết nối SSH đang có (thêm `-L` vào lệnh SSH hiện tại); không cần mở / giữ port 11438 trên Windows. Token riêng cho worker (không dùng mật khẩu web).
- **Pipeline**: transcript / analysis / selection / titling dùng nguồn gốc (không stale); chỉ `render` đọc `source_hd.mp4` khi có (khóa nguồn HD vào `render_key`). Tập đã đăng không tự render lại (tick "Đã đăng" stale, lý do như CP8.14) — HUMAN LEAD bấm render lại khi muốn; khai thị `.kt` dùng chung nguồn HD.
- **Worker Windows**: một chương trình Python chạy nền (Task Scheduler khi đăng nhập / khởi động), dependency chỉ trên Windows (PyTorch CUDA, opencv; NVENC qua ffmpeg). Cài theo hướng dẫn từng bước như E2.
- **Giá**: ADR mới (kiến trúc + API worker + token = security model), API mới trên web, worker Windows, dung lượng +≈ 0,5–1 GiB / giờ video (`source_hd.mp4`; có thể xóa nguồn gốc sau khi ghép nếu HUMAN LEAD muốn), mạng ≈ 0,7 GiB tải xuống + 0,5–1 GiB gửi lên mỗi giờ video, tập cũ enhance bù theo hàng đợi.

### 5.4 Bước tiếp theo đề xuất

1. HUMAN LEAD xem video so sánh → chọn cấu hình (`g10` / `g05`, 360p / 540p) hoặc dừng nếu da "nhựa" không chấp nhận được.
2. HUMAN LEAD chạy E2 trên RTX 3060 → ORCHESTRATOR điền §3, cập nhật §4.
3. Nếu tiếp tục: ADR + contract S2 theo §5.3 (dual-agent).

## 6. Giới hạn / sai lệch

- Mẫu nhỏ (3 đoạn × 10 s; model nặng 2 s); mặt nạ vùng tĩnh và độ nét chỉ là chỉ số thô.
- Bản cũ chỉ 352×262 (yt-dlp không có bản lớn hơn) → đoạn A khó hơn thực tế của 43 tập hiện có (≥ 720p).
- Chưa có số GPU; số GPU ở §4 là ước lượng FLOPs với hiệu dụng giả định.
- GFPGAN và model video không thử (lý do ở §2.1).
- Số tập thư viện: `work/` hiện có 22 tập chính (không tính `.kt`), khác "35 + 8" trong contract (chưa rõ nguyên nhân: có thể đếm ở thời điểm khác hoặc cả `.kt`); dùng số đo thực.
