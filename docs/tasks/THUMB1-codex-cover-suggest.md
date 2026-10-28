# Task: THUMB1-codex-cover-suggest — Trang thumbnail cả bộ: Codex gợi ý 4 mẫu → chọn → dựng (tập + khai thị)

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, module + trang mới); dự phòng subagent `implementer` (Sonnet) cho test web / socket
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-28: "Với trang dựng thumnail cả bộ nên sửa lại luôn, dùng codex gợi ý 4 mẫu để user chọn sau đó render. Không cần các bước phức tạp như hiện tại" + "bắt đầu luôn với thumnail cho khai thị ghép vào thumail khai thị"; trả lời 3 câu hỏi cùng ngày: G1 nút trên web (8080 tự gọi Codex), G2 chữ khai thị = tiêu đề + TẬP N, G3 thay hẳn trang cũ.
- Parallel group: —
- Owned paths: `src/auto_short/packaging/cover.py`, `src/auto_short/packaging/cover_suggest.py` (mới), `src/auto_short/packaging/khaithi_thumbs.py` (mới), `src/auto_short/packaging/episode.py` (chỉ phần dựng cả bộ gọi thêm khai thị + zip), `src/auto_short/packaging/__main__.py`, `src/auto_short/web/episode_thumbs.py`, `src/auto_short/web/static/thumbs.html`, `src/auto_short/web/static/thumbs.js`, phần nút tải thumbnail khai thị trên trang tập khai thị (`src/auto_short/web/static/` file trang tập hiện có, chỉ thêm link), `src/auto_short/config.py` (mục `[thumbs]` mới), `config.example.toml`, `tests/test_packaging_cover.py`, `tests/test_cover_suggest.py` (mới), `tests/test_khaithi_thumbs.py` (mới), `tests/test_web_episode_thumbs.py`, contract này
- Dependencies: COV1 (#179/#180, ảnh mẫu + "TẬP N"), PKG2 (đường dựng thumbnail tập), CP8.9 (khai thị `<id>.kt`, `titles.json` / `review.json`)
- Base commit / branch: `62b9f65` (`origin/main`) / `feature/thumb1-codex-covers`
- Human Lead approval: APPROVED 2026-10-28 ("bắt đầu luôn" + G1–G3)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: (1) web 8080 lần đầu gọi một AI CLI bên ngoài (`codex exec`, quota ChatGPT của HUMAN LEAD) — tích hợp mới; (2) thay trang / API thumbnail cả bộ PKG2 (gỡ form A/B/C); (3) thêm artifact mới (thumbnail khai thị từng clip).

## Bối cảnh / quyết định

- COV1: thumbnail tập = ảnh bìa AI (tên kinh + chủ giảng vẽ sẵn, **khung trống**) + chữ "TẬP N" do code viết. Ảnh bìa đến nay do ORCHESTRATOR chạy Codex `image_generation` bằng tay, đo box bằng mắt rồi `cover install` (CLI). Trang `/playlists/<pid>/thumbs` vẫn là form PKG2 8 bước (kiểu A/B/C, gõ dòng, ảnh chung, thanh trượt, kiểu riêng bản dọc…) và bỏ qua form khi bộ có ảnh bìa.
- Video khai thị (`<id>.kt`, clip `k01`, `k02`…, 9:16 4–7 phút) chưa có thumbnail.
- D-THUMB1-1 (G1): trang có nút **"Gợi ý 4 mẫu"** → 8080 chạy job nền gọi `codex exec` (không `danger-full-access`; sandbox `workspace-write` trong thư mục tạm riêng; model / effort / timeout từ config) → Codex vẽ 4 ảnh bìa dọc khác phong cách **và tự đo khung trống** (ghi `boxes.json`). Trang hiện 4 mẫu đã viết thử chữ → HUMAN LEAD chọn 1.
- D-THUMB1-2: sau khi chọn, job thứ hai cho Codex vẽ **cùng phong cách** (ảnh đã chọn là ảnh tham chiếu `-i`) 3 ảnh còn lại: ngang tập, dọc khai thị, ngang khai thị. Ảnh khai thị có **một khung trống lớn** (đủ 3 dòng tiêu đề + 1 dòng "TẬP N"). Tổng 7 ảnh / bộ, không gọi AI mỗi tập / mỗi clip.
- D-THUMB1-3 (G2): thumbnail khai thị = ảnh bìa khai thị + tiêu đề clip (`review.json` override > `titles.json`, như tiêu đề đang in trong video) tự xuống 1–3 dòng + dòng nhỏ "TẬP N", căn giữa khung. Mỗi clip 2 khổ.
- D-THUMB1-4 (G3): trang mới chỉ còn: Gợi ý 4 mẫu → chọn → (3 ảnh còn lại) → **Dựng cả bộ** (tập + khai thị) → Tải zip. Gỡ form A/B/C, ảnh chung, thanh trượt, kiểu riêng bản dọc, nút "Xem trước" PKG2. Bộ đã có ảnh bìa (VLT, Địa Tạng) dùng tiếp; muốn đổi thì "Gợi ý 4 mẫu" lại.
- D-THUMB1-5: HUMAN LEAD là người kiểm dấu tiếng Việt (AI có thể vẽ sai dấu): trang hiện ảnh đủ lớn + nút phóng to; chọn = xác nhận. Không OCR tự động.

## Goal

Trên `/playlists/<pid>/thumbs`: bấm "Gợi ý 4 mẫu" → vài phút sau có 4 ảnh bìa dọc (đã viết thử "TẬP 1") → chọn 1 → hệ thống tự vẽ thêm bản ngang + 2 bản khai thị cùng phong cách → xem thử (tập 1 / tập cuối / 1 clip khai thị) → "Dựng cả bộ" ra thumbnail 2 khổ cho mọi tập **và mọi clip khai thị** của bộ → tải zip.

## Scope

- In scope:
  - **Config** `[thumbs]`: `codex_bin` (mặc định `codex`), `codex_model` (mặc định `gpt-6.1-sol`), `codex_effort` (`medium`), `codex_timeout_minutes` (30), `enabled` (true). Thiếu binary → nút báo "chưa cài Codex trên máy chủ", không crash.
  - **`packaging/cover_suggest.py`**: dựng prompt tiếng Việt (tên bộ kinh + chủ giảng từ `episode.header` của tập đầu bộ; ghi chú phong cách tùy chọn ≤ 200 ký tự từ người dùng; yêu cầu: chữ đúng dấu, không thêm chữ, khung trang trí để trống với nền phẳng tối đồng màu, không logo / watermark / chân dung người thật; 4 phong cách khác nhau rõ rệt; tự đo khung bằng Python/PIL trong sandbox và ghi `boxes.json`). Chạy `codex exec -C <tmp> --skip-git-repo-check -s workspace-write -m <model> -c model_reasoning_effort=<effort> -o <tmp>/last.txt [-i ref.png] -` với prompt qua stdin, timeout, kill cả nhóm tiến trình khi hủy / quá giờ. Validate đầu ra trước khi nhận: đúng tên file, PNG đọc được (probe), kích thước gần đúng tỉ lệ khổ, ≤ 15 MB, box nằm trong ảnh, đủ lớn (tái dùng `cover._box` sau chuẩn hóa), vùng box tương đối đồng màu (độ lệch chuẩn độ sáng dưới ngưỡng — bắt khung có chữ / không có khung). Ảnh lệch → loại mẫu đó, giữ mẫu khác; < 1 mẫu hợp lệ → job fail với lý do.
  - **Lưu trạng thái**: `output/_compilations/<pid>/cover/suggest/<run_id>/` (ảnh, `boxes.json`, `prompt.md`, `state.json`: phase `options` | `variants`, status, lỗi, mẫu đã chọn, tokens nếu đọc được từ log). Giữ 3 lượt gần nhất, xóa lượt cũ hơn (không đụng ảnh đã cài).
  - **Job**: chạy trong thread riêng của service thumbnail (không dùng làn `prepare` / `ai` / `render`, để không chặn và không bị hàng đợi prepare chặn); tối đa 1 job Codex toàn máy chủ; restart 8080 → job đang chạy thành `failed: máy chủ khởi động lại` (không chạy lại tự động). Hủy được.
  - **`cover.py`**: thêm khổ `kt_vertical`, `kt_landscape` vào `cover.json` (schema tăng, đọc được bản cũ); `install` từ ảnh của lượt gợi ý (cùng đường kiểm như CLI). CLI `cover install --shape` nhận thêm 2 khổ mới.
  - **`packaging/khaithi_thumbs.py`**: thumbnail mỗi clip khai thị × 2 khổ: tiêu đề (tái dùng `thumbnail._fit_line` / `_draw_text` / font Old Standard của COV1; tự xuống ≤ 3 dòng, co chữ vừa khung) + "TẬP N" nhỏ hơn ở dưới, cùng màu vàng kim + bóng như COV1. File `output/<id>.kt/thumbs/<clip>-<shape>-<key>.jpg` + `thumbs.json`; cache key gồm sha ảnh bìa, box, tiêu đề, số tập, layout version, font sha, khổ. Bộ không có ảnh khai thị → bỏ qua (ghi lý do), không fallback A/B/C.
  - **"Dựng cả bộ"** (job làn `render` như hiện tại): thumbnail tập (COV1) + thumbnail khai thị mọi clip của các tập trong bộ. Zip cả bộ gồm cả khai thị (`khai-thi/T<ep>_KT<NN>_<shape>.jpg`).
  - **Web**: trang `thumbs.html` / `thumbs.js` viết lại gọn: (1) trạng thái ảnh bìa hiện tại (4 khổ); (2) "Gợi ý 4 mẫu" + ô ghi chú phong cách tùy chọn + tiến trình / hủy; (3) lưới 4 mẫu (ảnh có "TẬP 1" viết thử, bấm để phóng to) + nút "Chọn mẫu này"; (4) sau khi có 3 ảnh còn lại: xem thử tập 1, tập cuối, 1 clip khai thị, 2 khổ + nút "Dùng bộ ảnh này" (cài) / "Vẽ lại 3 ảnh" / "Gợi ý lại"; (5) "Dựng cả bộ" + tiến trình + "Tải zip" + "Xem từng tập" (lưới hiện có). Trang tập khai thị: link tải thumbnail của từng clip khi đã có.
  - API mới dưới `/api/playlists/{pid}/thumbs/suggest…` (tạo lượt, xem trạng thái, chọn mẫu, cài, hủy) + phục vụ ảnh lượt gợi ý qua route có kiểm id / tên file (không path traversal, không symlink). Thumbnail khai thị: `/files/episodes/{id}.kt/thumbs/{name}`.
- Out of scope:
  - Thumbnail video ghép yêu thích (compilation) và video ghép chủ đề PKG3 (giữ nguyên).
  - Tự kiểm dấu bằng OCR; tự đăng thumbnail lên YouTube (PUB2 giữ nguyên, tự dùng file mới qua `episode.valid_files`).
  - Sửa box bằng tay trên web (CLI `cover install --box` vẫn còn cho trường hợp đặc biệt).
  - Đổi intro bản dọc VERT2 (vẫn dùng thumbnail tập).

## Authority / key decisions

- `docs/decisions/PKG-video-packaging-authorization.md` (đóng gói ACCEPTED), COV1 contract (D-COV1-1/2), CP8.9 (khai thị), CP8.3 (web auth / job / phục vụ file), HUMAN LEAD G1–G3 ở trên.
- Security: prompt chứa tên bộ kinh từ metadata YouTube + ghi chú người dùng → coi là dữ liệu, đặt trong khối trích dẫn của prompt; Codex chỉ ghi trong thư mục tạm; server chỉ nhận file đúng tên đã liệt kê, kiểm bằng probe; không truyền token / mật khẩu / đường dẫn ngoài thư mục tạm vào prompt. Route chỉ cho người đã đăng nhập.

## Implementation approach

- Tách logic thuần (prompt, validate, state) khỏi subprocess: `run_codex` nhận `runner` để test giả lập Codex (ghi file mẫu) — test không gọi Codex thật, không mạng.
- Đo "vùng đồng màu" bằng ffmpeg (`signalstats` / `crop` trên box) hoặc PIL nếu đã là dependency; không thêm dependency mới.
- Thumbnail khai thị tái dùng hàm dựng của COV1 (`cover.build_episode` tổng quát hóa thành nhiều dòng) thay vì viết encoder mới.
- Trang mới: tái dùng polling job / lưới tập / zip hiện có trong `thumbs.js`.

## Phải giữ nguyên

- Thumbnail tập của bộ đã có ảnh bìa (VLT, Địa Tạng): byte-identical khi không đổi ảnh (cache key COV1 không đổi).
- `episode.valid_files` / `build_episode` cho VERT2 intro và PUB2; bộ **chưa có** ảnh bìa vẫn dựng được thumbnail PKG2 mặc định ở backend (VERT2 intro cần), chỉ UI bị gỡ.
- Route tải từng file / zip hiện có (đường dẫn, kiểm hash); PKG3 thumbnail video ghép chủ đề.
- CLI `cover install|remove|show` cho 2 khổ cũ.

## Code bị thay / xóa

- `thumbs.html` / `thumbs.js`: form kiểu A/B/C, dòng tiêu đề, người giảng, ảnh dùng chung + gallery, thanh trượt focus, "Bản dọc dùng kiểu riêng", nút "Xem trước" → xóa.
- `episode_thumbs.py`: route `PUT …/thumbs/settings`, `POST …/thumbs/preview` và `SettingsIn` → xóa nếu không còn caller (GET settings / gallery asset: xóa nếu trang mới không dùng); test tương ứng trong `tests/test_web_episode_thumbs.py` → xóa / thay bằng test trang mới.
- `episode.read_settings` / `write_settings` / `preview`: giữ nếu backend PKG2 mặc định còn dùng; xóa phần chỉ phục vụ form cũ.

## Acceptance Criteria

1. Codex giả lập ghi 4 ảnh + `boxes.json` → lượt gợi ý `options` có 4 mẫu hợp lệ, mỗi mẫu có ảnh xem thử "TẬP 1"; mẫu sai tên / không đọc được / sai tỉ lệ / box ngoài ảnh / box không đồng màu bị loại với lý do; 0 mẫu hợp lệ → fail có lý do; timeout / hủy → kill tiến trình, status `failed` / `cancelled`.
2. Lệnh Codex dựng đúng: `-s workspace-write`, `-C <tmp>`, `--skip-git-repo-check`, model / effort từ config, prompt qua stdin, `-i` ảnh tham chiếu ở phase 2; không bao giờ `danger-full-access`; prompt chứa tên kinh / chủ giảng / ghi chú trong khối dữ liệu.
3. Chọn mẫu → phase `variants` sinh đúng 3 ảnh (ngang, dọc KT, ngang KT) cùng validate; "Dùng bộ ảnh này" cài 4 khổ vào `cover.json` (schema mới, đọc được `cover.json` COV1 cũ) atomically; lượt cũ quá 3 bị xóa, ảnh đã cài không bị xóa.
4. Thumbnail khai thị: tiêu đề override > AI, ≤ 3 dòng vừa khung, "TẬP N", 2 khổ đúng kích thước `EPISODE_SIZES`; cache: đổi tiêu đề / ảnh / box → dựng lại, không đổi → dùng lại; bộ không có ảnh KT → bỏ qua có lý do.
5. "Dựng cả bộ" dựng tập + khai thị; zip có cả `khai-thi/…`; thumbnail tập VLT / Địa Tạng không đổi byte khi ảnh bìa không đổi.
6. Web: trang mới không còn form A/B/C; API suggest yêu cầu đăng nhập, chặn id lượt / tên file lạ (traversal, symlink); chỉ 1 job Codex cùng lúc (lượt thứ 2 → 409); restart → job đang chạy thành `failed`; thiếu binary → 503 / thông báo rõ.
7. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

Prefix: `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q`.

- `<prefix> tests/test_cover_suggest.py tests/test_packaging_cover.py` — AC 1–3.
- `<prefix> tests/test_khaithi_thumbs.py tests/test_packaging_episode.py` — AC 4–5.
- `<prefix> tests/test_web_episode_thumbs.py tests/test_publish_thumbs.py tests/test_vertical_silence_intro.py` — AC 5–6 (TestClient: ORCHESTRATOR chạy ngoài sandbox).
- `<prefix> -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 7.
- Chạy thật (ORCHESTRATOR, 8080 ghim commit nhánh): 1 bộ chưa có ảnh bìa (Cảm Ứng Thiên hoặc Thập Thiện) — Gợi ý 4 mẫu bằng Codex thật, ghi thời gian + tokens; HUMAN LEAD chọn + kiểm dấu; dựng cả bộ gồm khai thị; HUMAN LEAD xem thumbnail khai thị.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model; chạm web API nội bộ có auth (thêm route) và gọi AI CLI ngoài → manual test là gate trước merge.

- [ ] Gợi ý 4 mẫu ra 4 ảnh khác phong cách, chữ đúng dấu, "TẬP 1" nằm gọn trong khung.
- [ ] Chọn mẫu → 3 ảnh còn lại cùng phong cách; xem thử tập 1 / tập cuối / khai thị ổn.
- [ ] Dựng cả bộ + tải zip có thumbnail khai thị; tiêu đề dài 3 dòng vẫn vừa khung.
- [ ] Bộ VLT / Địa Tạng: trang hiện ảnh bìa đang dùng, thumbnail không đổi.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
