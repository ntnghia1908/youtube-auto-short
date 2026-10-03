# Task: CP8.22 — Tạm ngưng / Chạy tiếp hàng đợi + lưu hàng đợi qua khởi động lại

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `3d60b11` (`main`) / `feature/cp8.22-queue-pause` (worktree `../youtube-auto-short-queue`)
- Human Lead approval: APPROVED nguyên bản 2026-10-03
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi job model W5 (CP8.3 / CP8.10: hàng đợi hiện chỉ trong bộ nhớ, "queued jobs are forgotten with the process") — thêm trạng thái lưu đĩa và trạng thái tạm ngưng toàn cục; thêm API.

## Bối cảnh

2026-10-03: muốn khởi động lại 8080 (đổi `[render] jobs` 4 → 2, ghim bản mới) khi có 1 job chạy + 48 job chờ. Khởi động lại làm mất hàng đợi trong bộ nhớ; ORCHESTRATOR phải ghi danh sách qua API rồi gửi lại tay. HUMAN LEAD muốn có nút Tạm ngưng / Chạy tiếp trên web.

## Goal

1. Nút **"Tạm ngưng"** / **"Chạy tiếp"** cho toàn hàng đợi trên web.
2. Khởi động lại 8080 (kể cả VM khởi động lại) **không mất hàng đợi**.

## Scope

- In scope:
  - **Q1 Tạm ngưng toàn cục.** Hai cách, hai nút:
    - "Tạm ngưng ngay": không bắt đầu bước mới ở mọi làn; bước đang chạy bị ngắt như khi tắt server (KeyboardInterrupt + SIGINT tiến trình con, cơ chế `stop` hiện có), job đó trở lại **đầu** hàng của làn (không thành lỗi); Chạy tiếp → làm lại bước bị ngắt (các bước đã xong không chạy lại — stage hash CP2).
    - "Tạm ngưng sau bước hiện tại": bước đang chạy chạy xong, rồi không bắt đầu bước mới.
    - "Chạy tiếp": các làn nhận việc lại theo thứ tự cũ.
    - Trong lúc tạm ngưng: vẫn gửi link / thêm việc được (vào hàng, chưa chạy); thao tác không cần job (tick, tải, xem) bình thường. Job `post_search` (tìm ảnh) và job soạn bài do người bấm: theo hàng như các job khác (IMPLEMENTER đề xuất nếu cần ngoại lệ).
    - Trạng thái tạm ngưng **lưu đĩa** (giữ qua khởi động lại) và hiện rõ trên mọi trang (thanh trên cùng: "Hàng đợi đang tạm ngưng — n việc chờ · Chạy tiếp").
  - **Q2 Lưu hàng đợi.** Mọi job đang chờ / đang chạy / đang đợi giữa hai làn / đợi GPU được ghi xuống ổ (ghi atomic khi hàng đợi đổi) đủ để tạo lại: loại job, episode, tham số (URL, kinds, phút khai thị, series / episode, clip / title với job render, …), làn và vị trí. Server khởi động → khôi phục đúng thứ tự; job đang chạy lúc tắt về đầu hàng làn của nó; job không tạo lại được (thiếu workspace, tham số hỏng) → bỏ qua, ghi log, không chặn khởi động. Vị trí file do IMPLEMENTER đề xuất (trong `work/` hoặc thư mục state của web), ghi vào authority.
  - **Q3 Tắt server êm.** `Ctrl-C` / dừng server: lưu hàng đợi trước khi ngắt các làn; job bị ngắt được ghi là "chờ chạy lại" thay vì mất.
  - Tương thích tự dọn nguồn (W9 S5) và FIX-ollama-wait (đợi GPU): tập có job trong hàng đợi đã khôi phục vẫn được coi là "có job".
  - Cập nhật authority `docs/decisions/CP8.3-web-contract.md` W5 (+ W6 UI, W7 API, Config nếu có).
- Out of scope: tạm ngưng từng tập / từng làn riêng; sắp xếp lại hàng đợi bằng tay; hủy từng job (nếu chưa có).

## Acceptance Criteria

1. "Tạm ngưng ngay" → không bước nào chạy (không còn tiến trình con ffmpeg / Whisper của job); job bị ngắt về đầu hàng; "Chạy tiếp" → chạy lại đúng bước đó, các bước xong không chạy lại.
2. "Tạm ngưng sau bước hiện tại" → bước đang chạy xong bình thường, sau đó không bước mới.
3. Tạm ngưng vẫn nhận link mới vào hàng; trạng thái tạm ngưng giữ qua khởi động lại; UI hiện trạng thái trên mọi trang.
4. Khởi động lại server khi có job chạy + job chờ (+ job đợi GPU) → hàng đợi khôi phục đúng thứ tự, job đang chạy lên đầu làn; khai thị giữ số phút; job hỏng bị bỏ qua có log.
5. Tự dọn nguồn không dọn tập có job đã khôi phục.
6. Authority CP8.3 W5 / W6 / W7 khớp hành vi.
7. `PYTHONPATH=<worktree>/src python -m pytest -q -n auto` PASS (chập chờn đã biết ghi rõ); `node scripts/framework-check.mjs` PASS.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest -q -n auto` — AC 1–5, 7 (tests runner: tạm ngưng / chạy tiếp, lưu / khôi phục, job hỏng).
- Server test 8081 trên bản sao dữ liệu nhỏ (`~/.cache/auto-short-cp8.22-test/`, không ghi `work/` / `output/` chính, không đụng 8080): xếp vài job, tạm ngưng ngay, kiểm không còn tiến trình con, Chạy tiếp; tắt server giữa chừng, khởi động lại, kiểm hàng đợi — AC 1–4; dán log rút gọn vào Result.
- `node scripts/framework-check.mjs` — AC 6, 7.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model; đổi job model + thêm API → manual test là gate trước merge:

- [ ] Có job chạy: bấm "Tạm ngưng ngay" → thanh trạng thái hiện, máy hết tải; "Chạy tiếp" → chạy lại.
- [ ] "Tạm ngưng sau bước hiện tại" → bước xong rồi dừng.
- [ ] Khởi động lại 8080 khi có hàng đợi → mở web thấy đủ job, đúng thứ tự.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
