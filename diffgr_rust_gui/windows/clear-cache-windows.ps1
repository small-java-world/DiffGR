[CmdletBinding(SupportsShouldProcess=$true)]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$names = @(
    'diffgr-rust-gui',
    'diffgr_gui',
    'DiffGR Review',
    'DiffGRReview'
)

$bases = @(
    $env:APPDATA,
    $env:LOCALAPPDATA,
    (Join-Path $env:USERPROFILE 'AppData\Roaming'),
    (Join-Path $env:USERPROFILE 'AppData\Local')
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

$candidates = New-Object System.Collections.Generic.List[string]
foreach ($base in $bases) {
    foreach ($name in $names) {
        $candidates.Add((Join-Path $base $name))
        $candidates.Add((Join-Path (Join-Path $base 'egui') $name))
        $candidates.Add((Join-Path (Join-Path $base 'eframe') $name))
    }
}

$removed = 0
foreach ($path in ($candidates | Select-Object -Unique)) {
    if (Test-Path -LiteralPath $path) {
        if ($Force -or $PSCmdlet.ShouldProcess($path, 'Remove DiffGR GUI cache/config')) {
            Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
            Write-Host "Removed: $path" -ForegroundColor Yellow
            $removed++
        }
    }
}

if ($removed -eq 0) {
    Write-Host 'DiffGR GUI のキャッシュ/設定フォルダ候補は見つかりませんでした。' -ForegroundColor Green
} else {
    Write-Host "Removed $removed cache/config path(s)." -ForegroundColor Green
}
