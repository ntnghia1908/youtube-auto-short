# Task: CP8.12 — Trang tập: thanh Shorts / Khai thị + danh sách bước thu gọn

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `d2cfce3` (`origin/main`) / `feature/cp8.12-episode-ui` (worktree `../youtube-auto-short-cp812`)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-28: APPROVE; sửa U4 — tập Short đã xóa không dẫn tới 404 mà báo cho người dùng)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ đổi trình bày trang tập (HTML / CSS / JS tĩnh). Không đổi HTTP API, security model, job model, stage / hash / artifact, config, dependency. Hành vi CP8.9 K7 (link qua lại, khung "Tạo video khai thị") giữ nguyên, chỉ đổi hình thức. CP8.3 W6 mô tả trang tập → thêm một dòng pointer "Sửa đổi CP8.12" trỏ về task này (đồng bộ mô tả, không tạo rule mới ngoài task).

## Goal

Trên trang tập (máy tính và điện thoại): chuyển giữa trang Short và trang khai thị của cùng video bằng một thanh hai nút luôn nằm ở đầu màn hình khi cuộn; danh sách 6 bước xử lý gọn lại thành một dòng khi tập đã xong, tự mở khi đang chạy hoặc lỗi — lưới Short lên cao hơn, ít phải cuộn.

## Scope

- In scope:
  - `src/auto_short/web/static/episode.html`, `app.js` (phần trang tập), `style.css`.
  - Tests trong `tests/` (kiểm HTML / JS / CSS được phục vụ, theo mẫu `tests/test_web_khaithi_cp89.py`, `tests/test_web_series_cp811.py`).
  - Docs: `docs/decisions/CP8.3-web-contract.md` W6 (một dòng "Sửa đổi CP8.12" trỏ task này), `AUTO_SHORT_CHECKPOINT_PLAN.md` (mục CP8.12 ngắn, trỏ task), `docs/workflow/current-state.md` (sửa dòng "PR #23 chờ merge" → đã merge `d2cfce3`; CP8.12 IN_PROGRESS / READY), Result của contract này.
- Out of scope:
  - API / server (`app.py`, `episodes.py`, …): không thêm trường; `base_episode_id` giữ ngữ nghĩa CP8.9.
  - Trang chủ, trang bộ kinh, tab Bộ nhớ; topbar (không ghim topbar).
  - Bố cục title Short (S2 riêng), CP9, CL1.
  - Sửa web đang chạy ở worktree `../youtube-auto-short-web` (8080) — HUMAN LEAD tự chuyển ghim sau merge.

## Authority / key decisions

