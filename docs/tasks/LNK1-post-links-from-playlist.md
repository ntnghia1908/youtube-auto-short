# Task: LNK1 — Tự điền link bài đăng từ playlist YouTube

## Status / Approval

- Status: IN_PROGRESS
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
- Out of scope: mọi thao tác ghi lên YouTube từ web; route đăng nhập OAuth trên web (đăng nhập vẫn qua CLI `auth`); suy đoán theo thứ tự playlist hoặc nội dung tiêu đề; tự đăng bài cộng đồng; đổi link của ảnh, video ghép, bản HD; sửa ô dán tay.

## Authority / key decisions

- `docs/decisions/CP8.15-community-post-contract.md` P6, P7. Bổ sung vào P6 trong task này:
  - **L1 Nguồn**: YouTube Data API bằng token PUB2: `playlistItems.list` rồi `videos.list part=fileDetails,snippet,status`. Sửa PUB2 G1: tiến trình web được đọc token và chỉ gọi GET tới YouTube Data API; thao tác ghi Data API vẫn chỉ ở CLI. POST duy nhất được phép từ adapter web là refresh OAuth tới `https://oauth2.googleapis.com/token` (`TOKEN_URL`); token refresh được lưu atomic, mode 600, không lộ token / secret. Đọc ẩn danh bị loại: đo 2026-11-01 playlist Short 285 video chỉ 79 có tiêu đề, khai thị 101 video chỉ 46 có tiêu đề, phần còn lại chỉ có id.
  - **L1a Phiên đăng nhập**: OAuth app ở chế độ Testing (Production đòi homepage + privacy policy, HUMAN LEAD chưa làm), token hết hạn sau 7 ngày, chạy lại `auth`. Token hỏng / bị thu hồi hoặc hết quota → lần quét báo lỗi trên trang bộ kinh ("chạy lại auth"), không xóa link, vòng sau thử lại. Quota: 1 đơn vị / 50 video, quét 6 giờ một lần là không đáng kể.
  - **L1b Nhiều kênh** (HUMAN LEAD 2026-11-01: 3 kênh cùng một Gmail, mỗi kênh một token): token mặc định PUB2 + mọi `~/.local/share/auto-short/youtube-tokens/*.json`. Với mỗi playlist, `playlists.list part=snippet` lấy `channelId`, so với `channels.list mine=true` của từng token để chọn token chủ playlist; không chọn tay trên web. Không token nào sở hữu playlist → lần quét báo tên kênh cần `auth --token`. Một token hỏng không chặn playlist của kênh khác. CLI `thumbs` giữ nguyên.
  - **L2 Phạm vi ghép**: chỉ trong bộ kinh đang dán playlist, nên `T29_S01` của hai bộ khác nhau không lẫn. Short và khai thị của bộ đều được xét.
  - **L2a Hai playlist**: Short và khai thị ở playlist riêng (HUMAN LEAD 2026-11-01), mỗi đợt 20 tập nên một bộ kinh có nhiều cặp playlist. Web giữ một danh sách playlist theo bộ kinh, không phân loại khi dán; `S` / `KT` trong mã quyết định loại, mọi video trong danh sách được ghép chung một lần quét. Mã trùng giữa các playlist xử lý theo L6.
  - **L3 Mã**: ưu tiên `fileDetails.fileName` (NFC); không có mã thì dùng tiêu đề (NFC, bỏ khoảng trắng đầu). Mã nằm ở đầu chuỗi: `T<tập>`, dấu cách hoặc `_`, rồi `S` / `KT` + 2–3 chữ số, tiếp theo là dấu cách, `_`, `.` hoặc hết chuỗi (tiêu đề thật có cả `T1 S10 …` và `T7_S07_…`). Đưa về dạng `review.names.short_code` rồi so chính xác theo vị trí trong `render_manifest.json`, không đoán. Tên file và tiêu đề ra hai mã khác nhau → coi là trùng (L6), không điền.
  - **G-FILE** (đã đo 2026-11-01, Thập Thiện, 386 video): 267/285 Short + 101/101 khai thị có mã và đều ứng đúng một Short trên web, 0 mã trùng, 0 mâu thuẫn tên file / tiêu đề; 88/89 link dán tay trùng khớp, 1 khác (L5). 18 Short không mã: HUMAN LEAD đã xử lý tay, không ghép (2026-11-01). Một số video có `fileName` rỗng nên vẫn cần tiêu đề.
  - **L4 Dạng link**: Short = `post.logic.normalize_link` (`/shorts/<id>`). Khai thị (4–7 phút, vượt giới hạn Shorts) = `https://youtube.com/watch?v=<id>`. Ô dán tay giữ nguyên P6.
  - **L5 Không ghi đè**: chỉ điền khi `link` trống, kể cả bài đã đăng; link đang có khác YouTube thì giữ và báo "khác link". Không xóa link khi video biến mất khỏi playlist.
  - **L6 Trùng**: hai video YouTube cùng mã, hoặc một mã ứng với hai Short trong bộ, thì bỏ qua và báo.
  - **L7 Bài chưa soạn**: không tạo bài; Short chưa có bài được tính là "chờ soạn" và điền ở lần quét sau khi đã có bài.
