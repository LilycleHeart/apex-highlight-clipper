"""Bounded clip lookahead: read-only preparation, ordered metadata commits.

OCR state belongs to each worker; DirectML sessions retain the existing global
device lock. Worker callbacks only replace a bounded latest-activity slot and
are forwarded by the calling thread.
"""
from concurrent.futures import ThreadPoolExecutor,TimeoutError
import threading
import queue
import time
from dataclasses import asdict,is_dataclass
from contextlib import contextmanager

_REPORTS=[]
_SHARED=None


def queue_reports():return list(_REPORTS)


def _data(value):return asdict(value) if is_dataclass(value) else vars(value) if hasattr(value,'__dict__') else None

from engine_pool import init_worker_pool
from app_cancel import TaskStopped


class SharedReadPool:
    """One resource budget for all independent manifests in this process."""
    def __init__(self,policy,groups,remaining):
        self.policy=policy;self.remaining=remaining;self.active=0;self.peak_active=0
        self.condition=threading.Condition()
        self.workers=policy.budget.max_workers
        self.groups=groups;self.queues=set();self.coordinators=set()
        self.executor=ThreadPoolExecutor(max_workers=self.workers,thread_name_prefix='hud-read',initializer=init_worker_pool)
        policy.controller.start(time.monotonic())

    def register(self,queue):
        with self.condition:
            self.queues.add(queue);self.coordinators.add(threading.get_ident())

    def unregister(self,queue):
        with self.condition:self.queues.discard(queue)

    @property
    def prefetch(self):
        import math
        with self.condition:
            # Reserve the initial share for coordinators that have not entered
            # yet; finished groups then give their share to the remaining queues.
            groups=max(1,self.groups-len(self.coordinators)+len(self.queues))
            return max(2,math.ceil(self.workers/groups))

    def acquire(self):
        from app_cancel import check_cancel
        with self.condition:
            while self.active>=self.policy.capacity(max(1,self.remaining)):
                check_cancel();self.condition.wait(.1)
            check_cancel();self.active+=1;self.peak_active=max(self.peak_active,self.active)
            if self.active==self.policy.controller.target:self.policy.controller.actual_level=True

    def release(self,work,profile):
        with self.condition:
            self.active-=1;self.remaining=max(0,self.remaining-1)
            self.policy.controller.can_probe=self.remaining>self.policy.controller.target
            self.policy.observe(time.monotonic(),work,profile)
            self.condition.notify_all()

    def event(self):
        with self.condition:
            history=self.policy.controller.history
            event=history[-1] if history else {'target':self.policy.controller.target,'reason':'resource_budget'}
            return {**event,'budget':_data(self.policy.budget),'resources':_data(self.policy.resources),'active':self.active,'scope':'batch'}


@contextmanager
def shared_read_pool(policy,groups,remaining):
    global _SHARED
    if _SHARED is not None:raise RuntimeError('识别工作池不能嵌套')
    pool=SharedReadPool(policy,groups,remaining);_SHARED=pool
    try:yield pool
    finally:
        pool.executor.shutdown(wait=True,cancel_futures=True)
        _SHARED=None


