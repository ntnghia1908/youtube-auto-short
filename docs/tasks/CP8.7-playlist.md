# Task: CP8.7 — Playlist (Bộ kinh) trên Web

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `e430b58` (`feature/cp8.6-storage`, implement xong + review, stacked) / `feature/cp8.7-playlist`
- Human Lead approval: accepted (HUMAN LEAD 2026-09-27: "Xong" tự động khi đăng hết (sửa P2); P1, P3, P4 theo đề xuất)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: kéo một phần "batch" của CP9 lên (re-plan HUMAN LEAD 2026-09-27); đổi rule input web CP8.3 W3 (trước đây từ chối playlist); tạo state mới (danh sách bộ kinh, cờ "xong tập"); thêm gọi mạng tới YouTube để liệt kê playlist. Không thêm dependency (`yt-dlp` đã có, CP1 §10).

## Goal

Người dùng dán URL playlist (một bộ kinh) → web liệt kê mọi tập **chưa tải, chưa render**. Muốn làm tập nào thì bấm tập đó → pipeline chạy. Đăng hết Short thì tập tự thành "Xong". Theo dõi 1–2 bộ kinh trong thời gian dài, không tốn bộ nhớ cho tập chưa làm.

## Scope

- In scope:
  - Nhập playlist (P1): liệt kê bằng `yt-dlp` `extract_flat` (không tải video): id, title, thứ tự trong playlist, thời lượng, số tập (parse `title_pattern` của CP6, vd "tập 1/149" → 1); tập private/đã xóa → "không khả dụng".
  - Trang "Bộ kinh": danh sách bộ kinh trên trang chủ (tên, số tập, đã xử lý x, xong y); trang bộ kinh liệt kê các tập theo thứ tự playlist với trạng thái (chưa xử lý / đang chờ / đang xử lý + stage / xong render n Short, đã đăng a/n / lỗi / đã dọn nguồn / **Xong** (tự động, L4)); nút "Xử lý" từng tập; bấm nhiều tập → xếp hàng lần lượt (W5); nút "Cập nhật danh sách" (lấy lại playlist khi kênh thêm tập mới); nút "Xóa bộ kinh" (chỉ xóa bản ghi danh sách, **không** xóa tập đã xử lý).
  - Trạng thái "Xong" tự động (L4) trên trang bộ kinh, trang tập và danh sách tập lẻ; lọc Tất cả / Chưa xử lý / Đang làm / Xong.
  - Liên kết CP8.6: tập đã tick "Xong" được gợi ý dọn (video nguồn / cả tập) trong tab Bộ nhớ như tập đã đăng hết.
  - Tập lẻ (dán URL video) vẫn như cũ, nằm ở mục "Tập lẻ" trên trang chủ.
  - Tests (yt-dlp giả), chạy thật với playlist 149 tập ở trên (liệt kê, xử lý 1 tập đã có sẵn → skip nhanh, tick xong), HUMAN LEAD thử.
  - Docs: CP8.3 record (W3 nhận playlist, bộ kinh, API, state), README, contract Result; roadmap CP9 (ghi phần batch đã kéo lên).
  - Bổ sung HUMAN LEAD 2026-09-27 ("Nếu bấm tải xuống thì tự tick đã đăng"): tải một Short (`?download=1`, nút "Tải về") tick "Đã đăng" Short đó với `sha256` của file, phía server, trước khi gửi file (idempotent, tải tiếp bằng `Range` không ảnh hưởng); "Tải tất cả" (zip) tick mọi Short trong zip; phát video không tick; bỏ tick vẫn được (chỉ tải lại mới tick lại); tập archived vẫn tick; "Xong" và gợi ý dọn CP8.6 theo đó. Rule: `docs/decisions/CP8.3-web-contract.md` W8.
  - Bổ sung HUMAN LEAD 2026-09-27 (nút Copy tiêu đề): nút "Copy" ngay cạnh tiêu đề mỗi Short trên trang tập, copy đúng title trong file hiện tại (`render_manifest.json` `title`), báo "Đã copy" — vì app YouTube trên điện thoại không lấy title từ tên file / metadata MP4. Site là HTTP thường trong LAN (không secure context): `navigator.clipboard` chỉ khi `window.isSecureContext`, còn lại `<textarea>` tạm + `select()` + `execCommand("copy")` trong lúc bấm; thất bại → hiện ô chứa title đã chọn sẵn để giữ-copy. Không tự copy khi tải. Rule: `docs/decisions/CP8.3-web-contract.md` W6.
  - Bổ sung HUMAN LEAD 2026-09-27 (A — bia mộ tập đã xóa): trước khi `delete_episode` xóa thư mục (xóa tập ở trang tập và nút "Làm" tab Bộ nhớ) ghi `<workspace.dir>/_deleted/<episode_id>.json` (title, source_url, deleted_at, số Short, số đã đăng đúng file, Xong lúc xóa, header series/episode); bộ kinh vẫn đếm tập đó ("✔ Xong (đã xóa dữ liệu)" / "Đã xóa dữ liệu (chưa xong)", nút "Xử lý lại" có xác nhận); tập lẻ đã xóa ở mục thu gọn "Đã xóa (n)" trên trang chủ, "Xóa khỏi lịch sử" chỉ xóa bia mộ. Rule: `docs/decisions/CP8.3-web-contract.md` W8 § Xóa tập, W10.
  - Bổ sung HUMAN LEAD 2026-09-27 (B — hashtag khi copy): nút Copy copy `<title> <hashtags>` — `#<series>` (titles.json `header.fields.series`) + `[web] hashtags` (mặc định `["TịnhKhông", "LờiPhậtDạy", "TịnhĐộ", "NiệmPhật"]`), dạng NFC chỉ giữ chữ/số, bỏ trùng không phân biệt hoa thường, cả chuỗi ≤ 100 ký tự (bỏ hashtag từ cuối, không cắt title); dòng hashtag nhỏ màu xám dưới title; server tính `copy_text`. Rule: W6.
  - Bổ sung HUMAN LEAD 2026-09-27 (C — giao diện điện thoại): tab Bộ nhớ ≤ 640 px hiện mỗi tập thành thẻ (title 2 dòng, nhãn trạng thái, tổng dung lượng nổi bật, dòng "Nguồn · Short · Khác", "Đã đăng x/y", nút hành động rộng hết thẻ), gợi ý dạng thẻ, thanh ổ đĩa rộng hết với số liệu dòng riêng, nút ≥ 40 px, không cuộn ngang; bảng giữ cho màn hình rộng; áp cùng luật cho trang bộ kinh, "Bộ kinh"/"Tập lẻ"/"Đã xóa" trang chủ. Rule: W6.
