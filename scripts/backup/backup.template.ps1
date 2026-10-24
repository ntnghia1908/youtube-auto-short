# Sao lưu bản HD ngang + bản dọc của Kinh Địa Tạng từ web 8080 về máy này (chạy qua đêm).
# Chạy lại bao nhiêu lần cũng được: file đã tải và kiểm tra xong sẽ bỏ qua, file dở sẽ tải tiếp.
#
#   powershell -ExecutionPolicy Bypass -File .\kdt-backup.ps1 -Dest D:\KinhDiaTang_HD
#   bỏ bản dọc tập 1-10 đã có:        ... -SkipDoc "1-10"
#   hoặc kiểm và nhận file đã tải:    ... -Have "C:\Users\<tên>\Downloads"
#   chỉ tải thumbnail (không tải video): ... -ThumbsOnly
#   Thumbnail: mỗi video đã có trong thư mục đích được tải kèm ảnh cùng tên, đuôi .jpg (tải lại mỗi lần chạy, ảnh nhỏ).
#
# Sinh tự động ngày @@GENERATED@@ (bảng sha256 bên dưới); file mới hơn bảng chỉ kiểm theo dung lượng.
param(
    [string]$Server = "http://10.8.102.102:8080",
    [string]$Dest = "D:\KinhDiaTang_HD",
    [string]$Playlist = "PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4",
    [int]$Retries = 30,
    [switch]$NoVertical,
    [switch]$ThumbsOnly,     # chỉ tải thumbnail cho video đã có trong thư mục đích
    [string]$SkipDoc = "",   # tập không tải bản dọc, vd "1-10" hoặc "1-10,15"
    [string]$Have = ""       # thư mục chứa file đã tải từ web trước đây (tên gốc ..._TậpN_Doc.mp4 / _HD.mp4): kiểm sha rồi nhận vào
)
$ErrorActionPreference = "Stop"

# sha256 đã biết trên server: "<video_id>|HD" (enhance.json) và "<video_id>|Doc" (output/<id>/full/vertical.mp4)
$KnownSha = @{
@@SHA@@
}

