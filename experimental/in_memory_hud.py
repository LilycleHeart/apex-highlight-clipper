"""Bounded indexed-frame HUD experiment; never presents memory IDs as JPEGs.

The detector functions and numeric OCR are shared with production. This module
does not change detection rules, export clips, or claim sparse temporal coverage.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import threading
import time

import cv2
from image_io import read_image
import numpy as np

from apex_clipper import (BASE, crop, counter_offset, icon_signature, inactive_view,
                          downed_score, ammo_number, numeric)
from outcome_reader import friend_view
from ocr_cache import ExactTextCache
from .indexed_reader import IndexedKeyframeReader


@dataclass(frozen=True)
class MemoryFrame:
    pts: int
    time_base: Fraction
    keyframe_index: int
    burst_slot: int
    image: np.ndarray = field(repr=False, compare=False)

    @property
    def timestamp(self):
        return self.pts * self.time_base

    @property
    def frame_id(self):
        return f'memory:key-{self.keyframe_index}:slot-{self.burst_slot}:pts-{self.pts}'


@dataclass
class PreparedHUD:
    row: dict
    rois: dict


def iter_prepared_keyframes(source, features, *, start_index=0, stats=None,
                            cancel=None, preview=None, reader_factory=IndexedKeyframeReader, batch_frames=16):
    """Overlap independent decode/features with serial OCR and ordered commits.

    One native slice thread per decoder avoids nested pools. Measured useful
    throughput controls the number of independent decoders, not GPU percent.
    """
    from adaptive_scheduler import WorkBudget, ThroughputTuner, ordered_work
    stats = stats if stats is not None else {}
    with reader_factory(source, threads=1) as reader:
        count = len(reader.keyframes)
        width, height = reader.width, reader.height
        source_frames = reader.source_frames
        stats.update(keyframes=count, source_index_entries=source_frames,
                     width=width, height=height, decoder_threads_per_worker=1)
    if not 0 <= start_index <= count:
        raise ValueError('Invalid starting keyframe index')
    # Native surfaces/reorder buffers, BGR/ROI copies, per-reader container index.
    budget = WorkBudget.detect(width * height * 12 + source_frames * 256 + 1280 * round(height * 1280 / width) * 6)
    readers = []; idle = []; lock = threading.Lock(); created=0; peak=0
    tuner = ThroughputTuner(budget.workers,initial=math.isqrt(budget.workers))
    def prepare(index):
        nonlocal created,peak
        if cancel: cancel()
        with lock:
            reader = idle.pop() if idle else None
        if reader is None:
            reader = reader_factory(source, threads=1)
            with lock:
                readers.append(reader);created+=1;peak=max(peak,len(readers))
        try:
            started = time.perf_counter(); raw = reader.read_keyframe(index)
            if raw.pts is None or raw.time_base is None:
                raise ValueError('Authoritative decoder PTS/time_base are required')
            image = reader.body_image(raw)
            frame = MemoryFrame(int(raw.pts), Fraction(raw.time_base), index, 0, image)
            if cancel: cancel()
            decoded = time.perf_counter() - started; started = time.perf_counter()
            row, rois = features.prepare(frame)
            return frame, PreparedHUD(row, rois), decoded, time.perf_counter() - started
        finally:
            with lock:
                if len(readers) > tuner.value:
                    readers.remove(reader); reader.close()
                else: idle.append(reader)
    previous = None; stage_stats = {}
    stats.update(video_packets_submitted=0, decode_worker_seconds=0., feature_worker_seconds=0., yielded_frames=0)
    try:
        with ordered_work(range(start_index, count), prepare, budget=budget, tuner=tuner,cancel=cancel, stats=stage_stats,lookahead=batch_frames) as values:
            for frame, prepared, decoded, feature_seconds in values:
                if previous is not None and frame.timestamp <= previous:
                    raise ValueError('Overlapping/out-of-order keyframes')
                previous = frame.timestamp
                if preview: prepared.row['diagnostics'] = preview(frame.image, dict(prepared.row))
                stats['video_packets_submitted'] += 1; stats['decode_worker_seconds'] += decoded
                stats['feature_worker_seconds'] += feature_seconds; stats['yielded_frames'] += 1
                yield prepared
    finally:
        for reader in readers: reader.close()
        stats['reader_instances'] = created;stats['max_live_readers']=peak;stats['scheduler'] = stage_stats


def iter_indexed_images(source, *, mode='bursts', span=Fraction(1, 8), workers=4,
                        prefetch=8, stats=None, reader_factory=IndexedKeyframeReader,start_index=0):
    """Each worker owns one decoder; at most ``prefetch`` futures retain BGR.

    The caller must consume/release frames rather than retain this iterator's
    images. ``read_indexed_hud`` immediately replaces each image with small ROIs.
    """
    if mode not in ['keyframes', 'bursts']:
        raise ValueError('mode must be keyframes or bursts')
    if workers not in [1, 2, 4] or not workers <= prefetch <= 32:
        raise ValueError('Use 1/2/4 workers and a bounded prefetch in [workers,32]')
    span=Fraction(span)
    if mode=='bursts' and not 0 < span <= 1:
        raise ValueError('Burst span must be in (0,1] seconds')
    stats=stats if stats is not None else {}
    with reader_factory(source,threads=1) as reader:
        count=len(reader.keyframes)
        stats.update(keyframes=count, source_index_entries=reader.source_frames,
                     width=reader.width, height=reader.height)
    if not 0<=start_index<=count: raise ValueError('Invalid starting keyframe index')
    local=threading.local(); readers=[]; lock=threading.Lock()
    def read(index):
        if not hasattr(local,'reader'):
            local.reader=reader_factory(source,threads=1)
            with lock: readers.append(local.reader)
        started=time.perf_counter(); reader=local.reader
        if mode=='keyframes':
            frames=[reader.read_keyframe(index)]; packets=1
        else:
            first,last,packets=reader.read_burst(index,span); frames=[first,last]
        result=[]
        for slot,frame in enumerate(frames):
            if frame.pts is None or frame.time_base is None:
                raise ValueError('Authoritative decoder PTS/time_base are required')
            result.append(MemoryFrame(int(frame.pts),Fraction(frame.time_base),index,slot,reader.body_image(frame)))
        return result,packets,time.perf_counter()-started
    pool=ThreadPoolExecutor(max_workers=workers)
    pending=deque(); next_index=start_index; previous=None
    stats.update(max_pending_keyframes=0, video_packets_submitted=0, decode_worker_seconds=0.,
                 yielded_frames=0, decoder_threads_per_worker=1)
    try:
        while next_index<count or pending:
            while next_index<count and len(pending)<prefetch:
                pending.append(pool.submit(read,next_index)); next_index+=1
                stats['max_pending_keyframes']=max(stats['max_pending_keyframes'],len(pending))
            future=pending.popleft()
            frames,packets,elapsed=future.result()
            stats['video_packets_submitted']+=packets; stats['decode_worker_seconds']+=elapsed
            for frame in frames:
                if previous is not None and frame.timestamp<=previous:
                    raise ValueError('Overlapping/out-of-order bursts; no uniform timestamps are fabricated')
                previous=frame.timestamp; stats['yielded_frames']+=1
                yield frame
    finally:
        for future in pending: future.cancel()
        pool.shutdown(wait=True,cancel_futures=True)
        for reader in readers: reader.close()
        stats['reader_instances']=len(readers)


class HUDFeatures:
    """Use production ROI, marker, icon and view-state functions unchanged."""
    def __init__(self, profile, *, marker=None, downed_template=None, feature_hook=None):
        self.profile=profile
        self.marker=marker if marker is not None else read_image(str(BASE/profile['counter_marker']),cv2.IMREAD_GRAYSCALE)
        self.downed=downed_template if downed_template is not None else read_image(str(BASE/profile['downed_marker']),cv2.IMREAD_GRAYSCALE)
        if self.marker is None or self.downed is None:
            raise ValueError('Missing production HUD templates')
        self.feature_hook=feature_hook

    def prepare(self, frame):
        image=frame.image
        if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3:
            raise ValueError('Expected an 8-bit BGR image')
        profile=self.profile; delta,score=counter_offset(image,profile,self.marker)
        inactive=inactive_view(image); shield=downed_score(image,profile,self.downed)
        if shield>=profile['downed_marker_threshold']:inactive=False
        row={'frame':frame.frame_id,'frame_kind':'memory','time':float(frame.timestamp),
             'pts':frame.pts,'time_base':[frame.time_base.numerator,frame.time_base.denominator],
             'keyframe_index':frame.keyframe_index,'burst_slot':frame.burst_slot,
             'counter_offset':delta,'counter_marker_score':float(score),
             'weapon_icon':icon_signature(image,profile),'inactive_view':bool(inactive),
             'downed_score':float(shield),'downed':bool(shield>=profile['downed_marker_threshold']),
             'friend_spectate':bool(friend_view(image,inactive))}
        rois={}
        for key in ['ammo','damage','kills']:
            box=profile[key]
            if key in ['damage','kills']:
                if delta is None:
                    rois[key]=None; continue
                dx,dy=delta; box=[box[0]+dx,box[1]+dy,box[2]+dx,box[3]+dy]
            rois[key]=crop(image,box,profile['reference_size'])
        if self.feature_hook:
            extra=self.feature_hook(image,dict(row))
            # Reject accidental retention of full arrays by diagnostic callbacks.
            json.dumps(extra)
            row['diagnostics']=extra
        return row,rois


def numeric_recognizer(backend=None):
    """Reuse the production recognition adapter and batch/load policy."""
    from engine_pool import pooled_engine
    from gpu_ocr_backend import create_ocr_engine
    backend=backend or os.environ.get('APEX_OCR_BACKEND','cpu')
    engine=pooled_engine(('digits',backend,os.environ.get('APEX_GPU_LOAD','fast')),
        lambda:create_ocr_engine(backend=backend,rec_batch_num=24,adaptive_numeric=True))
    return ExactTextCache(engine.text_rec)


def read_memory_frames(frames, features, recognizer, *, batch_frames=16, stats=None,on_batch=None,cancel=None):
    if not 1<=batch_frames<=64: raise ValueError('Numeric batch must contain 1..64 frames')
    stats=stats if stats is not None else {}
    stats.update(feature_seconds=0.,numeric_seconds=0.,max_prepared_frames=0,max_roi_bytes=0)
    rows=[]; prepared=[]
    def flush():
        if not prepared: return
        images=[]; slots=[]
        for row,rois in prepared:
            positions={}
            for key,roi in rois.items():
                positions[key]=None if roi is None else len(images)
                if roi is not None: images.append(roi)
            slots.append(positions)
        stats['max_roi_bytes']=max(stats['max_roi_bytes'],sum(image.nbytes for image in images))
        started=time.perf_counter(); values,_=recognizer(images)
        stats['numeric_seconds']+=time.perf_counter()-started
        if len(values)!=len(images): raise ValueError('Numeric recognizer returned the wrong number of ROIs')
        first_new=len(rows)
        for (row,_),positions in zip(prepared,slots):
            for key,index in positions.items():
                text,confidence=('',0.) if index is None else values[index]
                row[key+'_text']=text; row[key+'_score']=float(confidence)
                row[key]=ammo_number(text,confidence) if key=='ammo' else numeric(text,confidence,{'damage':20000,'kills':60}[key],.88)
            rows.append(row)
        prepared.clear()
        if on_batch: on_batch(rows[first_new:])
    try:
        for frame in frames:
            if cancel: cancel()
            started=time.perf_counter()
            prepared.append((frame.row,frame.rois) if isinstance(frame,PreparedHUD) else features.prepare(frame))
            stats['feature_seconds']+=time.perf_counter()-started
            stats['max_prepared_frames']=max(stats['max_prepared_frames'],len(prepared))
            if len(prepared)>=batch_frames: flush()
        flush()
    finally:
        if hasattr(frames,'close'): frames.close()
    return rows


def read_indexed_hud(source, profile, *, mode='bursts', span=Fraction(1,8), workers=4,
                     prefetch=8, batch_frames=16, backend=None, feature_hook=None):
    source=Path(source); before=source.stat(); stats={}; started=time.perf_counter()
    features=HUDFeatures(profile,feature_hook=feature_hook)
    recognizer=numeric_recognizer(backend)
    stats['setup_seconds']=time.perf_counter()-started
    frames=iter_indexed_images(source,mode=mode,span=span,workers=workers,prefetch=prefetch,stats=stats)
    rows=read_memory_frames(frames,features,recognizer,batch_frames=batch_frames,stats=stats)
    after=source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('Source changed during the experiment')
    stats.update(total_seconds=time.perf_counter()-started,ocr=recognizer.stats(),source_unchanged=True,
                 bgr_queue_frame_bound=(prefetch+1)*(2 if mode=='bursts' else 1))
    return {'experimental':True,'production_compatible':False,'frame_storage':'memory_only',
            'timestamp_basis':'decoded_pts','uniform_fps':None,'sampling':{'mode':mode,'span':str(Fraction(span))},
            'profile':profile,'rows':rows,'stats':stats,
            'scope':'Indexed read + in-memory HUD only; no full temporal coverage, result qualification or export'}
