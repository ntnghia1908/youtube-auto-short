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

### Amendment A (HUMAN LEAD 2026-11-08, sau chạy thật AC 7 / 9: "Hoạt động rất tốt nhưng còn 2 vấn đề")

Owned paths thêm: `static/app.js` và `static/favorites.js` — chỉ gắn `data-watch-fav` (JSON `{playlist_id, episode_id, clip, favorite}`) lên `<video>` của card có nút tim; cập nhật thuộc tính khi tim đổi.

10. **Tim trên `/watch`** ("Thêm nút yêu thích trái tim vào trang"): mục `queue` nhận tùy chọn `fav` (cùng kiểm tra: `playlist_id` / `episode_id` / `clip` là chuỗi hợp lệ theo `valid_playlist_id` / `valid_episode_id` / `valid_clip_id`, `favorite` bool). `/watch` hiện nút ♡/♥ cho video hiện tại khi có `fav`; bấm → gọi `POST /api/playlists/{pl}/favorites` có sẵn → lệnh phòng `favorite {index, favorite}` cập nhật mục đó để máy kia thấy cùng trạng thái. Video không có `fav` thì ẩn nút.
11. **Một máy rời trình duyệt / tắt màn hình không làm máy kia dừng**: sự kiện `pause` khi `document.visibilityState === "hidden"` (hoặc trong 1,5 s quanh lúc chuyển sang hidden / pagehide) không gửi lên phòng; khi trang hiện lại thì đồng bộ theo phòng (tua + phát). `pagehide` vẫn `leave`.
12. **Chế độ nghe nền**: công tắc "Nghe nền" trên `/watch` (nhớ trong `localStorage`): phát bằng một `<audio>` dùng cùng `src` (ẩn video), cùng logic đồng bộ / tự chuyển video; Media Session (`metadata` = tên video, handler play / pause / previoustrack / nexttrack gửi lệnh phòng). Điện thoại khóa màn hình / chuyển app vẫn nghe và tự chuyển video kế; tắt công tắc → quay về video tại vị trí hiện tại.
13. Chạy thật: điện thoại bật "Nghe nền", chuyển sang app khác 1 phút → vẫn nghe, máy tính không dừng, hết video cả hai cùng sang video kế; mở lại trình duyệt → khớp phòng.

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

- Vòng 1: ORCHESTRATOR đã commit implementation và sửa wiring router / lọc key `self` ở HEAD `980feee`. HUMAN LEAD báo chạy thật trên 8080 bằng hai máy: "Hoạt động rất tốt"; Amendment A bổ sung tim và nghe nền sau lượt này.
- Main changes vòng 2 (IMPLEMENTER 2026-11-08, chỉ AC10–12):
  - `watch_party.py`: queue nhận `fav` tùy chọn, validate bằng `valid_playlist_id` / `valid_episode_id` / `valid_clip_id` sẵn có và bool nghiêm ngặt; action `favorite` cập nhật đúng index, tăng version; snapshot sao chép sâu metadata để không lộ state qua tham chiếu.
  - `static/app.js`, `static/favorites.js`: chỉ bổ sung `data-watch-fav` và cập nhật khi tim đổi. Dòng yêu thích hiện dùng link Xem, không tạo video; metadata trong favorites.js chỉ gắn vào player sẵn có khớp nguồn, không tạo thêm player / đổi hành vi card.
  - `watch.js`: đọc metadata (JSON hỏng bỏ qua), tim ♡/♥ gọi API yêu thích hiện có rồi gửi action `favorite` cho phòng. Video thiếu `fav` ẩn tim.
  - `watch.js`: theo dõi visibility/pagehide, không gửi pause khi hidden / trong cửa sổ 1,5 s. Pause native khi trang còn hiện được giữ 1,5 s để hủy nếu điện thoại gửi pause trước sự kiện hidden; Media Session là thao tác rõ ràng và gửi ngay. Khi hiện lại force poll/sync kể cả trạng thái có `by` là mình; pagehide vẫn leave, dừng vòng polling cũ.
  - `watch.html`, `watch.js`, `style.css`: công tắc Nghe nền nhớ localStorage, một audio và một video, hàm `media()` chọn phần tử hiện hành; đổi chế độ giữ vị trí / rate / trạng thái phát, dỡ nguồn phần tử cũ, dùng chung listener / đồng bộ / ended CAS. Media Session có tên video và play/pause/previoustrack/nexttrack khi trình duyệt hỗ trợ.
- AC → verification vòng 2:
  - AC10 server: `test_favorite_metadata_and_action_preserve_playback`, `test_favorite_metadata_invalid_is_atomic_422`, `test_favorite_invalid_command_is_atomic_422` trong `tests/test_web_watch_party.py` (22 ca mới). Có route-factory call trực tiếp để kiểm status 422, không dùng socket hay TestClient.
  - AC10 client: `entryFor`, listener `watch-favorite`, metadata trong `shortCard` / `heartButton` / favorites `watchFav`; smoke DOM/media giả kiểm parse fav, bỏ JSON hỏng và chuỗi gọi API yêu thích → action phòng → đổi tim.
  - AC11: `hiddenPause`, `cancelPause`, listener pause/visibilitychange/pagehide/pageshow; smoke kiểm pause trước/sau hidden, force resume khi `by=self`, pagehide vẫn beacon leave và không pause phòng.
  - AC12: `media`, `loadMedia`, `syncPlayback`, `updateSession`, listener `watch-background` và Media Session; smoke kiểm chuyển video ↔ audio giữ vị trí/rate/paused, localStorage, audio ended gửi next kèm version, audio nhận cập nhật từ máy khác, các handler Media Session gửi lệnh phòng.
- Lệnh đã chạy vòng 2:
  - `PYTHONPATH=/home/ntnghia/projects/yas-watch1/src conda run -n auto-short pytest tests/test_web_watch_party.py -q -k 'not test_http'`: **61 passed, 3 deselected in 2.92s**.
  - Nạp `/home/ntnghia/.nvm/nvm.sh`, chạy `node --check` cho `src/auto_short/web/static/watch.js`, `app.js`, `favorites.js`: **PASS cả 3**.
  - `node /tmp/watch1-round2-dom.cjs` và `node /tmp/watch1-round2-player.cjs`: **PASS** (DOM/media giả; không thay thế trình duyệt thật).
  - `git diff --check`: **PASS**.
- Lệnh không chạy vòng 2: TestClient và full suite theo phân công HUMAN LEAD (ORCHESTRATOR chạy ngoài sandbox); chưa chạy thật AC13. Không claim PASS HTTP/full suite hay nghe nền trên điện thoại.
- Helper mới (đã tìm): tái dùng 3 validator ID, API `/api/playlists/{pl}/favorites`, router factory và helper web test sẵn có. Thêm `_fav` để validate/copy metadata; `watchFav` chỉ gắn data attribute ở favorites.js. Helper nội bộ watch.js (`media`, `playMedia`, `loadMedia`, `hiddenPause`, `cancelPause`, `updateSession`) gom logic mới cho hai media, không thêm global / dependency.
- Diff vòng 2 so với `980feee`, không tính contract: app **+215 / −50**, tests **+61 / −0**, tổng code **+276 / −50**. Amendment A đã có sẵn trong working tree trước lượt này và được giữ nguyên.
- Review / lifecycle: đã rà diff và verification cục bộ, sẵn sàng ORCHESTRATOR review vòng 2. Giữ Status IN_PROGRESS; task chưa được đánh dấu READY khi HTTP/full suite và chạy thật bổ sung chưa hoàn tất. Không commit / push / PR / gọi agent khác / gọi mạng thật.
- Known limitations: trạng thái phòng mất khi restart; nền / khóa màn hình phụ thuộc trình duyệt và cần xác nhận AC13 trên điện thoại thật. Pause native có cửa sổ chờ 1,5 s như mô tả trên.
- PR: chưa tạo theo chỉ dẫn HUMAN LEAD.
