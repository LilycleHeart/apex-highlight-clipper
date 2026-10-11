param(
    [switch]$Apply,
    [switch]$PurgeLegacyTests,
    [switch]$SkipImageCache,
    [string]$OutputRoot = '',
    [string]$UserData = '',
    [string]$DataRoot = '',
    [ValidateRange(1, 10)][int]$KeepRecent = 3,
    [ValidateRange(1, 90)][int]$MaxAgeDays = 7
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$validationRoot = Join-Path $(if ($DataRoot) { [IO.Path]::GetFullPath($DataRoot) } else { $projectRoot }) 'validation'
if (-not (Test-Path -LiteralPath $validationRoot -PathType Container)) { exit 0 }
if ((Get-Item -LiteralPath $validationRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse validation root' }
$maintenanceLock = $null
try {
    $lockPath = Join-Path $validationRoot '.maintenance.lock'
    if ((Test-Path -LiteralPath $lockPath) -and ((Get-Item -LiteralPath $lockPath).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Reparse maintenance lock' }
    $maintenanceLock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
} catch [IO.IOException] { Write-Output 'Skipped: maintenance is already running'; exit 0 }
try {
function Inside([string]$Child, [string]$Parent) {
    return $Child.Equals($Parent, [StringComparison]::OrdinalIgnoreCase) -or $Child.StartsWith($Parent + '\', [StringComparison]::OrdinalIgnoreCase)
}
function Read-Json([string]$File) { return Get-Content -LiteralPath $File -Raw -Encoding UTF8 | ConvertFrom-Json }
function Worker-Running {
    return @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^python(w|3([.]\d+)?)?[.]exe$' -and $_.CommandLine -and $_.CommandLine -match 'app_worker[.]py|hud_enrichment[.]py|repair_cached_statistics[.]py' -and
        $_.CommandLine.IndexOf($projectRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0
    }).Count -gt 0
}
if (Worker-Running) { Write-Output 'Skipped: recognition worker is running'; exit 0 }
$taskFiles = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$roots = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$protectedSources = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$protectedPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$taskScanOK = $true
if ($OutputRoot) { [void]$roots.Add([IO.Path]::GetFullPath($OutputRoot)) }
if ($DataRoot) { [void]$roots.Add((Join-Path ([IO.Path]::GetFullPath($DataRoot)) 'tasks')) }
try {
    $last = Read-Json (Join-Path $validationRoot 'app-last-task.json')
    if ($last.task) { [void]$taskFiles.Add($last.task); [void]$roots.Add((Split-Path (Split-Path $last.task))) }
} catch { if (Test-Path -LiteralPath (Join-Path $validationRoot 'app-last-task.json')) { $taskScanOK = $false } }
if ($UserData -and (Test-Path -LiteralPath (Join-Path $UserData 'library.json'))) {
    try {
        $library = Read-Json (Join-Path $UserData 'library.json')
        foreach ($file in $library.tasks) { [void]$taskFiles.Add($file) }
        foreach ($root in $library.roots) { [void]$roots.Add($root) }
    } catch { $taskScanOK = $false }
}
function Find-Tasks([string]$Directory, [int]$Depth) {
    if (-not (Test-Path -LiteralPath $Directory -PathType Container)) { return }
    if ((Get-Item -LiteralPath $Directory).Attributes -band [IO.FileAttributes]::ReparsePoint) { return }
    $file = Join-Path $Directory 'task.json'
    if (Test-Path -LiteralPath $file -PathType Leaf) { [void]$taskFiles.Add($file); return }
    if ($Depth -ge 3) { return }
    foreach ($child in Get-ChildItem -LiteralPath $Directory -Directory) {
        if ($child.Name -notin @('validation', 'runtime', 'node_modules', '.git')) { Find-Tasks $child.FullName ($Depth + 1) }
    }
}
foreach ($cache in Get-ChildItem -LiteralPath (Join-Path $validationRoot 'app-cache') -Directory -ErrorAction SilentlyContinue) {
    if ($cache.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
    try {
        $usage = Read-Json (Join-Path $cache.FullName '.cache-use.json')
        if ($usage.task -and [IO.Path]::IsPathRooted($usage.task)) { [void]$taskFiles.Add($usage.task) }
    } catch {}
}
foreach ($root in $roots) { Find-Tasks $root 0 }
foreach ($file in $taskFiles) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { continue }
    try {
        $task = Read-Json $file
        if ($task.version -notin @(1, 2) -or -not $task.items) { $taskScanOK = $false; continue }
        foreach ($item in $task.items) {
            if ($item.status -eq 'complete') { continue }
            if ($item.source -and -not (Inside ([IO.Path]::GetFullPath($item.source)) $validationRoot)) { [void]$protectedSources.Add($item.source) }
            foreach ($name in @('analysis_cache', 'sample_directory')) {
                if ($item.$name) { [void]$protectedPaths.Add([IO.Path]::GetFullPath($item.$name)) }
                if ($item.record.$name) { [void]$protectedPaths.Add([IO.Path]::GetFullPath($item.record.$name)) }
            }
        }
    } catch { $taskScanOK = $false }
}
$deletedBytes = [long]0; $deletedFiles = 0; $deletedDirectories = 0
function Mark-Pruned([string]$Cache) {
    if (-not $Apply) { return }
    if ((Split-Path $Cache -Parent) -ne (Join-Path $validationRoot 'app-cache') -or (Split-Path $Cache -Leaf) -notmatch '^[a-f0-9]{16}$') { throw 'Invalid cache marker target' }
    if ((Get-Item -LiteralPath $Cache).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse cache' }
    $marker = Join-Path $Cache '.images-pruned.json'
    if (-not (Test-Path -LiteralPath $marker)) {
        @{ generation = [Guid]::NewGuid().ToString('N'); cleaned = [DateTimeOffset]::UtcNow.ToString('o') } |
            ConvertTo-Json -Compress | Set-Content -LiteralPath $marker -Encoding UTF8
    }
}
$sampleReferences = @()
foreach ($cache in Get-ChildItem -LiteralPath (Join-Path $validationRoot 'app-cache') -Directory -ErrorAction SilentlyContinue) {
    if ($cache.Name -notmatch '^[a-f0-9]{16}$' -or ($cache.Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
    try {
        $samples = [IO.Path]::GetFullPath((Read-Json (Join-Path $cache.FullName 'sample-reference.json')).samples)
        $sampleReferences += [pscustomobject]@{ Cache = $cache.FullName; Samples = $samples }
        $source = (Read-Json (Join-Path $cache.FullName 'hud.json')).source.path
        if ($protectedSources.Contains($source)) { [void]$protectedPaths.Add($samples) }
    } catch {}
}
function Delete-File($File) {
    if (-not (Inside $File.FullName $validationRoot)) { throw 'Cleanup outside validation' }
    if ($File.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse file' }
    if ($Apply) { Remove-Item -LiteralPath $File.FullName -ErrorAction Stop }
    $script:deletedBytes += $File.Length; $script:deletedFiles++
}
function Delete-Tree([string]$Directory) {
    if (-not (Inside $Directory $validationRoot) -or $Directory -eq $validationRoot) { throw 'Invalid cleanup directory' }
    if ((Get-Item -LiteralPath $Directory).Attributes -band [IO.FileAttributes]::ReparsePoint) { return }
    $ownCache = (Split-Path $Directory -Parent) -eq (Join-Path $validationRoot 'app-cache') -and (Split-Path $Directory -Leaf) -match '^[a-f0-9]{16}$'
    $ownMarker = if ($ownCache) { Join-Path $Directory '.images-pruned.json' } else { '' }
    if ($ownCache) { Mark-Pruned $Directory }
    $entries = @(Get-ChildItem -LiteralPath $Directory -Recurse -Force)
    if ($entries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { Write-Warning "Skip linked directory: $Directory"; return }
    if (Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and (Inside $_.ExecutablePath $Directory) }) { return }
    if (Worker-Running) { throw 'Worker started; stop cleanup' }
    foreach ($reference in $sampleReferences) {
        if ((Inside $reference.Samples $Directory) -and -not (Inside $reference.Cache $Directory) -and (Test-Path -LiteralPath $reference.Cache)) { Mark-Pruned $reference.Cache }
    }
    $files = @($entries | Where-Object { -not $_.PSIsContainer -and $_.FullName -ne $ownMarker })
    $script:deletedBytes += [long](($files | Measure-Object Length -Sum).Sum); $script:deletedFiles += $files.Count
    if ($Apply) {
        # Every descendant was checked above. Delete subtrees without force; keep the recovery marker until last.
        $directChildren = @(Get-ChildItem -LiteralPath $Directory -Force)
        foreach ($dir in ($directChildren | Where-Object PSIsContainer)) { Remove-Item -LiteralPath $dir.FullName -Recurse -ErrorAction Stop }
        $rootFiles = @($directChildren | Where-Object { -not $_.PSIsContainer -and $_.FullName -ne $ownMarker })
        if ($rootFiles.Count) { Remove-Item -LiteralPath @($rootFiles.FullName) -ErrorAction Stop }
        if ($ownMarker -and (Test-Path -LiteralPath $ownMarker)) { Delete-File (Get-Item -LiteralPath $ownMarker) }
        Remove-Item -LiteralPath $Directory
    }
    $script:deletedDirectories++
}
$cutoff = [DateTime]::UtcNow.AddDays(-$MaxAgeDays)
# Explicit historical diagnostic/test names; unknown directories and human annotations stay untouched.
$legacyPattern = '^(accuracy-ui-|blanca-|combat-|decode-|early-round-probe-|electron-ui-|ffmpeg-first-run$|filter-|fine-|fixed-scroll-|fluid-ui-|focused-|fps-compatibility-|gap-fill-|geometry-|indexed-ui-|kaomoji-|legacy-fps-|local-resume-|mascot-reference$|optimization$|own-result-|packaged-ui-|page-scroll-|pipeline-|player-|primary-fluid-|public-snapshot-|puppet-|push-snapshot-|quality-export-|rank-probe$|real-filter-|refinement-|resume-test-|retired-v3$|smart-test-|stats-|update-ui-|v[35]-fixture$|v5-ui-fixture$|app-tests$|__pycache__$)'
$diagnostics = @(Get-ChildItem -LiteralPath $validationRoot -Directory | Where-Object { $_.Name -match $legacyPattern -or (Test-Path -LiteralPath (Join-Path $_.FullName '.apex-validation.json')) })
$recentDiagnostics = @($diagnostics | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First $KeepRecent | ForEach-Object FullName)
foreach ($dir in $diagnostics) {
    if (-not $PurgeLegacyTests -and $dir.LastWriteTimeUtc -ge $cutoff -and $dir.FullName -in $recentDiagnostics) { continue }
    if (-not $taskScanOK) { continue }
    if (@($protectedPaths | Where-Object { Inside $_ $dir.FullName }).Count) { continue }
    Delete-Tree $dir.FullName
}
foreach ($file in Get-ChildItem -LiteralPath (Join-Path $validationRoot 'app-requests') -File -ErrorAction SilentlyContinue) {
    if ($file.Name -match '^[a-f0-9-]{36}(-counter-repair)?[.](json|stop)$' -and ($PurgeLegacyTests -or $file.LastWriteTimeUtc -lt $cutoff)) { Delete-File $file }
}
$summaries = @(Get-ChildItem -LiteralPath $validationRoot -File -Filter '*report.json' | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First $KeepRecent | ForEach-Object FullName)
foreach ($file in Get-ChildItem -LiteralPath $validationRoot -File) {
    if ($file.Name -in @('app-last-task.json', 'user-labelled-non-combat.json', '.maintenance.json') -or $file.FullName -in $summaries) { continue }
    if ($file.Extension -notin @('.jpg', '.jpeg', '.png', '.log', '.json', '.mp4')) { continue }
    if ($file.Name -like '*label*' -or $file.Name -like '*annotation*') { continue }
    if ($PurgeLegacyTests -or $file.LastWriteTimeUtc -lt $cutoff) { Delete-File $file }
}
# Keep only recent cache runs. Finished results live in the output task, not in validation.
$protectedIDs = @(); $cacheDirectoriesRemoved = 0
if ($taskScanOK -and -not $SkipImageCache) {
    $python = Join-Path $projectRoot 'runtime/cpu/python.exe'
    if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $projectRoot '.venv/Scripts/python.exe' }
    $helper = Join-Path $PSScriptRoot 'validation-task-caches.py'
    try {
        $existingTasks = @($taskFiles | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
        $json = ConvertTo-Json -InputObject $existingTasks -Compress
        $info = [Diagnostics.ProcessStartInfo]::new()
        $info.FileName = $python; $info.Arguments = '"' + $helper + '"'
        $info.UseShellExecute = $false; $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true; $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
        $info.EnvironmentVariables['PYTHONUTF8'] = '1'
        $reader = [Diagnostics.Process]::Start($info)
        $inputBytes = [Text.Encoding]::UTF8.GetBytes($json)
        $reader.StandardInput.BaseStream.Write($inputBytes, 0, $inputBytes.Length); $reader.StandardInput.Close()
        $result = $reader.StandardOutput.ReadToEnd(); $failure = $reader.StandardError.ReadToEnd(); $reader.WaitForExit()
        if ($reader.ExitCode -ne 0) { throw "Task cache inventory failed: $failure" }
        $protectedIDs = @($result | ConvertFrom-Json); $reader.Dispose()
    } catch { $taskScanOK = $false; Write-Warning 'Cache cleanup skipped: cannot verify paused tasks' }
    if ($taskScanOK) {
        $jobs = @()
        foreach ($dir in Get-ChildItem -LiteralPath (Join-Path $validationRoot 'app-cache') -Directory -ErrorAction SilentlyContinue) {
            if ($dir.Name -notmatch '^[a-f0-9]{16}$' -or ($dir.Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
            $used = $dir.LastWriteTimeUtc
            foreach ($name in @('hud.json', '.cache-use.json')) {
                $file = Join-Path $dir.FullName $name
                if (Test-Path -LiteralPath $file) { $used = (Get-Item -LiteralPath $file).LastWriteTimeUtc }
            }
            $source = ''
            try { $source = (Read-Json (Join-Path $dir.FullName 'hud.json')).source.path } catch {}
            $protected = $dir.Name -in $protectedIDs -or $protectedSources.Contains($source) -or
                @($protectedPaths | Where-Object { Inside $_ $dir.FullName }).Count -gt 0
            $valid = -not (Test-Path -LiteralPath (Join-Path $dir.FullName '.images-pruned.json'))
            $jobs += [pscustomobject]@{ Path = $dir.FullName; Used = $used; Protected = $protected; Valid = $valid }
        }
        $keep = @($jobs | Where-Object Valid | Sort-Object Used -Descending | Select-Object -First $KeepRecent | ForEach-Object Path)
        # Older generations may supply the samples of a recent run: keep those dependencies too.
        do {
            $previousCount = $keep.Count
            foreach ($reference in $sampleReferences) {
                if ($reference.Cache -notin $keep) { continue }
                foreach ($candidate in $jobs) {
                    if ((Inside $reference.Samples $candidate.Path) -and $candidate.Path -notin $keep) { $keep += $candidate.Path }
                }
            }
        } while ($keep.Count -gt $previousCount)
        foreach ($job in ($jobs | Sort-Object Used)) {
            if ($job.Protected -or $job.Path -in $keep) { continue }
            $lockFile = Join-Path $job.Path '.resume.lock'
            try {
                if (Test-Path -LiteralPath $lockFile) { $stream = [IO.File]::Open($lockFile, 'Open', 'ReadWrite', 'None'); $stream.Dispose() }
            } catch [IO.IOException] { continue }
            Delete-Tree $job.Path; $cacheDirectoriesRemoved++
            if ($cacheDirectoriesRemoved % 10 -eq 0) { Write-Output "Removed old caches: $cacheDirectoriesRemoved" }
        }
    }
}
[pscustomobject]@{ Applied = [bool]$Apply; Bytes = $deletedBytes; Files = $deletedFiles; Directories = $deletedDirectories;
    CacheDirectoriesRemoved = $cacheDirectoriesRemoved; KeepRecent = $KeepRecent; TaskScanOK = $taskScanOK; ProtectedSources = $protectedSources.Count } | ConvertTo-Json -Compress
if ($Apply -and $taskScanOK -and -not $SkipImageCache) {
    $retainedCount = @(Get-ChildItem -LiteralPath (Join-Path $validationRoot 'app-cache') -Directory -ErrorAction SilentlyContinue).Count
    @{ completed = [DateTimeOffset]::UtcNow.ToString('o'); cache_count = $retainedCount } | ConvertTo-Json -Compress |
        Set-Content -LiteralPath (Join-Path $validationRoot '.maintenance.json') -Encoding UTF8
}
} finally { $maintenanceLock.Dispose() }
