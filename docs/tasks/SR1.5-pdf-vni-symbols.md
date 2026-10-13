# Task: SR1.5 — Import: font VNI cũ, bỏ ký hiệu pháp khí, văn bản không có tiêu đề mục

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Human Lead: HUMAN LEAD
- Base commit / branch: sau SR1.4 / `feature/sr1-sutra-reader`
- Human Lead approval: accepted 2026-10-12 (SR1.4 rồi SR1.5, cùng PR SR1)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: mở rộng thuật toán S5a trong `sutra/pdf.py` (đã ghi sửa đổi trong decision record), không dependency / route / schema mới.

## Goal

Import PDF soạn bằng font VNI (VNI-Times…) ra chữ Unicode đúng; ký hiệu pháp khí / nhịp của sách nghi thức không còn lẫn vào chữ hay thành tiêu đề giả.

## Scope

- In scope: `sutra/pdf.py` (bảng đổi VNI-Windows → Unicode, nhận font, lọc ký hiệu, cảnh báo đoạn dạng bản nhạc), tests, số đo trên PDF thật.
  - `sutra/importer.py`: văn bản (`.txt` / `.docx` / `.pdf`) không nhận được dòng tiêu đề mục nào → tự chèn `# <tên bộ>` ngay sau dòng `=` (kèm cảnh báo) thay vì để ô soạn báo lỗi "nội dung nằm ngoài mục" (gặp 2026-10-12 với `.docx` Đại Thế Chí, Bát Đại Nhân Giác).
- Out of scope: TCVN3 / VISCII (chỉ ghi cảnh báo nếu phát hiện), dựng lại bài in dạng bản nhạc, OCR.

## Authority / key decisions

- `docs/decisions/SR1-sutra-reader-contract.md` S5a (mục "Font VNI cũ").
- Tham chiếu: bộ đổi VNI ORCHESTRATOR dùng một lần cho bản A Di Đà Hán Việt (`vni.py`, `pdf2sutra_vni.py` trong scratchpad session 2026-10-12; ORCHESTRATOR đưa đường dẫn khi giao).

## Acceptance Criteria

1. Đổi đúng mọi tổ hợp VNI: nguyên âm + mũ / trăng / móc + 5 dấu thanh, chữ hoa / thường, `ñ/Ñ`, `ô ö`, `æ ó ò î` …; chữ Unicode sẵn (font không phải VNI) không bị đổi.
2. Một chữ VNI bị tách hai đoạn chữ vẫn đổi đúng.
3. Đoạn / dòng chỉ gồm ký hiệu pháp khí bị bỏ; không sinh tiêu đề `#` từ ký hiệu.
4. PDF A Di Đà Hán Việt (HUMAN LEAD gửi 2026-10-12): mục "PHẬT THUYẾT A DI ĐÀ KINH" ra chữ Unicode đúng, không còn chuỗi kiểu `PHAÄT`; `markup.parse` OK; số đo ghi vào S5a. 4 PDF cũ không kém đi (so số đo SR1.3).
5. `.docx` / `.txt` không có tiêu đề mục → văn bản trả về parse được, có đúng một mục mang tên bộ.
6. Toàn bộ test PASS.

## Required verification

- `python -m pytest -q -n auto`; `scripts/sutra_pdf_measure.py` trên 5 PDF; `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API; điểm danh sau automated verification.

- [x] Thêm lại A Di Đà Hán Việt từ PDF trên web (bộ thử, rồi xóa): chữ đúng dấu, không còn ký hiệu.

## Result

- Manual test: HUMAN LEAD 2026-10-12 trên điện thoại (8080) — OK (SR1.4: lỗi khung trắng ở chế độ lật trang đã sửa `a8f8c07` rồi thử lại OK).

- Main changes: `sutra/vni.py` (mới; bảng VNI-Windows → Unicode NFC); `sutra/pdf.py` (`Run.font` từ `/BaseFont`, `font_kind` symbol / vni / tcvn, gộp đoạn VNI liền nhau rồi mới đổi, thay đoạn ký hiệu bằng dấu cách, giữ `O` sát chữ và `•` đầu dòng thường, cảnh báo mục dạng bản nhạc, cảnh báo font TCVN3 / VISCII); `sutra/importer.py` (`_ensure_section`: văn bản không có `#` / `@` mà có nội dung → chèn `# <tên bộ>` + cảnh báo); decision record S5a "Số đo SR1.5" + làm rõ; dòng `sutra/` của `docs/ai/project-profile.md`.
- Tests: `tests/test_sutra_vni.py` (5: bảng đầy đủ nguyên âm × dấu × hoa / thường, NFC), `tests/test_sutra_pdf.py` (+9: font_kind, VNI vs font Unicode, chữ VNI tách hai đoạn, ký hiệu, `O`, gạch đầu dòng, không tiêu đề giả từ ký hiệu, cảnh báo bản nhạc, `page_runs` mang tên font), `tests/test_sutra_importer.py` (+3: docx / txt không tiêu đề, văn bản giữ nguyên). Full suite `python -m pytest -q -n auto`: 1737 passed, 1 skipped; `node scripts/framework-check.mjs`: PASS. Số đo 5 PDF: decision record S5a "Số đo SR1.5" (4 PDF cũ: văn bản giống hệt SR1.3; A Di Đà Hán Việt: 25 mục, không còn chuỗi mã VNI; 2 `.docx` không tiêu đề: parse OK, một mục mang tên bộ).
- Review: chưa.
- Important findings / decisions: (1) cảnh báo "bản nhạc" dùng ngưỡng ≥ 30 % từ một chữ cái (không phải 1–2 chữ cái): ngưỡng 1–2 chữ cái báo nhầm chú Đại Bi (âm tiết hai chữ); (2) `•` đầu dòng ở font thường được giữ vì Vô Lượng Thọ dùng làm gạch đầu dòng (bỏ hẳn làm 4 PDF cũ kém đi); (3) `O` đơn lẻ chỉ bị bỏ khi không sát chữ liền kề; (4) đoạn ký hiệu thay bằng dấu cách thay vì xóa hẳn để hai chữ hai bên không dính nhau.
- Known limitations: bài in dạng bản nhạc vẫn rời rạc và còn tiêu đề giả (`Y Y Y`, `TIẾP` / `DẪN` / `NGUYỆN`) — chỉ cảnh báo 4 mục; TCVN3 / VISCII chỉ cảnh báo; mục bản nhạc có nốt rải ít chữ một chữ cái có thể không bị cảnh báo; `•` đầu dòng trong bản nhạc vẫn còn.
- PR:
