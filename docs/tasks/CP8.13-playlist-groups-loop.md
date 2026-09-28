# Task: CP8.13 — Bộ kinh: nhóm lọc mới, bỏ link "Khai thị"; nút lặp lại video

## Status / Approval

- Status: IN_PROGRESS
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
  - `src/auto_short/web/playlists.py`: `GROUPS` theo G1 (`queued`/`processing` → `running`; `failed`/`incomplete` → `failed`; `rendered` → `doing`; `new` → `todo`; `complete` → `done`; `deleted` giữ `group_of` cũ), `GROUP_NAMES`; `counts` = `{all, todo, running, failed, doing, done}` dựng từ `GROUP_NAMES`; `summary` thêm `running`, `failed` (cùng bảng nhóm qua `view`).
  - `static/playlist.html`: 6 nút lọc theo danh sách G2 (thêm "Lỗi / dở dang"), dòng báo `#pl-failed-empty`.
  - `static/app.js`: bộ kinh lọc bằng `data-group` cho mọi tab (bỏ `entryRunning` / `data-running` của CP8.12 A1); `PL_FILTERS` nhận giá trị lưu `failed`; số đếm = `counts` server; poll 5 s khi `state` là `queued` / `processing`; bỏ link "Khai thị" trên dòng tập (G4; dòng số lượng khai thị giữ nguyên); trang chủ `playlistSummary` (G3, mục = 0 bỏ); trang tập: `loopButton` ("🔁 Lặp lại", `aria-pressed`) sau "Tải về" trên thẻ có `<video>`, `Map` `loops` clip_id → bật, đọc lại khi dựng thẻ (G5).
  - `static/style.css`: `.loop-btn[aria-pressed="true"]` (nền nhấn như nút lọc đang chọn). Thanh lọc ≤ 640 px đã có `flex-wrap` + nút ≥ 40 px (CP8.7) — không đổi.
  - Docs: CP8.3 W6 (G5), W7 (bảng API `GET /api/playlists`, `counts`), W10 (nhóm lọc, trang chủ, tab, ghi chú CP8.12 A1 → CP8.13); CP8.9 A1.4 (bỏ link "Khai thị", tóm tắt theo nhóm mới); `AUTO_SHORT_CHECKPOINT_PLAN.md` mục CP8.13; `docs/workflow/current-state.md`.
- Tests:
  - Test cũ cập nhật (đổi hành vi đã duyệt G1–G3, không che lỗi): `tests/test_playlist_cp87.py` — `counts` có thêm `running`, `failed` (giá trị cũ giữ nguyên vì các tập ở đó là `new` / `rendered` / `complete` / `deleted`); tóm tắt `GET /api/playlists` có thêm `running`, `failed`. `tests/test_web_episode_ui_cp812.py` — tab "Đang xử lý" không còn lọc phía client (`entryRunning` / `data-running` bỏ theo G2), thứ tự tab 6 nút lọc có `failed`; tập có job khai thị đang chạy giờ ở nhóm `running` (trước: `doing`) theo G1. `tests/test_web_khaithi_cp89.py` không phải sửa (assert `doing` = 1 cho tập `rendered`, vẫn đúng theo G1).
  - Test mới `tests/test_web_playlist_groups_cp813.py`: bảng nhóm G1; `view` / `counts` / `summary` cho 16 tổ hợp Short + khai thị + job (một bên lỗi → `failed`, một bên chạy → `running`, `incomplete` → `failed`, `deleted` Xong / chưa Xong); API thật với workspace `rendered` / `failed` / `incomplete` / stage `running` / `new` (AC1, AC3); HTML 6 tab theo đúng danh sách G2 + dòng báo, JS lọc theo `data-group` + giá trị lưu (AC2); dòng tập không có link "Khai thị", còn dòng số lượng (AC4); nút lặp lại chỉ trên thẻ có video, `aria-pressed`, `video.loop`, `Map`, không API / không lưu (AC5).
  - `PYTHONPATH=<worktree>/src conda run -n auto-short python -m pytest -q`: `881 passed, 1 warning in 172.76s` (warning: StarletteDeprecationWarning httpx, có sẵn).
  - `node scripts/framework-check.mjs`: toàn PASS, exit 0.
  - Web scratch `127.0.0.1:8093` (worktree `src`, dữ liệu tạm trong scratchpad, đã tắt): API bộ kinh 8 entry (`rendered`+khai thị `rendered`, `failed`, `incomplete`, stage `running`, `complete`, `rendered`+khai thị `failed`, `new`, `unavailable`) → group `doing, failed, failed, running, done, failed, todo, None`, `counts {all 8, todo 1, running 1, failed 3, doing 1, done 1}`; `GET /api/playlists` `running 1, failed 3, doing 1` (AC1, AC3). Node + DOM giả chạy `app.js` được phục vụ: mặc định tab "Đang làm"; giá trị lưu `failed` / `running` được nạp lại, giá trị lạ → "Đang làm"; mỗi tab hiện đúng tập; bộ kinh không có tập chạy / lỗi → dòng "Không có tập nào đang xử lý" / "… lỗi / dở dang" hiện; không link "Khai thị" trên dòng tập, dòng "2 video khai thị, đã đăng 0/2" còn (AC2, AC4); trang chủ "8 tập · đã xử lý 6 · Xong 1 · đang xử lý 1 · lỗi / dở dang 3 · đang làm 1" và "2 tập · đã xử lý 1 · Xong 0 · đang làm 1" (G3); trang tập Short và khai thị: thẻ `rendered` có "Tải về / 🔁 Lặp lại", thẻ bỏ qua không có nút; bấm → `aria-pressed=true`, `video.loop=true`, thẻ khác không đổi; thẻ dựng lại do tick "Đã đăng" + refresh vẫn bật; bấm lại tắt / bật; không gọi API (AC5).
- Review:
- Important findings / decisions:
  - AC2 / checklist ghi "7 nút lọc / 7 tab" nhưng G2 liệt kê 6 (Tất cả / Chưa xử lý / Đang xử lý / Lỗi / dở dang / Đang làm / Xong — "Lỗi / dở dang" là một tab): làm đúng danh sách G2 (6 nút); đề nghị HUMAN LEAD xác nhận.
  - Nút lặp lại đặt sau "Tải về", trước "Xóa" trong hàng nút của thẻ; dùng class `.btn` như "Tải về".
  - `busy` (poll) dựa `state` gộp `queued` / `processing` — tương đương điều kiện cũ (`combine_status` đã trả `queued` / `processing` khi job khai thị chạy).
  - Kiểm bằng mắt trên trình duyệt (AC2, AC4, AC5, điện thoại): chưa làm — máy không có trình duyệt; manual test HUMAN LEAD trước READY (như CP8.12).
- Known limitations:
  - Trạng thái "Lặp lại" mất khi tải lại trang (theo G5: không lưu).
- PR:
