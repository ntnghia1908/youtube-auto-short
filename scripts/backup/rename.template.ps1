# Đổi tên file backup @@SERIES@@ từ dạng cũ "Tap001_<id>_HD.mp4" sang
# "[HD] @@SERIES@@ - Tập 1.mp4" / "[HD Mobile] @@SERIES@@ - Tập 1.mp4" (bản dọc; trước đây "[HD Dọc]").
# Chạy được trong lúc backup.ps1 đang tải: chỉ đổi file đã tải xong, không đụng file .part.
# SHA256SUMS.txt chỉ được cập nhật khi backup.ps1 không chạy (chạy lại script này sau khi tải xong).
#
#   powershell -ExecutionPolicy Bypass -File .\rename.ps1 -Dest E:\@@DESTNAME@@
param([Parameter(Mandatory = $true)][string]$Dest, [string]$Series = '@@SERIES@@')
$ErrorActionPreference = "Stop"

function BackupName([int]$n, [string]$kind) {
    $tag = if ($kind -eq "Doc") { "[HD Mobile]" } else { "[HD]" }
    return "$tag $Series - Tập $n.mp4"
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
Get-ChildItem -LiteralPath $Dest -File | Where-Object { $_.Name -like "[[]HD Dọc[]] *" } | ForEach-Object {
    $new = "[HD Mobile] " + $_.Name.Substring("[HD Dọc] ".Length)
    $target = Join-Path $Dest $new
    if (Test-Path -LiteralPath $target) { Write-Host "Bỏ qua $($_.Name): đã có '$new'"; return }
    Move-Item -LiteralPath $_.FullName -Destination $target
    $map[$_.Name] = $new
    Write-Host "$($_.Name) -> $new"
    $renamed++
}
Write-Host "Đã đổi tên $renamed file."

$sums = Join-Path $Dest "SHA256SUMS.txt"
$running = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe' OR Name = 'pwsh.exe'" |
    Where-Object { $_.CommandLine -match "backup\.ps1" }
if ($running) {
    Write-Host "backup.ps1 đang chạy: chưa sửa SHA256SUMS.txt (bản tải kế tiếp vẫn nhận tên cũ). Chạy lại script này khi tải xong."
} elseif (Test-Path -LiteralPath $sums) {
    $fixed = 0
    $lines = Get-Content -LiteralPath $sums -Encoding UTF8 | ForEach-Object {
        $p = $_ -split "  ", 2
        if ($p.Count -eq 2 -and $p[1].StartsWith("[HD Dọc] ") -and (Test-Path -LiteralPath (Join-Path $Dest ("[HD Mobile] " + $p[1].Substring(9))))) {
            $fixed++; "{0}  {1}" -f $p[0], ("[HD Mobile] " + $p[1].Substring(9)); return
        }
        if ($p.Count -eq 2 -and $p[1] -match "^Tap(\d{3})_(.+)_(HD|Doc)\.mp4$") {
            $new = BackupName ([int]$Matches[1]) $Matches[3]
            if (Test-Path -LiteralPath (Join-Path $Dest $new)) { $fixed++; "{0}  {1}" -f $p[0], $new } else { $_ }
        } else { $_ }
    }
    Set-Content -LiteralPath $sums -Value $lines -Encoding UTF8
    Write-Host "SHA256SUMS.txt: cập nhật $fixed dòng sang tên mới."
}
