# CP4 — Shot / Segment Analysis Contract

| Metadata | Value |
|---|---|
| Status | PROPOSED |
| Accepted by | — (A1–A11 duyệt cùng APPROVE TASK 2026-09-26; chờ review ACCEPTED) |
| Checkpoint | CP4 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP4 |
| Task contract | `docs/tasks/CP4-analysis.md` |
| Builds on | `docs/decisions/CP1-product-contract.md` §3, §5, §8, §10; `docs/decisions/CP2-workspace-contract.md` D1–D8; `docs/decisions/CP3-transcript-contract.md` T6–T7 |

File này là **canonical owner** của shot/silence detection, content window, điểm cắt, speech unit, candidate + kế hoạch rút khoảng lặng và schema `shots.json`, `silences.json`, `candidates.json` mà CP5+ dùng lại. Nơi khác chỉ trỏ tới đây. Stage framework (manifest v1, skip/stale, config hash, CLI exit code) giữ nguyên theo `docs/decisions/CP2-workspace-contract.md`; `transcript.json` theo `docs/decisions/CP3-transcript-contract.md`. Thay đổi cần decision gate mới với HUMAN LEAD.

Implementation tham chiếu: `src/auto_short/analysis/` (`detect.py`, `candidates.py`, `stage.py`). Dữ kiện đo và lý do chọn tham số (P1–P3, Q3, Q4): `docs/tasks/CP4-analysis.md`.

## A1. Stage / artifact

- Stage `analysis` (CP1 §8), subpackage `src/auto_short/analysis/`.
- Artifact `work/<id>/shots.json`, `silences.json`, `candidates.json`: ghi atomic, **không** chứa timestamp tạo file (byte-stable; provenance ở manifest, CP2 D5). `silences.json` bổ sung so với bản gốc CP1 §8.
- Số giây làm tròn 3 chữ số. Tính toán candidate dùng millisecond nguyên (không sai số float): `duration`, `trims` chính xác tới ms.

## A2. Shot detection

- `ffmpeg -i <media> -an -vf "scale=<scale_width>:-2,select='gt(scene,<scene_threshold>)',showinfo" -f null -` trên media nguồn (`source.path` của manifest); parse `pts_time` các dòng frame của `showinfo`.
- Chuyển shot: làm tròn 3 chữ số, chỉ giữ giá trị trong `(0, duration)`, sắp xếp, bỏ trùng. Không có chuyển shot → một shot `[0, duration]`.
- Mặc định `scene_threshold = 0.3`, `scale_width = 320`.

## A3. Silence detection

- `ffmpeg -i <media> -vn -af "silencedetect=noise=<silence_noise_db>dB:d=<silence_min>" -f null -`; mặc định `silence_noise_db = -45`, `silence_min = 0.3`.
- `silence_start` âm → 0; khoảng lặng chưa đóng ở cuối log kết thúc tại `duration` (`metadata.json`); cắt về `[0, duration]`.
- Gộp hai khoảng lặng cách nhau < 0.05 s (so trên giá trị thô trước khi làm tròn).
- Media không có audio (`metadata.json` `audio_codec = null`) → stage `failed`. `ffmpeg` exit ≠ 0 hoặc không có trên PATH → `failed` (`error` = dòng cuối stderr).

## A4. Hard break

Hard break là một trong:

- (a) segment `kind: non_speech` nằm trong content window (bắt đầu trong `[content.start, content.end)`);
- (b) khoảng lặng ≥ `hard_break_silence` (**10.0 s**, P3) nằm trong content window (không cần khớp segment).

Khoảng lặng giao với một nhãn `non_speech` gộp với nhãn đó thành một hard break. Candidate không bao giờ chứa hard break (không ghép đoạn không liên tục, CP1 §5); với hard break là khoảng lặng, candidate chỉ chạm tối đa `boundary_pad` ở mép (A6).

## A5. Content window (CP1 §5, Q3)

