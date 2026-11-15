# Task: LISTEN2 — Sửa tiêu đề ngay trong tab Nghe + nghe tiếp, tự chuyển bài khi tắt màn hình

## Status / Approval

- Status: READY (chờ HUMAN LEAD thử trên điện thoại ở 8080)
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
  - Sửa tiêu đề trong Xem chung (phòng).
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

## Phải giữ nguyên

- Tất cả hành vi LISTEN1 / WATCH1 đang có test: thứ tự danh sách, nhóm tập / phần Yêu thích, thẻ đếm ngược khi màn hình sáng, không cuộn trang khi tự chuyển, tim, nhớ chỗ nghe, Xem chung, PiP.
- Tab Quản lý: "Sửa tiêu đề" hoạt động y như trước.
- Không tự cuộn trang / đổi danh sách khi đang ẩn.

## Code bị thay / xóa

- `titleEditor` trong `app.js` chuyển sang module dùng chung; xóa bản trong `app.js`.

## Acceptance Criteria

1. Tab Nghe (trang tập, Yêu thích) có nút / ô sửa tiêu đề cho bài đang phát, chỉ hiện khi Short đó sửa được (`editable`, chưa xóa); trong Xem chung không hiện.
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

- ORCHESTRATOR verification 2026-11-15 (ngoài sandbox): `tests/test_web_listen.py tests/test_web_watch_party.py tests/test_web_titles.py` 191 passed; full suite `python -m pytest -q -n auto` 4344 passed, 2 skipped, 2 m 44 s. Review: OK (đường `next` của phòng khớp `watch_party.py`, 409 không double skip).

- IMPLEMENTER handoff (2026-11-15, gồm Amendment A): implementation AC 1–10 hoàn tất, sẵn sàng ORCHESTRATOR review bản sửa mới. ORCHESTRATOR đã báo solo / editor OK và 177 test targeted PASS ngoài sandbox cho bản trước Amendment A; đây là bằng chứng do ORCHESTRATOR cung cấp, không phải lượt chạy của IMPLEMENTER và không chứng minh bản Amendment A. Chưa chuyển task sang READY: full verification ngoài sandbox / điện thoại thật cho bản mới vẫn còn chờ.
- Main changes:
  - `static/title_editor.js` mới: tách editor cũ, dùng chung cho Quản lý / Nghe qua `window.AutoShort.titleEditor`; tham số hóa episode, khóa, giới hạn ký tự và callback lưu. Giữ preview, phương án AI, reset, lỗi API và thông báo restore; hủy debounce / bỏ preview trễ khi đổi bài.
  - `static/app.js`: xóa editor cũ, gọi editor dùng chung, xuất đối tượng `window.AutoShort`. `static/episode.html` và `static/favorites.html`: thêm host dưới tiêu đề và nạp module trước khởi tạo trang.
  - `static/listen.js`: tải view khi mở editor / đổi bài lúc editor đang mở; cache theo episode tối đa 5 giây, xóa cache khi đóng / lưu; chặn phản hồi trễ bằng sequence và identity. Editor chỉ dựng khi `editable && !deleted`, ẩn trong phòng. Lưu chỉ đổi title trong `all` / `items`, heading / queue / Media Session; không gọi `setState` hay thay nguồn media. Khóa editor sau khi job được nhận. `save` đã dùng `media()`; thêm timeupdate cho audio và bỏ sự kiện từ phần tử không hoạt động.
  - `static/player.js`: audio ẩn và phần tử phát hiện hành; đổi nguồn / vị trí / rate khi ẩn / hiện, tạm dừng phần tử cũ và bỏ sự kiện lập trình / phần tử không hoạt động. Solo và phòng đều phát audio nền. Phòng `ended` + auto + next đặt state lạc quan với đúng `[index, video_url]`, load / play ngay trong handler rồi gọi `onHiddenAdvance` với version cũ; không tăng version lạc quan. Callback `roomHiddenAdvance` cập nhật `rstate` theo chỉ số lạc quan, gửi `next` đúng một lần với `expect_version`, và sau lỗi chờ `W.sent()` rồi `W.poll(true)` để nhận state server. ACK / poll trùng bài không load lại; khác bài thì nạp theo server. Tắt auto / hết danh sách vẫn gửi `ended`; countdown khi sáng và PiP giữ nguyên. Media Session, retry / log dùng media hiện hành; danh sách / heading của cả solo và phòng chỉ cập nhật lại khi trang hiện.
  - `routes/watch.py`: chỉ thêm `to_audio`, `to_video`, `hidden_advance` vào `LOG_TYPES` theo amendment. `tests/test_web_listen.py`: mở rộng harness DOM / audio / visibility / Media Session và chạy cả editor thật; thêm 12 hàm test, 37 ca sau parametrize (Amendment A thêm 3 hàm / 14 ca). Harness mới có tùy chọn chạy `watch.js` thật với backend / fetch giả, gồm serialization, CAS, 409 poll và queue cache. `tests/test_web_watch_party.py`: mở rộng test validator / log thực tế cho ba event mới, page `listen`. Không sửa CSS hay file ngoài Owned paths.
- Amendment A — `watch.js` không đổi: đã kiểm `pageHidden`; chỉ `stopPolling()` ở `pagehide` đặt cờ này, `visibilitychange` không chặn poll. Harness chạy transport thật xác nhận GET tiếp tục khi hidden. Poll trong catch 409 của `command()` chưa accept state vì `pending > 0`; callback mới chờ `W.sent()` xong rồi poll lại, không sửa transport hoặc gửi lại `next`. Các định nghĩa `pauseTimer`, `hiddenPause`, `cancelPause` / `syncBlocked` và thuật toán `sync` / `seek_skipped_hidden` cũ được giữ nguyên.
- Tests:
  - PASS: `PYTHONPATH=src python -m pytest tests/test_web_listen.py tests/test_web_watch_party.py -q -k 'not http'` → **161 passed, 11 deselected**, 9.39 s. Gồm 14 ca Amendment A mới và toàn bộ hồi quy LISTEN1 / WATCH1 không cần socket.
  - PASS: `PYTHONPATH=src python -m pytest tests/test_web_watch_party.py -q -x --tb=short -k 'log_route_accepts_pip_and_retry_cap_events'` → **1 passed, 108 deselected** sau sửa assertion page `listen`.
  - PASS: `node --check` cho `app.js`, `title_editor.js`, `listen.js`, `player.js`, `watch.js`; `git diff --check`.
  - Lượt trước Amendment A KHÔNG HOÀN TẤT trong sandbox: `timeout 15s env PYTHONPATH=src python -m pytest tests/test_web_titles.py -q -x --tb=short` → exit **124**, không có output test trước timeout; đã dừng, không chờ thêm và không claim PASS. File này dùng TestClient; không chạy lại trong lượt Amendment A vì editor không đổi. ORCHESTRATOR sau đó báo 177 targeted PASS ngoài sandbox cho phần solo / editor (bản trước Amendment A).
  - Chưa chạy bản không lọc của `PYTHONPATH=src python -m pytest tests/test_web_listen.py tests/test_web_watch_party.py -q` (11 ca HTTP / TestClient đã loại theo giới hạn sandbox), full suite và 8080 / điện thoại thật; thuộc ORCHESTRATOR theo contract và delegation.
- AC → test (tên rút gọn trong bảng có prefix `test_player_js_`, trừ tên ghi đầy đủ):

  | AC | Test / bằng chứng hiện tại |
  |---|---|
  | 1 | `shared_title_editor_saves_without_reloading` (trang tập / Yêu thích), `title_eligibility_locks_errors_and_restore` (không sửa được / đã xóa), `title_ignores_late_reads_previews_and_saves` (ẩn trong phòng). PASS |
  | 2 | `shared_title_editor_saves_without_reloading` (preview, AI, reset, management callback / khóa động), `title_eligibility_locks_errors_and_restore` (job / restore, 409 / 422, thông báo hoãn). JS PASS; editor đã được ORCHESTRATOR review OK trước Amendment A |
  | 3 | `shared_title_editor_saves_without_reloading`: title / queue / Media Session đổi ngay, nguồn / vị trí / load / play / pause giữ nguyên cho cả video và audio; regroup vẫn giữ title. PASS |
  | 4 | `title_ignores_late_reads_previews_and_saves`: GET trễ, preview trễ, debounce bị hủy, save cũ giữ đúng endpoint và không ghi đè editor bài mới; cache episode. PASS |
  | 5 | `audio_handoff_session_controls_and_position`, `new_video_after_hidden_advance_and_late_media_events`, `paused_or_suspended_visibility_never_starts_playback`: nguồn / vị trí / rate, nguồn mới sau chuyển tập, đổi visibility khi đang load, promise cũ, paused / suspend. PASS trong harness; độ lệch thực cần điện thoại |
  | 6 | `hidden_advance_is_synchronous_across_groups`: hai lần next không timer / metadata, cả ranh giới tập và phần Yêu thích; auto off / hết danh sách dừng, không đổi danh sách hoặc cuộn khi ẩn. PASS |
  | 7 | `audio_handoff_session_controls_and_position` (Media Session prev / next / play / pause, save từ audio), `audio_retry_progress_giveup_and_log_batches` (retry của audio). PASS |
  | 8 | `visible_room_and_pip_keep_video`, `room_ended_fallbacks_keep_server_countdown` và hồi quy LISTEN1 / WATCH1 trong nhóm 161 test: phòng khi sáng vẫn dùng video / countdown server; PiP giữ video, ra / vào PiP đổi lại phần tử thích hợp. PASS phần không socket |
  | 9 | `audio_handoff_session_controls_and_position` (to_audio / to_video), `hidden_advance_is_synchronous_across_groups` (hidden_advance), `audio_retry_progress_giveup_and_log_batches` (retry, giới hạn batch client), `test_log_route_accepts_pip_and_retry_cap_events` (server chấp nhận và ghi event). PASS |
  | 10 | `room_hidden_advance_reconciles_without_double_skip` (3 trang × ACK / 409 trùng / 409 khác bài, hai lần next đúng version, không timer / mạng trước play, không reload khi trùng); `room_audio_remote_controls_preserve_pause_and_seek_guards` (paused / đang phát, pauseTimer, syncBlocked, remote pause / play / seek / next, Media Session, seek_skipped_hidden, poll nền với transport thật); `room_ended_fallbacks_keep_server_countdown` (auto off, cuối danh sách, visible countdown). 14 ca PASS |

  AC 9 dùng 4 hàm vì cần tách handoff, ended, giới hạn batch / retry client và validator server; test validator cũ được mở rộng, không chép helper sang file khác.
- Assertion cũ được thay theo Amendment A: `test_player_js_room_and_pip_keep_video[room]` trước đây ẩn trang rồi khẳng định phòng không tạo / phát audio. Đổi tên thành `test_player_js_visible_room_and_pip_keep_video` và chỉ giữ nhánh phòng ở màn hình sáng; nhánh PiP khi hidden giữ nguyên. Hành vi phòng khi hidden được thay bằng 14 ca AC 10 mới. Không bỏ test WATCH1 / LISTEN1 để che lỗi.
- Diff + / − (app, test): **app +311 / −141; test +553 / −26**. Riêng Amendment A so với bản đã review: **app +33 / −13; test +185 / −10**. Tính bằng `git diff --numstat` cộng 105 dòng file mới `static/title_editor.js` chưa tracked; không tính task report. Bản `titleEditor` cũ đã xóa.
- Helper mới / tái dùng:
  - Đã tìm: `rg -n 'titleEditor|editsLocked|maxChars|refreshEpisode|function el|function api|function jobActive' src/auto_short/web/static/app.js`; chuyển nguyên editor thành module tham số hóa, tái dùng `AutoShort.el` / `AutoShort.api`, không tạo bản sao.
  - Đã tìm: `rg -n 'media\(|visibilityChanged|arm\(|isProgrammed|playMedia|recover|record|load\(' src/auto_short/web/static/player.js`; tái dùng `media`, `arm`, `isProgrammed`, `playMedia`, `recover`, `record`, `load`. Thêm `selectMedia` để chọn phần tử và dừng phần tử cũ khi đổi nguồn; `switchMedia` dùng nó để chuyển cả vị trí / rate khi giữ cùng bài. Trước task không có helper chuyển video / audio; `load` cũ chỉ đặt nguồn video, không thể dùng trực tiếp cho cả hai hành vi.
  - `renderTitleEditor` mới ở listen quản lý lazy load, cache, lifecycle và callback theo bài; `renderCurrent` cũ chỉ vẽ heading / list, editor cũ bị đóng với episode của trang nên cần lớp điều phối này. `dispose` trong module hủy debounce và vô hiệu preview cũ; getter khóa dùng chung cho khóa động của management và listen.
  - Amendment A đã tìm `rg -n 'new AutoShortPlayer|pageHidden|stopPolling|visibilitychange|onHiddenAdvance|syncBlocked|seek_skipped_hidden|pauseTimer' src/auto_short/web/static/{player,listen,watch}.js tests/test_web_listen.py`. Tái dùng `setState` / `load` / `playMedia` để chuẩn bị bài lạc quan, `roomCommand`, `W.sent` và `W.poll` để đối soát. Thêm callback `roomHiddenAdvance` vì `roomEnded` đi qua countdown server, còn `roomNavigate` chỉ gửi mạng, không cập nhật index lạc quan hoặc đợi hàng lệnh trước recovery poll. Thêm `useRoomTransport` vào harness, tái dùng `useRoom` làm backend có `snapshot` / `apply`; mock command cũ không chạy serialization / pending của `watch.js` nên không kiểm được 409 poll thực tế.
  - Harness tái dùng `run_player_js` / `Element` / `metadata` / `end` hiện có. Thêm `visibility`, `titleView`, `editorInput`, `editorButton` trong cùng file để mô phỏng và thao tác editor / media; đã tìm `rg -n 'class Fake|visibilitychange|playPending' tests -g '*.py'`, không có fixture trình duyệt dùng chung đáp ứng audio + title lifecycle. Không dependency mới.
- Review: ORCHESTRATOR đã review solo / editor OK trước Amendment A. IMPLEMENTER đã rà diff / Scope / AC 10, so với bản trước Amendment A, và chạy kiểm tra trên; independent review của Amendment A còn thuộc ORCHESTRATOR. Không đổi endpoint sửa title / security / dependency / public API. Amendment chỉ mở rộng enum log nội bộ như đã duyệt.
- Known limitations: điện thoại thật mới xác nhận được chính sách autoplay / background của Chrome Android và độ lệch thực tế ≤ 1 s; 11 ca HTTP và full suite / manual checklist của bản Amendment A chưa xác minh ngoài sandbox; lần báo 177 targeted PASS của ORCHESTRATOR là trước Amendment A. Phát nền / chuyển bài phòng trên điện thoại thật vẫn cần kiểm chứng. Khi editor đang khóa, đóng / mở lại lấy trạng thái job mới; đổi bài cũng lấy cache mới sau hạn 5 giây. Giữ task IN_PROGRESS cho tới khi required verification được ORCHESTRATOR chạy PASS.
- PR: không có; không commit / push / PR, không gọi agent khác hoặc mạng thật.