$drives = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -gt 0 }
$qual = Split-Path -Qualifier $Dest -ErrorAction SilentlyContinue
if (-not $qual -or -not ($drives | Where-Object { "$($_.Name):" -eq $qual })) {
    Write-Host "Ổ đích '$qual' không dùng được trên máy này. Các ổ hiện có:"
    $drives | ForEach-Object { Write-Host ("  {0}:  còn trống {1:N0} GB" -f $_.Name, ($_.Free / 1GB)) }
    Write-Host "Chạy lại với -Dest <ổ còn >= 200 GB>\KinhDiaTang_HD"
    exit 2
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$Log = Join-Path $Dest "backup-log.txt"
$Jar = Join-Path $Dest ".cookies.txt"
$Sums = Join-Path $Dest "SHA256SUMS.txt"
$Index = Join-Path $Dest "danh-sach.csv"
function Log($msg) { $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $msg; Write-Host $line; Add-Content -Path $Log -Value $line -Encoding UTF8 }

$curl = (Get-Command curl.exe -ErrorAction SilentlyContinue).Source
if (-not $curl) { throw "Không thấy curl.exe (cần Windows 10 1803 trở lên)" }

# Không cho máy ngủ khi đang chạy
Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[Win32.Power]::SetThreadExecutionState([uint32]2147483649) | Out-Null  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED

function Login {
    if (-not $script:Password) {
        $sec = Read-Host "Mật khẩu web 8080" -AsSecureString
        $script:Password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    }
    $pw = Join-Path $env:TEMP ("kdt-pw-" + [guid]::NewGuid() + ".txt")
    [IO.File]::WriteAllText($pw, $script:Password)  # curl đọc mật khẩu từ file để không lộ trên dòng lệnh
    try {
        $code = & $curl -s -o NUL -w "%{http_code}" -c $Jar --data-urlencode "password@$pw" --data-urlencode "next=/" "$Server/login"
    } finally { Remove-Item $pw -Force -ErrorAction SilentlyContinue }
    if ($code -ne "303") { $script:Password = $null; throw "Đăng nhập thất bại (HTTP $code): sai mật khẩu hoặc server không chạy" }
}

function Get-Json($path) {
    $tmp = Join-Path $Dest ".api.json"
    for ($i = 1; $i -le $Retries; $i++) {
        $code = & $curl -s -o $tmp -w "%{http_code}" -b $Jar "$Server$path"
        if ($code -eq "200") { return (Get-Content -Raw -Encoding UTF8 $tmp | ConvertFrom-Json) }
        if ($code -eq "401") { Login; continue }
        Log "API $path lỗi HTTP $code, thử lại sau 60 s ($i/$Retries)"; Start-Sleep 60
    }
    throw "API $path không trả lời"
}

# Dung lượng thật của file trên server (Range 0-0 -> Content-Range: bytes 0-0/<tổng>)
function Get-RemoteSize($url) {
    $hdr = & $curl -s -o NUL -D - -r 0-0 -b $Jar "$Server$url"
    $m = [regex]::Match(($hdr -join "`n"), "(?im)^content-range:\s*bytes\s+0-0/(\d+)")
    if ($m.Success) { return [int64]$m.Groups[1].Value }
    if ($hdr -match "^HTTP/\S+ 401") { Login; return Get-RemoteSize $url }
    return -1
}

# Tên file backup: "[HD] Kinh Địa Tạng Bồ Tát Bổn Nguyện - Tập 1.mp4" / "[HD Dọc] ... - Tập 1.mp4"
function BackupName([int]$n, [string]$kind) {
    $tag = if ($kind -eq "Doc") { "[HD Dọc]" } else { "[HD]" }
    return "$tag Kinh Địa Tạng Bồ Tát Bổn Nguyện - Tập $n.mp4"
}

$SkipSet = @{}
foreach ($r in ($SkipDoc -split ",")) {
    if ($r -match "^\s*(\d+)\s*-\s*(\d+)\s*$") { [int]$Matches[1]..[int]$Matches[2] | ForEach-Object { $SkipSet[$_] = $true } }
    elseif ($r -match "^\s*(\d+)\s*$") { $SkipSet[[int]$Matches[1]] = $true }
}

# File đã tải trước đây trong -Have: nhận vào nếu dung lượng (và sha256 khi server có) khớp
function Adopt($url, $file, $key, $origName) {
    if (-not $Have -or -not $origName) { return $null }
    $src = Join-Path $Have $origName
    if (-not (Test-Path -LiteralPath $src)) { return $null }
    $size = Get-RemoteSize $url
    if ((Get-Item -LiteralPath $src).Length -ne $size) { Log "  có $origName nhưng dung lượng khác server, tải lại"; return $null }
    $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $src).Hash.ToLower()
    $want = $KnownSha[$key]
    if ($want -and $sha -ne $want) { Log "  có $origName nhưng SAI sha256, tải lại"; return $null }
    Copy-Item -LiteralPath $src -Destination "$file.part" -Force
    Move-Item -Force -LiteralPath "$file.part" -Destination $file
    Add-Content -LiteralPath $Sums -Value ("{0}  {1}" -f $sha, (Split-Path $file -Leaf)) -Encoding UTF8
    return $(if ($want) { "OK nhận file có sẵn ($origName), sha256 khớp server" } else { "OK nhận file có sẵn ($origName), dung lượng khớp" })
}

function Fetch($url, $file, $key) {
    $part = "$file.part"
    for ($i = 1; $i -le $Retries; $i++) {
        $size = Get-RemoteSize $url
        if ($size -le 0) { Log "  không lấy được dung lượng ($url), thử lại sau 60 s"; Start-Sleep 60; continue }
        $have = if (Test-Path -LiteralPath $part) { (Get-Item -LiteralPath $part).Length } else { 0 }
        if ($have -gt $size) { Remove-Item -LiteralPath $part -Force; $have = 0 }
        if ($have -lt $size) {
            if ($have -gt 0) { Log ("  tải tiếp từ {0:N2} / {1:N2} GB" -f ($have / 1GB), ($size / 1GB)) }
            & $curl --progress-bar -S -f -b $Jar -C - -o $part "$Server$url"  # thanh tiến độ của file đang tải
            $rc = $LASTEXITCODE
            $after = if (Test-Path -LiteralPath $part) { (Get-Item -LiteralPath $part).Length } else { 0 }
            $script:SessionBytes += [math]::Max([int64]0, [int64]($after - $have))  # int64: file > 2 GB
            $have = $after
            if ($rc -ne 0) { Log "  curl lỗi $rc (lần $i/$Retries), tải tiếp sau 60 s"; Start-Sleep 60; continue }
        }
        if ($have -ne $size) { Log "  dung lượng $have != $size, tải tiếp"; continue }
        Write-Host "  kiểm sha256..."
        $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $part).Hash.ToLower()
        $want = $KnownSha[$key]
        if ($want -and $sha -ne $want) { Log "  SAI sha256 ($sha != $want), xóa tải lại"; Remove-Item -LiteralPath $part -Force; continue }
        Move-Item -Force -LiteralPath $part -Destination $file
        Add-Content -LiteralPath $Sums -Value ("{0}  {1}" -f $sha, (Split-Path $file -Leaf)) -Encoding UTF8
        return $(if ($want) { "OK sha256 khớp server" } else { "OK dung lượng khớp (chưa có sha server để đối chiếu)" })
    }
    return $null
}

