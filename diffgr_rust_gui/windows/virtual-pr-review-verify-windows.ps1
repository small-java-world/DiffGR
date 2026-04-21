param([switch]$Json)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..')
$argsList = @()
if ($Json) { $argsList += '--json' }
$python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
& $python (Join-Path $root 'tools\verify_virtual_pr_review.py') @argsList
