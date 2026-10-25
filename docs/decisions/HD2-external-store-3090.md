# HD2 — Máy 3090 làm kho lưu trữ ngoài của web (bản HD / dọc)

| Metadata | Value |
|---|---|
| Status | ACCEPTED — HUMAN LEAD 2026-10-25 "ok cả hai" |
| Authority | HUMAN LEAD 2026-10-25: "đã sao lưu xong … trong thời gian chuyển lên youtube tôi sẽ dùng 3090 như ổ cứng của web"; chọn: tạo bản dọc HD còn thiếu, làm Short / khai thị / ghép chủ đề, tải về qua web, lưu luôn file mới lên 3090 — từ file trên 3090; sau khi upload xong vẫn giữ 3090 làm kho lâu dài |
| Change class | S2 (architecture: thêm tầng lưu trữ ngoài; sửa `HD1-hd-backup-release.md` G4 / G5 và CP13.1 E5 / E6; security model: kênh VM ↔ 3090 mới) |
| Integration | Push / PR / merge vẫn cần HUMAN LEAD duyệt riêng |

## 1. Bối cảnh

HD1 (PR #144) cho phép xác nhận sao lưu bằng sha256 và giải phóng `source_hd.mp4` / `full/vertical.mp4` trên VM; HD1 G4 / G5 định lấy lại nguồn từ bản HD đã upload YouTube. HUMAN LEAD đổi: **bản trên 3090 là nguồn chính** (đúng từng byte bản đã xác nhận → Short cũ vẫn hợp lệ, không nén lại qua YouTube). VM không có sudo / cifs / sshfs → không gắn ổ mạng; 3090 đã có SSH thường trực tới VM (`ssh -N gpu-worker-v4`, `LocalForward 18080 → VM 8080`, `tools/enhance_worker/windows/setup-enhance-worker.ps1`) và Python (env worker enhance).

## 2. Đề xuất (G1–G8)

- **G1 Dịch vụ kho trên 3090**: `tools/store/store.py` (Python stdlib, chạy trong env worker sẵn có) phục vụ **một thư mục gốc** (mặc định `E:\AutoShortStore` — ổ E còn > 1 TB, HUMAN LEAD 2026-10-25; mỗi bộ kinh một thư mục con; thư mục sao lưu Kinh Địa Tạng hiện có trên ổ E được khai báo làm thư mục của bộ đó, không phải chép lại). Chỉ lắng nghe `127.0.0.1`. API: `GET /files/<video_id>/<kind>` (Range), `HEAD` (kích thước + sha256 từ `SHA256SUMS.txt`), `PUT` (nhận file mới, ghi `.part`, kiểm sha256 gửi kèm rồi đổi tên, cập nhật `SHA256SUMS.txt` + `index.csv`), `GET /index` (danh sách `video_id`, `kind`, tên, kích thước, sha256). `kind` ∈ {`hd`, `vertical`}. Không xóa qua API.
- **G2 Kênh**: thêm `RemoteForward 18090 → 127.0.0.1:18090` vào block SSH `gpu-worker-v4` của 3090 → VM gọi `http://127.0.0.1:18090`. Không mở cổng mới trên LAN. Token ngẫu nhiên ≥ 32 byte ở cả hai đầu (VM: env `AUTO_SHORT_STORE_TOKEN` như token enhance; 3090: file cấu hình cạnh `store.py`), so sánh hằng thời gian. Script cài đặt + tác vụ tự chạy khi đăng nhập như worker enhance.
- **G3 Tên file trên 3090**: giữ quy ước HD1: `[HD] <bộ kinh> - Tập N.mp4`, `[HD Mobile] <bộ kinh> - Tập N.mp4` (+ ảnh `.jpg`); tập không có số tập: `[HD] <video_id>.mp4`. `index.csv` là nguồn ánh xạ `video_id` ↔ file (script sao lưu đã ghi).
- **G4 Nguồn cho tập đã giải phóng (thay HD1 G4 / G5 YouTube)**: khi job cần bản HD / dọc của tập `released` (tạo bản dọc, render Short / khai thị, ghép chủ đề), VM tải từ kho vào `work/<owner>/source_hd.mp4` (hoặc file dọc tạm), **kiểm sha256 = sha đã giải phóng (`backup.json`)**, dùng xong xóa. Vì đúng byte cũ → render key không đổi, Short cũ vẫn hiện hành. Kho tắt / không có file → job dừng "đợi 3090" (không phải lỗi, như "đợi HD" của E6), tự chạy lại khi kho trả lời; vẫn có nút "Render bằng bản gốc". YouTube (HD1 G4 / G5) hoãn, chỉ làm sau nếu cần dự phòng.
- **G5 Tải về qua web**: link tải HD / dọc của tập `released` vẫn hiện; VM chuyển tiếp luồng từ kho (giữ Range, tên file như cũ). Kho tắt → 503 "3090 đang tắt".
- **G6 File mới lên thẳng 3090**: bản dọc HD mới dựng (và `source_hd.mp4` khi enhance xong một tập mới, nếu bật cờ cấu hình `[store] offload_hd`) được `PUT` lên kho, kho xác nhận sha → VM ghi xác nhận (HD1 G1) và giải phóng (HD1 G2) tự động. Kho tắt → giữ trên VM, thử lại khi kho trả lời. Cờ `[store] offload` (mặc định tắt) để bật / tắt cả cơ chế.
- **G7 Bộ nhớ đệm VM**: file tải từ kho cho một job xóa ngay sau job; không giữ bản sao lâu dài. Tab Bộ nhớ hiện dung lượng dành cho file tạm từ kho.
- **G8 Dependency / security**: không thêm dependency (stdlib hai đầu). Kho chỉ phục vụ file trong thư mục gốc (chặn `..`, symlink), không thực thi gì; VM kiểm sha mọi file nhận về; token ngoài git, không ghi log.

## 3. Ngoài scope

Gắn ổ mạng trên VM; xóa file trên 3090 qua web; nhiều máy kho; đồng bộ ngược thư mục 3090 → VM ngoài các job ở G4; nguồn YouTube (HD1 G4 / G5 — hoãn).

## 4. Thứ tự làm khi được duyệt

1. HD2a: G1 + G2 + G3 + G4 (kho + kênh + nguồn cho tạo bản dọc / render) — cần cho 52 tập Kinh Địa Tạng chưa có bản dọc.
2. HD2b: G5 + G6 + G7 (tải qua web, đẩy file mới lên kho, Bộ nhớ).

## 5. Việc HUMAN LEAD cần làm một lần

Chạy script cài đặt kho trên 3090 (thêm RemoteForward vào SSH sẵn có, tạo token, tác vụ tự chạy), dán token vào `~/.local/share/auto-short/` trên VM theo hướng dẫn của script; 3090 cần bật khi web dùng file trên kho.
