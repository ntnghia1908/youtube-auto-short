# CL1 — Chinese Learning MVP Contract

| Metadata | Value |
|---|---|
| Status | PROPOSED — kiến trúc hai ứng dụng duyệt về nguyên tắc (HUMAN LEAD 2026-09-27: G1, G2, G3, G5 phần lấy clip, G7, G8, G9, G10, G11); G4, G6 tạm, chốt từ số đo; chuyển ACCEPTED khi CL1 hoàn tất |
| Accepted by | — |
| Checkpoint | CL1 (S2) — Experiment Chinese Learning MVP |
| Task contract | `docs/tasks/CL1-chinese-learning-mvp.md` (tổng, DRAFT); `docs/tasks/CL1.1-chinese-captions-media.md` (APPROVED 2026-09-27) |
| Builds on | `docs/decisions/CP2-workspace-contract.md` (D3 episode id, D5 manifest, D6 skip/stale, D7 config hash); `docs/decisions/CP3-transcript-contract.md` (T2 caption fetch, T6 json3 normalization); `docs/decisions/CP8.3-web-contract.md` (W2 auth/security, W5 job model, W7 file); `docs/decisions/CP1-product-contract.md` §10 (dependency), §11 (Ollama) |
| Revision | R3 2026-09-27: HUMAN LEAD duyệt kiến trúc về nguyên tắc + APPROVE riêng CL1.1 (phụ đề + clip 5 phút); C5 viết lại theo số đo sơ bộ (tín hiệu URL `kind`/`tlang` thay vì hậu tố `-orig`). R2 2026-09-27: Chinese Learning là **ứng dụng thứ hai** trong host repository, không phải feature/stage của Auto Short (HUMAN LEAD). Thay R1 (`work/<id>/learning/`, slice trong Auto Short). |

Khi ACCEPTED, file này là **canonical owner** của: ứng dụng Chinese Learning (input, namespace `work/_learning/`, stage learning, chọn phụ đề tiếng Trung, cửa sổ 5 phút, AI enrichment, schema `lesson.json`, route/API/trang learning, tiến độ phía client) và của **quy ước host/application** tối thiểu ở C1 (G11). Nơi khác chỉ trỏ tới đây. Auto Short (CP1–CP8.7) **không đổi behavior**; mọi điểm chạm code chung liệt kê ở C3 và đi qua gate tương ứng.

Implementation: `src/auto_short/learning/` — CL1.1 *implemented* (C4 workspace/ownership, C5, C6, C9 stage `subtitle` + `media` và `run_stage(downstream)`, C10 phần lấy clip, C12 lệnh `learn`; `[learning]` `window_seconds`, `min_han_ratio`, `media_format`). CL1.2 *implemented* (C7 AI enrichment + preflight riêng, C8 `lesson.json`, C9 stage `lesson`; `[learning]` key C7; chi tiết cục bộ: `docs/tasks/CL1.2-ai-enrichment-lesson.md`). Model G6 **chưa chốt**. Còn *planned*: C10 phục vụ clip, C11 web/job, xóa bài học.

## C0. Dữ kiện từ repository (base `eab3134`, 2026-09-27)

- **`work/` đã là root cấp host, không chỉ của Auto Short:** ngoài `work/<episode_id>/` còn có `work/.web_secret` (auth web, `web/auth.py`), `work/_playlists/` (`web/playlists.py`), `work/_deleted/` (`review/tombstone.py`). Tiền tố `_` không bao giờ là episode id hợp lệ (`workspace._EPISODE_ID_RE` bắt đầu bằng chữ/số) nên `iter_manifests`, danh sách tập, tab Bộ nhớ và `delete_episode` đều bỏ qua các thư mục này.
- `workspace.py`: `Workspace(root, id)` generic (`dir = root/id`); `iter_manifests(root)` generic theo root. `run_stage` → `mark_downstream_stale` gọi `STAGES.index(stage)`: stage không nằm trong `STAGES` của Auto Short → `ValueError`. `check_up_to_date`, `record_failure`, `atomic_write_*`, `validate_episode_id`, `utc_now` dùng lại được nguyên trạng.
- `pipeline.py` là orchestrator của Auto Short (`PIPELINE_STAGES`, `run_pipeline`, `ollama_preflight` kiểm model `[selection]`/`[titling]`); helper `_tags`/`_has_model` là private.
- `review/delete.py` `delete_episode` xóa `work/<id>/` và `output/<id>/` (mỗi path phải là con trực tiếp của root). `web/storage.py` tính dung lượng tập bằng `tree_size(work/<id>)` → mọi thứ lồng trong `work/<id>/` bị tính là của tập Auto Short.
- `web/jobs.py`: class `JobRunner` generic (một worker, key = chuỗi `episode_id`, `submit(key, kind, target)`, chống trùng job active cùng key, `forget(key)`); nhưng **module** import `pipeline` + `render` ở top-level (`pipeline_target`, `render_target` là job target của Auto Short).
- `web/app.py`: một FastAPI app; middleware auth áp mọi path trừ `/login`, `/static/style.css` (`/api/*`, `/files/*` → 401 JSON; trang → 303 login); header `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`. `api_list` (`GET /api/episodes`) chèn **mọi job active** có key chưa có workspace vào danh sách tập Auto Short → job learning sẽ lọt vào nếu không lọc. `_jobs_by_episode`, `api_storage` duyệt mọi job nhưng tra theo video id → key có tiền tố không va chạm. Route `/files/{episode_id}/{name}` phục vụ mp4 bằng `FileResponse` (Starlette 1.7: có `Range`).
- `config.py`: một `Config` frozen gồm section host (`workspace`, `ingest`, `web`) và section Auto Short; section TOML lạ bị bỏ qua (`from_dict` chỉ đọc section đã biết). `config_hash` mỗi stage chỉ lấy key của section mình → thêm section không đổi hash stage Auto Short. Parser helper (`_section`, `_str`, `_number`…) là private → `[learning]` được parse trong `config.py` (host config biết section của app: coupling chấp nhận cho CL1; tách config theo app = DEFER).
- `validate_episode_id` (`^[A-Za-z0-9]…`) từ chối video id YouTube bắt đầu bằng `-` hoặc `_` (id hợp lệ theo `[A-Za-z0-9_-]{11}`) → Auto Short hiện không xử lý được các video này (finding ngoài scope, báo HUMAN LEAD, **không** sửa trong CL1); learning dùng cùng hàm nên thừa hưởng cùng giới hạn (Known limitation).
- `transcript/youtube.py`: `YtDlpCaptionFetcher` (`tracks`, `download`) độc lập ngôn ngữ; `TRACK_PREFERENCE`/`pick_track` hard-code tiếng Việt. `automatic_captions` của yt-dlp chứa cả **bản dịch máy**; track ASR gốc có hậu tố `-orig`. `transcript/parsers.py` `parse_json3` thuần. `transcript/normalize.py` `normalize()` độc lập ngôn ngữ; `validate()` gắn tiếng Việt.
- `selection/client.py`: `OllamaClient`, `ChatClient`, `ChatError`, `resolve_host` — stdlib, không phụ thuộc selection.
- `ingest/stage.py` tải toàn bộ video (`bv*+ba/b`) → không hợp cho 5 phút đầu.

