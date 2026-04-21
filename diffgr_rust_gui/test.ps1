[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$RemainingArgs
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'windows\test-windows.ps1') @RemainingArgs
exit $LASTEXITCODE
