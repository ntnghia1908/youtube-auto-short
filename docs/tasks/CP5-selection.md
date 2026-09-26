# Task: CP5 — AI Clip Selection

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `f0c21d4` (main, sau merge PR #6) / `feature/cp5-selection`
- Human Lead approval: accepted (APPROVE TASK, 2026-09-26; B1–B10; P1–P3 theo đề xuất mặc định: P1 `think` quyết sau đo, tạm `false`; P2 `min_score` 7; P3 không đạt clip → `done` + `clips: []`)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì CP5: (a) tạo artifact contract `clips.json` mà CP6 (title), CP7 (render), CP9 (review) dùng lại; (b) là boundary deterministic ↔ AI đầu tiên (CP1 §8): prompt/versioning, validation output AI, rule chống chồng lấn và giới hạn số clip; (c) sửa CP1 §5 (tối đa 25 clip); (d) mở rộng config + CLI. Quyết định B1–B10 dưới đây duyệt cùng APPROVE TASK. Không thêm dependency.

## Goal

Từ một episode đã có `candidates.json` (CP4), stage `selection` gọi Ollama (mặc định `qwen3:14b`) để đánh giá **ý trọn vẹn** trên text theo unit và sinh `work/<id>/clips.json`: tối đa 25 clip, mỗi clip là đúng một candidate CP4 tồn tại (tham chiếu `candidate_id`), không chồng lấn nhau, kèm điểm, lý do và đánh giá câu đầu/câu cuối trọn ý của AI; mọi lời gọi AI (prompt, model, options, response thô) lưu ở `selection_log.json` để review/truy vết (roadmap CP5 Success; CP1 §5, §8).

## Scope

- In scope:
  - Subpackage `src/auto_short/selection/`: client Ollama (`urllib`, stdlib), dựng prompt theo window, parse + validate response, map về candidate, chọn cuối deterministic (chống chồng lấn, giới hạn số clip), validation artifact.
  - Artifact `clips.json` (schema v1) và `selection_log.json`.
  - Config `[selection]` (typed, `tomllib`), `config.example.toml`.
  - CLI `auto-short selection <episode_id> [--force] [--config PATH]`.
  - Tests `pytest` không cần Ollama/video thật (fake LLM client; fixture `candidates.json` nhỏ + trích từ `rbjfCfFq3Dk`).
  - Chạy thật trên `rbjfCfFq3Dk` với `qwen3:14b` (think bật/tắt) và `qwen3:30b` để đo; render thử (scratchpad, không phải CP7) vài clip có áp `trims` để HUMAN LEAD nghe.
  - Docs: decision record `docs/decisions/CP5-selection-contract.md` (ACCEPTED sau review); CP1 §5 sửa tối đa 20 → **25**; CP1 §11 ghi kết quả đo model; project profile (module map `selection/` → implemented); README (usage); current-state.
- Out of scope:
  - Title/hook (CP6); render thật + `render_manifest.json` (CP7); review approve/reject/edit (CP9).
  - Tạo timestamp/candidate mới, nối qua hard break, sửa/mở rộng candidate (CP1 §5: AI chỉ chọn trong candidate).
  - Sửa CP4 (điểm cắt, hard break). Nhãn `[âm nhạc]` ngắn có thể nhận nhầm (Result CP4) chỉ ghi nhận ảnh hưởng; xử lý là task riêng (CP4 change) hoặc CP9.
  - Phục hồi dấu câu / NLP segmentation; embedding; so sánh `gemma3:12b` (chưa pull trên máy GPU → CP10).
  - Thay đổi manifest schema v1, rule skip/stale (CP2), `candidates.json` (CP4).

## Authority / key decisions

- `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP5; `docs/decisions/CP1-product-contract.md` §3 (30/60–90/180 s sau rút khoảng lặng), §5 (trọn ý, không chồng lấn, chỉ chọn trong candidate), §8 (AI + validate), §10 (Ollama qua `urllib`), §11 (`OLLAMA_HOST`, `qwen3:14b`, đo so sánh); `docs/decisions/CP2-workspace-contract.md` D1–D8 (dùng lại nguyên trạng); `docs/decisions/CP4-analysis-contract.md` A7–A10 (unit, candidate, `candidates.json`).
- **Sửa CP1 §5 (HUMAN LEAD 2026-09-26, mở CP5):** tối đa **25** Short mỗi episode (config `max_clips`), thay cho 20. Ưu tiên trọn ý vẫn đứng trên số lượng.
- Dữ kiện đo 2026-09-26 trên `work/rbjfCfFq3Dk/candidates.json`:
  - 195 unit, 5187 từ, 22.6k ký tự text; unit median 8.9 s. 1484 candidate (325 `in_target`).
  - Hard break / content edge chia content thành **11 đoạn liền mạch** (gọi là *window*): số unit `2, 4, 19, 40, 4, 2, 13, 27, 9, 26, 49`; dài nhất 764 s / 1100 từ và 753 s / 1207 từ; số candidate mỗi window 0–540. Candidate không bao giờ vượt window (A8).
  - → Trình bày cho AI **text theo unit của từng window** vừa context (~1.2k từ ≈ vài nghìn token); liệt kê 1484 candidate kèm text là không khả thi (mỗi candidate lặp lại text nhiều unit).
  - Caption auto không có dấu câu; mép unit là khoảng lặng ≥ 3.0 s — điều kiện cần, không đủ cho trọn ý (CP4 Known limitations, vd `c00182` bắt đầu "trong Bồ Tát đặc biệt …"). Mép window do hard break có thể rơi giữa ý (vd nhãn `[âm nhạc]` nhận nhầm `s00275` 1248.15, `s00539` 2380.59).
  - Ollama `127.0.0.1:11435`: lúc soạn contract bị connection reset; HUMAN LEAD kết nối lại khi APPROVE (2026-09-26): model `qwen3:14b` (context 40960, capabilities completion/tools/thinking), `qwen3:30b`, `qwen3-embedding:4b/8b`.
- Quyết định (DECIDE cùng APPROVE TASK):
  - **B1 Stage / artifact:** stage `selection` (CP1 §8), subpackage `src/auto_short/selection/`. Artifact `work/<id>/clips.json` (trusted, qua validation) và `selection_log.json` (log AI: prompt, response thô, parse, lý do loại). Ghi atomic; `clips.json` không chứa timestamp tạo file (provenance ở manifest, CP2 D5). Số giây làm tròn 3 chữ số như CP4.
  - **B2 Window:** window = dãy unit liên tiếp giữa hai ranh giới không phải `silence` (hard break / content edge) — đúng miền mà candidate CP4 có thể nằm. Window không có candidate → không gọi AI. Window có số từ > `max_window_words` (mặc định 2500) → chia thành các window con chồng lấn nhau, mỗi window con ≤ `max_window_words`, phần chồng ≥ số unit của candidate dài nhất bắt đầu trong đó (không mất candidate nào); đề xuất trùng giữa window con gộp theo `candidate_id`. Video test: không window nào bị chia.
  - **B3 Prompt (version `prompt_version`, mặc định `"v1"`, lưu trong code, nội dung đầy đủ ghi ở `selection_log.json`):**
    - Input cho AI mỗi window: thông tin video (title từ `metadata.json` nếu có), rồi danh sách unit `id | thời lượng thực tế sau trim (s) | ranh giới trước (silence x s / hard break / đầu-cuối nội dung) | text`; ràng buộc 30–180 s, mục tiêu 60–90 s; lưu ý caption không có dấu câu, có thể sai chính tả, mép window có thể rơi giữa ý.
    - Yêu cầu: đề xuất các đoạn `first_unit`–`last_unit` **trình bày trọn một ý**: câu đầu tự đứng được (không bắt đầu giữa câu / không phụ thuộc câu trước), câu cuối kết thúc ý (không dở dang); thà không đề xuất còn hơn đề xuất cụt ý. Mỗi đề xuất: `first_unit`, `last_unit`, `score` (1–10, giá trị làm Short độc lập), `start_complete`, `end_complete` (bool), `topic` (ngắn), `reason` (ngắn, tiếng Việt).
    - Output: JSON theo JSON schema qua tham số `format` của Ollama `/api/chat`; `stream: false`; `options.temperature = 0`, `options.seed` cố định, `options.num_ctx` theo config.
  - **B4 Map về candidate (AI chỉ chọn trong candidate, CP1 §5 / CP4 A9):** đề xuất hợp lệ ⇔ tồn tại đúng một candidate có `unit_ids = [first_unit, last_unit]` → lấy `candidate_id`. Không map được (unit không thuộc window, ngược thứ tự, duration ngoài 30–180, bị shot guard loại…) → **loại**, ghi `rejected` kèm lý do trong log; không sửa/nới đề xuất. Không bao giờ sinh timestamp mới.
  - **B5 Response lỗi:** HTTP lỗi / timeout / JSON không parse được / sai schema → thử lại tối đa `retries` lần (mặc định 2) cho window đó; vẫn lỗi → stage `failed` (`error` nêu window và lỗi), không để artifact. Ollama không truy cập được → `failed`.
  - **B6 Chọn cuối (deterministic, code):**
    - Chỉ giữ đề xuất hợp lệ có `start_complete = true`, `end_complete = true` và `score ≥ min_score` (mặc định 7).
    - Sắp theo `score` giảm dần, rồi `in_target` (true trước), rồi `source_start` tăng dần; greedy nhận clip nếu không chồng lấn (khoảng `[source_start, source_end]` giao nhau > 0) clip đã nhận; dừng khi đủ `max_clips` (**25**).
    - Clip cuối sắp theo `source_start`; id `k01`…`k25` theo thứ tự đó (tên file render CP7: `shorts/<clip_id>.mp4`, CP1 §2).
    - Không đạt clip nào → stage `done` với `clips: []` và cảnh báo stderr (CP1 §5: thà ít clip hơn còn hơn cụt ý).
  - **B7 Schema `clips.json` v1** (thứ tự key cố định; giá trị minh họa):
    ```json
    {"schema_version": 1, "episode_id": "rbjfCfFq3Dk",
     "candidates_sha256": "<sha256 canonical JSON candidates.json>",
     "model": {"provider": "ollama", "name": "qwen3:14b", "think": false,
               "options": {"temperature": 0, "seed": 42, "num_ctx": 16384}},
     "prompt_version": "v1", "prompt_sha256": "<sha256 system prompt + template>",
     "params": {"max_clips": 25, "min_score": 7, "max_window_words": 2500, "retries": 2},
     "stats": {"windows": 11, "ai_calls": 10, "proposals": 64, "valid": 52, "eligible": 40, "selected": 18,
               "selected_seconds": 1350.4},
     "clips": [{"id": "k01", "candidate_id": "c00123", "source_start": 187.2, "source_end": 290.5,
                "source_duration": 103.3, "duration": 76.4, "in_target": true,
                "unit_ids": ["u0009", "u0014"], "segment_ids": ["s00040", "s00071"],
                "score": 8, "start_complete": true, "end_complete": true,
                "topic": "…", "reason": "…", "window": "w03"}]}
    ```
    Clip chép các trường thời gian/tham chiếu của candidate để review dễ; `trims` và `text` không chép (CP7/CP9 tra `candidates.json` theo `candidate_id`/`unit_ids`). `selection_log.json`: `windows` [{`id`, `unit_ids`, `ai_calls`: [{`attempt`, `request` (messages + format + options), `response` (raw content, `thinking` nếu có, `eval_count`, `total_duration`), `error`}], `proposals`: [{…đề xuất AI…, `status`: `valid | rejected | ineligible | selected | overlapped | over_limit`, `candidate_id`, `reject_reason`}]}].
  - **B8 Validation trước khi ghi (vi phạm → `failed`, lỗi code):** mọi `candidate_id` tồn tại và các trường chép khớp candidate; clip không chồng lấn nhau; số clip ≤ `max_clips`; `duration` trong 30–180 (thừa kế CP4); `unit_ids`/`segment_ids` hợp lệ; id `k..` duy nhất, theo `source_start`; `candidates_sha256` khớp input.
  - **B9 Stage / resume / CLI** (dùng `run_stage` CP2 nguyên trạng):
    - Yêu cầu `analysis` = `done` và `candidates.json` tồn tại; chưa done → stage `failed` + `error`, không artifact.
    - `inputs` = `candidates.json`, `metadata.json` (relative + sha256).
    - `config_hash` = `model`, `think`, `temperature`, `seed`, `num_ctx`, `prompt_version`, `max_clips`, `min_score`, `max_window_words`, `retries` (+ sha256 prompt trong code). **Không** gồm `ollama_host` / `timeout` (thực thi). Đổi config stage khác (vd render) không chạy lại selection (roadmap CP5).
    - Host: env `OLLAMA_HOST` > config `[selection] ollama_host` (mặc định `http://127.0.0.1:11435`); không hard-code model/host (CP1 §11).
    - Chạy lại selection → downstream stale; analysis chạy lại → selection stale.
    - CLI `auto-short selection <episode_id> [--force] [--config PATH]` — stdout `<episode_id>\t<selected (<n> clips)|skipped (up to date)>\t<path clips.json>`; log (mỗi window: số unit, số đề xuất, thời gian gọi; tổng valid/eligible/selected, tổng thời lượng) ra stderr; exit code theo CP2 D8.
  - **B10 Model / reproducibility:** mặc định `qwen3:14b`, `temperature 0`, `seed 42`. `think` là tham số đo (P1). Đo trên video test: `qwen3:14b` think off, `qwen3:14b` think on, `qwen3:30b` think off → thời gian, số đề xuất/valid/selected, và mẫu clip để HUMAN LEAD nghe; HUMAN LEAD chốt model + `think` (ghi CP1 §11). Chạy lại cùng config với `--force` → so sánh `clips.json` (kỳ vọng giống; nếu Ollama không deterministic thì ghi nhận mức khác biệt, không che).
- **Sửa B3 (HUMAN LEAD 2026-09-26, sau đo v1):** thêm prompt **v2** — mỗi dòng unit có thêm thời gian cộng dồn (thời lượng Short thực tế tính từ đầu window, theo cách tính của đề xuất) để model tự kiểm 30–180 s; `prompt_version` mặc định `"v2"`, giữ v1 trong code để so sánh. Đo lại v2 với các cấu hình B10 (bỏ `qwen3:30b` think off — không dùng được, xem Result) và render mẫu; HUMAN LEAD nghe một lượt cả v1/v2 rồi chốt P1 + model.
- **Chốt P1 + model (HUMAN LEAD 2026-09-26, sau nghe mẫu v1/v2):** cấu hình **C2** — `qwen3:30b`, `think = true`, prompt `v2` là mặc định (CP1 §11 ghi chốt model).
- **B11 Lọc từ nối câu đầu (HUMAN LEAD 2026-09-26, thêm trong CP5):** bộ lọc deterministic trong code, chạy sau B4, trước B6: đề xuất valid có `text` của unit đầu (chuẩn hóa NFC, lowercase, gộp khoảng trắng) bắt đầu bằng một cụm trong `start_blocklist` (khớp trọn từ) → `ineligible`, `reject_reason = "start connector: <cụm>"`. `start_blocklist` là config `[selection]` (vào `config_hash`), mặc định là danh sách từ nối của prompt v2: "cho nên", "vì vậy", "thế nên", "thế là", "do đó", "còn", "và", "nhưng", "mà", "rồi", "thì", "cái này", "điều đó", "việc này", "như vậy", "ở đây". Danh sách rỗng → tắt lọc. Không sửa/nới đề xuất, không đổi prompt. Giới hạn đã biết: không bắt được câu mở giữa câu không có từ nối.
- Tham số HUMAN LEAD cần chốt (đề xuất mặc định, có thể chốt lại sau đo như P1 của CP4):
  - **P1 `think`:** đề xuất quyết sau đo (mặc định `false` cho tới khi chốt).
  - **P2 `min_score`:** 7 / 10.
  - **P3 Không đạt clip nào:** `done` + `clips: []` (đề xuất) hay `failed`.
- Không dependency mới: `urllib` + `json` stdlib (CP1 §10).

## Implementation approach

- Hàm thuần tách biệt: `build_windows` (B2), `render_prompt` (B3), `parse_response` + schema check, `map_proposals` (B4), `select_clips` (B6), `validate_clips` (B8); client qua Protocol (`ChatClient.chat(messages, format, options, think) -> ChatResult`) để test bằng fake; implementation thật `OllamaClient` gọi `POST <host>/api/chat` bằng `urllib.request`.
- Prompt là hằng trong code, có `PROMPT_VERSION`; đổi nội dung prompt phải tăng version (hash prompt cũng nằm trong `config_hash` để không skip nhầm).
- Fixtures: `candidates.json` tổng hợp nhỏ (2–3 window, hard break, candidate bị shot guard loại) + response AI mẫu (hợp lệ, unit ngoài window, ngược thứ tự, không map được, JSON hỏng, chồng lấn, vượt `max_clips`).
- Decision record `docs/decisions/CP5-selection-contract.md` là canonical owner của B1–B10, prompt versioning và schema `clips.json`/`selection_log.json`.

## Acceptance Criteria

1. Window đúng B2 (mỗi window giữa hai ranh giới không phải `silence`; window không candidate không gọi AI; window quá dài chia chồng lấn không mất candidate).
2. Request Ollama đúng B3 (`/api/chat`, `format` JSON schema, `stream: false`, `temperature`, `seed`, `num_ctx`, `think`, model/host từ config/env); prompt có text unit, thời lượng sau trim, ranh giới và yêu cầu trọn ý.
3. Mọi clip trong `clips.json` là một candidate CP4 tồn tại (`candidate_id`, trường chép khớp); đề xuất không map được bị loại kèm lý do trong log; không có timestamp mới.
4. Chọn cuối đúng B6: chỉ clip `start_complete` + `end_complete` + `score ≥ min_score`; không chồng lấn; ≤ `max_clips` (25); thứ tự ưu tiên và id `k..` đúng; không clip nào → `done`, `clips: []`, cảnh báo.
5. Response lỗi → retry đúng `retries`; vẫn lỗi hoặc Ollama không truy cập được → exit ≠ 0, manifest `failed` + `error`, không artifact dở dang.
6. `selection_log.json` đủ để truy vết mọi quyết định: request, response thô, trạng thái từng đề xuất (B7).
7. Chạy lại → `selection: skip (up to date)` (không gọi AI); đổi key `[selection]` trong hash / analysis chạy lại → chạy lại; đổi `ollama_host`/`timeout` hoặc config stage khác → skip; `--force` luôn chạy lại; analysis chưa `done` → `failed`.
8. Không dependency mới; không code title/render/review. CP1 §5 ghi tối đa 25 clip.
9. `node scripts/framework-check.mjs` PASS; decision record CP5 ACCEPTED.

## Required verification

- `pytest -q` trong conda env `auto-short` → PASS (AC1–AC7 bằng fixture + fake client).
- Chạy thật (cần Ollama truy cập được): `auto-short selection rbjfCfFq3Dk` với ba cấu hình B10 → ghi thời gian, số window/call/đề xuất/valid/eligible/selected, tổng thời lượng clip; script kiểm độc lập trên output thật: mọi clip map đúng candidate, không chồng lấn, ≤ 25, trong 30–180 s (AC3–AC4).
- Chạy lại không đổi → skip, không gọi AI, sha256 `clips.json` không đổi; `--force` cùng config → so sánh `clips.json` (B10).
- `git diff --stat main...HEAD` + đọc `pyproject.toml` (AC8).
- `node scripts/framework-check.mjs` (AC9).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract mạng (chỉ gọi Ollama nội bộ đã duyệt CP1 §10–11). CLI thêm lệnh; manual test là điểm danh sau automated verification, nhưng **chất lượng trọn ý do HUMAN LEAD nghe quyết** (P1, model).

- [ ] Mở `clips.json`: đọc `topic`/`reason` và text unit đầu/cuối của vài clip.
- [ ] Nghe 4–6 clip mẫu (render thô có áp `trims`, gửi file) của mỗi cấu hình B10: câu đầu tự đứng được, câu cuối kết ý, không cụt chữ.
- [ ] Xem `selection_log.json`: các đề xuất bị loại có lý do hợp lý.
- [ ] `auto-short status rbjfCfFq3Dk` → `selection done`.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
