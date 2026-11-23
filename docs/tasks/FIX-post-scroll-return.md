# Task: FIX-post-scroll-return — Trang Bài đăng lúc tự cuộn lúc không sau "Sao chép bài"

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1 — chỉ JS phía trình duyệt của trang Bài đăng; không đổi API / dữ liệu / dependency
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25); quota 5 giờ 1 %, tuần 11 %
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-23: "Ok làm liền" sau đề xuất "trang ghi nhớ cần cuộn khi đang ở nền, cuộn ngay khi quay lại"
- Parallel group: —
- Owned paths: `src/auto_short/web/static/app.js` (chỉ phần trang Bài đăng: `scrollToNextPost`, `tickPostedAfterCopy`, `togglePosted`, khởi tạo trang Bài đăng), test mới `tests/test_web_post_scroll_return.py`, file này
- Dependencies: none
- Base commit / branch: `8a682e2` (origin/main) / `fix/post-scroll-return` (worktree `~/projects/yas-scroll`)
- Human Lead approval: accepted 2026-11-23
- Implementation authorized: YES

## Bằng chứng (2026-11-23)

- HUMAN LEAD: tự cuộn tới bài kế tiếp (PST1 / PST2) "làm được một hồi thì không tự cuộn nữa", "lúc được lúc không".
- Quy trình trên điện thoại: bấm "Sao chép bài" → chuyển sang app YouTube đăng → quay lại web.
- `tickPostedAfterCopy` chỉ cuộn sau 2 lượt await (POST `/posted`, rồi `loadPostsPage` gồm 3 GET) ≈ 1–2 s. Nếu người dùng đã chuyển app, trang đang ở nền (`document.hidden`) → trình duyệt điện thoại có thể bỏ / không áp dụng `scrollIntoView({behavior: "smooth"})` → quay lại vẫn đứng ở bài cũ. Phụ thuộc thời điểm → ngẫu nhiên.
- Đã loại: polling 2,5 s (`anyPostWork`) — hàng đợi Codex trống (`remaining 0`); dữ liệu — tập `e2GdX0svtvU` k01–k16 ticked đều có `slot_at`.

## Goal

Sau khi bấm "Sao chép bài" (tự tick) hoặc tick tay "Đã đăng bài", dù người dùng chuyển app ngay hay không, khi quay lại trang Bài đăng thì màn hình nằm ở bài chưa đăng kế tiếp (cùng đích như `scrollToNextPost` hiện nay).

## Scope

- In scope:
  - Sau tick thành công (copy hoặc tick tay, `posted = true`) ghi cờ "cần cuộn khi quay lại" trên `postsPage`.
  - Nếu lúc gọi cuộn trang đang ẩn (`document.hidden`) thì không cuộn ngay, chỉ giữ cờ.
  - Listener `visibilitychange` (đăng ký 1 lần cho trang Bài đăng): khi trang hiện lại và cờ đang bật → xóa cờ, gọi `scrollToNextPost()` (sau 1 frame `requestAnimationFrame` để layout ổn định).
  - Nếu trang đang hiện lúc tick xong → cuộn ngay như cũ và cũng giữ cờ cho lần quay lại kế tiếp (trường hợp trình duyệt bỏ qua lệnh cuộn khi người dùng chuyển app đúng lúc đang cuộn).
- Out of scope: đổi đích cuộn / thứ tự bài / giờ đăng, đổi polling, các trang khác.

## Authority / key decisions

- PST1 / PST2 contract (cách chọn bài kế tiếp) giữ nguyên; task chỉ thêm thời điểm cuộn.

## Implementation approach

- Một cờ boolean trên `postsPage` + 1 listener `visibilitychange`; tái dùng `scrollToNextPost()`.

## Phải giữ nguyên

- Cuộn ngay sau tick khi trang đang hiện; tick bỏ (`posted = false`) không cuộn; cuộn ban đầu theo `#post-<clip>` / bài kế tiếp khi mở trang.
- Người dùng quay lại mà không có tick mới → không cuộn (cờ chỉ bật sau tick thành công).

## Code bị thay / xóa

- Không có (chỉ thêm cờ + listener; 2 chỗ gọi `scrollToNextPost()` sau tick đi qua helper mới).

## Acceptance Criteria

