<#
.SYNOPSIS
  Sap xep kho STR1; mac dinh chi in ke hoach, khong di chuyen file.
.EXAMPLE
  .\sap-xep-kho.ps1 -Series PLtest
  .\sap-xep-kho.ps1 -Series PLtest -Apply
  .\sap-xep-kho.ps1 -Series all -Apply
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Series,
    [string]$Config = (Join-Path $env:LOCALAPPDATA "AutoShortStore\config.json"),
    [string]$Python = "",
    [switch]$Apply
)
$ErrorActionPreference = "Stop"

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


$py = Find-WorkerPython
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) { throw "Khong thay config: $Config" }
$StoreFile = Join-Path (Split-Path -Parent (Resolve-Path -LiteralPath $Config).Path) "store.py"
if (-not (Test-Path -LiteralPath $StoreFile -PathType Leaf)) { $StoreFile = Join-Path $PSScriptRoot "store.py" }
if (-not (Test-Path -LiteralPath $StoreFile -PathType Leaf)) { throw "Khong thay store.py" }
$arguments = @($StoreFile, "--config", $Config, "reorganize", "--series", $Series)
if ($Apply) { $arguments += "--apply" }
Write-Host $(if ($Apply) { "[INFO] Apply: $Series" } else { "[INFO] Dry run: $Series" }) -ForegroundColor Cyan
& $py @arguments
exit $LASTEXITCODE
