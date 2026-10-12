# Task: SR2.1 — Thư viện Khai thị (đọc bài đăng theo bộ kinh, nhóm 10 tập)

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Human Lead: HUMAN LEAD
- Base commit / branch: `a8f8c07` / `feature/sr1-sutra-reader` (cùng PR SR1)
- Human Lead approval: accepted 2026-10-12 (SR2 K-a–K-d)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: API mới đọc dữ liệu Auto Short cho ứng dụng Đọc Kinh (xuyên hai ứng dụng trong host), ghi trạng thái "Đã đăng bài" từ trang mới.

## Goal

Thư viện có tab "Khai thị": chọn bộ kinh → nhóm "Tập 1–10"… → đọc toàn bộ bài đăng (Short + khai thị) của các tập đó bằng trang đọc SR1 (cỡ chữ, nền, lật trang, mục lục theo tập); mỗi bài có nút Copy để đăng, copy xong tự tick "Đã đăng bài". Tab Bài đăng không đổi.

## Scope

- In scope: API K2 (phía host, dùng lại helper `.docx` CP8.31); route trang `/sutras/khaithi/{playlist_id}`; `sutras.html` hai tab; `sutra.js` / `sutra.css`: nguồn dữ liệu khai thị, ẩn đếm biến, nút Copy + tick; tests; pointer CP8.15 (P8 có thêm nơi gọi) và project-profile.
- Out of scope: mục "Ngoài scope SR2"; đổi `posts.json`, tab Bài đăng, soạn bài, `.docx`.

## Authority / key decisions

- `docs/decisions/SR2-khaithi-library-contract.md` K1–K3.
- `docs/decisions/CP8.15-community-post-contract.md` P4, P7, P8, P16; `docs/decisions/SR1-sutra-reader-contract.md` S3, S7.

## Implementation approach

- Tách phần dựng dữ liệu của `_export_group` / `_export_episode` thành hàm dùng chung (không đổi kết quả `.docx`: test `.docx` hiện có phải PASS nguyên trạng), thêm `episode_id`, `clip_id`, `copy_text` (cùng hàm tạo `text` của `_post_entry_view`), `posted`, `stale`.
- Copy trên HTTP: dùng lại cách dự phòng của `app.js` (`copyText`), chép sang `sutra.js` (không import chéo file tĩnh).

## Acceptance Criteria

1. `GET /api/reading/khaithi` liệt kê bộ có bài + nhóm 10 tập + "Video lẻ"; số bài đúng.
2. `GET /api/reading/khaithi/{id}?from=&to=` trả S3 + trường K2; thứ tự tập / bài như `.docx`; 404 / 422 đúng K2; chưa đăng nhập 401.
3. Trang đọc khai thị dùng được mọi cài đặt SR1 (kể cả lật trang), không hiện đếm biến; nhớ vị trí theo khóa K3.
4. Copy → clipboard có đúng text như tab Bài đăng; bài chuyển "Đã đăng ✓"; tab Bài đăng thấy tick.
5. `.docx` và tab Bài đăng không đổi (test cũ PASS); toàn bộ test PASS.

## Required verification

- `python -m pytest -q -n auto`; `node --check` JS; `node scripts/framework-check.mjs`.
- Manual test (dưới).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Thêm API đọc + một nơi gọi route ghi có sẵn (sau auth): manual test là gate trước integration.

- [ ] Điện thoại: tab Khai thị → bộ Vô Lượng Thọ → "Tập 1–10": đọc, mục lục theo tập, lật trang.
- [ ] Copy một bài → dán vào ứng dụng ghi chú đúng nội dung; tab Bài đăng của tập đó đã tick "Đã đăng bài".
- [ ] Sửa một bài ở tab Bài đăng → mở lại thư viện thấy chữ mới.

## Result

- Main changes: `web/app.py` — `_export_group` / `_export_episode` tách thành `_export_items` / `_export_data` (dùng chung `.docx` và API; `.docx` không đổi), `_pick_range` (chọn tập theo `from`/`to`/`other`, dùng chung `.docx`), `GET /api/reading/khaithi`, `GET /api/reading/khaithi/{playlist_id}`, trang `/sutras/khaithi/{playlist_id}` (đăng ký trước router `sutra`). `web/reading.py` — hàm thuần (nhóm 10 tập, sách S3). `sutra.js` / `sutra.css` / `sutras.html` — tab Đọc Kinh | Khai thị (nhớ tab), nguồn khai thị, nút Copy + "Đã đăng ✓", nhãn "Short đã đổi", khóa vị trí `sutra:pos:kt:<id>:<from>-<to>|other`. Pointer CP8.15 P8 + project-profile.
- Tests: `tests/test_web_sr21.py` (13 test); `tests/test_web_cp831.py` + `test_web_sutra_sr1*.py` PASS nguyên trạng. Toàn bộ: `python -m pytest -q -n auto` 1750 passed, 1 skipped. `node --check sutra.js` OK; `node scripts/framework-check.mjs` `framework-check` PASS.
- Review: chưa.
- Important findings / decisions: (1) `copy_text` dùng title của titling như tab Bài đăng (khi titling không đọc được, tab Bài đăng không có title, thư viện cũng không; tiêu đề mục vẫn lấy fallback từ render manifest như `.docx`). (2) "Video lẻ": tập Short không thuộc bộ nào có bài, ngày tạo = `started_at` sớm nhất của manifest (dự phòng mtime), vị trí 1 = mới nhất, nhóm `from`/`to` theo vị trí. (3) Vị trí đọc khai thị lưu thêm `clip` (`episode_id/clip_id`) để khôi phục đúng bài khi số bài đổi.
- Known limitations: "Video lẻ" đánh số theo vị trí mới nhất trước nên khi có tập lẻ mới, nhóm và vị trí đã lưu dịch đi; mã mục `s<n>` đổi khi thêm bài (đã bù bằng `clip`). Chưa thử trên điện thoại / clipboard HTTP thật (manual test). Copy dùng bản chép của `app.js`.
- PR: chưa (không push theo yêu cầu).
