"""关键帧粗查、计分变化驱动二分、局部细查；计分核对异常时自动补查。"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
import cv2
from apex_clipper import (BASE,probe,tool,fingerprint,write_json,read_hud,detect_events,icon_similarity,
                         counter_offset,inactive_view,downed_score,icon_signature)
from resume_media import sample_with_resume
from app_cancel import check_cancel
from outcome_reader import friend_view,enrich_outcomes
from ui_observer import phase,preview

def load(path): return json.loads(Path(path).read_text(encoding='utf-8'))

def extract(source,directory,profile,keyframes=True,at=None):
    directory=Path(directory); (directory/'hud').mkdir(parents=True,exist_ok=True)
    args=[tool('ffmpeg'),'-hide_banner','-loglevel','info','-nostdin','-threads','2']
    if keyframes: args+=['-skip_frame','nokey']
    if at is not None: args+=['-ss',f'{at:.9f}']
    x,y,w,h=profile['weapon_native_crop']
    graph=f'[0:v:0]split=2[b][h];[b]scale=1280:-2,showinfo[body];[h]crop={w}:{h}:{x}:{y}[hud]'
    args+=['-i',str(source),'-filter_complex',graph,'-map','[body]','-fps_mode','passthrough','-q:v','2']
    if at is not None: args+=['-frames:v','1']
    args+=['-n',str(directory/'%06d.jpg'),'-map','[hud]','-fps_mode','passthrough','-q:v','2']
    if at is not None: args+=['-frames:v','1']
    args+=['-n',str(directory/'hud/%06d.jpg')]
    with (directory/'decode.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            while proc.poll() is None: check_cancel(); time.sleep(.3)
        except BaseException: proc.terminate(); proc.wait(); raise
    text=(directory/'decode.log').read_text(encoding='utf-8',errors='replace')
    if proc.returncode: raise RuntimeError(text[-3000:])
    frames=sorted(directory.glob('*.jpg'))
    times=[float(t) for _,t in re.findall(r'\bn:\s*(\d+).*?\bpts_time:([\d.eE+\-]+)',text)]
    if at is not None:
        if len(frames)!=1: raise ValueError('二分探测帧不完整')
        times=[at+(times[0] if times else 0.)]
    elif len(times)!=len(frames): raise ValueError('粗查帧与真实 PTS 不一致')
    return {p.name:t for p,t in zip(frames,times)}

def coarse_scan(source,job,profile,fps):
    source=Path(source); folder=Path(job)/'coarse'; folder.mkdir(parents=True,exist_ok=True)
    identity=fingerprint(source); complete=folder/'sampling.json'
    if complete.exists():
        saved=load(complete)
        if saved['source']!=identity: raise ValueError('粗查缓存来源已变化')
        samples=Path(saved['samples']); times=saved['timestamps']
        if not all((samples/name).is_file() and (samples/'hud'/name).is_file() for name in times): complete.unlink(); return coarse_scan(source,job,profile,fps)
    else:
        samples=folder/('samples-'+uuid.uuid4().hex[:8])
        times=extract(source,samples,profile)
        write_json(complete,{'source':identity,'samples':str(samples),'timestamps':times})
    cache_path=folder/'hud.json'
    if cache_path.exists() and load(cache_path).get('coarse_strategy')=='anchor8s-state-v3':
        cached=load(cache_path)
        if cached['rows']:
            row=cached['rows'][-1]; preview(samples/row['frame'],row['time'])
        return cached
    marker=cv2.imread(str(BASE/profile['counter_marker']),cv2.IMREAD_GRAYSCALE)
    downed=cv2.imread(str(BASE/profile['downed_marker']),cv2.IMREAD_GRAYSCALE)
    cheap=[]; chosen=set(); previous=None; last_anchor=-100.
    for name,t in sorted(times.items(),key=lambda item:item[1]):
        check_cancel(); frame=cv2.imread(str(samples/name)); delta,score=counter_offset(frame,profile,marker)
        state=inactive_view(frame); shield=downed_score(frame,profile,downed)
        r={'frame':name,'time':t,'ammo':None,'damage':None,'kills':None,'weapon_icon':icon_signature(frame,profile),
            'inactive_view':state,'downed_score':shield,'downed':shield>=profile['downed_marker_threshold'],
            'friend_spectate':friend_view(frame,state),'counter_offset':delta,'counter_marker_score':score}
        changes=previous is not None and any(r.get(k)!=previous.get(k) for k in ['inactive_view','downed','friend_spectate'])
        visibility=previous is not None and (delta is not None)!=(previous['counter_offset'] is not None)
        if t-last_anchor>=8 or changes or visibility or r['downed'] or r['friend_spectate']:
            chosen.add(name); last_anchor=t
            if (changes or visibility) and previous: chosen.add(previous['frame'])
        cheap.append(r); previous=r
        preview(samples/name,t)
    chosen.add(cheap[-1]['frame'])
    number_path=folder/'numbers.json'
    numbers=read_hud(samples,profile,fps,number_path,timestamps=times,resume=True,source_identity=identity,selected_names=chosen)
    by_name={r['frame']:r for r in numbers}
    for r in cheap:
        if r['frame'] in by_name: r.update(by_name[r['frame']])
    cache={'source':identity,'profile':profile,'fps':fps,'complete':True,'rows':cheap,'outcome_events':[],
        'coarse_strategy':'anchor8s-state-v3','numeric_frames':len(numbers)}
    write_json(cache_path,cache)
    return cache

def refine_coarse(source,job,profile,fps,coarse):
    from adaptive_evidence import refinement_names
    folder=Path(job)/'coarse'; output=folder/'refined.json'
    signature=hashlib.sha256(json.dumps({'source':fingerprint(source),'profile':profile,'fps':fps,
        'coarse_rows':coarse['rows']},sort_keys=True).encode()).hexdigest()
    if output.exists():
        cached=load(output)
        if cached.get('refinement_signature')!=signature: raise ValueError('关键帧复查缓存与当前粗查不匹配')
        return cached
    chosen=refinement_names(coarse['rows'],activity_brackets(coarse['rows']))
    saved=load(folder/'sampling.json'); samples=Path(saved['samples'])
    cache=dict(coarse); cache['rows']=[dict(r) for r in coarse['rows']]
    if chosen:
        numbers=read_hud(samples,profile,fps,folder/'refinement-numbers.json',timestamps=saved['timestamps'],
            resume=True,source_identity=fingerprint(source),selected_names=chosen)
        by_name={r['frame']:r for r in numbers}
        for r in cache['rows']:
            if r['frame'] in by_name: r.update(by_name[r['frame']])
        cache['refinement_numeric_frames']=len(numbers)
    else: cache['refinement_numeric_frames']=0
    cache['refinement_signature']=signature; write_json(output,cache)
    return cache

def activity_brackets(rows):
    seeds=[]; previous={}; last=None; last_ammo=None
    for row in rows:
        t=row['time']
        if last and t-last['time']>5: seeds.append({'start':last['time'],'end':t,'reason':'wide_keyframe_gap'})
        if row.get('downed') or row.get('friend_spectate'):
            seeds.append({'start':last['time'] if last else t,'end':t,'reason':'team_or_downed'})
        if last and row.get('inactive_view')!=last.get('inactive_view') and (last.get('ammo') is not None or last.get('friend_spectate')):
            seeds.append({'start':last['time'],'end':t,'reason':'view_transition'})
        if not row.get('inactive_view'):
            for key in ['damage','kills']:
                value=row.get(key)
                if value is None: continue
                before=previous.get(key)
                if value>0 and ((before and value>before[key]) or (before is None and t>15)):
                    left=before['time'] if before else (last['time'] if last else max(0,t-3))
                    seeds.append({'start':left,'end':t,'reason':key,'before':before[key] if before else 0,'after':value})
                elif before and value<before[key]:
                    seeds.append({'start':max(0,t-8),'end':t,'reason':'counter_reset_or_uncertain'})
                previous[key]=row
            if row.get('ammo') is not None:
                if last_ammo and row['ammo']<last_ammo['ammo'] and t-last_ammo['time']<=12 and icon_similarity(last_ammo['weapon_icon'],row['weapon_icon'])>=.5:
                    seeds.append({'start':last_ammo['time'],'end':t,'reason':'ammo_change'})
                last_ammo=row
        else: last_ammo=None
        last=row
    if rows and not rows[0].get('inactive_view') and rows[0].get('ammo') is not None:
        seeds.append({'start':0,'end':min(15,rows[-1]['time']),'reason':'recording_started_in_play'})
    return seeds

def merge_windows(seeds,duration,padding):
    result=[]
    for seed in sorted(seeds,key=lambda s:s['start']):
        a=max(0,seed['start']-padding); b=min(duration,seed['end']+padding)
        if result and a<=result[-1][1]: result[-1][1]=max(result[-1][1],b)
        else: result.append([a,b])
    return result

def frame_ranges(windows,duration,fps):
    count=max(1,math.floor(duration*fps+.5)); ranges=[]
    for start,end in windows:
        first=max(1,math.ceil(start*fps+.5)); last=min(count,math.floor(end*fps+.5))
        if last<first: continue
        if ranges and first<=ranges[-1][1]+1: ranges[-1][1]=max(ranges[-1][1],last)
        else: ranges.append([first,last])
    return ranges

def bisect_edges(source,job,profile,fps,seeds,gap):
    folder=Path(job)/'probes'; folder.mkdir(exist_ok=True); points_path=folder/'points.json'
    points=load(points_path) if points_path.exists() else {}
    def query(t):
        key=f'{t:.6f}'
        if key not in points:
            check_cancel(); directory=folder/uuid.uuid4().hex[:8]
            times=extract(source,directory,profile,keyframes=False,at=t)
            output=directory/'hud.json'
            read_hud(directory,profile,fps,output,timestamps=times,source_identity=fingerprint(source))
            points[key]=load(output)['rows'][0]; write_json(points_path,points)
            preview(directory/points[key]['frame'],points[key]['time'])
        return points[key]
    # 只细化每组伤害变化的首尾，不逐个追查每发子弹。
    damage=[s for s in seeds if s['reason']=='damage']; groups=[]
    for s in damage:
        if groups and s['start']-groups[-1][-1]['end']<=gap: groups[-1].append(s)
        else: groups.append([s])
    refined=[]
    for group in groups:
        for seed,first in [(group[0],True),(group[-1],False)]:
            left,right=seed['start'],seed['end']; baseline=seed['before']; terminal=seed['after']
            for _ in range(5):
                if right-left<=max(.5,1/fps): break
                middle=(left+right)/2; row=query(middle); value=row.get('damage')
                if value is None or row.get('inactive_view'): break
                if first:
                    if value>baseline: right=middle
                    else: left=middle
                else:
                    if value>=terminal: right=middle
                    else: left=middle
            refined.append({'start':left,'end':right,'reason':'binary_damage_edge'})
    return refined,len(points)

def audit_counters(coarse,fine,duration,outcomes=None):
    edges=[0]+sorted({e['time'] for e in (outcomes or coarse.get('outcome_events',[])) if e['time']>0})+[duration+1]
    checks=[]
    events=detect_events(fine)
    for start,end in zip(edges,edges[1:]):
        for key,kind in [('damage','hit'),('kills','kill')]:
            observed=[r for r in coarse['rows'] if start<=r['time']<=end and not r.get('inactive_view') and r.get(key) is not None]
            detail=[r for r in fine if start<=r['time']<=end and not r.get('inactive_view') and r.get(key) is not None]
            if not observed: continue
            if not detail:
                checks.append({'field':key,'start':start,'end':end,'passed':False,'reason':'coarse_counter_missing_in_detail'}); continue
            # 终值必须对齐；起始录像半局的基线沿用细查头部，避免关键帧与0.25s相位差。
            endpoint=observed[-1][key]
            near=[r[key] for r in detail if abs(r['time']-observed[-1]['time'])<=3]
            baseline=detail[0][key] if detail[0]['time']-start<15 else 0
            expected=max(0,endpoint-baseline)
            detected=sum(e['after']-(e['before'] or 0) for e in events if e['kind']==kind and start<=e['time']<=end)
            checks.append({'field':key,'start':start,'end':end,'coarse_final':endpoint,'detail_final':detail[-1][key],
                'observed_increment_lower_bound':expected,'detected_increment':detected,
                'passed':bool(near and min(near)<=endpoint<=max(near) and detected>=expected)})
    return {'passed':all(c['passed'] for c in checks),'checks':checks}

def smart_read(source,job,samples,profile,fps,output,gap=35,pre=10,post=15,cuda=False,result_first=False):
    timings={}
    def timed(name,call):
        start=time.perf_counter()
        try: return call()
        finally: timings[name]=round(timings.get(name,0)+time.perf_counter()-start,3)
    identity=fingerprint(source); meta,video=probe(source); duration=float(meta['format']['duration'])
    job=Path(job); plan_path=job/'smart-plan.json'; full_count=max(1,math.floor(duration*fps+.5))
    config={'source':identity,'profile':profile,'fps':fps,'gap':gap,'pre':pre,'post':post,'version':3 if result_first else 2}
    token=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    print('SMART_PROGRESS: 5',flush=True)
    phase('coarse','正在寻找交战的蛛丝马迹……',5)
    coarse=timed('coarse',lambda:coarse_scan(source,job,profile,fps))
    print('SMART_PROGRESS: 20',flush=True)
    if plan_path.exists():
        plan=load(plan_path)
        if plan['signature']!=token: raise ValueError('智能识别断点参数不匹配')
        if plan.get('strategy') in ['evidence-v3','focused-v5','focused-v6']: coarse=refine_coarse(source,job,profile,fps,coarse)
    else:
        phase('bisect','发现计数变化，正在复查附近已有画面……',20)
        coarse=timed('refine',lambda:refine_coarse(source,job,profile,fps,coarse))
        seeds=activity_brackets(coarse['rows'])
        from adaptive_evidence import evidence_windows
        windows=evidence_windows(coarse['rows'],seeds,duration,merge_windows,gap)
        original_windows=windows
        early=None; excluded=[]
        if result_first:
            from early_round_end import inspect_early_round_ends,terminal_idle_ranges,subtract_windows
            from planning_evidence import classify_seed_strength,focused_windows
            phase('outcomes','先检查本局结束或换局证据，缩小细查范围……',22)
            coarse_samples=load(job/'coarse/sampling.json')['samples']
            early=timed('early_round',lambda:inspect_early_round_ends(coarse,coarse_samples,job/'early-round-ends.json'))
            excluded=terminal_idle_ranges(coarse['rows'],early['events'],duration)
            windows=focused_windows(coarse['rows'],classify_seed_strength(coarse['rows'],seeds),duration,merge_windows,gap)
            windows=subtract_windows(windows,excluded)
            # 少量保护边界会让简单录像反而多查；此时保留原有更小且已验证的计划。
            original_trimmed=subtract_windows(original_windows,excluded)
            if sum(b-a+1 for a,b in frame_ranges(windows,duration,fps))>=sum(b-a+1 for a,b in frame_ranges(original_trimmed,duration,fps)):
                windows=original_trimmed
        ranges=frame_ranges(windows,duration,fps)
        plan={'signature':token,'strategy':'focused-v6' if result_first else 'evidence-v3','windows':windows,'frame_ranges':ranges,'seed_count':len(seeds),'binary_probes':0,
            'refinement_numeric_frames':coarse.get('refinement_numeric_frames',0),
            'coarse_frames':len(coarse['rows']),'coarse_numeric_frames':coarse['numeric_frames'],'full_frames':full_count,'mode':'smart','can_delete_source':False}
        if result_first: plan.update(early_round_evidence=early,confirmed_idle_ranges=excluded)
        write_json(plan_path,plan)
    print('SMART_PROGRESS: 30',flush=True)
    decode_cuda,decode_threads=cuda,None
    if plan.get('strategy') in ['evidence-v3','focused-v5','focused-v6']:
        from adaptive_evidence import decode_policy
        decode_cuda,decode_threads,plan['decode_strategy']=decode_policy(video,cuda)
        if decode_threads: print('低GPU档：4线程CPU提取细查画面，GPU按低占用节奏识别',flush=True)
    selected=sum(b-a+1 for a,b in plan['frame_ranges'])
    print(f'智能计划：粗查 {plan["coarse_frames"]} 帧，二分 {plan["binary_probes"]} 次，局部细查 {selected}/{full_count} 帧',flush=True)
    if selected>full_count*.85:
        plan['fallback_reason']='活动或不确定区域过密，回退完整识别'; plan['frame_ranges']=[[1,full_count]]
    if not plan.get('need_full_fallback'):
        phase('fallback' if plan.get('fallback_reason') else 'fine',plan.get('fallback_reason') or '正在检查疑似交战区域……',30)
        timed('sampling',lambda:sample_with_resume(source,samples,fps,decode_cuda,frame_ranges=plan['frame_ranges'],**({'cpu_threads':decode_threads} if decode_threads else {})))
        print('SMART_PROGRESS: 55',flush=True)
        phase('fine','正在读取交战区域的弹药、伤害和击杀……',55)
        rows=timed('numeric',lambda:read_hud(samples,profile,fps,output,resume=True,source_identity=identity))
        phase('outcomes','正在确认这段交战的结束画面……',60)
        detail=timed('outcomes',lambda:enrich_outcomes(load(output),samples,checkpoint=output)); write_json(output,detail)
        phase('audit','正在核对累计伤害与击杀，检查是否需要补查……',62)
        rows=detail['rows']; audit=audit_counters(coarse,rows,duration,detail['outcome_events']); plan['counter_audit']=audit
        if not audit['passed']:
            plan['need_full_fallback']=True; write_json(plan_path,plan)
    if plan.get('need_full_fallback'):
        phase('fallback','计分核对不一致，正在完整补查……',62)
        print('伤害/击杀终值核对不一致，补查全部剩余区间',flush=True)
        if plan.get('strategy') in ['evidence-v3','focused-v5','focused-v6']:
            from evidence_completion import complete_missing
            saved,samples=complete_missing(source,job,samples,profile,fps,output,decode_cuda,cpu_threads=decode_threads)
            saved=enrich_outcomes(saved,samples,checkpoint=job/'gap-fill'/'audit.json')
            rows=saved['rows']; write_json(output,saved)
            plan['completion']=saved['evidence_completion']
            plan['audit_after_completion']=audit_counters(coarse,rows,duration,saved.get('outcome_events',[]))
            if not plan['audit_after_completion']['passed']:
                plan['counter_review_reason']='已检查全部采样帧，累计计分与事件归因仍不一致，需复核伤害/击杀统计'
                print(plan['counter_review_reason'],flush=True)
        else:
            # 已启动的旧任务保持原断点格式，避免升级时丢失全片补查进度。
            fallback=job/'full-fallback'
            sample_with_resume(source,fallback,fps,cuda)
            output_fallback=Path(output).with_name('hud-full-fallback.json')
            rows=read_hud(fallback,profile,fps,output_fallback,resume=True,source_identity=identity)
            write_json(output,load(output_fallback)); samples=fallback
        plan['fallback_reason']='计分核对失败，已补齐未识别区间' if plan.get('strategy') in ['evidence-v3','focused-v5','focused-v6'] else '计分核对失败，已完整补查'
    plan['fine_frames']=len(rows); plan['finished']=True; plan['timings_this_run']=timings; write_json(plan_path,plan)
    saved=load(output); saved['smart_plan']=plan; write_json(output,saved)
    if fingerprint(source)!=identity: raise ValueError('智能识别时源录像发生变化')
    return rows,Path(samples)
