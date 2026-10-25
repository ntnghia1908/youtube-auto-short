<#
.SYNOPSIS
  Cai kho HD2 tren Windows, dung Python cua enhance worker (khong tai dependency).
.EXAMPLE
  .\setup-store.ps1 -Root E:\AutoShortStore -SeriesDir E:\KinhDiaTang_HD
  .\setup-store.ps1 -Python C:\Users\me\miniconda3\envs\enhance-worker\python.exe
  .\setup-store.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$Python = "",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "AutoShortStore"),
    [string]$Root = "E:\AutoShortStore",
    [string]$SeriesDir = "E:\KinhDiaTang_HD",
    [string]$TaskName = "AutoShortStore",
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$ConfigFile = Join-Path $InstallDir "config.json"
$StoreFile = Join-Path $InstallDir "store.py"
$SshConfig = Join-Path $env:USERPROFILE ".ssh\config"
$Utf8 = New-Object Text.UTF8Encoding($false)

function Info([string]$Message) { Write-Host "[INFO] $Message" -ForegroundColor Cyan }
function Ok([string]$Message) { Write-Host "[ OK ] $Message" -ForegroundColor Green }

if ($Uninstall) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Ok "Da go task '$TaskName'. Giu nguyen file, token va SSH config."
    exit 0
}

function Find-WorkerPython {
    if ($Python) {
        if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Khong thay -Python: $Python" }
        return (Resolve-Path -LiteralPath $Python).Path
    }
    # Worker setup luu duong dan Python thuc te trong wrapper.
    $wrapper = Join-Path $env:USERPROFILE "enhance-worker\worker-wrapper.ps1"
    if (Test-Path -LiteralPath $wrapper) {
        $match = [regex]::Match([IO.File]::ReadAllText($wrapper), '(?m)^\$Python\s*=\s*''([^'']+)''')
        if ($match.Success -and (Test-Path -LiteralPath $match.Groups[1].Value -PathType Leaf)) {
            return $match.Groups[1].Value
        }
    }
    $candidates = @()
    foreach ($base in @($env:USERPROFILE, $env:LOCALAPPDATA, $env:ProgramData)) {
        foreach ($distribution in @("miniconda3", "anaconda3")) {
            $candidates += Join-Path $base "$distribution\envs\enhance-worker\python.exe"
        }
    }
    if ($env:CONDA_PREFIX -and (Split-Path -Leaf $env:CONDA_PREFIX) -eq "enhance-worker") {
        $candidates += Join-Path $env:CONDA_PREFIX "python.exe"
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    $conda = Get-Command conda.exe -ErrorAction SilentlyContinue
    if ($conda) {
        $listing = & $conda.Source env list --json
        if ($LASTEXITCODE -eq 0) {
            foreach ($folder in (($listing | Out-String | ConvertFrom-Json).envs)) {
                if ((Split-Path -Leaf $folder) -eq "enhance-worker") {
                    $candidate = Join-Path $folder "python.exe"
                    if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
                }
            }
        }
    }
    throw "Khong tim thay Python worker. Chay lai voi -Python <duong-dan-python.exe>."
}

function Update-SshConfig([int]$Port) {
    if (-not (Test-Path -LiteralPath $SshConfig)) { throw "Thieu $SshConfig; cai enhance worker truoc." }
    $content = [IO.File]::ReadAllText($SshConfig)
    $pattern = '(?ims)^(?<header>[ \t]*Host[ \t]+gpu-worker-v4[ \t]*(?:\r?\n|$))(?<body>.*?)(?=^[ \t]*(?:Host|Match)[ \t]+|\z)'
    $blocks = [regex]::Matches($content, $pattern)
    if ($blocks.Count -ne 1) { throw "Can dung mot block Host gpu-worker-v4 trong SSH config." }
    $block = $blocks[0]
    $forward = "    RemoteForward 127.0.0.1:$Port 127.0.0.1:$Port"
    $existing = '(?im)^[ \t]*RemoteForward[ \t]+127\.0\.0\.1:' + $Port + '[ \t]+127\.0\.0\.1:' + $Port + '[ \t]*(?:#.*)?\r?$'
    if ([regex]::IsMatch($block.Value, $existing)) {
        Ok "RemoteForward da co (giu nguyen SSH config)."
        return
    }
    $conflict = '(?im)^[ \t]*RemoteForward[ \t]+(?:\S+:)?' + $Port + '[ \t]+'
    if ([regex]::IsMatch($block.Value, $conflict)) { throw "RemoteForward cong $Port da co dich khac; kiem tra SSH config." }
    $backup = "$SshConfig.store-$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString('N')).bak"
    Copy-Item -LiteralPath $SshConfig -Destination $backup
    $header = $block.Groups["header"].Value.TrimEnd([char[]]"`r`n")
    $replacement = $header + "`r`n" + $forward + "`r`n" + $block.Groups["body"].Value
    $updated = $content.Substring(0, $block.Index) + $replacement + $content.Substring($block.Index + $block.Length)
    [IO.File]::WriteAllText($SshConfig, $updated, $Utf8)
    Ok "Da them RemoteForward; backup: $backup"
}

$py = Find-WorkerPython
& $py -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Can Python >= 3.11." }
Info "Python: $py"
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot "store.py")) -ne [IO.Path]::GetFullPath($StoreFile)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "store.py") -Destination $StoreFile -Force
}
if (-not (Test-Path -LiteralPath $ConfigFile)) {
    $cfg = Get-Content -LiteralPath (Join-Path $PSScriptRoot "config.example.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $cfg.root = $Root
    $cfg.series.'PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4' = $SeriesDir
    [IO.File]::WriteAllText($ConfigFile, ($cfg | ConvertTo-Json -Depth 5), $Utf8)
    Ok "Da tao config.json."
} else {
    Info "Giu config.json hien co; -Root / -SeriesDir chi dung lan cai dau."
}
$cfg = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
function Config-Path([string]$Value) {
    if ([IO.Path]::IsPathRooted($Value)) { return $Value }
    return Join-Path $InstallDir $Value
}
New-Item -ItemType Directory -Path (Config-Path $cfg.root) -Force | Out-Null
foreach ($property in $cfg.series.PSObject.Properties) {
    New-Item -ItemType Directory -Path (Config-Path $property.Value) -Force | Out-Null
}
$tokenPath = Config-Path $cfg.token_file
if (-not (Test-Path -LiteralPath $tokenPath)) {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $newToken = [BitConverter]::ToString($bytes).Replace("-", "").ToLowerInvariant()
    [IO.File]::WriteAllText($tokenPath, $newToken, $Utf8)
    # Chi in khi tao moi; cac lan chay lai khong doc / in token.
    Write-Host ""
    Write-Host "TOKEN MOI (chi in lan nay): $newToken" -ForegroundColor Yellow
    Write-Host "Tren VM, them dong sau vao ~/.local/share/auto-short/store.env (ngoai git):"
    Write-Host 'AUTO_SHORT_STORE_TOKEN=<dan token vua in o tren>'
    Write-Host "Dat quyen chmod 600; nap file env nay vao tien trinh web tren VM."
    $newToken = $null
}
$who = "$env:USERDOMAIN\$env:USERNAME"
& icacls.exe $tokenPath /inheritance:r /grant:r "${who}:(R,W)" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Khong dat duoc quyen token cho user hien tai." }

# Self-test truoc khi dang ky/chay task, khong mo socket.
& $py $StoreFile --config $ConfigFile --self-test
if ($LASTEXITCODE -ne 0) { throw "Self-test that bai; kiem tra config, token va thu muc." }
Update-SshConfig -Port ([int]$cfg.port)
$action = New-ScheduledTaskAction -Execute $py -WorkingDirectory $InstallDir `
    -Argument "-u `"$StoreFile`" --config `"$ConfigFile`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $who
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $who -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Kho HD2 (loopback), tu chay khi dang nhap."
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Ok "Task Scheduler: $TaskName"
Info "Khoi dong lai tunnel task EnhanceWorker-Tunnel de nap RemoteForward (Restart / End roi Run trong Task Scheduler)."
Info "Cac lan chay lai giu token. -Uninstall chi go task, giu file va token."
# Kiem tra lai ban cai dat o cuoi script.
& $py $StoreFile --config $ConfigFile --self-test
if ($LASTEXITCODE -ne 0) { throw "Self-test cuoi that bai." }
Ok "Cai kho xong."
