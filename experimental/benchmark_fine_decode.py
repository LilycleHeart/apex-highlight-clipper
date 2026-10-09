"""Isolate fine-sampling decode, JPEG and thread costs without editing production."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
import uuid

import cv2
from apex_clipper import fingerprint, probe, tool


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--start',type=float,required=True)
    p.add_argument('--count',type=int,default=60)
    p.add_argument('--fps',type=float,default=2)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--decoder-test',action='store_true',help='Compare stock H.264 hardware acceleration with CUVID parsing')
    a=p.parse_args()
    if not math.isfinite(a.start) or a.start<0 or a.count<1 or not 0<a.fps<=5:
        raise ValueError('Invalid sampling interval')
    if a.report.exists() or a.report.resolve()==a.source.resolve(): raise ValueError('Use a new report file')
    identity=fingerprint(a.source); _,v=probe(a.source)
    w,h=v['width'],v['height']; cx=round(w*.75/2)*2;cy=round(h*5/6/2)*2
    transfer='hwdownload,format=p010le,' if '10' in v.get('pix_fmt','') else 'hwdownload,format=nv12,'
    graph=f'[0:v:0]fps={a.fps},'+transfer+f'split=2[b][h];[b]scale=1280:-2[body];[h]crop={w-cx}:{h-cy}:{cx}:{cy}[hud]'
    a.report.parent.mkdir(parents=True,exist_ok=True)
    root=a.report.parent/('fine-decode-'+uuid.uuid4().hex[:8]);root.mkdir()
    records=[]; baseline=None
    variants=['jpeg-default','jpeg-bounded','null-default','null-bounded']
    if a.decoder_test:variants=['jpeg-default','jpeg-cuvid']
    for i,name in enumerate(variants+variants[::-1]):
        folder=root/f'{i}-{name}';(folder/'hud').mkdir(parents=True)
        bounded=name.endswith('bounded');jpeg=name.startswith('jpeg')
        cmd=[tool('ffmpeg'),'-hide_banner','-loglevel','warning','-nostdin','-ss',f'{a.start:.9f}',
             '-t',f'{a.count/a.fps+1/a.fps:.9f}','-hwaccel','cuda','-hwaccel_output_format','cuda']
        if bounded:cmd+=['-threads','2','-filter_complex_threads','2']
        if name.endswith('cuvid'):cmd+=['-c:v','h264_cuvid']
        cmd+=['-i',str(a.source),'-filter_complex',graph]
        for stream,sub in [('body',''),('hud','hud')]:
            cmd+=['-map',f'[{stream}]','-frames:v',str(a.count)]
            if jpeg:
                cmd+=['-q:v','2']
                if bounded:cmd+=['-threads:v','1']
                cmd+=['-n',str(folder/sub/'%06d.jpg')]
            else:cmd+=['-f','null','-']
        started=time.perf_counter();result=subprocess.run(cmd,capture_output=True)
        elapsed=time.perf_counter()-started
        (folder/'stderr.log').write_bytes(result.stderr)
        if result.returncode:raise RuntimeError(result.stderr.decode('utf-8',errors='replace')[-3000:])
        record={'variant':name,'seconds':elapsed}
        if jpeg:
            files=sorted(folder.glob('*.jpg'))+sorted((folder/'hud').glob('*.jpg'))
            if len(files)!=a.count*2:raise ValueError('Unexpected JPEG count')
            encoded=[hashlib.sha256(f.read_bytes()).hexdigest() for f in files]
            pixels=[hashlib.sha256(cv2.imread(str(f)).tobytes()).hexdigest() for f in files]
            if baseline is None:baseline=(encoded,pixels)
            record.update(jpegs=len(files),bytes=sum(f.stat().st_size for f in files),
                          encoded_equal_to_first=encoded==baseline[0],pixels_equal_to_first=pixels==baseline[1])
        records.append(record);print(json.dumps(record),flush=True)
    report={'runs':records,'source_unchanged':identity==fingerprint(a.source),
            'start':a.start,'count':a.count,'fps':a.fps,'outputs':str(root),
            'scope':'Same fine-sampling interval, forward/reverse order; process startup included, hash verification excluded; OS cache uncontrolled; no OCR/export'}
    a.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
