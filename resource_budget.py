"""Hardware-derived resource budgets and throughput feedback; no recognition rules."""
from dataclasses import dataclass,asdict,replace
import ctypes
from ctypes import wintypes
import math
import os
import shutil
import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def nvidia_only_adapter():
    if os.name!='nt':return False
    try:
        command="$v=@(Get-CimInstance Win32_VideoController | Where-Object PNPDeviceID -like 'PCI*'); if($v.Count -eq 1 -and $v[0].PNPDeviceID -like '*VEN_10DE*'){'single-nvidia'}"
        value=subprocess.check_output(['powershell.exe','-NoProfile','-Command',command],encoding='utf-8',timeout=3,creationflags=subprocess.CREATE_NO_WINDOW)
        return value.strip()=='single-nvidia'
    except (OSError,subprocess.SubprocessError):return False

MIB=1024**2
GIB=1024**3


@dataclass(frozen=True)
class Resources:
    logical:int
    physical:int|None=None
    ram_total:int|None=None
    ram_available:int|None=None
    gpu_total:int|None=None
    gpu_available:int|None=None
    gpu_status:str='not_queried'


def probe_resources(backend='cpu'):
    """No new dependencies, no model creation; unavailable metrics remain None."""
    result=Resources(max(1,os.cpu_count() or 1))
    if os.name=='nt':
        class Memory(ctypes.Structure):
            _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[(name,ctypes.c_ulonglong) for name in ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
        memory=Memory();memory.length=ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            result=replace(result,ram_total=memory.total,ram_available=memory.available)
        try:
            size=wintypes.DWORD();api=ctypes.windll.kernel32.GetLogicalProcessorInformationEx
            api(0,None,ctypes.byref(size))
            if size.value:
                buffer=ctypes.create_string_buffer(size.value)
                if api(0,buffer,ctypes.byref(size)):
                    offset=0;physical=0
                    while offset+8<=size.value:
                        relation,record_size=(wintypes.DWORD*2).from_buffer(buffer,offset)
                        if record_size<8:break
                        physical+=int(relation==0);offset+=record_size
                    if physical:result=replace(result,physical=physical)
        except (AttributeError,OSError,ValueError):pass
    else:
        try:result=replace(result,ram_total=os.sysconf('SC_PHYS_PAGES')*os.sysconf('SC_PAGE_SIZE'),ram_available=os.sysconf('SC_AVPHYS_PAGES')*os.sysconf('SC_PAGE_SIZE'))
        except (AttributeError,OSError,ValueError):pass
    if backend in {'dml','cuda'}:
        executable=shutil.which('nvidia-smi')
        if executable and (backend=='cuda' or nvidia_only_adapter()):
            try:
                output=subprocess.check_output([executable,'--query-gpu=memory.total,memory.free','--format=csv,noheader,nounits'],encoding='utf-8',timeout=2,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                total,available=[int(value.strip())*MIB for value in output.splitlines()[0].split(',')]
                result=replace(result,gpu_total=total,gpu_available=available,gpu_status='nvidia_smi')
            except (ValueError,OSError,subprocess.SubprocessError):result=replace(result,gpu_status='unavailable')
        else:result=replace(result,gpu_status='unavailable')
    else:result=replace(result,gpu_status='not_applicable')
    return result


@dataclass(frozen=True)
class Budget:
    max_workers:int
    initial_workers:int
    per_worker_bytes:int
    ram_reserve:int|None
    reasons:tuple[str,...]


def resource_budget(resources,backend='dml',preset='high',cache_mib=64,decode_threads=1,manual_limit=None):
    logical=max(1,resources.logical);physical=max(1,resources.physical or logical)
    # CPU ORT readers already have two intra-op threads. GPU preparation uses
    # independent CPU readers while model sessions are shared by the backend.
    gpu=backend in {'dml','cuda'}
    cpu_limit=max(1,min(physical,logical if gpu else logical//2))
    per_worker=(cache_mib+decode_threads*64+(256 if gpu else 448))*MIB
    reasons=[];reserve=None
    if resources.ram_total is not None and resources.ram_available is not None:
        # High mode uses more of the remaining RAM, while retaining both a
        # system reserve (at least 1 GiB) and headroom within the worker budget.
        reserve=max(GIB,math.ceil(resources.ram_total*(.05 if preset=='high' else .10)))
        usable=max(0,resources.ram_available-reserve-256*MIB)
        memory_limit=max(1,math.floor(usable*(.90 if preset=='high' else .80)/per_worker))
        if usable<per_worker:reasons.append('low_available_ram')
    else:
        memory_limit=1;reasons.append('ram_telemetry_unavailable')
    limit=min(cpu_limit,memory_limit)
    if manual_limit is not None:limit=min(limit,max(1,int(manual_limit)))
    if gpu:
        if resources.gpu_total is not None and resources.gpu_available is not None:
            usable_gpu=max(0,resources.gpu_available-max(256*MIB,math.ceil(resources.gpu_total*.10))-512*MIB)
            if usable_gpu<16*MIB:limit=1;reasons.append('low_available_vram')
        else:limit=1;reasons.append('vram_telemetry_unavailable')
    if preset=='low':initial=1
    elif preset=='balanced':initial=max(1,math.ceil(limit/3))
    elif preset=='custom':initial=limit
    else:initial=limit
    if 'ram_telemetry_unavailable' in reasons or 'vram_telemetry_unavailable' in reasons:initial=1
    return Budget(limit,min(initial,limit),per_worker,reserve,tuple(reasons))


class ThroughputController:
    """Bounded bidirectional probing, rollback, and natural tail drain.

    Feedback is actual completed work per wall second. No speculative OCR work
    is created, and already running reads are never forcibly stopped to resize.
    """
    def __init__(self,budget,adaptive=True):
        self.budget=budget;self.target=budget.initial_workers;self.adaptive=adaptive
        self.best_target=self.target;self.best_rate=None;self.window_start=None
        self.window_work=0.;self.window_done=0;self.trial=False;self.history=[]
        self.phase='reference';self.reference=None;self.probe=None;self.warmup=True;self.window_sizes=[]
        self.window_mix={};self.reference_mix=None;self.probe_mix=None
        self.direction=-1 if self.target==budget.max_workers else 1
        self.probe_target=None

    def allowed(self,remaining,available_ram=None):
        target=self.target
        if available_ram is not None and self.budget.ram_reserve is not None and available_ram<self.budget.ram_reserve+self.budget.per_worker_bytes:
            target=1
            if self.target!=1:
                self.history.append(dict(previous=self.target,target=1,reason='memory_pressure'))
                self.target=1;self.phase='reference';self.reference=None;self.probe=None;self.warmup=True
                self.window_done=0;self.window_work=0.;self.window_sizes=[];self.window_mix={};self.window_start=None
                self.direction=1;self.probe_target=None
        return max(0,min(target,self.budget.max_workers,remaining))

    def start(self,now):self.window_start=now

    def completed(self,now,work=1.,available_ram=None,profile=None):
        if work<=0:return self.target
        if self.window_start is None:self.start(now);return self.target
        if self.warmup:
            self.warmup=False;self.window_start=now;return self.target
        self.window_work+=max(0.,work);self.window_done+=1
        self.window_sizes.append(max(.001,work))
        for key,value in (profile or {}).items():self.window_mix[key]=self.window_mix.get(key,0)+value
        elapsed=now-self.window_start
        if not self.adaptive or elapsed<.5 or self.window_done<2:return self.target
        rate=self.window_work/elapsed;before=self.target
        total=sum(self.window_mix.values());mix={key:value/total for key,value in self.window_mix.items()} if total else {}
        def comparable(other):return other is None or all(abs(mix.get(key,0)-other.get(key,0))<=.15 for key in set(mix)|set(other))
        pressure=available_ram is not None and self.budget.ram_reserve is not None and available_ram<self.budget.ram_reserve+self.budget.per_worker_bytes
        if pressure:self.target=1;self.phase='reference';self.reference=None;self.direction=1;self.probe_target=None;reason='memory_pressure'
        elif self.phase!='reference' and (max(self.window_sizes)/min(self.window_sizes)>2 or not comparable(self.reference_mix) or self.phase=='control' and not comparable(self.probe_mix)):
            self.target=self.best_target;self.phase='reference';self.reference_mix=None;self.probe_mix=None;reason='incomparable_work_window'
        elif self.phase=='reference':
            self.reference=rate;self.reference_mix=mix;self.best_target=before
            if before>=self.budget.max_workers:self.direction=-1
            elif before<=1:self.direction=1
            self.target=max(1,min(self.budget.max_workers,before+self.direction)) if getattr(self,'can_probe',True) else before
            self.probe_target=self.target
            self.phase='probe' if self.target!=before else 'reference'
            reason='bounded_probe' if self.target>before else 'bounded_down_probe' if self.target<before else 'tail_drain'
        elif self.phase=='probe':
            self.probe=rate;self.probe_mix=mix;self.target=self.best_target
            if rate<self.reference*.85:self.phase='reference';self.direction*=-1;reason='throughput_regression_rollback'
            else:self.phase='control';reason='recheck_reference'
        else:
            drift=rate/self.reference if self.reference else 0
            if .85<=drift<=1.15 and self.probe>max(rate,self.reference)*1.08:
                self.target=self.probe_target;reason='confirmed_throughput_gain'
            else:self.target=self.best_target;self.direction*=-1;reason='drift_or_no_gain_rollback'
            self.phase='reference'
        self.history.append(dict(seconds=now,previous=before,target=self.target,rate=rate,reason=reason))
        self.history=self.history[-128:]
        self.window_start=now;self.window_done=0;self.window_work=0.;self.window_sizes=[];self.window_mix={}
        return self.target
