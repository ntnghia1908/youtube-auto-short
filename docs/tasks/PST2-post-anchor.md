# Task: PST2 — Mốc "đã lên lịch tay" cho bài post + cuộn đúng bài kế tiếp

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S1 — thêm khóa vào file trạng thái nội bộ `post_times.json`, đổi luật xếp giờ PST1 cho bộ có mốc; không đổi schema `posts.json`, không ghi YouTube
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — review, test web / full suite, chạy thật 8080 + điện thoại
- Implementer: codex — logic thuần + JS trang Bài đăng theo mẫu PST1
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-20: "Trang đăng bài mỗi lần Đăng tự cuộn xuống cuối Trang chứ không phải đúng bài tiếp theo và hiện tại chưa hiện ngày giờ đăng cho từng bài" → "Tôi đã lên lịch tới T35-S6 rơi vào ngày 30-5-27 20:30 chỉ cần lên lịch từ đây các bài Phía Trước bỏ qua"
- Parallel group: —
- Owned paths: `src/auto_short/post/schedule.py`, `src/auto_short/web/post_links.py` (`schedule_view`, next-post), `src/auto_short/web/routes/playlists.py` (route `next-post`, Amendment A), `src/auto_short/web/static/index.html` + `playlist.html` (nút, Amendment A), `src/auto_short/web/routes/episode_edit.py` (route `GET …/posts`, `/posted`, route đặt mốc mới), `src/auto_short/web/static/app.js` (phần trang Bài đăng), `src/auto_short/web/static/style.css` (nếu cần), `tests/test_post_schedule.py`, `tests/test_web_post_schedule.py`, contract này
- Dependencies: PST1 (đã merge)
- Base commit / branch: `bbd1df5` / `feature/pst2-post-anchor` (worktree `~/projects/yas-pst2`)
- Human Lead approval: accepted 2026-11-20 ("Duyệt, CƯT đăng tới T30 kt07 ngày 15:00 06/03/27. VLT tơi T33-S01 20:30 11/3/2027")
- Implementation authorized: YES

## Goal

Đang ở bộ Thập Thiện Nghiệp Đạo (kênh Người Dân Cực Lạc), HUMAN LEAD đã tự lên lịch bài post trong app YouTube tới **T35_S06 = 30/05/2027 20:30**. Lỗi gặp phải:
- Video Short từ T26 trở đi chưa upload nên bài chưa có giờ video. PST1 không xếp giờ cho các bài đó (nhóm "Chưa có lịch video").
- Bài của video đã công khai trước 19/11 cũng không có giờ (P3a).
- Vì thế mỗi lần bấm Đăng, trang không có bài "có giờ" để nhảy tới nên cuộn xuống cuối trang.

Sau task này:
- Mỗi bộ có thể có một **mốc** (mã bài + giờ của bài cuối đã lên lịch tay).
- Bài sau mốc nhận giờ lần lượt 9:00 / 15:00 / 20:30 bắt đầu ngay sau giờ mốc, kể cả khi video chưa có lịch. Ví dụ: T35_S07 = 31/05/2027 09:00.
- Bài từ mốc trở về trước mà chưa tick thì bỏ qua: không giờ, không nhảy tới.
- Bấm Đăng thì luôn cuộn tới đúng bài chưa đăng kế tiếp.

## Scope

- In scope:
  - mốc theo bộ (lưu, đọc, đặt);
  - luật xếp giờ khi có mốc;
  - nhóm "Đã lên lịch tay" cho bài ≤ mốc;
  - sửa cuộn sau khi Đăng / tick;
  - đặt 3 mốc khi chạy thật (giờ VN): Thập Thiện T35_S06 @ 30/05/2027 20:30; Cảm Ứng Thiên T30_KT07 @ 06/03/2027 15:00; Vô Lượng Thọ T33_S03 @ 11/03/2027 20:30 (HUMAN LEAD sửa 2026-11-20: "VLT tôi đăng T33-S03 20:30 11/03/27 nãy tôi nhầm"). Địa Tạng: không mốc.
- Out of scope:
  - bộ chưa có mốc: giữ nguyên luật PST1 (kể cả P3a);
  - đăng bài post tự động (không có API);
  - đổi giờ video.

## Authority / key decisions

