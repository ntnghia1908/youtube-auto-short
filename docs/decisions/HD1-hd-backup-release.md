# HD1 — Sao lưu bản HD / dọc ra máy ngoài, giải phóng VM, lấy lại nguồn HD từ YouTube

| Metadata | Value |
|---|---|
| Status | ACCEPTED — HUMAN LEAD 2026-10-24 "duyệt đề xuất HD1 nhưng đổi … HD Dọc chuyển thành HD Mobile" (sửa G6) |
| Authority | HUMAN LEAD 2026-10-24: tải hết bản ngang HD + dọc Kinh Địa Tạng về máy 3090 rồi dọn ổ VM; "script tải mới tự check có bản dọc nào rồi để xóa luôn"; Short / khai thị làm sau từ bản HD đã upload YouTube — chọn cách **B** (gắn video HD đã upload vào tập cũ, giữ transcript / AI) |
| Change class | S2 (sửa artifact `source_hd` + "render dùng nguồn HD" của `CP13.1-enhance-worker-contract.md` E5 / E6; luật dọn / archived của `CP8.3-web-contract.md` CP8.6; thêm route web) |
| Integration | Push / PR / merge vẫn cần HUMAN LEAD duyệt riêng |

## 1. Vấn đề

Ổ VM 95 % (còn 28 GB). `source_hd.mp4` (117 file, 243 GB) và `output/<id>/full/vertical.mp4` (101 file, 81 GB) không có cách dọn: "Dọn video nguồn" (CP8.6, `POST /api/episodes/{id}/archive`) chỉ xóa `source.*`. Xóa tay `source_hd.mp4` thì: render key (E6) đổi → Short / khai thị coi là cũ, có thể tự render lại từ bản gốc; enhance có thể xếp lại tập (≈ 6 h / tập); bản dọc dựng lại từ bản gốc chất lượng thấp.

Script `kdt-backup.ps1` (máy 3090, sinh bởi `~/.local/share/auto-short/backup/make-kdt-backup.py`, ngoài git) đã tải bản HD ngang + dọc về `D:\KinhDiaTang_HD` và kiểm sha256 với bảng của VM.

## 2. Đề xuất (G1–G7)

- **G1 Xác nhận sao lưu bằng sha256**: route `POST /api/episodes/{id}/backup` thân `{kind: "hd" | "vertical", sha256}` (cookie như mọi API). VM chỉ nhận khi `sha256` **bằng sha của file hiện có trên VM** (HD: `enhance.json source_hd_sha256` + kích thước khớp; dọc: sha của `vertical.mp4`, tính một lần, cache theo kích thước + mtime). Ghi `work/<owner>/backup.json` (`kind`, `sha256`, `size`, `confirmed_at`). Không có route nào nhận "đã tải" mà không có sha.
- **G2 Giải phóng ("Đã chuyển ra máy ngoài")**: route `POST /api/episodes/{id}/release` xóa `source_hd.mp4` và `full/vertical.mp4` của video, **chỉ khi** cả hai file (cái nào đang có) đã xác nhận ở G1 với đúng sha hiện tại, không có job / vertical job / lease enhance đang chạy. Tập chưa có bản dọc → từ chối (tạo bản dọc trước — giữ chất lượng HD), trừ khi gửi `allow_no_vertical: true`. Ghi `released_at` + sha đã xóa vào `backup.json`. Không đụng transcript, AI, `titles` / `clips`, Short đã render, bài đăng, theme index, thumbnail, cờ "Đã đăng".
- **G3 Trạng thái sau khi giải phóng** (sửa E5 / E6): `enhance.json` giữ `state: done` + `source_hd_sha256`, thêm `released: true` → (a) Short / khai thị đã render **không** thành cũ, không tự render lại; (b) enhance không xếp lại tập; (c) web hiện "HD đã chuyển ra máy ngoài" thay link tải HD / dọc; (d) `effective_source` trả "cần lấy lại" (G5) thay vì rơi về bản gốc im lặng.
- **G4 Gắn video HD đã upload (cách B)**: trên trang bộ kinh, HUMAN LEAD dán link **playlist YouTube chứa bản HD đã upload**. VM đọc danh sách bằng yt-dlp (như ingest, không OAuth): ghép theo "Tập N" trong tiêu đề **và** thời lượng khớp tập cũ (≤ 1 s; enhance giữ đúng số khung, CP13.1). Ghi `work/<owner>/hd_link.json` (`youtube_id`, `duration`, `linked_at`). Không khớp / trùng → không gắn, liệt kê để HUMAN LEAD xem. Có nút gỡ / gắn tay từng tập (dán link video, vẫn kiểm thời lượng).
- **G5 Lấy lại nguồn HD khi cần**: job cần nguồn cho tập `released` (render Short / khai thị mới hoặc làm lại, bản dọc, ghép chủ đề) tải `hd_link.youtube_id` (chất lượng cao nhất ≤ 1080p) vào `work/<owner>/source_hd_yt.mp4`, kiểm thời lượng, dùng xong xóa (như tải lại bản gốc của tập archived, CP8.32 K2). Render key dùng sha của file tải về → Short mới là bản mới; Short cũ giữ nguyên. Chưa gắn link → job dừng với thông báo "HD đã chuyển ra máy ngoài — gắn link bản HD trên YouTube hoặc render bằng bản gốc" (nút "Render bằng bản gốc" như E6). Bản tải từ YouTube đã nén lại một lần (chấp nhận được cho Short).
- **G6 Script 3090**: `kdt-backup.ps1` thêm bước cuối: với mỗi file đã kiểm sha khớp (kể cả file có sẵn nhận qua `-Have`), gọi G1; rồi in danh sách tập đủ điều kiện G2 cùng dung lượng sẽ giải phóng, hỏi **một lần** "Giải phóng N tập (X GB) trên VM? (y/N)" → gọi G2. Cờ `-Release` bỏ câu hỏi (chạy qua đêm), `-NoRelease` chỉ xác nhận. Generator + template chuyển vào repo `scripts/backup/` (tham số playlist, không cố định Kinh Địa Tạng); bảng sha vẫn sinh từ VM. **Tên file bản dọc: `[HD Mobile] <bộ kinh> - Tập N.mp4`** (thay `[HD Dọc]`, HUMAN LEAD 2026-10-24); ảnh kèm `[HD Mobile] … .jpg`; script tự đổi tên file `[HD Dọc]` cũ trong thư mục đích (giữ sha đã kiểm). Bản ngang giữ `[HD] …`.
- **G7 Dependency / security**: không thêm dependency (yt-dlp, curl có sẵn). Route mới sau cookie, kiểm regex id như route hiện có, chỉ xóa đúng hai đường dẫn cố định trong `work/<owner>/` và `output/<owner>/full/`; nhật ký trong `backup.json`. Không mở port mới.

- Hệ quả cho PUB2 (PR #141, G2 ghép theo tên file upload): nhận cả `[HD Mobile]` lẫn `[HD Dọc]` (video đã upload trước khi đổi tên) — sửa trong PUB2, không trong HD1.

## 3. Ngoài scope

Xóa tự động không cần sha; dọn Short / khai thị đã render; upload YouTube (vẫn tay; PUB2 chỉ gắn thumbnail); tự tìm playlist HD; khôi phục `source_hd.mp4` từ 3090 lên VM (cách C — có thể làm sau, G5 chừa chỗ cho nguồn khác).

## 4. Thứ tự làm khi được duyệt

1. HD1a: G1 + G2 + G3 + G6 (đủ để tải và dọn Kinh Địa Tạng ngay).
2. HD1b: G4 + G5 (cần trước khi làm lại Short / khai thị từ bản HD đã upload).
