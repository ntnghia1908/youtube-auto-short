# PUB2 — Gắn thumbnail cho video đã upload tay qua YouTube Data API

| Metadata | Value |
|---|---|
| Status | ACCEPTED — HUMAN LEAD 2026-10-24 ("Đồng ý", G1–G5) |
| Authority | HUMAN LEAD 2026-10-24: "Thử cách a, không được thì gắn tay" (sau PKG2.2) |
| Change class | S2 (scope: PKG §5 để "tự đăng / upload YouTube" ngoài scope; security model: token OAuth ghi được lên kênh) |
| Integration | Push / PR / merge vẫn cần HUMAN LEAD duyệt riêng |

## 1. Mục tiêu

HUMAN LEAD vẫn **upload video bằng tay** (Studio). Sau đó một lệnh trên VM tự gắn thumbnail PKG2 (`output/<id>/thumbs/`) cho đúng video, thay vì chọn ảnh từng video trong Studio. Không đăng / sửa gì khác.

## 2. Đề xuất (G1–G5)

- **G1 Phạm vi lệnh**: CLI `python -m auto_short.publish thumbs --playlist <pid> [--yt-playlist <id playlist YouTube>]` (không route web). Chỉ gọi: đọc danh sách video của kênh (`channels.list mine`, `playlistItems.list` uploads) hoặc chỉ playlist chỉ định (`playlistItems.list`, cùng scope `youtube.readonly`), `videos.list part=fileDetails,snippet` và `thumbnails.set` (sửa đổi PUB2P, HUMAN LEAD duyệt 2026-11-02). Không upload video, không đổi tiêu đề / mô tả / trạng thái / playlist.
- **G2 Ghép video ↔ ảnh**: khi không có `--yt-playlist`, theo **tên file gốc lúc upload** (`fileDetails.fileName`, chỉ chủ kênh đọc được): `[HD] <bộ kinh> - Tập N.mp4` → ảnh 16:9, `[HD Mobile] <bộ kinh> - Tập N.mp4` (tên kho 3090 / `backup.ps1`, HD1 G6) hoặc `[HD Dọc] <bộ kinh> - Tập N.mp4` (tên cũ, video upload trước khi đổi) → ảnh 9:16 (sửa đổi PUB2M, 2026-11-02). Không khớp tên → bỏ qua, in ra; không đoán theo tiêu đề. Với `--yt-playlist`, HUMAN LEAD đã tự chọn video vào playlist nên được ghép theo thứ tự **nhật ký → tên file → tiêu đề**: bản ghi `youtube_id` cùng `playlist_id` nguồn dùng `video_id` / khuôn đã lưu; tên file nhận thêm mẫu web cũ `[HD ]<bộ kinh>_Tập<N>_Doc.mp4` (tiền tố `[HD] ` tùy chọn, không phân biệt hoa thường, khuôn dọc); tiêu đề `[HD …] <bộ kinh> - … - Tập N` nhận thẻ `[HD]` → ngang, `[HD Dọc]` / `[HD Mobile]` → dọc không phân biệt hoa thường, tên bộ so như `_series`. Không khớp → bỏ qua, in lý do; các nguồn lệch tập / khuôn → bỏ qua với lý do "nhật ký và tên / tiêu đề lệch nhau". Bảng thêm cột "ghép theo" (sửa đổi PUB2P, HUMAN LEAD duyệt 2026-11-02).
- **G3 An toàn khi chạy**: mặc định chạy thử (in bảng video → ảnh, không gọi `thumbnails.set`); `--apply` mới gắn. Ghi nhật ký `work/_publish/thumbs.json` (video YouTube id, video_id nguồn, khuôn, sha256 ảnh, thời điểm); lần sau bỏ qua video đã gắn cùng sha256.
- **G4 Token / bí mật**: OAuth "TVs and Limited Input devices" (device flow: lệnh in mã, HUMAN LEAD nhập ở google.com/device bằng điện thoại). Scope tối thiểu Google cho phép cho các lệnh ở G1 (`youtube.readonly` + `youtube.upload`; nếu device flow không nhận thì `youtube`). Client + token ở `~/.local/share/auto-short/youtube-client.json` / `youtube-token.json`, mode 600, ngoài git, không ghi vào log. Thu hồi: myaccount.google.com/permissions.
- **G5 Dependency**: không thêm — HTTP bằng `urllib` (stdlib).

## 3. Việc HUMAN LEAD cần làm một lần

1. Google Cloud Console: tạo project, bật **YouTube Data API v3**.
2. OAuth consent screen: External, chế độ Testing, thêm tài khoản Google của kênh làm test user. (Chế độ Testing: token hết hạn sau 7 ngày → đăng nhập lại bằng mã.)
3. Credentials → OAuth client ID → loại **TVs and Limited Input devices** → tải JSON, chép lên VM `~/.local/share/auto-short/youtube-client.json` (chmod 600).
4. Kênh phải đã xác minh (youtube.com/verify) mới được dùng thumbnail tùy chỉnh.

## 4. Hạn mức

Quota mặc định 10 000 đơn vị / ngày: `thumbnails.set` 50 → tối đa ≈ 190 ảnh / ngày sau phần đọc danh sách (1 / trang 50 video). Hết quota → lệnh dừng, chạy lại hôm sau (bỏ qua video đã gắn).

## 5. Ngoài scope

Upload video, sửa metadata, lên lịch đăng, YouTube Analytics, route web, thumbnail cho Short (YouTube không nhận thumbnail tùy chỉnh qua API cho Short theo cùng cách — chưa kiểm, không làm).
