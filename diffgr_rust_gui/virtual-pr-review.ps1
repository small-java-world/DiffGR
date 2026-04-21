param(
  [string]$Input = "",
  [string]$State = "",
  [string]$Output = "",
  [switch]$Json,
  [switch]$Markdown,
  [switch]$Prompt,
  [switch]$FailOnBlockers,
  [int]$MaxItems = 12
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$argsList = @('virtual-pr-review')
if ($Input) { $argsList += @('--input', $Input) }
if ($State) { $argsList += @('--state', $State) }
if ($Output) { $argsList += @('--output', $Output) }
if ($Json) { $argsList += '--json' }
if ($Markdown) { $argsList += '--markdown' }
if ($Prompt) { $argsList += @('--prompt', '--max-items', [string]$MaxItems) }
if ($FailOnBlockers) { $argsList += '--fail-on-blockers' }
& (Join-Path $root 'diffgrctl.ps1') @argsList
