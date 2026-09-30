# Task: CP11 — Đo hiệu năng pipeline + khuyến nghị tối ưu

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project; viết script đo và chạy thí nghiệm, ORCHESTRATOR review số liệu + viết khuyến nghị.
- Base commit / branch: `224f166` (`origin/main`) / `feature/cp11-performance` (worktree `../youtube-auto-short-cp11`)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-30: APPROVE TASK; Whisper trên máy GPU giữ ngoài scope; thí nghiệm Ollama chỉ chạy khi hàng đợi 8080 rỗng)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ thêm script đo trong `scripts/` và một báo cáo; không đổi source trong `src/`, không đổi config mặc định, contract, dependency hay hành vi production. Mọi tối ưu được chọn sau báo cáo là task riêng (S1/S2 theo từng mục) — task này dừng ở decision gate đó.

## Bối cảnh

`AUTO_SHORT_CHECKPOINT_PLAN.md` CP11: "Measure on the actual target machine before selecting optimization strategies."

Máy chạy: VM 48 CPU, 125 GB RAM, **không có GPU**; Ollama (qwen3:30b) ở máy GPU, truy cập qua `127.0.0.1:11437`. Whisper chạy CPU (`large-v3-turbo`, `int8`).

Baseline từ `manifest.json` của 28 tập trong `work/` (video ≈ 1 giờ, giây, min–max):

| Stage | Short | Khai thị | Ghi chú |
|---|---|---|---|
| ingest | 39–720 | 1–283 | mạng / YouTube; `.kt` dùng lại nguồn |
| transcript (caption YouTube) | 1–3 | 0 | 11/14 video |
| transcript (Whisper CPU) | 1728–1862 | 0 | 3/14 video; ≈ 0.5× thời lượng video |
| analysis | 57–143 | 57–143 | hai lượt ffmpeg (shot, silence) |
| selection | 169–864 | 150–312 | Ollama, `num_ctx` 32768, `think` bật |
| titling | 20–60 | 12–23 | Ollama |
| render | 190–542 | 337–865 | ffmpeg libx264 `medium`, tuần tự từng Short |

Thứ tự đáng đo theo baseline: render → selection → Whisper → analysis. Titling và ingest không phải điểm nghẽn do code.

## Goal

Có báo cáo số liệu đo trên máy thật cho từng điểm nghẽn, kèm khuyến nghị xếp hạng (lợi ích ước tính, rủi ro, có làm lại artifact cũ hay không), để HUMAN LEAD chọn tối ưu nào được làm.

## Scope

- In scope:
  - Script đo `scripts/cp11_bench.py` (chỉ stdlib + package hiện có), chạy trên **bản sao** dữ liệu ở `~/.cache/auto-short-cp11-bench/` với config riêng.
  - Thí nghiệm E1–E6 bên dưới.
  - Báo cáo `docs/decisions/CP11-performance-report.md` (Status: PROPOSED) + file số liệu thô.
  - Mẫu video cho các phương án đổi chất lượng hình (preset), gửi HUMAN LEAD xem.
- Out of scope:
  - Sửa `src/`, đổi config mặc định, đổi `config.toml` repo chính.
  - Ghi vào `work/`, `output/` chính; khởi động lại 8080.
  - Thêm dependency; chạy Whisper trên máy GPU (đổi architecture — chỉ ghi nhận là phương án, không thử).
  - Thực hiện tối ưu nào.

## Authority / key decisions

- D1 — CP11 tách hai bước: task này (đo + khuyến nghị); mỗi tối ưu được chọn là task riêng.
- D2 — Ràng buộc cho mọi khuyến nghị: nêu rõ phương án có đổi `config_hash` / `render_key` hay không. Phương án đổi hash làm tập cũ chạy lại stage và tick "Đã đăng" thành stale → xếp riêng, cần HUMAN LEAD duyệt rõ (CP2 workspace contract, CP8.2 `render_key`).
- D3 — Thiết lập *execution-only* (`render.threads`, `whisper.cpu_threads`, số job song song) được ưu tiên vì không đổi hash.
- D4 — Phương án đổi chất lượng đầu ra (preset x264, model / `think` của selection) chỉ đo và báo cáo; quyết định bằng mắt / tai của HUMAN LEAD trên mẫu.
- D5 — Thí nghiệm dùng Ollama chỉ chạy khi hàng đợi 8080 rỗng (kiểm `GET /api/ps` + trạng thái job) để số đo không nhiễu và không làm chậm việc của HUMAN LEAD.
- Authority liên quan: `docs/decisions/CP7-render-contract.md`, `CP5-selection-contract.md`, `CP3-transcript-contract.md`, `CP4-analysis-contract.md`, `CP8.3-web-contract.md` W5 (làn).

## Implementation approach

Tập đo: một tập Short có Whisper (`4oOZz2CBz3g`), một tập caption YouTube, và tập `.kt` tương ứng; sao chép (hard-link nguồn) sang thư mục bench. Mỗi phép đo chạy ≥ 2 lần, ghi wall time, CPU time, kích thước file.

