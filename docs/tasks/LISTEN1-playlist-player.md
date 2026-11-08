# Task: LISTEN1 — Nghe theo danh sách cả bộ kinh (Short → khai thị, xuyên tập), view mặc định của trang tập

## Status / Approval

- Status: DONE (chờ merge PR)
- Type: FEATURE
- Change class: S1 — 1 endpoint đọc mới sau login, trang tập thêm tab; không dependency, không đổi security model / API hiện có
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25); quota thấp thì subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-08: "Nghe theo playlist rất tiện lợi, có thể implement thêm view nghe theo playlist như này (không cần phải nghe chung mới view này). Và đặt làm view mặc định. View playlist này nên hoàn thiện một chút có theo thông tin tập nào..."; chọn: danh sách = cả bộ kinh; khai thị "Chọn 1. Nhưng mặc định cả 2" (công tắc Short / Khai thị / Cả hai, mặc định Cả hai); "Playlist nên cho chạy xuyên từ short qua khai thị luôn cho tiện"; mặc định = trang tập mở ở chế độ Nghe
- Parallel group: —
- Owned paths: `src/auto_short/web/listen.py` (mới), `src/auto_short/web/routes/playlists.py` (chỉ endpoint mới), `src/auto_short/web/static/player.js` (mới, lõi trình phát tách từ `watch.js`), `src/auto_short/web/static/watch.js`, `watch.html`, `listen.js` (mới), `episode.html`, `app.js` (chỉ chuyển tab Nghe / Quản lý), `style.css` (khối mới), `tests/test_web_listen.py` (mới), `tests/test_web_watch_party.py` (nếu cần theo refactor), file này
- Dependencies: WATCH1 (nhánh `feature/watch1-watch-together`, chưa merge — task này xếp chồng lên)
- Base commit / branch: `89250f2` (WATCH1 vòng 3) / `feature/listen1-playlist-player` (worktree `~/projects/yas-listen1`)
- Human Lead approval: accepted 2026-11-08 ("APPROVED LISTEN1")
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`.

## Goal

Mở trang một tập là nghe được ngay: trình phát danh sách của cả bộ kinh, bắt đầu từ tập đó. Trong mỗi tập phát các Short rồi tới khai thị, hết tập thì chạy tiếp sang tập sau. Màn hình luôn cho biết đang nghe tập nào, Short hay khai thị, bài thứ mấy. Có Nghe nền, tim, Trước / Tiếp như trang Xem chung, nhưng chỉ dùng một mình.

## Scope

- In scope:
  - `GET /api/playlists/{playlist_id}/listen`: danh sách theo thứ tự số tập (`index` của entry bộ kinh), trong mỗi tập: Short đã render, chưa xóa, theo thứ tự của render manifest; rồi tới khai thị đã render của tập đó (khai thị episode của tập). Mỗi mục: `kind` (`short` | `khaithi`), `episode_id`, `base_episode_id`, `ep_index`, `ep_title`, `clip_id`, `title` (chữ trong file), `duration`, `video_url`, `fav` (`{playlist_id, episode_id, clip, favorite}` cùng dạng WATCH1). Kèm tên bộ kinh. Chỉ đọc file sẵn có (render manifest + favorites), không chạy job, không gọi kho 3090 / mạng.
  - Trang tập: 2 tab **Nghe** (mặc định) và **Quản lý** (toàn bộ nội dung hiện có của trang, không đổi). Lựa chọn tab được nhớ trong `localStorage`. Tập không thuộc bộ kinh nào → danh sách chỉ gồm Short + khai thị của tập đó.
  - Trình phát Nghe:
    - bắt đầu ở mục đầu của tập đang mở (trang khai thị thì bắt đầu ở khai thị của tập đó);
    - hết mục thì tự sang mục kế, xuyên Short → khai thị → tập sau;
    - Trước / Tiếp, Nghe nền (`<audio>` dùng file tiếng `/api/watch/audio/…` của WATCH1 Amendment B + Media Session), tim ♡/♥ (gọi API yêu thích có sẵn); không có ô tốc độ (theo WATCH1 AC 14); Trước / Tiếp là nút biểu tượng ⏮ / ⏭ có `aria-label` + `title` (HUMAN LEAD 2026-11-08: "nút trước và tiếp nên đổi thành icon mũi tên cho gọn", áp cho cả Xem chung và Nghe);
    - công tắc **Short / Khai thị / Cả hai** (mặc định Cả hai, được nhớ).
  - Thông tin: tên bộ kinh; "Tập N — <tên video>"; nhãn Short / Khai thị; tiêu đề clip; "mục i / tổng". Danh sách bên dưới nhóm theo tập (tiêu đề tập), mục đang phát được tô, bấm để nhảy; nhảy nhanh tới tập.
  - Nhớ chỗ đang nghe theo bộ kinh (`localStorage`: episode + clip + giây). Mở lại trang tập đó → nút "Nghe tiếp từ …" (không tự nhảy).
  - Nút "Xem chung" trong Nghe: đẩy tối đa 300 mục từ mục hiện tại sang phòng WATCH1 rồi mở `/watch`.
  - Refactor: tách lõi trình phát của `watch.js` (chọn video / audio, Nghe nền, Media Session, chặn sự kiện do code gây ra, tim) thành `player.js`; `watch.js` (phòng, polling) và `listen.js` (danh sách cục bộ) cùng dùng.
- Out of scope: tự đánh dấu "Đã xem", đổi thứ tự / sắp danh sách, trang chủ / trang bộ kinh mở vào Nghe, phát video ghép / bản dọc / HD, lưu chỗ nghe trên server.

## Authority / key decisions

- HUMAN LEAD 2026-11-08 (các lựa chọn ở Authorization source).
- S1 cục bộ: danh sách tạo phía server từ file manifest sẵn có (một request cho cả bộ kinh, khoảng ≤ 130 tập); chỗ nghe lưu ở trình duyệt.

## Phải giữ nguyên

- Mọi hành vi của trang tập trong tab Quản lý (sửa tiêu đề, đăng, xóa, loop, Đã xem, tim, Bài đăng, kind-bar…) và các URL hiện có.
- WATCH1: phòng, đồng bộ, Nghe nền, tim, bỏ qua pause khi ẩn trang — test `tests/test_web_watch_party.py` vẫn PASS.
- Video Short đang offload lên kho 3090 vẫn phát qua `video_url` như trang tập hiện tại.

## Code bị thay / xóa

- Phần lõi trình phát trong `watch.js` chuyển sang `player.js`; không để lại bản sao trong `watch.js`.

## Acceptance Criteria

1. API trả đúng thứ tự: tập tăng dần; trong tập, Short (thứ tự manifest) rồi khai thị; bỏ Short / khai thị chưa render hoặc đã xóa; `fav.favorite` khớp tim hiện tại.
2. API: bộ kinh không tồn tại → 404; chưa đăng nhập → 401; tập không có khai thị thì chỉ có Short.
3. Trang tập mở tab Nghe mặc định; chọn Quản lý thì lần sau mở Quản lý; tab Quản lý giống hệt trang hiện tại.
4. Nghe bắt đầu ở tập đang mở; hết Short cuối của tập thì sang khai thị của tập đó, hết khai thị thì sang Short đầu của tập sau; công tắc Short / Khai thị / Cả hai lọc đúng.
5. Màn hình hiện bộ kinh, "Tập N — tên", nhãn Short / Khai thị, tiêu đề clip, "i / tổng"; danh sách nhóm theo tập.
6. Nghe nền trên điện thoại: khóa màn hình / chuyển app vẫn nghe và tự sang mục kế; nút Trước / Tiếp trên màn hình khóa hoạt động.
7. Tim trong Nghe đổi yêu thích thật (tab Quản lý thấy cùng trạng thái sau khi tải lại).
8. "Nghe tiếp từ …" hiện khi có chỗ đã nhớ của bộ kinh; bấm thì phát từ đúng mục + giây.
9. WATCH1 không hồi quy (test + chạy thật nhanh: Xem chung 1 trang, đồng bộ phát / dừng / Tiếp).

### Amendment A (HUMAN LEAD 2026-11-08, chạy thật WATCH1 vòng 3 trên Android Chrome)

Bằng chứng: "tôi không cần tick nghe nền vẫn nghe được. Nên bỏ luôn nút nghe nền để 3 nút: trái tim và 2 nút mũi tên, trên cùng một hàng cho gọn" — xác nhận: chuyển app vẫn nghe khi trang **đang hiện video** (chế độ video thường). "Playlist nên cho user bấm nút bài tiếp theo và có option tự chuyển bài tiếp theo. Khi hết một tập nên báo user biết đã hết tập".

Code bị thay / xóa thêm: công tắc Nghe nền, phần tử `<audio>`, chế độ audio / handoff / audio fallback trong `player.js`; `src/auto_short/web/watch_audio.py`, route `/api/watch/audio/...`, `audio_url` trong API listen, test liên quan; cache `work/_watch_audio/` không còn được tạo (ORCHESTRATOR xóa thư mục trên 8080 sau merge). Giữ: Media Session + playbackState, bỏ qua pause khi trang ẩn, không retry play khi hidden. Owned paths thêm `src/auto_short/web/routes/watch.py`, `tests/test_web_watch_party.py`.

10. Cả `/watch` và tab Nghe: một hàng gọn **♡ ⏮ ⏭** (icon-btn, `title` + `aria-label`); tim ẩn khi mục không có `fav` thì hai nút mũi tên vẫn giữ chỗ / cùng hàng. "Kết thúc xem chung" (chỉ `/watch`) ở dòng riêng, nút nhỏ. Không còn công tắc Nghe nền.
11. Công tắc **"Tự chuyển bài"** (mặc định bật). Tab Nghe: nhớ trong `localStorage`. `/watch`: là trạng thái của phòng (`auto` bool trong WatchRoom, mặc định true, lệnh `auto`), hai máy thấy cùng giá trị. Tắt → hết bài thì dừng ở cuối bài, không gửi `next`; ⏭ vẫn chuyển.
12. **Hết tập**: khi mục vừa xong là mục cuối của một tập (mục kế thuộc tập khác hoặc hết danh sách), hiện thông báo nổi bật (role="status") "Đã hết Tập N — <tên>" kèm "Tiếp theo: Tập N+1" (khi tự chuyển) hoặc nút "Nghe Tập N+1" (khi tắt tự chuyển / hết danh sách thì "Đã hết danh sách"). Thông báo tự ẩn sau ~8 s hoặc khi bấm. `/watch` dùng cùng logic dựa trên `episode_id` suy từ url mục (danh sách 1 trang thường là 1 tập → "Đã hết danh sách").
13. Chạy thật: tắt Tự chuyển → hết bài dừng; bật → qua bài; hết tập thấy thông báo; điện thoại chuyển app vẫn nghe (video thường).

### Amendment B (HUMAN LEAD 2026-11-08, Android Chrome, 8080 = WATCH1 `89250f2`)

Bằng chứng: "Tôi nghe trên điện thoại được một lúc thì tự dừng, tôi phải chuyển qua lại web rồi mới nghe tiếp được"; dừng "Giữa chừng một bài". Code hiện tại khi trang ẩn: bỏ qua pause (không báo phòng) + không retry play → phần tử bị trình duyệt dừng sẽ im tới khi trang hiện lại. Nghi: tua đồng bộ (lệch > 1 s) khi trang ẩn, hoặc mất audio focus.

14. Trang ẩn (`visibilityState === "hidden"`): không tua đồng bộ theo lệch vị trí (chỉ áp lệnh rời rạc: đổi bài, play / pause do người khác bấm, tua do người khác bấm — `/watch`), tua bù khi trang hiện lại. Áp cho cả `/watch` và tab Nghe.
15. Phần tử bị dừng giữa bài khi trang ẩn mà trạng thái mong muốn là đang phát (phòng / tab Nghe): thử `play()` lại sau ~1 s, tối đa 3 lần mỗi lần dừng (giãn 1 / 3 / 10 s); thành công thì thôi.
16. Nhật ký chẩn đoán: `POST /api/watch/log` (sau login) nhận lô sự kiện ngắn từ client (`pause_hidden`, `retry_ok`, `retry_blocked` + tên lỗi, `seek_skipped_hidden`, `stalled`, `waiting`, `visibility`, `page` = watch | listen, `t` media, độ lệch), ghi một dòng `logging` mỗi sự kiện (giới hạn: ≤ 20 sự kiện / lô, ≤ 2 KB, ≤ 1 lô / 5 s / client, chuỗi đã lọc ký tự điều khiển). Client gom và gửi khi có sự kiện, dùng `sendBeacon` lúc pagehide. Không lưu file mới.
17. Chạy thật: điện thoại ở app khác ≥ 10 phút; nếu vẫn dừng thì log 8080 cho biết nguyên nhân.

### Amendment C (HUMAN LEAD 2026-11-08, chạy thật `d7fdb2a` trên Android Chrome)

Bằng chứng: "Tab nghe chưa ổn, phải zoom cho khớp với màn hình điện thoại. Thêm nữa các tập xả ra toàn bộ nhìn khá rối. Cây tập nhỏ trong từng tập nên là dropdown, phát tập nào thì tập đó tự xả ra." "Nghe app khác vẫn bị vấn đề cũ. Có thể cho xem màn hình nhỏ tôi nghĩ sẽ giải quyết được." Log `/api/watch/log` 8080: ngay khi `visibility hidden`, thời gian media đứng yên — `/watch` t = 17,357 (41 sự kiện, drift tăng 1,7 → 25 s), tab Nghe t = 24,575: 73 sự kiện `pause_hidden` / `retry_ok` xen kẽ (play() resolve rồi bị dừng lại ngay) → Chrome Android dừng phần tử video khi trang ẩn; retry vô ích và lặp vô hạn.

18. **Màn hình nhỏ (Picture-in-Picture)**: nút ⧉ trong hàng điều khiển (♡ ⏮ ⏭ ⧉) ở `/watch` và tab Nghe, chỉ hiện khi `document.pictureInPictureEnabled`; bấm → `video.requestPictureInPicture()` (bấm lại / đang PiP → `exitPictureInPicture`). Đổi bài trong PiP giữ cùng phần tử `<video>` (đổi `src`) nên cửa sổ nhỏ vẫn giữ. Thêm `navigator.mediaSession.setActionHandler("enterpictureinpicture", …)` khi trình duyệt hỗ trợ (bọc try). Trang ẩn mà đang PiP thì không coi là "ẩn" cho AC 14 / 11 (vẫn đồng bộ bình thường, kể cả tua). Không hỗ trợ PiP (vd. http không bảo mật) → hiện nút ⛶ toàn màn hình + gợi ý một dòng "Bật toàn màn hình rồi bấm nút Home để thu nhỏ".
19. Retry (AC 15) có trần chung: dừng thử khi 2 lần liên tiếp `play()` resolve mà `currentTime` không tăng sau 2 s, hoặc tổng 6 lần trong một lần ẩn; ghi một sự kiện `retry_gave_up`. `seek_skipped_hidden` chỉ log 1 lần / lần ẩn. Thêm sự kiện log `pip_enter`, `pip_leave`, `pip_unsupported` (khi tải trang, kèm `err` = lý do: insecure / disabled / api-missing).
20. **Vừa màn hình điện thoại**: tab Nghe, `/watch`, thanh mời không gây cuộn ngang ở bề rộng 360 px (không phải zoom): chữ dài (tên tập, tiêu đề, option của select) xuống dòng / cắt, select / video / nút `max-width: 100%`, không bề rộng cố định vượt khung; kiểm cả phần đầu trang tập ở tab Nghe.
21. **Danh sách theo tập dạng thu gọn**: mỗi tập là một `<details>` (summary "Tập N — tên · k bài"); chỉ tập đang phát mở; chuyển sang tập khác thì tập mới tự mở, tập cũ tự đóng (trừ tập người dùng tự mở tay sau đó vẫn để mở); mục đang phát cuộn vào tầm nhìn trong danh sách (không cuộn cả trang khi trang đang ẩn). Áp cho tab Nghe; `/watch` (thường 1 tập) giữ danh sách phẳng.
22. Chạy thật: Android Chrome — PiP nghe ≥ 10 phút qua nhiều bài; tab Nghe không cần zoom; danh sách gọn.

### Amendment D (HUMAN LEAD 2026-11-08, chạy thật `d7c969e`)

Bằng chứng: "tab nghe: nhấp vào short ở tập nào đó thì tự cuộn lên video, hiện tại tôi phải cuộn lên. Các form ở trang này cũng còn rất thô. Tên tập ở trang nghe lẫn trang nghe chung nên ở dạng ngắn ví dụ T20_S01_. Trang nghe chung khi tự chuyển tập có cảm giác hơi gấp, có cách nào không ví dụ chờ 3s".

23. Bấm một mục trong danh sách (tab Nghe, `/watch`) → phát mục đó và cuộn mượt lên khung video (`scrollIntoView({behavior: "smooth", block: "start"})`, trừ đi thanh trên cùng nếu có).
24. **Mã ngắn**: mỗi mục có `code` = `review.names.short_code(...)` (`T20_S01`, khai thị `T20_KT01`; cùng số / độ rộng như tên file tải về — tái dùng helper, không tự tính lại). API listen trả `code`; `/watch` lấy `code` do server suy từ url mục (như `fav`). Hiển thị: dòng danh sách "`T20_S01` · tiêu đề"; đang phát "`T20_S01` — tiêu đề" + dòng phụ "Tập 20 · Short 1 / 8"; nhóm tập "Tập 20 · 8 bài" (tên video dài bỏ khỏi summary, chỉ hiện nhỏ một lần ở khung đang phát nếu cần). Không còn chuỗi tên video dài lặp lại.
25. **Chờ 3 s trước khi tự chuyển** (cả hai trang): hết bài → thẻ "Bài tiếp theo: `T20_S02` — tiêu đề · sau 3 s" có đếm ngược + nút "Phát ngay" / "Hủy". `/watch`: đếm ngược là trạng thái phòng (server ghi `advance_at` = lúc hết bài + 3 s khi nhận lệnh `ended` kèm `expect_version`; tự sang mục kế khi tới hạn lúc đọc trạng thái; lệnh `advance_now` / `cancel_advance`), hai máy thấy cùng đếm ngược; hai máy cùng báo `ended` chỉ tạo một lần chờ. Hết tập: thông báo AC 12 gộp vào cùng thẻ này (không hai thông báo chồng nhau).
26. **Giao diện gọn, đồng bộ với phần còn lại của web** (dùng biến màu / `.btn` / `.icon-btn` sẵn có trong style.css, không thư viện mới):
    - Khung đang phát: video, ngay dưới là mã + tiêu đề (đậm), dòng phụ nhỏ màu nhạt, hàng nút ♡ ⏮ ⏭ ⧉ căn giữa, kích thước chạm ≥ 44 px.
    - Công tắc Short / Khai thị / Cả hai: nhóm nút liền (segmented control) thay `<select>`; "Tự chuyển bài": công tắc gạt (checkbox kiểu switch) có nhãn.
    - Danh sách: dòng gọn (mã đơn cách, tiêu đề cắt 2 dòng, thời lượng bên phải), mục đang phát nền nhấn; nhóm tập là `<details>` có mũi tên.
    - "Nghe tiếp từ …", thông báo, thanh mời: cùng kiểu thẻ (bo góc, viền nhạt).
    - Dọc 360 px vẫn không cuộn ngang (AC 20).
27. Chạy thật: bấm mục ở tập xa → tự cuộn lên video; hết bài thấy đếm ngược 3 s ở cả hai máy (`/watch`); giao diện HUMAN LEAD duyệt trên điện thoại.

## Required verification

- `PYTHONPATH=~/projects/yas-listen1/src conda run -n auto-short pytest tests/test_web_listen.py tests/test_web_watch_party.py -q` — AC 1, 2, 9 (phần server).
- `node --check` cho `player.js`, `watch.js`, `listen.js`, `app.js`.
- Full suite `pytest -n auto -q`.
- AC 3–9: chạy thật trên 8080 ghim commit nhánh (máy tính + điện thoại).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / API hiện có → manual test là điểm danh.

- [ ] Mở một tập Vô Lượng Thọ → tab Nghe, nghe hết Short sang khai thị sang tập sau.
- [ ] Điện thoại bật Nghe nền, khóa màn hình vài phút.
- [ ] Đổi công tắc Khai thị → chỉ còn khai thị.

## Result

### Vòng 1 — 0bc53cf (trước Amendment A)

- Main changes (IMPLEMENTER 2026-11-08):
  - Thêm `web/listen.py` + `GET /api/playlists/{playlist_id}/listen`: sắp entry theo index, Short theo manifest rồi khai thị; bỏ chưa render / rejected (cả review đang chờ render), giữ title trong file, URL SHA như trang tập, audio URL WATCH1 và favorites đọc mới một lần/request. Không resolve file / gọi kho / chạy job.
  - `player.js` chứa toàn bộ lõi media dùng chung: video/audio, transfer timeline/rate, audio-only + fallback MP4, chặn sự kiện do code gây ra, chống retry hidden, Media Session theo media thật, tim qua API cũ, nút icon Trước/Tiếp. `watch.js` chỉ giữ phòng/polling/invitation, pause guard 1,5 s và điều hướng phòng; giữ version CAS.
  - Trang tập thêm tab Nghe mặc định / Quản lý nhớ lựa chọn; giữ nguyên HTML nội dung Quản lý so với base (đã đối chiếu exact text). Nghe có bộ lọc nhớ lựa chọn, thông tin bộ/tập/kind/title/i-tổng, danh sách nhóm tập + nhảy tập, tự nối xuyên kind/tập, lưu chỗ nghe và nút nghe tiếp, gửi tối đa 300 mục từ hiện tại sang Xem chung. Chưa có thao tác thì không gọi play. Đổi tab dừng media bên kia và trao lại Media Session, không tự phát khi quay về.
- Files: `web/listen.py`, `routes/playlists.py` (chỉ endpoint mới), `static/player.js`, `watch.js`, `watch.html`, `listen.js`, `episode.html`, `app.js` (chỉ tabs/điều phối media giữa tabs), `style.css` (khối LISTEN1 mới), `tests/test_web_listen.py`, contract này. Không sửa `test_web_watch_party.py`.
- Helper mới (đã tìm bằng rg trong episodes/playlists/compilations/review và đọc watch.js):
  - `playlist_listen`: chưa có queue kết hợp hai kind xuyên tập; tái dùng `ep.render_manifest`, `ep._short_view`, `read_review`, `episode_id_for`, `ctx.playlist_or_404`, `ctx.compilations.favorites`. Không dùng full `episode_view` / `PlaylistStore.view` / `short_locations` vì đọc thêm titles, publication, jobs, trạng thái file không cần thiết.
  - `AutoShortPlayer`: tách logic có sẵn khỏi WATCH1, không giữ bản sao trong watch.js. `listen.js` chỉ bổ sung state/danh sách cục bộ; namespace `AutoShortWatch.start` dùng lại command/client của WATCH1.
  - Tập ngoài bộ kinh: client dựng từ API tập hiện có (tối đa base + khai thị), ít code và không cần thêm endpoint/Owned path. Không có bộ kinh thì không có tim.
- AC → test:
  - AC1/2: `test_queue_order_fields_favorites_and_no_khaithi`, `test_review_rejected_current_candidate_only`, `test_unrendered_episode_and_khaithi_are_omitted`, `test_released_short_uses_episode_url_without_resolving_storage`, `test_route_fresh_favorites_and_404`; `test_http_listen_auth_404_and_queue` kiểm middleware 401/404/queue, chờ chạy TestClient ngoài sandbox.
  - AC3–8: smoke DOM/media giả `/tmp/listen1-local-player.cjs` PASS: không autoplay; khởi đầu đúng tập/.kt; nhóm tập; ended xuyên Short→khai thị→tập sau; lọc; request favorites thật tới API (fetch giả); audio endpoint + ended khi hidden; Media Session Trước/Tiếp; save/resume đúng giây; dừng/không tự phát khi chuyển tab; fallback tập ngoài bộ; handoff WATCH1 và cap 300. Smoke không thay thế trình duyệt/điện thoại thật; nhớ tab và layout cần manual test.
  - AC9: toàn bộ test WATCH1 không HTTP PASS; `/tmp/listen1-watch-regression.cjs`, `/tmp/listen1-watch-controls.cjs`, `/tmp/listen1-watch-scan.cjs` PASS: favorites mới từ poll, pause hidden/pagehide, retry suppression/reset, audio/video/fallback giữ timeline/rate, Media Session theo media thật, ended CAS, đồng bộ remote, quét video động/lời mời. Đây là mock, chưa claim chạy thật.
- Lệnh đã chạy:
  - `PYTHONPATH=/home/ntnghia/projects/yas-listen1/src conda run --no-capture-output -n auto-short pytest tests/test_web_listen.py tests/test_web_watch_party.py -q -k 'not test_http' -x --tb=short`: **56 passed, 6 deselected in 3.04s** (lần cuối).
  - Lệnh required cả hai file (cùng PYTHONPATH/conda, `-q`, bọc `timeout --signal=TERM --kill-after=5s 90s`): **exit 124**, treo ở TestClient sau 4 test LISTEN1 không HTTP (trước khi bổ sung test unrendered). Không claim PASS HTTP; ORCHESTRATOR chạy lại ngoài sandbox.
  - Full suite `PYTHONPATH=/home/ntnghia/projects/yas-listen1/src timeout --signal=TERM --kill-after=5s 180s conda run --no-capture-output -n auto-short pytest -n auto -q`: **exit 124**; log `/tmp/listen1-full-pytest.log` tới khoảng 62%, có E/F, chưa có summary/traceback để kết luận nguyên nhân. Không claim PASS; ORCHESTRATOR cần chạy/đánh giá ngoài sandbox.
  - `node --check` cho cả `player.js`, `watch.js`, `listen.js`, `app.js`: **PASS**. Bốn smoke JS kể trên: **PASS**. Đối chiếu nội dung HTML Quản lý với base: **PASS**. `git diff --check` + whitespace file mới: **PASS**.
- Performance (chỉ đọc dữ liệu thật tại `~/projects/youtube-auto-short/{work,output}`, không tạo app/job hoặc gọi mạng): bộ lớn nhất 374 entry → 738 mục; 3 lần **0,0900 / 0,0864 / 0,0858 s**, gồm đọc favorites; script `/tmp/listen1-benchmark.py`.
- Diff + / − (không tính contract): app **+582 / −192**, test **+124 / −0**, tổng **+706 / −192**.
- Review: đã tự rà Owned paths, giữ management HTML, suppression/hidden pause, khởi tạo không autoplay, save identity khi lọc, async tim khi đổi mục. Không commit / push / PR / gọi agent khác / dịch vụ thật / thêm dependency.
- Known limitations / lifecycle: implementation xong, sẵn sàng ORCHESTRATOR review; giữ **IN_PROGRESS**, chưa đủ điều kiện READY vì TestClient/full suite và manual AC3–9 (8080 + điện thoại/khóa màn hình) chưa PASS trong lượt này. Danh sách là snapshot lúc mở trang, thay render/favorites ở tab khác cần tải lại như API tập hiện có; chỗ nghe chỉ lưu tại trình duyệt.
- PR: chưa tạo theo chỉ dẫn HUMAN LEAD.


### Vòng 2 — Amendment A (IMPLEMENTER 2026-11-08)

- Baseline: `0bc53cf`; ORCHESTRATOR báo 84 PASS ngoài sandbox cho `test_web_listen.py` + `test_web_watch_party.py` + `test_web_app.py` của vòng 1. Bằng chứng Android Chrome của HUMAN LEAD nằm ở Amendment A; chưa claim đã chạy thật phiên bản vòng 2.
- Main changes / files:
  - Xóa `web/watch_audio.py`; gỡ route audio/cache/store-fetch/import khỏi `routes/watch.py`; gỡ `audio_url` khỏi `listen.py` và fallback danh sách cục bộ. Xóa fixture/test audio/remux/cache/Range và import không còn dùng trong `test_web_watch_party.py`. Không tạo/đụng cache thật trên 8080.
  - `player.js` chỉ còn video: gỡ background/storage, audio, handoff, transfer, fallback, audioUrl và các guard chọn media thừa. Giữ suppression, Media Session, playbackState theo media thật và giới hạn retry hidden. `watch.js` giữ pause guard khi ẩn trang.
  - `watch.html`, `episode.html`, `style.css`: một hàng cố định ♡ ⏮ ⏭, wrapper tim giữ chỗ khi tim ẩn; công tắc Tự chuyển bài ở dòng riêng. Kết thúc xem chung là nút nhỏ, dòng riêng. HTML/scripts Quản lý không đổi so với vòng 1 (`app.js` không sửa).
  - `watch_party.py`: snapshot có `auto` bool mặc định true; action `auto` validate strict bool trước mutation, tăng version và giữ timeline/rate/index/paused. Đổi queue trong cùng phòng giữ lựa chọn; kết thúc phòng reset true. Tắt auto làm CAS của lệnh ended cũ mất hiệu lực.
  - `listen.js` nhớ `auto-short-listen-auto` trong localStorage; `watch.js` gửi action auto và nhận lại giá trị qua snapshot. Shared player kiểm auto khi ended: bật thì next như cũ, tắt thì pause tại cuối bài (không gửi next); nút mũi tên/Media Session vẫn điều hướng được.
  - Thông báo hết tập nằm chung trong `player.js`: gộp Short + `.kt` theo base episode; nhận metadata listen hoặc suy episode từ `/files/<ep>/<clip>.mp4` trên WATCH1. Hiện role=status, tên tập + mục kế/nút Nghe Tập kế hoặc Đã hết danh sách; tự ẩn sau 8 s hoặc bấm. Client nhận chuyển bài từ máy kia ngay trước ended cũng hiện thông báo nếu đang sát cuối bài. Nút thông báo cũ không nhảy nhầm nếu người dùng đã đổi nguồn.
- Helper mới (đã tìm trong player/watch/listen, chưa có helper thông báo ranh giới tập): `AutoShortPlayer.episode`, `notifyEpisodeEnd`, `hideNotice`; tái dùng player/onNavigate và phiên bản CAS hiện có, không thêm module/dependency.
- AC → test:
  - AC10: hai HTML dùng chung `.player-controls` grid 3 ô và wrapper tim; node smoke + rà markup/CSS. Phần layout thật còn ORCHESTRATOR/HUMAN LEAD kiểm.
  - AC11: `test_auto_defaults_updates_preserve_playback_and_reset`, `test_auto_rejects_non_bool_atomically` (7 kiểu sai + thiếu field), `test_auto_change_invalidates_stale_ended_version`, `test_auto_route_defaults_fresh_snapshot_and_422` PASS. Thêm `test_http_auto_sync_and_validation` để ORCHESTRATOR chạy TestClient.
  - AC12: `/tmp/listen1-round2-local.cjs` và `/tmp/listen1-round2-watch.cjs` PASS với DOM/media/fetch giả: auto=false không next; next thủ công vẫn đổi mục; auto đồng bộ/nhớ; Short→khai thị cùng tập không báo sớm; hết tập có thông tin tiếp/nút; hết danh sách; tự ẩn 8 s/bấm; peer advance trước ended. WATCH1 smoke còn kiểm tim, pause hidden, playbackState thực, không retry hidden mỗi poll và reset khi visible/version mới. Listen smoke giữ kiểm không autoplay, resume/tab/fallback tập lẻ/cap 300.
  - AC13: chưa chạy Android Chrome thật ở vòng 2. Smoke không thay thế bằng chứng thiết bị.
  - API listen: `test_queue_order_fields_favorites_and_no_khaithi` thêm assert mọi mục không có audio_url; các test order/filter/fav/404 cũ vẫn PASS. `rg` toàn `src/` + `tests/` không còn watch_audio/cache/route/công tắc và helper audio đã gỡ (chỉ còn assert phủ định audio_url).
- Verification vòng 2:
  - `PYTHONPATH=/home/ntnghia/projects/yas-listen1/src conda run --no-capture-output -n auto-short pytest tests/test_web_listen.py tests/test_web_watch_party.py -q -k 'not test_http' -x --tb=short`: **60 passed, 6 deselected in 1.89s**.
  - `node --check` cho `player.js`, `watch.js`, `listen.js`, `app.js`: **PASS**; `node /tmp/listen1-round2-local.cjs` và `node /tmp/listen1-round2-watch.cjs`: **PASS**.
  - Đối chiếu HTML/scripts Quản lý với `0bc53cf`: **PASS**; `git diff --check`: **PASS**.
  - Không chạy lại TestClient/full suite trong sandbox theo delegation vòng 2; ORCHESTRATOR chạy ngoài sandbox. Không chạy 8080/điện thoại trong lượt này.
- Diff vòng 2 so với `0bc53cf`, không tính contract/Amendment A có sẵn: app **+117 / −201**, test **+68 / −154**, tổng **+185 / −355**.
- Review / lifecycle: sẵn sàng ORCHESTRATOR review vòng 2; giữ IN_PROGRESS đến khi required verification và chạy thật hoàn tất. Không commit/push/PR, gọi agent khác, gọi mạng thật, thêm dependency hoặc sửa ngoài phạm vi delegation.
- Known limitation: WATCH1 chỉ có URL/title thì nhãn tập dùng ID gốc; queue gửi từ Nghe có prefix Tập N — tên nên giữ được nhãn đầy đủ. Cache cũ `work/_watch_audio/` trên 8080 do ORCHESTRATOR dọn sau merge như Amendment A.


### Vòng 3 — Amendment B (IMPLEMENTER 2026-11-08)

- Baseline: `11027bb`; ORCHESTRATOR báo 88 PASS ngoài sandbox cho vòng 2. Bằng chứng Android Chrome và giả thuyết dừng giữa bài được giữ ở Amendment B; chưa khẳng định nguyên nhân hoặc đã chữa xong trên thiết bị thật.
- Main changes / files:
  - `static/player.js`: hidden không seek bù drift, không play lại mỗi poll; initial source/resume vẫn đặt vị trí được. `/watch` truyền cờ remote; player chỉ nhận diện seek khi by khác mình, version đổi và position lệch >1 s so với anchor phòng ngoại suy ở updated_at mới. Đổi auto/rate/anchor theo thời gian bình thường không thành seek. Remote pause/play được áp; khi visible thì sync đầy đủ.
  - Bỏ hoàn toàn `hiddenPlayBlocked` / `resetRetry` và reset retry mỗi version. Pause không do code khi hidden + desired playing được giữ nguyên desired state (cả listen), không gửi pause lên phòng; lập một chu kỳ thử play ở **1 / 3 / 10 s tính từ pause**, tối đa ba lần. Polling/version thông thường không gia hạn chu kỳ. Hủy timer khi media play thật, desired paused, visible, đổi source, rời tab Nghe/pagehide. Khi play promise thành công nhưng media đã paused trở lại thì không ghi retry_ok hoặc xóa chu kỳ mới.
  - Log client dùng chung trong player: pause_hidden, retry_ok, retry_blocked (error.name), seek_skipped_hidden (drift), stalled/waiting khi hidden, visibility; có t và hidden. Queue giữ tối đa 20 sự kiện; mỗi batch UTF-8 ≤2048 byte, tối đa một lần mỗi 5 s; sendBeacon pagehide khi đủ nhịp, nếu còn cooldown thì giữ queue/timer thay vì gửi vượt nhịp. Chẩn đoán best effort, không cản phát media. Drift/waiting/stalled trùng được gom theo 5 s.
  - `routes/watch.py`: POST `/api/watch/log` sau auth hiện có, đọc stream và chặn raw body >2048 byte trước khi nối chunk; strict schema 1–20 events, enum page/type, số hữu hạn (t ≥0, drift có dấu), hidden bool, client/err chuỗi ≤200 ký tự. Lọc ký tự điều khiển/format/line separator; INFO vào logger `auto_short.web.watch`, một dòng JSON/sự kiện, không file mới. Rate limit một batch/5 s/client dùng monotonic + lock, xóa mốc hết hạn, trả 422/429 trước logging; không sửa trạng thái phòng.
  - `watch.js` / `listen.js` chỉ nối client ID sẵn có, cờ remote và bỏ reset cũ; không nhân đôi logic. `tests/test_web_watch_party.py` bổ sung tests log. `app.js`, HTML/CSS, listen API và **WatchRoom không đổi** (đã kiểm diff).
- Helper mới (đã tìm trong player/watch/listen và router): `_log_batch` cho validation/sanitize chẩn đoán; `wantsPlay`, `cancelRecovery`, `recover` cho bounded retry; `record`, `scheduleLog`, `flushLog` cho batch/cooldown. Chưa có helper phù hợp các hành vi này; tái dùng client ID của WATCH1, player/suppression/Media Session hiện có và middleware auth, không dependency/module mới.
- AC → test:
  - AC14/15: `/tmp/listen1-round3-player.cjs` PASS bằng clock/DOM/media/fetch giả: không hidden drift seek; remote seek chỉ khi đổi version/jump; own change/anchor-only không tua; remote play/pause/đổi bài; visible catch-up; pause hidden giữ desired playing cho watch và listen; retry chính xác các mốc 1/3/10 s, tối đa ba, polling không thêm; success hủy và pause lần sau có chu kỳ mới; desired pause/visible/suspend/source/ended không retry sai.
  - AC16: `test_log_route_records_sanitized_events_and_limits_rate` kiểm caplog INFO/một dòng, lọc newline/NUL/ESC/U+2028, drift âm, 429 cùng client xuyên page, client khác độc lập, ranh giới 5 s, version phòng không đổi. `test_log_route_rejects_invalid_without_logging_or_rate_charge` (21 ca) kiểm 422 và không ghi/không tính nhịp cho lô sai. `test_log_route_byte_and_event_boundaries` kiểm UTF-8/raw 2048/2049 bytes, 20/21 events, malformed JSON/UTF-8. `test_log_requires_auth_without_testclient` gọi đúng middleware auth hiện hành, xác nhận 401 trước endpoint. Tất cả PASS; thêm `/api/watch/log` vào HTTP auth test và `test_http_log_auth_validation_rate_and_records` chờ ORCHESTRATOR chạy TestClient.
  - AC16 client: shared smoke kiểm queue20, UTF-8 ≤2 KB, cooldown5 s, page/client, chỉ log waiting/stalled lúc hidden và pagehide beacon. `/tmp/listen1-round3-local.cjs`, `/tmp/listen1-round3-watch.cjs` PASS để kiểm nối với hai trang và giữ auto/hết tập/tim/resume/tabs/cap300/CAS.
  - AC17: chưa chạy Android ở app khác ≥10 phút. Cần HUMAN LEAD/ORCHESTRATOR nghe thật và đọc logger 8080 nếu còn dừng; mock không chứng minh audio focus/timer Android thực.
- Verification vòng 3:
  - `PYTHONPATH=/home/ntnghia/projects/yas-listen1/src conda run --no-capture-output -n auto-short pytest tests/test_web_listen.py tests/test_web_watch_party.py -q -k 'not test_http' -x --tb=short`: **84 passed, 7 deselected in 5.26s** (lần cuối).
  - `node --check` cho `player.js`, `watch.js`, `listen.js`, `app.js`: **PASS**. `node /tmp/listen1-round3-player.cjs`, `node /tmp/listen1-round3-local.cjs`, `node /tmp/listen1-round3-watch.cjs`: **PASS**.
  - `git diff --exit-code 11027bb -- src/auto_short/web/watch_party.py`: **PASS, diff rỗng**; `git diff --check`: **PASS**. Không còn hiddenPlayBlocked/resetRetry.
  - Không chạy TestClient/full suite trong sandbox theo delegation; ORCHESTRATOR chạy ngoài sandbox. Không gọi mạng thật, không chạy 8080/thiết bị trong lượt này.
- Diff so với `11027bb`, không tính contract/Amendment B có sẵn: app **+197 / −36**, test **+107 / −1**, tổng **+304 / −37**.
- Review / lifecycle: sẵn sàng ORCHESTRATOR review vòng 3; giữ IN_PROGRESS vì required verification/TestClient và AC17 trên Android chưa hoàn tất cho code mới. Không commit/push/PR, gọi agent khác, thêm dependency hoặc sửa ngoài Owned paths.


### Vòng 4 — Amendment C (IMPLEMENTER 2026-11-08)

- Baseline: `d7fdb2a`; ORCHESTRATOR báo full suite **4151 PASS** và đã ghim 8080 cho vòng 3. Log Android thật (media đứng ở t=24,575, 73 pause_hidden/retry_ok) nằm ở Amendment C; không dùng play promise resolve như bằng chứng media đã chạy ổn.
- Main changes / files:
  - `static/player.js`: thêm nút ⧉ bằng JS vào `.player-controls` chung; toggle request/exit PiP, event enter/leave cập nhật aria-pressed và màu nút. Media Session enterpictureinpicture bọc try/catch. Không hỗ trợ → ⛶ dùng requestFullscreen / webkitEnterFullscreen, có gợi ý Home; log pip_unsupported khi tải trang với insecure / disabled / api-missing. Đổi clip vẫn dùng đúng phần tử video hiện có, không tạo video mới.
  - `inPiP` / `isHidden` là nguồn dùng chung cho pause, seek, retry, waiting/stalled và cờ hidden trong log. PiP được coi là đang hiện; enter/leave cập nhật hiệu lực visibility, sync và budget. `watch.js` dùng cùng định nghĩa cho hiddenPause và poll khi visibility đổi; PiP không bị guard 1,5 s của trang ẩn chặn thao tác pause.
  - Trần retry giữ suốt một lần **ẩn hiệu lực**, qua cả retry_ok / nguồn mới: tối đa 6 retry; mỗi promise retry resolve được kiểm currentTime sau 2 s. Hai lần liên tiếp không tiến thời gian → hủy retry, ghi đúng một retry_gave_up; cap tổng 6 cũng ghi một lần. Progress watchdog độc lập timer retry, không bị sự kiện play/pause xóa mất. Desired pause / suspend / đổi nguồn bỏ watchdog cũ; visible/PiP reset budget. seek_skipped_hidden chỉ ghi một lần trong lần ẩn đó. Không bỏ các guard bounded retry và auto/CAS đã có.
  - `routes/watch.py`: chỉ mở rộng LOG_TYPES với retry_gave_up, pip_enter, pip_leave, pip_unsupported; giữ schema, sanitize, giới hạn nhịp/bytes và auth. `tests/test_web_watch_party.py` thêm test route nhận đủ các type/lý do và caplog đúng một dòng mỗi sự kiện.
  - `listen.js`: dùng lại buildList/renderCurrent để dựng details/summary có số bài. Chỉ nhóm hiện tại tự mở; đóng nhóm cũ trừ nhóm đã mở tay. Phân biệt toggle do .open và do người dùng (summary click + expectedToggle), kể cả toggle bất đồng bộ/coalesced. Dropdown vẫn nhảy/mở tập; filter cập nhật số bài. scrollIntoView nearest chỉ khi document visible và tab Nghe active, gồm lúc trở lại trang/tab.
  - `episode.html`, `watch.html`, `style.css`: thêm control container/hint, body episode-page để scope chống tràn. Header tập cho wrap, flex/grid con min-width:0, track minmax(0,1fr), text dài overflow-wrap:anywhere; select width/max-width 100%, option có wrap và selected text ellipsis, video/nút max-width100%. Hàng điều khiển đổi sang flex, giữ chỗ tim và thêm nút thứ tư. Danh sách WATCH1 vẫn phẳng. Nội dung HTML/scripts Quản lý không đổi so với base; CSS ở đó chỉ chống tràn.
- Helper mới (đã tìm trong player/watch/listen): inPiP/isHidden/visibilityChanged để gom định nghĩa visibility; setupPiP/togglePiP cho control chung; clearProgressChecks/giveUpRetry/checkRetryProgress cho trần qua nhiều chu kỳ play/pause. Tái dùng recover, record/log batching, Media Session, buildList/renderCurrent; không dependency/module mới.
- AC → test:
  - AC18/19: `/tmp/listen1-round4-player.cjs` PASS (clock/DOM/media/fetch giả): nút và action PiP; request/exit; aria; PiP + document hidden vẫn sync tua; đổi src giữ nguyên video; fullscreen và WebKit fallback; 3 lý do unsupported; mô phỏng play resolve rồi pause lại nguyên t → gave_up; cap 6 qua các lần có tiến thời gian; budget không reset do đổi nguồn, reset khi visible; một gave_up/seek_skipped trong lần ẩn.
  - AC18 WATCH1: `/tmp/listen1-round4-watch.cjs` PASS, gồm deliberate pause khi document hidden nhưng PiP đang chạy vẫn gửi phòng, remote seek vẫn sync; giữ smoke auto, CAS, tim, thông báo hết tập/danh sách, playbackState.
  - AC19 API: `test_log_route_accepts_pip_and_retry_cap_events` PASS cho các type mới, mọi lý do unsupported và caplog; toàn bộ test route log/WatchRoom/listen không HTTP cũ vẫn PASS.
  - AC21: `/tmp/listen1-round4-details.cjs` PASS: chỉ nhóm đầu hiện tại mở, ended xuyên Short→khai thị→tập sau, tự gập nhóm cũ; mở/đóng tay được giữ đúng, auto toggle không bị coi là manual và xử lý coalesced toggle; dropdown/filter/summary count; không scroll khi hidden/inactive, cuộn khi trở lại; trang .kt/tập ngoài bộ/tab Quản lý đã nhớ không tự phát.
  - AC20: đã rà CSS/markup và kiểm ID duy nhất + Quản lý HTML/scripts giữ nguyên. Sandbox không có Chromium/Firefox/Playwright/Puppeteer; chưa đo scrollWidth hoặc chạy render thực ở 360 px. Không claim PASS layout trình duyệt.
  - AC22: chưa chạy Android PiP ≥10 phút qua nhiều bài. HUMAN LEAD/ORCHESTRATOR cần kiểm cả PiP giữ cửa sổ sau src/load và layout 360 px thật.
- Verification vòng 4:
  - `PYTHONPATH=/home/ntnghia/projects/yas-listen1/src conda run --no-capture-output -n auto-short pytest tests/test_web_listen.py tests/test_web_watch_party.py -q -k 'not test_http' -x --tb=short`: **85 passed, 7 deselected in 5.57s**.
  - `node --check` cả `player.js`, `watch.js`, `listen.js`, `app.js`: **PASS**; ba smoke JS vòng 4 kể trên: **PASS**.
  - `git diff --exit-code d7fdb2a -- src/auto_short/web/watch_party.py src/auto_short/web/static/app.js`: **PASS, diff rỗng**. Đối chiếu nội dung Quản lý và IDs HTML: **PASS**. `git diff --check`: **PASS**.
  - Không chạy lại TestClient/full suite trong sandbox theo delegation; không gọi mạng thật hoặc chạm runtime 8080. Kết quả 4151 PASS nêu ở baseline thuộc vòng 3.
- Diff so với `d7fdb2a`, không tính contract/Amendment C có sẵn: app **+188 / −43**, test **+14 / −0**, tổng **+202 / −43**.
- Review / lifecycle: sẵn sàng ORCHESTRATOR review vòng 4; giữ IN_PROGRESS đến khi required verification/code mới và AC20/22 trên trình duyệt/Android hoàn tất. Không commit/push/PR, gọi agent khác, thêm dependency hoặc sửa ngoài Owned paths.


### Vòng 5 — Amendment D (IMPLEMENTER 2026-11-08)

- Baseline: `d7c969e`, ORCHESTRATOR báo 114 test PASS ngoài sandbox và đã ghim 8080 cho vòng 4. Phản hồi chạy thật ở Amendment D được giữ nguyên; chưa claim HUMAN LEAD đã duyệt giao diện vòng 5.
- Main changes / files:
  - `web/listen.py`: thêm `clip_metadata`, dùng **review.names.short_code + ep.kind_fields + ep.label**, đánh số 1-based trên toàn render manifest và total=độ dài manifest, gồm mục skipped/deleted như `_names` / `copy_prefixes`. API listen có code, ep_label, number, total. `routes/watch.py.decorate` dùng cùng helper cho queue và mục hiện tại; cache metadata mỗi episode trong một lần decorate, không tin code/title do client gửi khi có manifest. Không gọi kho/job/ffprobe. `review/names.py` chỉ đọc, không sửa.
  - Tập ngoài bộ kinh vẫn dùng API tập hiện có; client lấy code đã có trong download_name (được tạo qua short_code), không tự tạo mã hoặc tính lại độ rộng số. Số bài UI lấy từ view tập đang có.
  - `watch_party.py`: thêm advance_at, ended/advance_now/cancel_advance. Ended version hợp lệ dừng ở cuối bài và đặt hạn +3 s khi auto=true và có mục kế. Snapshot/command áp chuyển khi đến hạn, version tăng, anchor ở deadline; auto=false/hết danh sách thì dừng. Hủy/tắt auto/manual navigation xóa lịch; phát ngay chuyển luôn. Marker nội bộ giữ ended idempotent kể cả hai máy cùng version, máy báo muộn đã nhận version chờ, sau khi Hủy và sau deadline; replay cho phép ended mới. Không có timer/job nền trên server.
  - `player.js`: thẻ đếm ngược chung dùng server_time + advance_at cho WATCH1, deadline performance.now cho Nghe. Có code/title mục kế, 3/2/1, Phát ngay/Hủy; gộp hết tập/hết danh sách vào một thẻ. WATCH1 gửi ended, không gửi next từ sự kiện ended; client đợi snapshot server chuyển. Xóa notifyEpisodeEnd / noticeTimer cũ. Lệnh next thủ công sau Hủy vẫn phát mục kế. Guard finishedKey/current.ended tránh sự kiện ended trùng/cũ tạo lại lịch.
  - Shared heading/duration/queueButton: code đơn cách, title tối đa 2 dòng, m:ss bên phải. scrollToVideo chỉ khi visible, scroll mượt block=start với scroll-margin tính từ thanh sticky/fixed đang hiện. List click ở Nghe và WATCH1 dùng helper; Nghe không cuộn xuống list trước khi cuộn lên video.
  - `listen.js`, `watch.js`, `episode.html`, `watch.html`, `style.css`: video rồi code — title đậm / dòng phụ Tập N · kind number/total; bỏ tên video dài khỏi summary, chỉ giữ nhỏ ở khung Nghe. Nhóm “Tập N · k bài”, segmented buttons aria-pressed nhớ filter, checkbox role=switch, control icons căn giữa ≥44 px, queue gọn, resume/notice/invitation cùng biến màu/thẻ bo viền. Giữ PiP, budget retry và details/manual-open của vòng trước. Quản lý HTML/scripts và app.js không đổi.
- Helper mới (đã tìm và đối chiếu `_names`, `copy_prefixes`, `_copy`, `ep.label`, `review.names.episode_label/short_code/download_name`): clip_metadata chia sẻ canonical numbering; WatchRoom._apply_advance cho deadline thuần clock; AutoShortPlayer.heading/duration/queueButton/scrollToVideo/renderAdvance/advanceNow/cancelAdvance cho UI dùng chung. Tái dùng player, auth, API favorite và kiểu card/button/màu hiện có; không dependency/module mới.
- AC → test:
  - AC23/24/26 client: `/tmp/listen1-round5-local.cjs` PASS với DOM/media/clock/fetch giả: code/heading/meta/row và duration, nhóm ngắn, filter buttons aria-pressed/localStorage, cuộn video smooth chỉ khi visible (kể cả margin offset), code tập lẻ từ download_name; giữ không autoplay, details tự mở tập đang phát.
  - AC24 server: `test_codes_use_download_labels_positions_and_width_including_skipped` PASS: label 20 từ titles thay vì playlist index, manifest 100 mục có skipped → T20_S002/T20_S003, khai thị T20_KT01/KT02, đối chiếu code với download_name qua ep._names. `test_watch_codes_are_derived_from_download_manifest_not_client` PASS: queue/current code, canonical title/number/total/duration, bỏ code giả và không bịa code cho URL không có manifest.
  - AC25 server: `test_ended_countdown_is_shared_idempotent_and_advances_on_read`, `test_ended_simultaneous_only_creates_one_deadline`, `test_late_peer_ended_with_fresh_version_does_not_extend_or_restart_wait`, `test_countdown_cancel_now_auto_and_last_item`, `test_due_countdown_is_applied_before_commands_and_navigation_cancels` PASS. Clock giả kiểm trước/sau 3 s, hai máy, duplicate muộn, cancel/advance_now/auto=false/hết danh sách, replay và áp deadline trước command.
  - AC25 client: smoke local kiểm 3→2→1, chưa chuyển ở 2,999 s, chuyển ở 3 s, Hủy không chuyển sau 5 s, Phát ngay, đổi nguồn xóa lịch, auto=false/hết danh sách, chỉ một thẻ gộp thông báo tập. `/tmp/listen1-round5-watch.cjs` PASS: ended không gửi next, snapshot deadline, Hủy/advance_now, poll chuyển thật theo state server giả, code/meta/queue, cuộn mượt. Next trong smoke chỉ xuất hiện do thao tác thủ công sau Hủy.
  - Không hồi quy PiP/retry: `node /tmp/listen1-round4-player.cjs` PASS với code mới (PiP/fallback, effective visibility, source element, cap no-progress/6, log một lần).
  - AC26/27: đã rà CSS dùng biến/card/button hiện có, track min-width:0, overflow-wrap, max-width100%, controls chạm ≥44 px; chưa render/đo scrollWidth 360 px hoặc thử giao diện/đếm ngược hai máy thật. HUMAN LEAD/ORCHESTRATOR cần xác nhận trên 8080/điện thoại.
- Verification vòng 5:
  - `PYTHONPATH=/home/ntnghia/projects/yas-listen1/src conda run --no-capture-output -n auto-short pytest tests/test_web_listen.py tests/test_web_watch_party.py -q -k 'not test_http' -x --tb=short`: **92 passed, 7 deselected in 5.65s** (lần cuối).
  - `node --check` cả player.js/watch.js/listen.js/app.js: **PASS**; hai smoke vòng 5 và smoke PiP/retry vòng 4: **PASS**.
  - `git diff --exit-code d7c969e -- src/auto_short/review/names.py src/auto_short/web/static/app.js`: **PASS, diff rỗng**; so sánh Quản lý HTML/scripts và ID duy nhất: **PASS**; `git diff --check`: **PASS**.
  - Không chạy TestClient/full suite trong sandbox theo delegation; không gọi mạng thật, không chạm runtime 8080. Kết quả 114 PASS ở baseline thuộc vòng 4.
- Diff so với `d7c969e`, không tính contract/Amendment D có sẵn: app **+311 / −101**, test **+120 / −0**, tổng **+431 / −101**.
- Review / lifecycle: sẵn sàng ORCHESTRATOR review vòng 5; giữ IN_PROGRESS tới khi required verification/code mới và AC27 thực tế được hoàn tất. Không commit/push/PR, gọi agent khác, thêm dependency hoặc sửa ngoài Owned paths.

### Amendment J (HUMAN LEAD 2026-11-08, chạy thật `ef40827`) — đã implement, chờ review / verification ngoài sandbox

Bằng chứng: "Khai thị cho 15 tập 1 phần. Nút đã rõ chữ. 3. Có nhớ" (PASS AC 42, AC 44). "Top playlist trong trang yêu thích thay thế luôn cho tab yêu thích và ghép tay vì cái này tôi không dùng đến".

46. Cỡ phần khai thị (AC 43): 15 bài / phần (thay 12).
47. Trang Yêu thích: trình phát (khối `listen-*`, hiện ở đầu trang) chuyển thành tab **"Nghe yêu thích"**, tab đầu tiên và mặc định, **thay tab "Yêu thích & ghép tay"** (gỡ pane `fv-pane-manual` và JS chỉ phục vụ pane đó trong `favorites.js`). Còn 3 tab: Nghe yêu thích · Gợi ý chủ đề (AI) · Video đã ghép. Rời tab Nghe → trình phát tạm dừng (`suspend` sẵn có), quay lại → tiếp tục được. Backend / API ghép tay và video đã ghép giữ nguyên (không xóa route / dữ liệu). Bỏ tim qua ♡ của trình phát.
48. Chạy thật: Android Chrome — trang Yêu thích mở vào tab Nghe, đổi tab dừng phát, khai thị 15 bài / phần.

#### Result — Amendment J (IMPLEMENTER 2026-11-08, base `a127081`)

- **Chạy thật HUMAN LEAD tại `ef40827`: PASS AC 42 (chữ nút đọc được) và AC 44 (nhớ chỗ nghe)**, theo xác nhận delegation / bằng chứng Amendment J; không phải kết quả chạy thật do IMPLEMENTER thực hiện. ORCHESTRATOR báo 185 test web PASS ngoài sandbox ở baseline; chưa suy ra PASS cho code J.
- AC 46: đổi duy nhất `AutoShortPlayer.favoritePartSizes.khaithi` thành **15**. Short 35 và Cả hai 4 tập giữ nguyên; phòng nhận nhóm từ client theo cơ chế I.
- AC 47: `favorites.html` có tab đầu / mặc định **Nghe yêu thích**, rồi AI và Video đã ghép. Khối trình phát cũ nằm trong `fv-pane-listen`; gỡ `fv-pane-manual` / `fv-tab-manual`. `favorites.js` luôn mở Nghe kể cả browser có lựa chọn tab cũ, vẫn giữ chuyển tab bằng phím và `Favorites.showTab("videos")` dùng bởi kế hoạch chủ đề. `favorites-tab` nối vào helper `switchTab` tách từ listener `episode-tab` sẵn có trong `listen.js`: rời Nghe lưu vị trí rồi suspend; quay lại activate, một mình có thể bấm phát tiếp đúng bài / giây, phòng đồng bộ lại timeline mà không dừng phòng của người khác. Guard khởi tạo cũng xét pane tổ tiên nếu đang ẩn.
- Code bị xóa: chọn nhiều / checkbox / bộ lọc riêng của ghép tay, `autoPreview`, `unheart`, `create`, `loopBox`, `row`, `updateConcat`, `updateAuto`, state `ticked/openLoop/kindFilter`, lưu lựa chọn tab/filter cũ và listener phục vụ pane manual trong `favorites.js`. `listen.js` bỏ `refreshFavorites`, hàng đợi `favoriteRefresh`, listener refresh từ manual pane, sự kiện `listen-favorite-changed` và source marker không còn cần. Giữ `favorites-changed` cho `theme_plan.js`; bỏ tim và lọc queue phòng trong trình phát giữ nguyên. Giữ card video ghép cũ, phát / tải / copy / xóa, đã đăng, ảnh bìa và nhạc; không sửa backend / route / API / dữ liệu ghép tay.
- Tìm bằng `rg -n 'fv-pane-manual|fv-tab-manual|ghép tay' tests/`: chỉ test UI trong `tests/test_web_theme_plan.py` kiểm pane cũ. Cập nhật file này theo yêu cầu delegation (test tương ứng của Amendment J); không sửa / xóa test backend `tests/test_web_compilation.py`. Test Node từng bấm nút ghép để kích reload nay dùng callback polling thật của module; vẫn kiểm video đã ghép, publish, thumbnail và các ca theme. Các test sự kiện từ manual pane trong `test_web_listen.py` thay bằng test lifecycle tab; không giữ test cho UI đã gỡ.
- Helper mới duy nhất: `switchTab` là phần body của listener cũ, dùng chung cho trang tập / Yêu thích; không thêm module / dependency.

| AC | Test / evidence |
|---|---|
| 46 | `test_favorites_part_sizes_and_sparse_episode_groups` (parametrize 15/35/4); `test_favorites_tab_suspends_and_can_resume_same_track` (phần có 15 khai thị cả một mình/phòng) |
| 47, tab / UI còn lại | `test_js_favorites_tabs_and_existing_compilations` (default/legacy saved/blocked storage, keyboard, video, published); `test_favorites_ui_tab_panel_ownership` (thứ tự tab, ownership, pane và JS manual đã gỡ) |
| 47, suspend / nghe tiếp | `test_favorites_tab_suspends_and_can_resume_same_track` (một mình/phòng, hidden không phát sau poll, trở lại đúng bài / giây, sự kiện tim cho theme vẫn có và không tải lại list) |
| 48 | Chưa chạy Android Chrome; ORCHESTRATOR / HUMAN LEAD xác nhận |

- Verification đã chạy, cwd worktree:
  - `PYTHONPATH=/home/ntnghia/projects/yas-listen1/src conda run --no-capture-output -n auto-short pytest tests/test_web_listen.py tests/test_web_watch_party.py tests/test_web_theme_plan.py -q -k 'not test_http and (not test_web_theme_plan or test_js_favorites_tabs_and_existing_compilations or test_favorites_ui_tab_panel_ownership or test_js_smoke_and_text_only)' -x --tb=short` → **165 passed, 77 deselected, 1 warning in 9.23s** (warning deprecation từ import TestClient; không khởi tạo TestClient). Gồm 126 test listen/phòng và 39 test JS/theme tĩnh; test HTTP / socket không chạy.
  - `node --check` cho `player.js`, `listen.js`, `favorites.js` → **PASS** (mọi JS đổi); `git diff --check` → **PASS**.
  - `git diff --exit-code a127081 -- src/auto_short/compilation src/auto_short/web/compilations.py src/auto_short/web/routes/compilations.py tests/test_web_compilation.py` → **PASS, diff rỗng**.
- Không chạy bộ đủ 5 file web của delegation, phần HTTP/server trong `test_web_theme_plan.py`, full suite hoặc Android/two-browser thật vì giới hạn sandbox không có loopback; ORCHESTRATOR chạy ngoài sandbox. Không claim PASS AC 48.
- Diff so với `a127081`, không tính contract (bao gồm Amendment J do ORCHESTRATOR soạn sẵn): app **+57 / −249**, test **+67 / −71**, tổng **+124 / −320**. Sẵn sàng review; lifecycle giữ **IN_PROGRESS** tới khi review / required verification ngoài sandbox hoàn tất. Không commit / push / PR / gọi agent khác / gọi mạng thật / restart server.

#### Result — Amendment J, sửa harness packaging (IMPLEMENTER 2026-11-08, base `20f11fb`)

- Theo delegation vòng sửa, bổ sung `CustomEvent` và `document.dispatchEvent` vào VM `NODE_CARDS` trong `tests/test_web_packaging.py`; lưu sự kiện và assert `favorites-tab` / `detail = "listen"` khi khởi tạo. Không đổi JS trình duyệt, không nới hoặc bỏ các assertion thumbnail / intro / ảnh bìa cũ.
- Rà `rg -n 'favorites\.js' tests/`: VM nạp module chỉ ở packaging và theme-plan; VM theme-plan đã có cả hai API, test music chỉ đọc source. Không còn harness VM khác thiếu API này.
- AC 47 / hồi quy packaging: cả 6 case `test_both_video_cards_thumbnail_actions_and_polling[empty|stale|missing]` và `test_kti2_intro_status_and_cover_links_on_both_cards[intro_stale|intro_current|missing_cover]` **PASS** trong lệnh targeted dưới đây.
- Verification: `PYTHONPATH=/home/ntnghia/projects/yas-listen1/src conda run --no-capture-output -n auto-short pytest tests/test_web_packaging.py tests/test_web_theme_plan.py tests/test_web_listen.py -q -k 'test_web_packaging or (test_web_listen and not test_http) or test_js_favorites_tabs_and_existing_compilations or test_favorites_ui_tab_panel_ownership or test_js_smoke_and_text_only' -x --tb=short` → **81 passed, 70 deselected, 1 warning in 23.27s** (warning TestClient deprecation lúc import). Bao gồm toàn bộ packaging, JS/theme và listen không HTTP.
- Đã thử lệnh đủ ba file theo delegation với `timeout 30s` và `conda run --no-capture-output`: chạy qua 18 case packaging, sau đó không hoàn tất phần HTTP/TestClient của theme-plan trong sandbox; **exit 124**, không claim PASS cả ba file. ORCHESTRATOR chạy đủ ngoài sandbox. `git diff --check` **PASS**.
- Diff test **+4 / −3**, app **+0 / −0**, không helper production mới. Sẵn sàng review; không commit / push / PR / mạng thật / restart server; lifecycle giữ IN_PROGRESS chờ verification ngoài sandbox.

### Amendment I (HUMAN LEAD 2026-11-08, chạy thật `fdd6d39`) — đã implement, chờ review / verification ngoài sandbox

Bằng chứng: "1,2 đều ổn nhưng chữ trên nút bị tệp màu ko thấy" (thẻ đè video: PASS AC 28 / 31 vị trí). "Khi sử dụng playlist ở yêu thích càng về sau video càng nhiều như vậy tôi sẽ không thể nào coi được hết nên có cách phân ra nhiều [phần] và nên thêm có chức năng chọn bài trong playlist của yêu thích". Cỡ phần: "10-15 bài khai thị, short 30-40 shorts vì short nhiều hơn khai thị, nếu cả hai thì 3,5 tập lớn" → ORCHESTRATOR chốt giữa khoảng: lọc chỉ khai thị 12 bài / phần; chỉ Short 35 bài / phần; cả hai: 4 tập / phần (bài yêu thích của 4 tập liền nhau có bài yêu thích).

42. Sửa: chữ của nút / select trong thẻ đè video (nền tối) đủ tương phản (cả `.btn` thường và `.btn.primary`), mọi trang dùng khối `listen-*`.
43. **Yêu thích chia phần** (thay "một danh sách liên tục" của AC 39) theo bộ lọc hiện tại (Short / Khai thị / cả hai — bộ lọc sẵn có): cỡ phần như trên, hằng số một chỗ. Danh sách chỉ hiện bài của phần đang phát, tiêu đề "Phần k · …"; **bấm một bài → phát bài đó** (như AC 23). Ô chọn phần ở vị trí ô chọn tập ("Phần 1 (Tập 1–4)" / "Phần 1 (bài 1–35)"). Tự chuyển / đếm ngược trong phần; hết phần → dừng + thẻ "Đã hết Phần k" với nút "Nghe Phần k+1" + chọn phần khác — tái dùng cơ chế biên tập AC 31 (phần là "nhóm" thay cho tập; không nhân đôi code). Đổi bộ lọc → chia lại, giữ bài đang phát. Chế độ phòng (Xem chung từ Yêu thích) dùng cùng nhóm phần, đồng bộ hai máy.
44. **Nhớ chỗ nghe** ở Yêu thích (như tab Nghe: `localStorage`, bài + vị trí): mở lại trang → về đúng bài / phần. Nhận diện bằng bài (episode_id + clip), không bằng số thứ tự.
45. Chạy thật: Android Chrome — chữ nút đọc được; Yêu thích thấy phần, bấm bài được, hết phần thấy thẻ hỏi, mở lại trang nghe tiếp đúng chỗ.

#### Result — Amendment I (IMPLEMENTER 2026-11-08, base `825c5df`)

- Delegation hiện hành authorize phần server nhóm trong `src/auto_short/web/watch_party.py` (bổ sung Owned paths cho Amendment I); các file còn lại nằm trong Owned paths ở đầu contract / Amendment H. Không sửa route hoặc API listen, trang Quản lý, HTML ghép video, dependency hay runtime.
- Cách làm:
  - AC 42: sửa CSS sau rule `.small` của thẻ tối: `.btn` / `.btn.primary` dùng chữ `#1d1d1b` trên nền sáng / vàng sẵn có; select / option chữ tối trên nền trắng. Rule `.small { color: #ddd }` trước đó ghi đè màu chữ nút nhỏ làm mất tương phản.
  - AC 43: nhóm là một khái niệm trong `player.js`: `group(entry)` lấy nhóm gửi sẵn hoặc tập từ helper `episode`; danh sách, biên tự chuyển, ô chọn và thẻ hết nhóm đều dùng nó. `groupFavorites` thuần tạo phần từ danh sách đã lọc; cỡ phần chỉ khai báo tại `favoritePartSizes` (12 khai thị / 35 Short / 4 tập có bài yêu thích cho Cả hai). Giữ danh tính và giây khi đổi bộ lọc mà bài vẫn thuộc bộ lọc; nếu bài bị loại bởi bộ lọc thì chọn điểm bắt đầu như hành vi cũ. `choose` hủy thẻ / timer cũ kể cả khi giữ cùng bài. Chỉ hiển thị bài của phần hiện tại, bấm bài phát và cuộn lên video, hết phần dừng với nút nghe phần sau + select phần khác. Bỏ tim dùng `visible` cũ, so sánh danh tính thay tham chiếu object vì nhóm được tạo lại.
  - Phòng gửi `group: {id, label, choice, kind}` theo từng mục trong lệnh `set`; server validate trước mutation, dùng nhóm thay tập khi có, lệnh `group` chọn mục đầu nhóm cho cả phòng. `queue_version` và decorate route hiện có tự giữ metadata này, không cần một luồng riêng. Snapshot sao chép sâu để nhóm lồng nhau không bị input / người đọc sửa. Phòng cũ không có nhóm vẫn dùng tập suy từ URL / lệnh `episode`; `continuous` chỉ còn là tương thích phòng cũ (client tập trung fallback tại `group`, server tại `_group_of`). Link `/watch` giữ nguyên.
  - AC 44: dùng `save` và khóa `auto-short-listen-position:<playlist>:fav` sẵn có; mở Yêu thích chọn đúng `episode_id + clip_id` và giây đã lưu, ở trạng thái dừng. Phần tính lại từ danh tính, không lưu index / số phần. Bài bị lọc thì mở Cả hai để khôi phục; bài đã mất thì về bài đầu. Tab Nghe giữ nút "Nghe tiếp" như trước.
