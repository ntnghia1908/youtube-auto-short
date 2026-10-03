<#
.SYNOPSIS
  Sua Enhance Worker: dung / chay lai dung task + tien trinh cua worker, kiem tunnel, chay self-test.

.DESCRIPTION
  Chi dong den task "EnhanceWorker-*" va tien trinh ssh -N gpu-worker-v4 / worker.py.
  Khong dong den tunnel Ollama v4 (dung auto-fix-gpu-v4.ps1 cho viec do).
#>
[CmdletBinding()]
param(
    [Parameter()]
    [string]$InstallDir = "",

    [Parameter()]
    [string]$JumpAlias = "gpu-jump-v4",

    [Parameter()]
    [string]$WorkerAlias = "gpu-worker-v4",

    [Parameter()]
    [ValidateRange(1, 65535)]
    [int]$LocalPort = 18080,

    [Parameter()]
    [string]$TunnelTaskName = "EnhanceWorker-Tunnel",

    [Parameter()]
    [string]$WorkerTaskName = "EnhanceWorker-Worker",

    # Duong dan python.exe cua env conda; bo trong: doc tu worker-wrapper.ps1
    [Parameter()]
    [string]$PythonPath = "",

    [switch]$SkipSelfTest
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Join-Path $env:USERPROFILE "enhance-worker"
}

$AppDir     = Join-Path $InstallDir "app"
$LogDir     = Join-Path $InstallDir "logs"
$ConfigFile = Join-Path $InstallDir "config.json"
$TunnelWrap = Join-Path $InstallDir "tunnel-wrapper.ps1"
$WorkerWrap = Join-Path $InstallDir "worker-wrapper.ps1"
$FixLog     = Join-Path $LogDir "auto-fix.log"
$SshConfig  = Join-Path (Join-Path $env:USERPROFILE ".ssh") "config"

function Write-Info([string]$Message) { Write-Host "[INFO] $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "[ OK ] $Message" -ForegroundColor Green }
function Write-Warn([string]$Message) { Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-Fail([string]$Message) { Write-Host "[ERROR] $Message" -ForegroundColor Red; exit 1 }

function Write-FixLog([string]$Message) {
    try {
        if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
        Add-Content -Path $FixLog -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
    }
    catch {}
}

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $Exe @Arguments 2>$null
        return @{ Code = $LASTEXITCODE; Output = $out }
    }
    finally {
        $ErrorActionPreference = $old
    }
}

function Get-SshPath {
    $cmd = Get-Command ssh.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidate = Join-Path $env:SystemRoot "System32\OpenSSH\ssh.exe"
    if (Test-Path $candidate) { return $candidate }
    return $null
}

function Get-WorkerProcesses {
    $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    return @($procs | Where-Object {
        $c = [string]$_.CommandLine
        ($c -like "*$TunnelWrap*") -or ($c -like "*$WorkerWrap*") -or
        (($_.Name -eq "ssh.exe") -and ($c -match ('-N\s+' + [regex]::Escape($WorkerAlias) + '(\s|$)'))) -or
        (($_.Name -eq "python.exe") -and ($c -like "*$AppDir*worker.py*"))
    })
}

function Stop-WorkerStuff {
    foreach ($n in @($TunnelTaskName, $WorkerTaskName)) {
        try { Stop-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue } catch {}
    }
    Start-Sleep -Seconds 2

    # wrapper truoc (de khong tu sinh lai), roi tien trinh con
    $all = Get-WorkerProcesses
    $wrappers = @($all | Where-Object { $_.Name -eq "powershell.exe" })
    $others = @($all | Where-Object { $_.Name -ne "powershell.exe" })
    foreach ($p in ($wrappers + $others)) {
        try {
            Stop-Process -Id ([int]$p.ProcessId) -Force -ErrorAction Stop
            Write-FixLog "Stopped PID $($p.ProcessId) ($($p.Name))."
        }
        catch {
            Write-Warn "Khong dung duoc PID $($p.ProcessId): $($_.Exception.Message)"
        }
    }
    Start-Sleep -Seconds 1
    Write-Ok "Da dung task + tien trinh cu cua worker."
}

function Test-LocalPort {
    param([int]$Port)
    $c = New-Object Net.Sockets.TcpClient
    try {
        $iar = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne(2000)) {
            $c.EndConnect($iar)
            return $true
        }
        return $false
    }
    catch { return $false }
    finally { $c.Close() }
}

function Test-Auth {
    param([string]$Alias, [string]$Marker, [string]$Layer)
    $ssh = Get-SshPath
    Write-Info "Kiem tra dang nhap SSH: $Layer..."
    $r = Invoke-Native -Exe $ssh -Arguments @("-F", $SshConfig, "-o", "ClearAllForwardings=yes",
        "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", $Alias, "echo $Marker")
    if ($r.Code -ne 0) {
        Write-Fail "$Layer dang nhap that bai (khong phai loi tunnel). Thu auto-fix-gpu-v4.ps1 / kiem tra VM + khoa SSH."
    }
    Write-Ok "$Layer dang nhap duoc."
    Write-FixLog "$Layer auth OK."
}

function Get-PythonFromWrapper {
    if (-not (Test-Path $WorkerWrap)) { return "" }
    $m = [regex]::Match((Get-Content $WorkerWrap -Raw), "\`$Python = '(?<p>[^']+)'")
    if ($m.Success) { return $m.Groups["p"].Value }
    return ""
}

function Show-Status {
    Write-Host ""
    Write-Host "=== Enhance Worker Status ===" -ForegroundColor White
    foreach ($n in @($TunnelTaskName, $WorkerTaskName)) {
        try {
            $t = Get-ScheduledTask -TaskName $n -ErrorAction Stop
            $i = Get-ScheduledTaskInfo -TaskName $n -ErrorAction Stop
            Write-Host ("Task {0}: {1} (last result {2})" -f $n, $t.State, $i.LastTaskResult)
        }
        catch {
            Write-Host "Task ${n}: khong co" -ForegroundColor Yellow
        }
    }
    $procs = @(Get-WorkerProcesses | Where-Object { $_.Name -ne "powershell.exe" })
    if ($procs.Count -gt 0) {
        foreach ($p in $procs) { Write-Host "  PID $($p.ProcessId) $($p.Name)" }
    }
    else {
        Write-Host "Tien trinh ssh / python cua worker: KHONG CHAY" -ForegroundColor Yellow
    }
    if (Test-LocalPort -Port $LocalPort) { Write-Host "Tunnel 127.0.0.1:${LocalPort}: dang nghe" }
    else { Write-Host "Tunnel 127.0.0.1:${LocalPort}: KHONG nghe" -ForegroundColor Yellow }
    Write-Host ""
}

function Show-Logs {
    foreach ($f in @("tunnel.log", "wrapper.log", "worker.log")) {
        $p = Join-Path $LogDir $f
        if (Test-Path $p) {
            Write-Host "--- $f (cuoi) ---" -ForegroundColor Cyan
            Get-Content -Path $p -Tail 15
        }
    }
}

# -----------------------------
# Main
# -----------------------------

Write-Host ""
Write-Host "=== Enhance Worker Auto-Fix ===" -ForegroundColor White
Write-Host ""

if (-not (Get-SshPath)) { Write-Fail "Khong thay OpenSSH Client. Chay setup-gpu-node-v4.ps1 / setup-enhance-worker.ps1 truoc." }
if (-not (Test-Path $SshConfig)) { Write-Fail "Khong thay $SshConfig." }
if (-not (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue)) { Write-Fail "Cmdlet Task Scheduler khong co." }
foreach ($f in @($ConfigFile, $TunnelWrap, $WorkerWrap)) {
    if (-not (Test-Path $f)) { Write-Fail "Thieu $f. Chay setup-enhance-worker.ps1 truoc." }
}
if (-not (Get-ScheduledTask -TaskName $TunnelTaskName -ErrorAction SilentlyContinue) -or
    -not (Get-ScheduledTask -TaskName $WorkerTaskName -ErrorAction SilentlyContinue)) {
    Write-Fail "Chua co task '$TunnelTaskName' / '$WorkerTaskName'. Chay setup-enhance-worker.ps1 truoc."
}

$ssh = Get-SshPath
$r = Invoke-Native -Exe $ssh -Arguments @("-F", $SshConfig, "-G", $WorkerAlias)
if ($r.Code -ne 0 -or -not ((Get-Content $SshConfig -Raw) -match "Host\s+$([regex]::Escape($WorkerAlias))")) {
    Write-Fail "SSH alias '$WorkerAlias' khong dung duoc. Chay lai setup-enhance-worker.ps1."
}
Write-Ok "SSH alias $WorkerAlias hop le."

Write-FixLog "=== Auto-fix started ==="

Test-Auth -Alias $JumpAlias -Marker "ENHANCE_JUMP_AUTH_OK" -Layer "Jump"
Test-Auth -Alias $WorkerAlias -Marker "ENHANCE_SERVER_AUTH_OK" -Layer "VM qua Jump"

Stop-WorkerStuff

Write-Info "Khoi dong task tunnel..."
Start-ScheduledTask -TaskName $TunnelTaskName
$up = $false
for ($i = 0; $i -lt 25; $i++) {
    if (Test-LocalPort -Port $LocalPort) { $up = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $up) {
    Show-Status
    Show-Logs
    Write-Fail "Tunnel khong len cong $LocalPort. Cong dang bi chuong trinh khac dung? Xem log tren."
}
Write-Ok "Tunnel dang nghe tren 127.0.0.1:$LocalPort."
Write-FixLog "Tunnel listening on $LocalPort."

$selfOk = $true
if (-not $SkipSelfTest) {
    if ([string]::IsNullOrWhiteSpace($PythonPath)) { $PythonPath = Get-PythonFromWrapper }
    if (-not $PythonPath -or -not (Test-Path $PythonPath)) {
        Write-Warn "Khong tim thay python.exe cua env conda (dung -PythonPath). Bo qua self-test."
    }
    else {
        Write-Info "Chay self-test..."
        & $PythonPath (Join-Path $AppDir "worker.py") --config $ConfigFile --self-test
        if ($LASTEXITCODE -ne 0) { $selfOk = $false; Write-Warn "Self-test co loi (xem tren)." }
        Write-FixLog "Self-test exit code $LASTEXITCODE."
    }
}

Write-Info "Khoi dong task worker..."
Start-ScheduledTask -TaskName $WorkerTaskName
Start-Sleep -Seconds 5

Show-Status

if ($selfOk) { Write-Ok "Enhance Worker da duoc khoi dong lai." }
else { Write-Warn "Worker da chay lai nhung self-test chua dat; xem log:" ; Show-Logs }
Write-Host ""
Write-Host "Log: $LogDir" -ForegroundColor Cyan
