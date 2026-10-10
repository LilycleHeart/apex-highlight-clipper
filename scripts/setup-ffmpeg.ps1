$ErrorActionPreference = 'Stop'
$ProjectDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$ToolsDirectory = Join-Path $ProjectDirectory 'tools'
$DownloadDirectory = Join-Path $ProjectDirectory 'validation\ffmpeg-setup'
New-Item -ItemType Directory -Force -Path $ToolsDirectory,$DownloadDirectory | Out-Null
$Archive = Join-Path $DownloadDirectory 'ffmpeg-9.0.2.zip'
$Url = 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip'
Write-Host 'Preparing FFmpeg 9.0.2 from Gyan official distribution (first run only)...'
if (-not (Test-Path -LiteralPath $Archive)) { Invoke-WebRequest -Uri $Url -OutFile $Archive -UseBasicParsing }
$ExpectedHash = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'
if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedHash) { throw 'FFmpeg checksum mismatch. No executable was installed.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$Zip = [IO.Compression.ZipFile]::OpenRead($Archive)
try {
    foreach ($Name in @('ffmpeg.exe','ffprobe.exe')) {
        $Entry = $Zip.Entries | Where-Object { $_.FullName -eq "ffmpeg-9.0.2-essentials_build/bin/$Name" } | Select-Object -First 1
        if (-not $Entry) { throw "Archive missing $Name" }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($Entry,(Join-Path $ToolsDirectory $Name),$false)
    }
    foreach ($Name in @('LICENSE','README.txt')) {
        $Entry = $Zip.Entries | Where-Object { $_.FullName -eq "ffmpeg-9.0.2-essentials_build/$Name" } | Select-Object -First 1
        if ($Entry) { [IO.Compression.ZipFileExtensions]::ExtractToFile($Entry,(Join-Path $ToolsDirectory "FFmpeg-$Name"),$true) }
    }
} finally { $Zip.Dispose() }
Write-Host 'FFmpeg ready. License and upstream build information are in tools/.'
