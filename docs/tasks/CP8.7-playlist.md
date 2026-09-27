# Task: CP8.7 — Playlist (Bộ kinh) trên Web

## Status / Approval

- Status: APPROVED
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
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
