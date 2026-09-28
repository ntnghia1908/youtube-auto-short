# CP8.9 — Khai thị Contract (video dài, thời lượng tùy chỉnh)

| Metadata | Value |
|---|---|
| Status | ACCEPTED (chờ review / manual test HUMAN LEAD) |
| Accepted by | HUMAN LEAD 2026-09-28: APPROVE TASK, D1–D6 (K1–K9 là chi tiết hóa); sửa đổi A1 cùng ngày (trong lúc IN_PROGRESS) |
| Checkpoint | CP8.9 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP8.9 |
| Task contract | `docs/tasks/CP8.9-khai-thi.md` |
| Builds on | CP1 §2–§5, §8; CP2 D3–D7; CP4 A8, A10, A11; CP5 B2, B3, B8, B9, B11; CP6; CP7; CP8 E2–E5; CP8.2; CP8.3 W3–W10 |

File này là **canonical owner** của loại output "khai thị": tập khai thị và `khaithi.json` (K1), thời lượng hiệu lực (K2), prompt selection `kt1` (K3), window (K4), dùng lại nguồn + transcript của tập Short (K5), CLI (K6), web (K7 + A1), tên file / hashtag / bộ kinh (K8 + A1), config `[khaithi]` (K9). Nơi khác chỉ trỏ tới đây. Mọi điều không nói ở đây giữ nguyên contract gốc (stage, schema artifact, render, titling, review, publish, archive, xóa tập). Thay đổi cần decision gate mới với HUMAN LEAD.

Implementation tham chiếu: `src/auto_short/khaithi.py`, `analysis/stage.py`, `selection/stage.py` + `selection/prompt.py` (`kt1`), `ingest/stage.py` + `transcript/stage.py` (K5), `pipeline.py`, `cli.py`, `web/app.py`, `web/episodes.py`, `web/playlists.py`, `review/names.py`, `web/static/`.

## K1. Tập khai thị

- Khai thị = video 9:16 cùng template CP7 (header, tiêu đề AI CP6, layout), dài hơn Short, trọn một ý; đăng như video dọc thường.
- Mỗi nguồn tối đa **một** tập khai thị: episode id `<base_id>.kt` (`base_id` = id CP2 D3 của nguồn; `<base_id>.kt` phải hợp lệ theo regex CP2 D3). Workspace `work/<base_id>.kt/`, output `output/<base_id>.kt/`; tập Short `work/<base_id>/` không bị ghi đè.
- Loại tập xác định **chỉ** bởi `work/<id>/khaithi.json` (không suy từ hậu tố):

```json
{"schema_version": 1, "kind": "khaithi", "base_episode_id": "rbjfCfFq3Dk", "min_minutes": 4, "max_minutes": 7}
```

- Ghi atomic, thứ tự key cố định, không timestamp; nội dung không đổi → không ghi lại. Viết bởi `run` (CLI) / `POST /api/episodes` (web) trước khi stage nào chạy; không phải stage (không có entry trong manifest), như `review.json`. Tập archived (CP8.6) → từ chối ghi.
- Đọc: sai JSON / sai schema / `base_episode_id` không hợp lệ / phút ngoài K2 → lỗi user-facing (CLI exit 1), không stage nào chạy, manifest không đổi (`run_pipeline` kiểm trước preflight; `ingest`, `transcript`, `analysis`, `selection`, `status` kiểm trước khi ghi manifest).

## K2. Thời lượng

- `min_minutes`, `max_minutes` số nguyên, `1 ≤ min < max ≤ [khaithi] max_minutes_limit` (mặc định 15; config không cho quá 15).
- Tính trên thời lượng thực tế sau rút khoảng lặng (CP1 §3, CP4 A8).
- Tập khai thị: analysis dùng `min_duration = 60·min`, `max_duration = 60·max`, `target_min = min_duration`, `target_max = max_duration` thay cho giá trị `[analysis]`; các key `[analysis]` khác giữ nguyên. Giá trị hiệu lực nằm trong `used_config` (config hash CP2 D7) và `candidates.json` `params` → đổi min–max làm analysis chạy lại và các stage sau stale (CP2 D6); đổi thời lượng Short trong `[analysis]` không làm tập khai thị stale.
- Tập Short (không có `khaithi.json`): config, `used_config`, `params`, config hash **không đổi byte nào** (`tests/test_khaithi_ac1.py` chốt giá trị tính từ code trước CP8.9).

