# Remove only unchanged files listed by the previous package; preserve user data and edits.
$ErrorActionPreference = 'Stop'
$Content = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$Root = [IO.Path]::GetFullPath((Join-Path $Content '..')).TrimEnd('\')
if ((Split-Path $Content -Leaf) -ne 'resources' -or -not (Test-Path -LiteralPath (Join-Path $Content 'app_worker.py'))) { throw 'Invalid application layout' }
$Current = Get-Content -LiteralPath (Join-Path $Content 'FILES.sha256.json') -Raw | ConvertFrom-Json
$Allowed = @{}
foreach ($Property in $Current.PSObject.Properties) { $Allowed[$Property.Name] = $true }
$Removed = 0
$Kept = 0
$Directories = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
function Safe-OldPath([string]$Name) {
    if ($Name -match '(^[\\/]|:|(^|[\\/])\.\.([\\/]|$))') { return $null }
    $Path = [IO.Path]::GetFullPath((Join-Path $Root $Name))
    if (-not $Path.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase)) { return $null }
    $Check = $Path
    while ($Check -ne $Root) {
        if ((Test-Path -LiteralPath $Check) -and ((Get-Item -LiteralPath $Check -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { return $null }
        $Check = [IO.Path]::GetDirectoryName($Check)
    }
    return $Path
}
foreach ($Name in @('FILES.sha256.json','INSTALLER-FILES.sha256.json')) {
    $Manifest = Safe-OldPath $Name
    if (-not $Manifest -or -not (Test-Path -LiteralPath $Manifest -PathType Leaf)) { continue }
    $Entries = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
    foreach ($Entry in $Entries.PSObject.Properties) {
        $Relative = $Entry.Name.Replace('\','/')
        if ($Relative -eq 'Apex Highlight Clipper.exe' -or $Relative.StartsWith('resources/')) { continue }
        $Mapped = if ($Relative.StartsWith('app/')) { 'resources/desktop/' + $Relative.Substring(4) } else { 'resources/' + $Relative }
        if (-not $Allowed.ContainsKey($Mapped) -and $Relative -ne 'Start.cmd' -and -not $Relative.StartsWith('tools/')) { continue }
        if ($Relative.StartsWith('tools/') -and $Relative -notin @('tools/ffmpeg.exe','tools/ffprobe.exe','tools/FFmpeg-LICENSE','tools/FFmpeg-README.txt')) { continue }
        $Path = Safe-OldPath $Relative
        if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { continue }
        if ($Entry.Value -notmatch '^[a-fA-F0-9]{64}$' -or (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Entry.Value) { $Kept++; continue }
        if ([IO.Path]::GetExtension($Path) -eq '.py') {
            $CacheName = [IO.Path]::GetFileNameWithoutExtension($Path)
            $CacheRelative = [IO.Path]::Combine([IO.Path]::GetDirectoryName($Relative), '__pycache__')
            $Cache = Safe-OldPath $CacheRelative
            if ($Cache -and (Test-Path -LiteralPath $Cache -PathType Container)) {
                foreach ($Cached in Get-ChildItem -LiteralPath $Cache -File) {
                    if ($Cached.Name -match ('^' + [regex]::Escape($CacheName) + '\.cpython-311(?:\.opt-[12])?\.pyc$') -and -not ($Cached.Attributes -band [IO.FileAttributes]::ReparsePoint)) { Remove-Item -LiteralPath $Cached.FullName }
                }
                [void]$Directories.Add($Cache)
            }
        }
        Remove-Item -LiteralPath $Path
        $Removed++
        $Parent = [IO.Path]::GetDirectoryName($Path)
        while ($Parent -ne $Root) { [void]$Directories.Add($Parent); $Parent = [IO.Path]::GetDirectoryName($Parent) }
    }
    Remove-Item -LiteralPath $Manifest
}
foreach ($Directory in $Directories | Sort-Object Length -Descending) {
    if ((Test-Path -LiteralPath $Directory -PathType Container) -and @(Get-ChildItem -LiteralPath $Directory -Force).Count -eq 0) { Remove-Item -LiteralPath $Directory }
}
$OldConfig = Safe-OldPath 'ffmpeg.local.json'
$NewConfig = Join-Path $Content 'ffmpeg.local.json'
if ($OldConfig -and (Test-Path -LiteralPath $OldConfig -PathType Leaf)) {
    # This resolver configuration belongs to the application, including user-supplied tool paths.
    try {
        $Config = Get-Content -LiteralPath $OldConfig -Raw | ConvertFrom-Json
        if ($Config.directory -is [string] -and @($Config.PSObject.Properties.Name | Where-Object { $_ -notin @('directory','version','shared') }).Count -eq 0) {
            if (-not (Test-Path -LiteralPath $NewConfig)) { Move-Item -LiteralPath $OldConfig -Destination $NewConfig }
            elseif ((Get-Content -LiteralPath $NewConfig -Raw | ConvertFrom-Json).directory -eq $Config.directory) { Remove-Item -LiteralPath $OldConfig }
        }
    } catch { $Kept++ }
}
$LogDirectory = if ($env:APEX_DATA_ROOT) { Join-Path $env:APEX_DATA_ROOT 'logs' } else { Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Apex Highlight Clipper\logs' }
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
"Layout migration: removed $Removed unchanged program files; preserved $Kept modified files." | Set-Content -LiteralPath (Join-Path $LogDirectory 'layout-migration.log') -Encoding UTF8