## C1. Host / application boundary (gate G1, G11)

Repository là **host** chứa nhiều ứng dụng dùng chung hạ tầng. Distribution/package Python vẫn là `auto_short` (đổi tên = refactor lớn, **DEFER**). Không di chuyển file nào của Auto Short trong CL1.

### Phân loại thành phần hiện có

| Loại | Thành phần | Vị trí | Vì sao | CL1 import trực tiếp? | Di chuyển bây giờ? |
|---|---|---|---|---|---|
| A — shared thật | Stage framework: `Workspace`, `iter_manifests`, `check_up_to_date`, `record_failure`, `run_stage`, `atomic_write_*`, `validate_episode_id`, `utc_now` | `workspace.py` | generic theo root/stage; CP2 D5–D6 là quy ước chung | Có (`run_stage` sau G3) | Không |
| A | `config_hash`, `canonical_json`, `sha256_file` | `hashing.py` | thuần | Có | Không |
| A | Auth (secret, cookie, middleware) | `web/auth.py`, middleware trong `web/app.py` | áp mọi path của process | Không import; route learning tự được bảo vệ | Không |
| A | Process web + `lifespan` | `web/app.py` `create_app`, `web/server.py` | một process, một port | Không; host mount router learning | Không |
| A | `JobRunner` (class) | `web/jobs.py` | generic key/kind/target | Có (class, `Job`, `JobFailed`, `KIND_*`) | Không (module còn kéo `pipeline`; tách khi có lý do khác) |
| A | Config host: `[workspace] dir`, `[ingest] js_runtimes` | `config.py` | đường dẫn root, runtime yt-dlp | Có | Không |
| A | URL YouTube: `classify_url`, `canonical_url`, `youtube_video_id` | `web/urls.py`, `ingest/source.py` | thuần, không phụ thuộc Auto Short | Có | Không |
| B — Auto Short | Orchestrator `pipeline.py` (`run_pipeline`, `PIPELINE_STAGES`, `ollama_preflight`), `ingest/stage.py`, `transcript/stage.py` + `TRACK_PREFERENCE`/`pick_track`/`validate`, `analysis/`, `selection/` (trừ client), `titling/`, `render/`, `review/`, `web/episodes.py`, `web/playlists.py`, `web/storage.py`, `pipeline_target`/`render_target`, `web/static/*` hiện có | — | chứa quy tắc sản phẩm Auto Short (tiếng Việt, Shorts 9:16, bộ kinh, xuất bản) | **Không** | Không |
| C — có thể shared, chưa chứng minh | `YtDlpCaptionFetcher`, `CaptionTracks`, `CaptionFetchError` | `transcript/youtube.py` | caption fetch độc lập ngôn ngữ; CL1 là người dùng thứ hai | Có (import, không sửa) | Không — tách sau CL1 nếu reuse bền |
| C | `parse_json3`, `normalize` | `transcript/parsers.py`, `transcript/normalize.py` | thuần; hành vi thuộc CP3 | Có (import, không sửa); test learning có fixture riêng để phát hiện thay đổi CP3 | Không |
| C | `OllamaClient`, `ChatClient`, `ChatError`, `resolve_host` | `selection/client.py` | client stdlib; nằm trong package Auto Short | Có (import, không sửa) | Không |
| C | Ollama preflight (`/api/tags`, kiểm model) | `pipeline.py` (private) | logic nhỏ gắn `[selection]`/`[titling]` | **Không** — learning viết preflight riêng (~20 dòng) | Không; sau CL1 có 2 bản → ứng viên tách |
| C | Xóa thư mục an toàn (con trực tiếp của root, không symlink) | `review/delete.py` `episode_dirs` | hard-code root `work/`/`output/` | Không; learning có hàm guard riêng | Không |
| C | `tree_size`, cảnh báo ổ đĩa | `web/storage.py` | chỉ biết tập Auto Short | Chỉ dùng cờ `block` qua callable host truyền vào (C11) | Không |

### Quy ước tối thiểu cho mọi ứng dụng (G11)

1. Mỗi ứng dụng là một package `src/auto_short/<app>/`; Auto Short giữ layout hiện tại (legacy, không di chuyển).
2. Artifact của ứng dụng mới nằm trong namespace riêng `<workspace.dir>/_<app>/<id>/` (theo tiền lệ `_playlists`, `_deleted`); Auto Short giữ `work/<id>/` + `output/<id>/`. Không ứng dụng nào ghi/xóa ngoài namespace của mình.
3. Core của ứng dụng không import package ứng dụng khác, không import `pipeline.py` hay `web/app.py`; chỉ import hạ tầng loại A và (khi contract cho phép) loại C.
4. Web: ứng dụng tự sở hữu router + static của mình; host `web/app.py` chỉ mount. Job có `kind` riêng và key có tiền tố `<app>:` trên `JobRunner` chung; view của mỗi ứng dụng chỉ đọc job `kind` của mình.
5. Tách/di chuyển hạ tầng loại C sang module chung chỉ bằng task riêng, sau khi ≥ 2 ứng dụng dùng thật.

