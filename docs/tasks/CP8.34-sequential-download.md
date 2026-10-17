# Task: CP8.34 — Tải lần lượt nhiều file (1–3 file cùng lúc) trên trang bộ kinh

## Status / Approval

- Status: DRAFT
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `185ba20` (`main`) / `feature/cp8.34-sequential-download` (worktree `../youtube-auto-short-cp834`). **Bắt đầu sau khi PR #85 (CP8.32) và CP8.33 merge** (cả hai sửa trang bộ kinh): rebase lên `main` mới rồi mới giao IMPLEMENTER.
- Human Lead approval: pending
- Implementation authorized: NO

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: route web mới + thay đổi hành vi route tải hiện có (theo dõi tiến độ gửi), CP8.3 web contract. Không đổi dependency, security model.

## Bối cảnh (2026-10-17, ORCHESTRATOR)

- HUMAN LEAD: "Nên hỗ trợ tải tuần tự … trên điện thoại tôi chỉ tải một lần được hai video hoặc hai bản zip để đảm bảo tốc độ tải. Nếu tôi tải nhiều bản thì sẽ chậm và có thể bị mất gói. Nên có chức năng cho tải nhiều nhưng tải từ từ, mỗi lần một hai gói." Trả lời câu hỏi cùng ngày: chọn ở **trang bộ kinh**; số file cùng lúc **chọn được 1–3, mặc định 2**; lỗi → **tự thử lại 2 lần**.
- Tải hiện nay: link `<a download>` → trình duyệt / trình quản lý tải của điện thoại tải thẳng (không giữ file trong bộ nhớ trang). Zip (`shorts.zip`, `all.zip`) là `StreamingResponse` tạo lúc tải (không có `Content-Length`, không hỗ trợ Range); mp4 (bản dọc, bản ngang HD, Short) là `FileResponse`.
- Trang web **không biết** khi nào một lần tải native xong. Tải bằng `fetch` + blob thì biết, nhưng giữ cả file (có thể vài GB) trong RAM điện thoại → không dùng.

## Quyết định cần HUMAN LEAD duyệt (D1–D7)

- **D1 Chọn.** Trang bộ kinh: mỗi tập có ô tick; thanh "Tải lần lượt" chọn loại: zip (Short + khai thị như nút zip hiện có, CP8.31 D3), bản dọc cả tập, bản ngang HD (chỉ tập có loại đó; tập không có thì bỏ qua và ghi rõ). Nút nhanh: "Chọn tất cả chưa đăng" (tập còn Short / khai thị chưa tick "Đã đăng").
- **D2 Cùng lúc.** Ô chọn 1 / 2 / 3, mặc định 2; nhớ theo trình duyệt (localStorage, try/catch).
- **D3 Biết khi nào một file xong (server theo dõi).** Mỗi lần tải trang thêm `?dl=<token>` (ngẫu nhiên, do trang tạo) vào URL tải. Server ghi trong bộ nhớ (không lưu đĩa, hết hạn 6 h) cho token đó: `state` = `sending` / `done` (đã gửi byte cuối) / `aborted` (client ngắt giữa chừng), `bytes_sent`, `bytes_total` (nếu biết). Route mới `GET /api/downloads/{token}` (cùng auth). Trang hỏi mỗi 2 s; `done` → bắt đầu file tiếp theo; `aborted` hoặc không có request nào tới sau 60 s → lỗi. Route tải không có `dl` giữ nguyên hành vi.
- **D4 Thử lại.** Lỗi → tự tải lại tối đa 2 lần (token mới, chờ 5 s); vẫn lỗi → dòng đỏ + nút "Thử lại", chuyển sang file sau. Zip tạo lúc tải nên tải lại là tải từ đầu (không tải tiếp phần dở); mp4 cũng tải lại từ đầu (Range: out of scope).
- **D5 Trạng thái trên trang.** Bảng hàng đợi tải: tên file, đang chờ / đang tải (MB đã gửi / tổng nếu biết) / xong / lỗi; nút "Dừng" (không bắt đầu file mới; file đang tải thì để trình duyệt tự xong) và "Tiếp tục". Trang phải mở trong lúc tải: giữ màn hình sáng (Wake Lock như trang Đọc Kinh, nếu trình duyệt hỗ trợ) + dòng nhắc "Để trang này mở cho tới khi tải xong". Đóng / tải lại trang → hàng đợi mất (file đã xong vẫn còn trong máy).
- **D6 "Đã đăng".** Zip vẫn tick "Đã đăng" phía server như CP8.31 D1 khi request tới (tải lại cùng zip tick lại cùng file — không đổi kết quả).
- **D7 "Xong" = server gửi xong.** `done` nghĩa là server đã đẩy hết byte vào mạng, không phải điện thoại đã ghi xong file; với 1–3 file cùng lúc thì sai lệch chỉ là vài giây cuối. Trình quản lý tải của điện thoại tự gửi lại request (cùng URL, cùng token) → token tính theo request mới nhất.

## Scope

- In scope: D1–D7; module nhỏ `web/downloads.py` (bảng token, bọc stream đếm byte cho `FileResponse` / `StreamingResponse`); route `GET /api/downloads/{token}`; tham số `dl` ở các route tải zip / bản dọc / bản ngang HD; UI trang bộ kinh; pointer trong CP8.3 web contract; README dòng ngắn.
- Out of scope: tải tiếp phần dở (HTTP Range); hàng đợi tải ở trang tập / trang Yêu thích / tab khác; hàng đợi sống qua đóng trang; giới hạn băng thông phía server; tải Short lẻ, bài đăng `.docx`.

## Acceptance Criteria

1. Chọn n tập, cùng lúc k (1–3): không lúc nào có quá k file `sending`; file sau chỉ bắt đầu khi một file trước `done` / lỗi.
2. `?dl=<token>`: state `sending` → `done` khi gửi hết; client ngắt giữa chừng → `aborted`; token lạ → 404; không cookie → 401. Không có `dl` → byte gửi đi giống hệt trước (zip / mp4).
3. Lỗi → tự thử lại đúng 2 lần rồi báo lỗi + "Thử lại"; các file khác vẫn tiếp tục.
4. Loại không có ở một tập (vd chưa có bản dọc) → bỏ qua, ghi rõ trong bảng.
5. "Dừng" / "Tiếp tục" đúng D5; số cùng lúc nhớ qua lần mở trang sau.
6. Zip qua hàng đợi vẫn tick "Đã đăng" như tải bằng nút thường.
7. Toàn bộ suite PASS; route tải cũ không đổi hành vi.

## Required verification

- `python -m pytest -q -n auto` — PASS (test mới `tests/test_web_downloads*.py` cho AC 1–7; phần JS kiểm logic hàng đợi qua test API + một test hàm thuần nếu tách được).
- `node scripts/framework-check.mjs` — PASS.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API (route mới + tham số mới ở route tải, cùng auth); không chạm database, security model. Manual test trên điện thoại (8080 ghim commit nhánh) là gate trước integration.

- [ ] Trên điện thoại: chọn 6 tập zip, cùng lúc 2 → luôn chỉ 2 file đang tải, đủ 6 file, mở được.
- [ ] Tắt Wi-Fi giữa chừng một file → tự thử lại, rồi báo lỗi nếu vẫn mất mạng; bật lại → "Thử lại" được.
- [ ] Bản dọc cả tập (file lớn) qua hàng đợi, cùng lúc 1.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