- **Intro:** nếu có segment `non_speech` với `start < intro_window` (60 s): `m` = `end` muộn nhất của các segment đó; `content.start` = `end` của khoảng lặng đầu tiên dài ≥ `intro_min_silence` (1.0 s) có `start ≥ m` và `start < intro_window`; không có → `content.start = m`. Không có `non_speech` trong window → `content.start = 0` (không phát hiện intro).
- **Outro:** `content.end` = `start` của segment `non_speech` đầu tiên có `end > duration − outro_window` (180 s) **và** `start ≥ content.start` (để nhãn intro của video ngắn không bị coi là outro); không có → `duration`. Mọi thứ sau đó (kể cả lời hồi hướng) bị loại.
- Nhãn `non_speech` giữa bài chỉ là hard break (A4), không đổi content window.
- `start_reason` / `end_reason`: `intro: non_speech <id> + silence <start>-<end>` | `intro: non_speech <id> (no silence >= <x> s before <y> s)` | `no intro detected`; `outro: non_speech <id>` | `no outro detected`.
- Video test `rbjfCfFq3Dk`: `22.875` – `3554.6`.

## A6. Điểm cắt (không cắt giữa câu, P2)

Điểm cắt là một vùng thời gian giữa hai speech unit, gồm:

- **`silence`:** khoảng lặng audio dài ≥ `min_boundary_silence` (**3.0 s**) và < `hard_break_silence`, nằm trong content window, **khớp ranh giới segment caption**: có segment `speech` bắt đầu trong `[silence.start − align_tolerance, silence.end + align_tolerance]` (`align_tolerance` 0.5 s). Khoảng lặng < 3.0 s không phải điểm cắt.
- **`hard_break`:** A4.
- **`content_edge`:** `content.start`, `content.end`.

Timestamp cắt (ranh giới logic vẫn là ranh giới segment, CP1 §5):

- Ở điểm cắt là khoảng lặng (`silence` hoặc hard break khoảng lặng): unit trước kết thúc tại `silence.start`, unit sau bắt đầu tại `silence.end`; clip: đầu = `silence.end − boundary_pad`, cuối = `silence.start + boundary_pad` (`boundary_pad` 0.3 s, CP1 §5).
- Ở mép nhãn `non_speech` / content edge: lấy mép lời nói theo khoảng lặng gần nhất quanh timestamp caption:
  - đầu unit: `t0` = `start` segment đầu của unit; nếu có khoảng lặng giao `[t0 − align_tolerance, t0 + align_tolerance]` (kết thúc trước điểm cắt kế tiếp) thì lấy `end` của khoảng lặng có `end` gần `t0` nhất, không có thì `t0`; kẹp ≥ mép vùng (hết nhãn / `content.start`);
  - cuối unit: `t1` = `end` segment cuối; tương tự, lấy `start` của khoảng lặng có `start` gần `t1` nhất (bắt đầu sau đầu unit), không có thì `t1`; kẹp ≤ mép vùng (đầu nhãn / `content.end`);
  - `boundary_pad` áp dụng nhưng clip **không** vượt mép vùng: không lấn vào nhạc/nhãn `non_speech`, không ra ngoài content window.

## A7. Speech unit

- Đoạn giữa hai điểm cắt liên tiếp = một unit (`u0001`…, theo thời gian).
- Segment `speech` thuộc unit theo trung điểm; ranh giới chia là trung điểm của vùng điểm cắt (khoảng lặng / nhãn), `content.start`, `content.end` — mỗi segment trong content thuộc đúng một unit, kể cả segment caption có trung điểm rơi vào khoảng lặng.
- Đoạn không có segment speech (hoặc mép lời nói suy biến): nếu một bên là điểm cắt `silence` thì bỏ điểm cắt đó (đoạn nhập vào unit bên cạnh; hai bên đều là `silence` → bỏ khoảng lặng ngắn hơn, bằng nhau → bỏ cái sau); hai bên đều là hard break / content edge → không có unit (vd. đoạn nhạc chen giữa hai nhãn `[âm nhạc]`).
- Trường: `start`/`end` (mép lời nói, A6), `segment_ids` [đầu, cuối], `text` (nối text segment bằng một khoảng trắng), `words` (token speech, bỏ nhãn `[...]`, như CP3 T7), `break_before`/`break_after` = `{"kind": "silence | hard_break | content_edge", "seconds": <độ dài khoảng lặng | null>}` (`null` cho content edge và hard break có nhãn `non_speech`).

## A8. Candidate + rút khoảng lặng (P1)

