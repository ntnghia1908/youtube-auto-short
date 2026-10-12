# Task: SR1.2 — Thêm / sửa / xóa bộ kinh (import `.txt` / `.docx`)

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Human Lead: HUMAN LEAD
- Base commit / branch: sau SR1.1 / `feature/sr1-sutra-reader`
- Human Lead approval: accepted 2026-10-12 (SR1.1–SR1.3, làm lần lượt, một PR)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: upload file mới (security boundary) của ứng dụng SR1. Không thêm dependency (python-docx đã duyệt CP8.31).

## Goal

Từ thư viện bấm "Thêm bộ kinh" → tải `.docx` / `.txt` (hoặc dán chữ) → xem trước cấu trúc (mục lục + vài đoạn đầu) và sửa văn bản S2 → Lưu → bộ mới có trong thư viện. Sửa văn bản và xóa một bộ có sẵn từ trang đọc.

## Scope

- In scope:
  - `sutra/importer.py` (S5): `.txt` / `.docx` → văn bản S2 + cảnh báo; kiểm zip; heuristic tiêu đề; chú thích Word.
  - `sutra/web.py`: `POST /api/sutras/import`, `POST /api/sutras`, `PUT /api/sutras/{slug}` (409 theo `sha256`), `DELETE /api/sutras/{slug}`; trang `/sutras/new`, `/sutras/{slug}/edit`.
  - Static `sutra-edit.html` (+ phần JS trong `sutra.js`): chọn file / dán chữ, ô soạn, xem trước parse (lỗi kèm số dòng, bấm lỗi nhảy tới dòng), Lưu; menu Sửa / Xóa (hỏi xác nhận, nói rõ mất lịch sử biến) ở trang đọc; nút "Thêm bộ kinh" ở thư viện.
  - Tests mới.
- Out of scope: PDF (SR1.3); sửa từng đoạn ngay trên trang đọc; mục "Ngoài scope SR1".

## Authority / key decisions

- `docs/decisions/SR1-sutra-reader-contract.md` S2, S4 (xóa), S5, S6.
- `docs/decisions/CP8.15-community-post-contract.md` P5a (mẫu upload body thô).

## Implementation approach

- Xem trước: trang soạn gửi văn bản tới `POST /api/sutras?dry_run=1` (trả S3 hoặc lỗi, không ghi) — debounce khi gõ và trước khi Lưu.
- Fixture `.docx` sinh trong test bằng `python-docx` (heading, đoạn, ngắt mềm, chú thích, bảng), không dùng văn bản có bản quyền.

## Acceptance Criteria

1. `.txt` UTF-8 (có / không BOM) và `.docx` chuyển đúng S5; văn bản đã có `=` giữ nguyên.
2. Giới hạn: > 5 MB → 413; đuôi khác → 415; zip hỏng / giải nén > 50 MB / > 2 000 member → 422, không mở bằng python-docx.
3. `POST` tạo slug mới (chống trùng); `?dry_run=1` không ghi; lỗi parse → 400 kèm danh sách `{line, message}`; `PUT` sai `sha256` → 409; `DELETE` xóa thư mục, slug lạ → 404.
4. Trang soạn: tải file → ô soạn có văn bản S2; xem trước mục lục; Lưu chuyển sang trang đọc bộ mới.
5. Không đổi behavior Auto Short / learning / SR1.1: toàn bộ test PASS.

## Required verification

- `python -m pytest -q -n auto` — AC 1–3, 5.
- `node scripts/framework-check.mjs`.
- Manual test (dưới) — AC 4.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm security (upload file) trong web đã có auth: manual test là gate trước integration.

- [x] Thêm một bộ từ `.docx` thật trên điện thoại; sửa tiêu đề mục trong ô soạn; Lưu; đọc được.
- [x] Thêm từ `.txt`; cố ý để lỗi (nội dung ngoài mục) → báo đúng dòng.
- [x] Sửa một bộ có sẵn; xóa một bộ thử (có hỏi xác nhận).

## Result

- Manual test: HUMAN LEAD 2026-10-12 trên điện thoại (8080) — OK (SR1.4: lỗi khung trắng ở chế độ lật trang đã sửa `a8f8c07` rồi thử lại OK).

- Main changes: `sutra/importer.py` (`.txt` / `.docx` -> S2; zip kiểm trước python-docx: <= 2 000 member, <= 50 MB giải nén, phải có `word/document.xml`; heading style / dòng hoa / CHƯƠNG, PHẨM -> `#`; ngắt mềm -> dòng; bảng -> chữ từng ô; chú thích Word đọc từ `word/footnotes.xml` + `w:footnoteReference` -> `[^n]` đánh số lại theo mục, định nghĩa cuối mục; python-docx 1.2.0 không có API chú thích). `sutra/web.py`: `POST /api/sutras/import`, `POST /api/sutras` (+ `?dry_run=1`), `PUT`, `DELETE`, trang `/sutras/new` và `/sutras/{slug}/edit` (đăng ký trước `/sutras/{slug}`), JSON > 3 MB -> 413. Static `sutra-edit.html` + `initEdit` trong `sutra.js` (xem trước debounce, lỗi bấm nhảy tới dòng), nút "Thêm bộ kinh", menu Sửa / Xóa ở trang đọc. Sửa từ review SR1.1: `SutraStore._entries(strict=True)` cho đường ghi — `recitations.json` hỏng -> `SutraError` (422), không ghi đè; đọc hiển thị vẫn chịu lỗi.
- Tests: `tests/test_sutra_importer.py`, `tests/test_web_sutra_sr12.py`, thêm 2 test vào `tests/test_sutra_store.py`; bỏ `test_sr12_routes_not_present` (SR1.1). Full suite `python -m pytest -q -n auto`: 1675 passed, 1 skipped; `node scripts/framework-check.mjs`; `node --check sutra.js`. Manual test (AC 4) chưa chạy — HUMAN LEAD, sau SR1.3.
- Review: chờ ORCHESTRATOR.
- Important findings / decisions: slug `new` bị giữ chỗ (tên "New" -> `new-2`) để không che trang `/sutras/new`. `.txt` có dòng bắt đầu `#` / `@` / `~` được coi là markup S2 (không escape); `.docx` thì escape dòng bắt đầu bằng ký tự đặc biệt. Văn bản đã có dòng `=` đầu: giữ nguyên (docx: bỏ qua heading style).
- Known limitations: chú thích Word chỉ xử lý khi có `word/footnotes.xml`; endnote, text box, hộp văn bản bị bỏ; bảng lồng nhau bị bỏ; thiếu manual test trên điện thoại.
- PR: (chưa; một PR cho SR1.1–SR1.3)
