# Task: PKG3.1 — Trang Đóng gói: chọn thumbnail mẫu A / B / C dựng sẵn, xem lại trước khi duyệt

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review, test web / full suite, xem trang trên 8080
- Implementer: claude-code `implementer` (Sonnet) — việc UI + test web (sandbox Codex chặn loopback, project-profile §7)
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/PKG-video-packaging-authorization.md` (PKG1 thumbnail) + HUMAN LEAD 2026-10-24 xem PKG3 trên 8080: "UI còn rất khó, đặc biệt chưa có chức năng review thumbnail. Nên cho chọn thumbnail mẫu thay vì bắt user custom"; chọn "Ít mẫu hơn: 3 kiểu A/B/C" và "Giữ #140, làm tiếp trên nó"
- Parallel group: —
- Owned paths: `src/auto_short/web/static/package.html`, `src/auto_short/web/static/package.js`, `src/auto_short/web/packaging.py`, `src/auto_short/packaging/record.py`, `tests/test_web_packaging.py`, contract này. **Không** sửa `packaging/thumbnail.py` (vẽ ảnh giữ nguyên PKG3), `packaging/episode.py`, phần ambient / nhạc nền của trang (VIS1 / AUD1).
- Dependencies: PKG3 (PR #140) — branch nối tiếp `feature/pkg3-khaithi-thumbs`
- Base commit / branch: `c4a21d5` (`feature/pkg3-khaithi-thumbs`) / `feature/pkg3.1-thumb-presets`
- Human Lead approval: HUMAN LEAD 2026-10-24 (chọn hướng 3 mẫu A / B / C, làm trên #140)
- Implementation authorized: YES

## Goal

Mở trang Đóng gói của một video ghép là thấy ngay **3 thumbnail mẫu A / B / C đã dựng sẵn** (chữ, bảng màu, nền, ảnh lấy mặc định — không phải điền gì). HUMAN LEAD bấm một mẫu để **xem lại**: ảnh ngang 16:9 cỡ lớn, ảnh dọc 9:16, và cỡ nhỏ như danh sách YouTube có nhãn thời lượng; rồi **Duyệt** và tải. Chỉnh chữ / bảng màu / nền / ảnh chỉ là tùy chọn, nằm trong mục "Tùy chỉnh" đóng sẵn.

## Scope

- In scope: tự dựng 3 kiểu khi bản ghi chưa có ảnh xem trước; ảnh mặc định cho bản ghi mới; lưới 3 mẫu bấm-để-chọn; khung xem lại (ngang lớn, dọc, cỡ YouTube + nhãn thời lượng); nút "Ảnh khác" đổi ảnh của mẫu đang chọn rồi dựng lại; gom tiêu đề / mô tả / duyệt / tải thành luồng rõ ràng; thu ô tùy chỉnh hiện có vào `<details>` "Tùy chỉnh".
- Out of scope: đổi cách vẽ ảnh (`thumbnail.py`), thêm kiểu / bảng màu mới, nhiều hơn 3 mẫu, phần Hình ambient / Nhạc nền, thumbnail tập (PKG2), upload YouTube (PUB2).

## Authority / key decisions

- Ảnh mặc định bản ghi mới: chọn tất định từ ảnh `approved` + `usable` trong kho (`episode.images` hoặc tương đương), theo `plan_id` (ví dụ chỉ số = hash(plan_id) mod số ảnh), cùng một ảnh cho cả 3 kiểu; kho trống → không ảnh (như hiện tại). Bản ghi đã có (asset_ids do người dùng chọn) không bị đổi.
- "Ảnh khác": ảnh kế tiếp trong cùng danh sách tất định (vòng lại đầu), áp cho mẫu đang chọn, lưu qua PUT hiện có rồi dựng lại.
- Tự dựng: trang gọi dựng (route `POST …/thumbnails` hiện có) đúng một lần khi tải trang mà kiểu nào cũng chưa có ảnh xem trước và không có job đang chạy; cache PKG3 giữ nguyên nên mở lại không gọi ffmpeg.
- Cỡ YouTube: ảnh ngang hiển thị rộng ~360 px với nhãn thời lượng góc phải dưới (CSS, không dựng ảnh mới), lấy từ thời lượng TC3.

## Implementation approach

- `record.new`: điền `asset_ids` mặc định như trên (cần danh sách ảnh — truyền vào hoặc đọc qua config hiện có).
- `web/packaging.py`: nếu cần, trả thêm vào view thông tin để trang hiển thị (thời lượng giây, danh sách id ảnh theo thứ tự tất định) — thêm trường, không bỏ trường.
- `package.html` / `package.js`: bố cục mới — (1) lưới 3 mẫu (ảnh ngang, tên kiểu, viền đậm khi chọn; trạng thái "đang dựng…"), (2) khung xem lại mẫu đang chọn + nút "Ảnh khác", (3) tiêu đề + copy, (4) Duyệt / tải; (5) `<details>` "Tùy chỉnh" chứa các ô PKG3 hiện có (3 dòng, bộ kinh, người giảng, vị trí ảnh, bảng màu / nền kiểu A, ảnh từng kiểu, Lưu, Dựng lại). Tái dùng `api`, `request`, `perform`, `el`, `save`, `load` hiện có.

## Phải giữ nguyên

- Ảnh dựng ra (filtergraph / cache key PKG3) và thumbnail tập PKG2.
- Route và payload hiện có của package (chỉ thêm trường), state draft / approved / stale, duyệt / tải 2 khuôn, phần Hình ambient / Nhạc nền.

## Code bị thay / xóa

- Khu "Chọn kiểu thumbnail" (`#pkg-thumbnails` dạng radio + select từng kiểu) và nút "Dựng thumbnail" ngoài cùng trong `package.html` / `package.js` → thay bằng lưới mẫu + khung xem lại; ô chọn ảnh từng kiểu chuyển vào "Tùy chỉnh". Test cũ trong `tests/test_web_packaging.py` kiểm markup / id bị bỏ phải sửa theo markup mới (không xóa test hành vi API).

