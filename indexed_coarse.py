"""Indexed experimental coarse locator with bounded memory and resumable HUD blocks.

Only local dense JPEG samples may enter the final detection/export pipeline.
The few JPEGs produced here are explicitly preview-only, never sample aliases.
"""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import time
import uuid

import cv2
from image_io import write_image

from apex_clipper import BASE,fingerprint,write_json
from app_cancel import check_cancel
from gpu_load import get_gpu_policy
from resume_io import RowJournal
from experimental.indexed_reader import IndexedKeyframeReader,UnsupportedIndexedVideo
from experimental.in_memory_hud import HUDFeatures,numeric_recognizer,iter_indexed_images,read_memory_frames


def _runtime_version():
    try:
        import av
    except ImportError as error:
        raise RuntimeError('索引识别需要 PyAV；请安装 requirements-experimental.txt') from error
    return av.__version__


def indexed_coarse_scan(source,job,profile,fps):
    check_cancel(); source=Path(source); identity=fingerprint(source)
    version=_runtime_version()
    try:
        with IndexedKeyframeReader(source,threads=1) as reader:
            # Nonzero container origins are normalized instead of rejected:
            # sampling, HUD rows and export all use time from the first frame.
            origin=reader.time_origin
            entries=[(e.dts,e.position,e.size) for e in reader.keyframes]
            total=len(entries)
    except (UnsupportedIndexedVideo,IndexError) as error:
        raise RuntimeError('无法读取此录像的可靠视频索引；当前需要 H.264、HEVC 或 AV1 的 MP4/MOV 录像：'+str(error)) from error
    import rapidocr_onnxruntime
    model=Path(rapidocr_onnxruntime.__file__).parent/'models/ch_PP-OCRv4_rec_infer.onnx'
    from stat_counter_fallback import KILLS_FALLBACK
    config={'version':'indexed-coarse-v1','source':identity,'profile':profile,'fps':fps,'pyav':version,'kills_fallback':KILLS_FALLBACK,
            'index':entries,'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
            'templates':{key:hashlib.sha256((BASE/profile[key]).read_bytes()).hexdigest() for key in ['counter_marker','downed_marker']}}
    signature=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    folder=Path(job)/'indexed-coarse'; folder.mkdir(parents=True,exist_ok=True)
    complete=folder/'hud.json'
    def valid(row,index):
        try:
            return (index<total and row['keyframe_index']==index and row['frame_kind']=='memory' and
                row['frame'].startswith('memory:') and row['time']==float(Fraction(row['pts'])*Fraction(*row['time_base'])-origin) and
                all(key in row for key in ['ammo','damage','kills','weapon_icon','inactive_view','downed','friend_spectate']))
        except (KeyError,TypeError,ValueError,ZeroDivisionError): return False
    journal=RowJournal(folder/'rows.jsonl',signature,valid)
    workers=2 if get_gpu_policy()['name'] in ['low','balanced'] else 4
    stats={'restored_frames':len(journal.rows),'workers':workers}; preview_time=-1.
    if len(journal.rows)<total:
        def show(image,row):
            nonlocal preview_time
            now=time.monotonic()
            if now-preview_time>=1:
                # Unique URLs prevent stale browser image caching; retain only 8.
                previews=folder/'previews'; previews.mkdir(exist_ok=True)
                path=previews/f'frame-pts-{row["pts"]}-{uuid.uuid4().hex[:8]}.jpg'; temp=previews/'writing.jpg'
                if not write_image(str(temp),image,[cv2.IMWRITE_JPEG_QUALITY,82]): raise ValueError('无法保存索引预览画面')
                temp.replace(path); preview_time=now
                from ui_observer import preview
                preview(path,row['time'])
                for old in sorted(previews.glob('frame-pts-*.jpg'),key=lambda p:p.stat().st_mtime_ns)[:-8]:
                    old.resolve().relative_to(previews.resolve()); old.unlink()
            return {}
        features=HUDFeatures(profile,feature_hook=show); recognizer=numeric_recognizer()
        def committed(rows):
            journal.append(rows)
            print(f'SMART_PROGRESS: {5+15*len(journal.rows)/max(1,total):.1f}',flush=True)
            print(f'索引粗查：{len(journal.rows)}/{total} 帧，已保存断点',flush=True)
            check_cancel()
        frames=iter_indexed_images(source,mode='keyframes',workers=workers,prefetch=workers*2,
                                   start_index=len(journal.rows),stats=stats)
        read_memory_frames(frames,features,recognizer,batch_frames=16,stats=stats,on_batch=committed,cancel=check_cancel)
        stats['ocr']=recognizer.stats()
    else:
        print(f'索引粗查续接：复用全部 {total} 帧',flush=True)
    check_cancel()
    if fingerprint(source)!=identity: raise ValueError('索引粗查时原录像发生变化')
    cache={'signature':signature,'source':identity,'profile':profile,'fps':fps,'complete':True,
           'rows':journal.rows,'outcome_events':[],'coarse_strategy':'indexed-keyframes-v1',
           'numeric_frames':len(journal.rows),'frame_storage':'memory_only','timestamp_basis':'decoded_pts',
           'refinement_numeric_frames':0,'stats_this_run':stats}
    write_json(complete,cache)
    return cache