## K3. Prompt selection `kt1`

- `PROMPTS["kt1"]` trong `selection/prompt.py`: dựa trên v3 (cùng B11 head cut `<<HEAD_CUT_WORDS>>`, cùng dòng unit / user template v2, cùng `RESPONSE_SCHEMA`); nhiệm vụ "VIDEO KHAI THỊ NGẮN ĐỘC LẬP", trọn một lời khai thị (nêu vấn đề, giảng giải, kết lại).
- Placeholder thời lượng điền từ phút hiệu lực: `<<MIN_MINUTES>>`, `<<MAX_MINUTES>>`, `<<MIN_SECONDS>>`, `<<MAX_SECONDS>>` ("Thời lượng bắt buộc 4–7 phút (240–420 giây). Đoạn dưới 240 giây hoặc trên 420 giây bị loại bỏ") và ví dụ tính thời lượng có độ dài = giữa khoảng (`<<EXAMPLE_END>>` = 40.2 + giữa khoảng tính bằng giây, `<<EXAMPLE_SECONDS>>`, `<<EXAMPLE_MINUTES>>`).
- `prompt_sha256` tính trên template (có placeholder); phút điền vào nằm trong config hash (`selection.duration_minutes = [min, max]`, chỉ có ở tập khai thị), như `head_cut_words`. `system_prompt` trong `selection_log.json` là bản đã điền.
- Tập khai thị dùng `[khaithi] prompt_version` (mặc định `kt1`); tập Short vẫn `[selection] prompt_version` (`v3`); v1–v3 giữ nguyên văn. Prompt có placeholder thời lượng chỉ dùng cho tập khai thị và ngược lại (sai → selection lỗi, manifest không đổi).
- Chọn cuối (B6), validation (B8 — dùng `params` min/max hiệu lực của `candidates.json`), schema `clips.json` / `selection_log.json` không đổi; `max_clips`, `min_score`, model, `num_ctx`… dùng chung `[selection]`.

## K4. Window

- Tập khai thị: `max_window_words = max([selection] max_window_words, [khaithi] window_words_per_minute × max_minutes)` (mặc định 400 từ/phút ≈ 2 lần tốc độ nói) → window con chồng lấn (B2) chứa được candidate dài nhất. Giá trị hiệu lực vào config hash + `clips.json` `params`.
- `num_ctx` dùng `[selection]`; chạy thật ghi `prompt_eval_count` lớn nhất so với `num_ctx` (task contract § Result); không tự đổi `num_ctx`.

## K5. Dùng lại nguồn + transcript của tập Short

- **Ingest** tập khai thị nguồn YouTube: khi `work/<base_id>/` có ingest `done`, cùng video id, cùng config hash ingest (`[ingest] youtube_format`), không archived, file nguồn trong workspace còn và sha256 (hash lại thật) khớp manifest → hardlink (lỗi → copy + kiểm sha256) sang `work/<base_id>.kt/source.<ext>` thay vì tải; `metadata.json` lấy thông tin YouTube của tập gốc (ffprobe lại file). Không thỏa → tải như CP2 D4. Nguồn local: như CP2 D4 (không copy).
- **Transcript**: khi tập gốc có transcript `done`, cùng source sha256 (metadata + `transcript.json` `media_sha256`), cùng config hash transcript và cùng input phụ đề (inputs ngoài `metadata.json`) → copy nguyên byte `transcript.json` + artifact phụ của stage (vd `transcript/youtube.*.json3`) và ghi manifest như stage đã chạy (`inputs` của tập khai thị, config hash giống tập gốc); không provider nào được gọi. Không thỏa → CP3 bình thường.
- Chỉ đọc trong `work/<base_id>/`. Tập gốc không bắt buộc phải có.

## K6. CLI

