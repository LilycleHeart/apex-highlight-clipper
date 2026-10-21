"""Recognition-only RapidOCR adapter with explicit ONNX Runtime providers.

Factory usage: create_ocr_engine(backend='dml', model_path=...).text_rec(crops).
No package monkey patching, environment mutation, or detector/classifier sessions.
DirectML requirements: https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html
"""
from __future__ import annotations

from pathlib import Path
from contextlib import nullcontext
import ctypes
from importlib import metadata
import locale
import os
import threading
import time
from types import SimpleNamespace

import onnxruntime as ort
import rapidocr_onnxruntime
from rapidocr_onnxruntime.ch_ppocr_rec.text_recognize import TextRecognizer
from rapidocr_onnxruntime.ch_ppocr_rec.utils import CTCLabelDecode
from rapidocr_onnxruntime.utils.infer_engine import OrtInferSession
from gpu_load import get_gpu_policy,cooldown_seconds

# DirectML sessions are safe individually with sequential Run, but parallel
# sessions in this RTX3070/ORT 1.24.4 process failed during real dynamic-shape
# outcome OCR. Serialize device work and share identical live sessions.
_DML_DEVICE_LOCK = threading.RLock()
_SESSION_CACHE_LOCK = threading.RLock()
# ORT 1.24.4/DirectML also failed on the first Run of a following clip after
# the independent name model's final Python owner disappeared. Keep the small,
# fixed product model set alive for the worker lifetime, including between clips.
# Limit the set rather than evicting a live device graph in the middle of work.
_LIVE_SESSIONS = {}
_MAX_DML_SESSIONS = 8
# CUDA readers share models across worker threads, with their own capacity so
# enabling a comparison does not consume or evict any DirectML session.
_CUDA_LIVE_SESSIONS = {}
_MAX_CUDA_SESSIONS = 8
_CUDA_DLLS_PRELOADED = False
_CUDA_DLL_HANDLES = {}
# Only low/balanced CUDA pacing serializes models, including the rest period.
# Fast CUDA leaves independent model sessions free to execute concurrently.
_CUDA_THROTTLE_LOCK = threading.RLock()


def _preload_packaged_cudnn():
    if os.name != 'nt':
        return
    # New cuDNN releases add sublibraries beyond ORT's fixed preload list.
    # Use the installed package's RECORD, never another environment or PATH.
    package = metadata.distribution('nvidia-cudnn-cu12')
    libraries = [file for file in package.files or ()
                 if len(file.parts) == 4 and file.parts[:3] == ('nvidia', 'cudnn', 'bin')
                 and file.name.lower().startswith('cudnn') and file.suffix.lower() == '.dll']
    if not libraries:
        raise RuntimeError('nvidia-cudnn-cu12 未登记 cuDNN DLL，请检查 CUDA 运行环境。')
    for file in sorted(libraries, key=lambda value: value.name):
        path = Path(package.locate_file(file)).resolve(strict=True)
        if not path.is_file():
            raise FileNotFoundError(f'cuDNN DLL 不存在：{path}')
        key = os.path.normcase(str(path))
        if key not in _CUDA_DLL_HANDLES:
            _CUDA_DLL_HANDLES[key] = ctypes.WinDLL(str(path))


def _preload_cuda_dlls():
    global _CUDA_DLLS_PRELOADED
    with _SESSION_CACHE_LOCK:
        if not _CUDA_DLLS_PRELOADED:
            # ORT 1.24.4 searches this environment's NVIDIA packages first.
            # Keep DLL discovery local; no PATH mutation or torch dependency.
            ort.preload_dlls(cuda=True, cudnn=True, msvc=True, directory='')
            _preload_packaged_cudnn()
            _CUDA_DLLS_PRELOADED = True


class ExplicitOrtSession(OrtInferSession):
    """Reuse RapidOCR's metadata interface, replacing only session creation."""

    def __init__(self, model_path, backend, device_id=0, profile_prefix=None):
        self._verify_model(model_path)
        provider = {'cpu': 'CPUExecutionProvider', 'dml': 'DmlExecutionProvider',
                    'cuda': 'CUDAExecutionProvider'}.get(backend)
        if provider is None:
            raise ValueError(f'Unknown OCR backend: {backend}')
        if provider not in ort.get_available_providers():
            raise RuntimeError(f'{provider} unavailable; available={ort.get_available_providers()}')
        if backend == 'cuda':
            _preload_cuda_dlls()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.enable_mem_pattern = backend != 'dml'
        if profile_prefix:
            options.enable_profiling = True
            options.profile_file_prefix = str(profile_prefix)
        provider_options = {'device_id': str(device_id)}
        if backend == 'cuda':
            # Compare the existing FP32 models without TF32's reduced mantissa.
            provider_options['use_tf32'] = '0'
        providers = [(provider, provider_options)] if backend != 'cpu' else [provider]
        if backend != 'cpu':
            providers.append('CPUExecutionProvider')
        with _DML_DEVICE_LOCK if backend == 'dml' else nullcontext():
            self.session = ort.InferenceSession(str(model_path), sess_options=options,
                                                providers=providers)
            self.session.disable_fallback()
        if self.session.get_providers()[0] != provider:
            raise RuntimeError(f'{provider} session initialization fell back: {self.session.get_providers()}')
        self._lock = threading.Lock()
        self.backend = backend
        self.model_path = str(Path(model_path).resolve())

    def __call__(self, input_content):
        from pipeline_metrics import record
        record(getattr(self,'model_path','unknown'),input_content)
        cuda_policy=get_gpu_policy() if self.backend=='cuda' else None
        execution_lock=(_DML_DEVICE_LOCK if self.backend=='dml' else
                        _CUDA_THROTTLE_LOCK if cuda_policy and cuda_policy['duty']<1 else nullcontext())
        # DirectML disallows concurrent Run calls on one session. Lock the CPU
        # interface too so a caller can safely swap providers.
        with execution_lock:
            with self._lock:
                started=time.perf_counter()
                try:
                    result=self.session.run(self.get_output_names(),
                                            dict(zip(self.get_input_names(), [input_content])))
                except UnicodeDecodeError as error:
                    # ORT's native error can contain localized Windows text in
                    # the ANSI code page; pybind then attempts UTF-8 decoding.
                    # Preserve the actual DirectML/device error for diagnostics.
                    encoding = 'mbcs' if os.name == 'nt' else locale.getpreferredencoding(False)
                    message = error.object.decode(encoding, errors='replace')
                    raise RuntimeError(f'{self.backend} inference failed for shape '
                                       f'{input_content.shape}: {message}') from error
                if self.backend=='dml' or cuda_policy:
                    policy=get_gpu_policy() if self.backend=='dml' else cuda_policy
                    pause=cooldown_seconds(time.perf_counter()-started,policy)
                    if pause: time.sleep(pause)
                return result

    def describe(self):
        options = self.session.get_session_options()
        policy=get_gpu_policy() if self.backend in {'dml','cuda'} else None
        return {'backend': self.backend, 'onnxruntime_version': ort.__version__,
                'model_path': self.model_path, 'providers': self.session.get_providers(),
                'provider_options': self.session.get_provider_options(),
                'memory_pattern': options.enable_mem_pattern,
                'device_execution_serialized': self.backend == 'dml' or bool(policy and policy['duty']<1),
                'load_policy': policy,
                'execution_mode': str(options.execution_mode),
                'intra_op_threads': options.intra_op_num_threads,
                'inter_op_threads': options.inter_op_num_threads}


