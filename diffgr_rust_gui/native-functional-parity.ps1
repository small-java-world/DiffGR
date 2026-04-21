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

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script = Join-Path $Root 'tools\verify_functional_parity.py'
$Py = if ($Python) { $Python } elseif ($env:PYTHON) { $env:PYTHON } else { 'python' }
$argsList = @($Script)
if ($Json) { $argsList += '--json' }
if ($List) { $argsList += '--list' }
if ($SkipNativeUnavailable) { $argsList += '--skip-native-unavailable' }
if ($KeepTemp) { $argsList += '--keep-temp' }
if ($StrictShape) { $argsList += '--strict-shape' }
if ($CompatOnly) { $argsList += '--compat-only' }
if ($NativeCmd) { $argsList += @('--native-cmd', $NativeCmd) }
foreach ($item in ($Only | Where-Object { $_ })) { $argsList += @('--only', $item) }
& $Py @argsList
exit $LASTEXITCODE
