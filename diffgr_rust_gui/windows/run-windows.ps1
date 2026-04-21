[CmdletBinding()]
param(
    [string]$Diffgr,
    [string]$State,
    [switch]$Release,
    [switch]$Build,
    [switch]$NoBuild,
    [switch]$Wait,
    [switch]$LowMemory,
    [switch]$Smooth,
    [switch]$NoBackgroundIO,
    [switch]$ClearCache
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $Root

if ($ClearCache) {
    & (Join-Path $PSScriptRoot 'clear-cache-windows.ps1') -Force
}

if ($LowMemory) {
    $env:DIFFGR_LOW_MEMORY = '1'
}
if ($Smooth) {
    $env:DIFFGR_SMOOTH_SCROLL = '1'
}
if ($NoBackgroundIO) {
    $env:DIFFGR_NO_BACKGROUND_IO = '1'
}

function Test-Command {
    param([Parameter(Mandatory=$true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Quote-Arg {
    param([Parameter(Mandatory=$true)][string]$Value)
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Invoke-Cargo {
    param([Parameter(Mandatory=$true)][string[]]$CargoArgs)
    Write-Host "cargo $($CargoArgs -join ' ')" -ForegroundColor Cyan
    & cargo @CargoArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$profile = if ($Release) { 'release' } else { 'debug' }
$exe = Join-Path $Root "target\$profile\diffgr_gui.exe"

$needBuild = $Build -or ((-not $NoBuild) -and (-not (Test-Path $exe)))
if ($needBuild) {
    if (-not (Test-Command 'cargo')) {
        throw "cargo が見つかりません。まず .\windows\setup-rust-windows.ps1 を実行してください。"
    }
    $buildArgs = @()
    if ($Release) { $buildArgs += '--release' }
    Invoke-Cargo (@('build') + $buildArgs)
}

if (-not (Test-Path $exe)) {
    throw "実行ファイルがありません: $exe  先に .\windows\build-windows.ps1 を実行してください。"
}

$argsList = @()
if ($Diffgr) {
    $argsList += (Resolve-Path -LiteralPath $Diffgr).Path
}
if ($State) {
    $argsList += '--state'
    $argsList += (Resolve-Path -LiteralPath $State).Path
}
if ($Smooth) {
    $argsList += '--smooth-scroll'
}
if ($NoBackgroundIO) {
    $argsList += '--no-background-io'
}

if ($Wait) {
    & $exe @argsList
} else {
    $argLine = ($argsList | ForEach-Object { Quote-Arg $_ }) -join ' '
    Start-Process -FilePath $exe -ArgumentList $argLine -WorkingDirectory $Root
}
