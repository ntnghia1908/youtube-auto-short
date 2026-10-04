<#
.SYNOPSIS
  Cai Enhance Worker (CP13.1a) tren may Windows co GPU NVIDIA.

.DESCRIPTION
  - Tim Miniconda, tao / dung env conda rieng (mac dinh "enhance-worker", Python 3.11),
    pip cai torch (CUDA) + numpy + opencv-python-headless trong env do.
  - Kiem ffmpeg co NVENC (tai ban build neu thieu), tai trong so realesr-general-x4v3 (kiem sha256).
  - Them block SSH rieng "Enhance Worker v1" (Host gpu-worker-v4, LocalForward 18080 -> VM 8080);
    KHONG sua block / task Ollama v4.
  - Dang ky 2 Task Scheduler rieng (tunnel + worker), tu chay khi dang nhap, tu khoi dong lai.
  - CP13.4: cai them gfpgan + facexlib + basicsr (chi trong env cua worker) va tai trong so GFPGAN v1.4 +
    RetinaFace + ParseNet (kiem sha256) de worker v3 nhan viec "phuc hoi mat". Bo qua bang -SkipFace.
  - Cuoi cung chay worker.py --self-test (phai bao "GFPGAN OK" tru khi -SkipFace).

  Chay trong thu muc `tools\enhance_worker\windows` (da chep ca thu muc `enhance_worker` sang may nay).
  Huong dan: docs/guides/enhance-worker-windows.md

.EXAMPLE
  .\setup-enhance-worker.ps1 -WorkerName rtx3090 -YieldToOllama
  .\setup-enhance-worker.ps1 -WorkerName rtx3050
  .\setup-enhance-worker.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [Parameter()]
    [string]$WorkerName = "",

    [switch]$YieldToOllama,

    # Token do VM cap (CP13.1b). Bo trong: dung token da luu, hoac hoi.
    [Parameter()]
    [string]$Token = "",

    [Parameter()]
    [string]$JumpAlias = "gpu-jump-v4",

    [Parameter()]
    [string]$ServerAlias = "gpu-server-v4",

    # Mac dinh lay tu block "Host gpu-server-v4" co san trong ~/.ssh/config
    [Parameter()]
    [string]$ServerHost = "",

    [Parameter()]
    [string]$ServerUser = "",

    [Parameter()]
    [ValidateRange(1, 65535)]
    [int]$LocalPort = 18080,

    [Parameter()]
    [ValidateRange(1, 65535)]
    [int]$RemotePort = 8080,

    [Parameter()]
    [string]$InstallDir = "",

    # conda.exe hoac thu muc goc Miniconda; bo trong: tu tim
    [Parameter()]
    [string]$CondaPath = "",

    [Parameter()]
    [string]$EnvName = "enhance-worker",

    [Parameter()]
    [string]$PythonVersion = "3.11",

    [Parameter()]
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu121",

    [Parameter()]
    [ValidateRange(1, 64)]
    [int]$BatchSize = 4,

    [Parameter()]
    [ValidateRange(5, 100000)]
    [int]$MaxDiskGb = 100,

    [Parameter()]
    [ValidateRange(0, 15)]
    [int]$CudaDevice = 0,

    [Parameter()]
    [string]$FfmpegPath = "",

    [Parameter()]
    [string]$TunnelTaskName = "EnhanceWorker-Tunnel",

    [Parameter()]
    [string]$WorkerTaskName = "EnhanceWorker-Worker",

    [switch]$SkipTorch,
    # CP13.4: khong cai GFPGAN (phuc hoi mat); worker van chay viec thuong, khong nhan viec co mat
    [switch]$SkipFace,
    [switch]$SkipSelfTest,
    [switch]$NoTask,

    # Chi cho -Uninstall
    [switch]$KeepData,
    [switch]$RemoveEnv,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Join-Path $env:USERPROFILE "enhance-worker"
}

$AppDir      = Join-Path $InstallDir "app"
$ModelsDir   = Join-Path $InstallDir "models"
$WorkDir     = Join-Path $InstallDir "work"
$LogDir      = Join-Path $InstallDir "logs"
$FfmpegDir   = Join-Path $InstallDir "ffmpeg"
$ConfigFile  = Join-Path $InstallDir "config.json"
$TunnelWrap  = Join-Path $InstallDir "tunnel-wrapper.ps1"
$WorkerWrap  = Join-Path $InstallDir "worker-wrapper.ps1"
$SourceDir   = Split-Path -Parent $PSScriptRoot