- Code bị thay / xóa: `continuous` / `listLabel` ở player và các nhánh hiển thị danh sách liên tục trong listen; `renderEpisodeList` → `renderGroupList`, `nextInEpisode` → `nextInGroup`, `episodes` → `groups`, callback `onEpisode` → `onGroup`; server `_same_episode_next` → `_same_group_next`. Không giữ bản sao cơ chế phần / tập. Cờ `continuous` server được giữ riêng vì tương thích.
- Helper mới: `group`, `groupFavorites`, `favoritePartSizes` (player), `rebuildItems` (listen), `_group_of` (server). Đã tìm bằng `rg -n 'onEpisode|episodes\(|nextInEpisode|renderEpisodeList|continuous|listLabel' src/auto_short/web/static` và đọc `episode_of` / `_same_episode_next`: tái dùng và khái quát các helper cũ nêu trên; helper chia phần là mới vì chưa có logic cỡ phần theo bộ lọc. Test dùng fixture `run_player_js` chung trong cùng file, DOM / clock giả chạy trực tiếp source JS bằng Node, không server / browser dependency.

| AC | Test / evidence |
|---|---|
| 42 | `test_overlay_action_text_has_contrast` (tĩnh: màu chữ / nền và thứ tự override); chưa đo giao diện thật |
| 43, chia phần / chọn bài / hết phần | `test_favorites_part_sizes_and_sparse_episode_groups` (parametrize 3 bộ lọc, tập cách số, không cắt Short/KT cùng tập); `test_favorites_click_filter_end_card_and_unheart` (DOM thật module, click / đếm ngược / biên phần / đổi lọc); phần payload của `test_favorites_resume_identity_and_room_group_payload` |
| 43, phòng / tương thích | `test_favorites_groups_cross_episode_but_stop_at_part_end` (cùng nhóm qua tập, khác nhóm cùng tập, lệnh chọn, hai client); `test_group_metadata_survives_route_queue_cache_and_invite` (gọi endpoint trực tiếp, queue cache / client mới); `test_invalid_group_metadata_is_rejected_atomically`; test `episode` / `continuous` cũ vẫn PASS |
| 44 | `test_favorites_resume_identity_and_room_group_payload` (xóa bài phía trước đổi index/phần, lưu lại giây); `test_favorites_resume_hidden_kind_or_missing_identity` (Short / KT cùng clip id, bài bị lọc hoặc đã mất) |
| 23/28/29/30/31/40 | `test_episode_groups_keep_end_boundary_and_manual_next`, `test_favorites_click_filter_end_card_and_unheart`, các guard tĩnh cũ về cuộn / overlay / giao diện chung và test server tập cũ |
| 45 | Chưa chạy Android Chrome; ORCHESTRATOR / HUMAN LEAD xác nhận |

