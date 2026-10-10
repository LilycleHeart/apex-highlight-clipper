"""已保留片段的独立战绩核对；HUD端点、完整提示去重、末队本人胜利结算补齐。"""
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import cv2

from apex_clipper import BASE,crop,counter_offset,numeric,write_json,fingerprint
from combat_outcome_reader import inspect_combat_outcomes,parse_result_line

VERSION='combat-statistics-v7'
ASSIST_BOX=[2202,94,2228,124]
FIELDS=('kills','assists','damage')

def target_key(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',text or '').upper() if c.isalnum())

def same_target(a,b):
    a,b=target_key(a),target_key(b)
    return bool(a and b and (a==b or min(len(a),len(b))>=4 and SequenceMatcher(None,a,b).ratio()>=.78))

def unique_toasts(events):
    """同一目标持续显示只算一次；助攻击倒/消灭属于同一助攻，不算两次。"""
    tracks=[]
    for raw in sorted(events,key=lambda e:e['time']):
        parsed=parse_result_line(raw.get('text','')) or {}
        event={**parsed,**raw};event['target_text']=parsed.get('target_text',raw.get('target_text',''))
        matched=None
        for track in reversed(tracks):
            gap=event['time']-track['last_seen']
            # 助攻击倒到消灭可能隔数秒；只合并同目标的这两种阶段，不合并复活后的再次击倒。
            assist_pair=(event['kind']=='assist' and event.get('action')=='elimination' and
                         track.get('action')=='knock' and gap<=25)
            a,b=track.get('prefix_box'),event.get('prefix_box')
            same_prefix=(a is not None and b is not None and abs(a[0]-b[0])<=8 and abs(a[1]-b[1])<=5 and
                         (not target_key(track.get('target_text')) or not target_key(event.get('target_text')) or
                          min(track.get('text_confidence',1),event.get('text_confidence',1))<.90))
            if track['kind']==event['kind'] and (gap<=3.0 or assist_pair) and (same_target(track.get('target_text'),event.get('target_text')) or gap<=3 and same_prefix):
                matched=track;break
        if matched:
            matched['last_seen']=event['time'];matched['frames']=sorted(set(matched['frames']+[event.get('frame','')]))
            matched['observations']+=1
            if event.get('confidence',0)>matched.get('confidence',0):
                for key in ['text','confidence']: matched[key]=event.get(key)
            if event.get('target_text') and not matched.get('target_text'):matched['target_text']=event['target_text']
            if event.get('action')=='elimination': matched['action']='elimination'
        else:
            tracks.append({**event,'last_seen':event['time'],'frames':[event.get('frame','')],'observations':1})
    for event in tracks:
        event['confirmed']=len([f for f in event['frames'] if f])>=2
    return tracks

def stable_value(rows,key):
    """端点必须由至少两张不同画面的高置信数值确认。"""
    votes=Counter(r[key] for r in rows if r.get(key) is not None)
    reliable={v for v,n in votes.items() if n>=2}
    return next((r[key] for r in reversed(rows) if r.get(key) in reliable),None)

def counter_endpoints(cache,samples,segments,profile,extra_samples=None,scan_fps=None,initial_samples=None):
    from experimental.in_memory_hud import numeric_recognizer
    from sample_locations import SampleResolver
    resolver=SampleResolver(cache,samples)
    rows=cache['rows'];chosen={};probes=[]
    eligible=[r for r in rows if not r.get('inactive_view') and not r.get('friend_spectate') and
              r.get('counter_marker_score',0)>=.78 and resolver.path(r['frame']).is_file()]
    for segment in segments:
        start,end=segment['start'],segment['end']
        before=[r for r in eligible if max(0,start-120)<=r['time']<=start]
        if not before: before=[r for r in eligible if start<r['time']<=start+2]
        after=[r for r in eligible if start<=r['time']<end]
        initial=[r for r in after if r['time']<=start+15][:5] if not before else []
        pair=(before[-5:],after[-5:],initial);probes.append(pair)
        for group in pair:
            for row in group: chosen[row['frame']]=row
    marker=cv2.imread(str(BASE/profile['counter_marker']),0);images=[];positions=[];recognized={}
    boxes={'kills':profile['kills'],'assists':ASSIST_BOX,'damage':profile['damage']}
    for row in chosen.values():
        image=cv2.imread(str(resolver.path(row['frame'])));delta,score=counter_offset(image,profile,marker)
        result={'frame':row['frame'],'time':row['time'],'marker_score':float(score)};recognized[row['frame']]=result
        if delta is None: continue
        dx,dy=delta
        for key,box in boxes.items():
            images.append(crop(image,[box[0]+dx,box[1]+dy,box[2]+dx,box[3]+dy],profile['reference_size']))
            positions.append((row['frame'],key))
    recognizer=numeric_recognizer();values=[]
    for i in range(0,len(images),24):
        from app_cancel import check_cancel
        check_cancel();batch,_=recognizer(images[i:i+24]);values.extend(batch)
    for (frame,key),(text,confidence) in zip(positions,values):
        recognized[frame][key]=numeric(text,float(confidence),20000 if key=='damage' else 99,.88)
    from stat_counter_fallback import CounterFallback
    fallback=CounterFallback();extra_views=[];extra_positions=[]
    for frame,result in recognized.items():
        missing=[key for key in FIELDS if result.get(key) is None]
        if not missing:continue
        image=cv2.imread(str(resolver.path(frame)));delta,_=counter_offset(image,profile,marker)
        if delta is None:continue
        patches=fallback.patches(image,profile,delta)
        for key in missing:
            patch=patches.get(key)
            if patch is not None:extra_views.append(patch);extra_positions.append((frame,key))
    extra_values=[]
    for i in range(0,len(extra_views),24):
        batch,_=recognizer(extra_views[i:i+24]);extra_values.extend(batch)
    for (frame,key),(text,confidence),view in zip(extra_positions,extra_values,extra_views):
        value=numeric(text,float(confidence),20000 if key=='damage' else 99,.90)
        if value is None:
            alias=fallback.decode_numeric_alias(text,view)
            if alias is not None:value=numeric(alias,fallback.last_match_score,20000 if key=='damage' else 99,.90)
        if value is not None:recognized[frame][key]=value;recognized[frame].setdefault('recovered_fields',[]).append(key)
    endpoints=[]
    for segment_index,(segment,(before,after,initial)) in enumerate(zip(segments,probes)):
        base_rows=[recognized[r['frame']] for r in before];end_rows=[recognized[r['frame']] for r in after]
        baseline={key:stable_value(base_rows,key) for key in FIELDS}
        hidden=[r for r in rows if segment['start']<=r['time']<min(segment['end'],segment['start']+5) and
                not r.get('inactive_view') and (r.get('counter_marker_score') or 0)<.78]
        prior_visible=any(r['time']<segment['start'] and r.get('counter_marker_score',0)>=.78 and
                          (r.get('kills') is not None or r.get('damage') is not None) for r in rows)
        # 本人计分栏在首次战果前尚未显现；半局起录但已有计分栏时绝不归零。
        hidden_count=len(hidden)
        if not prior_visible and hidden_count<2 and extra_samples is not None:
            from combat_outcome_reader import candidate_indices
            from apex_clipper import inactive_view
            rate=scan_fps or cache['fps']
            for index in candidate_indices({'start':segment['start'],'end':min(segment['end'],segment['start']+5)},rate)[:10]:
                path=Path(initial_samples or samples)/f'{index:06d}.jpg'
                if not path.is_file():path=Path(extra_samples)/f'candidate-{segment_index+1:03d}'/path.name
                if not path.is_file():continue
                image=cv2.imread(str(path));delta,_=counter_offset(image,profile,marker)
                if delta is None and not inactive_view(image):hidden_count+=1
                if hidden_count>=2:break
        from apex_clipper import stable_counter
        previous_damage=[value for index,value in stable_counter(rows,'damage').items() if rows[index]['time']<segment['start']]
        first_damage=stable_value([recognized[r['frame']] for r in initial],'damage')
        reset_evidence=(not before and hidden_count>=2 and previous_damage and first_damage is not None and first_damage<previous_damage[-1]-20)
        initial_zero=(not prior_visible or bool(reset_evidence)) and hidden_count>=2
        if initial_zero:
            baseline={key:0 if value is None else value for key,value in baseline.items()}
        last_values={key:stable_value(end_rows,key) for key in FIELDS}
        updates={}
        for key,value in last_values.items():
            last_change=None;last_seen_value=None
            for row in rows:
                if row['time']>=segment['end']:break
                if row.get('inactive_view') or row.get('friend_spectate') or row.get(key) is None:continue
                if row[key]!=last_seen_value:last_change=row['time'];last_seen_value=row[key]
            updates[key]=last_change if last_seen_value==value else None
        endpoints.append({'baseline':baseline,'last_hud':last_values,'last_hud_update':updates,
                          'baseline_frames':base_rows,'end_frames':end_rows,'initial_hidden_zero':initial_zero,'new_round_reset':bool(reset_evidence)})
    return endpoints

def parse_settlement(detections):
    """只读个人排位战斗明细的标签右侧第一数值，不把 RP 当击杀/助攻。"""
    rows=[]
    for points,text,confidence in detections or []:
        xs=[p[0] for p in points];ys=[p[1] for p in points]
        rows.append({'text':unicodedata.normalize('NFKC',text).replace(' ',''),'confidence':float(confidence),
                     'left':min(xs),'right':max(xs),'cy':sum(ys)/4,'height':max(ys)-min(ys)})
    clean=''.join(r['text'] for r in rows)
    if not ('RP' in clean.upper() and any(w in clean for w in ['總戰鬥','总战斗','總戰闘','總戰','战斗','戰鬥'])): return None
    result={}
    for key,pattern in [('kills',r'^([擊击][殺杀][數数]?|KILLS)$'),('assists',r'^(助攻|ASSISTS)$')]:
        labels=[r for r in rows if re.match(pattern,r['text'],re.I) and r['confidence']>=.70]
        for label in labels:
            nearby=sorted([r for r in rows if r['left']>label['right'] and abs(r['cy']-label['cy'])<=max(5,label['height']*.65)],key=lambda r:r['left'])
            if nearby and re.fullmatch(r'\d{1,2}',nearby[0]['text']) and nearby[0]['confidence']>=.88:
                result[key]=int(nearby[0]['text']);break
    return result if len(result)==2 else None

def last_team_settlement(cache,samples,segments):
    """只在本人获胜的最后交战之后检查少量结算帧，普通片段不做补充检测。"""
    if not segments:return None
    last=segments[-1]
    wins=[e for e in cache.get('outcome_events',[]) if e['kind']=='win' and last['start']<=e['time']<=last['end']+3]
    if not wins:return None
    win=wins[0]
    previous=[r for r in cache['rows'] if win['time']-5<=r['time']<win['time'] and not r.get('inactive_view') and
              not r.get('friend_spectate') and r.get('counter_marker_score',0)>=.78]
    if len(previous)<2:return None
    possible=[r for r in cache['rows'] if win['time']+5<=r['time']<=win['time']+30 and (Path(samples)/r['frame']).is_file()]
    if not possible:return None
    # 结算通常在冠军展示后出现；从末尾取三张间隔至少0.5秒的已有帧。
    selected=[]
    for row in reversed(possible):
        if not selected or selected[-1]['time']-row['time']>=.5:selected.append(row)
        if len(selected)==3:break
    from weapon_reader import new_engine
    engine=new_engine();observations=[]
    for row in selected:
        from app_cancel import check_cancel
        check_cancel();image=cv2.imread(str(Path(samples)/row['frame']));h,w=image.shape[:2]
        region=image[round(h*.463):round(h*.724),round(w*.1367):round(w*.3711)]
        detected,_=engine(cv2.resize(region,None,fx=2,fy=2),use_cls=False)
        values=parse_settlement(detected)
        observations.append({'time':row['time'],'frame':row['frame'],'values':values})
    consensus=Counter(tuple(sorted(o['values'].items())) for o in observations if o['values'])
    agreed=next((dict(values) for values,n in consensus.items() if n>=2),None)
    return {'scope':'self_last_team_win','win_time':win['time'],'totals':agreed,'observations':observations}

def terminal_toast_burst(cache,segment,settlement,checkpoint):
    """没录到结算时，仅末队结束前后约3秒加密到8Hz，捕捉被冠军动画覆盖的短提示。"""
    from resume_media import sample_with_resume
    from combat_outcome_reader import candidate_indices,ranges_from_indices
    win=settlement['win_time'];bounds={'start':max(segment['start'],win-3),'end':min(segment['end'],win+.25)}
    root=Path(checkpoint).parent/'statistics-terminal-8hz'
    sample_with_resume(Path(cache['source']['path']),root,8,False,frame_ranges=ranges_from_indices(candidate_indices(bounds,8)))
    # 本人末队胜利已由最近本人HUD与冠军提示确认；动画黑边不能误当观战。
    rows=[{'frame':f'{i:06d}.jpg','time':(i-.5)/8,'inactive_view':False,'friend_spectate':False} for i in candidate_indices(bounds,8)]
    burst={**cache,'fps':8,'rows':rows,'locale_reference_rows':cache['rows']}
    result=inspect_combat_outcomes(burst,root,[bounds],checkpoint=Path(checkpoint).with_name('terminal-toasts.json'),
                                  _stop_after_positive=False,_allow_upgrade=False,_only_existing=True)
    events=[{**e,'frame':'terminal-8hz/'+e['frame']} for e in result['decisions'][0]['events']]
    return {'events':events,'bounds':bounds,'fps':8,'stats':result['stats']}

def reconciled_counts(endpoint,events,coverage,settlement=None):
    baseline=endpoint['baseline'];end=dict(endpoint['last_hud']);settled=settlement and settlement.get('totals')
    if settled:end.update(settled)
    confirmed=[e for e in events if e['confirmed']];counts={};partial={};notes=[]
    for key,kind in [('kills','elimination'),('assists','assist'),('damage',None)]:
        b,v=baseline.get(key),end.get(key)
        if b is not None and v is not None and v>=b:
            counts[key]=v-b;partial[key]=bool(settlement and not settled) or bool(settlement and key=='damage')
        else:
            n=sum(e['kind']==kind for e in confirmed) if kind else 0
            counts[key]=n or None;partial[key]=True
            if b is not None and v is not None and v<b:notes.append(key+'计数发生回退，无法可靠分段归因')
    complete=(coverage['checked_frames']==coverage['expected_frames'] and not coverage['ambiguous_frames'] and
              coverage.get('calibrated_style_confirmed',False))
    knocks=sum(e['kind']=='knock' for e in confirmed)
    counts['knockdowns']=knocks if complete else knocks or None
    partial['knockdowns']=not complete or any(not e['confirmed'] for e in events if e['kind']=='knock')
    if settlement and not settled:
        last_update=endpoint.get('last_hud_update',{}).get('kills')
        extra=[e for e in confirmed if e['kind']=='elimination' and last_update is not None and e['time']>last_update+1]
        if counts['kills'] is not None:counts['kills']+=len(extra)
        else:counts['kills']=sum(e['kind']=='elimination' for e in confirmed) or None
        # 胜利后助攻击倒可能转为本人击杀；只统计已确认消灭的助攻，避免把上限冒充下限。
        assists=[e for e in confirmed if e['kind']=='assist' and e.get('action')=='elimination' and
                 not any(k['kind']=='elimination' and same_target(k.get('target_text'),e.get('target_text')) for k in confirmed)]
        counts['assists']=len(assists) or None
        partial['kills']=partial['assists']=True
    if settled:notes.append('末队本人胜利结算核对：击杀与助攻使用结算累计减本段基线')
    elif settlement:notes.append('末队 HUD 消失；结算未可靠确认，仅保留已读到的计数下限')
    return {'counts':counts,'partial':partial,'notes':notes,'endpoint':endpoint,'settlement_totals':settled}

def collect_statistics(cache,samples,segments,profile,checkpoint):
    """筛选完成后才调用。只补齐保留区间；断点和原数字缓存互不覆盖。"""
    checkpoint=Path(checkpoint);checkpoint.parent.mkdir(parents=True,exist_ok=True)
    from stat_counter_fallback import counter_recipe
    token=hashlib.sha256(json.dumps({'version':VERSION,'counter_recipe':counter_recipe(),'source':cache['source'],'fps':cache['fps'],
        'bounds':[(s['start'],s['end']) for s in segments],'outcomes':cache.get('outcome_events',[]),
        'profile':profile,'assist_box':ASSIST_BOX},sort_keys=True).encode()).hexdigest()
    if checkpoint.exists():
        previous=json.loads(checkpoint.read_text(encoding='utf-8'))
        if previous.get('signature')==token and previous.get('complete'):return previous
    # 计数和筛选使用不同记录，确保旧的“首正例停止”缓存不冒充整段统计。
    working=cache;scan_samples=Path(samples)
    if cache['fps']<2:
        from resume_media import sample_with_resume
        from combat_outcome_reader import candidate_indices,ranges_from_indices
        working={**cache,'fps':2,'rows':[],'locale_reference_rows':cache['rows']}
        scan_samples=checkpoint.parent/'statistics-2hz'
        sample_with_resume(Path(cache['source']['path']),scan_samples,2,False,
                           frame_ranges=ranges_from_indices(i for s in segments for i in candidate_indices(s,2)))
    report=inspect_combat_outcomes(working,scan_samples,segments,checkpoint=checkpoint.with_name('statistics-toasts.json'),
                                  _stop_after_positive=False,_allow_upgrade=False)
    extra=checkpoint.parent/('combat-outcome-samples-'+report['signature'][:12])
    endpoints=counter_endpoints(cache,samples,segments,profile,extra_samples=extra,scan_fps=working['fps'],initial_samples=scan_samples)
    settlement=last_team_settlement(cache,samples,segments);results=[];terminal=None
    if settlement and not settlement.get('totals'):
        terminal=terminal_toast_burst(cache,segments[-1],settlement,checkpoint)
    for i,(segment,decision,endpoint) in enumerate(zip(segments,report['decisions'],endpoints)):
        raw=list(decision['events'])
        if terminal and i==len(segments)-1:raw.extend(terminal['events'])
        events=unique_toasts(raw)
        correction=settlement if i==len(segments)-1 else None
        counts=reconciled_counts(endpoint,events,decision['coverage'],correction)
        results.append({'start':segment['start'],'end':segment['end'],**counts,'events':events,'coverage':decision['coverage']})
    result={'version':VERSION,'signature':token,'complete':True,'source':cache['source'],'segments':results,
            'last_team_settlement':settlement,'terminal_toast_burst':terminal,'scan_stats':report['stats']}
    if fingerprint(Path(cache['source']['path']))!=cache['source']:raise ValueError('核对战绩时原录像发生变化')
    write_json(checkpoint,result);return result

def overlay_summaries(summaries,aligned,statistics):
    if statistics is None:return summaries
    records=statistics['segments']
    if len(records)!=len(aligned) or any(abs(s['start']-r['start'])>.001 or abs(s['end']-r['end'])>.001 for s,r in zip(aligned,records)):
        raise ValueError('战绩统计与导出区间不匹配')
    for summary,record in zip(summaries,records):
        summary.update(record['counts'],statistics_version=statistics['version'],statistics_partial=record['partial'],
                       statistics_notes=record['notes'],statistics_basis='本段本人HUD端点增量，中心结果提示去重；仅末队本人胜利使用结算补齐')
    return summaries
