[CmdletBinding()]
param(
    [switch]$Json,
    [switch]$List
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = $env:PYTHON
if (-not $Python) { $Python = 'python' }
$argsList = @()
if ($Json) { $argsList += '--json' }
if ($List) { $argsList += '--list' }
& $Python (Join-Path $Root 'tools\verify_ut_matrix.py') @argsList
exit $LASTEXITCODE