Mọi dãy unit liên tiếp `[u_i … u_j]` mà mọi ranh giới giữa chúng là `silence` (không hard break, không content edge, không đoạn bị bỏ):

- `source_start` = `u_i.start − boundary_pad`, `source_end` = `u_j.end + boundary_pad`, kẹp theo A6; `source_duration` = hiệu.
- `trims`: với mỗi khoảng lặng (A3) giao `[source_start, source_end]`, xét phần nằm trong clip `[a, b]`; nếu `b − a > max_pause` (**1.0 s**, CP1 §5) thì cắt `[a + max_pause/2, b − max_pause/2]` (giữ đúng `max_pause`). Khoảng lặng ≤ `max_pause` không trim. Danh sách sắp theo thời gian, không chồng nhau. CP7 thực hiện đúng danh sách này.
- `duration` (thời lượng Short thực tế) = `source_duration − Σ trims`; giữ candidate khi `min_duration ≤ duration ≤ max_duration` (30 / 180 s, CP1 §3); `in_target` = `duration` trong `[target_min, target_max]` (60–90 s), chỉ là thông tin.
- Shot guard: loại candidate có chuyển shot trong `(source_start, source_start + shot_guard)` hoặc `(source_end − shot_guard, source_end)` (1.0 s).
- `unit_ids`, `segment_ids` = [đầu, cuối]; `words` = tổng; `boundary` = `break_before` của unit đầu / `break_after` của unit cuối; `shot_ids` = shot giao clip; `shot_changes` = chuyển shot trong `(source_start, source_end)`.
- Id `c00001`… theo `(source_start, source_end)` tăng dần. Candidate chồng lấn nhau là bình thường; chống chồng lấn giữa clip được chọn là việc CP5.

## A9. Liệt kê đầy đủ (Q4)

`candidates.json` liệt kê mọi candidate hợp lệ. CP5 có thể trình bày text theo unit cho AI; kết quả AI phải map về một `id` candidate tồn tại (CP1 §5: AI chỉ chọn trong candidate).

## A10. Schema v1

Thứ tự key cố định như dưới. Giá trị minh họa hình dạng (lấy từ video test).

```json
// shots.json
{"schema_version": 1, "episode_id": "rbjfCfFq3Dk", "media_sha256": "<metadata.json source.sha256>",
 "method": {"tool": "ffmpeg", "filter": "scene", "threshold": 0.3, "scale_width": 320},
 "duration": 3622.001, "changes": [21.321, 47.948],
 "shots": [{"id": "h0001", "start": 0.0, "end": 21.321}]}
// silences.json
{"schema_version": 1, "episode_id": "rbjfCfFq3Dk", "media_sha256": "…",
 "method": {"tool": "ffmpeg", "filter": "silencedetect", "noise_db": -45.0, "min_seconds": 0.3},
 "stats": {"count": 720, "total_seconds": 1645.445},
 "silences": [{"start": 19.667, "end": 22.875}]}
// candidates.json
{"schema_version": 1, "episode_id": "rbjfCfFq3Dk",
 "transcript_sha256": "<transcript.json transcript_sha256>",
 "shots_sha256": "<sha256 canonical JSON shots.json>", "silences_sha256": "<sha256 canonical JSON silences.json>",
 "params": {"min_boundary_silence": 3.0, "align_tolerance": 0.5, "hard_break_silence": 10.0, "max_pause": 1.0,
            "boundary_pad": 0.3, "min_duration": 30.0, "max_duration": 180.0, "target_min": 60.0, "target_max": 90.0,
            "shot_guard": 1.0, "intro_window": 60.0, "intro_min_silence": 1.0, "outro_window": 180.0},
 "content": {"start": 22.875, "end": 3554.6, "start_reason": "intro: non_speech s00001 + silence 19.667-22.875",
             "end_reason": "outro: non_speech s00815"},
 "stats": {"units": 195, "candidates": 1484, "in_target": 325, "content_seconds": 3531.725,
           "content_seconds_trimmed": 2523.145},
 "units": [{"id": "u0001", "start": 22.875, "end": 25.8, "segment_ids": ["s00007", "s00007"],
            "text": "các vị đồng tu Xin chào mọi người", "words": 8,
            "break_before": {"kind": "content_edge", "seconds": null}, "break_after": {"kind": "silence", "seconds": 5.125}}],
 "candidates": [{"id": "c00001", "source_start": 22.875, "source_end": 65.448, "source_duration": 42.573,
                 "duration": 34.212, "in_target": false, "unit_ids": ["u0001", "u0002"], "segment_ids": ["s00007", "s00015"],
                 "words": 55, "trims": [[26.3, 30.425], [33.295, 33.793], [40.239, 40.752], [41.848, 43.237],
                                        [46.043, 47.637], [50.686, 50.819], [56.195, 56.304]],
                 "boundary": {"start": {"kind": "content_edge", "seconds": null}, "end": {"kind": "hard_break", "seconds": 12.524}},
                 "shot_ids": ["h0002", "h0003"], "shot_changes": [47.948]}]}
```