- Authority: `docs/decisions/CP8.3-web-contract.md` W6 (trang tập, nhật ký mở sẵn khi chạy / lỗi, mobile ≤ 640 px nút ≥ 40 px, không cuộn ngang); `docs/decisions/CP8.9-khai-thi-contract.md` K7 + A1.3 (link qua lại, khung "Tạo video khai thị", nhãn), A2.3 (từ ngữ "video" / "Short").
- Quyết định cục bộ S1 (hướng HUMAN LEAD duyệt 2026-09-28; chi tiết đề xuất — sửa trước khi APPROVE nếu cần):
  - **U1 Thanh chọn loại:** thay `#kind-links` bằng thanh hai nút `[Shorts | Khai thị]` nằm ngay trên thẻ đầu tiên của `main`; hiện trên mọi trang tập.
    - Nút của trang hiện tại: tô đậm (nền vàng accent), `aria-current="page"`, không phải link.
    - Nút kia khi có trang đích (Short page: `khaithi_episode_id`; khai thị page: `base_episode_id`): link `/episodes/<id>` → thay cho link chữ CP8.9 K7 (yêu cầu "link qua lại" giữ nguyên).
    - Trang Short, chưa có khai thị: nút "Khai thị" mờ (vẫn bấm được) → mở `#kt-box` (`open = true`), cuộn tới khung, focus ô "Dài từ (phút)". Khi `#kt-box` bị ẩn (không có `source_url`) → nút mờ, `disabled`, `title` giải thích ("Không có link video nguồn").
    - Trang khai thị không có `base_episode_id` (`khaithi.json` hỏng) → nút "Shorts" mờ, `disabled`.
    - Trang khai thị có `base_episode_id` nhưng tập Short không còn → xem U4.
    - Nút cao ≥ 44 px, chia đều chiều rộng thanh trên điện thoại (không cuộn ngang); nhãn giữ "Shorts" / "Khai thị" (không kèm số phút — số phút đã có ở `#ep-meta`).
    - Ghim: `position: sticky; top: 0` (nền đặc + bóng nhẹ, `z-index` trên lưới video), vẫn ghim khi cuộn qua lưới Short.
  - **U2 Khung các bước:** `#stages` bọc trong `<details id="stages-box">`; `<summary>` chứa dòng trạng thái job (`#job-status` hiện tại chuyển vào summary, giữ class `ok` / `error` / `busy`). Không có dòng job (vd server restart) → summary = "Các bước xử lý: x/6 xong" (x = số stage `done`).
    - Trạng thái mong muốn: **đóng** khi mọi stage `done` và không có job active; **mở** trong mọi trường hợp khác (job queued / running / waiting, stage `running` / `failed` / `stale` / `pending`, job `failed` / `interrupted`).
    - Tự mở / đóng **theo cạnh**: chỉ đặt `open` khi trạng thái mong muốn khác lần áp dụng trước (và lần render đầu) → poll 2 s không ghi đè thao tác mở / đóng tay của người dùng khi trạng thái không đổi.
    - `#archived-note`, nút "Chạy tiếp / chạy lại", "Xóa tập này", `#kt-box`, nhật ký giữ nguyên vị trí / hành vi (ngoài khung thu gọn); nhật ký vẫn mở sẵn khi chạy / lỗi (W6).
  - **U4 Tập đích không còn (HUMAN LEAD 2026-09-28): không dẫn người dùng tới trang lỗi.**
    - Trang khai thị: sau khi tải dữ liệu, kiểm một lần `GET /api/episodes/<base_episode_id>` (API hiện có; nhớ kết quả, không gọi lại mỗi lần poll). 404 → nút "Shorts" mờ; bấm hiện thông báo ngay trên trang (dưới thanh, không `alert`): "Tập Short của video này đã bị xóa. Muốn có lại Short: gửi lại link video ở trang chủ (chọn Short)." Lỗi mạng / lỗi khác → giữ nút là link (không chặn vì lỗi tạm).
    - Mọi trang tập: `GET /api/episodes/<id>` trả 404 → thay nội dung trang bằng thông báo "Tập này không còn (đã bị xóa hoặc chưa từng xử lý)." + link về trang chủ; dừng poll (không hiện dòng lỗi "không có episode này" rồi poll mãi như hiện tại). Lỗi khác giữ hành vi cũ (hiện lỗi, poll chậm).
  - **U3** Áp như nhau trên máy tính và điện thoại; không thêm trang / route / trường API.

## Sửa đổi A1 — tab "Đang xử lý" ở trang bộ kinh (HUMAN LEAD 2026-09-28, trong lúc IN_PROGRESS)

- Trang bộ kinh (`playlist.html`, phần bộ kinh của `app.js`, `style.css`) thêm nút lọc **"Đang xử lý (n)"** giữa "Chưa xử lý" và "Đang làm": chỉ tập có job đang đợi hàng hoặc đang chạy (`state` `queued` / `processing`) **hoặc** job khai thị của cùng video đang đợi / chạy (`khaithi_state` `queued` / `processing`). Mỗi dòng vẫn hiện làn / stage như hiện tại ("đang tải trước", "đợi GPU", "đợi render", stage đang chạy).
- Lọc phía client từ dữ liệu `GET /api/playlists/{pid}` hiện có; không đổi API, không đổi nhóm `group` của server (W10). "Đang làm" giữ nguyên (tập đang xử lý hiện ở cả hai tab). Bộ lọc mặc định giữ "Đang làm"; lựa chọn được nhớ như cũ (`autoShort.plFilter`, thêm giá trị mới hợp lệ).
- Tab rỗng → dòng "Không có tập nào đang xử lý". Poll 5 s như cũ: tập xử lý xong tự rời tab. Thanh lọc trên điện thoại xuống dòng, không cuộn ngang, nút ≥ 40 px (W6 CP8.7).
- Scope thêm: `playlist.html`; docs CP8.3 W10 thêm một dòng "Sửa đổi CP8.12 A1" trỏ task này.
- AC A1: HTML trang bộ kinh có nút `data-filter` mới "Đang xử lý"; JS lọc đúng `queued` / `processing` (Short hoặc khai thị) và chấp nhận giá trị lưu mới; test tĩnh + kiểm web scratch có một tập đang chạy.
- Manual test: [ ] Trang bộ kinh có tập đang chạy → tab "Đang xử lý" chỉ hiện tập đó, số đếm đúng; tập xong → tự rời tab; mặc định vẫn mở "Đang làm".

## Implementation approach

- HTML: thêm `<nav id="kind-bar" class="kind-bar">` trước thẻ đầu; bỏ `#kind-links`; bọc `#stages` bằng `<details id="stages-box"><summary><span id="job-status" …></span></summary>…</details>`.
- JS: `renderKindLinks` → `renderKindBar(d)` (dựng hai nút, xử lý mờ / disabled / mở `#kt-box`); `setJobStatus` giữ API, thêm fallback "x/6 xong" cho summary; hàm thuần `stagesShouldOpen(d)` + biến nhớ trạng thái đã áp dụng lần trước.
- CSS: `.kind-bar` sticky, hai nút `flex: 1`, `min-height: 44px`; summary của `#stages-box` đủ vùng bấm (≥ 44 px) và vẫn hiện màu `ok` / `error` / `busy`.
- Không có framework test JS trong repo (không thêm dependency): logic kiểm bằng pytest trên nội dung tĩnh được phục vụ + manual test.

## Acceptance Criteria

1. `GET /episodes/<id>` trả HTML có `#kind-bar` (hai nút Shorts / Khai thị) và `#stages-box` (`<details>` chứa `#stages`, summary chứa `#job-status`); không còn `#kind-links`.
2. Trang Short có tập khai thị → nút "Khai thị" là link tới `/episodes/<id>.kt`; trang khai thị → nút "Shorts" link tới `base_episode_id`; nút trang hiện tại tô đậm, `aria-current="page"`.
3. Trang Short chưa có khai thị → nút "Khai thị" mờ; bấm mở `#kt-box`, cuộn tới và focus ô phút. Không có `source_url` → nút disabled.
4. Thanh ghim ở đầu màn hình khi cuộn (CSS `position: sticky; top: 0`), nút ≥ 44 px, không cuộn ngang ở 360 px.
5. `#stages-box` đóng khi mọi bước `done` và không có job active; mở khi job đang đợi / chạy hoặc có lỗi / bước chưa xong; poll không ghi đè thao tác tay khi trạng thái không đổi; summary luôn có chữ (dòng job hoặc "x/6 xong").
6. U4: trang khai thị có tập Short đã xóa → nút "Shorts" mờ, bấm hiện thông báo trên trang (không điều hướng, không 404); trang tập có API 404 → thông báo "Tập này không còn …" + link trang chủ, không poll tiếp.
7. Hành vi khác của trang tập không đổi: "Tạo video khai thị", "Chạy tiếp / chạy lại", xóa tập, nhật ký, lưới Short, sửa title; toàn bộ test hiện có PASS.