## Acceptance Criteria

1. Bản ghi mới của video ghép có cùng một ảnh mặc định cho cả 3 kiểu, tất định theo `plan_id`; kho ảnh trống → không ảnh, không lỗi; bản ghi đã có giữ nguyên `asset_ids`.
2. Mở trang lần đầu: tự gửi đúng một yêu cầu dựng, hiện "đang dựng…", xong thì thấy 3 mẫu; mở lại khi đã có ảnh hoặc job đang chạy: không gửi thêm yêu cầu dựng.
3. Bấm một mẫu → chọn kiểu đó (lưu `selected`), hiện khung xem lại: ngang lớn, dọc, cỡ YouTube có nhãn thời lượng đúng thời lượng TC3.
4. "Ảnh khác" đổi sang ảnh kế tiếp cho mẫu đang chọn, dựng lại, ảnh xem trước đổi; các mẫu khác giữ nguyên.
5. Duyệt / tải 2 khuôn của mẫu đã chọn chạy như PKG3; các ô tùy chỉnh PKG3 vẫn dùng được trong "Tùy chỉnh" (đóng mặc định).
6. Test PKG2 / PKG3 hiện có về ảnh và API vẫn pass (chỉ sửa test markup bị thay).

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_web_packaging.py tests/test_packaging_thumbnail.py tests/test_packaging_episode.py tests/test_web_episode_thumbs.py -q` — AC1–AC6 (AC2–AC4 kiểm logic server + markup / JS có mặt; hành vi trình duyệt kiểm trên 8080).
- Full suite (ORCHESTRATOR).
- Xem trang trên 8080 với video ghép `PLOynZc0cJJfA6C9mATbfggiF7ATJmwSJa` / `bddcede7d89d` (ORCHESTRATOR + HUMAN LEAD).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model, public API ngoài (chỉ thêm trường vào API nội bộ trang Đóng gói) → manual test là điểm danh.

- [ ] Mở trang Đóng gói: 3 mẫu tự hiện, bấm xem lại, "Ảnh khác", duyệt, tải ngang / dọc.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
