# Task: CL1.2 — AI enrichment + `lesson.json`

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Human Lead: HUMAN LEAD
- Base commit / branch: `0a61637` (`main` sau merge CL1.1, PR #12) / `feature/cl1.2-lesson`, worktree `../youtube-auto-short-cl1` (nhánh cũ `feature/cl1-chinese-learning` không dùng)
- Human Lead approval: accepted 2026-09-27 — "HUMAN LEAD APPROVES CL1.2 ONLY"; G6 (model) chốt sau khi HUMAN LEAD đọc mẫu 20 dòng thật
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: stage AI mới của ứng dụng thứ hai, schema artifact mới `lesson.json` (C8), section config `[learning]` mở rộng. Không thêm dependency. Task tổng: `docs/tasks/CL1-chinese-learning-mvp.md`.

## Goal

`auto-short learn <url>` chạy `subtitle → media → lesson`: stage `lesson` gửi từng batch câu `{id, zh}` cho Ollama, nhận Pinyin + nghĩa tiếng Việt, validate/retry, và ghi `work/_learning/<id>/lesson.json` (C8) mà timestamp + chữ Hán lấy nguyên từ phụ đề đã normalize. Auto Short giữ nguyên behavior.

## Scope

- In scope:
  - Mới: `src/auto_short/learning/prompt.py`, `enrich.py`, `lesson.py`, `preflight.py`.
  - Additive: `learning/run.py` (thêm stage `lesson` sau `media`, preflight), `learning/cli.py` (in dòng stage `lesson`), `config.py` + `config.example.toml` (key C7 trong `[learning]`).
  - Tests mới `tests/test_learning_lesson.py`, `tests/test_learning_enrich.py` (+ helper/fixture learning mới nếu cần).
  - Docs: task này; `docs/decisions/CL1-chinese-learning-contract.md` (dòng Implementation, § Đo thực tế / CL1.2).
- Out of scope:
  - Web/router/job (CL1.3–CL1.4), phục vụ clip, đổi C10/cách lấy clip, Whisper, `pypinyin`/dependency mới.
  - Đưa `lesson` vào `STAGES`/`PIPELINE_STAGES` của Auto Short.
  - Chốt model G6 (HUMAN LEAD, sau mẫu 20 dòng).

## Authority / key decisions

- `docs/decisions/CL1-chinese-learning-contract.md` R3: C4 (artifact), C7 (AI enrichment), C8 (`lesson.json` v1), C9 (stage `lesson`: inputs, config hash, `downstream`), C12 (CLI).
- `docs/decisions/CP2-workspace-contract.md` D5–D8 (`run_stage`, skip/stale, config hash, exit code).
- Quyết định cục bộ CL1.2 (trong boundary đã duyệt):
  - `[learning]` thêm (mặc định): `model = "qwen3:14b"`, `think = false`, `temperature = 0.0`, `seed = 42`, `num_ctx = 8192`, `prompt_version = "v1"`, `batch_lines = 20`, `retries = 2`; execution-only: `ollama_host = "http://127.0.0.1:11437"` (env `OLLAMA_HOST` ghi đè qua `resolve_host`), `timeout = 600.0`, `retry_backoff = [5.0, 15.0]`. Validate kiểu/khoảng trong `config.py` như section khác (`batch_lines ≥ 1`, `retries ≥ 0`); `prompt_version` kiểm trong `run_learning` trước mọi stage (như `run_selection`, tránh import vòng) → `LearningError`.
  - Stage `lesson`: `downstream = ()`; `inputs` = `[{"path": "subtitle.json3", "sha256"}, {"path": "source.json", "sha256"}]` + `{"path": "clip.mp4", "sha256"}` khi file có mặt; `config_hash` = `{"learning.model", "learning.think", "learning.temperature", "learning.seed", "learning.num_ctx", "learning.prompt_version", "learning.prompt_sha256", "learning.batch_lines", "learning.window_seconds"}` — **không** gồm `ollama_host`, `timeout`, `retry_backoff`, `retries`. `prompt_sha256` như CP5 (prompt sửa mà quên tăng version vẫn không skip).
  - Dòng bài học: segment `normalize(parse_json3(subtitle.json3))` có `kind = speech`, `start < window_seconds` (dùng lại `subtitle.in_window`) → `{id, start, end, zh = text}`; batch liên tiếp `batch_lines` dòng.
  - Payload user message mỗi batch = **đúng** JSON `[{"id", "zh"}]` (không timestamp, thời lượng, media, tiêu đề); hướng dẫn nằm ở system prompt có version. Output ép bằng JSON schema `format`: `{"lines": [{"id", "pinyin", "vi"}]}`.
  - Validation batch (lý do đầu tiên → reject): JSON không parse/không đúng dạng; `id` trùng; thiếu `id`; thừa `id`; `pinyin` rỗng (sau strip); `pinyin` chứa chữ Hán (CJK Unified/Ext A) hoặc chữ không phải Latin; `vi` rỗng. Field khác bị bỏ qua (kể cả `zh`/`start`/`end` model trả về). `ChatError` cũng tính là một lần thử thất bại. Retry tới `retries` lần sau lần đầu, chờ `retry_backoff` (sleep injectable).
  - Ghép: `id`, `start`, `end`, `zh` luôn từ dòng subtitle; chỉ `pinyin`, `vi` (đã strip) từ AI. `lines_sha256` = sha256 của `hashing.canonical_json([{id, start, end, zh}])` UTF-8.
  - `lesson.json` đúng C8: `video.url` = `https://youtu.be/<id>`; `video` các field còn lại từ `source.json`; `subtitle` = `{path, sha256 (tính từ file), track (= source.selected.key), auto}`; `media` = `{path: "clip.mp4", sha256 (tính từ file), start, end (từ media.json window)}` hoặc `null` khi không có clip; `enrichment` = `{model, prompt_version, think, temperature, seed}`; `stats` = `{lines, han_chars}`. Không thời điểm tạo, không nội dung log.
  - `lesson_log.json` (không nằm trong `lesson.json`): `schema_version`, `episode_id`, `model`, `prompt_version`, `prompt_sha256`, `options`, `think`, `batches: [{index, ids, attempts: [{attempt, request (messages + format + options), response (content thô | null), error | rejection, duration_s}], accepted_attempt}]`. Thành công: ghi cùng `lesson.json`. Hết retry: stage `failed` (error nêu batch + lý do cuối), `lesson.json` không tồn tại, `lesson_log.json` vẫn được ghi (sau `record_failure`, không nằm trong `artifacts` của entry failed).
  - Preflight: `learning/preflight.py` `learning_preflight(config, *, opener=None, timeout=…)` — `GET <resolve_host(ollama_host)>/api/tags` bằng stdlib `urllib` (không import từ `pipeline.py`), kiểm `[learning] model` có mặt (`name`/`model`, `:latest` như CP8 E8) → `LearningPreflightError` với thông điệp rõ (không tới được / thiếu model + `ollama pull`). `run_learning` gọi preflight (injectable) **ngay trước** stage `lesson` chỉ khi stage đó sẽ chạy (`--force` hoặc `check_up_to_date` ≠ None); lỗi → `LearningError`, không gọi AI.
  - Orchestrator: `subtitle → media → lesson`, dừng ở stage lỗi đầu tiên (media lỗi → không chạy lesson). `subtitle` giữ `downstream=("lesson",)`.
  - CLI: thêm dòng `<id>\tlesson\t<ran|skipped (up to date)>`; dòng cuối giữ `<id>\tdone\t<workspace dir>`; lỗi preflight → exit 1 `auto-short: error: …`.

## Implementation approach

- `prompt.py`: `PROMPT_VERSION`, system prompt v1 (tiếng Việt/Anh ngắn: mỗi câu tiếng Trung → Pinyin có dấu thanh, tách theo từ/âm tiết, không chữ Hán; nghĩa tiếng Việt tự nhiên; giữ nguyên `id`; không thêm/bớt dòng), `OUTPUT_SCHEMA`, `prompt_texts(version)`, `prompt_sha256(version)`, `batch_payload(lines) -> str`.
- `enrich.py`: hàm thuần `validate_batch(submitted_ids, content) -> (dict id→(pinyin, vi)) | reason`; `enrich(lines, cfg, client, sleep) -> (enrichment by id, log doc)` raise `EnrichmentError(batch, reason, log)` khi hết retry.
- `lesson.py`: `STAGE = "lesson"`, `used_config`, `inputs`, `produce(ws, config, client, sleep)` (đọc artifact, gọi enrich, dựng + ghi `lesson.json`/`lesson_log.json` atomic), `remove_outputs`.
- `run.py`: thêm stage; truyền `client`, `sleep`, `preflight` injectable cho test.

## Acceptance Criteria

1. Payload Ollama mỗi batch chỉ chứa `[{"id", "zh"}]` — không `start`/`end`/thời lượng/timestamp/media.
2. AI giả trả `id`/`zh`/`start`/`end` khác → `lesson.json` mang giá trị subtitle; `lines_sha256` khớp giá trị tính trực tiếp từ subtitle.
3. Thiếu / thừa / trùng `id`, `pinyin` rỗng, `vi` rỗng, `pinyin` có chữ Hán → reject + retry; retry rồi đúng → thành công, log có mọi lần thử + lý do; hết retry → `failed`, `error` nêu batch + lý do, không còn `lesson.json`, `lesson_log.json` giữ mọi request/response + lý do.
4. `lesson.json` đúng C8, thứ tự key cố định, không thời điểm tạo; AI giả deterministic + `--force` → byte-identical; `media` trỏ `clip.mp4` với sha thật hoặc `null`.
5. Chạy lại không đổi → `lesson` skip; đổi `model` / `prompt_version` / key khác trong config hash → chạy lại; đổi `ollama_host` / `timeout` / `retries` / `retry_backoff` → skip; `subtitle` chạy lại → `lesson` stale + chạy lại, `media` không chạy lại.
6. Preflight: không tới được Ollama / thiếu model → lỗi rõ, không gọi `chat`.
7. Auto Short không đổi: `git diff 0a61637 -- src/auto_short/pipeline.py src/auto_short/ingest src/auto_short/transcript src/auto_short/selection src/auto_short/web src/auto_short/workspace.py pyproject.toml` rỗng; test Auto Short hiện có không bị sửa. Ngoại lệ duy nhất (HUMAN LEAD 2026-09-27, vì orchestrator thêm stage `lesson`): test learning CL1.1 `tests/test_learning_cli.py`, `tests/test_learning_subtitle.py`, `tests/test_learning_media.py`, `tests/learning_helpers.py` được sửa **hẹp** — chỉ (a) thêm dòng/file/stage `lesson` vào giá trị mong đợi, (b) inject fake preflight/client/sleep để không test nào gọi Ollama thật; không xóa, không nới điều kiện kiểm tra nào.

## Required verification

- `pytest -q tests/test_learning_lesson.py tests/test_learning_enrich.py` — AC1–AC6.
- `pytest -q` — hồi quy.
- `node scripts/framework-check.mjs` PASS.
- Lệnh `git diff` ở AC7 rỗng; `git diff 0a61637 --stat -- tests` chỉ có file mới + 4 file CL1.1 ở ngoại lệ AC7 (review từng hunk: không assertion nào bị xóa/nới).
- Số đo thật trên video CL1.1 (≥ 2): `qwen3:14b` think off + 1 model so sánh (`qwen3:30b` think off) → tổng thời gian, thời gian từng batch, số retry, mẫu 20 dòng liên tiếp, nhận xét Pinyin / nghĩa → CL1 contract § Đo thực tế / CL1.2. Model **chưa** chốt cho tới khi HUMAN LEAD đọc mẫu.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Task chạm CLI công khai (thêm stage) và schema artifact mới; **không** chạm database, security model hay web API. Manual test sau automated verification là điểm danh; riêng mẫu 20 dòng là gate G6.

- [ ] `auto-short learn <URL CL1.1>` → `lesson.json` có Pinyin + nghĩa; chạy lại → cả ba stage skip.
- [ ] Đọc mẫu 20 dòng thật (Pinyin, nghĩa) → chốt model G6.

## Result

- Main changes:
  - Mới `src/auto_short/learning/prompt.py` (prompt `v1`, `OUTPUT_SCHEMA`, `prompt_sha256` = system prompt + schema, `batch_payload` = đúng `[{"id","zh"}]`), `enrich.py` (`validate_batch`, `enrich` với retry/backoff/sleep injectable, `EnrichmentError` mang log), `lesson.py` (stage `lesson`: `used_config`, `inputs`, `produce`, `lesson.json` C8, `lesson_log.json`), `preflight.py` (`learning_preflight`, `LearningPreflightError`, stdlib `urllib`, không import `pipeline.py`).
  - `learning/run.py`: `subtitle → media → lesson`; `prompt_version` kiểm trước mọi stage; preflight (injectable, mặc định `learning_preflight`) gọi ngay trước `lesson` chỉ khi `--force` hoặc `check_up_to_date` ≠ None; `client`/`sleep` injectable; lỗi `lesson` → xóa `lesson.json` + `lesson_log.json`, rồi ghi `lesson_log.json` của lần lỗi **sau** `record_failure` (không nằm trong `artifacts`). `learning/cli.py`, `learning/__init__.py`: docstring (dòng `lesson` in qua `on_stage` sẵn có).
  - `config.py` + `config.example.toml`: key C7 trong `[learning]` (additive, mặc định như quyết định cục bộ; execution-only: `ollama_host`, `timeout`, `retries`, `retry_backoff`).
  - Docs: CL1 contract dòng Implementation + § Đo thực tế / CL1.2.
- Tests:
  - Mới `tests/test_learning_enrich.py` (41) + `tests/test_learning_lesson.py` (30): payload chỉ `id`+`zh`; AI đổi `id`/`zh`/`start`/`end` → giữ giá trị subtitle, `lines_sha256` tính lại độc lập; thiếu/thừa/trùng `id`, `pinyin` rỗng, `vi` rỗng, Hán (cả Ext A) / chữ ngoài Latin trong `pinyin`; retry rồi thành công (log mọi lần thử + lý do, backoff 5/15); hết retry → `failed`, error nêu batch + lý do, không `lesson.json`, `lesson_log.json` còn đủ; `ChatError`; Ctrl-C; byte-identical qua `--force`; `media` sha thật / `null`; skip; đổi `model`/`think`/`temperature`/`seed`/`num_ctx`/`batch_lines`/`prompt_version`/prompt text → chạy lại; `ollama_host`/`timeout`/`retries`/`retry_backoff` → skip; `subtitle` chạy lại → `lesson` stale + chạy lại, `media` không; clip đổi → `lesson` chạy lại; preflight không tới được / thiếu model / `:latest` / env `OLLAMA_HOST` / không gọi khi skip / không gọi `chat` khi lỗi; media lỗi → không chạy lesson; CLI dòng `lesson` + exit 1 khi preflight lỗi; config `[learning]` mặc định/giá trị/không hợp lệ + `config.example.toml`.
  - Ngoại lệ AC7 (hẹp): `tests/learning_helpers.py` thêm `FakeChat`, `FakePreflight`, fixture autouse `no_real_ollama` (thay `OllamaClient`/`learning_preflight` mặc định của `learning.run`); `tests/test_learning_cli.py`, `test_learning_subtitle.py`, `test_learning_media.py` chỉ import fixture đó và thêm dòng/file/stage `lesson` vào giá trị mong đợi; trong `test_rerun_and_stale_rules` lần `--force` cuối inject preflight lỗi để trạng thái `stale` của `lesson` vẫn quan sát được (assertion giữ nguyên). Không xóa/nới assertion nào.
  - `pytest -q tests/test_learning_lesson.py tests/test_learning_enrich.py`: 71 passed. `pytest -q`: 738 passed (1 warning có sẵn). `node scripts/framework-check.mjs`: PASS. `git diff 0a61637 -- src/auto_short/pipeline.py src/auto_short/ingest src/auto_short/transcript src/auto_short/selection src/auto_short/web src/auto_short/workspace.py pyproject.toml`: rỗng.
  - Đo thật (G6): CL1 contract § Đo thực tế / CL1.2 — `qwen3:14b` 3/3 video done (57–67 s/video, batch 20 dòng ≈ 12–19 s), `qwen3:30b` 2/3 done (26–29 s/video, batch ≈ 5–7 s), 1 failed (Hán trong Pinyin, lặp lại y hệt ở cả 3 lần thử).
- Review:
- Important findings / decisions:
  - Retry với `temperature = 0` + `seed` cố định tái tạo cùng output → chỉ cứu lỗi mạng/timeout, không cứu lỗi nội dung (đo thật: 30b `DVRy3l9ojq4` failed dù 2 retry). Đổi chiến lược retry là quyết định riêng, chưa làm.
  - Cả hai model sai Pinyin ở mức đáng kể (âm sai hẳn, thiếu dấu, biến điệu 一/不 không nhất quán); validation C7 không phát hiện được loại lỗi này. Model G6 **chưa chốt** — chờ HUMAN LEAD đọc mẫu 20 dòng.
- Known limitations:
  - Một dòng lỗi làm cả stage `lesson` `failed` (không có `lesson.json` một phần — đúng C7).
  - Pinyin do LLM: không kiểm thanh/âm (C7; `pypinyin` là proposal riêng).
  - Số đo thời gian trên GPU dùng chung, chỉ tham khảo.
- PR:
