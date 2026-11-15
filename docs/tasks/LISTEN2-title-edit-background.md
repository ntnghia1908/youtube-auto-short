# Task: LISTEN2 — Sửa tiêu đề ngay trong tab Nghe + nghe tiếp, tự chuyển bài khi tắt màn hình

## Status / Approval

- Status: READY (Amendment C; chờ HUMAN LEAD thử điện thoại ở 8080)
- Type: FEATURE + BUG
- Change class: S1 — chỉ client (HTML / JS / CSS) của tab Nghe, dùng lại endpoint sửa tiêu đề có sẵn; không endpoint mới, không dependency, không đổi security model / public API
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25), quota 5 h 3 % / tuần 0 % (2026-11-15)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-15: "1. tôi muốn khung sửa tiêu đề nằm ngay trên trang nghe playlist để tôi nghe tới đâu sửa luôn; 2. nghe mà tắt màn hình vẫn bị vấn đề, chuyển bài không được… có phải do player hay không, có thể dùng một lib player nào đó có sẵn để fix"; chọn "Tự đổi khi tắt màn hình" và "Đồng ý, làm luôn"
- Parallel group: —
- Owned paths: `src/auto_short/web/static/player.js`, `listen.js`, `episode.html`, `favorites.html`, `app.js` (chỉ tách / dùng lại trình sửa tiêu đề), file JS mới cho trình sửa tiêu đề dùng chung (nếu tách), `style.css` (khối nhỏ), `tests/test_web_listen.py`, `src/auto_short/web/routes/watch.py` (chỉ thêm tên sự kiện log được phép — amendment 2026-11-15, Codex BLOCKED vì AC 9), `tests/test_web_watch_party.py` (test validator), `src/auto_short/web/static/watch.js` (Amendment A, nếu cần), file này
- Dependencies: none
- Base commit / branch: `68e4463` (origin/main) / `feature/listen2-title-background` (worktree `~/projects/yas-listen2`)
- Human Lead approval: accepted 2026-11-15
- Implementation authorized: YES

## Bằng chứng (vấn đề 2)

Log `player` của 8080 (tmux `youtube:web`, client `fd8473ba…`, page `listen`): khi màn hình tắt lặp lại `pause_hidden → retry_ok → pause_hidden → … → retry_gave_up`. Trình duyệt điện thoại (Chrome Android) tự dừng phần tử `<video>` có hình khi trang bị ẩn, `play()` lại vẫn bị dừng ngay. Phần tử `<audio>` được phép phát tiếp khi trang ẩn.

Ngoài ra, chế độ một mình chuyển bài bằng chuỗi `setTimeout(200 ms)` đếm ngược 3 s (`renderAdvance` / `localAdvanceAt`); khi trang ẩn, timer bị trình duyệt hãm (≥ 1 s, có khi 1 phút) nên kể cả khi tiếng còn chạy, chuyển bài vẫn trễ / không chạy.

Thư viện player (video.js, Plyr, Howler…) không vượt được chính sách này của trình duyệt (vẫn dùng `<video>`, hoặc chỉ là `<audio>` bọc lại) → không thêm dependency; sửa trực tiếp bằng `<audio>`.

## Goal

1. Trong tab Nghe (trang tập và trang Yêu thích), ngay dưới tiêu đề bài đang phát có ô sửa tiêu đề của chính bài đó: nghe tới đâu sửa tới đó, không phải chuyển sang tab Quản lý.
2. Đang nghe một mình, tắt màn hình (hoặc chuyển app): tiếng vẫn chạy, hết bài tự chuyển sang bài tiếp theo (khi bật "Tự chuyển bài"), nút Tiếp / Trước trên màn hình khóa vẫn chạy. Mở màn hình lại: video hiện tiếp đúng bài và đúng chỗ đang nghe.

## Scope

