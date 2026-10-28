"""HD1a: backup confirmation by sha256 (G1), release (G2), released state (G3), script generator (G6)."""

import hashlib
import importlib.util
import json
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from auto_short import khaithi  # noqa: E402
from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.enhance import state as st  # noqa: E402
from auto_short.khaithi import KhaiThi  # noqa: E402
from auto_short.render import full  # noqa: E402
from auto_short.render.stage import RenderError, run_render  # noqa: E402
from auto_short.review import backup  # noqa: E402
from auto_short.web import episodes as ep  # noqa: E402

from web_helpers import login, web_client as client, write_episode  # noqa: E402

VID = "aaaaaaaaaa1"
KT = VID + ".kt"
HD = bytes(range(256)) * 40
VERT = b"vertical" * 300
HD_SHA = hashlib.sha256(HD).hexdigest()
V_SHA = hashlib.sha256(VERT).hexdigest()
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output", preset="ultrafast", threads=2))


def wsdir(cfg, eid=VID) -> Path:
    return Path(cfg.workspace.dir) / eid


def make_ep(cfg, *, kt=False, hd=True, vertical=True, data=HD, vdata=VERT):
    write_episode(cfg, VID, clips=("k01",))
    if kt:
        write_episode(cfg, KT, clips=("k01",))
        khaithi.write(wsdir(cfg, KT), KhaiThi(VID, 4, 7))
    d = wsdir(cfg)
    if hd:
        (d / "source_hd.mp4").write_bytes(data)
        stt = (d / "source_hd.mp4").stat()
        doc = st.new_doc(VID)
        doc.update(wanted=True, state=st.DONE, source_hd_sha256=hashlib.sha256(data).hexdigest(),
                   source_hd_size=stt.st_size, source_hd_mtime_ns=stt.st_mtime_ns)
        st.write(d, doc)
        if kt:
            st.mirror(cfg, VID)
    if vertical:
        vd = full.vertical_dir(cfg, VID)
        vd.mkdir(parents=True, exist_ok=True)
        (vd / full.VIDEO_NAME).write_bytes(vdata)
        (vd / full.META_NAME).write_text(json.dumps({"plan_version": full.FULL_PLAN_VERSION, "hd_sha256": hashlib.sha256(data).hexdigest(),
                                                     "size": len(vdata), "key": "k"}), encoding="utf-8")
    for name, body in (("transcript.json", "{}"), ("clips.json", "{}"), ("titles.json", '{"header": {}}')):
        (d / name).write_text(body, encoding="utf-8")


def snapshot(cfg) -> dict[str, str]:
    """sha256 of every file except the HD / vertical files and the files release is meant to change."""
    skip = {"source_hd.mp4", "vertical.mp4", "enhance.json", "backup.json"}
    out = {}
    for base in (Path(cfg.workspace.dir), Path(cfg.render.output_dir)):
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.name not in skip:
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def confirm_both(c, eid=VID):
    assert c.post(f"/api/episodes/{eid}/backup", json={"kind": "hd", "sha256": HD_SHA}).status_code == 200
    assert c.post(f"/api/episodes/{eid}/backup", json={"kind": "vertical", "sha256": V_SHA}).status_code == 200


def logged(cfg):
    c = client(cfg)
    login(c)
    return c


# --- AC1: /backup ------------------------------------------------------------------------------------------------

def test_backup_accepts_only_current_sha(tcfg):
    make_ep(tcfg)
    c = logged(tcfg)
    r = c.post(f"/api/episodes/{VID}/backup", json={"kind": "hd", "sha256": HD_SHA})
    assert r.status_code == 200 and r.json()["confirmed"]["sha256"] == HD_SHA
    rec = json.loads((wsdir(tcfg) / "backup.json").read_text(encoding="utf-8"))
    assert rec["confirmed"]["hd"]["sha256"] == HD_SHA and rec["confirmed"]["hd"]["size"] == len(HD)
    assert rec["confirmed"]["hd"]["confirmed_at"]
    r = c.post(f"/api/episodes/{VID}/backup", json={"kind": "vertical", "sha256": V_SHA.upper()})
    assert r.status_code == 200
    assert json.loads((wsdir(tcfg) / "backup.json").read_text(encoding="utf-8"))["confirmed"]["vertical"]["sha256"] == V_SHA


