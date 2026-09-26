# CP1 — Product Contract & Architecture Baseline

| Metadata | Value |
|---|---|
| Status | PROPOSED — chờ HUMAN LEAD DECIDE |
| Checkpoint | CP1 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP1 |
| Task contract | `docs/tasks/CP1-product-contract.md` |

> Tài liệu này là **đề xuất** của pha DISCUSS. Không mục nào là quyết định cho tới khi HUMAN LEAD chốt; sau DECIDE, Status đổi thành ACCEPTED và từng mục ghi quyết định cuối.
>
> Mỗi mục: **Đề xuất** (recommendation) · **Lựa chọn khác** · **Cần HUMAN LEAD** khi là lựa chọn sản phẩm/thẩm mỹ mà agent không có dữ kiện.

## 0. Dữ kiện môi trường (đo 2026-09-26)

| Mục | Kết quả |
|---|---|
| Máy chạy repo | VM VMware, 48 CPU, 125 GB RAM, **không có GPU** (`VMware SVGA II`, không có `/dev/nvidia*`) |
| Python | Miniconda 3, Python 3.14.7 (base env) |
| `ffmpeg` / `ffprobe` / `yt-dlp` | **chưa cài** |
| Ollama | `127.0.0.1:11434` và `:11435` đang LISTEN nhưng trả `Connection reset` — có vẻ là SSH tunnel tới máy GPU mà đầu kia chưa chạy Ollama. HUMAN LEAD cho biết GPU ở port 11435. |
| Reference `youtube-vietnamese-dubber` | Python ≥3.11, `pyproject.toml` + hatchling, `yt-dlp`, `faster-whisper`, `pyyaml`; Ollama gọi bằng `urllib` stdlib; model đã kiểm chứng `gemma3:12b` cho tiếng Việt |

## 1. Input contract

- **Đề xuất:** một episode = một nguồn, một trong hai:
  1. YouTube URL (video đơn);
  2. file video local (`.mp4/.mkv/.webm`) + tùy chọn file phụ đề local (`.srt/.vtt`).
- Nguồn là tiếng Việt; không nhận/không tạo translation, TTS, dubbing.
- Playlist/batch: ngoài CP1–CP8, để CP9.
- Metadata tùy chọn cho header: `series`, `episode`, `speaker` qua config/CLI (xem §6).

## 2. Output contract

- **Đề xuất:** mỗi Short một file `output/<episode_id>/shorts/<clip_id>.mp4`:
  - 1080×1920 (9:16), H.264 (yuv420p), AAC 48 kHz, 30 fps (hoặc giữ fps nguồn nếu ≤ 30);
  - kèm `render_manifest.json` (clip, title, source hash, render config hash).
- Không tự upload YouTube (ngoài scope; nếu cần là quyết định riêng sau CP12).

## 3. Short duration policy

- **Đề xuất:** mục tiêu 30–60 s, tối thiểu 20 s, tối đa 60 s; không cắt giữa câu.
- Lựa chọn khác: cho phép tới 180 s (YouTube Shorts hiện hỗ trợ tới 3 phút).
- **Quyết định HUMAN LEAD (2026-09-26):** min 30 s / mục tiêu 60–90 s / max 180 s; không cắt giữa câu.

## 4. Composition 9:16

- **Đề xuất (bố cục 3 dải dọc):**

```text
┌──────────────────────┐
│ Header (upper panel) │  series/episode — deterministic, không AI
├──────────────────────┤
│   Video nguồn        │  scale giữ tỉ lệ, crop giữa (16:9 → vùng giữa)
├──────────────────────┤
│ Yellow title panel   │  title/hook AI (CP6)
├──────────────────────┤
│ Lower panel          │  subtitle (nếu bật) + tên kênh/ghi chú
└──────────────────────┘
```

- **Cần HUMAN LEAD:** ảnh/mẫu tham chiếu cho yellow panel (thứ tự dải, tỉ lệ chiều cao, màu nền chính xác, font, logo). CP1 chỉ chốt cấu trúc + tham số; pixel-level design lấy từ mẫu HUMAN LEAD cung cấp và không được redesign ở CP7.

## 5. Clip selection boundaries

- Clip phải bắt đầu/kết thúc tại ranh giới segment transcript (không cắt giữa câu); có thể nới ±0.3 s để tránh cắt âm.
- Một clip = một ý trọn vẹn; không ghép đoạn không liên tục (không "jump cut") trong MVP.
- Không chồng lấn giữa các clip được chọn của cùng episode.
- Số clip mỗi episode: **đề xuất** tối đa N = 10 (config).
- AI (CP5) chỉ chọn trong danh sách candidate do code deterministic sinh ra (CP4), không tự tạo timestamp mới.

## 6. Title / header structure

- **Header:** deterministic — lấy từ config/CLI (`series`, `episode`) hoặc metadata YouTube; không dùng AI.
- **Title/hook (yellow panel):** AI sinh từ transcript của clip; tiếng Việt; **đề xuất** ≤ 60 ký tự, tối đa 2 dòng; không thêm thông tin không có trong clip; không emoji/clickbait.
- Lưu `titles.json` với clip ID, model, prompt version, source hash.

