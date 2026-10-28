# Task: THUMB2-codex-compilation-thumbs — Thumbnail khai thị ghép do Codex vẽ; bỏ trang Đóng gói, gộp vào thẻ video

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-28: "trang đống gói hiện rất phức tạp khó sài … thiết kế lại trang này sao cho dễ sài nhất có thể. Hoặc bỏ luôn nếu không cần thiết" → chọn "Bỏ, gộp vào thẻ video"; "Thumanil cho khai thị ghép có thể gọi từng ảnh không cần phụ thụ thumail bộ kinh vì vốn dĩ khai thị ghép sẽ ít và là sản phẩn chiến lượt của kênh"
- Parallel group: —
- Owned paths: `src/auto_short/packaging/compilation_thumbs.py` (mới), `src/auto_short/packaging/record.py`, `src/auto_short/packaging/thumbnail.py` (gỡ phần theme A/B/C), test PKG3 / PKG3.1 hiện có (`tests/test_packaging_thumbnail.py`, `tests/test_web_packaging.py`, …) khi khẳng định hành vi bị gỡ, `src/auto_short/web/compilations.py`, `src/auto_short/web/packaging.py`, `src/auto_short/web/static/favorites.{html,js}`, `src/auto_short/web/static/package.{html,js}` (xóa), `src/auto_short/web/static/theme_plan.js`, phần VIS1 / AUD1 / duyệt bản đăng trong `src/auto_short/packaging/` + `src/auto_short/web/packaging.py` khi chỉ phục vụ trang Đóng gói, test tương ứng, `src/auto_short/packaging/cover_suggest.py` (chỉ tổng quát hóa runner / validate cho khóa ngoài playlist, không đổi hành vi THUMB1), `tests/test_compilation_thumbs.py` (mới), `tests/test_web_compilation.py`, `tests/test_web_packaging.py`, contract này
- Dependencies: THUMB1 — bắt đầu sau khi THUMB1 merge (runner Codex `cover_suggest`, config `[thumbs]`, thread 1 job Codex); CP8.33 (video ghép yêu thích); TC3 / PKG3 (tuyển tập chủ đề + Đóng gói)
- Base commit / branch: `origin/main` sau khi THUMB1 merge / `feature/thumb2-compilation-thumbs`
- Human Lead approval: APPROVED 2026-10-28 (chỉ thị trên; phạm vi 2 loại video ghép là giả định của ORCHESTRATOR, xem D-THUMB2-1)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm nguồn thumbnail AI cho sản phẩm đóng gói PKG (quyết định PKG) và mở rộng tích hợp Codex của THUMB1 sang trang khác.

## Bối cảnh / quyết định

- Khai thị ghép ít, là sản phẩm chiến lược → đáng gọi AI riêng cho từng video, vẽ **trọn ảnh** (tên chủ đề / tiêu đề in luôn trong ảnh), không dùng ảnh bìa bộ kinh + khung chữ như THUMB1.
- D-THUMB2-1 (giả định, HUMAN LEAD sửa nếu sai): áp dụng cho cả hai loại khai thị ghép: (a) video ghép yêu thích CP8.33 (`_compilations/<pid>/<cid>.mp4`, 9:16, hiện chưa có thumbnail); (b) tuyển tập chủ đề TC3 (`<pid>/theme/<plan_id>-r<rev>.mp4`, 16:9, đang có PKG3 A/B/C) → thumbnail chỉ còn Codex.
- D-THUMB2-4 (HUMAN LEAD 2026-10-28: "Bỏ luôn A/B/C của khai thị ghép làm sao cho phần thumail đơn giản dễ sài nhất cho end user"): gỡ PKG3 A/B/C + preset PKG3.1 của tuyển tập chủ đề (UI, dựng, file). Trang Đóng gói / mục video ghép chỉ còn một khối thumbnail: [Vẽ thumbnail] → 2 mẫu → [Chọn] / [Gợi ý thêm] → [Tải ảnh]. Không chọn kiểu, không chỉnh chữ / ảnh / thanh trượt. PKG2 A/B/C của thumbnail **tập** (backend, intro bản dọc VERT2 khi bộ chưa có ảnh bìa) giữ nguyên.
- D-THUMB2-2 (HUMAN LEAD 2026-10-28: "Mỗi khai thị ghép chỉ gợi ý 2 ảnh nếu user không vừa ý mới bấm gen thêm ảnh gợi ý"): mỗi video: Codex vẽ **2 mẫu** ở khổ chính của video ((a) dọc 1080×1920, (b) ngang 1280×720 `EPISODE_SIZES`); chưa vừa ý → nút **"Gợi ý thêm"** (kèm ghi chú tùy chọn) vẽ thêm 2 mẫu, các mẫu cũ của video vẫn hiện để chọn. HUMAN LEAD chọn + kiểm dấu → Codex vẽ khổ còn lại cùng phong cách (ảnh chọn làm `-i`).
- D-THUMB2-3: chữ trong ảnh do Codex vẽ: tiêu đề video (đã lưu: (a) `title` trong `<cid>.json`, (b) tiêu đề plan), tên bộ kinh, chủ giảng; có thể sửa chữ trước khi vẽ (ô văn bản, ≤ 3 dòng × 40 ký tự). Ảnh bìa bộ kinh đã cài (nếu có) chỉ là tham chiếu phong cách tùy chọn, không bắt buộc.

- D-THUMB2-5 (HUMAN LEAD 2026-10-28, chọn "Bỏ, gộp vào thẻ video"): **bỏ trang Đóng gói** (`/playlists/{pid}/theme-plans/{plan_id}/package`). Mỗi video ghép (cả (a) và (b)) trên trang Yêu thích là một thẻ với: Xem · Tải video · Copy tiêu đề · Copy mô tả · khối thumbnail Codex. Bỏ bước "Duyệt bản đăng", hình ambient (VIS1) và nhạc nền (AUD1) khỏi UI + API; video đã dựng có nhạc / hình trên đĩa: để nguyên, không xóa. Tiêu đề / mô tả tải về: lấy từ sidecar render hiện có (không cần duyệt).

## Goal

Trên trang Yêu thích, mỗi thẻ video ghép (yêu thích và tuyển tập chủ đề): nút "Vẽ thumbnail bằng Codex" → 2 mẫu (thêm 2 khi bấm "Gợi ý thêm") → chọn → có thumbnail 2 khổ đúng kích thước để tải (và PUB2 / zip dùng được), không phụ thuộc ảnh bìa bộ kinh.

## Scope

- In scope:
  - `packaging/compilation_thumbs.py`: prompt (khối dữ liệu cho tiêu đề / tên kinh / chủ giảng / ghi chú), lượt vẽ lưu cạnh video ((a) `_compilations/<pid>/thumbs/<cid>/<run_id>/`, (b) trong package record `<plan_id>-r<rev>`), validate (tên file, probe, tỉ lệ, ≤ 15 MB), chuẩn hóa về `EPISODE_SIZES`, chọn → file chính thức + sha256 vào sidecar; giữ 3 lượt gần nhất.
  - Tái dùng runner Codex / thread 1 job / hủy / timeout / restart → failed của THUMB1 (một hàng chung: THUMB1 và THUMB2 không chạy Codex song song).
  - Web (a): nút + lưới mẫu + "Gợi ý thêm" + chọn + tải thumbnail trong mục video ghép của `favorites`; (b): cùng khối trong thẻ tuyển tập chủ đề trên trang Yêu thích (D-THUMB2-5). Ô sửa chữ trước khi vẽ (D-THUMB2-3) thu gọn trong "Sửa chữ", mặc định dùng tiêu đề sẵn có.
  - Revision mới của tuyển tập (r+1) → thumbnail Codex cũ không tự chuyển (tiêu đề có thể đổi): hiện "vẽ cho bản cũ", cho dùng lại hoặc vẽ lại.
