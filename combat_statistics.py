"""已保留片段的独立战绩核对；HUD端点、完整提示去重、末队本人胜利结算补齐。"""
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

import cv2
from image_io import read_image

from apex_clipper import BASE,crop,counter_offset,numeric,write_json,fingerprint
from combat_outcome_reader import inspect_combat_outcomes,parse_result_line,clean_target_name,PARSER_VERSION
from player_names import consensus_name

VERSION='combat-statistics-v15'
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
        event={**parsed,**raw};event['target_text']=clean_target_name(raw.get('target_text','')) if raw.get('target_method') else parsed.get('target_text',clean_target_name(raw.get('target_text','')))
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
            if event.get('target_method'):matched['target_method']=event['target_method']
            matched['last_seen']=event['time'];matched['frames']=sorted(set(matched['frames']+[event.get('frame','')]))
            matched['observations']+=1
            matched['_name_reads'].append({'name':event.get('target_text',''),'confidence':event.get('target_read_confidence',event.get('text_confidence',event.get('confidence',0))),'frame':event.get('frame','')})
            if event.get('confidence',0)>matched.get('confidence',0):
                for key in ['text','confidence']: matched[key]=event.get(key)
            if event.get('target_text') and not matched.get('target_text'):matched['target_text']=event['target_text']
            if event.get('action')=='elimination': matched['action']='elimination'
        else:
            tracks.append({**event,'last_seen':event['time'],'frames':[event.get('frame','')],'observations':1,
                '_name_reads':[{'name':event.get('target_text',''),'confidence':event.get('target_read_confidence',event.get('text_confidence',event.get('confidence',0))),'frame':event.get('frame','')}]})
    for event in tracks:
        # 击倒提示通常只显示半秒，2Hz 采样可能只抓到一帧；目标名复核时已经按原生帧
        # 读过同一提示，这些帧同样能证明提示确实持续出现，一并计入确认。
        native_frames={value.get('frame') for value in (event.get('native_action_evidence') or [])
                       if isinstance(value,dict) and value.get('frame')}
        votes=len([f for f in event['frames'] if f])+len(native_frames)
        # 纯「击倒 +150」没有目标名，也不产生原生动作帧，而游戏里只闪约半秒，
        # 2Hz 采样常常只抓到一帧。这类明确动作词用单帧高置信度补确认，并留下标记。
        single=votes<2 and event.get('kind') in {'knock','elimination'} and max(
            float(event.get('confidence') or 0),float(event.get('text_confidence') or 0))>=.9
        event['confirmed']=votes>=2 or single
        if single:event['single_frame_confirmed']=True
        reads={}
        for value in event.pop('_name_reads'):
            frame=value['frame']
            if frame and (frame not in reads or value['confidence']>reads[frame]['confidence']):reads[frame]=value
        name=consensus_name(list(reads.values()))
        event['target_text']=name['name'] if name else ''
        event['target_confidence']=name['confidence'] if name else 0.
        if event.get('target_method'):
            event['target_method']='two_frame_name_consensus';event['text_confidence']=event['target_confidence']
    return tracks

def stable_value(rows,key):
    """端点必须由至少两张不同画面的高置信数值确认。"""
    unique={r.get('native_time',r.get('frame',index)):r for index,r in enumerate(rows)}
    votes=Counter(r[key] for r in unique.values() if r.get(key) is not None)
    reliable={v for v,n in votes.items() if n>=2}
    return next((r[key] for r in reversed(rows) if r.get(key) in reliable),None)


def final_counter_reader():
    import os
    from engine_pool import pooled_engine
    from numeric_reader import NumericReader
    from ocr_cache import ExactTextCache
    backend=os.environ.get('APEX_OCR_BACKEND','cpu')
    return pooled_engine(('final-counters-exact-v2',backend),lambda:ExactTextCache(NumericReader(backend)))

