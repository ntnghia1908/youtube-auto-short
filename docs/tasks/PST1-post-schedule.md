# Task: PST1 — Giờ đăng bài post trên trang Bài đăng (giờ đăng + làm lần lượt)

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S1 — thêm trường đọc vào API bài đăng + file trạng thái mới; không đổi schema `posts.json` (CP8.15), không thêm thao tác ghi YouTube
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — review, test web / full suite, chạy thật 8080 + điện thoại
- Implementer: codex — logic thuần + route / trang web theo mẫu có sẵn
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-18/19: "Làm 1,2" → "Bỏ ý 1 đi. Thêm ý 3: thời gian đăng vào" → "Giờ post: 9:00, 15:00, 20:30" → "A" (giữ 3 giờ/ngày, chấp nhận trễ dần)
- Parallel group: —
- Owned paths: `src/auto_short/post/schedule.py` (mới), `src/auto_short/web/post_links.py`, `src/auto_short/web/routes/episode_edit.py` (route `GET …/posts` thêm giờ + tập kế, route `/posted`), `src/auto_short/web/static/app.js` (phần trang Bài đăng), `src/auto_short/web/static/posts.html`, `src/auto_short/web/static/style.css` (lớp mờ nếu cần), `tests/test_post_schedule.py` + `tests/test_web_post_schedule.py` (mới), contract này
- Dependencies: LNK1 (đã merge). Không phụ thuộc PUB3 / PUB3.1 (giờ video đọc từ YouTube qua LNK1).
- Base commit / branch: `1502331` / `feature/pst1-post-schedule`
- Human Lead approval: accepted 2026-11-19 ("Duyệt nhưng số 4 ko cần trang mới nhỉ. Update vào trang bài đăng luôn")
- Implementation authorized: YES

## Goal

HUMAN LEAD đăng bài Cộng đồng bằng app YouTube trên điện thoại (YouTube không có API cho bài post — chép chữ / gắn ảnh / chọn giờ / Lên lịch vẫn làm tay). **Trang "Bài đăng" của tập** (`/episodes/{id}/posts`, không tạo trang mới — HUMAN LEAD 2026-11-19) hiện **giờ đăng đề xuất** (giờ VN) cho mỗi bài; sau "Sao chép bài" (tự tick như POSTCOPY1) bài mờ đi và trang cuộn tới bài chưa đăng kế tiếp; hết tập → nút "Tập kế tiếp →".

## Scope

- In scope: ghi giờ video (lịch / công khai) khi LNK1 quét; hàm xếp giờ bài post; lưu giờ đã chọn khi tick "Đã đăng bài"; thêm giờ + tập kế vào API / trang Bài đăng của tập.
- Out of scope: đăng / lên lịch bài post tự động (không có API; tự động hóa giao diện YouTube bị loại); chép ảnh vào bộ nhớ tạm (thử 2026-11-18: app YouTube chỉ nhận dán chữ); đổi giờ video; trang web mới.

## Authority / key decisions

- CP8.15 (bài đăng), POSTCOPY1 (sao chép → tick), LNK1 (gắn link từ playlist YouTube).
- **P1 giờ video**: khi LNK1 sync khớp một video với bài (cùng mã `T{n}_S{k}` / `T{n}_KT{k}`), ghi `video_at` = `status.publishAt` nếu có, ngược lại `snippet.publishedAt` khi video công khai (video riêng tư không lịch → không có giờ). Lưu ở file mới `work/_publish/post_times.json` (atomic, `schema_version` 1, khóa `"<episode_id>/<clip_id>"` → `{video_id, video_at, slot_at?}`), **không** thêm trường vào `posts.json`. Mỗi lần sync ghi đè `video_at` theo YouTube; giữ `slot_at`.
- **P2 khung giờ**: `09:00`, `15:00`, `20:30` giờ `Asia/Ho_Chi_Minh`, mọi ngày; hằng số trong `post/schedule.py`. Mỗi bộ (playlist website = một kênh) một dãy khung giờ riêng.
- **P3 xếp giờ** (hàm thuần, `now` truyền vào): ô đã dùng = `slot_at` của bài đã tick. Bài chưa đăng có `video_at` → sắp theo (`video_at`, mã tập, số clip); lần lượt nhận khung giờ trống sớm nhất ≥ max(`video_at`, `now` + 10 phút). Bài chưa có `video_at` → nhóm cuối "chưa có lịch video", không giờ. Không giới hạn trễ (HUMAN LEAD chọn A: 3 bài / ngày, bài dư trễ dần).
- **P4 lưu giờ khi tick**: route `/posted` (value true) ghi `slot_at` = giờ đề xuất hiện tại của bài đó (nếu có) vào `post_times.json`; bỏ tick → xóa `slot_at`. Tick cũ (trước PST1) không có `slot_at` → không chiếm ô.
- **P5 trang Bài đăng của tập**: `GET /api/episodes/{id}/posts` thêm (chỉ thêm trường, không đổi trường cũ) mỗi bài `slot_at` đề xuất / đã lưu + `slot_label` (`Thứ x dd/mm HH:MM`), hoặc nhóm "chưa có lịch video"; và `next_episode` = tập (cùng bộ) có bài chưa đăng với giờ đề xuất sớm nhất, ngoài tập này. Bộ của tập = playlist website chứa tập (nhiều bộ → bộ có `link_playlists`; không có → không giờ). Trang hiện giờ cạnh mỗi bài; sau "Sao chép bài" thành công + tick → bài mờ + cuộn tới bài chưa đăng kế tiếp (theo giờ); hết bài → nút "Tập kế tiếp →" tới `/episodes/{next}/posts`. Mobile-first.

