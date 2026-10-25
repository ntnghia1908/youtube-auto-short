# Task: FIX-queue-restore-kt — Khôi phục hàng đợi giữ job bản dọc của video chỉ còn `<id>.kt`

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review, test web / full suite
- Implementer: codex — sửa nhỏ 1 điểm + test (HUMAN LEAD 2026-10-25 ưu tiên Codex)
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-25 "viết contract nhỏ fix lỗi" (sau restart 8080 05:05 mất 5 job bản dọc Kinh Địa Tạng)
- Parallel group: —
- Owned paths: `src/auto_short/web/app.py` (`_rebuild_job`), `tests/test_web_queue_cp822.py`, contract này.
- Dependencies: FIX-hd-owner-kt (đã merge, #144)
- Base commit / branch: `db9738e` / `fix/queue-restore-kt`
- Human Lead approval: HUMAN LEAD 2026-10-25
- Implementation authorized: YES

## Goal

Restart web khi hàng đợi còn job bản dọc của video chỉ còn `work/<id>.kt/` (không còn `work/<id>/`): job được khôi phục và chạy tiếp như video còn đủ. Thực tế 2026-10-25: 5 tập Kinh Địa Tạng (`1VAkCR8kK5I`, `LeqFAlSS2oA`, `GLHlwvZdU4c`, `RLkVp6Bsevc`, `ztfEEXhnBf4`) bị log "bỏ qua việc đã lưu … (vertical): không tạo lại được".

## Scope

- In scope: nhánh `KIND_VERTICAL` của `_rebuild_job` — kiểm thư mục chủ theo `enhance_state.owner_for(config, eid)` thay vì `work/<eid>/`.
- Out of scope: kind khác (pipeline, render, enhance, add, post, restore-source), khóa job (`ep.hd_owner` vẫn là id gốc), lỗi "chưa có tiêu đề" của tập chưa xử lý (đúng hành vi).

## Authority / key decisions

- Quy tắc chủ HD / dọc: FIX-hd-owner-kt (`enhance_state.owner_for`). Không có quy tắc mới.

## Implementation approach

- Trong `_rebuild_job`, xử lý `KIND_VERTICAL` trước điều kiện `if not (ws / eid).is_dir()`: trả `None` khi `ws / owner_for(config, eid)` không tồn tại, ngược lại `ctx.vertical_target(eid)`. Tái dùng `enhance_state.owner_for`; không thêm helper.

## Phải giữ nguyên

- Video còn `work/<id>/`: khôi phục như cũ.
- Video không còn workspace nào (`<id>` lẫn `<id>.kt`): vẫn bỏ qua với log hiện có.
- Mọi test hiện có pass không sửa.

## Code bị thay / xóa

- Không có (đổi điều kiện trong một nhánh).

## Acceptance Criteria

1. Queue file có job `vertical` cho `<id>` chỉ có `work/<id>.kt/`: sau restart job được khôi phục (có trong lane `render`, target là vertical target của `<id>`).
2. Không có `work/<id>/` lẫn `work/<id>.kt/`: job bị bỏ qua (log "không tạo lại được"), như `test_restore_skips_job_whose_workspace_is_gone`.
3. Video còn `work/<id>/`: không đổi.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_web_queue_cp822.py tests/test_hd_owner_kt.py tests/test_web_vertical_cp832.py -q` (ORCHESTRATOR chạy nếu sandbox Codex không chạy được TestClient).
- Full suite (ORCHESTRATOR).

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API; manual test là điểm danh.

- [ ] Lần restart 8080 kế tiếp khi còn job bản dọc `.kt` trong hàng đợi: log không còn "bỏ qua việc đã lưu … (vertical)" cho tập `.kt`.

## Result

- Main changes: `_rebuild_job` xử lý `KIND_VERTICAL` trước kiểm `work/<eid>/`: kiểm `work/<enh_state.owner_for(config, eid)>/`; bỏ nhánh vertical cũ.
- Tests: AC1 `test_restore_vertical_job_with_only_khaithi_workspace`; AC2 `test_restore_skips_vertical_job_whose_workspaces_are_gone`; AC3 test hiện có. Targeted (`test_web_queue_cp822`, `test_hd_owner_kt`, `test_web_vertical_cp832`) 43 passed. Full suite: 2697 passed, 1 failed (test chập chờn `test_lower_thread_priority…`, chạy riêng PASS), 19 error `tests/test_publish_thumbs.py` có sẵn trên main (`episode.shapes` không còn — ngoài scope, xem findings).
- Diff + / − (app, test): app +4 / −2, test +36.
- Helper mới (đã tìm, lý do không tái dùng): không.
- Review: ORCHESTRATOR đọc diff, đúng scope; Codex (gpt-6.1-sol, medium) 1 vòng, 31.788 tokens, sandbox treo TestClient → ORCHESTRATOR chạy test.
- Important findings / decisions: main có 19 error ở `tests/test_publish_thumbs.py` (`AttributeError: module 'auto_short.packaging.episode' has no attribute 'shapes'`) — cần FIX riêng.
- Known limitations: —
- PR: (điền sau khi mở)