- Không thêm dependency.

## Implementation approach

- `publish/youtube.py`: thêm `default_token_dir()`, `channel_id()`, `playlist_channel(playlist_id)`, `playlist_videos(playlist_id)`, tách phần phân trang + lô `videos.list` dùng chung với `videos()`; không đổi hành vi `videos()`.
- `post/links.py`: hàm thuần `parse_code(text)`, `link_for(video_id, khaithi)`, `plan(entries, targets, current_links)` trả danh sách cần điền và số liệu từng lý do.
- `web/post_links.py`: dựng `targets` từ `playlists` + `episodes.copy_prefixes` / `kind_fields`, gọi `YouTube.playlist_videos`, ghi `posts.json` dưới `ctx.post_lock` qua `post_store.with_fields`. Lần quét gần nhất lưu ở `work/_publish/post_links.json`; `rows` chỉ giữ `no_code`, `unmatched`, `duplicate`, `different`, `waiting` (`plan()` vẫn trả mọi dòng). Khóa quét chỉ tuần tự hóa `add` / `sync` / `sync_all`; `view` đọc file atomic và `remove` dùng khóa riêng của playlist, không chờ quét mạng.
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
7. Một bộ kinh có nhiều playlist, gồm playlist Short và playlist khai thị riêng: dán theo thứ tự nào cũng điền đúng loại; "Cập nhật danh sách" không làm mất playlist đã gắn; gỡ playlist không xóa link đã điền.
8. Vòng nền chạy theo `link_sync_hours`, `0` thì không chạy; YouTube lỗi / timeout chỉ ghi lỗi của lần quét, playlist khác và vòng sau vẫn chạy.
9. Trang bộ kinh hiện số đã điền, không có mã, trùng, khác link, chờ soạn và thời điểm + lỗi lần quét gần nhất. Link không hợp lệ / Mix báo 422.
10. Test không gọi mạng thật (transport giả). Web chỉ GET YouTube Data API; POST duy nhất là refresh tới OAuth `TOKEN_URL` theo L1. Có test chặn POST Data API, kiểm access token hết hạn / phản hồi 401 → refresh thành công rồi GET, lưu token atomic mode 600.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_post_links.py tests/test_web_post_links.py tests/test_publish_thumbs.py -q` — AC1–AC10, `videos()` không đổi.
- `python -m pytest -q -n auto` — toàn bộ suite (ORCHESTRATOR chạy ngoài sandbox).
- Chạy thật trên bản sao `work/`, playlist thật của HUMAN LEAD: đối chiếu mẫu link ↔ tiêu đề.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Task chạm security model (web đọc token OAuth của kênh, chỉ GET Data API và refresh OAuth theo L1), nên manual test là gate trước integration. Không chạm database; thêm route web sau đăng nhập, không đổi API cũ.

- [ ] Trang bộ kinh: dán playlist thật, thấy số liệu quét.
- [ ] Tab Bài đăng: link đã điền, nút Copy có dòng `▶ Xem video:`, mở link đúng video.

## Result

- Main changes: hoàn tất phần IMPLEMENTER: đọc playlist nhiều kênh bằng GET; ghép thuần L2–L7; lưu `link_playlists`, route / UI tiếng Việt, vòng nền cấu hình; mọi ghi `posts.json` của service đi qua `ctx.post_lock` + `with_fields`. CP8.15 P6 và PUB2 G1/G2/G4 chỉ trỏ tới L1–L7, không nhân bản rule.
- Tests: `PYTHONPATH=/home/ntnghia/projects/youtube-auto-short-lnk1/src ~/miniconda3/envs/auto-short/bin/python -m pytest tests/test_post_links.py tests/test_publish_thumbs.py -q -x --tb=short` — PASS 72 (sau vòng sửa F1–F3). `tests/test_web_post_links.py --collect-only -q` — 13 ca thu thập được, chưa thực thi HTTP. `node --check src/auto_short/web/static/app.js`, `git diff --check` — PASS; dựng app + đăng ký đủ 4 route mới bằng kiểm tra trực tiếp, không socket.
- AC → test: AC1–6, 7a, 7, 8, 10 → `test_post_links.py` (matcher + service + transport GET giả + coroutine không socket); AC1–7a/7, 9–10 → `test_web_post_links.py` (auth, route, giữ user fields khi refresh, UI; chờ ORCHESTRATOR chạy). `test_publish_thumbs.py` kiểm hồi quy `videos()` / CLI.
- Diff + / − vòng sửa F1–F3: app +20 / −20; test +127 / −10; docs +8 / −8 (so với đầu vòng sửa, gồm file chưa stage).
- Helper mới (đã tìm, lý do không tái dùng): `default_token_dir`, `channel_id`, `playlist_channel`, `playlist_videos`, `_playlist_videos` (mở rộng adapter sẵn có, dùng chung phân trang/lô); `parse_code`, `link_for`, `plan` (chưa có matcher LNK1; tái dùng `short_code`, `normalize_link`); `PostLinks`, `playlist_id_from_url`, `_safe_error`, `_post_link_loop`, `PlaylistStore.set_link_playlist` (điều phối / trạng thái mới, tái dùng `copy_prefixes`, `kind_fields`, URL policy, khóa playlist và `with_fields`).
- Review: tự rà owned paths, khóa ghi, không log / trả exception gốc chứa bí mật; chưa có review độc lập. Không gọi agent khác.
- Important findings / decisions: vòng sửa F1–F3 theo yêu cầu HUMAN LEAD: `read_only` chỉ chặn method khác GET ở `_request` (YouTube Data API); `_refresh` được POST tới OAuth `TOKEN_URL`, tái dùng lưu token atomic mode 600. `view` / `remove` không chờ khóa quét; journal chỉ lưu các dòng cần xử lý, giữ nguyên `plan()` và toàn bộ counts.
- Known limitations: chưa chạy lệnh required gồm `tests/test_web_post_links.py` (sandbox không socket loopback; ORCHESTRATOR chạy), `python -m pytest -q -n auto`, chạy thật trên bản sao `work/` và manual checklist (theo phân công / cấm mạng thật). Test vòng nền từng treo khi dùng event loop thật trong sandbox, đã dừng và kiểm bằng coroutine + `to_thread` giả. Chưa chuyển task READY vì các required verification trên còn thiếu.
- ORCHESTRATOR: full suite `python -m pytest -q -n auto` 3672 passed, 1 skipped. Chạy thật 2026-11-01 trên bản sao Thập Thiện với 2 playlist thật: điền 178 Short + 101 khai thị (135 → 414 link), 88 link cũ giữ nguyên, 1 "khác link" (`T6_S01`, giữ link cũ), 18 không mã, 0 trùng, quét lại điền 0 (idempotent), journal 5 KB. 3 token 3 kênh đọc được (2026-11-01).
- Vòng sửa: 1 vòng ORCHESTRATOR (F1 chặn refresh, F2 khóa quét treo trang, F3 rows thừa). Codex: 125.743 + 156.145 tokens.
- Giới hạn: dán playlist nhầm bộ kinh sẽ ghép theo mã của bộ đó; gỡ playlist không xóa link đã điền. Testing mode: `auth` lại sau 7 ngày. Manual test trên 8080 chờ sau đợt Vô Lượng Thọ.
- Vòng reviewer: Codex review `8cef435`: P2 gỡ playlist giữa lúc quét vẫn ghi link, đã sửa ở `0b821db`.
- Full suite sau `0b821db` chưa xanh: 4 / 4 lần, mỗi lần 1 test khác nhau fail (load 50–85, đợt Vô Lượng Thọ đang chạy): `test_web_lanes_cp810::test_disk_block_rechecked_in_prepare_lane`, `test_ollama_wait_runner::test_submit_202_and_gpu_field_while_down`, `test_theme_render::test_description_refresh_on_cache_hit_without_encoding` (lệch atime 1 giây, module không liên quan), `test_web_stop_fix::test_ac2_no_child_survives_stop`. Từng test chạy riêng: PASS. So sánh: base `a6837e3` full suite 2 / 2 lần xanh; chạy lặp 3 file test đó `-n 24` 8 vòng: `test_ac2_orphaned_grandchild_and_children_started_after` fail 8 / 8 trên cả base và nhánh. Chưa chứng minh nhánh không làm tăng tỉ lệ fail; chạy lại full suite khi load thấp trước READY.
- PR: không commit / push / PR theo yêu cầu.
- 2026-11-01: full suite trên commit gộp `08bd6ac` (origin/main + LNK1 + AUD2): 3758 passed, 1 skipped (load 46–50). Còn manual test 8080.
