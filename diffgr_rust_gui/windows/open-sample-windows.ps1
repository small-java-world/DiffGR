[CmdletBinding()]
param([switch]$Release)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
$sample = Join-Path $Root 'examples\minimal.diffgr.json'
& (Join-Path $PSScriptRoot 'run-windows.ps1') -Diffgr $sample -Release:$Release
