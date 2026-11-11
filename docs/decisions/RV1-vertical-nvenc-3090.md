# RV1 — Dựng bản dọc bằng NVENC trên 3090, chạy song song Ollama

| Metadata | Value |
|---|---|
| Status | PROPOSED — chờ HUMAN LEAD chạy phép đo §4 trên 3090 rồi chọn G1–G6 |
| Authority | HUMAN LEAD 2026-10-25: "Viết decision RV1: bản dọc NVENC trên 3090 chạy song song Ollama" |
| Change class | S2 (architecture: việc render đầu tiên chạy ngoài VM; đổi CP8.32 nơi dựng bản dọc; dùng lại kênh / token worker CP13.1) |
| Integration | Push / PR / merge cần HUMAN LEAD duyệt riêng; chưa authorize implementation |

## 1. Bối cảnh (số đo 2026-10-25)

- Bản dọc (CP8.32, `render/full.py`) mã hóa `libx264 -preset medium -crf 22`, 1080×1920 yuv420p, cả tập (≈ 58 phút). Trên VM: ≈ 1 085–1 470 s / tập khi 2 job song song (job 53–55), tức ≈ 22 phút CPU / tập chiếm 1 slot làn render.
- 2 render song song ≈ 65 % CPU VM; GPU 3090 (Ollama) là nút thắt AI ≈ 9 phút / tập Kinh Địa Tạng; render Short ≈ 14 phút slot / tập. Khi bản dọc chiếm slot, Short xuống render phải chờ (Short tập 21 chờ 6 phút) — RENDER-short-first giảm chờ bằng giữ chỗ, nhưng tổng CPU VM cho bản dọc vẫn còn.
- 3090 đã có: worker enhance (CP13.1, ffmpeg có `h264_nvenc`, kênh SSH `18080 → VM 8080`, token, Task Scheduler, `yield_to_ollama`), kho HD2 (`E:\AutoShortStore` / `E:\KinhDiaTang_HD`, nguồn HD của tập đã giải phóng nằm sẵn trên 3090). VM **không ssh được** vào 3090 (chỉ chiều 3090 → VM).
- NVENC là khối mã hóa phần cứng riêng, không dùng nhân CUDA của Ollama; nhưng giải mã + filter (crop / scale lanczos / overlay chữ) vẫn tốn CPU 3090, và NVENC cần ít VRAM (vài trăm MB). Chất lượng NVENC ở cùng bitrate thường kém x264 medium một chút → phải đo trước khi chọn (§4).

## 2. Đề xuất (G1–G6)

- **G1 Nơi chạy**: worker bản dọc trên 3090, nhận việc từ VM theo giao thức lease kiểu E3 (CP13.1) qua kênh 18080 sẵn có; VM vẫn là nơi xếp hàng / hiển thị / xác nhận. Không mở cổng mới, không cần VM ssh vào 3090.
- **G2 Nguồn / đích**: worker đọc nguồn HD thẳng từ kho HD2 trên ổ 3090 (tập đã giải phóng không phải tải về VM) hoặc tải `source_hd.mp4` từ VM (tập chưa giải phóng); bản dọc ghi vào kho (đúng tên HD1 G3 `[HD Mobile] …`), báo sha256 + kích thước cho VM → VM ghi `full/meta.json` như đã giải phóng (HD1 G1 / G2). Không đẩy file ~1 GB qua tunnel trừ khi web cần tải.
- **G3 Đồ họa giống hệt**: VM dựng sẵn filter graph (`render.full.filter_graph`) + ảnh / dòng chữ panel và gửi kèm lease; worker chỉ chạy ffmpeg (decode → filter → encode). Bố cục, chữ giữ nguyên; key bản dọc thêm trường encoder để bản NVENC và x264 không lẫn nhau.
- **G4 Encoder**: `h264_nvenc` (giữ h264 để `verify()` / YouTube / thiết bị cũ không đổi), tham số chọn theo §4 (ứng viên: `-preset p7 -tune hq -rc vbr -cq <20|23> -b:v 0 -spatial-aq 1 -temporal-aq 1 -bf 3`). Cấu hình `[render.vertical] encoder = "x264" | "nvenc"` (mặc định `x264` = như cũ).
- **G5 Chung GPU với Ollama**: mặc định chạy song song (không `yield_to_ollama`), tối đa 1 job bản dọc trên 3090; nếu §4 cho thấy thời gian AI / tập tăng > 10 % khi NVENC chạy → worker hỏi `may-run` như enhance và nhường. Fallback: 3090 tắt / worker lỗi → job bản dọc quay về VM (libx264) sau thời hạn lease.
- **G6 Bảo mật / dependency**: không thêm dependency (stdlib + ffmpeg sẵn có trên 3090); dùng token worker hiện có hoặc token riêng cùng cơ chế; worker không chạy lệnh tùy ý — VM gửi dữ liệu graph, worker tự ráp danh sách tham số cố định.

## 3. Ngoài scope

Short / khai thị / ghép chủ đề bằng NVENC; HEVC / AV1; ngắt job bản dọc đang chạy trên VM; đổi tham số x264 trên VM.

## 4. Phép đo HUMAN LEAD chạy trên 3090 (trước khi chọn)

PowerShell trên 3090, dùng ffmpeg của worker enhance. Chọn một tập bất kỳ trong `E:\KinhDiaTang_HD`; mọi bản mã hóa cắt **cùng đoạn 60 s** (từ phút 10). Filter dưới đây dựng đúng khung video của bản dọc thật (crop 930×1080 → 1080×1254 lanczos tại y = 293) và hai ô panel trơn ở vị trí panel thật (chữ không ảnh hưởng so sánh encoder).

```powershell
$ff  = "$env:USERPROFILE\enhance-worker\ffmpeg\bin\ffmpeg.exe"   # hoặc 'ffmpeg' nếu có trong PATH
$src = "E:\KinhDiaTang_HD\[HD] Kinh Địa Tạng - Tập 10.mp4"        # đổi theo tên file thật
$dir = "E:\rv1-test"; New-Item -ItemType Directory -Force $dir | Out-Null; Set-Location $dir
$vf  = "crop=930:1080:495:0,scale=1080:1254:flags=lanczos,setsar=1,pad=1080:1920:0:293:color=black," +
       "drawbox=x=81:y=22:w=918:h=249:color=0x3a2a1a:t=fill,drawbox=x=81:y=1569:w=918:h=329:color=0x3a2a1a:t=fill,format=yuv420p"
$aud = "-c:a aac -b:a 192k -ar 48000 -ac 2 -movflags +faststart".Split(' ')

# 1. Đoạn 60 s nguồn (copy, không mã hóa lại)
& $ff -y -hide_banner -ss 600 -i $src -t 60 -c copy ref60.mp4
# 2. Bản tham chiếu không mất mát (để chấm điểm)
& $ff -y -hide_banner -i ref60.mp4 -vf $vf -c:v libx264 -preset ultrafast -qp 0 -an ref_lossless.mkv
# 3. libx264 như VM hiện nay (in số giây)
(Measure-Command { & $ff -y -hide_banner -i ref60.mp4 -vf $vf -c:v libx264 -preset medium -crf 22 -pix_fmt yuv420p @aud x264_crf22.mp4 }).TotalSeconds
# 4. NVENC hai mức chất lượng (in số giây)
foreach ($cq in 23, 20) {
  (Measure-Command { & $ff -y -hide_banner -i ref60.mp4 -vf $vf -c:v h264_nvenc -preset p7 -tune hq -rc vbr -cq $cq -b:v 0 `
     -spatial-aq 1 -temporal-aq 1 -bf 3 -pix_fmt yuv420p @aud "nvenc_cq$cq.mp4" }).TotalSeconds
}
# 5. Điểm chất lượng so với bản không mất mát (VMAF nếu bản ffmpeg có libvmaf; luôn có SSIM / PSNR) + kích thước
foreach ($f in "x264_crf22.mp4", "nvenc_cq23.mp4", "nvenc_cq20.mp4") {
  "== $f  $([math]::Round((Get-Item $f).Length / 1MB, 1)) MB"
  & $ff -hide_banner -i $f -i ref_lossless.mkv -lavfi "[0:v][1:v]ssim;[0:v][1:v]psnr" -f null - 2>&1 | Select-String "SSIM|PSNR"
  & $ff -hide_banner -i $f -i ref_lossless.mkv -lavfi "libvmaf=n_threads=8" -f null - 2>&1 | Select-String "VMAF score"
}
# 6. Xem bằng mắt: ghép cạnh nhau 20 s (trái x264, phải NVENC cq23)
& $ff -y -hide_banner -i x264_crf22.mp4 -i nvenc_cq23.mp4 -filter_complex "[0:v][1:v]hstack" -t 20 -c:v libx264 -crf 12 -an sbs.mp4
```

Song song Ollama (khi web đang chạy AI cả bộ Kinh Địa Tạng): mở cửa sổ thứ hai chạy `nvidia-smi dmon -s um -c 60` (cột `enc` / `sm` / `fb`), rồi chạy lại bước 4 ba lần liên tiếp; ghi giờ bắt đầu / kết thúc. ORCHESTRATOR so thời gian job AI trong log web ở khoảng giờ đó với lúc không có NVENC.

Gửi lại: thời gian bước 3 / 4, kích thước + SSIM / PSNR / VMAF bước 5, cảm nhận `sbs.mp4`, VRAM (`fb`) và `enc` % khi chạy cùng Ollama.

## 5. Câu hỏi cho HUMAN LEAD sau khi đo

1. NVENC `cq` nào đạt (hay giữ x264 trên VM)?
2. G5: chạy song song Ollama không nhường, hay nhường như enhance?
3. Làm RV1 (worker bản dọc trên 3090, G1–G6) ngay, hay gác vì RENDER-short-first + `render_workers = 3` đã đủ?