AC 43 có hơn 3 hàm test vì gồm thuật toán chia phần thuần, DOM một mình, trạng thái phòng, cache route và validation; các ca cùng nhánh được parametrize, không thêm dependency.

- Verification đã chạy (cwd `/home/ntnghia/projects/yas-listen1`):
  - `PYTHONPATH=/home/ntnghia/projects/yas-listen1/src conda run --no-capture-output -n auto-short pytest tests/test_web_listen.py tests/test_web_watch_party.py -q -k 'not test_http' -x --tb=short`: **121 passed, 9 deselected in 6.30s** (lần cuối). Gồm các test Node ở trên và endpoint trực tiếp, không socket.
  - `node --check src/auto_short/web/static/player.js` và `node --check src/auto_short/web/static/listen.js`: **PASS** (mọi JS đổi).
  - `git diff --check`: **PASS**.
- Không chạy theo giới hạn delegation (sandbox không có loopback, TestClient / server có thể treo):
  - `PYTHONPATH=/home/ntnghia/projects/yas-listen1/src conda run -n auto-short pytest tests/test_web_listen.py tests/test_web_watch_party.py tests/test_web_app.py tests/test_web_compilation.py tests/test_web_episode_ui_cp812.py -q` (đủ 5 file, gồm 9 test HTTP bị bỏ chọn và các file dùng TestClient).
  - Full suite `pytest -n auto -q`; thử Android / hai trình duyệt thật AC 45. ORCHESTRATOR chạy phần này; không claim PASS.
