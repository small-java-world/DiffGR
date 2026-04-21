[CmdletBinding()]
param(
    [string]$Name = 'DiffGR Review',
    [string]$Diffgr,
    [string]$State,
    [switch]$Release
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
$profile = if ($Release) { 'release' } else { 'debug' }
$exe = Join-Path $Root "target\$profile\diffgr_gui.exe"

if (-not (Test-Path $exe)) {
    throw "実行ファイルがありません: $exe  先に .\windows\build-windows.ps1 を実行してください。"
}

function Quote-Arg {
    param([Parameter(Mandatory=$true)][string]$Value)
    return '"' + ($Value -replace '"', '\"') + '"'
}

$argsList = @()
if ($Diffgr) { $argsList += (Resolve-Path -LiteralPath $Diffgr).Path }
if ($State) { $argsList += '--state'; $argsList += (Resolve-Path -LiteralPath $State).Path }
$argLine = ($argsList | ForEach-Object { Quote-Arg $_ }) -join ' '

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop "$Name.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exe
$shortcut.Arguments = $argLine
$shortcut.WorkingDirectory = $Root
$shortcut.IconLocation = $exe
$shortcut.Description = 'DiffGR Review GUI'
$shortcut.Save()

Write-Host "Shortcut created: $shortcutPath" -ForegroundColor Green