- `shots_sha256` / `silences_sha256` = sha256 của `canonical_json` (CP2 D7) toàn bộ tài liệu tương ứng.
- `stats.content_seconds` = `content.end − content.start`; `content_seconds_trimmed` = thời lượng content window sau khi rút mọi khoảng lặng > `max_pause` còn `max_pause` (theo A8).
- `text` chỉ nằm ở unit; candidate tham chiếu `unit_ids`/`segment_ids` [đầu, cuối].

Validation trước khi ghi artifact (vi phạm → `failed`, lỗi code): mọi unit/candidate trong content window; candidate không chứa hard break; mép đúng A6 (ranh giới `silence` ≥ `min_boundary_silence`); `trims` trong clip, không chồng nhau, đúng A8; `duration = source_duration − Σ trims` trong `[min_duration, max_duration]`; `in_target` đúng; shot guard; id duy nhất theo thứ tự; tham chiếu `segment_ids`/`shot_ids` hợp lệ.

## A11. Stage / resume / CLI

Dùng `run_stage` của CP2 nguyên trạng:

- Yêu cầu `transcript` = `done` và `transcript.json`, `metadata.json` tồn tại; không có manifest → lỗi; transcript chưa done → stage `failed` + `error`, không để artifact.
- `inputs` = `metadata.json`, `transcript.json` (relative + sha256) và media nguồn theo manifest `source` (relative/absolute theo CP2 D5, sha256 qua hash cache CP2 D6 — không hash lại file lớn khi không đổi).
- `config_hash` = mọi key `[analysis]`. Đổi key nào → chạy lại cả stage (shot + silence ~90 s trên video test).
- `artifacts` = `shots.json`, `silences.json`, `candidates.json`; lỗi → cả ba bị xóa.
- Chạy lại analysis → downstream stale; transcript chạy lại → analysis stale.
- CLI `auto-short analysis <episode_id> [--force] [--config PATH]` — stdout `<episode_id>\t<analyzed (<n> candidates)|skipped (up to date)>\t<path candidates.json>`; log (content window, số shot change/silence/unit/candidate/in_target, content seconds) ra stderr; exit code theo CP2 D8. `status` không đổi.

## Config `[analysis]`

Xem `config.example.toml`: `scene_threshold`, `scale_width`, `silence_noise_db`, `silence_min` (detection) và 13 tham số ghi vào `params` (A10). Ràng buộc: `min_duration ≤ max_duration`, `target_min ≤ target_max`, `min_boundary_silence ≤ hard_break_silence`.

## Đo thực tế (2026-09-26, video test `rbjfCfFq3Dk`, VM 48 CPU không GPU)

| Hạng mục | Kết quả |
|---|---|
| Content window | `22.875` – `3554.6` (3531.725 s); sau rút khoảng lặng 1.0 s: 2523.145 s |
| Shot | 14 chuyển shot, 15 shot |
| Silence (−45 dB, ≥ 0.3 s, sau gộp) | 720 khoảng, 1645.445 s |
| Unit / candidate | 195 unit (median 8.94 s); 1484 candidate, 325 `in_target`; median `duration` 93.28 s, `duration/source_duration` median 0.734 |
| Thời gian | 88.6 s wall (`--force`); chạy lại khi không đổi: skip, 0.1 s, ba artifact byte-identical |

Ước lượng trong task contract (189 unit, ~1722 candidate) chưa tính 8 nhãn `[âm nhạc]` giữa bài là hard break (A4a); bỏ các nhãn đó thì implementation cho đúng 189 unit.
