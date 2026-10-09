import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import app_worker
from engine_pool import pooled_engine,clear_pool
from sample_pipeline import sample_and_read

class PipelineTests(unittest.TestCase):
    def tearDown(self): clear_pool()

    def test_engine_is_reused_but_pool_is_bounded(self):
        with patch.dict(os.environ,{'APEX_OCR_POOL':'1'}):
            engine=pooled_engine(('digits','cpu'),object)
            self.assertIs(engine,pooled_engine(('digits','cpu'),lambda:self.fail('不应重建')))
            pooled_engine(('names','cpu'),object); pooled_engine(('third','cpu'),object)
            self.assertIsNot(engine,pooled_engine(('digits','cpu'),object))

    def test_two_threads_log_complete_json_lines(self):
        output=io.StringIO(); logger=app_worker.ProgressLog('pipeline',5,65)
        barrier=threading.Barrier(2)
        def write(text): logger.write(text); barrier.wait(); logger.write('\n')
        with patch.object(app_worker.sys,'__stdout__',output):
            a=threading.Thread(target=write,args=('画面采样: 50.0% (10帧)',)); b=threading.Thread(target=write,args=('OCR: 5.0s / 10.0s',))
            a.start(); b.start(); a.join(); b.join()
        messages=[json.loads(line)['message'] for line in output.getvalue().splitlines()]
        self.assertEqual(set(messages),{'画面采样: 50.0% (10帧)','OCR: 5.0s / 10.0s'})

    def test_decoder_error_is_propagated_and_does_not_finish_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.mp4'; source.write_bytes(b'fixture')
            with patch('sample_pipeline.probe',return_value=({'format':{'duration':'12'}},None)),patch('sample_pipeline.sample_with_resume',side_effect=RuntimeError('解码失败')),self.assertRaisesRegex(RuntimeError,'解码失败'):
                sample_and_read(source,directory,{},2,Path(directory)/'hud.json')

if __name__=='__main__': unittest.main()
