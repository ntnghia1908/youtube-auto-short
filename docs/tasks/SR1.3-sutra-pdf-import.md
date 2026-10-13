# Task: SR1.3 — Import PDF vào Đọc Kinh

## Status / Approval

- Status: READY
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

- [x] Trên điện thoại: thêm A Di Đà từ PDF → ô soạn có mục lục hợp lý; sửa vài chỗ; Lưu; đọc được.
- [x] Thêm Vô Lượng Thọ, Thái Thượng từ PDF; ghi lại phần phải sửa tay.
- [x] Tải một PDF scan (không có chữ) → báo lỗi rõ ràng.

## Result

- Manual test: HUMAN LEAD 2026-10-12 trên điện thoại (8080) — OK (SR1.4: lỗi khung trắng ở chế độ lật trang đã sửa `a8f8c07` rồi thử lại OK).

- Main changes: `pyproject.toml` extra `[web]` `pypdf==6.20.0` (+ CP1 §10 dòng dependency và dòng "Sửa đổi HUMAN LEAD 2026-10-12"); `sutra/pdf.py` (hàm thuần trên `Run` / `Line` / `Page`: nhóm đoạn chữ thành dòng + 2 cột + ô chữ Hán, sửa dấu tách Word theo khoảng cách x, gắn `[^n]` lúc trích dòng, bỏ header / footer / số trang / header theo chương, định nghĩa chú thích, tiêu đề, ghép dòng logic, chữ đậm, giãn dòng; `extract()` bằng pypdf; entry `main()` in JSON, `RLIMIT_AS` 3 GiB); `sutra/importer.py` (`import_pdf`: file tạm `<store root>/.tmp/`, `subprocess.run([python, -I, -c, boot, <src dir>, <file>], timeout=120)` rồi xóa file tạm mọi trường hợp, quét file tạm cũ > 1 h; 413 / 422 / 504; tên bộ lấy từ tên file); `sutra/web.py` (giới hạn theo đuôi file: pdf 30 MB, txt / docx 5 MB); trang soạn nhận `.pdf` + thông báo "chữ trích từ PDF cần soát lại"; `scripts/sutra_pdf_measure.py`; số đo + làm rõ thuật toán ở cuối S5a của decision record; dòng `sutra/` của `docs/ai/project-profile.md`.
- Tests: `tests/test_sutra_pdf.py` (31: hàm thuần với Line / Run dựng tay + đường pypdf và process con trên PDF Helvetica tự viết), `tests/test_sutra_pdf_route.py` (12: route 200 / 413 / 415 / 422 / 504, kill process con, dọn file tạm), `tests/sutra_pdf_helpers.py`; sửa 2 test SR1.2 đã lỗi thời trong `tests/test_web_sutra_sr12.py` (`.pdf` giờ được nhận, `accept` thêm `.pdf`) và `tests/test_sutra_importer.py` (dùng `.exe` cho ca 415). Full suite `python -m pytest -q -n auto`: 1718 passed, 1 skipped; `node scripts/framework-check.mjs` PASS; `node --check sutra.js` OK. Số đo 4 PDF thật: decision record S5a "Số đo SR1.3" (AC 4: `markup.parse` OK cả 4; 48 / 48 phẩm và 48 / 48 nhãn nguyện bản đầy đủ).
- Review: chờ ORCHESTRATOR.
- Important findings / decisions: route chạy process con bằng `-I -c` + `sys.path.insert(<src dir>)` thay vì `-I -m` (vì `-I` bỏ `PYTHONPATH`, web 8080 chạy từ worktree ghim bằng `PYTHONPATH`); entry `python -I -m auto_short.sutra.pdf <file>` vẫn dùng được khi package đã cài. Quy tắc header của S5a làm rõ thêm (cụm lặp không số chỉ xóa khi cả dòng khớp và cùng độ cao; ô tách theo cỡ chữ; header theo chương có số ở giữa) — liệt kê ở cuối S5a.
- Known limitations: khổ kệ có dòng gần bằng dòng văn xuôi bị nối (cần soát tay, nhất là A Di Đà 2 trang / tờ); PDF xoay `/Rotate` chưa xử lý; trang bìa / mục lục cho tiêu đề rời rạc; manual test trên điện thoại (HUMAN LEAD) chưa chạy.
- PR: (chưa; một PR cho SR1.1–SR1.3)
