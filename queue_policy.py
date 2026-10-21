"""Admission only: no recognition thresholds or speculative reads."""
import ctypes
from ctypes import wintypes
import os
import time
import threading
from concurrent.futures import Future
from resource_budget import probe_resources,resource_budget,ThroughputController


def available_ram():
    if os.name!='nt':return None
    class Memory(ctypes.Structure):
        _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[(key,ctypes.c_ulonglong) for key in ('total','available','p1','p2','v1','v2','unused')]
    value=Memory();value.length=ctypes.sizeof(value)
    return value.available if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)) else None


class QueuePolicy:
    def __init__(self):
        backend=os.environ.get('APEX_OCR_BACKEND','cpu');preset=os.environ.get('APEX_SCHEDULE_PRESET','high')
        self.backend=backend
        self.resources=probe_resources(backend)
        self.budget=resource_budget(self.resources,backend,preset,int(os.environ.get('APEX_FRAME_CACHE_MB','64')),
            int(os.environ.get('APEX_DECODE_THREADS','1')),int(os.environ['APEX_HUD_WORKERS']) if preset=='custom' else None)
        self.controller=ThroughputController(self.budget,adaptive=preset=='high')
        self.controller.actual_level=False
        self.last_gpu_check=time.monotonic();self.gpu_low=False
        self._gpu_probe=None

    def _refresh_gpu(self):
        """Never wait for nvidia-smi while the shared admission lock is held."""
        if self.resources.gpu_total is None:return
        now=time.monotonic()
        if self._gpu_probe is not None:
            if self._gpu_probe.done():
                self.gpu_low=self._gpu_probe.result();self._gpu_probe=None
            elif now-self.last_gpu_check>=3:
                # A stalled probe cannot authorize more work on stale telemetry.
                self.gpu_low=True
        if self._gpu_probe is not None or now-self.last_gpu_check<3:return
        pending=Future();self._gpu_probe=pending;self.last_gpu_check=now
        def probe():
            try:
                fresh=probe_resources(self.backend)
                low=fresh.gpu_available is None or fresh.gpu_available<max(256*1024**2,self.resources.gpu_total*.10)
            except Exception:
                low=True
            pending.set_result(low)
        try:threading.Thread(target=probe,name='hud-gpu-telemetry',daemon=True).start()
        except RuntimeError:pending.set_result(True)

    def capacity(self,remaining):
        self._refresh_gpu()
        available=available_ram()
        if self.gpu_low or available is None:
            before=self.controller.target
            self.controller.allowed(remaining,0)
            if before!=self.controller.target:self.controller.history[-1]['reason']='vram_pressure_or_unknown' if self.gpu_low else 'ram_telemetry_unavailable'
            return min(1,remaining)
        return self.controller.allowed(remaining,available)

    def completed(self,now,work):self.controller.completed(now,work,available_ram())

    def observe(self,now,work,profile):
        if not self.controller.actual_level:return
        before=self.controller.target
        self.controller.completed(now,work,available_ram(),profile)
        if before!=self.controller.target:self.controller.actual_level=False


def create_policy():return QueuePolicy() if os.environ.get('APEX_ADAPTIVE_HUD')=='1' else None
