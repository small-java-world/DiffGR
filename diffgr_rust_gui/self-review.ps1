[CmdletBinding()]
param([switch]$Json,[switch]$Strict,[string]$Root)
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ArgsList = @()
if ($Json) { $ArgsList += '-Json' }
if ($Strict) { $ArgsList += '-Strict' }
if ($Root) { $ArgsList += @('-Root', $Root) }
& (Join-Path $ScriptRoot 'windows\self-review-windows.ps1') @ArgsList
exit $LASTEXITCODE
