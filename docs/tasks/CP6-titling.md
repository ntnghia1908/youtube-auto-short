# Task: CP6 — AI Title / Hook Generation

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `0ce2a04` (main, sau merge PR #7) / `feature/cp6-titling`
- Human Lead approval: accepted (APPROVE TASK, 2026-09-26; G1–G10; P1 `max_chars` = 60 — title được phép 3 dòng hoặc thu nhỏ chữ ở CP7; P2–P4 theo đề xuất: evidence chặn, `untitled` + cảnh báo, không đưa `topic`)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì CP6: (a) tạo artifact contract `titles.json` mà CP7 (render), CP9 (review) dùng lại; (b) là boundary deterministic ↔ AI thứ hai (CP1 §8): prompt/versioning, validation title, rule header deterministic; (c) mở rộng config + CLI; (d) sửa CP1 §4/§6: title tối đa 60 ký tự, được phép 3 dòng hoặc thu nhỏ chữ (P1). Quyết định G1–G10 dưới đây duyệt cùng APPROVE TASK. Không thêm dependency.

## Goal

Từ một episode đã có `clips.json` (CP5), stage `titling` sinh `work/<id>/titles.json`: một **header** deterministic cho episode (speaker / series / tập — không AI, CP1 §6) và cho **mỗi clip** một title/hook tiếng Việt ngắn do Ollama (mặc định `qwen3:30b` + think) sinh từ chính text của clip, qua validation deterministic (độ dài, một dòng, không emoji/clickbait ký tự, có trích dẫn căn cứ nằm trong text clip); mọi lời gọi AI lưu ở `titling_log.json` để review/truy vết (roadmap CP6; CP1 §4, §6, §8).

## Scope

- In scope:
  - Subpackage `src/auto_short/titling/`: resolve header (G2), dựng text clip (G3), prompt (G4), parse + validate option (G5), chọn title, validation artifact (G8), stage.
  - Artifact `titles.json` (schema v1) và `titling_log.json`.
  - Config `[titling]` + `[titling.header]` (typed, `tomllib`), `config.example.toml`.
  - CLI `auto-short titling <episode_id> [--force] [--config PATH] [--speaker S] [--series S] [--episode N]`.
  - Tests `pytest` không cần Ollama/video thật (fake client; fixture `clips.json` + `candidates.json` nhỏ, có clip `head_cut`).
  - Chạy thật trên `rbjfCfFq3Dk` (13 clip) với `qwen3:30b` think on (mặc định) và `qwen3:14b` think off để so sánh; HUMAN LEAD đọc title rồi chốt model (CP1 §11).
  - Docs: decision record `docs/decisions/CP6-titling-contract.md` (ACCEPTED sau review); CP1 §4/§6 (theo P1) và §11 (chốt model titling); project profile (module map `titling/` → implemented, authority order); README (usage); current-state.
- Out of scope:
  - Render panel, font, ngắt dòng thực tế, cỡ chữ (CP7) — CP6 chỉ bảo đảm giới hạn ký tự; header/title có vừa khung hay không do CP7 kiểm với font đã chốt.
  - Review/sửa title bằng tay (CP9); title/description/hashtag để upload YouTube (ngoài scope CP1 §2).
  - Dùng AI cho header; sửa `clips.json`/selection (CP5), `candidates.json` (CP4).
  - Cache/tái dùng kết quả AI giữa các lần chạy (đổi header → gọi lại AI cho mọi clip; chấp nhận).
  - Di chuyển/refactor client Ollama của CP5 thành module dùng chung (xem G10).

## Authority / key decisions

- `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP6; `docs/decisions/CP1-product-contract.md` §1 (metadata header qua config/CLI), §4 (header ≤ 3 dòng, title ≤ 2 dòng, cỡ chữ title ≈ 1.5× header), §6 (header deterministic; title ≤ 60 ký tự, ≤ 2 dòng, không thêm thông tin, không emoji/clickbait; `titles.json` có clip ID, model, prompt version, source hash), §8 (AI + validate), §10–§11 (Ollama qua `urllib`, host/model không hard-code); `docs/decisions/CP2-workspace-contract.md` D1–D8 (nguyên trạng); `docs/decisions/CP5-selection-contract.md` B3 (request/client), B5 (retry/backoff), B7 (`clips.json`, `head_cut`), B11.
- Dữ kiện đo 2026-09-26 (main `0ce2a04`, `work/rbjfCfFq3Dk`):
  - `clips.json`: 13 clip, 2 có `head_cut` (`k04` "thì", `k10` "thế là"). Text clip (nối text unit `unit_ids[0]..unit_ids[1]` trong `candidates.json`) dài 61–218 từ → prompt mỗi clip nhỏ (< 1k token + system).
  - Caption auto không dấu câu, viết hoa lộn xộn, có lỗi nhận dạng (vd "Tướng Tùy Tâm chuyển", "liền xanh", "dù ký pháp").
  - `metadata.json` title: "Phật Thuyết Thập Thiện Nghiệp Đạo Kinh tập 9 - Lão Pháp Sư Tịnh Không"; regex `^(?:Phật Thuyết\s+)?(?P<series>.+?)\s+tập\s+(?P<episode>\d+)\b` → `series` "Thập Thiện Nghiệp Đạo Kinh", `episode` "9". Ảnh mẫu CP1 §4 có header "HT.Tịnh Không" / "Thập Thiện Nghiệp Đạo Kinh (tập 14)" (hiển thị thành 3 dòng) — speaker trong mẫu **không** suy được từ title YouTube ("Lão Pháp Sư Tịnh Không").
  - Ảnh mẫu: title "Các bậc thang tu học Phật pháp" (30 ký tự) chiếm đủ 2 dòng ở cỡ chữ mẫu (dòng dài nhất ≈ 16 ký tự) → ước lượng **≈ 16–18 ký tự/dòng, ≈ 34–36 ký tự cho 2 dòng**. 60 ký tự (CP1 §6) không vừa 2 dòng ở cỡ chữ mẫu (xem P1).
  - Ollama `127.0.0.1:11437` truy cập được; model `qwen3:30b`, `qwen3:14b`, `qwen3-embedding:4b/8b`.
- Quyết định (DECIDE cùng APPROVE TASK):
  - **G1 Stage / artifact:** stage `titling` (CP1 §8, đã có trong `STAGES`), subpackage `src/auto_short/titling/`. Artifact `titles.json` (trusted, qua G8) và `titling_log.json` (log AI). Ghi atomic; `titles.json` không chứa timestamp (CP2 D5).
  - **G2 Header (deterministic, không AI):**
    - Trường `speaker`, `series`, `episode`; mỗi trường resolve theo thứ tự: CLI flag (`--speaker/--series/--episode`) > config `[titling.header]` (chuỗi không rỗng) > named group cùng tên của `title_pattern` (regex, config) khớp `metadata.title`. Nguồn từng trường ghi ở `header.sources` (`cli | config | metadata`).
    - Dòng header = template `[titling.header] lines`, mặc định `["{speaker}", "{series} (tập {episode})"]`; 1–3 dòng (CP1 §4); dòng render ra rỗng → lỗi. Trường template cần mà không resolve được → stage `failed` với `error` nêu trường + flag cần truyền (vd video local không có title).
    - Mặc định config: `speaker = "HT.Tịnh Không"` (theo ảnh mẫu), `series = ""`, `episode = ""`, `title_pattern` = regex ở dữ kiện đo. Video test → `["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"]`.
    - CP6 không ngắt dòng; "dòng" là dòng logic. Ngắt dòng hiển thị và kiểm ≤ 3 dòng hiển thị là của CP7.
    - Header đã resolve (`lines`) vào `config_hash`. CLI flag không được lưu lại: chạy lại không flag mà giá trị resolve khác → chạy lại stage (giá trị ổn định nên đặt trong config). Chấp nhận.
  - **G3 Text clip:** với mỗi clip trong `clips.json`: text = nối (một khoảng trắng) `text` các unit từ `unit_ids[0]` tới `unit_ids[1]` trong `candidates.json`. Clip có `head_cut` → bỏ các token đầu khớp `head_cut.words` (chuẩn hóa như CP5 B11); không khớp → `failed` (dữ liệu không nhất quán). `clips.json.candidates_sha256` phải khớp `candidates.json` đã đọc, nếu không → `failed` (chạy lại selection). `clips: []` → `titles: []`, stage `done`, không gọi AI.
  - **G4 Prompt (version `prompt_version`, mặc định `"v1"`, hằng trong `titling/prompt.py`; đổi chữ nào phải thêm version; `prompt_sha256` vào `config_hash`, như CP5 B3):**
    - System prompt (tiếng Việt): đặt tiêu đề cho một YouTube Short cắt từ bài giảng Phật pháp; tiêu đề nêu đúng ý chính **của chính đoạn này**; tiếng Việt, một dòng, ≤ `max_chars` ký tự; viết hoa chữ đầu câu và danh từ riêng (kiểu "Các bậc thang tu học Phật pháp"); chỉ dùng thông tin có trong đoạn, không thêm tên người giảng/tên kinh/số tập (đã có ở header), không emoji, hashtag, dấu chấm than, ngoặc kép bao ngoài, không giật tít; caption không có dấu câu và có thể sai chính tả → được sửa chính tả hiển nhiên nhưng không đổi ý.
    - User message mỗi clip: `Video: <metadata.title | (không rõ)>`, thời lượng clip, text clip (G3).
    - Output JSON (`format` schema): `{"options": [{"evidence", "title"}]}` — đúng `n_options` (mặc định 3) option, tốt nhất trước; `evidence` = trích **nguyên văn** một cụm liên tiếp (3–25 từ) trong text làm căn cứ cho title (thứ tự property: căn cứ trước title).
    - Mỗi clip một lời gọi. Request như CP5 B3: `POST /api/chat`, `stream: false`, `think`, `options = {temperature, seed, num_ctx}`.
  - **G5 Validate option (deterministic, code) và chọn title:**
    - Chuẩn hóa title: NFC, bỏ khoảng trắng hai đầu, gộp khoảng trắng.
    - Option `valid` ⇔ không rỗng; không xuống dòng; `min_chars` ≤ số ký tự (code point NFC) ≤ `max_chars`; không chứa emoji/pictograph, `#`, `@`, `!`, URL; không bị bao bởi ngoặc kép; không viết HOA toàn bộ; `evidence` sau chuẩn hóa (NFC, lowercase, bỏ dấu câu, gộp khoảng trắng) là chuỗi con của text clip đã chuẩn hóa và có ≥ 3 từ (P2). Không đạt → `invalid` + `reject_reason`. Không sửa/cắt title của AI.
    - Title = option `valid` đầu tiên theo thứ tự AI; các option `valid` còn lại lưu `alternatives` (cho CP9).
    - Không option nào valid → coi như response lỗi, thử lại theo G6; hết lượt → theo P3.
    - Clickbait/sai nội dung ở mức ý nghĩa không kiểm được bằng code: dựa vào prompt + HUMAN LEAD đọc (manual) + CP9.
  - **G6 Response lỗi:** như CP5 B5 (per clip): HTTP lỗi / timeout / không kết nối / envelope sai / không phải JSON / sai schema (số option ≠ `n_options`, thiếu/sai kiểu trường) → thử lại tối đa `retries` (mặc định 2), backoff `retry_backoff` (mặc định `[5, 15]`, thực thi); hết lượt → stage `failed`, `error` = `clip <kNN>: <lỗi> (after N attempts)`, xóa cả hai artifact.
  - **G7 Schema v1** (thứ tự key cố định; giá trị minh họa):
    ```json
    // titles.json
    {"schema_version": 1, "episode_id": "rbjfCfFq3Dk",
     "clips_sha256": "<sha256 canonical JSON clips.json>",
     "candidates_sha256": "<như clips.json>",
     "header": {"lines": ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"],
                "fields": {"speaker": "HT.Tịnh Không", "series": "Thập Thiện Nghiệp Đạo Kinh", "episode": "9"},
                "sources": {"speaker": "config", "series": "metadata", "episode": "metadata"}},
     "model": {"provider": "ollama", "name": "qwen3:30b", "think": true,
               "options": {"temperature": 0, "seed": 42, "num_ctx": 16384}},
     "prompt_version": "v1", "prompt_sha256": "<G4>",
     "params": {"n_options": 3, "min_chars": 10, "max_chars": 60, "retries": 2},
     "stats": {"clips": 13, "ai_calls": 13, "titled": 13, "untitled": 0},
     "titles": [{"clip_id": "k09", "candidate_id": "c00723", "title": "Tướng tùy tâm chuyển",
                 "evidence": "tướng tùy tâm chuyển lời nói này không sai chút nào",
                 "alternatives": [{"title": "…", "evidence": "…"}], "status": "titled"}]}
    ```
    `titles` cùng thứ tự và cùng số phần tử với `clips.json.clips`; `status` = `titled | untitled` (`title`/`evidence` = `null` khi `untitled`, theo P3). `titling_log.json`: `schema_version`, `episode_id`, `clips_sha256`, `model`, `prompt_version`, `prompt_sha256`, `system_prompt`, `response_format`, `header`, `stats`, `clips`: [{`clip_id`, `candidate_id`, `text`, `ai_calls`: [{`attempt`, `backoff_seconds`, `seconds`, `request`, `response` (raw content, `thinking`, `eval_count`, `prompt_eval_count`, `total_duration`, `done_reason`), `error`, `options`: [{`title`, `evidence`, `status`: `valid | invalid`, `reject_reason`}]}]}].
  - **G8 Validation trước khi ghi (vi phạm → `failed`, lỗi code):** mỗi clip của `clips.json` có đúng một entry, cùng thứ tự, `clip_id`/`candidate_id` khớp; `title` `titled` qua G5 và `evidence` là chuỗi con của text clip; header 1–3 dòng không rỗng; `clips_sha256`, `candidates_sha256` khớp input đã đọc.
  - **G9 Stage / resume / CLI** (`run_stage` CP2 nguyên trạng):
    - Yêu cầu `selection` = `done` và `clips.json`, `candidates.json`, `metadata.json` tồn tại; chưa done → `failed` + `error`, không artifact, không gọi AI.
    - `inputs` = `clips.json`, `candidates.json`, `metadata.json` (relative + sha256).
    - `config_hash` = `[titling]` `model`, `think`, `temperature`, `seed`, `num_ctx`, `prompt_version`, `n_options`, `min_chars`, `max_chars`, `retries` + `prompt_sha256` + header đã resolve (`lines`). **Không** gồm `ollama_host`, `timeout`, `retry_backoff`.
    - Host: env `OLLAMA_HOST` > `[titling] ollama_host` (mặc định `http://127.0.0.1:11437`).
    - Chạy lại titling → downstream stale; selection chạy lại → titling stale (D6).
    - CLI stdout `<episode_id>\t<titled (<n>/<m> clips)|skipped (up to date)>\t<path titles.json>`; stderr: model/host, header, mỗi clip (title chọn, số option valid, thời gian gọi), tổng, cảnh báo retry/untitled; exit code CP2 D8.
  - **G10 Model / client:**
    - `[titling]` là section riêng (CP1 §11: titling chốt model riêng), mặc định `qwen3:30b`, `think = true`, `temperature 0`, `seed 42`, `num_ctx 16384`, `timeout 600`.
    - Dùng lại `ChatClient`, `OllamaClient`, `ChatError`, `resolve_host` từ `auto_short.selection.client` bằng import; không di chuyển/sửa code CP5 (tránh shared abstraction mới). Backoff: cùng quy tắc CP5 B5 (được import hàm từ selection hoặc viết lại hàm nhỏ trong titling — IMPLEMENTER chọn, không đổi hành vi CP5).
    - Đo trên video test: `qwen3:30b` think on và `qwen3:14b` think off → thời gian, số option valid/invalid theo lý do, số retry/untitled, bảng 13 title của mỗi cấu hình; HUMAN LEAD đọc và chốt model (ghi CP1 §11). Chạy lại `--force` cùng config → ghi mức khác biệt (không tất định như CP5, không che).
- **Sửa G4 (HUMAN LEAD 2026-09-26, sau đọc title v1):** title v1 quá cao siêu (thuật ngữ Hán Việt, văn giảng kinh). Thêm prompt **v2**, mặc định `prompt_version = "v2"`, v1 giữ nguyên văn để so sánh:
  - Người đọc: người học Phật tại gia và người bình dân. Title là **hook YouTube**: đọc vào là hiểu ngay, lời lẽ đời thường, gần gũi, gợi một chút tò mò (vd nêu câu hỏi hoặc vấn đề đời sống mà đoạn trả lời).
  - Tránh thuật ngữ khó (Hán Việt, Duy thức…) khi có cách nói đời thường tương đương; nếu phải giữ thuật ngữ thì đặt trong ý dễ hiểu.
  - Vẫn chính xác, chỉ dùng thông tin có trong đoạn; **không giật tít** (không hứa hẹn/phóng đại, không "sốc", "bí mật", "không thể tin"…), không emoji, không dấu chấm than. Dấu hỏi được phép.
  - Ví dụ minh họa trong prompt không lấy từ video test (tránh khớp mẫu).
  - Validation G5, schema, evidence (P2) không đổi. Đo lại v2 với cả `qwen3:30b` + think và `qwen3:14b` think off; HUMAN LEAD đọc rồi chốt model + prompt.
- **Cơ chế người dùng tự sửa title (HUMAN LEAD 2026-09-26):** yêu cầu ghi nhận; phạm vi (CP6 hay CP9 review approve/reject/edit) chờ HUMAN LEAD chốt.
- Tham số (chốt cùng APPROVE TASK 2026-09-26):
  - **P1 `max_chars` — chốt (HUMAN LEAD 2026-09-26): 60** (config, mặc định; giữ giới hạn CP1 §6). Title dài hơn sức chứa 2 dòng ở cỡ chữ mẫu (≈ 34–36 ký tự) được phép hiển thị **3 dòng hoặc thu nhỏ chữ** — CP7 quyết cách fit với font chốt. Sửa CP1 §4 (title "tối đa 2 dòng") và §6 ("≤ 60 ký tự, tối đa 2 dòng") theo đó. `min_chars` 10.
  - **P2 Kiểm `evidence` — chốt: chặn** (đề xuất) (option có evidence không nằm trong text → `invalid`). Phương án khác: chỉ ghi log. Nếu đo thấy tỉ lệ invalid do evidence cao (model sửa chính tả khi trích) → báo HUMAN LEAD trước khi nới.
  - **P3 Clip không có title hợp lệ sau retry — chốt:** `untitled` (`title: null`) + cảnh báo, stage vẫn `done` (CP7 không render clip `untitled` cho tới khi CP9 sửa). Phương án khác: stage `failed`.
  - **P4 Đưa `topic` của CP5 vào prompt làm gợi ý — chốt: không** (title chỉ từ text clip, tránh lặp nhận xét của bước chọn).
- Không dependency mới (`urllib`, `json`, `re`, `unicodedata` stdlib).

## Implementation approach

- Hàm thuần: `resolve_header` (G2), `clip_text` (G3), `render_prompt` (G4), `parse_response` + schema check, `validate_option`/`choose_title` (G5), `validate_titles` (G8); stage `run_titling` theo khuôn `selection/stage.py`.
- Prompt là hằng trong code có version; `prompt_sha256` như CP5.
- Fixtures: `clips.json` 3–4 clip (có `head_cut`, có `clips: []`) + `candidates.json` nhỏ; response AI mẫu: hợp lệ, title quá dài, emoji/`!`, evidence không có trong text, thiếu option, JSON hỏng, mọi option invalid.
- Decision record `docs/decisions/CP6-titling-contract.md` là canonical owner của G1–G10, prompt versioning và schema `titles.json`/`titling_log.json`.

## Acceptance Criteria

1. Header đúng G2: thứ tự CLI > config > `title_pattern`; template `lines`; thiếu trường → `failed` nêu flag; video test → `["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"]`; không gọi AI cho header.
2. Text clip đúng G3 (nối unit, bỏ từ `head_cut`); `candidates_sha256` lệch → `failed`; `clips: []` → `titles: []`, `done`, không gọi AI.
3. Request Ollama đúng G4 (mỗi clip một lần, `format` schema, `stream: false`, options, `think`, model/host từ config/env); prompt có ràng buộc độ dài, không thêm thông tin, không emoji/clickbait.
4. Validation option đúng G5: mỗi luật loại có test; title = option valid đầu tiên; `alternatives` đúng; không option valid → retry → P3.
5. Response lỗi → retry đúng `retries` + backoff; hết lượt → exit ≠ 0, manifest `failed` + `error`, không artifact dở dang.
6. `titles.json` đúng G7/G8 (ghi clip ID, model, prompt version, source hash — CP1 §6); `titling_log.json` đủ để truy vết mọi option và lý do loại.
7. Chạy lại → `titling: skip (up to date)` (không gọi AI); đổi key `[titling]` trong hash / header resolve khác / selection chạy lại → chạy lại; đổi `ollama_host`/`timeout`/`retry_backoff` hoặc config stage khác → skip; `--force` luôn chạy lại; selection chưa `done` → `failed`.
8. Không dependency mới; không sửa hành vi CP5; không code render/review.
9. `node scripts/framework-check.mjs` PASS; decision record CP6 ACCEPTED.

## Required verification

- `pytest -q` trong conda env `auto-short` → PASS (AC1–AC7 bằng fixture + fake client; test CP5 vẫn PASS).
- Chạy thật `auto-short titling rbjfCfFq3Dk` với hai cấu hình G10 → ghi thời gian, số call/retry, option valid/invalid theo lý do, số titled/untitled, bảng title; script kiểm độc lập trên `titles.json` thật: mọi clip có entry đúng thứ tự, title qua luật G5, evidence nằm trong text clip, header đúng (AC1, AC4, AC6).
- Chạy lại không đổi → skip, không gọi AI, sha256 `titles.json` không đổi; `--force` cùng config → so sánh (G10).
- `auto-short status rbjfCfFq3Dk` → `titling done`.
- `git diff --stat main...HEAD` + đọc `pyproject.toml` (AC8).
- `node scripts/framework-check.mjs` (AC9).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract mạng (chỉ gọi Ollama nội bộ đã duyệt CP1 §10–11). CLI thêm lệnh; manual test là điểm danh sau automated verification, nhưng **chất lượng title do HUMAN LEAD đọc quyết** (model, P1).

- [ ] Đọc header và 13 title (mỗi cấu hình) cạnh text clip: đúng ý chính, không thêm thông tin, không giật tít, chính tả đúng.
- [ ] Xem `alternatives` và option bị loại trong `titling_log.json`: lý do loại hợp lý.
- [ ] `auto-short status rbjfCfFq3Dk` → `titling done`.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