def test_backup_rejects_wrong_sha_missing_file_unknown_id_without_writing(tcfg):
    make_ep(tcfg, vertical=False)
    c = logged(tcfg)
    for kind, sha in (("hd", "0" * 64), ("hd", "zz"), ("vertical", V_SHA)):
        r = c.post(f"/api/episodes/{VID}/backup", json={"kind": kind, "sha256": sha})
        assert r.status_code == 422, (kind, sha, r.text)
    assert not (wsdir(tcfg) / "backup.json").exists()
    assert c.post("/api/episodes/bbbbbbbbbb2/backup", json={"kind": "hd", "sha256": HD_SHA}).status_code == 404
    assert c.post("/api/episodes/x/backup", json={"kind": "hd", "sha256": HD_SHA}).status_code in (404, 422)
    assert c.post(f"/api/episodes/{VID}/backup", json={"kind": "other", "sha256": HD_SHA}).status_code == 422


def test_backup_hd_requires_size_match_and_done_state(tcfg):
    make_ep(tcfg)
    (wsdir(tcfg) / "source_hd.mp4").write_bytes(HD + b"x")  # file differs from enhance.json (size and sha)
    c = logged(tcfg)
    assert c.post(f"/api/episodes/{VID}/backup", json={"kind": "hd", "sha256": HD_SHA}).status_code == 422
    assert c.post(f"/api/episodes/{VID}/backup",
                  json={"kind": "hd", "sha256": hashlib.sha256(HD + b"x").hexdigest()}).status_code == 422
    assert not (wsdir(tcfg) / "backup.json").exists()


def test_vertical_sha_is_cached_by_size_and_mtime(tcfg, monkeypatch):
    make_ep(tcfg)
    calls = []
    real = backup.sha256_file
    monkeypatch.setattr(backup, "sha256_file", lambda p: (calls.append(p), real(p))[1])
    c = logged(tcfg)
    for _ in range(3):
        assert c.post(f"/api/episodes/{VID}/backup", json={"kind": "vertical", "sha256": V_SHA}).status_code == 200
    assert len(calls) == 1
    vp = full.vertical_path(tcfg, VID)
    vp.write_bytes(b"changed" * 100)  # new size -> hashed again, the old sha is refused
    assert c.post(f"/api/episodes/{VID}/backup", json={"kind": "vertical", "sha256": V_SHA}).status_code == 422
    assert len(calls) == 2


def test_khaithi_id_acts_on_its_video(tcfg):
    make_ep(tcfg, kt=True)
    c = logged(tcfg)
    assert c.post(f"/api/episodes/{KT}/backup", json={"kind": "hd", "sha256": HD_SHA}).status_code == 200
    assert (wsdir(tcfg) / "backup.json").is_file() and not (wsdir(tcfg, KT) / "backup.json").exists()


# --- AC2: /release -----------------------------------------------------------------------------------------------

