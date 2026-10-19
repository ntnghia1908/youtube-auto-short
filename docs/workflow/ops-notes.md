# Ops Notes

| Metadata | Value |
|---|---|
| Status | OPERATIONAL NOTES — NOT AUTHORITY |

Ghi chú vận hành ít dùng, tách từ `current-state.md` (CHG-current-state-trim). Không nạp mỗi phiên; chỉ đọc khi việc đang làm cần. Có thể đã cũ — kiểm lại trên máy trước khi dựa vào.

## Web 8080

- Sau reboot VM: tmux mới `youtube:web` trong `~/projects/youtube-auto-short-web`, `conda activate auto-short`, `source ~/.nvm/nvm.sh`, rồi `~/.local/bin/auto-short-web-restart`.
- Worktree web chạy detached, `PYTHONPATH=<worktree>/src`, `--config` của repo chính; mật khẩu chỉ trong env pane và `web.env` (mode 600).
- Wake Lock trên http cần cờ Chrome `unsafely-treat-insecure-origin-as-secure` cho `http://10.8.102.102:8080` (điện thoại HUMAN LEAD đã bật).
- Trang `/playlists/{pid}/theme-index` read-only, không sinh AI / index trên GET.

## Backup / dữ liệu ngoài git

- Chuyển thư mục 2026-10-19: đường dẫn tuyệt đối trong 229 manifest, theme index / plan / proposals / video ghép đã viết lại giữ nguyên vân tay. Bản JSON gốc trước khi sửa: `~/.cache/auto-short-move-backup-20261019/` — xóa được sau khi chạy ổn.
- Bundle nhánh CL1: `~/.local/share/auto-short/cl1-branches-2026-10-19.bundle`.
- Kinh / khai thị: `work/_sutras/` (8 bộ, không trong git — bản quyền).
- Video ghép: `output/_compilations/<playlist_id>/`.

## Hạ tầng

- VM 32 nhân, 125 GB RAM; IP DHCP, hiện `10.8.102.102` (đổi 2026-10-08; trước đó `.100`, `.101`) — nên xin IP cố định. ssh config máy 3090 / 3050 phải theo IP hiện hành.
- `setup-gpu-node-v4.ps1` mặc định `-ServerHost 10.8.102.101` (cũ) → chạy với `-ServerHost <IP hiện hành>`.
- Enhance: worker trên 3090 + 3050, `[enhance] face = "gfpgan_v1.4"`, `lease_hours = 12`; ước ≈ 6 h / tập (3090), ≈ 13 h (3050); 3090 GPU 100 % — thêm worker không nhanh hơn.

## Tuning `config.toml` repo chính

`[web] prepare_workers = 4`, `worker_nice = 10`, `render_workers = 2`, `render_max_cpu = 0.6`; `[transcript.whisper] cpu_threads = 24`, `cpu_threads_per_job = 8`; `[render] jobs = 2`. Bản sao lưu cũ: `~/.cache/config.toml.bak-pre-*`.

## Ghi nhận cũ (2026-10-04, chưa kiểm lại)

- Bộ Địa Tạng (playlist `PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`, 102 tập; văn bản gốc `DiaTangBoTatBonNguyenKinhGiangKy_01`, 2 video / trang): tập 3–102 "Chuẩn bị + HD"; tập 1, 2 cắt lại theo CP8.23. Lúc đó chưa bấm "Chạy tiếp cả bộ".
- CP14 Whisper GPU: số đo CPU cũ đã xóa — đo lại khi mở lại.
