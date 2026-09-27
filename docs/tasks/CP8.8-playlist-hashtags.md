# Task: CP8.8 — Hashtag riêng cho từng bộ kinh (Web)

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: single-agent
- Base commit / branch: `eab3134` (`main`, sau merge PR #10) / `feature/cp8.8-playlist-hashtags`
- Human Lead approval: accepted (HUMAN LEAD 2026-09-27: APPROVE TASK, H1–H7, P1–P3 theo đề xuất)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm trường vào state đã có contract (`_playlists/<id>.json`, CP8.3 W10 L1); thêm endpoint HTTP API (W7); đổi rule tính `copy_text` (W6, bổ sung B của CP8.7). Không thêm dependency, không chạm security model (dùng auth hiện có), không vào hash stage nào, không render lại.

Nguồn: backlog HUMAN LEAD 2026-09-27 (`AUTO_SHORT_CHECKPOINT_PLAN.md` § Backlog); code dở chưa review ở nhánh local `wip/playlist-hashtags` (`fced010`) — được dùng làm điểm xuất phát, review lại từng dòng, không merge thẳng nhánh WIP.

## Goal

Trên trang bộ kinh, người dùng sửa danh sách hashtag (thêm / bỏ / đổi thứ tự) dùng khi bấm "Copy" tiêu đề cho mọi Short của các tập thuộc bộ kinh đó, xem trước chuỗi copy (≤ 100 ký tự), lưu, hoặc khôi phục mặc định. Tập lẻ và bộ kinh chưa sửa giữ nguyên hành vi hiện tại (`#<series>` + `[web] hashtags`).

## Scope

- In scope:
  - Lưu danh sách hashtag riêng trong file bộ kinh (H1), ngữ nghĩa danh sách (H2), kiểm tra (H3), tập thuộc nhiều bộ kinh (H4), vòng đời khi cập nhật / xóa bộ kinh (H5).
  - API (H6): `hashtags` + `hashtags_custom` trong `GET /api/playlists/{id}`; `PUT` / `DELETE /api/playlists/{id}/hashtags`; `POST /api/playlists/{id}/hashtags/preview`.
  - `copy_text` / `hashtags` của Short trong `GET /api/episodes/{id}` dùng danh sách riêng khi tập thuộc bộ kinh có danh sách riêng.
  - UI trang bộ kinh (H7): khung thu gọn "Hashtag khi Copy tiêu đề (mặc định | riêng bộ kinh này)": từng hashtag một dòng với ↑ ↓ ✕, ô thêm (hiện dạng sẽ lưu), xem trước, "Lưu", "Khôi phục mặc định"; bố cục ≤ 640 px như CP8.7 C.
  - Docs: CP8.3 record (W6, W7, W10 L1, Config `[web]` ghi chú), README (nếu có mô tả hashtag), plan (bỏ mục backlog, thêm CP8.8), `docs/workflow/current-state.md`, contract Result.
  - Tests + chạy thật trên scratch (không đụng `work/` / `output/` của web đang chạy).
- Out of scope:
  - Sửa hashtag cho từng tập lẻ / từng Short; sửa `[web] hashtags` qua web (vẫn là config).
  - Hashtag trong mô tả video, upload YouTube (CP8.4).
  - Đổi title, tên file tải về, render, `publish.json` / trạng thái "Xong" (không Short nào bị render lại hay mất tick).
  - Xóa nhánh `wip/playlist-hashtags` (HUMAN LEAD quyết sau merge).

## Authority / key decisions

- `docs/decisions/CP8.3-web-contract.md` W6 (Copy + hashtag, bổ sung B CP8.7), W7 (API), W10 L1 (file bộ kinh), Config `[web]`; `auto_short.review.names.hashtag` / `copy_text` (chuẩn hóa NFC chữ/số, bỏ trùng, ≤ 100 ký tự, không cắt title).
- Quyết định (DECIDE cùng APPROVE TASK):
  - **H1 Lưu:** trường tùy chọn `"hashtags": ["ThậpThiện", "TịnhĐộTông"]` (đã chuẩn hóa, không có `#`, đúng thứ tự) trong `_playlists/<playlist_id>.json`, sau `entries`; không có trường = mặc định. Ghi atomic dưới lock của `PlaylistStore`. `schema_version` giữ 1 (thêm trường tùy chọn, bản cũ đọc được).
  - **H2 Ngữ nghĩa (P1):** danh sách riêng là **danh sách đầy đủ** thay cho cả `#<series>` lẫn `[web] hashtags` (người dùng thấy và sửa được cả hashtag tên bộ kinh). Khi mở lần đầu, khung sửa điền sẵn danh sách mặc định đang áp dụng (`#<series>` của tập đầu tiên đã xử lý + `[web] hashtags`). Danh sách riêng rỗng = không hashtag nào (khác "Khôi phục mặc định"). Phương án khác: luôn tự thêm `#<series>` đứng đầu, danh sách riêng chỉ thay `[web] hashtags`.
  - **H3 Kiểm tra (P2):** mỗi mục chuẩn hóa bằng `hashtag()` (NFC, chỉ chữ/số, bỏ `#` / khoảng trắng / dấu câu); rỗng sau chuẩn hóa, trùng (không phân biệt hoa thường) hoặc > 15 mục → 422, không ghi. Giới hạn 15 là giới hạn UI (YouTube bỏ qua mọi hashtag khi > 60; chuỗi copy vốn chỉ chứa được vài hashtag vì ≤ 100 ký tự). Quá 100 ký tự vẫn theo rule cũ: bỏ hashtag từ cuối, không cắt title; xem trước ghi rõ hashtag nào bị bỏ.
  - **H4 Tập thuộc nhiều bộ kinh (P3):** dùng danh sách riêng của bộ kinh đầu tiên theo `playlist_id` (thứ tự chữ) có chứa tập và có danh sách riêng; không bộ nào có → mặc định. Tất định, không cần state thêm. Phương án khác: bộ kinh được lưu hashtag gần nhất.
  - **H5 Vòng đời:** "Cập nhật danh sách" giữ nguyên `hashtags`; "Xóa bộ kinh" xóa luôn danh sách (tập về mục "Tập lẻ" → mặc định). Đổi hashtag có hiệu lực ngay cho mọi Short (kể cả đã đăng) vì `copy_text` tính lúc xem; không đổi file, không đổi tick.
  - **H6 API:** `PUT /api/playlists/{id}/hashtags` body `{"hashtags": [str, …]}` (≤ 100 phần tử ở schema, H3 kiểm tiếp) → 200 `{"playlist_id", "hashtags": ["#…"], "hashtags_custom": true}` / 404 / 422; `DELETE` cùng path → xóa trường, trả danh sách mặc định (`hashtags_custom: false`); `POST …/hashtags/preview` cùng body, không ghi → `{"hashtags", "title", "title_is_real", "copy_text", "chars", "max_chars", "dropped"}`, title = title dài nhất trong file Short `rendered` của các tập trong bộ kinh, không có → câu mẫu 60 ký tự. Cần đăng nhập như mọi API; không tạo job, được gọi khi đang có job chạy.
  - **H7 UI:** như Scope; khung sửa không bị poll 5 s ghi đè khi người dùng đang sửa; JS chuẩn hóa để hiển thị, server kiểm lại.

## Implementation approach

- Checkout các file từ `wip/playlist-hashtags` lên nhánh này, review từng hunk theo H1–H7 (sửa lệch nếu HUMAN LEAD chọn khác ở P1–P3), bổ sung test còn thiếu (H5 xóa bộ kinh, JSON body sai kiểu, lock/atomic), rồi docs.
- `episodes.episode_view(..., hashtags=)` nhận danh sách riêng từ `PlaylistStore.hashtags_for(video_id)`; đường mặc định không đổi.

## Acceptance Criteria

1. Bộ kinh chưa sửa và tập lẻ: `copy_text` / `hashtags` giống hệt trước (test CP8.7 cũ vẫn pass).
2. `PUT` hợp lệ ghi `hashtags` chuẩn hóa vào file bộ kinh; Short của mọi tập trong bộ kinh trả `copy_text` = `<title> <danh sách riêng>` (≤ 100 ký tự, không cắt title).
3. Rỗng sau chuẩn hóa / trùng / > 15 / sai kiểu → 422, file không đổi; bộ kinh không tồn tại → 404; chưa đăng nhập → 401.
4. `DELETE` khôi phục mặc định; danh sách rỗng `[]` cho `copy_text` = title.
5. "Cập nhật danh sách" giữ `hashtags`; "Xóa bộ kinh" → tập dùng lại mặc định.
6. Tập thuộc hai bộ kinh có danh sách riêng → dùng bộ có `playlist_id` nhỏ hơn (H4).
7. Preview trả đúng title dài nhất / câu mẫu, `chars`, `dropped`; không ghi file.
8. Không file nào trong `work/<id>/`, `output/` bị đổi; không stage nào stale.

## Required verification

- `pytest -q` — toàn bộ, gồm test mới AC1–AC8.
- `node scripts/framework-check.mjs` — PASS.
- Chạy thật trên scratch (config trỏ thư mục tạm, hardlink một tập đã có, cổng khác 8080): PUT / preview / DELETE qua curl, kiểm `copy_text` và sha256 thư mục chính không đổi.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API contract (endpoint mới) — manual test là gate trước integration. Không chạm database, không đổi security model.

- [ ] Trang bộ kinh (máy tính + điện thoại): mở khung hashtag, thấy danh sách mặc định; thêm / bỏ / đổi thứ tự; xem trước cập nhật; Lưu → trạng thái "riêng bộ kinh này".
- [ ] Trang tập thuộc bộ kinh: dòng hashtag và nút Copy dùng danh sách mới; tập lẻ không đổi.
- [ ] "Khôi phục mặc định" → trở lại như cũ; "Cập nhật danh sách" không làm mất danh sách riêng.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
