"""Adaptive numeric microbatches around the unchanged RapidOCR/CTC adapter.

Only numeric crops with the canonical 3x48x320 normalization may be regrouped.
Wide text uses the original grouping; names/outcome detection do not opt in.
"""
import threading
import time

from adaptive_scheduler import ResourceProbe, ThroughputTuner, available_memory
from app_cancel import check_cancel


def is_memory_error(error):
    message = str(error).lower()
    return any(token in message for token in
               ('out of memory', 'e_outofmemory', 'failed to allocate memory',
                'bad allocation', '0x8007000e', 'cuda_error_out_of_memory'))


class AdaptiveNumericRecognizer:
    def __init__(self, recognizer, *, backend, probe=None, tuner=None):
        self.recognizer = recognizer; self.backend = backend
        self.legacy_batch = recognizer.rec_batch_num
        self.probe = probe or ResourceProbe(gpu=backend != 'cpu')
        # Activation workspace is provider/model dependent. This conservative
        # input multiplier is only a memory ceiling; measured trials choose use.
        self.item_bytes = 3 * 48 * 320 * 4 * 64
        memory = available_memory()
        maximum = max(1, memory // (4 * self.item_bytes)) if memory is not None else self.legacy_batch
        # Existing batch is a warm-start hint, not a ceiling or device profile.
        self.tuner = tuner or ThroughputTuner(maximum, initial=min(maximum, self.legacy_batch))
        self.lock = threading.RLock(); self.oom_retries = 0; self.compatibility_calls = 0
        self.calls = 0; self.max_batch = 0

    def __getattr__(self, key):
        return getattr(self.recognizer, key)

    def __call__(self, images, *args, **kwargs):
        if not images:
            return [], 0.
        with self.lock:
            check_cancel()
            # Grouping wide crops can change normalization width, not just the
            # batch dimension. Keep the original request and grouping intact.
            if args or kwargs or any(image.shape[1] / image.shape[0] > 320 / 48 for image in images):
                self.compatibility_calls += 1
                return self._run(images, self.legacy_batch, *args, **kwargs)
            snapshot = self.probe.snapshot()
            limits = [self.tuner.maximum]
            for key in ('available_memory', 'gpu_free_memory'):
                if snapshot[key] is not None:
                    limits.append(max(1, snapshot[key] // (4 * self.item_bytes)))
            limit = min(limits)
            self.tuner.observe(0, 0, pressure=snapshot['pressure'], ceiling=limit)
            started = time.perf_counter()
            while True:
                batch = min(len(images), self.tuner.value)
                try:
                    values, elapsed = self._run(images, batch)
                    break
                except Exception as error:
                    if not is_memory_error(error) or batch == 1:
                        raise
                    self.oom_retries += 1
                    # Remember the failed shape so subsequent requests do not
                    # repeatedly allocate it. Never commit partial predictions.
                    self.tuner.maximum = min(self.tuner.maximum, batch - 1)
                    self.tuner.observe(0, 0, pressure=True)
                    check_cancel()
            self.calls += 1; self.max_batch = max(self.max_batch, batch)
            # Use canonical grouping at decision boundaries where tiny floating
            # differences could change downstream classification/cache reuse.
            grouping_changed = min(batch,len(images)) != min(self.legacy_batch,len(images))
            if grouping_changed and any(abs(float(score) - threshold) <= .002 for text, score in values
                   for threshold in (.67, .75, .80, .86, .88, .90, .95)):
                self.compatibility_calls += 1
                values, elapsed = self._run(images, self.legacy_batch)
                # A useful trial must pay for compatibility work too. Return
                # to canonical grouping rather than repeatedly doubling work
                # on a stream with many borderline predictions.
                self.tuner.value=min(self.legacy_batch,self.tuner.maximum)
                self.tuner.trial=self.tuner.reference=None;self.tuner.cooldown=3
            # Tail/cache-hit requests smaller than the trial do not compare
            # different amounts of work and falsely reject a profitable batch.
            if (not grouping_changed or self.tuner.value==batch) and len(images) >= self.tuner.value:
                self.tuner.observe(len(images), time.perf_counter() - started, ceiling=min(limit, len(images)))
            return values, elapsed

    def _run(self, images, batch, *args, **kwargs):
        before = self.recognizer.rec_batch_num
        self.recognizer.rec_batch_num = max(1, int(batch))
        try:
            return self.recognizer(images, *args, **kwargs)
        finally:
            self.recognizer.rec_batch_num = before

    def scheduler_stats(self):
        return {'calls': self.calls, 'max_batch': self.max_batch, 'current_batch': self.tuner.value,
                'batch_limit': self.tuner.maximum, 'oom_retries': self.oom_retries,
                'compatibility_calls': self.compatibility_calls, 'tuning': list(self.tuner.history),
                'resources': self.probe.snapshot()}