- Diff so với `825c5df` (không tính contract): app **+134 / −65**, test **+283 / −5**, tổng **+417 / −70**.
- Handoff: implementation sẵn sàng review; giữ lifecycle **IN_PROGRESS** tới khi required verification / review ngoài sandbox hoàn tất. Không commit / push / PR / gọi agent khác / gọi mạng thật / restart server.

#### Result — Amendment I, sửa review 1 (IMPLEMENTER 2026-11-08, base `b3f3a8e`)

- HEAD kiểm bằng `git log -1`: `b3f3a8e` (worktree sạch lúc nhận). ORCHESTRATOR báo **178 test web PASS ngoài sandbox** ở baseline; đó không phải kết quả verification của vòng sửa này.
- Finding 1 / AC 36: `startRoom` luôn gửi lệnh `auto` với đúng giá trị local sau `set`, cả true và false. Tái dùng API cũ; server / semantics `set` không đổi.
- Finding 2 / AC 40 + 43: `onFavorite` cập nhật cả đối tượng tim và cache `all`; đánh dấu URL đã bỏ tim trong `removedFavorites`. `roomHandler` cập nhật `currentItem` / `items` theo bài của phòng và trạng thái tim server trả về. `syncFavoriteRoom` chỉ chạy ở trang Yêu thích: giữ mục hiện tại, bỏ các mục đã bỏ tim khác bằng `set`, giữ danh tính bài, vị trí, paused, rate và giá trị auto của phòng. Khi bài hiện tại đổi, mục vừa bỏ tim rời queue của cả phòng và cache một mình; queue còn lại chia phần bằng `groupFavorites` hiện có, theo bộ lọc trong group của phòng. Guard `pruningRoom` tránh set lặp trong callback snapshot.
- Finding 3 / AC 40: trang Yêu thích nghe `favorites-changed`, `refreshFavorites` tải lại API favorites-only hiện có, cập nhật cache, giữ mục hiện tại nếu vừa bỏ tim để nghe hết, giữ bài + giây + trạng thái phát/dừng và chia lại phần. Các refresh xếp tuần tự để response cũ không ghi đè response mới. Sự kiện trình phát gửi có `detail.source = "listen"`, listener bỏ qua nguồn này; vẫn gửi `listen-favorite-changed` cho tab ghép tay như trước. Không cần sửa `favorites.js` / server.
- Helper mới: `roomEntry` gom serializer queue đã có ở `startRoom` để dùng lại khi lọc phòng; `syncFavoriteRoom`, `refreshFavorites` nối `rebuildItems`, `choose`, `groupFavorites` và transport `roomCommand` hiện có (đã tìm / đọc `onFavorite`, `unheart`, `favorites-changed`, `startRoom`, `roomHandler`). Code bị thay: nhánh chỉ poll khi bỏ tim trong phòng, nhánh chỉ gửi auto=false, serializer queue inline cũ.

