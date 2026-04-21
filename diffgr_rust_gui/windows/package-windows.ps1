[CmdletBinding()]
param(
    [string]$OutputRoot,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $Root

function Invoke-Cargo {
    param([Parameter(Mandatory=$true)][string[]]$CargoArgs)
    Write-Host "cargo $($CargoArgs -join ' ')" -ForegroundColor Cyan
    & cargo @CargoArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $Root 'dist'
}

if (-not $SkipBuild) {
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
        throw "cargo が見つかりません。まず .\windows\setup-rust-windows.ps1 を実行してください。"
    }
    Invoke-Cargo @('build', '--release')
}

$exe = Join-Path $Root 'target\release\diffgr_gui.exe'
$ctlExe = Join-Path $Root 'target\release\diffgrctl.exe'
foreach ($required in @($exe, $ctlExe)) {
    if (-not (Test-Path $required)) {
        throw "release exe がありません: $required"
    }
}

$packageDir = Join-Path $OutputRoot 'diffgr_gui_windows'
$zip = Join-Path $OutputRoot 'diffgr_gui_windows.zip'

Remove-Item -LiteralPath $packageDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $packageDir | Out-Null

Copy-Item -LiteralPath $exe -Destination (Join-Path $packageDir 'diffgr_gui.exe')
Copy-Item -LiteralPath $ctlExe -Destination (Join-Path $packageDir 'diffgrctl.exe')
Copy-Item -LiteralPath (Join-Path $Root 'README.md') -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $Root 'WINDOWS.md') -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $Root 'TESTING.md') -Destination $packageDir -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $Root 'CHANGELOG.md') -Destination $packageDir -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $Root 'PYTHON_PARITY.md') -Destination $packageDir -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $Root 'PYTHON_PARITY_MANIFEST.json') -Destination $packageDir -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $Root 'PYTHON_COMPATIBILITY.md') -Destination $packageDir -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $Root 'COMPLETE_PARITY_AUDIT.md') -Destination $packageDir -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $Root 'STRICT_PYTHON_PARITY.md') -Destination $packageDir -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $Root 'COMPLETE_PYTHON_SOURCE_AUDIT.json') -Destination $packageDir -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $Root 'agent_cli.toml') -Destination $packageDir -ErrorAction SilentlyContinue
foreach ($item in @(
    'Run DiffGR Review.cmd',
    'Run Low Memory.cmd',
    'Clear Cache.cmd',
    'Build Release.cmd',
    'Test.cmd',
    'Check Test Build.cmd',
    'Doctor.cmd',
    'Package Windows.cmd',
    'run.ps1',
    'build.ps1',
    'test.ps1',
    'doctor.ps1',
    'diffgrctl.ps1',
    'virtual-pr-review.ps1',
    'virtual-pr-review.sh',
    'virtual-pr-review-verify.ps1',
    'virtual-pr-review-verify.sh',
    'VIRTUAL_PR_REVIEW_AUDIT.json',
    'Virtual PR Review Gate.cmd',
    'Virtual PR Review Verify.cmd',
    'DiffGR Tools.cmd',
    'Python Parity Smoke.cmd',
    'Python Parity Audit.cmd',
    'Python Compat Smoke.cmd',
    'Python Compat Verify.cmd',
    'Python Compatibility Mode.cmd',
    'compat-python.ps1',
    'compat-python-verify.ps1',
    'compat-python-smoke.sh',
    'compat-python-verify.sh',
    'native-functional-parity.ps1',
    'native-functional-parity.sh',
    'Native Functional Parity Verify.cmd',
    'NATIVE_FUNCTIONAL_PARITY.md',
    'NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json',
    'UT_MATRIX.json',
    'ut-matrix.ps1',
    'ut-matrix.sh',

    'SELF_REVIEW.md',
    'SELF_REVIEW_AUDIT.json',
    'GUI_COMPLETION_AUDIT.json',
    'self-review.ps1',
    'self-review.sh',
    'quality-review.ps1',
    'quality-review.sh',
    'completion-review.ps1',
    'completion-review.sh',
    'Self Review.cmd',
    'Quality Review.cmd',
    'Python GUI Completion Verify.cmd',
    'UT Matrix Verify.cmd',
    'UT_DEPTH_AUDIT.json',
    'ut-depth.ps1',
    'ut-depth.sh',
    'UT Depth Verify.cmd'
)) {
    Copy-Item -LiteralPath (Join-Path $Root $item) -Destination $packageDir -ErrorAction SilentlyContinue
}
Copy-Item -LiteralPath (Join-Path $Root 'examples') -Destination $packageDir -Recurse
Copy-Item -LiteralPath (Join-Path $Root 'windows') -Destination $packageDir -Recurse
Copy-Item -LiteralPath (Join-Path $Root 'scripts') -Destination $packageDir -Recurse -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $Root 'schemas') -Destination $packageDir -Recurse -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $Root 'compat') -Destination $packageDir -Recurse -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $Root 'tools') -Destination $packageDir -Recurse -ErrorAction SilentlyContinue

@'
[CmdletBinding()]
param(
    [string]$Diffgr,
    [string]$State,
    [switch]$LowMemory
)
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $Here 'diffgr_gui.exe'
if ($LowMemory) { $env:DIFFGR_LOW_MEMORY = '1' }
$argsList = @()
if ($Diffgr) { $argsList += (Resolve-Path -LiteralPath $Diffgr).Path }
if ($State) { $argsList += '--state'; $argsList += (Resolve-Path -LiteralPath $State).Path }
Start-Process -FilePath $exe -ArgumentList (($argsList | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ' ') -WorkingDirectory $Here
'@ | Set-Content -LiteralPath (Join-Path $packageDir 'run-release.ps1') -Encoding UTF8


@'
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ToolArgs
)
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $Here 'diffgrctl.exe'
& $exe @ToolArgs
exit $LASTEXITCODE
'@ | Set-Content -LiteralPath (Join-Path $packageDir 'diffgrctl-release.ps1') -Encoding UTF8

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $packageDir '*') -DestinationPath $zip -Force
Write-Host "Packaged: $zip" -ForegroundColor Green
