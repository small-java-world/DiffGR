[CmdletBinding()]
param([switch]$Json,[switch]$CheckSubgates,[string]$Root,[string]$Python)
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $Root) { $Root = $ProjectRoot }
if (-not $Python) { if ($env:PYTHON) { $Python = $env:PYTHON } else { $Python = 'python' } }
$Tool = Join-Path $ProjectRoot 'tools\verify_gui_completion.py'
$ArgsList = @($Tool, '--root', $Root)
if ($Json) { $ArgsList += '--json' }
if ($CheckSubgates) { $ArgsList += '--check-subgates' }
& $Python @ArgsList
exit $LASTEXITCODE