## Required verification

- `PYTHONPATH=<worktree>/src conda run -n auto-short python -m pytest -q` — toàn bộ suite PASS (AC 1, 2, 6 qua test tĩnh mới + test cũ).
- Test mới (vd `tests/test_web_episode_ui_cp812.py`): HTML trang tập có / không có các id ở AC 1; `app.js` có `renderKindBar`, `stagesShouldOpen`, `aria-current`, thông báo U4; `style.css` có `.kind-bar` sticky + `min-height: 44px`.
- `node scripts/framework-check.mjs` PASS.
- Chạy web scratch từ worktree (port khác 8080, `work/` scratch hoặc bản sao chỉ-đọc) + kiểm bằng trình duyệt ở 360 px và ≥ 1024 px: AC 2–5 (implementer ghi lại cách kiểm và kết quả trong Result).
  - **Sửa đổi HUMAN LEAD 2026-09-28:** máy không có trình duyệt (không cài thêm) → phần kiểm bằng mắt ở 360 px / ≥ 1024 px (AC4: sticky, không cuộn ngang, vùng bấm) chuyển sang manual test của HUMAN LEAD trên điện thoại + máy tính, trên web scratch port 8093 (bản hard-link `work/` / `output/`), và là gate trước READY cho riêng AC4.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Task không chạm database, security model hay public API contract → manual test sau automated verification là điểm danh (HUMAN LEAD, trên điện thoại).

- [ ] Trang tập Short có khai thị: thanh [Shorts | Khai thị] ở đầu, Shorts tô đậm; bấm Khai thị → sang trang khai thị, Khai thị tô đậm; bấm Shorts → quay lại.
- [ ] Cuộn xuống lưới Short: thanh vẫn ghim ở đầu màn hình, bấm được bằng ngón tay.
- [ ] Trang tập Short chưa có khai thị: nút Khai thị mờ; bấm → mở khung "Tạo video khai thị", nhập phút được.
- [ ] Tập đã xong: khung các bước đóng, một dòng "Xong: …"; bấm mở / đóng được, không tự bật lại sau vài giây.
- [ ] Gửi "Chạy tiếp / chạy lại" hoặc tập đang chạy / lỗi: khung các bước tự mở, dòng trạng thái cập nhật.
- [ ] Trang khai thị của video đã xóa tập Short (dữ liệu scratch): bấm Shorts → thông báo trên trang, không sang trang lỗi. Mở `/episodes/<id không tồn tại>` → thông báo "Tập này không còn" + link trang chủ.
- [ ] Máy tính: như trên, không vỡ bố cục.

## Result

- Main changes:
  - `episode.html`: `nav#kind-bar` (hai nút) + `p#kind-note` (thông báo U4) trên thẻ đầu của `main`; bỏ `#kind-links`; `<details id="stages-box">` với `<summary>` chứa `#job-status`, bọc `#stages`. `#archived-note` giờ nằm ngay dưới khung các bước (trước ở giữa dòng job và danh sách bước), vẫn ngoài khung thu gọn.
  - `app.js`: `renderKindBar(d)` (thay `renderKindLinks`; chỉ dựng lại khi trạng thái thanh đổi), `checkBaseEpisode` (U4, một lần / trang), `openKtBox`; `stagesShouldOpen(d)` + `applyStagesOpen(d)` (theo cạnh); `setJobStatus` fallback "Các bước xử lý: x/6 xong"; `showEpisodeGone()` khi API 404 (dừng poll). `api()` gắn `err.status` vào lỗi (không đổi message / hành vi nơi khác).
  - `style.css`: `.kind-bar` sticky `top: 0` (nền `--card`, bóng, `z-index: 20`), `.kind-btn` `flex: 1 1 0; min-width: 0; min-height: 44px`, `.current` nền accent, `.dim` mờ; summary `#stages-box` `min-height: 44px`, dấu ▸ / ▾, giữ màu `ok` / `error` / `busy`.
  - A1 (`playlist.html`, `app.js` phần bộ kinh): nút `data-filter="running"` "Đang xử lý (n)" giữa "Chưa xử lý" và "Đang làm"; `entryRunning(e)` = `state` hoặc `khaithi_state` ∈ `queued` / `processing`; số đếm tính phía client; `li[data-running="1"]`; `p#pl-running-empty` "Không có tập nào đang xử lý" khi tab rỗng; `autoShort.plFilter` nhận thêm `running`; mặc định vẫn "Đang làm"; điều kiện poll 5 s dùng cùng `entryRunning` (tương đương cũ vì `state` gộp đã phản ánh job khai thị). Không đổi CSS (thanh lọc `.filters` sẵn xuống dòng, nút ≥ 40 px trên điện thoại).
  - Docs: CP8.3 W6 dòng "Sửa đổi CP8.12", W10 dòng "Sửa đổi CP8.12 A1" + metadata Accepted by; `AUTO_SHORT_CHECKPOINT_PLAN.md` mục CP8.12; `docs/workflow/current-state.md`.
