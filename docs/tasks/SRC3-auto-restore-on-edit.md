# Task: SRC3 — Sửa tập đã dọn tự lấy lại nguồn (3090 trước YouTube)

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`), một writer; test web / full suite do ORCHESTRATOR chạy ngoài sandbox
- Authorization mode: task
- Authorization source: `docs/decisions/SRC3-SRC4-store-first-sources.md` G1–G3 (ACCEPTED 2026-10-25, G1–G3; G2 = a)
- Parallel group: SRC3 ∥ SRC4 (Owned paths rời nhau)
- Owned paths: `src/auto_short/review/archive.py` (`restore_source`, kiểm bản khác byte); `src/auto_short/web/routes/episode_edit.py` (5 route sửa); `src/auto_short/web/app.py` (chỉ target khôi phục + nối thao tác sau khôi phục); `src/auto_short/web/static/` phần trang tập (trạng thái "đang lấy lại nguồn"); `tests/test_restore_source_cp837.py`, `tests/test_src3_auto_restore.py` (mới); A1: `tests/test_storage_cp86.py`, `tests/test_web_cp9.py` (chỉ cập nhật test luật archived theo G1, giữ assertion khác); file này
- Dependencies: SRC1 (#154), SRC2 (#155); F1 dùng `store.index_cache` của SRC4 (`f7849ae`)
- Base commit / branch: `f7849ae` (`feature/src4-ingest-from-store`, SRC4); HEAD lúc bắt đầu F1: `d73419d` (WIP SRC3 do ORCHESTRATOR commit, đã rebase trên SRC4) / `feature/src3-auto-restore`
- Human Lead approval: accepted — HUMAN LEAD 2026-10-25 "Duyệt cả hai"
- Implementation authorized: YES

Amendment A1 — ORCHESTRATOR 2026-10-25: thêm hai test HTTP trên vào Owned paths để thay kỳ vọng CP8.6 S3 đã bị G1 đổi; kiểm 202 + job khôi phục chung, request không hợp lệ không tạo job, nộp lại URL vẫn 409. Không đổi implementation hoặc nới assertion khác. HTTP/full suite do ORCHESTRATOR chạy ngoài sandbox.

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`.

S2 vì đổi luật CP8.6 S3 (tập `archived` từ chối sửa) và CP8.37 (chỉ nhận đúng sha).

## Goal

Sửa tiêu đề / cắt lại / thêm / khôi phục Short trên tập đã dọn chạy được ngay: web tự lấy lại nguồn (3090 trước YouTube) rồi làm tiếp thao tác, không bắt bấm "Khôi phục nguồn" trước.

## Scope

- In scope: G1, G2 a.
- Out of scope: G4 (chỉ đổi `config.toml`); sửa transcript / analysis; ingest (SRC4); ghép chủ đề (TC3.2).

## Authority / key decisions

- G1: 5 route trong `episode_edit.py` đang trả 409 `ArchivedError` → xếp job khôi phục (làn prepare, `YoutubeWait` khi chặn) rồi xếp thao tác; trả 202 + trạng thái. Hai lần sửa liên tiếp trên cùng tập dùng chung một job khôi phục.
- G2 a (HUMAN LEAD chọn): bản khác sha nhận khi thời lượng khớp và mọi Short đã render khớp `theme_render.audio.compare` với |lag| ≤ 1 khung; `restored.json` ghi `differs_from_ingest`, sha mới; `manifest.source` giữ nguyên.

## Implementation approach

- `restore_source(…, accept_redownload=…)`: sau khi bản tải về không trùng sha → nếu G2 a: kiểm thời lượng + audio từng Short (dùng lại `audio.compare`, `_reference`-tương đương lấy Short từ `render_manifest.json`) trong thư mục tạm; đạt → cài như hiện nay, ghi provenance.
- Web: target khôi phục hiện có (`app.py` ~123) nhận "thao tác tiếp theo" (route + payload đã kiểm) và submit khi xong; route trả 202 kèm job id.
- Frontend: thông báo "đang lấy lại nguồn từ 3090…" thay lỗi 409.

## Phải giữ nguyên

- Nút "Khôi phục nguồn" và API hiện có; rollback khi cài lỗi; grace `restored.json`; luật dọn của SRC1.

## Code bị thay / xóa

- Nhánh 409 `ArchivedError` trong 5 route (giữ class `ArchivedError` cho chỗ khác còn dùng).

## Acceptance Criteria

