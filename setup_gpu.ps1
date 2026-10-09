param([string]$Python = "python")
$ErrorActionPreference = 'Stop'
$GpuEnvironment = Join-Path $PSScriptRoot '.gpu-venv'
$GpuPython = Join-Path $GpuEnvironment 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $GpuPython)) {
    & $Python -m venv $GpuEnvironment
    if ($LASTEXITCODE -ne 0) { throw 'GPU virtual environment creation failed' }
}
& $GpuPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-gpu.txt')
if ($LASTEXITCODE -ne 0) { throw 'GPU dependencies installation failed' }
& $GpuPython -m pip install --no-deps rapidocr-onnxruntime==1.4.4
if ($LASTEXITCODE -ne 0) { throw 'RapidOCR installation failed' }
& $GpuPython -c "import onnxruntime as o; print(o.__version__, o.get_available_providers()); assert 'DmlExecutionProvider' in o.get_available_providers()"
if ($LASTEXITCODE -ne 0) { throw 'DirectML is unavailable in the isolated GPU environment' }
