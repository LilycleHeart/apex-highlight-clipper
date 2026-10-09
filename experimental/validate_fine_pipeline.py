"""Fresh-process comparison of legacy versus continuous sparse fine reading."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from apex_clipper import BASE,fingerprint,probe,read_hud
from resume_media import sample_with_resume


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--mode',choices=['legacy','continuous'],required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--reference-samples',type=Path,required=True)
    p.add_argument('--reference-hud',type=Path,required=True)
    p.add_argument('--backend',choices=['cpu','dml'],default='dml')
    args=p.parse_args()
    if args.report.exists():raise ValueError('Use a new report file')
    args.report.resolve().relative_to((BASE/'validation').resolve())
    plan=json.loads(args.plan.read_text(encoding='utf-8'));ranges=plan['frame_ranges']
    reference=json.loads(args.reference_hud.read_text(encoding='utf-8'))
    identity=fingerprint(args.source)
    if reference.get('source')!=identity:raise ValueError('Reference source does not match')
    fps=reference['fps'];profile=reference['profile']
    root=BASE/'validation'/('fine-pipeline-'+uuid.uuid4().hex[:8]);root.mkdir()
    samples=root/'samples';hud=root/'hud.json'
    os.environ.update(APEX_OCR_BACKEND=args.backend,APEX_GPU_LOAD='fast',APEX_OCR_POOL='1')
    started=time.perf_counter()
    if args.mode=='legacy':
        sample_with_resume(args.source,samples,fps,args.backend=='dml',frame_ranges=ranges)
        rows=read_hud(samples,profile,fps,hud,resume=True,source_identity=identity)
    else:
        from sparse_pipeline import sample_and_read_sparse
        rows=sample_and_read_sparse(args.source,samples,profile,fps,hud,ranges,cuda=args.backend=='dml')
    seconds=time.perf_counter()-started
    rows=json.loads(hud.read_text(encoding='utf-8'))['rows']
    expected=[f'{i:06d}.jpg' for first,last in ranges for i in range(first,last+1)]
    different=[]
    for name in expected:
        for relative in [Path(name),Path('hud')/name]:
            a=samples/relative;b=args.reference_samples/relative
            if not b.is_file() or hashlib.sha256(a.read_bytes()).digest()!=hashlib.sha256(b.read_bytes()).digest():different.append(str(relative))
    old={r['frame']:r for r in reference['rows']};changes=[]
    fields=['time','ammo','damage','kills','weapon_icon','counter_offset','inactive_view','downed']
    for row in rows:
        for key in fields:
            if row.get(key)!=old.get(row['frame'],{}).get(key):changes.append({'frame':row['frame'],'field':key,'new':row.get(key),'reference':old.get(row['frame'],{}).get(key)})
    report={'mode':args.mode,'seconds':seconds,'source_unchanged':fingerprint(args.source)==identity,
        'rows':len(rows),'planned':len(expected),'image_differences':different,'numeric_state_differences':changes,
        'samples':str(samples),'hud':str(hud),'sampling_state':json.loads((samples/'sampling-checkpoint.json').read_text(encoding='utf-8')),
        'scope':'Fresh decode/OCR cache in this process; includes initialization; excludes validation and combat qualification/export; OS cache uncontrolled'}
    report['passed']=not different and not changes and report['source_unchanged'] and [r['frame'] for r in rows]==expected
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='sampling_state'},ensure_ascii=True),flush=True)
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
