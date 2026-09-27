# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

Chuỗi CP8 → CP8.1 → CP8.2 → CP8.3 → CP8.5 → CP8.6 → CP8.7: READY (manual test HUMAN LEAD 2026-09-27 đạt), push chung một PR từ `feature/cp8.7-playlist` (HUMAN LEAD). CP8.4 upload YouTube: planned, chưa lên lịch.

Web đang chạy cho HUMAN LEAD từ worktree `../youtube-auto-short-web` (checkout tách của `feature/cp8.7-playlist`), config local trỏ `work/`, `output/`, `models/` của repo chính; mật khẩu chỉ qua env, không lưu.

## Next proposed action

1. HUMAN LEAD merge PR của chuỗi CP8–CP8.7.
2. Sau merge: chạy web từ repo chính (`pip install -e ".[dev,web]"`, `AUTO_SHORT_WEB_PASSWORD=… auto-short web`), dọn các worktree tạm.
3. Việc kế tiếp HUMAN LEAD chọn: sửa hashtag theo bộ kinh (backlog, code dở ở nhánh local `wip/playlist-hashtags`), CP8.4 upload YouTube, CP9, CP10.

Đây là PROPOSED, không authorize implementation tiếp theo.

## Open decisions

- Không.

## Blockers

- Không. Runtime: conda env `auto-short` (Python 3.12); YouTube cần `node` trên PATH (nvm); model Whisper tải vào `models/` (gitignored).
