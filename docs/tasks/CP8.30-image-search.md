# Task: CP8.30 — Tìm ảnh theo từ khóa → duyệt → thêm vào thư viện; chia lại ảnh cho bài chưa đăng

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `abd6704` (`main`) / `feature/cp8.30-image-search` (worktree `../youtube-auto-short-imgsearch`)
- Human Lead approval: APPROVED 2026-10-04 ("A+B" — nguồn A Google Programmable Search + B các trang đã biết; phạm vi ORCHESTRATOR đề xuất cùng ngày)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm dịch vụ ngoài (Google API, khóa bí mật), mở rộng P5 / P5b / P13 của `docs/decisions/CP8.15-community-post-contract.md` (canonical owner — sửa decision), thao tác hàng loạt lên `posts.json`.

## Bối cảnh (2026-10-04)

ORCHESTRATOR làm tay: tìm ảnh Hòa thượng Tịnh Không / A Di Đà / Tịnh Độ / Tây Phương Tam Thánh từ niemphatanvui.vn (bộ sưu tập `/bo-suu-tap-hinh-phat-chat-luong-cao/<slug>` + trang con `/hinh-phat-chat-luong-cao/<slug>-NN`, ảnh `cdn.prod.website-files.com/...{jpg,jpeg,png}`, bỏ biến thể `-p-NNN`), ph.tinhtong.vn (`/images/LoatAnhKyNiemChangDuong60NamHoangPhap/ImageNNN.jpg`), amtb-m.org.my, sachphat.net, hwadzan.com; lọc kích thước (P5a ≥ 600 px), trùng sha256, nhìn tay để bỏ ảnh trùng gần / chữ / banner; thêm vào thư viện (25 → 129 ảnh) và chia lại ảnh cho 771 bài chưa đăng (least-used, không trùng trong một tập, bài đã đăng giữ nguyên). HUMAN LEAD muốn việc này thành chức năng.

## Goal

Tab Bài đăng → Thư viện ảnh: (1) "Tìm ảnh theo từ khóa": nhập từ khóa → hệ thống tìm (nguồn B, và A nếu có khóa API) → tải, lọc → lưới ứng viên → HUMAN LEAD tick chọn → "Thêm vào thư viện"; (2) "Chia lại ảnh cho bài chưa đăng".

## Scope

- In scope:
  - **S1 Nguồn B (trang đã biết).** Bộ "nguồn" khai báo được (config `[post] image_sources` hoặc file trong `image_dir`, mặc định: các bộ sưu tập niemphatanvui.vn + mẫu trang con, loạt ảnh ph.tinhtong.vn, các trang hwadzan / amtb-m / sachphat đã biết): khớp từ khóa với tên / tiêu đề bộ sưu tập (bỏ dấu, so từ), lấy ảnh từ trang khớp; giới hạn số trang / ảnh mỗi lần tìm.
  - **S2 Nguồn A (Google Programmable Search JSON API, tìm ảnh).** Bật khi có khóa + Search Engine ID qua biến môi trường (không lưu trong repo / `config.toml` — như token enhance); không có khóa → chỉ B, UI ghi rõ. Giới hạn lượt (mặc định ≤ 100 / ngày, đếm trong file trạng thái). IMPLEMENTER kiểm tình trạng hiện hành của API (còn nhận khách mới / thay thế nếu bị ngừng) và ghi vào Result; nếu API không dùng được, giao diện nguồn vẫn tách để thay sau.
  - **S3 Tải + lọc.** Tải theo luật P13 hiện có (`post/fetch.py`: host công khai, redirect, giới hạn dung lượng); kiểm P5a (JPEG / PNG, ≥ 600 px); bỏ trùng sha256 với thư viện và trong lô; **bỏ trùng gần** (perceptual hash / dHash trên ảnh thu nhỏ — stdlib + ffmpeg đã có, không thêm dependency; ngưỡng ghi Result); đánh dấu (không tự bỏ) ảnh nghi chữ / banner nếu nhận được rẻ. Ứng viên lưu tạm (thư mục riêng ngoài thư viện, tự dọn sau N giờ).
  - **S4 Job + UI.** Job `image_search` (làn `prepare`, như `post_search` P5b) — tiến độ; lưới ứng viên (ảnh thu nhỏ, kích thước, nguồn, nhãn nghi chữ), tick chọn / chọn tất cả, "Thêm vào thư viện" (đặt tên tiếp số, ghi `sources.tsv` 2 cột `tên<TAB>url`).
  - **S5 Chia lại ảnh.** Nút + route: bài chưa đăng (`posted_at` rỗng) nhận ảnh least-used (đếm cả bài đã đăng), không trùng trong cùng video (Short + `.kt`), xáo trộn ổn định; bài đã đăng giữ nguyên; không làm bài thành stale; dưới `post_lock`; hỏi xác nhận (số bài sẽ đổi); sao lưu `posts.json` trước khi ghi (thư mục backup, giữ vài bản).
  - Sửa decision CP8.15 (P5, P5b, P13 + P5c tìm theo từ khóa, P5d chia lại), README / hướng dẫn.
  - Test (không mạng: opener giả, HTML mẫu, ảnh tổng hợp nhỏ; Google API giả).
- Out of scope: Facebook / trang cần đăng nhập; sửa ảnh (cắt / chèn chữ); tự thêm không cần duyệt; nguồn C (cào trang kết quả DuckDuckGo / Bing).

## Authority / key decisions

- `docs/decisions/CP8.15-community-post-contract.md` P5 / P5a / P5b / P13 (sửa); `docs/tasks/CP8.15-community-post.md`; `docs/tasks/CP8.16-post-tab-auto.md` (khóa job `post`).
- K1: khóa API chỉ qua env (`AUTO_SHORT_GOOGLE_CSE_KEY`, `AUTO_SHORT_GOOGLE_CSE_CX` hoặc tên IMPLEMENTER chọn — ghi decision), không log / không trả về UI.
- K2: không thêm dependency Python.

## Acceptance Criteria

1. Từ khóa "Tây Phương Tam Thánh" (nguồn B, HTML mẫu thu gọn từ niemphatanvui) → ứng viên đúng bộ sưu tập; ảnh < 600 px, trùng sha256, trùng gần (cùng ảnh khác cỡ) bị bỏ, có số lượng bỏ theo lý do.
2. Nguồn A với API giả: có khóa → gọi đúng tham số tìm ảnh, gộp với B; không khóa → chỉ B; vượt hạn lượt → báo rõ.
3. Chọn 3 ứng viên → "Thêm" → 3 file mới đúng tên tiếp số, `sources.tsv` 2 cột; ứng viên không chọn không vào thư viện; bấm lại không thêm trùng.
4. Chia lại: bài đã đăng không đổi; bài chưa đăng phủ ảnh đều (chênh tối đa nhỏ), không trùng trong một video; `stale` không đổi; có bản sao lưu; job post đang chạy → 409 / đợi.
5. Tải tuân P13 (host nội bộ / redirect lạ bị chặn) — test.
6. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–6.
- `node scripts/framework-check.mjs`.
- Chạy thật trên server test 8081 (bản sao thư viện + vài tập, không đụng 8080 / thư viện thật): tìm "A Di Đà Phật" (nguồn B) — số ứng viên, số bị bỏ theo lý do, ảnh chụp lưới; Google: chỉ khi HUMAN LEAD cấp khóa (nếu không, ghi chưa kiểm).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model web (khóa API mới chỉ qua env). Điểm danh trên 8080: tìm một từ khóa, chọn vài ảnh, thêm; bấm chia lại; (tùy) nhập khóa Google rồi tìm lại.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