- Out of scope:
  - Tự động xử lý cả playlist / hẹn giờ (người dùng bấm từng tập — đúng yêu cầu tiết kiệm bộ nhớ).
  - Upload YouTube (CP8.4); playlist không phải YouTube; channel URL (chỉ playlist).

## Authority / key decisions

- `docs/decisions/CP8.3-web-contract.md` W3 (input), W5 (job), W7 (API); `docs/decisions/CP8-pipeline-contract.md` (run, resume); CP6 `title_pattern` (series/episode); CP2 D3 (episode id = video id).
- Dữ kiện đo 2026-09-27: kênh của video test có 415 playlist; liệt kê playlist "Thập Thiện Nghiệp Đạo Kinh [trọn bộ 149 tập] - PS Tịnh Không" (`PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp`) bằng `extract_flat`: 149 tập trong 1.7 s, có id/title/duration; title dạng "Thập Thiện Nghiệp Đạo Kinh tập 1/149 - Pháp Sư Tịnh Không" khớp `title_pattern` hiện tại (series + episode).
- Quyết định (DECIDE cùng APPROVE TASK):
  - **L1 Lưu bộ kinh (P1):** `<workspace.dir>/_playlists/<playlist_id>.json` (tên bắt đầu `_` không thể là episode id CP2 D3): `{"schema_version": 1, "playlist_id", "title", "url", "fetched_at", "entries": [{"index", "video_id", "title", "duration", "episode", "available"}]}`, ghi atomic. "Cập nhật danh sách" thay `entries`. Trạng thái xử lý của từng tập **không** lưu ở đây — đọc từ `work/<video_id>/manifest.json` + job runner (một nguồn sự thật).
  - **L2 URL:** `youtube.com/playlist?list=<id>` → bộ kinh; `watch?v=<id>&list=<id>` → hỏi người dùng "tập lẻ" hay "cả bộ kinh" (UI hai nút); `list` là Mix/radio (`RD…`), "Watch later" (`WL`), "Liked" (`LL`) → từ chối.
  - **L3 Xử lý tập:** nút "Xử lý" = gửi URL `https://youtu.be/<video_id>` như tập lẻ (preflight Ollama, W4/W5, không job trùng). Chặn khi ổ thấp (CP8.6 S4).
  - **L4 Xong tập (P2 — HUMAN LEAD: tự động):** không lưu, **suy ra**: tập Xong ⇔ render `done` và mọi Short đã render, không bị xóa (`rejected`) đều tick "Đã đăng" với `sha256` khớp file hiện tại (Short "đã đăng bản cũ" **chưa** tính); xóa hết Short → Xong. Bỏ tick → hết Xong. Không có nút tick Xong riêng. Áp cho cả tập trong bộ kinh và tập lẻ. Tập Xong → tab Bộ nhớ gợi ý dọn (CP8.6 S2 mục 1, cùng điều kiện "đăng hết").
  - **L5 Hiệu năng:** liệt kê playlist chạy trong request (timeout 60 s, báo lỗi rõ); trang bộ kinh đọc manifest của các tập đã có (≤ vài trăm file nhỏ), cache ≤ 5 s.
