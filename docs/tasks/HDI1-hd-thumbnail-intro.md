# Task: HDI1-hd-thumbnail-intro — Bản HD ngang có 3 giây thumbnail đầu video

## Status / Approval

- Status: DRAFT
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, route + ffmpeg mới); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-29: "Tạo thêm 1 bản địa tạng hd để tôi test trước" → xem bản thử `output/_samples/dt-hd-intro/DiaTang_Tap1_HD_intro.mp4` → "Ok viết task riêng"
- Parallel group: —
- Owned paths: `src/auto_short/render/hd_intro.py` (mới), `src/auto_short/web/routes/episodes.py` (chỉ route tải HD có intro), `src/auto_short/web/static/` (chỉ thêm link "Tải HD có intro" cạnh link HD hiện có), `src/auto_short/config.py` + `config.example.toml` (chỉ nếu G2 = cache có giới hạn), `tests/test_hd_intro.py` (mới), contract này
- Dependencies: THUMB1 (#182, thumbnail tập khổ ngang hợp lệ qua `episode.valid_files`), VERT2 (`render/full.intro_image` — cách tìm playlist + dựng thumbnail), HD2a (mượn HD từ kho 3090)
- Base commit / branch: `origin/main` sau khi THUMB1 merge / `feature/hdi1-hd-intro`
- Human Lead approval: pending (G1, G2)
- Implementation authorized: NO

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1: thêm một route tải + một module ffmpeg; không đổi file HD gốc, kho 3090, Short, bản dọc hay security model (route dùng auth / kiểm id hiện có).

## Goal

Trên trang tập, cạnh "Tải HD" có thêm "Tải HD có intro": file HD ngang giống hệt bản HD hiện có nhưng 3 giây đầu là thumbnail tập khổ ngang đang dùng (Bồ Tát + "TẬP N" với Địa Tạng), không encode lại phần bài giảng.

## Scope

- In scope:
  - `render/hd_intro.py`: từ HD hiệu lực (`source_hd.mp4` cục bộ, hoặc mượn từ kho như HD2a khi đã giải phóng) + thumbnail ngang hợp lệ (`episode.valid_files`, dựng nếu thiếu như `full.intro_image`) → encode intro đúng **90 khung** (3,003 s ở 30000/1001; tổng quát: `round(3 × fps)` khung) cùng codec / profile / kích thước / pix_fmt / timescale với HD, âm thanh im lặng cùng codec (aac / opus) / sample rate / số kênh, cắt cùng độ dài khung hình; ghép bằng concat demuxer `-c copy` + `+faststart`. Codec HD ngoài h264 + aac/opus → báo lỗi rõ, không tạo file sai.
  - Khung ảnh: HD khác 16:9 (vd. 1440×1080 của Địa Tạng) xử lý theo **G1**.
  - Lưu / phục vụ theo **G2**; tên tải `ep.hd_download_name` thêm hậu tố `_intro`.
  - Kiểm sau ghép: thời lượng = HD + intro (±1 khung), mốc bắt đầu hình và tiếng của phần HD lệch ≤ 20 ms (đo pts gói đầu sau mốc ghép); sai → xóa file, báo lỗi.
  - Route `GET /api/episodes/{id}/source-hd-intro` (auth như `source-hd`, Range, không tick "Đã đăng"); job làn `render` nếu file chưa có (tái dùng polling job hiện có trên trang tập).
- Out of scope:
  - Tự đăng lên YouTube; sửa / thay HD gốc trên kho; bản dọc (VERT2 đã có intro); Short.
  - Chạy cả bộ tự động (có thể thêm sau nếu HUMAN LEAD cần).

## Authority / key decisions

- VERT2 (intro 3 giây = thumbnail tập), HD2a / HD2b (mượn HD từ kho, xóa bản mượn sau khi dùng), CP8.3 (auth / phục vụ file), HUMAN LEAD 2026-10-29 duyệt bản thử Địa Tạng tập 1.
- **G1 — HD 4:3 (khác 16:9)** (chờ HUMAN LEAD): (a) thu thumbnail vừa khung, viền đen trên dưới (như bản thử; không mất chữ / hình) · (b) phóng thumbnail phủ kín khung, cắt hai bên (mất ~12 % mỗi bên — có thể cắt chữ "KINH ĐỊA TẠNG" ở mép trái).
- **G2 — lưu file** (chờ HUMAN LEAD): (a) dựng khi bấm tải, giữ cache cục bộ tối đa N file / X GB (mặc định 2 file), xóa file cũ nhất · (b) dựng một lần và lưu lâu dài cạnh HD (mỗi tập thêm ~2 GB trên máy / kho).

## Implementation approach

- Tách hàm thuần (dựng lệnh ffmpeg từ kết quả probe, kiểm thời lượng / pts) khỏi subprocess; test bằng video nhỏ do ffmpeg tạo trong `tmp_path` (h264 + aac và h264 + opus, 16:9 và 4:3) — không mạng, không kho thật.
- Tái dùng: `render.full.intro_image` (tách phần tìm playlist / dựng thumbnail thành hàm chung nếu cần, cả hai caller dùng), `store.borrow` (mượn HD), `ep.hd_source`, `ep.hd_download_name`, `probe_media`.
- Quy trình đã chứng minh bằng bản thử: `/home/ntnghia/.claude/jobs/1c1feb65/tmp/hd_sample.py` (ops, ngoài repo) — encode intro `-frames:v 90`, `atrim=0:3.003`, `-video_track_timescale <HD>`, concat `-c copy`.

## Phải giữ nguyên

- Route `source-hd` và file HD gốc (byte-identical), kho 3090, bản dọc, thumbnail.
- HD mượn từ kho bị xóa sau khi dùng như HD2a.

## Code bị thay / xóa

- Không có (tính năng mới). Nếu tách `intro_image` thì `render/full.py` gọi hàm chung, không giữ bản sao.

## Acceptance Criteria

1. HD h264 + aac và h264 + opus (16:9 và 4:3) → file có intro: 3 giây đầu là thumbnail ngang hiện hành (G1), phần sau byte-identical về gói hình / tiếng với HD (so sha gói hoặc `framemd5` vài đoạn), tổng thời lượng đúng ±1 khung, lệch mốc hình / tiếng ≤ 20 ms.
2. Codec không hỗ trợ / thiếu thumbnail ngang / thiếu HD → lỗi rõ, không để file dở.
3. HD đã giải phóng → mượn từ kho, xóa bản mượn sau khi xong; route không gọi kho khi file đã có (G2).
4. Route yêu cầu đăng nhập, id lạ → 404, hỗ trợ Range, tên tải có `_intro`; G2 giới hạn / xóa file cũ đúng.
5. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

Prefix: `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q`.

- `<prefix> tests/test_hd_intro.py` — AC 1–4.
- `<prefix> -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 5.
- Chạy thật (ORCHESTRATOR, 8080 ghim commit nhánh): Địa Tạng tập 1 (HD đã giải phóng, 4:3) tải "HD có intro" → so với bản thử đã duyệt; HUMAN LEAD xem 10 giây đầu.

## Manual test checklist (Tech Lead)

- [ ] Trang tập có "Tải HD có intro"; tải về xem 3 giây đầu là thumbnail, tiếng khớp môi sau intro.
- [ ] Tua giữa video không lỗi (Range / faststart).

## Result

- (chưa thực hiện)