$SshDir      = Join-Path $env:USERPROFILE ".ssh"
$SshConfig   = Join-Path $SshDir "config"
$WorkerAlias = "gpu-worker-v4"
$BlockStart  = "# >>> Enhance Worker v1 >>>"
$BlockEnd    = "# <<< Enhance Worker v1 <<<"
$BlockRegex  = '(?ms)# >>> Enhance Worker v1 >>>.*?# <<< Enhance Worker v1 <<<\r?\n?'

$WeightsBase = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0"
$Weights = @(
    @{ Name = "realesr-general-x4v3.pth";     Sha256 = "8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292" },
    @{ Name = "realesr-general-wdn-x4v3.pth"; Sha256 = "1641f8c4464b9f097c9fdda5589273713f67cf59f3d909e0bd688f0cee269dca" }
)
# CP13.4: phuc hoi mat GFPGAN v1.4 (Apache-2.0) + facexlib (MIT); facexlib doc models\facexlib\weights\
$FaceWeights = @(
    @{ Name = "GFPGANv1.4.pth"; Rel = "GFPGANv1.4.pth"; Sha256 = "e2cd4703ab14f4d01fd1383a8a8b266f9a5833dacee8e6a79d3bf21a1b6be5ad";
       Url = "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth" },
    @{ Name = "detection_Resnet50_Final.pth"; Rel = "facexlib\weights\detection_Resnet50_Final.pth"; Sha256 = "6d1de9c2944f2ccddca5f5e010ea5ae64a39845a86311af6fdf30841b0a5a16d";
       Url = "https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth" },
    @{ Name = "parsing_parsenet.pth"; Rel = "facexlib\weights\parsing_parsenet.pth"; Sha256 = "3d558d8d0e42c20224f13cf5a29c79eba2d59913419f945545d8cf7b72920de2";
       Url = "https://github.com/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth" }
)
$FfmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

function Info([string]$Message) { Write-Host "[INFO] $Message" -ForegroundColor Cyan }
function Ok([string]$Message)   { Write-Host "[ OK ] $Message" -ForegroundColor Green }
function Warn([string]$Message) { Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Fail([string]$Message) { Write-Host "[ERROR] $Message" -ForegroundColor Red; exit 1 }

# Chay lenh native, bo qua stderr khi $ErrorActionPreference = Stop (Windows PowerShell 5.1).
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

function Get-SshHostValue {
    param([string]$Content, [string]$HostAlias, [string]$Key)
    $hostPattern = '(?ms)(?:^|\r?\n)[ \t]*Host[ \t]+' + [regex]::Escape($HostAlias) +
        '[ \t]*\r?\n(?<block>.*?)(?=\r?\n[ \t]*Host[ \t]+|\z)'
    $m = [regex]::Match($Content, $hostPattern)
    if (-not $m.Success) { return "" }
    $kv = [regex]::Match($m.Groups["block"].Value, '(?im)^[ \t]*' + [regex]::Escape($Key) + '[ \t]+(?<v>\S+)[ \t]*$')
    if (-not $kv.Success) { return "" }
    return $kv.Groups["v"].Value
}

function Stop-EnhanceProcesses {
    # Dung dung tien trinh cua worker (wrapper truoc, roi ssh -N gpu-worker-v4 / python worker.py).
    # Khong dung toi ssh / task cua Ollama v4.
    $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $wrappers = @($procs | Where-Object {
        $c = [string]$_.CommandLine
        ($c -like "*$TunnelWrap*") -or ($c -like "*$WorkerWrap*")
    })
    foreach ($p in $wrappers) {
        try { Stop-Process -Id ([int]$p.ProcessId) -Force -ErrorAction Stop } catch {}
    }
    Start-Sleep -Milliseconds 500
    $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $children = @($procs | Where-Object {
        $c = [string]$_.CommandLine
        (($_.Name -eq "ssh.exe") -and ($c -match ('-N\s+' + [regex]::Escape($WorkerAlias) + '(\s|$)'))) -or
        (($_.Name -eq "python.exe") -and ($c -like "*$AppDir*worker.py*"))
    })
    foreach ($p in $children) {
        try { Stop-Process -Id ([int]$p.ProcessId) -Force -ErrorAction Stop } catch {}
    }
}

function Find-Conda {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($CondaPath)) {
        if (Test-Path $CondaPath -PathType Leaf) { $candidates += $CondaPath }
        else { $candidates += (Join-Path $CondaPath "Scripts\conda.exe") }
    }
    else {
        $cmd = Get-Command conda.exe -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += $cmd.Source }
        $candidates += (Join-Path $env:USERPROFILE "miniconda3\Scripts\conda.exe")
        $candidates += (Join-Path $env:LOCALAPPDATA "miniconda3\Scripts\conda.exe")
        $candidates += (Join-Path $env:ProgramData "miniconda3\Scripts\conda.exe")
    }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    Fail ("Khong tim thay Miniconda (conda.exe). Cai Miniconda (https://docs.conda.io/en/latest/miniconda.html, " +
          "ban Windows 64-bit, 'Just Me'), mo lai PowerShell roi chay lai; hoac chi dinh -CondaPath <conda.exe hoac thu muc Miniconda>. " +
          "Script khong tu cai Python.")
}