## C2. Scope sản phẩm (gate G1)

- Input: **một** URL video YouTube (dạng CP8.3 W3 video đơn). Playlist, file local, channel: ngoài scope.
- Chỉ **5 phút đầu** (`window = [0, 300.0)` giây, C6).
- Output: bài học theo câu — chữ Hán từ phụ đề + Pinyin + nghĩa tiếng Việt do AI sinh, timestamp lấy nguyên từ phụ đề; web phát video, bấm câu để nhảy, lặp câu, ẩn/hiện Pinyin/nghĩa, tiến độ lưu localStorage.
- Không có: Whisper tiếng Trung (task sau), tách từ/từ điển, chấm phát âm, Anki/SRS, gamification, TTS, AI tutor, tài khoản, database, React, app mobile, đồng bộ tiến độ.

## C3. Điểm chạm code

### NEW (thuộc ứng dụng learning)

- `src/auto_short/learning/`: `__init__.py`, `tracks.py` (chọn track C5, lớp con `YtDlpCaptionFetcher` đọc metadata từ info đã cache), `subtitle.py` (stage `subtitle`), `prompt.py` + `enrich.py` (AI), `lesson.py` (stage `lesson`), `media.py` (stage `media`), `preflight.py`, `run.py` (`run_learning`, orchestrator riêng), `cli.py` (handler lệnh `learn`), `web.py` (router FastAPI + job target; chỉ import khi chạy web), `static/` (`learn.html`, `lesson.html`, `learn.js`).
- Tests `tests/test_learning_*.py`, `tests/test_web_learning.py`.

### MODIFY (hạ tầng chung, additive, mỗi điểm thuộc một gate)

| File | Thay đổi | Gate |
|---|---|---|
| `workspace.py` | `run_stage(..., downstream: Sequence[str] \| None = None)` → `mark_downstream_stale(manifest, stage, downstream=None)`; `None` = hành vi CP2 D6 nguyên trạng | G3 |
| `config.py`, `config.example.toml` | dataclass + parser section `[learning]` (additive; section cũ và hash stage cũ không đổi) | G6 |
| `cli.py` | thêm subparser `learn` gọi `learning.cli` | G8 |
| `web/app.py` | (a) mount router + static learning trong `create_app`; (b) `api_list` chỉ chèn job `kind ∈ {pipeline, render}` | G7 |
| `web/static/index.html` | một link "Học tiếng Trung" → `/learn` (bước cuối CL1.4) | G7 |
| Docs | `project-profile.md` (mục Applications + module map + authority), pointer ở CP2 D6, CP3 (reuse `parse_json3`/`normalize`), CP8.3 (router learning, lọc kind), README | G1, G3, G7 |

### IMPORT ONLY (không sửa)

`hashing.py`; `workspace.py` (ngoài `run_stage`/`mark_downstream_stale`); `transcript/youtube.py` (`YtDlpCaptionFetcher`, `CaptionTracks`, `CaptionFetchError`); `transcript/parsers.py` (`parse_json3`, `ParseError`, `RawSegment`); `transcript/normalize.py` (`normalize`); `selection/client.py`; `web/jobs.py` (`JobRunner`, `Job`, `JobFailed`); `web/urls.py` (`classify_url`, `canonical_url`); `ingest/source.py` (`youtube_video_id`); `web/static/style.css` (link, không sửa).

### MUST NOT MODIFY

`pipeline.py`, `ingest/`, `transcript/`, `analysis/`, `selection/`, `titling/`, `render/`, `review/`, `web/jobs.py`, `web/episodes.py`, `web/playlists.py`, `web/storage.py`, `web/auth.py`, `web/urls.py`, `web/server.py`, `web/static/*` hiện có (trừ một link ở `index.html`), `pyproject.toml`, test hiện có.

## C4. Workspace, ownership và vòng đời xóa (gate G2)

- Episode id = YouTube video id (CP2 D3). Workspace learning = `Workspace(root=<workspace.dir>/_learning, episode_id)` → `work/_learning/<id>/` — dùng class `Workspace` nguyên trạng, không subclass. Manifest `work/_learning/<id>/manifest.json`, schema v1 CP2 D5 (`source` = `{"kind": "youtube", "uri", "path": null, "sha256": null, "size": null, "mtime_ns": null}`), artifact relative theo `work/_learning/<id>/`.
- Namespace cố định trong code (`LEARNING_DIR = "_learning"`), như `_playlists`/`_deleted`; không thêm config key.

| Câu hỏi | Trả lời |
|---|---|
| Ai sở hữu root `work/`? | Host (`[workspace] dir`): chứa `.web_secret` và các namespace. Không ứng dụng nào xóa root. |
| Ai sở hữu `work/<id>/` + `output/<id>/`? | Auto Short (legacy, không đổi tên thành `auto-short/`). |
| Ai sở hữu `work/_learning/`? | Chinese Learning, toàn bộ. |
| "Xóa tập" Auto Short? | Không đổi: `delete_episode` xóa `work/<id>/` + `output/<id>/` (+ tombstone). Không chạm `work/_learning/<id>/` vì không lồng bên trong. |
| "Xóa bài học"? | Xóa `work/_learning/<id>/` (guard: con trực tiếp của `work/_learning`, không symlink, không job learning active) + quên job `learning:<id>`. Không chạm `work/<id>/`, `output/<id>/`, tombstone. |
| Cùng một video ở cả hai? | Hai workspace độc lập, cùng video id, không stale/xóa lẫn nhau. **Không** có lớp `shared/source` trong CL1: learning không cần video đầy đủ (chỉ phụ đề + clip 5 phút), Auto Short có thể đã dọn `source.*` (CP8.6). Phụ đề/clip tải lại độc lập (vài trăm KB + vài chục MB). Lớp nguồn dùng chung: DEFER tới khi có ứng dụng cần artifact của ứng dụng khác. |

