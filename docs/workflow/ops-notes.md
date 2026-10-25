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

## Kho 3090 (HD1 / HD2, từ 2026-10-25)

- Task `AutoShortStore`: cài `%LOCALAPPDATA%\AutoShortStore`, root `E:\AutoShortStore`, Kinh Địa Tạng `E:\KinhDiaTang_HD`.
- VM tới kho qua `RemoteForward 127.0.0.1:18090` trong ssh block `gpu-worker-v4` (task `EnhanceWorker-Tunnel`). Đổi ssh config phải kill `ssh.exe` cũ; `Stop-ScheduledTask` không đủ.
- `config.toml` `[store] enabled = true`, url `http://127.0.0.1:18090`; backup `~/.local/share/auto-short/config.toml.bak-2026-10-25-pre-store`. Token `~/.local/share/auto-short/store.env` (mode 600, script restart tự source).
- Đo ≈ 43 MB/s VM←3090.
- Script backup `~/.local/share/auto-short/backup-hd1/backup.ps1` (generator `scripts/backup/make_backup.py`): luôn truyền `-Dest E:\KinhDiaTang_HD`.

## Hạ tầng

- VM 32 nhân, 125 GB RAM; IP DHCP, hiện `10.8.102.102` (đổi 2026-10-08; trước đó `.100`, `.101`) — nên xin IP cố định. ssh config máy 3090 / 3050 phải theo IP hiện hành.
- `setup-gpu-node-v4.ps1` mặc định `-ServerHost 10.8.102.101` (cũ) → chạy với `-ServerHost <IP hiện hành>`.
- Enhance: worker trên 3090 (+ A100 mượn), `[enhance] face = "gfpgan_v1.4"`, `lease_hours = 12`; ước ≈ 6 h / tập (3090); 3090 GPU 100 % — thêm worker không nhanh hơn.
- 3050 thôi làm enhance từ 2026-10-24 (HUMAN LEAD; máy giữ cho việc GPU khác sau này): token `rtx3050` đã gỡ khỏi `enhance-tokens.env` (backup `~/.cache/enhance-tokens.env.bak-pre-drop-3050-20261024`), hiệu lực từ lần restart web kế tiếp. Dùng lại: chép dòng token từ backup rồi restart web.

## A100 mượn (Slurm khoa, từ 2026-10-24, vài ngày)

- Gateway `ntnghia@10.8.102.15` (ngoài: `125.234.238.107`), node `gpu01` 1 × A100-SXM4-80GB, không sudo; mọi việc GPU qua Slurm. Giới hạn tài khoản: 16 CPU, 1 GPU, 32 GB RAM, `--time` ≤ 3 ngày / job. Internet cụm ≈ 0,3–1 MB/s, hay đứt (chép từ 3090 qua LAN ≈ 11–19 MB/s).
- Tất cả trong `/shared/users/ntnghia/autoshort`: `autoshort-a100.sbatch` (Ollama cổng 11534, context 32768, 2 slot, KV q8_0 + 3 enhance worker `a100` / `a100b` / `a100c` + tunnel SSH tự nối lại), env `envs/enhance-worker` (torch 2.5.1+cu124), `enhance/config*.json` (token, mode 600), log `logs/`, `enhance/logs/`. Job hết hạn: `sbatch autoshort-a100.sbatch` lại; xem `squeue -u ntnghia`.
- A100 không có NVENC (phần cứng) → `libx264`; nghẽn ở luồng CPU của worker (GPU ≈ 7 % / worker), nên chạy 3 worker. Đo đầu: ≈ 2,3 phút / đoạn (3090 ≈ 5,5).
- VM: tunnel = khóa `autoshort-a100-tunnel` trong `~/.ssh/authorized_keys` (chỉ forward `127.0.0.1:8080` / listen `127.0.0.1:11438`); `config.toml` `[selection]` / `[titling]` / `[post]` `ollama_host = "http://127.0.0.1:11438"`, `[enhance] yield_workers = []`; token `a100*` trong `enhance-tokens.env`.
- **Trả máy:** `scancel` job; trong `config.toml` xóa 3 dòng `ollama_host` + đặt `yield_workers = ["rtx3090"]` (backup `~/.cache/config.toml.bak-pre-a100-*`); bỏ `a100*` khỏi `AUTO_SHORT_ENHANCE_TOKENS`; xóa dòng `autoshort-a100-tunnel` trong `authorized_keys`; restart web; xóa `/shared/users/ntnghia/autoshort` nếu admin yêu cầu.

## Tuning `config.toml` repo chính

`[web] prepare_workers = 4`, `worker_nice = 10`, `render_workers = 2`, `render_max_cpu = 0.6`; `[transcript.whisper] cpu_threads = 24`, `cpu_threads_per_job = 8`; `[render] jobs = 2`. Bản sao lưu cũ: `~/.cache/config.toml.bak-pre-*`.

## Ghi nhận cũ (2026-10-04, chưa kiểm lại)

- Bộ Địa Tạng (playlist `PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`, 102 tập; văn bản gốc `DiaTangBoTatBonNguyenKinhGiangKy_01`, 2 video / trang): tập 3–102 "Chuẩn bị + HD"; tập 1, 2 cắt lại theo CP8.23. Lúc đó chưa bấm "Chạy tiếp cả bộ".
- CP14 Whisper GPU: số đo CPU cũ đã xóa — đo lại khi mở lại.
