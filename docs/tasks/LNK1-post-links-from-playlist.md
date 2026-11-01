# Task: LNK1 — Tự điền link bài đăng từ playlist YouTube

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — contract, review, test web + full suite, chạy thật
- Implementer: codex — phần việc tự chứa, spec rõ; test web / socket do ORCHESTRATOR chạy
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: yêu cầu HUMAN LEAD 2026-11-01 ("chỉ cần input playlist đó thì web tự dán link vào"; sửa cùng ngày: "cần link của bài lên lịch chưa công khai luôn"); sửa đổi PUB2 G1, G2 ở mục Authority
- Parallel group: —
- Owned paths: `src/auto_short/post/links.py` (mới), `src/auto_short/publish/youtube.py`, `src/auto_short/web/post_links.py` (mới), `src/auto_short/web/playlists.py`, `src/auto_short/web/routes/playlists.py`, `src/auto_short/web/app.py`, `src/auto_short/web/context.py`, `src/auto_short/config.py`, `src/auto_short/web/static/` (trang bộ kinh), `tests/test_post_links.py` (mới), `tests/test_web_post_links.py` (mới), `docs/decisions/CP8.15-community-post-contract.md` (P6), `docs/decisions/PUB2-youtube-thumbnail-set.md` (G1, G2, G4), contract này
- Dependencies: OAuth client + token kênh Thập Thiện đã có 2026-11-01 (app ở Testing); 2 kênh còn lại HUMAN LEAD chạy `auth --token` sau
- Base commit / branch: `a6837e3` / `feature/lnk1-post-links`
- Human Lead approval: HUMAN LEAD 2026-11-01 ("Xong, Duyệt")
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`.

## Goal

Trên trang bộ kinh, HUMAN LEAD dán link một hoặc nhiều playlist YouTube đã upload. Web đọc playlist bằng đăng nhập kênh (OAuth, chỉ đọc), thấy cả video đang lên lịch, nhận ra từng Short / khai thị theo mã `T29_S01` / `T29_KT01` trong tên file gốc lúc upload, rồi điền link vào bài đăng còn trống ngay cả khi video chưa công khai. Web tự kiểm lại định kỳ để nhận video mới thêm vào playlist.

## Scope

- In scope: lưu danh sách playlist theo bộ kinh; ghép tiêu đề với Short / khai thị; điền link; quét ngay khi thêm, nút "Cập nhật ngay", vòng nền định kỳ; hiển thị kết quả lần quét.
- Out of scope: mọi thao tác ghi lên YouTube từ web; route đăng nhập OAuth trên web (đăng nhập vẫn qua CLI `auth`); suy đoán theo thứ tự playlist hoặc so gần đúng tiêu đề; tự đăng bài cộng đồng; đổi link của ảnh, video ghép, bản HD; sửa ô dán tay.

## Authority / key decisions

- `docs/decisions/CP8.15-community-post-contract.md` P6, P7. Bổ sung vào P6 trong task này:
  - **L1 Nguồn**: YouTube Data API bằng token PUB2: `playlistItems.list` rồi `videos.list part=fileDetails,snippet,status`. Sửa PUB2 G1: tiến trình web được đọc token và chỉ gọi GET; thao tác ghi vẫn chỉ ở CLI. Đọc ẩn danh bị loại: đo 2026-11-01 playlist Short 285 video chỉ 79 có tiêu đề, khai thị 101 video chỉ 46 có tiêu đề, phần còn lại chỉ có id.
  - **L1a Phiên đăng nhập**: OAuth app ở chế độ Testing (Production đòi homepage + privacy policy, HUMAN LEAD chưa làm), token hết hạn sau 7 ngày, chạy lại `auth`. Token hỏng / bị thu hồi hoặc hết quota → lần quét báo lỗi trên trang bộ kinh ("chạy lại auth"), không xóa link, vòng sau thử lại. Quota: 1 đơn vị / 50 video, quét 6 giờ một lần là không đáng kể.
  - **L1b Nhiều kênh** (HUMAN LEAD 2026-11-01: 3 kênh cùng một Gmail, mỗi kênh một token): token mặc định PUB2 + mọi `~/.local/share/auto-short/youtube-tokens/*.json`. Với mỗi playlist, `playlists.list part=snippet` lấy `channelId`, so với `channels.list mine=true` của từng token để chọn token chủ playlist; không chọn tay trên web. Không token nào sở hữu playlist → lần quét báo tên kênh cần `auth --token`. Một token hỏng không chặn playlist của kênh khác. CLI `thumbs` giữ nguyên.
  - **L2 Phạm vi ghép**: chỉ trong bộ kinh đang dán playlist, nên `T29_S01` của hai bộ khác nhau không lẫn. Short và khai thị của bộ đều được xét.
  - **L2a Hai playlist**: Short và khai thị ở playlist riêng (HUMAN LEAD 2026-11-01), mỗi đợt 20 tập nên một bộ kinh có nhiều cặp playlist. Web giữ một danh sách playlist theo bộ kinh, không phân loại khi dán; `S` / `KT` trong mã quyết định loại, mọi video trong danh sách được ghép chung một lần quét. Mã trùng giữa các playlist xử lý theo L6.
  - **L3 Mã**: ưu tiên `fileDetails.fileName` (NFC); không có mã thì dùng tiêu đề (NFC, bỏ khoảng trắng đầu). Mã nằm ở đầu chuỗi: `T<tập>`, dấu cách hoặc `_`, rồi `S` / `KT` + 2–3 chữ số, tiếp theo là dấu cách, `_`, `.` hoặc hết chuỗi (tiêu đề thật có cả `T1 S10 …` và `T7_S07_…`). Đưa về dạng `review.names.short_code` rồi so chính xác theo vị trí trong `render_manifest.json`, không đoán. Tên file và tiêu đề ra hai mã khác nhau → coi là trùng (L6), không điền.
  - **L3a Không có mã**: chỉ khi cả tên file và tiêu đề đều không có mã, so tiêu đề YouTube (bỏ hashtag, bỏ dấu câu, gộp khoảng trắng, NFC, casefold) với title của Short trong bộ; đúng một Short khớp nguyên văn thì điền, không khớp hoặc nhiều Short khớp thì đưa vào danh sách dán tay. Không so gần đúng.
  - **G-FILE** (đã đo 2026-11-01, Thập Thiện, 386 video): 267/285 Short + 101/101 khai thị có mã và đều ứng đúng một Short trên web, 0 mã trùng, 0 mâu thuẫn tên file / tiêu đề; 88/89 link dán tay trùng khớp, 1 khác (L5). 18 Short không mã: 15 khớp nguyên văn (L3a), 3 phải dán tay. Một số video có `fileName` rỗng nên vẫn cần tiêu đề.
  - **L4 Dạng link**: Short = `post.logic.normalize_link` (`/shorts/<id>`). Khai thị (4–7 phút, vượt giới hạn Shorts) = `https://youtube.com/watch?v=<id>`. Ô dán tay giữ nguyên P6.
  - **L5 Không ghi đè**: chỉ điền khi `link` trống, kể cả bài đã đăng; link đang có khác YouTube thì giữ và báo "khác link". Không xóa link khi video biến mất khỏi playlist.
  - **L6 Trùng**: hai video YouTube cùng mã, hoặc một mã ứng với hai Short trong bộ, thì bỏ qua và báo.
  - **L7 Bài chưa soạn**: không tạo bài; Short chưa có bài được tính là "chờ soạn" và điền ở lần quét sau khi đã có bài.
- Không thêm dependency.

## Implementation approach

- `publish/youtube.py`: thêm `default_token_dir()`, `channel_id()`, `playlist_channel(playlist_id)`, `playlist_videos(playlist_id)`, tách phần phân trang + lô `videos.list` dùng chung với `videos()`; không đổi hành vi `videos()`.
- `post/links.py`: hàm thuần `parse_code(text)`, `link_for(video_id, khaithi)`, `plan(entries, targets, current_links)` trả danh sách cần điền và số liệu từng lý do.
- `web/post_links.py`: dựng `targets` từ `playlists` + `episodes.copy_prefixes` / `kind_fields`, gọi `YouTube.playlist_videos`, ghi `posts.json` dưới `ctx.post_lock` qua `post_store.with_fields`. Lần quét gần nhất lưu ở `work/_publish/post_links.json`.
- Danh sách playlist lưu ở trường `link_playlists` của `work/_playlists/<pid>.json`, thêm vào `USER_FIELDS` để "Cập nhật danh sách" không làm mất.
- Route: `GET` / `POST` / `DELETE /api/playlists/{playlist_id}/link-playlists[/{youtube_playlist_id}]`, `POST …/link-playlists/sync`. `POST` kiểm link bằng `web/urls.py` (từ chối Mix, Watch later, Liked; chấp nhận thêm khi `watch?v=…&list=…` lấy `list`).
- Vòng nền `_post_link_loop` trong `app.py` theo mẫu `_auto_archive_loop`, chạy tuần tự từng playlist, `asyncio.to_thread`, lỗi không làm dừng vòng. Config `[post] link_sync_hours` mặc định 6; 0 = chỉ quét bằng tay.
- Web: khối "Link bài đăng từ YouTube" trên trang bộ kinh, cạnh khối văn bản gốc (`#dc-state`).
- Tái dùng: `publish.youtube.YouTube`, `review.names.short_code`, `episodes.copy_prefixes`, `post_store.with_fields`, `web/urls.py`.

## Phải giữ nguyên

- Ô "Lưu link" và API `PUT …/posts/{clip}`; link dán tay không bị đổi.
- `posted_at`, `paragraphs`, `image`, `origin` của bài. Không tick "Đã đăng bài".
- Hàng đợi job: quét không xếp job, không chiếm làn prepare / ai / render.
- Giao diện Bài đăng hiện có: link đã điền hiện ở ô cũ, bản Copy có dòng `▶ Xem video:` như link dán tay.
- Danh sách và user fields sẵn có của `work/_playlists/<pid>.json`.

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. Thêm playlist trên trang bộ kinh thì web quét ngay và điền đúng link Short (`/shorts/<id>`) + khai thị (`watch?v=<id>`) cho bài trống, kể cả video đang lên lịch / riêng tư và playlist riêng tư.
2. Token hỏng, hết quota, YouTube lỗi: lần quét báo lỗi rõ, link đã có giữ nguyên, không lộ token / secret trong log hay phản hồi API.
3. Bài đã có link không đổi; link khác được báo "khác link" (L5).
4. Cùng mã ở hai bộ kinh không lẫn; mã trùng trong một bộ bị bỏ qua và báo (L2, L6).
5. Tên file và tiêu đề đều không có mã / mã không có Short tương ứng không điền gì, được đếm riêng và trang bộ kinh liệt kê tiêu đề để dán tay. `T1 S10`, `T7_S07_…`, `T1_S10_x.mp4` đều nhận; `T29_S01` không khớp `T29_S010`.
6. Bài chưa soạn không bị tạo; soạn xong, lần quét sau điền link (L7).
7a. Playlist của kênh khác được đọc đúng token kênh đó; không có token phù hợp hoặc một token hỏng thì chỉ playlist đó báo lỗi rõ, playlist khác vẫn điền (L1b).
7b. Short không mã khớp nguyên văn đúng một Short thì được điền; khớp nhiều hoặc không khớp thì không điền (L3a).
7. Một bộ kinh có nhiều playlist, gồm playlist Short và playlist khai thị riêng: dán theo thứ tự nào cũng điền đúng loại; "Cập nhật danh sách" không làm mất playlist đã gắn; gỡ playlist không xóa link đã điền.
8. Vòng nền chạy theo `link_sync_hours`, `0` thì không chạy; YouTube lỗi / timeout chỉ ghi lỗi của lần quét, playlist khác và vòng sau vẫn chạy.
9. Trang bộ kinh hiện số đã điền, không có mã, trùng, khác link, chờ soạn và thời điểm + lỗi lần quét gần nhất. Link không hợp lệ / Mix báo 422.
10. Test không gọi mạng thật (transport giả). Web chỉ gọi method GET (có test chặn).

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_post_links.py tests/test_web_post_links.py tests/test_publish_thumbs.py -q` — AC1–AC10, `videos()` không đổi.
- `python -m pytest -q -n auto` — toàn bộ suite (ORCHESTRATOR chạy ngoài sandbox).
- Chạy thật trên bản sao `work/`, playlist thật của HUMAN LEAD: đối chiếu mẫu link ↔ tiêu đề.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Task chạm security model (web đọc token OAuth của kênh, chỉ GET), nên manual test là gate trước integration. Không chạm database; thêm route web sau đăng nhập, không đổi API cũ.

- [ ] Trang bộ kinh: dán playlist thật, thấy số liệu quét.
- [ ] Tab Bài đăng: link đã điền, nút Copy có dòng `▶ Xem video:`, mở link đúng video.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
