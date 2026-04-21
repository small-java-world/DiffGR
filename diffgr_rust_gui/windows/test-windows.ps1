[CmdletBinding()]
param(
    [switch]$Release,
    [switch]$Check,
    [switch]$Fmt,
    [switch]$Locked,
    [string]$TestName
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

if ($Fmt) {
    Invoke-Cargo @('fmt', '--all', '--', '--check')
}

if ($Check) {
    Invoke-Cargo (@('check', '--all-targets') + $commonArgs)
}

$testArgs = @('test', '--all-targets') + $commonArgs
if ($Release) { $testArgs += '--release' }
if ($TestName) { $testArgs += $TestName }
Invoke-Cargo $testArgs
