# Task: CP8.35 — "Xử lý" tự tạo luôn bản dọc cả tập

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `e7a9d05` (`main`, sau #88 CP8.34) / `feature/cp8.35-auto-vertical` (worktree `../youtube-auto-short-cp835`).
- Human Lead approval: APPROVED D1–D6 (2026-10-18)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi hành vi `POST /api/episodes` (field mới trong body), hành vi hàng đợi (job bản dọc tự xếp), UI hai trang; CP8.3 web contract W5 / W6 / W7. Không đổi dependency, security model.

## Bối cảnh (2026-10-18, ORCHESTRATOR)

- HUMAN LEAD: "khi nhấn xử lý một tập thì mặc định tạo luôn video bản dọc cho tập đó; hiện tại bấm xử lý nhưng không tự tạo video dọc". Trả lời câu hỏi cùng ngày: áp dụng **trang bộ kinh + trang gửi video lẻ**; Short xong mà HD chưa xong → **đợi HD rồi tạo**.
- Hiện nay: bản dọc chỉ tạo bằng tay ("Tạo bản dọc" một tập — `POST /api/episodes/{id}/vertical`; "Tạo bản dọc cả bộ" — CP8.32 V3). Job `vertical` chạy ở làn `render`, sau mọi job khác (CP8.32 V1), cần nguồn HD: `source_hd.mp4` (enhance) hoặc video gốc ≥ `[enhance] min_height` (CP8.32); gốc đã dọn → job tải lại (CP8.32 W9). Ô "Khi bấm Xử lý tạo:" (`#pl-kinds`, CP8.9 A2.2) chỉ có Short / Khai thị, nhớ trong `localStorage` `autoShort.plKinds`. Khi enhance bật, job pipeline "đợi HD" sau titling (CP13.1b E6); `_hd_ready` chạy khi ghép HD xong.

## Goal

Bấm "Xử lý" (hoặc gửi một video) với ô "Bản dọc" được tick → sau khi Short của tập xong và nguồn HD tốt nhất đã sẵn sàng, job bản dọc tự vào hàng đợi; không phải bấm "Tạo bản dọc".

## Quyết định cần HUMAN LEAD duyệt (D1–D6)

- **D1 Ô chọn.** Thêm ô "Bản dọc" vào "Khi bấm Xử lý tạo:" (trang bộ kinh) và vào ô loại ở trang gửi video; **mặc định tick**; nhớ cùng chỗ với lựa chọn hiện có (bộ kinh: `autoShort.plKinds`; trang gửi video: theo cách trang đó đang nhớ, nếu có). Trình duyệt đã lưu lựa chọn cũ (không có khóa bản dọc) → coi như tick. "Bản dọc" không tính là một "loại" Short / Khai thị: bỏ tick cả Short lẫn Khai thị vẫn báo "Chọn ít nhất một loại".
- **D2 Áp dụng.** "Xử lý", "Xử lý lại" (trang bộ kinh), "Chạy tiếp cả bộ" / xử lý nhiều tập dùng cùng lựa chọn của ô, và trang gửi một video. Bộ kinh: gửi link playlist (nhập bộ) không đổi.
- **D3 API.** `POST /api/episodes` nhận field tùy chọn `vertical: bool` (vắng = `false` → hành vi cũ, client cũ / script không đổi). `true` → ghi ý muốn "tự tạo bản dọc" cho video **trên đĩa** (sống qua khởi động lại server), gắn với video (`hd_owner`), xóa khi job bản dọc đã được xếp hoặc khi lần "Xử lý" sau gửi `vertical: false`.
- **D4 Khi nào xếp job bản dọc.** Khi một job của tập chạy bước render kết thúc `done` (hook CP8.16 R2a) **hoặc** khi HD của video ghép xong (`_hd_ready`), nếu video có ý muốn D3:
  - enhance của video đang bật và HD chưa xong (đang chờ / đang chạy / còn đoạn) → **chưa xếp**, đợi `_hd_ready`;
  - có nguồn HD (`source_hd.mp4` xong, hoặc enhance không bật cho video và gốc ≥ `min_height`, kể cả gốc đã dọn — job tự tải lại như CP8.32) → xếp job `vertical` như nút "Tạo bản dọc" (cùng hàm submit, cùng làn / thứ tự CP8.32 V1, trùng → "đã có");
  - không có nguồn HD (gốc < `min_height`, enhance không bật) → không xếp, xóa ý muốn, log 1 dòng + trang bộ kinh hiện lý do như hiện nay ("không có bản HD / video gốc < …p");
  - bản dọc đã `current` (cùng nguồn) → không xếp lại.
- **D5 Khai thị.** Bản dọc là của cả video (`hd_owner`), một lần cho cả Short lẫn Khai thị; tập chỉ chạy Khai thị (`.kt`) cũng kích hoạt.
- **D6 Hiển thị.** Không thêm màn hình mới: job bản dọc hiện ở hàng đợi / tab Theo dõi và icon bản dọc của trang bộ kinh như job bấm tay. Tập có ý muốn D3 mà đang đợi HD: dòng trạng thái bản dọc ghi "sẽ tạo khi có HD".

## Scope

- In scope: D1–D6; UI `playlist.html` / `index.html` (trang gửi video) / `app.js`; `POST /api/episodes` field `vertical`; lưu ý muốn trên đĩa; hook ở `web/app.py` (on_finished + `_hd_ready`); pointer CP8.3 web contract (W5, W6, W7); README dòng ngắn.
- Out of scope: tạo lại bản dọc khi HD đến sau một bản dọc từ gốc (đã chọn "đợi HD"); bản dọc cho tập đã xử lý trước đây mà không bấm lại "Xử lý" (dùng "Tạo bản dọc cả bộ"); đổi thuật toán bản dọc (`render_full`); render song song (CP8.36).

## Acceptance Criteria

1. Ô "Bản dọc" có ở hai trang, mặc định tick, nhớ qua lần mở sau; lựa chọn cũ không có khóa → tick.
2. `vertical: true` + enhance không bật + gốc ≥ 720p → sau job render `done` có đúng một job `vertical` xếp (log + hàng đợi).
3. `vertical: true` + enhance bật, HD chưa xong → không xếp khi Short xong; HD ghép xong → xếp đúng một job `vertical` từ `source_hd.mp4`.
4. `vertical: true` + gốc < `min_height` + enhance không bật → không xếp, ý muốn bị xóa, lý do hiển thị.
5. `vertical` vắng / `false` → không xếp job bản dọc (hành vi cũ); khởi động lại server giữa chừng → ý muốn còn, job vẫn được xếp khi điều kiện D4 tới.
6. Short + Khai thị cùng video → một job bản dọc (không trùng); bản dọc đã `current` → không xếp lại.
7. Toàn bộ suite PASS; route / hành vi cũ không đổi.

## Required verification

- `python -m pytest -q -n auto` — PASS (test mới `tests/test_web_auto_vertical_cp835.py` cho AC 1–7).
- `node scripts/framework-check.mjs` — PASS.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API (field mới ở `POST /api/episodes`, cùng auth); không chạm database, security model. Manual test qua 8080 (ghim commit nhánh) là gate trước integration.

- [ ] Trang bộ kinh: ô "Bản dọc" đã tick sẵn; "Xử lý" một tập không enhance (gốc ≥ 720p) → sau khi Short xong có job bản dọc trong hàng đợi, tải được bản dọc.
- [ ] Một tập có enhance: Short xong → chưa có job bản dọc ("sẽ tạo khi có HD"); HD xong → job bản dọc tự xếp.
- [ ] Bỏ tick "Bản dọc" → "Xử lý" không tạo bản dọc.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
