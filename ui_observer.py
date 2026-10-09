"""可选 UI 观测通道：只观察已提交帧，不参与识别、断点或清理决策。"""
from pathlib import Path
import threading
import time

_lock=threading.RLock()
_callback=None
_source=None
_stage='idle'
_last_preview=0.

def configure(callback=None,source=None):
    global _callback,_source,_last_preview
    with _lock:
        _callback=callback; _source=str(source) if source else None; _last_preview=0.

def set_stage(name):
    global _stage
    with _lock: _stage=name

def phase(name,message,progress=None,cached=False):
    with _lock:
        set_stage(name)
        if _callback:
            event={'stage':name,'message':message,'source':_source,'cached':cached}
            if progress is not None: event['progress']=progress
            _callback('stage',**event)

def preview(path,timestamp,frame_kind='body',force=False):
    global _last_preview
    with _lock:
        if not _callback: return
        now=time.monotonic()
        if not force and now-_last_preview<1: return
        path=Path(path)
        if not path.is_file() or path.suffix.lower() not in ['.jpg','.jpeg','.png']: return
        _last_preview=now
        _callback('preview',source=_source,stage=_stage,sample_path=str(path.resolve()),
                  timestamp_seconds=float(timestamp),frame_kind=frame_kind)
