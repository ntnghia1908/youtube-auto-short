# Task: SR1.4 — Độ đậm chữ + lật trang ngang

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Human Lead: HUMAN LEAD
- Base commit / branch: sau SR1.3 / `feature/sr1-sutra-reader`
- Human Lead approval: accepted 2026-10-12 (SR1.4 rồi SR1.5, cùng PR SR1)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ phía client trang đọc, trong boundary SR1 S7 (đã ghi sửa đổi HUMAN LEAD 2026-10-12); không route / schema / dependency mới.

## Goal

Trong "Cài đặt đọc" chọn được Độ đậm chữ (Thường / Đậm vừa / Đậm) và Kiểu đọc (Cuộn dọc / Lật trang ngang như sách). Ở chế độ lật trang: mỗi trang vừa một màn hình, vuốt hoặc chạm mép để sang trang, thấy số trang; mở lại về đúng chỗ.

## Scope

- In scope: `sutra.js`, `sutra.css`, `sutra.html` (trang đọc); cài đặt lưu trong `sutra:settings`; tests web nhẹ nếu có (tĩnh: file chứa các lựa chọn).
  - Nhỏ, cùng task: thư viện sắp theo tên **bỏ dấu** (`store.list`: hiện `casefold` đẩy "Đại Thế Chí…" xuống cuối vì `Đ`).
- Out of scope: server, markup, import; tự cuộn; hiệu ứng lật trang 3D.

## Authority / key decisions

- `docs/decisions/SR1-sutra-reader-contract.md` S7 (sửa đổi SR1.4), S8 (giữ màn hình sáng vẫn chạy ở cả hai kiểu).

## Implementation approach

- Độ đậm: biến CSS `--sutra-weight` (400 / 500 / 700) trên `article`; `strong` = một bậc trên đó (tối đa 800); dùng font có sẵn của hệ thống — chấp nhận trình duyệt giả lập đậm nếu font thiếu bậc.
- Lật trang: CSS multi-column (`column-width` = chiều rộng vùng đọc, `height` = chiều cao màn hình trừ thanh công cụ) + cuộn ngang `scroll-snap`; sang trang bằng `scrollLeft`; vuốt (touch) + chạm 25 % mép trái / phải + phím ← →; số trang = `round(scrollLeft / pageWidth) + 1` / tổng; tiêu đề mục không bị cắt giữa trang (`break-inside` / `break-after: avoid` cho tiêu đề). Mục lục nhảy tới trang chứa mục.
- Giữ chỗ khi đổi cỡ chữ / độ đậm / kiểu đọc / xoay màn hình: lấy phần tử đang ở đầu khung nhìn trước khi đổi, sau khi dựng lại thì đưa phần tử đó về đầu (cuộn dọc) hoặc tới trang chứa nó (lật trang). Vị trí lưu vẫn là `{section, offset}`.
- Thanh công cụ ở chế độ lật trang: chạm giữa màn hình để hiện / ẩn.

## Acceptance Criteria

1. Ba bậc độ đậm đổi được, được nhớ; dòng `strong` vẫn nổi bật hơn chữ thường.
2. Lật trang ngang: vuốt / chạm mép / phím đều sang đúng một trang; không có chữ bị cắt ngang giữa hai trang; có số trang.
3. Đổi qua lại hai kiểu đọc, đổi cỡ chữ, xoay máy: vẫn ở đoạn đang đọc (lệch không quá một màn hình).
4. Mở lại bộ kinh ở chế độ lật trang → về đúng trang chứa vị trí đã lưu; "Tụng xong" vẫn bấm được ở trang cuối.
5. Thư viện sắp theo tên bỏ dấu ("Đại…" nằm giữa "Bát…" và "Kinh…").
6. Không dùng `innerHTML` với dữ liệu; toàn bộ test PASS.

## Required verification

- `python -m pytest -q -n auto`; `node --check src/auto_short/web/static/sutra.js`; `node scripts/framework-check.mjs`.
- Manual test (dưới) — AC 1–4.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API; manual test là điểm danh sau automated verification.

- [ ] Điện thoại: đổi 3 bậc độ đậm trên A Di Đà và Thái Thượng.
- [ ] Bật lật trang ngang: vuốt qua 10 trang, chạm mép, nhảy mục lục; xoay máy.
- [ ] Thoát ra, mở lại: đúng trang; đổi về cuộn dọc: đúng đoạn.

## Result

- Main changes: `sutra.js` / `sutra.css` / `sutra.html` — cài đặt Độ đậm chữ (400 / 500 / 700, `strong` = 700 / 700 / 800) và Kiểu đọc (Cuộn dọc / Lật trang ngang) lưu trong `sutra:settings`; chế độ lật trang = `#reader` cố định, `#text` CSS multi-column rộng đúng một trang, `scrollLeft` do JS điều khiển (vuốt, chạm 25 % mép, phím ← → / PageUp / PageDown), số trang `x / y`, chạm giữa ẩn / hiện thanh công cụ, mục lục nhảy tới trang, "Tụng xong" nằm cuối bài viết ở trang cuối; giữ chỗ (phần tử đầu khung nhìn) khi đổi cỡ / giãn dòng / độ đậm / kiểu đọc / xoay máy (resize debounce 150 ms); vị trí lưu `{section, offset}` dùng toạ độ tuyến tính (y hoặc x) nên chạy ở cả hai kiểu. `store.list` sắp tên bỏ dấu.
- Tests: `test_list_sorts_without_diacritics`, `test_reader_sr14_options_present`; toàn bộ `python -m pytest -q -n auto`: 1719 passed, 1 skipped (chạy trước khi thêm test tĩnh; hai file test liên quan sau đó 30 passed); `node --check` OK; `framework-check` PASS.
- Review: chưa.
- Important findings / decisions: lệch nhỏ so với Implementation approach: không dùng `scroll-snap` (CSS snap không áp được lên cột); chuyển trang bằng JS với `overflow: hidden`, mỗi cử chỉ đúng một trang. Không có trình duyệt headless trong môi trường nên bố cục chưa được chạy thử; cần manual test trên điện thoại.
- Known limitations: đoạn ngắn (< 200 ký tự) không bị cắt giữa hai trang, đoạn dài vẫn ngắt giữa các dòng (không cắt ngang dòng); số trang tính theo `scrollWidth` (trình duyệt khác nhau có thể lệch ± 1); giữ chỗ chính xác tới cỡ một trang.
- PR:
