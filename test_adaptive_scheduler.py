from fractions import Fraction
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from adaptive_scheduler import WorkBudget, ThroughputTuner, ordered_work, cpu_slots
from adaptive_ocr import AdaptiveNumericRecognizer
from app_cancel import TaskStopped
from experimental.in_memory_hud import iter_prepared_keyframes, read_memory_frames
from resume_io import RowJournal


class Probe:
    def snapshot(self):
        return {'available_memory': 10**10, 'gpu_free_memory': None, 'pressure': False}


class SchedulingTests(unittest.TestCase):
    def test_consumer_bottleneck_shrinks_pool_at_equal_throughput(self):
        tuner=ThroughputTuner(64,initial=8,window=1)
        for _ in range(2):tuner.observe(50,.5,wait_seconds=.001)
        self.assertEqual(tuner.value,4)
        for _ in range(2):tuner.observe(50,.5,wait_seconds=.1)
        self.assertLessEqual(tuner.value,4)

    def test_device_limits_respect_affinity_quota_and_memory(self):
        with patch('adaptive_scheduler.os.cpu_count',return_value=64),patch('adaptive_scheduler.os.sched_getaffinity',return_value=set(range(32)),create=True),patch('adaptive_scheduler.Path.read_text',return_value='200000 100000'):
            self.assertEqual(cpu_slots(),2)
        self.assertEqual(WorkBudget(64,2000,100).workers,19)
        self.assertEqual(WorkBudget(1,2000,100).workers,1)

    def test_unprofitable_trial_rolls_back_and_pressure_shrinks_immediately(self):
        tuner=ThroughputTuner(32,initial=4,window=1)
        for _ in range(2):tuner.observe(50,.5)
        self.assertEqual(tuner.value,6)
        for _ in range(2):tuner.observe(50,.5)
        self.assertEqual(tuner.value,4)
        tuner.observe(0,0,pressure=True)
        self.assertEqual(tuner.value,2)
        tuner.observe(0,0,ceiling=1)
        self.assertEqual(tuner.value,1)
        for _ in range(8):tuner.observe(50,.5)
        self.assertGreater(tuner.value,1)

    def test_completion_order_does_not_reorder_results_and_queue_is_bounded(self):
        stats={}; active=0; peak=0; lock=threading.Lock()
        def work(index):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            time.sleep(.015 if index==0 else .001)
            with lock:active-=1
            return index
        with ordered_work(range(24),work,budget=WorkBudget(3,1000,100),
                          tuner=ThroughputTuner(3,initial=3),probe=Probe(),stats=stats) as results:
            self.assertEqual(list(results),list(range(24)))
        self.assertLessEqual(stats['max_pending'],3);self.assertLessEqual(peak,3)
        self.assertGreater(peak,1)

    def test_batch_lookahead_is_separate_from_active_parallelism_and_ram_bound(self):
        active=0;peak=0;lock=threading.Lock();stats={}
        def work(index):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            time.sleep(.001)
            with lock:active-=1
            return index
        with ordered_work(range(20),work,budget=WorkBudget(4,600,100),tuner=ThroughputTuner(4),probe=Probe(),stats=stats,lookahead=16) as results:
            self.assertEqual(list(results),list(range(20)))
        self.assertEqual(peak,1);self.assertEqual(stats['max_pending'],5)

    def test_failure_and_consumer_cancel_join_workers_without_later_results(self):
        for failure in [RuntimeError('worker failed'),TimeoutError('callback timeout')]:
            delivered=[]
            def work(index):
                if index==3:raise failure
                return index
            with self.assertRaisesRegex(type(failure),str(failure)):
                with ordered_work(range(30),work,budget=WorkBudget(4,1000,100),probe=Probe()) as results:
                    for result in results:delivered.append(result)
            self.assertEqual(delivered,[0,1,2])
        active=threading.Event();finished=threading.Event()
        def blocked(index):active.set();time.sleep(.03);finished.set();return index
        def cancel():
            if active.is_set():raise TaskStopped()
        with self.assertRaises(TaskStopped):
            with ordered_work(range(30),blocked,budget=WorkBudget(4,1000,100),probe=Probe(),cancel=cancel) as results:
                list(results)
        self.assertTrue(finished.is_set())


