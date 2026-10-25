# Task: RENDER-short-first — Làn render: Short / khai thị trước, bản dọc lấp chỗ trống

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review, test web / full suite, đo trên 8080
- Implementer: codex — đổi quy tắc chọn job trong 1 hàm + test (HUMAN LEAD 2026-10-25 ưu tiên Codex)
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-25 chọn "Render: Short trước dọc" (cân bằng CPU / 3090 khi nhiều job)
- Parallel group: P1 (song song FIX-publish-thumbs-shapes; owned paths rời nhau)
- Owned paths: `src/auto_short/web/jobs.py` (`_render_pick_locked` và helper nhỏ cạnh nó), `tests/test_render_short_first.py` (mới), contract này.
- Dependencies: none
- Base commit / branch: `b05fbaf` (origin/main) / `feature/render-short-first`
- Human Lead approval: HUMAN LEAD 2026-10-25
- Implementation authorized: YES

## Goal

Khi hàng đợi render có cả job bản dọc (`vertical`, ≈ 22 phút CPU / tập) và job Short / khai thị (`pipeline` bước render, `render`, `add`), job không phải bản dọc luôn được lấy trước; bản dọc chỉ dùng slot còn trống. Đo 2026-10-25: Short tập 21 xong AI nhưng chờ render 6 phút vì 2 slot đều chạy bản dọc, trong khi GPU 3090 là nút thắt (≈ 9 phút AI / tập) và CPU chỉ ≈ 65 %.

## Scope

- In scope: thứ tự chọn job của làn `render` (`_render_pick_locked`):
  1. lấy job không phải `vertical` trước (giữ thứ tự hiện có của `_pick`: ưu tiên P2 rồi FIFO);
  2. chỉ khi không có job đó mới lấy `vertical`;
  3. giữ chỗ: khi làn `ai` còn job chạy / chờ (Short sắp xuống render), bản dọc không được chiếm slot cuối cùng còn trống — tối đa `render_workers − 1` bản dọc chạy cùng lúc (với `render_workers = 1` thì quy tắc giữ chỗ không áp dụng).
- Out of scope: làn prepare / ai, `VERTICAL_PREFETCH`, CPU gate (`render_max_cpu`), compilation (giữ nguyên "chạy một mình" / drain), ngắt job bản dọc đang chạy, NVENC (RV1).

## Authority / key decisions

- CP8.36 (render song song, CPU gate), CP8.26 P2 (ưu tiên video), CP8.32 (bản dọc). Quyết định cục bộ S1: bản dọc là việc nền, có độ ưu tiên thấp hơn Short / khai thị trong làn render; ưu tiên video (P2) chỉ xếp thứ tự trong cùng nhóm.

## Implementation approach

- Trong `_render_pick_locked`: sau kiểm compilation, chọn `job = _pick(queue, not vertical & điều kiện hiện có)`; nếu None thì `_pick(queue, vertical & điều kiện hiện có)` và áp quy tắc giữ chỗ (đếm `vertical` đang chạy, `len(self._queues[AI])` + job ai đang chạy). Tái dùng `_pick`, `_lane_running_locked`, `_video_of`; không đổi `_pop`.

## Phải giữ nguyên

- Compilation chạy một mình / drain như cũ.
- Không 2 job cùng video chạy song song trong làn render.
- Slot phụ vẫn chỉ start khi CPU dưới `render_max_cpu`.
- Hàng đợi chỉ có bản dọc (không có việc AI): bản dọc dùng đủ mọi slot như cũ.
- Mọi test hiện có pass không sửa.

## Code bị thay / xóa

- Không có (đổi điều kiện chọn trong một hàm).

## Acceptance Criteria

1. Hàng đợi render `[vertical A, pipeline-render B]`, 1 slot rảnh: B start trước A.
2. 2 slot, `ai` còn job, đang chạy 1 vertical, hàng đợi chỉ còn vertical: slot thứ 2 không start vertical (giữ chỗ); khi `ai` trống thì start.
3. Chỉ có vertical, `ai` trống: chạy song song tới `render_workers` như cũ.
4. Ưu tiên P2 trong nhóm: hai job Short, job của video được ưu tiên start trước.
5. Compilation, cùng-video, CPU gate: test hiện có pass.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_render_short_first.py tests/test_web_render_parallel*.py tests/test_web_vertical_cp832.py tests/test_web_queue_cp822.py -q` (ORCHESTRATOR chạy nếu sandbox Codex không chạy được).
- Full suite (ORCHESTRATOR).

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API; manual test là điểm danh.

- [ ] 8080 khi chạy cả bộ Kinh Địa Tạng + bản dọc: log cho thấy Short xuống render không phải chờ bản dọc.

## Result

- Main changes: `_render_pick_locked` thêm quy tắc giữ chỗ: job được chọn là `vertical`, `render_workers > 1`, làn `ai` còn job chờ / chạy và đã có ≥ `render_workers − 1` bản dọc chạy → không start (slot chờ; `_after` của làn ai đã `notify_all` nên slot thức khi ai xong).
- Tests: `tests/test_render_short_first.py` (mới): AC1 `test_non_vertical_precedes_marked_vertical`; AC2 `test_vertical_reserves_last_slot_while_ai_busy`, `test_reservation_counts_vertical_jobs_only`, `test_ai_completion_notifies_reserved_render_slot`; AC3 `test_vertical_uses_all_slots_when_ai_idle`; AC4 `test_p2_and_fifo_within_short_group`; AC5 test hiện có `test_web_render_slots_cp836.py`, `test_render_parallel.py`, `test_web_vertical_cp832.py`, `test_web_queue_cp822.py`. ORCHESTRATOR chạy ngoài sandbox: targeted 83 passed; full suite 2721 passed, 1 skipped, 19 error `test_publish_thumbs` (lỗi có sẵn trên main, FIX-publish-thumbs-shapes sửa), 1 fail chập chờn đã biết `test_lower_thread_priority…` (chạy lại riêng PASS).
- Diff + / − (app, test): app +5 / −0; test +108 / −0.
- Helper mới (đã tìm, lý do không tái dùng): không có trong app; `_job` cục bộ trong test (không có factory `Job` dùng chung).
- Review: ORCHESTRATOR đọc diff + test, ACCEPTED vòng 1. IMPLEMENTER Codex (`gpt-6.1-sol`, effort high), 1 vòng, ≈ 80 k token; sandbox Codex timeout ở test TestClient (đã biết) → ORCHESTRATOR chạy.
- Important findings / decisions: scope 1–2 (không phải `vertical` trước) **đã có sẵn** từ `_rank` (CP8.32: `vertical` xếp sau mọi job khác); Short tập 21 chờ 6 phút vì cả 2 slot đã bị bản dọc chiếm *trước khi* Short tới — giữ chỗ là phần thực sự mới; AC1 / AC4 thành test khóa hành vi.
- Known limitations: slot giữ chỗ vẫn chịu CPU gate (`render_max_cpu`) khi là slot phụ — nếu bản dọc đẩy CPU vượt ngưỡng, Short vẫn chờ CPU (ngoài scope). Làn ai "down" (GPU tắt) mà còn job chờ thì slot giữ chỗ để trống tới khi ai trống.
- PR:
