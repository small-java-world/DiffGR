[CmdletBinding()]
param(
    [switch]$Deep,
    [switch]$Locked,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $Root

function Test-Command {
    param([Parameter(Mandatory=$true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Write-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail = '')
    $color = if ($Ok) { 'Green' } else { 'Yellow' }
    $mark = if ($Ok) { 'OK' } else { 'WARN' }
    Write-Host ("[{0}] {1} {2}" -f $mark, $Name, $Detail) -ForegroundColor $color
}

Write-Host 'DiffGR Review Doctor' -ForegroundColor Cyan
Write-Host "Project: $Root"
Write-Host "PowerShell: $($PSVersionTable.PSVersion)"
Write-Host ''

$cargoOk = Test-Command 'cargo'
$rustcOk = Test-Command 'rustc'
$cargoDetail = if ($cargoOk) { (& cargo --version) } else { 'not found' }
$rustcDetail = if ($rustcOk) { (& rustc --version) } else { 'not found' }
Write-Check 'cargo' $cargoOk $cargoDetail
Write-Check 'rustc' $rustcOk $rustcDetail
if (Test-Command 'rustup') {
    $toolchain = (& rustup show active-toolchain)
    Write-Check 'rustup' $true $toolchain
} else {
    Write-Check 'rustup' $false 'not found; rustup 管理を推奨'
}

$manifest = Join-Path $Root 'Cargo.toml'
Write-Check 'Cargo.toml' (Test-Path $manifest) $manifest
Write-Check 'minimal sample' (Test-Path (Join-Path $Root 'examples\minimal.diffgr.json')) 'examples\minimal.diffgr.json'

$releaseExe = Join-Path $Root 'target\release\diffgr_gui.exe'
$debugExe = Join-Path $Root 'target\debug\diffgr_gui.exe'
$releaseCtl = Join-Path $Root 'target\release\diffgrctl.exe'
$debugCtl = Join-Path $Root 'target\debug\diffgrctl.exe'
Write-Check 'release gui exe' (Test-Path $releaseExe) $releaseExe
Write-Check 'debug gui exe' (Test-Path $debugExe) $debugExe
Write-Check 'release diffgrctl exe' (Test-Path $releaseCtl) $releaseCtl
Write-Check 'debug diffgrctl exe' (Test-Path $debugCtl) $debugCtl
Write-Check 'diffgrctl wrapper' (Test-Path (Join-Path $Root 'diffgrctl.ps1')) 'diffgrctl.ps1'

$pathLength = $Root.Path.Length
Write-Check 'path length' ($pathLength -lt 180) "length=$pathLength; 180未満推奨"

if (-not $cargoOk) {
    Write-Host ''
    Write-Host 'Rust/Cargo が無い場合:' -ForegroundColor Yellow
    Write-Host '  .\windows\setup-rust-windows.ps1 -UseWinget -InstallBuildTools'
    exit 1
}

if ($Deep) {
    Write-Host ''
    Write-Host 'Running deep checks...' -ForegroundColor Cyan
    $testArgs = @('-Fmt', '-Check')
    if ($Locked) { $testArgs += '-Locked' }
    & (Join-Path $PSScriptRoot 'test-windows.ps1') @testArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    if (-not $SkipBuild) {
        $buildArgs = @()
        if ($Locked) { $buildArgs += '-Locked' }
        & (Join-Path $PSScriptRoot 'build-windows.ps1') @buildArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
} else {
    Write-Host ''
    Write-Host '深く確認する場合:' -ForegroundColor Cyan
    Write-Host '  .\windows\doctor-windows.ps1 -Deep'
    Write-Host '  .\test.ps1 -Fmt -Check'
    Write-Host '  .\build.ps1 -Test'
}

Write-Host ''
Write-Host 'Doctor completed.' -ForegroundColor Green
