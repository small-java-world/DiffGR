[CmdletBinding()]
param([switch]$Json,[switch]$Strict,[switch]$Deep,[string]$Root,[string]$Python)
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $Root) { $Root = $ProjectRoot }
if (-not $Python) { if ($env:PYTHON) { $Python = $env:PYTHON } else { $Python = 'python' } }
$Tool = Join-Path $ProjectRoot 'tools\verify_self_review.py'
$ArgsList = @($Tool, '--root', $Root)
if ($Json) { $ArgsList += '--json' }
if ($Strict -or $Deep) { $ArgsList += '--strict' }
& $Python @ArgsList
exit $LASTEXITCODE