## 7. Subtitle policy

- **Đề xuất:** burn-in subtitle tiếng Việt từ transcript đã normalize, mỗi dòng ≤ ~32 ký tự, tối đa 2 dòng, ở lower panel.
- Lựa chọn khác: không có subtitle; hoặc subtitle kiểu karaoke/từng từ (cần timestamp từng từ → phụ thuộc Whisper, không có với YouTube captions).
- **Quyết định HUMAN LEAD (2026-09-26):** **tắt** subtitle mặc định. Lower panel không chứa subtitle; nội dung lower panel theo mẫu layout (§4).

## 8. Artifact model & pipeline boundaries

Workspace: `work/<episode_id>/` (đã gitignore). Mỗi stage một artifact, có `stage`, `inputs` (path + sha256), `config_hash`, `created_at`:

| Stage | Artifact | Deterministic? | CP |
|---|---|---|---|
| ingest | `source.*`, `metadata.json` | có | CP2 |
| transcript | `transcript.json` (YouTube → local subtitle → Whisper) | có (provider ngoài) | CP3 |
| analysis | `shots.json`, `candidates.json` | có | CP4 |
| selection | `clips.json` | **AI** + validate | CP5 |
| titling | `titles.json` | **AI** + validate | CP6 |
| review | `review.json` (approve/reject/edit) | người | CP9 |
| render | `render_manifest.json`, `shorts/*.mp4` | có | CP7 |

- Stage bỏ qua khi artifact tồn tại và input hash + config hash khớp; lệch → stage và downstream stale.
- Boundary deterministic ↔ AI: AI chỉ ở selection và titling; output AI phải qua schema validation trước khi thành artifact trusted.
- **Human review:** mặc định render mọi clip AI chọn (MVP CP8); review gate đầy đủ ở CP9. Auto-approve chỉ là config explicit.

## 9. Execution profile

- **Đề xuất:** `single-agent` mặc định cho CP1–CP12; HUMAN LEAD có thể chọn `dual-agent` cho từng checkpoint trong task contract.

## 10. Dependency policy & proposals

Nguyên tắc: stdlib trước; mỗi dependency qua dependency proposal; không thêm dependency ngoài danh sách được duyệt.

| Library | Purpose | Vì sao cần | Alternative | Impact |
|---|---|---|---|---|
| Python ≥ 3.11 + `venv` + `pip`, `pyproject.toml` (hatchling) | runtime + packaging | giống reference, không cần tool thêm | `uv`, conda env | `.venv/` trong repo (đã gitignore) |
| `yt-dlp` | tải video + lấy caption YouTube (kể cả auto-generated) | một lib cho cả download và transcript YouTube | `youtube-transcript-api` (+ vẫn cần downloader) | runtime |
| `faster-whisper` | fallback transcript khi không có caption hợp lệ | local, có timestamp, đã kiểm chứng ở reference | `openai-whisper` (nặng hơn) | runtime, model tải về `models/` |
| `pytest` | test | chuẩn | `unittest` stdlib | dev only |
| `ffmpeg`/`ffprobe` (system binary) | probe, cắt, compose, render; scene detect bằng filter `select=gt(scene,…)` | không có thay thế thực tế | PySceneDetect (thêm dep) | cần cài hệ thống |
| Ollama HTTP API qua `urllib` | clip selection + title | không cần SDK | `ollama` python client | không thêm dep |

- **Quyết định HUMAN LEAD (2026-09-26):** config dùng **TOML / `tomllib`** (stdlib); **không** thêm `pyyaml`.

## 11. Local GPU / Ollama assumptions

- Ollama chạy trên **máy GPU riêng**, truy cập qua `OLLAMA_HOST` (mặc định đề xuất `http://127.0.0.1:11435` theo HUMAN LEAD); code không hard-code host/model.
- **Quyết định HUMAN LEAD (2026-09-26):** host mặc định `http://127.0.0.1:11435`, model khởi đầu `gemma3:12b`; chốt lại bằng đo đạc ở CP5/CP10.
- Whisper chỉ là fallback; trên VM không GPU chạy CPU (`int8`, 48 core). Đo thực tế ở CP11.
- **Blocker môi trường cần HUMAN LEAD xử lý trước CP5:** Ollama trên port 11435 hiện không phản hồi. **Trước CP2:** cài `ffmpeg` (cần `sudo apt install ffmpeg`).

## 12. Open questions cho HUMAN LEAD

Đã chốt 2026-09-26: duration (§3), subtitle (§7), config format (§10), Ollama host/model (§11).

Còn mở:

1. Mẫu layout / yellow panel: file ảnh hoặc thông số (§4).
2. Chấp nhận hoặc sửa các đề xuất còn lại: §1, §2, §5, §6, §8, §9 và danh sách dependency §10.