function Get-CondaEnvPath {
    param([string]$Conda, [string]$Name)
    $r = Invoke-Native -Exe $Conda -Arguments @("env", "list", "--json")
    if ($r.Code -ne 0) { return "" }
    try {
        $json = ($r.Output | Out-String) | ConvertFrom-Json
    }
    catch { return "" }
    foreach ($e in $json.envs) {
        if ((Split-Path -Leaf $e) -eq $Name) { return $e }
    }
    return ""
}

function Ensure-Env {
    $conda = Find-Conda
    Ok "conda: $conda"

    $envPath = Get-CondaEnvPath -Conda $conda -Name $EnvName
    if (-not $envPath) {
        Info "Tao env conda '$EnvName' (python=$PythonVersion, kenh conda-forge)..."
        & $conda create -y -n $EnvName "python=$PythonVersion" -c conda-forge --override-channels | Out-Host
        if ($LASTEXITCODE -ne 0) { Fail "conda create that bai." }
        $envPath = Get-CondaEnvPath -Conda $conda -Name $EnvName
    }
    if (-not $envPath) { Fail "Khong tim thay env '$EnvName' sau khi tao." }

    $py = Join-Path $envPath "python.exe"
    if (-not (Test-Path $py)) { Fail "Khong thay python.exe trong env: $envPath" }
    $ver = (Invoke-Native -Exe $py -Arguments @("--version")).Output | Out-String
    Ok "Env '$EnvName': $py ($($ver.Trim()))"
    if ($ver -notmatch [regex]::Escape($PythonVersion)) {
        Warn "Env khong phai Python $PythonVersion; van tiep tuc (PyTorch cu121 can 3.9-3.12)."
    }
    return $py
}

function Ensure-Packages {
    param([string]$Py)

    $probe = "import torch; print(torch.cuda.is_available())"
    $r = Invoke-Native -Exe $Py -Arguments @("-c", $probe)
    $hasTorch = ($r.Code -eq 0)
    $hasCuda = $hasTorch -and (($r.Output | Out-String).Trim() -eq "True")

    if ($SkipTorch) {
        Info "Bo qua cai torch (-SkipTorch)."
    }
    elseif ($hasCuda) {
        Ok "PyTorch CUDA da co trong env."
    }
    else {
        if ($hasTorch) { Warn "Env co torch nhung khong co CUDA -> cai lai ban CUDA." }
        Info "Cai PyTorch (CUDA) tu $TorchIndexUrl (~2.5 GB)..."
        & $Py -m pip install --upgrade pip | Out-Host
        & $Py -m pip install --upgrade --force-reinstall torch --index-url $TorchIndexUrl | Out-Host
        if ($LASTEXITCODE -ne 0) { Fail "pip install torch that bai." }
    }

    Info "Cai numpy + opencv-python-headless..."
    & $Py -m pip install numpy opencv-python-headless | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "pip install numpy / opencv that bai." }

    $r = Invoke-Native -Exe $Py -Arguments @("-c", "import torch, numpy, cv2; print(torch.__version__, torch.cuda.is_available())")
    if ($r.Code -ne 0) { Fail "Khong import duoc torch / numpy / cv2 trong env." }
    Ok "Thu vien: $(($r.Output | Out-String).Trim())"
    if (-not $SkipTorch -and (($r.Output | Out-String) -notmatch "True")) {
        Warn "torch.cuda.is_available() = False. Kiem tra driver NVIDIA (nvidia-smi); worker se khong chay duoc tren GPU."
    }
}

