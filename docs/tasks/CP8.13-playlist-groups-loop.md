# Task: CP8.13 — Bộ kinh: nhóm lọc mới, bỏ link "Khai thị"; nút lặp lại video

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `33ca2f8` (`origin/main`, sau merge PR #25 CP8.12) / `feature/cp8.13-playlist-groups` (worktree `../youtube-auto-short-cp813`)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-28: APPROVE, G1–G5 theo đề xuất; yêu cầu HUMAN LEAD 2026-09-28 sau manual test CP8.12: "Đang làm" chỉ còn tập đã render chưa đăng hết; tab "Lỗi / dở dang" mới; bỏ link "Khai thị" ở danh sách tập bộ kinh; video có nút tự lặp lại)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi nhóm lọc của server (`docs/decisions/CP8.3-web-contract.md` W10: `group`, `counts`, tóm tắt bộ kinh `doing`) và bỏ link "Khai thị" mà `docs/decisions/CP8.9-khai-thi-contract.md` A1.4 quy định. Không đổi security model, job model, stage / hash / artifact, config, dependency.

## Goal

Trang bộ kinh chia tập theo đúng việc cần làm: đang chạy, lỗi / dở dang cần chạy tiếp, đã render chờ đăng, xong. Dòng tập gọn hơn (không còn link "Khai thị"). Xem Short trên trang tập có thể bật lặp lại từng video.

## Scope

- In scope:
  - `src/auto_short/web/playlists.py`: nhóm mới (G1), `counts`, tóm tắt bộ kinh (G3).
  - `src/auto_short/web/static/` (`playlist.html`, `app.js`, `style.css` nếu cần): tab (G2), bỏ link (G4), nút lặp lại (G5), dòng tóm tắt trang chủ (G3).
  - Tests: sửa test đang assert nhóm cũ (`tests/test_playlist_cp87.py`, `tests/test_web_khaithi_cp89.py`, `tests/test_web_episode_ui_cp812.py`) theo nhóm mới — đây là đổi hành vi đã duyệt, không phải che lỗi; test mới cho G1–G5.
  - Docs: CP8.3 W10 (danh sách nhóm lọc, tóm tắt), W6 (nút lặp lại), CP8.9 A1.4 (bỏ link "Khai thị" — sửa đổi CP8.13), `AUTO_SHORT_CHECKPOINT_PLAN.md`, `docs/workflow/current-state.md`, Result.
- Out of scope: trang chủ danh sách tập lẻ (link khai thị dưới tập Short giữ nguyên); nút / nhãn trên trang tập ngoài G5; thay đổi `state` của entry; tự động xử lý lại tập lỗi.

## Authority / key decisions

- Authority: CP8.3 W10 (L3 nút, L4 Xong, nhóm lọc, tóm tắt), W6; CP8.9 A1.4 (`combine_status`, trạng thái gộp Short + khai thị); CP8.12 A1 (tab "Đang xử lý").
- Quyết định (HUMAN LEAD 2026-09-28 — đề xuất chi tiết, sửa trước APPROVE nếu cần):
  - **G1 Nhóm server** theo `state` gộp (A1.4): `todo` = Chưa xử lý (`new`, `deleted` chưa Xong — không đổi); `running` = Đang xử lý (`queued`, `processing`); `failed` = Lỗi / dở dang (`failed`, `incomplete`); `doing` = Đang làm (**chỉ** `rendered`: đã render, chưa đăng hết); `done` = Xong (`complete`, `deleted` đã Xong — không đổi); `unavailable` chỉ ở "Tất cả". `counts` = `{all, todo, running, failed, doing, done}`.
  - **G2 Tab** trang bộ kinh theo thứ tự: Tất cả / Chưa xử lý / Đang xử lý / Lỗi / dở dang / Đang làm / Xong. Mặc định vẫn "Đang làm"; lựa chọn đã lưu (`autoShort.plFilter`) nhận thêm `failed`. Tab "Đang xử lý" (CP8.12 A1) chuyển sang dùng `group` của server; tab rỗng "Đang xử lý" / "Lỗi / dở dang" có dòng báo "Không có tập nào …". Thanh lọc trên điện thoại xuống dòng, nút ≥ 40 px, không cuộn ngang.
  - **G3 Tóm tắt bộ kinh** (`GET /api/playlists`): `doing` đổi nghĩa theo G1; thêm `running`, `failed`. Dòng trang chủ: "… · đang xử lý a · lỗi / dở dang b · đang làm c" (mục = 0 bỏ).
  - **G4 Bỏ link "Khai thị"** trên dòng tập của trang bộ kinh (thay phần "link Khai thị" của CP8.9 A1.4). Dòng số lượng "n Shorts, đã đăng a/n · m video khai thị, đã đăng b/m" giữ nguyên; sang trang khai thị qua trang tập (thanh [Shorts | Khai thị] CP8.12). Field API `khaithi_episode_id` giữ nguyên.
  - **G5 Nút lặp lại** trên mỗi thẻ Short có video (trang tập, cả Short lẫn khai thị): nút bật / tắt "🔁 Lặp lại" (`aria-pressed`) cạnh nút "Tải về"; bật → `video.loop = true` (xem hết tự phát lại từ đầu). Trạng thái theo từng video, giữ khi thẻ được dựng lại do poll trong lúc trang còn mở; mặc định tắt; không lưu qua lần mở trang. Không đổi cách phát / tải / tick "Đã đăng".

## Implementation approach

- `GROUPS` trong `playlists.py` theo G1; `counts` và tóm tắt dùng chung bảng nhóm (không nhân bản luật).
- JS bộ kinh: bỏ `entryRunning` lọc client, dùng `data-group`; giữ `busy` (poll 5 s) theo `state`.
- G5: `Map` clip_id → loop trong module trang tập; `shortCard` đọc map khi dựng thẻ.

## Acceptance Criteria

1. `group` / `counts` đúng G1 cho mỗi `state` (gồm tập gộp Short + khai thị: một bên lỗi → `failed`; một bên đang chạy → `running`).
2. Trang bộ kinh có 7 nút lọc theo G2, mặc định "Đang làm", giá trị lưu `failed` / `running` được nạp lại; tab rỗng có dòng báo.
3. `GET /api/playlists` có `running`, `failed`, `doing` theo G1; dòng trang chủ theo G3.
4. Dòng tập trang bộ kinh không còn link "Khai thị"; dòng số lượng khai thị còn nguyên.
5. Thẻ Short có video có nút "Lặp lại" bật / tắt `loop`, trạng thái giữ qua poll; thẻ không có video (đã xóa / bỏ qua) không có nút.
6. Mọi test PASS (test nhóm cũ cập nhật theo G1, có ghi lý do trong Result).

## Required verification

- `PYTHONPATH=<worktree>/src conda run -n auto-short python -m pytest -q` — toàn bộ PASS.
- `node scripts/framework-check.mjs` PASS.
- Web scratch (port ≠ 8080, dữ liệu tạm): gọi API bộ kinh kiểm AC1, AC3; kiểm JS được phục vụ cho AC2, AC4, AC5 (Node + DOM giả như CP8.12 nếu cần). Kiểm bằng mắt trên trình duyệt: manual test HUMAN LEAD (máy không có trình duyệt — như CP8.12).

## Manual test checklist (Tech Lead)

Không chạm database / security model; đổi nghĩa trường `doing` và thêm trường trong HTTP API nội bộ của web (chỉ UI của project dùng) → manual test là điểm danh, riêng phần hiển thị (AC2, AC4, AC5 bằng mắt) là gate trước READY như CP8.12.

- [ ] Trang bộ kinh: 7 tab, số đếm đúng; "Đang làm" chỉ còn tập đã render chưa đăng hết; tập lỗi / dở dang ở "Lỗi / dở dang" với nút "Chạy tiếp"; mặc định mở "Đang làm".
- [ ] Dòng tập không còn link "Khai thị"; vẫn thấy số video khai thị.
- [ ] Trang chủ: dòng tóm tắt bộ kinh ghi đang xử lý / lỗi / đang làm.
- [ ] Trang tập: bấm "Lặp lại" trên một Short → xem hết tự phát lại; tắt → dừng ở cuối; Short khác không bị ảnh hưởng.
- [ ] Điện thoại: thanh lọc xuống dòng, không cuộn ngang.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
