import gc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import weakref

import numpy as np

import gpu_ocr_backend as backend


class DeviceModelLifetimeTests(unittest.TestCase):
    def test_model_survives_between_clip_owners_and_is_reused(self):
        class Session:
            def get_character_list(self):return ['A','B']
            def describe(self):return {'backend':'dml'}
        references=[]
        def create(*args):
            session=Session();references.append(weakref.ref(session));return session
        with tempfile.TemporaryDirectory() as temporary,patch.dict(backend._LIVE_SESSIONS,{},clear=True),patch.object(backend,'ExplicitOrtSession',side_effect=create):
            model=Path(temporary)/'model.onnx';model.write_bytes(b'test')
            owner=backend.create_ocr_engine(backend='dml',model_path=model)
            del owner;gc.collect()
            self.assertIsNotNone(references[0]())
            next_clip=backend.create_ocr_engine(backend='dml',model_path=model)
            self.assertIs(next_clip.text_rec.session,references[0]())
            self.assertTrue(next_clip.backend_info['session_reused']);self.assertEqual(len(references),1)

    def test_capacity_does_not_evict_a_device_graph_during_work(self):
        class Session:
            def get_character_list(self):return ['A']
            def describe(self):return {'backend':'dml'}
        with tempfile.TemporaryDirectory() as temporary,patch.dict(backend._LIVE_SESSIONS,{},clear=True),patch.object(backend,'_MAX_DML_SESSIONS',2),patch.object(backend,'ExplicitOrtSession',side_effect=lambda *args:Session()):
            paths=[Path(temporary)/f'{i}.onnx' for i in range(3)]
            for path in paths:path.write_bytes(b'test')
            first=backend.create_ocr_engine(backend='dml',model_path=paths[0]);backend.create_ocr_engine(backend='dml',model_path=paths[1])
            with self.assertRaisesRegex(RuntimeError,'模型会话上限'):backend.create_ocr_engine(backend='dml',model_path=paths[2])
            self.assertIs(backend.create_ocr_engine(backend='dml',model_path=paths[0]).text_rec.session,first.text_rec.session)


