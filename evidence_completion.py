"""审计失败只补未识别区间；复用原行及图像，不整片重复解码/OCR。"""
import hashlib
import json
import math
from pathlib import Path
import shutil

from apex_clipper import fingerprint,probe,read_hud,write_json
from resume_media import sample_with_resume
from app_cancel import check_cancel


def missing_ranges(total, rows, fps):
    present=set()
    for row in rows:
        index=int(Path(row['frame']).stem)
        if not 1<=index<=total or abs(row['time']-(index-.5)/fps)>1e-6:
            raise ValueError('补查只能复用原时间网格的识别行')
        if index in present: raise ValueError('局部识别行重复')
        present.add(index)
    ranges=[]
    for index in range(1,total+1):
        if index in present: continue
        if ranges and index==ranges[-1][1]+1: ranges[-1][1]=index
        else: ranges.append([index,index])
    return ranges


def merge_rows(existing, added, total, fps):
    by_frame={r['frame']:dict(r) for r in added}
    # 已有行含结束/枪械字段，必须保留，不能被数字补查覆盖。
    for row in existing: by_frame.setdefault(row['frame'],{}).update(row)
    rows=sorted(by_frame.values(),key=lambda r:r['time'])
    if missing_ranges(total,rows,fps): raise ValueError('补查后仍有缺失的识别帧')
    return rows


def complete_missing(source,job,samples,profile,fps,output,cuda=False,cpu_threads=None):
    job=Path(job); samples=Path(samples); output=Path(output)
    cache=json.loads(output.read_text(encoding='utf-8'))
    duration=float(probe(source)[0]['format']['duration']); total=max(1,math.floor(duration*fps+.5))
    identity=fingerprint(source)
    if cache.get('source')!=identity: raise ValueError('局部结果来源已变化')
    if cache.get('fps')!=fps or cache.get('profile',profile)!=profile: raise ValueError('局部结果的HUD配置或频率不匹配')
    root=job/'gap-fill'; root.mkdir(exist_ok=True)
    done=root/'complete.json'; merged=root/'hud-merged.json'; assembled=root/'samples'
    if done.exists():
        state=json.loads(done.read_text(encoding='utf-8'))
        if state['source']!=identity or state['fps']!=fps or state['profile']!=profile: raise ValueError('已完成补查的来源、HUD配置或频率不匹配')
        if hashlib.sha256(merged.read_bytes()).hexdigest()!=state['hud_sha256']: raise ValueError('补查结果文件损坏')
        for entry in state['files']:
            target=assembled/entry['path']; target.resolve().relative_to(assembled.resolve())
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=entry['sha256']:
                raise ValueError('补查合并图像损坏')
        return json.loads(merged.read_text(encoding='utf-8')),assembled
    ranges=missing_ranges(total,cache['rows'],fps)
    config={'source':identity,'fps':fps,'profile':profile,'samples':str(samples.resolve()),'ranges':ranges,
            'rows_sha256':hashlib.sha256(json.dumps(cache['rows'],sort_keys=True).encode()).hexdigest()}
    plan=root/'plan.json'
    if plan.exists():
        if json.loads(plan.read_text(encoding='utf-8'))!=config: raise ValueError('缺口补查断点与局部结果不匹配')
    else: write_json(plan,config)
    missing=root/'missing'; missing_hud=root/'missing-hud.json'
    if ranges:
        sample_with_resume(source,missing,fps,cuda,frame_ranges=ranges,**({'cpu_threads':cpu_threads} if cpu_threads else {}))
        added=read_hud(missing,profile,fps,missing_hud,resume=True,source_identity=identity)
    else: added=[]
    rows=merge_rows(cache['rows'],added,total,fps)
    (assembled/'hud').mkdir(parents=True,exist_ok=True)
    old_names={r['frame'] for r in cache['rows']}
    files=[]
    for row in rows:
        check_cancel(); origin=samples if row['frame'] in old_names else missing
        for relative in [Path(row['frame']),Path('hud')/row['frame']]:
            target=assembled/relative; source_image=origin/relative
            target.resolve().relative_to(assembled.resolve())
            if not source_image.is_file(): raise ValueError('缺少补查合并图像')
            content=source_image.read_bytes()
            if not target.is_file() or target.read_bytes()!=content:
                scratch=target.with_suffix('.copying'); shutil.copyfile(source_image,scratch); scratch.replace(target)
            files.append({'path':str(relative),'sha256':hashlib.sha256(content).hexdigest()})
    cache.update(rows=rows,complete=True,evidence_completion={'reused_frames':len(old_names),'added_frames':len(added),'ranges':ranges})
    for key in ['outcome_signature','outcome_events','weapon_label_signature']:
        cache.pop(key,None)
    # 完整采样与合并结果只在所有缺口已完成之后提交；中断可复用两个阶段的原断点。
    write_json(assembled/'complete.json',{'source':identity,'fps':fps,'width':1280,'duration':duration})
    write_json(merged,cache)
    if fingerprint(source)!=identity: raise ValueError('补查时源录像发生变化')
    write_json(done,{'source':identity,'fps':fps,'profile':profile,'hud_sha256':hashlib.sha256(merged.read_bytes()).hexdigest(),'files':files})
    return cache,assembled
