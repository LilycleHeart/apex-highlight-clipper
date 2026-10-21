from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import patch
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from resource_budget import Budget,ThroughputController,Resources,resource_budget,GIB
from hud_read_queue import ClipReadQueue



class AdaptiveQueueTests(unittest.TestCase):
    def controller(self,initial=2):return ThroughputController(Budget(8,initial,1,100,()))

    def test_probe_needs_a_stable_reference_recheck_before_acceptance(self):
        policy=self.controller();policy.start(0)
        for second,work in [(1,1),(2,1),(3,1),(4,2),(5,2)]:policy.completed(second,work)
        self.assertEqual(policy.target,2);self.assertEqual(policy.phase,'control')
        policy.completed(6,1);policy.completed(7,1)
        self.assertEqual(policy.target,3);self.assertEqual(policy.history[-1]['reason'],'confirmed_throughput_gain')

    def test_background_drift_does_not_validate_a_probe(self):
        for initial in (2,8):
            policy=self.controller(initial);policy.start(0)
            for second,work in [(1,1),(2,1),(3,1),(4,2),(5,2),(7,1),(9,1)]:policy.completed(second,work)
            self.assertEqual(policy.target,initial);self.assertEqual(policy.history[-1]['reason'],'drift_or_no_gain_rollback')

    def test_faster_lower_concurrency_is_rechecked_and_can_later_probe_up(self):
        policy=self.controller(8);policy.start(0)
        for second,work in [(1,1),(2,1),(3,1)]:policy.completed(second,work)
        self.assertEqual(policy.target,7);self.assertEqual(policy.history[-1]['reason'],'bounded_down_probe')
        for second in (4,5):policy.completed(second,2)
        self.assertEqual(policy.target,8);self.assertEqual(policy.phase,'control')
        for second in (6,7):policy.completed(second,1)
        self.assertEqual(policy.target,7);self.assertEqual(policy.history[-1]['reason'],'confirmed_throughput_gain')
        for second in (8,9):policy.completed(second,2)
        self.assertEqual(policy.target,6)
        for second in (10,11):policy.completed(second,1)
        self.assertEqual(policy.target,7);self.assertEqual(policy.history[-1]['reason'],'throughput_regression_rollback')
        for second in (12,13):policy.completed(second,2)
        self.assertEqual(policy.target,8)
        for second in (14,15):policy.completed(second,3)
        self.assertEqual(policy.target,7)
        for second in (16,17):policy.completed(second,2)
        self.assertEqual(policy.target,8);self.assertEqual(policy.history[-1]['reason'],'confirmed_throughput_gain')

    def test_lower_concurrency_without_actual_gain_keeps_full_budget(self):
        policy=self.controller(8);policy.start(0)
        for second in range(1,8):policy.completed(second,1)
        self.assertEqual(policy.target,8);self.assertEqual(policy.history[-1]['reason'],'drift_or_no_gain_rollback')

    def test_hardware_not_a_fixed_universal_worker_count(self):
        low=resource_budget(Resources(4,2,8*GIB,5*GIB,2*GIB,GIB,'test'))
        high=resource_budget(Resources(64,32,128*GIB,100*GIB,24*GIB,20*GIB,'test'))
        self.assertLess(low.max_workers,high.max_workers);self.assertLess(low.initial_workers,high.initial_workers)
        self.assertEqual(low.initial_workers,low.max_workers);self.assertEqual(high.initial_workers,high.max_workers)

    def test_high_memory_budget_fills_physical_cores_and_keeps_live_reserve(self):
        resources=Resources(16,10,32*GIB,int(6.3*GIB),8*GIB,6*GIB,'fixture')
        high=resource_budget(resources,preset='high')
        self.assertEqual((high.initial_workers,high.max_workers),(10,10))
        self.assertAlmostEqual(high.ram_reserve/GIB,1.6,places=6)
        controller=ThroughputController(high)
        self.assertEqual(controller.allowed(100,high.ram_reserve+high.per_worker_bytes),10)
        self.assertEqual(controller.allowed(100,high.ram_reserve+high.per_worker_bytes-1),1)
        self.assertEqual(controller.history[-1]['reason'],'memory_pressure')
        small=resource_budget(Resources(16,10,8*GIB,6*GIB,8*GIB,6*GIB,'fixture'),preset='high')
        self.assertEqual(small.ram_reserve,GIB);self.assertLessEqual(small.max_workers,10)
        for preset,initial in (('low',1),('balanced',2),('custom',6)):
            other=resource_budget(resources,preset=preset)
            self.assertEqual((other.initial_workers,other.max_workers),(initial,6))
            self.assertAlmostEqual(other.ram_reserve/GIB,3.2,places=6)
        self.assertEqual(resource_budget(resources,preset='custom',decode_threads=4,manual_limit=10).max_workers,4)

    def test_unknown_memory_metrics_are_explicit_and_conservative(self):
        budget=resource_budget(Resources(32))
        self.assertEqual(budget.initial_workers,1)
        self.assertIn('ram_telemetry_unavailable',budget.reasons);self.assertIn('vram_telemetry_unavailable',budget.reasons)

    def test_cuda_uses_gpu_budget_and_keeps_its_backend_for_live_telemetry(self):
        from resource_budget import probe_resources
        from queue_policy import QueuePolicy
        resources=Resources(16,10,32*GIB,24*GIB,8*GIB,6*GIB,'fixture')
        self.assertEqual(resource_budget(resources,backend='cuda'),resource_budget(resources,backend='dml'))
        unknown=resource_budget(Resources(16,10,32*GIB,24*GIB),backend='cuda')
        self.assertEqual(unknown.max_workers,1);self.assertIn('vram_telemetry_unavailable',unknown.reasons)
        with patch('resource_budget.shutil.which',return_value='nvidia-smi'),patch('resource_budget.nvidia_only_adapter',return_value=False),patch('resource_budget.subprocess.check_output',return_value='8192, 6144'):
            observed=probe_resources('cuda')
        self.assertEqual((observed.gpu_total,observed.gpu_available,observed.gpu_status),(8*GIB,6*GIB,'nvidia_smi'))
        with patch.dict('os.environ',{'APEX_OCR_BACKEND':'cuda','APEX_SCHEDULE_PRESET':'high'}),patch('queue_policy.probe_resources',return_value=resources) as probe,patch('queue_policy.available_ram',return_value=24*GIB):
            policy=QueuePolicy();policy.last_gpu_check=time.monotonic()-4
            self.assertEqual(policy.capacity(100),10)
            self.assertFalse(policy._gpu_probe.result(timeout=1))
            self.assertEqual([call.args for call in probe.call_args_list],[('cuda',),('cuda',)])

    def test_slow_gpu_telemetry_does_not_block_admission_and_failed_probe_lowers_capacity(self):
        from queue_policy import QueuePolicy
        resources=Resources(8,4,16*GIB,12*GIB,8*GIB,6*GIB,'fixture')
        entered=threading.Event();release=threading.Event()
        def slow_probe(*args):
            entered.set();release.wait(2)
            raise OSError('telemetry unavailable')
        with patch('queue_policy.probe_resources',return_value=resources),patch('queue_policy.available_ram',return_value=12*GIB):
            policy=QueuePolicy()
            policy.last_gpu_check=time.monotonic()-4
            with patch('queue_policy.probe_resources',side_effect=slow_probe) as probe:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    admission=executor.submit(policy.capacity,20)
                    try:
                        self.assertTrue(entered.wait(1))
                        self.assertGreater(admission.result(timeout=.5),1)
                        pending=policy._gpu_probe
                        policy.capacity(20)
                        self.assertEqual(probe.call_count,1)
                    finally:release.set()
                    self.assertTrue(pending.result(timeout=1))
                self.assertEqual(policy.capacity(20),1)
                self.assertTrue(policy.gpu_low)

    def test_memory_pressure_drops_admission_and_resets_stale_feedback(self):
        for initial in (2,8):
            policy=self.controller(initial);policy.start(0);policy.completed(1);policy.completed(2)
            self.assertEqual(policy.allowed(20,0),1)
            self.assertIsNone(policy.reference);self.assertEqual(policy.window_done,0)
            self.assertEqual(policy.allowed(0,0),0)

    def test_different_model_mix_does_not_validate_faster_window(self):
        for initial in (2,8):
            policy=self.controller(initial);policy.start(0)
            for second in [1,2,3]:policy.completed(second,1,profile={'numeric':1})
            for second in [4,5]:policy.completed(second,2,profile={'name':2})
            self.assertEqual(policy.target,initial);self.assertEqual(policy.history[-1]['reason'],'incomparable_work_window')

    def test_cache_hits_do_not_count_as_acceleration_work(self):
        for initial in (2,8):
            policy=self.controller(initial);policy.start(0)
            for second in range(1,30):policy.completed(second,0)
            self.assertEqual(policy.history,[]);self.assertEqual(policy.target,initial)

    def test_actual_regression_immediately_reduces_target(self):
        for initial,probe in ((2,3),(8,7)):
            policy=self.controller(initial);policy.start(0)
            for second in [1,2,3]:policy.completed(second,1,profile={'numeric':1})
            self.assertEqual(policy.target,probe)
            policy.completed(5,1,profile={'numeric':1});policy.completed(7,1,profile={'numeric':1})
            self.assertEqual(policy.target,initial);self.assertEqual(policy.history[-1]['reason'],'throughput_regression_rollback')

    def test_custom_cap_and_cpu_native_thread_budget(self):
        resources=Resources(64,32,128*GIB,100*GIB,24*GIB,20*GIB,'fixture')
        custom=resource_budget(resources,preset='custom',manual_limit=7)
        self.assertEqual((custom.initial_workers,custom.max_workers),(7,7))
        self.assertEqual(resource_budget(resources,preset='low').initial_workers,1)
        self.assertEqual(resource_budget(resources,preset='balanced').initial_workers,11)
        self.assertLessEqual(resource_budget(resources,backend='cpu').max_workers,32)

    def test_tail_does_not_announce_a_probe_without_enough_real_work(self):
        for initial in (2,8):
            policy=self.controller(initial);policy.can_probe=False;policy.start(0)
            for second in [1,2,3]:policy.completed(second,1)
            self.assertEqual(policy.target,initial);self.assertEqual(policy.history[-1]['reason'],'tail_drain')

    def test_cancel_drains_only_started_reads_without_admitting_new_work(self):
        from app_cancel import TaskStopped
        gate=threading.Event();aborted=threading.Event();seen=[]
        class Policy:
            budget=SimpleNamespace(max_workers=4)
            controller=SimpleNamespace(target=2,history=[],start=lambda now:None)
            def capacity(self,remaining):return 2
            def completed(self,now,work):pass
        def read(index,activity):
            seen.append(index)
            if index==0:gate.wait(1);raise TaskStopped()
            gate.set()
            try:
                for _ in range(1000):activity({'frames_done':1});time.sleep(.001)
            except TaskStopped:aborted.set();raise
        with self.assertRaises(TaskStopped):
            with ClipReadQueue(list(range(10)),read,policy=Policy()) as queue:queue.result(0)
        self.assertEqual(set(seen),{0,1});self.assertTrue(aborted.is_set())

    def test_adaptive_cancel_resume_retains_committed_field_and_name_finalization(self):
        from unittest.mock import patch
        from pathlib import Path
        from app_cancel import TaskStopped
        from test_hud_recovery import RecoveryIntegrationTests
        from hud_enrichment import run_jobs
        fixture=RecoveryIntegrationTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        marker=fixture.root/'stop';gate=threading.Event()
        request={**fixture.request,'adaptive_schedule':True,'schedule_preset':'high','stop_file':str(marker)}
        resources=Resources(8,4,16*GIB,12*GIB)
        def read(file,fields,**options):
            if file==fixture.files[1]:
                gate.wait(1)
                for _ in range(1000):options['on_activity']({'frames_done':1});time.sleep(.001)
            return fixture.fresh(fields)
        def emit(event):
            if event['type']=='hud-info-progress' and event['index']==1:marker.write_text('stop');gate.set()
        with patch('queue_policy.probe_resources',return_value=resources),patch('queue_policy.available_ram',return_value=12*GIB),patch('hud_enrichment.recognize_video',side_effect=read):
            with self.assertRaises(TaskStopped):run_jobs(request,direct=True,emit=emit)
        job=fixture.store.list_jobs()[0];self.assertEqual(fixture.store.summary(job['id'])['fields']['done'],1)
        marker.unlink()
        with patch('queue_policy.probe_resources',return_value=resources),patch('queue_policy.available_ram',return_value=12*GIB),patch('hud_enrichment.recognize_video',return_value=fixture.fresh(['account'])) as reads:
            run_jobs({**request,'resume_job':job['id']},direct=True,emit=lambda event:None)
        self.assertEqual(reads.call_count,1);self.assertEqual(reads.call_args.args[0],fixture.files[1])
        self.assertEqual(fixture.store.load(job['id'])['status'],'completed')

    def test_real_queue_resizes_and_saves_in_order_without_duplicate_reads(self):
        main=threading.get_ident();seen=[];callbacks=[]
        class Policy:
            budget=SimpleNamespace(max_workers=4)
            controller=SimpleNamespace(target=2,history=[],start=lambda now:None)
            completed_count=0
            def capacity(self,remaining):return min(self.controller.target,remaining)
            def completed(self,now,work):
                self.completed_count+=1;self.controller.target=1 if self.completed_count<3 else 4
        def read(index,activity):
            seen.append(index);activity({'read':index});time.sleep(.002);return index
        with ClipReadQueue(list(range(12)),read,policy=Policy()) as queue:
            for index in range(12):
                self.assertEqual(queue.result(index,lambda event:callbacks.append(threading.get_ident())),index)
                queue.advance(index);self.assertLessEqual(len(queue.futures),6)
        self.assertEqual(sorted(seen),list(range(12)));self.assertTrue(all(thread==main for thread in callbacks))


if __name__=='__main__':unittest.main()
