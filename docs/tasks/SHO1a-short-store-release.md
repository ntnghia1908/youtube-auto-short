# Task: SHO1a — Short + khai thị đã đăng hết lên kho 3090, web xem / tải từ kho

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, tính năng mới hai đầu kho / VM); quota 2026-10-26: 5 giờ 19 %, tuần 21 %; dự phòng subagent `implementer` (Sonnet). Test web (TestClient) và full suite do ORCHESTRATOR chạy ngoài sandbox.
- Authorization mode: task
- Authorization source: `docs/decisions/SHO1-short-store-3090.md` ACCEPTED (HUMAN LEAD 2026-10-26 "duyệt tất cả"), G1 + G2 + G3 + G4 + G6 (trừ ghép Short) + G8
- Parallel group: —
- Owned paths: `tools/store/store.py`; `src/auto_short/store/client.py` (tham số `clip`); `src/auto_short/store/shorts.py` (mới: hồ sơ giải phóng, chọn tập, đẩy); `src/auto_short/config.py` (chỉ `StoreConfig.offload_shorts`); `src/auto_short/web/storage.py` (chỉ hàm thuần chọn tập theo G2); `src/auto_short/web/episodes.py` (helper vị trí Short G6, `short_files` / `all_zip` / `archive_zips`); `src/auto_short/web/routes/files_catchall.py` (phát / tải / ZIP từ kho); `src/auto_short/web/app.py` (vòng đẩy nền, theo mẫu `offload_pass`); `src/auto_short/review/archive.py` (chỉ chỗ đọc file Short, nếu cần cho G6); `tests/test_store_server.py`, `tests/test_store_client.py`, `tests/test_store_shorts.py` (mới), `tests/test_archive_zips.py`; contract này
- Dependencies: HD2a, SRC1, HD2b, ARC1 (đã merge); không dependency mới
- Base commit / branch: `docs/sho1-short-store` (PR #173, chứa quyết định + contract) / `feature/sho1a-short-store`
- Human Lead approval: accepted — HUMAN LEAD 2026-10-26 "duyệt tất cả" (SHO1)
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: sửa API / danh mục kho HD2 G1 (kind `short` theo file), luật mới "file Short được vắng khi đã giải phóng", luồng VM ↔ 3090 mới.

## Goal

Bật `[store] offload_shorts`: Short + khai thị của video đã đăng hết đủ 5 ngày được đẩy lên kho 3090, kho khớp sha từng file thì VM xóa chúng (giải phóng tới ≈ 100 GB); trên web các Short đó vẫn liệt kê, phát, tải từng file, "Tải cả hai" và ZIP lưu trữ ARC1 như trước (VM chuyển tiếp từ kho). Cờ vẫn **tắt** trên 8080 cho tới khi SHO1b (sửa / ghép) merge.

## Scope

- In scope:
  - **K1 kho (G1)**: `kind = short` với đường dẫn `/files/<video_id>/short/<clip>` cho `GET` (Range) / `HEAD` / `PUT`; `<clip>` khớp `k[0-9]{2,3}\.mp4` (hoặc đúng regex clip id hiện có của web + `.mp4`); kind cũ giữ `/files/<video_id>/<kind>` (không nhận `clip`). Danh mục `index-short.csv` (`video_id`, `clip`, `file`), `SHA256SUMS.txt` chung; `GET /index` trả thêm dòng Short có `clip`. Khóa nhận diện Short = (`video_id`, `short`, `clip`); quy tắc 409 / 200 (cùng file) như kind cũ. Không xóa qua API.
  - **K2 client**: `head` / `put` / `open_stream` / `fetch` nhận `clip` tùy chọn (bắt buộc cho `short`).
  - **K3 chọn tập (G2)**: hàm thuần trong `storage.py` (cạnh `auto_archive_plan`, tái dùng `_videos` / `complete_since`): video mà mọi phần "Xong" giữ ≥ `auto_archive_grace_minutes`, không phần nào đang xử lý, có ít nhất một Short trên VM chưa giải phóng; **gồm cả video có khai thị**.
  - **K4 đẩy + giải phóng (G3)**: cờ `[store] offload_shorts` (mặc định `false`). Vòng nền một video mỗi lượt (như `offload_pass`: nhường khi có job của Short / khai thị, dừng hợp tác khi tắt web, lỗi một video không chặn video khác): mỗi Short `rendered` của `<id>` và `<id>.kt`: sha256 lấy từ `render_manifest.json` (kiểm lại file khớp sha trước khi đẩy) → `PUT` tên G1 → `HEAD` khớp sha + kích thước. Đủ mọi file của phần đó → ghi `output/<episode>/store.json` (`released`: clip → `{sha256, size, mtime_ns}`, `at`) bằng ghi nguyên tử, rồi mới xóa file. Thiếu / lệch → không xóa gì, thử lại lượt sau. Không đổi `render_manifest.json`, `publish.json`, bài đăng.
  - **K5 vị trí Short (G6)**: helper chung trong `web/episodes.py` trả mỗi Short `rendered`: trên VM (path) / trên kho (đã giải phóng, có sha / size / mtime) / không có. `short_files` cũ giữ nghĩa "file trên VM" cho chỗ cần file thật (ghép Short — SHO1b); liệt kê / đếm / ZIP / tải dùng helper mới. File vắng mà không có `store.json` → như hiện nay (không có file).
  - **K6 phát / tải (G4)**: `/files/<id>/<clip>.mp4` của Short trên kho: chuyển tiếp từ kho (giữ `Range`, `Content-Length`, `Content-Range`, tên file tải như cũ; `download=1` vẫn đánh dấu "Đã đăng" như cũ). `shorts.zip` / `all.zip` (cả `?archive=1`): entry trên kho đọc luồng từ kho, tên / nội dung như cũ, mtime entry = `mtime_ns` đã ghi. `/api/archive/zips`: vân tay ARC1 dùng size + mtime đã ghi (không đổi sau giải phóng). Kho tắt → file đơn 503 "3090 đang tắt"; ZIP có entry trên kho → 503 trước khi bắt đầu luồng (kiểm `available()`); kho rớt giữa luồng → đóng luồng (client thấy lỗi tải, script ARC1 tự kiểm ZIP thiếu).
- Out of scope (SHO1b): lấy lại Short khi dựng lại / sửa (G5), mượn khi ghép Short, tab Bộ nhớ (G7), bật cờ trên 8080. Không xóa trên 3090; không nút bấm tay.

## Authority / key decisions

- SHO1 G1–G4, G6, G8 (ACCEPTED). HD2 G1 / G2 / G8 (kho, kênh, token) giữ. W9 S5 (tự dọn nguồn) không đổi — K3 là hàm riêng.
- CP8.31 D1 (tải ZIP / `download=1` đánh dấu "Đã đăng"), ARC1 A1 (`?archive=1` không đánh dấu) giữ nguyên.

## Implementation approach

- Kho: tách phân tích đường dẫn thành (`video_id`, `kind`, `clip|None`); `_rows` đọc thêm `index-short.csv`; `_publish` ghi vào `index-short.csv` cho `short`. Lưu ý `index()` đang stat mọi file mỗi lần `lookup` — với ~4.000 Short nếu chậm thì lookup Short tra trực tiếp danh mục của thư mục (cache theo chữ ký file như `_rows`).
- VM: theo mẫu `store/offload.py` + `app.py` `offload_pass` (stop event, busy, lỗi theo tập); tên file / thư mục bộ kinh qua `store/backup.py` `_destination`. Phát từ kho theo mẫu `web/routes/episodes.py` (~dòng 516, `open_stream`). `_zip_stream` nhận entry có thể là luồng kho.

## Phải giữ nguyên

- `offload_shorts = false` (mặc định): không lượt đẩy nào, mọi route Short như trước (byte ZIP không đổi).
- Kind `hd` / `vertical` / `source`: API, `index.csv`, `danh-sach.csv`, `backup.ps1` không đổi; mọi test HD2a / HD2b / SRC1–SRC4 / ARC1 / CP8.17 / CP8.31 hiện có.
- Render không bị kích hoạt lại vì file Short vắng; trạng thái "Xong" / "đã đăng x/y" không đổi sau giải phóng.

## Code bị thay / xóa

- Không xóa. Chỗ liệt kê / ZIP / tải Short chuyển từ `short_files` sang helper K5.

## Acceptance Criteria

1. Kho nhận `PUT /files/<id>/short/k01.mp4` (cả `<id>.kt`), `HEAD` / `GET` Range đúng byte; tên / clip sai → 400; cùng khóa khác sha → 409; `index-short.csv` + `SHA256SUMS.txt` cập nhật; `index.csv` không đổi; kind cũ hoạt động như trước.
2. K3: video đã đăng hết đủ grace (kể cả có khai thị) được chọn; chưa đủ ngày / còn Short chưa đăng / đang xử lý / đã giải phóng hết → không.
3. K4: đẩy đủ + khớp → `store.json` ghi, file VM bị xóa; kho tắt / sha lệch / thiếu một file / file VM lệch sha manifest → không xóa file nào, thử lại sau; video khác vẫn chạy; tập có job → bỏ qua.
4. Sau giải phóng: trang tập / danh sách hiện đủ Short, "đã đăng x/y" và "Xong" như trước; không job render nào được tạo.
5. Phát / tải Short đã giải phóng: đúng byte (sha), `Range` 206; `download=1` đánh dấu "Đã đăng"; kho tắt → 503.
6. `shorts.zip`, `all.zip`, `all.zip?archive=1` cho tập đã giải phóng (một phần hoặc toàn bộ): entry đúng tên + byte; vân tay `/api/archive/zips` trước = sau giải phóng; kho tắt → 503.
7. `offload_shorts = false`: không lượt đẩy; full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_server.py tests/test_store_client.py tests/test_store_shorts.py tests/test_archive_zips.py` — AC 1–6 (test web / server cần socket: ORCHESTRATOR chạy ngoài sandbox).
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 7.
- ORCHESTRATOR chạy thật (không bật cờ trên 8080): kho tạm chạy `tools/store/store.py` mới trên VM (thư mục tạm, cổng khác) + bản sao workspace của 1 tập đã đăng hết có khai thị → chạy một lượt đẩy, kiểm `store.json`, phát / tải / `all.zip?archive=1` khớp sha, vân tay ARC1 không đổi.

## Manual test checklist (Tech Lead)

Chạm public API kho (thêm kind) và luồng dữ liệu VM ↔ 3090; không chạm security model (token / kênh cũ), không database. Manual test sau SHO1b, khi bật cờ trên 8080:

- [ ] Một tập đã giải phóng: phát Short, tải 1 Short, "Tải cả hai" được (3090 bật); tắt 3090 → báo "3090 đang tắt".

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
