param([string]$Python = "python")
$ErrorActionPreference = 'Stop'
$CudaEnvironment = Join-Path $PSScriptRoot '.cuda-venv'
$CudaPython = Join-Path $CudaEnvironment 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $CudaPython)) {
    & $Python -m venv $CudaEnvironment
    if ($LASTEXITCODE -ne 0) { throw 'CUDA virtual environment creation failed' }
}
& $CudaPython -m pip install --no-cache-dir -r (Join-Path $PSScriptRoot 'requirements-cuda.txt')
if ($LASTEXITCODE -ne 0) { throw 'CUDA dependencies installation failed' }
& $CudaPython -m pip install --no-cache-dir --no-deps rapidocr-onnxruntime==1.4.4
if ($LASTEXITCODE -ne 0) { throw 'RapidOCR installation failed' }
Push-Location $PSScriptRoot
try {
    & $CudaPython -c "import numpy as np; from gpu_ocr_backend import create_ocr_engine; e=create_ocr_engine(backend='cuda',rec_batch_num=1); e.text_rec([np.zeros((32,160,3),dtype=np.uint8)]); print(e.backend_info); assert e.backend_info['providers'][0]=='CUDAExecutionProvider'"
    if ($LASTEXITCODE -ne 0) { throw 'CUDA model initialization failed; CPU and DirectML environments were not changed' }
} finally {
    Pop-Location
}