class NumericBatchTests(unittest.TestCase):
    def images(self,count=48,width=64):
        return [np.full((48,width,3),i,np.uint8) for i in range(count)]

    def recognizer(self,*,fail_above=None,score=.99):
        class Recognizer:
            rec_batch_num=24
            calls=[]
            def __call__(self,images):
                self.calls.append(self.rec_batch_num)
                if fail_above and self.rec_batch_num>fail_above:raise RuntimeError('E_OUTOFMEMORY')
                return [(str(int(image[0,0,0])),score) for image in images],.001
        return Recognizer()

    def test_oom_retries_same_input_without_loss_and_keeps_safe_limit(self):
        raw=self.recognizer(fail_above=6)
        adaptive=AdaptiveNumericRecognizer(raw,backend='dml',probe=Probe(),tuner=ThroughputTuner(64,initial=24))
        values,_=adaptive(self.images())
        self.assertEqual([text for text,score in values],[str(i) for i in range(48)])
        self.assertEqual(raw.calls,[24,12,6]);self.assertEqual(raw.rec_batch_num,24)
        adaptive(self.images());self.assertEqual(raw.calls[-1],6)
        self.assertEqual(adaptive.oom_retries,2)

    def test_wide_crops_and_borderline_scores_use_canonical_grouping(self):
        raw=self.recognizer(score=.8801)
        adaptive=AdaptiveNumericRecognizer(raw,backend='cpu',probe=Probe(),tuner=ThroughputTuner(64,initial=4))
        adaptive(self.images(5));self.assertEqual(raw.calls,[4,24])
        adaptive(self.images(5,width=400));self.assertEqual(raw.calls[-1],24)
        self.assertEqual(adaptive.compatibility_calls,2)

    def test_canonical_batch_and_short_tail_never_duplicate_inference(self):
        raw=self.recognizer(score=.8801)
        adaptive=AdaptiveNumericRecognizer(raw,backend='cpu',probe=Probe(),tuner=ThroughputTuner(64,initial=24))
        adaptive(self.images());adaptive(self.images(5))
        self.assertEqual(raw.calls,[24,5]);self.assertEqual(adaptive.compatibility_calls,0)

    def test_profitable_batches_can_grow_past_legacy_24(self):
        raw=self.recognizer()
        adaptive=AdaptiveNumericRecognizer(raw,backend='dml',probe=Probe(),tuner=ThroughputTuner(96,initial=24,window=0))
        for _ in range(3):adaptive(self.images(96))
        self.assertGreater(max(raw.calls),24)

    def test_other_errors_and_stop_are_never_retried_as_oom(self):
        raw=self.recognizer()
        adaptive=AdaptiveNumericRecognizer(raw,backend='cpu',probe=Probe())
        with patch.object(type(raw),'__call__',side_effect=RuntimeError('device removed')),self.assertRaisesRegex(RuntimeError,'device removed'):
            adaptive(self.images())
        with patch('adaptive_ocr.check_cancel',side_effect=TaskStopped()),self.assertRaises(TaskStopped):adaptive(self.images())
        self.assertEqual(adaptive.oom_retries,0)


