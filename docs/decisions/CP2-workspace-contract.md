# CP2 — Workspace, Manifest & Stage Contract

| Metadata | Value |
|---|---|
| Status | ACCEPTED |
| Accepted by | HUMAN LEAD, 2026-09-26 |
| Checkpoint | CP2 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP2 |
| Task contract | `docs/tasks/CP2-media-workspace.md` |
| Builds on | `docs/decisions/CP1-product-contract.md` §1, §8, §10 |

File này là **canonical owner** của convention workspace / manifest / stage status / hash mà mọi stage (CP3+) dùng lại. Nơi khác chỉ trỏ tới đây. Thay đổi cần decision gate mới với HUMAN LEAD.

Implementation tham chiếu: `src/auto_short/workspace.py`, `src/auto_short/hashing.py`, `src/auto_short/ingest/`.

## D1. Package / layout

- Package Python `auto_short`, src-layout: `src/auto_short/`, mỗi stage một subpackage `src/auto_short/<stage>/` (tên stage theo CP1 §8).
- Stage framework dùng chung (workspace, manifest, skip/stale) ở `src/auto_short/workspace.py`; hash ở `src/auto_short/hashing.py`; config ở `src/auto_short/config.py`; CLI ở `src/auto_short/cli.py`.

## D2. Runtime

> Sửa đổi HUMAN LEAD 2026-09-26 sau review: conda env riêng thay cho `.venv` từ system Python; pin `yt-dlp==2026.8.19`.

- Conda env riêng `auto-short` (Python 3.12): `conda create -n auto-short python=3.12`; không cài gì vào conda `base`.
- `pyproject.toml` (hatchling), `requires-python >=3.11`; runtime deps: chỉ `yt-dlp`, pin `yt-dlp==2026.8.19` (bản stable đã chạy thật thành công); optional `dev`: chỉ `pytest`. Cài bằng `pip install -e ".[dev]"` trong env đó.
- Khi YouTube thay đổi làm bản pin hỏng, nâng pin qua task mới.
- `faster-whisper` chỉ thêm ở CP3 khi dùng (vẫn trong danh sách CP1 §10).
- Config: TOML qua `tomllib`; `config.example.toml` commit, `config.toml` gitignored. Không có `config.toml` thì dùng default (bằng `config.example.toml`).

## D3. Episode ID

- YouTube: video id 11 ký tự (vd `rbjfCfFq3Dk`).
- File local: `<slug tên file>-<12 hex đầu sha256>` (vd `rbjfcffq3dk-7271326dbe93`). Slug: bỏ dấu tiếng Việt (`đ→d`), lowercase, ký tự khác `[a-z0-9]` thành `-`, tối đa 48 ký tự, rỗng → `video`.
- `--episode-id` ghi đè. ID hợp lệ: `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`.
- Một workspace thuộc một nguồn: dùng lại workspace cho nguồn khác loại hoặc video YouTube khác → lỗi. Nguồn local đổi path/nội dung dưới cùng ID là "input changed" → chạy lại.

## D4. Source handling

> Sửa đổi HUMAN LEAD 2026-09-26 sau review: chất lượng video YouTube tốt nhất, bỏ giới hạn ≤1080p.

- YouTube: tải bằng `yt-dlp` (Python library) vào `work/<id>/source.<ext>`; format mặc định `bv*+ba/b` (best video + best audio), merge `mp4`. Tải vào `work/<id>/.ingest-tmp/`, chỉ chuyển thành `source.<ext>` sau khi probe OK. Không tải caption (CP3).
- File local: **không copy**. Manifest ghi absolute path + sha256 + size + mtime.

## D5. Manifest schema v1

`work/<episode_id>/manifest.json`, ghi atomic (temp file cùng thư mục + `fsync` + `os.replace`):

