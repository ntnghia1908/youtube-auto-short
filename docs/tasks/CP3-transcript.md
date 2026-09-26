# Task: CP3 — Transcript Acquisition & Normalization

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `85ed95f` / `feature/cp3-transcript`
- Human Lead approval: accepted (APPROVE TASK, 2026-09-26; T1–T9 as proposed)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì CP3: (a) tạo artifact contract `transcript.json` mà CP4–CP6 dùng lại; (b) thêm runtime dependency `faster-whisper` (có trong danh sách CP1 §10 nhưng lần đầu vào `pyproject.toml`, kéo theo transitive deps); (c) mở rộng CLI. Các quyết định T1–T9 dưới đây cần HUMAN LEAD duyệt cùng APPROVE TASK.

## Goal

Từ một episode đã ingest, stage `transcript` sinh `work/<id>/transcript.json` tiếng Việt có timestamp, cùng một contract cho mọi provider, theo thứ tự YouTube caption → phụ đề local → `faster-whisper`; không chạy Whisper khi đã có transcript hợp lệ từ provider trước (roadmap CP3 Success).

## Scope

- In scope:
  - Subpackage `src/auto_short/transcript/`: provider boundary, 3 provider (YouTube caption, local subtitle `.srt/.vtt/.json3`, `faster-whisper`), parser/normalizer, acceptance validation, stage runner.
  - Artifact `transcript.json` (schema v1) + file caption gốc trong `work/<id>/transcript/`.
  - Config `[transcript]` (typed, `tomllib`), `config.example.toml`.
  - CLI `auto-short transcript <episode_id> [--subtitle PATH] [--force] [--config PATH]`.
  - `pyproject.toml`: thêm `faster-whisper` (pin).
  - Tests `pytest` không cần mạng, không cần model Whisper (fake fetcher / fake backend).
  - Docs: decision record `docs/decisions/CP3-transcript-contract.md` (ACCEPTED sau review), project profile (module map `transcript/` → implemented), README (usage + model Whisper), current-state.
- Out of scope:
  - Sentence/idea segmentation, phục hồi dấu câu, shot detection, candidate (CP4). CP3 chỉ giữ word timing để CP4 dùng.
  - Translation, TTS, dubbing; clip selection; title (CP5/CP6).
  - Tối ưu tốc độ Whisper / GPU (CP11); chạy Whisper cho cả video 1 giờ không phải required verification.
  - Thay đổi manifest schema v1 hay rule skip/stale của `docs/decisions/CP2-workspace-contract.md`.
  - Dependency ngoài CP1 §10.

## Authority / key decisions

- `AUTO_SHORT_CHECKPOINT_PLAN.md` §3, §4 CP3; `docs/decisions/CP1-product-contract.md` §1, §5, §8, §10, §11; `docs/decisions/CP2-workspace-contract.md` D1–D8 (stage framework dùng lại nguyên trạng).
- Dữ kiện đo 2026-09-26 trên video test `rbjfCfFq3Dk`: caption YouTube chỉ có auto (`vi-orig`, `vi`), không có manual; json3 có 827 event dòng chữ + word timing (`tOffsetMs`, `acAsrConf`), không dấu câu, có nhãn `[âm nhạc]`; event chồng thời gian (roll-up) nên tổng duration > độ dài video.
- Quyết định đề xuất (DECIDE cùng APPROVE TASK):
  - **T1 Provider boundary:** `TranscriptProvider` (Protocol) trong `src/auto_short/transcript/`; mỗi provider trả về transcript thô đã parse hoặc báo `unavailable`/`error`. Thứ tự cố định `youtube → local_subtitle → whisper`; config chỉ được **tắt** provider, không đổi thứ tự. Provider đầu tiên có transcript qua validation (T5) thắng; provider sau không được gọi.
  - **T2 YouTube caption:** chỉ áp dụng khi `source.kind = youtube`. Lấy bằng `yt-dlp` (skip download video) định dạng `json3`. Ưu tiên track: manual `vi` → auto `vi-orig` → auto `vi`. File gốc lưu `work/<id>/transcript/youtube.<track>.json3`. Cần mạng + JS runtime như ingest.
  - **T3 Local subtitle:** nguồn phụ đề theo thứ tự: `--subtitle PATH` (explicit) → sidecar cạnh file video local cùng stem (`<stem>.vi.srt`, `<stem>.vi.vtt`, `<stem>.vi.json3`, `<stem>.srt`, `<stem>.vtt`, `<stem>.json3`, lấy file đầu tiên tồn tại). Định dạng `.srt`, `.vtt` (CP1 §1) và thêm `.json3` (định dạng caption YouTube, để dùng caption đã tải sẵn — vd video test). File phụ đề là input của stage (absolute path + sha256), không copy. `--subtitle` không được lưu vào manifest: chạy lại không kèm flag sẽ dùng sidecar/whisper và bị coi là input đổi.
  - **T4 Whisper fallback:** `faster-whisper` pin `faster-whisper==1.2.1` (runtime dep, import lazy chỉ khi cần). Mặc định `model = "large-v3-turbo"`, `device = "cpu"`, `compute_type = "int8"`, `language = "vi"` (ép, không auto-detect), `word_timestamps = true`, `vad_filter = true`; model tải về `models/` (gitignored) lần đầu (cần mạng tới Hugging Face). HUMAN LEAD 2026-09-26: máy CPU 48 core đủ mạnh, giữ `large-v3-turbo`; thêm `whisper.cpu_threads` mặc định = số CPU (`os.cpu_count()`), là thiết lập thực thi nên không vào config hash. Transitive deps: `ctranslate2`, `huggingface-hub`, `tokenizers`, `onnxruntime`, `av`, `tqdm` — ghi rõ trong decision record.
  - **T5 Acceptance validation** (áp dụng cho mọi provider, deterministic, ngưỡng trong config):
    - schema/parse OK; timestamps hữu hạn, `0 ≤ start < end`, start không giảm, `end ≤ duration + 1 s`;
    - text không rỗng sau khi bỏ nhãn non-speech (`[...]`);
    - language: metadata track/provider là `vi` (YouTube `vi`/`vi-orig`; local subtitle và Whisper theo `transcript.language`) **và** tỉ lệ từ có ký tự đặc trưng tiếng Việt ≥ `min_vietnamese_ratio` (mặc định 0.3);
    - coverage: tổng thời lượng speech (sau khi bỏ chồng lấn) / `duration` ≥ `min_coverage` (mặc định 0.5);
    - đủ dùng cho CP4: ≥ `min_words_per_minute` (mặc định 30) trên độ dài video.
    - Không đạt → ghi lý do vào `attempts`, sang provider sau. Mọi provider đều không đạt → stage `failed` với tóm tắt lý do từng provider.
  - **T6 Normalization:** mọi provider → cùng danh sách segment. Timestamp giây, làm tròn 3 chữ số. json3: mỗi event có chữ = một segment; `end = min(start + dur, start event kế tiếp)` để bỏ chồng lấn roll-up; word `start = tStart + tOffset`, `end` = start word kế / end segment; bỏ event chỉ có `\n`. VTT: bỏ tag inline, gộp dòng lặp roll-up. Whisper: segment + word của model. Nhãn `[âm nhạc]`… giữ lại với `kind: "non_speech"`, không tính vào speech coverage. Không sửa chữ (không thêm dấu câu, không sửa chính tả).
  - **T7 `transcript.json` schema v1** (không chứa timestamp tạo file → byte-stable; provenance thời gian ở manifest theo CP2 D5):
    ```json
    {
      "schema_version": 1,
      "episode_id": "rbjfCfFq3Dk",
      "source": "youtube | local_subtitle | whisper",
      "method": "youtube_manual_caption | youtube_auto_caption | subtitle_srt | subtitle_vtt | subtitle_json3 | faster_whisper",
      "language": "vi",
      "media_sha256": "<sha256 nguồn media>",
      "raw": {"path": "transcript/youtube.vi-orig.json3", "sha256": "…"},
      "provider": {"track": "vi-orig", "auto": true},
      "attempts": [{"provider": "youtube", "status": "accepted | rejected | unavailable | error", "reason": null}],
      "stats": {"segments": 0, "words": 0, "speech_seconds": 0.0, "coverage": 0.0},
      "transcript_sha256": "<sha256 canonical JSON của segments>",
      "segments": [
        {"id": "s00001", "start": 3.08, "end": 10.28, "kind": "speech", "text": "Phật thuyết …",
         "words": [{"start": 3.08, "end": 4.08, "text": "Phật"}]}
      ]
    }
    ```
    `raw` là `null` với Whisper; `provider` với Whisper = `{"model", "device", "compute_type", "vad_filter", "faster_whisper_version"}`; với local subtitle = `{"path", "format"}`. `words` là `[]` khi nguồn không có word timing (srt/vtt thường). Segment id ổn định theo thứ tự (`s` + 5 chữ số). `transcript_sha256` để stage sau (CP4+) dùng làm input hash.
  - **T8 Stage / resume** (dùng `run_stage` của CP2): yêu cầu `ingest` = `done`, nếu không → lỗi rõ. `inputs` = `metadata.json` (path + sha256) + file phụ đề local nếu có (T3). `config_hash` = toàn bộ key `[transcript]` trừ thiết lập thực thi không đổi artifact (vd `whisper.cpu_threads`). Artifacts: `transcript.json` + file raw (nếu có). Chạy lại transcript → downstream stale theo CP2 D6. Ingest chạy lại → transcript stale (đã có sẵn trong CP2).
  - **T9 CLI:** `auto-short transcript <episode_id> [--subtitle PATH] [--force] [--config PATH]` — stdout `<episode_id>\t<transcribed (<source>/<method>)|skipped (up to date)>\t<path transcript.json>`, log (kể cả attempt từng provider) ra stderr; exit code như CP2 D8. `status` không đổi.

