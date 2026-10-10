import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from rank_reader import RankReader,read_division,recognize_segments,BASE
from apex_clipper import fingerprint

class RankTests(unittest.TestCase):
    def test_real_recording_diamond_two(self):
        frame=BASE/'validation/sample100.jpg'
        if not frame.exists(): self.skipTest('本地真实录像样本不存在')
        rank=RankReader().inspect(cv2.imread(str(frame)))
        self.assertEqual(rank['tier'],'diamond');self.assertEqual(rank['division'],'II')
        self.assertGreater(rank['confidence'],.8)

    def test_blank_wrong_layout_and_blurred_rank_are_unknown(self):
        reader=RankReader()
        self.assertIsNone(reader.inspect(np.zeros((540,1280,3),np.uint8)))
        self.assertIsNone(reader.inspect(np.zeros((1080,1920,3),np.uint8)))
        self.assertIsNone(read_division(np.zeros((8,14,3),np.uint8)))

    def test_two_existing_samples_confirm_and_checkpoint_reuses_without_ocr(self):
        frame=BASE/'validation/sample100.jpg'
        if not frame.exists(): self.skipTest('本地真实录像样本不存在')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.mp4';source.write_bytes(b'fixture')
            for i in range(3):(root/f'{i:06d}.jpg').write_bytes(frame.read_bytes())
            cache={'source':fingerprint(source),'rows':[{'time':float(i),'frame':f'{i:06d}.jpg'} for i in range(3)]}
            result=recognize_segments(cache,root,[{'start':0,'end':3}],root/'rank.json')
            self.assertEqual(result['segments'][0]['rank']['division'],'II')
            self.assertEqual(result['new_sample_frames'],0);self.assertEqual(result['ocr_calls'],0)
            with patch('rank_reader.RankReader',side_effect=AssertionError('缓存不能重算')):
                self.assertEqual(recognize_segments(cache,root,[{'start':0,'end':3}],root/'rank.json'),result)

    def test_single_frame_is_not_enough_to_claim_rank(self):
        frame=BASE/'validation/sample100.jpg'
        if not frame.exists(): self.skipTest('本地真实录像样本不存在')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.mp4';source.write_bytes(b'fixture');(root/'000000.jpg').write_bytes(frame.read_bytes())
            cache={'source':fingerprint(source),'rows':[{'time':0.,'frame':'000000.jpg'}]}
            result=recognize_segments(cache,root,[{'start':0,'end':3}],root/'rank.json')
            self.assertIsNone(result['segments'][0]['rank'])

if __name__=='__main__':unittest.main()