## Implementation approach

- `post/schedule.py`: `slots_after(t)`, `plan(posts, times, now)` thuần; đọc / ghi `post_times.json` dùng `workspace.atomic_write_json` / `read_json_dict`.
- `web/post_links.py`: trong `sync`, sau `links.plan`, với mọi row khớp mục tiêu (kể cả `unchanged`) ghi `video_at` (cần lấy `status` của entry — `playlist_videos` đã đọc `status`). Không đổi kết quả / đếm LNK1.
- Route `GET …/posts` tính kế hoạch cả bộ: đọc posts các tập qua `store.read_posts` như LNK1 (`_targets` / `orders`), dưới `ctx.post_lock`; chi phí chỉ đọc file local.
- JS: sửa phần trang Bài đăng trong `app.js` — nhãn giờ, lớp mờ, cuộn, nút tập kế; giữ `copyPostButton` / POSTCOPY1 / `Tải ảnh`.

## Phải giữ nguyên

- Kết quả / đếm / journal LNK1; schema `posts.json`; hành vi trang bài của tập, nút sao chép (fallback HTTP), POSTCOPY1; test cũ PASS không sửa.

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. P1: sync ghi `video_at` đúng (lịch → `publishAt`, công khai → `publishedAt`, riêng tư không lịch → không có); giữ `slot_at`; LNK1 kết quả không đổi.
2. P2 / P3: xếp đúng khung 9:00 / 15:00 / 20:30 giờ VN qua nhiều ngày; không trước `video_at` / `now` + 10 phút; ô đã có `slot_at` bị bỏ qua; thứ tự theo giờ video rồi mã; bài không `video_at` vào nhóm cuối; 5 bài / ngày → trễ dần đúng.
3. P4: tick lưu `slot_at` = giờ đề xuất; bỏ tick xóa; tick cũ không chiếm ô.
4. P5: API bài đăng thêm `slot_at` / `slot_label` / `next_episode` đúng, trường cũ không đổi; trang hiện giờ; sau sao chép bài mờ + cuộn tới bài kế; hết bài có nút tập kế.
5. Test cũ (LNK1, posts, POSTCOPY1) PASS không sửa.

## Required verification

- `PYTHONPATH=src python -m pytest -q tests/test_post_schedule.py` — AC2–3 (IMPLEMENTER, sandbox).
- `PYTHONPATH=src python -m pytest -q tests/test_web_post_schedule.py tests/test_web_post_links.py tests/test_post_links.py` + test web bài đăng hiện có — AC1, 4, 5 (ORCHESTRATOR, cần socket).
- `PYTHONPATH=src python -m pytest -q -n auto` — full suite (ORCHESTRATOR).
- Chạy thật (ORCHESTRATOR): gắn các danh sách phát `[Tập a-b] Short / Khai Thị Ngắn` vào LNK1 của 4 bộ; sync; trang Bài đăng tập 21 CƯT hiện giờ, T21_KT01 ≥ 24/11 20:30.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract (thêm route đọc / file trạng thái nội bộ).

- [ ] HUMAN LEAD mở trang Bài đăng tập 21 CƯT trên điện thoại (8080), đăng 2–3 bài theo giờ trang ghi; bài mờ + cuộn tới bài kế; nút tập kế; giờ khớp lịch video.

## Result

- Main changes:
  - P1: LNK1 ghi giờ video cho mọi row khớp rõ ràng (`filled`, `unchanged`, `different`, `waiting`), bỏ row trùng / mâu thuẫn; giữ `slot_at`. File mới có dạng `{"schema_version": 1, "times": {"<episode_id>/<clip_id>": {"video_id": "…", "video_at": "…", "slot_at": "…"}}}`; riêng tư không lịch có `video_at: null`. Không đổi counts / rows / journal LNK1, kể cả khi file giờ hỏng (log cảnh báo, không ghi đè file hỏng).
  - P2–P4: hàm thuần xếp ba khung giờ VN, mốc tối thiểu `now + 10 phút`, thứ tự giờ video / mã số tập / số clip; lịch dư trễ qua ngày sau. Chỉ bài đã tick có giờ lưu chiếm ô (kể cả Short sau đó bị xóa); tick cũ không giờ không chiếm ô. Route tick / bỏ tick cập nhật file giờ dưới `post_lock`.
  - P5: API tính kế hoạch cả bộ bằng file local, ưu tiên bộ có `link_playlists`; trả `slot_at`, `slot_label`, `next_episode`. Tập kế loại cả Short / khai thị của video hiện tại vì hai phần dùng chung trang Bài đăng. Giữ response rỗng CP8.15 `{"posts": [], "post_error": null}` khi không có bài và không có tập kế; các response có bài luôn có `next_episode` (có thể `null`).
  - Trang cũ hiện giờ VN, giữ nhóm Shorts / Khai thị; bài không có giờ vào nhóm cuối. Copy thành công + tick thành công → mờ bài, tải lại lịch, cuộn tới bài chưa đăng sớm nhất; hết bài hiện nút tập kế. Giữ cảnh báo AI, fallback HTTP, copy lại bài đã tick, và Tải ảnh.
- Helpers mới / reuse:
  - `post/schedule.py`: `slots_after`, `plan`, `slot_fields`, `video_at`; các helper IO / timestamp `path`, `read`, `write`, `timestamp`, `_iso` chỉ phục vụ file giờ / múi giờ mới. Tái dùng `workspace.atomic_write_json`, `read_json_dict`, `zoneinfo.ZoneInfo`.
  - `PostLinks.schedule_view`: chọn bộ, dựng kế hoạch và tập kế dưới khóa do caller giữ; tái dùng `_targets` / `orders` LNK1, `store.read_posts`, `ep.hd_owner`.
  - JS `postTimeOrder`, `scrollToNextPost`: so giờ và chọn thẻ bài để cuộn. Tái dùng `copyPostButton`, `tickPostedAfterCopy`, `loadPostsPage`; không tạo cơ chế clipboard mới.
  - Đã tìm bằng `rg -n 'ZoneInfo|slot_label|slots_after' src/auto_short/post src/auto_short/web` và `rg -n 'scrollIntoView|slots_after|slot_label|post_times|ZoneInfo' src/auto_short`: chưa có helper xếp lịch / file giờ bài đăng; các nơi cuộn hiện có chọn video / mục kinh, không chọn bài chưa đăng.
- AC → test (test mới; test cũ không sửa):

  | AC | Test / bằng chứng |
  |---|---|
  | 1 | `test_post_schedule.py`: `test_sync_records_video_time_and_keeps_slot_without_changing_lnk1`, `test_sync_matched_rows_and_ambiguous_codes`, `test_time_file_corruption_is_not_overwritten_and_sync_result_survives` — PASS |
  | 2 | `test_post_schedule.py`: `test_slots_after_boundaries_and_vietnam_timezone`, `test_plan_orders_reserves_only_ticked_slots_and_puts_unknown_last`, `test_plan_five_videos_per_day_delays_without_a_limit` — PASS |
  | 3 | `test_plan_orders_reserves_only_ticked_slots_and_puts_unknown_last` — PASS; `test_web_post_schedule.py`: `test_tick_saves_proposal_untick_removes_it_and_legacy_ticks_reserve_nothing`, `test_posts_without_video_time_or_playlist_have_no_slot` — đã viết, chưa chạy |
  | 4 | `test_schedule_view_selects_linked_playlist_and_isolates_channels` — PASS; `test_web_post_schedule.py`: `test_posts_api_adds_slots_and_next_episode_preserving_old_fields`, `test_posts_ui_copy_dim_scroll_next_and_failure_paths` — đã viết, chưa chạy |
  | 5 | `tests/test_post_links.py` — 50 PASS; web posts / POSTCOPY1 cũ chưa chạy (ORCHESTRATOR) |

- Diff ứng dụng: **+228 / −12**; test: **+373 / −0** (gồm file mới, đo `git diff --numstat` + `git diff --no-index --numstat /dev/null <file mới>`).
- Verification IMPLEMENTER:
  - Python mặc định thiếu pytest; dùng conda env `auto-short`.
  - `conda run -n auto-short env PYTHONPATH=src python -m pytest -q tests/test_post_schedule.py tests/test_post_links.py` — **68 passed in 1.16s** ở lần cuối (18 ca PST1 + 50 ca LNK1 cũ).
  - `node --check src/auto_short/web/static/app.js`, kiểm cú pháp Python bằng `ast.parse`, `git diff --check` — PASS.
- Handoff: implementation hoàn tất trong Owned paths; **chưa READY toàn task** cho tới khi ORCHESTRATOR chạy verification còn lại. Không commit / push / PR, không gọi agent khác, không gọi mạng thật.
- Các lệnh **chưa chạy** theo phân công / sandbox không có loopback; không claim PASS:
  - `PYTHONPATH=src python -m pytest -q tests/test_web_post_schedule.py tests/test_web_post_links.py tests/test_post_links.py tests/test_web_post_cp815.py tests/test_web_post_cp816.py tests/test_web_cp817.py tests/test_web_post_doc_gate.py` — API / UI mới, posts và POSTCOPY1 cũ; giao ORCHESTRATOR (test web cần TestClient / socket).
  - `PYTHONPATH=src python -m pytest -q -n auto` — full suite, giao ORCHESTRATOR.
  - Sync thật 4 bộ + tập 21 CƯT, kiểm trên điện thoại và checklist Tech Lead — chưa chạy, giao ORCHESTRATOR / HUMAN LEAD.