class CoarseResumeTests(unittest.TestCase):
    def test_parallel_coarse_cancel_reuses_only_committed_prefix(self):
        instances=[];reads=[]
        class Reader:
            width=100;height=60;source_frames=400;keyframes=tuple(range(40))
            def __init__(self,*args,**kwargs):self.closed=False;instances.append(self)
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
            def close(self):self.closed=True
            def read_keyframe(self,index):
                reads.append(index)
                if index%5==0:time.sleep(.002)
                return SimpleNamespace(pts=index*200+3,time_base=Fraction(1,100))
            def body_image(self,frame):return np.full((60,100,3),(frame.pts-3)//200,np.uint8)
        class Features:
            def prepare(self,frame):
                row={'frame':frame.frame_id,'time':float(frame.timestamp),'pts':frame.pts,
                     'time_base':[1,100],'keyframe_index':frame.keyframe_index}
                return row,{key:frame.image[:4,:4].copy() for key in ('ammo','damage','kills')}
        def recognize(images):return [(str(int(image[0,0,0])),.99) for image in images],0.
        budget=WorkBudget(3,1000,100)
        with tempfile.TemporaryDirectory() as temp,patch('adaptive_scheduler.WorkBudget.detect',return_value=budget),patch('adaptive_scheduler.ResourceProbe',return_value=Probe()),patch('adaptive_scheduler.ThroughputTuner',side_effect=lambda maximum,**kwargs:ThroughputTuner(maximum,initial=3)):
            path=Path(temp)/'rows.jsonl';journal=RowJournal(path,'unchanged-signature')
            def frames(start):return iter_prepared_keyframes('fixture',Features(),start_index=start,reader_factory=Reader)
            def commit(rows):
                journal.append(rows)
                if len(journal.rows)==16:raise TaskStopped()
            with self.assertRaises(TaskStopped):read_memory_frames(frames(0),Features(),recognize,on_batch=commit)
            self.assertEqual(len(journal.rows),16)
            self.assertTrue(all(reader.closed for reader in instances))
            # Mimic a hard stop after writing an uncommitted tail.
            with path.open('ab') as stream:stream.write(b'{"torn":')
            journal=RowJournal(path,'unchanged-signature');reads.clear()
            read_memory_frames(frames(len(journal.rows)),Features(),recognize,on_batch=journal.append)
            self.assertTrue(all(index>=16 for index in reads))
            self.assertEqual([row['keyframe_index'] for row in journal.rows],list(range(40)))
            self.assertEqual([row['ammo'] for row in journal.rows],list(range(40)))
            self.assertTrue(all(reader.closed for reader in instances))


class DenseResumeTests(unittest.TestCase):
    def test_fast_preparation_matches_serial_rows_across_stop_and_resume(self):
        from apex_clipper import read_hud
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);marker=root/'marker.png';marker.write_bytes(b'marker')
            for index in range(1,39):(root/f'{index:06d}.jpg').write_bytes(b'fixture')
            profile={'counter_marker':str(marker),'reference_size':[100,60],
                     'ammo':[0,0,4,4],'damage':[0,0,4,4],'kills':[0,0,4,4]}
            def image(path,*args):
                index=0 if str(path).endswith('.png') else int(Path(path).stem)
                return np.full((60,100,3),index,np.uint8)
            engine=SimpleNamespace(text_rec=lambda images:([(str(int(image[0,0,0])),.99) for image in images],0.))
            with patch('engine_pool.pooled_engine',return_value=engine),patch('apex_clipper.read_image',side_effect=image),patch('apex_clipper.counter_offset',return_value=((0,0),.99)),patch('apex_clipper.crop',side_effect=lambda image,*a:image[:4,:4].copy()),patch('apex_clipper.icon_signature',return_value='AA=='),patch('apex_clipper.inactive_view',return_value=False):
                with patch.dict(os.environ,{'APEX_GPU_LOAD':'balanced','APEX_OCR_BACKEND':'cpu'}):
                    expected=read_hud(root,profile,2,root/'serial.json')
                output=root/'fast.json'
                def stop():
                    header=root/'fast.rows.jsonl.checkpoint.json'
                    if header.exists() and '"committed": 16' in header.read_text():raise TaskStopped()
                with patch.dict(os.environ,{'APEX_GPU_LOAD':'fast','APEX_OCR_BACKEND':'cpu'}):
                    with patch('app_cancel.check_cancel',side_effect=stop),self.assertRaises(TaskStopped):
                        read_hud(root,profile,2,output,resume=True,source_identity={'id':1})
                    actual=read_hud(root,profile,2,output,resume=True,source_identity={'id':1})
                self.assertEqual(json.loads(json.dumps(actual)),json.loads(json.dumps(expected)))
                self.assertEqual(len((root/'fast.rows.jsonl').read_text().splitlines()),38)


if __name__=='__main__':unittest.main()
