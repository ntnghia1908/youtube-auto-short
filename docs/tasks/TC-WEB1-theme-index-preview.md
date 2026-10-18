# Task: TC-WEB1 — Web preview kiểm thử TC1

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Human Lead: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: codex — contract đã chuẩn bị; reviewer độc lập khi Claude Code bàn giao
- Implementer: claude-code — HUMAN LEAD đổi binding ngày 2026-10-18; writer duy nhất, không delegate thêm để giảm overhead/token
- Authorization mode: boundary
- Authorization source: HUMAN LEAD 2026-10-18 trả lời “duyệt” phương án TC-WEB1/G1–G5 và yêu cầu Claude Code làm tiếp, Codex làm reviewer. Authorize implementation theo contract này và preview sandbox cô lập; không authorize production deployment/integration.
- Parallel group: —
- Owned paths: `src/auto_short/web/theme_index.py`, `src/auto_short/web/app.py` (chỉ wiring), `src/auto_short/web/static/theme_index.html`, `src/auto_short/web/static/theme_index.js`, `tests/test_web_theme_index.py`, `scripts/theme_index_preview_fixture.py`, contract này. Layout static đã đối chiếu; không tự mở rộng ownership.
- Dependencies: TC1 READY tại `483a2923c13fbdd648336f7e19106beb96be97b0`; chưa integrated. Không dependency thư viện mới.
- Base commit / branch: base `483a2923c13fbdd648336f7e19106beb96be97b0`; branch `feature/tc-web1-theme-index-preview` và worktree `/tmp/youtube-auto-short-tc-web1` đã tạo.
- Human Lead approval: accepted G1–G5 theo recommended options, 2026-10-18; accepted đổi Implementer sang Claude Code, Codex reviewer
- Implementation authorized: YES
- Direct invocation approval: HUMAN LEAD 2026-10-18 yêu cầu Codex ORCHESTRATOR giao trực tiếp cho Claude Code (Sonnet 5.5, main session làm IMPLEMENTER, không delegate/spawn) trong worktree `/tmp/youtube-auto-short-tc-web1`, branch `feature/tc-web1-theme-index-preview`, base `483a2923c13fbdd648336f7e19106beb96be97b0` (xác minh `git log -1` trước khi sửa; worktree sạch trừ contract untracked).

Lifecycle boundary: `DRAFT → IN_PROGRESS → READY`. Hiện READY: source/automated review ACCEPTED; HUMAN LEAD xác nhận manual test thành công ngày 2026-10-18. Chưa integrated. Một writer: Claude Code viết source/tests và sửa review findings; Codex review độc lập. Lượt planning trước chỉ ORCHESTRATOR viết contract, native worker audit read-only. Push/PR/merge và chạy trên web hiện hành có integration/deployment gate riêng.

## Goal

HUMAN LEAD mở một web preview cô lập để kiểm tra kết quả TC1: favorite nào eligible/ineligible, metadata extractive, evidence, provenance, uncertainty và cache còn hợp lệ hay không. Không tạo/cắt/render/download clip, không gọi AI thật.

## Scope

- In scope: một trang xem cho đúng một playlist được chọn, một GET API read-only; seed dataset synthetic và cache giả lập trong scratch bằng TC1 thật với fake client; kiểm thử invalidation bằng thay đổi fixture rồi refresh trang.
- Out of scope: semantic thematic search/ranking, chọn clip để ghép, TC2/TC3 implementation, sửa metadata/approval/favorites/review, job/queue mới, build index production, AI thật, media playback synthetic, route tải media, publish, dependency, framework/accepted decisions, restart hoặc deploy web đang chạy.
- Không thay module TC1 để nới eligibility, chấp nhận nguồn thiếu hoặc transcript ngoài final ranges. Nếu adapter không đủ dùng callable hiện tại thì quay lại gate, không tự refactor core.

## Authority / key decisions

