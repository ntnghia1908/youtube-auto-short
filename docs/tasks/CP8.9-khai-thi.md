# Task: CP8.9 — Video khai thị (thời lượng tùy chỉnh)

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `194c7f4` (`docs/cp8.4-skip`, trên `origin/main` `7274d8e`) / `feature/cp8.9-khai-thi`
- Human Lead approval: accepted (HUMAN LEAD 2026-09-28: APPROVE TASK, D1–D6 theo đề xuất; K1–K9 dưới đây là chi tiết hóa D1–D6, không thêm quyết định mới)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: sửa CP1 §2/§3 (loại output mới, thời lượng không cố định 30–180 s); thêm artifact theo episode và đổi config hash của analysis/selection (CP2 D7, CP4, CP5 B3/B9); thêm prompt selection mới; đổi HTTP API (CP8.3 W3, W7) và tên file tải về (W8). Không thêm dependency, không đổi security model, không đổi hành vi / hash của tập Short hiện có.

## Goal

Từ web (và CLI), người dùng gửi một video YouTube kèm lựa chọn **Khai thị** và khoảng thời lượng **min–max phút**. Pipeline tạo nhiều video khai thị 9:16 (cùng template, header, tiêu đề AI như Short), mỗi video trọn một ý, dài trong khoảng đã chọn (tính sau rút khoảng lặng), nằm trong một tập riêng không ghi đè các Short của cùng video. Xem, sửa tiêu đề, xóa, tải về, tick "Đã đăng" như Short.

## Scope

- In scope:
  - K1 tập khai thị riêng + artifact tham số `khaithi.json`; K2 thời lượng hiệu lực cho analysis/selection; K3 prompt selection `kt1`; K4 window lớn hơn; K5 dùng lại video nguồn + transcript của tập Short; K6 CLI; K7 web; K8 tên file / hashtag / bộ kinh; K9 config `[khaithi]`.
  - Titling, review (sửa title, xóa / khôi phục), render, `publish.json`, archive, xóa tập, tab Bộ nhớ chạy trên tập khai thị như tập thường (không code riêng nếu không cần).
  - Docs: decision record mới `docs/decisions/CP8.9-khai-thi-contract.md` (canonical owner của K1–K9); pointer ở CP1 §2/§3, CP2 D3, CP4 (params thời lượng), CP5 B3/B9, CP8.3 W3/W7/W8/W10; project profile (authority list, module map); README (usage); `AUTO_SHORT_CHECKPOINT_PLAN.md` (mục CP8.9); `config.example.toml`; `docs/workflow/current-state.md`; Result của contract này.
  - Tests + chạy thật trên scratch.
- Out of scope:
  - Khung ngang 16:9 (backlog), video > 15 phút, upload YouTube (CP8.4 đã bỏ).
  - Nút khai thị cho cả bộ kinh / xếp hàng hàng loạt; trạng thái "Xong" của bộ kinh tính khai thị (D6: chỉ tính Short).
  - Đổi prompt titling, layout render, luật title (≤ 60 ký tự giữ nguyên).
  - Khử trùng dung lượng hardlink trong tab Bộ nhớ (ghi vào Known limitations).
  - Sửa web đang chạy ở worktree `../youtube-auto-short-web` (HUMAN LEAD tự chuyển sau merge).

## Authority / key decisions