def counter_endpoints(cache,samples,segments,profile,extra_samples=None,scan_fps=None,initial_samples=None):
    from sample_locations import SampleResolver
    resolver=SampleResolver(cache,samples)
    source=Path(cache['source']['path']);native=source.is_file()
    if native and fingerprint(source)!=cache['source']:raise ValueError('原录像发生变化，不能复核战绩端点')
    if cache.get('profile',{}).get('layout_version'):profile=cache['profile']
    if native:
        from hud_enrichment import native_frames
    def frame_image(row):
        if native:
            frame=next(native_frames(source,0,row['time']+1,[row['time']]),None)
            if frame is not None and 0<=frame[0]-row['time']<.15:
                second,image=frame
                from apex_clipper import inactive_view
                from outcome_reader import spectator_view
                if spectator_view(image,inactive_view(image)):return None,{'native_verified':False,'excluded_view':True}
                return image,{'native_verified':True,'native_time':second,'image_size':[image.shape[1],image.shape[0]]}
            return None,{'native_verified':False,'native_read_missing':True}
        image=read_image(str(resolver.path(row['frame'])))
        return image,{'native_verified':False}
    rows=cache['rows'];chosen={};probes=[]
    eligible=[r for r in rows if not r.get('inactive_view') and not r.get('friend_spectate') and
              r.get('counter_marker_score',0)>=.78 and (native or resolver.path(r['frame']).is_file())]
    for segment in segments:
        start,end=segment['start'],segment['end']
        before=[r for r in eligible if max(0,start-120)<=r['time']<=start]
        if not before: before=[r for r in eligible if start<r['time']<=start+2]
        after=[r for r in eligible if start<=r['time']<end]
        initial=[r for r in after if r['time']<=start+15][:5] if not before else []
        pair=(before[-5:],after[-5:],initial);probes.append(pair)
        for group in pair:
            for row in group: chosen[row['frame']]=row
    from stat_counter_fallback import CounterFallback,counter_box,digit_view
    fallback=CounterFallback();fallback_views={}
    marker=read_image(str(BASE/profile['counter_marker']),0);images=[];positions=[];recognized={}
    boxes={'kills':profile['kills'],'assists':profile.get('assists',ASSIST_BOX),'damage':counter_box(profile,'damage')}
    for row in chosen.values():
        image,provenance=frame_image(row)
        result={'frame':row['frame'],'time':row['time'],**provenance};recognized[row['frame']]=result
        if image is None:continue
        delta,score=counter_offset(image,profile,marker);result['marker_score']=float(score)
        if delta is None: continue
        regions=fallback.regions(image,profile,delta)
        fallback_views[row['frame']]={key:digit_view(region) for key,region in regions.items()}
        for key,box in boxes.items():
            if key not in regions:continue
            images.append(cv2.resize(regions[key],None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC))
            positions.append((row['frame'],key))
    recognizer=final_counter_reader();values=[]
    for i in range(0,len(images),24):
        from app_cancel import check_cancel
        check_cancel();batch,_=recognizer(images[i:i+24]);values.extend(batch)
    for (frame,key),(text,confidence) in zip(positions,values):
        recognized[frame][key]=numeric(text,float(confidence),20000 if key=='damage' else 99,.88)
    extra_views=[];extra_positions=[]
    for frame,result in recognized.items():
        missing=[key for key in FIELDS if result.get(key) is None]
        if not missing:continue
        patches=fallback_views.get(frame,{})
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
    # 尾端刚增加的伤害可能只有一张固定采样；在其附近补最多两帧，不能退回较早的多数值冒充最终数。
    if native:
        for segment,(_,after,_) in zip(segments,probes):
            if not after:continue
            last=after[-1];latest=recognized[last['frame']]
            pending=[key for key in FIELDS if latest.get(key) is not None and latest[key]!=stable_value([recognized[row['frame']] for row in after],key)]
            extra_times=[last['time']+min(.08,(segment['end']-last['time'])/2),last['time']-.06]
            for second in extra_times if pending else []:
                if second<segment['start'] or any(abs(row['time']-second)<.04 for row in after):continue
                row={'frame':f'native:counter:{second:.5f}','time':second}
                image,provenance=frame_image(row)
                if image is None:continue
                if provenance['native_time']>=segment['end']:continue
                delta,score=counter_offset(image,profile,marker)
                if delta is None:continue
                result={**row,**provenance,'marker_score':float(score)}
                regions=fallback.regions(image,profile,delta);keys=[key for key in boxes if key in regions]
                for key,(text,confidence) in zip(keys,recognizer([cv2.resize(regions[key],None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC) for key in keys])[0]):result[key]=numeric(text,float(confidence),20000 if key=='damage' else 99,.88)
                recognized[row['frame']]=result;after.append(row);after.sort(key=lambda value:value['time'])
                if all(latest.get(key)==stable_value([recognized[value['frame']] for value in after],key) for key in pending):break
    if native:
        from stat_counter_fallback import without_counter_divider
        # 仅在伤害端点尚未确认时复读现有原生帧，不能改变已有双帧确认值。
        for before,after,_ in probes:
            for group in [before,after]:
                if stable_value([recognized[row['frame']] for row in group],'damage') is not None:continue
                missing=[row for row in group if recognized[row['frame']].get('native_verified') is True and recognized[row['frame']].get('damage') is None and recognized[row['frame']].get('marker_score',0)>=.78]
                for row in missing[:3]:
                    image,_=frame_image(row)
                    if image is None:continue
                    delta,_=counter_offset(image,profile,marker)
                    if delta is None:continue
                    region=fallback.regions(image,profile,delta).get('damage')
                    clean=without_counter_divider(cv2.resize(region,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)) if region is not None else None
                    if clean is None:continue
                    (text,confidence)=recognizer([clean])[0][0]
                    value=numeric(text,float(confidence),20000,.88)
                    if value is not None:
                        recognized[row['frame']]['damage']=value
                        recognized[row['frame']].setdefault('recovered_fields',[]).append('damage_divider')
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
                image=read_image(str(path));delta,_=counter_offset(image,profile,marker)
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
        unconfirmed_latest={key:next((row[key] for row in reversed(end_rows) if row.get(key) is not None),None) for key in FIELDS}
        unconfirmed_latest={key:value for key,value in unconfirmed_latest.items() if value is not None and value!=last_values[key]}
        updates={}
        for key,value in last_values.items():
            last_change=None;last_seen_value=None
            for row in rows:
                if row['time']>=segment['end']:break
                if row.get('inactive_view') or row.get('friend_spectate') or row.get(key) is None:continue
                if row[key]!=last_seen_value:last_change=row['time'];last_seen_value=row[key]
            updates[key]=last_change if last_seen_value==value else None
        endpoints.append({'baseline':baseline,'last_hud':last_values,'last_hud_update':updates,
                          'baseline_frames':base_rows,'end_frames':end_rows,'unconfirmed_latest':unconfirmed_latest,'initial_hidden_zero':initial_zero,'new_round_reset':bool(reset_evidence)})
        if native:
            from outcome_reader import SELF_VIEW_VERSION
            from numeric_reader import METHOD
            endpoints[-1]['native_view_version']=SELF_VIEW_VERSION
            endpoints[-1]['native_numeric_method']=METHOD
    if native and fingerprint(source)!=cache['source']:raise ValueError('核对战绩端点期间原录像发生变化')
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
        check_cancel();image=read_image(str(Path(samples)/row['frame']));h,w=image.shape[:2]
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

def terminal_unreadable_fields(endpoint):
    """末帧没有读到的字段不能沿用较早数值充当完整片尾。兼容已有原生证据。"""
    rows=[row for row in endpoint.get('end_frames',[]) if isinstance(row.get('native_time',row.get('time')),(int,float)) and not isinstance(row.get('native_time',row.get('time')),bool) and math.isfinite(row.get('native_time',row.get('time')))]
    if not rows:return []
    latest=max(rows,key=lambda row:row.get('native_time',row.get('time')))
    return [key for key in FIELDS if endpoint.get('last_hud',{}).get(key) is not None and latest.get(key) is None]


def confirmed_assist_eliminations(events):
    """助攻下限只接受完整消灭阶段；原生待确认动作不能沿用旧聚合分类。"""
    completed=[]
    for event in events:
        if not event.get('confirmed') or event.get('ownership')!='self' or event.get('kind')!='assist':continue
        if 'native_action_status' in event:
            accepted=event['native_action_status']=='confirmed' and event.get('action')=='elimination'
        else:
            parsed=parse_result_line(event.get('text') or '') or {}
            accepted=parsed.get('kind')=='assist' and parsed.get('action')=='elimination'
        if accepted:completed.append(event)
    return completed


def complete_exported_counter_delta(endpoint,key):
    """现有成片的完整可见增量不受未录到的局后归因推测覆盖。"""
    if endpoint.get('native_counter_scope')!='exported_visible_delta' or endpoint.get('native_view_version')!='self-hud-view-v3':return False
    if endpoint.get('native_numeric_method') not in ['numeric-three-model-v3','numeric-three-model-v4']:return False
    if key not in endpoint.get('export_baseline_fields',[]) or key in endpoint.get('unconfirmed_latest',{}) or endpoint.get('excluded_terminal_view'):return False
    baseline=endpoint.get('baseline',{}).get(key);last=endpoint.get('last_hud',{}).get(key)
    if any(not isinstance(value,int) or isinstance(value,bool) or value<0 for value in [baseline,last]) or last<baseline:return False
    for group,value in [('baseline_frames',baseline),('end_frames',last)]:
        times={row['native_time'] for row in endpoint.get(group,[]) if row.get('native_verified') is True and not row.get('excluded_view') and isinstance(row.get('native_time'),(int,float)) and not isinstance(row['native_time'],bool) and math.isfinite(row['native_time']) and row.get(key)==value}
        if len(times)<2:return False
    rows=endpoint.get('end_frames',[])
    if any(row.get('excluded_view') for row in rows):return False
    timed=[row for row in rows if isinstance(row.get('native_time',row.get('time')),(int,float)) and not isinstance(row.get('native_time',row.get('time')),bool) and math.isfinite(row.get('native_time',row.get('time')))]
    if len(timed)!=len(rows):return False
    latest=max(timed,key=lambda row:row.get('native_time',row.get('time')))
    time=latest.get('native_time')
    return latest.get('native_verified') is True and isinstance(time,(int,float)) and not isinstance(time,bool) and math.isfinite(time) and latest.get(key)==last


