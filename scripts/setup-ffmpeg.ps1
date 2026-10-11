param([switch]$NoDownload)
$ErrorActionPreference = 'Stop'
$ProjectDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$LocalData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [Environment]::GetFolderPath('LocalApplicationData') }
$SharedRoot = Join-Path $LocalData 'Apex Highlight Clipper\dependencies\ffmpeg'
$ToolsDirectory = Join-Path $SharedRoot '9.0.2'
$ExpectedArchiveHash = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'
$ExpectedFiles = @{
    'ffmpeg.exe' = '3256173f3f8bffd7df12227c68adf68025edb1832273a9530688a7bb1ed8edec'
    'ffprobe.exe' = 'f0d36ecbbdd3bcfac3efa078c96c7271c2e68b3810595552ac3b7f17e9a65c52'
}
function Test-Tools([string]$Directory) {
    if (-not $Directory) { return $false }
    foreach ($Name in $ExpectedFiles.Keys) {
        $File = Join-Path $Directory $Name
        if (-not (Test-Path -LiteralPath $File -PathType Leaf)) { return $false }
        if ((Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedFiles[$Name]) { return $false }
    }
    return $true
}
function Remember-Tools {
    # Keeps older Python/tool resolvers compatible, without copying executables per app version.
    @{ directory = $ToolsDirectory; version = '9.0.2'; shared = $true } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ProjectDirectory 'ffmpeg.local.json') -Encoding UTF8
    Write-Host "FFmpeg 9.0.2 ready (shared): $ToolsDirectory"
}
if (Test-Tools $ToolsDirectory) { Remember-Tools; exit 0 }
New-Item -ItemType Directory -Force -Path $SharedRoot | Out-Null
# Serializes concurrent first launches from different app versions.
$Lock = $null
for ($Attempt = 0; $Attempt -lt 120; $Attempt++) {
    try { $Lock = [IO.File]::Open((Join-Path $SharedRoot '.setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None'); break }
    catch [IO.IOException] { Start-Sleep -Milliseconds 500 }
}
if (-not $Lock) { throw 'Another FFmpeg setup is still running. Please retry shortly.' }
$Stage = Join-Path $SharedRoot ('.staging-' + [Guid]::NewGuid().ToString('N'))
try {
    if (Test-Tools $ToolsDirectory) { Remember-Tools; exit 0 }
    New-Item -ItemType Directory -Path $Stage | Out-Null
    $Candidates = @((Join-Path $ProjectDirectory 'tools'), (Join-Path $LocalData 'Programs\Apex Highlight Clipper\tools'))
    # Older portable releases commonly sit beside the new folder. Inspect only those direct neighbours.
    $Parent = Split-Path $ProjectDirectory -Parent
    foreach ($Folder in Get-ChildItem -LiteralPath $Parent -Directory -ErrorAction SilentlyContinue) {
        if (($Folder.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $Folder.FullName -eq $ProjectDirectory) { continue }
        if (Test-Path -LiteralPath (Join-Path $Folder.FullName 'scripts\setup-ffmpeg.ps1')) { $Candidates += Join-Path $Folder.FullName 'tools' }
    }
    $Existing = $Candidates | Select-Object -Unique | Where-Object { Test-Tools $_ } | Select-Object -First 1
    if ($Existing) {
        foreach ($Name in @('ffmpeg.exe','ffprobe.exe','FFmpeg-LICENSE','FFmpeg-README.txt')) {
            $File = Join-Path $Existing $Name
            if (Test-Path -LiteralPath $File -PathType Leaf) { Copy-Item -LiteralPath $File -Destination (Join-Path $Stage $Name) }
        }
        Write-Host 'Reusing existing FFmpeg installation; no download needed.'
    } else {
        $Archive = Join-Path $Stage 'ffmpeg.zip'
        $Cached = @((Join-Path $ProjectDirectory 'validation\ffmpeg-setup\ffmpeg-9.0.2.zip'), (Join-Path $ProjectDirectory 'publish\downloads\ffmpeg-9.0.2-essentials_build.zip')) |
            Where-Object { (Test-Path -LiteralPath $_ -PathType Leaf) -and (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant() -eq $ExpectedArchiveHash } | Select-Object -First 1
        if ($Cached) { $Archive = $Cached }
        elseif ($NoDownload) { throw 'No verified local FFmpeg installation or archive is available.' }
        else {
            Write-Host 'Preparing shared FFmpeg 9.0.2 (once for all app versions)...'
            Invoke-WebRequest -Uri 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip' -OutFile $Archive -UseBasicParsing
        }
        if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedArchiveHash) { throw 'FFmpeg checksum mismatch. No executable was installed.' }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $Zip = [IO.Compression.ZipFile]::OpenRead($Archive)
        try {
            foreach ($Name in @('ffmpeg.exe','ffprobe.exe','LICENSE','README.txt')) {
                $Binary = $Name.EndsWith('.exe')
                $Relative = if ($Binary) { "bin/$Name" } else { $Name }
                $Entry = $Zip.GetEntry("ffmpeg-9.0.2-essentials_build/$Relative")
                if (-not $Entry) { throw "Archive missing $Name" }
                $DestinationName = if ($Binary) { $Name } else { "FFmpeg-$Name" }
                [IO.Compression.ZipFileExtensions]::ExtractToFile($Entry,(Join-Path $Stage $DestinationName),$false)
            }
        } finally { $Zip.Dispose() }
        if ($Archive -eq (Join-Path $Stage 'ffmpeg.zip')) { Remove-Item -LiteralPath $Archive }
    }
    if (-not (Test-Tools $Stage)) { throw 'Extracted FFmpeg checksum mismatch.' }
    # Repair only this fixed version's known files; never recursively replace a user directory.
    New-Item -ItemType Directory -Force -Path $ToolsDirectory | Out-Null
    foreach ($File in Get-ChildItem -LiteralPath $Stage -File) { Move-Item -LiteralPath $File.FullName -Destination (Join-Path $ToolsDirectory $File.Name) -Force }
    Remember-Tools
} finally {
    if (Test-Path -LiteralPath $Stage) {
        $ResolvedStage = [IO.Path]::GetFullPath($Stage)
        $ResolvedRoot = [IO.Path]::GetFullPath($SharedRoot).TrimEnd('\') + '\'
        if (-not $ResolvedStage.StartsWith($ResolvedRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refusing to remove a temporary directory outside the shared FFmpeg root.' }
        foreach ($File in Get-ChildItem -LiteralPath $Stage -File) { Remove-Item -LiteralPath $File.FullName }
        Remove-Item -LiteralPath $Stage
    }
    $Lock.Dispose()
}