function Ensure-FacePackages {
    # CP13.4: chi trong env cua worker. --no-deps de khong keo opencv-python (trung opencv-python-headless) va
    # tb-nightly; chi cai nhung goi ma buoc mat thuc su import (face.py). basicsr bien dich loi tren mot so may
    # Windows ("KeyError: __version__") -> thu ban basicsr-fixed.
    param([string]$Py)
    if ($SkipFace) { Info "Bo qua GFPGAN (-SkipFace)."; return }
    $probe = "import sys; sys.path.insert(0, r'$SourceDir'); import face; face.shim_basicsr(); import basicsr, facexlib; from gfpgan.archs.gfpganv1_clean_arch import GFPGANv1Clean; print('ok')"
    $r = Invoke-Native -Exe $Py -Arguments @("-c", $probe)
    if ($r.Code -eq 0) { Ok "GFPGAN / facexlib / basicsr da co trong env."; return }
    Info "Cai torchvision + goi phu cua GFPGAN..."
    & $Py -m pip install --upgrade torchvision --index-url $TorchIndexUrl | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "pip install torchvision that bai." }
    & $Py -m pip install scipy pyyaml requests tqdm pillow addict future | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "pip install goi phu (scipy, pyyaml, ...) that bai." }
    Info "Cai basicsr + facexlib + gfpgan (--no-deps)..."
    & $Py -m pip install --no-deps basicsr facexlib gfpgan | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Warn "pip install basicsr that bai -> thu basicsr-fixed."
        & $Py -m pip install --no-deps basicsr-fixed facexlib gfpgan | Out-Host
        if ($LASTEXITCODE -ne 0) { Fail "Khong cai duoc basicsr / basicsr-fixed + facexlib + gfpgan. Gui dong loi cho ORCHESTRATOR hoac chay lai voi -SkipFace." }
    }
    $r = Invoke-Native -Exe $Py -Arguments @("-c", $probe)
    if ($r.Code -ne 0) { Fail "Khong import duoc gfpgan / facexlib / basicsr sau khi cai: $(($r.Output | Out-String).Trim())" }
    Ok "GFPGAN / facexlib / basicsr: import duoc."
}

function Test-FfmpegNvenc {
    param([string]$Exe)
    $r = Invoke-Native -Exe $Exe -Arguments @("-hide_banner", "-encoders")
    return (($r.Code -eq 0) -and (($r.Output | Out-String) -match "h264_nvenc"))
}

function Ensure-Ffmpeg {
    $exe = ""
    if (-not [string]::IsNullOrWhiteSpace($FfmpegPath)) {
        if (-not (Test-Path $FfmpegPath)) { Fail "Khong thay -FfmpegPath: $FfmpegPath" }
        $exe = $FfmpegPath
    }
    else {
        $local = Get-ChildItem -Path $FfmpegDir -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($local) { $exe = $local.FullName }
        else {
            $cmd = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
            if ($cmd) { $exe = $cmd.Source }
        }
    }

    if ($exe -and (Test-FfmpegNvenc $exe)) {
        Ok "ffmpeg co NVENC: $exe"
        return $exe
    }
    if ($exe) { Warn "ffmpeg tim thay ($exe) nhung khong co h264_nvenc -> tai ban build co NVENC." }

    Info "Tai ffmpeg (ban build gyan.dev, co NVENC, ~100 MB)..."
    New-Item -ItemType Directory -Path $FfmpegDir -Force | Out-Null
    $zip = Join-Path $FfmpegDir "ffmpeg.zip"
    Invoke-WebRequest -Uri $FfmpegUrl -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $FfmpegDir -Force
    Remove-Item $zip -Force
    $found = Get-ChildItem -Path $FfmpegDir -Recurse -Filter ffmpeg.exe | Select-Object -First 1
    if (-not $found) { Fail "Khong thay ffmpeg.exe sau khi giai nen. Tu tai ffmpeg co NVENC roi dung -FfmpegPath." }
    if (-not (Test-FfmpegNvenc $found.FullName)) {
        Warn "ffmpeg vua tai khong liet ke h264_nvenc. Worker se dung libx264 (CPU, cham hon)."
    }
    else {
        Ok "ffmpeg co NVENC: $($found.FullName)"
    }
    return $found.FullName
}

function Ensure-Weights {
    New-Item -ItemType Directory -Path $ModelsDir -Force | Out-Null
    foreach ($w in $Weights) {
        $dest = Join-Path $ModelsDir $w.Name
        if (Test-Path $dest) {
            if ((Get-FileHash -Path $dest -Algorithm SHA256).Hash.ToLower() -eq $w.Sha256) {
                Ok "Trong so da co, sha256 khop: $($w.Name)"
                continue
            }
            Warn "Trong so sai sha256, tai lai: $($w.Name)"
            Remove-Item $dest -Force
        }
        Info "Tai trong so $($w.Name)..."
        Invoke-WebRequest -Uri "$WeightsBase/$($w.Name)" -OutFile $dest -UseBasicParsing
        $h = (Get-FileHash -Path $dest -Algorithm SHA256).Hash.ToLower()
        if ($h -ne $w.Sha256) {
            Remove-Item $dest -Force
            Fail "sha256 trong so $($w.Name) khong khop (nhan $h). Khong dung file nay."
        }
        Ok "Trong so OK: $($w.Name)"
    }
}

function Ensure-FaceWeights {
    if ($SkipFace) { return }
    foreach ($w in $FaceWeights) {
        $dest = Join-Path $ModelsDir $w.Rel
        New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
        if (Test-Path $dest) {
            if ((Get-FileHash -Path $dest -Algorithm SHA256).Hash.ToLower() -eq $w.Sha256) {
                Ok "Trong so da co, sha256 khop: $($w.Rel)"
                continue
            }
            Warn "Trong so sai sha256, tai lai: $($w.Rel)"
            Remove-Item $dest -Force
        }
        Info "Tai trong so $($w.Name)..."
        Invoke-WebRequest -Uri $w.Url -OutFile $dest -UseBasicParsing
        $h = (Get-FileHash -Path $dest -Algorithm SHA256).Hash.ToLower()
        if ($h -ne $w.Sha256) {
            Remove-Item $dest -Force
            Fail "sha256 trong so $($w.Name) khong khop (nhan $h). Khong dung file nay."
        }
        Ok "Trong so OK: $($w.Rel)"
    }
}

function Copy-App {
    foreach ($f in @("worker.py", "srvgg.py", "face.py")) {
        $src = Join-Path $SourceDir $f
        if (-not (Test-Path $src)) { Fail "Khong thay $src. Chep ca thu muc tools\enhance_worker sang may nay." }
    }
    New-Item -ItemType Directory -Path $AppDir -Force | Out-Null
    Copy-Item (Join-Path $SourceDir "worker.py") $AppDir -Force
    Copy-Item (Join-Path $SourceDir "srvgg.py") $AppDir -Force
    Copy-Item (Join-Path $SourceDir "face.py") $AppDir -Force
    Ok "Da chep worker vao $AppDir"
}

function Update-SshConfig {
    if (-not (Test-Path $SshConfig)) {
        Fail "Khong thay $SshConfig. Chay setup-gpu-node-v4.ps1 (tunnel Ollama) truoc."
    }
    $config = Get-Content $SshConfig -Raw -ErrorAction SilentlyContinue
    if (-not $config) { $config = "" }

    $jumpKey = Get-SshHostValue -Content $config -HostAlias $JumpAlias -Key "IdentityFile"
    $jumpHost = Get-SshHostValue -Content $config -HostAlias $JumpAlias -Key "HostName"
    if (-not $jumpHost) {
        Fail "SSH config chua co 'Host $JumpAlias'. Chay setup-gpu-node-v4.ps1 truoc, hoac dung -JumpAlias."
    }
    if (-not $jumpKey) { $jumpKey = Join-Path $SshDir "id_ed25519" }

    $sh = $ServerHost
    $su = $ServerUser
    if ([string]::IsNullOrWhiteSpace($sh)) { $sh = Get-SshHostValue -Content $config -HostAlias $ServerAlias -Key "HostName" }
    if ([string]::IsNullOrWhiteSpace($su)) { $su = Get-SshHostValue -Content $config -HostAlias $ServerAlias -Key "User" }
    if ([string]::IsNullOrWhiteSpace($sh) -or [string]::IsNullOrWhiteSpace($su)) {
        Fail "Khong doc duoc HostName / User cua 'Host $ServerAlias'. Truyen -ServerHost va -ServerUser."
    }

    $config = [regex]::Replace($config, $BlockRegex, "")
    if ($config.Length -gt 0 -and -not $config.EndsWith("`n")) { $config += "`r`n" }

    $block = @"
$BlockStart
Host $WorkerAlias
    HostName $sh
    User $su
    ProxyJump $JumpAlias
    IdentityFile $jumpKey
    ServerAliveInterval 30
    ServerAliveCountMax 3
    TCPKeepAlive yes
    ConnectTimeout 15
    ConnectionAttempts 1
    ExitOnForwardFailure yes
    LocalForward 127.0.0.1:$LocalPort 127.0.0.1:$RemotePort
$BlockEnd
"@
    Set-Content -Path $SshConfig -Value ($config + $block + "`r`n") -Encoding ascii
    Ok "SSH config: da them block '$WorkerAlias' (block / task Ollama v4 khong bi sua)."
}

