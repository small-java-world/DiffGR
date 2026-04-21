[CmdletBinding()]
param(
    [switch]$Json,
    [switch]$Pytest
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Verifier = Join-Path $Root 'tools\verify_python_parity.py'
$ArgsList = @($Verifier, '--compile', '--smoke')
if ($Json) { $ArgsList += '--json' }
if ($Pytest) { $ArgsList += '--pytest' }

$python = $env:PYTHON
if (-not $python) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & py -3 @ArgsList
        exit $LASTEXITCODE
    }
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) { $python = $pythonCmd.Source }
}
if (-not $python) {
    throw 'Python 3 が見つかりません。Python互換検証には Python 3 が必要です。'
}
& $python @ArgsList
exit $LASTEXITCODE
