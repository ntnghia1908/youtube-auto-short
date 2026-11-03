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

- **G1 Phạm vi lệnh**: CLI `python -m auto_short.publish thumbs --playlist <pid> [--yt-playlist <id playlist YouTube>]` và `kt-thumbs --playlist <pid nguồn> --yt-playlist <id playlist KT YouTube>` (KT bắt buộc cả hai playlist; sửa đổi PUB2K, HUMAN LEAD duyệt 2026-11-02; không route web). Chỉ gọi: đọc danh sách video của kênh (`channels.list mine`, `playlistItems.list` uploads) hoặc chỉ playlist chỉ định (`playlistItems.list`, cùng scope `youtube.readonly`), `videos.list part=fileDetails,snippet` (đọc playlist chỉ định: thêm `status`, dùng chung với LNK1 — chỉ đọc, cùng scope) và `thumbnails.set` (sửa đổi PUB2P, HUMAN LEAD duyệt 2026-11-02). Không upload video, không đổi tiêu đề / mô tả / trạng thái / playlist. Sửa đổi LNK1 (HUMAN LEAD 2026-11-01): web được đọc token, chỉ GET Data API để lấy link bài đăng; thao tác ghi Data API vẫn chỉ CLI. POST duy nhất là refresh OAuth tới `https://oauth2.googleapis.com/token`, lưu token atomic mode 600 theo [LNK1 L1](../tasks/LNK1-post-links-from-playlist.md#authority--key-decisions). Quy tắc đọc playlist / video và nhiều kênh: L1–L1b cùng contract.
- **G2 Ghép video ↔ ảnh**: khi không có `--yt-playlist`, theo **tên file gốc lúc upload** (`fileDetails.fileName`, chỉ chủ kênh đọc được): `[HD] <bộ kinh> - Tập N.mp4` → ảnh 16:9, `[HD Mobile] <bộ kinh> - Tập N.mp4` (tên kho 3090 / `backup.ps1`, HD1 G6) hoặc `[HD Dọc] <bộ kinh> - Tập N.mp4` (tên cũ, video upload trước khi đổi) → ảnh 9:16 (sửa đổi PUB2M, 2026-11-02). Không khớp tên → bỏ qua, in ra; không đoán theo tiêu đề. Với `--yt-playlist`, HUMAN LEAD đã tự chọn video vào playlist nên được ghép theo thứ tự **nhật ký → tên file → tiêu đề**: bản ghi `youtube_id` cùng `playlist_id` nguồn dùng `video_id` / khuôn đã lưu; tên file nhận thêm mẫu web cũ `[HD ]<bộ kinh>_Tập<N>_Doc.mp4` (tiền tố `[HD] ` tùy chọn, không phân biệt hoa thường, khuôn dọc); tiêu đề `[HD …] <bộ kinh> - … - Tập N` nhận thẻ `[HD]` → ngang, `[HD Dọc]` / `[HD Mobile]` → dọc không phân biệt hoa thường, tên bộ so như `_series`. Không khớp → bỏ qua, in lý do; các nguồn lệch tập / khuôn → bỏ qua với lý do "nhật ký và tên / tiêu đề lệch nhau". Bảng thêm cột "ghép theo" (sửa đổi PUB2P, HUMAN LEAD duyệt 2026-11-02). Ghép link bài đăng là quy tắc riêng ở [LNK1 L2–L7](../tasks/LNK1-post-links-from-playlist.md#authority--key-decisions), không đổi `thumbs`.
  Với `kt-thumbs`, ghép theo mã `T<N>[ _]KT<NN>` ở đầu tên file gốc (ưu tiên) hoặc đầu tiêu đề, sau khi strip / NFC, không phân biệt hoa thường; sau số NN không được là chữ số. HUMAN LEAD xác nhận mã trên YouTube đúng như web quy định (PUB2K, 2026-11-02). Cả hai có mã mà lệch nhau hoặc không có mã → bỏ qua, in lý do. Tập N phải có đúng một `<video_id>.kt` với `work/<video_id>.kt/khaithi.json`, `video_id` thuộc playlist nguồn và số tập lấy từ `episode.header`; clip số NN lấy từ `khaithi_thumbs.read(...)["clip_numbers"]`, dùng ảnh KT ngang (mặc định `landscape`) hoặc dọc theo `--shape {vertical,landscape}`, còn hiệu lực của `khaithi_thumbs.valid_files(...)[clip][shape]` trong `khaithi_thumbs.directory` (Sửa đổi 1 PUB2K, HUMAN LEAD duyệt 2026-11-02). Thiếu khuôn đã chọn → bỏ qua, lý do nêu rõ khuôn; không lấy khuôn còn lại thay thế. Thiếu / nhiều tập, thiếu clip hoặc ảnh hợp lệ → bỏ qua với lý do riêng. Tiêu đề YouTube (bỏ mã đầu / hashtag, chuẩn hóa NFC, hoa thường và khoảng trắng) khác tiêu đề web → chỉ cảnh báo, vẫn gắn theo mã. `thumbs --yt-playlist` bỏ qua bản ghi nhật ký có `clip_id` khi ghép tập.
- **G3 An toàn khi chạy**: mặc định chạy thử (in bảng video → ảnh, không gọi `thumbnails.set`); `--apply` mới gắn. Ghi nhật ký `work/_publish/thumbs.json` (video YouTube id, video_id nguồn, khuôn, sha256 ảnh, thời điểm); lần sau bỏ qua video đã gắn cùng sha256. Bản ghi KT có `video_id = "<id>.kt"`, thêm `clip_id` kiểu chuỗi và `shape` theo lựa chọn ở G2; giữ `schema_version` 1 (PUB2K, HUMAN LEAD duyệt 2026-11-02).
- **G4 Token / bí mật**: OAuth "TVs and Limited Input devices" (device flow: lệnh in mã, HUMAN LEAD nhập ở google.com/device bằng điện thoại). Scope tối thiểu Google cho phép cho các lệnh ở G1 (`youtube.readonly` + `youtube.upload`; nếu device flow không nhận thì `youtube`). Client + token ở `~/.local/share/auto-short/youtube-client.json` / `youtube-token.json`, mode 600, ngoài git, không ghi vào log. Thu hồi: myaccount.google.com/permissions. Phiên Testing, token nhiều kênh và lỗi auth trên web: [LNK1 L1a–L1b](../tasks/LNK1-post-links-from-playlist.md#authority--key-decisions); token / secret không vào phản hồi API.
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