- Hệ quả chấp nhận: bài học không hiện trong tab Bộ nhớ (chỉ biết tập Auto Short); dung lượng learning vẫn nằm trên cùng ổ nên cảnh báo/khóa ổ đầy (CP8.6 S4) vẫn áp dụng.
- Artifact:

| File (trong `work/_learning/<id>/`) | Stage | Nội dung |
|---|---|---|
| `manifest.json` | — | provenance (CP2 D5) |
| `subtitle.json3` | `subtitle` | bytes gốc track được chọn, toàn video |
| `source.json` | `subtitle` | metadata video (id, title, channel, duration, webpage_url), track đã chọn, `attempts` |
| `clip.mp4` | `media` | 5 phút đầu (G5 = B) |
| `media.json` | `media` | provenance clip: `path`, `sha256`, `size`, `window` {`start`, `end`}, `duration`, `width`, `height`, `video_codec`, `audio_codec` (ffprobe), `format_id` yt-dlp, `method` |
| `lesson.json` | `lesson` | bài học (C8) |
| `lesson_log.json` | `lesson` | log AI: prompt version, request/response thô từng batch, lý do reject (project-profile §4) |

## C5. Chọn phụ đề tiếng Trung (gate G4 — tạm, chốt bằng số đo CL1.1)

- Fetch: `YtDlpCaptionFetcher(js_runtimes=config.ingest.js_runtimes)`; một `extract_info(download=False)` cho track list + metadata (lớp con trong `learning/tracks.py` đọc info đã cache và URL từng track; `download()` dùng nguyên trạng; không sửa `transcript/`).
- Chỉ xét track có định dạng `json3`. Thuộc tính mỗi track lấy từ query của URL json3 (số đo sơ bộ: key yt-dlp không đủ tin cậy):
  - `lang` (ngôn ngữ nguồn; key có thể mang hậu tố id, vd `vi-e4D66FZAwWw`) — thiếu thì dùng key;
  - `tlang` có mặt ⇒ **bản dịch máy** (vd video tiếng Việt: key `zh-Hans` = `lang=vi&kind=asr&tlang=zh-Hans`) ⇒ **không bao giờ** nhận;
  - `kind=asr` ⇒ nhận dạng giọng nói tự động.
- Thứ tự:
  1. manual (`subtitles`): không `tlang`, subtag chính của `lang` là `zh`; ưu tiên theo `lang`: `zh-Hans`, `zh-CN`, `zh-SG`, `zh`, `zh-Hant`, `zh-TW`, `zh-HK`, rồi `zh-*` khác theo thứ tự chữ; cùng `lang` → key không hậu tố trước, rồi theo thứ tự chữ;
  2. auto (`automatic_captions`): `kind=asr`, không `tlang`, subtag chính của `lang` là `zh`; key kết thúc `-orig` trước, rồi cùng thứ tự `lang` như trên;
  3. không có → `subtitle` `failed`, `error` nêu lý do + tóm tắt đã thấy (vd `no Chinese subtitle track (manual zh*, auto zh ASR); found: machine-translated zh-Hans, zh-Hant`). Whisper fallback: task sau.
- `source.json` ghi mọi track liên quan tới tiếng Trung đã thấy (key, manual/auto, `lang`, `kind`, `tlang`, có json3) + track đã chọn + lý do.
- Không chuyển giản ↔ phồn thể (cần dependency).

## C6. Cửa sổ 5 phút và validation

- `[learning] window_seconds = 300.0`.
- Lấy segment sau `normalize()` có `kind = speech` và `start < window_seconds`; `start`/`end` giữ nguyên. Video ngắn hơn → cả video.
- Acceptance (lý do đầu tiên không đạt → `failed`): parse OK và ≥ 1 segment speech trong cửa sổ; timestamp như CP3 T5 #2; tag có subtag chính `zh`; tỉ lệ ký tự Hán (CJK Unified + Ext A) trên ký tự chữ ≥ `[learning] min_han_ratio` (0.5). Không áp coverage / words-per-minute CP3.

## C7. AI enrichment (gate G6)

- `selection.client.OllamaClient` (import); host `[learning] ollama_host`, `OLLAMA_HOST` ghi đè theo `resolve_host`. `[learning]`: `model` (đề xuất `qwen3:14b`), `think = false`, `temperature = 0.0`, `seed = 42`, `num_ctx`, `prompt_version = "v1"`, `batch_lines` (20), `retries` (2), `timeout`, `retry_backoff`.
- Input mỗi batch: chỉ `[{"id", "zh"}]` (không timestamp). Output (JSON schema qua `format`): `{"lines": [{"id", "pinyin", "vi"}]}`.
- Validation mỗi batch: tập `id` trả về == tập gửi; `pinyin` không rỗng, chỉ chữ Latin (dấu thanh hoặc số thanh), khoảng trắng, dấu câu; `vi` không rỗng; field khác bị bỏ qua. Sai → retry batch; hết retry → `lesson` `failed` (không ghi `lesson.json` một phần).
- Ghép: `id`, `start`, `end`, `zh` luôn từ segment đã normalize; `pinyin`, `vi` từ AI.
- Pinyin do LLM có rủi ro sai thanh/đa âm; `pypinyin` là dependency mới → proposal riêng, ngoài CL1.
- Preflight: `learning/preflight.py` riêng (`GET <host>/api/tags`, model `[learning]` có mặt); **không** import helper private của `pipeline.py`, không sửa `ollama_preflight`. Web gọi trước khi submit (503), job gọi lại khi bắt đầu, CLI gọi trước `lesson`.

## C8. `lesson.json` schema v1

`work/_learning/<id>/lesson.json`, ghi atomic, không chứa thời điểm tạo (byte-stable). Thứ tự key cố định:

```json
{
  "schema_version": 1,
  "episode_id": "<video id>",
  "video": {"id": "…", "title": "…", "channel": "…", "duration": 1234.5, "url": "https://youtu.be/…"},
  "window": {"start": 0.0, "end": 300.0},
  "subtitle": {"path": "subtitle.json3", "sha256": "…", "track": "zh-Hans", "auto": false},
  "media": {"path": "clip.mp4", "sha256": "…", "start": 0.0, "end": 300.0},
  "enrichment": {"model": "qwen3:14b", "prompt_version": "v1", "think": false, "temperature": 0.0, "seed": 42},
  "lines_sha256": "<sha256 canonical JSON của [{id,start,end,zh}]>",
  "stats": {"lines": 72, "han_chars": 1310},
  "lines": [
    {"id": "s00001", "start": 1.2, "end": 3.84, "zh": "大家好", "pinyin": "dà jiā hǎo", "vi": "Chào mọi người"}
  ]
}
```

- `media` = `null` nếu chưa có clip (G5 khác B). `lines_sha256` chứng minh timestamp/chữ Hán không đổi so với subtitle đã normalize.

## C9. Orchestration và stage (gate G3)

**Quyết định đề xuất: C — orchestrator riêng của learning + dùng stage primitive chung với tham số `downstream`.**

| Phương án | Mô tả | Blast radius | Reuse | Rủi ro hồi quy | Ứng dụng thứ 3 |
|---|---|---|---|---|---|
| A | Chỉ thêm `run_stage(downstream=…)`, không nói gì về orchestration | 1 hàm chung | cao | thấp (mặc định = CP2 D6) | chưa rõ nơi đặt thứ tự stage → dễ bị nhét vào `pipeline.py` |
| B | `LearningPipeline` tự viết skip/stale/failure trên `check_up_to_date` + `record_failure` | 0 file chung | thấp: chép lại ~40 dòng logic tinh (RUNNING, KeyboardInterrupt, xóa artifact) | 0 cho Auto Short, nhưng hai bản CP2 D6 trôi nhau | mỗi app lại chép |
| **C (chọn)** | Orchestrator `learning/run.py` (`run_learning`: `subtitle` → `media` → `lesson`) thuộc app; mỗi stage gọi `run_stage` chung với `downstream` tường minh | 1 hàm chung, additive | cao: một cài đặt CP2 D6 duy nhất | thấp: đường `downstream=None` giữ nguyên code, test CP2–CP8.7 hiện có chứng minh | app thứ 3 viết orchestrator riêng + truyền `downstream` |

- Lý do: `run_stage` là **stage framework** (loại A, CP2 D6) — đã có người dùng thứ hai thật nên mở rộng là đúng nguyên tắc; `pipeline.py` là **orchestrator của Auto Short** (loại B) nên learning không đi qua nó, không thêm stage vào `STAGES`/`PIPELINE_STAGES`. Dùng `downstream` (tập tường minh) thay vì "thứ tự stage của app" vì đồ thị learning không tuyến tính: `media` không phụ thuộc `subtitle`.
- Framework v4.1: sửa shared abstraction = decision gate (G3) + ghi chú sửa đổi CP2 D6.
- Stage: `subtitle` (`downstream=("lesson",)`), `media` (`()`), `lesson` (`()`).
  - `subtitle`: `inputs = []` (URL gắn với episode id + `source.uri`); `config_hash` = `window_seconds`, `min_han_ratio`, danh sách ưu tiên track; artifact `subtitle.json3`, `source.json`.
  - `media`: `inputs = []`; `config_hash` = `window_seconds`, `media_format`; artifact `clip.mp4`, `media.json`. Chạy sau `subtitle` và chỉ khi `subtitle` done (không có phụ đề Trung → không tải media).
  - `lesson`: `inputs` = `subtitle.json3` + `source.json` (+ `clip.mp4` nếu có, để `lesson.media` đúng sha); `config_hash` = key `[learning]` ảnh hưởng output (model, think, temperature, seed, num_ctx, prompt_version, batch_lines, window_seconds); không gồm `ollama_host`, `timeout`, `retry_backoff`, `retries`.
- `--force` chạy lại; lỗi → `failed` + xóa artifact stage đó (CP2 D6). Dừng ở stage lỗi đầu tiên.

## C10. Nguồn video trên web (gate G5)

- **B — clip 5 phút cục bộ (đề xuất):** stage `media` tải `[0, window]` bằng yt-dlp (`download_ranges`, `force_keyframes_at_cuts`, format `[learning] media_format` mặc định `bv*[height<=720]+ba/b[height<=720]`, merge mp4) vào `work/_learning/<id>/clip.mp4` (qua thư mục tạm, chỉ đổi tên sau khi probe OK). **Không tải cả video** để cắt: `download_ranges` để yt-dlp/ffmpeg chỉ đọc đoạn đầu; nếu bản pin không làm được thì dừng và ghi lý do (BLOCKED, không tự chuyển sang tải toàn bộ). Chấp nhận clip khi `ffprobe` có video + audio và `duration` ∈ [min(window, thời lượng video) − 2 s, window + 2 s]. Lấy clip thuộc CL1.1; phục vụ web thuộc CL1.3. Phát bằng `<video>` same-origin qua `GET /files/learning/{id}/clip.mp4` (`FileResponse`, có `Range`; path cố định từ server). Không script bên thứ ba, không đổi header W2. Không dependency mới (yt-dlp pin + ffmpeg hệ thống); cần đo ở CL1.3.
- A — YouTube embed: **REJECT cho CL1** — cần nới `X-Frame-Options`/`Referrer-Policy` và chạy script bên thứ ba trong trang đã đăng nhập (đổi security model W2).

## C11. Web và job (gate G7)

- Router thuộc app: `learning/web.py` `learning_router(config, runner, *, preflight, run, disk_block) -> APIRouter` (injectable cho test); static ở `learning/static/`, mount `/learn/static`. Host `web/app.py` `create_app` import `learning.web` và `include_router` + mount — không có logic learning trong `web/app.py`.
- Route (sau middleware auth hiện có, không thêm public path):
  - `GET /learn` — danh sách bài + ô dán URL; `GET /learn/{episode_id}` — trang học.
  - `GET /api/learning` — `{id, title, lines, status, job}` (đọc `iter_manifests(work/_learning)`).
  - `POST /api/learning` `{"url"}` — video đơn (playlist → 422), preflight (503), `disk_block()` (507), submit; trùng job active → 200 cùng job.
  - `GET /api/learning/{episode_id}` — `lesson.json` + trạng thái stage + job; `DELETE /api/learning/{episode_id}` — xóa `work/_learning/<id>/` (409 khi job active).
  - `GET /files/learning/{episode_id}/clip.mp4`.