- Workflow v4.4 §3–8, project-profile §2/§5/§7 và `docs/tasks/TC1-theme-index.md` là authority liên quan. Web auth hiện hành: `docs/decisions/CP8.3-web-contract.md` W2; source/tests là implementation state.
- TC1 chỉ callable: `audit_playlist` read-only/no AI; `build_index` re-audit, validate fingerprint và cached metadata, mặc định có thể gọi Ollama và ghi `theme_index.json`. Web preview không được dùng các defaults đó.
- Repository không có contract/accepted scope riêng TC2 hoặc TC3 qua tìm kiếm `TC2|TC3|TC1|theme.index|thematic` trong `docs/` và `adapters/`. TC1 Result chỉ có “Proposed TC2”; không suy từ tên hoặc từ tham chiếu boundary TC1–TC3 rằng web này đã được duyệt. Đề xuất task riêng TC-WEB1; chỉ đổi thành TC2 nếu HUMAN LEAD xác nhận scope và authority cụ thể.
- Thiết kế/AC dưới đây đã được HUMAN LEAD duyệt ở cấp task ngày 2026-10-18; chưa phải implementation hiện có. Không sửa accepted decision records/framework trong scope này.

### Snapshot xác minh 2026-10-18

- TC1 branch `feature/tc1-theme-index`, HEAD `483a2923c13fbdd648336f7e19106beb96be97b0`; merge-base với base được cung cấp = `bec36c02c7b38e92e2646a50f16349d6405d94b9`.
- `git ls-remote origin refs/heads/main` và local `origin/main` cùng `bec36c02c7b38e92e2646a50f16349d6405d94b9`. Local checkout `main` và web worktree detached ở `ad59dfea9e157620a25fafac98033882bcf456d0`. Đây là divergence về refs đã quan sát, chưa phân tích quan hệ commits; không tự fetch/reset/rebase/integrate. G5 đã duyệt base TC1 SHA nêu trên; trước implementation chỉ xác minh lại, không tự đổi base theo remote main.
- `git worktree list --porcelain`: 10 worktrees; `git status --short --untracked-files=all` ở cả 10 không có output trước khi tạo DRAFT. Chỉ contract mới này được thêm trong TC1 worktree, không ghi đè file cũ.
- TC1 contract ghi verification lịch sử: 1963 passed, 1 skipped; checker PASS. Không coi đó là rerun của session planning này.
- Audit thật đã ghi trong TC1: playlist `PLOynZc0cJJfA3FSfw_GxZ7uG2cGdDwRR_`, 0 eligible / 2 ineligible: `yZai50V4p44.kt/k02` mất original source; `k03` duration ngoài 300–420 s. Không rerun audit hoặc ghi index production trong lượt planning này.

### Decision gates — HUMAN LEAD đã duyệt 2026-10-18

| Gate | Issue / evidence → impact | Options / recommendation | Decision |
|---|---|---|---|
| G1 Scope và quan hệ TC2 | TC1 loại trừ UI/API; không có contract TC2/TC3 → không được kế thừa authorization theo tên | Khuyến nghị TC-WEB1 riêng, chỉ preview TC1. Hoặc HUMAN LEAD cung cấp/chốt TC2 boundary rồi đổi contract trước code | ACCEPTED — recommended option |
| G2 HTTP/API + security boundary | Thêm route mới → S2/public HTTP API gate dù tái dùng auth | Duyệt chính xác 2 GET routes, response/error/side effects dưới đây; dùng auth hiện có, không public exemption; không API generation | ACCEPTED — recommended option |
| G3 Dataset và giới hạn đánh giá | Playlist thật 0 eligible; fake fixture không phải video → chưa kiểm semantic/playback thật | Khuyến nghị synthetic scratch + fake metadata có nhãn rõ. Tùy chọn sau: HUMAN LEAD chọn dữ liệu eligible đã tồn tại để audit read-only; AI thật hoặc phục hồi nguồn cần scope riêng | ACCEPTED — recommended option |
| G4 Runtime và cách kiểm cache | Startup web có restore queue, auto-archive và HD callbacks; TC1 hash toàn bộ source/render → không dùng production config hay poll tự động | Config/work/output/input scratch riêng, preview loopback cổng rảnh (đề xuất 8081), refresh thủ công; cache chỉ seed offline trong scratch; request luôn write=False + no-network client | ACCEPTED — recommended option |
| G5 Base/integration | Remote main khác local main; TC1 chưa push/PR/merge → preview không tự giải quyết integration | Khuyến nghị nhánh/worktree mới từ TC1 SHA sau recheck; nếu chọn base khác phải review lại compatibility và contract. Không push/PR/merge/deploy ở task planning | ACCEPTED — recommended option |

Không gate dependency/DB mới vì đề xuất không thêm chúng. Security model giữ nguyên nhưng route/data exposure mới phải duyệt ở G2. G1–G5 được duyệt theo recommended options trong câu trả lời “duyệt”; approval implementation không đồng nghĩa approval deploy production. Nếu evidence mới đòi mở boundary, quay lại HUMAN LEAD.

## Implementation approach

### UI và HTTP contract tối thiểu (APPROVED cho task)

1. `GET /playlists/{playlist_id}/theme-index`: trang riêng, truy cập bằng URL trực tiếp để tránh sửa navigation hiện hành. Một nút “Kiểm tra lại” gọi GET API; không auto-poll vì audit hash media đầy đủ.
2. `GET /api/playlists/{playlist_id}/theme-index`: trả JSON schema envelope version 1 gồm `playlist_id`, `checked_at`, `data_mode` (`synthetic_preview` trong sandbox), `generation_enabled: false`, counts theo status và toàn bộ `records` của kết quả kiểm lại. Không drop invalid favorite. Response `Cache-Control: no-store`; lỗi playlist artifact không được biểu diễn thành danh sách rỗng thành công.
3. Page/API đi qua auth middleware hiện có: chưa đăng nhập page redirect login, API 401; invalid/missing playlist 404; playlist/favorites artifact malformed 422 với thông báo an toàn, không stack trace. Text hiển thị bằng escaping/textContent; không trả arbitrary files hoặc thêm public path.
4. Adapter gọi `build_index(config, pid, write=False, client=<no-network client>)`. Client này luôn raise `ChatError` với reason cố định khi TC1 cần generation; không default/fallback Ollama, không fake generation trên GET. Cache hit vẫn phải đi qua TC1 audit/fingerprint/validate_metadata; không lấy raw cache làm authority. TC1 cache miss/invalid tạo `ai_error` cùng reason generation-disabled, UI giữ status này và giải thích “chưa có index hợp lệ; preview không sinh metadata”. Không tuyên bố AI thật đã lỗi/chạy khi nó chưa chạy.
5. UI giữ identity/favorite position, status/reason TC1 (không gộp thành “không có clip”), duration khi có; metadata topic/subtopic/synopsis/key_messages; evidence ID/text/timestamps, final_segments, source reference/hash, input_fingerprint, provenance model/options/think/prompt/hash/method, indexed_at, cached và uncertainty cả record lẫn metadata. Có thể thu gọn phần chi tiết nhưng không loại bỏ dữ liệu. Absent fields ghi “không có”; không tự suy luận duration/source ranges cho ineligible records.
6. Source path có thể chứa absolute server path trong TC1. HTTP view chỉ trả reference tương đối trong scratch được phép + hashes; không trả absolute path hoặc đường dẫn ra ngoài roots, không sửa artifact TC1 để đạt điều đó. Reason giữ thông tin eligibility, redact phần absolute path nếu có và giải thích đã ẩn đường dẫn. Không giấu uncertainty hoặc biến metadata synthetic thành kết luận semantic.
7. Không lưu semantic approval. Mỗi trang có nhãn “Dữ liệu kiểm thử tổng hợp; metadata giả lập; chưa đánh giá độ đúng chủ đề của AI thật”. Unheart/reject/source/cut/render/transcript thay đổi phải loại cache cũ khỏi kết quả usable ở lần kiểm tra tiếp; dữ liệu trang là snapshot tại `checked_at`, không bảo đảm freshness khi inputs đang bị sửa đồng thời. Chỉ dùng sandbox tĩnh/quiescent; live concurrent input support nằm ngoài scope.

