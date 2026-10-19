# Task: TC2.3 — Ghép theo chủ đề: quy trình một bước + bố cục điện thoại

## Status / Approval

- Status: READY
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

## Scope

- In scope: trang Yêu thích (tab, thẻ chủ đề, nút “Ghép video” một bước, “Video đã ghép”), CSS mobile, tests.
- Out of scope: backend, TC1 / TC3, hành vi CP8.33.

## Authority / key decisions


- Sửa G4 (HUMAN LEAD 2026-10-19): bỏ tick xác nhận độ dài; độ dài ngoài 30–40 phút chỉ hiện chữ thông tin (“21,6 phút — ngắn hơn 30 phút”), không chặn. Việc bấm “Ghép video” với tiêu đề đã chọn là duyệt rõ ràng của HUMAN LEAD (boundary §4 giữ nguyên: người duyệt chủ đề, clip, thứ tự trước khi xuất).
- Không đổi API / backend: JS gọi tuần tự các route hiện có: `POST /theme-plans` {proposal_id} → (nếu tiêu đề khác mặc định) `PUT` {revision, title, clip_ids} → `POST …/approve` {revision, duration_override: true} → `POST …/render`. Lỗi ở bước nào thì báo rõ bước đó; bấm lại không tạo trùng (nếu đã có plan từ cùng proposal_id thì dùng tiếp plan đó).
- Thẻ chủ đề: tiêu đề (3 phương án dạng radio, mặc định ★, ô sửa), dòng phụ: số clip · phút · nhãn / lý do ngắn; danh sách clip thu gọn trong `<details>` “Xem N khai thị”; nút “Ghép video”.
- “Video đã ghép” (các plan): mỗi dòng tiêu đề + trạng thái (đang chờ / đang ghép / xong → Tải về + Copy mô tả / lỗi + “Ghép lại” / nội dung clip đã đổi → “Gợi ý lại”) + Xóa. Sửa danh sách clip (↑ ↓ ✕ thêm) giữ nhưng thu gọn trong `<details>` “Sửa danh sách clip” — sửa xong “Ghép lại” (PUT → approve → render).
- Bố cục: trang Yêu thích có tab (theo mẫu tab của `episode.html`): **“Ghép theo chủ đề (AI)”** (mặc định) | **“Yêu thích & ghép tay”** (danh sách yêu thích, ghép / lặp / tự ghép CP8.33, video ghép CP8.33). Nhớ tab cuối trong localStorage (try/catch). Mobile ≤ 640 px: không tràn ngang, nút đủ lớn để chạm.

## Implementation approach

- JS-only theo các quyết định trên; tái dùng helper `el` / `api` / `fmtDur` / `copyText` của `favorites.js` và mẫu tab của `episode.html`.

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

- Vòng sửa production 2026-10-19 (IMPLEMENTER Codex; ORCHESTRATOR Claude Code): xác minh worktree đúng `feature/tc2.3-simple-ui`, HEAD `c1d3f65`, tree sạch trước sửa. Theo bằng chứng HUMAN LEAD: backend đã có plan approved + output nhưng thẻ chủ đề vẫn hiện Ghép video, dẫn đến bấm lại 3 lần.
  - Thẻ tìm plan theo cùng `proposal_id`: approved + output hiện `✓ Đã ghép · <phút>`, Tải về (đúng `download_url` / `download_name`) và Copy mô tả. Reload lấy tiêu đề đã lưu của plan; đổi radio / sửa tay khác `plan.title` hiện Ghép lại với tiêu đề này, dùng PUT → approve → render trên plan cũ. Job queued/running hiện Đang ghép… disabled; failed/interrupted hiện lỗi và Ghép lại. Nút chuyển sang Đang ghép… ngay trước request đầu tiên, polling hiện có cập nhật tới output. Phần sửa trạng thái ban đầu không sửa backend/CSS; phần bổ sung phát inline bên dưới được HUMAN LEAD authorize riêng. Không mạng, không commit/push.
  - PASS: `node --check src/auto_short/web/static/theme_plan.js`; `node scripts/framework-check.mjs`; `git diff --check`.
  - PASS: `env PYTHONPATH=/home/ntnghia/youtube-auto-short-tc23/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_theme_plan.py -k 'js or tab_panel or without_http' -x --tb=short` — 26 passed, 24 deselected. Harness kiểm tra chưa có plan, đang ghép (ngay khi bấm / queued / running), đã ghép (poll / reload không còn job history), đã ghép nhưng đổi tiêu đề (radio / sửa tay / đổi về tiêu đề cũ), download/copy và job lỗi/retry.
  - Chưa PASS toàn file trong sandbox: `timeout 35s env PYTHONPATH=/home/ntnghia/youtube-auto-short-tc23/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_theme_plan.py -x --tb=short -o faulthandler_timeout=20` — timeout exit 124; stack ở login fixture dòng 34 / TestClient / AnyIO portal. Full suite và manual production không chạy lại trong vòng sửa này. Bàn giao ORCHESTRATOR review diff và chạy verification ngoài sandbox trước khi xác nhận READY theo workflow; review ACCEPTED bên dưới thuộc phiên trước.