- Job: `JobRunner` **chung** (một worker → không chạy Ollama song song với pipeline Auto Short); `kind = "learning"`, key `learning:<episode_id>` (không phải episode id hợp lệ → không va chạm Auto Short/bộ kinh; `forget` chỉ khớp đúng key). Job learning có thể phải chờ job Auto Short đang chạy (hiển thị `queue_position`).
- Ranh giới job tối thiểu ở host: `api_list` chỉ chèn job active có `kind ∈ {pipeline, render}`. Không đổi `JobRunner`, `Job.to_dict`, view khác.
- UI: HTML/CSS/vanilla JS, không thư viện ngoài, không build step; dùng `/static/style.css` chung.
- Tiến độ: chỉ `localStorage`, key `auto-short.learn.v1.<episode_id>`, `{"last_line", "done": [...], "updated_at"}`, đọc/ghi trong `try/catch`; server không nhận tiến độ.

## C12. CLI (gate G8)

`auto-short learn <youtube-url> [--force] [--config PATH]` — `cli.py` chỉ đăng ký subparser và gọi `learning.cli`; chạy `run_learning`; stdout `<episode_id>\t<done|skipped (up to date)>\t<path lesson.json>`; log stderr; exit code như CP2 D8. Mục đích chính: đo thật ở CL1.1–CL1.3 trước khi có web.

## Decision gates (HUMAN LEAD)

| Gate | Đề xuất R1 | R2 | Đề xuất R2 |
|---|---|---|---|
| G1 | Vertical slice trong Auto Short | MODIFY | Chinese Learning là ứng dụng thứ hai trong host repo; `project-profile.md` thêm mục Applications; giữ package `auto_short` (đổi tên DEFER) |
| G2 | `work/<id>/learning/`, chấp nhận "Xóa tập" xóa luôn bài học | MODIFY | `work/_learning/<id>/` (namespace app, như `_playlists`); `Workspace` nguyên trạng; xóa độc lập; không lớp shared source (DEFER) |
| G3 | `run_stage(downstream=…)` | MODIFY | Phương án C: orchestrator `learning/run.py` riêng + `downstream` tùy chọn trên `run_stage`; không chạm `pipeline.py`/`STAGES` |
| G4 | Thứ tự track zh, auto chỉ `*-orig` | KEEP | chốt sau số đo CL1.1 |
| G5 | B clip cục bộ | MODIFY | B, phục vụ bởi router learning `/files/learning/{id}/clip.mp4`; A REJECT (đổi security W2) |
| G6 | `[learning]`, Pinyin LLM, preflight riêng | MODIFY | như C7; preflight learning không dùng helper private của `pipeline.py`; model chốt sau CL1.2 |
| G7 | Route trong `web/`, lọc kind trong `api_list` | MODIFY | router + static thuộc `learning/`, host chỉ mount; `JobRunner` chung, key `learning:<id>`; `api_list` allow-list kind `pipeline`/`render` |
| G8 | CLI `auto-short learn` | MODIFY | giữ lệnh; handler ở `learning/cli.py`, `cli.py` chỉ đăng ký |
| G9 | Không dependency mới | KEEP | — |
| G10 | `dual-agent`, branch từ `main` khi APPROVE, một PR | MODIFY | như cũ + làm trong **worktree riêng** (session Auto Short song song dùng working tree chính); docs dùng chung (`project-profile.md`, CP2/CP3/CP8.3, README) sửa ở CL1.4, rebase trước READY |
| G11 | — | NEW | Quy ước host/application C1 (package app, namespace `_<app>/`, hướng import, router app, job kind) là project-wide convention |

## Đo thực tế

### Sơ bộ (ORCHESTRATOR, 2026-09-27, yt-dlp `2026.08.19`, chỉ `extract_info`, không tải) — căn cứ viết lại C5

| Video | Loại | Track zh thấy được | Ghi chú |
|---|---|---|---|
| `gnCXffOg7T8` (HSK 1-2, 1253 s) | học tiếng Trung | manual `zh-Hans` (json3); auto `zh-Hans` **không có json3** | key auto trùng key manual, không dùng được |
| `DVRy3l9ojq4` (HSK 1–2, 1137 s) | học tiếng Trung | manual `zh`; auto `zh` không json3 | |
| `qcqQbMj4s-w` (vlog, 414 s) | học tiếng Trung | manual `zh`, `zh-CN`, `zh-Hant` | nhiều manual zh → cần thứ tự |
| `4N33a-_OpJw` (vlog, 541 s) | học tiếng Trung | manual `zh-CN` | id bắt đầu chữ nhưng chứa `_`/`-`: hợp lệ |
| `Pd3l0u8HUjM` (5464 s) | học tiếng Trung, "Multi-Subs" | không có zh; manual key dạng `vi-e4D66FZAwWw` | **key có hậu tố id** |
| 6 video phỏng vấn đường phố Thượng Hải, 6 video livestream tiếng Trung, 2 video 新闻联播 | tiếng Trung tự nhiên | **không** track zh nào (manual lẫn ASR) | YouTube không thấy sinh ASR tiếng Trung |
| `rbjfCfFq3Dk` (tiếng Việt) | đối chứng | auto `zh-Hans`, `zh-Hant` = `lang=vi&kind=asr&tlang=zh-*` | bản dịch máy phải bị loại; `vi-orig` và `vi` cùng là ASR gốc |

Kết luận sơ bộ: (1) không thấy track ASR tiếng Trung gốc nào trên 14 video tiếng Trung tự nhiên → nhánh "auto Chinese" hiện gần như không bao giờ kích hoạt; video không có manual zh sẽ cần Whisper (task sau, không mở rộng CL1.1); (2) `automatic_captions` với key `zh-*` trên video không phải tiếng Trung là bản dịch — nhận diện bằng `tlang`, không bằng key; (3) key manual có thể mang hậu tố id → ngôn ngữ lấy từ `lang` của URL. CL1.1 đo lại end-to-end trên ≥ 3 video và ghi bảng chính thức bên dưới.

