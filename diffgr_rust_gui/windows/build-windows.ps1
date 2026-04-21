[CmdletBinding()]
param(
    [switch]$Debug,
    [switch]$Clean,
    [switch]$RunAfterBuild,
    [switch]$Test,
    [switch]$Check,
    [switch]$Locked,
    [switch]$Package
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $Root

function Test-Command {
    param([Parameter(Mandatory=$true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-Cargo {
    param([Parameter(Mandatory=$true)][string[]]$CargoArgs)
    Write-Host "cargo $($CargoArgs -join ' ')" -ForegroundColor Cyan
    & cargo @CargoArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not (Test-Command 'cargo')) {
    throw "cargo が見つかりません。まず .\windows\setup-rust-windows.ps1 を実行してください。"
}

$commonArgs = @()
if ($Locked) { $commonArgs += '--locked' }

if ($Clean) {
    Invoke-Cargo @('clean')
}

if ($Check) {
    Invoke-Cargo (@('check', '--all-targets') + $commonArgs)
}

if ($Test) {
    Invoke-Cargo (@('test', '--all-targets') + $commonArgs)
}

$buildArgs = @('build') + $commonArgs
if (-not $Debug) {
    $buildArgs += '--release'
}
Invoke-Cargo $buildArgs

$profile = if ($Debug) { 'debug' } else { 'release' }
$exe = Join-Path $Root "target\$profile\diffgr_gui.exe"
Write-Host "Built: $exe" -ForegroundColor Green

if ($RunAfterBuild) {
    Start-Process -FilePath $exe -WorkingDirectory $Root
}

if ($Package) {
    & (Join-Path $PSScriptRoot 'package-windows.ps1') -SkipBuild
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
