# SRC1 — Sao lưu video gốc lên kho 3090 trước khi tự dọn

| Metadata | Value |
|---|---|
| Status | PROPOSED — G1, G4 đã chọn trong chat 2026-10-25; chờ HUMAN LEAD duyệt toàn văn |
| Authority | HUMAN LEAD 2026-10-25: "vấn đề giữ nguồn khá quan trọng với ghép video. Đặc biệt là cơ chế tự dọn nguồn hiện tại cần cơ chế backup"; chọn "Tất cả video" và "Đẩy dần, E: đủ chỗ" |
| Change class | S2 (sửa `HD2-external-store-3090.md` G1 `kind`, G7; sửa W9 S5 / FIX-keep-khaithi-source: tự dọn chỉ sau khi có bản sao; luồng dữ liệu VM → 3090 mới) |
| Integration | Push / PR / merge vẫn cần HUMAN LEAD duyệt riêng |

## 1. Bối cảnh — bằng chứng (2026-10-25, đọc read-only)

- `[storage] auto_archive` xóa `work/<id>/source.mp4` của video đã "Xong" sau 5 ngày (`auto_archive_grace_minutes = 7200`), **không có bản sao**: đã xóa 130 tập, 70,0 GB. Trên VM còn 188 `source.mp4`, 62,8 GB. Từ FIX-keep-khaithi-source, video có khai thị được giữ, nhưng video chỉ có Short vẫn bị xóa; ♥ có thể được bấm sau khi đã dọn.
- Ghép chủ đề (TC3) cần đúng video gốc. 25 video yêu thích: 14 trong `work/_theme_sources/`, 7 còn ở workspace, **4 đã mất** (ví dụ `xPBuSsKEY-U`, tự dọn 2026-10-18). Job ghép 111 "Chuyển hóa tâm niệm" (Kinh Vô Lượng Thọ) lỗi 2026-10-25 vì tải lại `xPBuSsKEY-U` bị YouTube trả `HTTP Error 403: Forbidden`.
- Kho 3090 (HD2) đã có `PUT` kiểm sha256 nhưng `kind` chỉ ∈ {`hd`, `vertical`}; client VM chưa có `put`.

## 2. Đề xuất (G1–G7)

- **G1 Phạm vi (đã chọn)**: mọi `source.mp4` từ YouTube (`source.kind = youtube`), không chỉ video yêu thích / khai thị.
- **G2 Loại mới trên kho**: `kind = source` (cột `loai` = `Goc`), tên `[Goc] <bộ kinh> - Tập N.mp4`; tập không có số tập `[Goc] <video_id>.mp4`; thư mục bộ kinh như HD2 G3 (video không thuộc playlist nào: thư mục `_khac`). Byte nguyên bản (sha256 = `manifest.source.sha256`), không nén lại. Không xóa qua API (giữ HD2 G1).
- **G3 Tự dọn chỉ sau khi có bản sao**: khi `[store] enabled`, `archive_source` (cả tự dọn lẫn nút dọn trên tab Bộ nhớ) chỉ xóa `source.mp4` khi kho `HEAD` trả đúng sha256 + kích thước; ghi `archive.json` `"backup": {"store": "source", "sha256": …}`. Kho tắt / chưa có bản → **không xóa**, tự dọn thử lại ở lượt sau; nút dọn báo "chưa sao lưu lên 3090". `[store]` tắt → giữ hành vi cũ (dọn không sao lưu) để môi trường không có 3090 vẫn chạy. Ngoại lệ khai thị của FIX-keep-khaithi-source giữ nguyên.
- **G4 Đẩy dần bản đang có (đã chọn)**: web chạy nền một luồng sao lưu tuần tự (một file một lúc, ưu tiên video sắp đến hạn tự dọn rồi tới video yêu thích, rồi còn lại), chỉ khi không có job render đang chạy; nhớ tiến độ qua `HEAD` (đã có thì bỏ qua). Kho tắt → nghỉ `retry_seconds` rồi thử lại. Cờ `[store] backup_source` (mặc định tắt; bật trên 8080 khi HUMAN LEAD đồng ý) bật / tắt cả G3 + G4.
- **G4a Video yêu thích trước (HUMAN LEAD 2026-10-25: "xem lại tất cả video nào có yêu thích mà bị xóa thì plan tải lại và backup cho đủ")**: luồng G4 đẩy trước mọi video có ♥ (Short hoặc khai thị), gồm cả bản chỉ còn trong `work/_theme_sources/` (đẩy file cache; sha có thể khác `manifest.source.sha256` khi bản tải lại khác byte — ghi sha thật của file, `cached_source` / TC3 đã kiểm lại audio từng clip). Kiểm kê 2026-10-25 (25 video ♥): 7 còn ở workspace (VLT tập 21–27), 14 chỉ còn trong cache (TTCƯT tập 10–20, Thập Thiện, VLT tập 7, 18; 6,2 GB), **4 mất hẳn** (VLT tập 16, 17, 19, 20 — `xPBuSsKEY-U`, `5wv5_Q0Utn8`, `AKMjavDI0iY`, `R6ju1kozrwE`; ≈ 1,85 GB; tự dọn 2026-10-18) → tải lại chậm từ YouTube (lệnh `python -m auto_short.theme_render.sources` có sẵn; tự động trong TC3.2) rồi đẩy như trên. Mục tiêu: mọi video ♥ có bản trên 3090.
- **G5 Lấy lại nguồn**: thứ tự cho ghép chủ đề (TC3) và "Khôi phục nguồn" (CP8.37): workspace → `work/_theme_sources/` → **kho 3090 (`source`)** → YouTube. File mượn từ kho cho ghép chủ đề vào thư mục tạm của job, xóa sau job (HD2 G7); "Khôi phục nguồn" đặt lại `work/<id>/source.mp4` như hiện nay. Kiểm sha256 mọi file nhận về.
- **G6 Hiển thị**: tab Bộ nhớ thêm "đã sao lưu lên 3090: N / M video gốc" và hàng đợi sao lưu còn lại.
- **G7 Dependency / security**: không thêm dependency; dùng lại token / kênh RemoteForward 18090 của HD2; giới hạn `MAX_BODY` 20 GiB vẫn đủ (gốc lớn nhất hiện ≈ 0,7 GB).

## 3. Ngoài scope

130 video gốc đã xóa (chỉ lấy lại từ YouTube cho video yêu thích — TC3.2); xóa bản gốc trên 3090; sao lưu file khác (transcript / render nhỏ, đã ở VM); nén lại / đổi định dạng; nhiều máy kho.

## 4. Thứ tự làm khi được duyệt

1. `docs/tasks/SRC1-source-backup.md`: G2–G7.
2. `docs/tasks/TC3.2-theme-source-ready.md` (phụ thuộc G5): tự tải chậm từ YouTube video yêu thích còn thiếu ở mọi nơi, trạng thái nguồn trên thẻ chủ đề, chờ khi YouTube chặn.

## 5. Việc HUMAN LEAD cần làm một lần

Sau khi SRC1 merge: chép `tools/store/store.py` mới lên 3090 và khởi động lại tác vụ kho (script cài đặt HD2); bật `[store] backup_source = true` trên 8080 (agent hỏi trước khi sửa `config.toml` / restart).
