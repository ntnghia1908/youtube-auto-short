# Task: CP8.17 — Tự tick "Đã đăng bài", zip không tick "Đã đăng", tên zip + "Tải cả hai"

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project; task có UI + route file, cần review diff riêng.
- Base commit / branch: `d0c1517` (`origin/main`) / `feature/cp8.17-download-rules` (implement trong worktree `../youtube-auto-short-cp817`)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-30: APPROVE D1–D5, Q1 chọn (a))
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: (a) đổi luật đã duyệt CP8.7 "tải về = đã đăng" (CP8.3 W8: zip không còn tick); (b) đổi public API web (route file mới `all.zip`, field mới trong `GET /api/episodes/{id}`, tên file trong `Content-Disposition`); (c) đổi hành vi tick CP8.15 P8 (tick tự động). Không thêm dependency, không đổi schema `publish.json` / `posts.json`, không đổi stage CP2–CP9, không đổi job model.

## Bối cảnh

Góp ý HUMAN LEAD 2026-09-30 khi test CP8.16 trên 8080 (`docs/tasks/CP8.16-post-tab-auto.md` Result; `docs/workflow/current-state.md` CP8.17 PROPOSED):

1. Tự tick "Đã đăng bài" khi đã "Sao chép bài" **và** "Tải ảnh" của bài đó.
2. Tải zip cả tập (Short hoặc khai thị) **không** tự tick "Đã đăng"; chỉ tải từng Short mới tick.
3. Tên zip ghi rõ bộ kinh + Short / khai thị **và** nút "Tải cả hai" (một zip, hai thư mục) — HUMAN LEAD 2026-09-30: làm cả hai.

Hiện trạng (code `d0c1517`):

- `web/app.py` route `GET /files/{id}/shorts.zip` gọi `_mark_downloaded(episode_id, <mọi clip trong zip>)`; `GET /files/{id}/{clip}.mp4?download=1` gọi `_mark_downloaded(episode_id, [clip])` (CP8.3 W8 "tải về = đã đăng").
- `review/names.py` `zip_name` → `Tập<N>_Shorts.zip` / `Tập<N>_KhaiThị.zip`; không có tên bộ kinh (hai tập số 29 của hai bộ kinh khác nhau cho cùng tên zip).
- `web/static/app.js` trang Bài đăng: "Sao chép bài" = `copyTitleButton(cur.text)` (không có callback); "Tải ảnh" = link `/files/post-images/<name>?download=1` (route chung cả thư viện, server không biết bài nào); tick "Đã đăng bài" = `POST …/posts/{clip}/posted`.

## Goal

Đăng một bài cộng đồng (sao chép bài + tải ảnh) xong thì bài tự được tick "Đã đăng bài". Tải zip cả tập không còn làm Short thành "Đã đăng". File zip tải về nhìn tên là biết bộ kinh nào, tập nào, Short hay khai thị; có một nút tải cả Short lẫn khai thị của một video trong một zip.

## Quyết định (HUMAN LEAD 2026-09-30: APPROVE D1–D5, Q1 = (a))

