# Task: LISTEN2 — Sửa tiêu đề ngay trong tab Nghe + nghe tiếp, tự chuyển bài khi tắt màn hình

## Status / Approval

- Status: READY (Amendment G chạy thật 8080 2026-11-15)
- Type: FEATURE + BUG
- Change class: S1 — chỉ client (HTML / JS / CSS) của tab Nghe, dùng lại endpoint sửa tiêu đề có sẵn; không endpoint mới, không dependency, không đổi security model / public API
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25), quota 5 h 3 % / tuần 0 % (2026-11-15)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-15: "1. tôi muốn khung sửa tiêu đề nằm ngay trên trang nghe playlist để tôi nghe tới đâu sửa luôn; 2. nghe mà tắt màn hình vẫn bị vấn đề, chuyển bài không được… có phải do player hay không, có thể dùng một lib player nào đó có sẵn để fix"; chọn "Tự đổi khi tắt màn hình" và "Đồng ý, làm luôn"
- Parallel group: —
- Owned paths: `src/auto_short/web/static/player.js`, `listen.js`, `episode.html`, `favorites.html`, `app.js` (chỉ tách / dùng lại trình sửa tiêu đề), file JS mới cho trình sửa tiêu đề dùng chung (nếu tách), `style.css` (khối nhỏ), `tests/test_web_listen.py`, `src/auto_short/web/routes/watch.py` (chỉ thêm tên sự kiện log được phép — amendment 2026-11-15, Codex BLOCKED vì AC 9), `tests/test_web_watch_party.py` (test validator), `src/auto_short/web/static/watch.js` (Amendment A, nếu cần), `src/auto_short/web/routes/files_catchall.py` + module mới cho cache audio (Amendment F), test mới cho route audio, file này
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

## Amendment D — phát lại bền hơn khi bị dừng lúc nền (2026-11-15)

Thử thật bản `4e14886`: tắt màn hình từ trang và chuyển bài khi ẩn đã chạy (`hidden_advance` ×2, `video_resync` khi hiện lại). Còn lỗi: HUMAN LEAD "chuyển qua màn hình chính thì vẫn có tiếng, khi tắt màn hình thì mới tắt tiếng; lúc đó màn hình khóa có điều khiển Auto Short", phải bấm Play. Log: `pause_hidden → retry_ok → pause_hidden` ×4 cùng `t` → `retry_gave_up` trong ~10 s (có lần 1 lần retry là chạy tiếp). Android / Chrome dừng audio lúc tắt màn hình (nhiều khả năng mất audio focus tạm thời); retry dồn trong 10 s rồi bỏ cuộc.

- Retry khi ẩn bền hơn: giữ 1 / 3 / 10 s đầu, sau đó thử lại mỗi 15 s tới 5 phút kể từ lần dừng (vẫn chỉ khi ẩn, `wantsPlay`, cùng bài, audio dừng và chưa hết bài); tiến độ phát (currentTime tăng) thì reset bộ đếm. Bỏ ngưỡng 6 lần / 2 lần "flat" (thay bằng hạn 5 phút). Dừng retry ngay khi người dùng bấm dừng (Media Session / control) hoặc trang hiện lại.
- Media Session `play` từ màn hình khóa luôn phát lại được (kể cả sau khi đã bỏ cuộc), và đặt lại vòng retry.
- Log chẩn đoán thêm `freeze` / `resume` (Page Lifecycle `document` events) và trường `rs` (audio.readyState) / `ns` (networkState) trên `pause_hidden`; tên log mới thêm vào `LOG_TYPES`.
- AC 11: vòng retry ẩn kéo dài tới 5 phút (test giả thời gian), reset khi có tiến độ, dừng khi người dùng dừng / trang hiện; Media Session play sau bỏ cuộc phát lại; `freeze` / `resume` được ghi.

## Amendment E — pause của video không được tự dừng audio (2026-11-15)