- Authority: CP1 §2–§5, §8; CP2 D3–D7; CP4 (candidates, `params`); CP5 B2, B3, B9; CP6; CP7; CP8 E2–E5; CP8.2 T1–T7; CP8.3 W3–W10 (+ CP8.5–CP8.8).
- Quyết định (D1–D6 HUMAN LEAD 2026-09-28, chi tiết hóa):
  - **K1 Tập khai thị (D1, D3):** loại output "khai thị" = video 9:16 cùng template CP7, dài hơn Short, đăng như video dọc thường (không phải YouTube Short khi > 3 phút). Mỗi nguồn có tối đa **một** tập khai thị, episode id `<base_id>.kt` (`base_id` = id CP2 D3 của nguồn; hợp lệ theo regex CP2 D3; video id YouTube không có `.` nên không trùng). Workspace `work/<base_id>.kt/`, output `output/<base_id>.kt/`. Loại tập xác định **chỉ** bởi file `work/<id>/khaithi.json` (không suy từ hậu tố):
    ```json
    {"schema_version": 1, "kind": "khaithi", "base_episode_id": "rbjfCfFq3Dk", "min_minutes": 5, "max_minutes": 10}
    ```
    Ghi atomic, thứ tự key cố định, không timestamp; viết bởi `run` (CLI / web) trước khi chạy stage; không phải stage (không entry trong manifest), như `review.json`. Sai schema / giá trị ngoài K2 → lỗi user-facing, stage không chạy, manifest không đổi.
  - **K2 Thời lượng (D2):** `min_minutes`, `max_minutes` nguyên, `1 ≤ min < max ≤ [khaithi] max_minutes_limit` (mặc định 15). Tính trên thời lượng thực tế sau rút khoảng lặng (như CP1 §3 sửa đổi 2026-09-26). Với tập khai thị, analysis dùng `min_duration = 60·min`, `max_duration = 60·max`, `target_min = min_duration`, `target_max = max_duration` thay cho giá trị `[analysis]`; các key `[analysis]` khác giữ nguyên. Giá trị hiệu lực nằm trong `used_config` (config hash) và `candidates.json` `params` → đổi min–max làm analysis và các stage sau stale (CP2 D6); đổi thời lượng Short trong `[analysis]` không làm tập khai thị stale. Tập Short: `used_config`, `params`, config hash **không đổi byte nào** (không Short nào stale sau khi nâng cấp).
  - **K3 Prompt (D4):** thêm prompt selection `kt1` (dựa trên v3, cùng B11 head cut, cùng format dòng unit / `RESPONSE_SCHEMA`): nhiệm vụ là "video khai thị ngắn độc lập"; thời lượng bắt buộc/lý tưởng lấy từ placeholder điền bằng giá trị hiệu lực K2 (phút và giây), ví dụ tính thời lượng đổi cho phù hợp độ dài. `prompt_sha256` tính trên template (có placeholder), giá trị điền nằm trong config hash (như `head_cut_words`). Tập khai thị dùng `[khaithi] prompt_version` (mặc định `kt1`); tập Short vẫn `[selection] prompt_version` (`v3`), prompt v1–v3 giữ nguyên văn. Chọn cuối (B6), validation (B8, dùng min/max hiệu lực), schema `clips.json` / `selection_log.json` không đổi; `max_clips`, `min_score` dùng chung `[selection]`.
  - **K4 Window:** tập khai thị dùng `max_window_words = max([selection] max_window_words, [khaithi] window_words_per_minute × max_minutes)` (mặc định `window_words_per_minute = 400`, ≈ 2 lần tốc độ nói, để window con chồng lấn chứa được candidate dài nhất); giá trị hiệu lực vào config hash + `params`. `num_ctx` dùng `[selection]`; chạy thật phải ghi `prompt_eval_count` lớn nhất so với `num_ctx` (vượt / sát → báo, không tự đổi `num_ctx`).
  - **K5 Dùng lại (D3):** ingest tập khai thị YouTube: nếu `work/<base_id>/` có ingest `done`, cùng video id, cùng `ingest.youtube_format`, file nguồn còn (không archived) và khớp sha256 trong manifest → hardlink (lỗi → copy) sang `work/<base_id>.kt/source.<ext>` thay vì tải; không thì tải như CP2 D4. Nguồn local: không copy (CP2 D4), chỉ ghi manifest. Transcript: nếu tập gốc có transcript `done`, cùng source sha256 và cùng `used_config` transcript → copy `transcript.json` (+ artifact phụ của stage, nếu có) và ghi manifest như stage đã chạy với provenance không đổi; không thì chạy CP3 bình thường. Không ghi / đổi gì trong `work/<base_id>/`. Tập gốc không bắt buộc phải có.
  - **K6 CLI (D5):** `auto-short run <source> --khai-thi --min-minutes N --max-minutes M` (thiếu min/max → `[khaithi] default_min_minutes` / `default_max_minutes` = 5 / 10) → episode `<base_id>.kt` (`--episode-id X` đổi `base_id`); ghi / cập nhật `khaithi.json` rồi chạy pipeline CP8 như thường. `--min/--max-minutes` không có `--khai-thi` → lỗi. Lệnh từng stage (`analysis <id>.kt`, …) và `title`, `status` tự đọc `khaithi.json`. `status` hiện loại + min–max.
  - **K7 Web (D5):** `SubmitIn` thêm `kind: "short" | "khaithi"` (mặc định `"short"`), `min_minutes`, `max_minutes` (int; chỉ với `khaithi`; sai → 422 message tiếng Việt). `kind: "khaithi"` chỉ cho URL một video (playlist → 422). Luồng như W4 trên episode `<video_id>.kt` (job trùng → 200 `created: false`, archived → 409, ổ đầy → 507, preflight). Tập khai thị đã có với min–max khác → job cập nhật `khaithi.json` rồi pipeline tự chạy lại từ analysis; UI hỏi xác nhận trước ("thay toàn bộ video khai thị cũ, tick Đã đăng cũ thành bản cũ"). Form trang chủ: chọn "Short" / "Khai thị", khi chọn khai thị hiện hai ô phút (mặc định 5–10, giới hạn 1–15). `GET /api/episodes` / `GET /api/episodes/{id}` thêm `kind` (`"short"` | `"khaithi"`), `min_minutes`, `max_minutes`, `base_episode_id` (null với Short) và `khaithi_episode_id` ở tập Short khi có tập khai thị. UI: nhãn "Khai thị m–n phút" ở danh sách và trang tập; link qua lại giữa trang tập Short và trang tập khai thị cùng video; trang tập Short có nút "Tạo video khai thị" (hai ô phút, cùng API).
  - **K8 Tên file, hashtag, bộ kinh (D5, D6):** tập khai thị tải về `Tập<episode>_KT<NN>_<title>.mp4`, zip `Tập<episode>_KhaiThị.zip` (`<episode>`, `<NN>`, làm sạch như W8; `<episode>` không có → `base_id`, không kèm `.kt`). Hashtag Copy: như tập gốc `base_id` (bộ kinh chứa `base_id` → danh sách của bộ kinh, CP8.8 H4). Bộ kinh: trạng thái / "Xong" / đếm của từng tập chỉ theo tập Short (không đổi); dòng tập có link "Khai thị" khi `work/<video_id>.kt/` tồn tại. Trang chủ mục "Tập lẻ": tập khai thị có `base_id` thuộc bộ kinh đã lưu không hiện ở đây (như tập Short của nó); còn lại hiện với nhãn. "Xong" (W10 L4) tính riêng cho tập khai thị ở trang tập của nó.
  - **K9 Config `[khaithi]`:** `default_min_minutes = 5`, `default_max_minutes = 10`, `max_minutes_limit = 15`, `prompt_version = "kt1"`, `window_words_per_minute = 400`; validate khi load (như các section khác). Chỉ các giá trị hiệu lực (K2–K4) vào config hash; default và limit là execution-only.

