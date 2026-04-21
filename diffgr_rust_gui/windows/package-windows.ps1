[CmdletBinding()]
param(
    [string]$OutputRoot,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $Root

function Invoke-Cargo {
    param([Parameter(Mandatory=$true)][string[]]$CargoArgs)
    Write-Host "cargo $($CargoArgs -join ' ')" -ForegroundColor Cyan
    & cargo @CargoArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $Root 'dist'
}

if (-not $SkipBuild) {
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
        throw "cargo が見つかりません。まず .\windows\setup-rust-windows.ps1 を実行してください。"
    }
    Invoke-Cargo @('build', '--release')
}

$exe = Join-Path $Root 'target\release\diffgr_gui.exe'
if (-not (Test-Path $exe)) {
    throw "release exe がありません: $exe"
}

$packageDir = Join-Path $OutputRoot 'diffgr_gui_windows'
$zip = Join-Path $OutputRoot 'diffgr_gui_windows.zip'

Remove-Item -LiteralPath $packageDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $packageDir | Out-Null

Copy-Item -LiteralPath $exe -Destination (Join-Path $packageDir 'diffgr_gui.exe')
Copy-Item -LiteralPath (Join-Path $Root 'README.md') -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $Root 'WINDOWS.md') -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $Root 'TESTING.md') -Destination $packageDir -ErrorAction SilentlyContinue
foreach ($item in @(
    'Run DiffGR Review.cmd',
    'Run Low Memory.cmd',
    'Clear Cache.cmd',
    'Build Release.cmd',
    'Test.cmd',
    'Check Test Build.cmd',
    'run.ps1',
    'build.ps1',
    'test.ps1'
)) {
    Copy-Item -LiteralPath (Join-Path $Root $item) -Destination $packageDir -ErrorAction SilentlyContinue
}
Copy-Item -LiteralPath (Join-Path $Root 'examples') -Destination $packageDir -Recurse
Copy-Item -LiteralPath (Join-Path $Root 'windows') -Destination $packageDir -Recurse
Copy-Item -LiteralPath (Join-Path $Root 'scripts') -Destination $packageDir -Recurse -ErrorAction SilentlyContinue

@'
[CmdletBinding()]
param(
    [string]$Diffgr,
    [string]$State,
    [switch]$LowMemory
)
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $Here 'diffgr_gui.exe'
if ($LowMemory) { $env:DIFFGR_LOW_MEMORY = '1' }
$argsList = @()
if ($Diffgr) { $argsList += (Resolve-Path -LiteralPath $Diffgr).Path }
if ($State) { $argsList += '--state'; $argsList += (Resolve-Path -LiteralPath $State).Path }
Start-Process -FilePath $exe -ArgumentList (($argsList | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ' ') -WorkingDirectory $Here
'@ | Set-Content -LiteralPath (Join-Path $packageDir 'run-release.ps1') -Encoding UTF8

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $packageDir '*') -DestinationPath $zip -Force
Write-Host "Packaged: $zip" -ForegroundColor Green
