# Task: FAVZIP1 — Tải từng phần Yêu thích (.zip)

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — mặc định IMPLEMENTER (`.claude/rules/execution.md`), quota 5 giờ 30 %, tuần 54 %
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-09 "1. đồng ý và bắt đầu" (đề xuất: nút "Tải phần này (.zip)" ở tab Nghe yêu thích, file mp4 đánh số theo thứ tự phát + danh sách tiêu đề, theo bộ lọc Short / Khai thị / Cả hai, zip tạo lúc tải, Short trên kho 3090 tự lấy về)
- Parallel group: —
- Owned paths: `src/auto_short/web/routes/files.py`, `src/auto_short/web/routes/files_catchall.py` (chuyển `zip_body` ra cấp module + entry bytes; ORCHESTRATOR bổ sung 2026-11-09, contract sót), `src/auto_short/web/compilations.py` (chỉ thêm hàm tra cứu nếu cần), `src/auto_short/review/names.py` (tên zip), `src/auto_short/web/static/favorites.html`, `src/auto_short/web/static/listen.js`, `src/auto_short/web/static/player.js` (chỉ nếu cần đọc nhóm), `src/auto_short/web/static/style.css`, `tests/test_web_favorites_zip.py` (mới), file này
- Dependencies: none
- Base commit / branch: `68e4463` / `feature/favzip1`
- Human Lead approval: accepted (2026-11-09)
- Implementation authorized: YES

## Goal

Ở trang Yêu thích của một bộ kinh (`/playlists/<pid>/favorites`, tab "Nghe yêu thích"), HUMAN LEAD chọn một phần ("Phần N", chia như danh sách phát hiện tại theo bộ lọc Short / Khai thị / Cả hai) và tải về **một file .zip** chứa các video của phần đó, đánh số theo đúng thứ tự phát, kèm danh sách tiêu đề, để tự đăng lên YouTube.

## Scope

- In scope:
  - Route `GET /files/playlists/{playlist_id}/favorites.zip?items=<episode_id>/<clip>,…&filter=<both|short|khaithi>&part=<N>`: stream zip (ZIP_STORED, không ghi file tạm ra đĩa).
  - Nội dung zip: `NN_<tên tải đơn lẻ hiện có>.mp4` (NN = vị trí trong phần, 2 chữ số, theo thứ tự `items`) + `danh-sach.txt` (UTF-8, mỗi dòng `NN. <code> — <tiêu đề>`; dòng đầu: tên bộ kinh, phần, bộ lọc, tổng thời lượng).
  - Tên zip: `[<series>_]YeuThich_<Shorts|KhaiThị|Shorts+KhaiThị>_Phan<N>.zip` (helper mới trong `review/names.py`, cùng cách làm sạch / cắt series như `zip_name`).
  - Nút / control trên UI: chọn phần (theo `AutoShortPlayer.groupFavorites` với bộ lọc đang chọn) + link "Tải phần này (.zip)"; danh sách phần hiển thị nhãn `choice` sẵn có ("Phần 1 (bài 1–15)" / "Phần 1 (Tập 3–9)").
- Out of scope: ghép video (compilation), đăng YouTube, đánh dấu "Đã đăng", tải nhiều phần một lần, đổi kích thước phần, trang Nghe ngoài Yêu thích, chế độ Xem chung.

## Authority / key decisions

- D1: Kích thước phần chỉ có một owner: `AutoShortPlayer.favoritePartSizes` / `groupFavorites` (player.js). Client gửi danh sách `items` của phần; server **không** chia phần lại, chỉ kiểm tra từng item.
- D2: Server chỉ nhận item là yêu thích hiện tại của bộ kinh và dùng được (có trong `Compilations._lookup(doc)`; gồm bản giữ lại G11 và Short đã lên kho = `StoredShort`). Item lạ / trùng / quá `MAX_BODY_ITEMS` / `filter` hoặc `part` sai → 400, không stream gì.
- D3: Tải zip phần yêu thích **không** đánh dấu "Đã đăng" / không track (như ARC1 `archive=1`): đây là bản để làm nội dung khác, không phải đăng Short.
- D4: Có Short trên kho mà 3090 tắt → 503 "3090 đang tắt" (như `zip_body` hiện có).

