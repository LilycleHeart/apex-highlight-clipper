"""Compare repeated 30-second decoder sessions to one continuous range."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

from apex_clipper import fingerprint,probe,tool


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--start',type=float,required=True)
    p.add_argument('--count',type=int,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--parallel-test',action='store_true')
    a=p.parse_args()
    if a.report.exists() or a.start<0 or not 1<=a.count<=5000:raise ValueError('Use valid bounds and a new report')
    identity=fingerprint(a.source); _,v=probe(a.source);w,h=v['width'],v['height']
    if '10' in v.get('pix_fmt',''):raise ValueError('This test currently expects an 8-bit source')
    cx=round(w*.75/2)*2;cy=round(h*5/6/2)*2
    graph=f'[0:v:0]fps=2,hwdownload,format=nv12,split=2[b][h];[b]scale=1280:-2[body];[h]crop={w-cx}:{h-cy}:{cx}:{cy}[hud]'
    root=a.report.parent/('fine-chunks-'+uuid.uuid4().hex[:8]);root.mkdir(parents=True)
    records=[];reference=None
    order=['split','parallel','parallel','split'] if a.parallel_test else ['split','continuous','continuous','split']
    for trial,kind in enumerate(order):
        blocks=[(n,min(60,a.count-n)) for n in range(0,a.count,60)] if kind in ['split','parallel'] else [(0,a.count)]
        elapsed=0;hashes=[];body=[];hud=[]
        def decode(block):
            offset,count=block
            folder=root/f'{trial}-{kind}-{offset}';(folder/'hud').mkdir(parents=True)
            command=[tool('ffmpeg'),'-hide_banner','-loglevel','warning','-nostdin','-ss',str(a.start+offset/2),
                '-t',str(count/2+.5),'-hwaccel','cuda','-hwaccel_output_format','cuda','-i',str(a.source),'-filter_complex',graph]
            for stream,sub in [('body',''),('hud','hud')]:
                command+=['-map',f'[{stream}]','-frames:v',str(count),'-q:v','2','-n',str(folder/sub/'%06d.jpg')]
            result=subprocess.run(command,capture_output=True)
            if result.returncode:raise RuntimeError(result.stderr.decode('utf-8',errors='replace')[-3000:])
            return folder,count
        started=time.perf_counter()
        if kind=='parallel':
            with ThreadPoolExecutor(max_workers=2) as pool: decoded=list(pool.map(decode,blocks))
        else: decoded=[decode(block) for block in blocks]
        elapsed=time.perf_counter()-started
        for folder,count in decoded:
            for target,sub in [(body,''),(hud,'hud')]:
                files=sorted((folder/sub).glob('*.jpg'))
                if len(files)!=count:raise ValueError('Wrong sample count')
                target.extend(hashlib.sha256(f.read_bytes()).hexdigest() for f in files)
        hashes=body+hud
        if reference is None:reference=hashes
        record={'mode':kind,'processes':len(blocks),'seconds':elapsed,'jpegs':len(hashes),'encoded_frames_equal':hashes==reference}
        records.append(record);print(json.dumps(record),flush=True)
    report={'runs':records,'source_unchanged':identity==fingerprint(a.source),'start':a.start,'count':a.count,
            'scope':'2 FPS exact output JPEG comparison, ABBA process-inclusive wall time, verification excluded; caches uncontrolled; continuous variant has no incremental checkpoint implementation'}
    a.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
