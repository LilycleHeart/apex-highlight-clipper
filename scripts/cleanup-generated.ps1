param(
    [switch]$Apply,
    [string[]]$Protect = @(),
    [ValidateRange(1, 5)][int]$KeepPortable = 2,
    [ValidateRange(1, 5)][int]$KeepElectron = 1
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$processes = @(Get-CimInstance Win32_Process)
$protectedRoots = @($Protect | ForEach-Object { $_.Split('|') } | Where-Object { $_ } | ForEach-Object { [IO.Path]::GetFullPath($_).TrimEnd('\') })
$candidates = @()
# Only directories explicitly marked by our builders; never infer ownership from a name.
foreach ($parent in @((Join-Path $projectRoot 'publish'), (Join-Path $projectRoot 'electron-ui'))) {
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { continue }
    foreach ($directory in Get-ChildItem -LiteralPath $parent -Directory) {
        if ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
        $markerPath = Join-Path $directory.FullName '.apex-build.json'
        if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) { continue }
        if ((Get-Item -LiteralPath $markerPath).Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
        try { $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json } catch { continue }
        if ($marker.owner -ne 'apex-auto-clipper' -or $marker.schema -ne 1) { continue }
        $kind = if ($parent -eq (Join-Path $projectRoot 'publish')) { 'portable' } else { 'electron' }
        if ($marker.kind -ne $kind -or $marker.status -notin @('building', 'failed', 'succeeded')) { continue }
        $path = [IO.Path]::GetFullPath($directory.FullName)
        $protected = @($protectedRoots | Where-Object {
            $_ -eq $path -or $_.StartsWith($path + '\', [StringComparison]::OrdinalIgnoreCase)
        }).Count -gt 0
        $running = @($processes | Where-Object {
            ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($path + '\', [StringComparison]::OrdinalIgnoreCase)) -or
            ($_.CommandLine -and $_.CommandLine.IndexOf($path + '\', [StringComparison]::OrdinalIgnoreCase) -ge 0)
        }).Count -gt 0
        if ($marker.status -eq 'building' -and $marker.pid -and @($processes | Where-Object ProcessId -eq $marker.pid).Count) { $running = $true }
        $candidates += [pscustomobject]@{ Path = $path; Kind = $kind; Status = $marker.status;
            Updated = [DateTimeOffset]::Parse($marker.updated); Protected = ($protected -or $running) }
    }
}
$remove = @()
foreach ($kind in @('portable', 'electron')) {
    $limit = if ($kind -eq 'portable') { $KeepPortable } else { $KeepElectron }
    $success = @($candidates | Where-Object { $_.Kind -eq $kind -and $_.Status -eq 'succeeded' } | Sort-Object Updated -Descending)
    $keep = @($success | Select-Object -First $limit | ForEach-Object Path)
    $remove += $candidates | Where-Object {
        $_.Kind -eq $kind -and -not $_.Protected -and
        (($_.Status -eq 'succeeded' -and $_.Path -notin $keep) -or $_.Status -eq 'failed' -or
            ($_.Status -eq 'building' -and $_.Updated -lt [DateTimeOffset]::UtcNow.AddHours(-24)))
    }
}
$releasedBytes = [long]0
foreach ($entry in $remove) {
    $path = $entry.Path
    if (-not $path.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Cleanup outside project' }
    $children = @(Get-ChildItem -LiteralPath $path -Recurse -Force)
    if ($children | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
        Write-Warning "Skip reparse directory: $path"; continue
    }
    if ($children | Where-Object { $_.Name -eq 'task.json' -and $_.FullName -notmatch '[\\/]validation[\\/]' }) {
        Write-Warning "Skip directory containing output tasks: $path"; continue
    }
    # Recheck processes immediately before deletion, not just when planning.
    if (Get-CimInstance Win32_Process | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($path + '\', [StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($path + '\', [StringComparison]::OrdinalIgnoreCase) -ge 0)
    }) { Write-Warning "Skip running directory: $path"; continue }
    $bytes = [long](($children | Where-Object { -not $_.PSIsContainer } | Measure-Object Length -Sum).Sum)
    if ($Apply) {
        # Delete reviewed individual files, then empty directories. No recursive force deletion.
        foreach ($file in ($children | Where-Object { -not $_.PSIsContainer })) { Remove-Item -LiteralPath $file.FullName }
        foreach ($directory in ($children | Where-Object PSIsContainer | Sort-Object { $_.FullName.Length } -Descending)) {
            Remove-Item -LiteralPath $directory.FullName
        }
        Remove-Item -LiteralPath $path
        $releasedBytes += $bytes
    }
    [pscustomobject]@{ Action = $(if ($Apply) { 'Removed' } else { 'Would remove' }); Path = $path; Bytes = $bytes }
}
Write-Output "Released bytes: $releasedBytes"