### Dữ liệu eligible và vận hành sandbox

- Fixture tool tạo dataset artifact mới chỉ dưới scratch root được chỉ định, không overwrite root không rỗng; seed TC1 bằng deterministic fake client, lưu cache bằng cơ chế hiện có trong scratch. Không tạo media thật: byte sentinel giống fixture `tests/test_theme_index.py`, liên kết/hash đủ để kiểm TC1 nhưng không phải video playable. Không thêm nút play/download.
- Có ít nhất một eligible 350 s, ineligible mất source/duration/kept-only/rejected, empty favorites, boundary-crossing transcript với uncertainty, malformed metadata/cache và fake AI error. Boundary 299/300/420/421 được kiểm automated. Mỗi mutation scenario chạy trên dataset riêng hoặc reset scratch có kiểm soát, không sửa dataset thật.
- Cache-hit baseline seed bằng fake với provenance model test rõ ràng. Cache-miss dùng fixture chưa seed hoặc thay input; refresh chỉ trả trạng thái TC1 no-generation. Muốn reseed phải chạy fixture tool offline trong scratch, không có HTTP write endpoint.
- Playlist thật 0 eligible chỉ là negative control theo audit đã ghi; không sửa favorite/duration hay bỏ nguồn để ép eligible. Sau này nếu cần dữ liệu thật: HUMAN LEAD chọn favorite có original source/render/transcript còn tồn tại, đúng playlist, duration 300–420 và không rejected; audit read-only trước, dừng nếu không đủ. Không cần tạo clip mới cho lượt này.
- Preview dùng config scratch riêng, mọi path ghi/đọc và queue/secret/log chỉ trong scratch; không dùng config production, không hardlink các artifact có thể mutate, không reuse queue/enhance credentials production. Kiểm startup side effects trước chạy; `auto_archive_interval=0` hiện vẫn có startup archive nên không phải isolation control. Không start server ở planning session. Lần chạy sandbox sau authorization cần launch recipe cụ thể với network/AI callbacks bị chặn, không chỉ dựa vào việc sửa endpoint Ollama.

## Acceptance Criteria

1. G1–G5 có HUMAN LEAD decision, base/owned paths/authorization được chốt trước implementation; không thay accepted decisions/framework/TC1 eligibility, không ghi production hay tác động server hiện hành.
2. Trang/API được bảo vệ bằng auth hiện có, validate PID/artifacts, escape dữ liệu; không lộ absolute path hoặc arbitrary filesystem access; response và errors đúng HTTP proposal.
3. Mỗi favorite có record và reason/status đầy đủ; empty/0 eligible, kept-only và invalid favorite không bị ẩn. Không thêm field được suy đoán như thể TC1 đã cung cấp.
4. Eligible/indexed hiện đầy đủ metadata, evidence trong final ranges, provenance/fingerprint/timestamp/cache state và cả hai nguồn uncertainty; synthetic nhãn rõ, không playback/semantic approval claim.
5. Mọi GET không AI/network, không ghi index/favorites/review/publish/media hoặc enqueue job; malformed/stale/missing cache không trả metadata cũ như current. Cache-hit phải validate lại bằng TC1; miss có `ai_error` generation-disabled rõ ràng.
6. Fixture đủ eligible/ineligible, fake metadata/cache; source/render/cut/transcript/model/prompt/options/favorites/rejection changes chứng minh invalidation hoặc ineligibility, không có stale usable record; unheart xóa khỏi current records, watched không cấp approval.
7. Sandbox startup và request không chạm production, không gọi download/ffmpeg/Ollama/monitor network, không restore queue thật; mọi test/preview dùng scratch độc lập. Manual desktop/mobile đạt trước integration vì có HTTP API mới.
8. Required verification PASS, Claude Code bàn giao, Codex review độc lập ACCEPTED trước READY. Không push/PR/merge/deploy nếu chưa có authorization riêng.

