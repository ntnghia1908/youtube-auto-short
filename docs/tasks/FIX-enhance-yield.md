# Task: FIX-enhance-yield — Worker enhance nhường GPU cho Ollama ngay giữa đoạn

## Status / Approval

- Status: APPROVED
- Type: BUG
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project; task chạm worker nhiều thread + giao thức E3, cần review diff riêng.
- Base commit / branch: `37114b9` (`origin/main` 2026-10-07) / `fix/enhance-yield` (worktree `../youtube-auto-short-enhance-yield`)
- Human Lead approval: accepted (HUMAN LEAD 2026-10-07: APPROVE D1–D4; Q1 không biết → không ảnh hưởng nhờ D3; Q2 = không thêm gợi ý)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì sửa quyết định đã duyệt trong `docs/decisions/CP13.1-enhance-worker-contract.md` (canonical owner): E7 (worker chỉ dừng *sau* đoạn hiện tại) và E3 (thêm field cho response `may-run`). Không thêm dependency, không đổi schema artifact, không đổi `config_hash` stage nào, không đổi security model (E8).

## Bối cảnh (sự cố 2026-10-07)

- Bốn job `pipeline` của Kinh Địa Tạng (tập 4 `ja52PvWoU4o`, tập 5 `1VAkCR8kK5I`, cùng hai tập khai thị `.kt`) đều lỗi ở bước selection, cửa sổ `w01.1`: `timeout after 600 s … (after 3 attempts)`. Mỗi job tốn khoảng 30 phút. HUMAN LEAD bấm "Chạy tiếp" hai lần, lần nào cũng lỗi. Tập 8, 9, 10 (`RLkVp6Bsevc`, `ztfEEXhnBf4`, `uuymFxiObZE`) và `K4B4tmtEQ0Q` cũng lỗi giống vậy từ 2026-10-04.
- Chạy lại đúng request của `1VAkCR8kK5I` / `w01.1` (gọi trực tiếp, streaming): xong trong 270 s, 10,5k token, trả JSON hợp lệ. Dữ liệu và prompt không có vấn đề.
- Cùng lúc đó worker `rtx3090` (nằm trong `[enhance] yield_workers`) đang enhance `o6cW9tQ0e2g` bằng GFPGAN (CP13.4). Bình thường mỗi đoạn mất khoảng 6 phút, riêng `seg_00019` mất **2 h 12 ph** (00:52 → 03:04 UTC), trùng khít khoảng thời gian bốn job bị lỗi. Khi job lỗi cuối cùng kết thúc, worker chạy lại nhịp 6 phút một đoạn. Kết luận: Ollama (`qwen3:30b`, 21,7 GB VRAM) và GFPGAN tranh nhau RTX 3090 24 GB, cả hai cùng chậm đi hàng chục lần.
- Nguyên nhân gốc: E7 chỉ kiểm `may-run` *trước* mỗi đoạn và ghi giả định "≤ 1 đoạn ≈ vài chục giây với 3090". Từ khi có GFPGAN, một đoạn mất khoảng 6 phút. Nếu đoạn bắt đầu đúng lúc job vừa vào làn `ai` (kiểm `may-run` xong rồi job mới tới), worker sẽ giữ GPU suốt đoạn đó, và đoạn đó còn dài thêm vì bị tranh GPU. Thêm nữa, phía worker chỉ giải phóng VRAM khi `yield_to_ollama = true`. VM không biết giá trị này (E3 note).

## Goal

Khi làn `ai` (hoặc một job `post`) cần Ollama, worker trong `yield_workers` phải dừng enhance và trả VRAM **trong vòng ≤ 15 s**, kể cả khi đang làm dở một đoạn. Selection / titling không còn bị timeout chỉ vì đang enhance.

## Scope

