# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

CP8–CP8.7 đã merge (PR #10, `main` = `eab3134`). CP8.8 hashtag riêng từng bộ kinh: READY (manual test HUMAN LEAD cho đạt 2026-09-27), PR chờ merge (`docs/tasks/CP8.8-playlist-hashtags.md`), worktree `../youtube-auto-short-hashtags`, nhánh `feature/cp8.8-playlist-hashtags`; code dở tham khảo ở nhánh local `wip/playlist-hashtags`. CP8.4 upload YouTube: planned, chưa lên lịch.

Web chạy cho HUMAN LEAD trong tmux `youtube:web` từ worktree `../youtube-auto-short-web` (detached, ghim `eab3134`, `PYTHONPATH=<worktree>/src`, `--config` của repo chính → `work/`, `output/`, `models/` repo chính); mật khẩu chỉ qua env của pane, không lưu.

Session song song hướng CL1: worktree `../youtube-auto-short-cl1`, nhánh `feature/cl1-chinese-learning` — không sửa từ session khác.

## Next proposed action

1. HUMAN LEAD merge PR CP8.8.
2. Sau merge CP8.8: đưa worktree web lên commit mới và khởi động lại web; dọn worktree `../youtube-auto-short-hashtags`, nhánh `wip/playlist-hashtags` (HUMAN LEAD quyết).
3. Việc kế tiếp HUMAN LEAD chọn: CP8.4 upload YouTube, CP9, CP10.

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper tải vào `models/` (gitignored).