Log "=== Bắt đầu: $Server -> $Dest"
Login
$pl = Get-Json "/api/playlists/$Playlist"
$free = (Get-PSDrive ((Resolve-Path $Dest).Drive.Name)).Free
Log ("Ổ đích còn trống {0:N0} GB" -f ($free / 1GB))

$done = @{}
if (Test-Path -LiteralPath $Sums) { Get-Content -LiteralPath $Sums -Encoding UTF8 | ForEach-Object { $p = $_ -split "  ", 2; if ($p.Count -eq 2) { $done[$p[1]] = $true } } }
$ok = 0; $skip = 0; $failed = @(); $notReady = @(); $rows = @(); $todo = @()
foreach ($e in ($pl.entries | Sort-Object { [int]("0" + ($_.episode -replace "\D", "")) })) {
    $ep = "{0:D3}" -f [int]("0" + ($e.episode -replace "\D", ""))
    $items = @()
    if ($e.hd_url) { $items += ,@("HD", $e.hd_url, $e.hd_name) } else { $notReady += "tập $ep HD" }
    if (-not $NoVertical -and -not $SkipSet[[int]$ep]) {
        if ($e.vertical -and $e.vertical.ready -and $e.vertical.url) { $items += ,@("Doc", $e.vertical.url, $e.vertical.name) } else { $notReady += "tập $ep Dọc" }
    }
    foreach ($it in $items) {
        $name = BackupName ([int]$ep) $it[0]
        $file = Join-Path $Dest $name
        $rows += [pscustomobject]@{ tap = $ep; loai = $it[0]; file = $name; video_id = $e.video_id; tieu_de = $e.title }
        # tên cũ (bản script trước): Tap001_<id>_HD.mp4 -> đổi sang tên mới, sha256 đã kiểm giữ nguyên
        $legacy = "Tap{0}_{1}_{2}.mp4" -f $ep, $e.video_id, $it[0]
        $legacyFile = Join-Path $Dest $legacy
        if ($done[$legacy] -and (Test-Path -LiteralPath $legacyFile) -and -not (Test-Path -LiteralPath $file)) {
            Move-Item -LiteralPath $legacyFile -Destination $file
            Log "Đổi tên $legacy -> $name"
        }
        # file dở của bản cũ: đổi tên .part để tải tiếp thay vì tải lại từ đầu
        if ((Test-Path -LiteralPath "$legacyFile.part") -and -not (Test-Path -LiteralPath "$file.part")) {
            Move-Item -LiteralPath "$legacyFile.part" -Destination "$file.part"
        }
        if ((Test-Path -LiteralPath $file) -and ($done[$name] -or $done[$legacy])) { $skip++; continue }
        $todo += [pscustomobject]@{ ep = [int]$ep; kind = $it[0]; url = $it[1]; orig = $it[2]; file = $file; name = $name; key = "$($e.video_id)|$($it[0])"; size = 0 }
    }
}

if ($ThumbsOnly) { $todo = @() }

