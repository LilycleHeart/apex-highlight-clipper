"""工作进程内最多保留两个 OCR 引擎；批次结束后随进程释放。"""
from collections import OrderedDict
import os
import threading

_POOL=OrderedDict(); _LOCK=threading.RLock()

def pooled_engine(key,factory):
    if os.environ.get('APEX_OCR_POOL')!='1': return factory()
    with _LOCK:
        if key not in _POOL: _POOL[key]=factory()
        _POOL.move_to_end(key)
        while len(_POOL)>2: _POOL.popitem(last=False)
        return _POOL[key]

def clear_pool():
    with _LOCK: _POOL.clear()