## Implementation approach

- Hàm thuần đọc / kiểm `khaithi.json` và tính tham số hiệu lực (một chỗ, dùng chung analysis / selection / CLI / web); analysis và selection nhận config hiệu lực thay vì đọc `config.analysis` / `config.selection` trực tiếp cho các key K2–K4.
- Prompt `kt1` thêm vào `PROMPTS` như v3; render placeholder thời lượng trong `system_prompt`.
- Ingest / transcript: nhánh dùng lại K5 trước khi tải / lấy transcript; manifest vẫn theo CP2.
- Web: `api_submit` rẽ nhánh theo `kind`; `episodes.episode_view` / `list_episodes` / `names` / `playlists` nhận biết tập khai thị qua `khaithi.json`.
- Thứ tự gợi ý: config + tham số hiệu lực + analysis → selection `kt1` → ingest/transcript dùng lại → CLI → web API → UI → docs.

## Acceptance Criteria

1. Tập Short (không có `khaithi.json`): config hash, `used_config`, `candidates.json` `params`, prompt và kết quả mọi stage giống hệt trước; một workspace Short tạo bởi code cũ được skip toàn bộ (không stage nào stale). Test cũ vẫn pass.
2. `run --khai-thi --min-minutes 5 --max-minutes 10` tạo `work/<id>.kt/khaithi.json` đúng schema; mọi candidate và clip có `duration` trong [300, 600] s; `candidates.json` `params` ghi giá trị hiệu lực; `selection_log.json` ghi `prompt_version` `kt1` và system prompt đã điền 5–10 phút.
3. Đổi min–max của tập khai thị → analysis, selection, titling, render stale và chạy lại; chạy lại cùng min–max → skip toàn bộ. Đổi `[analysis] min_duration/max_duration` → tập khai thị không stale, tập Short stale như trước.
4. `min ≥ max`, `min < 1`, `max > max_minutes_limit`, không phải số nguyên, `khaithi.json` hỏng → lỗi rõ ràng (CLI exit ≠ 0 / web 422), không stage nào chạy, manifest không đổi.
5. K5: có tập Short cùng video đã ingest + transcript `done` → tập khai thị không gọi downloader, không gọi fetcher/Whisper; source là hardlink (cùng inode) hoặc bản copy cùng sha256; `transcript.json` giống hệt; `work/<id>/` không đổi file nào. Tập gốc archived / không có / khác format → tải bình thường.
6. K4: candidate dài nhất (`max_minutes`) luôn nằm trọn trong ít nhất một window; không có `SelectionError` "more than max_window_words" với max = 15 phút trên dữ liệu test.
7. Web: `POST /api/episodes` với `kind: "khaithi"` hợp lệ → 202, job trên `<video_id>.kt`; giá trị sai / kèm playlist → 422; job trùng → 200 `created: false`; archived → 409; chưa đăng nhập → 401. `GET` trả `kind`, `min_minutes`, `max_minutes`, `base_episode_id`, `khaithi_episode_id` đúng.
8. Tên file tải về / zip của tập khai thị theo K8; Copy dùng hashtag của bộ kinh chứa `base_id`; trạng thái / "Xong" / đếm bộ kinh không đổi khi có tập khai thị; tập khai thị của video thuộc bộ kinh không hiện ở "Tập lẻ".
9. Sửa title, xóa / khôi phục, tick "Đã đăng", xóa tập, archive hoạt động trên tập khai thị; xóa / archive tập Short không làm hỏng tập khai thị (và ngược lại).
10. `config.example.toml` có `[khaithi]` với giá trị K9; config sai → lỗi load rõ ràng.