# Tiến độ: tổng dung lượng phải tải, phần đã có của file .part dở được tính là đã xong
Write-Host "Đang lấy dung lượng $($todo.Count) file..."
$total = [int64]0; $doneBytes = [int64]0
foreach ($t in $todo) {
    $t.size = [math]::Max([int64]0, [int64](Get-RemoteSize $t.url))
    $total += $t.size
    $p = "$($t.file).part"
    if (Test-Path -LiteralPath $p) { $doneBytes += [math]::Min([int64]$t.size, [int64](Get-Item -LiteralPath $p).Length) }
}
Log ("Cần tải {0} file, {1:N1} GB (đã có sẵn {2:N1} GB trong file dở); bỏ qua {3} file đã xong" -f $todo.Count, ($total / 1GB), ($doneBytes / 1GB), $skip)
$script:SessionBytes = [int64]0
$started = Get-Date
try { $env:COLUMNS = [string]([Console]::WindowWidth - 1) } catch { }  # thanh tiến độ curl vừa một dòng
$n = 0
foreach ($t in $todo) {
    $n++
    $kindVi = if ($t.kind -eq "Doc") { "dọc" } else { "ngang" }
    $pct = if ($total -gt 0) { 100 * $doneBytes / $total } else { 0 }
    $Host.UI.RawUI.WindowTitle = ("KĐT {0:N0}% - [{1}/{2}] Tập {3} {4}" -f $pct, $n, $todo.Count, $t.ep, $kindVi)
    Log ("[{0}/{1}] Tập {2} bản {3} ({4:N2} GB): {5}" -f $n, $todo.Count, $t.ep, $kindVi, ($t.size / 1GB), $t.name)
    $partBefore = if (Test-Path -LiteralPath "$($t.file).part") { [math]::Min([int64]$t.size, [int64](Get-Item -LiteralPath "$($t.file).part").Length) } else { [int64]0 }
    $r = Adopt $t.url $t.file $t.key $t.orig
    if (-not $r) { $r = Fetch $t.url $t.file $t.key }
    if ($r) { $ok++; Log "  $r" } else { $failed += $t.name; Log "  THẤT BẠI sau $Retries lần" }
    $doneBytes += $t.size - $partBefore
    $secs = ((Get-Date) - $started).TotalSeconds
    $speed = if ($secs -gt 0) { $script:SessionBytes / $secs } else { 0 }
    $left = $total - $doneBytes
    $eta = if ($speed -gt 0) { $ts = [TimeSpan]::FromSeconds($left / $speed); "{0}:{1:D2}" -f [math]::Floor($ts.TotalHours), $ts.Minutes } else { "?" }
    Log ("  TỔNG: {0:N1} / {1:N1} GB ({2:N0}%), {3}/{4} file, tốc độ TB {5:N1} MB/s, còn khoảng {6} (giờ:phút)" -f ($doneBytes / 1GB), ($total / 1GB), (100.0 * $doneBytes / [math]::Max([double]1, [double]$total)), $n, $todo.Count, ($speed / 1MB), $eta)
}
# Thumbnail cạnh video: "[HD] ... - Tập N.jpg" (16:9) / "[HD Dọc] ... - Tập N.jpg" (9:16), chỉ cho video đã có
$thumbOk = 0; $thumbMissing = @()
foreach ($e in $pl.entries) {
    $epNum = [int]("0" + ($e.episode -replace "\D", ""))
    if ($epNum -lt 1 -or -not $e.video_id) { continue }
    foreach ($pair in @(@("HD", "landscape"), @("Doc", "vertical"))) {
        $video = Join-Path $Dest (BackupName $epNum $pair[0])
        if (-not (Test-Path -LiteralPath $video)) { continue }
        $jpg = [IO.Path]::ChangeExtension($video, ".jpg")
        $url = "/files/episodes/$($e.video_id)/thumbs/$($pair[1]).jpg"
        $got = $false
        for ($i = 1; $i -le 3 -and -not $got; $i++) {
            $code = & $curl -s -b $Jar -o "$jpg.part" -w "%{http_code}" "$Server$url"
            if ($code -eq "200") { Move-Item -Force -LiteralPath "$jpg.part" -Destination $jpg; $got = $true }
            elseif ($code -eq "401") { Login }
            else { break }
        }
        Remove-Item -LiteralPath "$jpg.part" -Force -ErrorAction SilentlyContinue
        if ($got) { $thumbOk++ } else { $thumbMissing += (Split-Path $jpg -Leaf) }
    }
}
Log "Thumbnail: tải $thumbOk ảnh, thiếu $($thumbMissing.Count) (chưa dựng trên server)"
if ($thumbMissing) { Log ("Thiếu thumbnail: " + ($thumbMissing -join ", ")) }

$Host.UI.RawUI.WindowTitle = "KĐT backup xong"
$rows | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $Index
Remove-Item (Join-Path $Dest ".api.json") -Force -ErrorAction SilentlyContinue
Log "=== Xong: tải mới $ok, đã có $skip, lỗi $($failed.Count), chưa sẵn sàng trên server $($notReady.Count)"
if ($failed) { Log ("Lỗi: " + ($failed -join ", ")) }
if ($notReady) { Log ("Chưa sẵn sàng: " + ($notReady -join ", ")) }
[Win32.Power]::SetThreadExecutionState([uint32]2147483648) | Out-Null
