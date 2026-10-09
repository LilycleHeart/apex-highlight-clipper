from fractions import Fraction
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from apex_clipper import BASE,write_json
from app_cancel import TaskStopped
from app_options import parse_options
from app_task import open_task,save_task
from experimental.in_memory_hud import MemoryFrame
from indexed_coarse import indexed_coarse_scan,_runtime_version
from smart_scan import smart_read
from test_core import row


class IndexedModeTests(unittest.TestCase):
    def test_indexed_cannot_recycle_or_enable_full_pipeline(self):
        options=parse_options({'scan_mode':'indexed','delete_source':True,'pipeline':True})
        self.assertEqual(options['scan_mode'],'indexed')
        self.assertFalse(options['delete_source']); self.assertFalse(options['pipeline'])

    def test_new_indexed_namespace_and_resume_freeze(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'APEX_DISABLE_LAST_TASK':'1'}):
            source=Path(temp)/'fixture.mp4'; source.write_bytes(b'fixture')
            request={'files':[str(source)],'output':temp,'backend':'cpu','scan_mode':'indexed'}
            path,task,_,_=open_task(request); save_task(path,task)
            self.assertEqual(task['smart_cache_version'],'indexed-v2')
            _,again,_,options=open_task({'resume_task':str(path),'scan_mode':'smart'})
            self.assertEqual(options['scan_mode'],'indexed'); self.assertEqual(again['smart_cache_version'],'indexed-v2')
            task['smart_cache_version']='indexed-v1';save_task(path,task)
            _,old,_,_=open_task({'resume_task':str(path)})
            self.assertEqual(old['smart_cache_version'],'indexed-v1')
            path,task,_,_=open_task({**request,'scan_mode':'smart'}); save_task(path,task)
            _,_,_,options=open_task({'resume_task':str(path),'scan_mode':'indexed'})
            self.assertEqual(options['scan_mode'],'smart')

    def test_missing_pyav_has_actionable_message(self):
        with patch.dict('sys.modules',{'av':None}),self.assertRaisesRegex(RuntimeError,'requirements-experimental'):
            _runtime_version()

    def test_nonzero_stream_origin_is_rejected_before_any_sampling(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'fixture.mp4'; source.write_bytes(b'fixture')
            with patch('indexed_coarse._runtime_version',return_value='fixture'),patch('indexed_coarse.IndexedKeyframeReader') as reader:
                reader.return_value.__enter__.return_value.stream.start_time=100
                with self.assertRaisesRegex(RuntimeError,'PTS'):
                    indexed_coarse_scan(source,temp,{},2)
            self.assertFalse((Path(temp)/'indexed-coarse').exists())

    def test_dense_hud_remains_final_and_file_coarse_refinement_is_not_used(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'fixture.mp4'; source.write_bytes(b'fixture'); output=root/'hud.json'
            coarse={'rows':[row(20,ammo=20,damage=100,kills=1),row(22,ammo=17,damage=145,kills=1)],'numeric_frames':2,'refinement_numeric_frames':0}
            coarse['rows'][0]['frame']='memory:key-0'; coarse['rows'][1]['frame']='memory:key-1'
            def dense(samples,profile,fps,path,**kwargs):
                rows=[row(20,ammo=20,damage=100,kills=1),row(20.5,ammo=20,damage=100,kills=1),row(22,ammo=17,damage=145,kills=1),row(22.5,ammo=17,damage=145,kills=1)]
                for i,r in enumerate(rows): r['frame']=f'{i+1:06d}.jpg'
                write_json(path,{'rows':rows,'outcome_events':[]}); return rows
            with patch('indexed_coarse.indexed_coarse_scan',return_value=coarse),patch('smart_scan.coarse_scan') as old,patch('smart_scan.refine_coarse') as refine,patch('smart_scan.probe',return_value=({'format':{'duration':'30'}},{})),patch('smart_scan.sample_with_resume') as sample,patch('smart_scan.read_hud',side_effect=dense),patch('smart_scan.enrich_outcomes',side_effect=lambda c,*a,**k:c),patch('smart_scan.audit_counters',return_value={'passed':True}):
                rows,_=smart_read(source,root,root/'samples',{},2,output,indexed=True,result_first=True)
                self.assertFalse(old.called); self.assertFalse(refine.called); self.assertTrue(sample.called)
                self.assertFalse(any(r['frame'].startswith('memory:') for r in rows))
                plan=json.loads((root/'smart-plan.json').read_text(encoding='utf-8'))
                self.assertEqual(plan['strategy'],'indexed-v1')
                self.assertEqual(plan['early_round_strategy'],'disabled_no_coarse_image_cache')


class IndexedCheckpointTests(unittest.TestCase):
    def test_cancel_after_block_then_resume_only_remaining_keyframes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'fixture.mp4'; source.write_bytes(b'fixture')
            profile=json.loads((BASE/'profile-ultrawide.json').read_text(encoding='utf-8'))
            starts=[]; stop=[True]
            class Reader:
                def __init__(self,*a,**k):
                    self.keyframes=[SimpleNamespace(dts=i*200,position=i*100,size=100) for i in range(20)]
                    self.stream=SimpleNamespace(start_time=0)
                def __enter__(self): return self
                def __exit__(self,*a): pass
            class Features:
                def __init__(self,*a,**k): pass
                def prepare(self,frame):
                    r={'frame':frame.frame_id,'frame_kind':'memory','keyframe_index':frame.keyframe_index,
                       'pts':frame.pts,'time_base':[1,100],'time':float(frame.timestamp),'weapon_icon':'icon',
                       'inactive_view':False,'downed':False,'friend_spectate':False}
                    return r,{key:np.zeros((4,4,3),np.uint8) for key in ['ammo','damage','kills']}
            class Recognizer:
                def __call__(self,images): return [('24',.99),('100',.99),('1',.99)]*(len(images)//3),0.
                def stats(self): return {}
            def frames(*args,start_index=0,**kwargs):
                starts.append(start_index)
                for index in range(start_index,20): yield MemoryFrame(index*200,Fraction(1,100),index,0,np.zeros((4,4,3),np.uint8))
            def cancel():
                header=root/'indexed-coarse/rows.jsonl.checkpoint.json'
                if stop[0] and header.exists() and json.loads(header.read_text())['committed']>=16: raise TaskStopped()
            with patch('indexed_coarse._runtime_version',return_value='fixture'),patch('indexed_coarse.IndexedKeyframeReader',Reader),patch('indexed_coarse.HUDFeatures',Features),patch('indexed_coarse.numeric_recognizer',return_value=Recognizer()),patch('indexed_coarse.iter_indexed_images',side_effect=frames),patch('indexed_coarse.check_cancel',side_effect=cancel):
                with self.assertRaises(TaskStopped): indexed_coarse_scan(source,root,profile,2)
                stop[0]=False
                result=indexed_coarse_scan(source,root,profile,2)
                self.assertEqual(starts,[0,16]); self.assertEqual(len(result['rows']),20)
                self.assertEqual(result['frame_storage'],'memory_only')
                self.assertFalse(list((root/'indexed-coarse').glob('[0-9]*.jpg')))


if __name__=='__main__': unittest.main()
