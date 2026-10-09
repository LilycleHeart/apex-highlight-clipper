import tempfile
import unittest
from unittest.mock import Mock,patch
from pathlib import Path
from types import SimpleNamespace
import os
import json
import numpy as np
from ocr_cache import ExactTextCache
from damage_bisection import plan_damage_search
from verify_export import validate_segments
from apex_clipper import read_hud

class ExactReuseTests(unittest.TestCase):
    def test_explicit_keyframe_pts_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            for name in ['000001.jpg','000002.jpg']: (directory/name).write_bytes(b'fixture')
            profile={'counter_marker':'fixture.png','ammo':[0,0,1,1],'damage':[0,0,1,1],'kills':[0,0,1,1],'reference_size':[1280,540]}
            image=np.zeros((540,1280,3),dtype=np.uint8)
            engine=SimpleNamespace(text_rec=lambda crops:([('0',.99) for _ in crops],0.))
            with patch.dict(os.environ,{'APEX_OCR_BACKEND':'cpu'}),patch('rapidocr_onnxruntime.RapidOCR',return_value=engine),patch('apex_clipper.cv2.imread',return_value=image),patch('apex_clipper.counter_offset',return_value=((0,0),.99)),patch('apex_clipper.crop',return_value=np.zeros((48,64,3),dtype=np.uint8)),patch('apex_clipper.icon_signature',return_value='AA=='):
                rows=read_hud(directory,profile,2,directory/'hud.json',timestamps={'000001.jpg':0.,'000002.jpg':2.083333})
            self.assertEqual([r['time'] for r in rows],[0.,2.083333])
            self.assertEqual(json.loads((directory/'hud.json').read_text(encoding='utf-8'))['timestamp_basis'],'explicit_pts')

    def test_identical_regions_reuse_but_one_changed_pixel_is_inferred(self):
        infer=Mock(side_effect=lambda images:([('8',.99) for _ in images],0.01))
        cache=ExactTextCache(infer)
        image=np.zeros((48,32,3),dtype=np.uint8)
        first,_=cache([image,image.copy()]); second,_=cache([image.copy()])
        changed=image.copy(); changed[3,5,0]=1; cache([changed])
        self.assertEqual(first,[('8',.99),('8',.99)])
        self.assertEqual(second,[('8',.99)])
        self.assertEqual(cache.inferred,2)
        self.assertEqual(infer.call_count,2)

    def test_near_threshold_result_is_not_reused_across_batches(self):
        infer=Mock(side_effect=lambda images:([('8',.8801) for _ in images],0.01))
        cache=ExactTextCache(infer); image=np.zeros((48,32,3),dtype=np.uint8)
        cache([image]); cache([image]); self.assertEqual(infer.call_count,2)

class DamageSearchTests(unittest.TestCase):
    def test_monotonic_damage_jump_is_found_without_querying_all_frames(self):
        rows=[{'damage':0 if i<120 else 100,'kills':0,'ammo':20,'downed':False,'inactive_view':False} for i in range(240)]
        plan=plan_damage_search(len(rows),2,lambda i:rows[i],context_seconds=5)
        self.assertIn(120,plan['dense_indices'])
        self.assertLess(len(plan['probe_indices']),len(rows)//2)

    def test_observed_midpoint_reset_does_not_discard_next_round_damage(self):
        rows=[{'damage':100 if i<40 or i>=80 else 0,'kills':0,'ammo':20,'downed':False,'inactive_view':False} for i in range(121)]
        plan=plan_damage_search(len(rows),2,lambda i:rows[i],anchor_seconds=60,context_seconds=5)
        self.assertIn(80,plan['dense_indices'])

    def test_zero_damage_is_not_claimed_to_prove_no_combat(self):
        rows=[{'damage':0,'kills':0,'ammo':20 if i<10 else 10,'downed':False,'inactive_view':False} for i in range(40)]
        plan=plan_damage_search(len(rows),2,lambda i:rows[i])
        self.assertIn('无伤害',plan['warning'])
        self.assertEqual(plan['growth_brackets'],[])

class RangeVerificationTests(unittest.TestCase):
    def fixture(self,directory):
        (Path(directory)/'source.mp4').write_bytes(b'source')
        (Path(directory)/'clip.mp4').write_bytes(b'clip')
        metadata={'format':{'duration':'30'},'streams':[{'index':0,'codec_type':'video','codec_name':'h264'},{'index':1,'codec_type':'audio','codec_name':'aac'}]}
        def packets_(video,audio):
            return {0:[{'data_hash':x,'flags':'K','dts_time':str(i)} for i,x in enumerate(video)],
                    1:[{'data_hash':x,'flags':'','dts_time':str(i)} for i,x in enumerate(audio)]}
        target=packets_(['v1','v2'],['a1','a2'])
        manifest={'outputs':[str(Path(directory)/'clip.mp4')],'clips':[{'output':str(Path(directory)/'clip.mp4'),'segment':{'start':10,'end':12}}]}
        return metadata,packets_,target,manifest

    def test_missing_preroll_falls_back_without_skipping_any_target_packet(self):
        with tempfile.TemporaryDirectory() as temp:
            meta,make,target,manifest=self.fixture(temp)
            window=make(['v1','v2'],['a2']); full=make(['v0','v1','v2'],['a0','a1','a2'])
            with patch('verify_export.probe',return_value=(meta,None)),patch('verify_export.packets',side_effect=[target,window,full]) as reader:
                result=validate_segments(Path(temp)/'source.mp4',Path(temp),manifest)
            self.assertTrue(result['passed']); self.assertTrue(result['full_source_fallback_used'])
            self.assertEqual(reader.call_count,3)
            self.assertEqual(result['clips'][0]['streams'][1]['packets'],2)

    def test_changed_target_payload_still_fails_after_full_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            meta,make,target,manifest=self.fixture(temp)
            target[0][1]['data_hash']='corrupted'
            source=make(['v0','v1','v2'],['a0','a1','a2'])
            with patch('verify_export.probe',return_value=(meta,None)),patch('verify_export.packets',side_effect=[target,source,source]),self.assertRaises(AssertionError):
                validate_segments(Path(temp)/'source.mp4',Path(temp),manifest)

if __name__=='__main__': unittest.main()
