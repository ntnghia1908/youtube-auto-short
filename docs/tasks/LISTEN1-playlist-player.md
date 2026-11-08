# Task: LISTEN1 — Nghe theo danh sách cả bộ kinh (Short → khai thị, xuyên tập), view mặc định của trang tập

## Status / Approval

- Status: IN_PROGRESS
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