## Implementation approach

- Tái dùng `_zip_stream` / `zip_body` trong `src/auto_short/web/routes/files_catchall.py` (import hoặc chuyển phần dùng chung sang chỗ cả hai route import được; không copy). Có thể cần cho `_zip_stream` nhận thêm một entry bytes (danh-sach.txt) — mở rộng tối thiểu, giữ hành vi zip cũ.
- Tra item: `ctx.compilations._lookup(doc)` / `clips(doc)` + `favorites(playlist_id)`; tên file từng mục: `review.names.download_name(clip.label, clip.number, clip.total, clip.title, khaithi=clip.kind == "khaithi")`.
- Series: `ctx.compilations.series_of(doc)` như `Compilations.names`.
- UI: trong pane Nghe yêu thích, một `<select>` các phần + `<a download>` cập nhật `href` khi đổi bộ lọc / danh sách thay đổi; ẩn khi không có phần nào. Item không `usable` không đưa vào `items`.

## Phải giữ nguyên

- `shorts.zip` / `all.zip` (cả `archive=1`) giữ nguyên tên entry, tick "Đã đăng", kiểm sha256 Short trên kho.
- Danh sách phát / chia phần / Xem chung / tim yêu thích hiện có không đổi hành vi.
- Video ghép (compilations) không đổi.

## Code bị thay / xóa

- Không có (chỉ thêm mới; nếu chuyển `_zip_stream` sang module dùng chung thì xóa bản cũ, không để 2 bản).

## Acceptance Criteria

1. GET với `items` hợp lệ (khai thị + Short local) → 200 `application/zip`, `Content-Disposition` tên `…_YeuThich_<Kind>_Phan<N>.zip`; entry `01_…mp4`, `02_…mp4` đúng thứ tự `items`, byte giống file gốc; có `danh-sach.txt` đúng số dòng / tiêu đề.
2. Item là Short đã lên kho (`StoredShort`) → lấy từ kho trong zip (kiểm sha256 như cũ); kho tắt → 503.
3. Item không phải yêu thích của bộ kinh / trùng / sai định dạng / `filter` hoặc `part` sai / rỗng → 400; bộ kinh lạ → 404.
4. Tải zip không đổi trạng thái "Đã đăng" / downloaded của Short nào.
5. UI: tab Nghe yêu thích có chọn phần + link tải; đổi bộ lọc thì danh sách phần + link theo bộ lọc mới; link chứa đúng `items` của phần (theo `groupFavorites`).

## Required verification

- `PYTHONPATH=src pytest -q tests/test_web_favorites_zip.py` — AC1–AC4 (TestClient; ORCHESTRATOR chạy, Codex sandbox không có socket).
- `PYTHONPATH=src pytest -q tests/test_web_compilation.py tests/test_archive_zips.py` — không hồi quy zip / compilation.
- Full suite (ORCHESTRATOR) trước READY.
- AC5: kiểm tay trên 8080 (pin commit nhánh) — ORCHESTRATOR tải thử 1 phần, mở zip kiểm thứ tự + danh-sach.txt.

## Manual test checklist (Tech Lead)

Không chạm database / security model; thêm 1 route GET sau đăng nhập (cùng cơ chế session hiện có). Manual test là điểm danh.

- [x] (ORCHESTRATOR, 8080 2026-11-09; HUMAN LEAD kiểm lại trên điện thoại khi tiện) Trên điện thoại / PC: trang Yêu thích Vô Lượng Thọ → bộ lọc Khai thị → chọn Phần 1 → tải zip, mở được, 15 file đánh số + danh-sach.txt.

## Result