- Bổ sung cùng vòng sửa (HUMAN LEAD 2026-10-19: video đã ghép cần xem được): chỉ mở rộng backend trong route `GET /files/playlists/{pid}/theme/{name}`. `inline=1` bỏ Content-Disposition attachment, giữ video/mp4 và FileResponse/Range; gọi kiểm output metadata không hash video, chặn file rỗng bằng stat. Metadata hiện không có byte count để đối chiếu; FileResponse dùng stat cho Content-Length / Range. Tải thường giữ verify SHA như cũ. Hai vị trí output có Xem / Ẩn video, chỉ tạo `<video controls playsinline preload="metadata">` khi bấm, gỡ khi tắt; CSS giới hạn chiều rộng 100% khung.
  - PASS: `node --check src/auto_short/web/static/theme_plan.js`; harness/pytest `-k 'js or tab_panel or without_http' -x --tb=short` — 26 passed, 25 deselected, gồm bật/tắt/tạo lại video, đúng src `?inline=1` và thuộc tính ở cả thẻ chủ đề lẫn Video đã ghép. `git diff --check` PASS.
  - Thêm `test_inline_file_range_and_hash_policy`: inline không attachment, video/mp4, hai Range requests phải trả 206 + đúng body/Content-Range, không hash MP4 khi inline, tải thường vẫn hash + attachment, tải file sửa bị 404, inline file rỗng / metadata sai bị 404. Chạy trong sandbox với `timeout 25s ... -m pytest -q tests/test_web_theme_plan.py -k inline_file -x --tb=short -o faulthandler_timeout=15` vẫn treo tại fixture login/TestClient/AnyIO; chưa xác nhận PASS cho HTTP/Range. ORCHESTRATOR cần chạy ngoài sandbox trước READY. Không chạy lại full suite hay manual điện thoại trong sandbox.
- Main changes: AI là tab mặc định; nhớ tab cuối bằng localStorage có try/catch và hỗ trợ phím mũi tên/Home/End. CP8.33 nằm nguyên trong tab ghép tay. Thẻ chủ đề có radio tiêu đề (★ mặc định), ô sửa, thông tin thời lượng và danh sách khai thị thu gọn. Một nút Ghép video gọi create → PUT nếu đổi tiêu đề → approve (`duration_override: true`) → render, dùng revision trả về từng bước; không checkbox thời lượng. GET mới trước khi tạo để dùng tiếp plan theo `proposal.proposal_id`, khóa thao tác khi gửi và báo rõ bước lỗi. Video đã ghép hiển thị job/status, Tải về/Copy mô tả, Ghép lại, Xóa và Gợi ý lại cho stale/invalid; editor clip thu gọn giữ sửa/thêm/xóa/thứ tự, draft và trạng thái mở khi polling. CSS mới giới hạn trong trang Yêu thích, nút ≥44 px ở ≤640 px.
- Tests:
  - PASS: `node --check src/auto_short/web/static/favorites.js`; `node --check src/auto_short/web/static/theme_plan.js`.
  - PASS: `env PYTHONPATH=/home/ntnghia/youtube-auto-short-tc23/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_theme_plan.py -k 'js or tab_panel or without_http' -x --tb=short` — 23 passed, 24 deselected. Bao gồm luồng mặc định/chọn/sửa tiêu đề, không checkbox, override, revision, lỗi từng bước và thử lại, mất phản hồi create, bấm kép/reload, polling/focus/draft, sửa clip + retry sau PUT, stale, output/copy, tab/storage và payload concat/auto/loop CP8.33. Không thay đổi các HTTP tests hiện có.
  - PASS: `node scripts/framework-check.mjs`; `git diff --check`.
  - Chưa PASS trong sandbox: lệnh user yêu cầu `env PYTHONPATH=/home/ntnghia/youtube-auto-short-tc23/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_theme_plan.py -x --tb=short` treo tại TestClient, đã ngắt (exit 130). Chạy lại required web command với `timeout 40s` và `-o faulthandler_timeout=20`: `tests/test_web_theme_plan.py tests/test_web_compilation.py -x --tb=short` timeout (exit 124); stack tại login fixture `tests/test_web_theme_plan.py:34` / AnyIO portal. Probe tạo socket loopback riêng nhận `PermissionError: [Errno 1] Operation not permitted`.
  - Full suite: `timeout 60s env PYTHONPATH=/home/ntnghia/youtube-auto-short-tc23/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -n auto -x --tb=short` timeout (exit 124), có failure/error trước khi timeout nhưng không có final summary/chi tiết; không claim full suite PASS. Log tạm `/tmp/tc23-full-suite.log`. ORCHESTRATOR cần chạy lại required web command và full suite ngoài sandbox.
  - Manual 375 px/điện thoại: chưa chạy; HUMAN LEAD thực hiện theo Required verification. Không restart production.
- Review: ORCHESTRATOR ACCEPTED 2026-10-19 (Codex ≈ 117k tokens); `-m pytest -q -n auto` ngoài sandbox 2260 passed, 1 skipped. Manual test điện thoại: HUMAN LEAD.
- PR: chưa.