- In scope:
  - **Y1 — VM, `may-run` (E3, E7)**: response thêm `preempt: bool`. Giá trị là `true` khi `run: false` vì Ollama bận (làn `ai` có job đang chạy hoặc đang đợi, hoặc một job `post` đang soạn). Giá trị là `false` khi `run: false` vì "Tạm dừng enhance" hoặc `enabled = false`. Field `reason` giữ nguyên. Worker cũ bỏ qua field mới; VM cũ không gửi field (worker mới coi như `false`).
  - **Y2 — Worker, dừng giữa đoạn**: trong lúc `run_segment` chạy, worker hỏi `may-run` định kỳ (`preempt_check_seconds`, mặc định 10 s; key mới của config worker). Nếu nhận `run: false` và `preempt: true` thì đặt `abort`, xóa file đoạn dở, **luôn** gọi `release_vram()` (bất kể `yield_to_ollama`), rồi vào `wait_may_run` như hiện nay. Khi được chạy lại, worker làm lại đoạn đó từ đầu. Lần dừng này không tính là lỗi đoạn (`fails`), không release lease, lease vẫn heartbeat bình thường. Lỗi mạng khi hỏi định kỳ thì coi như `run: true` (giống E4 offline). Pause toàn cục (`preempt: false`) vẫn giữ hành vi cũ: chạy hết đoạn hiện tại rồi mới dừng.
  - **Y3 — Worker giữa hai đoạn**: `wait_may_run` nhận `preempt: true` thì luôn `release_vram()`, không còn phụ thuộc `yield_to_ollama`. `yield_to_ollama` giữ trong config để tương thích nhưng ghi rõ nó chỉ còn tác dụng với VM cũ (không gửi `preempt`).
  - **Y4 — ADR**: sửa E7 (bỏ giả định "vài chục giây", thêm luật dừng giữa đoạn + chu kỳ hỏi) và E3 (field `preempt`) trong `docs/decisions/CP13.1-enhance-worker-contract.md`, kèm dòng "Sửa đổi HUMAN LEAD … (FIX-enhance-yield)". Cập nhật `config.example.json` / README của worker nếu chúng có nhắc tới hai điểm này.
  - Test: `tests/test_enhance_api.py` cho Y1, `tests/test_enhance_worker.py` (dùng `fake_server.py`) cho Y2 / Y3.
- Out of scope:
  - Lưu tiến độ giữa đoạn (checkpoint khung). Bị dừng thì mất tối đa một đoạn (≈ 6 phút GPU).
  - Đổi timeout / retry của selection, titling, post (CP5 B5, CP6 G6, CP8.15 P3).
  - Đổi kích thước đoạn (`segment_frames`) hoặc model enhance.
  - Thông báo lỗi "GPU đang bận enhance" trên UI (xem Q2).
  - Chạy lại các tập đang lỗi: HUMAN LEAD bấm "Chạy tiếp" trên 8080 (S0, không cần task này).

## Authority / key decisions

- Canonical owner: `docs/decisions/CP13.1-enhance-worker-contract.md` E3, E4, E7 (task này sửa E3 và E7). Job lanes: `docs/decisions/CP8.3-web-contract.md` W5 (không đổi). `ai_busy` giữ định nghĩa hiện tại (CP13.1b).
- Quyết định (HUMAN LEAD 2026-10-07: APPROVE D1–D4):
  - **D1**: dừng giữa đoạn bằng cách bỏ phần đoạn đang làm dở và làm lại từ đầu, không checkpoint.
  - **D2**: chu kỳ hỏi `may-run` trong lúc làm đoạn là 10 s (`preempt_check_seconds`, cho phép đặt 5–60).
  - **D3**: `preempt: true` thì luôn giải phóng VRAM, không phụ thuộc `yield_to_ollama`.
  - **D4**: "Tạm dừng enhance" toàn cục vẫn để chạy hết đoạn hiện tại (không mất công đã làm).
- Câu hỏi (đã trả lời 2026-10-07):
  - **Q1**: máy RTX 3090 hiện đặt `yield_to_ollama` là bao nhiêu? → HUMAN LEAD không biết; D3 đã duyệt nên không còn quan trọng với VM mới.
  - **Q2**: có cần thêm gợi ý vào lỗi timeout Ollama (ví dụ "worker rtx3090 đang enhance") không? Đề xuất: không. Sau Y2 trường hợp này không nên xảy ra nữa; nếu vẫn gặp thì tách thành task riêng. → HUMAN LEAD: đồng ý (không thêm).

## Implementation approach