- **D1. Tự tick "Đã đăng bài" — theo dõi ở trình duyệt, không đổi server.**
  - Trang Bài đăng ghi nhớ cho từng bài (`<episode_id>/<clip_id>`) hai dấu: *đã sao chép* (kèm chính text đã sao chép) và *đã tải ảnh* (kèm tên ảnh). Khi cả hai dấu còn hiệu lực và bài chưa tick → trang gọi route có sẵn `POST …/posts/{clip}/posted {value: true}` (CP8.15 P9), hiện tick như khi bấm tay. Thứ tự hai thao tác không quan trọng.
  - Dấu *đã sao chép* chỉ đặt khi sao chép **thành công** (`copyText` trả `true`); khi rơi vào ô dự phòng "Giữ vào ô để copy" (CP8.3 W6) thì không tính — tick tay.
  - Dấu mất hiệu lực khi text bài (`text` đầy đủ P4) khác lúc sao chép, hoặc ảnh của bài khác lúc tải (đổi ảnh / soạn lại / sửa đoạn / đổi link sau khi sao chép → phải làm lại thao tác đó).
  - Lưu trong `localStorage` của trình duyệt (giữ qua tải lại trang — điện thoại hay nạp lại tab khi chuyển sang app YouTube rồi quay về); không đọc / ghi được `localStorage` → giữ trong bộ nhớ trang, tính năng vẫn chạy trong một lần mở trang. Sau khi tự tick, hai dấu của bài đó bị xóa: bỏ tick tay thì **không** tự tick lại cho tới khi làm lại cả hai thao tác.
  - Bài đã tick: sao chép / tải ảnh không đổi gì (không ghi lại `posted_at`).
  - Không đổi `posts.json` (P7), không thêm route. Hệ quả chấp nhận: dấu theo từng thiết bị / trình duyệt (sao chép trên điện thoại, tải ảnh trên máy tính → không tự tick).
  - Phương án khác (không đề xuất): ghi `copied_at` / `image_downloaded_at` vào `posts.json` qua route mới — đổi schema + API cho một tiện ích UI, và route tải ảnh hiện không gắn với bài nào.
- **D2. Bài không có ảnh tải được** (`image` rỗng hoặc `image_missing` → không có nút "Tải ảnh") — Q1, HUMAN LEAD chọn (a): chỉ cần "Sao chép bài" (thành công) là tự tick (không còn thao tác nào khác để chờ). Phương án (b) không tự tick: không chọn.
- **D3. Zip cả tập không tick "Đã đăng"** (sửa CP8.3 W8 "tải về = đã đăng").
  - `GET /files/{id}/shorts.zip` và zip "Tải cả hai" (D5) **không** gọi `mark_downloaded`. Chỉ `GET /files/{id}/{clip}.mp4?download=1` (nút "Tải về" từng Short) tick, giữ nguyên luật CP8.7 cho nó (idempotent, tick trước khi gửi file, lỗi ghi không chặn tải).
  - Tick đã có trong `publish.json` (kể cả tick do zip trước đây) giữ nguyên; không migrate.
  - Hệ quả: "Xong" (W10 L4), `publish_group`, gợi ý dọn `all_published` (W9) không còn đạt được bằng một lần tải zip — phải tải từng Short hoặc tick tay. Luật của chúng không đổi.
  - UI: bỏ việc làm mới trang 1,5–2 s sau khi bấm nút zip (không còn gì đổi); giữ cho nút "Tải về" từng Short.
- **D4. Tên zip có tên bộ kinh.**
  - `<series>_Tập<episode>_Shorts.zip` / `<series>_Tập<episode>_KhaiThị.zip`, vd `Thập Thiện Nghiệp Đạo Kinh_Tập29_Shorts.zip`.
  - `<series>` = `titles.json` `header.fields.series` của chính tập đó (tập khai thị: `titles.json` của `<id>.kt`; không có thì của tập Short gốc), làm sạch theo luật W8 (`clean_part`: giữ dấu tiếng Việt + khoảng trắng), cắt ≤ 80 byte UTF-8 ở ranh giới từ. Không có / rỗng → tên cũ `Tập<episode>_Shorts.zip` / `Tập<episode>_KhaiThị.zip`.
  - Tên entry trong zip và tên file Short tải lẻ (`Tập<episode>_S<NN>_<title>.mp4`, `…_KT<NN>_…`) **không đổi**.
  - Nhãn nút: "Tải tất cả Short (.zip)" ở view Shorts, "Tải tất cả khai thị (.zip)" ở view Khai thị (thay "Tải tất cả (.zip)").
  - Phương án khác (không đề xuất): dùng "Tên bộ kinh" của playlist (CP8.11) — tập lẻ không có, và header video mới là tên đã hiện trên Short.