Log `4e14886`: mỗi lần trang ẩn, ~10 ms sau `visibility hidden` có `pause_hidden` của audio. Nguyên nhân trong code: Chrome Android dừng `<video>` lúc app vào nền, có khi trước khi `visibilityState` thành `hidden`; handler pause của video (`player.js` ~dòng 95) coi đó là thao tác người dùng và gọi `audio.pause()` → trang nền phải *bắt đầu* phát lại → bị chặn. HUMAN LEAD: "đang nghe vẫn có lúc không chuyển bài được khi tắt màn hình".

- Pause của video chỉ chuyển sang audio khi là thao tác người dùng: trang đang hiện **và** (`navigator.userActivation?.isActive` đúng, hoặc sau 1500 ms trang vẫn hiện, video vẫn dừng, audio vẫn phát, cùng bài — giống cửa sổ 1500 ms của WATCH1 / `hiddenPause`). Trang ẩn trong 1500 ms đó → bỏ qua. Không có `navigator.userActivation` → chỉ dùng nhánh chờ 1500 ms.
- Video bị dừng mà không chuyển sang audio thì video theo lại audio khi trang hiện (`syncVideo`).
- AC 12: pause của video lúc hiện rồi ẩn trong < 1500 ms không dừng audio, không gửi `onAction("pause")`; pause với userActivation đang active dừng audio ngay; pause không có activation mà trang vẫn hiện sau 1500 ms thì dừng audio.

## Amendment F — bản chỉ có tiếng (.m4a) cho tab Nghe (2026-11-15)

Bằng chứng (trang thử `/static/bgtest.html` trên 8080, điện thoại HUMAN LEAD, Chrome + Samsung Internet): phát Short **mp4** bằng `<audio>` (có / không có `<video>`) đều bị trình duyệt dừng khi ẩn / tắt màn hình (file có track hình → chính sách chặn video nền). Cùng 3 Short tách tiếng **.m4a** (`ffmpeg -vn -c:a copy`) thì ẩn trang / tắt màn hình phát liên tục, chuyển bài khi ẩn chạy 2/3 lần. Link mp3 ngoài cũng phát nền bình thường. HUMAN LEAD: "Rất tốt, chuyển trình duyệt hay tắt màn hình đều mượt mà không bị ngắt tiếng"; "Tiếp tục".

- Route mới, sau login như `/files`: `GET /files/{episode_id}/{clip_id}.m4a` (cùng tham số `v`), trả audio-only AAC (`audio/mp4`, hỗ trợ Range). Tách bằng `ffmpeg -vn -c:a copy` (không mã hóa lại), cache dưới `<workspace>/_audio_cache/` theo episode + clip + dấu bản (sha / mtime của mp4) để bản render lại sinh file mới; khóa theo key để không tách trùng; ghi file tạm rồi đổi tên. Giới hạn dung lượng cache (vd. 2 GB, xóa cũ nhất). Short ở kho 3090 (`StoredShort`): lấy đủ byte qua `StoreClient` vào file tạm rồi tách; kho tắt → 503 như mp4.
- Không đánh dấu "đã tải" (`ctx.tracked` / `mark_downloaded`) cho `.m4a`.
- Client tab Nghe (một mình + Xem chung): audio phát URL `.m4a` tương ứng `video_url` (cùng `v`); video vẫn mp4 muted. Lỗi tải `.m4a` (404 / 503 / decode) → audio quay về mp4 của bài đó, ghi log `audio_fallback`.
- Out of scope ở F: cách chuyển bài khi ẩn (chờ kết quả thử chuyển bài, Amendment G).
- AC 13: route trả audio-only (ffprobe chỉ có stream audio), Range 206, cache dùng lại (lần 2 không gọi ffmpeg), mp4 đổi → m4a mới, kho tắt → 503, id sai → 404, không tick đã tải. AC 14: client dùng `.m4a`, fallback mp4 khi lỗi.

## Amendment G — chuyển bài khi ẩn: bài sau có 1,5 s im lặng ở đầu, bật sớm 0,5 s (2026-11-15)

Thử thật trên trang `/static/bgtest.html` (file .m4a 25 s cuối của 3 Short, ẩn / tắt màn hình, HUMAN LEAD, ảnh nhật ký 19:20–19:27 và sau đó):
- E (hết bài → đổi `src` + `play()` cùng phần tử): Chrome hoãn bài mới tới khi trang hiện lại.
- F (phần tử thứ hai bật bài sau âm lượng đầy, sớm 1 s, dừng bài cũ): không dừng; "chuyển bài cảm giác hơi gấp".
- G (mồi âm lượng 0 / 0.01): Chrome chặn (`AbortError`), cả hai bản như nhau.
- H (như F, file bài sau có sẵn 1,5 s im lặng ở đầu, bật sớm 0,5 s): HUMAN LEAD "Cách H đã ổn".

Làm H:
- Server (`audio_cache.py`): bản `.m4a` có 1,5 s im lặng ở đầu: `-af adelay=1500:all=1 -c:a aac -b:a 128k` (mã hóa lại phần tiếng, ~1 s / Short). Hằng số `AUDIO_PAD = 1.5` ở một chỗ; cache key gồm bản pad để file cũ không pad bị thay.
- Client: thời gian nội dung = `audio.currentTime − pad` (pad = 1.5 cho `.m4a`, 0 khi fallback mp4). Mọi vị trí ra ngoài / vào trong (state, phòng, nhớ chỗ nghe, tua, video muted theo audio, log `t`) dùng thời gian nội dung; bắt đầu / tua bài khi trang hiện thì đặt audio tại `vị trí + pad` (không nghe 1,5 s im lặng khi tự bấm).
- Chuyển bài khi ẩn (một mình và Xem chung, theo luật auto / bài tiếp hiện có khi ẩn): hai phần tử `<audio>`; phần tử còn lại nạp sẵn `.m4a` bài sau khi bài hiện tại bắt đầu. Khi bài hiện tại còn ≤ 0,5 s (sự kiện `timeupdate`, không timer): phần tử sau `currentTime = 0`, âm lượng đầy, `play()`; khi resolve: dừng bài cũ, phần tử sau thành `media()`, cập nhật state như chuyển bài khi ẩn hiện nay (một mình `onNavigate("next")`; phòng state lạc quan + `next` với `expect_version`) mà **không nạp lại** audio. Nếu `ended` tới trước khi kịp bật sớm: `play()` phần tử sau ngay trong handler `ended` (đường cũ) + retry như D. Log `hidden_advance`, `early_start`, `early_blocked` (kèm `err`); thêm vào `LOG_TYPES`.
- Màn hình sáng: giữ đếm ngược 3 s như cũ.
- AC 15: route `.m4a` dài hơn mp4 ≈ 1,5 s, đầu file im lặng, cache key đổi theo pad; harness: vị trí nội dung = audio − pad (state, save, video sync, room); trang ẩn: bật sớm ở ≤ 0,5 s cuối, âm lượng đầy, từ 0, không `load()` lại, state đổi bài, phòng gửi `next` với `expect_version`; `ended` trước → đường cũ; fallback mp4 pad 0.

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

### Amendment G (bản H) — READY implementation (base `25d62f5`, chưa commit)