- Main changes: route `GET /files/playlists/{pid}/favorites.zip` kiểm toàn bộ item (yêu thích hiện tại, dùng được, không trùng, `filter` / `part` hợp lệ) trước khi stream, giữ thứ tự `items`; `zip_body` chuyển ra cấp module trong `files_catchall.py` và `_zip_stream` nhận thêm entry bytes (`danh-sach.txt`), hai caller cũ giữ hành vi; helper tên `favorites_zip_name` (`review/names.py`); control chọn phần + link "Tải phần này (.zip)" theo `AutoShortPlayer.groupFavorites` (`listen.js`, `favorites.html`). Không đánh dấu "Đã đăng" / không track. Chỉ sửa Owned paths (`files_catchall.py` bổ sung vào Owned paths 2026-11-09).
- IMPLEMENTER: Codex (1 vòng, dừng ở blocker ownership `files_catchall.py`); ORCHESTRATOR áp dụng phần `zip_body` / `_zip_stream` sau khi bổ sung Owned paths, review diff, chạy test web + full suite.
- Tests (`PYTHONPATH=src`, conda `auto-short`):
  - `pytest -q tests/test_web_favorites_zip.py tests/test_web_compilation.py tests/test_archive_zips.py`: **81 PASS** (chạy lại 2026-11-09 16:5x VN trên `763f31f`).
  - Full suite: **4334 PASS** (phiên trước, trên `763f31f`; không chạy lại phiên này).
- AC → test (`tests/test_web_favorites_zip.py` trừ khi ghi khác):

  | AC | Test | Trạng thái |
  |---|---|---|
  | AC1 | `test_favorites_zip_name`, `test_local_zip_order_manifest_and_no_publication_or_tracking`, `test_web_auth_and_favorites_zip` | PASS |
  | AC2 | `test_stored_short_zip_integrity_and_unavailable` | PASS |
  | AC3 | `test_invalid_favorites_zip_rejected_before_stream`, `test_kept_favorite_and_missing_kept_file`, `test_web_auth_and_favorites_zip` | PASS |
  | AC4 | `test_local_zip_order_manifest_and_no_publication_or_tracking`, `test_web_auth_and_favorites_zip` | PASS |
  | AC5 | `test_download_controls_use_grouped_favorites` + kiểm tay 8080 | PASS |

- AC5 kiểm tay (8080 restart lên `763f31f` lúc 16:39 VN 2026-11-09, sau khi hàng đợi Codex dịch bài chạy hết): dữ liệu `/api/playlists/PLOynZc0cJJfA3FSfw_GxZ7uG2cGdDwRR_/listen?favorites=1` + `groupFavorites` thật (`player.js`, bộ lọc Khai thị) → 7 phần ("Phần 1 (bài 1–15)" … "Phần 7 (bài 91–104)"); tải Phần 1: HTTP 200 `application/zip`, tên `Kinh Vô Lượng Thọ_YeuThich_KhaiThị_Phan1.zip`, 1,10 GB; `zipfile.testzip()` OK, ZIP_STORED; 15 entry `01_T7_KT02_…mp4` … `15_T18_KT01_…mp4` đúng thứ tự phát; `danh-sach.txt` dòng đầu "Kinh Vô Lượng Thọ — Phần 1 — Khai thị — Tổng thời lượng: 1:16:58" + 15 dòng `NN. <code> — <tiêu đề>`. Nút trên giao diện chưa bấm bằng trình duyệt thật (link dựng bằng cùng code `listen.js`).
- Diff + / − (`git diff --numstat 68e4463 HEAD -- src tests`): app **+105 / −13** (`names.py` +8/0, `files.py` +55/−2, `files_catchall.py` +16/−11, `favorites.html` +4/0, `listen.js` +22/0); test mới **+195 / −0**.
- Helper mới: `favorites_zip_name` (tên phần Yêu thích chưa có; dùng lại `clean_part` / `truncate_utf8` / `MAX_SERIES_BYTES`), `renderDownloadParts` (UI, dựng từ `groupFavorites`, không sao chép kích thước phần). `zip_body` / `_zip_stream` tái dùng, chỉ chuyển ra cấp module (không còn bản nested).
- Known limitations: chưa có ca Short trên kho 3090 trong lần kiểm tay (AC2 chỉ test tự động).
- PR: xem nhánh `feature/favzip1`.
