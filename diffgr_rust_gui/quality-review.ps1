[CmdletBinding()]
param([switch]$Json,[switch]$Deep,[string]$Root)
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ArgsList = @()
if ($Json) { $ArgsList += '-Json' }
if ($Deep) { $ArgsList += '-Strict' }
if ($Root) { $ArgsList += @('-Root', $Root) }
& (Join-Path $ScriptRoot 'windows\quality-review-windows.ps1') @ArgsList
exit $LASTEXITCODE
