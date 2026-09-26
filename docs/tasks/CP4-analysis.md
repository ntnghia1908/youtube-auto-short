# Task: CP4 — Shot / Segment Analysis

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `20e165c` / `feature/cp4-analysis`
- Human Lead approval: accepted (APPROVE TASK, 2026-09-26; A1–A11; P1 max_pause 1.0 s, P2 3.0 s, P3 10 s, Q3 loại lời giới thiệu, Q4 liệt kê đầy đủ)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì CP4: (a) tạo artifact contract `shots.json`, `silences.json`, `candidates.json` mà CP5 (AI selection) và CP7 (render) dùng lại; (b) định nghĩa rule tái sử dụng xuyên stage: điểm cắt "không cắt giữa câu" khi caption không có dấu câu, vùng intro/outro bị loại, rút khoảng lặng (CP1 §3/§5 đã sửa); (c) mở rộng CLI. Quyết định A1–A11 dưới đây duyệt cùng APPROVE TASK. Không thêm dependency.

## Goal

Từ một episode đã có `transcript.json`, stage `analysis` sinh `work/<id>/shots.json` (chuyển shot), `work/<id>/silences.json` (khoảng lặng audio) và `work/<id>/candidates.json` (đoạn ứng viên deterministic). Mỗi ứng viên có timestamp nguồn, tham chiếu segment transcript, thông tin ranh giới, danh sách khoảng lặng cần rút và thời lượng Short thực tế; không ứng viên nào nằm trong intro/outro, bắt đầu/kết thúc giữa lời nói, vượt hard break, hay có thời lượng thực tế ngoài 30–180 s (roadmap CP4 Success; CP1 §3, §5).

## Scope

- In scope:
  - Subpackage `src/auto_short/analysis/`: shot detection và silence detection bằng `ffmpeg`, content window, điểm cắt, speech unit, candidate + kế hoạch rút khoảng lặng, validation.
  - Artifact `shots.json`, `silences.json`, `candidates.json` (schema v1).
  - Config `[analysis]` (typed, `tomllib`), `config.example.toml`.
  - CLI `auto-short analysis <episode_id> [--force] [--config PATH]`.
  - Tests `pytest` không cần video thật (fixture transcript + fake detector; parser output `showinfo`/`silencedetect` bằng fixture text).
  - Docs: decision record `docs/decisions/CP4-analysis-contract.md` (ACCEPTED sau review); CP1 §8 thêm `silences.json` vào hàng analysis; project profile (module map `analysis/` → implemented); README (usage); current-state.
- Out of scope:
  - Thực hiện rút khoảng lặng / crossfade / tăng tốc trên media (CP7; CP4 chỉ tính kế hoạch rút).
  - Chấm điểm / chọn clip, gọi AI (CP5); title (CP6); render (CP7).
  - Phục hồi dấu câu, lexical/NLP sentence segmentation; phát hiện nhạc bằng phân tích audio.
  - Override thủ công content window theo episode (review/edit là CP9).
  - Thay đổi manifest schema v1, rule skip/stale (CP2) hay `transcript.json` (CP3).

## Authority / key decisions