- `audio_cache.py`: `AUDIO_PAD = 1.5`, encode AAC 128k với `adelay`, cache key gồm pad / kiểu encode. `player.js` có hai audio, nạp trước bài kế, phát âm lượng 1 từ thời gian file 0 ở ≤ 0,5 s cuối khi ẩn; resolve mới dừng bài cũ và dùng luôn audio mới, không reload. `ended` trước thì phát phần tử đã nạp ngay trong handler; lỗi play nền vào retry D. Giữ countdown sáng, fallback mp4 pad 0, log `early_start` / `early_blocked` trong validator.
- `position` / `seek` / `pad` quy đổi clock file ↔ nội dung cho state, phòng, video, log và save. `listen.js` nghe timeupdate cả hai audio (chỉ save phần tử đang phát), lấy next theo index lạc quan của player; giữ nguyên syncBlocked / pauseTimer / hiddenPause và xử lý 409. Promise trễ bị chặn sau pause / seek / auto off / hiện trang / đổi bài / suspend; nếu đã ended thì quay về đường kết thúc cũ.
- AC 15 → `test_audio_route_only_audio_range_cache_and_render_version` kiểm duration +1,5 s, PCM đầu im lặng, thay pad đổi key (thay assertion AAC packet hash không đổi của F vì H encode lại). Harness mới: `test_player_js_padded_audio_keeps_external_content_clock` (2 ca), `test_player_js_hidden_early_start_reuses_preloaded_audio` (4 ca, đổi audio hai lần, solo / phòng / watch, expect_version), `test_player_js_early_start_failure_end_and_cancellation` (12 ca, gồm ended trước / play bị chặn + retry). Test cũ giữ tên; sửa clock thành thời gian nội dung và tham chiếu active audio sau handoff ở các ca video follows / hidden advance / room reconcile, giữ kiểm 409 không double skip.
- Verification: `PYTHONPATH=src python -m pytest tests/test_web_listen.py tests/test_web_watch_party.py tests/test_web_audio.py -q -k "not http"` → **226 passed, 12 deselected, 15.01 s**; `git diff --check` PASS. Chỉ đổi 4 file app (`audio_cache.py`, `player.js`, `listen.js`, `routes/watch.py`), 3 file test nêu trên và contract; diff riêng G không tính docs: **app +228 / −113; test +204 / −55**.
- Reuse: đã tìm `rg -n 'currentTime' src/auto_short/web/static/player.js src/auto_short/web/static/listen.js` cùng các điểm getNext / onHiddenAdvance / timeupdate; giữ arm / isProgrammed / loadMedia / playMedia / recover / record và callback điều hướng hiện có. Thêm helper clock / preload / handoff vì đường một audio không đổi được phần tử mà giữ playback; `advanceHidden` / `finishEnded` tách nguyên logic cũ để dùng lại, `programKey` tách event mark theo từng audio. Không đưa bgtest.html vào repo. HTTP bị loại theo filter; chưa chạy full suite hoặc thử bản tích hợp trên điện thoại / 8080. Không commit / push / PR, mạng thật hay agent khác.

### Amendment F — kết quả trước G (đã commit `25d62f5`)

- File đổi: `routes/files_catchall.py`, module mới `web/audio_cache.py`, `static/player.js`, `routes/watch.py`, `tests/test_web_audio.py` mới, `tests/test_web_listen.py`, `tests/test_web_watch_party.py`, contract này. `listen.js` dùng chung player nên không cần sửa: state / queue / sourceKey vẫn giữ URL mp4, chỉ nguồn audio đổi sang m4a (giữ query `v`); video vẫn mp4 muted.
- Server: tách AAC `-vn -c:a copy`, FileResponse `audio/mp4` + Range; cache `<workspace>/_audio_cache` theo episode / clip / stat hoặc SHA bản kho, khóa cùng key, file tạm + rename, hạn 2 GiB xóa cũ nhất. Nguồn kho tải đủ byte, kiểm size / SHA, đóng stream và dọn tạm kể cả khi lỗi. M4a bỏ qua cả `tracked` và `mark_downloaded`, kể cả khi có `download` / `dl`.
- Client: lỗi nguồn / decode m4a → fallback mp4 một lần mỗi bài, giữ vị trí / tốc độ / trạng thái pause, không reload video hoặc thay sourceKey; log `audio_fallback`. Đã đổi assertion audio.src trong các test nền / room / video hiện có sang m4a, giữ nguyên assertion video_url / sourceKey mp4; không xóa test cũ.
- Reuse: đã tìm `rg -n 'ffmpeg|def open_stream' src/auto_short -g '*.py'` và `rg -n 'StoredShort|def short_locations' src/auto_short/web/episodes.py`; dùng lại `render.stage._run`, `ep.short_locations`, `ep.StoredShort`, `StoreClient.open_stream`, FileResponse, arm / playMedia / record. Thêm `cached_audio` / `_prune` vì chưa có cache tách AAC có version / khóa / quota; `audioUrl` / `loadMedia` gom ánh xạ URL và lập trình load dùng chung cho đổi bài / fallback.