class ClipReadQueue:
    def __init__(self,items,read,workers=2,policy=None):
        from queue_policy import create_policy
        self.shared=_SHARED
        self.policy=None if self.shared else policy or create_policy()
        self.items=items;self.read=read;self.workers=min(max(1,len(items)),self.policy.budget.max_workers if self.policy else max(1,int(workers)))
        if self.shared:self.workers=min(max(1,len(items)),self.shared.workers)
        self.executor=None;self.futures={};self.activities={};self.lock=threading.Lock();self.aborted=threading.Event()
        self.next_index=0;self.completions=queue.SimpleQueue();self.last_policy=None
        self.active=0;self.peak_active=0;self.peak_retained=0;self.cpu_seconds=0.

    def __enter__(self):
        self.executor=self.shared.executor if self.shared else ThreadPoolExecutor(max_workers=self.workers,thread_name_prefix='hud-read',initializer=init_worker_pool)
        self.started=time.monotonic()
        if self.shared:self.shared.register(self)
        if self.policy:self.policy.controller.start(time.monotonic())
        self._admit()
        return self

    def _submit(self,index):
        if index>=len(self.items):return
        def activity(details):
            if self.aborted.is_set():raise TaskStopped()
            with self.lock:
                self.activities[index]=details
                frames[0]=max(frames[0],details.get('frames_done',0))
        frames=[0]
        def read():
            from pipeline_metrics import begin,end
            if self.shared:self.shared.acquire()
            begin();started_cpu=time.thread_time();succeeded=False;result=None
            with self.lock:self.active+=1;self.peak_active=max(self.peak_active,self.active)
            try:result=self.read(self.items[index],activity);succeeded=True
            finally:
                profile=end()
                with self.lock:self.active-=1;self.cpu_seconds+=time.thread_time()-started_cpu
                if self.shared:
                    work=sum(profile.values()) if profile else frames[0]
                    if not succeeded or result is None or hasattr(result,'computed_fields') and not result.computed_fields:work=0
                    self.shared.release(work,profile)
            work=sum(profile.values()) if profile else frames[0]
            if result is None or hasattr(result,'computed_fields') and not result.computed_fields:work=0
            self.completions.put((time.monotonic(),work,profile))
            return result
        self.futures[index]=self.executor.submit(read)
        self.peak_retained=max(self.peak_retained,len(self.futures))

    def _admit(self):
        remaining=len(self.items)-self.next_index+len(self.futures)
        limit=min(self.workers,self.policy.capacity(remaining)) if self.policy else self.workers
        if self.shared:limit=min(limit,self.shared.prefetch)
        # Completed reads must not consume a running slot while an earlier
        # clip is still pending. Two extra retained results let short reads
        # refill idle slots without allowing unbounded read-ahead.
        if any(future.cancelled() or future.done() and future.exception() is not None for future in self.futures.values()):return
        pending=sum(not future.done() for future in self.futures.values())
        while self.next_index<len(self.items) and pending<limit and len(self.futures)<limit+2:
            self._submit(self.next_index);self.next_index+=1;pending+=1
        if self.policy and hasattr(self.policy.controller,'actual_level'):
            active=sum(not future.done() for future in self.futures.values())
            if active==self.policy.controller.target:self.policy.controller.actual_level=True

    def _feedback(self,on_activity=None):
        if self.shared and on_activity:
            event=self.shared.event();signature=(event.get('seconds'),event['target'],event['reason'])
            if signature!=self.last_policy:
                on_activity({'message':f"动态并行目标 {event['target']} 路 / 全批上限 {self.shared.workers} 路",'performance_policy':event})
                self.last_policy=signature
        if self.policy:
            unfinished=len(self.items)-self.next_index+sum(not future.done() for future in self.futures.values())
            self.policy.controller.can_probe=unfinished>self.policy.controller.target
        while not self.completions.empty():
            now,work,profile=self.completions.get()
            if self.policy:
                if hasattr(self.policy,'observe'):self.policy.observe(now,work,profile)
                else:self.policy.completed(now,work)
        if self.policy:
            event=self.policy.controller.history[-1] if self.policy.controller.history else {'target':self.policy.controller.target,'reason':'resource_budget'}
            signature=(event.get('seconds'),event['target'],event['reason'])
            if signature!=self.last_policy and on_activity:
                on_activity({'message':f"动态并行目标 {self.policy.controller.target} 路 / 本批上限 {self.workers} 路",'performance_policy':{**event,'budget':_data(self.policy.budget),'resources':_data(getattr(self.policy,'resources',None))}})
                self.last_policy=signature
        self._admit()

    def result(self,index,on_activity=None):
        def forward():
            with self.lock:details=self.activities.pop(index,None)
            if details is not None and on_activity:on_activity(details)
        future=self.futures[index]
        while True:
            self._feedback(on_activity)
            forward()
            try:result=future.result(timeout=.1);break
            except TimeoutError:
                if future.done():raise
        forward();return result

    def advance(self,index):
        # Also reap skipped reads before admitting another clip.
        if not self.futures[index].done():self.result(index)
        else:self.futures[index].result()
        self.futures.pop(index)
        with self.lock:self.activities.pop(index,None)
        self._feedback()

    def __exit__(self,*error):
        if error[0] is not None:self.aborted.set()
        for future in self.futures.values():future.cancel()
        if self.shared:
            from concurrent.futures import wait
            wait(list(self.futures.values()))
            self.shared.unregister(self)
        else:self.executor.shutdown(wait=True,cancel_futures=True)
        _REPORTS.append({'items':len(self.items),'capacity':self.workers,'peak_active':self.peak_active,'peak_retained':self.peak_retained,
            'thread_cpu_seconds':self.cpu_seconds,'seconds':time.monotonic()-self.started,
            'history':list(self.policy.controller.history) if self.policy else [],
            'budget':_data(self.policy.budget) if self.policy else None,'resources':_data(getattr(self.policy,'resources',None)) if self.policy else None})
        del _REPORTS[:-32]
        self.futures.clear();self.activities.clear()