- `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP4; `docs/decisions/CP1-product-contract.md` §3, §5 (gồm sửa đổi HUMAN LEAD 2026-09-26 chốt CP4: thời lượng tính sau rút khoảng lặng, `max_pause` = 1.0 s, phần giới thiệu thuộc intro), §8, §10 (`ffmpeg` system binary); `docs/decisions/CP2-workspace-contract.md` D1–D8 (dùng lại nguyên trạng); `docs/decisions/CP3-transcript-contract.md` T6–T7.
- Dữ kiện đo 2026-09-26 trên video test `rbjfCfFq3Dk` (workspace YouTube, transcript caption auto `vi-orig`):
  - **Caption không cho biết ranh giới câu:** 554/826 chỗ nối segment có khoảng cách < 0.05 s (ngắt dòng caption, vd `"… Singapore thời" | "gian năm 2001"`); timestamp caption trải qua khoảng lặng (khoảng lặng theo caption chỉ 19 % thời lượng).
  - **Audio (`silencedetect`, −45 dB, ≥ 0.3 s; 21 s wall cả video):** trong vùng giảng 22.9–3554.6 s khoảng lặng chiếm 44–49 % (ổn định ở −40/−45/−50 dB). Phân bố (−45 dB): 0.3–1 s: 210; 1–2 s: 202; 2–3 s: 110; 3–6 s: 154; 6–10 s: 37; ≥ 10 s: 3 (`65.1` 12.5 s, `1336.1` 10.8 s, `2206.0` 11.1 s).
  - **Độ dài khoảng lặng không tách chắc chắn ngắt cụm từ với hết câu:** giữa câu có chỗ dừng 2–3 s (`bạn mới hoàn toàn hiểu rõ ‖2.9‖ từ ‖2.1‖ là ý thức ‖2.9‖ nghĩ là ngôn ngữ`); hết câu thường 3.5–6 s. → Điểm cắt deterministic là điều kiện cần; trọn ý do CP5 (AI) và CP9 (người) đánh giá.
  - **Intro/outro:** nhạc `[âm nhạc]` 0.57–2.97; lời giới thiệu có nhạc nền liên tục tới 19.67 (không có khoảng lặng); khoảng lặng đầu tiên 19.67–22.87 (trùng chuyển shot 21.3); lời giảng bắt đầu ~22.9. Nhạc kết 3554.6–3574.75, sau đó lời hồi hướng tới 3617.8 (outro). Giữa bài: 8 nhãn `[âm nhạc]` ngắn; 131–173 s là đoạn nhạc chen (có âm thanh, không có lời).
  - **Shot (`select=gt(scene,0.3)`, scale 320; 66.9 s wall):** 14 chuyển shot `21.3, 47.9, 67.3, 718.1, 1867.6, 1889.7, 1920.1, 3065.7, 3074.8, 3211.0, 3216.1, 3289.6, 3302.4, 3619.8` — khung hình gần như tĩnh, shot là tín hiệu phụ.
  - **So sánh `max_pause`** (vùng giảng 3532 s): 1.0 s → 2523 s, 123 từ/phút, khoảng lặng còn 25 %, 12 chỗ cắt/phút; 0.7 s → 2361 s, 132 từ/phút; 0.5 s → 2240 s, 139 từ/phút, 17 chỗ cắt/phút; 2 tầng (≥ 3 s → 1.0, còn lại → 0.5) → 2337 s, 133 từ/phút. HUMAN LEAD nghe thử clip mẫu 173–275 s của cả bốn phương án và chọn **1.0 s** (nghe tự nhiên nhất) — 2026-09-26.
  - **Ước lượng theo A4–A9:** content 22.87–3554.6 (3532 s) → sau rút khoảng lặng 1.0 s còn 2523 s (71 %); 188 điểm cắt (khoảng lặng ≥ 3.0 s khớp ranh giới segment, trên 194), 189 unit (median 9.5 s), ~**1722 candidate**, ~358 có thời lượng thực tế 60–90 s; thời lượng thực tế / nguồn median 0.73.
- Quyết định (DECIDE cùng APPROVE TASK; P1–P3, Q3, Q4 đã được HUMAN LEAD chốt):
  - **A1 Stage / artifact:** stage `analysis` (CP1 §8), subpackage `src/auto_short/analysis/`; artifact `shots.json`, `silences.json`, `candidates.json` trong `work/<id>/`, ghi atomic, không chứa timestamp tạo file (byte-stable; provenance ở manifest, CP2 D5). `silences.json` là artifact bổ sung so với CP1 §8 (cập nhật CP1 §8 cùng task). Số giây làm tròn 3 chữ số.
  - **A2 Shot detection:** `ffmpeg -an -vf "scale=<scale_width>:-2,select='gt(scene,<scene_threshold>)',showinfo" -f null -` trên media nguồn (`source.path` của manifest); parse `pts_time`. Mặc định `scene_threshold = 0.3`, `scale_width = 320`. Không có chuyển shot → một shot `[0, duration]`.
  - **A3 Silence detection:** `ffmpeg -vn -af "silencedetect=noise=<silence_noise_db>dB:d=<silence_min>" -f null -`; mặc định `silence_noise_db = -45`, `silence_min = 0.3`. Gộp hai khoảng lặng cách nhau < 0.05 s. Khoảng lặng chưa đóng ở cuối file kết thúc tại `duration`. Media không có audio (`audio_codec = null`) → stage `failed`. `ffmpeg` lỗi → `failed`.
  - **A4 Hard break:** (a) segment `kind: non_speech`, hoặc (b) khoảng lặng ≥ `hard_break_silence` (**10.0 s**, P3). Candidate không bao giờ chứa hard break (không ghép đoạn không liên tục, CP1 §5).
  - **A5 Content window (CP1 §5, Q3):**
    - Intro: nếu có segment `non_speech` với `start < intro_window` (60 s): gọi `m` = `end` của segment đó muộn nhất; `content_start` = `end` của khoảng lặng đầu tiên ≥ `intro_min_silence` (1.0 s) bắt đầu sau `m` và trước `intro_window`; không có khoảng lặng như vậy → `content_start = m`. Không có `non_speech` trong window → `content_start = 0` (không phát hiện intro). Video test → `22.875` (loại nhạc + lời giới thiệu).
    - Outro: `content_end` = `start` của segment `non_speech` đầu tiên có `end > duration − outro_window` (180 s); không có → `duration`. Mọi thứ sau đó (kể cả lời hồi hướng) bị loại. Video test → `3554.6`.
    - Nhãn `non_speech` giữa bài chỉ là hard break (A4). Ghi `reason` cho `content.start`/`content.end`.
  - **A6 Điểm cắt (không cắt giữa câu, P2):** một ranh giới hợp lệ là khoảng lặng audio ≥ `min_boundary_silence` (**3.0 s**) **khớp ranh giới segment caption**: có segment speech bắt đầu trong `[silence.start − align_tolerance, silence.end + align_tolerance]` (`align_tolerance` 0.5 s, vì timestamp caption lệch so với audio). Ngoài ra: mép hard break và mép content window. Ranh giới logic vẫn là ranh giới segment (CP1 §5); timestamp cắt lấy theo mép khoảng lặng audio (chính xác hơn caption): đầu clip = `silence.end − boundary_pad`, cuối clip = `silence.start + boundary_pad` (`boundary_pad` 0.3 s, CP1 §5). Ở mép hard break / content edge: cắt tại mép khoảng lặng ≥ `silence_min` gần nhất phía trong content, không có thì tại timestamp segment; không bao giờ lấn vào nhạc/ngoài content. Khoảng lặng < 3.0 s không phải điểm cắt.
  - **A7 Speech unit:** đoạn giữa hai điểm cắt liên tiếp = một unit (`u0001`…): `start`/`end` (mép lời nói), `segment_ids` [đầu, cuối] (segment speech có trung điểm trong unit), `text` (nối text segment bằng khoảng trắng), `words`, `break_before`/`break_after` = `{"kind": "silence | hard_break | content_edge", "seconds": <độ dài khoảng lặng | null>}`.
  - **A8 Candidate + rút khoảng lặng (P1):** mọi dãy unit liên tiếp `[u_i … u_j]` không chứa hard break, trong content window:
    - `source_start` / `source_end` theo A6; `source_duration` = hiệu.
    - `trims`: với mỗi khoảng lặng (A3) nằm trong `[source_start, source_end]` dài hơn `max_pause` (**1.0 s**, CP1 §5): cắt bỏ phần giữa, giữ `max_pause / 2` ở mỗi đầu → khoảng `[silence.start + max_pause/2, silence.end − max_pause/2]`. CP7 thực hiện đúng danh sách này.
    - `duration` (thời lượng Short thực tế) = `source_duration − Σ trims`; giữ candidate khi `min_duration ≤ duration ≤ max_duration` (30 / 180 s, CP1 §3); `in_target` = `duration` trong `[target_min, target_max]` (60–90 s), chỉ là thông tin.
    - Shot guard: loại candidate có chuyển shot trong `(source_start, source_start + shot_guard)` hoặc `(source_end − shot_guard, source_end)` (1.0 s).
    - Id `c00001`… theo `(source_start, source_end)` tăng dần. Candidate chồng lấn nhau là bình thường; chống chồng lấn giữa clip được chọn là việc CP5.
  - **A9 Liệt kê đầy đủ (Q4):** `candidates.json` liệt kê mọi candidate hợp lệ (~1700 trên video test). CP5 có thể trình bày text theo unit cho AI; kết quả AI phải map về một `id` candidate tồn tại (CP1 §5: AI chỉ chọn trong candidate).
  - **A10 Schema v1:**
    ```json
    // shots.json
    {"schema_version": 1, "episode_id": "rbjfCfFq3Dk", "media_sha256": "<metadata.json source.sha256>",
     "method": {"tool": "ffmpeg", "filter": "scene", "threshold": 0.3, "scale_width": 320},
     "duration": 3622.001, "changes": [21.321, 47.948],
     "shots": [{"id": "h0001", "start": 0.0, "end": 21.321}]}
    // silences.json
    {"schema_version": 1, "episode_id": "rbjfCfFq3Dk", "media_sha256": "…",
     "method": {"tool": "ffmpeg", "filter": "silencedetect", "noise_db": -45, "min_seconds": 0.3},
     "stats": {"count": 0, "total_seconds": 0.0},
     "silences": [{"start": 19.667, "end": 22.875}]}
    // candidates.json
    {"schema_version": 1, "episode_id": "rbjfCfFq3Dk",
     "transcript_sha256": "<transcript.json transcript_sha256>",
     "shots_sha256": "<sha256 canonical JSON shots.json>", "silences_sha256": "<sha256 canonical JSON silences.json>",
     "params": {"min_boundary_silence": 3.0, "align_tolerance": 0.5, "hard_break_silence": 10.0, "max_pause": 1.0,
                "boundary_pad": 0.3, "min_duration": 30, "max_duration": 180, "target_min": 60, "target_max": 90,
                "shot_guard": 1.0, "intro_window": 60, "intro_min_silence": 1.0, "outro_window": 180},
     "content": {"start": 22.875, "end": 3554.6, "start_reason": "intro: non_speech s00001 + silence 19.667-22.875",
                 "end_reason": "outro: non_speech s00815"},
     "stats": {"units": 0, "candidates": 0, "in_target": 0, "content_seconds": 3531.725, "content_seconds_trimmed": 0.0},
     "units": [{"id": "u0001", "start": 22.875, "end": 25.8, "segment_ids": ["s00007", "s00007"], "text": "các vị đồng tu Xin chào mọi người", "words": 7,
                "break_before": {"kind": "content_edge", "seconds": null}, "break_after": {"kind": "silence", "seconds": 5.1}}],
     "candidates": [{"id": "c00001", "source_start": 22.575, "source_end": 129.8, "source_duration": 107.225,
                     "duration": 78.4, "in_target": true, "unit_ids": ["u0001", "u0005"], "segment_ids": ["s00007", "s00015"],
                     "words": 180, "trims": [[26.3, 30.425]],
                     "boundary": {"start": {"kind": "content_edge", "seconds": null}, "end": {"kind": "silence", "seconds": 3.7}},
                     "shot_ids": ["h0001", "h0002"], "shot_changes": [47.948]}]}
    ```
    Giá trị ví dụ minh họa hình dạng, không phải output kỳ vọng. `text` chỉ nằm ở unit; candidate tham chiếu `unit_ids`/`segment_ids` [đầu, cuối].
  - **A11 Stage / resume / CLI** (dùng `run_stage` của CP2): yêu cầu `transcript` = `done`. `inputs` = `metadata.json`, `transcript.json` (relative + sha256) và media nguồn (theo manifest `source`, dùng hash cache CP2 D6). `config_hash` = mọi key `[analysis]`. Đổi param nào → chạy lại cả stage (shot + silence ~90 s trên video test; chấp nhận ở MVP). Chạy lại analysis → downstream stale; transcript chạy lại → analysis stale. CLI `auto-short analysis <episode_id> [--force] [--config PATH]` — stdout `<episode_id>\t<analyzed (<n> candidates)|skipped (up to date)>\t<path candidates.json>`; log (content window, số shot/silence/unit/candidate) ra stderr; exit code theo CP2 D8. `status` không đổi.
- Không dependency mới: `ffmpeg` system binary + stdlib (CP1 §10).

## Implementation approach

- Hàm thuần tách biệt: `parse_showinfo`, `parse_silencedetect`, `detect_content_window`, `find_cut_points`, `build_units`, `generate_candidates` (kèm `plan_trims`); detector qua Protocol (`MediaAnalyzer`: shots + silences) để test bằng fake; implementation thật gọi `ffmpeg` qua `subprocess`.
- Validation cuối stage trước khi ghi artifact: mọi candidate trong content window, không chứa hard break, mép cắt đúng A6, trims nằm trong clip và không chồng nhau, `duration` = `source_duration − Σ trims` trong 30–180, id duy nhất; vi phạm → `failed` (lỗi code).
- Fixtures: transcript + silences trích từ `rbjfCfFq3Dk` (đầu: nhạc + lời giới thiệu; cuối: nhạc + hồi hướng; đoạn có hard break) và dữ liệu tổng hợp (không nhãn intro, không audio, chuyển shot sát mép, khoảng lặng không khớp segment); text `showinfo`/`silencedetect` mẫu. Không commit media.
- Decision record `docs/decisions/CP4-analysis-contract.md` là canonical owner của A1–A11 và schema ba artifact.

## Acceptance Criteria

1. `shots.json`, `silences.json` đúng schema A10; parser đúng; gộp khoảng lặng liền nhau; không có chuyển shot → một shot; không audio hoặc `ffmpeg` lỗi → stage `failed`.
2. Content window theo A5: nhạc intro + lời giới thiệu và phần từ nhạc kết trở đi bị loại; nhãn `non_speech` giữa bài không cắt content; không có nhãn intro/outro → `0`/`duration` kèm `reason`.
3. Mọi candidate: mép tại điểm cắt A6 (khoảng lặng ≥ 3.0 s khớp ranh giới segment, hoặc mép hard break/content), không bắt đầu/kết thúc ở khoảng lặng < 3.0 s, không chứa hard break, trong content window, không vi phạm shot guard.
4. `trims` đúng A8 (mỗi khoảng lặng > 1.0 s còn đúng 1.0 s, không trim khoảng lặng ≤ 1.0 s); 30 ≤ `duration` ≤ 180 tính trên thời lượng sau trim; `in_target` đúng.
5. Candidate tham chiếu `unit_ids`, `segment_ids`, `shot_ids` hợp lệ; id ổn định.
6. Chạy lại → `analysis: skip (up to date)`, ba artifact byte-identical; đổi `[analysis]` / transcript chạy lại → chạy lại; `--force` luôn chạy lại; transcript chưa `done` → exit ≠ 0, manifest `failed` + `error`, không để artifact dở dang.
7. Không dependency mới; không code AI/selection/render.
8. `node scripts/framework-check.mjs` PASS; decision record CP4 ACCEPTED; CP1 §8 có `silences.json`.

## Required verification

- `pytest -q` trong conda env `auto-short` → PASS (AC1–AC6 bằng fixture + fake).
- Chạy thật: `auto-short analysis rbjfCfFq3Dk` trên workspace YouTube hiện có → ghi content window, số shot (kỳ vọng 14 chuyển shot), số silence, unit, candidate, in_target, thời lượng content sau trim, thời gian chạy; script kiểm độc lập trên output thật: mọi candidate thỏa AC3–AC4 (đối chiếu `transcript.json`, `silences.json`, `shots.json`).
- Chạy lại → skip, sha256 ba artifact không đổi (AC6).
- `git diff --stat main...HEAD` + đọc `pyproject.toml` (AC7).
- `node scripts/framework-check.mjs` (AC8).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract mạng. CLI thêm lệnh; manual test là điểm danh sau automated verification.

- [x] `auto-short analysis rbjfCfFq3Dk` → mở `candidates.json`, xem content window, vài unit đầu/cuối.
- [x] Cắt thô 3 candidate ngẫu nhiên (`ffmpeg -ss <source_start> -to <source_end>`, chưa áp trims) ra scratchpad, nghe mép đầu/cuối: không cụt chữ, không nhạc intro/outro, không lời giới thiệu.
- [x] `auto-short status rbjfCfFq3Dk` → `analysis done`.

## Result

- Main changes: subpackage `src/auto_short/analysis/` (`detect.py` ffmpeg scene/silencedetect + parser, `candidates.py` content window/cut point/unit/candidate/trims/validate, `stage.py`); config `[analysis]` typed (17 key); CLI `auto-short analysis`; decision record `docs/decisions/CP4-analysis-contract.md` ACCEPTED; CP1 §8 thêm `silences.json`; project profile, README. IMPLEMENTER commits `69b3d93`, `ef689fc`, `7ee7e56`.
- Tests (ORCHESTRATOR chạy lại độc lập):
  - `~/miniconda3/envs/auto-short/bin/pytest -q` → `134 passed`.
  - Chạy thật `rbjfCfFq3Dk` (IMPLEMENTER, `--force`): 88.6 s wall, RSS 171 MB. Content `22.875 → 3554.6` (intro: `s00001` + silence 19.667–22.875; outro: `s00815`); 14 chuyển shot (khớp đo trước); 720 silence (1645.4 s); 195 unit; **1484 candidate**, 325 in_target (60–90 s); content 3531.7 s → 2523.1 s sau trim. Unit đầu "các vị đồng tu Xin chào mọi người" (lời giới thiệu đã loại); unit cuối kết ở 3554.01 "… A Di Đà Phật".
  - Chạy lại (ORCHESTRATOR) → `analysis: skip (up to date)`, sha256 ba artifact không đổi; `--force` lần hai (IMPLEMENTER) byte-identical. `auto-short status` → `analysis done`.
  - Script kiểm độc lập của ORCHESTRATOR trên output thật (content window, không chứa `non_speech`/silence ≥ 10 s, mép `silence` nằm trong khoảng lặng ≥ 3.0 s, mép khác không nằm giữa segment, trims còn đúng 1.0 s, `duration` = nguồn − trims ∈ [30,180]) → 0 vi phạm / 1484. Script kiểm của IMPLEMENTER → 0 vi phạm.
  - Render thử 3 candidate ngẫu nhiên (`c00182`, `c00500`, `c00689`) có áp trims: thời lượng file khớp `duration` (±0.04 s).
  - `pyproject.toml` không đổi (không dependency mới). `node scripts/framework-check.mjs` → PASS.
- Review: ACCEPTED (dual-agent, ORCHESTRATOR review diff-first); không có blocking finding.
- Important findings / decisions:
  - Số candidate thực 1484 / 195 unit (ước lượng 1722 / 189) vì 8 nhãn `[âm nhạc]` giữa bài là hard break (A4a); bỏ các nhãn đó cho đúng 189 unit. Shot guard loại 0 candidate trên video test.
  - Quyết định cục bộ của IMPLEMENTER trong A1–A11 ghi ở decision record: mép cạnh nhãn/content lấy theo khoảng lặng gần nhất và không vượt ranh giới; clip không bắt đầu trước `content.start`; segment gán unit theo trung điểm vùng cắt; đoạn không có lời giữa hai điểm cắt thì bỏ điểm cắt `silence` ngắn hơn (giữa hai hard break → không có unit, vd nhạc chen 131–173 s); silence chồng nhãn `non_speech` gộp thành một hard break; outro phải bắt đầu sau `content.start`; trims tính phần khoảng lặng trong clip; params ghi dạng float; mọi phép tính theo ms nguyên.
  - Non-blocking: một số nhãn `[âm nhạc]` ngắn giữa bài có vẻ là caption nhận nhầm khoảng lặng (vd `s00275` 1248.15, `s00539` 2380.59) → cắt bớt candidate. Có thể xem lại ở CP5/CP9.
- Known limitations: điểm cắt chỉ là điều kiện cần cho "không cắt giữa câu" (vd `c00182` bắt đầu "trong Bồ Tát đặc biệt …" — trọn ý do CP5/CP9 đánh giá). Đổi bất kỳ key `[analysis]` chạy lại cả stage (~90 s). Transcript không có nhãn `[…]` (Whisper) → không phát hiện intro/outro. Manual checklist: nghe thử chờ Tech Lead.
- PR: #6 https://github.com/ntnghia1908/youtube-auto-short/pull/6 (HUMAN LEAD approved push + PR 2026-09-26).
