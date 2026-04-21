[CmdletBinding()]
param(
    [switch]$Json
)
$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
$Python = $env:PYTHON
if (-not $Python) { $Python = 'python' }
$argsList = @()
if ($Json) { $argsList += '--json' }
& $Python (Join-Path $Root 'tools\verify_ut_depth.py') @argsList
exit $LASTEXITCODE
