"""Bounded, ordered work scheduling. Tune useful throughput, never GPU percent.

No dependency on an NVIDIA device or psutil. Unknown telemetry is reported as
unknown. CPU affinity/container limits and available RAM bound speculation.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from dataclasses import dataclass
import math
import os
from pathlib import Path
import subprocess
import threading
import time


def cpu_slots():
    counts = [getattr(os, 'process_cpu_count', os.cpu_count)() or 1]
    if hasattr(os, 'sched_getaffinity'):
        try:counts.append(len(os.sched_getaffinity(0)))
        except OSError:pass
    try:
        quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if quota != 'max':
            counts.append(max(1, math.ceil(int(quota) / int(period))))
    except (OSError, ValueError):
        pass
    return max(1, min(counts))


def available_memory():
    """Available physical/container RAM in bytes; None if unavailable."""
    if os.name == 'nt':
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in
                ('total', 'available', 'page_total', 'page_available', 'virtual_total', 'virtual_available', 'extended')]
        status = MemoryStatus(); status.length = ctypes.sizeof(status)
        return int(status.available) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None
    try:
        fields = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
        available = int(fields['MemAvailable'].split()[0]) * 1024
        try:
            limit = Path('/sys/fs/cgroup/memory.max').read_text().strip()
            if limit != 'max':
                used = int(Path('/sys/fs/cgroup/memory.current').read_text())
                available = min(available, max(0, int(limit) - used))
        except (OSError, ValueError):
            pass
        return available
    except (OSError, ValueError, KeyError):
        return None


def _system_cpu_times():
    """(total, idle) seconds. Used only to notice competing CPU pressure."""
    if os.name == 'nt':
        import ctypes
        idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
        if ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return (kernel.value + user.value) / 1e7, idle.value / 1e7
    else:
        try:
            values = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
            hz = os.sysconf('SC_CLK_TCK')
            return sum(values) / hz, (values[3] + values[4]) / hz
        except (OSError, ValueError, IndexError):
            pass
    return None


class ResourceProbe:
    """Cache RAM queries; optionally use coarse NVIDIA memory pressure.

    DML adapter ordering need not match CUDA/NVML. Use the most constrained
    reported NVIDIA adapter conservatively, and do not infer GPU utilization.
    Missing/failed nvidia-smi never prevents recognition on CPU/DML/AMD/Intel.
    """
    def __init__(self, gpu=False, clock=time.monotonic):
        self.clock = clock; self.gpu = gpu; self.checked = -math.inf
        self.gpu_checked = -math.inf; self.gpu_free = None; self.gpu_pressure = False
        self.current = {}; self.initial_memory = available_memory()
        self.cpu_before = _system_cpu_times(); self.process_before = time.process_time()

    def snapshot(self):
        now = self.clock()
        if now - self.checked < 1:
            return self.current
        self.checked = now; memory = available_memory()
        if self.gpu and now - self.gpu_checked >= 5:
            self.gpu_checked = now
            try:
                output = subprocess.check_output(
                    ['nvidia-smi', '--query-gpu=memory.free,memory.total', '--format=csv,noheader,nounits'],
                    timeout=.5, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, text=True)
                pairs = [tuple(float(x.strip()) * 1024**2 for x in row.split(','))
                         for row in output.splitlines() if row.strip()]
                self.gpu_free = min(free for free, total in pairs)
                self.gpu_pressure = any(free < total * .1 for free, total in pairs)
            except (OSError, ValueError, subprocess.SubprocessError):
                self.gpu_free = None; self.gpu_pressure = False
        cpu = _system_cpu_times(); process = time.process_time(); external = None
        if cpu is not None and self.cpu_before is not None:
            total = cpu[0] - self.cpu_before[0]
            if total > 0:
                external = max(0., (total - (cpu[1] - self.cpu_before[1]) - (process - self.process_before)) / total)
        self.cpu_before = cpu; self.process_before = process
        pressure = memory is not None and self.initial_memory is not None and memory < self.initial_memory * .15
        self.current = {'available_memory': memory, 'gpu_free_memory': self.gpu_free,
                        'external_cpu_fraction': external,
                        'pressure': pressure or self.gpu_pressure or (external is not None and external > .85),
                        'gpu_memory_source': 'nvidia-smi (all adapters)' if self.gpu_free is not None else None}
        return self.current


class ThroughputTuner:
    """One-variable hill climb with measured trials, rollback and retry delay.

    Each epoch includes consumer time (OCR and durable commits), so filling a
    queue without improving completed throughput cannot justify more workers.
    Pressure immediately halves speculation. Short/tail windows do not tune.
    """
    def __init__(self, maximum, *, initial=1, window=.75):
        self.maximum = max(1, int(maximum)); self.value = min(self.maximum, max(1, initial))
        self.window = window; self.items = 0; self.seconds = 0.; self.samples = 0
        self.wait_seconds = 0.; self.wait_tracked = False
        self.reference = None; self.trial = None; self.cooldown = 0
        self.history = deque(maxlen=64)

    def observe(self, items, seconds, *, pressure=False, ceiling=None, wait_seconds=None):
        limit = max(1, min(self.maximum, self.maximum if ceiling is None else int(ceiling)))
        if pressure or self.value > limit:
            self.value = max(1, min(limit, self.value // 2 if pressure else self.value))
            self.reference = self.trial = None; self.cooldown = 3
            self.items = self.samples = 0; self.seconds = 0.
            self.wait_seconds = 0.; self.wait_tracked = False
            self.history.append({'value': self.value, 'reason': 'pressure' if pressure else 'memory_bound'})
            return self.value
        if items <= 0:
            return self.value
        self.items += items; self.seconds += max(0., seconds); self.samples += 1
        if wait_seconds is not None:
            self.wait_seconds += max(0.,wait_seconds); self.wait_tracked = True
        if self.seconds < self.window or self.samples < 2:
            return self.value
        rate = self.items / max(self.seconds, 1e-9)
        wait_fraction = self.wait_seconds / max(self.seconds, 1e-9) if self.wait_tracked else None
        self.items = self.samples = 0; self.seconds = 0.
        self.wait_seconds = 0.; self.wait_tracked = False
        self.history.append({'value': self.value, 'items_per_second': rate, 'wait_fraction':wait_fraction,'reason': 'measured'})
        if self.trial is not None:
            old_value, old_rate = self.trial
            # A smaller pool is useful even at equal throughput; extra workers
            # must earn their memory/CPU with a measurable improvement.
            if rate < old_rate * (.97 if self.value < old_value else 1.03):
                self.value = min(limit, old_value); self.reference = old_rate; self.cooldown = 3
            else:
                self.reference = rate
                if self.value < old_value:self.cooldown = 3
            self.trial = None
        elif self.reference is not None and rate < self.reference * .85 and self.value > 1:
            self.trial = (self.value, rate); self.value = max(1, self.value // 2)
            return self.value
        else:
            self.reference = rate
        if self.cooldown:
            self.cooldown -= 1
        elif wait_fraction is not None and wait_fraction < .1:
            if self.value > 1:
                self.trial = (self.value, rate); self.value = max(1,self.value//2)
            else:self.cooldown = 3
        elif self.value < limit:
            self.trial = (self.value, rate)
            self.value = min(limit, self.value + max(1, self.value // 2))
        return self.value


@dataclass(frozen=True)
class WorkBudget:
    slots: int
    memory_bytes: int
    item_bytes: int

    @classmethod
    def detect(cls, item_bytes):
        # Spend at most one quarter of currently available RAM on this stage.
        # Unknown RAM permits one worker, not unlimited buffering.
        memory = available_memory()
        item_bytes = max(1, int(item_bytes))
        return cls(cpu_slots(), max(item_bytes * 2, memory // 4) if memory is not None else item_bytes * 2, item_bytes)

    @property
    def workers(self):
        return max(1, min(self.slots, self.capacity))

    @property
    def capacity(self):
        return max(1,self.memory_bytes // self.item_bytes - 1)


@contextmanager
def ordered_work(items, work, *, budget, tuner=None, probe=None, cancel=None, stats=None, lookahead=1):
    """Single ordered consumer, bounded lazy worker pool, interruptible waits.

    Worker callbacks must not write journals, UI previews or shared OCR caches.
    A failed future aborts the stream; no later result can be committed first.
    Native calls already running finish before their resources are closed.
    """
    stats = stats if stats is not None else {}
    tuner = tuner or ThroughputTuner(budget.workers,initial=math.isqrt(budget.workers))
    probe = probe or ResourceProbe()
    stats.update(cpu_slots=budget.slots, worker_limit=budget.workers,
                 memory_budget_bytes=budget.memory_bytes, estimated_item_bytes=budget.item_bytes,
                 max_pending=0, consumer_wait_seconds=0., completed=0)
    if lookahead < 1:raise ValueError('lookahead must be positive')
    pool = ThreadPoolExecutor(max_workers=budget.workers, thread_name_prefix='ahc-prepare')
    pending = deque(); source = iter(items); exhausted = False; abort = threading.Event()
    gate = threading.Condition(); active = 0
    def run(item):
        nonlocal active
        with gate:
            while active >= min(budget.workers,tuner.value) and not abort.is_set():gate.wait(.05)
            if abort.is_set():return None
            active += 1
        try:
            return work(item)
        finally:
            with gate:active -= 1;gate.notify_all()
    def stream():
        nonlocal exhausted
        previous = time.perf_counter()
        def fill():
            nonlocal exhausted
            snapshot = probe.snapshot()
            memory = snapshot['available_memory']
            capacity = budget.capacity if memory is None else max(1, min(budget.capacity, memory // (4 * budget.item_bytes) - 1))
            tuner.observe(0, 0, pressure=snapshot['pressure'], ceiling=min(budget.workers,capacity))
            # Enough lookahead for the consumer's atomic batch even when only
            # one producer is profitable. Futures cannot bypass the active gate.
            depth = min(capacity,max(tuner.value,lookahead))
            with gate:gate.notify_all()
            while not exhausted and len(pending) < depth:
                if cancel: cancel()
                try: item = next(source)
                except StopIteration:
                    exhausted = True; break
                pending.append(pool.submit(run, item))
                stats['max_pending'] = max(stats['max_pending'], len(pending))
        fill()
        while pending:
            if cancel: cancel()
            future = pending.popleft(); started = time.perf_counter()
            while True:
                try:
                    value = future.result(timeout=.05); break
                except TimeoutError:
                    if future.done(): raise  # callback's own TimeoutError
                    if cancel: cancel()
            waited = time.perf_counter() - started
            stats['consumer_wait_seconds'] += waited
            now = time.perf_counter()
            tuner.observe(1, now - previous,wait_seconds=waited); previous = now
            stats['completed'] += 1
            fill()  # replacement overlaps consumer OCR/commit, even with one worker
            yield value
    iterator = stream()
    try:
        yield iterator
    finally:
        abort.set()
        with gate:gate.notify_all()
        iterator.close()
        for future in pending: future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        if hasattr(source, 'close'): source.close()
        stats['final_workers'] = tuner.value; stats['tuning'] = list(tuner.history)


def ort_threads():
    from gpu_load import get_gpu_policy
    return max(1, math.isqrt(cpu_slots())) if get_gpu_policy()['name'] == 'fast' else 2
