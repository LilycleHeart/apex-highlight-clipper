"""Compare indexed/sequential keyframe reads. Source video is read-only.

Usage: python -m experimental.benchmark_indexed_reader VIDEO --report REPORT.json
No frames are written to disk. Timing includes conversion and hashing in memory.
"""
import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .indexed_reader import IndexedKeyframeReader


def fingerprint(path):
    s=path.stat();return {'size':s.st_size,'mtime_ns':s.st_mtime_ns}


def main():
    import av
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=1,choices=[1,2,4])
    args=parser.parse_args();before=fingerprint(args.source)
    started=time.perf_counter();indexed=[]
    with IndexedKeyframeReader(args.source) as reader:
        index_seconds=time.perf_counter()-started;count=len(reader.keyframes)
        metadata={'width':reader.width,'height':reader.height,'time_base':str(reader.time_base)}
    def partition(worker):
        result=[]
        with IndexedKeyframeReader(args.source,threads=2 if args.workers==1 else 1) as reader:
            for i in range(worker*count//args.workers,(worker+1)*count//args.workers):
                frame=reader.read_keyframe(i);image=reader.body_image(frame)
                result.append((frame.pts,hashlib.sha256(image.tobytes()).hexdigest()))
        return result
    if args.workers==1:indexed=partition(0)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for values in pool.map(partition,range(args.workers)):indexed.extend(values)
    indexed_seconds=time.perf_counter()-started
    started=time.perf_counter();sequential=[]
    with av.open(str(args.source)) as container:
        stream=container.streams.video[0]
        stream.codec_context.thread_count=2;stream.codec_context.thread_type='SLICE'
        stream.codec_context.skip_frame='NONKEY'
        for frame in container.decode(stream):
            image=IndexedKeyframeReader.body_image(frame)
            sequential.append((frame.pts,hashlib.sha256(image.tobytes()).hexdigest()))
    sequential_seconds=time.perf_counter()-started
    report={'passed':indexed==sequential and before==fingerprint(args.source),
            'index_seconds':index_seconds,'indexed_seconds':indexed_seconds,
            'sequential_seconds':sequential_seconds,'keyframes':len(indexed),
            'all_pts_and_pixels_equal':indexed==sequential,'source_unchanged':before==fingerprint(args.source),
            'pyav':av.__version__,'indexed_workers':args.workers,'indexed_threads_per_worker':2 if args.workers==1 else 1,
            'sequential_threads':2,**metadata,
            'scope':'decoded keyframes only; in-memory scale/hash; no OCR/export; OS cache uncontrolled'}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    if not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
