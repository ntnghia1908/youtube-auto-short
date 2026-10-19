# Task: TC2.3 — Ghép theo chủ đề: quy trình một bước + bố cục điện thoại

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session
- Implementer: codex — `codex exec` (gpt-6.1-sol, high); quota 5 giờ 1 %
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/TC1-TC3-implementation-authorization.md` §4 + HUMAN LEAD 2026-10-19: “Trang AI tự ghép hơi khó xài … bỏ xác nhận độ dài … chỉ cần sử dụng chủ đề là vô ghép được luôn, có thể hỏi tiêu đề trước khi ghép, bỏ qua giai đoạn nháp … giao diện chưa hỗ trợ điện thoại tốt, danh sách yêu thích dài ở trên đầu phải kéo xuống dưới cùng mới thấy ghép bằng AI”
- Parallel group: —
- Owned paths: `src/auto_short/web/static/favorites.html`, `src/auto_short/web/static/favorites.js` (chỉ phần tab / thu gọn), `src/auto_short/web/static/theme_plan.js`, `src/auto_short/web/static/style.css` (class mới), `tests/test_web_theme_plan.py`, contract này
- Dependencies: TC2 / TC2.2 / TC3 (merged #98)
- Base commit / branch: `6c466d8` / `feature/tc2.3-simple-ui`, worktree `/home/ntnghia/youtube-auto-short-tc23`
- Human Lead approval: accepted (yêu cầu trực tiếp 2026-10-19)
- Implementation authorized: YES

## Goal

Từ trang Yêu thích, trên điện thoại: mở trang là thấy ngay “Ghép theo chủ đề (AI)”; bấm “AI gợi ý chủ đề” → mỗi chủ đề có tiêu đề (chọn 1 trong 3 hoặc sửa) và nút **“Ghép video”** → bấm là ghép luôn (không giai đoạn nháp, không xác nhận độ dài) → hiện tiến độ, xong có Tải về + Copy mô tả.

## Scope / decisions

- Sửa G4 (HUMAN LEAD 2026-10-19): bỏ tick xác nhận độ dài; độ dài ngoài 30–40 phút chỉ hiện chữ thông tin (“21,6 phút — ngắn hơn 30 phút”), không chặn. Việc bấm “Ghép video” với tiêu đề đã chọn là duyệt rõ ràng của HUMAN LEAD (boundary §4 giữ nguyên: người duyệt chủ đề, clip, thứ tự trước khi xuất).
- Không đổi API / backend: JS gọi tuần tự các route hiện có: `POST /theme-plans` {proposal_id} → (nếu tiêu đề khác mặc định) `PUT` {revision, title, clip_ids} → `POST …/approve` {revision, duration_override: true} → `POST …/render`. Lỗi ở bước nào thì báo rõ bước đó; bấm lại không tạo trùng (nếu đã có plan từ cùng proposal_id thì dùng tiếp plan đó).
- Thẻ chủ đề: tiêu đề (3 phương án dạng radio, mặc định ★, ô sửa), dòng phụ: số clip · phút · nhãn / lý do ngắn; danh sách clip thu gọn trong `<details>` “Xem N khai thị”; nút “Ghép video”.
- “Video đã ghép” (các plan): mỗi dòng tiêu đề + trạng thái (đang chờ / đang ghép / xong → Tải về + Copy mô tả / lỗi + “Ghép lại” / nội dung clip đã đổi → “Gợi ý lại”) + Xóa. Sửa danh sách clip (↑ ↓ ✕ thêm) giữ nhưng thu gọn trong `<details>` “Sửa danh sách clip” — sửa xong “Ghép lại” (PUT → approve → render).
- Bố cục: trang Yêu thích có tab (theo mẫu tab của `episode.html`): **“Ghép theo chủ đề (AI)”** (mặc định) | **“Yêu thích & ghép tay”** (danh sách yêu thích, ghép / lặp / tự ghép CP8.33, video ghép CP8.33). Nhớ tab cuối trong localStorage (try/catch). Mobile ≤ 640 px: không tràn ngang, nút đủ lớn để chạm.
- Out of scope: backend, TC1 / TC3, CP8.33 hành vi.

## Acceptance Criteria

1. Trang mở ở tab AI; trên 375 px không cần cuộn qua danh sách yêu thích để thấy nút “AI gợi ý chủ đề” và các chủ đề.
2. Một lần bấm “Ghép video” (sau khi chọn / sửa tiêu đề) → plan được tạo, duyệt (override khi ngoài khoảng) và job render được xếp; không có checkbox độ dài; bấm lại / reload không tạo plan trùng.
3. Trạng thái job và Tải về / Copy mô tả hiển thị trong “Video đã ghép”; plan stale hiện hướng dẫn rõ.
4. Tab “Yêu thích & ghép tay” giữ đủ chức năng CP8.33 hiện có.
5. Tests (Node harness / pytest hiện có) cho luồng một bước + không checkbox; full suite PASS.

## Required verification

- `env PYTHONPATH=/home/ntnghia/youtube-auto-short-tc23/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_theme_plan.py tests/test_web_compilation.py -x --tb=short` (ORCHESTRATOR chạy ngoài sandbox), full suite, `node --check` các file JS, framework-check, `git diff --check`.
- Manual: HUMAN LEAD trên điện thoại (8080 ghim nhánh, hỏi trước khi restart).

## Result

- Main changes:
- Tests:
- Review:
- PR: chưa.
