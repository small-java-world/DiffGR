[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
$Sample = Join-Path $Root 'examples\multi_file.diffgr.json'
& (Join-Path $Root 'scripts\summarize_diffgr.ps1') -CompatPython --input $Sample --json | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $Root 'scripts\extract_diffgr_state.ps1') -CompatPython --input $Sample | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $Root 'scripts\check_virtual_pr_coverage.ps1') -CompatPython --input $Sample --json | Out-Null
if (($LASTEXITCODE -ne 0) -and ($LASTEXITCODE -ne 2)) { exit $LASTEXITCODE }
Write-Host 'compat-python smoke passed'
