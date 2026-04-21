[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ToolArgs
)

& "$PSScriptRoot\windows\diffgrctl-windows.ps1" @ToolArgs
exit $LASTEXITCODE