## Required verification

Lệnh sau là required verification của task implementation, chưa được chạy trong planning. Dùng conda Python, `PYTHONPATH=<new-worktree>/src`; tên file/path phải được chốt ở G5.

- `env PYTHONPATH=<new-worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_index.py tests/test_web_theme_index.py -x --tb=short` — AC2–7, fake/no-network; tests web fixture/cache/auth/errors/escaping/path projection và GET side effects. Chốt danh sách regression web/auth/compilation từ source trước implement.
- Invalidation matrix: source bytes, render bytes/manifest, manual cut, transcript content/linkage, model/options/think, prompt/schema, corrupt cache/timestamp, removal/rejection/unheart. Kiểm hit không gọi client; miss gọi refusing client, không chạm network, không lộ stale metadata. FS before/after snapshot của GET và spy runner; filesystem canary ngoài scratch + startup callback spies chứng minh isolation (AC5–7).
- `env PYTHONPATH=<new-worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -n auto` — full suite trước READY và sau vòng fix review theo project test policy. Slow suite chỉ khi scope thực tế chạm render/worker; scope hiện tại không chạm.
- `node scripts/framework-check.mjs`; `git diff --check`; tracked/untracked inventory + diff review owned paths. ORCHESTRATOR chạy lại required verification độc lập theo adapter; không dùng TC1 historical suite thay thế.
- Browser thật trên scratch server: desktop/mobile, login, refresh hit/miss/0 eligible, expand evidence/provenance/uncertainty và confirm no playback/no stale result. Ghi environment, thao tác, kết quả; không có browser thì ghi NOT RUN và giữ manual gate mở.

Tất cả required verification phải chạy và PASS trước READY; không claim PASS cho implementation chưa được authorize.

## Manual test checklist (Tech Lead)

Không database mới; giữ security model hiện có, thêm HTTP API contract → manual gate trước integration.

- [x] HUMAN LEAD xác nhận preview LAN test thành công ngày 2026-10-18; chấp nhận manual gate. Các scenario bên dưới là checklist tham chiếu, chưa có báo cáo riêng từng mục/thiết bị; không đánh dấu thay HUMAN LEAD.

- [x] HUMAN LEAD duyệt G1–G5 và scope task riêng ngày 2026-10-18.
- [ ] Xác nhận URL/scratch launch recipe bằng evidence sau implementation.
- [ ] Login desktop/mobile; nhìn rõ nhãn synthetic và không có action tạo media/AI.
- [ ] Eligible 350 s hiển thị extractive evidence đúng final ranges, uncertainty ở đoạn crossing, provenance/fingerprint/cache hit.
- [ ] Refresh sau mutation thấy ineligible/ai_error generation-disabled hoặc record removed, không thấy metadata cache cũ usable.
- [ ] 0 eligible hiển thị reasons, phân biệt với empty favorites và lỗi artifact.
- [ ] Confirm sandbox không tác động production/server/queue; nếu muốn semantic review dữ liệu thật thì mở decision riêng.

## Result

