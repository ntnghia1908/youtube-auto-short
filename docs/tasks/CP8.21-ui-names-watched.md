# Task: CP8.21 — Khai thị layout cũ, tên file / title có mã, "Đã xem", gọn thẻ video

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `c2007c6` (`main`) / `feature/cp8.21-ui-names` (worktree `../youtube-auto-short-cp821`)
- Human Lead approval: APPROVED (HUMAN LEAD 2026-10-03, nguyên bản; yêu cầu mục 1–6, Q1–Q4 cùng ngày)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi CP7 render contract (layout riêng cho khai thị), CP8.3 web contract (tên file tải về, text Copy, state "Đã xem" mới), giao diện web.

## Goal

1. Video khai thị dùng lại layout trước CP8.14; Short giữ layout V16.
2. Trang "Bài đăng": khai thị có nút "Xem Khai thị" thay cho "Xem Short".
3. Tên file tải về và title Copy (đăng YouTube) có mã tập / số thứ tự; title trong video không đổi.
4. Nút "Đã xem" trên thẻ video trang tập, tự tick khi xem hết.
5. Ẩn "Sửa đầu/cuối" và "Từ điển sửa lỗi".
6. Thẻ video trang tập gọn hơn: nút dạng icon.

## Scope

- In scope:
  - **D1 Khai thị layout cũ.** Episode khai thị (`kind` khai thị, CP8.9) render bằng layout trước CP8.14 (`deaf736^`): khối header + video + title căn giữa dọc, title dưới video, kích thước mặc định như trước CP8.14. Short: không đổi gì (layout V16, cùng hash render → không Short nào stale). Khai thị đã render: không tự render lại; chỉ đổi khi tập được chạy lại / tập mới (Q3). Cách cấu hình (hằng số hay mục config riêng cho khai thị) do IMPLEMENTER đề xuất trong plan, giữ nguyên key `[render]` hiện có.
  - **D2 "Xem Khai thị".** Trang Bài đăng: thẻ của khai thị ghi "Xem Khai thị"; Short giữ "Xem Short".
  - **D3 Tên có mã (Q1).**
    - File tải về: Short `T<tập>_S<NN>_<title>.mp4`; khai thị `T<tập>_TK<NN>_<title>.mp4` (thay `Tập<tập>_S<NN>` / `Tập<tập>_KT<NN>` của CP8.5 X1 / CP8.9 K8). `<tập>`, `<NN>`, làm sạch, cắt độ dài: như hiện tại (`review/names.py`). Không title → `T<tập>_S<NN>.mp4`.
    - Text nút Copy (title YouTube): Short `T<tập>_S<NN>_<title> #tag…`; khai thị `Khai Thị: T<tập>_TK<NN>_<title> #tag…`. Giới hạn 100 ký tự giữ nguyên: bớt hashtag từ cuối, không cắt title (luật hiện có).
    - Tên zip (CP8.17 D4): không đổi. Tên file trong zip theo tên mới.
    - Title vẽ trong video, `titles.json`, tên file trên đĩa: không đổi.
  - **D4 "Đã xem" (Q2).** Lưu ở server như "Đã đăng" (user state, không job, không làm stale render): ví dụ thêm vào `publish.json` hoặc file riêng trong `work/<id>/` — IMPLEMENTER đề xuất, giữ tương thích file cũ (thiếu field = chưa xem). Thẻ video trang tập có ô "Đã xem" cạnh "Đã đăng"; tự tick khi `<video>` phát tới hết (`ended`), một lần; bỏ tick tay được; bật "Lặp lại" vẫn tick ở lần hết đầu tiên. Re-render (file khác `sha256`) → hiện "đã xem bản cũ" giống "Đã đăng". Chỉ trang tập (không trang Bài đăng).
  - **D5 Ẩn (Q4).** Ẩn nút "Sửa đầu/cuối" (CP9) và "Từ điển sửa lỗi" (CP8.18) trên giao diện; code và API giữ nguyên; bật lại bằng một khóa config (mặc định ẩn). Từ điển đã có vẫn được áp dụng khi soạn bài như hiện tại. "Thêm Short" (CP9) giữ nguyên.
  - **D6 Thẻ video gọn.** Trên thẻ video trang tập: "Tải về" → icon mũi tên tải xuống, "Xóa" → icon thùng rác, "Lặp lại" → icon vòng xoay (trạng thái bật thấy rõ). Mỗi icon có `title` + `aria-label` bằng chữ cũ; vùng bấm ≥ 40 px trên điện thoại. Icon inline SVG / ký tự, không thêm dependency. Hành vi (tải về, xác nhận xóa, lặp) không đổi.
  - Cập nhật authority: CP7 render contract (layout khai thị), CP8.3 web contract (tên file, Copy, "Đã xem", ẩn nút), CP8.9 nếu nhắc tên `KT<NN>`; README / config example nếu có khóa mới.
