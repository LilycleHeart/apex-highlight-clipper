"""仅修复旧完整任务的空计数，使用保留的采样；不需要原录像，不改视频或任务参数。"""
import hashlib
import json
import os
from pathlib import Path
import sys

def repair(record):
    from combat_statistics import counter_endpoints,reconciled_counts,VERSION
    from apex_clipper import BASE,write_json
    destination=Path(record['directory']);original=destination/'statistics.json'
    if not original.is_file():return
    raw=original.read_bytes();report=json.loads(raw)
    if report.get('version')==VERSION:return
    cache=json.loads((Path(record['analysis_cache'])/'hud.json').read_text(encoding='utf-8'))
    if cache.get('source')!=report.get('source'):return
    from stat_counter_fallback import counter_recipe
    recipe=counter_recipe();signature=hashlib.sha256(raw+VERSION.encode()+recipe.encode()).hexdigest();target=destination/'statistics-corrected.json'
    if target.is_file():
        try:
            if json.loads(target.read_text(encoding='utf-8')).get('repair_signature')==signature:return
        except (OSError,ValueError):pass
    if not any(s['counts'].get(key) is None for s in report['segments'] for key in ['kills','assists','damage']):return
    profile=json.loads((BASE/'profile-ultrawide.json').read_text(encoding='utf-8'))
    endpoints=counter_endpoints(cache,record['sample_directory'],report['segments'],profile)
    changed=0
    for index,(segment,fresh) in enumerate(zip(report['segments'],endpoints)):
        old=segment['endpoint']
        for group in ['baseline','last_hud']:
            for key,value in old[group].items():
                if value is not None:fresh[group][key]=value
        settlement=report.get('last_team_settlement') if index==len(report['segments'])-1 else None
        result=reconciled_counts(fresh,segment['events'],segment['coverage'],settlement)
        for key in ['kills','assists','damage']:
            if result['counts'][key] is not None and (segment['counts'].get(key) is None or segment['partial'].get(key,False) and not result['partial'][key]):
                segment['counts'][key]=result['counts'][key];segment['partial'][key]=result['partial'][key];changed+=1
        segment['endpoint']=fresh
    report.update(repair_signature=signature,counter_recipe=recipe,version=VERSION,repair_fields=changed)
    write_json(target,report)

def main(request):
    os.environ['APEX_OCR_BACKEND']='cpu';os.environ['APEX_GPU_LOAD']='low';os.environ['APEX_OCR_POOL']='1'
    records=json.loads(Path(request).read_text(encoding='utf-8'));done=0
    for record in records:
        try:repair(record);done+=1
        except (OSError,ValueError,KeyError):pass
    print(json.dumps({'processed':done}),flush=True)

if __name__=='__main__':main(sys.argv[1])