- Đã chốt (HUMAN LEAD 2026-09-27):
  - **P1** Lưu bộ kinh như L1 (đề xuất).
  - **P2 — chốt:** tự đánh "Xong" khi đăng hết (L4).
  - **P3** Cho bấm "Xử lý" nhiều tập để xếp hàng (đề xuất có; mỗi tập ≈ 1 GB, cảnh báo ổ CP8.6 vẫn áp dụng).
  - **P4** Push: gộp CP8.7 cùng PR CP8–CP8.6 (đề xuất).

## Acceptance Criteria

1. Dán URL playlist 149 tập → trang bộ kinh liệt kê 149 tập đúng thứ tự, số tập, thời lượng; không tải video nào (không thư mục `work/<id>` mới).
2. Bấm "Xử lý" một tập → job pipeline chạy như tập lẻ, trạng thái cập nhật trên trang bộ kinh; tập đã có (vd tập 29 nếu nằm trong playlist) hiện đúng trạng thái xong + số Short.
3. Tick "Đã đăng" mọi Short còn lại của một tập → tập hiện "Xong" (giữ sau restart); bỏ tick một Short / sửa title một Short đã đăng → hết Xong; bộ lọc đúng; tab Bộ nhớ gợi ý dọn tập Xong.
4. "Cập nhật danh sách" thêm tập mới, giữ thứ tự; "Xóa bộ kinh" không xóa tập đã xử lý; URL Mix/WL → 422; `watch?v&list` → hỏi.
5. Test cũ + mới PASS; framework-check PASS; docs cập nhật.

## Required verification

- `pytest -q` — AC1–AC5 (yt-dlp giả).
- Chạy thật trên bản sao dữ liệu với playlist thật — AC1, AC2 (xử lý một tập đã có → skip), AC3, AC4.
- HUMAN LEAD thử trên web thật (manual gate cùng CP8.5/CP8.6).
- `node scripts/framework-check.mjs` — AC5.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

- [ ] Dán playlist bộ kinh, xem danh sách tập.
- [ ] Bấm xử lý một tập mới, theo dõi tới khi có Short; tick "Đã đăng" hết → tập tự "Xong".