- In scope:
  - Ô sửa tiêu đề trong tab Nghe cho bài đang phát (solo, cả trang tập lẫn Yêu thích): cùng hành vi với "Sửa tiêu đề" ở tab Quản lý — xem trước dòng / cỡ chữ, chọn phương án AI khác, Lưu & render lại, Khôi phục title AI, khóa khi tập đang có job, thông báo "đang lấy lại nguồn từ 3090" khi bị hoãn. Sau khi lưu, tiêu đề trong danh sách / dòng tiêu đề đổi ngay sang chữ mới; bài đang phát không bị dừng hay nạp lại.
  - Chuyển bài sang bài khác thì ô sửa theo bài mới (bỏ phần đang gõ dở của bài cũ, không gửi nhầm cho bài mới).
  - Phát nền trong chế độ một mình: khi trang bị ẩn (không ở PiP) mà đang phát, chuyển sang một phần tử `<audio>` ẩn cùng nguồn, cùng vị trí, cùng tốc độ; khi trang hiện lại, chuyển về `<video>` ở vị trí của audio. Trong lúc ẩn: hết bài thì chuyển ngay (không đếm ngược 3 s, không phụ thuộc timer) bằng cách đặt `src` mới và `play()` ngay trong handler `ended`; Trước / Tiếp / Phát / Dừng từ Media Session điều khiển audio.
  - Log chẩn đoán (`/api/watch/log`) thêm sự kiện cho việc đổi sang / về audio và chuyển bài khi ẩn, để đọc được trên log 8080.
- Out of scope:
  - Endpoint mới, file audio riêng (m4a) phía server, HTTPS cho 8080.
  - Đổi trình sửa tiêu đề ở tab Quản lý (ngoài việc tách ra dùng chung, hành vi phải giữ nguyên).

## Authority / key decisions

- Dùng lại `POST /api/episodes/{eid}/shorts/{clip}/title` và `/title/preview` (không đổi API). Dữ liệu cho ô sửa (tiêu đề hiện tại / pending, phương án AI, có override, `editable`, giới hạn ký tự, job đang chạy) lấy từ `GET /api/episodes/{eid}` có sẵn, chỉ gọi khi mở ô sửa / khi bài đổi — không tải toàn bộ tập trước.
- Không thêm thư viện player (lý do ở mục Bằng chứng).
- "Tự đổi khi tắt màn hình" (HUMAN LEAD chọn): màn hình sáng vẫn xem video như cũ.

## Implementation approach

- Tách `titleEditor` của `app.js` thành module dùng chung (vd. `static/title_editor.js`, nạp ở `episode.html` và `favorites.html`), tham số hóa episode id, trạng thái khóa, callback sau khi lưu; tab Quản lý và tab Nghe cùng gọi một hàm. Không chép code.
- `player.js`: thêm phần tử `<audio>` (tạo trong JS hoặc trong markup) và khái niệm "phần tử đang phát" (`media()` đã có điểm vào này). Đổi phần tử ở `visibilitychange` / `pause_hidden` khi `wantsPlay()`; chuyển vị trí / tốc độ; bỏ qua sự kiện play/pause do chính việc chuyển gây ra (cơ chế `arm` / `programmed` có sẵn). Retry / give-up hiện có áp dụng cho phần tử đang phát.
- Đường chuyển bài khi ẩn: handler `ended` (của audio) với `state.auto` và có bài tiếp theo → gọi luôn `onNavigate("next")` đồng bộ, và `choose` / `load` dùng phần tử đang phát (audio) → `play()` ngay, không chờ `loadedmetadata` mới play.
- Chế độ một mình và phòng đều đổi phần tử khi ẩn (Amendment A); phòng chuyển bài khi ẩn theo Amendment A.

## Amendment A — Xem chung nghe được khi tắt màn hình (2026-11-15)

HUMAN LEAD 2026-11-15: "Nếu nghe chung mà tắt màn hình vẫn phải nghe được".

