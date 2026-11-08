# Task: WATCH1 — Xem chung: 2 người xem đồng bộ một video trên web

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S1 — thêm endpoint + trang mới sau login sẵn có; không dependency mới, không đổi security model (cùng cookie login, chỉ nhận URL cùng origin), không đổi API hiện có
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25); quota thấp thì subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-08: "Tôi cần 1 feature mới: xem video chung. 2 người dùng chung web này có thể cùng xem đồng bộ video"; chọn: mọi video trên web; đồng bộ phát / dừng / tua / tốc độ (không chat); một phòng chung duy nhất
- Parallel group: —
- Owned paths: `src/auto_short/web/watch_party.py` (mới), `src/auto_short/web/routes/watch.py` (mới), `src/auto_short/web/app.py` (chỉ dòng `include_router`), `src/auto_short/web/routes/pages.py` (route `/watch`), `src/auto_short/web/static/watch.html` + `watch.js` (mới), `src/auto_short/web/static/style.css` (khối CSS mới), các `static/*.html` đang nạp `app.js` (chỉ thêm 1 thẻ `<script src="/static/watch.js">`), `tests/test_web_watch_party.py` (mới), file này
- Dependencies: none
- Base commit / branch: `bc2ee68` (origin/main) / `feature/watch1-watch-together` (worktree `~/projects/yas-watch1`)
- Human Lead approval: accepted 2026-11-08 ("APPROVED", gồm danh sách phát)
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`.

## Goal

Hai người đăng nhập web 8080 (hai máy / điện thoại) xem cùng một video. Một người bấm "Xem chung" trên bất kỳ trình phát nào → người kia thấy lời mời ở trang đang mở. Trên trang `/watch`, ai phát / dừng / tua / đổi tốc độ thì máy kia làm theo trong ~1 s.

## Scope

- In scope:
  - Phòng duy nhất, trạng thái giữ trong RAM của server: `video_url`, `title`, `paused`, `position` (s), `rate`, `updated_at` (giờ server), `version`, `by` (id máy gửi), danh sách máy đang xem (id + lần cuối thấy, hết hạn sau 10 s).
  - API (sau middleware login): `GET /api/watch` (trạng thái + `server_time`), `POST /api/watch` (đặt video / phát / dừng / tua / tốc độ), `POST /api/watch/leave`, `DELETE /api/watch` (kết thúc phòng).
  - Trang `/watch`: một trình phát lớn, tên video, "Đang xem: N người", nút "Kết thúc xem chung".
  - `watch.js` nạp ở mọi trang dùng `app.js`: gắn nút "Xem chung" cạnh mọi `<video controls>` (cả video thêm sau qua `MutationObserver`). Bấm → đặt video của phòng tại vị trí hiện tại → mở `/watch`. Khi phòng có video do máy khác đặt → hiện thanh mời "Đang xem chung: <tên> — Vào xem".
  - Đồng bộ: hỏi `GET /api/watch` mỗi ~1 s (chỉ khi có phòng hoặc đang ở `/watch`). Máy nhận tính vị trí mong muốn = `position + (server_time − updated_at) × rate` khi đang phát. Lệch > 1 s thì tua về; bỏ qua thay đổi do chính mình gửi; sự kiện do code gây ra (tua / phát theo phòng) không gửi ngược lại.
  - Trình duyệt chặn tự phát có tiếng: hiện nút "Bấm để phát" thay vì báo lỗi.
  - **Danh sách phát (HUMAN LEAD 2026-11-08: video ngắn, phải chuyển liên tục, chỉ 1 người thao tác)**: bấm "Xem chung" trên một video → phòng nhận cả danh sách các video `controls` của trang đó (đúng thứ tự trên trang, bỏ video ẩn / keep-awake, tối đa 300), bắt đầu từ video được bấm. Phòng giữ `queue` (url + title) và `index`.
  - Trang `/watch`: nút "Trước" / "Tiếp", danh sách bấm để nhảy tới video bất kỳ; hết video thì **tự chuyển video kế** (chỉ một yêu cầu thắng nhờ `version` — hai máy cùng báo hết thì không nhảy 2 lần); hết danh sách thì dừng.
  - Máy đã vào `/watch` **tự đi theo** mọi lần đổi video, không cần bấm lại; dùng lại cùng một phần tử `<video>` (đổi `src`) để điện thoại chỉ cần chạm 1 lần đầu cho phép phát có tiếng.
  - Đang ở `/watch` mà bấm "Xem chung" ở tab khác → thay danh sách của phòng.
- Out of scope: chat, nhiều phòng / link phòng, quyền điều khiển riêng, lưu phòng qua restart, WebSocket / SSE, video YouTube nhúng, danh sách gộp nhiều trang / sắp xếp lại danh sách.

## Authority / key decisions

- HUMAN LEAD 2026-11-08 (3 lựa chọn ở trên).
- S1 cục bộ — truyền tin bằng **polling ngắn** (không SSE / WebSocket): uvicorn hiện không có `websockets` / `wsproto` (WebSocket cần dependency mới), còn kết nối giữ lâu kiểu SSE làm Ctrl-C chờ đóng kết nối → script restart bị treo (vấn đề vừa sửa 2026-11-08). Hai người × 1 lần/s là tải không đáng kể.
- Bảo mật: `video_url` chỉ nhận đường dẫn cùng origin (bắt đầu bằng `/`, không `//`, không scheme, ≤ 2 KB); `title` ≤ 200 ký tự, hiển thị bằng `textContent`. Không thêm path vào `PUBLIC_PATHS`.

## Implementation approach

- `watch_party.py`: lớp `WatchRoom` thuần (lock + clock tiêm được để test), không I/O.
- `routes/watch.py`: factory `build(ctx)` như các route khác; một `WatchRoom` cho mỗi app (giữ trong ctx hoặc closure).
- `watch.js` độc lập với `app.js` (IIFE, không global mới ngoài một namespace); id máy ngẫu nhiên trong `sessionStorage`.

## Phải giữ nguyên

- Mọi trình phát hiện có vẫn hoạt động như cũ (loop CP8.13, "Đã xem" khi xem hết CP8.21, video keep-awake ẩn `#dq-awake` / `#awake` không được gắn nút).
- Lọc / ẩn thẻ không dựng lại card (video đang phát vẫn phát).
- Trang đăng nhập, `PUBLIC_PATHS`, catch-all route đăng ký cuối cùng.
- Web chạy bình thường khi không ai dùng Xem chung (không polling khi không có phòng và không ở `/watch`, trừ 1 lần kiểm tra khi tải trang + mỗi 10 s để hiện lời mời).

## Code bị thay / xóa

- Không có (chỉ thêm mới).

## Acceptance Criteria

1. `POST /api/watch` với video hợp lệ tạo phòng; `GET` từ client khác trả về đúng video, `paused`, `position`, `rate`, `version` tăng mỗi lần đổi.
2. `video_url` ngoài origin (`http://…`, `//host/…`, `javascript:…`, không bắt đầu bằng `/`) và title quá dài bị từ chối 422; phòng không đổi.
3. Chưa đăng nhập: mọi `/api/watch*` và `/watch` bị chặn như các trang khác (401 / redirect login).
4. Máy hết hạn sau 10 s không gọi thì biến khỏi danh sách đang xem; `leave` xóa ngay; `DELETE` kết thúc phòng, `GET` trả về không có phòng.
5. Vị trí ngoại suy: khi đang phát, `GET` sau t giây cho phép client tính `position + t × rate` (test với clock giả).
6. `watch.js`: nút "Xem chung" xuất hiện trên video `controls` (kể cả video thêm sau khi tải trang), không xuất hiện trên video keep-awake; thanh mời hiện khi phòng do máy khác đặt.
8. Danh sách: `POST` với `queue` hợp lệ lưu đúng thứ tự + `index`; mọi url trong `queue` qua cùng kiểm tra AC 2; quá 300 mục → 422; lệnh "tiếp" kèm `version` cũ (máy thứ hai báo hết video) không nhảy thêm (409 hoặc bỏ qua), hết danh sách thì `paused` = true.
9. Chạy thật: người A mở `/watch` từ trang 1 tập (~10 Short), người B vào 1 lần, sau đó B không chạm gì mà vẫn theo được: tự chuyển hết video, A bấm "Tiếp" / chọn video trong danh sách, B đổi theo ≤ 2 s (điện thoại: chỉ chạm 1 lần đầu).
7. Chạy thật trên 8080, 2 trình duyệt (máy tính + điện thoại): phát / dừng / tua / đổi tốc độ ở bên nào bên kia cũng theo trong ≤ 2 s, lệch khi cùng phát ≤ 1 s; không vòng lặp tua qua lại.

## Required verification

- `PYTHONPATH=~/projects/yas-watch1/src conda run -n auto-short pytest tests/test_web_watch_party.py -q` — AC 1–5, 8 (TestClient; ORCHESTRATOR chạy ngoài sandbox).
- `node --check src/auto_short/web/static/watch.js` — cú pháp JS.
- Full suite `pytest -n auto -q` — không hồi quy.
- AC 6, 7, 9: chạy thật trên 8080 ghim commit nhánh (feedback test-on-8080), 2 trình duyệt.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API hiện có (chỉ thêm endpoint mới sau login) → manual test là điểm danh sau automated verification.

- [ ] Máy tính bấm "Xem chung" trên 1 Short → điện thoại thấy lời mời → vào xem, hai bên đồng bộ phát / dừng / tua.
- [ ] Đổi tốc độ 1.5× trên điện thoại → máy tính theo.
- [ ] "Kết thúc xem chung" → lời mời biến mất ở cả hai bên.

## Result

- Main changes: đã triển khai WatchRoom thuần (lock + clock tiêm được), API factory riêng mỗi app, `/watch` với một video dùng lại qua danh sách, polling / chống echo / autoplay fallback, lời mời và nút Xem chung ở 9 trang đang nạp app.js. Không thay PUBLIC_PATHS hay player hiện có.
- Tests (IMPLEMENTER 2026-11-08):
  - `PYTHONPATH=/home/ntnghia/projects/yas-watch1/src conda run --no-capture-output -n auto-short pytest tests/test_web_watch_party.py -q -k 'not test_http'`: **39 passed, 3 deselected**. AC1/5: `test_commands_and_extrapolation`; AC2: `test_reject_urls_atomically`, `test_reject_invalid_set_without_mutation`; AC4: `test_viewer_expiry_leave_end_and_copies`; AC8: `test_queue_cas_navigation_and_end`, `test_simultaneous_ended_only_advances_once`, cùng kiểm tra lệnh lỗi không làm đổi phòng.
  - Lệnh required cho cả `tests/test_web_watch_party.py` đã thử 2 lần, bọc `timeout --signal=TERM --kill-after=5s 120s`: đều exit **124** tại TestClient, lần cuối in 39 dấu chấm unit thành công; không claim PASS các HTTP test. AC3 có `test_http_auth`; AC1/2/4/8 có `test_http_room_lifecycle_and_validation`; app isolation có `test_http_rooms_are_per_app`.
  - `node --check src/auto_short/web/static/watch.js` (nạp `/home/ntnghia/.nvm/nvm.sh`): **PASS**.
  - Hai smoke script tạm `/tmp/watch1-dom-check.cjs`, `/tmp/watch1-player-check.cjs`: **PASS** với DOM/media giả (nút / video ẩn / keep-awake / MutationObserver / lời mời dạng text / queue thứ tự DOM; autoplay fallback / cùng video element / đổi nguồn không echo / ended gửi expect_version). Đây không thay thế AC6/7/9 chạy trình duyệt thật.
  - Full suite `PYTHONPATH=/home/ntnghia/projects/yas-watch1/src conda run --no-capture-output -n auto-short pytest -n auto -q`, bọc timeout 120s: exit **124**, dừng khoảng 63%, đã xuất hiện E/F nhưng chưa có traceback / summary. Log: `/tmp/watch1-full-pytest.log`. Không claim không hồi quy.
  - Smoke gọi trực tiếp router factory qua `pages.build_watch`: **PASS** cho tạo / đọc phòng, validate 422, conflict 409, end và trạng thái tách biệt giữa hai factory; không thay thế HTTP/auth tests. `pages.py` re-export factory để `app.py` chỉ thêm đúng một dòng include_router.
  - Python AST parse các file Python mới và `git diff --check`: **PASS**.
- Diff + / − (app, test): app **+496 / −0**, test **+191 / −0**; tổng code **+687 / −0**, không tính contract này (đã có sẵn dưới dạng untracked khi bootstrap).
- Helper mới (đã tìm, lý do không tái dùng): đã đọc `web/urls.py`, auth, router factories, player code và `tests/web_helpers.py`; tái dùng `login` / `make_app`, middleware login và factory pattern. Chưa có helper kiểm đường dẫn cùng origin hoặc state phòng; thêm `validate_url`, `_number`, `_index`, `_client`, `WatchConflict` trong `watch_party.py` để validate tập trung / atomic. JS dùng helper nội bộ IIFE, không thêm global.
- Review: IMPLEMENTER đã rà diff / scope và chạy smoke giả; chờ ORCHESTRATOR review độc lập. Chưa commit / push / PR.
- Important findings / decisions: implementation đã viết xong, **chưa đủ điều kiện READY**. Giữ Status IN_PROGRESS; ORCHESTRATOR cần chạy HTTP tests / full suite ngoài sandbox và AC6/7/9 trên 8080 với hai trình duyệt. Không gọi agent khác, không gọi dịch vụ thật, không thêm dependency.
- Known limitations: trạng thái mất khi restart 8080; đồng bộ dùng polling khoảng 1 s, độ trễ thực tế và autoplay trên điện thoại chưa được xác nhận bằng chạy thật.
- PR: chưa tạo theo chỉ dẫn HUMAN LEAD.
