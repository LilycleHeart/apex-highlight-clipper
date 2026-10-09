import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from gpu_load import get_gpu_policy,cooldown_seconds
from app_options import parse_options
import app_worker

class GpuLoadTests(unittest.TestCase):
    def test_desktop_defaults_to_low_and_accepts_all_three_modes(self):
        self.assertEqual(parse_options({})['gpu_load'],'low')
        for mode in ['low','balanced','fast']:
            self.assertEqual(parse_options({'gpu_load':mode})['gpu_load'],mode)
        with self.assertRaises(ValueError): parse_options({'gpu_load':'30%'})

    def test_pacing_leaves_idle_time_and_limits_burst_size(self):
        low=get_gpu_policy('low'); balanced=get_gpu_policy('balanced'); fast=get_gpu_policy('fast')
        self.assertLess(low['batch'],balanced['batch'])
        self.assertLess(balanced['batch'],fast['batch'])
        self.assertAlmostEqual(cooldown_seconds(.02,low),.06)
        self.assertAlmostEqual(cooldown_seconds(.02,balanced),.02)
        self.assertEqual(cooldown_seconds(.02,fast),0)
        self.assertGreater(cooldown_seconds(0,low),0)
        self.assertEqual(low['decode_rate'],2)
        self.assertIsNone(fast['decode_rate'])

    def test_environment_selects_policy(self):
        with patch.dict(os.environ,{'APEX_GPU_LOAD':'balanced'}):
            self.assertEqual(get_gpu_policy()['name'],'balanced')

    def test_progress_log_emits_to_original_pipe_without_recursion(self):
        events=io.StringIO()
        with patch.object(app_worker.sys,'__stdout__',events):
            app_worker.stage('sample','采样',5,30,lambda:print('画面采样: 50.0% (10帧)',flush=True))
        rows=[json.loads(line) for line in events.getvalue().splitlines()]
        self.assertEqual([r['type'] for r in rows],['stage','log','progress'])
        self.assertEqual(rows[1]['progress'],18)

if __name__=='__main__': unittest.main()