## Implementation approach

- Parser từng định dạng là hàm thuần (text → segments) để test bằng fixture nhỏ; provider YouTube nhận `CaptionFetcher` (Protocol) để test bằng fake; Whisper qua `WhisperBackend` (Protocol) để test không cần model.
- Validation + normalization chung một module, chạy cho mọi provider.
- Fixtures: trích 1–2 phút đầu `rbjfCfFq3Dk.vi.json3` (vài KB) + srt/vtt nhỏ tự viết (có roll-up lặp); không commit file lớn.
- Decision record `docs/decisions/CP3-transcript-contract.md` làm canonical owner của T1–T9 và schema `transcript.json`.

## Acceptance Criteria

1. Episode YouTube có caption hợp lệ → `transcript.json` với `source: youtube`, Whisper **không** được gọi (test đếm lời gọi fake backend = 0).
2. Caption YouTube thiếu hoặc bị reject (rỗng, sai ngôn ngữ, coverage thấp, timestamp hỏng) → fallback local subtitle rồi Whisper; mỗi lần thử ghi trong `attempts` với lý do.
3. Local subtitle `.srt`, `.vtt` (có roll-up lặp), `.json3` → cùng contract; `--subtitle` ưu tiên hơn sidecar.
4. Normalization: segment không chồng lấn, start không giảm, timestamp 3 chữ số, word timing giữ khi nguồn có, nhãn `[…]` là `non_speech`.
5. Chạy lại → `transcript: skip (up to date)`, `transcript.json` byte-identical; đổi config `[transcript]` / phụ đề / ingest chạy lại → chạy lại; `--force` luôn chạy lại.
6. Mọi provider thất bại hoặc ingest chưa `done` → exit ≠ 0, message rõ, manifest `failed` + `error`, không để artifact dở dang.
7. Chỉ thêm `faster-whisper==1.2.1`; không dependency ngoài CP1 §10; không code analysis/AI/render.
8. `node scripts/framework-check.mjs` PASS; decision record CP3 ACCEPTED.

## Required verification

- `pytest -q` trong conda env `auto-short` → PASS (AC1–AC6 bằng fixture + fake).
- Chạy thật local: `auto-short ingest input/rbjfCfFq3Dk/rbjfCfFq3Dk.mp4` + `auto-short transcript <id>` → `source: local_subtitle`, `method: subtitle_json3` (sidecar), ghi stats; chạy lại → skip, sha256 `transcript.json` không đổi (AC3, AC5).
- Chạy thật YouTube: `auto-short transcript rbjfCfFq3Dk` trên workspace YouTube → `source: youtube`, track `vi-orig`, không gọi Whisper (AC1).
- Chạy thật Whisper: cắt 120 s đầu video test ra file tạm trong scratchpad (không sidecar) → ingest + transcript → `source: whisper`, ghi thời gian chạy và model (T4) (AC2).
- `git diff --stat main...HEAD` + đọc `pyproject.toml` (AC7).
- `node scripts/framework-check.mjs` (AC8).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract mạng. CLI mở rộng thêm lệnh; manual test là điểm danh sau automated verification.