```json
{
  "schema_version": 1,
  "episode_id": "rbjfcffq3dk-7271326dbe93",
  "source": {
    "kind": "local",
    "uri": "/abs/path/input.mp4",
    "path": "/abs/path/input.mp4",
    "sha256": "7271326d…c3b77b",
    "size": 694636363,
    "mtime_ns": 1790405506309217453
  },
  "stages": {
    "ingest": {
      "status": "done",
      "artifacts": ["metadata.json"],
      "inputs": [{"path": "/abs/path/input.mp4", "sha256": "7271326d…c3b77b"}],
      "config_hash": "44136fa3…",
      "started_at": "2026-09-26T07:41:52Z",
      "finished_at": "2026-09-26T07:41:52Z",
      "error": null
    }
  }
}
```

- `source.kind`: `local | youtube`. `source.uri`: URL gốc hoặc absolute path. `source.path`: file media (YouTube: `source.<ext>`, relative). `path`/`sha256`/`size`/`mtime_ns` là `null` khi YouTube chưa tải xong.
- `source.mtime_ns` (nanoseconds, `st_mtime_ns`) là key cache hash của D6; ngoài D5 gốc, thêm để thực thi D4/D6.
- Path convention: file **trong** `work/<id>/` ghi relative (POSIX) theo thư mục episode; file **ngoài** workspace ghi absolute.
- `stages.<name>.status`: `pending | running | done | failed | stale`. Stage chưa có entry được hiểu là `pending`. `stale` do D6 đặt (stage đã từng chạy nhưng upstream đã chạy lại).
- `started_at`/`finished_at`: UTC ISO-8601 `YYYY-MM-DDTHH:MM:SSZ`. `error`: message khi `failed`, ngược lại `null`.
- Provenance của artifact (CP1 §8: stage, inputs, config hash, thời điểm tạo) nằm ở entry stage trong manifest; artifact nội dung (vd `metadata.json`) không chứa timestamp để byte-stable khi chạy lại.
- Schema version khác 1 → từ chối đọc.

### `metadata.json` (artifact của ingest, `schema_version: 1`)

`episode_id`; `source` {`kind`, `uri`, `path`, `sha256`, `size`}; `duration` (s, 3 chữ số thập phân), `width`, `height`, `fps` (3 chữ số), `video_codec`, `audio_codec` (`null` nếu không có audio) — probe bằng `ffprobe`. YouTube thêm `title`, `channel` và `youtube` {`id`, `title`, `channel`, `upload_date`, `webpage_url`, `duration`}.

## D6. Resume / stale rule

- Stage được **skip** khi entry `status = done`, `inputs` (path + sha256) khớp, `config_hash` khớp và mọi `artifacts` tồn tại. Log `<stage>: skip (up to date)`.
- Ngược lại stage chạy lại (log lý do); lúc bắt đầu chạy: entry → `running`, mọi stage downstream (theo thứ tự CP1 §8: ingest → transcript → analysis → selection → titling → review → render) đã có entry → `stale`.
- `--force` luôn chạy lại.
- Lỗi: entry → `failed` + `error`; artifact của stage đó (chỉ file nằm trong workspace) bị xóa; file tạm được dọn; source local không bao giờ bị xóa; exit code ≠ 0.
- Hash cache: sha256 file được dùng lại khi `(absolute path, size, mtime_ns)` khớp entry `source` trong manifest — không hash lại file lớn khi không đổi. File local chưa biết episode id: tra cache qua mọi manifest nguồn local trong workspace root.

## D7. Config hash

- `config_hash = sha256(canonical JSON)`, canonical = `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, chỉ gồm các key config ảnh hưởng tới artifact của stage.
- Ingest: nguồn YouTube dùng `{"ingest.youtube_format": …}`; nguồn local dùng `{}`. `ingest.js_runtimes` là thiết lập thực thi (không đổi artifact) nên không vào hash; `workspace.dir` quyết định vị trí workspace nên không vào hash.

## D8. CLI

- `auto-short` (entry point) và `python -m auto_short`.
- `auto-short ingest <url|path> [--episode-id ID] [--force] [--config PATH]` — in `<episode_id>\t<ingested|skipped (up to date)>\t<workspace>` ra stdout, log ra stderr.
- `auto-short status <episode_id> [--config PATH]` — in source và trạng thái mọi stage theo thứ tự CP1 §8.
- Exit code: `0` thành công/skip; `1` lỗi (message `auto-short: error: …`); `2` sai cú pháp (argparse).