| AC | Test / kết quả trong sandbox |
|---|---|
| 13 | `test_audio_route_only_audio_range_cache_and_render_version`: ffprobe chỉ AAC, packet hash không đổi, Range 206 / 416, cache hit không gọi ffmpeg, đổi mtime sinh bản mới. Các test `invalid_or_missing`, `released_short_stream_and_failures`, `serializes_same_key_and_evicts_oldest`, `failed_extraction`, `uses_existing_files_login_boundary`: PASS; không tick / track, kho tắt 503, id sai 404, khóa / quota / dọn tạm / auth |
| 14 | `test_player_js_audio_only_source_and_one_fallback_per_track`: solo / phòng × lỗi 404 / 503 / decode (6 ca PASS), query v, giữ clock / pause / video, không fallback lặp / reload khi poll, bài mới thử lại m4a; validator nhận `audio_fallback`: PASS |

- Verification: `PYTHONPATH=src python -m pytest tests/test_web_audio.py tests/test_web_listen.py tests/test_web_watch_party.py -q -k '(audio_route or audio_cache or player_js or static or log) and not http'` → **109 passed, 111 deselected, 10.68 s**. `node --check src/auto_short/web/static/player.js` và `git diff --check` PASS. Diff riêng F (không tính docs): **app +127 / −10; test +285 / −14**.
- Giới hạn: lượt đầu cùng nhóm test treo tại AnyIO worker I/O của FileResponse, đã dừng; lượt chẩn đoán `-vv -o faulthandler_timeout=15` xác nhận rồi dừng. Helper test `serve` chạy FileResponse / Range thật, chỉ thay worker I/O bằng gọi đồng bộ để không cần socket wakeup. Chưa chạy HTTP/TestClient (có thêm `test_http_audio_route_login_and_range` cho ORCHESTRATOR), full suite hoặc điện thoại / 8080; không claim các phần đó PASS. Không mạng thật, agent khác, commit / push / PR. Cách chuyển bài khi ẩn giữ nguyên, thuộc Amendment G nếu cần.

### Kết quả trước F (đã commit trong `93d7791`)

- Amendment E: pause video có userActivation active dừng audio ngay; còn lại chờ 1500 ms và kiểm cùng bài / còn visible / video dừng / audio phát. Hủy timer khi visibilitychange, đổi bài hoặc Play; mirror không tự play video trong lúc chờ. Giữ nguyên logic retry / log của D, không thêm helper.
- AC 12: `test_player_js_video_pause_requires_activation_or_visible_grace` có 3 ca PASS. Lệnh listen `-k "player_js"`: **58 passed, 26 deselected**, 4.19 s; lệnh watch-party `-k "player_js or static"`: **115 deselected, exit 5** (không có test khớp, không claim PASS).
- Chỉ sửa E trong `player.js`, harness / 3 ca tại `tests/test_web_listen.py` và ba dòng Result này; giữ các thay đổi D chưa commit. Không chạy thêm test / full suite, không commit; còn thử lại điện thoại / 8080.

