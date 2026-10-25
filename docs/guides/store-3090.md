# Cài kho HD / dọc trên máy 3090

Máy 3090 cần Windows, Python >= 3.11 của enhance worker và SSH `Host gpu-worker-v4` đã hoạt động. Kho chỉ nghe `127.0.0.1`, dùng lại tunnel SSH; không cần mở cổng LAN hay cài thư viện Python.

1. Chép cả ba file `tools/store/store.py`, `config.example.json`, `setup-store.ps1` vào cùng một thư mục trên 3090. Mở PowerShell bằng tài khoản đang chạy enhance worker:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup-store.ps1 -Root E:\AutoShortStore -SeriesDir E:\KinhDiaTang_HD
   ```

   Nếu không tìm được Python, thêm `-Python "C:\Users\<ten>\miniconda3\envs\enhance-worker\python.exe"`.

2. Script cài vào `%LOCALAPPDATA%\AutoShortStore`, tạo `config.json`, `token.txt` và task `AutoShortStore` chạy khi đăng nhập, tự khởi động lại khi lỗi. Token chỉ được in **một lần khi tạo mới**. Trên VM, tạo file ngoài git:

   ```bash
   mkdir -p ~/.local/share/auto-short
   chmod 700 ~/.local/share/auto-short
   (umask 077; touch ~/.local/share/auto-short/store.env)
   chmod 600 ~/.local/share/auto-short/store.env
   nano ~/.local/share/auto-short/store.env
   ```

   Dán `AUTO_SHORT_STORE_TOKEN=<token vừa in>` vào file. Nạp biến này vào tiến trình web khi khởi động lại web; trong shell kiểm tra có thể dùng:

   ```bash
   set -a
   . ~/.local/share/auto-short/store.env
   set +a
   ```

3. Script sao lưu `~/.ssh/config` trước khi thêm `RemoteForward 127.0.0.1:18090 127.0.0.1:18090` vào block `gpu-worker-v4`. Khởi động lại task **EnhanceWorker-Tunnel** (End rồi Run trong Task Scheduler) để tunnel nhận cấu hình mới.

4. Trên VM, sau khi nạp token:

   ```bash
   curl --fail -H "Authorization: Bearer $AUTO_SHORT_STORE_TOKEN" http://127.0.0.1:18090/index
   ```

   Kết quả là danh sách file có `video_id`, `kind`, `series`, `file`, `size`, `sha256`. Thiếu/sai token trả 401. Không kết nối được: kiểm tra 3090 đang bật, task kho và tunnel đang chạy. Danh sách rỗng: kiểm tra CSV và `SHA256SUMS.txt` trong thư mục bộ kinh.

Kho đọc `index.csv` và cả `danh-sach.csv` do script backup hiện tại ghi (UTF-8/BOM, cột `tap,loai,file,video_id,tieu_de`; `loai` là `HD` hoặc `Doc`). `index.csv` được ưu tiên nếu trùng tập/loại. Chỉ file `.mp4` tồn tại và có sha trong `SHA256SUMS.txt` mới xuất hiện; kho đọc lại khi CSV/sums thay đổi. Giữ nguyên các file sao lưu cũ, không cần chép sang thư mục gốc. PUT mới ghi `index.csv` cùng các cột trên; bộ chưa khai báo được lưu tại `<root>\<playlist_id>`. PUT giới hạn 20 GiB, không có API xóa.

Chạy lại setup giữ cấu hình và token. `-Root` / `-SeriesDir` chỉ áp dụng lúc tạo cấu hình lần đầu; muốn thêm bộ hoặc đổi đường dẫn, sửa `config.json` rồi khởi động lại task kho. Để kiểm tra trực tiếp, dừng task kho và chạy Python đã chọn:

```powershell
& "C:\Users\<ten>\miniconda3\envs\enhance-worker\python.exe" "$env:LOCALAPPDATA\AutoShortStore\store.py" --config "$env:LOCALAPPDATA\AutoShortStore\config.json" --self-test
```

Bỏ `--self-test` để chạy kho ở cửa sổ hiện tại. `setup-store.ps1 -Uninstall` dừng và gỡ task kho, giữ file, token và SSH config. Không đưa token hay `store.env` vào git hoặc ảnh chụp/log chia sẻ.
