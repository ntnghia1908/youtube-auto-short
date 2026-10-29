# Task: HDI1-hd-thumbnail-intro — Bản HD ngang có 3 giây thumbnail đầu video

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, route + ffmpeg mới); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-29: "Tạo thêm 1 bản địa tạng hd để tôi test trước" → xem bản thử `output/_samples/dt-hd-intro/DiaTang_Tap1_HD_intro.mp4` → "Ok viết task riêng" → "G1 a. G2 b nhưng chỉ dùng cho địa tạng làm 1 bản test trước. Hiện tại địa tạng hd đã có trên 3090"
- Parallel group: —
- Owned paths: `src/auto_short/render/hd_intro.py` (mới), `src/auto_short/web/routes/episodes.py` (route tải / tạo HD có intro), `src/auto_short/web/context.py` + `src/auto_short/web/jobs.py` hoặc nơi khai báo kind job (chỉ thêm kind `hd_intro`), `src/auto_short/web/static/` (chỉ nút "Tạo / Tải HD có intro" cạnh link HD hiện có), `src/auto_short/store/client.py` (thêm kind `hd_intro`), `tools/store/store.py` (thêm loại `HDIntro` = `hd_intro`), `src/auto_short/config.py` + `config.example.toml` (mục `[hd_intro]`), `tests/test_hd_intro.py` (mới), test kho hiện có của `client.py` / `store.py` (chỉ thêm ca kind mới), contract này
- Dependencies: THUMB1 (#182, thumbnail tập khổ ngang hợp lệ qua `episode.valid_files`), VERT2 (`render/full.intro_image` — cách tìm playlist + dựng thumbnail), HD2a (mượn HD từ kho 3090)
- Base commit / branch: `721fb7f` (xếp chồng trên THUMB1 #182, chưa merge) / `feature/hdi1-hd-intro`; PR base đổi sang `main` sau khi THUMB1 merge
- Human Lead approval: APPROVED 2026-10-29 (G1 a, G2 b, chỉ Địa Tạng, 1 bản test trước)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1: thêm một module ffmpeg, một kind job, một loại file trên kho 3090 (giao thức kho không đổi, chỉ thêm giá trị loại); không đổi file HD gốc, Short, bản dọc hay security model (route dùng auth / kiểm id hiện có). `tools/store/store.py` mới phải được HUMAN LEAD chép lên 3090 trước khi đẩy bản đầu tiên.

## Goal

Với bộ kinh được bật trong config (hiện chỉ Địa Tạng `PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`), trang tập có nút "Tạo HD có intro" → job dựng file HD ngang giống hệt bản HD (đang ở kho 3090) nhưng 3 giây đầu là thumbnail tập khổ ngang (Bồ Tát + "TẬP N"), không encode lại phần bài giảng → đẩy lên kho 3090 (loại `hd_intro`), xóa bản cục bộ; sau đó nút "Tải HD có intro" tải từ kho. Làm **1 tập test trước** (Địa Tạng tập 1), HUMAN LEAD duyệt rồi mới làm cả bộ.

## Scope

- In scope:
  - `render/hd_intro.py`: từ HD hiệu lực (`source_hd.mp4` cục bộ, hoặc mượn từ kho như HD2a khi đã giải phóng) + thumbnail ngang hợp lệ (`episode.valid_files`, dựng nếu thiếu như `full.intro_image`) → encode intro đúng **90 khung** (3,003 s ở 30000/1001; tổng quát: `round(3 × fps)` khung) cùng codec / profile / kích thước / pix_fmt / timescale với HD, âm thanh im lặng cùng codec (aac / opus) / sample rate / số kênh, cắt cùng độ dài khung hình; ghép bằng concat demuxer `-c copy` + `+faststart`. Codec HD ngoài h264 + aac/opus → báo lỗi rõ, không tạo file sai.
  - Khung ảnh: HD khác 16:9 (vd. 1440×1080 của Địa Tạng) xử lý theo **G1**.
  - Lưu theo **G2 = b**: dựng một lần → `client.put(owner, "hd_intro", series, <tên HD>_intro.mp4, …)` như `offload.push_vertical` → kiểm `head` khớp sha / size → xóa file cục bộ. Kho: `tools/store/store.py` thêm loại `HDIntro` (cột `loai` trong `danh-sach.csv`), cùng thư mục bộ kinh. Tên tải `ep.hd_download_name` thêm hậu tố `_intro`.
  - Config `[hd_intro] playlists = [...]` (mặc định rỗng = tắt; config 8080 đặt Địa Tạng). Bộ không bật → không có nút, route 404.
  - Cache key intro (ghi trong record cục bộ nhỏ `hd_intro.json` của workspace owner): sha HD + sha thumbnail ngang + phiên bản thuật toán; khác → nút "Tạo lại" (không tự dựng lại).
  - Kiểm sau ghép: thời lượng = HD + intro (±1 khung), mốc bắt đầu hình và tiếng của phần HD lệch ≤ 20 ms (đo pts gói đầu sau mốc ghép); sai → xóa file, báo lỗi.
  - Route `POST /api/episodes/{id}/hd-intro` (tạo job làn `render`, kind `hd_intro`; mượn HD từ kho như HD2a, xóa bản mượn khi xong) và `GET /api/episodes/{id}/source-hd-intro` (tải từ kho qua `_store_download(…, "hd_intro", …)`, auth như `source-hd`, Range, không tick "Đã đăng"). Tái dùng polling job trên trang tập.
- Out of scope:
  - Tự đăng lên YouTube; sửa / thay HD gốc trên kho; bản dọc (VERT2 đã có intro); Short.
  - Nút "cả bộ" (thêm sau khi HUMAN LEAD duyệt bản test; có thể chỉ là gọi route từng tập).

## Authority / key decisions

- VERT2 (intro 3 giây = thumbnail tập), HD2a / HD2b (mượn HD từ kho, xóa bản mượn sau khi dùng), CP8.3 (auth / phục vụ file), HUMAN LEAD 2026-10-29 duyệt bản thử Địa Tạng tập 1.
- **G1 = a** (HUMAN LEAD 2026-10-29): HD khác 16:9 → thu thumbnail vừa khung, viền đen (như bản thử).
- **G2 = b** (HUMAN LEAD 2026-10-29): dựng một lần, lưu lâu dài trên kho 3090 cạnh HD (~2 GB / tập trên kho, không giữ cục bộ); chỉ Địa Tạng, 1 bản test trước.

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
3. HD đã giải phóng → mượn từ kho, xóa bản mượn và bản intro cục bộ sau khi `head` kho khớp sha / size; đẩy lỗi → giữ file cục bộ để thử lại, không báo xong. Kho nhận / liệt kê / tải loại `hd_intro` (CSV `loai = HDIntro`), loại lạ vẫn 400.
4. Route yêu cầu đăng nhập, id lạ / bộ không bật → 404, tải hỗ trợ Range, tên tải có `_intro`; đổi thumbnail / HD → trạng thái "cần tạo lại".
5. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

Prefix: `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q`.

- `<prefix> tests/test_hd_intro.py` + test kho (`client.py` / `tools/store/store.py`) — AC 1–4.
- `<prefix> -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 5.
- Chạy thật (ORCHESTRATOR, 8080 ghim commit nhánh, sau khi HUMAN LEAD chép `store.py` lên 3090): Địa Tạng tập 1 "Tạo HD có intro" → bản trên kho khớp sha → tải về so với bản thử đã duyệt; HUMAN LEAD xem 10 giây đầu.

## Manual test checklist (Tech Lead)

- [ ] Trang tập có "Tải HD có intro"; tải về xem 3 giây đầu là thumbnail, tiếng khớp môi sau intro.
- [ ] Tua giữa video không lỗi (Range / faststart).

## Result

- (chưa thực hiện)
