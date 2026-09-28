# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

Auto Short: CP8–CP8.9 và CP8.11 đã merge (trừ CP8.4). CP8.4 upload YouTube: BỎ QUA (HUMAN LEAD 2026-09-27, `AUTO_SHORT_CHECKPOINT_PLAN.md`); Short vẫn tải về và đăng tay. CP8.9 video khai thị (+ A1–A3) đã merge (PR #19, `7e347a3`); dữ liệu web test (tập khai thị `.kt` + Short mới) đã chuyển vào `work/` / `output/` chính, không ghi đè tập có sẵn. CP8.11 nhận dạng tên bộ kinh / số tập + ô "Tên bộ kinh" đã merge (PR #20, `716e858`), manual test HUMAN LEAD đạt 2026-09-28. CP8.10 hàng đợi theo làn prepare / ai / render đã merge (PR #22, `8fa8596`; HUMAN LEAD merge 2026-09-28 khi chưa chạy manual test checklist của contract — kiểm trên web 8080 khi dùng). Dữ liệu chạy thật CP8.10 (`4oOZz2CBz3g`, `4oOZz2CBz3g.kt`, `Irmcm5Ep478`, `E4QhRRXFbIM`) đã chuyển vào `work/` / `output/` chính (không ghi đè, mọi stage `done`). Tập `.kt` làm trước `c76d55e` (`7axON1RpRjo.kt`, `7w4nSj3PguI.kt`, `W2d-xS4ttTw.kt`) có analysis stale: chạy lại sẽ làm lại analysis + selection.

Chinese Learning (CL1, bản đồ: `docs/tasks/CL1-roadmap.md`): CL1.1 MERGED (PR #12); CL1.2 MERGED (PR #15, `38d828f`). G6A (Pinyin authority) và G6B (model dịch): PENDING HUMAN LEAD DECISION — chưa chọn model. CL1.3: PENDING G6A/G6B + C10. CL1.4: PENDING CL1.3.

Web chạy cho HUMAN LEAD trong tmux `youtube:web` từ worktree `../youtube-auto-short-web` (detached, ghim `8fa8596`, `[web] queue_mode` mặc định `lanes`, `PYTHONPATH=<worktree>/src`, `--config` của repo chính → `work/`, `output/`, `models/` repo chính); mật khẩu chỉ qua env của pane, không lưu.

## Next proposed action

1. G6A — thí nghiệm + khuyến nghị chiến lược Pinyin authority (task contract riêng, từ `origin/main` sạch); không đổi production Pinyin trước khi HUMAN LEAD duyệt.
2. Sau G6A: G6B → CL1.3 (+ C10) → CL1.4 theo roadmap.
3. Auto Short tiếp theo (PROPOSED): CP9, CP10. Ngoài scope ghi nhận ở CP8.10: fixture `cfg` (`tests/conftest.py`) để `render.output_dir` tương đối → một test web ghi `output/abcdefghijk/` vào thư mục chạy pytest (task riêng).

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper tải vào `models/` (gitignored).