- Phòng (trang tập / Yêu thích ở chế độ Xem chung, và `/watch`) cũng đổi sang `<audio>` khi trang ẩn / về `<video>` khi hiện, như chế độ một mình.
- Hết bài khi trang ẩn, "Tự chuyển bài" của phòng bật, còn bài tiếp theo: ngay trong handler `ended` nạp bài tiếp trên audio và `play()` (lạc quan, không chờ mạng / timer), đồng thời gửi lệnh phòng `next` kèm `expect_version` (qua ranh giới tập / phần cũng chuyển, giống chế độ một mình khi ẩn). 409 (người khác đã chuyển) → poll và nhận state phòng; nếu state đó trùng bài đã nạp thì không nạp lại. Màn hình sáng giữ đường cũ (`ended` → đếm ngược 3 s của server).
- Lệnh từ người khác khi ẩn (dừng, phát, chuyển bài) vẫn áp dụng lên audio; quy tắc không tua khi ẩn của WATCH1 giữ nguyên.
- Owned paths thêm `src/auto_short/web/static/watch.js` nếu cần (chỉ phần poll khi ẩn).

## Amendment B — Sửa tiêu đề cả trong Xem chung (2026-11-15)

HUMAN LEAD 2026-11-15 (đang nghe trong phòng): "sao tab nghe tôi chưa thấy chỗ đổi tiêu đề". Ô sửa tiêu đề hiện cả khi trang tập / Yêu thích đang ở chế độ Xem chung: bài đang phát của phòng tra trong danh sách `all` theo `video_url`; không có (vd. trang `/watch`) thì không hiện. Lưu xong: tiêu đề mới hiện ngay trong danh sách / dòng tiêu đề của phòng trên máy này, và poll phòng sau đó không ghi đè lại chữ cũ (giữ bảng tiêu đề đã sửa theo url, áp khi nhận state phòng). Không đổi server / queue của phòng.

## Amendment C — audio luôn là nguồn tiếng (2026-11-15)

Bằng chứng thử thật 8080 (bản `0f4943a`, client `071b638e…`, Xem chung): trang ẩn → `to_audio` → `waiting`, rồi `pause_hidden` + `retry_blocked` `AbortError` lặp tới `retry_gave_up`. Chrome Android đã dừng `<video>` lúc trang ẩn, nên trang không còn đang phát tiếng; trang nền không được *bắt đầu* phát `<audio>` mới. Đổi phần tử lúc ẩn (cách cũ) không dùng được. HUMAN LEAD báo: "Hết bài chuyển sang bài mới nhưng vẫn không nghe được khi tắt màn hình".

Cách mới (thay cách "đổi phần tử khi ẩn" của Scope / AC 5 / AC 10, giữ UX HUMAN LEAD chọn: màn hình sáng vẫn thấy video):
- `<audio>` luôn là nguồn tiếng và đồng hồ trong tab Nghe (một mình và Xem chung) từ lần phát đầu: mọi play / pause / seek / rate / ended / Media Session / retry / log đi qua audio (`media()` = audio).
- `<video>` chỉ để xem: `muted`, cùng src, chạy theo audio (play / pause theo audio; lệch > 0.5 s thì tua theo audio; khi trang hiện lại / ra khỏi PiP thì tua tới vị trí audio). Thao tác của người dùng trên control của video (play / pause / tua / tốc độ) chuyển sang audio. Video bị trình duyệt dừng khi ẩn thì không coi là pause của người dùng.
- Hết bài (audio `ended`) khi ẩn: đổi `audio.src` sang bài tiếp và `play()` ngay trong handler (như Amendment A cho phòng, như AC 6 cho một mình). Trang sáng giữ đếm ngược như cũ.
- PiP / toàn màn hình vẫn trên video (muted); tiếng vẫn từ audio.
- Bỏ `switchMedia` / `selectMedia` / sự kiện `to_audio`, `to_video` (code bị thay, xóa luôn; tên log có thể giữ trong `LOG_TYPES` hoặc bỏ). Thêm log `video_resync` (lệch khi hiện lại, giới hạn tần suất).
- AC thay thế: **AC 5'**: solo + phòng, trang ẩn: audio tiếp tục phát (không có pause / play mới do ẩn), video dừng không sinh `onAction("pause")`; hiện lại: video tua tới audio (lệch ≤ 0.5 s) và phát theo audio nếu audio đang phát. **AC 10'**: AC 10 giữ nguyên trên audio, không còn bước đổi phần tử.

