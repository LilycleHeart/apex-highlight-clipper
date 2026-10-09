import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import ExitStack

import numpy as np
from apex_clipper import read_hud
from sparse_pipeline import sample_and_read_sparse


class SparseHUDTests(unittest.TestCase):
    def fixtures(self,root):
        marker=root/'fixture.png';marker.write_bytes(b'fixture-marker')
        profile={'counter_marker':str(marker),'ammo':[0,0,1,1],'damage':[0,0,1,1],
                 'kills':[0,0,1,1],'reference_size':[1280,540]}
        engine=SimpleNamespace(text_rec=lambda crops:([('8',.99)]*len(crops),0.))
        stack=ExitStack()
        stack.enter_context(patch.dict(os.environ,{'APEX_OCR_BACKEND':'cpu','APEX_OCR_POOL':'0'}))
        stack.enter_context(patch('rapidocr_onnxruntime.RapidOCR',return_value=engine))
        stack.enter_context(patch('apex_clipper.cv2.imread',return_value=np.zeros((540,1280,3),np.uint8)))
        stack.enter_context(patch('apex_clipper.counter_offset',return_value=((0,0),.99)))
        stack.enter_context(patch('apex_clipper.crop',return_value=np.zeros((48,64,3),np.uint8)))
        stack.enter_context(patch('apex_clipper.icon_signature',return_value='AA=='))
        return profile,stack

    def test_noncontiguous_plan_resumes_without_renumbering_or_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); profile,stack=self.fixtures(root)
            names=['000001.jpg','000002.jpg','000278.jpg','000279.jpg']
            for name in names[:2]: (root/name).write_bytes(b'fixture')
            (root/'000009.jpg').write_bytes(b'extra-unplanned')
            with stack:
                first=read_hud(root,profile,2,root/'hud.json',resume=True,source_identity={'id':1},
                    expected_names=names,frame_limit=2,partial=True)
                self.assertEqual([r['frame'] for r in first],names[:2])
                self.assertFalse((root/'hud.json').exists())
                for name in names[2:]: (root/name).write_bytes(b'fixture')
                final=read_hud(root,profile,2,root/'hud.json',resume=True,source_identity={'id':1},expected_names=names)
            self.assertEqual([r['frame'] for r in final],names)
            self.assertEqual([r['time'] for r in final],[.25,.75,138.75,139.25])
            self.assertEqual(len((root/'hud.rows.jsonl').read_text().splitlines()),4)
            self.assertTrue(json.loads((root/'hud.json').read_text())['complete'])

    def test_missing_committed_prefix_cannot_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); profile,stack=self.fixtures(root)
            (root/'000001.jpg').write_bytes(b'fixture')
            with stack,self.assertRaisesRegex(ValueError,'缺帧'):
                read_hud(root,profile,2,root/'hud.json',expected_names=['000001.jpg','000278.jpg'])
            self.assertFalse((root/'hud.json').exists())


class SparsePipelineTests(unittest.TestCase):
    def test_callbacks_use_global_last_id_not_total_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.mp4';source.write_bytes(b'fixture');seen=[]
            def sample(*args,on_checkpoint,**kwargs):
                on_checkpoint({'chunks':[{'first':1,'count':3}]})
                on_checkpoint({'chunks':[{'first':1,'count':3},{'first':278,'count':60}]})
            def read(*args,expected_names,frame_limit=None,partial=False,**kwargs):
                if partial:seen.append(frame_limit)
                return [{'frame':name} for name in expected_names if frame_limit is None or int(name[:-4])<=frame_limit]
            module=SimpleNamespace(sample_continuous_with_resume=sample)
            with patch.dict('sys.modules',{'continuous_sampler':module}),patch('sparse_pipeline.read_hud',side_effect=read):
                rows=sample_and_read_sparse(source,tmp,{},2,Path(tmp)/'hud.json',[[1,3],[278,337]])
            self.assertEqual(seen,[322]);self.assertEqual(len(rows),63)

    def test_consumer_failure_unblocks_full_notification_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.mp4';source.write_bytes(b'fixture')
            def sample(*args,on_checkpoint,**kwargs):
                for count in range(1,21):on_checkpoint({'chunks':[{'first':1,'count':count}]})
            module=SimpleNamespace(sample_continuous_with_resume=sample);started=time.monotonic()
            with patch.dict('sys.modules',{'continuous_sampler':module}),patch('sparse_pipeline.read_hud',side_effect=RuntimeError('OCR失败')),self.assertRaisesRegex(RuntimeError,'OCR失败'):
                sample_and_read_sparse(source,tmp,{},2,Path(tmp)/'hud.json',[[1,20]])
            self.assertLess(time.monotonic()-started,3)

    def test_decoder_failure_is_not_reported_as_empty_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.mp4';source.write_bytes(b'fixture')
            def sample(*args,**kwargs):raise RuntimeError('解码失败')
            module=SimpleNamespace(sample_continuous_with_resume=sample)
            with patch.dict('sys.modules',{'continuous_sampler':module}),self.assertRaisesRegex(RuntimeError,'解码失败'):
                sample_and_read_sparse(source,tmp,{},2,Path(tmp)/'hud.json',[[1,3]])


if __name__=='__main__':unittest.main()
