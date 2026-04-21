[CmdletBinding()]
param([switch]$Json,[switch]$CheckSubgates,[string]$Root)
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ArgsList = @()
if ($Json) { $ArgsList += '-Json' }
if ($CheckSubgates) { $ArgsList += '-CheckSubgates' }
if ($Root) { $ArgsList += @('-Root', $Root) }
& (Join-Path $ScriptRoot 'windows\gui-completion-verify-windows.ps1') @ArgsList
exit $LASTEXITCODE