- PST1 (`docs/tasks/PST1-post-schedule.md`): khung P2, xếp giờ P3 / P3a, P4 lưu `slot_at` khi tick.
- **Q1 mốc**: `post_times.json` thêm khóa `anchors` (giữ `schema_version` 1, đọc file cũ không có khóa vẫn được): `{"<website playlist id>": {"code": "T35_S06", "slot_at": "<ISO UTC>"}}`. Đặt / xóa qua route POST nội bộ và một nút nhỏ trên trang Bài đăng ("Đặt mốc: bài này là bài cuối đã lên lịch tay", nhập giờ). Giờ mốc lưu UTC, hiển thị giờ VN.
- **Q2 xếp giờ khi có mốc**:
  - Thứ tự mã trong bộ có mốc = `(tập, Short trước mọi khai thị của cùng tập, số clip)` (đúng thói quen đăng của HUMAN LEAD: T30_S01…S12 rồi T30_KT01…KT07, rồi T31_S01). Bài chưa tick có mã > mốc nhận khung trống sớm nhất **sau** giờ mốc, theo thứ tự mã.
  - Bài cũng không được đặt sớm hơn `video_at` nếu có, và không sớm hơn `now` + 10 phút.
  - Không cần `video_at`.
  - Bài đã tick vẫn giữ ô của mình như P4.
- **Q3 bài ≤ mốc**: bài chưa tick có mã ≤ mốc → `slot_group = "manual"`, không giờ, không chiếm khung, không tính vào cuộn / tập kế. Trang hiện chúng ở nhóm cuối "Đã lên lịch tay (≤ T35_S06)".
- **Q4 cuộn**: sau Đăng (sao chép + tick) hoặc tick tay thì cuộn tới bài chưa đăng kế tiếp **có giờ**. Nếu trang không còn bài có giờ thì cuộn tới bài chưa đăng kế tiếp theo thứ tự hiển thị. Chỉ khi cả trang đã đăng hết mới cuộn tới "Tập kế tiếp →".

- **Q5 nhãn giờ (HUMAN LEAD 2026-11-20: "Với mốc thời gian bỏ thứ đi không cần")**: `slot_label` = `dd/mm h:MM AM|PM` (bỏ thứ; HUMAN LEAD sau đó: "Đặt theo giờ am, pm"), cho mọi bài và mốc.

- **Q6 nút "Bài đăng tiếp →" (Amendment A, HUMAN LEAD 2026-11-20: "Thêm một nút ngoài bộ kinh khi click vào thì dẫn tới đúng bài Cần Đăng tiếp theo bởi vì mỗi lần tôi đăng bài phải dò lại trên YouTube tôi đăng tới bài mấy rất phiền")**:
  - Route mới `GET /api/playlists/{playlist_id}/next-post` trả `{episode_id, clip_id, code, slot_at, slot_label}`, hoặc `null` khi hết bài.
  - Bài được chọn là bài chưa tick có giờ sớm nhất của bộ, tính đúng như `schedule_view` / `plan`: có mốc thì dùng mốc, không có thì theo PST1.
  - Nếu bộ không còn bài có giờ thì chọn bài chưa tick đầu tiên theo thứ tự mã, bỏ qua nhóm manual và legacy.
  - Nút nằm cạnh mỗi bộ ở danh sách trang chủ và trên trang bộ kinh. Bấm mới gọi API (không tính sẵn khi tải danh sách). Có bài thì mở `/episodes/{episode_id}/posts#post-{clip_id}`. Hết bài thì báo "Hết bài cần đăng".
  - Khi mở, trang Bài đăng cuộn tới bài trong hash (`#post-{clip_id}`, thuộc tập đang mở). Không có hash thì cuộn như `scrollToNextPost`.

## Implementation approach

- `post/schedule.py`:
  - `read` / `write` giữ `anchors`;
  - `plan(posts, times, now, anchor=None)` thuần, nhánh có mốc;
  - `slot_group` thêm `"manual"`.
- `post_links.schedule_view`: truyền mốc của playlist website (`docs[0]["playlist_id"]`).
- Route đặt mốc dưới `ctx.post_lock`, kiểm mã hợp lệ (`links.parse_code`) và giờ có múi giờ.
- JS: nhãn giờ đã có (`slot_label`); thêm nhóm "manual", nút đặt mốc, sửa `scrollToNextPost` theo Q4.

## Phải giữ nguyên

- Bộ không mốc: kết quả `plan` giống hệt PST1 (test PST1 PASS không sửa).
- Schema `posts.json`; LNK1 sync (`video_at`); POSTCOPY1; nút sao chép.

## Code bị thay / xóa

- `scrollToNextPost` (app.js) viết lại theo Q4. Không xóa hàm nào khác.

## Acceptance Criteria