## Phải giữ nguyên

- Tất cả hành vi LISTEN1 / WATCH1 đang có test: thứ tự danh sách, nhóm tập / phần Yêu thích, thẻ đếm ngược khi màn hình sáng, không cuộn trang khi tự chuyển, tim, nhớ chỗ nghe, Xem chung, PiP.
- Tab Quản lý: "Sửa tiêu đề" hoạt động y như trước.
- Không tự cuộn trang / đổi danh sách khi đang ẩn.

## Code bị thay / xóa

- `titleEditor` trong `app.js` chuyển sang module dùng chung; xóa bản trong `app.js`.

## Acceptance Criteria

1. Tab Nghe (trang tập, Yêu thích) có nút / ô sửa tiêu đề cho bài đang phát, chỉ hiện khi Short đó sửa được (`editable`, chưa xóa); trong Xem chung cũng hiện (Amendment B), trang `/watch` không hiện.
2. Ô sửa có xem trước, chọn phương án AI, Lưu & render lại, Khôi phục title AI, khóa khi tập có job, hiện lỗi 409 / 422 và thông báo hoãn (restore) — cùng code với tab Quản lý.
3. Lưu thành công: tiêu đề của mục đó trong danh sách và dòng tiêu đề đổi ngay sang chữ mới; video / audio đang phát không bị dừng, không nạp lại, vị trí không đổi.
4. Chuyển bài khi ô sửa đang mở: ô sửa theo bài mới, chữ đang gõ của bài cũ không bị gửi cho bài mới; phản hồi trễ của bài cũ không ghi đè ô của bài mới.
5. Solo, đang phát, trang ẩn (không PiP): phát tiếp bằng `<audio>` cùng nguồn, lệch vị trí ≤ 1 s, cùng tốc độ; `<video>` dừng. Trang hiện lại: `<video>` phát tiếp ở vị trí của audio (lệch ≤ 1 s), audio dừng. Đang dừng thì ẩn / hiện không tự phát.
6. Solo, trang ẩn, "Tự chuyển bài" bật, audio `ended` có bài tiếp theo: chuyển và gọi `play()` ngay trong handler `ended` (không qua timer); tắt "Tự chuyển bài" hoặc hết danh sách thì dừng như cũ. Đi qua ranh giới tập / phần Yêu thích khi ẩn thì vẫn chuyển (giống "Phát ngay").
7. Media Session Trước / Tiếp / Phát / Dừng khi ẩn điều khiển audio và đổi bài đúng; nhớ chỗ nghe (`save`) ghi vị trí của phần tử đang phát.
8. PiP và Xem chung khi màn hình sáng: hành vi không đổi (test WATCH1 / LISTEN1 hiện có PASS).
10. (Amendment A) Phòng, trang ẩn: đổi sang audio / về video như AC 5; `ended` + auto + có bài tiếp → nạp và `play()` bài tiếp ngay trong handler, gửi `next` với `expect_version`; 409 → poll, không nạp lại khi trùng bài; auto tắt → gửi `ended` như cũ; lệnh dừng / phát / chuyển bài của người khác áp dụng lên audio.
9. Log chẩn đoán có sự kiện đổi sang audio / về video và chuyển bài khi ẩn (trong giới hạn kích thước batch hiện có).

## Required verification

- `PYTHONPATH=src python -m pytest tests/test_web_listen.py tests/test_web_watch_party.py -q` (harness `run_player_js` giả lập `<audio>`, visibility, `ended`) — AC 1–9; Codex chạy phần không cần socket, ORCHESTRATOR chạy đủ.
- Test tab Quản lý liên quan tới sửa tiêu đề (grep `title/preview` trong `tests/`) — AC 2, giữ nguyên.
- Full suite (ORCHESTRATOR, ngoài sandbox).
- Chạy thật trên 8080 (ORCHESTRATOR ghim 8080 vào commit nhánh): sửa tiêu đề 1 Short trong tab Nghe; log `player` khi HUMAN LEAD tắt màn hình qua ít nhất 2 lần chuyển bài.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract → manual test là điểm danh sau automated verification, nhưng phần nền chỉ kiểm được trên điện thoại thật.

- [ ] Điện thoại, tab Nghe: sửa tiêu đề bài đang nghe, Lưu → danh sách đổi chữ, tiếng không ngắt; ít phút sau Short render lại xong.
- [ ] Bấm phát, tắt màn hình: tiếng chạy tiếp, hết bài tự sang bài sau (≥ 2 lần), kể cả qua tập mới.
- [ ] Màn hình khóa: nút Tiếp / Trước chạy (nếu điện thoại hiện điều khiển).
- [ ] Mở màn hình lại: video đúng bài, đúng chỗ.

## Result

- Amendment C — IMPLEMENTER handoff (2026-11-15): implementation hoàn tất trên base `01b73ae`, chờ ORCHESTRATOR review / HUMAN LEAD thử lại 8080. Chưa claim phát nền thực tế PASS: cách cũ đã thất bại trên điện thoại như bằng chứng trong Amendment C, bản mới chưa chạy trên điện thoại trong lượt này. Không commit.
- Main changes / files:
  - `static/player.js`: `media()` luôn trả audio. Audio giữ nguồn tiếng / đồng hồ cho solo và phòng ngay từ lần Play đầu ở foreground; chỉ metadata audio quyết định `loading`. Control play / pause / seek / rate của video được chuyển tới audio, không dùng thời gian video cho Play / Pause. Video luôn muted, bị unmute sẽ đặt lại muted; video ended không chuyển bài.
  - `syncVideo` mới giữ video theo audio: cùng src, play / pause / rate theo audio, tua khi lệch > 0.5 s và khi hiện lại / thay đổi PiP. Khi hidden ngoài PiP chỉ dừng video; không pause / play / đổi src audio vì visibility. Bỏ qua pause video do browser khi hidden. Có token cho promise play video để phản hồi trễ không làm khởi động lại video lúc hidden hoặc ảnh hưởng audio.
  - Xóa `switchMedia`, `selectMedia`, `currentMedia` và đường phát log `to_audio` / `to_video` trong client. `arm` / `isProgrammed` vẫn dùng chung, tách marker audio và video để sự kiện mirror không gửi ngược lệnh / thay trạng thái audio. Chỉ arm pause khi phần tử đang phát và tiêu thụ marker khi inactive, tránh nuốt thao tác thật sau suspend / resume.
  - `load` đặt src / vị trí / rate cho cả audio và video muted, gọi `playMedia(audio)` ngay nếu cần phát, không chờ metadata hoặc mạng. Giữ nguyên đường audio ended cho `hidden_advance`, solo auto và room optimistic next / expect_version / 409; countdown khi sáng và WATCH1 sync / hidden seek guard giữ nguyên.
  - `static/listen.js`: chỉ lắng nghe timeupdate audio để nhớ chỗ nghe; các đường save / filter / room vốn dùng `media()` nay luôn đọc audio. Amendment B (editor phòng / Map title / không reload khi lưu) giữ nguyên.
  - `routes/watch.py`: chỉ thêm `video_resync` vào `LOG_TYPES`. `record` giới hạn event này một lần / 5 giây qua `logMarks`, giữ giới hạn batch 20 event / 2 KB. Giữ tên `to_audio` / `to_video` trong allowlist server để tương thích client cũ; client mới không phát chúng.
  - `tests/test_web_listen.py`: metadata mặc định mô phỏng cả audio và video; ended mặc định phát trên audio; fake load phát pause nếu trước đó đang chạy. Thay test đổi phần tử bằng test audio-clock / video follower, điều chỉnh các clock injection cũ sang audio. `tests/test_web_watch_party.py`: validator / logger kiểm thêm `video_resync`.
- Verification trong môi trường hiện tại:
  - PASS: `PYTHONPATH=src python -m pytest tests/test_web_listen.py tests/test_web_watch_party.py -q -k '(player_js or static or countdown or overlay or log) and not http'` → **75 passed, 105 deselected**, 7.47 s.
  - PASS hồi quy rộng hơn: `PYTHONPATH=src python -m pytest tests/test_web_listen.py tests/test_web_watch_party.py -q -k 'not http'` → **169 passed, 11 deselected**, 9.82 s. Bao gồm danh sách / nhóm / tim / nhớ vị trí / tab, editor solo / phòng, WATCH1, optimistic next / 409 và validator log không dùng socket.
  - PASS: `node --check` cho `player.js`, `listen.js`; `git diff --check`.
  - Lệnh nguyên văn yêu cầu đã thử với giới hạn chờ: `timeout 20s env PYTHONPATH=src python -m pytest tests/test_web_listen.py tests/test_web_watch_party.py -q -k "player_js or static or countdown or overlay or log"` → **exit 124**, không có kết quả tổng kết PASS. `--collect-only` xác nhận chọn **76 / 180** test, gồm `test_http_log_auth_validation_rate_and_records` dùng TestClient. 75 test không HTTP nêu trên đã chạy PASS; test HTTP này còn chờ ngoài sandbox. Không chờ tiếp / không claim lệnh đầy đủ PASS.
- AC → test (tên rút gọn có prefix `test_player_js_`, trừ tên ghi đầy đủ):

  | AC | Bằng chứng |
  |---|---|
  | 5′ | `audio_clock_survives_visibility_and_video_controls` (solo / phòng): Play từ video gọi audio.play trước metadata audio khi trang còn sáng; seek / rate / pause / play điều khiển audio, pause trước metadata cũng dừng video; mirror không echo lệnh; ẩn / hiện không tăng audio play / pause / load; browser pause video không sinh pause_hidden; video hiện lại theo vị trí / rate audio. `video_follows_new_source_and_ignores_late_play`: cả hai src đổi trong audio ended, audio tiếp tục khi video metadata / play trễ và qua visibility; video bắt kịp audio. `paused_audio_never_starts_from_visibility`: paused / suspend không tự phát, control sau resume vẫn hoạt động. PASS |
  | 10′ | `room_hidden_advance_reconciles_without_double_skip` (3 trang × ACK / 409 trùng / 409 khác): audio load + play ngay trước POST / timer / metadata, hai lần next đúng version, ACK trùng không reload, 409 không double skip. `room_audio_remote_controls_preserve_pause_and_seek_guards`: remote pause / play / seek / next, Media Session, pauseTimer / syncBlocked / seek_skipped_hidden / poll nền. `room_ended_fallbacks_keep_server_countdown`: auto off / cuối danh sách dùng ended cũ, visible countdown server. 14 ca PASS trên audio luôn hoạt động |
  | 6, 7 | `hidden_advance_is_synchronous_across_groups`: solo qua tập / phần, auto off / cuối danh sách dừng. `audio_clock_survives_visibility_and_video_controls`: Media Session / save đọc audio. `audio_retry_progress_giveup_and_log_batches`: retry / progress / give-up / log đọc audio. PASS |
  | 8 | `visible_room_and_pip_follow_audio`: video muted khi visible / PiP; video ended không advance; ra / vào PiP không phát lại hoặc dừng audio, countdown vẫn theo audio. PASS |
  | 9 | `audio_clock_survives_visibility_and_video_controls`: log video_resync có thực và 10 lần resync liên tiếp vẫn chỉ ghi một event trong cửa sổ 5 s, không phát to_audio / to_video. `audio_retry_progress_giveup_and_log_batches`: cap batch / retry không đổi. `test_log_route_accepts_pip_and_retry_cap_events`: server nhận và ghi video_resync cùng các event cũ. PASS |
  | 1–4 | Các test editor / API doubles của solo và phòng trong hai nhóm PASS phía trên: lazy view, editable / deleted / khóa job / restore / lỗi, chống phản hồi trễ, save không đổi nguồn hay ngắt media, title cục bộ vẫn giữ qua full / cached room poll. |

