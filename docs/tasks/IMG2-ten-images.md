# Task: IMG2-ten-images — AI vẽ 10 ảnh mỗi lượt cho thư viện ảnh bài đăng

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `medium`, sửa nhỏ)
- Authorization mode: boundary
- Authorization source: HUMAN LEAD 2026-11-02: "Ai vẽ ảnh cho bài Đăng đang làm khá tốt nhưng có thể vẽ một lượt 10 ảnh không"
- Parallel group: —
- Owned paths: `src/auto_short/post/imggen.py`, `src/auto_short/web/static/posts.html` (chỉ nhãn nút), `src/auto_short/web/static/app.js` (chỉ chữ "5 ảnh" nếu có), `tests/test_imggen_img1.py`, `tests/test_web_imggen_img1.py`, `docs/decisions/CP8.15-community-post-contract.md` (P5e: số ảnh), `docs/tasks/IMG1-ai-post-images.md` (dòng pointer tới IMG2), contract này
- Dependencies: IMG1 (#192, đã merge)
- Base commit / branch: `23d5088` (`origin/main`) / `feature/img2-ten-images`
- Human Lead approval: inherited from boundary (nguồn ở trên)
- Implementation authorized: YES

Lifecycle: `DRAFT → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ đổi số ảnh mỗi lượt và prompt; không route, config, dependency mới.

## Goal

Nút "AI vẽ 10 ảnh": mỗi lượt Codex vẽ tối đa 10 ảnh vuông thay vì 5.

## Key decisions

- D-IMG2-1: số ảnh là hằng `COUNT = 10` trong `imggen.py`; prompt, vòng đọc `image-1..10.png`, nhãn nút dùng cùng số. Không thêm config, không cho chọn trên UI.
- D-IMG2-2: ảnh 1–5 giữ 5 phong cách D-IMG1-8, bố cục toàn cảnh; ảnh 6–10 lặp lại 5 phong cách đó theo thứ tự nhưng bố cục cận cảnh chủ thể / góc nhìn khác, để không trùng ảnh 1–5. Các rule D-IMG1-2 (không người thật, không chữ / logo / watermark) giữ nguyên.
- D-IMG2-3: thời gian một lượt ~2 × IMG1 (đo IMG1: 266–319 s cho 5 ảnh), vẫn dưới `[thumbs] codex_timeout_minutes = 30`.

## Acceptance criteria

- AC1: prompt yêu cầu đúng 10 ảnh, liệt kê 10 mục, lưu `image-1.png` đến `image-10.png`.
- AC2: Codex giả trả 10 ảnh hợp lệ → lượt `done` có 10 ứng viên; thiếu vài ảnh → vẫn `done` với số còn lại, lý do ở `skipped` (như IMG1).
- AC3: nhãn nút "AI vẽ 10 ảnh".
- AC4: test IMG1 cũ cập nhật số, không nới điều kiện khác.

## Verification

- `PYTHONPATH=<worktree>/src conda run -n auto-short python -m pytest -q tests/test_imggen_img1.py tests/test_web_imggen_img1.py`
- Full suite (ORCHESTRATOR, ngoài sandbox).
- Chạy thật 1 lượt trên thư mục ảnh tạm (ORCHESTRATOR).

## Result

- Implementer: Codex 1 vòng (effort medium, 52.832 tokens), +53/−17 trong 6 file; ORCHESTRATOR thêm ghi chú bố cục vào D-IMG1-3 (CP8.15). Không cần vòng sửa.
- AC1–AC4: `tests/test_imggen_img1.py` + `tests/test_web_imggen_img1.py` 47 PASS (có ca 7/10 ảnh → `done` 7 ứng viên, `skipped` `{"thiếu ảnh": 3}`).
- Full suite: `1 failed, 3751 passed, 1 skipped`; test fail là `test_prepare_parallel_cp829.py::test_lower_thread_priority_is_per_thread_and_inherited_by_children` (chập chờn đã biết, current-state), chạy lại riêng PASS.
- Chạy thật (HUMAN LEAD chọn từ khóa "A Di Đà Phật", 2026-11-02): `done`, 10/10 ảnh 1024×1024, `skipped` rỗng, 304 s, 41.773 tokens (IMG1 5 ảnh: 266–319 s, 26.690 tokens). Ảnh 1–5 toàn cảnh, 6–10 cận cảnh đúng 5 phong cách; không chữ.
- Chưa kiểm: nút trên trình duyệt (cần restart 8080).