class CudaAdapterTests(unittest.TestCase):
    def test_preload_once_before_creation_and_disable_tf32_without_device_lock(self):
        events=[]
        native=Mock()
        native.get_providers.return_value=['CUDAExecutionProvider','CPUExecutionProvider']
        class ForbiddenLock:
            def __enter__(self):raise AssertionError('CUDA must not acquire the DirectML device lock')
            def __exit__(self,*args):pass
        def create(*args,**kwargs):
            events.append('session')
            return native
        with tempfile.TemporaryDirectory() as temporary,patch.object(backend,'_CUDA_DLLS_PRELOADED',False),patch.object(
                backend.ort,'get_available_providers',return_value=['CUDAExecutionProvider','CPUExecutionProvider']),patch.object(
                backend.ort,'preload_dlls',side_effect=lambda **kwargs:events.append('preload')) as preload,patch.object(
                backend.ort,'InferenceSession',side_effect=create) as factory,patch.object(
                backend,'_preload_packaged_cudnn'),patch.object(backend,'_DML_DEVICE_LOCK',ForbiddenLock()):
            model=Path(temporary)/'model.onnx';model.write_bytes(b'test')
            first=backend.ExplicitOrtSession(model,'cuda',device_id=2)
            backend.ExplicitOrtSession(model,'cuda',device_id=2)
            self.assertEqual(events,['preload','session','session'])
            preload.assert_called_once_with(cuda=True,cudnn=True,msvc=True,directory='')
            self.assertEqual(factory.call_args.kwargs['providers'],[
                ('CUDAExecutionProvider',{'device_id':'2','use_tf32':'0'}),'CPUExecutionProvider'])
            native.get_inputs.return_value=[SimpleNamespace(name='image')]
            native.get_outputs.return_value=[SimpleNamespace(name='prediction')]
            # Context manager methods need explicit delegation on a Mock.
            lock=unittest.mock.MagicMock()
            lock.__enter__.side_effect=first._lock.__enter__
            lock.__exit__.side_effect=first._lock.__exit__
            first._lock=lock
            tensor=np.zeros((1,3,48,320),np.float32)
            first(tensor)
            lock.__enter__.assert_called_once();lock.__exit__.assert_called_once()
            native.run.assert_called_once()

    def test_cuda_factory_shares_concurrent_readers_without_using_dml_capacity(self):
        class Session:
            def get_character_list(self):return ['A','B']
            def describe(self):return {'backend':'mock'}
        with tempfile.TemporaryDirectory() as temporary,patch.dict(backend._LIVE_SESSIONS,{},clear=True),patch.dict(
                backend._CUDA_LIVE_SESSIONS,{},clear=True),patch.object(backend,'_MAX_CUDA_SESSIONS',1),patch.object(
                backend,'ExplicitOrtSession',side_effect=lambda *args:Session()) as create:
            model=Path(temporary)/'model.onnx';model.write_bytes(b'test')
            barrier=threading.Barrier(3)
            def read(_):
                barrier.wait(timeout=2)
                return backend.create_ocr_engine(backend='cuda',model_path=model)
            with ThreadPoolExecutor(max_workers=3) as pool:engines=list(pool.map(read,range(3)))
            self.assertEqual(create.call_count,1)
            self.assertTrue(all(engine.text_rec.session is engines[0].text_rec.session for engine in engines))
            dml=backend.create_ocr_engine(backend='dml',model_path=model)
            self.assertIsNot(dml.text_rec.session,engines[0].text_rec.session)
            changed=Path(temporary)/'other.onnx';changed.write_bytes(b'test')
            with self.assertRaisesRegex(RuntimeError,'模型会话上限'):
                backend.create_ocr_engine(backend='cuda',model_path=changed)
            self.assertIs(backend.create_ocr_engine(backend='cuda',model_path=model).text_rec.session,engines[0].text_rec.session)
            profiled=backend.create_ocr_engine(backend='cuda',model_path=model,profile_prefix=Path(temporary)/'profile')
            self.assertIsNot(profiled.text_rec.session,engines[0].text_rec.session)
            self.assertEqual(len(backend._CUDA_LIVE_SESSIONS),1)

    def test_cpu_and_dml_keep_original_provider_options_without_preloading(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(backend.ort,'preload_dlls') as preload,patch.object(
                backend.ort,'get_available_providers',return_value=['CPUExecutionProvider','DmlExecutionProvider']):
            model=Path(temporary)/'model.onnx';model.write_bytes(b'test')
            for mode,provider,options in [
                    ('cpu','CPUExecutionProvider',['CPUExecutionProvider']),
                    ('dml','DmlExecutionProvider',[('DmlExecutionProvider',{'device_id':'0'}),'CPUExecutionProvider'])]:
                with self.subTest(backend=mode):
                    native=Mock();native.get_providers.return_value=[provider]
                    with patch.object(backend.ort,'InferenceSession',return_value=native) as create:
                        backend.ExplicitOrtSession(model,mode)
                    self.assertEqual(create.call_args.kwargs['providers'],options)
                    self.assertEqual(create.call_args.kwargs['sess_options'].enable_mem_pattern,mode!='dml')
            preload.assert_not_called()


class CudaPacingTests(unittest.TestCase):
    def session(self,run):
        session=backend.ExplicitOrtSession.__new__(backend.ExplicitOrtSession)
        session.backend='cuda';session.model_path='fixture.onnx';session._lock=threading.Lock()
        native=Mock();native.run.side_effect=run
        native.get_inputs.return_value=[SimpleNamespace(name='image')]
        native.get_outputs.return_value=[SimpleNamespace(name='prediction')]
        native.get_session_options.return_value=SimpleNamespace(
            enable_mem_pattern=True,execution_mode='sequential',intra_op_num_threads=2,inter_op_num_threads=1)
        native.get_providers.return_value=['CUDAExecutionProvider','CPUExecutionProvider']
        native.get_provider_options.return_value={'CUDAExecutionProvider':{'use_tf32':'0'}}
        session.session=native
        return session

    def test_low_balanced_hold_other_models_until_cooldown_but_fast_can_overlap(self):
        tensor=np.zeros((1,3,48,320),np.float32)
        for mode in ['low','balanced','fast']:
            with self.subTest(mode=mode),patch.dict('os.environ',{'APEX_GPU_LOAD':mode}):
                blocked=threading.Event();release=threading.Event();second_started=threading.Event();second_ran=threading.Event()
                owner=[]
                def first_run(*args):
                    owner.append(threading.get_ident())
                    if mode=='fast':blocked.set();release.wait(2)
                    return []
                def pause(seconds):
                    if threading.get_ident()==owner[0]:blocked.set();release.wait(2)
                first=self.session(first_run);second=self.session(lambda *args:second_ran.set())
                def second_call():
                    second_started.set()
                    return second(tensor)
                with patch.object(backend.time,'sleep',side_effect=pause) as sleep,ThreadPoolExecutor(max_workers=2) as pool:
                    pending=pool.submit(first,tensor)
                    try:
                        self.assertTrue(blocked.wait(1))
                        following=pool.submit(second_call)
                        self.assertTrue(second_started.wait(1))
                        self.assertEqual(second_ran.wait(.25 if mode=='fast' else .03),mode=='fast')
                    finally:release.set()
                    pending.result(timeout=1);following.result(timeout=1)
                    self.assertEqual(sleep.call_count,0 if mode=='fast' else 2)
                description=first.describe()
                self.assertEqual(description['device_execution_serialized'],mode!='fast')
                self.assertEqual(description['load_policy']['name'],mode)

    def test_cuda_batch_limit_follows_load_policy_even_when_session_is_reused(self):
        class Session:
            def get_character_list(self):return ['A']
            def describe(self):return {'backend':'cuda'}
        with tempfile.TemporaryDirectory() as temporary,patch.dict(backend._CUDA_LIVE_SESSIONS,{},clear=True),patch.object(
                backend,'ExplicitOrtSession',return_value=Session()) as create:
            model=Path(temporary)/'model.onnx';model.write_bytes(b'test')
            for mode,limit in [('low',4),('balanced',8),('fast',24)]:
                with self.subTest(mode=mode),patch.dict('os.environ',{'APEX_GPU_LOAD':mode}):
                    engine=backend.create_ocr_engine(backend='cuda',model_path=model,rec_batch_num=24)
                    self.assertEqual(engine.text_rec.rec_batch_num,limit)
                    self.assertEqual(backend.create_ocr_engine(backend='cuda',model_path=model,rec_batch_num=2).text_rec.rec_batch_num,2)
            self.assertEqual(create.call_count,1)


@unittest.skipUnless(backend.os.name=='nt','cuDNN sublibrary discovery is Windows-only')
class CudaDependencyDiscoveryTests(unittest.TestCase):
    def package(self,root,names):
        files=[PurePosixPath('nvidia/cudnn/bin')/name for name in names]
        for file in files:
            target=root/str(file);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'dll')
        return SimpleNamespace(files=files,locate_file=lambda file:root/str(file))

    def test_installed_record_loads_all_cudnn_sublibraries_by_absolute_path_once(self):
        names=['cudnn64_9.dll','cudnn_engines_tensor_ir64_9.dll','cudnn_ext64_9.dll','cudnn_cnn64_9.dll']
        events=[];handles=[]
        def load(path):
            events.append(path);handle=object();handles.append(handle);return handle
        with tempfile.TemporaryDirectory() as temporary,patch.object(backend,'_CUDA_DLLS_PRELOADED',False),patch.dict(
                backend._CUDA_DLL_HANDLES,{},clear=True),patch.object(
                backend.ort,'preload_dlls',side_effect=lambda **kwargs:events.append('ort')),patch.object(
                backend.ctypes,'WinDLL',side_effect=load) as loader:
            root=Path(temporary);package=self.package(root,names)
            package.files.extend([PurePosixPath('other/bin/cudnn_fake64_9.dll'),
                                  PurePosixPath('nvidia/cudnn/bin/readme.txt')])
            with patch.object(backend.metadata,'distribution',return_value=package) as distribution:
                backend._preload_cuda_dlls();backend._preload_cuda_dlls()
            distribution.assert_called_once_with('nvidia-cudnn-cu12')
            expected=[str((root/'nvidia/cudnn/bin'/name).resolve()) for name in sorted(names)]
            self.assertEqual(events,['ort',*expected])
            self.assertEqual(loader.call_count,4)
            self.assertEqual(list(backend._CUDA_DLL_HANDLES.values()),handles)
            self.assertTrue(backend._CUDA_DLLS_PRELOADED)

    def test_missing_package_or_recorded_file_does_not_mark_preload_complete(self):
        with patch.object(backend,'_CUDA_DLLS_PRELOADED',False),patch.object(backend.ort,'preload_dlls'),patch.object(
                backend.metadata,'distribution',side_effect=backend.metadata.PackageNotFoundError('nvidia-cudnn-cu12')),patch.object(
                backend.ctypes,'WinDLL') as loader:
            with self.assertRaises(backend.metadata.PackageNotFoundError):backend._preload_cuda_dlls()
            self.assertFalse(backend._CUDA_DLLS_PRELOADED);loader.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary,patch.object(backend,'_CUDA_DLLS_PRELOADED',False),patch.object(
                backend.ort,'preload_dlls'),patch.object(backend.ctypes,'WinDLL') as loader:
            root=Path(temporary)
            package=SimpleNamespace(files=[PurePosixPath('nvidia/cudnn/bin/cudnn_ext64_9.dll')],
                                    locate_file=lambda file:root/str(file))
            with patch.object(backend.metadata,'distribution',return_value=package):
                with self.assertRaises(FileNotFoundError):backend._preload_cuda_dlls()
                self.assertFalse(backend._CUDA_DLLS_PRELOADED);loader.assert_not_called()
                package.files=[]
                with self.assertRaisesRegex(RuntimeError,'未登记 cuDNN DLL'):backend._preload_cuda_dlls()
                self.assertFalse(backend._CUDA_DLLS_PRELOADED)

    def test_load_failure_retains_successful_handles_and_retry_finishes_missing_library(self):
        first,second=object(),object()
        with tempfile.TemporaryDirectory() as temporary,patch.object(backend,'_CUDA_DLLS_PRELOADED',False),patch.dict(
                backend._CUDA_DLL_HANDLES,{},clear=True),patch.object(backend.ort,'preload_dlls'),patch.object(
                backend.ctypes,'WinDLL',side_effect=[first,OSError('fixture load failure'),second]) as loader:
            package=self.package(Path(temporary),['cudnn64_9.dll','cudnn_ext64_9.dll'])
            with patch.object(backend.metadata,'distribution',return_value=package):
                with self.assertRaisesRegex(OSError,'fixture load failure'):backend._preload_cuda_dlls()
                self.assertFalse(backend._CUDA_DLLS_PRELOADED)
                self.assertEqual(list(backend._CUDA_DLL_HANDLES.values()),[first])
                backend._preload_cuda_dlls()
            self.assertTrue(backend._CUDA_DLLS_PRELOADED)
            self.assertEqual(list(backend._CUDA_DLL_HANDLES.values()),[first,second])
            self.assertEqual(loader.call_count,3)
            self.assertEqual(loader.call_args_list[1].args,loader.call_args_list[2].args)


if __name__=='__main__':unittest.main()
