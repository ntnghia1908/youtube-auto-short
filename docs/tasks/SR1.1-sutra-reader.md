# Task: SR1.1 — Trang Đọc Kinh: thư viện, đọc, đếm biến

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Human Lead: HUMAN LEAD
- Base commit / branch: `6c36861` / `feature/sr1-sutra-reader`
- Human Lead approval: accepted 2026-10-12 (SR1.1–SR1.3, làm lần lượt, một PR); manual test HUMAN LEAD gộp sau SR1.3
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: ứng dụng mới trong host (namespace `work/_sutras/`, route / API mới, schema mới). Không thêm dependency.

## Goal

Đăng nhập web → mục "Đọc Kinh" trên thanh trên cùng → thư viện các bộ kinh trong `work/_sutras/` → đọc trên điện thoại với cỡ chữ / nền / kiểu chữ / giãn dòng chỉnh được, mục lục theo nhóm, mở lại đúng chỗ đang đọc, màn hình không tự tắt khi đọc, ghi "Tụng xong (+1 biến)" và xem lịch sử.

## Scope

- In scope:
  - `src/auto_short/sutra/`: `__init__.py`, `markup.py` (parse S2 → S3, lỗi có số dòng), `store.py` (S4: list / get / text / create / update / delete + slug + đếm biến + hoàn tác; `create` / `update` / `delete` dùng ở SR1.2 nhưng viết + test ở đây vì là một module), `web.py` (router: route trang + API đọc / đếm của S6: `GET /api/sutras`, `GET /api/sutras/{slug}`, `GET /api/sutras/{slug}/text`, `POST …/recitations`, `DELETE …/recitations/last`).
  - `web/app.py`: `include_router`; topnav "Đọc Kinh" trên mọi trang tĩnh hiện có (`index`, `episode`, `playlist`, `posts`, `monitor`, `storage`).
  - Static: `sutras.html`, `sutra.html`, `sutra.js`, `sutra.css`, `sutra-awake.mp4` (S7, S8).
  - Tests mới; pointer trong `docs/ai/project-profile.md` (authority + module map).
- Out of scope: import / thêm / sửa / xóa qua web (SR1.2); mọi mục "Ngoài scope SR1" của decision record; sửa `app.js`, logic Auto Short / learning.

## Authority / key decisions

- `docs/decisions/SR1-sutra-reader-contract.md` S1–S4, S6 (phần đọc / đếm), S7, S8.
- `docs/decisions/CL1-chinese-learning-contract.md` C1 (quy ước host / app); `docs/decisions/CP8.3-web-contract.md` W2.

## Implementation approach

- `markup.parse(text) -> Sutra | raises MarkupError(errors=[(line, message)])`; hàm thuần, dataclass + `to_json()`.
- `SutraStore(root: Path)` (root = `<workspace.dir>/_sutras`), khóa theo slug, `clock` tiêm được cho test.
- Router dựng bằng hàm `router(store, static_dir) -> APIRouter`; host truyền store từ `config.workspace.dir`.
- `sutra-awake.mp4`: `ffmpeg -f lavfi -i color=c=black:s=16x16:r=1 -f lavfi -i anullsrc=r=8000:cl=mono -t 2 -c:v libx264 -pix_fmt yuv420p -c:a aac -b:a 8k -movflags +faststart sutra-awake.mp4` (ghi lệnh vào comment `sutra.js`).
- Nạp 3 bộ đầu cho manual test: file S2 do ORCHESTRATOR chuyển từ PDF bằng prototype S5a + soát tay, nạp vào `work/_sutras/<slug>/` bằng một script nhỏ dùng `SutraStore.create` (không commit nội dung).

## Acceptance Criteria

1. `markup.parse` đúng S2 / S3: `=`, `~`, `@`, `#`, đoạn, `inst`, `han`, `[^n]`, `\` escape; mọi lỗi S2 trả đủ kèm số dòng; văn bản > 2 MB bị từ chối.
2. `SutraStore`: slug bỏ dấu + chống trùng; slug sai regex / symlink / ngoài root bị từ chối; ghi atomic; `recitations` +1 / hoàn tác / 409 khi rỗng; xóa chỉ con trực tiếp của root.
3. API S6 phần đọc / đếm đúng mã trạng thái (200 / 404 / 409); chưa đăng nhập → 401 (API) / 303 login (trang).
4. Mọi trang tĩnh có mục "Đọc Kinh"; thanh "Short | Khai thị | Bài đăng" của trang video không đổi.
5. Trang đọc: cài đặt S7 đổi được và được nhớ; mục lục nhảy đúng mục; mở lại về vị trí đã lưu; "Tụng xong" + hoàn tác + lịch sử theo ngày; dùng `textContent`, không `innerHTML` với dữ liệu kinh.
6. Không đổi behavior Auto Short / learning: toàn bộ test hiện có PASS không sửa.

## Required verification

- `python -m pytest -q -n auto` — AC 1–4, 6.
- `node scripts/framework-check.mjs`.
- Manual test (dưới) — AC 4, 5, S8.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Thêm route / API mới sau auth hiện có (không đổi security model, không public API ngoài web). Manual test sau automated verification, trên 8080 ghim commit của branch, bằng điện thoại.

- [x] Topbar "Đọc Kinh" → thư viện có 3 bộ.
- [x] Đọc A Di Đà: đổi cỡ chữ, nền Tối / Giấy, kiểu chữ, giãn dòng; mục lục nhảy "Chính kinh".
- [x] Thoát trình duyệt, mở lại → đúng chỗ; thư viện "Đọc tiếp".
- [x] Để yên quá thời gian tự tắt màn hình → màn hình vẫn sáng (ghi trình duyệt / hệ điều hành).
- [x] Thái Thượng: dòng chữ Hán hiển thị đúng font, chạm chú thích hiện nội dung.
- [x] "Tụng xong" → số biến tăng, hoàn tác được, lịch sử đúng ngày.

## Result

- Manual test: HUMAN LEAD 2026-10-12 trên điện thoại (8080) — OK (SR1.4: lỗi khung trắng ở chế độ lật trang đã sửa `a8f8c07` rồi thử lại OK).

- Main changes: `src/auto_short/sutra/` (`markup.py` parse S2 -> S3, mọi lỗi kèm số dòng; `store.py` S4 gồm create / update (sha256) / delete / đếm biến + hoàn tác; `web.py` router trang + API đọc / đếm); `web/app.py` chỉ `include_router`; mục "Đọc Kinh" ở topnav 6 trang tĩnh; static `sutras.html`, `sutra.html`, `sutra.js`, `sutra.css`, `sutra-awake.mp4`; `.gitignore` thêm ngoại lệ `!…/sutra-awake.mp4` (vì `*.mp4` bị ignore).
- Tests: `tests/test_sutra_markup.py`, `tests/test_sutra_store.py`, `tests/test_web_sutra_sr11.py` (full suite 1648 passed, 1 skipped).
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