## Required verification

- `pytest -q` — toàn bộ, gồm test mới cho AC1–AC10 (AC1 có test so sánh config hash / `params` tập Short với giá trị cố định trước thay đổi).
- `node scripts/framework-check.mjs` — PASS.
- Chạy thật trên scratch (config trỏ thư mục tạm; hardlink một tập đã có từ `work/` chính để kiểm K5; Ollama `127.0.0.1:11437`; không đụng `work/` / `output/` chính và web đang chạy): `run --khai-thi --min-minutes 5 --max-minutes 10` trên một video thật tới render. Ghi: số candidate / clip, thời lượng từng video, thời gian từng stage, số window và `prompt_eval_count` lớn nhất so với `num_ctx`, xác nhận downloader / Whisper không chạy (K5), sha256 `work/` chính không đổi. Web scratch (cổng khác 8080): gửi `kind: "khaithi"` qua curl, xem `GET` và tên file tải về.
- Bằng chứng cảm quan: gửi HUMAN LEAD 1–2 video khai thị mẫu để nghe / xem (trọn ý, điểm đầu / cuối).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API contract (trường mới của `POST` / `GET /api/episodes`) — manual test là gate trước integration. Không chạm database, không đổi security model.

- [ ] Trang chủ: chọn "Khai thị", đặt 5–10 phút, gửi một video → tiến độ, xong có nhãn "Khai thị 5–10 phút", các video dài đúng khoảng.
- [ ] Trang tập Short → "Tạo video khai thị"; link qua lại hai trang tập.
- [ ] Nghe / xem ít nhất 2 video khai thị: trọn ý, header + tiêu đề đúng; sửa tiêu đề + render lại một video.
- [ ] Tải về (tên `Tập<n>_KT<NN>_…`, zip), Copy tiêu đề (hashtag bộ kinh), tick Đã đăng; bộ kinh vẫn đếm như cũ.
- [ ] Gửi lại cùng video với min–max khác → hộp xác nhận → chạy lại từ analysis.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