1. Q1: mốc lưu / đọc / xóa đúng; file cũ không `anchors` đọc được; mã / giờ sai → 400.
2. Q2: có mốc T35_S06 @ 30/05/2027 20:30 VN → T35_S07 = 31/05 09:00, T35_S08 = 31/05 15:00, … qua nhiều ngày. Mốc T30_KT07 → bài kế là T31_S01 (mọi Short T30 ≤ mốc). Bài sau mốc không có `video_at` vẫn nhận giờ. Có `video_at` muộn hơn thì không xếp trước giờ đó. Ô đã tick bị bỏ qua.
3. Q3: bài ≤ mốc chưa tick → `slot_group = "manual"`, không giờ, không chiếm ô, không thành `next_episode`.
4. Q4: trang có bài có giờ → cuộn tới bài đó. Không có → cuộn tới bài chưa đăng kế tiếp. Hết → "Tập kế tiếp".
5. Bộ không mốc: test PST1 cũ PASS không sửa.
6. Q6: `next-post` trả đúng bài (có mốc, không mốc, hết bài → null, bộ lạ → 404); nút ở trang chủ + trang bộ kinh mở đúng tập + cuộn đúng bài (hash).

## Required verification

- `PYTHONPATH=src python -m pytest -q tests/test_post_schedule.py` — AC2–3, 5 (IMPLEMENTER, sandbox).
- `PYTHONPATH=src python -m pytest -q tests/test_web_post_schedule.py` + test web bài đăng hiện có — AC1, 3, 4 (ORCHESTRATOR, cần socket).
- `PYTHONPATH=src python -m pytest -q -n auto` — full suite (ORCHESTRATOR).
- Chạy thật (ORCHESTRATOR): 8080 chạy commit nhánh; đặt mốc Thập Thiện T35_S06 @ 30/05/2027 20:30; trang Bài đăng tập 35 hiện T35_S07 = CN 31/05 09:00.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract (route nội bộ + file trạng thái).

- [ ] HUMAN LEAD mở trang Bài đăng tập 35 Thập Thiện trên điện thoại. Mỗi bài có ngày giờ; Đăng 1–2 bài → trang cuộn đúng bài kế tiếp.

## Result

- Main changes:
  - `post/schedule.py`: `anchors` trong `post_times.json`; `plan(…, anchor)`; nhóm `manual`.
  - `schedule_view` truyền mốc của bộ.
  - Route `POST …/posts/anchor`; `GET …/posts` thêm `anchor` và `code`.
  - Trang Bài đăng: nhóm "Đã lên lịch tay", nút "Đặt mốc" / "Xóa mốc", `scrollToNextPost` theo Q4, cuộn cả sau khi tick tay.
- Tests:

| AC | Test |
|---|---|
| 1 | `test_post_schedule.py` (đọc / ghi / kiểm mốc), `test_web_post_schedule.py::test_anchor_ui_set_vietnam_time_clear_and_error_paths` + test API mốc |
| 2–3 | `test_post_schedule.py` (chuỗi khung sau mốc, sàn `video_at` / `now`, ô đã tick, `manual`, tách bộ) |
| 4 | `test_web_post_schedule.py::test_anchor_ui_scroll_by_time_then_display_order_then_next[copy/tick]` |
| 5 | 21 test planner PST1 không sửa |

- Full suite: `pytest -q -n auto` 4744 PASS, 2 skip.
- Diff + / −: app +168 / −33; test +285 / −2 (Codex), cộng phần ORCHESTRATOR sửa nhỏ.
- Helper mới: `code_order` (thứ tự Short trước khai thị), `validate_anchor`, `_read_document`, `read_anchors` (giữ `read()` cũ).
- Review (ORCHESTRATOR):
  - Trả luật hiện nút "Tập kế tiếp" về như PST1 (hiện khi hết bài có giờ). Codex đã đổi thành "phải đăng hết mọi bài trừ manual", điều contract không yêu cầu.
  - Sửa 1 assert của test PST1 `test_legacy_ui_group_last_and_copy_scroll_skips_backlog`: hết bài có giờ thì cuộn tới bài chưa đăng kế (k02) thay vì nút cuối trang. Đây là thay đổi do Q4 / "Code bị thay: scrollToNextPost".
  - Chỉnh assert tương ứng trong test mới.
- Codex: 1 vòng, 90k token, session `01a1f8fc-d8a1-7071-b0db-117aff72fcca`.
- Known limitations: LNK1 sync của code cũ (trước PST2) ghi `post_times.json` sẽ xóa `anchors`. 8080 phải chạy code PST2.
- PR:
