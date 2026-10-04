# Task: CP8.27 — Nút tải video đầy đủ đã enhance (HD)

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `0e0581f` (`main`) / `feature/cp8.27-hd-download` (worktree `../youtube-auto-short-hddl`). Bắt đầu sau khi CP8.26 merge (chung `web/app.py`, `static/app.js`): rebase lên `main` mới rồi mới implement.
- Human Lead approval: APPROVED 2026-10-04 ("Thêm nút tải full video đã enhance")
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: thêm một route tải file sau đăng nhập web (cùng cookie / luật như các nút tải Short / zip CP8.7, CP8.17); không đổi dependency, security model, API worker.

## Bối cảnh

CP13.1b ghép bản HD cả tập vào `work/<id>/source_hd.mp4` (1440×1080, H.264 + Opus, ~1,3–2 GB / tập 1 giờ) và chỉ dùng để render. HUMAN LEAD muốn tải bản HD đầy đủ này về.

## Goal

Trang tập (và dòng tập ở trang bộ kinh) có nút "Tải video HD" khi `source_hd.mp4` đã xong (`enhance.json` `state = done`, sha / kích thước khớp); tải được file lớn ổn định (hỗ trợ `Range`, tải tiếp được), tên file dễ đọc.

## Scope

- In scope:
  - **H1 Route** `GET /api/episodes/{id}/source-hd` (tên tùy IMPLEMENTER): chỉ khi đã đăng nhập; chỉ file `source_hd.mp4` của tập (khai thị `.kt` dùng HD của video gốc); `FileResponse` (Range), `Content-Disposition: attachment` với tên `<bộ kinh>_Tập<N>_HD.mp4` (theo quy ước tên của CP8.17; tập lẻ / không có số tập → `<video id>_HD.mp4`; tên non-ASCII theo cách CP8.17 đang làm); 404 rõ khi chưa có HD.
  - **H2 UI**: nút "Tải video HD (x,x GB)" ở trang tập + biểu tượng tải ở dòng tập của trang bộ kinh khi có HD; ẩn khi chưa có.
  - **H3** Tải không tự tick "Đã đăng" / "Đã xem"; không chặn job đang chạy (đọc file, không khóa).
  - Test (file nhỏ giả) + README nếu có danh sách nút tải.
- Out of scope: tải bản HD từng đoạn / nén lại; tải video gốc; zip nhiều tập HD; xóa `source_hd.mp4`.

## Authority / key decisions

- `docs/tasks/CP13.1b-enhance-vm.md` (source_hd), `docs/tasks/CP8.17-download-rules.md` (tên file, luật tải), `docs/tasks/CP8.7-playlist.md`.

## Acceptance Criteria

1. Tập có HD xong: route trả file đúng, `Content-Disposition` tên đúng, `Range` trả 206.
2. Tập chưa có HD / đang enhance / HD hỏng (sha / size không khớp `enhance.json`): 404 + thông báo; nút ẩn.
3. `.kt` trả HD của video gốc; id sai / ngoài workspace → 404 / 422, không đọc file ngoài `work/`.
4. Chưa đăng nhập → bị chặn như các route khác.
5. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–5.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API. Điểm danh trên 8080: tải HD tập 1 Địa Tạng, mở xem được, tên file đúng.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