| Finding / AC | Test chạy source JS qua fixture `run_player_js` hiện có |
|---|---|
| 1 / 36 | `test_start_room_always_transfers_solo_auto` (true/false, phòng cũ có giá trị ngược) |
| 2 / 40,43 | `test_room_unheart_prunes_after_navigation_and_keeps_parts` (giữ bài đang phát, đổi bài loại khỏi queue, chia lại 35+2, không set lặp, kết thúc phòng về một mình vẫn không có bài đã bỏ) |
| 3 / 40,43 | `test_manual_unheart_event_refreshes_player_without_loop` (một mình/phòng × phát/dừng; xóa bài đứng trước đổi index nhưng giữ bài + giây; xóa bài hiện tại chỉ loại sau khi đổi bài; đếm GET chứng minh không lặp sự kiện) |

- Test fixture bổ sung event thật trên DOM giả, fetch clone phản hồi / lưu tim giả và transport phòng có trạng thái (`set` giữ auto cũ như server). Không socket / dịch vụ thật / dependency mới.
- Verification vòng sửa: `PYTHONPATH=/home/ntnghia/projects/yas-listen1/src conda run --no-capture-output -n auto-short pytest tests/test_web_listen.py tests/test_web_watch_party.py -q -k 'not test_http' -x --tb=short` → **128 passed, 9 deselected in 6.90s**. `node --check src/auto_short/web/static/listen.js` (JS duy nhất đổi) và `git diff --check` → **PASS**.
- Không chạy đủ 5 file `test_web_listen.py`, `test_web_watch_party.py`, `test_web_app.py`, `test_web_compilation.py`, `test_web_episode_ui_cp812.py`, full suite hoặc Android / hai máy thật theo giới hạn delegation (TestClient / server có thể treo khi sandbox không có loopback). ORCHESTRATOR chạy ngoài sandbox; không claim PASS vòng sửa cho phần này.
- Diff so với `b3f3a8e`, không tính contract: app **+77 / −5**, test **+118 / −6**, tổng **+195 / −11**. Implementation sẵn sàng review; lifecycle giữ **IN_PROGRESS** chờ verification / review ngoài sandbox. Không commit / push / PR / gọi agent khác / gọi mạng thật / restart server.