function Test-WorkerSsh {
    $ssh = Get-SshPath
    if (-not $ssh) { Fail "Khong thay OpenSSH Client (ssh.exe). Chay setup-gpu-node-v4.ps1 truoc." }
    Info "Kiem tra SSH toi VM qua jump (khong mo forward)..."
    $r = Invoke-Native -Exe $ssh -Arguments @("-F", $SshConfig, "-o", "ClearAllForwardings=yes", "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15", $WorkerAlias, "echo ENHANCE_WORKER_SSH_OK")
    if ($r.Code -ne 0) {
        Fail "SSH toi $WorkerAlias that bai. Kiem tra tunnel Ollama v4 cung dang nhap duoc (auto-fix-gpu-v4.ps1) va VM bat."
    }
    Ok "SSH toi VM qua jump hoat dong."
}

function Resolve-Token {
    if (-not [string]::IsNullOrWhiteSpace($Token)) { return $Token }
    if (Test-Path $ConfigFile) {
        try {
            $old = Get-Content $ConfigFile -Raw | ConvertFrom-Json
            if ($old.token) { Info "Dung token da luu trong config."; return [string]$old.token }
        }
        catch {}
    }
    $sec = Read-Host "Nhap token worker (do VM cap, CP13.1b; bo trong neu chua co)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Write-WorkerConfig {
    param([string]$Ffmpeg, [string]$TokenValue)
    $ffprobe = Join-Path (Split-Path -Parent $Ffmpeg) "ffprobe.exe"
    if (-not (Test-Path $ffprobe)) { $ffprobe = "ffprobe" }
    $cfg = [ordered]@{
        server_url      = "http://127.0.0.1:$LocalPort"
        worker_name     = $WorkerName
        token           = $TokenValue
        yield_to_ollama = [bool]$YieldToOllama
        work_dir        = $WorkDir
        models_dir      = $ModelsDir
        log_file        = (Join-Path $LogDir "worker.log")
        max_disk_gb     = $MaxDiskGb
        batch_size      = $BatchSize
        device          = "cuda"
        cuda_device     = $CudaDevice
        ffmpeg          = $Ffmpeg
        ffprobe         = $ffprobe
        face            = $(if ($SkipFace) { "off" } else { "auto" })
    }
    New-Item -ItemType Directory -Path $InstallDir, $LogDir, $WorkDir -Force | Out-Null
    $json = $cfg | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText($ConfigFile, $json, (New-Object Text.UTF8Encoding($false)))
    # Chi user hien tai doc / ghi (file chua token)
    $who = "$env:USERDOMAIN\$env:USERNAME"
    & icacls.exe $ConfigFile /inheritance:r /grant:r "${who}:(R,W)" | Out-Null
    if ($LASTEXITCODE -ne 0) { Warn "Khong dat duoc quyen chi-user cho $ConfigFile." }
    Ok "Da ghi cau hinh worker: $ConfigFile"
}

