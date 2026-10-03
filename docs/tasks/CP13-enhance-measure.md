# Task: CP13 — Đo: enhance (phục hồi chi tiết) video nguồn

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project; chạy thí nghiệm CPU, viết script đo GPU + hướng dẫn Windows; ORCHESTRATOR review, chọn mẫu, viết khuyến nghị.
- Base commit / branch: `b57fc29` (`main`) / `feature/cp13-enhance-measure` (worktree `../youtube-auto-short-enh`)
- Human Lead approval: APPROVED (HUMAN LEAD 2026-10-03, nguyên bản)
- Implementation authorized: YES

## Amendment 1 (HUMAN LEAD 2026-10-03)

Nguồn hiện có trong `work/` **đã là bản đã xử lý — không enhance lại**. Đối tượng enhance là video cũ chưa xử lý, ví dụ playlist "Kinh Địa Tạng Bồ Tát Bổn Nguyện (102 tập)" (`PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`: 102 tập, ≈ 98 giờ, tối đa 640×480). Thêm **E1b**: lặp E1 (`g10`, `g05`, Lanczos; không RRDB) trên 2 đoạn 10 s của tập 1 (`9NQFsvecC04`) và một tập cuối, 640×480 → 1080p, + video so sánh / ảnh crop; thêm đoạn 640×480 vào mẫu E2 và hướng dẫn Windows; E3 tính lại cho 98 giờ (cả tập và chỉ đoạn dùng cho Short). Status quay lại IN_PROGRESS tới khi E1b xong.

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ thêm script đo trong `scripts/`, hướng dẫn cài đặt và báo cáo; không đổi `src/`, config, contract, dependency của project hay hành vi production (như CP11 / CP8.20). Thư viện thí nghiệm (PyTorch CPU, Real-ESRGAN…) cài trong conda env riêng `enhance-bench`, không vào dependency project. Tích hợp (worker GPU, làn enhance, dùng nguồn HD khi render) là task S2 riêng sau báo cáo — cần ADR (architecture + dependency + worker mạng mới).

## Bối cảnh

HUMAN LEAD 2026-10-03: muốn enhance video cũ thành HD như kênh gốc đã làm (`AH5jLu40RMs` bản cũ → `2mVA5If4M3w` bản HD; `2mVA5If4M3w` đã có trong `work/`). Yêu cầu: enhance **cả video nguồn**; chỉ chạy khi server không có task; chạy trên GPU qua port 11438.

Hạ tầng: VM không có GPU (24 CPU, 502 GB). Hai GPU trên máy Windows, nối về VM bằng SSH reverse tunnel: RTX 3090 24 GB (Ollama, `127.0.0.1:11437`), RTX 3060 12 GB (sẽ mở ở `11438`, không phải lúc nào cũng mở). Hiện chỉ có Ollama — không enhance video được; cần worker riêng (Python + PyTorch CUDA).

Nguồn hiện có: 35 tập 1440×1080 / 1454×1080, 8 tập 960×720 — vấn đề là **mờ** (bản upscale từ SD), không phải thiếu pixel.

## Goal

Một báo cáo để HUMAN LEAD chọn: (1) model / cấu hình enhance (theo mắt nhìn trên mẫu); (2) có khả thi trên RTX 3060 / 3090 không (thời gian mỗi tập, dung lượng); (3) kiến trúc cho task S2 tích hợp.

## Scope

- In scope:
  - **E1 Chất lượng (CPU trên VM).** Conda env `enhance-bench` (PyTorch CPU). Ứng viên tối thiểu: Real-ESRGAN `realesr-general-x4v3` (có `denoise_strength`), `RealESRGAN_x4plus`, `RealESRGAN_x2plus`; tùy chọn GFPGAN cho mặt người; nếu khả thi trên CPU: một model video (RealBasicVSR hoặc tương đương) để so độ nhấp nháy. Cách xử lý: hạ về ~540p / 720p rồi phóng lại 1080p (tránh phóng bản upscale mờ).
  - Mẫu: 3–4 đoạn 10 s: (a) cùng một đoạn bài giảng ở `AH5jLu40RMs` (tải bản cũ vào bản sao) so với bản HD của kênh `2mVA5If4M3w` làm "đích"; (b) một tập 960×720; (c) một tập 1440×1080 mờ. Xuất video so sánh cạnh nhau (gốc / mỗi model / đích nếu có) + ảnh khung cắt sát mặt + chữ Hán trên màn hình.
  - Đo thêm: độ nhấp nháy giữa khung (chênh lệch khung liền kề ở vùng tĩnh), thời gian / khung trên CPU (chỉ tham khảo).
  - **E2 Tốc độ GPU (Windows).** Script độc lập `scripts/enhance_bench_win.py` + hướng dẫn `docs/guides/enhance-gpu-windows.md` (cài Python, PyTorch CUDA, model; chạy bench trên đoạn mẫu; in fps, VRAM, nhiệt độ nếu có). HUMAN LEAD chạy trên RTX 3060 (và 3090 nếu muốn) rồi dán kết quả; ORCHESTRATOR đưa vào báo cáo. Không mở port / dịch vụ mạng mới trong task này.
  - **E3 Ước lượng.** Từ E1 + E2: thời gian enhance một tập 1 giờ / cả thư viện hiện có; dung lượng nguồn HD (mã hóa lại); ảnh hưởng tới render (nguồn lớn hơn).
  - Báo cáo `docs/decisions/CP13-enhance-report.md`: số liệu, mẫu, khuyến nghị PROPOSED gồm phác thảo kiến trúc S2 (worker HTTP trên Windows qua tunnel 11438, giao thức gửi / nhận theo đoạn, làn `enhance` chỉ chạy khi hàng đợi rỗng và worker sống, dừng / chạy tiếp theo đoạn, dùng nguồn HD khi render, tập đã đăng / khai thị, hash stage).
  - Dữ liệu: bản sao `~/.cache/auto-short-cp13-test/` — không ghi `work/` / `output/` chính.