### Amendment H (HUMAN LEAD 2026-11-08) — chưa làm, làm sau G

Bằng chứng: "Trang yêu thích gồm những video được thả tim cũng nên chuyển sang dạng xem playlist giống vậy luôn". Owned paths bổ sung (ORCHESTRATOR theo yêu cầu này): `src/auto_short/web/static/favorites.html`, `src/auto_short/web/static/favorites.js`, route / API yêu thích trong `src/auto_short/web/app.py` nếu cần thêm field (url / code) cho trình phát, test tương ứng.

39. Trang Yêu thích (của một bộ kinh) có trình phát chung của Amendment G (chế độ một mình + nút Xem chung), danh sách = các mục đã thả tim của bộ đó, theo thứ tự tập rồi mã (`T20_S01`…). Cả danh sách yêu thích là **một danh sách liên tục** (tự chuyển / đếm ngược 3 s chạy qua hết, không dừng ở biên tập như AC 31); dòng danh sách vẫn ghi mã + tiêu đề.
40. Bỏ tim mục đang có trong danh sách → mục biến khỏi danh sách (đang phát mục đó thì phát tiếp tới hết bài rồi sang mục kế). Các chức năng sẵn có của trang Yêu thích (ghép video, đánh dấu đã đăng, ảnh bìa …) giữ nguyên.
41. Chạy thật: Android Chrome — mở Yêu thích, nghe liên tục qua nhiều mục, bấm Xem chung được.

