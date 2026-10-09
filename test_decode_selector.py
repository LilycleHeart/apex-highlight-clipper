"""真实fast对照后的调度回归：不把low的CPU协助推广成所有档强制CPU。"""
import os
import unittest
from unittest.mock import patch
from adaptive_evidence import decode_policy
from gpu_load import get_gpu_policy


class DecodeSchedulingTests(unittest.TestCase):
    def test_fast_and_balanced_keep_cuda_for_validated_h264_setup(self):
        video={'codec_name':'h264','pix_fmt':'yuvj420p','width':2560,'height':1080,'avg_frame_rate':'120/1'}
        with patch('adaptive_evidence.os.cpu_count',return_value=16):
            for mode in ['fast','balanced']:
                with self.subTest(mode=mode),patch.dict(os.environ,{'APEX_GPU_LOAD':mode,'APEX_SMART_CPU_DECODE':'1'}):
                    self.assertEqual(decode_policy(video,True),(True,None,'cuda'))

    def test_no_speedup_claim_is_implemented_by_removing_load_limits(self):
        self.assertIsNone(get_gpu_policy('fast')['decode_rate'])
        self.assertEqual(get_gpu_policy('balanced')['decode_rate'],5)
        self.assertEqual(get_gpu_policy('low')['decode_rate'],2)
        self.assertEqual(get_gpu_policy('low')['duty'],.25)

    def test_explicit_cpu_mode_does_not_get_overridden_by_gpu_selector(self):
        with patch.dict(os.environ,{'APEX_GPU_LOAD':'fast'}):
            self.assertEqual(decode_policy({'codec_name':'h264','pix_fmt':'yuvj420p'},False),(False,None,'cpu'))

if __name__=='__main__': unittest.main()
