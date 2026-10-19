# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

Auto Short (cập nhật 2026-10-19): `main` = `a3627a6`, 8080 chạy đúng commit này (worktree `../youtube-auto-short-web`, restart: hỏi HUMAN LEAD rồi `~/.local/bin/auto-short-web-restart`, mật khẩu ở `~/.local/share/auto-short/web.env` mode 600). **Thư mục dự án chuyển 2026-10-19** sang `~/projects/youtube-auto-short` + `~/projects/youtube-auto-short-web` (đường dẫn tuyệt đối trong 229 manifest, theme index / plan / proposals / video ghép đã viết lại giữ nguyên vân tay — 37 clip vẫn dùng AI cache, 2 plan vẫn approved; bản gốc JSON trước khi sửa: `~/.cache/auto-short-move-backup-20261019/`, xóa được sau khi chạy ổn; config, editable install, `auto-short-web-restart`, `codex-usage` đã sửa). Đã merge 2026-10-19: TC2 + TC3 ghép video ngang theo chủ đề (#98), FIX giữ nguồn video có khai thị (#99), FIX worker enhance lỗi CUDA (#100), framework Codex IMPLEMENTER (#101; kit ai-dev-framework #9), TC2.3 ghép một bước + tab điện thoại + nút Xem (#102), FIX ân hạn tự dọn 5 ngày (#103), CP8.37 khôi phục nguồn (#104). `config.toml` `[storage]`: `auto_archive = true`, `auto_archive_grace_minutes = 7200`. Kho nguồn gốc `work/_theme_sources/` (13 video, tải dần bằng `python -m auto_short.theme_render.sources`). Codex: quy trình `.claude/rules/execution.md`, quota `scripts/codex-usage.py`.

TC1 + TC-WEB1 (2026-10-18): HUMAN LEAD đã test preview LAN thành công và authorize integration/rollout. Web production `youtube:web` đã rollout code merge PR #96, giữ 9 parked-HD jobs và mật khẩu/tokens hiện hành; lanes rảnh khi restart, queue đã resume như trước. Trang read-only `/playlists/{pid}/theme-index` không sinh AI/index trên GET; dataset thật được kiểm vẫn 0 eligible/2 ineligible. Preview synthetic còn chạy trong tmux `tc-web1-preview`, scratch `/tmp/tc-web1-human-preview-tqmanfv4`, LAN `10.8.102.102:8099`, password thử chỉ trong scratch `.preview-password`; production không chứa fixture synthetic. Evidence/giới hạn: `docs/tasks/TC-WEB1-theme-index-preview.md`; TC2/TC3 chưa được implement bởi scope này.

Auto Short (cập nhật 2026-10-18): `main` = `ad59dfe`. Đã merge sau 2026-10-17: CP8.34 tải lần lượt nhiều file trên trang bộ kinh + giữ màn hình sáng bằng video câm lặp (#88), FIX-keepawake-mp4 (#89), FIX-runner-stop dừng server không treo / không để ffmpeg mồ côi (#90), CP8.36 làn render song song khi CPU bận < 60 % (`[web] render_workers = 2`, `render_max_cpu = 0.6`; #91), CP8.35 bấm "Xử lý" tự tạo luôn bản dọc sau khi có HD (#92); manual test HUMAN LEAD đạt 2026-10-18. Wake Lock trên http cần cờ Chrome `unsafely-treat-insecure-origin-as-secure` cho `http://10.8.102.102:8080` (điện thoại HUMAN LEAD đã bật).

Auto Short (cập nhật 2026-10-17): `main` = `508a94c`. Đã merge sau 2026-10-13: FIX-youtube-id-dash (#84, id YouTube bắt đầu `-` / `_`), CP8.32 bản dọc / bản ngang HD từ video gốc ≥ 720p + nút "Tạo bản dọc cả bộ" + hủy bản dọc (#85), CP8.33 yêu thích Short / khai thị (♥, trang `/playlists/{pid}/favorites`) + ghép video dài / lặp / tự ghép theo thời lượng, giữ clip yêu thích khi xóa tập (#86; manual test HUMAN LEAD đạt 2026-10-17). Video ghép ở `output/_compilations/<playlist_id>/`.

Auto Short (cập nhật 2026-10-09): `main` = `6c36861`. Đã merge sau 2026-10-04: CP13.3 đo chất lượng enhance (#73), CP8.30 tìm ảnh theo từ khóa (#76), FIX-enhance-yield (#77), CP8.31 zip tick "Đã đăng" + xuất bài đăng `.docx` (python-docx, theo khoảng 10 tập, có / không hình) + nút tải trên trang bộ kinh + bố cục mobile + huy hiệu tiến độ + enhance sang tab Theo dõi (#78; manual test HUMAN LEAD đạt 2026-10-09). VM IP hiện `10.8.102.102` (đổi 2026-10-08).

Auto Short (cập nhật 2026-10-04): `main` = `abd6704`. Phiên 2026-10-04 đã merge: CP13.2 "Chuẩn bị + HD" (#62), CP8.23 ngưỡng im lặng tự chọn (#63), CP8.24 văn bản gốc nhiều video / trang (#64), FIX-doc-match-050 (#65), FIX-youtube-botcheck-wait (#66), CP8.26 ưu tiên (#67), CP8.28 tab Theo dõi (#68), FIX-post-title-upper (#69), FIX-monitor-labels (#70), CP8.27 tải bản ngang HD + bản dọc cả tập (#71), CP8.29 chuẩn bị song song + nice (#72), CP13.4 GFPGAN cả tập (#74). CP8.25 (tự tìm văn bản gốc): HUMAN LEAD bỏ.

Đang chạy trên 8080 (2026-10-04 tối):

- Bộ Địa Tạng (playlist `PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`, 102 tập; văn bản gốc `DiaTangBoTatBonNguyenKinhGiangKy_01`, 2 video / trang): tập 3–102 "Chuẩn bị + HD" (làn prepare 4 song song); tập 1, 2 đã cắt lại theo CP8.23 (6 + 5, 8 + 6 Short / khai thị). Chưa bấm "Chạy tiếp cả bộ".
- Enhance BẬT, cấu hình GFPGAN (`[enhance] face = "gfpgan_v1.4"`); worker v3 trên 3090 + 3050 (cài lại 2026-10-04, self-test "GFPGAN OK"); 7 tập HD cũ đã bấm "Enhance lại"; ước ≈ 6 h / tập (3090), ≈ 13 h (3050), ≈ 18 ngày cả bộ. 3090 GPU 100 % — thêm worker không nhanh hơn.
- 13 video bộ khác lỗi YouTube chặn bot đêm 2026-10-03 đã xếp lại đầu hàng (một số đã xong).

Hạ tầng: VM 32 nhân, 125 GB RAM; IP đổi `10.8.102.101` → **`10.8.102.100`** khi reboot 2026-10-04 (DHCP) — ssh config 3090 / 3050 đã sửa; nên xin IP cố định. `setup-gpu-node-v4.ps1` mặc định `-ServerHost 10.8.102.101` (cũ) → chạy với `-ServerHost 10.8.102.100`. `config.toml` repo chính: `[enhance] lease_hours = 12`, `face = "gfpgan_v1.4"`; `[web] prepare_workers = 4`, `worker_nice = 10`; `[transcript.whisper] cpu_threads = 24`, `cpu_threads_per_job = 8`; `[render] jobs = 2` (bản sao lưu `~/.cache/config.toml.bak-pre-*`).

Chinese Learning (CL1): HUMAN LEAD bỏ 2026-10-19; code / test / config / nhánh đã gỡ bởi `docs/tasks/CHG-remove-cl1.md`. Bundle sao lưu nhánh: `~/.local/share/auto-short/cl1-branches-2026-10-19.bundle`. CL1 C0 / C1 (quy ước host) vẫn hiệu lực.

Đọc Kinh (SR1 + SR2, `docs/decisions/SR1-sutra-reader-contract.md`, `docs/decisions/SR2-khaithi-library-contract.md`): MERGED #82 (2026-10-13), manual test HUMAN LEAD OK. Trang `/sutras` (tab Đọc Kinh \| Khai thị). Dữ liệu kinh ở `work/_sutras/` (8 bộ, không trong git — bản quyền); dependency mới `pypdf==6.20.0` (env `auto-short` đã cài).

Web chạy cho HUMAN LEAD trong tmux `youtube:web` từ worktree `../youtube-auto-short-web` (detached, ghim code merge PR #96 `a77f04a` (TC1 + TC-WEB1), 2026-10-18), `PYTHONPATH=<worktree>/src`, `--config` repo chính; mật khẩu chỉ ở env của pane. Khởi động lại: `~/.local/bin/auto-short-web-restart` (đọc mật khẩu từ `web.env`, từ chối khi làn bận). Sau reboot VM: tmux mới `youtube:web` trong `~/projects/youtube-auto-short-web`, `conda activate auto-short`, `source ~/.nvm/nvm.sh`, rồi chạy script trên.

## Next proposed action

1. HUMAN LEAD cập nhật `tools/enhance_worker/worker.py` trên máy 3090 + 3050 (bản #100: thoát mã 4 khi lỗi CUDA); ORCHESTRATOR kiểm log server sau đó.
2. Manual test HUMAN LEAD trên điện thoại: ghép theo chủ đề (TC2.3) và "Khôi phục nguồn" (CP8.37) trên tập đã dọn; chấm tiêu đề AI (TC2.2).
3. FIX đề xuất (chưa duyệt): `tests/test_web_lanes_cp810.py::test_lanes_overlap_fifo_and_render_job` chập chờn khi VM tải nặng (chạy riêng đạt) — đổi chờ theo thời gian sang chờ điều kiện.
4. Chất lượng AI TC1 / TC2 (ghi nhận chạy thật): synopsis đôi khi là mẩu ngắn, chủ đề có xu hướng gom theo tập; prompt qwen3:30b `think=true` ≈ 1–2 phút / clip.
5. Cũ, vẫn mở: CP8.34 tránh tải lại khi token `aborted`; HTTPS cho 8080; FIX `setup-enhance-worker.ps1` (S1); CP14 Whisper GPU tạm gác (số đo CPU cũ `~/.cache/auto-short-cp14-test/` đã xóa — đo lại khi mở lại).

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper trong `models/` (gitignored).