function Write-Wrappers {
    param([string]$Py)

    $tunnel = @'
$ErrorActionPreference = 'Continue'
$ConfigPath = '__SSHCONFIG__'
$LogPath = '__LOGDIR__\tunnel.log'

function Write-Log([string]$Message) {
    try {
        Add-Content -Path $LogPath -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
    } catch {}
}

Write-Log '=== Enhance Worker tunnel started ==='

while ($true) {
    Write-Log 'Starting SSH tunnel __ALIAS__ (LocalForward __LPORT__)'
    & ssh.exe -F $ConfigPath -N __ALIAS__ 2>&1 | ForEach-Object {
        Write-Log ('ssh: ' + $_)
    }
    $code = $LASTEXITCODE
    Write-Log ('ssh.exe exited with code ' + $code + '. Reconnecting in 10 seconds...')
    Start-Sleep -Seconds 10
}
'@
    $tunnel = $tunnel.Replace("__SSHCONFIG__", $SshConfig).Replace("__LOGDIR__", $LogDir).Replace("__ALIAS__", $WorkerAlias).Replace("__LPORT__", [string]$LocalPort)

    $worker = @'
$ErrorActionPreference = 'Continue'
$Python = '__PYTHON__'
$Worker = '__WORKER__'
$Config = '__CONFIG__'
$LogPath = '__LOGDIR__\wrapper.log'
$OutPath = '__LOGDIR__\worker-console.log'

function Write-Log([string]$Message) {
    try {
        Add-Content -Path $LogPath -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
    } catch {}
}

try { (Get-Process -Id $PID).PriorityClass = 'BelowNormal' } catch {}
Write-Log '=== Enhance Worker wrapper started ==='

while ($true) {
    Write-Log 'Starting worker'
    & $Python -u $Worker --config $Config 2>&1 | Out-File -FilePath $OutPath -Encoding utf8
    $code = $LASTEXITCODE
    Write-Log ('worker exited with code ' + $code)
    if ($code -eq 3) { $wait = 300 } else { $wait = 15 }
    Start-Sleep -Seconds $wait
}
'@
    $worker = $worker.Replace("__PYTHON__", $Py).Replace("__WORKER__", (Join-Path $AppDir "worker.py")).Replace("__CONFIG__", $ConfigFile).Replace("__LOGDIR__", $LogDir)

    Set-Content -Path $TunnelWrap -Value $tunnel -Encoding utf8
    Set-Content -Path $WorkerWrap -Value $worker -Encoding utf8
    Ok "Da tao wrapper tu noi lai: $TunnelWrap, $WorkerWrap"
}

function Register-WrapperTask {
    param([string]$Name, [string]$Wrapper, [string]$Description)

    $powershell = (Get-Command powershell.exe).Source
    $action = New-ScheduledTaskAction -Execute $powershell `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Wrapper`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Limited
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description $Description

    try { Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue } catch {}
    try { Register-ScheduledTask -TaskName $Name -InputObject $task -Force | Out-Null }
    catch { Fail "Khong dang ky duoc task '$Name': $($_.Exception.Message)" }
    Ok "Task Scheduler: $Name"
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

function Remove-Setup {
    Info "Go Enhance Worker (khong dong cham Ollama v4)..."

    foreach ($n in @($TunnelTaskName, $WorkerTaskName)) {
        if (Get-Command Unregister-ScheduledTask -ErrorAction SilentlyContinue) {
            try { Stop-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue } catch {}
            try { Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue } catch {}
        }
    }
    Stop-EnhanceProcesses

    if (Test-Path $SshConfig) {
        $config = Get-Content $SshConfig -Raw
        $config = [regex]::Replace($config, $BlockRegex, "")
        Set-Content -Path $SshConfig -Value $config -Encoding ascii
        Ok "Da go block SSH 'Enhance Worker v1'."
    }

    if (Test-Path $InstallDir) {
        if ($KeepData) {
            foreach ($item in @($AppDir, $FfmpegDir, $LogDir, $ConfigFile, $TunnelWrap, $WorkerWrap)) {
                if (Test-Path $item) { Remove-Item $item -Recurse -Force -ErrorAction SilentlyContinue }
            }
            Ok "Da go worker; giu lai models\ va work\ (-KeepData)."
        }
        else {
            Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
            Ok "Da xoa $InstallDir"
        }
    }

    if ($RemoveEnv) {
        $conda = Find-Conda
        Info "Xoa env conda '$EnvName'..."
        & $conda env remove -y -n $EnvName | Out-Host
    }
    else {
        Info "Env conda '$EnvName' duoc giu (them -RemoveEnv de xoa)."
    }
    Ok "Enhance Worker da go."
}

# -----------------------------
# Main
# -----------------------------

if ($Uninstall) {
    Remove-Setup
    exit 0
}

if ([string]::IsNullOrWhiteSpace($WorkerName)) {
    Fail "Thieu -WorkerName (vi du -WorkerName rtx3090)."
}
if ($WorkerName -notmatch '^[A-Za-z0-9._-]{1,40}$') {
    Fail "-WorkerName chi gom chu, so, '.', '_', '-'."
}

Write-Host ""
Write-Host "=== Enhance Worker Setup (CP13.1a) ===" -ForegroundColor White
Write-Host "Worker:      $WorkerName (yield_to_ollama = $([bool]$YieldToOllama))"
Write-Host "Install dir: $InstallDir"
Write-Host "Conda env:   $EnvName"
Write-Host "Tunnel:      127.0.0.1:$LocalPort -> VM 127.0.0.1:$RemotePort (qua $WorkerAlias)"
Write-Host ""

$nv = Invoke-Native -Exe "nvidia-smi.exe" -Arguments @("-L")
if ($nv.Code -eq 0) { Ok "NVIDIA: $(($nv.Output | Out-String).Trim())" }
else { Warn "Khong chay duoc nvidia-smi (driver NVIDIA?)." }

if (-not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {
    Fail "Cmdlet Task Scheduler (ScheduledTasks) khong co tren may nay."
}

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
$py = Ensure-Env
Ensure-Packages -Py $py
Ensure-FacePackages -Py $py
$ffmpeg = Ensure-Ffmpeg
Ensure-Weights
Ensure-FaceWeights
Copy-App
Update-SshConfig
Test-WorkerSsh
$tok = Resolve-Token
Write-WorkerConfig -Ffmpeg $ffmpeg -TokenValue $tok
Write-Wrappers -Py $py

if ($NoTask) {
    Info "Bo qua Task Scheduler (-NoTask)."
}
else {
    Stop-EnhanceProcesses
    Register-WrapperTask -Name $TunnelTaskName -Wrapper $TunnelWrap -Description "SSH tunnel cua Enhance Worker (localhost:$LocalPort -> VM)."
    Register-WrapperTask -Name $WorkerTaskName -Wrapper $WorkerWrap -Description "Enhance Worker (CP13.1a): nhan viec enhance video tu VM."
    Start-ScheduledTask -TaskName $TunnelTaskName
    Info "Cho tunnel len cong $LocalPort..."
    $up = $false
    for ($i = 0; $i -lt 20; $i++) {
        if (Test-LocalPort -Port $LocalPort) { $up = $true; break }
        Start-Sleep -Seconds 1
    }
    if ($up) { Ok "Tunnel dang nghe tren 127.0.0.1:$LocalPort." }
    else { Warn "Tunnel chua len. Xem $LogDir\tunnel.log, hoac chay auto-fix-enhance-worker.ps1." }
}

$selfTestOk = $true
if ($SkipSelfTest) {
    Info "Bo qua self-test."
}
else {
    Info "Chay self-test..."
    $stOut = & $py (Join-Path $AppDir "worker.py") --config $ConfigFile --self-test 2>&1 | Out-String
    Write-Host $stOut
    if ($LASTEXITCODE -ne 0) {
        $selfTestOk = $false
        Warn "Self-test co loi (xem tren). Sua xong chay lai script nay hoac auto-fix-enhance-worker.ps1."
    }
    elseif (-not $SkipFace -and $stOut -notmatch "GFPGAN OK") {
        $selfTestOk = $false
        Warn "Self-test khong bao 'GFPGAN OK': worker se KHONG nhan viec phuc hoi mat. Xem dong [WARN] GFPGAN o tren."
    }
}

if (-not $NoTask) {
    Start-ScheduledTask -TaskName $WorkerTaskName
    Ok "Da khoi dong task worker."
}

Write-Host ""
if ($selfTestOk) { Ok "Enhance Worker setup xong." } else { Warn "Setup xong nhung self-test chua dat." }
Write-Host ""
Write-Host "Log worker:   $LogDir\worker.log" -ForegroundColor Cyan
Write-Host "Log tunnel:   $LogDir\tunnel.log" -ForegroundColor Cyan
Write-Host "Task:         $TunnelTaskName, $WorkerTaskName" -ForegroundColor Cyan
Write-Host "Sua loi:      .\auto-fix-enhance-worker.ps1" -ForegroundColor Cyan
Write-Host "Go cai dat:   .\setup-enhance-worker.ps1 -Uninstall" -ForegroundColor Cyan