- VM: `EnhanceService.may_run` trả thêm cờ preempt (hoặc `may_run_info` trả `(run, reason, preempt)`), giữ nguyên chữ ký cũ cho các chỗ đang gọi. Route `/api/enhance/may-run` thêm field vào JSON.
- Worker: mở rộng `_watch_abort` (luồng phụ đang có) để hỏi `may-run` mỗi `preempt_check_seconds`. Có preempt thì đặt cờ `self._preempted` và `abort`. Trong `_segments_loop`, phần `except Aborted` phân biệt hai trường hợp: preempted thì xóa file đoạn dở, `release_vram()`, rồi `continue` (vòng lặp gọi lại `wait_may_run`); còn lại (stop / lost) thì giữ như cũ. Không đổi format file trạng thái cục bộ.
- `fake_server.py` hỗ trợ `preempt`, và hỗ trợ đổi giá trị `may_run` khi đoạn đang chạy (test dùng engine giả chạy chậm theo `abort`).

## Acceptance Criteria

1. `GET /api/enhance/may-run` từ worker trong `yield_workers`: khi làn `ai` có job đang chạy hoặc đang đợi (không tính lúc hàng đợi tạm ngưng), hoặc khi có job `post` đang soạn, trả `{run: false, preempt: true}`. Khi "Tạm dừng enhance" thì trả `{run: false, preempt: false}`. Các trường hợp còn lại trả `{run: true, preempt: false}`. Worker không thuộc `yield_workers` không bao giờ nhận `preempt: true`.
2. Worker đang làm dở một đoạn, server chuyển sang `run: false, preempt: true`: trong ≤ `preempt_check_seconds` + 5 s, `run_segment` dừng, file đoạn dở bị xóa, `release_vram()` được gọi (cả khi `yield_to_ollama = false`), đoạn không được đánh dấu `encoded`, `fails` không tăng, lease không bị release.
3. Sau khi server trả lại `run: true`, worker làm lại đúng đoạn đó và các đoạn sau. Kết quả cuối (số đoạn, sha256 upload) giống như một lần chạy không bị dừng.
4. Đang làm dở một đoạn mà nhận `run: false, preempt: false` (pause): đoạn vẫn chạy xong và được upload, sau đó worker mới dừng (hành vi cũ).
5. Hỏi `may-run` định kỳ mà bị lỗi mạng hoặc HTTP: đoạn vẫn chạy tiếp, không abort.
6. VM cũ (response không có `preempt`): worker mới chạy như trước task này (không dừng giữa đoạn).
7. ADR E3 / E7 được cập nhật, ghi rõ nguồn sửa đổi. Không còn nơi nào ghi giả định "vài chục giây".

## Required verification

- `python -m pytest -q -x --tb=short tests/test_enhance_api.py tests/test_enhance_worker.py` — AC 1–6
- `python -m pytest -q -n auto` — toàn bộ suite, không regression
- `python -m pytest -q -n auto -m slow` — bắt buộc vì sửa `tools/enhance_worker/` (Test policy §8). Thiếu env `enhance-bench` thì SKIP và ghi rõ trong Result.
- `node scripts/framework-check.mjs`

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database. Có chạm giao thức worker ↔ VM (E3, field mới tương thích ngược). Security model (E8) không đổi. Manual test là gate trước merge, vì worker Windows phải được chép tay sang máy 3090.

- [ ] Chép `tools/enhance_worker/` mới sang máy RTX 3090, khởi động lại worker. Log in ra `preempt_check_seconds`.
- [ ] Lúc 3090 đang enhance giữa đoạn, bấm "Chạy tiếp" một tập đang lỗi selection (ví dụ `ja52PvWoU4o`). Log worker có dòng dừng giữa đoạn + giải phóng VRAM trong khoảng 15 s; `nvidia-smi` trên 3090 cho thấy tiến trình worker không còn giữ VRAM lớn.
- [ ] Selection của tập đó xong trong khoảng 5–10 phút, không timeout.
- [ ] Khi làn `ai` trống, worker tự làm lại đoạn bị dừng. Tập enhance hoàn tất và có "HD: đã xong".
- [ ] "Tạm dừng enhance" lúc đang làm dở một đoạn: đoạn đó vẫn chạy xong rồi worker mới dừng.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