def reconciled_counts(endpoint,events,coverage,settlement=None):
    baseline=endpoint['baseline'];end=dict(endpoint['last_hud']);settled=settlement and settlement.get('totals')
    if settled:end.update(settled)
    confirmed=[e for e in events if e.get('confirmed') is True and e.get('ownership')=='self'];assist_eliminations=confirmed_assist_eliminations(events);counts={};partial={};notes=[];hud_deltas={}
    visible_complete={key:complete_exported_counter_delta(endpoint,key) for key in FIELDS} if not settled else {}
    for key,kind in [('kills','elimination'),('assists','assist'),('damage',None)]:
        b,v=baseline.get(key),end.get(key)
        latest=endpoint.get('unconfirmed_latest',{}).get(key)
        if not settled and latest is not None and v is not None and latest<v:
            v=None;notes.append(key+'末端读数互相矛盾，不能作为计数下限')
        if b is not None and v is not None and v>=b:
            hud_deltas[key]=v-b
            counts[key]=v-b;partial[key]=bool(settlement and not settled) or bool(settlement and key=='damage') or not settled and (key in endpoint.get('unconfirmed_latest',{}) or key in terminal_unreadable_fields(endpoint) or bool(endpoint.get('excluded_terminal_view')))
            if visible_complete.get(key):partial[key]=False
        else:
            n=len(assist_eliminations) if key=='assists' else sum(e['kind']==kind for e in confirmed) if kind else 0
            counts[key]=n or None;partial[key]=True
            if b is not None and v is not None and v<b:notes.append(key+'计数发生回退，无法可靠分段归因')
        # 两种证据可能覆盖同一次战果；只提升下限，不能直接相加或覆盖完整 HUD。
        if kind and partial[key] and not settlement:
            center=len(assist_eliminations) if key=='assists' else sum(e['kind']==kind for e in confirmed)
            if center and (counts[key] is None or center>counts[key]):
                counts[key]=center;notes.append(('击杀' if key=='kills' else '助攻')+'由已确认本人中心提示补齐下限')
    complete=(coverage.get('expected_frames',0)>0 and coverage['checked_frames']==coverage['expected_frames'] and not coverage['ambiguous_frames'] and
              coverage.get('calibrated_style_confirmed',False) and coverage.get('reliable_absence',False) and not coverage.get('stopped_after_positive',False))
    knocks=sum(e['kind']=='knock' for e in confirmed)
    pending_knocks=any(not e['confirmed'] for e in events if e['kind']=='knock' and e.get('ownership')=='self')
    counts['knockdowns']=knocks if complete and not pending_knocks else knocks or None
    partial['knockdowns']=not complete or pending_knocks
    if settlement and not settled:
        if not visible_complete.get('kills'):
            last_update=endpoint.get('last_hud_update',{}).get('kills')
            extra=[e for e in confirmed if e['kind']=='elimination' and last_update is not None and e['time']>last_update+1]
            if 'kills' in hud_deltas:counts['kills']+=len(extra)
            else:counts['kills']=sum(e['kind']=='elimination' for e in confirmed) or None
            partial['kills']=True
        # 胜利后助攻击倒可能转为本人击杀；只统计已确认消灭的助攻，避免把上限冒充下限。
        if not visible_complete.get('assists'):
            assists=[e for e in assist_eliminations if
                     not any(k['kind']=='elimination' and k.get('ownership')=='self' and same_target(k.get('target_text'),e.get('target_text')) for k in confirmed)]
            counts['assists']=len(assists) or None
            partial['assists']=True
    if settled:notes.append('末队本人胜利结算核对：击杀与助攻使用结算累计减本段基线')
    elif settlement:notes.append('末队结算未可靠确认；完整复核的成片字段使用首尾可见增量，其余仅保留已确认下限')
    if endpoint.get('unconfirmed_latest') and not settled:notes.append('末端变化未获得双帧确认，相关计数仅为已确认下限')
    if terminal_unreadable_fields(endpoint) and not settled:notes.append('片尾计分栏未完整读取，较早已确认数值仅为下限')
    if endpoint.get('excluded_terminal_view') and not settled:notes.append('片尾包含观战画面；仅使用此前本人 HUD，计数保留为已确认下限')
    return {'counts':counts,'partial':partial,'notes':notes,'endpoint':endpoint,'settlement_totals':settled}

def collect_statistics(cache,samples,segments,profile,checkpoint):
    """筛选完成后才调用。只补齐保留区间；断点和原数字缓存互不覆盖。"""
    # 端点、末队结算与姓名复核逐个时刻读原生帧：共用一个解码器顺序续读，
    # 不再每个时刻重开容器从关键帧单线程重解；外层已有会话时沿用外层设置。
    from native_frame_reader import native_frame_session
    from performance_options import pipeline_decode_threads
    with native_frame_session(threads=pipeline_decode_threads()):
        return _collect_statistics(cache,samples,segments,profile,checkpoint)

def _collect_statistics(cache,samples,segments,profile,checkpoint):
    checkpoint=Path(checkpoint);checkpoint.parent.mkdir(parents=True,exist_ok=True)
    from stat_counter_fallback import counter_recipe
    token=hashlib.sha256(json.dumps({'version':VERSION,'counter_recipe':counter_recipe(),'source':cache['source'],'fps':cache['fps'],
        'toast_parser':PARSER_VERSION,
        'bounds':[(s['start'],s['end']) for s in segments],'outcomes':cache.get('outcome_events',[]),
        'profile':profile,'assist_box':profile.get('assists',ASSIST_BOX)},sort_keys=True).encode()).hexdigest()
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
        if events:
            from combat_outcome_reader import native_target_names
            print(f'原生战果姓名复核: {i+1}/{len(segments)} 段，{len(events)} 个结果',flush=True)
            events=native_target_names(Path(cache['source']['path']),events,hud_profile=profile)
        correction=settlement if i==len(segments)-1 else None
        counts=reconciled_counts(endpoint,events,decision['coverage'],correction)
        results.append({'start':segment['start'],'end':segment['end'],**counts,'events':events,'coverage':decision['coverage']})
    result={'version':VERSION,'parser_version':PARSER_VERSION,'signature':token,'complete':True,'source':cache['source'],'segments':results,
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