- Main changes (implementation, 2026-10-18): `src/auto_short/web/theme_index.py` (2 GET routes, `RefusingClient`, projection/redaction), wiring 3 dòng trong `web/app.py`, `static/theme_index.html|js` (textContent, chỉ GET, không video/download), `scripts/theme_index_preview_fixture.py` (seed offline + launcher sandbox), `tests/test_web_theme_index.py` (43 test mới). Không đụng module TC1, framework, dependency.
- HTTP: `GET /playlists/{pid}/theme-index` (HTML, no-cache) và `GET /api/playlists/{pid}/theme-index` (JSON envelope v1, `no-store`); auth middleware hiện có (page 303 login, API 401); pid sai/không có 404; playlist hoặc favorites artifact hỏng 422 thông báo cố định. Mỗi request gọi `build_index(write=False, client=RefusingClient())`; cache hit được TC1 validate lại, miss/invalid → `ai_error` với reason `generation-disabled…`. `source_reference.path` bị thay bằng `reference` tương đối (hoặc `[đã ẩn đường dẫn]`, `path_hidden`); `reason`/`favorite` redact đường dẫn tuyệt đối; evidence/metadata giữ nguyên. `data_mode` = `synthetic_preview` khi workspace có marker `.theme_index_preview.json` (do seed tool tạo), ngược lại `unmarked`.
- Launch recipe (sandbox, loopback, chỉ scratch):
  1. `env PYTHONPATH=/tmp/youtube-auto-short-tc-web1/src /home/ntnghia/miniconda3/envs/auto-short/bin/python scripts/theme_index_preview_fixture.py seed /tmp/tc-web1-scratch` (root phải rỗng/chưa có; ghi `config.toml` với workspace/output/queue/secret dưới root; seed bằng TC1 thật + fake client).
  2. `env PYTHONPATH=/tmp/youtube-auto-short-tc-web1/src AUTO_SHORT_WEB_PASSWORD=<mật khẩu thử> /home/ntnghia/miniconda3/envs/auto-short/bin/python scripts/theme_index_preview_fixture.py serve /tmp/tc-web1-scratch --port 8081`; mở `http://127.0.0.1:8081/playlists/PLeligible/theme-index`.
  Playlist: `PLeligible` (hit), `PLmissingcache` (miss), `PLmixedcases` (7 favorites: eligible, mất nguồn, duration 190, rejected, không phải khai thị, kept-only, favorite hỏng), `PLemptyfavs`, `PLmalformed` (422), `PLcorruptcache`. Launcher `assert_sandbox` từ chối root thiếu marker, path ngoài root, host khác 127.0.0.1; `build_app` thay mọi callable dịch vụ (pipeline/render/lister/titler/post/doc/vertical/ollama_ps/preflight) bằng stub từ chối, tắt auto_archive, enhance tokens rỗng, monitor interval 3600 s. Reseed = xoá scratch rồi seed lại (không có HTTP write).
- Tests (2026-10-18, conda Python, `PYTHONPATH=/tmp/youtube-auto-short-tc-web1/src`):
  - `pytest -q tests/test_theme_index.py tests/test_web_theme_index.py -x --tb=short` → 74 passed (31 TC1 + 43 mới), exit 0, sau vòng fix review 1. Gồm invalidation matrix, boundary 299/300/420/421, snapshot GET, redaction đệ quy (favorite lồng / không hợp lệ), page 404/422, allowlist sandbox + canary, và Node harness UI (success → fail không giữ dữ liệu cũ).
  - `pytest -q -n auto` → 2006 passed, 1 skipped, exit 0 (sau vòng fix review 1).
  - `node scripts/framework-check.mjs` → PASS, exit 0; `git diff --check` → exit 0.
  - Smoke thật (không phải browser): server scratch cổng 8099, curl: page chưa login 303, login 200, API JSON `PLeligible` indexed, page 200; đã dừng server, cổng đóng. Không động 8080/production.