- `auto-short run <source> --khai-thi [--min-minutes N] [--max-minutes M]` (thiếu → `[khaithi] default_min_minutes` / `default_max_minutes`, A1: 4 / 7) → episode `<base_id>.kt` (`--episode-id X` đổi `base_id`; nguồn local: `base_id` = id CP2 D3 tính từ sha256); ghi / cập nhật `khaithi.json` rồi chạy pipeline CP8 như thường. `--min/--max-minutes` không kèm `--khai-thi` → exit 1; không phải số nguyên → argparse exit 2. `run` không có `--khai-thi` chỉ tạo Short (A1 không đổi CLI).
- Lệnh từng stage (`analysis <id>.kt`, …), `title`, `status` tự đọc `khaithi.json`; `status` in thêm dòng `kind: short` hoặc `kind: khai thi <min>–<max> minutes (base episode <id>)`.

## K7 + A1.1. Web API

- `POST /api/episodes` `{url, series?, episode?, mode?, kinds?, min_minutes?, max_minutes?}`: `kinds` ⊆ `["short", "khaithi"]`, không rỗng, không trùng; **bỏ trống = cả hai**. `min_minutes` / `max_minutes` tùy chọn (bỏ trống = `[khaithi] default_*`), chỉ hợp lệ khi có `"khaithi"`. Sai (kiểu, rỗng, trùng, phút ngoài K2, phút khi không có khai thị) → 422 message tiếng Việt, không job, không ghi gì.
- Link playlist / "cả bộ kinh": như CP8.7 (lưu bộ kinh), `kinds` / phút không áp dụng. `watch?v&list` không `mode` → hỏi như cũ.
- Mỗi kind đi đúng luồng W4 trên episode của nó (`<video_id>` / `<video_id>.kt`): job trùng → phần tử `created: false` + job đó; archived → phần tử `error` + `status: 409`; ổ < 3 GB → 507; preflight Ollama **một lần** cho cả request (lỗi → các phần tử cần job mới nhận 503). Job xếp hàng **Short trước, khai thị sau** (K5 dùng lại nguồn + transcript). `khaithi.json` ghi ngay trước khi job khai thị vào hàng (dưới lock gửi URL); đổi min–max → pipeline tự chạy lại từ analysis.
- Response: `{"kind": "video", "episodes": [{"kind", "episode_id", "created", "job"} | {"kind", "episode_id", "error", "status"}], "created", "episode_id", "job"}` — ba field cuối lấy từ phần tử **đầu tiên không lỗi** (tương thích UI cũ). Có job mới → 202, không → 200. Mọi phần tử lỗi → mã lỗi của phần tử đầu, `{"detail", "kind", "episodes"}`.
- `GET /api/episodes` (mỗi item, kể cả job đang đợi chưa có workspace) và `GET /api/episodes/{id}` thêm `kind` (`"short"` | `"khaithi"`), `min_minutes`, `max_minutes`, `base_episode_id` (null với Short) và `khaithi_episode_id` (ở tập Short khi `work/<id>.kt/khaithi.json` tồn tại, không thì null). `khaithi.json` hỏng vẫn là `"khaithi"` (phút null).
- Job khai thị: `pipeline_target(…, episode_id="<video_id>.kt")`; `summary`, log, tiến độ như W4/W5.

## K7 + A1.3. Web UI

- Trang chủ: hai ô chọn "Short" và "Khai thị", **tick sẵn cả hai**; khai thị kèm hai ô phút (mặc định 4–7, giới hạn 1–15). Bỏ tick cả hai → không gửi được. Chọn khai thị cho video đã có tập khai thị với phút khác → hỏi xác nhận trước ("thay toàn bộ video khai thị cũ … tick Đã đăng cũ thành đã đăng bản cũ").
- Trang tập: nhãn "Khai thị m–n phút"; link qua lại giữa trang tập Short và trang tập khai thị cùng video; trang tập Short có khung "Tạo video khai thị" (hai ô phút, `kinds: ["khaithi"]`); "Chạy tiếp / chạy lại" gửi đúng kind của trang (khai thị kèm phút hiện tại). Lưới video như Short (sửa title, xóa / khôi phục, Đã đăng, tải về).

## K8 + A1.2 + A1.4 + A1.5. Tên file, hashtag, bộ kinh, "Tập lẻ"