### Amendment G (HUMAN LEAD 2026-11-08) — chưa làm

Bằng chứng: "Trang nghe chung cũng nên có tab tới tập giống trang nghe. Có điều tôi thấy hai trang này gần như bây giờ y chang nhau chúng ta có nên gộp một hay không" → ORCHESTRATOR đề xuất gộp, HUMAN LEAD chọn "Gộp ngay".

34. **Một giao diện, hai chế độ**: tab Nghe (một mình) và Xem chung (phòng) dùng chung một giao diện + một module JS (không còn `watch.js` / `listen.js` trùng nhau; `/watch` chỉ là trang vỏ nạp cùng giao diện ở chế độ phòng). Hàng điều khiển, danh sách theo tập (AC 30), thẻ đếm ngược / hết tập (AC 25 / 31), PiP (AC 18), log chẩn đoán (AC 16) giống hệt nhau ở hai chế độ.
35. **Ô chọn tập** (tới tập) có ở cả hai chế độ. Chế độ phòng: chọn tập = lệnh `episode` (cả phòng sang). Vì thế phòng tạo từ tab Nghe nhận **cả bộ kinh** (như danh sách của tab Nghe, cùng trần), index = mục đang phát — bỏ hạn chế "chỉ từ mục đang phát trở đi". Phòng tạo từ chỗ khác (danh sách một trang) giữ như cũ; ô chọn tập chỉ hiện các tập có trong phòng.
36. Nút **"Xem chung"** ở chế độ một mình: tạo phòng từ trạng thái hiện tại (mục, vị trí, Tự chuyển) và chính trang đó chuyển sang chế độ phòng, hiện link mời (thanh mời sẵn có), không mở trang mới. Mở link mời `/watch` → cùng giao diện, chế độ phòng. "Kết thúc xem chung" → về chế độ một mình tại mục / vị trí hiện tại (khi đang ở tab Nghe) hoặc như hành vi cũ ở `/watch`.
37. Giữ: API `/api/watch/*`, `/api/listen*`, link mời cũ vẫn chạy; hai máy đồng bộ như AC trước; không cuộn trang xuống danh sách (AC 29).
38. Chạy thật: Android Chrome — tab Nghe bấm Xem chung, máy 2 mở link, chọn tập ở một máy thì cả hai đổi; kết thúc thì về nghe một mình.

### Amendment F (HUMAN LEAD 2026-11-08, trước khi thử `cdf3b81`) — chưa làm

Bằng chứng: "Sửa lại một chút cho cả hai trang xem chung cũng như trang nghe là phần cuộn chỉ hiện đúng tập các tập hiện tại khi xem hết các tập nhỏ ở trong tập đó thì báo cho người dùng biết là hết tập và hỏi người dùng chuyển sang tập khác khi chuyển sang tập khác thì Trang chỉ hiện các tập nhỏ trong đúng tập đó thôi cho gọn".

30. **Danh sách chỉ của tập đang phát** (tab Nghe và `/watch`): khung danh sách chỉ hiện các mục (Short + khai thị) của tập chứa mục đang phát, tiêu đề "Tập N · k bài". Thay AC 21 (không còn `<details>` cho các tập khác). Đổi tập → danh sách thay bằng mục của tập mới. `/watch`: tập suy như AC 12 (`episode_id` từ url mục); danh sách phòng chỉ một tập thì như cũ.
31. **Hết tập thì hỏi, không tự sang tập khác**: tự chuyển / đếm ngược (AC 11 / 25) chỉ trong cùng tập. Hết mục cuối của tập → dừng, hiện thẻ (role="status", không tự ẩn) "Đã hết Tập N" + nút "Nghe Tập N+1" (nếu có) và cách chọn tập khác (tái dùng chọn tập sẵn có của trang nếu có); hết danh sách → "Đã hết danh sách". `/watch`: thẻ và lựa chọn đồng bộ hai máy theo trạng thái phòng (một người bấm là cả phòng sang tập đó). Thay phần "hết tập" của AC 12 / 25.
32. ⏮ / ⏭ ở mục đầu / cuối tập vẫn sang tập trước / sau (người dùng tự bấm), danh sách đổi theo AC 30.
33. Chạy thật: Android Chrome — danh sách chỉ một tập; hết tập thấy thẻ hỏi, bấm sang tập sau thì danh sách đổi; `/watch` hai máy thấy cùng.

### Amendment E (HUMAN LEAD 2026-11-08, chạy thật `9c5cf63`) — chưa làm