## Result

- Main changes:
  - `web/urls.py`: `classify_url` (L2: playlist / hỏi / video; từ chối `RD…`, `WL`, `LL`, `LM`), `valid_playlist_id`, `playlist_url`.
  - `web/playlists.py` (mới): `ytdlp_list` (`extract_flat`), `build_document` (số tập theo `title_pattern`, tập không khả dụng), `PlaylistStore` (`_playlists/<id>.json`, thêm / cập nhật / xóa, liệt kê trong luồng phụ tối đa 60 s, trạng thái từng tập từ manifest + job, cache 5 s), `disk_status`.
  - `review/publish.py`: `episode_complete` (L4), `mark_downloaded` (tải về = đã đăng), tick idempotent (cùng file → không đổi `at`).
  - `web/app.py`: `POST /api/episodes` nhận `mode` + trả `kind` (video / playlist / ask); `GET /api/playlists`, `GET|DELETE /api/playlists/{pid}`, `POST /api/playlists/{pid}/refresh`, trang `/playlists/{pid}`; tick khi tải (`?download=1`, zip); `in_playlist`; `create_app(playlist_lister=…, playlist_timeout=…)`. `web/episodes.py`: `complete` ở trang tập + danh sách; `publish_group` `done` = Xong. `web/storage.py`: gợi ý mục 1 = Xong; model Whisper hiện đường dẫn tuyệt đối + `exists` (sửa finding CP8.6).
  - UI: form nhận playlist + hộp hỏi, mục "Bộ kinh" / "Tập lẻ" trên trang chủ, trang bộ kinh (bộ lọc, "Xử lý" / "Chạy tiếp", cập nhật, xóa), "✔ Xong" trên trang tập, làm mới sau khi bấm tải.
  - Docs: CP8.3 record W3, W7, W8, W9, W10 + số đo + giới hạn; roadmap CP9 (phần batch kéo lên); README.
- Tests: `pytest -q` 588 passed (mới `tests/test_playlist_cp87.py` 23 với yt-dlp giả: phân loại URL, tài liệu + số tập, nhập không tải video, hỏi / `mode`, 422 Mix/WL/LL, lỗi + quá hạn liệt kê → 502, cập nhật thêm tập giữ thứ tự, xóa bộ kinh giữ tập, xử lý tập → xếp hàng + trạng thái, lỗi job đọc được, predicate Xong, Xong theo tick / restart / bản cũ / gợi ý dọn, tải về tick (một Short, zip, phát không tick, `Range`, bỏ tick, bản cũ → tick lại), tập archived, đường dẫn model; sửa kỳ vọng cũ: gợi ý mục 1 và `publish_group` theo Xong, `caches` thêm `exists`). `node scripts/framework-check.mjs` PASS. Chạy thật với playlist 149 tập trên bản sao scratch: AC1–AC4 đạt (số đo `docs/decisions/CP8.3-web-contract.md` § CP8.7); thư mục chính: 25 sha256 không đổi, không có `publish.json` mới.
- Review: ORCHESTRATOR review ACCEPTED (2026-09-27), không finding chặn; chấp nhận 6 lựa chọn khi implement (Mix kèm video → tập lẻ; thêm playlist đã có không liệt kê lại; Tập lẻ ẩn tập thuộc bộ kinh; tick tải dùng sha256 manifest; tính đã đăng khi server nhận request tải; trạng thái failed của job mất khi restart). Nút Copy (bổ sung HUMAN LEAD) `e4a9b4d`. Chờ manual test HUMAN LEAD.
- Important findings / decisions:
  - `tHtxw6ykUmM` không nằm trong playlist 149 tập (tập 29 ở đó là `nOvMD6aQSt8`, bản 29 phút khác) → AC2 "tập đã có" chạy thật với một bộ kinh giả trong scratch chứa `tHtxw6ykUmM`; không tải tập mới nào.
  - `watch?v=…&list=RD…` (Mix cạnh video) coi là video, không hỏi; `playlist?list=RD…/WL/LL/LM` → 422.
  - Thêm lại playlist đã lưu không liệt kê lại (dùng "Cập nhật danh sách").
  - Mục "Tập lẻ" chỉ hiện tập không thuộc bộ kinh đã lưu nào; bộ lọc danh sách tập (CP8.5) đổi "Đã đăng hết" thành "Xong" (bản cũ không tính).
  - `sha256` tick khi tải = `sha256` trong `render_manifest.json` (không băm lại file mỗi lần tải).
  - Model Whisper (finding CP8.6): giữ đúng ngữ nghĩa stage transcript (tương đối theo thư mục làm việc của server), hiện đường dẫn tuyệt đối + "chưa có thư mục"; server live cần `[transcript.whisper] models_dir` tuyệt đối trong config của nó (vd `/home/ntnghia/youtube-auto-short/models`) — việc cấu hình, không sửa ở CP8.7.
