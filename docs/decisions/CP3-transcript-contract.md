# CP3 — Transcript Acquisition & Normalization Contract

| Metadata | Value |
|---|---|
| Status | ACCEPTED |
| Accepted by | HUMAN LEAD, 2026-09-26 (T1–T9 duyệt cùng APPROVE TASK; review ACCEPTED) |
| Checkpoint | CP3 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP3 |
| Task contract | `docs/tasks/CP3-transcript.md` |
| Builds on | `docs/decisions/CP1-product-contract.md` §1, §8, §10; `docs/decisions/CP2-workspace-contract.md` D1–D8 |

File này là **canonical owner** của provider boundary, acceptance validation, normalization và schema `transcript.json` mà CP4+ dùng lại. Nơi khác chỉ trỏ tới đây. Stage framework (manifest v1, skip/stale, config hash, CLI exit code) giữ nguyên theo `docs/decisions/CP2-workspace-contract.md`. Thay đổi cần decision gate mới với HUMAN LEAD.

Implementation tham chiếu: `src/auto_short/transcript/` (`parsers.py`, `normalize.py`, `providers.py`, `youtube.py`, `whisper.py`, `stage.py`).

## T1. Provider boundary

- `TranscriptProvider` (Protocol, `providers.py`): `fetch(ctx) -> Candidate` (segment thô đã parse + metadata) hoặc raise `ProviderUnavailable` (không có gì để thử). Lỗi parse → `rejected`; lỗi khác (mạng, model, IO) → `error`.
- Thứ tự cố định `youtube → local_subtitle → whisper`. Config `[transcript.providers]` chỉ **tắt** provider (attempt `unavailable`, reason `disabled by config`), không đổi thứ tự.
- Provider đầu tiên có transcript qua validation (T5) thắng; provider sau không được gọi và không có attempt.

## T2. YouTube caption

- Chỉ khi `source.kind = youtube` (khác → `unavailable: source is not YouTube`). `yt-dlp` `extract_info(download=False)` (không tải video; `js_runtimes` dùng `ingest.js_runtimes`), lấy track định dạng `json3`.
- Ưu tiên: manual `vi` → auto `vi-orig` → auto `vi`. Không có track nào → `unavailable`.
- File gốc lưu `work/<id>/transcript/youtube.<track>.json3` (artifact của stage, chỉ khi được accept).

## T3. Local subtitle

- Nguồn: `--subtitle PATH` (explicit) → sidecar cạnh file video **local** cùng stem, lấy file đầu tiên tồn tại: `<stem>.vi.srt`, `<stem>.vi.vtt`, `<stem>.vi.json3`, `<stem>.srt`, `<stem>.vtt`, `<stem>.json3`. Nguồn YouTube không có sidecar.
- Định dạng theo đuôi file: `.srt`, `.vtt`, `.json3`. `--subtitle` không tồn tại hoặc đuôi khác → lỗi CLI trước khi stage chạy.
- File phụ đề là input của stage (absolute path + sha256), không copy. File phụ đề được resolve **trước** khi chạy provider và luôn vào `inputs` khi có (kể cả khi provider trước thắng), để thêm/đổi/bỏ phụ đề làm stage chạy lại.
- `--subtitle` không lưu vào manifest: chạy lại không kèm flag dùng sidecar/whisper và là "input changed".

## T4. Whisper fallback

