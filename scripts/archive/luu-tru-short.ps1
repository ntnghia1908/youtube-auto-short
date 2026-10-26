#requires -Version 5.1
# Lưu trữ mọi tập có cả Short và khai thị; không đánh dấu "Đã đăng" trên web.
# Chạy lại: bỏ qua ZIP có cùng vân tay trong danh-sach.csv và còn file trên ổ đích.
# powershell -ExecutionPolicy Bypass -File .\luu-tru-short.ps1 -Dest E:\LuuTru_Short
param(
    [string]$Server = 'http://10.8.102.102:8080',
    [string]$Dest = 'E:\LuuTru_Short',
    [ValidateRange(1, 100)][int]$Retries = 5
)
$ErrorActionPreference = 'Stop'
$Server = $Server.TrimEnd('/')
$drives = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -gt 0 }
$qual = Split-Path -Qualifier $Dest -ErrorAction SilentlyContinue
if (-not $qual -or -not ($drives | Where-Object { "$($_.Name):" -eq $qual })) {
    Write-Host "Ổ đích '$qual' không dùng được. Chạy lại với -Dest <ổ đĩa>\LuuTru_Short"
    $drives | ForEach-Object { Write-Host ("  {0}: còn {1:N1} GB" -f $_.Name, ($_.Free / 1GB)) }
    exit 2
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$Dest = (Resolve-Path -LiteralPath $Dest).Path
$Log = Join-Path $Dest 'luu-tru-log.txt'
$Index = Join-Path $Dest 'danh-sach.csv'
$tempId = [guid]::NewGuid().ToString('N')
$Jar = Join-Path $Dest ".archive-$tempId.cookies"
$Api = Join-Path $Dest ".archive-$tempId.json"
$IndexPart = Join-Path $Dest ".archive-$tempId.csv"
$curl = (Get-Command curl.exe -ErrorAction SilentlyContinue).Source
if (-not $curl) { throw 'Không thấy curl.exe (cần Windows 10 1803 trở lên)' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
# ES_CONTINUOUS | ES_SYSTEM_REQUIRED; khôi phục trong finally kể cả khi gặp lỗi.
if (-not ('Win32.Power' -as [type])) {
    Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
}

function Log($msg) {
    $line = '{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $msg
    Write-Host $line
    Add-Content -LiteralPath $Log -Value $line -Encoding UTF8
}

function Login {
    if (-not $script:Password) {
        $sec = Read-Host 'Mật khẩu web 8080' -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
        try { $script:Password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    }
    $pw = Join-Path $env:TEMP ("archive-pw-$tempId.txt")
    try {
        # curl đọc mật khẩu từ file, không đưa mật khẩu lên dòng lệnh.
        [IO.File]::WriteAllText($pw, $script:Password, (New-Object Text.UTF8Encoding($false)))
        $code = & $curl -sS --connect-timeout 30 --max-time 60 -o NUL -w '%{http_code}' -c $Jar --data-urlencode "password@$pw" --data-urlencode 'next=/' "$Server/login"
        if ($LASTEXITCODE -ne 0 -or $code -ne '303') {
            $script:Password = $null
            throw "Đăng nhập thất bại (HTTP $code)"
        }
    } finally { Remove-Item -LiteralPath $pw -Force -ErrorAction SilentlyContinue }
}

function Get-Zips {
    for ($i = 1; $i -le $Retries; $i++) {
        try {
            $code = & $curl -sS --connect-timeout 30 --max-time 120 -o $Api -w '%{http_code}' -b $Jar "$Server/api/archive/zips"
            if ($LASTEXITCODE -eq 0 -and $code -eq '200') {
                return (Get-Content -LiteralPath $Api -Raw -Encoding UTF8 | ConvertFrom-Json)
            }
            if ($code -eq '401') { Login }
            else { throw "HTTP $code" }
        } catch { Log "Lấy danh sách lỗi (lần $i/$Retries): $_" }
        if ($i -lt $Retries) { Start-Sleep -Seconds 60 }
    }
    throw 'Không lấy được danh sách ZIP'
}

function Replace-File($part, $file) {
    # Cùng ổ đĩa: chỉ thay bản cũ sau khi bản mới đã hoàn tất và kiểm tra xong.
    if (Test-Path -LiteralPath $file -PathType Leaf) { [IO.File]::Replace($part, $file, $null) }
    else { [IO.File]::Move($part, $file) }
}

function Fetch-Zip($item, $file) {
    $part = "$file.part"
    for ($i = 1; $i -le $Retries; $i++) {
        try {
            # ZIP stream không có Content-Length / Range: mỗi lần thử tải lại từ đầu.
            $code = & $curl --progress-bar -S --connect-timeout 30 -o $part -w '%{http_code}' -b $Jar "$Server$($item.url)"
            $rc = $LASTEXITCODE
            if ($code -eq '401') { Login; throw 'Cookie hết hạn, thử tải lại' }
            if ($rc -ne 0 -or $code -ne '200') { throw "curl $rc, HTTP $code" }
            $zip = [IO.Compression.ZipFile]::OpenRead($part)
            try {
                $size = [int64]0
                foreach ($entry in $zip.Entries) { $size += [int64]$entry.Length }
                if ($zip.Entries.Count -ne [int]$item.files -or $size -ne [int64]$item.bytes) {
                    throw "ZIP thiếu / khác file: $($zip.Entries.Count)/$($item.files) entry, $size/$($item.bytes) byte"
                }
            } finally { $zip.Dispose() }
            $downloaded = (Get-Item -LiteralPath $part).Length
            Replace-File $part $file
            return [int64]$downloaded
        } catch { Log "  Tải / kiểm ZIP lỗi (lần $i/$Retries): $_" }
        # File không hợp lệ không được giữ lại, bản ZIP cũ vẫn nguyên vẹn.
        Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
        if ($i -lt $Retries) { Start-Sleep -Seconds 60 }
    }
    return $null
}

$ok = 0; $skip = 0; $failed = 0; $savedBytes = [int64]0; $skippedBytes = [int64]0
[Win32.Power]::SetThreadExecutionState([uint32]2147483649) | Out-Null
try {
    Log "=== Bắt đầu: $Server -> $Dest"
    Login
    $items = @(Get-Zips)
    $rows = @{}
    # Giữ cả dòng cũ không còn trên server; chỉ ghi đè dòng sau khi ZIP mới hợp lệ.
    if (Test-Path -LiteralPath $Index) {
        foreach ($row in (Import-Csv -LiteralPath $Index -Encoding UTF8)) { $rows[$row.video_id] = $row }
    }
    Log "Có $($items.Count) tập đủ Short + khai thị"
    foreach ($item in $items) {
        try {
            # Tên bộ kinh từ API đã làm sạch giống tên ZIP; bảo vệ cả tên thư mục đặc biệt của Windows.
            $folder = ([string]$item.series).TrimEnd([char[]]' .')
            if (-not $folder) { $folder = 'Chua_ro_bo_kinh' }
            if ($folder -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') { $folder = "_$folder" }
            if ($folder.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0 -or
                [IO.Path]::GetFileName([string]$item.name) -ne $item.name) { throw 'Tên thư mục / ZIP không hợp lệ' }
            $dir = Join-Path $Dest $folder
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            $file = Join-Path $dir $item.name
            $old = $rows[$item.video_id]
            if ($old -and $old.fingerprint -eq $item.fingerprint -and $old.series -eq $item.series -and
                $old.name -eq $item.name -and (Test-Path -LiteralPath $file -PathType Leaf)) {
                $skip++; $skippedBytes += [int64]$item.bytes
                Log "Bỏ qua: $($item.name)"
                continue
            }
            Remove-Item -LiteralPath "$file.part" -Force -ErrorAction SilentlyContinue
            $free = (Get-PSDrive -Name ($qual.TrimEnd(':'))).Free
            # Cần chỗ cho toàn bộ .part bên cạnh bản cũ; dự phòng phần header ZIP.
            if ($free -lt ([int64]$item.bytes + [int64]$item.files * 1024 + 1MB)) { throw 'Ổ đích không đủ chỗ trống' }
            Log ("Tải {0} ({1:N2} GB)" -f $item.name, ([int64]$item.bytes / 1GB))
            $got = Fetch-Zip $item $file
            if ($null -eq $got) { throw "Thất bại sau $Retries lần" }
            $rows[$item.video_id] = [pscustomobject]@{
                video_id = $item.video_id; series = $item.series; episode = $item.episode
                name = $item.name; files = $item.files; bytes = $item.bytes
                fingerprint = $item.fingerprint; downloaded_at = (Get-Date).ToString('o')
            }
            $rows.Values | Sort-Object series, episode, video_id |
                Select-Object video_id, series, episode, name, files, bytes, fingerprint, downloaded_at |
                Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath $IndexPart
            Replace-File $IndexPart $Index
            $ok++; $savedBytes += [int64]$got
            Log '  Đã kiểm đủ entry và dung lượng, đã cập nhật CSV'
        } catch { $failed++; Log "LỖI $($item.video_id): $_" }
    }
    Log ("=== Xong: đã tải {0}, bỏ qua {1}, lỗi {2}; ZIP mới {3:N2} GB, dữ liệu bỏ qua {4:N2} GB" -f $ok, $skip, $failed, ($savedBytes / 1GB), ($skippedBytes / 1GB))
} finally {
    Remove-Item -LiteralPath $Jar, $Api, $IndexPart -Force -ErrorAction SilentlyContinue
    $script:Password = $null
    [Win32.Power]::SetThreadExecutionState([uint32]2147483648) | Out-Null
}
if ($failed) { exit 1 }
