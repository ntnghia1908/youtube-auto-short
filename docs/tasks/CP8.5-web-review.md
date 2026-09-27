# Task: CP8.5 — Web Review Workflow (tên file, xóa, đã đăng)

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `ecb6ed8` (`feature/cp8.3-web`, CP8–CP8.3 READY) / `feature/cp8.5-web-review` (worktree riêng; server đang chạy từ worktree CP8.3 không bị đổi code)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-27: P1 `S01`; P2 giữ khoảng trắng (sau khi ORCHESTRATOR giải thích không ảnh hưởng link tải); P3 xóa mềm — file mp4 xóa ngay để tiết kiệm bộ nhớ, giữ bản ghi để khôi phục, không cần hẹn giờ 7 ngày; P4 gộp chung PR với CP8–CP8.3; đồng ý xóa thử workspace `rbjfcffq3dk-7271326dbe93`)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: (a) mở rộng `review.json` v1 (CP8.2, canonical owner `docs/decisions/CP8.2-title-override-contract.md`) với clip bị xóa và đổi rule render (CP7 R2: clip `rejected` không render); (b) tạo state người dùng mới `publish.json`; (c) thao tác xóa không hoàn tác được (xóa cả tập); (d) đổi API/UI web (CP8.3 record). Yêu cầu HUMAN LEAD 2026-09-27 sau manual test CP8.3 (workflow: nghe → sửa title nếu muốn → tải về điện thoại → tự upload YouTube). Không thêm dependency.

## Goal

Trên web: file tải về có tên dễ đọc `Tập29_S3_<title>.mp4`; người dùng xóa được một Short (có khôi phục) hoặc cả tập; tick "Đã đăng" từng Short để biết Short nào đã lên YouTube.

## Scope

- In scope:
  - Tên file tải về + tên trong zip (X1).
  - Xóa / khôi phục một Short (X2); xóa cả tập (X3).
  - Tick "Đã đăng" (X4) + bộ lọc / đếm trên trang tập và danh sách tập.
  - Module: hàm thuần trong `src/auto_short/review/` (reject/restore, publish) — web gọi; render áp `rejected`.
  - Tests + chạy thật qua web (`curl`) + HUMAN LEAD thử trên điện thoại.
  - Docs: CP8.2 record (`review.json` thêm `rejected`), CP7 record (R2 `skip_reason: "rejected"`), CP8.3 record (API/UI/tên file/xóa tập), decision record mới cho `publish.json` hoặc gộp vào CP8.3 record (X4), README, contract Result.
- Out of scope:
  - Upload YouTube tự động (CP8.4); CLI cho xóa/đã đăng (web-only ở CP8.5); approve/reject kiểu CP9 đầy đủ, batch.
  - Clip ngắn định dạng khác (backlog roadmap).

## Authority / key decisions

- `docs/decisions/CP8.2-title-override-contract.md` (T1 `review.json`, T3 khóa `(clip_id, candidate_id)`, T5 cache + commit), `docs/decisions/CP7-render-contract.md` R2/R8/R11, `docs/decisions/CP8.3-web-contract.md` W2 (chỉ phục vụ file trong `shorts/`), W5 (job, 409), W7; CP6 `titles.json.header.fields.episode` (vd `"29"`).
- Quyết định (DECIDE cùng APPROVE TASK):
  - **X1 Tên file tải về:** `Tập<episode>_S<n>_<title>.mp4` — `<episode>` = `titles.json.header.fields.episode` (không có → `<episode_id>`); `<n>` = số thứ tự clip trong `clips.json` (hai chữ số: k03 → `S03`, k12 → `S12`; ≥ 100 clip → ba chữ số; **giữ nguyên** khi Short khác bị xóa) (P1); `<title>` = title đang có trong file (theo `render_manifest.json`), NFC, giữ dấu tiếng Việt, bỏ ký tự cấm trên Windows/Android/iOS `/ \ : * ? " < > |` và ký tự điều khiển, gộp khoảng trắng liên tiếp thành một, **giữ khoảng trắng** (P2), cắt ≤ 150 byte UTF-8 ở ranh giới từ. `Content-Disposition` có `filename*=UTF-8''…` (RFC 5987) + `filename=` ASCII bỏ dấu làm dự phòng. Zip: `Tập29_Shorts.zip`, các entry cùng quy tắc, cờ UTF-8. File trên đĩa không đổi tên (`shorts/k03.mp4`, CP7).
  - **X2 Xóa một Short (xóa mềm, khôi phục được — P3; mục đích tiết kiệm bộ nhớ: file mp4 bị xóa khỏi đĩa ngay ở bước commit của job render, chỉ giữ bản ghi):** `review.json` thêm `"rejected": [{"clip_id", "candidate_id"}]` (additive, v1; khóa T3). Render: clip rejected → `status: "skipped"`, `skip_reason: "rejected"`, không file; file cũ bị xóa ở bước commit (T5). Web: nút Xóa (hỏi xác nhận) → ghi `review.json` → job render (các Short khác reuse, vài giây). Short đã xóa ẩn khỏi lưới và zip; nút "Hiện Short đã xóa (n)" → "Khôi phục" → job render encode lại Short đó (≈ 16–40 s, byte-identical bản trước khi xóa nếu title không đổi). Xóa Short có title tay: giữ override (khôi phục ra đúng title đó). Áp 409 như sửa title (W5).
  - **X3 Xóa cả tập (không hoàn tác):** nút trên trang tập, hộp xác nhận ghi rõ tên tập + "không khôi phục được"; từ chối (409) khi có job của tập đang chạy/chờ. Xóa `work/<id>/` (gồm video nguồn đã tải) và `output/<id>/`. Nguồn local nằm ngoài workspace **không bao giờ bị xóa** (CP2 D4). Gửi lại URL sau đó = chạy lại từ đầu (~25 min; AI có thể chọn clip/title khác).
  - **X4 Đã đăng:** file `work/<id>/publish.json` (state người dùng, **không** là input pipeline — tick không làm render stale): `{"schema_version": 1, "episode_id": "…", "published": [{"clip_id", "candidate_id", "sha256": "<sha256 file lúc tick>", "at": "<UTC ISO-8601>"}]}`, ghi atomic. UI: checkbox "Đã đăng" trên mỗi Short (tick/bỏ tick, không cần job, được phép cả khi job đang chạy); Short đã tick mà file hiện tại khác `sha256` (vd sửa title sau khi đăng) → nhãn "đã đăng bản cũ". Trang tập: bộ lọc Tất cả / Chưa đăng / Đã đăng; danh sách tập: "đã đăng x/y". Short bị xóa vẫn giữ trạng thái tick (hiện khi xem Short đã xóa).
