# Task: CP8.36 — Làn render chạy song song khi server rảnh

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `e7a9d05` (`main`, sau #88 CP8.34) / `feature/cp8.36-render-parallel` (worktree `../youtube-auto-short-cp836`).
- Human Lead approval: APPROVED D1–D6 (2026-10-18)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi mô hình hàng đợi (CP8.3 web contract W5: "các làn khác giữ một worker", CP8.29), config `[web]` mới. Không đổi dependency, security model, API.

## Bối cảnh (2026-10-18, ORCHESTRATOR)

- HUMAN LEAD: "hàng render của server chỉ xử lý một việc một lần trong khi server rảnh khá nhiều; có thể tăng lên hai ba việc xử lý song song render nếu server rảnh". Trả lời câu hỏi cùng ngày: "rảnh" = **CPU dưới ngưỡng**; **không đo trước, đặt 2 luôn**.
- Hiện nay (`web/jobs.py`): làn `render` một worker; job của làn: `render` / phần render của `pipeline`, `add`, `enhance` (ghép HD, `enhance_key`), `vertical` (`vertical_key`, sau mọi job khác — CP8.32 V1, giới hạn gốc tải lại `VERTICAL_PREFETCH`), `compilation` (CP8.33). Làn `prepare` đã có nhiều slot (CP8.29: `prepare`, `prepare#1`…, luật cùng video không chạy cùng lúc, `worker_nice`). `[render] jobs = 2` là số Short encode song song **trong** một job.
- Đo 2026-10-18 01:14 UTC: CPU bận ≈ 89 % (một bản dọc + làn prepare 4 việc), RAM trống 112 GB; VM 32 nhân. Lúc làn prepare vắng thì CPU dư nhiều.

## Goal

Khi CPU còn rảnh, làn render chạy tới 2 việc cùng lúc (cấu hình được), không để hai việc đụng cùng file; khi CPU bận thì như cũ (một việc).

## Quyết định cần HUMAN LEAD duyệt (D1–D6)

- **D1 Slot.** `[web] render_workers` (số nguyên 1–4, **mặc định 2**; 1 = như cũ). Slot đầu `render` như hiện nay; slot thêm `render#1`, … như CP8.29. Chế độ `queue_mode = "serial"`: không đổi.
- **D2 "Rảnh".** Slot đầu luôn lấy việc như cũ. Slot thêm chỉ **bắt đầu** một việc khi tải CPU trung bình 1 phút (`/proc/loadavg`, `os.getloadavg`) < `[web] render_max_load` × số nhân (**mặc định 0.6**, tức < 19,2 trên VM 32 nhân); không đạt → chờ rồi kiểm lại (vd mỗi 30 s, hoặc khi có job mới / job xong). Việc đã chạy **không bị dừng** khi CPU lên lại.
- **D3 Không đụng nhau.** Hai việc cùng video (`<id>` / `<id>.kt`, `hd_owner`) không chạy cùng lúc trong làn render (gồm `enhance` ghép HD với `vertical` / `render` của cùng video). `compilation` (đọc file của nhiều tập trong bộ) chỉ bắt đầu khi làn render không chạy việc nào khác, và khi nó chạy thì slot khác không bắt đầu việc mới. Giữ thứ tự CP8.32 V1 (bản dọc sau mọi job khác), ưu tiên CP8.26, tạm ngưng CP8.22, giới hạn `VERTICAL_PREFETCH`.
- **D4 nice / threads.** Slot thêm dùng cùng `worker_nice`. Không đổi `[render] jobs` / threads ffmpeg của mỗi việc.
- **D5 Hiển thị.** Thanh hàng đợi / tab Theo dõi hiện đủ các việc render đang chạy (nhiều dòng như làn prepare); `/api/queue` `running` đếm đúng.
- **D6 Lưu hàng đợi.** Lưu / khôi phục hàng đợi qua khởi động lại (CP8.22) đúng với nhiều việc render đang chạy (việc đang chạy lúc dừng quay lại đầu hàng như hiện nay).

## Amendment A1 (2026-10-18, HUMAN LEAD: "CPU hiện tại avg 55% đáng ra phải render song song")

Thử trên 8080 (ghim `32f71e4`): CPU bận ≈ 53 % (`top`: 46,6 % idle) nhưng load average 1 phút 20,8 > 19,2 (0,6 × 32) → slot thêm không chạy. Load average đếm cả luồng chờ CPU (ffmpeg nhiều luồng, nice) nên cao hơn % CPU thật; HUMAN LEAD nhìn % CPU (tab Theo dõi).

- **A1a Thước đo.** Thay D2 "load average 1 phút < `render_max_load` × số nhân" bằng **% CPU bận trung bình ≈ 60 s** (từ `/proc/stat`, cùng cách tính tab Theo dõi CP8.28: (total − idle − iowait) / total trên mọi nhân; lấy mẫu định kỳ, trung bình trượt ~60 s) **< `[web] render_max_cpu`** (tỉ lệ 0–1, **mặc định 0.6**). Không đọc được / chưa đủ mẫu → coi như bận (slot thêm chờ). Bỏ `render_max_load` (chưa phát hành; config có khóa cũ → cảnh báo một dòng hoặc `ConfigError` rõ, implementer chọn và ghi lại).
- Còn lại của D1–D6 giữ nguyên. AC 2 đọc theo thước đo mới; nguồn % CPU phải inject được trong test.

## Scope

- In scope: D1–D6 trong `web/jobs.py` (slot, luật bắt đầu, luật không đụng nhau), `config.py` (`render_workers`, `render_max_load` + kiểm tra giá trị), `web/server.py` / `web/app.py` (truyền config), monitor / thanh hàng đợi nếu cần; `config.example.toml` (nếu có) + README; pointer CP8.3 web contract W5.
- Out of scope: đo 1 / 2 / 3 việc (HUMAN LEAD chọn không đo); chia lại threads ffmpeg theo số slot; ưu tiên / giới hạn theo RAM, đĩa (ngoài `VERTICAL_PREFETCH` có sẵn); làn `ai`.

## Acceptance Criteria

1. `render_workers = 2`, CPU rảnh (load giả lập thấp), hai job render của hai video khác nhau → chạy cùng lúc.
2. Load giả lập ≥ ngưỡng → slot thêm không bắt đầu việc; slot đầu vẫn chạy; load hạ → slot thêm bắt đầu.
3. Hai job cùng video (vd `render` + `vertical`, `enhance` + `vertical`, `<id>` + `<id>.kt`) → không chạy cùng lúc.
4. `compilation` không chạy song song với việc render nào khác (cả hai chiều).
5. `render_workers = 1` → hành vi giống hệt hiện nay (test cũ của làn render PASS không sửa).
6. Thứ tự V1 / ưu tiên / tạm ngưng / lưu hàng đợi đúng với 2 slot; `/api/queue` + monitor đếm đúng.
7. Config sai (`render_workers` ngoài 1–4, `render_max_load` ≤ 0) → `ConfigError` rõ ràng.
8. Toàn bộ suite PASS.

## Required verification

- `python -m pytest -q -n auto` — PASS (test mới `tests/test_web_render_slots_cp836.py` cho AC 1–7, load giả lập qua tham số inject được, không phụ thuộc tải máy thật).
- `node scripts/framework-check.mjs` — PASS.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm public API, database, security model; đổi mô hình hàng đợi. Manual test qua 8080 (ghim commit nhánh) sau automated verification.

- [ ] Lúc làn prepare vắng: hai việc render (vd hai bản dọc) chạy cùng lúc, tab Theo dõi hiện cả hai; web vẫn mượt.
- [ ] Lúc CPU bận (prepare 4 việc): chỉ một việc render chạy.
- [ ] Khởi động lại server khi đang chạy 2 việc render → cả hai quay lại hàng đợi, chạy tiếp.

## Result

- Main changes: `web/jobs.py` — `JobRunner(render_workers, render_max_load, load_source, cpu_count, load_check_seconds)`: slots `render`, `render#1`, ..; `_render_pick_locked` (D3: no job of a video another running job holds, `<id>` / `<id>.kt` via `_video_of`; `compilation` alone both ways, and when a compilation is the first in start order the lane drains instead of starting others); extra slots start only while `load_source()` (default `os.getloadavg()[0]`) < `render_max_load` x CPU count, re-checked every 30 s (`Condition.wait` timeout) and on every submit / finish; first slot never load-gated. `config.py` — `[web] render_workers` (1-4, default 2), `render_max_load` (> 0, default 0.6). `web/app.py` — one wiring line. Monitor / `/api/queue` / persistence needed no change (already per running job, CP8.29 / CP8.22). `config.example.toml`, README, CP8.3 W5 pointer + config table.
- Tests: `tests/test_web_render_slots_cp836.py` (14 tests, AC 1-7); full suite `-n auto`: 1902 passed, 1 skipped, 1 failed (`test_web_downloads_cp834.py::test_keep_awake_fallback_video_and_warning`, 404, fails identically on base `e7a9d05`: pre-existing, outside scope); `node scripts/framework-check.mjs` PASS.
- Review: ORCHESTRATOR 2026-10-18 ACCEPTED — đọc `jobs.py` (`_render_pick_locked`, `_cpu_idle`, slot `render#i`, `_take_locked(lane, slot)`), `config.py`, wiring `app.py`; đường `render_workers = 1` dùng cùng `_pick` / thứ tự như `_pop` cũ. 1 test lỗi của suite (`test_keep_awake_fallback_video_and_warning`, 404) có sẵn trên `main` `e7a9d05` — `keepawake.mp4` của CP8.34 bị `*.mp4` trong `.gitignore` bỏ qua; sửa ở FIX-keepawake-mp4, không thuộc CP8.36. Chấp nhận luật thêm "drain" cho compilation (tránh compilation chờ mãi, đúng tinh thần D3).
- Review A1: ORCHESTRATOR 2026-10-18 ACCEPTED — đọc `CpuAverage`, luồng `auto-short-cpu`, `_cpu_idle`, config `render_max_cpu` (khóa cũ `render_max_load` → `ConfigError`); `config.toml` repo chính không có khóa cũ. Sau khởi động lại slot thêm chờ ≈ 30 s (đủ mẫu) — chấp nhận.
- Important findings / decisions: `JobRunner()` constructor default `render_workers=1` (as `prepare_workers`); the config default 2 applies through `create_app`. The "drain" rule for a compilation at the head of the queue is an IMPLEMENTER choice (avoids starvation by a steady stream of jobs).
- Known limitations: unreadable load counts as busy (extra slot idle); load is not re-evaluated for running jobs.
- PR:

### Result — Amendment A1

- Main changes: the load-average gate is replaced by CPU busy fraction. `web/jobs.py` — `CpuAverage` (sliding ~60 s window of `/proc/stat` samples, formula of the CP8.28 monitor via `monitor.read_cpu_times`; `None` until the samples span >= 30 s or when unreadable = busy); a daemon thread `auto-short-cpu` samples every 5 s (only when `render_workers` > 1 and no injected source) and wakes the render slots; `JobRunner(render_max_cpu, cpu_source)` replaces `render_max_load` / `load_source` / `cpu_count`; extra slot starts only while `cpu_source() < render_max_cpu`. `config.py` — `[web] render_max_cpu` (0 < x <= 1, default 0.6); a leftover `render_max_load` key raises `ConfigError` ("replaced by web.render_max_cpu") — chosen over a warning so a stale setting is never silently ignored. README, `config.example.toml`, CP8.3 W5 / config table updated. `stop()` untouched.
- Tests: `tests/test_web_render_slots_cp836.py` 16 tests (AC 2 on the CPU fraction, unreadable = busy, `CpuAverage` over fake `/proc/stat`, config validation incl. the old key). Full-suite numbers: see the READY report.


### Result — test-only follow-up

- `test_vertical_is_last_even_with_a_free_slot` raced (an idle slot could take `v` before `a` / `b` were queued): the queue is now paused until all three are queued, then resumed. Other tests compared the start order of jobs that two slots start concurrently; those assertions now compare sorted lists. No runner change.
