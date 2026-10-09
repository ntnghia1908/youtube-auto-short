# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

Auto Short (cập nhật 2026-10-09): `main` = `6c36861`. Đã merge sau 2026-10-04: CP13.3 đo chất lượng enhance (#73), CP8.30 tìm ảnh theo từ khóa (#76), FIX-enhance-yield (#77), CP8.31 zip tick "Đã đăng" + xuất bài đăng `.docx` (python-docx, theo khoảng 10 tập, có / không hình) + nút tải trên trang bộ kinh + bố cục mobile + huy hiệu tiến độ + enhance sang tab Theo dõi (#78; manual test HUMAN LEAD đạt 2026-10-09). VM IP hiện `10.8.102.102` (đổi 2026-10-08).

Auto Short (cập nhật 2026-10-04): `main` = `abd6704`. Phiên 2026-10-04 đã merge: CP13.2 "Chuẩn bị + HD" (#62), CP8.23 ngưỡng im lặng tự chọn (#63), CP8.24 văn bản gốc nhiều video / trang (#64), FIX-doc-match-050 (#65), FIX-youtube-botcheck-wait (#66), CP8.26 ưu tiên (#67), CP8.28 tab Theo dõi (#68), FIX-post-title-upper (#69), FIX-monitor-labels (#70), CP8.27 tải bản ngang HD + bản dọc cả tập (#71), CP8.29 chuẩn bị song song + nice (#72), CP13.4 GFPGAN cả tập (#74). CP8.25 (tự tìm văn bản gốc): HUMAN LEAD bỏ.

Đang chạy trên 8080 (2026-10-04 tối):

- Bộ Địa Tạng (playlist `PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`, 102 tập; văn bản gốc `DiaTangBoTatBonNguyenKinhGiangKy_01`, 2 video / trang): tập 3–102 "Chuẩn bị + HD" (làn prepare 4 song song); tập 1, 2 đã cắt lại theo CP8.23 (6 + 5, 8 + 6 Short / khai thị). Chưa bấm "Chạy tiếp cả bộ".
- Enhance BẬT, cấu hình GFPGAN (`[enhance] face = "gfpgan_v1.4"`); worker v3 trên 3090 + 3050 (cài lại 2026-10-04, self-test "GFPGAN OK"); 7 tập HD cũ đã bấm "Enhance lại"; ước ≈ 6 h / tập (3090), ≈ 13 h (3050), ≈ 18 ngày cả bộ. 3090 GPU 100 % — thêm worker không nhanh hơn.
- 13 video bộ khác lỗi YouTube chặn bot đêm 2026-10-03 đã xếp lại đầu hàng (một số đã xong).

Hạ tầng: VM 32 nhân, 125 GB RAM; IP đổi `10.8.102.101` → **`10.8.102.100`** khi reboot 2026-10-04 (DHCP) — ssh config 3090 / 3050 đã sửa; nên xin IP cố định. `setup-gpu-node-v4.ps1` mặc định `-ServerHost 10.8.102.101` (cũ) → chạy với `-ServerHost 10.8.102.100`. `config.toml` repo chính: `[enhance] lease_hours = 12`, `face = "gfpgan_v1.4"`; `[web] prepare_workers = 4`, `worker_nice = 10`; `[transcript.whisper] cpu_threads = 24`, `cpu_threads_per_job = 8`; `[render] jobs = 2` (bản sao lưu `~/.cache/config.toml.bak-pre-*`).

Chinese Learning (CL1, bản đồ: `docs/tasks/CL1-roadmap.md`): CL1.1, CL1.2 MERGED. G6A / G6B: PENDING HUMAN LEAD DECISION. CL1.3, CL1.4 chờ.

Web chạy cho HUMAN LEAD trong tmux `youtube:web` từ worktree `../youtube-auto-short-web` (detached, ghim `6c36861` = `main` sau CP8.31, 2026-10-09), `PYTHONPATH=<worktree>/src`, `--config` repo chính; mật khẩu chỉ ở env của pane. Khởi động lại: Ctrl-C trong pane rồi gõ thẳng `PYTHONPATH=/home/ntnghia/youtube-auto-short-web/src auto-short web --config /home/ntnghia/youtube-auto-short/config.toml` (không dùng phím Up — dòng trước có `read -rs` hỏi mật khẩu); chỉ khi làn render rảnh (dòng `render: rendered N/N clips` / `job … done … Shorts (`). Sau reboot VM: tmux mới, `conda activate auto-short`, `source ~/.nvm/nvm.sh`, `set -a; source ~/.local/share/auto-short/enhance-tokens.env; set +a`, HUMAN LEAD gõ mật khẩu.

## Next proposed action

1. PR #73 (CP13.3 đo chất lượng enhance: script + hướng dẫn + báo cáo, đã review) — chờ HUMAN LEAD merge; điền số GPU thật 3090 / 3050 (`~/.cache/auto-short-cp133-test/results/cp133-results-{3090,3050}.zip`) vào báo cáo.
2. FIX nhỏ `tools/enhance_worker/windows/setup-enhance-worker.ps1` (S1, chưa có contract): self-test dừng script vì `UserWarning` trên stderr (PowerShell 5.1 + `ErrorActionPreference = Stop`); facexlib tải lại 2 trọng số dò mặt vào `enhance-worker\models` (setup đặt ở `facexlib\weights`); `setup-gpu-node-v4.ps1` mặc định IP cũ; `auto-fix-gpu-v4.ps1` báo lỗi giả khi tunnel đã lên.
3. Khi tập 1 Địa Tạng có HD GFPGAN (≈ 0 h 2026-10-05 VN): HUMAN LEAD xem Short / bản dọc; quyết "Chạy tiếp cả bộ".
4. CP14 Whisper trên GPU: tạm gác (worktree `../youtube-auto-short-wgpu`); số đo GPU chưa có.
5. Bản dọc (CP8.27): manual test trên điện thoại.
6. Dọn dữ liệu thử: `~/.cache/auto-short-cp8{27,28,29}-test/`, `~/.cache/auto-short-dt12-backup/`, `~/.cache/auto-short-cp13{2,4}-test/` (giữ `cp133-test` tới khi #73 merge).

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper trong `models/` (gitignored).
