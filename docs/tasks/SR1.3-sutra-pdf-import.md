# Task: SR1.3 — Import PDF vào Đọc Kinh

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Human Lead: HUMAN LEAD
- Base commit / branch: sau SR1.2 / `feature/sr1-sutra-reader`
- Human Lead approval: accepted 2026-10-12 (SR1.1–SR1.3, làm lần lượt, một PR)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm dependency `pypdf` (gate R5) + parse file upload trong process con (security).

## Goal

Ở trang "Thêm bộ kinh" chọn được file `.pdf` (có lớp chữ): server trích chữ theo SR1 S5a và trả văn bản S2 vào ô soạn để HUMAN LEAD soát / sửa rồi Lưu như `.docx` / `.txt`.

## Scope

- In scope:
  - `pyproject.toml`: `pypdf==6.20.0` trong extra `[web]`; `docs/decisions/CP1-product-contract.md` §10 thêm dòng dependency + dòng "Sửa đổi HUMAN LEAD" (canonical list).
  - `src/auto_short/sutra/pdf.py`: `extract(path) -> (text, warnings)` theo S5a + entry `python -I -m auto_short.sutra.pdf <file>` in JSON ra stdout.
  - `sutra/importer.py` / `sutra/web.py`: nhánh `.pdf` của `POST /api/sutras/import` — ghi file tạm `work/_sutras/.tmp/`, chạy process con (`subprocess.run`, `timeout=120`, `sys.executable -I -m …`), xóa file tạm mọi trường hợp; 413 (> 30 MB), 422 (hỏng / không có lớp chữ / > 1 000 trang), 504 (timeout).
  - Trang soạn: `accept` thêm `.pdf`; thông báo "Chữ trích từ PDF cần soát lại" + danh sách cảnh báo.
  - Tests; ghi số đo vào decision record (mục cuối S5a).
- Out of scope: OCR PDF scan; nhớ / học sửa tay giữa các lần import; chỉnh tay theo từng file PDF cụ thể.

## Authority / key decisions

- `docs/decisions/SR1-sutra-reader-contract.md` S5, S5a, S6, R5.
- Tham chiếu thuật toán: prototype của ORCHESTRATOR `pdf2sutra.py` (scratchpad session 2026-10-12; ORCHESTRATOR đưa đường dẫn khi giao task) — chỉ để tham khảo, viết lại sạch theo S5a.

## Implementation approach

- Tách thuần: `lines_from_page(page) -> list[Line]` (pypdf), phần còn lại (header / footer, tiêu đề, ghép dòng, chú thích, xuất S2) là hàm thuần trên `list[list[Line]]` → test không cần PDF thật.
- Fixture PDF nhỏ tự sinh trong test (viết tay nội dung PDF với font chuẩn Helvetica, chữ ASCII, vài trang có header / số trang / dòng thụt / tiêu đề in hoa) cho đường đi pypdf; logic tiếng Việt / chữ Hán / 2 cột test bằng `Line` dựng tay.
- Số đo thật (không đưa vào test, không commit nội dung): chạy trên 3 PDF HUMAN LEAD gửi (`~/.claude/uploads/8d8331b7-…/`), ghi: số mục nhận được / số mục thật, header còn sót, số dòng cần sửa tay ước lượng.

## Acceptance Criteria

1. Header / footer lặp và số trang bị bỏ (kể cả khi dính vào dòng khác); tiêu đề in hoa nhiều dòng gộp thành một `#`.
2. Ghép dòng: văn xuôi bị ngắt theo cột ghép lại thành đoạn; kệ giữ từng câu; khổ tách bằng dòng trống; 2 cột trang ngang đọc đúng thứ tự.
3. NFC + sửa "h ữu"; chữ Hán song song tách thành dòng riêng; chú thích `[^n]` ghép đúng hoặc có cảnh báo.
4. Văn bản trả về parse được bằng `markup.parse` (không lỗi) với cả 3 PDF thật.
5. File hỏng / không lớp chữ → 422; quá thời gian → 504 và process con bị kill; file tạm luôn bị xóa; > 30 MB → 413.
6. Toàn bộ test hiện có PASS.

## Required verification

- `python -m pytest -q -n auto` — AC 1–3, 5, 6.
- Script đo trên 3 PDF thật — AC 4 + số đo ghi vào decision record.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm dependency + upload file (security): manual test là gate trước integration.

- [ ] Trên điện thoại: thêm A Di Đà từ PDF → ô soạn có mục lục hợp lý; sửa vài chỗ; Lưu; đọc được.
- [ ] Thêm Vô Lượng Thọ, Thái Thượng từ PDF; ghi lại phần phải sửa tay.
- [ ] Tải một PDF scan (không có chữ) → báo lỗi rõ ràng.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
