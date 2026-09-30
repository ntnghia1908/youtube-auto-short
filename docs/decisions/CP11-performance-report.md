# CP11 — Báo cáo hiệu năng + khuyến nghị tối ưu

| Metadata | Value |
|---|---|
| Status | PROPOSED — chờ HUMAN LEAD chọn; chưa authorize tối ưu nào |
| Task contract | `docs/tasks/CP11-performance-measure.md` |
| Số liệu | `docs/decisions/CP11-performance-data.md` (mọi số dưới đây lấy từ đó; "§" = mục của file số liệu) |
| Người viết | ORCHESTRATOR, 2026-09-30 |

## 1. Tóm tắt

Máy chạy (VM 48 vCPU, không GPU) còn nhiều CPU nhàn rỗi: một ffmpeg render chỉ dùng ≈ 9 lõi, và Whisper chạy chậm nhất ở mức mặc định 48 luồng. Hai thay đổi execution-only (không đổi `config_hash` / `render_key`, không làm stale tập cũ) cho gần hết phần lợi:

| # | Khuyến nghị | Tiết kiệm ước tính / tập 1 giờ | Đổi hash | Rủi ro | Task dự kiến |
|---|---|---|---|---|---|
| **R1** | Render song song nhiều Short trong một job (p = 4) | Short 191 → ≈ 99 s (−92 s); khai thị 699 → ≈ 300 s (−400 s) | không | thấp–vừa: tranh CPU với làn `prepare` (§5) | S2 |
| **R2** | Whisper `cpu_threads = 24` thay 0 (= 48) | ≈ −730 s (1766 → 1039 s), chỉ tập không có caption | không | thấp: text giống từng chữ (§3) | S0 config / S2 nếu đổi mặc định |
| R3 | Whisper `BatchedInferencePipeline` (batch 8, ≤ 24 luồng) | thêm ≈ −200 s (1039 → 834 s), chỉ tập không có caption | có (transcript, nếu thêm khóa config) | vừa: segfault khi ≥ 28 luồng; text khác nhẹ (0.99) | S2 |
| R4 | Analysis: chạy hai lượt ffmpeg song song | −20 s (AV1) / −18 s (h264) | không | thấp: kết quả giống hệt (§4) | S1 |
| — | Không làm: đổi preset x264, `render.threads`, bất kỳ tham số selection nào | — | — | — | — |

Ví dụ tập caption YouTube làm cả Short + khai thị (tổng các stage ≈ 1 700 s hiện nay): R1 bớt ≈ 490 s (≈ −29%). Tập phải chạy Whisper: R1 + R2 bớt ≈ 1 220 s trên ≈ 3 450 s (≈ −35%); thêm R3 ≈ −41%.

## 2. Chi tiết từng khuyến nghị

### R1 — Render song song (ưu tiên 1)

- **Bằng chứng** (§1.1, §1.5): cả tập, mỗi tiến trình một video, threads mặc định: Short p=2 119.5 s, p=4 99.4 s, p=7 84.2 s; khai thị p=2 455.7 s, p=3 347.7 s, p=6 257.2 s. Một ffmpeg ≈ 9.3 lõi, và `threads` không giúp (§1.3: 16 = 0; 8 chậm hơn 34%) — nên chỉ song song nhiều tiến trình mới dùng được CPU còn lại.
- **Mức p đề xuất: 4.** Ở p=4, render ≈ 24 lõi; Whisper 24 luồng + render vẫn vừa 48 lõi. p cao hơn (7) chỉ lợi thêm ≈ 15 s với Short nhưng khi chồng Whisper sẽ tranh CPU nhiều hơn (§5: Whisper + một render đã ×1.27–1.34). Số khai thị ở p=4 chưa đo trực tiếp: nội suy giữa p=3 (348 s) và p=6 (257 s) ≈ 300 s.
- **Hash:** không đổi (lệnh ffmpeg mỗi Short giữ nguyên; §7). Tập cũ không render lại.
- **Vì sao S2:** thêm khóa execution-only mới (`render.jobs` hoặc tương tự) phải được loại khỏi `config_hash` — đổi danh sách hash trong `docs/decisions/CP7-render-contract.md` (dòng "`config_hash` = mọi key `[render]` trừ `output_dir`, `threads`…"). Cần giữ: file `.part` + đổi tên nguyên tử, thứ tự trong `render_manifest.json`, tiến độ trên web, lỗi một Short không để tiến trình khác chạy mồ côi.

