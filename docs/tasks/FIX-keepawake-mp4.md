# Task: FIX-keepawake-mp4 — `keepawake.mp4` của CP8.34 A2 không vào git

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: single-agent
- Implementer: — (single-agent: sửa 2 dòng `.gitignore` + 1 file tĩnh tạo lại bằng lệnh đã ghi; giao implementer không đáng)
- Base commit / branch: `e7a9d05` (`main`) / `fix/keepawake-mp4` (worktree `../youtube-auto-short-keepawake`).
- Human Lead approval: APPROVED (2026-10-18)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

`src/auto_short/web/static/keepawake.mp4` (video dự phòng giữ màn hình, CP8.34 A2) có trong git; `/static/keepawake.mp4` trả 200 trên 8080; `tests/test_web_downloads_cp834.py::test_keep_awake_fallback_video_and_warning` PASS trên `main`.

## Bối cảnh (2026-10-18, ORCHESTRATOR)

- IMPLEMENTER CP8.36 báo test trên PASS ở worktree CP8.34 nhưng 404 trên `main` `e7a9d05`. Nguyên nhân: `.gitignore:15` `*.mp4` → file tạo ở CP8.34 A2 không được commit; review CP8.34 chạy test trong worktree có file chưa track nên không thấy. 8080 (ghim `e7a9d05`) đang trả 404 cho video dự phòng → cách dự phòng A2 không chạy.

## Scope

- In scope: thêm ngoại lệ `!src/auto_short/web/static/keepawake.mp4` vào `.gitignore`; tạo lại file bằng lệnh đã ghi ở CP8.34 Result (`ffmpeg -y -f lavfi -i color=c=0x020202:s=64x64:r=5 -t 3 -c:v libx264 -profile:v baseline -pix_fmt yuv420p -an -movflags +faststart keepawake.mp4`); commit file.
- Out of scope: đổi code / test CP8.34.

## Acceptance Criteria

1. `git ls-files` có `src/auto_short/web/static/keepawake.mp4`; `git check-ignore` không còn bỏ qua nó.
2. Test `test_keep_awake_fallback_video_and_warning` PASS trên một clone sạch của nhánh (worktree mới, không file lạ).

## Required verification

- `git status --ignored` trong worktree sạch: không còn file chưa track nào cần cho test.
- `python -m pytest -q -n auto` — PASS (toàn bộ).
- `node scripts/framework-check.mjs` — PASS.

## Manual test checklist (Tech Lead)

Không chạm public API, database, security model.

- [ ] Sau khi ghim 8080: `/static/keepawake.mp4` trả 200 (đã đăng nhập); trên điện thoại tắt cờ Chrome → video nhỏ chạy khi hàng đợi tải chạy.

## Result

- Main changes: `.gitignore` thêm `!src/auto_short/web/static/keepawake.mp4` (dòng chú thích riêng: `.gitignore` không nhận chú thích cuối dòng); `keepawake.mp4` tạo lại bằng lệnh ở Scope (1 708 byte) và commit.
- Tests: worktree sạch `git worktree add --detach` của commit fix: `python -m pytest -q -n auto` 1889 passed, 1 skipped (gồm `test_keep_awake_fallback_video_and_warning`); `node scripts/framework-check.mjs` PASS; `git status --ignored` không còn file cần mà chưa track.
- Review: single-agent; ORCHESTRATOR tự kiểm như trên.
- Important findings / decisions: repo đã có `static/sutra-awake.mp4` (trang Đọc Kinh có cách dự phòng video riêng) — ghi chú CP8.34 "trang Đọc Kinh cùng vấn đề" chỉ đúng phần Wake Lock; không gộp hai file trong FIX này.
- Known limitations: —
- PR: #89