- Bổ sung A/B/C (commit follow-up thứ hai): `review/tombstone.py` (ghi trong `delete_episode`, nên cả DELETE trang tập và nút "Làm" tab Bộ nhớ), trạng thái `deleted` + `action` (`process` / `resume` / `reprocess`) trong bộ kinh, `GET /api/deleted`, `DELETE /api/deleted/{id}`; `review.names.hashtag` / `hashtags` / `copy_text`, `[web] hashtags` (config + `config.example.toml`, ngoài mọi hash), `copy_text` + `hashtags` trong Short; CSS ≤ 640 px + thẻ tab Bộ nhớ, kích thước MB/GB theo 1024 (648 MB = 678 949 583 B). Quyết định: bia mộ bị **bỏ qua** khi có workspace cùng id (xử lý lại không xóa file bia mộ); tập đã xóa chưa Xong thuộc nhóm "Chưa xử lý". Tests: `pytest -q` 600 passed (+10: hashtag, copy_text ≤ 100 + bỏ trùng, `[web] hashtags`, `copy_text` trong view, bia mộ khi xóa qua đường tab Bộ nhớ + trang tập, thống kê bộ kinh + `reprocess` + xác nhận trong JS, bia mộ bị bỏ qua khi xử lý lại, mục "Đã xóa" + "Xóa khỏi lịch sử", markup/CSS responsive); framework-check PASS. Chạy thật (scratch hardlink `tHtxw6ykUmM` trong bộ kinh giả, `127.0.0.1:8081`): `copy_text` 20 Short dài tối đa 100 ký tự (vd `Xã hội hiện nay đúng sai lẫn lộn? #ThậpThiệnNghiệpĐạoKinh #TịnhKhông #LờiPhậtDạy #TịnhĐộ #NiệmPhật`, 98 ký tự; title 55 ký tự giữ 2 hashtag); tải zip → Xong; xóa tập (0,005 s) → `_deleted/tHtxw6ykUmM.json` (20 Short, 20 đã đăng, `complete: true`, series + tập 29); bộ kinh: `deleted` / nhóm `done` / `reprocess`, `processed` 1, `complete` 1, `deleted` 1; xóa bộ kinh → tập hiện ở "Đã xóa" trang chủ; "Xóa khỏi lịch sử" → 200. Thư mục chính: 23 sha256 không đổi, không có `_deleted`/`publish.json` mới. Giao diện điện thoại: kiểm ở manual gate.
- Nút Copy tiêu đề (bổ sung HUMAN LEAD, commit follow-up): kiểm bằng test JS/CSS được phục vụ; hành vi copy trên điện thoại thật (Android Chrome, iOS Safari qua HTTP) kiểm ở manual gate.
- Known limitations: xem `docs/decisions/CP8.3-web-contract.md` § Giới hạn đã biết (CP8.7). Chưa kiểm UI trên trình duyệt thật (manual gate HUMAN LEAD).
- PR: gộp chung PR CP8–CP8.6 (P4); chưa push.
