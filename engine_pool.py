"""工作进程内最多保留两个 OCR 引擎；批次结束后随进程释放。"""
from collections import OrderedDict
from contextlib import nullcontext
import os
import threading

_POOL=OrderedDict(); _LOCK=threading.RLock()
_WORKER=threading.local()


def init_worker_pool():
    """Mutable readers are private to one bounded HUD preparation worker."""
    _WORKER.pool=OrderedDict()

def pooled_engine(key,factory):
    if os.environ.get('APEX_OCR_POOL')=='0':return factory()
    worker=getattr(_WORKER,'pool',None)
    if worker is None and os.environ.get('APEX_OCR_POOL')!='1': return factory()
    pool=_POOL if worker is None else worker
    with _LOCK if worker is None else nullcontext():
        if key not in pool: pool[key]=factory()
        pool.move_to_end(key)
        while len(pool)>2: pool.popitem(last=False)
        return pool[key]

def clear_pool():
    with _LOCK:
        pool=getattr(_WORKER,'pool',_POOL);pool.clear()