- Tests:
  - `tests/test_web_episode_ui_cp812.py` (7 test: HTML AC1, JS AC2/3/5/6 tĩnh, CSS AC4, dữ liệu API cho thanh, Short bị xóa / id không tồn tại; A1: HTML / JS tĩnh, dữ liệu `state` / `khaithi_state` khi job khai thị đang chạy). Toàn suite: `875 passed`.
  - Web scratch (port 8093, `work/` / `output/` tạm, không đụng repo chính / web 8080): chạy `app.js` được phục vụ trong Node với DOM giả tối thiểu (không có trình duyệt headless / jsdom trên máy, không cài thêm) — kiểm AC2, AC3 (có `source_url`), AC5 (theo cạnh, qua chuỗi trạng thái job giả; và job thật của pipeline giả bị chặn ở bước Phụ đề: khung mở + dòng "Đang tải trước: Phụ đề …", xong → khung đóng + "Xong: …"), AC6. A1: server scratch với pipeline giả chặn ở bước Phụ đề, bộ kinh 4 tập, một job khai thị đang chạy → "Đang xử lý (1)" chỉ hiện tập đó, "Đang làm (3)" giữ nguyên, lựa chọn lưu / nạp lại `running`; job xong → "Đang xử lý (0)", dòng "Không có tập nào đang xử lý", hết poll 5 s. **Chưa kiểm bằng trình duyệt thật ở 360 px / ≥ 1024 px** (sticky, không cuộn ngang, vùng bấm) — cần HUMAN LEAD / Tech Lead xem ở manual test.
- Review: ORCHESTRATOR đọc diff `c1de0a9` (HTML / JS / CSS / test / docs) theo U1–U4, A1: không thấy lỗi; chạy lại `tests/test_web_episode_ui_cp812.py` + `tests/test_web_khaithi_cp89.py` → 32 passed. Chờ manual test AC4.
- Important findings / decisions:
  - Tập Short chưa có khai thị: nút "Khai thị" là `<button>` mờ có `title` "Chưa có video khai thị — bấm để tạo"; trang khai thị không có `base_episode_id`: nút "Shorts" disabled, `title` "Không rõ tập Short của video này".
  - Trong lúc kiểm U4 đang chạy, nút "Shorts" hiển thị là link (lạc quan); lỗi mạng / lỗi khác giữ link.
  - Trang `/episodes/<id>` sai định dạng id vẫn trả JSON 404 từ server như trước (route ngoài scope).
- Known limitations:
  - Kiểm tập Short còn hay không (U4) chạy một lần khi mở trang khai thị; tập Short bị xóa trong lúc trang đang mở thì bấm "Shorts" sẽ tới thông báo "Tập này không còn …" của U4 (không phải 404 thô).
- PR:
