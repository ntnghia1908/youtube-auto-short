# Task: CP8.12 — Trang tập: thanh Shorts / Khai thị + danh sách bước thu gọn

## Status / Approval

- Status: APPROVED
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
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
  - Kiểm tập Short còn hay không (U4) chạy một lần khi mở trang khai thị; tập Short bị xóa trong lúc trang đang mở thì bấm "Shorts" sẽ tới thông báo "Tập này không còn …" của U4 (không phải 404 thô).
- PR:
