# Native default is the Rust CLI via the root wrapper. Windows wrapper: windows\diffgrctl-windows.ps1.
[CmdletBinding()]
param(
    [switch]$CompatPython,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

if ($CompatPython -or $env:DIFFGR_COMPAT_PYTHON -eq '1' -or $env:DIFFGR_COMPAT_PYTHON -eq 'true') {
    & "$PSScriptRoot\..\compat-python.ps1" summarize_reviewability @ScriptArgs
} else {
    & "$PSScriptRoot\..\diffgrctl.ps1" summarize-reviewability @ScriptArgs
}
exit $LASTEXITCODE

