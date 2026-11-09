# Task: FAVZIP1 — Tải từng phần Yêu thích (.zip)

## Status / Approval

- Status: IN_PROGRESS
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

- [ ] Trên điện thoại / PC: trang Yêu thích Vô Lượng Thọ → bộ lọc Khai thị → chọn Phần 1 → tải zip, mở được, 15 file đánh số + danh-sach.txt.

## Result

- Main changes: route GET kiểm toàn bộ item trước stream, giữ thứ tự client; helper tên zip; control chọn phần + link tải theo `groupFavorites`; tests mới. Chỉ sửa Owned paths. **Chưa READY**: route hợp lệ hiện thiếu shared `zip_body` (còn nested trong `files_catchall.build`).
- Tests (Codex, Python `/home/ntnghia/miniconda3/envs/auto-short/bin/python`, `PYTHONPATH=src`):
  - `python -m pytest -q tests/test_web_favorites_zip.py -k 'name or download_controls' -x --tb=short`: **4 PASS**.
  - `python -m pytest -q tests/test_web_favorites_zip.py -k invalid -x --tb=short`: **17 PASS**.
  - `python -m pytest -q tests/test_web_listen.py -k 'not http' -x --tb=short`: **24 PASS**.
  - `python -m pytest -q tests/test_archive_zips.py -k 'not web_auth' -x --tb=short`: **34 PASS** (source hiện tại, không patch).
  - `node --check src/auto_short/web/static/listen.js`, Python import `files` / `favorites_zip_name`, `git diff --check`: PASS.
  - `python -m pytest -q tests/test_web_favorites_zip.py -x --tb=short`: **FAIL** (3 PASS, 1 FAIL: ImportError `zip_body`, đúng blocker ownership dưới đây).
  - `timeout 20 python -m pytest -q tests/test_web_compilation.py tests/test_archive_zips.py -x --tb=short`: **timeout 124**, TestClient trong sandbox; không claim PASS.
  - Candidate chưa áp dụng: `/tmp/favzip1-files-catchall.patch` mở rộng `_zip_stream` nhận bytes + đưa `zip_body` ra module, sửa hai caller cũ. `/tmp/favzip1-verify-candidate.py` nạp candidate trong bộ nhớ rồi chạy hai file `test_web_favorites_zip.py` + `test_archive_zips.py`, `-k 'not web_auth'`: **60 PASS**, 2 deselected; không phải kết quả mã worktree hiện tại.
- AC → test (các tên dưới thuộc `tests/test_web_favorites_zip.py`):

  | AC | Test | Trạng thái |
  |---|---|---|
  | AC1 | `test_favorites_zip_name`, `test_local_zip_order_manifest_and_no_publication_or_tracking`, `test_web_auth_and_favorites_zip` | Tên PASS; local chỉ PASS với candidate; HTTP chờ ORCHESTRATOR |
  | AC2 | `test_stored_short_zip_integrity_and_unavailable` (up/down/sha) | PASS với candidate |
  | AC3 | `test_invalid_favorites_zip_rejected_before_stream`, `test_kept_favorite_and_missing_kept_file`, `test_web_auth_and_favorites_zip` | Validation PASS; kept PASS với candidate; HTTP chờ ORCHESTRATOR |
  | AC4 | `test_local_zip_order_manifest_and_no_publication_or_tracking`, `test_web_auth_and_favorites_zip` | Local PASS với candidate; HTTP chờ ORCHESTRATOR |
  | AC5 | `test_download_controls_use_grouped_favorites` | Node harness PASS; kiểm tay 8080 chờ ORCHESTRATOR |

- Diff + / − (app, test): `git diff --numstat`: app **+89 / −2** (`names.py` +8/0, `files.py` +55/−2, `favorites.html` +4/0, `listen.js` +22/0); test mới chưa tracked: `git diff --no-index --numstat /dev/null tests/test_web_favorites_zip.py`: **+195 / −0**. Không gồm candidate ngoài repo và task contract.
- Helper mới (đã tìm, lý do không tái dùng): đã chạy `rg -n 'def (zip_body|favorites_zip_name|timecode)|_zip_stream|groupFavorites' src/auto_short tests/test_web_listen.py` và đọc `names.py`, `compilations.py`, `files_catchall.py`. `favorites_zip_name`: tên phần Yêu thích chưa có, dùng lại `clean_part` / `truncate_utf8` / `MAX_SERIES_BYTES`; `renderDownloadParts`: dựng select/href mới từ `groupFavorites`, không sao chép kích thước phần. Fixture `favorite_zip` dùng lại `prepared_shorts`, `make_app`, `MemoryShortStore`, `run_player_js`; không tạo helper chung mới.
- Review: self-review diff/AC hoàn tất; ORCHESTRATOR review + web/full suite chưa chạy.
- Important findings / decisions: `files_catchall.py` không có trong Owned paths, nhưng `_zip_stream` cần thêm bytes entry cho `danh-sach.txt`; đã hỏi mở rộng tối thiểu ownership, chưa nhận xác nhận. Chưa sửa file này hoặc tự đổi Owned paths. Patch cụ thể đã chuẩn bị ở `/tmp/favzip1-files-catchall.patch`; ORCHESTRATOR cần cho phép và áp dụng trước khi route hợp lệ dùng được.
- Known limitations: thiếu helper trong worktree; required web/full suite + manual chưa PASS. Giữ status IN_PROGRESS, không claim READY.
- PR: không commit / push / PR theo chỉ thị; không gọi agent khác hoặc mạng thật.