### CL1.1 (chính thức)

IMPLEMENTER, 2026-09-27, yt-dlp `2026.08.19`, ffmpeg hệ thống, `python -m auto_short learn <url>` (code CL1.1, config mặc định `[learning]`: cửa sổ 300 s, `min_han_ratio` 0.5, format `bv*[height<=720]+ba/b[height<=720]`), workspace tạm ngoài repo. Bytes tải: `bytes_received` của socket TCP thuộc process `ffmpeg` (con của yt-dlp) lấy bằng `ss -tinp` mỗi 0,25 s — chỉ phần media; phần `python` (extract_info + phụ đề) ≈ 0,2–0,5 MB/lần; tổng hai phần khớp `rx` của card mạng trong cùng khoảng (`rx` lớn hơn 3–9 %: header gói tin + lưu lượng nền, nền nhàn rỗi ≈ 78 KB/30 s). "Cả video" = `filesize` yt-dlp của đúng format đã tải (`398` AV1 720p + `251` Opus).

| Video (thời lượng) | Track manual zh | Track auto zh | `-orig` | Track chọn / hành vi rule | Tên track bất thường | Thời gian (lần đầu) | Clip (`ffprobe`) | Bytes media tải / cả video (phần cửa sổ 300 s) |
|---|---|---|---|---|---|---|---|---|
| `gnCXffOg7T8` (1253 s) | `zh-Hans` | `zh-Hans` (không json3) | không | manual `zh-Hans`; 84 segment trong cửa sổ, `han_ratio` 1.0, `last_end` 300.936 | key auto trùng key manual | 177.2 s | 300.007 s, h264 1280x720 + aac, 14.1 MB | 10.39 MB / 38.40 MB = 27.1 % (cửa sổ = 23.9 %) |
| `qcqQbMj4s-w` (414 s) | `zh`, `zh-CN`, `zh-Hant` | `zh`, `zh-CN`, `zh-Hant` (đều không json3) | không | manual `zh-CN` (thứ tự `lang`: `zh-CN` trước `zh`, `zh-Hant`); 98 segment, `han_ratio` 0.999 | như trên | 166.8 s | 300.007 s, h264 1280x720 + aac, 126.2 MB | 58.60 MB / 75.44 MB = 77.7 % (cửa sổ = 72.5 %) |
| `DVRy3l9ojq4` (1137 s) | `zh` | `zh` (không json3) | không | manual `zh`; 70 segment, `han_ratio` 0.958 | như trên | 165.5 s | 300.007 s, h264 1280x720 + aac, 17.2 MB | 14.26 MB / 51.25 MB = 27.8 % (cửa sổ = 26.4 %) |
| `rbjfCfFq3Dk` (3622 s, tiếng Việt) | — | `zh-Hans`, `zh-Hant` = `lang=vi&kind=asr&tlang=zh-*` | `vi-orig` (không phải zh) | **không nhận** (bản dịch máy): `subtitle` `failed`, exit 1, `error` = `no Chinese subtitle track (manual zh*, auto zh ASR); found: machine-translated auto zh-Hans (lang=vi, tlang=zh-Hans), machine-translated auto zh-Hant (lang=vi, tlang=zh-Hant)`; không tải phụ đề, không chạy `media`, workspace chỉ còn `manifest.json` | key `zh-*` là bản dịch | 2.7 s | — | 0 (chỉ ≈ 0.2 MB extract_info) |

- Chạy lại cùng lệnh: 3 video tiếng Trung → cả hai stage `skipped (up to date)`, 0,3 s, không truy cập mạng; video tiếng Việt → chạy lại `subtitle` (trạng thái trước `failed`) và lỗi y như trên.
- **Không tải cả video (AC12):** bytes media tải ≈ 1,06–1,13 × phần cửa sổ của luồng nguồn (đọc trước của ffmpeg), không phải cả video; thời gian ≈ 166–177 s cho cả video 414 s lẫn 1253 s → không tỉ lệ với thời lượng video (bị chặn bởi việc mã hóa lại 300 s, ≈ 1,8× thời gian thực). `.media-tmp/` không còn sau mỗi lần chạy.
- Clip **lớn hơn** bytes tải vì `force_keyframes_at_cuts` khiến yt-dlp/ffmpeg mã hóa lại cả đoạn sang H.264 (libx264 mặc định): nguồn AV1 1.35 Mbit/s của `qcqQbMj4s-w` thành clip 3.4 Mbit/s (126 MB / 5 phút). Hệ quả: so sánh đúng cho AC12 là bytes tải với phần cửa sổ của nguồn, không phải với kích thước clip. Clip H.264 phát được trong mọi trình duyệt (AV1 thì không chắc). Dung lượng/tốc độ mã hóa là việc của CL1.3 (C10 "cần đo ở CL1.3"); CL1.1 không đổi C10.
- **C5 (G4):** số đo không bác bỏ rule → giữ nguyên. Chưa gặp track ASR tiếng Trung gốc (`kind=asr`, không `tlang`) trên video nào; nhánh auto mới chỉ được kiểm bằng test giả. Track auto `zh*` không có json3 trên video có manual zh (URL không có `tlang`) — bị bỏ qua đúng rule "không json3".

### CL1.2

IMPLEMENTER, 2026-09-27, `python -m auto_short learn https://youtu.be/<id> --config <tmp>` (code CL1.2, prompt `v1`, `think = false`, `temperature = 0`, `seed = 42`, `num_ctx = 8192`, `batch_lines = 20`, `retries = 2`, backoff 5 s/15 s), Ollama `http://127.0.0.1:11437` trên máy dev (GPU dùng chung với session khác — số đo mang tính tham khảo). Workspace = bản sao (`cp -a`) của workspace CL1.1 cho từng model → `subtitle`, `media` đều `skipped (up to date)`, không tải lại; chỉ `lesson` chạy. Hai model chạy lần lượt (14b cả 3 video, rồi 30b cả 3 video). Thời gian batch = `duration_s` trong `lesson_log.json` (tổng các lần thử của batch); tổng = wall-clock cả lệnh.

| Model | Video (dòng / chữ Hán) | Batch | Tổng lệnh | Batch: mean / max (batch 20 dòng: mean) | Retry | Kết quả |
|---|---|---|---|---|---|---|
| `qwen3:14b` | `gnCXffOg7T8` (84 / 583) | 5 | 56.9 s | 11.3 / 15.6 s (13.5 s) | 0 | done |
| `qwen3:14b` | `DVRy3l9ojq4` (70 / 1011) | 4 | 66.9 s | 16.6 / 20.0 s (19.2 s) | 0 | done |
| `qwen3:14b` | `qcqQbMj4s-w` (98 / 719) | 5 | 62.8 s | 12.3 / 12.5 s (12.3 s) | 0 | done |
| `qwen3:30b` | `gnCXffOg7T8` (84 / 583) | 5 | 29.1 s | 5.8 / 11.2 s (6.9 s) | 0 | done |
| `qwen3:30b` | `DVRy3l9ojq4` (70 / 1011) | 4 | 58.5 s | 9.5 / 12.0 s (8.7 s) | 2 | **failed**: `batch 4 (s00061..s00070): s00062: pinyin contains Han character '害' (after 3 attempts)` |
| `qwen3:30b` | `qcqQbMj4s-w` (98 / 719) | 5 | 26.1 s | 5.0 / 5.2 s (5.1 s) | 0 | done |

- Batch đầu của mỗi model trên video đầu tiên (`gnCXffOg7T8`) gồm thời gian nạp model (14b 15.6 s, 30b 11.2 s so với ≈ 13 s / ≈ 6 s các batch sau). `qwen3:30b` (MoE, ~3B tham số active) nhanh hơn `qwen3:14b` ≈ 2–2.4× trên cùng batch.
- **Retry không cứu được lỗi nội dung với sampling cố định:** ở lần `30b` lỗi, cả 3 lần thử trả về gần như cùng chuỗi (`qǐng bùyào害怕. shuō cuò le, …` cho `请不要害怕。说错了，真的没关系。`) vì `temperature = 0` + `seed` cố định → retry chỉ có ích cho lỗi mạng/timeout. Behavior đúng hợp đồng (stage `failed`, không có `lesson.json`, `lesson_log.json` giữ 3 request/response + lý do). Đổi chiến lược retry (đổi seed/temperature khi retry, sửa từng dòng, v.v.) là quyết định riêng — chưa làm.
- Validation (C7) chỉ bắt được Hán/chữ ngoài Latin, dòng rỗng, lệch `id`; **không** bắt sai thanh, sai âm, thiếu dấu thanh (vd. 14b `Suo yi` không dấu cho 所以 vẫn qua).
- Mẫu 20 dòng liên tiếp (`qcqQbMj4s-w` s00001–s00020, batch 1 của cả hai model, không chọn lọc) kèm nhận xét từng lỗi: gửi riêng cho HUMAN LEAD (file ngoài repo, scratchpad của session CL1.2: `cl12-sample-20.md`).
- Nhận xét IMPLEMENTER (chỉ là quan sát; **không** phải quyết định G6):
  - Pinyin — cả hai model đều có lỗi âm/thanh ở mức một người học sẽ bị dạy sai. `14b` (qcqQbMj4s-w, 98 dòng): 这样 `hànyàng`, 菜单 `cānkuǎn` (2 lần), 终于 `Zōngxīng`, 一会儿 `Yīhuì rì`, 看着 `kàizhe`, 热闹 `rènzhào`, 刷卡 `chuākǎ`, 稍后再见 `shāoxiān hòu jiàn`, 所以 `Suo yi` (không dấu); gnCXffOg7T8: 面包 `miàntuō`, 好吧 `Bàihǎo`. `30b`: 棉花糖 `mǐ huā táng`, 午饭 `wǔ shí`, 抓紧 `zhuānjǐn`, 拜拜 `bái bái`, 谢谢 `xièxiè`, 刚刚 → `gāngcái` (đổi sang 刚才); cả hai sai 贩卖机 (14b `mài fàn jī`, 30b `mài fā jī`). Đếm thô trên qcqQbMj4s-w: 14b ≈ 11 dòng có lỗi âm rõ, 30b ≈ 7.
  - Đa âm: phần lớn đúng ở cả hai (了 le, 还 hái, 的 de, 觉 trong 感觉 jué); một lỗi chọn âm thấy được: 写得 14b `xiě dé` (30b `xiě de` đúng). Lỗi chủ yếu là âm sai hẳn (ảo giác), không phải chọn sai âm đọc.
  - Biến điệu 一/不 (prompt yêu cầu): không nhất quán ở cả hai (`yīqǐ`, `yīxià`, `bù shì` lẫn `búcuò`, `bú tài`).
  - Tách từ / viết hoa: `14b` viết liền theo từ (`xiànzài`, `chūmén`) đúng prompt nhưng viết hoa đầu câu không nhất quán giữa các batch; `30b` thường tách từng âm tiết (`xiàn zài`) trên video vlog, nhưng viết liền theo từ trên video HSK — không nhất quán giữa video/batch.
  - Nghĩa tiếng Việt: cả hai nhìn chung đúng ý, tự nhiên cho câu ngắn. Lỗi: 14b quy đổi 五块钱 → "Năm nghìn đồng" (sai tiền tệ; 30b "Năm tệ" đúng), 14b 车站 → "trạm xe buýt" trong ngữ cảnh tàu điện, 14b bỏ 出口; 30b 有点贵 → "Gần đắt" (sai), 30b 再见 → "chào" (nhạt). Dòng tiếng Nhật lẫn trong phụ đề (`就輪投げ扔圈圈`) → cả hai sinh Pinyin vô nghĩa cho 輪投げ.
- **Model chưa được chấp nhận.** G6 chốt sau khi HUMAN LEAD đọc mẫu 20 dòng; mặc định `[learning] model = "qwen3:14b"` chỉ là đề xuất ban đầu của C7.

### CL1.3

Chưa có.