- **D5. Nút "Tải cả hai" — một zip, hai thư mục.**
  - Route mới `GET /files/{id}/all.zip` (`id` = tập Short `<vid>` hoặc tập khai thị `<vid>.kt`; cùng kết quả): zip stream `ZIP_STORED` như `shorts.zip`, entry `Shorts/<tên W8>` (mọi Short `rendered` của `<vid>`, thứ tự manifest) rồi `KhaiThị/<tên W8>` (của `<vid>.kt`); cờ UTF-8. Cookie + validate id như `shorts.zip` (W2). 404 khi một trong hai tập không có Short `rendered` nào (khi đó nút zip từng loại là đủ). Không tick (D3). Tập archived vẫn tải được.
  - Tên: `<series>_Tập<episode>_Shorts+KhaiThị.zip` (`<series>` / `<episode>` của tập Short gốc, luật D4; không có series → `Tập<episode>_Shorts+KhaiThị.zip`).
  - `GET /api/episodes/{id}` thêm `zip_all_url`, `zip_all_name` (`null` khi route sẽ 404). UI: nút "Tải cả hai (.zip)" cạnh nút zip ở view Shorts và view Khai thị, ẩn khi `zip_all_url` là `null`.
  - `all.zip` và `shorts.zip` không phải `.mp4` nên không đụng namespace clip id (W2).

## Scope

- In scope: `src/auto_short/review/names.py` (`zip_name` thêm series, tên zip cả hai), `src/auto_short/web/episodes.py` (series cho tên zip, danh sách file cả hai, field `zip_all_*`), `src/auto_short/web/app.py` (route `all.zip`, bỏ tick ở `shorts.zip`), `src/auto_short/web/static/` (`app.js`, `episode.html`, CSS nếu cần: dấu sao chép / tải ảnh + tự tick, nhãn nút, nút "Tải cả hai", bỏ làm mới sau zip), tests, docs (Documentation impact).
- Out of scope: schema `publish.json` / `posts.json`; luật "Xong" / gợi ý dọn; tên file Short tải lẻ và entry zip; tick tự động "Đã đăng" của Short theo cách khác; zip cả bộ kinh; CLI; job runner (`web/jobs.py`), `post/` (file của FIX-ollama-wait — không đụng); file framework (FW-starter-kit).

## Documentation impact

- `docs/decisions/CP8.3-web-contract.md`: W8 § Tên file tải về (D4, D5), § Đã đăng — "tải về = đã đăng" (D3); W6 (nhãn nút, "Tải cả hai"); W7 (route `all.zip`, tên `shorts.zip`, `zip_all_url` / `zip_all_name`); dòng "Accepted by" + "Task contract" — ghi "Sửa đổi CP8.17".
- `docs/decisions/CP8.15-community-post-contract.md`: P8, P9 (D1, D2) — ghi "Sửa đổi CP8.17".
- `docs/decisions/CP8.9-khai-thi-contract.md` K8: pointer tên zip khai thị → W8.
- `docs/ai/project-profile.md` dòng module `web/`; `AUTO_SHORT_CHECKPOINT_PLAN.md`; `docs/workflow/current-state.md` (ORCHESTRATOR).

## Implementation approach

- `review/names.py`: `zip_name(episode, *, khaithi=False, series=None, both=False)` (hàm thuần; series qua `clean_part` + `truncate_utf8(…, 80)`).
- `web/episodes.py`: helper đọc `header.fields.series` (cạnh `_label`), `zip_download_name` truyền series; hàm mới trả danh sách file hai nhóm + tên cho `all.zip`; `zip_all_url` / `zip_all_name` trong view tập.
- `web/app.py`: nhánh `name == "all.zip"` trong route `files` (dùng lại `_zip_stream` với tên entry có tiền tố thư mục); bỏ `_mark_downloaded` ở nhánh `shorts.zip`.
- `web/static/app.js`: `copyTitleButton(text, onCopied?)` (callback chỉ khi copy thành công; chỗ gọi cũ không đổi); trang Bài đăng: kho dấu nhỏ (`localStorage` bọc try/catch, dự phòng bộ nhớ), listener click trên link "Tải ảnh", hàm kiểm "đủ điều kiện" rồi gọi `togglePosted` hiện có; nút zip.
- IMPLEMENTER tự quyết chi tiết bên trong các điểm trên; lệch D1–D5 → dừng, báo ORCHESTRATOR.

