[CmdletBinding()]
param(
    [switch]$Json,
    [string]$Output
)

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$tool = Join-Path $root 'diffgrctl.ps1'
$argsList = @('parity-audit')
if ($Json) { $argsList += '--json' }
if ($Output) { $argsList += @('--output', $Output) }
& $tool @argsList
exit $LASTEXITCODE