### R2 — Whisper 24 luồng (ưu tiên 2, rẻ nhất)

- **Bằng chứng** (§3): đoạn 300 s: 48 luồng 144.4 s; 24 luồng 85.0 s (−41%); > 24 chậm dần (28 → 115 s, 32 → 124 s). Text giống từng chữ ở mọi mức luồng. `int8_float32` không nhanh hơn.
- **Hash:** `cpu_threads` là execution-only (CP3 contract), không đổi hash.
- **Hai cách:**
  - (a) Chỉ thêm `cpu_threads = 24` vào `[transcript.whisper]` trong `config.toml` của repo chính, rồi khởi động lại 8080. Không đổi code — S0 operational, HUMAN LEAD làm hoặc cho phép làm. **Khuyến nghị cách này.**
  - (b) Đổi ý nghĩa mặc định `0` (ví dụ `min(cpu_count, 24)`): đổi `docs/decisions/CP3-transcript-contract.md` → S2. Số 24 là của máy này (48 vCPU ảo, 1 core / socket), không chắc đúng máy khác, nên không đáng đổi mặc định bây giờ.
- Ảnh hưởng giới hạn: 3/14 video hiện có phải chạy Whisper.

### R3 — Whisper batched (tùy chọn, sau R2)

- **Bằng chứng** (§3): batch 8, 24 luồng 68.0 s (−20% so với R2); `BatchedInferencePipeline` có sẵn trong `faster-whisper` đã cài (không thêm dependency).
- **Rủi ro:** SIGSEGV ở `cpu_threads ≥ 28` (đã thử 28, 48; cả 2 lượt) → bắt buộc chặn luồng ≤ 24 khi batched; text khác nhẹ so với không batch (0.99) → transcript của tập mới khác cách cũ; đổi `docs/decisions/CP3-transcript-contract.md` (cách gọi Whisper, hash) → S2.
- Chỉ đáng làm nếu tập không có caption trở nên thường xuyên.

### R4 — Analysis song song (nhỏ)

- **Bằng chứng** (§4): chạy lượt shot và silence song song: 143 → 122.5 s (AV1), 58 → 40 s (h264); kết quả giống hệt production. Gộp một tiến trình không lợi (124 / 57 s).
- **Hash:** không đổi. Thay đổi trong `analysis/detect.py` / `stage.py`, không đổi contract → S1. Có thể gộp chung task với R1 nếu HUMAN LEAD muốn ít task.

## 3. Không khuyến nghị

- **Preset x264 nhanh hơn** (§1.4): `veryfast` chỉ nhanh ≈ 3% thời gian (render bị giới hạn bởi decode + filter, 45% thời gian), nhỏ hơn 26% dung lượng, SSIM 0.991 so với `medium`. Đổi preset làm đổi `render_key` → mọi tập render lại, tick "Đã đăng" thành stale. Không đáng vì tốc độ; mẫu đã gửi nếu HUMAN LEAD muốn cân nhắc vì dung lượng.
- **`render.threads`** (§1.3): giữ `0`.
- **Selection** (§2): `num_ctx` 24576 không nhanh hơn; 16384 **lỗi** (timeout); `think=false` trên 30b trả 0 clip; `qwen3:14b` nhanh hơn 22% (194 s so với 250 s) nhưng chỉ 6/7 clip trùng, và ta chưa đánh giá chất lượng — lợi nhỏ, đổi hash selection. Giữ nguyên cấu hình.
- **Whisper trên máy GPU:** ngoài scope (đổi architecture); có thể là bước lớn hơn R2 + R3 nếu sau này cần.

## 4. Phát hiện kèm theo (không phải tối ưu)

- **Selection không lặp lại hoàn toàn** (§2): cùng `seed=42`, `temperature=0`, lượt đầu sau khi Ollama nạp lại model ra 8 clip (4/7 trùng), các lượt sau lặp lại chính xác 7/7. Tức là "chạy lại selection" có thể cho kết quả khác dù config không đổi. Chỉ ghi nhận; không đề xuất sửa trong CP11.
- **Cache hoạt động đúng** (§6): chạy lại tập không đổi 0.05 s; sửa một title chỉ encode lại đúng Short đó (≈ 27 s).

## 5. Đề xuất thứ tự

1. R2 (a) — sửa `config.toml` + khởi động lại 8080 (khi hàng đợi rỗng).
2. R1 (+ R4 nếu muốn) — task S2 mới, dual-agent.
3. R3 — để sau, chỉ khi cần.
