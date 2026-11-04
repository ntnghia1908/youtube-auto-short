"""STN1 AC6: inspect generated PowerShell; no PowerShell/runtime network required."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("speaker", ["PS. Tịnh Không", "HT. Tịnh Không", "Thầy O'Neil"])
def test_backup_names_and_existing_file_resolution(speaker):
    spec = importlib.util.spec_from_file_location("stn1_backup", ROOT / "scripts/backup/make_backup.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    template = (ROOT / "scripts/backup/backup.template.ps1").read_text()
    text = gen.render(template, table={}, playlist="PLtest", series="Bộ thử", dest_name="Backup", today="today",
                      speaker_label=speaker)
    assert "@@" not in text
    assert f"[string]$SpeakerLabel = '{gen.ps_quote(speaker)}'" in text
    name_body = text.split("function BackupName(", 1)[1].split("\n}", 1)[0]
    assert '"[HD Mobile]"' in name_body and '"[HD]"' in name_body
    assert '$Series -match "Tịnh Không"' in name_body
    assert '"$Series - $SpeakerLabel"' in name_body
    assert 'return "$tag $label - Tập $n.mp4"' in name_body
    resolve = text.split("function ExistingBackupName(", 1)[1].split("\n}", 1)[0]
    # Prefer a new file, then the last current CSV row, then the speaker-free legacy name.
    assert resolve.index("$name = BackupName") < resolve.index('@("index.csv", "danh-sach.csv")') < resolve.index("$old = LegacyBackupName")
    assert "Select-Object -Last 1" in resolve and "return $row.file" in resolve and "return $old" in resolve
    assert "$name = ExistingBackupName ([int]$ep) $it[0] $e.video_id" in text
    assert "$video = BackupPath $pair[0] (ExistingBackupName $epNum $pair[0] $e.video_id)" in text
    assert text.index("$rows += [pscustomobject]") < text.index("$todo += [pscustomobject]")
    assert '$done[$name]' in text and '$sha = $shaOf[$r.file]' in text
    assert 'speaker_label=cfg.store.speaker_label' in (ROOT / "scripts/backup/make_backup.py").read_text()
    raw = gen.to_crlf_bom(text)
    assert raw.startswith(b"\xef\xbb\xbf") and b"\n" not in raw.replace(b"\r\n", b"")


def test_str1_powershell_layout_rules_and_call_sites():
    import inspect
    import re
    from test_store_server import SUBDIR_CASES, store

    text = (ROOT / "scripts/backup/backup.template.ps1").read_text()
    rules = text.split("function StoreSubdir(", 1)[1].split("\n}", 1)[0]
    # Compare the actual regex in both sources, then exercise its episode captures with the shared table.
    ps_pattern = re.search(r"\[regex\]::Match\(\$name, '([^']+)'\)", rules)[1]
    assert f'r"{ps_pattern}"' in inspect.getsource(store.subdir)
    assert '"Tap {0:D2}" -f [int]$episode.Groups[1].Value' in rules
    assert '"KhaiThi" } else { "Short" }' in rules and 'else { "Khac" }' in rules
    for kind, name, expected in SUBDIR_CASES:
        assert store.subdir(kind, name).as_posix() == expected
        if kind == "short" and "/Tap " in expected:
            assert int(re.search(ps_pattern, name)[1]) == int(expected.split("Tap ")[1])
    for label, directory in (("HD", "HD"), ("Doc", "HD Mobile"), ("Goc", "Goc")):
        assert f'"{label}" {{ return "{directory}" }}' in rules
    assert 'if ($name.EndsWith(".jpg")) { return "Hinh" }' in rules
    resolve = text.split("function BackupPath(", 1)[1].split("\n}", 1)[0]
    assert '$parent = Join-Path $Dest (StoreSubdir $kind $name)' in resolve
    assert resolve.index('$target =') < resolve.index('$legacy =')
    assert '-not $New' in resolve and 'return $legacy' in resolve and 'return $target' in resolve
    assert '$file = BackupPath $it[0] $name -Create' in text
    assert '$f = BackupPath $r.loai $r.file' in text  # -Release confirmation reads either layout
    assert '$jpg = BackupPath $pair[0]' in text and '".jpg")) -New -Create' in text
    assert '(BackupPath $old.loai $old.file)' in text  # keep released episodes in CSV
    legacy = text.split('function Rename-LegacyMobile {', 1)[1].split('\n$SkipSet', 1)[0]
    assert '(Join-Path $Dest "HD Mobile")' in legacy and '(Join-Path $Dest "Hinh")' in legacy
    assert '$target = BackupPath "Doc" $new -New -Create' in legacy
    assert '$renamed.ContainsKey($row.file)' in legacy
    assert 'Split-Path $file -Leaf' in text  # sums remain basename only


def test_str1_powershell_shared_table_and_flat_fallback_when_available(tmp_path):
    import json
    import shutil
    import subprocess
    from test_store_server import SUBDIR_CASES

    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        pytest.skip("PowerShell unavailable; generated-script structural checks run separately")
    text = (ROOT / "scripts/backup/backup.template.ps1").read_text()
    helpers = text[text.index("function StoreSubdir("):text.index("# Giữ tên file đã có")]
    cases = [(dict(hd="HD", vertical="Doc", source="Goc", short="short")[kind], name, expected)
             for kind, name, expected in SUBDIR_CASES]
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    script = helpers + r'''
$ErrorActionPreference = "Stop"
$Dest = $PSScriptRoot
$cases = Get-Content -Raw -LiteralPath (Join-Path $Dest "cases.json") | ConvertFrom-Json
foreach ($case in $cases) {
    $actual = (StoreSubdir $case[0] $case[1]).Replace('\', '/')
    if ($actual -ne $case[2]) { throw "Mismatch: $actual != $($case[2])" }
    $flat = Join-Path $Dest $case[1]
    [IO.File]::WriteAllText($flat, "flat")
    if ((BackupPath $case[0] $case[1]) -ne $flat) { throw "Flat fallback failed" }
    $new = BackupPath $case[0] $case[1] -New -Create
    [IO.File]::WriteAllText($new, "new")
    if ((BackupPath $case[0] $case[1]) -ne $new) { throw "New layout precedence failed" }
}
'''
    path = tmp_path / "check.ps1"
    path.write_bytes(b"\xef\xbb\xbf" + script.encode())
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", str(path)], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")


def test_str1_reorganize_wrapper_defaults_to_dry_run():
    text = (ROOT / "tools/store/sap-xep-kho.ps1").read_text()
    assert '[switch]$Apply' in text and '[string]$Config' in text
    assert '"reorganize", "--series", $Series' in text
    assert 'if ($Apply) { $arguments += "--apply" }' in text
    assert 'exit $LASTEXITCODE' in text
