# Task: PST1 — Giờ đăng bài post trên trang Bài đăng (giờ đăng + làm lần lượt)

## Status / Approval

- Status: APPROVED
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