- [ ] `auto-short transcript <id>` cho video test local → mở `work/<id>/transcript.json`, đọc vài segment đầu, kiểm timestamp khớp video.
- [ ] Chạy lại → thấy skip.
- [ ] `auto-short status <id>` → `transcript done`.

## Result

- Main changes: subpackage `src/auto_short/transcript/` (parsers json3/srt/vtt, normalize + validate, 3 provider, stage); config `[transcript]` typed; CLI `auto-short transcript`; `faster-whisper==1.2.1`; decision record `docs/decisions/CP3-transcript-contract.md` ACCEPTED; project profile, README. IMPLEMENTER commits `d7ded46`, `0a569a0`.
- Tests (ORCHESTRATOR chạy lại độc lập):
  - `~/miniconda3/envs/auto-short/bin/pytest -q` → `92 passed`.
  - Local `rbjfcffq3dk-7271326dbe93`: `local_subtitle/subtitle_json3` (sidecar `rbjfCfFq3Dk.vi.json3`), 827 segment (10 `non_speech`), 5298 từ, coverage 0.808; chạy lại → `skip (up to date)`, sha256 `transcript.json` `b18641f7…c5d1d3` không đổi.
  - YouTube `rbjfCfFq3Dk`: `youtube/youtube_auto_caption`, track `vi-orig`, attempts chỉ `youtube accepted` (Whisper không gọi); chạy lại → skip, sha256 `0d47d6d3…f1c92` không đổi; `transcript_sha256` trùng run local.
  - Whisper: clip 120 s đầu (workspace scratchpad, không sidecar) `--force` → `whisper/faster_whisper`, `large-v3-turbo` cpu int8 48 thread, attempts youtube/local_subtitle `unavailable` → whisper `accepted`; 32 segment, 147 từ, coverage 0.663; **80.85 s wall** (gồm load model; model 1.6 GB đã có trong `models/`).
  - Output thật: segment không chồng lấn, start < end, word nằm trong segment → True.
  - `node scripts/framework-check.mjs` → PASS. `pyproject.toml` chỉ thêm `faster-whisper==1.2.1`.
- Review: ACCEPTED (dual-agent, ORCHESTRATOR review diff-first); không có blocking finding.
- Important findings / decisions:
  - `faster-whisper` kéo `pyyaml` (transitive qua `ctranslate2`/`huggingface-hub`) cùng numpy, protobuf, httpx… (danh sách ở decision record T4). HUMAN LEAD 2026-09-26: chấp nhận; `pyyaml` được phép dùng khi cần (CP1 §10 đã sửa).
  - Non-blocking: nếu hai segment liền nhau có cùng `start`, cắt chồng lấn làm segment trước có `start = end` → validation reject cả transcript (chưa gặp ở dữ liệu thật; có thể gặp ở SRT nhiều người nói).
  - Non-blocking: chất lượng Whisper trên clip test có lỗi tên riêng (“Tịnh Khâu” thay “Tịnh Không”); coverage 0.663 với nhạc intro — ngưỡng 0.5 có thể sát với video nhiều nhạc/im lặng (chỉnh qua config). HUMAN LEAD: nhạc chỉ ở intro/outro, không dùng cho Short (CP1 §5 đã ghi, xử lý ở CP4).
  - Quyết định nhỏ của IMPLEMENTER trong phạm vi T1–T9 ghi ở decision record (bảng `[transcript.providers]`, `cpu_threads = 0` = số CPU, `models_dir` không vào config hash, word timing json3 chỉ khi mỗi seg là một token).
- Known limitations: caption auto không dấu câu — ranh giới câu/ý thuộc CP4. Chưa đo Whisper cả video 1 giờ (CP11).
- PR: #5 https://github.com/ntnghia1908/youtube-auto-short/pull/5 (HUMAN LEAD approved push + PR 2026-09-26).
