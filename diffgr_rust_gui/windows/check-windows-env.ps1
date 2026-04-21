[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Test-Command {
    param([Parameter(Mandatory=$true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
Write-Host "DiffGR Review Windows environment check" -ForegroundColor Cyan
Write-Host "Project: $Root"
Write-Host "PowerShell: $($PSVersionTable.PSVersion)"
Write-Host ""

$ok = $true

foreach ($cmd in @('cargo', 'rustc')) {
    if (Test-Command $cmd) {
        & $cmd --version
    } else {
        $ok = $false
        Write-Warning "$cmd が見つかりません。Rust toolchain をインストールしてください。"
    }
}

if (Test-Command 'rustup') {
    Write-Host ""
    rustup show active-toolchain
} else {
    Write-Warning "rustup が見つかりません。rustup での管理を推奨します。"
}

Write-Host ""
if (Test-Command 'cl.exe') {
    $cl = (Get-Command 'cl.exe').Source
    Write-Host "MSVC linker/toolchain candidate: $cl" -ForegroundColor Green
} else {
    Write-Warning "cl.exe が現在の PATH にはありません。通常の PowerShell では見えない場合があります。cargo build が linker エラーになる場合は Visual Studio Build Tools の 'Desktop development with C++' を入れてください。"
}

Write-Host ""
if ($ok) {
    Write-Host "OK: .\windows\run-windows.ps1 -Diffgr .\examples\minimal.diffgr.json で起動できます。" -ForegroundColor Green
    exit 0
}

Write-Host "次のどちらかを実行してください:" -ForegroundColor Yellow
Write-Host "  .\windows\setup-rust-windows.ps1 -UseWinget"
Write-Host "  .\windows\setup-rust-windows.ps1"
exit 1
