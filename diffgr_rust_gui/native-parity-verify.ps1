[CmdletBinding()]
param(
    [switch]$Json,
    [switch]$CheckCompat,
    [switch]$CargoCheck
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
$ArgsList = @('--root', $Root)
if ($Json) { $ArgsList += '--json' }
if ($CheckCompat) { $ArgsList += '--check-compat' }
if ($CargoCheck) { $ArgsList += '--cargo-check' }
& $Python (Join-Path $Root 'tools\verify_native_parity.py') @ArgsList
exit $LASTEXITCODE
