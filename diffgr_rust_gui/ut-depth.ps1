[CmdletBinding()]
param(
    [switch]$Json
)
$ErrorActionPreference = 'Stop'
$argsList = @()
if ($Json) { $argsList += '--json' }
& (Join-Path $PSScriptRoot 'windows\ut-depth-windows.ps1') @argsList
exit $LASTEXITCODE