- Đã chốt (HUMAN LEAD 2026-09-27): P1 `S01` (hai chữ số); P2 giữ khoảng trắng; P3 xóa mềm, file xóa ngay, không hẹn giờ; P4 gộp CP8.5 vào cùng PR với CP8–CP8.3.
- Ghi nhận cho sau (không trong CP8.5): video nguồn ≈ 700 MB/tập là phần tốn bộ nhớ chính; "dọn video nguồn nhưng giữ Short" có thể là task sau (sửa title/khôi phục khi đó cần tải lại nguồn).

## Implementation approach

- `review/`: `reject_clip`, `restore_clip`, `set_published`, `load_published`, `download_name(…)` (thuần, test được); render đọc `rejected` qua `resolve_titles`/tương đương CP8.2.
- `web/`: route mới `POST …/shorts/{clip}/delete|restore`, `POST …/shorts/{clip}/published {value}`, `DELETE /api/episodes/{id}`; tên file ở route tải + zip; UI checkbox, nút xóa/khôi phục, bộ lọc, xóa tập.
- Xóa tập: dùng đường dẫn từ config + `episode_id` đã validate; kiểm path nằm trong `workspace.dir`/`output_dir` trước khi `rmtree`.

## Acceptance Criteria

1. Tải một Short → tên `Tập29_S03_<title>.mp4` (vd `Tập29_S01_Đánh mắng trẻ là có tội không.mp4`), đúng dấu tiếng Việt trên Android/iOS/desktop; zip `Tập29_Shorts.zip` với entry cùng quy tắc; title có `?`/`"` bị bỏ ký tự đó.
2. Xóa `S05` của tập 29: job render ≤ vài giây, 19 Short khác reuse (sha256 không đổi), `k05.mp4` không còn, `render_manifest` `skipped`/`rejected`, zip 19 entry; khôi phục → `k05.mp4` byte-identical bản trước khi xóa.
3. Tick "Đã đăng" 2 Short → còn sau khi reload + restart server; bộ lọc + đếm đúng; sửa title một Short đã tick → nhãn "đã đăng bản cũ"; tick không tạo job, không làm render stale.
4. Xóa cả tập (thử trên workspace cũ `rbjfcffq3dk-7271326dbe93` — chỉ ingest từ CP2, nguồn local): thư mục workspace/output bị xóa, file `input/rbjfCfFq3Dk/rbjfCfFq3Dk.mp4` **còn nguyên**; tập biến mất khỏi danh sách; 409 khi có job; `episode_id` lạ/traversal → 404.
5. Test cũ + mới PASS; framework-check PASS; docs cập nhật.

## Required verification

- `pytest -q` — AC1–AC5 (logic tên file, reject/restore, publish, xóa tập, route).
- Chạy thật qua `curl` LAN trên tập 29 + workspace cũ — AC1–AC4.
- HUMAN LEAD tải một Short về điện thoại, xem tên file; thử xóa/khôi phục, tick — AC1–AC3 (manual gate: có thao tác xóa không hoàn tác).
- `node scripts/framework-check.mjs` — AC5.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm web đã có auth (không đổi security model) nhưng thêm thao tác xóa không hoàn tác → manual test là gate.

- [ ] Tải Short về điện thoại: tên file đúng mẫu, đọc được.
- [ ] Xóa một Short, khôi phục lại.
- [ ] Tick "Đã đăng", lọc "Chưa đăng".

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