- Test cũ thay theo AC 5′ / 10′:
  - `test_player_js_audio_handoff_session_controls_and_position` → `test_player_js_audio_clock_survives_visibility_and_video_controls` (thêm param solo / phòng).
  - `test_player_js_new_video_after_hidden_advance_and_late_media_events` → `test_player_js_video_follows_new_source_and_ignores_late_play`.
  - `test_player_js_paused_or_suspended_visibility_never_starts_playback` → `test_player_js_paused_audio_never_starts_from_visibility`.
  - `test_player_js_visible_room_and_pip_keep_video` → `test_player_js_visible_room_and_pip_follow_audio`.
  - Các assertion còn lại khẳng định media đổi sang video khi hiện lại / audio chưa từng phát khi visible đã đổi sang media luôn là audio; nằm trong `hidden_advance_is_synchronous_across_groups`, `room_hidden_advance_reconciles_without_double_skip`, `room_audio_remote_controls_preserve_pause_and_seek_guards`, `room_ended_fallbacks_keep_server_countdown`. Giữ các kiểm tra next / version / 409 / countdown / guard.
  - Ba test legacy `test_favorites_click_filter_end_card_and_unheart`, `test_favorites_resume_identity_and_room_group_payload`, `test_favorites_tab_suspends_and_can_resume_same_track` bơm thời gian vào audio thay vì video; assertion vị trí nhớ / payload phòng / video theo audio vẫn giữ. Test retry bơm audio clock, dùng event visibility thay cho to_audio đã bỏ để kiểm cap batch. Không bỏ test để che lỗi.
- Diff riêng Amendment C so với `01b73ae` (không tính docs): **app +129 / −111; test +105 / −82**.
- Helper / reuse:
  - Đã tìm `rg -n 'arm\(|isProgrammed|playMedia|recover|syncVideo|visibilityChanged|video_resync' src/auto_short/web/static/player.js src/auto_short/web/routes/watch.py`. Dùng lại `arm`, `isProgrammed`, `playMedia`, `recover`, `record`, `logMarks`, load / state / room command / sourceKey hiện có. `syncVideo` là helper mới vì `sync` cũ kéo media theo đồng hồ phòng với chính sách hidden và ngưỡng 1 s; video follower cần bám audio ở ngưỡng 0.5 s, chỉ sửa video và không gọi đường retry / action audio. Hai helper đổi phần tử cũ đã xóa, không giữ bản dư.
  - Harness tái dùng `run_player_js`, `Element`, metadata / ended / visibility, `useRoomTransport`, editor / API doubles có sẵn; không thêm fixture / dependency.
- Review / limitations: IMPLEMENTER đã rà diff với Amendment C và chạy các kiểm tra trên. Chưa chạy TestClient / full suite / 8080 / điện thoại thật cho bản C. Cần HUMAN LEAD thử solo và phòng qua ít nhất hai lần hidden advance, mở lại video, PiP và control khóa màn hình; các lượt PASS trước `01b73ae` không chứng minh bản C phát nền được trên điện thoại.
- Integration: không commit / push / PR; không gọi agent khác hoặc mạng thật.

- ORCHESTRATOR verification Amendment C 2026-11-15: full suite `-n auto` 4352 passed, 2 skipped (3 m 01 s).
