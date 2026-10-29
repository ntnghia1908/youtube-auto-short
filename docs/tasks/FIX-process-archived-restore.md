# Task: FIX-process-archived-restore — "Xử lý" tập đã dọn tự khôi phục nguồn từ kho rồi chạy tiếp

## Status / Approval

- Status: IN_PROGRESS
- Type: FIX
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `medium`); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-29 handoff: "FIX 'Xử lý tập đã dọn tự khôi phục nguồn từ kho'"
- Owned paths: `src/auto_short/web/context.py` (`queue_video`), `src/auto_short/web/app.py` (`RestoreSourceTarget` thêm bước xếp job sau khôi phục), `src/auto_short/web/playlists.py` (action cho tập đã dọn), `src/auto_short/web/static/app.js` (chỉ nhãn / confirm nút), test tương ứng (`tests/test_web_*restore*`, `tests/test_web_playlist*`), contract này
- Base commit / branch: `720dc10` (`origin/main`) / `fix/process-archived-restore`
- Human Lead approval: APPROVED 2026-10-29 (G1 = cả hai; "Duyệt, làm sau THUMB2")
- Implementation authorized: YES

## Hiện trạng (2026-10-29, đọc code)

- `queue_video` (`web/context.py:320`): kind có id đã dọn → 409 "đã dọn video nguồn; bấm Khôi phục nguồn"; không thử kho.
- Hàng bộ kinh: tập đã dọn (RENDERED / COMPLETE) không có nút (`web/playlists.py:58`, `:447`).
- Thêm khai thị cho tập đã dọn: chạy được nhưng tải lại nguồn riêng vào `work/<vid>.kt/`; Short vẫn ở trạng thái đã dọn.

## Goal

Bấm "Xử lý" (Short / khai thị) cho tập đã dọn → web tự xếp job "Khôi phục nguồn" (kho 3090 trước, YouTube sau, kiểm sha: `restore_source` hiện có), xong thì xếp tiếp các kind đã chọn; không bắt bấm "Khôi phục nguồn" trước, không tải nguồn hai lần.

## Scope

- `queue_video`: nhánh đã dọn → submit / nhập vào job `KIND_RESTORE_SOURCE` của `hd_owner` (logic busy / join như `routes/episodes.py:555-568`, như SRC3 `_defer_edit`), ghi kèm kind + tham số cần xếp; trả 202 kèm trạng thái "đang lấy lại nguồn".
- `RestoreSourceTarget`: khôi phục thành công → xếp các job pipeline đã ghi kèm (kind, phút khai thị, vertical); thất bại / hủy → không xếp, lỗi hiện trên job khôi phục.
- Restart giữa chừng: job khôi phục kèm danh sách xếp sau được khôi phục như SRC3 edits.
- Hàng bộ kinh: tập đã dọn có nút "Xử lý" khi còn kind chưa có (ví dụ chưa có khai thị) và "Xử lý lại" cho Short đã dọn (G1).
- Out of scope: đổi `restore_source`, chính sách dọn (`auto_archive`), Y2 bản dọc.

## Quyết định

- G1 (HUMAN LEAD 2026-10-29): **cả hai** — (a) thêm khai thị cho tập Short đã dọn; (b) "Xử lý lại" Short của tập đã dọn.

## Acceptance Criteria

1. Tập đã dọn + "Xử lý" → 1 job khôi phục (không 409), xong → job kind đã chọn được xếp và chạy với nguồn đã khôi phục (không tải thêm); bấm lặp → nhập vào job khôi phục đang có.
2. Khôi phục lỗi / hủy → không xếp job sau, lỗi rõ ràng; restart → danh sách xếp sau còn nguyên.
3. Tập chưa dọn: hành vi `queue_video` không đổi.
4. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

- Test targeted (job runner giả, store giả) + TestClient (ORCHESTRATOR); full suite `-n auto`.
- Chạy thật trên 8080: 1 tập đã dọn có bản trên kho → "Xử lý" khai thị → log thấy lấy từ kho, không gọi YouTube.

## Result

-