- Out of scope: thumbnail tập / khai thị từng clip (THUMB1); OCR kiểm dấu; tự đăng lên YouTube.

## Phải giữ nguyên

- Package record của tuyển tập (video, mô tả, tên tải) và route tải video; PKG2 thumbnail tập; video ghép và mô tả CP8.33; THUMB1.

## Code bị thay / xóa

- Trang Đóng gói: `package.{html,js}`, route `/playlists/{pid}/theme-plans/{plan_id}/package` + API `…/package/*`, VIS1 (hình ambient), AUD1 (nhạc nền), duyệt bản đăng → xóa cùng test; link "Đóng gói" trong `theme_plan.js` → thay bằng các nút trong thẻ. Quyết định `docs/decisions/PKG-video-packaging-authorization.md`: ghi chú phần bị gỡ (pointer tới contract này).

- PKG3 / PKG3.1: `thumbnail.theme_badge` / `theme_look` / `theme_text` / `check` / `build_theme` / `key` / `build` / `ready` và preset theme (nếu chỉ phục vụ tuyển tập), `record.STYLES` A/B/C của theme, job dựng thumbnail A/B/C trong `web/packaging.py`, UI chọn kiểu / preset trong `package.{html,js}`, route tải file `{A|B|C}-…jpg` → xóa; test tương ứng → xóa / thay. File A/B/C đã dựng trên đĩa: để nguyên (không xóa dữ liệu người dùng), không còn hiện.
- Nếu tổng quát hóa runner THUMB1 thì xóa bản lặp.

## Acceptance Criteria

1. Codex giả lập: lượt đầu vẽ đúng 2 mẫu; "Gợi ý thêm" vẽ thêm 2 và giữ mẫu cũ trong danh sách chọn; validate / loại mẫu lỗi có lý do; chọn → khổ thứ hai; file chính thức đúng kích thước, sha256 ghi sidecar; lượt > 3 bị dọn, file đã chọn còn.
2. Lệnh Codex như THUMB1 AC2 (không `danger-full-access`, prompt khối dữ liệu); chỉ 1 job Codex toàn máy chủ (chung THUMB1) → 409.
3. Trang Yêu thích: mỗi thẻ video ghép ((a) và (b)) có Xem / Tải video / Copy tiêu đề / Copy mô tả / thumbnail Codex; route + trang Đóng gói, A/B/C, preset, VIS1, AUD1, duyệt bản đăng bị gỡ (404); file cũ trên đĩa không bị xóa; PKG2 thumbnail tập không đổi byte; revision mới đánh dấu thumbnail cũ.
4. Route yêu cầu đăng nhập, chặn id / tên file lạ (traversal, symlink).
5. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

Prefix như THUMB1.

- `<prefix> tests/test_compilation_thumbs.py tests/test_cover_suggest.py` — AC 1–2.
- `<prefix> tests/test_web_compilation.py tests/test_web_packaging.py tests/test_packaging_thumbnail.py` — AC 3–4 (TestClient: ORCHESTRATOR).
- `<prefix> -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 5.
- Chạy thật: 1 video ghép yêu thích + 1 tuyển tập chủ đề, Codex thật, ghi thời gian / tokens; HUMAN LEAD chọn + kiểm dấu.

## Manual test checklist (Tech Lead)

Không chạm database / security model; thêm route có auth + gọi AI CLI ngoài → manual test là gate trước merge.

- [ ] 2 mẫu khác nhau ("Gợi ý thêm" ra 2 mẫu mới), chữ đúng dấu, tiêu đề đọc rõ ở cỡ thumbnail nhỏ.
- [ ] Khổ thứ hai cùng phong cách; tải về đúng kích thước.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
