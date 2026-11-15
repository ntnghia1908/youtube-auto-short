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

- Amendment B — IMPLEMENTER handoff (2026-11-15): hoàn tất trên base `0f4943a`, không commit. Chỉ sửa `src/auto_short/web/static/listen.js`, `tests/test_web_listen.py` và Result này; giữ nguyên amendment / AC do ORCHESTRATOR cập nhật.
- Main changes:
  - `renderTitleEditor` lấy bài phòng từ `all` theo `rstate.video_url`, dùng `items[index]` cho solo. Bỏ các guard `inRoom` chặn editor; vẫn kiểm `editable && !deleted`, key / sequence và host. `/watch` không có host; bài phòng không thuộc `all` cũng không có editor.
  - `onSaved` ghi `editedTitles` (Map URL → title), cập nhật `all` / `items`, `rstate.queue`, `rstate.title` và title của player hiện hành tại chỗ. Cập nhật heading / danh sách / Media Session, không gọi `player.setState`, không đổi URL / vị trí / trạng thái phát và không gửi lệnh phòng.
  - `roomHandler` áp Map lên `data.queue` / `data.title` trước `setState` / render, nên snapshot chữ cũ hoặc queue cache của `watch.js` không ghi đè chữ đã sửa. Các title khác, kể cả cùng clip id nhưng khác episode / URL, giữ đúng bài.
- Tests đã chạy trong sandbox:
  - PASS: `PYTHONPATH=src python -m pytest tests/test_web_listen.py -q -k "player_js or static or countdown or overlay"` → **46 passed, 24 deselected**, 5.44 s.
  - PASS: `PYTHONPATH=src python -m pytest tests/test_web_listen.py -q -x --tb=short -k 'room_title_editor'` → **7 passed, 63 deselected** trong vòng triển khai. Lượt 46 test sau đó gồm cả phần mở rộng test queue cache.
  - PASS: `node --check src/auto_short/web/static/listen.js`; `git diff --check`.
- AC → test (prefix tên rút gọn là `test_player_js_`):

  | AC | Bằng chứng |
  |---|---|
  | 1 (Amendment B) | `room_title_editor_keeps_saved_title_across_polls`: trang tập / Yêu thích đều có editor cho bài phòng, kể cả bài bị lọc khỏi solo `items`; mở editor mới GET đúng episode `.kt`. `room_title_editor_needs_local_item_and_host`: không editor khi bài ngoài `all` hoặc `/watch` không có host. `title_eligibility_locks_errors_and_restore`: vẫn giữ điều kiện editable / chưa xóa và khóa job. PASS |
  | 3 (Amendment B) | `room_title_editor_keeps_saved_title_across_polls`: cả video / audio đang phát giữ src, time, load / play / pause count, sourceKey, index, version, receivedAt sau lưu; title / queue / Media Session đổi ngay, hai poll chữ cũ (full / omitted queue) vẫn giữ chữ mới; số POST phòng và dữ liệu backend phòng không đổi. PASS |
  | 4 | `title_ignores_late_reads_previews_and_saves`: vẫn bỏ GET / preview / save trễ của bài cũ. `room_title_editor_keeps_saved_title_across_polls`: đổi bài phòng / quay lại vẫn chọn đúng editor và title theo URL, không lẫn hai episode có cùng clip id. PASS |
  | 2, 5–10 | Các test JS hiện có trong nhóm 46 test giữ PASS, gồm editor dùng chung / lỗi / restore, solo, audio nền phòng / optimistic next / 409, pause / seek guard, PiP, countdown và overlay. Không chạy lại toàn bộ HTTP / full suite trong lượt B. |

- Test cũ sửa assertion theo Amendment B:
  - `test_player_js_title_ignores_late_reads_previews_and_saves`: sau khi vào phòng, đổi assertion host bị ẩn thành có nút editor lazy; vẫn kiểm không tải thêm episode cho tới khi mở editor.
  - `test_player_js_visible_room_and_pip_keep_video[room]`: đổi assertion editor bị ẩn thành hiển thị. Các assertion media / ended / PiP giữ nguyên.
  - Harness `document.getElementById` trả `null` cho `listen-title-editor` ở `/watch`, khớp HTML thực tế; thêm static guard không có host tại `/watch`. Không bỏ test để che lỗi.
- Diff so với `0f4943a` (không tính docs): **app +17 / −7; test +86 / −4**.
- Helper / reuse: không thêm hàm helper hay dependency. Đã tìm `rg -n 'function renderTitleEditor|function roomHandler|onSaved\(|const (titleViews|editedTitles|same)|function (useRoomTransport|titleView)|const editor(Input|Button)' src/auto_short/web/static/listen.js tests/test_web_listen.py`; dùng lại editor, `renderCurrent`, `same`, `roomHandler`, `useRoomTransport`, `titleView`, `editorInput` / `editorButton`. Map mới giữ title qua các snapshot; không dùng `titleViews` vì cache đó chứa view / trạng thái job, hết hạn và bị xóa sau lưu, nên không thể bảo vệ title trước poll chữ cũ.
- Verification nền đã có trước B (ORCHESTRATOR ghi cho `0f4943a`, không phải lượt chạy mới của IMPLEMENTER): targeted `tests/test_web_listen.py tests/test_web_watch_party.py tests/test_web_titles.py` **191 passed**; full suite `python -m pytest -q -n auto` **4344 passed, 2 skipped**, 2 m 44 s; review optimistic next / 409 OK. Không dùng các kết quả này để claim full suite của bản B đã PASS.
- Known limitations / next verification: title phòng mới là cập nhật cục bộ trên trang đang mở, không gửi queue title cho người khác (đúng Amendment B). ORCHESTRATOR / HUMAN LEAD cần thử lại 8080: mở editor trong phòng, lưu và tiếp tục nghe qua các lần poll. Full suite ngoài sandbox và kiểm tra điện thoại của bản B chưa chạy trong lượt này.
- PR / integration: không commit / push / PR; không gọi agent khác hoặc mạng thật.
