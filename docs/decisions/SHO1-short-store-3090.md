# SHO1 — Short + khai thị đã đăng hết rời VM lên kho 3090, web vẫn xem / sửa

| Metadata | Value |
|---|---|
| Status | ACCEPTED — HUMAN LEAD 2026-10-26 "duyệt tất cả" (G1–G8) |
| Authority | HUMAN LEAD 2026-10-26: "bây giờ cần cơ chế xem sửa short và khai thị trên 3090 luôn"; chọn "Đưa lên kho, web vẫn dùng" và "Đã đăng hết" (tập mà mọi Short đã "Đã đăng" đủ 5 ngày) |
| Change class | S2 (sửa `HD2-external-store-3090.md` G1 `kind` + API theo file, HD2b Out of scope "Short"; luật mới: file Short được phép vắng trên VM; luồng dữ liệu VM ↔ 3090 mới) |
| Integration | Push / PR / merge vẫn cần HUMAN LEAD duyệt riêng |

## 1. Bối cảnh — bằng chứng (2026-10-26, đọc read-only)

- `output/*/shorts/` trên VM: 378 thư mục, **≈ 100 GB** (thư mục khai thị `<id>.kt` ≈ 65 GB); ổ VM 502 GB, đã dùng 318 GB, trống 163 GB.
- Kho 3090 (HD2 G1, SRC1 G2) nhận `kind` ∈ {`hd`, `vertical`, `source`}, **một file / (video_id, kind)**; `video_id` đã chấp nhận hậu tố `.kt` (`tools/store/store.py` `VIDEO_ID`). Short là nhiều file / tập (`shorts/k01.mp4` …).
- ARC1 (#170) chỉ tải ZIP về `E:\LuuTru_Short` — web không đọc được bản đó, không giải phóng gì trên VM.
- `render_manifest.json` đã ghi `sha256` từng Short. Web liệt kê Short theo file còn trên đĩa (`web/episodes.py` `short_files`: bỏ Short không có file); dựng lại chỉ tái dùng Short cũ khi file còn và đúng sha (`render/stage.py` `reusable`, CP8.2 T5), `validate_render` đòi mọi file tồn tại → nếu chỉ xóa file, web mất Short và sửa một Short sẽ dựng lại cả tập.

## 2. Đề xuất (G1–G8)

- **G1 Loại mới trên kho, theo file**: `kind = short`, thêm tham số tên clip: `GET` / `HEAD` / `PUT /files/<video_id>/short/<clip>` (`<clip>` = tên file trong `render_manifest`, ví dụ `k01.mp4`, regex chặt; `video_id` có thể mang `.kt`). Tên trên 3090 (phẳng trong thư mục bộ kinh — kho không nhận `\` trong tên): `[Short] <bộ kinh> - Tập N - k01.mp4`, khai thị `[KhaiThi] <bộ kinh> - Tập N - k01.mp4`; tập không có số tập: `[Short] <video_id> - k01.mp4`. Danh mục Short ở file riêng `index-short.csv` (`video_id`, `clip`, `file`) cạnh `index.csv`; `SHA256SUMS.txt` dùng chung; `index.csv` / `danh-sach.csv` của `backup.ps1` không đổi. Kiểm sha256 khi `PUT`, không xóa qua API (giữ HD2 G1).
  - **Sửa đổi G1 (HUMAN LEAD 2026-10-26, chọn "Lưu bản mới, giữ bản cũ"; làm ở SHO1b)**: Short đã sửa có sha khác bản trên kho → `PUT` không trả 409 mà lưu bản mới `… - k03 (r2).mp4`, `index-short.csv` trỏ bản mới; bản cũ giữ trên đĩa + `SHA256SUMS.txt` (vẫn không xóa qua API). Kind khác giữ 409.
- **G2 Khi nào rời VM (đã chọn)**: một video (Short `<id>` + khai thị `<id>.kt` nếu có) đủ điều kiện khi **mọi phần "Xong"** (CP8.7 L4 — mọi Short đã "Đã đăng") giữ đủ `auto_archive_grace_minutes` (hiện 5 ngày) — cùng điều kiện tự dọn nguồn (W9 S5), nhưng **áp dụng cả video có khai thị**. Tập đang xử lý / có job thì bỏ qua lượt này.
- **G3 Đẩy + giải phóng**: vòng nền như HD2b G6 (cờ `[store] offload_shorts`, mặc định tắt; một tập mỗi lượt, nhường làn render): `PUT` từng Short → `HEAD` khớp sha + kích thước với `render_manifest` → ghi `output/<id>/store.json` `{"released": {"<clip>": sha256, …}, "at": …}` → xóa file trên VM. Thiếu / lệch một file → không xóa file nào của tập, thử lại lượt sau. Bài đăng, trạng thái "Đã đăng", `render_manifest.json` giữ nguyên.
- **G4 Xem / tải qua web**: Short đã giải phóng vẫn hiện như cũ (danh sách, phát, tải từng Short, "Tải cả hai" `all.zip`, ARC1 `?archive=1`): VM chuyển tiếp luồng từ kho (giữ `Range`, tên file); ZIP dựng luồng từ kho từng entry: tên / nội dung entry như khi file còn trên VM, mtime entry = mtime ghi lúc giải phóng; vân tay ARC1 (`/api/archive/zips`) dùng size + mtime đã ghi nên không đổi sau giải phóng. Kho tắt → 503 "3090 đang tắt"; danh sách vẫn hiện, nút phát / tải báo 3090 tắt.
- **G5 Sửa (dựng lại)**: job render / thêm Short / sửa tiêu đề của tập đã giải phóng **trước hết lấy lại mọi Short đã giải phóng về `output/<id>/shorts/`** (kiểm sha = `store.json`), xóa `store.json` rồi chạy như bình thường → Short không đổi được tái dùng (T5), chỉ Short sửa được dựng lại. Kho tắt → job "đợi 3090" (mẫu HD2a G4 / FIX-store-wait-persist), tự chạy tiếp khi kho trả lời. Sau khi sửa, tập lại nằm trên VM cho tới khi đủ G2 lần nữa (Short sửa phải "Đã đăng" lại).
- **G6 Luật file vắng**: chỉ khi có `store.json` `released` thì file Short được phép vắng mà không bị coi là hỏng / phải dựng lại; mọi chỗ đọc file Short (`short_files`, ZIP, kiểm tra Bộ nhớ, ghép Short `web/compilations.py`) đi qua một helper chung trả "trên VM" hoặc "trên kho". Ghép Short dùng Short đã giải phóng: mượn tạm từ kho (mẫu HD2a G4) — làm ở SHO1b.
- **G7 Bộ nhớ**: tab Bộ nhớ hiện "Short trên 3090: N tập, X GB" + hàng chờ đẩy (đủ điều kiện / còn chờ ngày / lỗi).
- **G8 Dependency / security**: không thêm dependency; dùng lại token, kênh RemoteForward 18090, `MAX_BODY` của HD2.

## 3. Ngoài scope

Xóa Short trên 3090; tự giải phóng Short chưa đăng hết; nút "Đưa lên 3090" bấm tay; đổi ARC1 (script `luu-tru-short.ps1` vẫn dùng được — tải qua G4); bản dọc / HD / nguồn (đã có HD2b / SRC1).

## 4. Thứ tự làm khi được duyệt

1. `docs/tasks/SHO1a-short-store-release.md`: G1 + G3 + G6 + G4 (kho nhận Short, đẩy + giải phóng, xem / tải qua web) — dual-agent, Codex IMPLEMENTER.
2. `docs/tasks/SHO1b-short-store-edit.md`: G5 + G7 + phần ghép Short của G6 (lấy lại khi sửa, mượn khi ghép, Bộ nhớ). Bật `offload_shorts` trên 8080 chỉ sau khi SHO1b merge, để không có tập nào "giải phóng mà không sửa được".

## 5. Việc HUMAN LEAD cần làm một lần

Sau khi merge: chép `tools/store/store.py` mới lên 3090 và khởi động lại task `AutoShortStore` (như lần SRC1). Kiểm ổ E: còn ≥ 150 GB (hiện 1.642 GB).
