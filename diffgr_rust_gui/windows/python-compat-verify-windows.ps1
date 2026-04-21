[CmdletBinding()]
param(
    [switch]$Json,
    [switch]$Pytest
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
$Script = Join-Path $Root 'compat-python-verify.ps1'
$argsList = @()
if ($Json) { $argsList += '-Json' }
if ($Pytest) { $argsList += '-Pytest' }
& $Script @argsList
exit $LASTEXITCODE
