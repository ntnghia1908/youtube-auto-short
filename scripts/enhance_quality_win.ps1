<#
CP13.3 - cai env rieng + chay bo do chat luong enhance tren GPU Windows (PowerShell 5.1+).

Khong dung toi worker enhance dang cai (env `enhance-worker`, %USERPROFILE%\enhance-worker):
env moi nam trong <Root>\env (conda -p), du lieu trong <Root>. Xoa ca <Root> la het.

  .\enhance_quality_win.ps1 -Step Setup     # tim conda, tao env, pip install, tai trong so
  .\enhance_quality_win.ps1 -Step Run       # chay bo do tren cac doan mau (GPU), ghi <Root>\results
  .\enhance_quality_win.ps1 -Step Pack      # tom tat toc do (speed.csv) + nen zip de gui ve VM
  .\enhance_quality_win.ps1 -Step All       # ca ba buoc

Tham so: -Root (mac dinh %USERPROFILE%\enhance-quality), -CondaPath (conda.exe hoac thu muc Miniconda),
-Clips (thu muc co A.mkv D.mkv E.mkv; mac dinh .\clips canh script), -Frames 90, -CudaDevice 0,
-RbvsrChunk 0 (dat 30-45 neu card <= 12 GB bao het VRAM), -SkipRbvsr, -Specs "..." (ghi de danh sach spec).
#>
param(
    [ValidateSet('Setup', 'Run', 'Pack', 'All')][string]$Step = 'All',
    [string]$Root = (Join-Path $env:USERPROFILE 'enhance-quality'),
    [string]$CondaPath = '',
    [string]$Clips = (Join-Path $PSScriptRoot 'clips'),
    [int]$Frames = 90,
    [string]$CudaDevice = '0',
    [int]$RbvsrChunk = 0,
    [switch]$SkipRbvsr,
    [string]$Specs = '',
    [string]$Device = 'cuda'
)

$ErrorActionPreference = 'Stop'

function Find-Conda {
    param([string]$Hint)
    # 1) -CondaPath: conda.exe hoac thu muc Miniconda
    if ($Hint) {
        if (Test-Path -LiteralPath $Hint -PathType Leaf) { return (Resolve-Path -LiteralPath $Hint).Path }
        foreach ($rel in @('Scripts\conda.exe', 'condabin\conda.bat', 'conda.exe')) {
            $p = Join-Path $Hint $rel
            if (Test-Path -LiteralPath $p) { return $p }
        }
        throw "Khong thay conda trong -CondaPath '$Hint'"
    }
    # 2) PATH
    foreach ($n in @('conda.exe', 'conda.bat', 'conda')) {
        $c = Get-Command $n -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($c -and $c.Source) { return $c.Source }
    }
    # 3) cac cho hay gap (ten thu muc khac nhau)
    $bases = @()
    foreach ($root in @($env:USERPROFILE, $env:LOCALAPPDATA, $env:ProgramData, 'C:\', "$env:USERPROFILE\AppData\Local")) {
        if (-not $root) { continue }
        foreach ($n in @('miniconda3', 'Miniconda3', 'anaconda3', 'Anaconda3', 'miniforge3', 'Miniforge3', 'mambaforge')) {
            $bases += [System.IO.Path]::Combine($root, $n)
        }
    }
    foreach ($b in $bases) {
        foreach ($rel in @('Scripts\conda.exe', 'condabin\conda.bat')) {
            $p = [System.IO.Path]::Combine($b, $rel)
            if (Test-Path -LiteralPath $p) { return $p }
        }
    }
    # 4) tim kiem (cham hon): conda.exe trong Scripts, toi da 4 cap thu muc
    foreach ($r in @($env:USERPROFILE, $env:LOCALAPPDATA, $env:ProgramData, 'C:\')) {
        if (-not $r -or -not (Test-Path -LiteralPath $r)) { continue }
        $f = Get-ChildItem -Path $r -Filter conda.exe -Recurse -Depth 4 -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -like '*Scripts' } | Select-Object -First 1
        if ($f) { return $f.FullName }
    }
    throw "Khong tim thay Miniconda/Anaconda. Cai Miniconda hoac chay lai voi -CondaPath <conda.exe hoac thu muc Miniconda>."
}

function Invoke-Py {
    param([string]$Py, [string[]]$PyArgs)
    & $Py @PyArgs
    if ($LASTEXITCODE -ne 0) { throw "Lenh that bai (ma $LASTEXITCODE): $Py $($PyArgs -join ' ')" }
}

function Step-Setup {
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    $envDir = Join-Path $Root 'env'
    $py = Join-Path $envDir 'python.exe'
    if (-not (Test-Path -LiteralPath $py)) {
        $conda = Find-Conda -Hint $CondaPath
        Write-Host "conda: $conda"
        # -c conda-forge --override-channels: tranh loi dieu khoan (ToS) cua kenh mac dinh
        & $conda create -y -p $envDir -c conda-forge --override-channels python=3.11
        if ($LASTEXITCODE -ne 0) { throw "conda create that bai" }
    }
    Invoke-Py $py @('-m', 'pip', 'install', '--upgrade', 'pip')
    Invoke-Py $py @('-m', 'pip', 'install', 'torch', 'torchvision', '--index-url', 'https://download.pytorch.org/whl/cu121')
    Invoke-Py $py @('-m', 'pip', 'install', 'numpy', 'opencv-python-headless', 'imageio-ffmpeg', 'basicsr', 'gfpgan', 'facexlib')
    $chk = 'import torch; print(torch.__version__, torch.cuda.is_available())'
    if ($Device -eq 'cuda') { $chk += '; assert torch.cuda.is_available(), "CUDA khong kha dung"' }
    Invoke-Py $py @('-c', $chk)
    $mods = Join-Path $Root 'models'
    $args = @((Join-Path $PSScriptRoot 'enhance_quality_bench.py'), 'fetch', '--models-dir', $mods)
    if ($SkipRbvsr) { $args += '--skip-rbvsr' }
    Invoke-Py $py $args
    Write-Host "Setup xong. Env: $envDir"
}

function Step-Run {
    $py = Join-Path $Root 'env\python.exe'
    if (-not (Test-Path -LiteralPath $py)) { throw "Chua Setup (khong thay $py)" }
    $env:CUDA_VISIBLE_DEVICES = $CudaDevice
    $bench = Join-Path $PSScriptRoot 'enhance_quality_bench.py'
    $out = Join-Path $Root 'results'
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    $speclist = $Specs
    if (-not $speclist) {
        $speclist = 'cur,g100_p0,g075_p0,g050_p0,cur+col2,g100_p0+col2,cur+gfp,cur+cf50,cur+cf80,cur+cf50s,g100_p0+cf50'
        if (-not $SkipRbvsr) { $speclist += ',rbvsr_p360,rbvsr_p0' }
    }
    $sizes = @{ 'A' = '1454x1080'; 'D' = '1440x1080'; 'E' = '1440x1080' }
    foreach ($name in @('D', 'E', 'A')) {
        $clip = Join-Path $Clips "$name.mkv"
        if (-not (Test-Path -LiteralPath $clip)) { Write-Warning "Thieu $clip, bo qua"; continue }
        $a = @($bench, 'run', '--clip', $clip, '--name', $name, '--specs', $speclist, '--out', $out,
            '--models-dir', (Join-Path $Root 'models'), '--frames', "$Frames", '--device', $Device,
            '--out-size', $sizes[$name], '--codec', 'x264')
        if ($RbvsrChunk -gt 0) { $a += @('--rbvsr-chunk', "$RbvsrChunk") }
        Invoke-Py $py $a
    }
}

function Step-Pack {
    $out = Join-Path $Root 'results'
    $rows = Get-ChildItem -Path $out -Filter '*.json' | ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json } |
        Select-Object clip, spec, gpu, frames, sec_per_frame_base, sec_per_frame_post, sec_per_frame, vram_peak_mb, fp16, torch
    $csv = Join-Path $out 'speed.csv'
    $rows | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $csv
    $rows | Format-Table clip, spec, sec_per_frame_base, sec_per_frame_post, sec_per_frame, vram_peak_mb -AutoSize
    $zip = Join-Path $Root 'cp133-results.zip'
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip }
    Compress-Archive -Path (Join-Path $out '*') -DestinationPath $zip
    Write-Host ''
    Write-Host "Da nen: $zip"
    Write-Host "Gui ve VM (PowerShell):  scp `"$zip`" gpu-server-v4:.cache/auto-short-cp133-test/results/"
}

if ($MyInvocation.InvocationName -ne '.') {
    switch ($Step) {
        'Setup' { Step-Setup }
        'Run' { Step-Run }
        'Pack' { Step-Pack }
        'All' { Step-Setup; Step-Run; Step-Pack }
    }
}