- `faster-whisper==1.2.1` (runtime dep, import lazy chỉ khi provider whisper chạy). Transitive deps (đo khi cài 2026-09-26): `ctranslate2`, `huggingface-hub`, `tokenizers`, `onnxruntime`, `av`, `tqdm`, và kéo theo `numpy`, `pyyaml` (bởi `ctranslate2`/`huggingface-hub`; project không dùng trực tiếp), `protobuf`, `flatbuffers`, `httpx`/`httpcore`/`h11`/`anyio`, `hf-xet`, `fsspec`, `filelock`, `click`, `certifi`, `idna`, `typing-extensions`.
- Mặc định `model = "large-v3-turbo"`, `device = "cpu"`, `compute_type = "int8"`, `language` = `transcript.language` (ép, không auto-detect), `word_timestamps = true`, `vad_filter = true`.
- Model tải về `transcript.whisper.models_dir` (mặc định `models/`, gitignored) lần đầu, cần mạng tới Hugging Face (~1.6 GB cho `large-v3-turbo`).
- `whisper.cpu_threads` (mặc định `0` = `os.cpu_count()`) và `whisper.models_dir` là thiết lập thực thi, không vào config hash.
- Whisper đọc trực tiếp file media nguồn (`source.path` của manifest).

## T5. Acceptance validation

Áp dụng cho mọi provider sau normalization (T6), deterministic, ngưỡng trong `[transcript]`. Lý do đầu tiên không đạt được ghi vào attempt `rejected`:

1. parse OK (lỗi parse → `parse error: …`); có ít nhất một segment;
2. mọi timestamp hữu hạn, `0 ≤ start < end`, start không giảm, `end ≤ duration + 1 s` (`duration` từ `metadata.json`);
3. còn chữ sau khi bỏ nhãn non-speech `[...]`;
4. language metadata là `vi` (subtag chính: YouTube `vi`/`vi-orig`; local subtitle và Whisper theo `transcript.language`) **và** tỉ lệ từ có chữ cái đặc trưng tiếng Việt (so NFC, lowercase) trên các từ có chữ cái ≥ `min_vietnamese_ratio` (0.3);
5. coverage = thời lượng speech (hợp các khoảng segment `speech`) / `duration` ≥ `min_coverage` (0.5);
6. số từ speech / phút video ≥ `min_words_per_minute` (30).

Mọi provider không đạt → stage `failed`, `error` = `no acceptable transcript: <provider>: <status> (<reason>); …`.

## T6. Normalization

Mọi provider → cùng danh sách segment (`normalize.py`):

- json3: mỗi event có chữ = một segment (text = nối `utf8` các seg, gộp khoảng trắng); bỏ event không có chữ (chỉ `\n`, event định nghĩa window). Word timing `start = tStartMs + tOffsetMs` chỉ giữ khi mọi seg là một token (auto caption); dòng manual một seg nhiều từ → `words: []`.
- SRT/VTT: bỏ tag inline (`<i>`, `<c>`, `<v …>`, `{\an8}`), decode HTML entity. Roll-up: các dòng đầu của cue trùng các dòng cuối của cue trước đã được phát → chỉ dòng mới tạo segment; cue không có dòng mới (lặp/transition) bị bỏ. VTT có timestamp inline (`<00:00:01.000>`) → word timing (từ đầu dòng bắt đầu ở start cue); còn lại `words: []`.
- Whisper: segment + word của model (text strip).
- Chung: bỏ segment rỗng; `end = min(end, start segment kế)` khi segment kế không bắt đầu sớm hơn (start giảm để nguyên cho T5 reject); word kẹp trong segment, start không giảm, `end` thiếu = start word kế / end segment; segment chỉ gồm nhãn `[...]` → `kind: "non_speech"`, `words: []`; giây làm tròn 3 chữ số; id `s00001`… theo thứ tự.
- Không sửa chữ (không thêm dấu câu, không sửa chính tả, không đổi Unicode normalization).

## T7. `transcript.json` schema v1

`work/<id>/transcript.json`, ghi atomic, **không** chứa timestamp tạo file (byte-stable khi chạy lại; provenance thời gian ở manifest theo CP2 D5). Thứ tự key cố định:

```json
{
  "schema_version": 1,
  "episode_id": "rbjfCfFq3Dk",
  "source": "youtube | local_subtitle | whisper",
  "method": "youtube_manual_caption | youtube_auto_caption | subtitle_srt | subtitle_vtt | subtitle_json3 | faster_whisper",
  "language": "vi",
  "media_sha256": "<metadata.json source.sha256>",
  "raw": {"path": "transcript/youtube.vi-orig.json3", "sha256": "…"},
  "provider": {"track": "vi-orig", "auto": true},
  "attempts": [{"provider": "youtube", "status": "accepted | rejected | unavailable | error", "reason": null}],
  "stats": {"segments": 827, "words": 5298, "speech_seconds": 2926.519, "coverage": 0.808},
  "transcript_sha256": "<sha256 canonical JSON của segments>",
  "segments": [
    {"id": "s00002", "start": 3.08, "end": 7.639, "kind": "speech", "text": "Phật thuyết thập thiện nghiệp đạo Kinh",
     "words": [{"start": 3.08, "end": 4.08, "text": "Phật"}]}
  ]
}
```

- `language`: `transcript.language` của config.
- `raw`: YouTube → file trong workspace (relative); local subtitle → `{"path": <absolute>, "sha256"}` của file phụ đề; Whisper → `null`.
- `provider`: YouTube `{"track", "auto"}`; local subtitle `{"path", "format"}`; Whisper `{"model", "device", "compute_type", "vad_filter", "faster_whisper_version"}`.
- `attempts`: mỗi provider đã xét theo thứ tự, tới provider accepted.
- `stats`: `segments` (mọi segment), `words` (token speech, bỏ nhãn `[...]`), `speech_seconds` (3 chữ số), `coverage` (3 chữ số).
- `transcript_sha256` = sha256 của `canonical_json(segments)` (CP2 D7) — stage sau dùng làm input hash.

## T8. Stage / resume

Dùng `run_stage` của CP2 nguyên trạng:

- Yêu cầu `ingest` = `done` và `metadata.json` tồn tại; không có manifest → lỗi; ingest chưa done → stage `failed` + `error`.
- `inputs` = `metadata.json` (relative + sha256) + file phụ đề local nếu resolve được (T3, absolute + sha256).
- `config_hash` = mọi key `[transcript]` (language, 3 ngưỡng, `providers.*`, `whisper.model/device/compute_type/vad_filter/word_timestamps`) trừ `whisper.cpu_threads`, `whisper.models_dir`.
- `artifacts` = `transcript.json` + `transcript/youtube.<track>.json3` nếu có. Khi chạy lại, `transcript/` cũ bị xóa trước khi ghi; lỗi → `transcript.json` và `transcript/` bị xóa.
- Chạy lại transcript → downstream stale (CP2 D6); ingest chạy lại → transcript stale.

## T9. CLI

`auto-short transcript <episode_id> [--subtitle PATH] [--force] [--config PATH]` — stdout `<episode_id>\t<transcribed (<source>/<method>)|skipped (up to date)>\t<path transcript.json>`; log (kể cả attempt từng provider) ra stderr; exit code theo CP2 D8. `status` không đổi.

## Config `[transcript]`

Xem `config.example.toml`: `language`, `min_vietnamese_ratio`, `min_coverage`, `min_words_per_minute`; `[transcript.providers]` `youtube`/`local_subtitle`/`whisper`; `[transcript.whisper]` `model`, `device`, `compute_type`, `vad_filter`, `word_timestamps`, `cpu_threads`, `models_dir`.

## Đo thực tế (2026-09-26, video test `rbjfCfFq3Dk`, VM 48 CPU không GPU)

| Run | Kết quả |
|---|---|
| Local (sidecar `rbjfCfFq3Dk.vi.json3`) | `local_subtitle/subtitle_json3`; 827 segment (10 `non_speech`), 5298 từ, speech 2926.519 s, coverage 0.808; < 1 s |
| YouTube (`vi-orig` auto) | `youtube/youtube_auto_caption`; cùng stats và `transcript_sha256` với run local; ~2 s |
| Whisper 120 s đầu | `large-v3-turbo` cpu int8, 48 thread: 32 segment, 147 từ, coverage 0.663; 81 s wall (model đã có sẵn trong `models/`) |
