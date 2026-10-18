# Task: CP8.36 — Làn render chạy song song khi server rảnh

## Status / Approval

- Status: DRAFT
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `e7a9d05` (`main`, sau #88 CP8.34) / `feature/cp8.36-render-parallel` (worktree `../youtube-auto-short-cp836`).
- Human Lead approval: pending
- Implementation authorized: NO

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

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
