"""Compare early real burst frames against an independent FFmpeg decode."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from fractions import Fraction
from .indexed_reader import IndexedKeyframeReader

def main():
    from apex_clipper import tool
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path)
    parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
    before=args.source.stat();samples=[]
    with IndexedKeyframeReader(args.source) as reader:
        rate=reader.stream.average_rate;width,height=reader.width,reader.height
        for i in range(min(3,len(reader.keyframes))):
            first,last,_=reader.read_burst(i,Fraction(1,8))
            for frame in [first,last]:
                number=frame.pts*frame.time_base*rate
                if number.denominator!=1:raise ValueError('Reference verifier requires CFR samples')
                samples.append((int(number),frame.pts,hashlib.sha256(frame.to_ndarray(format=frame.format.name).tobytes()).hexdigest()))
        pixel_format=first.format.name
    if pixel_format not in ['yuv420p','yuvj420p']:raise ValueError('Reference verifier requires 8-bit 4:2:0')
    expression='+'.join(f'eq(n\\,{n})' for n,_,_ in samples)
    result=subprocess.run([tool('ffmpeg'),'-hide_banner','-loglevel','error','-threads','2','-i',str(args.source),
        '-map','0:v:0','-an','-sn','-vf','select='+expression,'-fps_mode','passthrough','-frames:v',str(len(samples)),
        '-pix_fmt',pixel_format,'-f','rawvideo','pipe:1'],capture_output=True,check=True)
    frame_bytes=width*height*3//2
    if len(result.stdout)!=frame_bytes*len(samples):raise ValueError('Unexpected FFmpeg reference frame count')
    checks=[{'frame_number':n,'pts':pts,'equal':digest==hashlib.sha256(result.stdout[i*frame_bytes:(i+1)*frame_bytes]).hexdigest()}
            for i,(n,pts,digest) in enumerate(samples)]
    after=args.source.stat()
    report={'passed':all(x['equal'] for x in checks),'checks':checks,'pixel_format':pixel_format,
            'source_unchanged':(before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),
            'scope':'first three keyframes and 1/8-second successors; native YUV bytes against FFmpeg, not whole-video detection validation'}
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    if not report['passed'] or not report['source_unchanged']:raise SystemExit(1)

if __name__=='__main__':main()