- Manual browser acceptance (HUMAN LEAD, 2026-10-18): sau khi mở preview qua LAN, HUMAN LEAD xác nhận “ok da test thanh cong”. Manual gate ACCEPTED theo xác nhận này; agent không tự chạy browser. Thiết bị/browser và kết quả từng thao tác không được báo riêng, không suy đoán đã kiểm riêng cả desktop lẫn mobile.
- Files: modified `src/auto_short/web/app.py`; new `src/auto_short/web/theme_index.py`, `src/auto_short/web/static/theme_index.html`, `src/auto_short/web/static/theme_index.js`, `scripts/theme_index_preview_fixture.py`, `tests/test_web_theme_index.py`; contract (untracked, giữ). Chưa commit.
- Limitations: startup web vẫn chạy lifespan thật (runner/lanes/sampler) nhưng toàn bộ dưới scratch + stub; `PLAYLIST_ID_RE` đòi id ≥ 10 ký tự nên id synthetic dài; synthetic eligible chỉ kiểm plumbing, không chứng minh đúng chủ đề AI thật hay playback; audit hash cả file nên không auto-poll; `data_mode` dựa vào marker file trong workspace; `[post]` image_dir/corrections đã được override vào scratch sau review R2. Allowlist không có route trang chủ `/`; mở trực tiếp URL theme-index.
- Review vòng 1 (Codex REQUEST CHANGES) đã sửa: R1 redact đệ quy mọi field trừ `evidence`/`metadata` (kể cả key, `identity`, `inputs`, `favorite`); R2 `[post] image_dir`/`corrections_path` override vào scratch, `assert_sandbox` kiểm chúng + auto_archive/enhance tắt, launcher bọc `Allowlist` (chỉ login/logout, 2 route theme, `style.css`, `theme_index.js`; còn lại 404 trước app/auth); R3 page dùng cùng validation 404/422; R4 JS xoá snapshot cũ ngay khi kiểm tra lại và khi lỗi. Giới hạn launch: allowlist chỉ có trong launcher fixture, không đổi app; `create_app` vẫn tạo các route khác nhưng không tới được qua launcher; lifespan vẫn chạy runner/lanes/sampler trên scratch.
- Review (Codex độc lập, 2026-10-18): source/automated review ACCEPTED sau một vòng sửa R1–R4, không còn blocking code finding. Đọc contract → diff tracked + toàn bộ source/tests mới → AC → verification; không sửa source/tests của IMPLEMENTER. Sau đó HUMAN LEAD xác nhận test preview qua LAN thành công ngày 2026-10-18; manual gate ACCEPTED, task READY, chưa integrated. Agent không có browser và không tự claim browser verification.
- Verification (Codex độc lập, 2026-10-18): `env PYTHONPATH=/tmp/youtube-auto-short-tc-web1/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_index.py tests/test_web_theme_index.py tests/test_web_auth.py tests/test_web_compilation.py -x --tb=short` → 99 passed, 1 warning, 34.23 s, exit 0. Cùng prefix `-m pytest -q -n auto` → 2006 passed, 1 skipped, 1116 warnings, 91.06 s, exit 0. `node scripts/framework-check.mjs` PASS exit 0; `git diff --check` exit 0; kiểm trailing whitespace của cả các file untracked source/tests/static không có lỗi; inventory đúng 7 owned paths (app.py + 6 files mới gồm contract).
- Native/CLI execution evidence: planning native worker chỉ audit; implementation dùng Claude Code CLI 2.1.302, adapter `--agent implementer` chọn `claude-sonnet-5-5`, session `bbd520ac-fd61-4799-8eda-b6d3f707c9df`. Codex giao trực tiếp theo HUMAN LEAD, resume cùng session cho vòng fix để dùng lại context; chỉ Claude viết source/tests, không spawn thêm agent, không permission denial. Không suy model từ transcript; model/session lấy từ runtime init JSON.
- Preview runtime (Codex, sau review): launcher đã chạy trong tmux `tc-web1-preview`, loopback `127.0.0.1:8099` (8081 đã có listener nên không dùng). Scratch mới `/tmp/tc-web1-human-preview-tqmanfv4`, password thử riêng ở `.preview-password` (mode 600), log `server.log`; không chứa password trong Git hoặc contract. URL `http://127.0.0.1:8099/playlists/PLeligible/theme-index`. Nếu truy cập từ máy khác cần SSH tunnel tới loopback này; chưa mở LAN/production. Dừng bằng `tmux kill-session -t tc-web1-preview` (chỉ session thử này).
- Smoke runtime Codex (HTTP thật, không browser): page chưa login303/API401; login200; page/JS200; cache hit indexed1; miss/corrupt ai_error1; mixed indexed1 + ineligible6; empty records0; malformed422; missing page/API404; POST post-corrections và GET jobs404 trước handler. PASS exit 0. Web worktree production vẫn sạch, không restart/deploy server hiện hành. Last recheck remote main vẫn bec36c0, preview HEAD vẫn TC1 SHA; không tự đồng bộ refs.
- PR: integration đã được HUMAN LEAD authorize bằng “cho phep het” ngày 2026-10-18; kết quả PR/merge/deploy ghi ở phần Integration sau khi thực hiện.

