# Task: POSTCOPY1 — Sao chép bài đăng tự tick "Đã đăng bài"

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: single-agent (sửa ~10 dòng JS + 2 test; giao IMPLEMENTER tốn hơn tự làm)
- Orchestrator: claude-code
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-02 "Với bài đăng thêm chức năng khi user nhấn sao chép bài thì tự tick vào đã đăng. Giống short và khai thị"
- Parallel group: —
- Owned paths: `src/auto_short/web/static/app.js`, `tests/test_web_post_doc_gate.py`, `tests/test_web_cp817.py`, `docs/decisions/CP8.15-community-post-contract.md`, file này
- Dependencies: none
- Base commit / branch: `d665342` (origin/main) / `fix/post-copy-ticks`
- Human Lead approval: accepted (yêu cầu trực tiếp 2026-11-02)
- Implementation authorized: YES

## Goal

Bấm "Sao chép bài" thành công là bài được tick "Đã đăng bài" ngay, không phải tải ảnh nữa (thay CP8.17 D1, D2).

## Scope

- In scope: thẻ bài ở trang Bài đăng (`postCard`); danh sách bài giữ lại ở trang chủ (CP8.38).
- Out of scope: server, route `posted`, `posts.json`; thư viện khai thị (`sutra.js`, đã tick khi copy từ SR2).

## Authority / key decisions

- `docs/decisions/CP8.15-community-post-contract.md` P8, đoạn "Sửa đổi POSTCOPY1".
- Sao chép không thành công (ô "Giữ vào ô để copy") → không tick. Bài đã tick → không gọi route. Bỏ tick tay vẫn được.

## Code bị thay / xóa

- Kho dấu `autoShort.postMarks` (`readPostMarks`, `writePostMarks`, `setPostMark`, `clearPostMark`, `postMarksDone`) và `markPostStep`: xóa; thay bằng `tickPostedAfterCopy`. Dấu cũ còn trong `localStorage` của trình duyệt: vô hại, không đọc nữa.

## Acceptance criteria

1. Sao chép thành công bài chưa tick (có ảnh hoặc không) → đúng một `POST /api/episodes/<id>/posts/<clip>/posted {value: true}`.
2. Sao chép thất bại → không gọi.
3. Bài giữ lại: "Copy" thành công trên bài chưa tick → tick + gọi route `kept-posts/…/posted`.

## Verification

- AC1, AC2: `tests/test_web_post_doc_gate.py` (chạy JS thật trong node, 4 origin × thành công / thất bại).
- AC3: manual test trên 8080.
- `node --check app.js`; full suite.

## Result

- Targeted: `tests/test_web_post_doc_gate.py tests/test_web_cp817.py` 20 passed; `node --check app.js` OK.
- Full suite (`-n 4`, chạy `nice -n 15` vì máy đang render): 3662 passed, 1 skipped, 1 failed = `test_prepare_parallel_cp829.py::test_lower_thread_priority_is_per_thread_and_inherited_by_children` (test chập chờn đã biết; chạy lại riêng PASS).
- AC3 / manual test trên 8080: chờ HUMAN LEAD.
