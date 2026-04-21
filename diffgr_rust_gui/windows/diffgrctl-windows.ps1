[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ToolArgs,

    [switch]$Release,
    [switch]$Build,
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $Root

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw 'cargo が見つかりません。Rust をインストールしてから再実行してください: https://www.rust-lang.org/tools/install'
}

$profile = if ($Release) { 'release' } else { 'debug' }
$exe = Join-Path $Root "target\$profile\diffgrctl.exe"

if ($Build -or ((-not $NoBuild) -and (-not (Test-Path $exe)))) {
    $buildArgs = @('build', '--bin', 'diffgrctl')
    if ($Release) { $buildArgs += '--release' }
    & cargo @buildArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not (Test-Path $exe)) {
    throw "diffgrctl.exe が見つかりません: $exe"
}

& $exe @ToolArgs
exit $LASTEXITCODE
