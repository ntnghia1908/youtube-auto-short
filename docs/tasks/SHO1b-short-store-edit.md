# Task: SHO1b — sửa / ghép Short đã giải phóng lên kho 3090 + Bộ nhớ

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, tính năng mới chạm render / job / ghép / kho); quota 2026-10-26: 5 giờ 12 %, tuần 2 %; dự phòng subagent `implementer` (Sonnet). Test web (TestClient), HTTP server và full suite do ORCHESTRATOR chạy ngoài sandbox.
- Authorization mode: task
- Authorization source: `docs/decisions/SHO1-short-store-3090.md` ACCEPTED (HUMAN LEAD 2026-10-26 "duyệt tất cả"), G5 + G7 + phần ghép Short của G6; sửa đổi G1 "Short sửa → bản mới" (HUMAN LEAD 2026-10-26 chọn "Lưu bản mới, giữ bản cũ")
- Parallel group: —
- Owned paths: `tools/store/store.py` (chỉ quy tắc bản mới của kind `short`); `src/auto_short/store/shorts.py` (lấy lại, mượn, snapshot Bộ nhớ); `src/auto_short/store/client.py` (chỉ khi cần cho `fetch` Short); `src/auto_short/render/stage.py` (chỉ điểm móc lấy lại ở `run_render`); `src/auto_short/web/jobs.py` (chỉ `add_short_target` → `StoreWaitJob`); `src/auto_short/web/app.py` (`store_retry_pass`, snapshot Bộ nhớ từ `shorts_offload_pass`); `src/auto_short/web/compilations.py`; `src/auto_short/web/storage.py` (snapshot + `report`); `src/auto_short/web/static/app.js` (dòng Bộ nhớ); `tests/test_store_server.py`, `tests/test_store_shorts.py`, `tests/test_store_shorts_edit.py` (mới), test compilation / storage hiện có liên quan (chỉ thêm test); `docs/decisions/SHO1-short-store-3090.md` (dòng sửa đổi G1); contract này
- Dependencies: SHO1a (#174, đã merge), HD2a, HD2b, FIX-store-wait-persist (đã merge); không dependency mới
- Base commit / branch: `main` `1ff1330` (sau #174) / `feature/sho1b-short-store-edit`
- Human Lead approval: accepted — HUMAN LEAD 2026-10-26 "duyệt tất cả" (SHO1) + chọn "Lưu bản mới, giữ bản cũ"
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi quy tắc API kho (kind `short` nhận bản mới thay vì 409), luồng VM ↔ 3090 mới (lấy lại khi sửa, mượn khi ghép), job đợi kho mới.

## Goal

Tập đã giải phóng Short lên 3090 vẫn sửa được như tập thường: sửa tiêu đề / cắt / xóa / khôi phục / thêm Short → job tự lấy lại mọi Short từ kho rồi dựng lại đúng Short đổi; video ghép dùng được Short đã giải phóng; tab Bộ nhớ hiện Short trên 3090 và hàng chờ đẩy. Sau khi merge, bật `offload_shorts` trên 8080 không còn tập nào "giải phóng mà không sửa được".

## Scope

- In scope:
  - **B1 kho — bản mới của Short (sửa đổi G1)**: `PUT /files/<video_id>/short/<clip>` khi khóa đã có file **khác sha** → không 409 nữa: ghi file mới tên `… - k03 (r2).mp4` (`(r3)` … số nhỏ nhất chưa dùng), dòng `index-short.csv` của khóa trỏ sang file mới; file cũ **giữ nguyên trên đĩa và trong `SHA256SUMS.txt`** (không xóa qua API). `HEAD` / `GET` trả bản hiện hành. Cùng sha bản hiện hành → 200 như cũ. Kind `hd` / `vertical` / `source` giữ 409. Ghi tạm + đổi tên nguyên tử, kiểm sha khi `PUT` như cũ.
  - **B2 lấy lại khi sửa (G5)**: helper trong `store/shorts.py` (ví dụ `restore_released(config, episode_id)`), gọi ở đầu `run_render` (sau kiểm "archived", trước nhánh HD của HD2a): phần có `output/<episode>/store.json` `released` → với mỗi clip vắng trên VM: `client.fetch(…, "short", …, clip=…)` vào đúng chỗ Short trên VM, kiểm sha = `store.json`, đặt lại mtime = `mtime_ns` đã ghi (vân tay ARC1 không đổi); đủ mọi clip → xóa `store.json`, rồi render như bình thường (T5 tái dùng Short không đổi, chỉ Short sửa được dựng lại). `[store]` tắt → `RenderError` rõ ("Short của tập đang ở kho 3090; bật [store] để sửa"); kho tắt / thiếu / lệch sha → `StoreWait` (`WAIT_PREFIX` "đợi 3090: …"); file đã lấy được giữ lại (file VM thắng record), lần sau chỉ lấy phần còn thiếu. Chỉ phần (`<id>` hoặc `<id>.kt`) mà job render.
  - **B3 đợi 3090 + chạy tiếp**: `add_short_target` đổi `StoreWait` → `StoreWaitJob` như `render_target`. `store_retry_pass` nhận thêm job render / thêm Short đang "đợi 3090" vì Short: kho trả lời và `HEAD` mọi clip đã giải phóng khớp sha → submit lại `KIND_RENDER` (`render_target`; job thêm Short không gọi lại AI — tiêu đề đã ghi `review.json`). Giữ nguyên nhánh HD hiện có; lưu / khôi phục khi restart (FIX-store-wait-persist) phải đúng cho cả hai.
  - **B4 ghép Short (G6)**: `compilations.py` liệt kê Short qua `short_locations` (Short đã giải phóng vẫn hiện ở Yêu thích / chọn được), thời lượng lấy từ `render_manifest` khi file vắng (không ffprobe file vắng). Job `compilation` mượn tạm Short trên kho (mẫu `store/borrow.py`: tải vào thư mục tạm dưới thư mục bộ kinh, kiểm sha, xóa sau khi ghép xong / lỗi, không đụng `store.json`); kho tắt / lệch → job `failed` "Short … đang ở kho 3090, 3090 không trả lời — bấm Ghép lại sau" (quyết định cục bộ: không thêm job đợi cho ghép). `keep_favorites` (xóa tập có Short yêu thích, G11): Short đã giải phóng → tải từ kho vào bản giữ (kiểm sha); không tải được → hủy xóa tập với thông báo rõ, không mất bản yêu thích. Temp mượn nằm trong `store_temp_files` để dọn sót.
  - **B5 Bộ nhớ (G7)**: vòng `shorts_offload_pass` cập nhật snapshot (mẫu `update_offload`): "Short trên 3090: N tập, X GB" (đếm từ `store.json` trên VM, không gọi kho), hàng chờ: đủ điều kiện / còn chờ ngày (mọi Short đã đăng, chưa đủ grace) / lỗi + lỗi cuối. `report()` trả khối `shorts_offload`; `app.js` hiện một dòng như `#vertical-offload`, chỉ khi cờ bật hoặc có tập đã giải phóng.
- Out of scope: bật cờ trên 8080 (HUMAN LEAD sau merge + chép `store.py` lên 3090); xóa file trên 3090 (kể cả bản cũ `(rN)`); nút bấm tay; đổi điều kiện G2 / luồng đẩy G3 của SHO1a (ngoài việc đẩy lại gặp B1); bản dọc / HD / nguồn.

## Authority / key decisions

- SHO1 G5, G6 (ghép), G7, G8 ACCEPTED; sửa đổi G1 (B1) HUMAN LEAD 2026-10-26. HD2 G1 "không xóa qua API" giữ. HD2a G4 / FIX-store-wait-persist: mẫu đợi 3090.
- Quyết định cục bộ (S1 trong S2 này): ghép Short gặp kho tắt → `failed` có thông báo, không đợi tự động (người dùng bấm "Ghép lại").
- `publish.py`: dấu "Đã đăng" của Short dựng lại thành cũ (sha khác) → tập không còn "Xong" tới khi đăng lại — đúng G5, không đổi.

## Implementation approach

- Tái dùng của SHO1a: `store/shorts.py` (đọc `store.json`, tên đích qua `store/backup.py` `_destination`, `_sha256_file`, `atomic_write_json`), `web/episodes.py` `short_locations` / `StoredShort` / `short_files`, `StoreClient.fetch(…, clip=)`; của HD2a: `store/borrow.py` (`WAIT_PREFIX`, `_FETCH` / đếm mượn), `render.stage.StoreWait`, `web/jobs.py` `StoreWaitJob`, `app.py` `store_retry_pass`.
- Kho: tìm tên `(rN)` trong thư mục bộ kinh dưới lock ghi hiện có; `index-short.csv` thay dòng của khóa (ghi nguyên tử như `_publish`).
- Lấy lại chạy trong job render (đã giữ khóa tập → vòng đẩy SHO1a bỏ qua tập bận); không thêm lock mới nếu không cần.

## Phải giữ nguyên

- `offload_shorts = false` và tập chưa giải phóng: render / ghép / xóa tập / Bộ nhớ như trước (không gọi kho).
- Kind `hd` / `vertical` / `source`: API + 409; `index.csv`, `danh-sach.csv`, `backup.ps1`; nhánh HD của `run_render` / `store_retry_pass`.
- SHO1a: xem / tải / ZIP / ARC1 của tập đã giải phóng; mọi test SHO1a, HD2a / HD2b, SRC1–SRC4, ARC1, CP8.2 T5, CP8.33 hiện có.

## Code bị thay / xóa

- `compilations.py`: hai chỗ dựng `files` từ `short_files` (liệt kê `clips`, `keep_favorites`) chuyển sang `short_locations` + mượn / tải; không giữ song song nhánh cũ.
- Kho: nhánh 409 "Existing file has a different sha256" không còn áp dụng cho kind `short` (thay bằng B1).

## Acceptance Criteria

1. B1: `PUT` Short khác sha cho khóa đã có → 200/201, file `(r2)` mới, `index-short.csv` trỏ file mới, file cũ + dòng `SHA256SUMS.txt` cũ còn; `HEAD` / `GET` trả bản mới; `PUT` lại cùng sha → 200 không thêm file; kind cũ vẫn 409.
2. B2: tập đã giải phóng (cả `<id>` và `<id>.kt`), sửa tiêu đề một Short → job lấy lại mọi Short (sha + mtime đúng), xóa `store.json`, chỉ Short sửa được encode lại (các Short khác tái dùng T5); `[store]` tắt → lỗi rõ, không đổi gì.
3. B2/B3: kho tắt khi sửa → job "đợi 3090: …", `render_manifest.json` / `store.json` không đổi; kho bật lại → `store_retry_pass` tự chạy lại và xong; restart web giữa lúc đợi → vẫn tự chạy lại; lấy dở (một phần clip) → lần sau chỉ lấy phần thiếu.
4. B3: thêm Short / xóa / khôi phục / cắt trên tập đã giải phóng đều đi qua B2; job thêm Short đợi 3090 chạy lại bằng render, không gọi AI lần hai.
5. Sau khi sửa và Short sửa được "Đã đăng" lại đủ grace: vòng đẩy SHO1a đẩy lại tập → kho lưu `(r2)` cho Short đổi, Short không đổi trả 200, VM giải phóng lại.
6. B4: Yêu thích liệt kê Short đã giải phóng; ghép có Short trên kho → video ghép đúng (mượn, temp bị xóa sau); kho tắt → job failed với thông báo, không còn temp; xóa tập có Short yêu thích đã giải phóng → bản giữ đúng sha; kho tắt → không xóa tập, báo rõ.
7. B5: `/api/storage` có `shorts_offload` (tập + byte đã giải phóng, đủ điều kiện / chờ ngày / lỗi); tab Bộ nhớ hiện dòng; báo cáo không gọi kho.
8. Cờ tắt / tập chưa giải phóng: không gọi kho; full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_server.py tests/test_store_shorts.py tests/test_store_shorts_edit.py` + test compilation / storage liên quan — AC 1–7 (test cần socket / TestClient: ORCHESTRATOR chạy ngoài sandbox).
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 8.
- ORCHESTRATOR chạy thật (không bật cờ trên 8080), theo cách SHO1a: bản sao cô lập + kho tạm `tools/store/store.py` mới (cổng khác): giải phóng một tập có khai thị → sửa tiêu đề 1 Short → lấy lại + chỉ 1 Short encode lại; đánh dấu đăng + đẩy lại → `(r2)` trên kho tạm, file cũ còn; tắt kho → "đợi 3090" → bật → tự chạy lại; ghép một video có Short đã giải phóng; `/api/storage` có `shorts_offload`.

## Manual test checklist (Tech Lead)

Chạm public API kho (quy tắc bản mới kind `short`) và luồng dữ liệu VM ↔ 3090; không chạm security model (token / kênh cũ), không database. Sau khi merge, chép `store.py` lên 3090, bật `offload_shorts` trên 8080:

- [ ] Một tập đã giải phóng: phát / tải Short, "Tải cả hai"; tắt 3090 → báo "3090 đang tắt".
- [ ] Sửa tiêu đề một Short của tập đó → job chạy xong, Short mới đúng tiêu đề.
- [ ] Tab Bộ nhớ hiện "Short trên 3090: …".

## Result

- (chưa có)