- Tải về tập khai thị: `Tập<episode>_KT<NN>_<title>.mp4`, zip `Tập<episode>_KhaiThị.zip` (`<episode>`, `<NN>`, làm sạch như W8; không có `header.fields.episode` → `base_id`, không kèm `.kt`).
- Hashtag Copy: như tập gốc `base_id` (bộ kinh chứa `base_id` có danh sách riêng → danh sách đó, CP8.8 H4; không → `#<series>` + `[web] hashtags`).
- **Bộ kinh (A1.4, thay D6):** dòng tập của `video_id` gộp trạng thái tập Short và, nếu `work/<video_id>.kt/` tồn tại, tập khai thị (`combine_status`): có job đợi / chạy ở một trong hai → `queued` / `processing`; một trong hai `failed` → `failed` (`error` ghi "Short: …" / "khai thị: …"); còn lại → trạng thái kém tiến độ hơn (`new`/`deleted` < `incomplete` < `rendered` < `complete`). **Xong** ⇔ tập Short Xong (W10 L4) **và** (nếu có) tập khai thị Xong. Tập không có khai thị → như CP8.7. Entry thêm `short_state`, `khaithi_state`, `khaithi_videos`, `khaithi_published`, `khaithi_episode_id`, `khaithi_job`, `resume_kinds`; UI ghi "n Short, đã đăng a/n · m khai thị, đã đăng b/m" và link "Khai thị". Tóm tắt bộ kinh (đã xử lý / Xong / đang làm) theo trạng thái gộp.
- **Nút bộ kinh (A1.2):** "Xử lý" (`new`), "Xử lý lại" (`deleted`) gửi không kèm `kinds` → cả hai. "Chạy tiếp" (`failed` / `incomplete`) gửi `kinds = resume_kinds`: Short nếu pipeline Short chưa xong (không `rendered` / `complete`) + khai thị **chỉ khi** `work/<video_id>.kt/` đã có và pipeline khai thị chưa xong; không tự tạo khai thị cho tập đã có Short từ trước CP8.9.
- **Trang chủ "Tập lẻ" (A1.5):** tập khai thị có `base_id` thuộc bộ kinh đã lưu không hiện (`in_playlist` theo `base_id`); tập khai thị có tập Short cùng video trong danh sách → hiện gộp dưới dòng tập Short (nhãn + link + trạng thái); không có tập Short → dòng riêng có nhãn. "Xong" của trang tập khai thị (W10 L4) tính riêng cho nó.
- Bia mộ (`_deleted/`), gợi ý dọn và tab Bộ nhớ (W9) chạy trên từng workspace như cũ (tập khai thị là một dòng riêng trong tab Bộ nhớ).

## K9. Config `[khaithi]`

| Key | Mặc định | Ghi chú |
|---|---|---|
| `default_min_minutes` | `4` (A1) | execution-only; 1 … limit−1, < `default_max_minutes` |
| `default_max_minutes` | `7` (A1) | execution-only; 2 … limit |
| `max_minutes_limit` | `15` | execution-only; 2–15 |
| `prompt_version` | `"kt1"` | prompt selection của tập khai thị (hiệu lực, vào config hash qua `selection.prompt_version`) |
| `window_words_per_minute` | `400` | ≥ 1; K4 (hiệu lực qua `selection.max_window_words`) |

Validate khi load (sai → `ConfigError`, exit 1). Chỉ các giá trị hiệu lực K2–K4 vào config hash.

## Known limitations

- Tab Bộ nhớ đếm source hardlink của tập khai thị như một file riêng (không khử trùng dung lượng hardlink); "Dọn video nguồn" một tập chỉ bỏ link của tập đó.
- Bia mộ tập khai thị đã xóa hiện trong "Đã xóa" trên trang chủ (bia mộ không ghi `base_id` nên không lọc theo bộ kinh / không gộp dưới tập Short).
- Link "→ Trang Short của video này" trên trang tập khai thị hiện theo `base_episode_id` kể cả khi tập Short không còn (trang đó báo "không có episode này").
- Candidate dài cần đủ đoạn nói liên tục giữa hai hard break (CP4 A4): video có nhiều nhạc / lặng ≥ 10 s chen giữa có thể cho ít hoặc không có candidate dài; khi đó tập khai thị có 0 video (cảnh báo như CP5 P3).