def test_release_deletes_exactly_the_two_files(tcfg):
    make_ep(tcfg)
    c = logged(tcfg)
    before = snapshot(tcfg)
    confirm_both(c)
    r = c.post(f"/api/episodes/{VID}/release", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["released"] == VID and body["changed"] is True and body["freed"] == len(HD) + len(VERT)
    assert not (wsdir(tcfg) / "source_hd.mp4").exists() and not full.vertical_path(tcfg, VID).exists()
    doc = st.read(wsdir(tcfg))
    assert doc["released"] is True and doc["released_at"] and doc["state"] == st.DONE
    assert doc["source_hd_sha256"] == HD_SHA and doc["source_hd_size"] == len(HD)
    rec = json.loads((wsdir(tcfg) / "backup.json").read_text(encoding="utf-8"))
    assert rec["released"]["released_at"] and rec["released"]["hd"]["sha256"] == HD_SHA
    assert rec["released"]["vertical"]["sha256"] == V_SHA
    assert snapshot(tcfg) == before  # AC4: nothing else changed (transcript, clips, titles, Shorts, render manifest)
    again = c.post(f"/api/episodes/{VID}/release", json={})
    assert again.status_code == 200 and again.json()["changed"] is False and again.json()["freed"] == 0


def test_release_refused_without_confirmation_or_after_change(tcfg):
    make_ep(tcfg)
    c = logged(tcfg)
    r = c.post(f"/api/episodes/{VID}/release", json={})
    assert r.status_code == 422 and "chưa xác nhận" in r.json()["detail"]
    assert c.post(f"/api/episodes/{VID}/backup", json={"kind": "hd", "sha256": HD_SHA}).status_code == 200
    r = c.post(f"/api/episodes/{VID}/release", json={})
    assert r.status_code == 422 and "bản dọc" in r.json()["detail"]
    assert c.post(f"/api/episodes/{VID}/backup", json={"kind": "vertical", "sha256": V_SHA}).status_code == 200
    full.vertical_path(tcfg, VID).write_bytes(b"another vertical file")  # changed after the confirmation
    r = c.post(f"/api/episodes/{VID}/release", json={})
    assert r.status_code == 422 and "không khớp" in r.json()["detail"]
    assert (wsdir(tcfg) / "source_hd.mp4").is_file() and full.vertical_path(tcfg, VID).is_file()
    assert not st.read(wsdir(tcfg)).get("released")


def test_release_without_vertical_needs_allow_flag(tcfg):
    make_ep(tcfg, vertical=False)
    c = logged(tcfg)
    assert c.post(f"/api/episodes/{VID}/backup", json={"kind": "hd", "sha256": HD_SHA}).status_code == 200
    r = c.post(f"/api/episodes/{VID}/release", json={})
    assert r.status_code == 422 and "chưa có bản dọc" in r.json()["detail"]
    assert (wsdir(tcfg) / "source_hd.mp4").is_file()
    r = c.post(f"/api/episodes/{VID}/release", json={"allow_no_vertical": True})
    assert r.status_code == 200 and r.json()["freed"] == len(HD)
    assert not (wsdir(tcfg) / "source_hd.mp4").exists()


def test_release_refused_while_lease_or_job_active(tcfg):
    make_ep(tcfg)
    c = logged(tcfg)
    confirm_both(c)
    doc = st.read(wsdir(tcfg))
    doc["lease"] = {"worker": "w", "expires_at": st.now_iso(time.time() + 3600)}
    st.write(wsdir(tcfg), doc)
    r = c.post(f"/api/episodes/{VID}/release", json={})
    assert r.status_code == 409 and (wsdir(tcfg) / "source_hd.mp4").is_file()
    doc["lease"] = None
    st.write(wsdir(tcfg), doc)
    app_runner = c.app.state.runner if hasattr(c.app.state, "runner") else None
    if app_runner is not None:  # a queued job of the video blocks too
        from auto_short.web.jobs import KIND_VERTICAL
        app_runner.submit(VID, KIND_VERTICAL, lambda job: time.sleep(5))
        r = c.post(f"/api/episodes/{VID}/release", json={})
        assert r.status_code == 409 and (wsdir(tcfg) / "source_hd.mp4").is_file()


def test_release_unknown_id_and_unfinished_enhance(tcfg):
    make_ep(tcfg, hd=False, vertical=False)
    c = logged(tcfg)
    assert c.post("/api/episodes/bbbbbbbbbb2/release", json={}).status_code == 404
    assert c.post(f"/api/episodes/{VID}/release", json={}).status_code == 422


# --- AC3 / AC4: the released state --------------------------------------------------------------------------------

def test_released_state_keeps_shorts_and_blocks_rerender(tcfg):
    make_ep(tcfg, kt=True)
    kt_hd = wsdir(tcfg, KT) / "source_hd.mp4"
    assert kt_hd.is_file()
    rm_path = Path(tcfg.render.output_dir) / VID / "render_manifest.json"
    manifest_before = (wsdir(tcfg) / "manifest.json").read_bytes()
    rm_before = rm_path.read_bytes()
    c = logged(tcfg)
    confirm_both(c, KT)  # a .kt id acts on its video
    assert c.post(f"/api/episodes/{KT}/release", json={}).status_code == 200
    assert not kt_hd.exists()  # the hard link of the khai thị episode goes too (else the space is not freed)
    assert st.read(wsdir(tcfg, KT))["released"] is True
    # render keys of existing Shorts untouched; a manual render refuses clearly and leaves the manifest as it was
    for eid in (VID, KT):
        with pytest.raises(RenderError, match="HD đã chuyển ra máy ngoài"):
            run_render(eid, tcfg)
    assert (wsdir(tcfg) / "manifest.json").read_bytes() == manifest_before
    assert rm_path.read_bytes() == rm_before
    # the effective source does not fall back to the original
    assert ep.hd_source(tcfg, VID) is None and ep.hd_source(tcfg, KT) is None
    assert st.is_released(wsdir(tcfg))
    # views: released, no HD / vertical link
    for eid in (VID, KT):
        v = c.get(f"/api/episodes/{eid}").json()
        h = v["hd_video"]
        assert h["released"] is True and h["released_at"] and h["url"] is None and h["vertical"] is None
        assert v["enhance"]["released"] is True and v["enhance"]["hd_ready"] is False
        assert c.get(f"/api/episodes/{eid}/source-hd").status_code == 404
        assert c.get(f"/api/episodes/{eid}/vertical").status_code == 404
        assert c.post(f"/api/episodes/{eid}/vertical").status_code == 404
    # no automatic or manual way back to enhance / render from the original
    assert c.post(f"/api/episodes/{VID}/enhance", json={"enabled": True}).status_code == 409
    assert c.post(f"/api/episodes/{VID}/enhance/render-original").status_code == 409
    assert c.post(f"/api/episodes/{VID}/enhance/redo").status_code == 409
    assert c.post(f"/api/episodes/{VID}/enhance/rerender").status_code == 409


def test_released_vertical_job_refuses_original(tcfg):
    make_ep(tcfg)
    c = logged(tcfg)
    confirm_both(c)
    assert c.post(f"/api/episodes/{VID}/release", json={}).status_code == 200
    with pytest.raises(RenderError, match="HD đã chuyển ra máy ngoài"):
        full.run_vertical(VID, tcfg)


def test_release_hook_and_auto_paths_do_nothing_for_released(tcfg):
    make_ep(tcfg)
    c = logged(tcfg)
    confirm_both(c)
    assert c.post(f"/api/episodes/{VID}/release", json={}).status_code == 200
    c.app.state.auto_vertical.set(VID, True)  # the wish "tự tạo bản dọc"
    c.app.state.hd_ready(VID)  # E6 auto re-render path + CP8.35 auto vertical check
    assert not [j for j in c.app.state.runner.jobs() if j.episode_id == VID]
    assert not c.app.state.auto_vertical.wanted(VID)  # wish dropped, no vertical job


# --- AC5: script + generator --------------------------------------------------------------------------------------

def load_generator():
    spec = importlib.util.spec_from_file_location("make_backup", ROOT / "scripts" / "backup" / "make_backup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_builds_scripts_with_parameters(tmp_path):
    work, out_dir = tmp_path / "work", tmp_path / "output"
    (work / "_playlists").mkdir(parents=True)
    (work / "_playlists" / "PLtest123.json").write_text(
        json.dumps({"entries": [{"video_id": VID}, {"video_id": "bbbbbbbbbb2"}]}), encoding="utf-8")
    (work / VID).mkdir()
    (work / VID / "source_hd.mp4").write_bytes(HD)
    (work / VID / "enhance.json").write_text(json.dumps({"source_hd_sha256": HD_SHA, "source_hd_size": len(HD)}),
                                             encoding="utf-8")
    (out_dir / VID / "full").mkdir(parents=True)
    (out_dir / VID / "full" / "vertical.mp4").write_bytes(VERT)
    conf = tmp_path / "config.toml"
    conf.write_text(f'[workspace]\ndir = "{work}"\n[render]\noutput_dir = "{out_dir}"\n', encoding="utf-8")
    gen = load_generator()
    dest = tmp_path / "scripts_out"
    rc = gen.main(["--playlist", "PLtest123", "--series", "Kinh Thử Nghiệm", "--dest-name", "ThuNghiem_HD",
                   "--out", str(dest), "--config", str(conf)])
    assert rc == 0
    raw = (dest / "backup.ps1").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    text = raw.decode("utf-8-sig")
    assert "@@" not in text
    assert f'"{VID}|HD" = "{HD_SHA}"' in text and f'"{VID}|Doc" = "{V_SHA}"' in text
    assert "'PLtest123'" in text and "'Kinh Thử Nghiệm'" in text and "E:\\ThuNghiem_HD" in text
    assert "[string]$Dest = 'E:\\ThuNghiem_HD'" in text
    assert json.loads((dest / "vertical-sha.cache.json").read_text(encoding="utf-8"))[VID]["sha256"] == V_SHA
    rename = (dest / "rename.ps1").read_bytes().decode("utf-8-sig")
    assert "@@" not in rename and "'Kinh Thử Nghiệm'" in rename


def test_generator_rejects_bad_playlist_and_quotes_series():
    gen = load_generator()
    with pytest.raises(SystemExit):
        gen.main(["--playlist", "bad id;", "--series", "X"])
    with pytest.raises(SystemExit):
        gen.main(["--playlist", "PLok", "--series", 'a"b'])
    assert gen.ps_quote("Kinh Nguyện's") == "Kinh Nguyện''s"


def _template() -> str:
    return (ROOT / "scripts" / "backup" / "backup.template.ps1").read_text(encoding="utf-8")


def test_template_merges_existing_index_and_keeps_fixed_columns():
    t = _template()
    merge = t[t.index("$newKeys = @{}"):t.index('Remove-Item (Join-Path $Dest ".api.json")')]
    assert 'foreach ($r in $rows) { $newKeys["$($r.tap)|$($r.loai)"] = $true }' in merge
    assert "if (Test-Path -LiteralPath $Index)" in merge
    assert "try {" in merge and "} catch {" in merge
    assert "Import-Csv -LiteralPath $Index -Encoding UTF8 -ErrorAction Stop" in merge
    assert '$key = "$($old.tap)|$($old.loai)"' in merge
    assert "-not $newKeys.ContainsKey($key)" in merge
    assert "Test-Path -LiteralPath (Join-Path $Dest $old.file)" in merge
    assert "$keptRows += $old" in merge
    fallback = merge.split("} catch {", 1)[1]
    assert 'Log "Cảnh báo:' in fallback and "$keptRows = @()" in fallback
    assert 'Log "Giữ lại $($keptRows.Count) dòng CSV cũ."' in merge
    assert "($rows + $keptRows) | Sort-Object tap, loai | Select-Object tap, loai, file, video_id, tieu_de |" in merge
    assert "Export-Csv -NoTypeInformation -Encoding UTF8 -Path $Index" in merge
    assert "$rows | Export-Csv" not in t


def test_template_defaults_and_instructions_use_e_drive():
    t = _template()
    assert "[string]$Dest = 'E:\\@@DESTNAME@@'" in t
    assert r"-Dest E:\@@DESTNAME@@" in t
    assert "D:\\@@DESTNAME@@" not in t
    generator = (ROOT / "scripts" / "backup" / "make_backup.py").read_text(encoding="utf-8")
    assert r"backup drive (E:\\<name>)" in generator


def test_template_keeps_old_behaviour_and_has_release_step():
    t = _template()
    for old in ("[string]$Dest", "[switch]$NoVertical", "[switch]$ThumbsOnly", "[string]$SkipDoc", "[string]$Have",
                "-C -", "Get-FileHash", "SHA256SUMS.txt", "/thumbs/", "$KnownSha", "@@SHA@@", ".part"):
        assert old in t, old
    # G6: routes, flags, the single prompt
    assert "[switch]$Release" in t and "[switch]$NoRelease" in t
    assert "/api/episodes/$($r.video_id)/backup" in t and "/api/episodes/$($x.id)/release" in t
    assert t.count("Read-Host") == 2  # the password prompt + the one release prompt
    assert "Giải phóng {0} tập ({1:N1} GB) trên VM? (y/N)" in t
    assert "if (-not $go)" in t and "$go = $Release" in t
    assert "-NoRelease: chỉ xác nhận" in t
    assert "kind = $kind; sha256 = $sha" in t and '"vertical" } else { "hd" }' in t
    # the script never deletes backup files
    assert "Remove-Item -LiteralPath $f" not in t


def test_template_names_and_legacy_rename():
    t = _template()
    assert '"[HD Mobile]"' in t and '"[HD]"' in t and "[HD Dọc]" in t  # the old tag only for renaming
    assert 'return "$tag $Series - Tập $n.mp4"' in t
    assert "Rename-LegacyMobile" in t and "Set-Content -LiteralPath $Sums" in t  # sums line follows the new name
    assert ".jpg" in t and "[HD Mobile] ... - Tập N.jpg" in t
    r = (ROOT / "scripts" / "backup" / "rename.template.ps1").read_text(encoding="utf-8")
    assert '"[HD Mobile]"' in r and "StartsWith(\"[HD Dọc] \")" in r and "backup.ps1" in r
