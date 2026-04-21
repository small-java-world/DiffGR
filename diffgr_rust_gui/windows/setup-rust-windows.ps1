[CmdletBinding()]
param(
    [switch]$UseWinget,
    [switch]$InstallBuildTools
)

$ErrorActionPreference = 'Stop'

function Test-Command {
    param([Parameter(Mandatory=$true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

Write-Host "DiffGR Review: Rust setup helper for Windows" -ForegroundColor Cyan

if (Test-Command 'cargo') {
    Write-Host "cargo はすでに利用できます:" -ForegroundColor Green
    cargo --version
    rustc --version
} elseif ($UseWinget -and (Test-Command 'winget')) {
    Write-Host "winget で Rustup をインストールします。"
    winget install --id Rustlang.Rustup -e --source winget
    Write-Host "インストール後、新しい PowerShell を開き直して .\windows\check-windows-env.ps1 を実行してください。" -ForegroundColor Yellow
} else {
    Write-Host "Rust公式インストールページを開きます。インストーラーの案内に従ってください。" -ForegroundColor Yellow
    Start-Process 'https://www.rust-lang.org/tools/install'
    Write-Host "winget が使えるなら: .\windows\setup-rust-windows.ps1 -UseWinget"
}

if ($InstallBuildTools) {
    if (Test-Command 'winget') {
        Write-Host "Visual Studio Build Tools を winget で起動します。インストーラーで 'Desktop development with C++' を選んでください。" -ForegroundColor Yellow
        winget install --id Microsoft.VisualStudio.2022.BuildTools -e --source winget
    } else {
        Write-Host "Visual Studio Build Tools のページを開きます。'Desktop development with C++' を選んでください。" -ForegroundColor Yellow
        Start-Process 'https://visualstudio.microsoft.com/visual-cpp-build-tools/'
    }
}

Write-Host ""
Write-Host "確認コマンド:" -ForegroundColor Cyan
Write-Host "  cargo --version"
Write-Host "  rustc --version"
Write-Host "  .\windows\check-windows-env.ps1"
