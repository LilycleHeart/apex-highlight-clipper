param(
    [switch]$CPU,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)
$ErrorActionPreference = 'Stop'
$GpuPython = Join-Path $PSScriptRoot '.gpu-venv\Scripts\python.exe'
$PythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!$CPU -and (Test-Path -LiteralPath $GpuPython)) {
    $PythonPath = $GpuPython
    $env:APEX_OCR_BACKEND = 'dml'
} else {
    $env:APEX_OCR_BACKEND = 'cpu'
}
if (!(Test-Path -LiteralPath $PythonPath)) {
    throw '请先创建 .venv 并安装 requirements.txt'
}
$env:PYTHONIOENCODING = 'utf-8'
& $PythonPath (Join-Path $PSScriptRoot 'apex_clipper.py') @Arguments
exit $LASTEXITCODE