## Acceptance Criteria

1. D3: `GET /files/{id}/shorts.zip` không ghi / không đổi `publish.json` (tập Short và khai thị); `GET /files/{id}/{clip}.mp4?download=1` vẫn tick như CP8.7; tick có sẵn không đổi sau khi tải zip.
2. D4: `Content-Disposition` của `shorts.zip` và `zip_name` trong API = `<series>_Tập<N>_Shorts.zip` / `…_KhaiThị.zip`; không có series → tên cũ; series có ký tự cấm / quá dài được làm sạch + cắt ≤ 80 byte; tên entry và tên Short tải lẻ không đổi.
3. D5: `GET /files/{id}/all.zip` (gọi bằng `<vid>` và `<vid>.kt`) trả zip `ZIP_STORED` có đúng entry `Shorts/…` rồi `KhaiThị/…` theo thứ tự manifest, sha256 entry = manifest, Short đã xóa không có; tên theo D5; 404 khi thiếu một trong hai; 401 khi không cookie; không tick; `GET /api/episodes/{id}` có `zip_all_url` / `zip_all_name` (`null` khi thiếu).
4. D1, D2: test JS thuần cho phần logic tách được (dấu, mất hiệu lực khi text / ảnh đổi, xóa dấu sau khi tick, không tự tick lại sau khi bỏ tick) nếu repo có khung chạy; nếu không — `node --check app.js` + harness tạm (không commit) như CP8.16, và manual test là gate cho phần giao diện.
5. Toàn bộ test suite PASS; test CP8.7 / CP8.9 / CP8.5 về zip được sửa **chỉ** ở chỗ hành vi đổi theo D3–D4 (mỗi chỗ ghi lý do trong Result), không nới assertion khác.

## Required verification

- `conda run -n auto-short python -m pytest -q -n auto` — toàn bộ PASS (AC 1–5), theo Test policy `docs/ai/project-profile.md` §8.
- `node scripts/framework-check.mjs` — exit 0.
- `node --check src/auto_short/web/static/app.js`.
- Chạy thật trên bản sao dữ liệu (không ghi `work/` / `output/` chính), server test 8081: một video có cả Short + khai thị → tải `shorts.zip` của hai tập và `all.zip`, ghi vào Result: tên file nhận được, số entry từng thư mục, `publish.json` trước / sau (không đổi); tải một Short lẻ → tick.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API contract (route `all.zip`, field mới, tên file) và luật "tải về = đã đăng" → manual test là gate trước integration. Server test 8081, dữ liệu bản sao (hoặc 8080 nếu HUMAN LEAD chọn như CP8.16).

- [ ] Điện thoại, tab Bài đăng: "Sao chép bài" rồi "Tải ảnh" (và thứ tự ngược lại) → bài tự tick "Đã đăng bài"; chỉ làm một trong hai → chưa tick.
- [ ] Sao chép, chuyển sang app YouTube, quay lại (trang nạp lại), "Tải ảnh" → vẫn tự tick.
- [ ] Bỏ tick tay → không tự tick lại; làm lại cả hai thao tác → tick lại.
- [ ] Bài không có ảnh: "Sao chép bài" → tự tick (Q1 = a).
- [ ] "Tải tất cả Short (.zip)" / "Tải tất cả khai thị (.zip)": tên file có tên bộ kinh + tập + loại; các Short **không** thành "Đã đăng".
- [ ] "Tải về" một Short: vẫn tick "Đã đăng".
- [ ] "Tải cả hai (.zip)": một file, hai thư mục `Shorts/` và `KhaiThị/`, giải nén được trên điện thoại / máy tính; nút ẩn ở video chỉ có một loại.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
