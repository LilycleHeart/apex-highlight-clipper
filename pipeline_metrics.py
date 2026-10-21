"""Read-local work counters; no timings, labels, thresholds, or output changes."""
from collections import Counter
from pathlib import Path
import threading

_local=threading.local()


def begin():_local.work=Counter()


def record(model,tensor):
    work=getattr(_local,'work',None)
    if work is not None and getattr(tensor,'ndim',0)==4:
        work[Path(model).name]+=int(tensor.shape[0])*int(tensor.shape[2])*int(tensor.shape[3])


def end():
    work=dict(getattr(_local,'work',{}));_local.work=None;return work
