param([switch]$ResolveOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$uiRoot = Join-Path $projectRoot 'electron-ui'
$electron = Join-Path $uiRoot 'node_modules/electron/dist/electron.exe'
$logDirectory = Join-Path $uiRoot 'output/preview/launcher'
$logFile = Join-Path $logDirectory 'launch.log'

try {
    if (-not (Test-Path -LiteralPath $electron)) { throw 'Missing Electron dependencies. Run npm ci in electron-ui first.' }
    $inputs = @('src', 'electron', 'public') | ForEach-Object {
        Get-ChildItem -LiteralPath (Join-Path $uiRoot $_) -Recurse -File
    }
    $inputs += Get-ChildItem -LiteralPath $uiRoot -File | Where-Object {
        $_.Name -match '^(index\.html|package(-lock)?\.json|tsconfig.*\.json|vite\.config\..+)$'
    }
    $newestInput = ($inputs | Measure-Object -Property LastWriteTimeUtc -Maximum).Maximum
    $outputs = @('dist/index.html', 'dist-electron/electron/main.js', 'dist-electron/electron/preload.js')
    $needsBuild = $false
    foreach ($relative in $outputs) {
        $target = Join-Path $uiRoot $relative
        if (-not (Test-Path -LiteralPath $target) -or (Get-Item -LiteralPath $target).LastWriteTimeUtc -lt $newestInput) {
            $needsBuild = $true
            break
        }
    }
    if ($ResolveOnly) {
        [pscustomobject]@{ Exe = $electron; Source = $uiRoot; NeedsBuild = $needsBuild; Log = $logFile } | ConvertTo-Json -Compress
        return
    }
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    # One bounded log, replaced on each launch. Existing successful builds are reused.
    ('Source preview: ' + [DateTime]::Now.ToString('s')) | Set-Content -LiteralPath $logFile -Encoding UTF8
    if ($needsBuild) {
        $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
        Push-Location $uiRoot
        try {
            # Windows PowerShell turns native stderr (including Vite warnings)
            # into error records. Judge the build by its exit code instead.
            $previousErrorPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                & $npm run build 2>&1 | Out-File -LiteralPath $logFile -Append -Encoding UTF8 -ErrorAction Stop
                $buildExitCode = $LASTEXITCODE
            } finally { $ErrorActionPreference = $previousErrorPreference }
            if ($buildExitCode -ne 0) { throw ('Preview build failed. See ' + $logFile) }
        } finally { Pop-Location }
    }
    $env:APEX_PROJECT_ROOT = $projectRoot
    # A shortcut must not inherit an old dev-server URL or another test's profile.
    Remove-Item Env:APEX_UI_DEV_URL -ErrorAction SilentlyContinue
    Remove-Item Env:APEX_UI_TEST_HOME -ErrorAction SilentlyContinue
    Remove-Item Env:APEX_DATA_ROOT -ErrorAction SilentlyContinue
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    # Only the PowerShell helper is hidden. SW_HIDE also suppresses Electron's
    # first native window display, leaving a running but invisible preview.
    Start-Process -FilePath $electron -ArgumentList ('"' + $uiRoot + '" --preview') -WorkingDirectory $uiRoot -WindowStyle Normal
} catch {
    if ($ResolveOnly) { throw }
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'AHC preview', 'OK', 'Error') | Out-Null
    exit 1
}