## Handoff cho Claude Code (HUMAN LEAD đã duyệt)

```text
Bạn là Claude Code IMPLEMENTER duy nhất cho TC-WEB1; Codex là ORCHESTRATOR/reviewer độc lập.
Bootstrap tối thiểu từ repository; contract hiện hành ở /tmp/youtube-auto-short-tc-web1/docs/tasks/TC-WEB1-theme-index-preview.md.
G1–G5 và đổi binding đã được HUMAN LEAD duyệt, Implementation authorized YES; không xin duyệt lại.
Base 483a2923c13fbdd648336f7e19106beb96be97b0 đã xác minh; giữ file contract untracked.
Branch/worktree đã tạo (`feature/tc-web1-theme-index-preview`, `/tmp/youtube-auto-short-tc-web1`); contract đã ở đó, trạng thái IN_PROGRESS.
Đọc TC1 source/tests và web auth/startup liên quan; dùng lại audit trong contract, không audit rộng hoặc delegate thêm.
Source/automated review đã ACCEPTED, 2006 passed/1 skipped; không implement thêm khi không có finding mới.
Task READY sau manual acceptance; integration đã được authorize, không implement behavior mới.
Commit/push/PR/merge/deploy đã được authorize riêng; giữ scope và verification evidence hiện có.
```

### Runtime access amendment — HUMAN LEAD 2026-10-18

HUMAN LEAD báo không truy cập được từ LAN tại `10.8.102.102:8099`; yêu cầu này authorize mở LAN cho preview sandbox hiện có. Codex đổi duy nhất launcher runtime trong scratch sang bind `10.8.102.102:8099`, giữ auth/password và route allowlist. Không sửa source/tests, config/launcher mặc định repository vẫn loopback, không thay web production. URL manual test mới: `http://10.8.102.102:8099/playlists/PLeligible/theme-index`. Evidence kiểm tra LAN ghi sau thao tác.

Runtime amendment verification: HTTP trực tiếp tới địa chỉ LAN trên máy server PASS (page chưa login303, API401, login200, page200, indexed1, write route404); chưa kiểm kết nối từ thiết bị LAN khác. Chỉ restart tmux preview; source/tests không đổi.

### Final acceptance — 2026-10-18

HUMAN LEAD: “ok da test thanh cong” sau khi truy cập preview LAN. TC-WEB1 READY: automated verification 2006 passed / 1 skipped, code review ACCEPTED, manual acceptance recorded. Không commit/push/PR/merge hoặc deployment production được authorize trong xác nhận này. Preview sandbox tiếp tục chạy để review; không tự dọn artifacts.

### Integration authorization — HUMAN LEAD 2026-10-18

Sau khi Codex nêu rõ còn commit/push/PR/merge và cập nhật web production, HUMAN LEAD trả lời “cho phep het”. Đây là authorization riêng cho commit, push, PR, merge TC-WEB1 cùng prerequisite TC1 đã READY và rollout code merged lên web production hiện có. Không authorize thêm behavior, gọi AI thật, tạo media hoặc seed synthetic vào production. Codex thực hiện integration/review/deployment; Claude vẫn là writer source/tests.

Integration plan: một PR chứa commit TC1 đã review và commit TC-WEB1; giữ main không force-push, merge sau checks. Deploy từ merged main khi các làn đang rảnh; giữ mật khẩu/tokens hiện hành và 9 parked-HD jobs qua queue persistence. Local main ad59dfe là ancestor của origin/main bec36c0 (0 local-only / 8 remote-only commits), không có divergence conflict. Preview LAN 8099 tiếp tục riêng. Ghi kết quả deployment và operational current-state sau rollout; không mô tả deployment như đã hoàn tất trước khi kiểm tra.