def create_ocr_engine(*, backend='cpu', model_path=None, rec_batch_num=24,
                      device_id=0, profile_prefix=None):
    """Return .text_rec(crops) -> ([(text, confidence), ...], elapsed).

    CPU is the safe default. GPU requests are strict: an unavailable provider
    raises instead of silently running the whole model on CPU. Unsupported
    individual GPU operators may run on CPU; inspect an ORT profile to measure.
    Existing OCR crop sizes, normalization, sorting, CTC and dictionary are
    preserved by reusing RapidOCR 1.4.4's TextRecognizer methods.
    """
    if int(rec_batch_num) < 1:
        raise ValueError('rec_batch_num must be positive')
    if model_path is None:
        model_path = Path(rapidocr_onnxruntime.__file__).parent / 'models' / 'ch_PP-OCRv4_rec_infer.onnx'
    reused = False
    if backend in {'dml', 'cuda'} and profile_prefix is None:
        resolved = Path(model_path).resolve()
        stat = resolved.stat()
        key = (str(resolved), stat.st_size, stat.st_mtime_ns, backend, device_id)
        sessions = _LIVE_SESSIONS if backend == 'dml' else _CUDA_LIVE_SESSIONS
        capacity = _MAX_DML_SESSIONS if backend == 'dml' else _MAX_CUDA_SESSIONS
        with _SESSION_CACHE_LOCK:
            session = sessions.get(key)
            reused = session is not None
            if session is None:
                if len(sessions)>=capacity:
                    raise RuntimeError('本识别工作进程已达到模型会话上限，请重新启动识别工作进程。')
                session = ExplicitOrtSession(model_path, backend, device_id, profile_prefix)
                sessions[key] = session
    else:
        session = ExplicitOrtSession(model_path, backend, device_id, profile_prefix)
    recognizer = TextRecognizer.__new__(TextRecognizer)
    recognizer.session = session
    recognizer.postprocess_op = CTCLabelDecode(character=session.get_character_list())
    recognizer.rec_batch_num = min(int(rec_batch_num),get_gpu_policy()['batch']) if backend in {'dml','cuda'} else int(rec_batch_num)
    recognizer.rec_image_shape = [3, 48, 320]
    return SimpleNamespace(text_rec=recognizer, backend_info={**session.describe(), 'session_reused': reused,'rec_batch_num':recognizer.rec_batch_num})


def create_full_ocr_engine(*, backend='cpu', model_path=None, rec_batch_num=24,
                           device_id=0, **rapidocr_kwargs):
    """Full RapidOCR engine with CPU detection/classification and chosen rec EP.

    Keeps the normal engine(image, use_cls=False), .text_det and .text_rec
    interfaces used by outcome_reader. Detection/classification stay on CPU;
    only recognition is accelerated. This avoids claiming an untested GPU
    detector is ready. Use the recognition-only factory for numeric batches.
    """
    from rapidocr_onnxruntime import RapidOCR
    rec = create_ocr_engine(backend=backend, model_path=model_path,
                           rec_batch_num=rec_batch_num, device_id=device_id)
    settings = dict(intra_op_num_threads=2, inter_op_num_threads=1,
                    rec_batch_num=rec_batch_num)
    settings.update(rapidocr_kwargs)
    # The wrapper always controls provider selection. Do not enable RapidOCR's
    # older DML session settings via kwargs.
    for stage in ('det', 'cls', 'rec'):
        settings[f'{stage}_use_cuda'] = False
        settings[f'{stage}_use_dml'] = False
    if model_path is not None:
        settings['rec_model_path'] = str(model_path)
    engine = RapidOCR(**settings)
    engine.text_rec = rec.text_rec
    engine.backend_info = {**rec.backend_info, 'det_backend': 'cpu', 'cls_backend': 'cpu'}
    return engine