- Out of scope: đổi layout Short; render lại tập cũ; đổi tên zip; đổi title trong video; "Đã xem" ở trang Bài đăng; xóa code CP9 / CP8.18; upload YouTube (CP8.4 bỏ qua).

## Authority / key decisions

- HUMAN LEAD 2026-10-03: CP8.20 không đổi title / điểm cắt; yêu cầu mục 1–6 của task này.
- Q1: format `T29_S01_…` / `T29_TK01_…`, title khai thị có tiền tố `Khai Thị: `. Q2: "Đã xem" lưu server, thẻ video trang tập. Q3: khai thị cũ không tự render lại. Q4: ẩn nút, giữ code.
- `docs/decisions/CP7-render-contract.md` R4; `docs/decisions/CP8.3-web-contract.md` (§ Tên file tải về, § Đã đăng); `docs/decisions/CP8.9-khai-thi-contract.md` K8; CP8.14 contract (layout V16 chỉ còn áp cho Short).

## Implementation approach

- Render: chọn hàm layout theo kind của episode; hash render của khai thị đổi, của Short giữ nguyên (test chứng minh).
- `review/names.py`: `download_name` / `copy_text` nhận tiền tố mới; tests cập nhật theo contract mới (không sửa test để che lỗi).
- "Đã xem": API kiểu "Đã đăng" (POST tick / untick), JS nghe `ended`.
- Ẩn nút: cờ trong payload / config đọc ở JS.

## Acceptance Criteria

1. Khai thị mới render ra layout trước CP8.14 (title dưới video, khối căn giữa); Short render ra đúng layout V16 với hash render không đổi so với `c2007c6` (test).
2. Trang Bài đăng: khai thị hiện "Xem Khai thị", Short hiện "Xem Short".
3. Tên file tải về và text Copy đúng format D3 cho Short và khai thị (gồm trường hợp không title, title dài, hashtag bị bớt vì tiền tố); tên file trong zip theo tên mới; tên zip không đổi.
4. "Đã xem": tick tay / bỏ tick, tự tick khi xem hết, lưu server (tải lại trang / máy khác thấy), file cũ không có field vẫn đọc được, re-render → "đã xem bản cũ"; không tạo job, không làm stale stage nào.
5. "Sửa đầu/cuối" và "Từ điển sửa lỗi" không hiện với config mặc định; bật khóa config thì hiện và chạy như cũ.
6. Thẻ video dùng icon tải về / thùng rác / vòng xoay, có `title` + `aria-label`, hành vi không đổi.
7. Authority docs cập nhật khớp hành vi mới.
8. `python -m pytest -q -n auto` PASS; `node scripts/framework-check.mjs` PASS.

## Required verification

- `python -m pytest -q -n auto` — AC 1, 3, 4, 5, 8 (tests mới cho layout khai thị + hash Short, names, "Đã xem" API/storage, cờ ẩn).
- `node scripts/framework-check.mjs` — AC 7, 8.
- Server test 8081 trên bản sao dữ liệu (`~/.cache/auto-short-cp821-test/`, không ghi `work/` / `output/` chính): render 1 khai thị mẫu + kiểm UI AC 2, 4, 5, 6 bằng HTTP / trình duyệt; ảnh khung khai thị trước / sau để HUMAN LEAD xem.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database hay security model. Chạm web API nội bộ (thêm endpoint "Đã xem") — manual test là gate trước merge.

- [ ] Xem khai thị mẫu layout cũ (điện thoại).
- [ ] Trang Bài đăng: "Xem Khai thị".
- [ ] Tải Short + khai thị: tên file đúng; Copy title đúng.
- [ ] Xem hết một video → "Đã xem" tự tick; tải lại trang vẫn tick; bỏ tick được.
- [ ] Không thấy "Sửa đầu/cuối", "Từ điển sửa lỗi".
- [ ] Thẻ video: icon gọn, bấm được trên điện thoại, xóa vẫn hỏi xác nhận.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
