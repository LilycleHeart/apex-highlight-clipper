from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engine_pool import init_worker_pool,pooled_engine
from hud_read_queue import ClipReadQueue
import test_hud_enrichment as fixtures
from hud_enrichment import enrich_manifest,run_jobs


class HudReadQueueTests(unittest.TestCase):
    def test_lookahead_is_bounded_and_callbacks_stay_on_commit_thread(self):
        started=[];barrier=threading.Barrier(2);main=threading.get_ident();callbacks=[]
        def read(index,activity):
            started.append(index)
            if index<2:barrier.wait(timeout=3)
            activity({'index':index});return index*10
        with ClipReadQueue(list(range(5)),read,2) as queue:
            self.assertEqual(queue.result(0,lambda event:callbacks.append((threading.get_ident(),event))),0)
            self.assertTrue({0,1}.issubset(started));self.assertTrue(set(started).issubset({0,1,2,3}))
            for index in range(5):
                self.assertEqual(queue.result(index),index*10);queue.advance(index)
                self.assertLessEqual(len(queue.futures),4)
        self.assertTrue(callbacks);self.assertTrue(all(thread==main for thread,_ in callbacks))

    def test_completed_lookahead_refills_while_head_waits_without_unbounded_retention(self):
        release=threading.Event();refilled=threading.Event()
        def read(index,activity):
            if index==0:
                if not release.wait(timeout=3):raise AssertionError('head was not released')
            if index==3:refilled.set()
            return index
        try:
            with ClipReadQueue(list(range(20)),read,2) as queue:
                deadline=time.monotonic()+2
                while not refilled.is_set() and time.monotonic()<deadline:
                    queue._feedback();refilled.wait(.01)
                self.assertTrue(refilled.is_set(),'completed reads prevented idle workers from refilling')
                self.assertEqual(len(queue.futures),4)
                self.assertFalse(queue.futures[0].done())
                release.set()
                for index in range(20):
                    self.assertEqual(queue.result(index),index);queue.advance(index)
                    self.assertLessEqual(len(queue.futures),4)
        finally:release.set()

    def test_remaining_group_grows_into_released_shared_pool_capacity(self):
        from hud_read_queue import shared_read_pool
        policy=SimpleNamespace(budget=SimpleNamespace(max_workers=4),resources=None,
            controller=SimpleNamespace(start=lambda now:None,target=4,actual_level=False,history=[]),
            capacity=lambda remaining:4,observe=lambda *args:None)
        entered=threading.Event();leave=threading.Event();release=threading.Event();full=threading.Event()
        started=[];lock=threading.Lock()
        def other_group():
            with ClipReadQueue([0],lambda item,activity:item) as queue:
                entered.set()
                if not leave.wait(timeout=3):raise AssertionError('other group was not released')
                queue.result(0);queue.advance(0)
        def read(index,activity):
            with lock:
                started.append(index)
                if len(started)==4:full.set()
            if not release.wait(timeout=3):raise AssertionError('reads were not released')
            return index
        try:
            with shared_read_pool(policy,2,9),ThreadPoolExecutor(max_workers=1) as coordinator:
                other=coordinator.submit(other_group)
                self.assertTrue(entered.wait(timeout=2))
                with ClipReadQueue(list(range(8)),read) as queue:
                    self.assertEqual(queue.next_index,2)
                    leave.set();other.result(timeout=2)
                    queue._feedback()
                    self.assertTrue(full.wait(timeout=2),'remaining group kept its original two-read share')
                    self.assertEqual(queue.next_index,4)
                    release.set()
                    for index in range(8):
                        self.assertEqual(queue.result(index),index);queue.advance(index)
                        self.assertLessEqual(len(queue.futures),6)
        finally:leave.set();release.set()

    def test_worker_reader_state_is_not_shared_but_reused_in_its_thread(self):
        barrier=threading.Barrier(2)
        def worker(_):
            first=pooled_engine('mutable',object);barrier.wait(timeout=3)
            return first,pooled_engine('mutable',object)
        with patch.dict(os.environ,{'APEX_OCR_POOL':'1'}),ThreadPoolExecutor(max_workers=2,initializer=init_worker_pool) as executor:
            results=list(executor.map(worker,range(2)))
        self.assertTrue(all(first is second for first,second in results))
        self.assertIsNot(results[0][0],results[1][0])

    def test_explicit_engine_pool_opt_out_is_preserved_in_worker(self):
        def worker():return pooled_engine('mutable',object),pooled_engine('mutable',object)
        with patch.dict(os.environ,{'APEX_OCR_POOL':'0'}),ThreadPoolExecutor(max_workers=1,initializer=init_worker_pool) as executor:
            first,second=executor.submit(worker).result()
        self.assertIsNot(first,second)

    def test_other_read_worker_aborts_cooperatively_after_first_failure(self):
        ready=threading.Event();aborted=threading.Event()
        def read(index,activity):
            if index==0:
                ready.wait(timeout=2);raise ValueError('first failed')
            ready.set()
            try:
                for _ in range(1000):activity({'index':index});time.sleep(.001)
            except BaseException:
                aborted.set();raise
        with self.assertRaisesRegex(ValueError,'first failed'):
            with ClipReadQueue([0,1],read) as queue:queue.result(0)
        self.assertTrue(aborted.is_set())

    def test_parallel_preparation_keeps_manifest_and_progress_order(self):
        fixture=fixtures.HudEnrichmentTests();results=[]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=fixture.fixture(root)
            for workers in ['1','2']:
                (root/'export.json').write_text(json.dumps(manifest),'utf-8');progress=[]
                def recognize(source,fields,**options):return copy.deepcopy(fixture.fresh(['account'],account={'name':'READ_ONLY','confidence':.99}))
                with patch.dict(os.environ,{'APEX_HUD_WORKERS':workers}),patch('hud_enrichment.recognize_video',side_effect=recognize):
                    results.append(enrich_manifest(root,[str(file) for file in files],['account'],lambda index,total,file:progress.append(index),force=True))
                self.assertEqual(progress,list(range(1,len(files)+1)))
        self.assertEqual(results[0],results[1])

    def test_existing_direct_payload_retains_one_worker(self):
        with patch.dict(os.environ,{'APEX_HUD_WORKERS':'2'}):
            observed=[]
            run_jobs({'backend':'cpu','fields':['hero'],'jobs':[]},direct=True,emit=lambda event:observed.append(os.environ['APEX_HUD_WORKERS']))
            self.assertEqual(set(observed),{'1'});self.assertEqual(os.environ['APEX_HUD_WORKERS'],'2')
            observed=[]
            run_jobs({'backend':'cpu','fields':['hero'],'jobs':[]},direct=False,emit=lambda event:observed.append(os.environ['APEX_HUD_WORKERS']))
            self.assertEqual(set(observed),{'2'});self.assertEqual(os.environ['APEX_HUD_WORKERS'],'2')

    def test_controller_defaults_follow_backend_and_available_cpu_budget(self):
        with patch.dict(os.environ,{},clear=False),patch('hud_enrichment.os.cpu_count',return_value=16):
            os.environ.pop('APEX_HUD_WORKERS',None)
            for backend,expected in [('dml','3'),('cpu','2')]:
                observed=[]
                run_jobs({'backend':backend,'fields':['hero'],'jobs':[]},direct=False,emit=lambda event:observed.append(os.environ['APEX_HUD_WORKERS']))
                self.assertEqual(set(observed),{expected});self.assertNotIn('APEX_HUD_WORKERS',os.environ)
            with patch('hud_enrichment.os.cpu_count',return_value=4):
                observed=[]
                run_jobs({'backend':'dml','fields':['hero'],'jobs':[]},direct=False,emit=lambda event:observed.append(os.environ['APEX_HUD_WORKERS']))
                self.assertEqual(set(observed),{'1'})

    def test_cpu_fallback_caps_a_gpu_three_worker_payload_to_two(self):
        observed=[]
        run_jobs({'backend':'cpu','cpu_workers':3,'fields':['hero'],'jobs':[]},direct=True,emit=lambda event:observed.append(os.environ['APEX_HUD_WORKERS']))
        self.assertEqual(set(observed),{'2'})

    def test_worker_failure_reaches_caller_and_releases_the_queue(self):
        seen=[]
        def read(index,activity):
            seen.append(index)
            if index==1:raise ValueError('fixture read failed')
            return index
        queue=ClipReadQueue(list(range(4)),read)
        with self.assertRaisesRegex(ValueError,'fixture read failed'):
            with queue:
                self.assertIsInstance(queue.futures[1].exception(timeout=2),ValueError)
                self.assertEqual(queue.result(0),0);queue.advance(0);queue.advance(1)
        self.assertEqual(set(seen),{0,1});self.assertEqual(queue.next_index,2)
        self.assertEqual(queue.futures,{});self.assertEqual(queue.activities,{})

    def test_distinct_workers_still_serialize_directml_device_calls(self):
        from gpu_ocr_backend import ExplicitOrtSession
        state={'active':0,'peak':0};lock=threading.Lock()
        def run(*args):
            with lock:state['active']+=1;state['peak']=max(state['peak'],state['active'])
            time.sleep(.005)
            with lock:state['active']-=1
            return ['unchanged']
        def worker(_):
            session=SimpleNamespace(backend='dml',_lock=threading.Lock(),session=SimpleNamespace(run=run),get_output_names=lambda:['out'],get_input_names=lambda:['in'])
            return ExplicitOrtSession.__call__(session,object())
        with patch.dict(os.environ,{'APEX_GPU_LOAD':'fast'}),ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(list(executor.map(worker,range(4))),[['unchanged']]*4)
        self.assertEqual(state['peak'],1)

    def test_batch_reuses_one_child_and_forwards_final_completion(self):
        jobs=[{'directory':str(index),'files':[str(index)+'.mp4']} for index in range(4)]
        done={'type':'hud-info-done','updated':4,'errors':[]};events=[]
        with patch('hud_enrichment._run_hud_child',return_value=done) as child:
            result=run_jobs({'backend':'cpu','fields':['hero'],'jobs':jobs},emit=events.append)
        self.assertEqual(child.call_count,1);self.assertEqual(child.call_args.args[0]['jobs'],jobs)
        self.assertEqual(result,done);self.assertEqual(events[-1],done)

    def test_independent_groups_overlap_with_one_bounded_read_pool_and_ordered_local_commits(self):
        from hud_batch import run_batch
        from queue_policy import QueuePolicy
        policy=SimpleNamespace(budget=SimpleNamespace(max_workers=2),resources=None,
            controller=SimpleNamespace(start=lambda now:None,target=2,actual_level=False,history=[]),
            capacity=lambda remaining:2,observe=lambda *args:None)
        state={'active':0,'peak':0};lock=threading.Lock();commits={};events=[];threads=set()
        def group(request,emit):
            key=request['jobs'][0]['directory'];commits[key]=[]
            def read(index,activity):
                with lock:
                    state['active']+=1;state['peak']=max(state['peak'],state['active']);threads.add(threading.current_thread().name)
                time.sleep(.01 if key!='0' else .04)
                with lock:state['active']-=1
                return index
            for offset,job in enumerate(request['jobs']):
                with ClipReadQueue(list(range(3)),read) as queue:
                    for index in range(3):
                        commits[key].append(queue.result(index));queue.advance(index)
                        emit({'type':'hud-info-progress','index':offset*3+index+1,'total':len(request['jobs'])*3,'file':key})
            return {'files_updated':[file for job in request['jobs'] for file in job['files']],'unconfirmed_files':[],'errors':[]}
        jobs=[{'directory':str(index),'files':[f'{index}-{j}' for j in range(3)]} for index in range(4)]
        jobs.append({'directory':'0','files':[f'0-extra-{j}' for j in range(3)]})
        with patch('queue_policy.QueuePolicy',return_value=policy):
            result=run_batch({'jobs':jobs,'fields':['hero']},events.append,group)
        self.assertEqual(state['peak'],2);self.assertLessEqual(len(threads),2)
        self.assertEqual(commits['0'],[0,1,2]*2);self.assertTrue(all(commits[str(index)]==[0,1,2] for index in range(1,4)));self.assertEqual(result['updated'],15)
        progress=[event['index'] for event in events if event['type']=='hud-info-progress']
        self.assertEqual(progress,sorted(progress));self.assertEqual(progress[-1],15)


if __name__=='__main__':unittest.main()
