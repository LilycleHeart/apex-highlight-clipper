import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app_options import parse_options
from hud_enrichment import run_jobs,enrich_manifest_isolated
from performance_options import PRESETS,performance_options,apply_resources,RESOURCE_ENV


class PerformanceSettingsTests(unittest.TestCase):
    def test_cuda_child_uses_its_runtime_and_never_the_cpu_interpreter(self):
        from hud_enrichment import _child_python
        with tempfile.TemporaryDirectory() as tmp,patch('hud_enrichment.BASE',Path(tmp)):
            root=Path(tmp)
            cpu=root/'.venv/Scripts/python.exe';cpu.parent.mkdir(parents=True);cpu.write_bytes(b'fixture')
            with self.assertRaisesRegex(RuntimeError,'CUDA'):_child_python('cuda')
            cuda=root/'.cuda-venv/Scripts/python.exe';cuda.parent.mkdir(parents=True);cuda.write_bytes(b'fixture')
            self.assertEqual(Path(_child_python('cuda')),cuda)
            self.assertEqual(Path(_child_python('cpu')),cpu)
            bundled=root/'runtime/cuda/python.exe';bundled.parent.mkdir(parents=True);bundled.write_bytes(b'fixture')
            self.assertEqual(Path(_child_python('cuda')),bundled)

    def test_named_presets_and_custom_roundtrip_keep_recognition_parameters(self):
        for name,policy in PRESETS.items():
            options=parse_options({'performance_preset':name,'fps':2,'gap':10,'pre':6,'post':6})
            self.assertEqual({key:options[key] for key in policy},policy)
            self.assertEqual(parse_options(json.loads(json.dumps(options))),options)
            self.assertEqual([options[key] for key in ['fps','gap','pre','post']],[2,10,6,6])
        custom={'performance_preset':'custom','gpu_load':'balanced','cpu_workers':2,'decode_threads':4,'frame_cache_mb':16}
        self.assertEqual(performance_options(custom),custom)

    def test_bad_bounds_never_reach_resources(self):
        for key,values in {'cpu_workers':[0,1025,1.5,True,float('nan')],'decode_threads':[0,5,float('inf')],'frame_cache_mb':[15,129,'64']}.items():
            for value in values:
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):performance_options({'performance_preset':'custom',key:value})

    def test_backend_core_caps_and_thread_budget_are_real(self):
        import cv2
        before=cv2.getNumThreads()
        try:
            for backend,cores,expected in [('dml',16,3),('cpu',16,3),('dml',4,3)]:
                with patch.dict(os.environ),patch('performance_options.os.cpu_count',return_value=cores):
                    result=apply_resources({'backend':backend,'performance_preset':'balanced'})
                    self.assertEqual(result['cpu_workers'],expected)
                    self.assertEqual(os.environ['APEX_HUD_WORKERS'],str(expected))
                    self.assertEqual(cv2.getNumThreads(),1)
        finally:cv2.setNumThreads(before)

    def test_frozen_request_reaches_child_and_ui_edits_cannot_mutate_it(self):
        request={'backend':'dml','performance_preset':'custom','cpu_workers':2,'decode_threads':4,'frame_cache_mb':16,'gpu_load':'fast','fields':['hero'],'jobs':[{'directory':'fixture','files':['clip']}]}
        captured=[]
        def child(payload,on_progress=None,on_activity=None,**options):
            # Represents saving different next-task preferences after launch.
            future_settings={**request,'decode_threads':1,'frame_cache_mb':128}
            captured.append({key:payload[key] for key in RESOURCE_ENV})
            self.assertEqual(future_settings['decode_threads'],1)
            return {'type':'hud-info-done','updated':0,'errors':[]}
        before={value:os.environ.get(value) for value in RESOURCE_ENV.values()}
        with patch('hud_enrichment._run_hud_child',side_effect=child):run_jobs(request,emit=lambda event:None)
        self.assertEqual(captured,[{'cpu_workers':2,'decode_threads':4,'frame_cache_mb':16}])
        self.assertEqual({value:os.environ.get(value) for value in RESOURCE_ENV.values()},before)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'APEX_HUD_WORKERS':'2','APEX_DECODE_THREADS':'4','APEX_FRAME_CACHE_MB':'16'}):
            root=Path(tmp);(root/'export.json').write_text('{"outputs":["clip"],"clips":[]}','utf-8')
            with patch('hud_enrichment._run_hud_child') as child:enrich_manifest_isolated(root,fields=['hero'])
            payload=child.call_args.args[0]
            self.assertEqual([payload[key] for key in RESOURCE_ENV],[2,4,16])


if __name__=='__main__':unittest.main()
