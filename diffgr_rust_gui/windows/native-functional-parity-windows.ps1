[CmdletBinding()]
param(
    [switch]$Json,
    [switch]$List,
    [switch]$SkipNativeUnavailable,
    [switch]$KeepTemp,
    [switch]$StrictShape,
    [switch]$CompatOnly,
    [string]$NativeCmd,
    [string]$Python,
    [string[]]$Only
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$params = @{}
if ($Json) { $params.Json = $true }
if ($List) { $params.List = $true }
if ($SkipNativeUnavailable) { $params.SkipNativeUnavailable = $true }
if ($KeepTemp) { $params.KeepTemp = $true }
if ($StrictShape) { $params.StrictShape = $true }
if ($CompatOnly) { $params.CompatOnly = $true }
if ($NativeCmd) { $params.NativeCmd = $NativeCmd }
if ($Python) { $params.Python = $Python }
if ($Only) { $params.Only = $Only }
& (Join-Path $Root 'native-functional-parity.ps1') @params
exit $LASTEXITCODE
