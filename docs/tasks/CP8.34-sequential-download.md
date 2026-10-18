# Task: CP8.34 — Tải lần lượt nhiều file (1–3 file cùng lúc) trên trang bộ kinh

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `508a94c` (`main`, sau #85 CP8.32 + #86 CP8.33) / `feature/cp8.34-sequential-download` (worktree `../youtube-auto-short-cp834`).
- Human Lead approval: APPROVED D1–D7 (2026-10-17)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: route web mới + thay đổi hành vi route tải hiện có (theo dõi tiến độ gửi), CP8.3 web contract. Không đổi dependency, security model.

## Bối cảnh (2026-10-17, ORCHESTRATOR)

- HUMAN LEAD: "Nên hỗ trợ tải tuần tự … trên điện thoại tôi chỉ tải một lần được hai video hoặc hai bản zip để đảm bảo tốc độ tải. Nếu tôi tải nhiều bản thì sẽ chậm và có thể bị mất gói. Nên có chức năng cho tải nhiều nhưng tải từ từ, mỗi lần một hai gói." Trả lời câu hỏi cùng ngày: chọn ở **trang bộ kinh**; số file cùng lúc **chọn được 1–3, mặc định 2**; lỗi → **tự thử lại 2 lần**.
- Tải hiện nay: link `<a download>` → trình duyệt / trình quản lý tải của điện thoại tải thẳng (không giữ file trong bộ nhớ trang). Zip (`shorts.zip`, `all.zip`) là `StreamingResponse` tạo lúc tải (không có `Content-Length`, không hỗ trợ Range); mp4 (bản dọc, bản ngang HD, Short) là `FileResponse`.
- Trang web **không biết** khi nào một lần tải native xong. Tải bằng `fetch` + blob thì biết, nhưng giữ cả file (có thể vài GB) trong RAM điện thoại → không dùng.

## Goal

Trang bộ kinh tải lần lượt nhiều file đã chọn (zip / bản dọc / bản ngang HD), 1–3 file cùng lúc, tự thử lại khi lỗi; server báo khi mỗi file đã gửi xong.

## Quyết định cần HUMAN LEAD duyệt (D1–D7)

- **D1 Chọn.** Trang bộ kinh: mỗi tập có ô tick; thanh "Tải lần lượt" chọn loại: zip (Short + khai thị như nút zip hiện có, CP8.31 D3), bản dọc cả tập, bản ngang HD (chỉ tập có loại đó; tập không có thì bỏ qua và ghi rõ). Nút nhanh: "Chọn tất cả chưa đăng" (tập còn Short / khai thị chưa tick "Đã đăng"). Lần đầu Chrome trên điện thoại có thể hỏi "Cho phép tải nhiều tệp?" — chọn Cho phép một lần; trang ghi dòng nhắc này cạnh nút "Tải lần lượt".
- **D2 Cùng lúc.** Ô chọn 1 / 2 / 3, mặc định 2; nhớ theo trình duyệt (localStorage, try/catch).
- **D3 Biết khi nào một file xong (server theo dõi).** Mỗi lần tải trang thêm `?dl=<token>` (ngẫu nhiên, do trang tạo) vào URL tải. Server ghi trong bộ nhớ (không lưu đĩa, hết hạn 6 h) cho token đó: `state` = `sending` / `done` (đã gửi byte cuối) / `aborted` (client ngắt giữa chừng), `bytes_sent`, `bytes_total` (nếu biết). Route mới `GET /api/downloads/{token}` (cùng auth). Trang hỏi mỗi 2 s; `done` → bắt đầu file tiếp theo; `aborted` hoặc không có request nào tới sau 60 s → lỗi. Route tải không có `dl` giữ nguyên hành vi.
- **D4 Thử lại.** Lỗi → tự tải lại tối đa 2 lần (token mới, chờ 5 s); vẫn lỗi → dòng đỏ + nút "Thử lại", chuyển sang file sau. Zip tạo lúc tải nên tải lại là tải từ đầu (không tải tiếp phần dở); mp4 cũng tải lại từ đầu (Range: out of scope).
- **D5 Trạng thái trên trang.** Bảng hàng đợi tải: tên file, đang chờ / đang tải (MB đã gửi / tổng nếu biết) / xong / lỗi; nút "Dừng" (không bắt đầu file mới; file đang tải thì để trình duyệt tự xong) và "Tiếp tục". Trang phải mở trong lúc tải: giữ màn hình sáng (Wake Lock như trang Đọc Kinh, nếu trình duyệt hỗ trợ) + dòng nhắc "Để trang này mở cho tới khi tải xong". Đóng / tải lại trang → hàng đợi mất (file đã xong vẫn còn trong máy).
- **D6 "Đã đăng".** Zip vẫn tick "Đã đăng" phía server như CP8.31 D1 khi request tới (tải lại cùng zip tick lại cùng file — không đổi kết quả).
- **D7 "Xong" = server gửi xong.** `done` nghĩa là server đã đẩy hết byte vào mạng, không phải điện thoại đã ghi xong file; với 1–3 file cùng lúc thì sai lệch chỉ là vài giây cuối. Trình quản lý tải của điện thoại tự gửi lại request (cùng URL, cùng token) → token tính theo request mới nhất. mp4 (`FileResponse`) có hỗ trợ Range: nếu trình quản lý tải tự tải tiếp bằng Range, `done` = đã gửi tới byte cuối của file, `bytes_total` = kích thước file.

## Amendment A1 (2026-10-17, HUMAN LEAD APPROVED)

Manual test trên điện thoại: tải 4 bản dọc (cùng lúc 2) → 2 file đầu "xong", 2 file sau đã tải xong trên máy nhưng trang vẫn "đang tải". ORCHESTRATOR dựng lại trên uvicorn thật (FastAPI + `@app.middleware("http")` + `TrackedResponse(FileResponse)`), thấy:

- Client ngắt giữa chừng → token vẫn `done` với đủ byte: uvicorn `send` lặng lẽ bỏ qua sau khi mất kết nối (không raise), `FileResponse` không nghe `http.disconnect` → đọc hết file "gửi vào hư không". Test hiện có giả lập `send` raise nên không bắt được.
- Nghi vấn treo: Chrome Android tải file lớn bằng nhiều request song song (Range từng khúc, cùng URL → cùng token). Theo D7 cũ token chỉ theo request tới sau cùng; nếu đó là một khúc giữa có giới hạn cuối thì nó xong mà không tới byte cuối → `sending` mãi.

Thay đổi (thay D7 câu "token tính theo request mới nhất"; phần còn lại của D3/D7 giữ):

- **A1a Phát hiện ngắt thật.** `TrackedResponse` nghe `receive()` song song; `http.disconnect` khi chưa gửi xong → huỷ response, chỉ tính byte đã gửi trước đó. Nếu disconnect tới lúc chunk cuối đang gửi (middleware báo disconnect sau khi response xong) → vẫn là gửi xong, không phải `aborted`.
- **A1b Gộp mọi request cùng token.** Mỗi token giữ các khoảng byte đã gửi (gộp lại) + số request đang chạy. `bytes_total` = kích thước file (từ `Content-Range` / `Content-Length`); `bytes_sent` = số byte đã phủ. `done` khi các khoảng phủ hết `[0, bytes_total)` (request còn lại có thể còn chạy). `aborted` khi không còn request nào chạy và chưa phủ hết, và request cuối kết thúc bằng ngắt / lỗi. Còn lại = `sending`. Không biết `bytes_total` (zip stream) → như cũ: một request gửi xong chunk cuối = `done`. Request mới tới sau khi `aborted` (trình quản lý tải tự thử lại) → về lại `sending`.
- **A1c Trang.** Mỗi lần hỏi `/api/downloads/{token}` có hạn 10 s (AbortController); một lần hỏi treo / lỗi không chặn vòng hỏi của các file khác hay lần hỏi sau (không để `Promise.all` của một lượt giữ cả hàng đợi).
- **A1d Log.** Mỗi request tải có `dl` khi kết thúc ghi một dòng INFO: token (6 ký tự đầu), route / tên file, Range (nếu có), byte đã gửi, kết quả (`done` / `partial` / `aborted`), trạng thái token sau đó.

AC bổ sung:

8. Trên uvicorn thật (test chạy server thật hoặc giả lập `send` không raise + `receive` trả `http.disconnect`): ngắt giữa chừng → `aborted`, byte < tổng; tải trọn → `done`.
9. Nhiều request Range cùng token, tới theo thứ tự bất kỳ (gồm khúc giữa có giới hạn cuối tới sau cùng), phủ hết file → `done`; thiếu một khúc và không còn request chạy → `aborted`.
10. Một lần hỏi trạng thái treo không làm hàng đợi đứng (test hàm thuần / JS nếu tách được).

## Amendment A2 (2026-10-18, HUMAN LEAD APPROVED: "thực thi cách 2")

Manual test: màn hình điện thoại vẫn tự tắt khi hàng đợi chạy. Nguyên nhân: Wake Lock API chỉ có trong secure context (HTTPS / `localhost`); 8080 mở bằng `http://10.8.102.102:8080` → `navigator.wakeLock` không có, trang im lặng bỏ qua. Màn hình tắt → Chrome đóng băng trang → hàng đợi không bắt đầu file mới (file đang tải vẫn tải trong trình quản lý tải). HUMAN LEAD đã bật cờ Chrome `unsafely-treat-insecure-origin-as-secure` cho địa chỉ 8080 (cách tạm, phải sửa khi IP đổi).

- **A2a Dự phòng giữ màn hình.** Không có Wake Lock (hoặc `request` lỗi) → khi hàng đợi chạy, trang phát một video rất nhỏ (file tĩnh mới, vài KB, H.264, không tiếng, vài giây, `muted` `loop` `playsinline`, đặt hiển thị nhỏ trong khung "Tải lần lượt" — không `display:none`), bắt đầu từ cú bấm "Tải lần lượt" / "Tiếp tục" (cần cử chỉ người dùng để `play()`); dừng khi hàng đợi hết việc. Trang quay lại (visibilitychange) → thử lại Wake Lock hoặc `play()`.
- **A2b Cảnh báo.** Khi không có Wake Lock, khung "Tải lần lượt" hiện dòng cảnh báo rõ: trang không phải HTTPS nên trình duyệt có thể không giữ màn hình sáng; đang thử cách dự phòng; nếu màn hình vẫn tắt thì chỉnh thời gian tắt màn hình của máy hoặc bật lại màn hình để hàng đợi chạy tiếp. Khi có Wake Lock, không hiện.
- Không đổi server, không đổi trang Đọc Kinh (cùng vấn đề, ghi Known limitation / follow-up). HTTPS cho 8080: out of scope (task riêng).

AC bổ sung:

11. Không có `navigator.wakeLock` → hàng đợi chạy thì video dự phòng phát (`muted`, `loop`, `playsinline`), hết việc thì dừng; có Wake Lock → không dùng video. (Test hàm thuần / kiểm tra trang tĩnh; hiệu quả thật kiểm bằng manual test điện thoại.)
12. Cảnh báo A2b hiện đúng khi không có Wake Lock.

Manual test bổ sung: tắt cờ Chrome, chạy hàng đợi, để yên điện thoại quá thời gian tắt màn hình → màn hình còn sáng (nếu không: ghi kết quả, giữ cảnh báo).

## Scope

- In scope: D1–D7; module nhỏ `web/downloads.py` (bảng token, bọc stream đếm byte cho `FileResponse` / `StreamingResponse`); route `GET /api/downloads/{token}`; tham số `dl` ở các route tải zip / bản dọc / bản ngang HD; UI trang bộ kinh; pointer trong CP8.3 web contract; README dòng ngắn.
- Out of scope: tải tiếp phần dở (HTTP Range); hàng đợi tải ở trang tập / trang Yêu thích / tab khác; hàng đợi sống qua đóng trang; giới hạn băng thông phía server; tải Short lẻ, bài đăng `.docx`.

## Acceptance Criteria

1. Chọn n tập, cùng lúc k (1–3): không lúc nào có quá k file `sending`; file sau chỉ bắt đầu khi một file trước `done` / lỗi.
2. `?dl=<token>`: state `sending` → `done` khi gửi hết; client ngắt giữa chừng → `aborted`; token lạ → 404; không cookie → 401. Không có `dl` → byte gửi đi giống hệt trước (zip / mp4).
3. Lỗi → tự thử lại đúng 2 lần rồi báo lỗi + "Thử lại"; các file khác vẫn tiếp tục.
4. Loại không có ở một tập (vd chưa có bản dọc) → bỏ qua, ghi rõ trong bảng.
5. "Dừng" / "Tiếp tục" đúng D5; số cùng lúc nhớ qua lần mở trang sau.
6. Zip qua hàng đợi vẫn tick "Đã đăng" như tải bằng nút thường.
7. Toàn bộ suite PASS; route tải cũ không đổi hành vi.

## Required verification

- `python -m pytest -q -n auto` — PASS (test mới `tests/test_web_downloads*.py` cho AC 1–7; phần JS kiểm logic hàng đợi qua test API + một test hàm thuần nếu tách được).
- `node scripts/framework-check.mjs` — PASS.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API (route mới + tham số mới ở route tải, cùng auth); không chạm database, security model. Manual test trên điện thoại (8080 ghim commit nhánh) là gate trước integration.

- [x] Trên điện thoại: chọn 6 tập zip, cùng lúc 2 → luôn chỉ 2 file đang tải, đủ 6 file, mở được.
- [x] Tắt Wi-Fi giữa chừng một file → tự thử lại, rồi báo lỗi nếu vẫn mất mạng; bật lại → "Thử lại" được.
- [x] Bản dọc cả tập (file lớn) qua hàng đợi, cùng lúc 1.
- [x] A1: 4 bản dọc, cùng lúc 2 → đều xong. A2: giữ màn hình (trang http).

HUMAN LEAD 2026-10-18: "CP8.34 đã ổn" (manual test trên điện thoại qua 8080 ghim `7164e15`).

## Result

- Main changes: `web/downloads.py` (bảng token trong bộ nhớ, TTL 6 h, `TrackedResponse` bọc ASGI `send` đếm byte, bỏ `pathsend` khi có `dl`, request mới cùng token thay request cũ); tham số `dl` ở `/files/{id}/{shorts.zip,all.zip,<clip>.mp4}`, `/api/episodes/{id}/vertical`, `/api/episodes/{id}/source-hd` (không `dl` hoặc token sai định dạng: không đổi); route `GET /api/downloads/{token}`; route trả lỗi có `dl` hợp lệ → token `aborted`. UI: `static/dlqueue.js` (máy trạng thái thuần), khối "Tải lần lượt" + ô tick từng tập trong `playlist.html` / `app.js` / `style.css`; Wake Lock, ghi chú Chrome, `localStorage` `autoShort.dlConcurrency`. Pointer CP8.3 web contract + dòng README. Thêm mục `## Goal` vào contract (framework-check yêu cầu).
- Tests: `tests/test_web_downloads_cp834.py` (17: AC2, AC6, D6, D7 Range, ngắt kết nối bằng ASGI thật, bytes giống hệt khi không `dl`, API bộ kinh), `tests/test_dlqueue_cp834.py` (5, chạy `dlqueue.js` bằng Node: AC1, AC3, AC4, AC5). Suite đầy đủ: 1878 passed, 1 skipped. `node scripts/framework-check.mjs`: PASS.
- Review: ORCHESTRATOR 2026-10-17 ACCEPTED — đọc diff server (`downloads.py`, `_tracked`, route `/api/downloads`) + client (`dlqueue.js`, `app.js`, `playlist.html`); chạy lại `pytest -q -n auto` (1878 passed, 1 skipped) + `framework-check` PASS. Chấp nhận 2 điểm ngoài chữ contract: lỗi 4xx có `dl` → `aborted` ngay (đúng tinh thần D3/D4); hộp xác nhận `beforeunload` khi hàng đợi còn chạy (hỗ trợ D5, HUMAN LEAD có thể bỏ). Còn chờ manual test điện thoại.
- Review A1: ORCHESTRATOR 2026-10-17 ACCEPTED — đọc `downloads.py` (watcher `receive`, khoảng byte gộp, `end` / `state`) + `app.js` / `dlqueue.js` (poll độc lập, 10 s); chạy lại `pytest -q -n auto` (1887 passed, 1 skipped) + `framework-check` PASS. Sửa 3 test cũ theo luật A1b: chấp nhận. Điểm treo còn lại: một khúc kết thúc bình thường mà còn lỗ và không còn request nào chạy → `sending` mãi (trang không có hạn sau khi đã thấy request); quyết sau khi có log thật từ điện thoại (A1d).
- Review A2: ORCHESTRATOR 2026-10-18 ACCEPTED — đọc `app.js` (`dqKeepAwake`, `dqVideo`), `dlqueue.js` (`keepAwakeMode`), `playlist.html`, `keepawake.mp4` (1,7 KB); chạy lại `pytest -q -n auto` (1889 passed, 1 skipped) + `framework-check` PASS. Hiệu quả giữ màn hình thật: chờ manual test điện thoại (tắt cờ Chrome).
- Important findings / decisions: lớp UI trong `app.js` (DOM, fetch, Wake Lock, thẻ `<a download>`) chưa có test tự động — chỉ kiểm cú pháp (`node --check`) và manual test; phần logic hàng đợi nằm ở `dlqueue.js` có test.
- Known limitations: file đang `sending` mà mạng treo (không `aborted`) thì hàng đợi chờ tới khi TCP ngắt; "xong" = server gửi xong (D7); tải lại luôn từ đầu (không Range); hàng đợi mất khi đóng / tải lại trang.
- Amendment A1: `TrackedResponse` nghe `receive()` song song (anyio task group) và huỷ response khi `http.disconnect` tới trước chunk cuối (cờ `final` đặt trước `await send(final)` nên disconnect do middleware báo sau khi xong không bị tính là abort); bảng token gộp khoảng byte của mọi request cùng token + số request đang chạy + cách kết thúc request cuối (`merge_interval`, `DownloadTable.begin/set_total/add_bytes/end/fail`); tổng không biết (zip) giữ luật một request. Một khúc Range kết thúc bình thường mà còn lỗ hổng, không còn request chạy → vẫn `sending` (chỉ `aborted` khi request cuối kết thúc bằng ngắt / lỗi, đúng chữ A1b). Log INFO `web: tải [token6…] <path> range=… đã gửi a/b byte -> done|partial|aborted (token: …)` ở logger `auto_short`. Trang: mỗi lần hỏi trạng thái có AbortController 10 s, `pollTargets/pollDone` trong `dlqueue.js` (mỗi item độc lập, không còn `Promise.all`). Test A1: `test_web_downloads_cp834.py` (silent-drop ASGI, disconnect cùng chunk cuối, Range mọi thứ tự, thiếu khúc → aborted → hồi phục, uvicorn thật trong thread, log), `test_dlqueue_cp834.py` (poll độc lập). Suite: 1887 passed, 1 skipped; framework-check PASS.
- Amendment A2: dự phòng giữ màn hình khi không có Wake Lock (trang http). `static/keepawake.mp4` (1,7 KB) tạo bằng `ffmpeg -y -f lavfi -i color=c=0x020202:s=64x64:r=5 -t 3 -c:v libx264 -profile:v baseline -pix_fmt yuv420p -an -movflags +faststart keepawake.mp4`; `<video id="dq-awake" muted loop playsinline>` nhỏ (48 px) hiển thị khi hàng đợi chạy, `play()` gọi đồng bộ trong click "Tải lần lượt" / "Tiếp tục" (dqTick), dừng khi hết việc, thử lại khi trang hiện lại; chọn cách bằng hàm thuần `DownloadQueue.keepAwakeMode` (wakelock / video / none; `request` lỗi → video); cảnh báo `#dq-awake-warn` (A2b) hiện khi không có Wake Lock hoặc `play()` bị từ chối. Không đổi server, không đổi trang Đọc Kinh. Suite: 1889 passed, 1 skipped; framework-check PASS.
- Known limitation (A2): trang Đọc Kinh có cùng vấn đề Wake Lock trên http (follow-up); HTTPS cho 8080 là task riêng; hiệu quả thật của video dự phòng chỉ kiểm bằng manual test điện thoại.
- Log thật từ điện thoại (A1d, 2026-10-18): Chrome Android tải mỗi bản dọc bằng 3 request song song (`range=-`, `bytes=⅓-`, `bytes=⅔-`, mở cuối), huỷ từng khúc khi chạm khúc sau và có lúc mở lại khúc → đúng nghi vấn A1; gộp khoảng byte cho `done` đúng. Có lúc token `aborted` thoáng qua giữa hai request khúc (không còn request nào chạy trong tích tắc) → trang thử lại bằng token mới, tải trùng cùng file (follow-up nhỏ: chờ vài giây trước khi coi `aborted` là lỗi).
- PR:
