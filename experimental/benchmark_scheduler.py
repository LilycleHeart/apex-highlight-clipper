"""Fresh-process ABBA benchmark of the actual indexed HUD stages.

Examples (all outputs are disposable, under validation/):
  python -m experimental.benchmark_scheduler --baseline-root ../ahc-before --kind simulated --report validation/scheduler-sim.json
  python -m experimental.benchmark_scheduler --baseline-root ../ahc-before --kind generated --limit 96 --report validation/scheduler-cpu.json
  python -m experimental.benchmark_scheduler --baseline-root ../ahc-before --source VIDEO --backend dml --limit 64 --report validation/scheduler-gpu.json

The baseline root must be an unchanged checkout of the revision being compared.
Simulated service times test scheduling only; they are NEVER hardware evidence.
"""
import argparse
from fractions import Fraction
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace


def _limited(frames, count):
    try:
        yield from itertools.islice(frames, count)
    finally:
        frames.close()


def _generate_fixture(path, profile_path, count):
    """Generated H.264 + real OCR workload; not a recognition accuracy fixture."""
    import av
    import cv2
    import numpy as np
    profile=json.loads(profile_path.read_text(encoding='utf-8'))
    width,height=profile['reference_size']
    marker=cv2.imread(str(Path(__file__).resolve().parents[1]/profile['counter_marker']))
    marker=cv2.resize(marker,None,fx=2,fy=2,interpolation=cv2.INTER_NEAREST)
    with av.open(str(path),'w') as output:
        stream=output.add_stream('libx264',rate=10)
        stream.width=width;stream.height=height;stream.pix_fmt='yuv420p'
        stream.options={'preset':'ultrafast','crf':'18','g':'1','threads':'1'}
        for index in range(count):
            image=np.full((height,width,3),45,np.uint8)
            x,y=profile['counter_marker_origin'];image[y:y+marker.shape[0],x:x+marker.shape[1]]=marker
            for key,text in [('ammo',str(40-index%35)),('damage',str(index*13)),('kills',str(index//20))]:
                x1,y1,x2,y2=profile[key]
                cv2.putText(image,text,(x1,y2-3),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),1,cv2.LINE_AA)
            for packet in stream.encode(av.VideoFrame.from_ndarray(image,format='bgr24')):output.mux(packet)
        for packet in stream.encode():output.mux(packet)


def _worker(args):
    sys.path.insert(0, str(args.root))
    os.environ.update(APEX_GPU_LOAD='fast', APEX_OCR_BACKEND=args.backend, APEX_OCR_POOL='0')
    import numpy as np
    import av
    import onnxruntime
    from apex_clipper import fingerprint, detect_events
    from experimental.in_memory_hud import (HUDFeatures, iter_indexed_images, read_memory_frames)
    from resume_io import RowJournal
    stats={}; setup=time.perf_counter(); engine=None
    if args.kind=='simulated':
        class Reader:
            width=100; height=60; source_frames=args.limit*100
            keyframes=range(args.start_index+args.limit)
            def __init__(self,*a,**k):pass
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def close(self):pass
            def read_keyframe(self,index):
                time.sleep(.002)
                return SimpleNamespace(pts=index*200,time_base=Fraction(1,100))
            def body_image(self,frame):return np.full((60,100,3),(frame.pts//200)%250,np.uint8)
        class Features:
            def prepare(self,frame):
                time.sleep(.006)
                return {'frame':frame.frame_id,'time':float(frame.timestamp),'pts':frame.pts,
                        'time_base':[1,100],'keyframe_index':frame.keyframe_index,
                        'inactive_view':False,'downed':False,'weapon_icon':'AA=='}, {
                            key:frame.image[:8,:8].copy() for key in ('ammo','damage','kills')}
        def recognize(images):
            time.sleep(.001+len(images)*.00005)
            return [(str(int(image[0,0,0])),.99) for image in images],0.
        features=Features();reader_factory=Reader
        identity=None;model_sha=None;backend_info={'backend':'simulated'}
    else:
        from gpu_ocr_backend import create_ocr_engine
        from ocr_cache import ExactTextCache
        from experimental.indexed_reader import IndexedKeyframeReader
        profile=json.loads(args.profile.read_text(encoding='utf-8'))
        features=HUDFeatures(profile);reader_factory=IndexedKeyframeReader
        identity=fingerprint(args.source)
        kwargs={'adaptive_numeric':True} if args.variant=='adaptive' else {}
        engine=create_ocr_engine(backend=args.backend,rec_batch_num=24,**kwargs)
        recognize=ExactTextCache(engine.text_rec);backend_info=engine.backend_info
        model_sha=hashlib.sha256(Path(backend_info['model_path']).read_bytes()).hexdigest()
    stats['setup_seconds']=time.perf_counter()-setup
    if args.variant=='adaptive':
        from experimental.in_memory_hud import iter_prepared_keyframes
        frames=iter_prepared_keyframes(args.source,features,start_index=args.start_index,
                                      reader_factory=reader_factory,stats=stats)
    else:
        frames=iter_indexed_images(args.source,mode='keyframes',workers=4,prefetch=8,
                                  start_index=args.start_index,reader_factory=reader_factory,stats=stats)
    journal=RowJournal(args.result.with_suffix('.jsonl'),'benchmark');commit_seconds=0.
    def commit(rows):
        nonlocal commit_seconds
        start=time.perf_counter();journal.append(rows);commit_seconds+=time.perf_counter()-start
    read_memory_frames(_limited(frames,args.limit),features,recognize,stats=stats,on_batch=commit)
    seconds=time.perf_counter()-setup
    if identity is not None:
        after=fingerprint(args.source)
        if after!=identity:raise ValueError(f'Benchmark source changed: before={identity}, after={after}')
    payload={'variant':args.variant,'seconds':seconds,'rows_per_second':len(journal.rows)/seconds,
             'rows':journal.rows,'events':detect_events(journal.rows),'stats':stats,
             'commit_seconds':commit_seconds,'source':identity,'backend':backend_info,'model_sha256':model_sha,
             'versions':{'python':platform.python_version(),'pyav':av.__version__,'onnxruntime':onnxruntime.__version__}}
    if hasattr(recognize,'stats'):payload['ocr']=recognize.stats()
    args.result.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')


def compare_rows(left,right):
    if len(left)!=len(right):return {'equal':False,'reason':'row count differs'}
    largest=0.; changed=0
    for a,b in zip(left,right):
        if a.keys()!=b.keys():return {'equal':False,'reason':'row fields differ'}
        for key in a:
            if key.endswith('_score'):
                if not math.isfinite(a[key]) or not math.isfinite(b[key]):
                    return {'equal':False,'reason':f'{key} is not finite'}
                difference=abs(a[key]-b[key]);largest=max(largest,difference)
                changed+=difference>0
                if difference>1e-5:return {'equal':False,'reason':f'{key} confidence differs by >1e-5'}
            elif a[key]!=b[key]:
                return {'equal':False,'reason':f'{key} differs at PTS {a.get("pts")}'}
    return {'equal':True,'max_confidence_difference':largest,'changed_confidences':changed}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parents[1]
    parser.add_argument('--baseline-root',type=Path)
    parser.add_argument('--kind',choices=['video','generated','simulated'],default='video')
    parser.add_argument('--source',type=Path)
    parser.add_argument('--profile',type=Path,default=root/'profile-ultrawide.json')
    parser.add_argument('--backend',choices=['cpu','dml','cuda'],default='cpu')
    parser.add_argument('--limit',type=int,default=64)
    parser.add_argument('--start-index',type=int,default=0)
    parser.add_argument('--pairs',type=int,default=2)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--_worker',action='store_true')
    parser.add_argument('--root',type=Path)
    parser.add_argument('--variant',choices=['baseline','adaptive'])
    parser.add_argument('--result',type=Path)
    args=parser.parse_args()
    if args._worker:
        _worker(args);return
    if not args.baseline_root or not args.report:
        parser.error('--baseline-root and --report are required')
    if args.limit<1 or args.start_index<0 or args.pairs<1:
        parser.error('Invalid range/repetition count')
    if args.kind=='video' and (args.source is None or not args.source.is_file()):
        parser.error('--source must be a local video')
    args.baseline_root=args.baseline_root.resolve()
    if args.baseline_root==root or not (args.baseline_root/'gpu_ocr_backend.py').is_file():
        parser.error('--baseline-root must be a separate source checkout')
    baseline_status=subprocess.check_output(['git','-C',str(args.baseline_root),'status','--porcelain'],text=True)
    if baseline_status:parser.error('Baseline checkout must be clean')
    report=args.report.resolve();report.relative_to((root/'validation').resolve())
    if report.exists():raise FileExistsError(report)
    report.parent.mkdir(parents=True,exist_ok=True)
    runs=[];reference=None;comparisons=[]
    with tempfile.TemporaryDirectory(prefix='scheduler-',dir=report.parent) as temp:
        if args.kind=='generated':
            if args.source is not None:parser.error('generated mode creates its own temporary source')
            args.source=Path(temp)/'generated-hud.mp4'
            _generate_fixture(args.source,args.profile,args.start_index+args.limit)
        for pair in range(args.pairs):
            for variant in (['baseline','adaptive'] if pair%2==0 else ['adaptive','baseline']):
                result=Path(temp)/f'{len(runs)}.json'
                command=[sys.executable,str(Path(__file__).resolve()),'--_worker','--root',str(args.baseline_root if variant=='baseline' else root),
                         '--variant',variant,'--kind',args.kind,'--backend',args.backend,'--profile',str(args.profile.resolve()),
                         '--limit',str(args.limit),'--start-index',str(args.start_index),'--result',str(result)]
                if args.source:command+=['--source',str(args.source.resolve())]
                launched=time.perf_counter();subprocess.run(command,check=True,cwd=root)
                run=json.loads(result.read_text(encoding='utf-8'));run['process_seconds']=time.perf_counter()-launched
                if reference is None:reference={key:run[key] for key in ('rows','events','model_sha256','source')}
                comparison=compare_rows(reference['rows'],run['rows'])
                comparison['events_equal']=reference['events']==run['events']
                comparison['model_equal']=reference['model_sha256']==run['model_sha256']
                comparison['source_equal']=reference['source']==run['source']
                comparisons.append(comparison)
                run['row_count']=len(run.pop('rows'));run.pop('events')
                runs.append(run)
                print(f'{variant}: {run["seconds"]:.3f}s, {run["rows_per_second"]:.2f} rows/s',flush=True)
    averages={variant:statistics.mean(run['seconds'] for run in runs if run['variant']==variant) for variant in ['baseline','adaptive']}
    commits={name:subprocess.check_output(['git','-C',str(folder),'rev-parse','HEAD'],text=True).strip()
             for name,folder in [('baseline',args.baseline_root),('adaptive',root)]}
    dirty=subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True)
    runtime_files=['apex_clipper.py','gpu_load.py','gpu_ocr_backend.py','ocr_cache.py','adaptive_scheduler.py','adaptive_ocr.py','experimental/in_memory_hud.py']
    source_hashes={name:{path:hashlib.sha256((folder/path).read_bytes()).hexdigest() for path in runtime_files if (folder/path).is_file()}
                   for name,folder in [('baseline',args.baseline_root),('adaptive',root)]}
    passed=all(c['equal'] and c['events_equal'] and c['model_equal'] and c['source_equal'] for c in comparisons)
    payload={'passed':passed,'kind':args.kind,'platform':platform.platform(),'commits':commits,
             'adaptive_worktree_dirty':bool(dirty),'runtime_source_sha256':source_hashes,'mean_seconds':averages,
             'speed_ratio':averages['baseline']/averages['adaptive'],'comparisons':comparisons,'runs':runs,
             'scope':'Indexed decode + HUD features + numeric OCR + durable journal, including model setup; excludes previews, dense refinement, outcome/name/weapon recognition, export and validation. Fresh processes, new OCR/journals; OS file cache uncontrolled.',
             'hardware_claim': 'NONE: simulated service times' if args.kind=='simulated' else f'{platform.system()} / {args.backend} only; '+('generated H.264, not Apex footage' if args.kind=='generated' else 'caller-supplied video')}
    report.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:payload[key] for key in ['passed','kind','mean_seconds','speed_ratio','hardware_claim']},ensure_ascii=False))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
