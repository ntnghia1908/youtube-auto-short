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
    assert "$video = Join-Path $Dest (ExistingBackupName $epNum $pair[0] $e.video_id)" in text
    assert text.index("$rows += [pscustomobject]") < text.index("$todo += [pscustomobject]")
    assert '$done[$name]' in text and '$sha = $shaOf[$r.file]' in text
    assert 'speaker_label=cfg.store.speaker_label' in (ROOT / "scripts/backup/make_backup.py").read_text()
    raw = gen.to_crlf_bom(text)
    assert raw.startswith(b"\xef\xbb\xbf") and b"\n" not in raw.replace(b"\r\n", b"")
