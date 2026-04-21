[CmdletBinding()]
param(
    [switch]$Release
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $Root

$Out = Join-Path $Root 'out\parity-smoke'
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Input = Join-Path $Root 'examples\multi_file.diffgr.json'
$State = Join-Path $Out 'review.state.json'
$Html = Join-Path $Out 'review.html'
$Bundle = Join-Path $Out 'bundle'
$Ctl = Join-Path $Root 'windows\diffgrctl-windows.ps1'
$ctlArgs = @()
if ($Release) { $ctlArgs += '-Release' }

& $Ctl @ctlArgs parity-audit --json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Ctl @ctlArgs summarize-diffgr --input $Input --json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Ctl @ctlArgs check-virtual-pr-coverage --input $Input --json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Ctl @ctlArgs extract-diffgr-state --input $Input --output $State
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Ctl @ctlArgs export-diffgr-html --input $Input --state $State --output $Html
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Ctl @ctlArgs export-review-bundle --input $Input --output-dir $Bundle
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Ctl @ctlArgs verify-review-bundle --bundle (Join-Path $Bundle 'bundle.diffgr.json') --state (Join-Path $Bundle 'review.state.json') --manifest (Join-Path $Bundle 'review.manifest.json')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Parity smoke output: $Out" -ForegroundColor Green