- Out of scope: sửa `src/`; worker mạng thật; render lại tập thật; đổi dependency project; tải model trả phí / dịch vụ cloud.

## Authority / key decisions

- HUMAN LEAD 2026-10-03: enhance cả video nguồn; chạy khi server rảnh; GPU nhỏ RTX 3060 12 GB ở port 11438 (không luôn mở), cả hai GPU là Windows; HUMAN LEAD chưa biết cài worker → cần hướng dẫn từng bước.
- CPU thí nghiệm không chạy chồng job của 8080: chạy khi hàng đợi 8080 rỗng, giới hạn luồng (≤ 16) để không làm nghẽn web.

## Acceptance Criteria

1. Env `enhance-bench` tách khỏi env `auto-short`; `git status` repo chính sạch, `work/` / `output/` chính không đổi.
2. Có video so sánh + ảnh khung cho ≥ 3 đoạn mẫu × ≥ 3 cấu hình, gồm đoạn có bản HD của kênh làm đích.
3. Script + hướng dẫn Windows chạy được trên VM ở chế độ CPU (kiểm cú pháp / chạy thử), hướng dẫn đủ để HUMAN LEAD tự làm.
4. Báo cáo có số liệu E1 (thời gian CPU, nhấp nháy), chỗ trống E2 cho kết quả GPU, ước lượng E3, và khuyến nghị PROPOSED kèm phác thảo kiến trúc S2 và cái giá (dependency, ADR, dung lượng, tập cũ).
5. `python -m pytest -q -n auto` PASS (không đổi `src/`); `node scripts/framework-check.mjs` PASS.

## Required verification

- Chạy E1 trên bản sao — AC 1, 2 (ORCHESTRATOR xem mẫu).
- Chạy `scripts/enhance_bench_win.py` chế độ CPU trên VM — AC 3.
- `python -m pytest -q -n auto`, `node scripts/framework-check.mjs` — AC 5.

Tất cả required verification phải chạy và PASS trước READY. E2 trên GPU do HUMAN LEAD chạy; nếu chưa có kết quả khi READY, báo cáo ghi rõ "chưa đo GPU".

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API.

- [ ] Xem video so sánh, chọn cấu hình.
- [ ] Làm theo hướng dẫn trên RTX 3060, dán kết quả bench.
- [ ] Chọn: làm S2 tích hợp (có / không), GPU dùng (3060 / 3090 / cả hai).

## Result

- Main changes: `scripts/enhance_bench_win.py` (E2, độc lập, CPU/CUDA), `scripts/cp13_e1_bench.py` (E1), `docs/guides/enhance-gpu-windows.md`, báo cáo `docs/decisions/CP13-enhance-report.md` (PROPOSED). Video so sánh + ảnh crop ở `~/.cache/auto-short-cp13-test/out/compare/` (ngoài repo). Không đổi `src/`.
- Tests: E1 chạy đủ 3 đoạn × 4–5 cấu hình (CPU); `enhance_bench_win.py` chạy chế độ CPU trên VM (và tile); `python -m pytest -q -n auto` + `node scripts/framework-check.mjs` — PASS (1337 passed, 1 skipped; framework-check PASS).
- Review: ORCHESTRATOR round 1 ACCEPTED (2026-10-03): xem ảnh crop A_face / C_face (g10 nét nhất nhưng da "nhựa"); script GPU chạy thử CPU trên VM OK; viết lại §5 (model, phạm vi, kiến trúc worker kéo việc chịu mất mạng theo yêu cầu HUMAN LEAD). E2 GPU chưa đo — báo cáo ghi rõ.
- Important findings / decisions: bản cũ `AH5jLu40RMs` chỉ 352×262; `general-x4v3` tốt nhất, RRDB nhấp nháy + chậm; mọi model per-frame nhấp nháy hơn Lanczos; Short dùng nguồn 1:1 → enhance theo từng clip rẻ hơn cả tập ≈ 8–15×; E2 GPU chưa đo.
- E1b (Amendment 1): 2 đoạn 640×480 (D = tập 1, E = tập 100) × `g10_p0` / `g10_p360` / `g05_p360` + Lanczos; E3 tính lại cho 98 giờ; nguồn 640×480 nên chạy `g10` không hạ khung (báo cáo §2.6).
- Known limitations: chưa đo GPU (E2 chờ HUMAN LEAD); không thử GFPGAN / model video; ước lượng GPU là FLOPs giả định.
- PR:
