[CmdletBinding()]
param(
    [switch]$SkipFmt,
    [switch]$Locked
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $Root

function Test-Command {
    param([Parameter(Mandatory=$true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command 'cargo')) {
    throw "cargo が見つかりません。まず .\windows\setup-rust-windows.ps1 を実行してください。"
}

Write-Host "DiffGR Review CI check" -ForegroundColor Cyan
cargo --version
if (Test-Command 'rustc') { rustc --version }

$testArgs = @('-Check')
if (-not $SkipFmt) { $testArgs += '-Fmt' }
if ($Locked) { $testArgs += '-Locked' }
& (Join-Path $PSScriptRoot 'test-windows.ps1') @testArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$buildArgs = @()
if ($Locked) { $buildArgs += '-Locked' }
& (Join-Path $PSScriptRoot 'build-windows.ps1') @buildArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
