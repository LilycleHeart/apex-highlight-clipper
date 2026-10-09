"""Time short indexed decode bursts, without claiming detection equivalence."""
import argparse
import hashlib
import json
import time
from pathlib import Path
from fractions import Fraction
from concurrent.futures import ThreadPoolExecutor
from .indexed_reader import IndexedKeyframeReader

def main():
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path)
    parser.add_argument('--workers',type=int,choices=[1,2,4],default=4)
    parser.add_argument('--span',default='1/8');parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();before=args.source.stat();started=time.perf_counter()
    with IndexedKeyframeReader(args.source) as reader:count=len(reader.keyframes);source_frames=reader.source_frames
    def partition(worker):
        values=[];decoded=0
        with IndexedKeyframeReader(args.source,threads=1) as reader:
            for i in range(worker*count//args.workers,(worker+1)*count//args.workers):
                first,last,n=reader.read_burst(i,Fraction(args.span));decoded+=n
                values.append({'index':i,'first':float(first.pts*first.time_base),'last':float(last.pts*last.time_base),
                    'hashes':[hashlib.sha256(reader.body_image(f).tobytes()).hexdigest() for f in [first,last]]})
        return values,decoded
    records=[];decoded=0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for values,n in pool.map(partition,range(args.workers)):records.extend(values);decoded+=n
    after=args.source.stat()
    report={'seconds':time.perf_counter()-started,'workers':args.workers,'span':args.span,'keyframes':count,
        'sample_frames':len(records)*2,'video_packets_submitted':decoded,'source_index_entries':source_frames,
        'source_unchanged':(before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),
        'scope':'IO prototype only; no detection/OCR/export; sparse pairs do not establish absence of combat',
        'records':records}
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='records'},indent=2))

if __name__=='__main__':main()