Bằng chứng: "3. Ok rồi" (nghe ở app khác bằng màn hình nhỏ / toàn màn hình: PASS AC 18 / 22). "Hết bài không thấy đếm ngược 3 giây. Ở trang nghe khi hết bài tự chuyển sang bài tiếp theo thì nhảy xuống tab tiêu đề, không cuộn lên video."

28. Sửa: thẻ đếm ngược 3 s (AC 25) phải hiện khi hết bài (tab Nghe và `/watch`) — tìm vì sao không render (kiểm `advance_at` / timer / CSS `hidden`).
29. Sửa: tự chuyển bài (và đổi bài do đếm ngược) không cuộn trang tới dòng danh sách; nếu cần cuộn thì cuộn lên khung video như AC 23 (chỉ khi trang visible), danh sách chỉ cuộn bên trong khung của nó.

### Amendment E — IMPLEMENTER 2026-11-08 (base a355e6c)

- Nguyên nhân AC 28/29 (cùng gốc): mô phỏng Node (DOM giả) cho thấy logic đếm ngược đúng, thẻ có hiện (không phải lỗi `advance_at` / `hidden` / CSS / server). Nhưng mỗi lần đổi bài `renderCurrent` gọi `button.scrollIntoView({block:"nearest"})` cho dòng đang phát → cuộn cả trang xuống danh sách (`.listen-queue` không có khung cuộn riêng). Sang bài sau, khung nhìn nằm ở danh sách nên thẻ đếm ngược (dưới video) nằm ngoài màn hình. Chưa kiểm trên trình duyệt thật; đây là nguyên nhân hợp lý nhất từ code.
- Sửa: `listen.js` bỏ `scrollIntoView`, dùng helper mới `AutoShortPlayer.scrollWithin(container, item)` (chỉnh `scrollTop` của khung); `style.css` `.listen-queue { max-height: 28rem; overflow: auto }` để có khung cuộn. `player.js`: khi hết bài gọi `scrollToVideo()` (thẻ đếm ngược hiện trong tầm nhìn), và sau khi đổi bài do hết bài (tự chuyển / "Phát ngay", cả `/watch`) cuộn lại lên video qua `scrollToVideo()` (chỉ khi visible + active), cờ `endedKey`. Không dùng `focus()`.
- Test: `tests/test_web_listen.py::test_auto_advance_never_scrolls_page_to_list` (assert tĩnh); mô phỏng Node ngoài repo xác nhận `scrollIntoView` chỉ gọi trên video. Verification: pytest 3 file 122 PASS; `node --check` 4 file OK. Chưa chạy thật trên trình duyệt.

### Amendment F — IMPLEMENTER 2026-11-08 (base 25af39f)

- Cách làm: `player.js` thêm `renderEpisodeList` (khung danh sách chỉ mục của tập đang phát, tiêu đề "Tập N · k bài", cuộn trong khung), `nextInEpisode`, `episodes`, `currentEntry`; tự chuyển / đếm ngược chỉ trong cùng tập; hết tập thẻ không tự ẩn: "Đã hết Tập N", nút "Nghe Tập N+1", `<select>` "Chọn tập khác…" (`onEpisode`). `listen.js` / `watch.js` dùng chung hàm này (`watch.html` `<ol>` → `<div>`). `watch_party.py`: `episode_of(url)` (tập suy từ `/files/<id>/…`, `.kt` về tập gốc), tự chuyển / `advance_now` / `ended` không vượt tập; snapshot thêm `finished` (thẻ đồng bộ hai máy); lệnh mới `episode` (cả phòng sang mục đầu của tập); `set` nhận thêm `ep_label` tùy chọn (≤ 40 ký tự) để nhãn "Tập N" đúng trong `/watch`. ⏮ / ⏭ vẫn vượt tập.
- Code bị xóa: nhóm `<details>` nhiều tập, `groups` / `manuallyOpen` / toggle trong `listen.js`; `queueKey` và dựng danh sách phẳng trong `watch.js`.
- Helper mới: `renderEpisodeList`, `nextInEpisode`, `episodes`, `currentEntry` (player), `episode_of`, `_same_episode_next` (server).
- AC → test: AC 31 `test_auto_advance_stops_at_episode_end_and_card_is_shared`, `test_episode_command_moves_whole_room_to_first_item` (AC 32 ⏭ vượt tập cũng ở test đầu); AC 30 `test_list_shows_only_playing_episode_in_both_pages` (assert tĩnh); mô phỏng Node: danh sách 1 tập, hết tập hiện thẻ không ẩn. API listen không đổi. Chưa chạy thật trình duyệt (AC 33).

### Amendment G + H — IMPLEMENTER 2026-11-08 (base 1e10689)

- G, cấu trúc mới: `listen.js` là module duy nhất của giao diện (hai chế độ `inRoom` false / true; `setRoomMode`, `roomHandler`, `startRoom`, `exitRoom`), dùng cho `episode.html` (tab Nghe), `watch.html` (vỏ, luôn chế độ phòng) và `favorites.html`. `watch.js` chỉ còn lớp truyền tải dùng mọi trang: client id, `command`/`poll`, thanh mời, nút "Xem chung" ở trang khác; lộ `AutoShortWatch.room {active, handler, message, onVersion}` + `end/stopPolling/resume/leave`. Không còn `AutoShortPlayer` hay danh sách trong `watch.js`.
- "Xem chung" (một mình): `set` với cả danh sách của tab (index = mục đang phát, vị trí, paused, rồi lệnh `auto` nếu đang tắt), chính trang chuyển sang chế độ phòng + link mời `/watch` (nút Sao chép). "Kết thúc xem chung" → `exitRoom` về một mình đúng mục / vị trí (vỏ `/watch` giữ hành vi cũ: "Chưa có phòng xem chung"). Ô chọn tập (`listen-jump`) ở cả hai chế độ: phòng gửi lệnh `episode`; chỉ liệt kê tập có trong danh sách hiện tại. Phòng bị người khác kết thúc → về một mình (trang tập).
- Trần queue: `WatchRoom.set` nâng 300 → `MAX_QUEUE = 1000` (API listen không có trần; thông báo lỗi đổi theo). Nếu danh sách lớn hơn 1000, client gửi cửa sổ 1000 mục chứa mục đang phát. Test cũ dùng 300/301 sửa theo (1000/1001; `QUEUE * 334`).
- H: trang Yêu thích có cùng giao diện (`favorites.html` thêm khối `listen-*`; ghép / đã đăng / ảnh bìa nguyên). `GET /api/playlists/{id}/listen?favorites=true` (tham số `favorites_only` của `playlist_listen`) chỉ trả mục đã thả tim theo thứ tự tập rồi mã. Chế độ "liên tục" là một cờ, không if rải rác: `player.continuous` (+ `listLabel`) trong `player.js` (`nextInEpisode`, `boundary`, `renderEpisodeList` đều đọc cờ); phòng có `continuous` (lệnh `set` nhận `continuous: bool`, snapshot trả lại) để tự chuyển xuyên tập. Bỏ tim: mục ở lại tới khi mục đang phát đổi (`visible()` trong `listen.js`), rồi rời danh sách; `listen-favorite-changed` / `favorites-changed` làm `favorites.js` và kế hoạch chủ đề tải lại. Danh sách Yêu thích hiện cả danh sách liên tục (tiêu đề "Yêu thích · k bài").
- Code bị xóa: toàn bộ trình phát / dựng danh sách / `renderRoom` / pause-guard / pagehide trong `watch.js` (chuyển sang `listen.js`, một bản); `watch.html` markup `watch-*` (thay bằng khối `listen-*`); `buildList` / `groups` trong `listen.js` từ F.
- Helper mới: `setRoomMode/roomHandler/startRoom/exitRoom/roomAction/roomNavigate/visible/renderJump/showInvite` (listen.js), `AutoShortWatch.{room,end,stopPolling,resume,leave,sent}`, `WatchRoom._continuous`, `playlist_listen(favorites_only)`.
- AC → test: AC 34/30/31 `test_listen_and_watch_share_one_module` (tĩnh, 3 trang cùng khối `listen-*`, một nơi dựng player); AC 35 trần `test_*` chứa 1000/1001 trong `test_watch_party` (đã sửa) + lệnh `episode` từ F; AC 39 `test_favorites_only_keeps_order_and_marks_all_hearted`, `test_http_listen_favorites_query`, `test_continuous_room_crosses_episodes_and_shows_flag`; AC 40 kiểm tĩnh (`item === currentItem`). Mô phỏng Node DOM giả (`/tmp/claude-1000/h/sim2.js`, không thuộc repo) chạy: một mình → Xem chung (`set`) → chọn tập (`episode`) → Kết thúc → về một mình, ở trang tập và trang Yêu thích (`continuous: true`). Chưa chạy thật trình duyệt (AC 36–38, 41).
- Sửa sau review G + H (tải poll): snapshot có `queue_version` (`"<epoch>.<n>"`, epoch ngẫu nhiên mỗi lần server chạy để cache cũ không khớp nhầm; n tăng khi `set` / `end`). Client (`watch.js`) gửi `queue_version` đã giữ (query ở GET, body ở POST / DELETE); server chỉ gửi `queue` (và chỉ decorate cả queue) khi khác, còn không thì bỏ field `queue` và chỉ decorate mục hiện tại; client giữ cache và gán lại `queue`. Máy mới / link mời không có version nên nhận đủ. Đo (400 mục, tiêu đề ~40 ký tự, `-s`): có queue 36 089 B, không queue 403 B (≈ 90 lần nhỏ hơn). Test: `test_http_queue_sent_only_when_version_changes_and_size`. Fav cấp mục không dùng nên không cần version riêng (fav của mục hiện tại vẫn tính mỗi lần).
- Sửa AC 28 lần 2 (chạy thật Android Chrome: thẻ có render nhưng nằm ngoài tầm nhìn): `episode.html` / `watch.html` / `favorites.html` bọc video + `#listen-notice` trong `.player-stage` (`position: relative`); thẻ `position: absolute`, cách đáy 3,5 rem (chừa thanh điều khiển gốc của video), nền tối rgba(20,20,20,.92) chữ trắng, `max-height` giới hạn và cuộn trong thẻ, `left/right .5rem` nên vừa 360 px. Thẻ ẩn (`hidden`) không chiếm chỗ, không chặn video; hết tập thẻ che phần dưới video cho tới khi chọn tiếp. Logic đếm ngược không đổi. Test: `test_countdown_card_overlays_the_video_on_all_pages`. Chưa kiểm trên máy thật.

### Kết thúc (ORCHESTRATOR 2026-11-08)

- Chạy thật HUMAN LEAD trên 8080 (bản ghép tạm `tmp/8080-listen1-shutdown` = LISTEN1 + FIX-web-shutdown-slow), Android Chrome: Amendment E (AC 28 đếm ngược thấy được sau khi thẻ đè lên video, AC 29), F (AC 30–33), G (AC 34–38, hai máy), H (AC 39–41), I (AC 42 "Nút đã rõ chữ", AC 43, AC 44 "Có nhớ"), J (AC 46–48): "Ok tất cả ổn" (d73046a).
- Review thứ hai: Codex read-only trên `51f4af6` (G + H) — 3 finding P2 đều được ORCHESTRATOR xác nhận và sửa ở `a127081` (Xem chung giữ Tự chuyển; bỏ tim cập nhật phòng / danh sách Yêu thích; nghe sự kiện bỏ tim từ tab khác). Tab ghép tay sau đó bị gỡ ở J.
- Full suite bản ghép `d73046a`: **4214 passed, 2 skipped** (lần trước đó `fbb823c`: 6 fail `tests/test_web_packaging.py` do harness VM thiếu `CustomEvent`, sửa harness ở `HEAD` trước bản ghép, không đổi code ứng dụng).
- Implementer: Sonnet (E, F, G, H, sửa thẻ đè video) khi Codex hết quota; Codex (I, sửa review, J, harness) — ~103k + tokens các lần resume.
- Ops sau merge: xóa `work/_watch_audio/` trên 8080 (chế độ âm thanh đã gỡ).
- Manual checklist cũ (Nghe nền / công tắc Khai thị): thay bằng các AC chạy thật ở trên (Nghe nền đã bỏ — Amendment B / D; bộ lọc Short / Khai thị / cả hai PASS trong I).