1. Sửa trên tập `archived` → job khôi phục + thao tác chạy nối tiếp; xong thì kết quả như tập chưa dọn.
2. Khôi phục lấy kho 3090 trước YouTube; YouTube chặn → chờ, không hỏng.
3. G2 a: bản khác byte đạt kiểm → khôi phục, `restored.json` ghi provenance; lệch > 1 khung / thời lượng sai → từ chối, không đổi file nào.
4. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_restore_source_cp837.py tests/test_src3_auto_restore.py tests/test_web_app.py -x --tb=short` — AC 1–3.
- `… -m pytest -q -n auto`; `node --check` JS đã sửa; `node scripts/framework-check.mjs`; `git diff --check` — AC 4.
- Chạy thật trên 8080 (ghim branch, hỏi trước khi restart): sửa tiêu đề 1 Short của 1 tập đã dọn có bản trên 3090 → Short render lại.

## Manual test checklist (Tech Lead)

- [ ] Sửa tiêu đề Short trên tập đã dọn: thấy "đang lấy lại nguồn", sau đó Short mới đúng tiêu đề.

## Result

- Delivery sau F1 (ORCHESTRATOR review vòng 3): đã sửa blocking finding; giữ Status `IN_PROGRESS` chờ review / full suite, chưa xác nhận AC4. IMPLEMENTER không commit / push / PR. Làm trên HEAD `d73419d`, xếp trên SRC4 `f7849ae`.
- Main changes:
  - `review/archive.py`: workspace → cache → HEAD/fetch kho 3090 → YouTube; fetch theo sha HEAD. Bản khác ingest kiểm thời lượng metadata + mọi Short của cả hai part bằng segments render manifest, sha Short và `audio.compare`, lệch tối đa một khung nguồn; provenance mới trong `restored.json`, giữ nguyên `manifest.source` và rollback.
  - `web/routes/episode_edit.py`: các nhánh archived chuyển sang 202 `{queued: "restore", job}`; validate payload read-only trước khi xếp; dùng chung job theo owner cho cả `.kt`; áp dụng tuần tự qua cùng hàm review và target hiện có.
  - `web/app.py`: nối prepare → thao tác/AI → render, lưu thao tác và checkpoint trong queue spec để tiếp tục sau restart; khôi phục thủ công không có thao tác vẫn chỉ dùng prepare; kho có nguồn chạy được khi YouTube đang backoff.
  - `web/static/app.js`: mở sửa / thêm / khôi phục trên tập archived, thông báo “Đang lấy lại nguồn từ 3090…”, dùng polling hiện có để tự làm mới.
  - Tests: sửa/bổ sung `tests/test_restore_source_cp837.py`, thêm `tests/test_src3_auto_restore.py`; A1 cập nhật `tests/test_storage_cp86.py`, `tests/test_web_cp9.py`; contract này cập nhật ownership, trạng thái và Result. Không sửa path khác.
- Helpers mới: `_verify_replacement`; `validate_restore_edit`, `apply_restore_edit`, `_defer_edit`; tách target thành `prepare`, `edit`, `render_edits`.

| AC | Bằng chứng test |
|---|---|
| 1 | `test_archived_edits_restore_then_apply` (title, restore, cut/reset, add proposal/range; lanes/serial); `test_two_edits_share_restore_and_keep_order`; `test_arriving_edit_during_download_shares_job`; `test_shared_manual_restore_and_sibling_edits`; `test_restore_failure_discards_edits`; queued/checkpoint restart; normal title vẫn render |
| 2 | SRC1 store-before-YouTube / cache precedence và CP8.37 YoutubeWait cũ; thêm `test_restore_store_can_run_during_youtube_backoff`, `test_youtube_block_keeps_edits_until_retry` |
| 3 | `test_src3_different_bytes_verify_all_parts_and_record_provenance` (YouTube/cache/store HEAD sha); `test_src3_replacement_failure_changes_no_files` (lag, duration, empty, audio, missing, fps, last part); exact bytes; real ffmpeg extraction; rollback cũ |
| 4 | ORCHESTRATOR báo sau A1: bộ 5 file HTTP/restore/web_app có 141 passed; chưa có full suite sau A1/F1, chạy thật 8080 chưa chạy |

Lệnh đã chạy, kết quả thật:

```sh
timeout 240 env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/src3-auto-restore/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_restore_source_cp837.py tests/test_src3_auto_restore.py -k 'not http' -x --tb=short
# 84 passed, 1 deselected in 17.19s (chạy lại sau A1)
timeout 60 node scripts/framework-check.mjs
# exit 0, PASS: framework structure
timeout 60 node --check src/auto_short/web/static/app.js
# exit 0
git diff --check
# exit 0
```

- Không chạy lệnh pytest nguyên bản không lọc HTTP, `tests/test_web_app.py`, full suite `pytest -q -n auto`, hoặc thử thật 8080: sandbox không mạng/socket loopback; giao ORCHESTRATOR chạy ngoài sandbox. Chưa restart dịch vụ.
- A1: blocker ownership cũ được gỡ. Đã đổi assertion title/reset/restore, cut/reset/add sang 202 + cùng một restore job; queue pause để không chạy downloader, giữ kiểm source/review/archive chưa đổi. Nộp lại URL vẫn 409 đúng message. Kiểm request sai trả 422 và chưa tạo job. Test storage bổ sung fingerprint nguồn ngay trong test vì fixture hiển thị cũ thiếu path/sha/size; không đổi fixture chung. `restore_clip` chưa xóa vốn là no-op hợp lệ (trả False), nên dùng title rỗng / clip không tồn tại cho case input sai. Giữ assertion play/download/published/delete; cancel restore đang đợi trước khi kiểm xóa cả tập. Đổi tên test CP9 thành `test_archived_edits_queue_shared_restore_and_source_file`.
- Verification A1 trong sandbox: chạy lại đúng bộ hai file với `-k 'not http'` như lệnh trên: **84 passed, 1 deselected in 17.19s**; `timeout 60 node --check src/auto_short/web/static/app.js` exit 0; `git diff --check` exit 0. Không chạy hai file HTTP hoặc full suite sau A1 theo phân công.
- Bằng chứng ORCHESTRATOR trước A1 (user báo, không phải lệnh IMPLEMENTER chạy): full suite ngoài sandbox **3 failed, 2905 passed, 1 skipped**, ba failure là assertion archived cũ trong hai file A1. Review vòng 3: ORCHESTRATOR báo bộ `test_storage_cp86` / `test_web_cp9` / `test_restore_source_cp837` / `test_src3_auto_restore` / `test_web_app` ngoài sandbox sau A1 có **141 passed**; đây chưa phải full suite sau A1/F1.
- `git diff --stat` lịch sử trước WIP `d73419d` (không phải diff của F1):

```text
 docs/tasks/SRC3-auto-restore-on-edit.md   |  53 ++++++++++-
 src/auto_short/review/archive.py          | 115 +++++++++++++++++++-----
 src/auto_short/web/app.py                 | 105 +++++++++++++++++++---
 src/auto_short/web/routes/episode_edit.py | 141 +++++++++++++++++++++++++++---
 src/auto_short/web/static/app.js          |  30 +++----
 tests/test_restore_source_cp837.py        | 139 +++++++++++++++++++++++++++++
 tests/test_storage_cp86.py                |  34 +++++--
 tests/test_web_cp9.py                     |  14 ++-
 8 files changed, 555 insertions(+), 76 deletions(-)
