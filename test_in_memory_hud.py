from fractions import Fraction
from types import SimpleNamespace
import time
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from apex_clipper import detect_events
from experimental.in_memory_hud import MemoryFrame, HUDFeatures, iter_indexed_images, read_memory_frames
from experimental.validate_in_memory_hud import validate_output_paths


class FakeReader:
    instances=[]
    overlap=False
    def __init__(self,source,threads=1):
        self.keyframes=list(range(12)); self.source_frames=1200
        self.width=100; self.height=60; self.closed=False
        self.__class__.instances.append(self)
    def __enter__(self): return self
    def __exit__(self,*args): self.close()
    def close(self): self.closed=True
    def read_keyframe(self,index):
        if index==0: time.sleep(.01)
        return SimpleNamespace(pts=index*200+3,time_base=Fraction(1,100))
    def read_burst(self,index,span):
        first=self.read_keyframe(index)
        return first,SimpleNamespace(pts=first.pts+(201 if self.overlap else 13),time_base=first.time_base),17
    def body_image(self,frame): return np.full((60,100,3),frame.pts%255,dtype=np.uint8)


class IndexedBufferTests(unittest.TestCase):
    def setUp(self): FakeReader.instances=[]; FakeReader.overlap=False

    def test_bounded_ordered_batches_preserve_fractional_pts(self):
        stats={}
        result=list(iter_indexed_images('fixture',workers=4,prefetch=4,stats=stats,reader_factory=FakeReader))
        self.assertEqual(len(result),24)
        self.assertEqual(result[0].timestamp,Fraction(3,100))
        self.assertEqual(result[1].timestamp,Fraction(16,100))
        self.assertTrue(all(a.timestamp<b.timestamp for a,b in zip(result,result[1:])))
        self.assertLessEqual(stats['max_pending_keyframes'],4)
        self.assertEqual(stats['video_packets_submitted'],12*17)
        self.assertTrue(all(r.closed for r in FakeReader.instances))

    def test_report_paths_cannot_overwrite_input_or_previous_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source.json'; source.write_text('fixture')
            with self.assertRaises(ValueError): validate_output_paths(source,[source],root)
            (root/'new-rows.json').write_text('fixture')
            with self.assertRaises(FileExistsError): validate_output_paths(root/'new.json',[source],root)
            with self.assertRaises(ValueError): validate_output_paths(root.parent/'outside.json',[source],root)

    def test_early_consumer_close_releases_all_readers(self):
        frames=iter_indexed_images('fixture',workers=2,prefetch=2,reader_factory=FakeReader)
        next(frames); frames.close()
        self.assertTrue(all(r.closed for r in FakeReader.instances))

    def test_overlapping_bursts_are_rejected_not_retimestamped(self):
        FakeReader.overlap=True
        with self.assertRaisesRegex(ValueError,'Overlapping'):
            list(iter_indexed_images('fixture',workers=1,prefetch=1,reader_factory=FakeReader))
        self.assertTrue(all(r.closed for r in FakeReader.instances))

    def test_decode_failure_closes_all_thread_owned_readers(self):
        original=FakeReader.read_keyframe
        def fail(reader,index):
            if index==4: raise RuntimeError('synthetic decode failure')
            return original(reader,index)
        with patch.object(FakeReader,'read_keyframe',fail),self.assertRaisesRegex(RuntimeError,'synthetic'):
            list(iter_indexed_images('fixture',workers=4,prefetch=4,reader_factory=FakeReader))
        self.assertTrue(all(r.closed for r in FakeReader.instances))


class MemoryFeatureTests(unittest.TestCase):
    def setUp(self):
        self.profile={'reference_size':[100,60],'ammo':[0,0,10,10],'damage':[10,0,20,10],
            'kills':[20,0,30,10],'weapon_icon':[30,0,40,10],'downed_marker_threshold':.86}
        self.marker=np.zeros((2,2),dtype=np.uint8)

    def test_roi_batch_uses_existing_numeric_rules_and_memory_ids(self):
        features=HUDFeatures(self.profile,marker=self.marker,downed_template=self.marker)
        frames=(MemoryFrame(123+i*13,Fraction(1,100),i//2,i%2,np.zeros((60,100,3),np.uint8)) for i in range(5))
        sizes=[]
        def recognize(images):
            sizes.append(len(images)); return [('24',.99),('153',.99),('2',.99)]*(len(images)//3),0.
        stats={}
        with patch('experimental.in_memory_hud.counter_offset',return_value=((0,0),.99)),patch('experimental.in_memory_hud.inactive_view',return_value=False),patch('experimental.in_memory_hud.downed_score',return_value=.2),patch('experimental.in_memory_hud.icon_signature',return_value='icon'),patch('experimental.in_memory_hud.friend_view',return_value=False):
            rows=read_memory_frames(frames,features,recognize,batch_frames=2,stats=stats)
        self.assertEqual(sizes,[6,6,3])
        self.assertEqual(stats['max_prepared_frames'],2)
        self.assertEqual(rows[0]['time'],1.23)
        self.assertEqual((rows[0]['ammo'],rows[0]['damage'],rows[0]['kills']),(24,153,2))
        self.assertTrue(all(r['frame_kind']=='memory' and not r['frame'].endswith('.jpg') for r in rows))

    def test_hidden_counter_is_not_sent_to_ocr(self):
        features=HUDFeatures(self.profile,marker=self.marker,downed_template=self.marker)
        frame=MemoryFrame(1,Fraction(1,10),0,0,np.zeros((60,100,3),np.uint8))
        with patch('experimental.in_memory_hud.counter_offset',return_value=(None,.1)),patch('experimental.in_memory_hud.inactive_view',return_value=False),patch('experimental.in_memory_hud.downed_score',return_value=.2),patch('experimental.in_memory_hud.icon_signature',return_value='icon'),patch('experimental.in_memory_hud.friend_view',return_value=False):
            rows=read_memory_frames(iter([frame]),features,lambda images:([('日',.9)]*len(images),0.))
        self.assertEqual(rows[0]['ammo'],0); self.assertIsNone(rows[0]['damage']); self.assertIsNone(rows[0]['kills'])

    def test_diagnostic_callback_cannot_retain_full_image_in_results(self):
        features=HUDFeatures(self.profile,marker=self.marker,downed_template=self.marker,feature_hook=lambda image,row:{'image':image})
        frame=MemoryFrame(0,Fraction(1,100),0,0,np.zeros((60,100,3),np.uint8))
        with patch('experimental.in_memory_hud.counter_offset',return_value=(None,.1)),patch('experimental.in_memory_hud.inactive_view',return_value=False),patch('experimental.in_memory_hud.downed_score',return_value=.2),patch('experimental.in_memory_hud.icon_signature',return_value='icon'),patch('experimental.in_memory_hud.friend_view',return_value=False),self.assertRaises(TypeError):
            features.prepare(frame)

    def test_sparse_pair_can_miss_shoot_reload_between_pairs(self):
        # Production detector is unchanged; a zero-damage shot/reload can vanish
        # entirely between two otherwise perfectly decoded burst pairs.
        icon='AAAAAAAAAAAAAAAAAAAAAA=='
        def row(t,ammo): return {'time':t,'ammo':ammo,'damage':0,'kills':0,'inactive_view':False,'weapon_icon':icon}
        sparse=[row(0,24),row(.125,24),row(2,24),row(2.125,24)]
        dense=[row(0,24),row(.5,24),row(1,12),row(1.5,24),row(2,24)]
        with patch('apex_clipper.icon_similarity',return_value=1.):
            self.assertFalse(any(e['kind']=='shoot' for e in detect_events(sparse)))
            self.assertTrue(any(e['kind']=='shoot' for e in detect_events(dense)))


if __name__=='__main__': unittest.main()
