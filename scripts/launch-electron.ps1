param([switch]$ResolveOnly, [Parameter(ValueFromRemainingArguments = $true)][string[]]$ProgramArgs = @())
$ErrorActionPreference = 'Stop'
$uiRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../electron-ui'))
$candidates = @()
foreach ($directory in Get-ChildItem -LiteralPath $uiRoot -Directory -Filter 'release*') {
    if ($directory.Name -notmatch '^release(-[a-z0-9-]+)?$' -or ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
    $exe = Join-Path $directory.FullName 'Apex Highlight Clipper-win32-x64/Apex Highlight Clipper.exe'
    if (-not (Test-Path -LiteralPath $exe)) { continue }
    $updated = $directory.LastWriteTimeUtc
    $marker = Join-Path $directory.FullName '.apex-build.json'
    if (Test-Path -LiteralPath $marker) {
        try {
            $state = Get-Content -LiteralPath $marker -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($state.status -ne 'succeeded') { continue }
            $updated = [DateTimeOffset]::Parse($state.updated).UtcDateTime
        } catch { continue }
    }
    $candidates += [pscustomobject]@{ Exe = $exe; Updated = $updated }
}
$latest = $candidates | Sort-Object Updated -Descending | Select-Object -First 1
$arguments = @($ProgramArgs)
if ($latest) { $exe = $latest.Exe } else {
    $exe = Join-Path $uiRoot 'node_modules/electron/dist/electron.exe'
    $arguments = @($uiRoot) + $arguments
}
if ($ResolveOnly) { [pscustomobject]@{ Exe = $exe; Arguments = $arguments } | ConvertTo-Json -Compress; exit 0 }
if (-not (Test-Path -LiteralPath $exe)) { throw '请先安装或打包Electron界面' }
$quoted = @($arguments | ForEach-Object {
    $value = [regex]::Replace($_, '(\\*)"', '$1$1\"')
    $value = [regex]::Replace($value, '(\\+)$', '$1$1')
    '"' + $value + '"'
}) -join ' '
if ($quoted) { Start-Process -FilePath $exe -ArgumentList $quoted -WindowStyle Normal }
else { Start-Process -FilePath $exe -WindowStyle Normal }