```

- Các file SRC3 trước F1 đã được ORCHESTRATOR commit trong WIP `d73419d`; IMPLEMENTER không tạo commit mới.

### Review vòng 3 — F1

- Finding: `RestoreSourceTarget.needs_download` gọi HEAD kho dưới scheduler lock, có thể chặn cả scheduler/web tới timeout mạng.
- Fix trong `web/app.py`: dùng `store.index_cache.has_source(self.config, ep.hd_owner(self.episode_id), blocking=False)`. Cache lạnh trả cần tải; snapshot có nguồn trả không cần tải. Refresh nền và listener đánh thức scheduler tái dùng SRC4, không sửa store cache / JobRunner. Không còn HEAD trên đường gọi đồng bộ của `needs_download`; `prepare` vẫn gọi `restore_source` HEAD/fetch kho như cũ, ngoài scheduler lock.
- Test mới: `test_restore_needs_download_uses_nonblocking_store_snapshot` với client giả chặn bằng Event, gọi target khi giữ scheduler lock; kiểm cache lạnh trả True, lock được trả trong lúc refresh vẫn chờ, không gọi HEAD; snapshot có nguồn trả False. Bao phủ owner thường và `.kt`, cấu hình lanes/serial. Thêm fixture cô lập cache, cập nhật client giả của test backoff để có index; giữ kiểm HEAD/fetch restore và YouTube backoff hiện có.
- Lệnh duy nhất chạy verification F1 trong sandbox (có timeout giới hạn):

```sh
timeout 240 env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/src3-auto-restore/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_src3_auto_restore.py tests/test_restore_source_cp837.py -k 'not http'
# 88 passed, 1 deselected in 16.13s; exit 0
```

- Không chạy TestClient, full suite, node/framework check hoặc gọi mạng thật trong vòng F1; các kết quả lệnh ở phần trước là bằng chứng các vòng trước. HTTP/full suite tiếp theo do ORCHESTRATOR chạy ngoài sandbox.


ORCHESTRATOR (2026-10-25, ngoài sandbox): review 3 vòng (A1 đổi assertion luật cũ CP8.6 S3 trong `test_storage_cp86.py`, `test_web_cp9.py` — nộp lại URL vẫn 409; F1 `needs_download` không gọi mạng dưới lock scheduler, dùng `index_cache` của SRC4 → branch xếp trên SRC4 #157). HTTP + targeted (`test_storage_cp86 test_web_cp9 test_restore_source_cp837 test_src3_auto_restore test_web_app`) 141 passed (trước F1); full suite `-n auto` **2942 passed, 1 skipped** (sau F1); `node --check app.js`, `framework-check`, `git diff --check` PASS. Còn: chạy thật 8080 (chờ HUMAN LEAD cho restart).
