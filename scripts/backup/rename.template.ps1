# Đổi tên file backup Kinh Địa Tạng từ dạng cũ "Tap001_<id>_HD.mp4" sang
# "[HD] Kinh Địa Tạng Bồ Tát Bổn Nguyện - Tập 1.mp4" / "[HD Dọc] ... - Tập 1.mp4".
# Chạy được trong lúc kdt-backup.ps1 đang tải: chỉ đổi file đã tải xong, không đụng file .part.
# SHA256SUMS.txt chỉ được cập nhật khi kdt-backup.ps1 không chạy (chạy lại script này sau khi tải xong).
#
#   powershell -ExecutionPolicy Bypass -File .\kdt-rename.ps1 -Dest E:\KinhDiaTang_HD
param([Parameter(Mandatory = $true)][string]$Dest)
$ErrorActionPreference = "Stop"

function BackupName([int]$n, [string]$kind) {
    $tag = if ($kind -eq "Doc") { "[HD Dọc]" } else { "[HD]" }
    return "$tag Kinh Địa Tạng Bồ Tát Bổn Nguyện - Tập $n.mp4"
}

$map = @{}
$renamed = 0
Get-ChildItem -LiteralPath $Dest -File | ForEach-Object {
    if ($_.Name -notmatch "^Tap(\d{3})_(.+)_(HD|Doc)\.mp4$") { return }
    $new = BackupName ([int]$Matches[1]) $Matches[3]
    $map[$_.Name] = $new
    $target = Join-Path $Dest $new
    if (Test-Path -LiteralPath $target) { Write-Host "Bỏ qua $($_.Name): đã có '$new'"; return }
    Move-Item -LiteralPath $_.FullName -Destination $target
    Write-Host "$($_.Name) -> $new"
    $renamed++
}
Write-Host "Đã đổi tên $renamed file."

$sums = Join-Path $Dest "SHA256SUMS.txt"
$running = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe' OR Name = 'pwsh.exe'" |
    Where-Object { $_.CommandLine -match "kdt-backup\.ps1" }
if ($running) {
    Write-Host "kdt-backup.ps1 đang chạy: chưa sửa SHA256SUMS.txt (bản tải kế tiếp vẫn nhận tên cũ). Chạy lại script này khi tải xong."
} elseif (Test-Path -LiteralPath $sums) {
    $fixed = 0
    $lines = Get-Content -LiteralPath $sums -Encoding UTF8 | ForEach-Object {
        $p = $_ -split "  ", 2
        if ($p.Count -eq 2 -and $p[1] -match "^Tap(\d{3})_(.+)_(HD|Doc)\.mp4$") {
            $new = BackupName ([int]$Matches[1]) $Matches[3]
            if (Test-Path -LiteralPath (Join-Path $Dest $new)) { $fixed++; "{0}  {1}" -f $p[0], $new } else { $_ }
        } else { $_ }
    }
    Set-Content -LiteralPath $sums -Value $lines -Encoding UTF8
    Write-Host "SHA256SUMS.txt: cập nhật $fixed dòng sang tên mới."
}