- E1 Render (ưu tiên 1): `threads` 0 / 8 / 16; chạy song song 1 / 2 / 3 / 4 ffmpeg; preset `medium` / `fast` / `veryfast` (thời gian, dung lượng, mẫu xem); tách thời gian decode + seek với encode; riêng cho Short và khai thị.
- E2 Selection: thời gian từng window, token/s, thời gian load model, số lần retry (từ `selection_log.json` + đo lại); `num_ctx` 32768 so với vừa đủ prompt; `think` bật / tắt và `qwen3:14b` (so clip được chọn với bản hiện tại).
- E3 Whisper CPU: `cpu_threads` 0 (48) / 8 / 16 / 24; `compute_type` `int8` / `int8_float32`; suy luận theo batch của `faster-whisper` nếu bản đã cài có sẵn; so text với bản hiện tại.
- E4 Analysis: thời gian từng lượt ffmpeg; gộp một lượt hoặc chạy hai lượt song song; kết quả phải giống hệt.
- E5 Song song an toàn: render song song trong lúc Whisper / analysis chạy (làn `prepare` + `render`) — mức chậm lẫn nhau.
- E6 Cache: tỉ lệ stage / Short được tái dùng khi chạy lại tập không đổi và khi sửa một title (kỳ vọng: chỉ Short đó render lại).

## Acceptance Criteria

1. `scripts/cp11_bench.py` chạy lại được từng thí nghiệm E1–E6 bằng một lệnh, chỉ ghi vào thư mục bench.
2. Báo cáo có bảng số đo cho E1–E6 (mỗi ô ≥ 2 lần chạy) và ghi rõ thí nghiệm nào không chạy được, vì sao.
3. Báo cáo có danh sách khuyến nghị xếp hạng; mỗi mục ghi: giây tiết kiệm ước tính trên một tập 1 giờ, rủi ro, đổi hash hay không (D2), S-class dự kiến của task thực hiện.
4. Mẫu video cho từng preset đo ở E1 đã gửi HUMAN LEAD.
5. `git status` của repo chính, `work/`, `output/` chính không đổi do task; 8080 không bị khởi động lại.
6. Không có thay đổi trong `src/`, `pyproject.toml`, `config.example.toml`.

## Required verification

- `python scripts/cp11_bench.py --help` và một lần chạy ngắn mỗi thí nghiệm — AC1.
- `python -m pytest -q -n auto` — không hồi quy (AC6).
- `node scripts/framework-check.mjs` — tài liệu hợp lệ.
- `git diff --stat 224f166 -- src pyproject.toml config.example.toml` rỗng — AC6.
- So `manifest.json` của tập đo trong `work/` chính trước / sau — AC5.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Task không chạm database, security model hay public API contract → manual test là điểm danh.

- [ ] Xem mẫu preset, chọn mức chấp nhận được.
- [ ] Đọc báo cáo, chọn tối ưu được làm (mở task riêng).

## Result

- Main changes: `scripts/cp11_bench.py` (E1–E6, `hashes`, `setup`, `--quick`; chỉ ghi vào thư mục bench); `docs/decisions/CP11-performance-data.md` (số liệu thô); `docs/decisions/CP11-performance-report.md` (khuyến nghị R1–R4, PROPOSED).
- Tests: `pytest -q -n auto` 1199 passed, 1 skipped (một lượt trước đó 1 fail `test_lanes_artifacts_identical_to_serial` — flaky đã biết, chạy riêng PASS); `framework-check` PASS; `git diff --stat 224f166 -- src pyproject.toml config.example.toml` rỗng; `manifest.json` 3 tập đo ở `work/` chính giữ nguyên sha256 + mtime; mọi thí nghiệm chạy `--quick` được.
- Review: ORCHESTRATOR round 1 ACCEPTED (số liệu nhất quán giữa các lượt, guard thư mục bench, hash kiểm bằng code).
- Important findings / decisions: R1 render song song p=4 (Short −92 s, khai thị ≈ −400 s, không đổi hash); R2 Whisper `cpu_threads=24` (−41%, text giống hệt); R3 Whisper batched (−20% thêm, segfault ≥ 28 luồng); R4 analysis song song (−20 s). Không khuyến nghị đổi preset / threads / selection. Selection không lặp lại hoàn toàn sau khi Ollama nạp lại model. Ngoài scope: render production lỗi kiểm frame rate ở `jr8mue8TJA0`, `VlLxSpVCcws` (+ `.kt`) — báo HUMAN LEAD, không sửa.
- Known limitations: E2 chỉ trên một tập Short; E3 đoạn 300 s ngoại suy tuyến tính; khai thị p=4 nội suy; E5 chưa đo hai render + Whisper. Dữ liệu bench ≈ 1.3 GB ở `~/.cache/auto-short-cp11-bench/` (xóa khi xong).
- PR:
