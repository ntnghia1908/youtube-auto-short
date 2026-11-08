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

- Vòng 3 theo Amendment B: gỡ UI `watch-rate`, `_fav` / action phòng `favorite`, metadata `data-watch-fav`; `app.js` và `favorites.js` trở về đúng base `bc2ee68`. Tim được suy ra trong router, audio dùng cache tách tiếng mới.

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

### Amendment B (HUMAN LEAD 2026-11-08, chạy thật vòng 2)

Bằng chứng: "Bỏ nút tốc độ trong trang xem chung"; "Nút nghe nền tôi đã thấy nhưng khi chuyển app thì không nghe được tiếng dù vẫn chạy số giây trên player"; "Tôi chưa thấy nút trái tim trên trang xem chung" — phòng lúc đó (8080) có 7 khai thị `-9AytPxmjLc.kt`, mọi mục `fav = None`, dù `/api/episodes/-9AytPxmjLc.kt` có `favorites` (tab tạo phòng mở từ trước restart → `app.js` cũ, không có `data-watch-fav`).

Owned paths thêm: `src/auto_short/web/watch_audio.py` (mới), `routes/watch.py`; bỏ phần `data-watch-fav` khỏi `app.js` / `favorites.js` (trả 2 file về như base).

14. Bỏ ô chọn tốc độ trên `/watch` (đồng bộ `rate` phía server giữ nguyên, không có UI đổi).
15. Tim do **server tự suy ra**: với mục có url dạng `/files/<episode_id>/<clip>.mp4[?…]` (id hợp lệ), `GET /api/watch` trả `fav` cho mục hiện tại từ `ctx.compilations.episode_favorites(episode_id)` (trạng thái mới nhất, không lưu trong phòng); không thuộc bộ kinh → không có tim. Client không gửi `fav` nữa (server bỏ qua nếu có). Bỏ action `favorite`: sau khi bấm tim, poll kế tiếp tự thấy trạng thái mới ở cả hai máy.
16. Nghe nền bằng **file chỉ có tiếng**: `GET /api/watch/audio/<episode_id>/<clip>` → m4a (`ffmpeg -vn -c:a copy -movflags +faststart`, không encode lại), cache `work/_watch_audio/<sha256 manifest>.m4a` (ghi file tạm + rename; giới hạn tổng 2 GB, xóa cũ nhất theo mtime). Nguồn: file local từ `ep.short_locations`; nếu là `StoredShort` thì `StoreClient.fetch` về file tạm (kiểm sha256) rồi tách, kho tắt → 503. Range được hỗ trợ (FileResponse). `<audio>` dùng url này; lỗi tải thì báo trên trang và dùng lại mp4.
17. Nghe nền: `navigator.mediaSession.playbackState` theo trạng thái thật của phần tử đang phát (sự kiện play / pause), không theo phòng; trang ẩn thì không gọi `play()` lặp lại mỗi giây khi bị trình duyệt chặn (chỉ thử lại khi trang hiện lại hoặc có lệnh mới từ phòng).
18. Nút Trước / Tiếp là biểu tượng ⏮ / ⏭ (`icon-btn`, có `title` + `aria-label`) — HUMAN LEAD 2026-11-08: "nút trước và tiếp nên đổi thành icon mũi tên cho gọn" (ORCHESTRATOR sửa trực tiếp, 2 dòng watch.html).

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

- Context: vòng 1 HUMAN LEAD báo chạy thật hai máy "Hoạt động rất tốt"; vòng 2 đã commit ở `e73f634`. Bằng chứng vòng 2 và thay đổi được duyệt ở Amendment B được giữ nguyên; vòng 3 không claim đã sửa xong trên điện thoại thật khi chưa chạy lại.
- Main changes vòng 3 (IMPLEMENTER 2026-11-08, AC14–17):
  - AC14: gỡ select `watch-rate` và code UI; `WatchRoom` / player vẫn đồng bộ `rate`.
  - AC15: `routes/watch.py` suy ra `snapshot.fav` từ URL video hiện tại (bỏ query, kiểm ID bằng helper `ep` sẵn có) và `episode_favorites`. Mỗi snapshot đọc trạng thái favorites mới, không tăng version phòng khi chỉ đổi tim. `WatchRoom` chỉ giữ url/title, bỏ qua fav từ client và không còn action `favorite`. Tim trên trang gọi API yêu thích có sẵn rồi `poll(true)`. `app.js` / `favorites.js` khôi phục đúng base `bc2ee68`.
  - AC16: thêm `watch_audio.AudioCache` thuần stdlib, subprocess/fetch tiêm được, remux `-map 0:a:0 -vn -c:a copy -movflags +faststart`. Cache `work/_watch_audio/<sha>.m4a`, SHA từ manifest / StoredShort, ghi trong thư mục tạm rồi `os.replace`, lock theo SHA và quota 2 GiB xóa mtime cũ nhất. Route audio dùng `ep.short_locations`; local đưa thẳng cho ffmpeg, StoredShort dùng `StoreClient.fetch(episode_id, "short", dest, sha, clip=stored.clip)` có kiểm SHA; kho tắt / không available trả 503. Trả FileResponse audio/mp4 để hỗ trợ Range. Client dùng endpoint audio cho clip phù hợp, lỗi audio thì giữ timeline và fallback MP4 kèm thông báo.
  - AC17: Media Session playbackState đọc paused của media hiện hành và cập nhật ngay theo play/pause, kể cả sự kiện bị chặn gửi lên phòng. `playPending` ngăn gọi chồng; sau khi play bị từ chối trong hidden, không thử lại mỗi poll; reset khi visible hoặc version phòng đổi.
- AC → test vòng 3 (`tests/test_web_watch_party.py`):
  - AC15: `test_client_fav_is_ignored_and_favorite_action_removed`, `test_fav_derived_and_refreshed_from_real_favorites`, `test_fav_only_for_valid_clip_and_owned_episode` (make_app + favorites thật/giả, gọi route trực tiếp, không socket); `test_http_watch_fav_is_fresh_without_client_metadata` đã viết, chờ chạy HTTP ngoài sandbox. Bỏ các test fav/action cũ theo Code bị thay.
  - AC16: `test_audio_route_local_remux_cache_and_changed_manifest`, `test_audio_route_stored_short_offline_and_fetch_parameters`; `test_audio_cache_concurrent_requests_remux_once`, `test_audio_cache_failure_is_atomic_and_cleans_temp`, `test_audio_cache_evicts_oldest_mtime`; `test_audio_real_remux_has_only_aac_and_faststart` dùng video AAC nhỏ từ fixture hiện có và ffmpeg/ffprobe thật. `test_http_auth` bổ sung path audio; `test_http_audio_range_auth_and_cache` kiểm 401 / 404 / 206 Range và cache, chờ HTTP ngoài sandbox.
  - AC14/15/16/17 client: smoke DOM/media giả `/tmp/watch1-round3-player.cjs` kiểm không còn rate UI, tim từ snapshot cập nhật sau API mà không gửi action favorite, audio URL / fallback, giữ rate, playbackState thực khi bị OS pause, chỉ retry hidden một lần mỗi version và retry khi visible kể cả by=self.
- Lệnh đã chạy vòng 3:
  - `PYTHONPATH=/home/ntnghia/projects/yas-watch1/src conda run --no-capture-output -n auto-short pytest tests/test_web_watch_party.py -q -k 'not test_http' -x --tb=short`: **51 passed, 5 deselected in 2.32s** (sau khi sửa helper test duyệt router lồng theo mẫu `test_store_download.py`, và dùng ID thực sự không hợp lệ theo validator hiện hành).
  - Lệnh cả file `PYTHONPATH=/home/ntnghia/projects/yas-watch1/src conda run --no-capture-output -n auto-short pytest tests/test_web_watch_party.py -q`, bọc `timeout --signal=TERM --kill-after=5s 120s`: exit **124**, dừng tại TestClient sau 39 dấu chấm unit. Không claim PASS HTTP.
  - Nạp `/home/ntnghia/.nvm/nvm.sh`, `node --check src/auto_short/web/static/watch.js`: **PASS**; `node /tmp/watch1-round3-player.cjs`: **PASS** (mock, không thay thế trình duyệt thật).
  - `git diff --exit-code bc2ee68 -- src/auto_short/web/static/app.js src/auto_short/web/static/favorites.js`: **PASS, diff rỗng**.
  - `git diff --check`: **PASS**.
- Chưa chạy vòng 3: full suite và chạy thật 8080 / điện thoại; ORCHESTRATOR cần chạy TestClient ngoài sandbox, xác nhận Range và âm thanh nền / khóa màn hình thực tế.
- Helper mới (đã tìm): tái dùng `ep.short_locations`, `ep.render_manifest`, `ep.valid_episode_id` / `valid_clip_id`, `episode_favorites`, `StoreClient.fetch` kiểm SHA, `FileResponse`, `make_app` / `login` / `write_episode` và fixture video ffmpeg. Đã xem helper audio / artifact trong `packaging/music.py`: chúng phục vụ mix/normalize/preview, chưa có cache remux theo SHA với quota byte phù hợp; thêm `AudioCache`, `WatchAudioError`, router decorator và helper JS `audioUrl` / `updatePlaybackState`. Helper test `endpoint` duyệt router lồng dùng pattern có sẵn trong tests.
- Diff so với `e73f634`, không tính contract: app **+177 / −94**, test **+222 / −54**, tổng code **+399 / −148**, gồm `watch_audio.py` mới **73 dòng**. Amendment B đã có sẵn trong working tree trước lượt này.
- Review / lifecycle: đã rà Owned paths và verification cục bộ; sẵn sàng ORCHESTRATOR review vòng 3. Giữ Status IN_PROGRESS vì HTTP/full suite và chạy thật chưa hoàn tất. Không commit / push / PR / gọi agent khác / gọi dịch vụ thật / thêm dependency.
- Known limitations: trạng thái phòng mất khi restart; cache chỉ remux, không encode lại; khi nguồn không có tiếng/container không hỗ trợ copy sẽ trả 503 và client fallback MP4. Khả năng nghe khi chuyển app / khóa màn hình cần kiểm tra lại trên điện thoại thật.
- PR: chưa tạo theo chỉ dẫn HUMAN LEAD.