1. Tick thành công (copy / tay) khi trang ẩn → không gọi cuộn lúc đó; `visibilitychange` sang hiện → cuộn tới bài kế tiếp đúng 1 lần.
2. Tick thành công khi trang hiện → cuộn ngay như cũ; lần quay lại kế tiếp cuộn thêm 1 lần tới cùng đích; lần quay lại sau đó không cuộn.
3. Không có tick → quay lại trang không cuộn; bỏ tick không cuộn.
4. Full suite PASS.

## Required verification

- `PYTHONPATH=<worktree>/src pytest -q tests/test_web_post_scroll_return.py` — AC1–3 (kiểm mã JS theo cách các test web khác kiểm static JS: helper / listener / cờ có mặt và được gọi đúng chỗ).
- `node --check src/auto_short/web/static/app.js`.
- `pytest -q -n auto` (ORCHESTRATOR, ngoài sandbox) — AC4.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API.

- [x] Điện thoại, 8080 = commit của task: "Sao chép bài" → chuyển ngay sang YouTube → quay lại → trang nằm ở bài kế tiếp; lặp ≥ 5 lần.

## Result

- Main changes: IMPLEMENTER hoàn tất phần được giao. Thêm `postsPage.scrollOnReturn`; copy / tick tay thành công với `r.posted = true` yêu cầu cuộn sau reload. Trang hiện cuộn ngay và giữ một lần thử lại; trang ẩn chỉ giữ cờ. Listener tại `initPosts` cuộn sau một frame khi hiện lại, xóa cờ trước khi cuộn. Không đổi đích cuộn, polling hoặc cuộn ban đầu.
- Tests:
  - `PYTHONPATH=/home/ntnghia/projects/yas-scroll/src python -m pytest -q tests/test_web_post_scroll_return.py` — **7 passed in 0.29s**, dùng Python của env `auto-short` qua PATH. Lần đầu với Python mặc định không chạy được vì `No module named pytest`.
  - `node --check src/auto_short/web/static/app.js` — **PASS** (exit 0).
  - AC → test:
    - AC1: `test_return_scroll_lifecycle[hidden]` + hai ca `test_successful_posted_handlers_request_scroll_after_reload` kiểm wiring copy / tick tay.
    - AC2: `test_return_scroll_lifecycle[visible]`; `[hidden-before-frame]` kiểm chuyển app lần nữa trước frame không làm mất cờ.
    - AC3: `test_return_scroll_lifecycle[no-tick]`; test wiring kiểm chỉ gọi khi `r.posted`, sau reload và ngoài nhánh lỗi; `test_return_listener_is_only_registered_in_posts_init` kiểm cờ mặc định tắt và listener chỉ ở khởi tạo trang Bài đăng.
    - AC4: **chưa chạy**, ORCHESTRATOR chạy full suite ngoài sandbox theo contract.
- Diff + / − (app, test): app **+19 / −3** (`git diff --numstat`); test mới **+84 / −0** (untracked, chưa xuất hiện trong `git diff --numstat`).
- Helper mới (đã tìm, lý do không tái dùng): `requestPostScroll` đặt cờ và cuộn khi hiện; `resumePostScroll` xử lý visibility / frame và tiêu thụ cờ một lần. Đã tìm bằng `rg -n 'postsPage =|scrollToNextPost|tickPostedAfterCopy|togglePosted|visibilitychange|requestAnimationFrame' src/auto_short/web/static/app.js`; tái dùng `scrollToNextPost` nguyên trạng. Listener ZIP / giữ màn hình sáng hiện có không quản lý cờ cuộn Bài đăng nên không dùng chung.
- Review: tự kiểm diff theo contract, chỉ sửa owned paths; chờ ORCHESTRATOR review độc lập. Test Node chạy helper thật với trạng thái visibility / hàng frame / lệnh cuộn giả, không thêm dependency.
- Important findings / decisions: kiểm lại `document.hidden` và cờ trong frame để giữ lần thử lại nếu người dùng chuyển app trước khi frame chạy, đồng thời tránh tiêu thụ cờ hai lần.
- ORCHESTRATOR 2026-11-23: review diff OK; full suite `pytest -q -n auto` 4844 passed, 2 skipped (AC4 PASS); 8080 = cc50547 (KTO1 + fix), HUMAN LEAD thử điện thoại: "Được rồi đó pass". Codex 45,7 k tokens, 1 vòng.
- Known limitations: chưa chạy full suite hoặc manual test điện thoại; không tuyên bố AC4 PASS.
- PR: không commit / push / PR theo yêu cầu bàn giao.