- Amendment D — IMPLEMENTER handoff (2026-11-15), base `4e14886`: hoàn tất, không commit. Chỉ sửa player, validator log, hai file test và Result này; không sửa audio-clock / editor / optimistic next của C / B / A.
- `player.js`: thay ngưỡng attempts 6 / flat 2 bằng hạn 300000 ms từ lần dừng. Retry ở 1 / 3 / 10 giây rồi mỗi 15 giây; chỉ gọi play khi hidden, muốn phát, cùng sourceKey, audio đang dừng / chưa ended. Play thành công nhưng chưa tiến thời gian không xóa vòng retry. Tiến độ qua timeupdate, kiểm tra 2 giây sau retry hoặc callback retry sẽ reset hạn / attempts. Pause, hiện trang hoặc đổi bài hủy timer; Media Session Play reset vòng và bỏ token playPending cũ để vẫn phát được sau give-up / promise cũ bị treo. Nút Play / control video dùng cùng reset.
- Log: thêm document `freeze` / `resume`, freeze dùng flushLog beacon hiện có; `pause_hidden` luôn kèm `rs` / `ns` của audio. `routes/watch.py` nhận hai type và kiểm rs là int 0–4, ns là int 0–3 (không nhận bool / chuỗi / float). Giới hạn batch / rate / auth giữ nguyên.
- Verification: **PASS 86 test, 110 deselected, 11.73 s** bằng `PYTHONPATH=src python -m pytest tests/test_web_listen.py tests/test_web_watch_party.py -q -k '(player_js or static or log) and not http'`. Loại HTTP theo giới hạn sandbox và TestClient đã treo ở các lượt trước; không thử lại test đã biết treo. PASS `node --check src/auto_short/web/static/player.js`, `git diff --check`. Không chạy full suite hay nhóm toàn bộ `not http`; ORCHESTRATOR chạy full suite.
- AC 11 → test:

  | Test | Bằng chứng |
  |---|---|
  | `test_player_js_background_retry_five_minute_limit_and_lock_screen_restart` | Solo / phòng × play bị từ chối / thành công rồi bị pause lại / promise treo: đúng mốc 1, 3, 10, 25 giây; vượt 6 lần vẫn thử, 299999 ms chưa give-up, 300000 ms dừng; màn hình khóa Play phát lại và reset vòng; freeze / resume và rs / ns được ghi. 6 ca PASS |
  | `test_player_js_background_retry_resets_on_progress_and_cancels_on_controls` | Tiến độ ngay trước hạn cũ mở lại thời hạn; pause, hiện trang, đổi bài hủy retry cũ. 4 ca PASS |
  | `test_player_js_audio_retry_progress_giveup_and_log_batches` | Test cũ (~949) đổi assertion flat / give-up sớm thành reset khi có tiến độ và give-up sau 5 phút; giữ retry_ok / retry_blocked / cap batch. PASS |

- `tests/test_web_watch_party.py`: mở rộng test logger hiện có (~525) cho freeze / resume / pause_hidden có rs / ns; thêm 6 payload rs / ns sai kiểu hoặc ngoài giới hạn vào test validator. Nhóm log PASS.
- Diff riêng D so với `4e14886` (không tính docs): **app +55 / −34; test +80 / −6**.
- Helper / reuse: đã tìm `rg -n 'hiddenRun|checkRetryProgress|giveUpRetry|attempts|\.flat|cancelRecovery|freeze|resume|networkState' src/auto_short/web/static/player.js tests/test_web_listen.py src/auto_short/web/routes/watch.py`. Dùng lại recover / playMedia / progressChecks / record / flushLog / harness; thêm `resetRetry` vì cancelRecovery cũ chỉ hủy timer, không reset hạn, attempts, give-up hoặc token play đang treo. Không dependency / module mới.
- Giới hạn: chưa thử D trên điện thoại / 8080; timer vẫn chịu scheduling / freeze của trình duyệt, callback dùng elapsed time để kiểm hạn khi chạy lại. Full suite và kiểm chứng thực tế thuộc ORCHESTRATOR / HUMAN LEAD. Không claim full suite hoặc thử thật PASS cho D; không commit / push / PR, không gọi agent khác hay mạng thật.
- ORCHESTRATOR verification Amendment D + E 2026-11-15: full suite `-n auto` 4371 passed, 2 skipped (2 m 46 s).
- ORCHESTRATOR verification Amendment F 2026-11-15: full suite `-n auto` 4392 passed, 2 skipped (2 m 45 s). Review OK.
- ORCHESTRATOR verification Amendment G 2026-11-15: full suite `-n auto` 4410 passed, 2 skipped (3 m 06 s). Review OK. 8080 = `2150a6e`. Chạy thật trên điện thoại (trang Nghe, một mình, HUMAN LEAD ~20:10–20:40 giờ VN): hai client đều có `early_start` → `hidden_advance` khi trang ẩn và bài sau phát tiếp; HUMAN LEAD: "Bây giờ thì lại ổn rồi". Lần đứng trước đó (client cũ dừng giữa bài ở 55,7 s / 14,6 s, `retry_ok` rồi `pause_hidden` lặp lại) trùng lúc client thứ hai bắt đầu phát, nên có thể hai trang tranh audio focus; chưa tái hiện, không sửa. Một lần `audio_fallback` err 4 lúc tạo `.m4a`, mp4 dự phòng phát được. Xem chung chưa thử trên điện thoại (chỉ có test tự động). Đã xóa trang thử `bgtest.html` và `bgtest-*.m4a` khỏi web checkout.
