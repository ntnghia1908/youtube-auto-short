# Task: PUB2 — CLI gắn thumbnail tập cho video đã upload tay (YouTube Data API)

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review, full suite, chạy thật với kênh khi HUMAN LEAD có OAuth client
- Implementer: codex — module mới tự chứa, test không cần mạng / socket
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: `docs/decisions/PUB2-youtube-thumbnail-set.md` (ACCEPTED 2026-10-24)
- Parallel group: PKG-2026-10-24b (song song PKG3, owned paths rời nhau, worktree riêng)
- Owned paths: `src/auto_short/publish/` (mới), `tests/test_publish_thumbs.py` (mới), `docs/decisions/PUB2-youtube-thumbnail-set.md`, contract này
- Dependencies: PKG2.2 (#138) — `episode.valid_files` trả cả hai khuôn; không import gì từ branch đó ngoài API `episode` có sẵn trên main
- Base commit / branch: `a829a5d` / `feature/pub2-thumbnail-set`
- Human Lead approval: HUMAN LEAD 2026-10-24 ("Đồng ý")
- Implementation authorized: YES

## Goal

`python -m auto_short.publish auth` đăng nhập kênh bằng device flow (in URL + mã). `python -m auto_short.publish thumbs --playlist <pid>` in bảng video YouTube ↔ ảnh thumbnail; thêm `--apply` thì gắn ảnh bằng `thumbnails.set`. Ghép theo tên file gốc lúc upload (`fileDetails.fileName`).

## Scope

- In scope: package `auto_short.publish` (OAuth device flow + refresh, gọi API bằng `urllib`, ghép, chạy thử / apply, nhật ký); CLI; test.
- Out of scope: upload video, sửa metadata / trạng thái / playlist YouTube, route web, config `config.toml` mới, Short, Analytics.

## Authority / key decisions

- Decision PUB2 G1–G5 (canonical). Chi tiết cục bộ của task:
  - Đường dẫn mặc định (cờ CLI `--client` / `--token` đổi được): `~/.local/share/auto-short/youtube-client.json` (JSON tải từ Google Cloud, khóa `installed` hoặc gốc có `client_id` / `client_secret`), `~/.local/share/auto-short/youtube-token.json` (ghi atomic, mode 600, tạo thư mục nếu thiếu). Không in / log access token, refresh token, client secret.
  - Scope: thử `https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload`; Google trả `invalid_scope` → thử lại `https://www.googleapis.com/auth/youtube` và in rõ đã dùng scope nào.
  - Device flow: `POST https://oauth2.googleapis.com/device/code`, poll `https://oauth2.googleapis.com/token` (grant `urn:ietf:params:oauth:grant-type:device_code`, tôn trọng `interval` / `slow_down`, hết `expires_in` → lỗi rõ). Refresh bằng `refresh_token`; `invalid_grant` → thông báo "chạy lại auth" (Testing mode hết hạn 7 ngày).
  - Liệt kê: `channels.list?part=contentDetails&mine=true` → playlist uploads; `playlistItems.list?part=contentDetails&maxResults=50` (phân trang) → id; `videos.list?part=fileDetails,snippet&id=<≤50>`.
  - Ghép: NFC `fileDetails.fileName` khớp `^\[(HD|HD Dọc)\] (.+) - Tập (\d+)\.mp4$` (không phân biệt hoa thường phần đuôi `.mp4`). Tên bộ kinh (nhóm 2) so NFC + casefold + gộp khoảng trắng với `--series` nếu có, mặc định `series` của playlist (`work/_playlists/<pid>.json`). `HD` → `landscape`, `HD Dọc` → `vertical`. Tập N → entry playlist có số tập N (dùng cùng cách lấy số tập như `episode.header`) → `episode.valid_files(config, video_id, pid=pid)[shape]` → file trong `episode.directory`. Kiểm sha256 file trước khi gửi. Video không khớp / tập không có ảnh hợp lệ → dòng "bỏ qua" có lý do. Hai video YouTube cùng khớp một (tập, khuôn) → gắn cả hai (in cảnh báo).
  - `thumbnails.set`: `POST https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId=<id>&uploadType=media`, `Content-Type: image/jpeg`, body = bytes ảnh. Ảnh > 2 MB → bỏ qua có lý do.
  - Nhật ký `work/_publish/thumbs.json` (workspace dir từ config): mỗi bản ghi youtube_id, video_id, playlist_id, shape, sha256, set_at. `--apply` bỏ qua video đã gắn cùng sha256 (trừ `--force`). Ghi nhật ký sau mỗi lần gắn thành công (atomic).
  - Lỗi 403 `quotaExceeded` / `forbidden` (kênh chưa xác minh) / 401 sau refresh → dừng, in lý do tiếng Việt, exit ≠ 0; các video đã gắn vẫn trong nhật ký.
- Không thêm dependency (G5).

## Implementation approach

- `publish/youtube.py`: client nhỏ; mọi HTTP qua một hàm `transport(method, url, headers, body) -> (status, headers, bytes)` truyền vào được (mặc định `urllib`) để test không cần mạng.
- `publish/thumbs.py`: `plan(...)` (thuần, nhận danh sách video + config) và `apply(...)`.
- `publish/__main__.py`: argparse `auth`, `thumbs`, `--config` như `auto_short.packaging.__main__`.
- Tái dùng: `auto_short.config.load`, `workspace.atomic_write_json` / `read_json_dict`, `hashing.sha256_file`, `packaging.episode` (`playlist`, `header`, `valid_files`, `directory`), `render.text.nfc`.

## Phải giữ nguyên

- Không đổi module có sẵn. Không ghi gì ngoài file token và nhật ký.

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. Device flow: in `verification_url` + `user_code`; poll xử lý `authorization_pending`, `slow_down`, hết hạn; lưu token mode 600; `invalid_scope` → thử scope `youtube`.
2. Token hết hạn → refresh tự động; `invalid_grant` → lỗi "chạy lại auth", exit ≠ 0.
3. Liệt kê đủ nhiều trang uploads và lô `videos.list` ≤ 50 id.
4. Ghép đúng `[HD]` / `[HD Dọc]`, tên bộ kinh khác → bỏ qua, tên không theo mẫu → bỏ qua, NFD → khớp sau NFC.
5. Chạy thử không gọi `thumbnails.set`; `--apply` gọi đúng URL / header / body; bỏ qua video đã gắn cùng sha256; `--force` gắn lại.
6. `quotaExceeded` dừng ngay, nhật ký giữ các video đã gắn; không token / secret nào xuất hiện trong stdout / stderr / nhật ký.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_publish_thumbs.py -q` — AC1–AC6 (transport giả, không mạng).
- Full suite (ORCHESTRATOR).
- Chạy thật (ORCHESTRATOR + HUMAN LEAD): `auth`, rồi `thumbs --playlist PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4` chạy thử; `--apply` với 1 video trước khi chạy cả bộ.

## Manual test checklist (Tech Lead)

Chạm security model (token OAuth ghi lên kênh) → manual test là gate trước integration.

- [ ] HUMAN LEAD đăng nhập bằng mã trên điện thoại; file token mode 600.
- [ ] Chạy thử: bảng khớp đúng các video đã upload.
- [ ] `--apply` 1 video → Studio hiện đúng thumbnail.

## Result

- Main changes:
