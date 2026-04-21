[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$RemainingArgs
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'windows\doctor-windows.ps1') @RemainingArgs
exit $LASTEXITCODE
