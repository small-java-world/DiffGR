[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Script,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PyRoot = Join-Path $Root 'compat\python'
$ScriptName = if ($Script.EndsWith('.py')) { $Script } else { "$Script.py" }
$ScriptPath = Join-Path (Join-Path $PyRoot 'scripts') $ScriptName
if (-not (Test-Path $ScriptPath)) {
    throw "compat Python script not found: $ScriptPath"
}

$python = $env:PYTHON
if (-not $python) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $env:PYTHONPATH = "$PyRoot" + ($(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { '' }))
        & py -3 $ScriptPath @ScriptArgs
        exit $LASTEXITCODE
    }
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) { $python = $pythonCmd.Source }
}
if (-not $python) {
    throw 'Python が見つかりません。厳密互換モードには Python 3 が必要です。'
}
$env:PYTHONPATH = "$PyRoot" + ($(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { '' }))
& $python $ScriptPath @ScriptArgs
exit $LASTEXITCODE
