"""交战边界之外的可选信息识别；同一实现支持原录像与已导出片段。"""
from pathlib import Path
from functools import lru_cache
from contextlib import nullcontext,contextmanager
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading

import cv2
from image_io import read_image
import numpy as np

from apex_clipper import BASE,fingerprint,probe,write_json,inactive_view,downed_score
from app_cancel import check_cancel,TaskStopped
from hud_layout import detect_images,VERSION as LAYOUT_VERSION
from player_names import player_name,consensus_name,canonical_name,name_key
from name_reader import NameReader,name_value
from japanese_name_reader import VERSION as NAME_VERSION
from native_frame_reader import native_frame_session,read_native_frames
from hud_recovery import persistent_job
from library_records import IMPORTED_FIELDS,VIDEO_EXTENSIONS

VERSION='optional-hud-v11'
FIELDS=['account','weapons','teammates','hero','rank']


@lru_cache(maxsize=8)
def visual_field_recipe(field,reader_versions):
    # 每个工作进程只摘要一次源码和小型运行资源，不加载模型或解码录像。
    modules=['rank_reader.py'] if field=='rank' else ['hero_reader.py','hero_portrait_reader.py']
    root=BASE/('assets/ranks' if field=='rank' else 'assets/legends')
    files=[BASE/name for name in modules]+sorted(file for file in root.rglob('*') if file.is_file() and file.suffix.lower() in {'.png','.json'})
    digest=hashlib.sha256(json.dumps(reader_versions).encode())
    for file in files:
        digest.update(str(file.relative_to(BASE)).replace('\\','/').encode());digest.update(b'\0')
        digest.update(hashlib.sha256(file.read_bytes()).digest())
    return digest.hexdigest()


def field_version(field):
    if field in {'account','teammates'}:return NAME_VERSION
    if field=='rank':
        from rank_reader import VERSION as RANK_VERSION
        return VERSION+':rank:'+RANK_VERSION+':'+visual_field_recipe(field,(RANK_VERSION,))
    if field=='hero':
        import hero_reader
        from hero_portrait_reader import VERSION as PORTRAIT_VERSION
        return VERSION+':hero:'+PORTRAIT_VERSION+':'+visual_field_recipe(field,(getattr(hero_reader,'VERSION',None),PORTRAIT_VERSION))
    return VERSION


def rank_detail_missing(rank):
    return bool(rank and rank.get('tier') not in {'rookie','master','predator','unranked'} and not rank.get('division'))


def field_unconfirmed(info,field):
    return info.get('field_status',{}).get(field)!='confirmed' or field=='rank' and rank_detail_missing(info.get('rank'))


def field_source_identity(info,field):
    """旧清单整组绑定来源；显式分字段记录不能借用较新的全局来源。"""
    if 'field_source_identities' in info:
        identities=info['field_source_identities']
        return identities.get(field) if isinstance(identities,dict) else None
    return info.get('source_identity')


def stable(observations,key):
    values=[row[key] for row in observations if row.get(key)]
    result=consensus_name(values,same_player=key in {'account','teammate'})
    if key in {'account','teammate'}:
        proved=[value for value in values if value.get('japanese_evidence',{}).get('glyphs')]
        physical=consensus_name(proved,same_player=True)
        if physical:result=physical
        elif result and proved:
            from japanese_name_reader import kana_family
            if any(kana_family(value['name'])==kana_family(result['name']) and value['name']!=result['name'] for value in proved):return None
    if not result:return None
    if key in {'account','teammate'} and any(value.get('glyph_review_pending') and name_key(value['name'])==name_key(result['name']) for value in values):return None
    if key=='rank':
        from collections import Counter
        divisions=Counter(value.get('division') for value in values if value.get('tier')==result.get('tier') and value.get('division'))
        result['division']=next(iter(divisions)) if len(divisions)==1 and next(iter(divisions.values()))>=2 else None
    result['method']='two_frame_'+key;return result


def native_frames(source,start,end,moments=None):
    yield from read_native_frames(source,moments if moments is not None else [start+(end-start)*f for f in [.15,.5,.85]])


def roi(image,profile,box):
    rw,rh=profile['reference_size'];x1,y1,x2,y2=box;h,w=image.shape[:2]
    return image[max(0,round(y1*h/rh)):min(h,round(y2*h/rh)),max(0,round(x1*w/rw)):min(w,round(x2*w/rw))]


@lru_cache(maxsize=8)
def voice_template(sx,sy):
    template=read_image(BASE/'templates/hud/voice.png',cv2.IMREAD_GRAYSCALE)
    if template is None:raise ValueError('缺少HUD语音图标模板')
    return cv2.resize(template,(max(1,round(template.shape[1]*sx)),max(1,round(template.shape[0]*sy))))


def name_patch(image,profile,bounds,*,left_padding=8):
    # 给首尾字符留边距，再用固定语音图标确定名字右边界，避免图标被读成数字/字母。
    sx,sy=profile.get('hud_scale',[1,1]);rw,rh=profile['reference_size'];h,w=image.shape[:2]
    bounds=[bounds[0]-round(left_padding*sx),bounds[1]-round(2*sy),bounds[2]+round(48*sx),bounds[3]+round(2*sy)]
    patch=roi(image,profile,bounds);matches=[]
    if patch.size:
        gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
        # 名称行图标可能小于计分区 HUD 的缩放，不能只用同一个图标尺寸。
        for factor in [.75,1.,1.25]:
            template=voice_template(round(sx*w/rw*factor,4),round(sy*h/rh*factor,4))
            if patch.shape[0]<template.shape[0] or patch.shape[1]<template.shape[1]:continue
            _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED))
            if score>=.83 and x>=round(25*sx*w/rw):matches.append((score,x,y,template.shape[0]))
        if matches:
            _,x,y,height=max(matches)
            patch=patch[max(0,y-2):min(patch.shape[0],y+height+2),:max(1,x-2)]
    return patch


def name_patch_quality(patch,*,text_right=None):
    """寻找能看到文字的画面；排除贴图边缘的大块亮色前景，不推测被盖住的字。"""
    if patch is None or not patch.size:return {'clear':False,'score':0.,'character_components':0,'blocking':[]}
    height,width=patch.shape[:2];hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
    mask=((hsv[:,:,1]<85)&(hsv[:,:,2]>=max(180,float(np.percentile(hsv[:,:,2],95))*.85))).astype(np.uint8)
    _,_,stats,_=cv2.connectedComponentsWithStats(mask);blocking=[];characters=0
    for x,y,w,h,area in stats[1:]:
        if (y+h>=height-1 or x+w>=width-1) and w>=h*1.2 and h>=height*.3 and area>=height*1.5:
            if text_right is None or min(x+w,text_right)-x>=max(3,height*.15):blocking.append([int(v) for v in [x,y,w,h,area]])
        elif height*.25<=h<=height*.9 and area>=3:characters+=1
    penalty=sum(box[-1] for box in blocking)/(height*width)
    return {'clear':not blocking and characters>=3,'score':characters/max(1,width)*height-penalty*100,'character_components':characters,'blocking':blocking}


def account_search_moments(observations,frame_times,start,end):
    visible=[row for row in observations if row.get('account')]
    if visible:
        seed=max(visible,key=lambda row:row['account'].get('confidence',0))['time']
        moments=[seed+delta for delta in [-2.4,-1.8,-1.2,-.6,.6,1.2,1.8,2.4]]
    else:moments=[start+(end-start)*fraction for fraction in [.05,.25,.35,.45,.55,.65,.75,.95]]
    return sorted({max(start,min(end-.04,second)) for second in moments if end-start>.04 and all(abs(max(start,min(end-.04,second))-seen)>.1 for seen in frame_times)})


def missing_visual_fields(fields,observations,weapons):
    missing=[field for field in ['hero','rank'] if field in fields and not stable(observations,field)]
    if 'weapons' in fields:
        ids={value['id'] for value in weapons}
        if not ids or any(len({value['time'] for value in weapons if value['id']==ident})<2 for ident in ids):missing.append('weapons')
    return missing


def adaptive_moments(observations,fields,teams,weapons,frame_times,start,end):
    # 每个未确认字段先分到一帧，不能让一个字段独占补读预算。
    seeds=[]
    for key in ['account','hero','rank']:
        if key in fields and not stable(observations,key):
            candidates=[row for row in observations if row.get(key)]
            if candidates:seeds.append(max(candidates,key=lambda row:(bool(key=='account' and (row[key].get('glyph_evidence') or row[key].get('japanese_evidence',{}).get('glyphs'))),row[key].get('confidence',0))))
            elif key=='hero':
                hints=[row for row in observations if row.get('hero_hint',0)>=.80]
                if hints:seeds.append(max(hints,key=lambda row:row['hero_hint']))
    if 'teammates' in fields:
        for slot,team in enumerate(teams):
            if stable(team,'teammate'):continue
            candidates=[row for row in observations if any(value.get('slot')==slot for value in row.get('teammates',[]))]
            if candidates:seeds.append(max(candidates,key=lambda row:max(((bool(value.get('glyph_evidence') or value.get('japanese_evidence',{}).get('glyphs')),value.get('confidence',0)) for value in row.get('teammates',[]) if value.get('slot')==slot),default=(False,0))))
    if 'weapons' in fields:
        for ident in dict.fromkeys(value['id'] for value in weapons):
            sightings=[value for value in weapons if value['id']==ident]
            if len({value['time'] for value in sightings})<2:
                strongest=max(sightings,key=lambda value:value['confidence'])
                seeds.append({'time':strongest['time']})
    fallback=sorted(observations,key=lambda row:len(row.get('weapon_ids',[]))*3+sum((row.get(key) or {}).get('confidence',0) for key in ['account','hero','rank'])+len(row.get('teammates',[])),reverse=True)
    seeds=seeds or fallback or [{'time':start+(end-start)*.15}]
    unique=list({row['time']:row for row in seeds}.values());times=[]
    for delta in [.4,-.4,.9]:
        for seed in unique:
            second=max(start,min(end-.04,seed['time']+delta))
            if second>=start and all(abs(second-time)>.1 for time in frame_times+times):times.append(second)
            if len(times)==3:return sorted(times)
    return sorted(times)


@native_frame_session()
def recognize_video(source,fields=None,start=0.,end=None,profile=None,on_activity=None):
    fields=list(dict.fromkeys(fields or FIELDS));source=Path(source)
    def notify(message,frames_done=0,frames_total=3):
        if on_activity:on_activity({'message':message,'fields':fields,'frames_done':frames_done,'frames_total':frames_total,'backend':os.environ.get('APEX_OCR_BACKEND','cpu')})
    notify('检查片段并读取 HUD 画面')
    before=fingerprint(source);meta,video=probe(source);end=min(float(meta['format']['duration']),end or float(meta['format']['duration']))
    frames=list(native_frames(source,start,end))
    if not frames:raise ValueError('片段中没有可读取的HUD画面')
    if profile and list(profile.get('reference_size',[]))!=[video['width'],video['height']]:profile=None
    if not profile:profile=detect_images([image for _,image in frames],video['width'],video['height'])
    notify('载入所选信息的识别模型',frames_total=len(frames))
    from weapon_reader import caption_views,recognize_text_views,MODEL_PATH,WeaponTextReader
    reader=None
    if set(fields)&{'account','weapons','teammates'}:
        from engine_pool import pooled_engine
        from gpu_ocr_backend import create_ocr_engine
        backend=os.environ.get('APEX_OCR_BACKEND','cpu')
        # 名字没有固定词表，长短混批的补白可能吞掉细笔画；每个视图独立保留比例。
        reader=pooled_engine(('optional-hud',VERSION,backend),lambda:create_ocr_engine(backend=backend,model_path=MODEL_PATH,rec_batch_num=1)).text_rec
    from rank_reader import RankReader
    rank_reader=RankReader() if 'rank' in fields else None
    from hero_reader import HeroReader
    hero_reader=HeroReader() if 'hero' in fields else None
    weapon_reader=WeaponTextReader(reader) if 'weapons' in fields else None
    name_reader=NameReader(reader) if set(fields)&{'account','teammates'} else None
    observations=[];weapons=[];teams=[[],[]];frame_times=[];field_times={field:[] for field in fields}
    shield=None;account_search=[];paired_account_times=set()
    def qualify_account(value,patch,quality,expected=None):
        old=[candidate['account']['name'] for candidate in observations if candidate.get('account') and candidate['account'].get('confidence',0)>=.85]
        truncated=any(len(name_key(name))-len(name_key(value['name']))>=3 and (name_key(name).startswith(name_key(value['name'])) or name_key(name).endswith(name_key(value['name']))) for name in old)
        proof=None
        if quality['clear'] and .85<=value.get('confidence',0)<.92:
            from name_reader import visible_latin_proof
            proof=visible_latin_proof(patch,value,reader)
        verified=bool(quality['clear'] and value.get('view_agreement',0)>=2 and (value.get('confidence',0)>=.92 or proof) and not truncated and not value.get('glyph_review_pending') and not value.get('japanese_review_pending') and (expected is None or value['name']==expected))
        value['name_visibility']={**quality,'verified':verified,'verified_name':value['name'] if verified else None,'truncated_candidate':truncated,**({'independent_reading':proof} if proof else {})}
    def own_view(image):
        nonlocal shield
        check_cancel()
        if inactive_view(image):
            # 同交战可能包含本人倒地后的队友观战；不能把观战对象当成本人。
            from outcome_reader import friend_view
            if friend_view(image,True):return False
            if shield is None:shield=read_image(str(BASE/profile['downed_marker']),0)
            if downed_score(image,profile,shield)<profile['downed_marker_threshold']:return False
        return True
    def inspect(second,image,*,account_quality=None,expected_account=None,selected_fields=None):
        if not start<=second<end:return
        selected=['account'] if account_quality is not None else fields if selected_fields is None else selected_fields
        selected=[field for field in selected if not any(abs(second-seen)<1e-6 for seen in field_times[field])]
        if not selected:return
        for field in selected:field_times[field].append(second)
        if not any(abs(second-seen)<1e-6 for seen in frame_times):frame_times.append(second)
        if not own_view(image):return
        row=next((row for row in observations if abs(row['time']-second)<1e-6),None)
        if row is None:
            row={'time':second,'teammates':[]};observations.append(row)
        crops=[];slots=[];gun_crops=[];gun_slots=[]
        regions=[]
        if 'account' in selected:regions.append(('account',profile['account_roi']))
        if 'teammates' in selected:regions.extend((f'team_{i}',box) for i,box in enumerate(profile['teammate_rois']))
        if 'weapons' in selected:regions.extend((f'weapon_{i}',box) for i,box in enumerate(profile['weapon_name_boxes']))
        for key,box in regions:
            patch=roi(image,profile,box) if key.startswith('weapon_') else name_patch(image,profile,box,left_padding=4 if key.startswith('team_') else 8)
            if patch.size:
                target=gun_crops if key.startswith('weapon_') else crops
                (gun_slots if key.startswith('weapon_') else slots).append((key,len(target)))
                if key.startswith('weapon_'):target.extend(caption_views(patch))
                else:target.append(patch)
        names=name_reader(crops) if crops else []
        for key,index in slots:
            value=names[index]
            if value:
                if key=='account':
                    if account_quality is not None:
                        qualify_account(value,crops[index],account_quality,expected_account)
                    row['account']=value
                else:
                    value['slot']=int(key[-1]);teams[value['slot']].append({'teammate':value});row['teammates'].append(value)
        gun_texts=weapon_reader(gun_crops)[0] if gun_crops else []
        if 'weapons' in selected:row['weapon_ids']=[]
        for key,index in gun_slots:
            label,match=recognize_text_views(gun_texts[index:index+2])
            if match:
                weapons.append({**match,'confidence':label['confidence'],'time':second});row['weapon_ids'].append(match['id'])
        if rank_reader and 'rank' in selected:row['rank']=rank_reader.inspect(image,profile)
        if hero_reader and 'hero' in selected:
            row['hero']=hero_reader.inspect(image,profile)
            scores=getattr(hero_reader,'last_scores',[])
            if isinstance(scores,list) and scores:row['hero_hint']=float(scores[0][1])
    def confirm_account_pair():
        seeds=[row for row in observations if row['time'] not in paired_account_times and row.get('account') and not row['account'].get('glyph_review_pending') and not row['account'].get('japanese_review_pending') and row['account'].get('view_agreement',0)>=2 and (row['account'].get('confidence',0)>=.92 or row['account'].get('name_visibility',{}).get('verified'))]
        if not seeds or profile.get('layout_status')!='confirmed':return
        seed=max(seeds,key=lambda row:(bool(row['account'].get('name_visibility',{}).get('verified')),row['account']['confidence']));expected=seed['account']['name']
        paired_account_times.add(seed['time'])
        for second,image in native_frames(source,start,end,[seed['time']]):
            if not own_view(image):return
            patch=name_patch(image,profile,profile['account_roi']);quality=name_patch_quality(patch)
            if not quality['clear'] and all(hasattr(reader,key) for key in ['session','resize_norm_img','rec_image_shape','postprocess_op']):
                from target_name_reader import ctc_tokens
                tokens=ctc_tokens(patch,reader)
                if tokens and player_name(''.join(token[0] for token in tokens))==expected:
                    quality=name_patch_quality(patch,text_right=min(patch.shape[1],tokens[-1][2]+patch.shape[0]*.15))
            if not quality['clear']:return
            qualify_account(seed['account'],patch,quality,expected)
        if not seed['account'].get('name_visibility',{}).get('verified'):return
        moments=[seed['time']+delta for delta in [-.04,.04] if start<=seed['time']+delta<end-.001]
        notify('相邻原生帧确认账号',len(frame_times),len(frame_times)+len(moments))
        for second,image in native_frames(source,start,end,moments):
            if not start<=second<end or not own_view(image):continue
            patch=name_patch(image,profile,profile['account_roi']);quality=name_patch_quality(patch)
            if not quality['clear'] and all(hasattr(reader,key) for key in ['session','resize_norm_img','rec_image_shape','postprocess_op']):
                from target_name_reader import ctc_tokens
                tokens=ctc_tokens(patch,reader)
                if tokens and player_name(''.join(token[0] for token in tokens))==expected:quality=name_patch_quality(patch,text_right=min(patch.shape[1],tokens[-1][2]+patch.shape[0]*.15))
            if not quality['clear']:continue
            account_search.append({'time':second,**quality,'selected':True,'sample_type':'adjacent_confirmation'})
            inspect(second,image,account_quality=quality,expected_account=expected)
            visible=[row for row in observations if row.get('account',{}).get('name_visibility',{}).get('verified')]
            if stable(visible,'account'):break
    for second,image in frames:
        inspect(second,image);notify('识别所选 HUD 信息',len(frame_times),len(frames))
    # 未确认才在已有清晰 HUD 附近补最多三帧，避免三个固定时刻都落在遮挡/换枪动画。
    uncertain=any(not stable(observations,f) for f in ['account','hero','rank'] if f in fields)
    uncertain=uncertain or ('teammates' in fields and any(not stable(team,'teammate') for team in teams))
    ids={w['id'] for w in weapons}
    uncertain=uncertain or ('weapons' in fields and (not ids or any(len({w['time'] for w in weapons if w['id']==ident})<2 for ident in ids)))
    if uncertain:
        times=adaptive_moments(observations,fields,teams,weapons,frame_times,start,end)
        planned=len(frame_times)+len(times);notify('复核未确认的信息',len(frame_times),planned)
        for second,image in native_frames(source,start,end,sorted(times)):
            inspect(second,image);notify('复核未确认的信息',len(frame_times),planned)
    # 原有时刻全落在倒地/切枪时，向未覆盖的时间段寻找实际图形；
    # 仅补读仍未确认的所选字段，遇到有效读数后用相邻原生帧确认。
    visual_search=[]
    if missing_visual_fields(fields,observations,weapons) and end-start>.08:
        moments=[start+(end-start)*fraction for fraction in [.05,.25,.35,.65,.75,.95]]
        moments=[second for second in moments if all(abs(second-seen)>.1 for seen in frame_times)]
        for second,image in native_frames(source,start,end,moments):
            pending=missing_visual_fields(fields,observations,weapons)
            if not pending:break
            notify('寻找未确认的技能、武器或段位',len(visual_search),len(moments))
            inspect(second,image,selected_fields=pending)
            visual_search.append({'time':second,'fields':pending})
            current=next((row for row in observations if abs(row['time']-second)<1e-6),{})
            visible=[field for field in pending if current.get(field) or field=='weapons' and current.get('weapon_ids')]
            if not visible:continue
            pair=[second+delta for delta in [-.04,.04] if start<=second+delta<end-.001]
            for adjacent,frame in native_frames(source,start,end,pair):
                pending=[field for field in visible if field in missing_visual_fields(fields,observations,weapons)]
                if not pending:break
                inspect(adjacent,frame,selected_fields=pending)
                visual_search.append({'time':adjacent,'fields':pending,'sample_type':'adjacent_confirmation'})
    if 'account' in fields and not stable(observations,'account'):
        confirm_account_pair()
    if 'account' in fields and not stable(observations,'account'):
        moments=account_search_moments(observations,field_times['account'],start,end);candidates=[]
        notify('寻找清晰账号画面',0,len(moments))
        for index,(second,image) in enumerate(native_frames(source,start,end,moments)):
            if own_view(image):
                quality=name_patch_quality(name_patch(image,profile,profile['account_roi']))
                account_search.append({'time':second,**quality,'selected':False})
                if quality['clear']:candidates.append((quality['score'],second,image,quality,account_search[-1]))
            notify('寻找清晰账号画面',index+1,len(moments))
        selected=0
        for _,second,image,quality,record in sorted(candidates,key=lambda item:(-item[0],item[1])):
            candidate_profile=detect_images([image],video['width'],video['height'])
            if candidate_profile.get('layout_status')!='confirmed':continue
            if any(abs(a-b)>8 for a,b in zip(candidate_profile['account_roi'],profile['account_roi'])):continue
            record['selected']=True;inspect(second,image,account_quality=quality);selected+=1
            notify('复核清晰账号画面',len(frame_times),len(frame_times)+3-selected)
            visible=[row for row in observations if row.get('account',{}).get('name_visibility',{}).get('verified')]
            if stable(visible,'account') or selected>=3:break
        notify('账号清晰度检查完成',len(frame_times),len(frame_times))
        visible=[row for row in observations if row.get('account',{}).get('name_visibility',{}).get('verified')]
        if not stable(visible,'account'):confirm_account_pair()
    names=[{k:v for k,v in row.items() if k in ['time','account','teammates']} for row in observations]
    result={'version':VERSION,'field_versions':{field:field_version(field) for field in fields},'source_identity':before,
        'field_source_identities':{field:dict(before) for field in fields},'profile_source_identity':dict(before),'requested_fields':fields,'profile':profile,
        'checked_frames':len(frame_times),'frame_times':frame_times,'account':None,'teammates':[],'name_observations':names,
        'hero':None,'weapons':[],'rank':None,'field_status':{}}
    if 'hero' in fields:result['hero_observations']=[{key:row[key] for key in ['time','hero','hero_hint'] if key in row} for row in observations]
    if account_search:result['account_visibility_search']=account_search
    if visual_search:result['visual_field_search']=visual_search
    for field in ['account','hero','rank']:
        if field in fields:result[field]=stable(observations,field)
    if 'rank' in fields:
        # 控制/混战等模式在段位位置显示的是时钟，本来就没有段位；多帧一致时
        # 明确记成「其他模式」，避免报告成「未识别段位」。
        clocks=[row['rank'] for row in observations if (row.get('rank') or {}).get('mode')=='other']
        if len(clocks)>=2 and not result['rank']:
            result['rank']={'tier':None,'name':'其他模式','division':None,'mode':'other',
                            'confidence':max(float(c.get('confidence') or 0) for c in clocks),
                            'method':'mode_clock_consensus','votes':len(clocks)}
    def detail_activity(details):notify(details['message'],details.get('frames_done',0),details.get('frames_total',0))
    if 'hero' in fields and not result['hero']:
        from hero_portrait_reader import confirm_video_portrait
        portrait=confirm_video_portrait(source,profile,start,end,on_activity=detail_activity)
        candidate=portrait['hero'];conflicts=[]
        if candidate:
            for ident in {row['hero']['id'] for row in observations if row.get('hero')}:
                times={row['time'] for row in observations if (row.get('hero') or {}).get('id')==ident}
                if ident!=candidate['id'] and len(times)>=2:conflicts.append(ident)
            if not conflicts:result['hero']=candidate
        result['hero_portrait_observations']=portrait['observations']
        if conflicts:result['hero_review_conflicts']=conflicts
        result['frame_times']=sorted(set(result['frame_times'])|{row['time'] for row in portrait['observations']});result['checked_frames']=len(result['frame_times'])
    if 'rank' in fields and rank_detail_missing(result['rank']) and (result['rank'] or {}).get('mode')!='other':
        result['rank']=rank_reader.confirm_division(source,profile,result['rank'],observations,start,end,on_activity=detail_activity)
        result['frame_times']=sorted(set(result['frame_times'])|{row['time'] for row in result['rank'].get('division_evidence',[])});result['checked_frames']=len(result['frame_times'])
    if 'rank' in fields:result['rank_observations']=[{'time':row['time'],'rank':row['rank']} for row in observations if 'rank' in row]
    if 'teammates' in fields:
        seen=set()
        for team in teams:
            value=stable(team,'teammate')
            if value and value['name'].casefold() not in seen:
                result['teammates'].append(value);seen.add(value['name'].casefold())
    if 'weapons' in fields:
        for key in dict.fromkeys(w['id'] for w in weapons):
            seen=[w for w in weapons if w['id']==key]
            if len({w['time'] for w in seen})>=2:result['weapons'].append(max(seen,key=lambda w:w['confidence']))
    for field in fields:result['field_status'][field]='confirmed' if result[field] else 'unknown'
    if fingerprint(source)!=before:raise ValueError('补充识别期间录像发生变化')
    return result


def recorded_match_keys(manifest,directory):
    """旧清单从对应分析中的对局结束事件恢复分组，不把整份录像当成同一局。"""
    try:analysis=json.loads((Path(directory)/'analysis.json').read_text('utf-8-sig'))
    except (OSError,ValueError):return {}
    if not isinstance(analysis,dict):return {}
    source=manifest.get('source')
    events=analysis.get('outcome_events');segments=analysis.get('segments')
    if not source or analysis.get('source')!=source or not isinstance(events,list) or not isinstance(segments,list):return {}
    if any(not isinstance(event,dict) or not isinstance(event.get('time'),(int,float)) for event in events):return {}
    bounds=[(segment.get('start'),segment.get('end')) for segment in segments if isinstance(segment,dict)]
    keys={}
    for clip in manifest.get('clips',[]):
        if clip.get('recognition',{}).get('match_key'):continue
        bound=clip.get('segment',{});left=bound.get('requested_start',bound.get('start'));right=bound.get('requested_end',bound.get('end'))
        if not all(isinstance(value,(int,float)) for value in [left,right,bound.get('start')]):continue
        if not any(isinstance(start,(int,float)) and isinstance(end,(int,float)) and abs(start-left)<.001 and abs(end-right)<.001 for start,end in bounds):continue
        round_index=sum(event['time']<=bound['start'] for event in events)
        keys[id(clip)]=hashlib.sha256((json.dumps(source,sort_keys=True)+':'+str(round_index)).encode()).hexdigest()[:16]
    return keys


def reconcile_manifest_names(manifest,fields=None,targets=None,*,updates=None,match_keys=None):
    """本人按原录像、队友按同一局的槽位确认；不跨局套用队友姓名。"""
    clips=manifest.get('clips',[]);accounts=[];teams={};match_keys=match_keys or {}
    fields=set(['account','teammates'] if fields is None else fields)
    if not fields&{'account','teammates'}:return
    identities={}
    def valid_source(clip,info,field):
        if info.get('field_status',{}).get(field)=='stale':return False
        if id(clip) not in identities:
            file=clip.get('output',clip.get('file'))
            try:identities[id(clip)]=fingerprint(Path(file)) if file else info.get('source_identity')
            except OSError:identities[id(clip)]=None
        actual=identities[id(clip)]
        return (actual is not None or not clip.get('output',clip.get('file'))) and field_source_identity(info,field)==actual
    for clip in clips:
        info=clip.get('recognition',{}).get('hud_info',{})
        if info.get('version')!=VERSION:continue
        key=clip.get('recognition',{}).get('match_key') or match_keys.get(id(clip)) or str(clip.get('output',clip.get('file','')))
        for row in info.get('name_observations',[]):
            versions=info.get('field_versions',{})
            if row.get('account') and valid_source(clip,info,'account') and versions.get('account',info.get('version'))==field_version('account'):accounts.append(row['account'])
            if valid_source(clip,info,'teammates') and versions.get('teammates',info.get('version'))==field_version('teammates'):
                for value in row.get('teammates',[]):teams.setdefault((key,value['slot']),[]).append(value)
    account=consensus_name(accounts,minimum=3,same_player=True)
    references={key:consensus_name(values,minimum=3,same_player=True) for key,values in teams.items()}
    for clip in clips if targets is None else targets:
        info=clip.get('recognition',{}).get('hud_info',{})
        if info.get('version')!=VERSION:continue
        writable=fields if updates is None else fields&updates.get(id(clip),set())
        if 'account' in writable and valid_source(clip,info,'account'):
            values=[canonical_name(row.get('account'),account,same_player=True) for row in info.get('name_observations',[])]
            info['account']=consensus_name(values,same_player=True) or canonical_name(info.get('account'),account,same_player=True)
            info.setdefault('field_status',{})['account']='confirmed' if info['account'] else 'unknown'
        key=clip.get('recognition',{}).get('match_key') or match_keys.get(id(clip)) or str(clip.get('output',clip.get('file','')))
        if 'teammates' in writable and valid_source(clip,info,'teammates'):
            raw={}
            for row in info.get('name_observations',[]):
                for value in row.get('teammates',[]):raw.setdefault(value['slot'],[]).append(value)
            known={v.get('slot'):v for v in info.get('teammates',[])};resolved=[]
            for slot in dict.fromkeys([*known,*raw]):
                reference=references.get((key,slot))
                value=consensus_name([canonical_name(v,reference,same_player=True) for v in raw.get(slot,[])],same_player=True) or canonical_name(known.get(slot),reference,same_player=True)
                if value:resolved.append(value)
            info['teammates']=resolved
            info.setdefault('field_status',{})['teammates']='confirmed' if resolved else 'unknown'


def merge_name_observations(previous,current,fields):
    """替换重读字段的观察证据，保留未选字段，避免旧姓名重新覆盖新结果。"""
    rows=[]
    for observations,fresh in [(previous,False),(current,True)]:
        for row in observations:
            names={key:row[key] for key in ['account','teammates']
                if row.get(key) and (key in fields)==fresh}
            if names:rows.append({'time':row.get('time'),**names})
    return rows


def invalidate_changed_fields(previous,identity):
    """媒体变化只使旧证据失效；不能让部分重读为未选字段换绑来源。"""
    known=set(previous.get('requested_fields',[]))|set(previous.get('field_status',{}))|set(previous.get('field_versions',{}))
    known.update(field for field in FIELDS if previous.get(field))
    stale=[field for field in FIELDS if field in known and field_source_identity(previous,field)!=identity]
    if not stale:return previous,[]
    info={**previous,'field_status':dict(previous.get('field_status',{})),
        'field_source_identities':{field:field_source_identity(previous,field) for field in FIELDS if field in known}}
    for field in stale:
        info[field]=[] if field in {'weapons','teammates'} else None
        info['field_status'][field]='stale'
    info['refreshed_fields']=list(dict.fromkeys(previous.get('refreshed_fields',[])+stale))
    info['name_observations']=merge_name_observations(previous.get('name_observations',[]),[],stale)
    if 'account' in stale:info.pop('account_visibility_search',None)
    if 'hero' in stale:
        for key in ['hero_observations','hero_portrait_observations','hero_review_conflicts']:info.pop(key,None)
    if 'rank' in stale:info.pop('rank_observations',None)
    if set(stale)&{'hero','weapons','rank'}:info.pop('visual_field_search',None)
    return info,stale


def _pending_visual_fields(recognition,previous,identity,fields,force):
    from hud_recovery import semantic_current
    versions=previous.get('field_versions') or {field:previous.get('version') for field in previous.get('requested_fields',[])}
    def outdated(field):
        current=semantic_current(recognition,field)
        return not current if current is not None else versions.get(field)!=field_version(field)
    return [field for field in fields if force or outdated(field) or field_source_identity(previous,field)!=identity or field not in previous.get('requested_fields',[]) or field_unconfirmed(previous,field)]


def _prepare_visual_clip(item,activity):
    clip,fields,force=item;file=Path(clip.get('output',clip.get('file','')))
    from hud_recovery import claim
    claim(file,fields)
    identity=fingerprint(file);previous,_=invalidate_changed_fields(clip.get('recognition',{}).get('hud_info',{}),identity)
    versions=previous.get('field_versions') or {field:previous.get('version') for field in previous.get('requested_fields',[])}
    pending=_pending_visual_fields(clip.get('recognition',{}),previous,identity,fields,force)
    if not pending:return None
    options={'on_activity':activity};frozen=previous.get('profile',{})
    from hud_recovery import profile_reusable
    if previous.get('profile_source_identity',previous.get('source_identity'))==identity and frozen.get('layout_version')==LAYOUT_VERSION and frozen.get('layout_status')=='confirmed' and profile_reusable(clip.get('recognition',{}),pending):options['profile']=frozen
    return recognize_video(file,pending,**options)


def _prepare_extra_clip(record,activity):
    from repair_cached_statistics import prepare_repair
    from hud_recovery import claim
    claim(record['files'][0],record['fields'])
    return prepare_repair(record,on_activity=activity)


def _mark_shared(info,identity,field,present):
    """登记复用来源：版本与指纹必须是本片段自己的，否则续接会判定来源不符重读。"""
    known=set(info.get('requested_fields',[]))|set(info.get('field_status',{}))|set(info.get('field_versions',{}))
    if 'field_source_identities' not in info:
        info['field_source_identities']={key:info.get('source_identity') for key in known}
    info['field_source_identities'][field]=dict(identity)
    info.setdefault('field_status',{})[field]='confirmed' if present else 'unknown'
    info.setdefault('field_versions',{})[field]=field_version(field)
    info['requested_fields']=list(dict.fromkeys(info.get('requested_fields',[])+[field]))


def _adopt_shared_field(info,identity,field,value):
    """把同局另一个片段的已确认结果写成本片段的确认结果。

    片段是独立文件，来源标识必须换成自己的指纹，否则续接时会判定来源不符而重读。
    空结果不标成确认：不同片段画面不同，某段读不到不代表整局都没有。
    """
    import copy
    info[field]=copy.deepcopy(value)
    _mark_shared(info,identity,field,bool(value))


def _self_confirmed(info,field,identity):
    """只认本片段自己读出来的确认值，借来的值不能再当投票。"""
    return (info.get('field_status',{}).get(field)=='confirmed' and bool(info.get(field))
            and field_source_identity(info,field)==identity
            and info.get('field_versions',{}).get(field)==field_version(field))


def _name_consensus(values,minimum=2):
    names=[value for value in values if isinstance(value,dict) and value.get('name')]
    if len(names)<minimum:return None
    if len({name_key(value['name']) for value in names})!=1:return None
    return consensus_name(names,minimum=minimum,same_player=True)


def _adopt_teammates(info,identity,resolved):
    """按槽位合并：只补齐缺失槽位，已有结果不覆盖。"""
    import copy
    existing={value.get('slot'):value for value in info.get('teammates',[]) if isinstance(value,dict)}
    for slot,value in resolved.items():existing.setdefault(slot,copy.deepcopy(value))
    info['teammates']=[existing[slot] for slot in sorted(existing,key=lambda slot:(slot is None,slot))]
    _mark_shared(info,identity,'teammates',bool(info['teammates']))


def _read_shared_fields(row,fields,activity=None):
    """就地读取指定字段并写回该片段，同时从待读列表里移除，避免同一片段重复读取。"""
    clip,identity,info,missing=row
    file=Path(clip.get('output',clip.get('file','')))
    try:current=recognize_video(file,list(fields),on_activity=activity)
    except Exception:return False
    if fingerprint(file)!=identity:raise ValueError('补充识别期间录像发生变化')
    for field in fields:
        value=current.get(field)
        if value:_adopt_shared_field(info,identity,field,value)
        else:info.setdefault('field_status',{})[field]='unknown'
        if field in missing:missing.remove(field)
    return True


def share_match_name_fields(manifest,selected,fields,force,write):
    """兼容入口：名字字段复用统一由 share_match_fields 处理。"""
    return share_match_fields(manifest,selected,fields,force,write)


def share_match_fields(manifest,selected,fields,force,write,activity=None):
    """同一局里不变的信息只识别一次：首段一次读完所有待补字段，其余片段沿用。

    hero 与 rank 每局不会变，直接复用。account 与 teammates 只有在同局至少两个片段
    独立读到同一个名字时才复用——跨局识别一旦漏检会把两局并成一局，名字复用会把错误
    放大；首轮先读两段攒票，所以同一次运行也能省。名字复用不复制 name_observations，
    事后仍由 reconcile_manifest_names 按全局证据收敛。force（手动重读）保持逐段识别。
    """
    wanted=[field for field in ('hero','rank','account','teammates') if field in fields]
    if force or not wanted:return 0
    groups={}
    for clip in selected:
        key=clip.get('recognition',{}).get('match_key')
        if key:groups.setdefault(key,[]).append(clip)
    shared=0
    for clips in groups.values():
        if len(clips)<2:continue
        rows=[]
        for clip in clips:
            file=Path(clip.get('output',clip.get('file','')))
            try:identity=fingerprint(file)
            except OSError:continue
            info=clip.setdefault('recognition',{}).setdefault('hud_info',{})
            missing=_pending_visual_fields(clip.get('recognition',{}),info,identity,wanted,False)
            rows.append((clip,identity,info,[field for field in wanted if field in missing]))
        if not rows:continue
        # 先让首段一次读完它缺的字段，避免每个字段各自重复读基础帧。
        if rows[0][3]:_read_shared_fields(rows[0],list(rows[0][3]),activity);write()
        for field in wanted:
            donors=[row for row in rows if _self_confirmed(row[2],field,row[1])]
            receivers=[row for row in rows if field in row[3]]
            if not receivers:continue
            if field in {'hero','rank'}:
                if not donors:continue
                value=donors[0][2][field]
                for row in receivers:
                    _adopt_shared_field(row[2],row[1],field,value);shared+=1
                    row[3].remove(field)
                write()
                continue
            # 名字需要两票；只有一票时继续读下一段凑票。
            voters=list(donors)
            queue=list(receivers)
            while len(voters)<2 and queue:
                row=queue.pop(0)
                _read_shared_fields(row,[field],activity)
                if _self_confirmed(row[2],field,row[1]):voters.append(row)
                if field not in row[3]:receivers.remove(row)
            if field=='account':
                value=_name_consensus([info['account'] for _,_,info,_ in voters])
                if value is not None:
                    for row in receivers:
                        _adopt_shared_field(row[2],row[1],'account',value);shared+=1
                        row[3].remove('account')
                    write()
                continue
            by_slot={}
            for _,_,info,_ in voters:
                for value in info.get('teammates',[]):
                    if isinstance(value,dict):by_slot.setdefault(value.get('slot'),[]).append(value)
            resolved={}
            for slot,values in by_slot.items():
                value=_name_consensus(values)
                if value is not None:resolved[slot]=value
            if resolved:
                for row in receivers:
                    _adopt_teammates(row[2],row[1],resolved);shared+=1
                    row[3].remove('teammates')
                write()
    return shared


def enrich_manifest(directory,files=None,fields=None,on_progress=None,*,force=False,on_activity=None):
    """只追加识别元数据，保持所有视频字节、名称与已冻结交战/计数不变。"""
    directory=Path(directory).resolve();path=directory/'export.json';manifest=json.loads(path.read_text('utf-8-sig'))
    fields=list(dict.fromkeys(fields or FIELDS))
    if manifest.get('metadata_directory') and Path(manifest['metadata_directory']).resolve()!=directory:raise ValueError('成片元数据目录不匹配')
    video_directory=Path(manifest.get('video_directory',directory)).resolve()
    wanted={str(Path(file).resolve()).casefold() for file in files} if files else None
    selected=[clip for clip in manifest['clips'] if not wanted or str(Path(clip.get('output',clip.get('file',''))).resolve()).casefold() in wanted]
    selected_paths={str(Path(clip.get('output',clip.get('file',''))).resolve()).casefold() for clip in selected}
    if wanted and selected_paths!=wanted:raise ValueError('所选视频不在对应导出清单中')
    recorded={str(Path(file).resolve()).casefold() for file in manifest.get('outputs',[])}
    # 用户整理过的成片（或登记的已有片段）由片段库确认后写入 relocated_outputs，可以不在原视频目录内。
    relocated={str(Path(file).resolve()).casefold() for file in manifest.get('relocated_outputs',[]) if isinstance(file,str)}
    if manifest.get('mode')=='imported' and set(fields)-set(IMPORTED_FIELDS):raise ValueError('已有片段只能补充画面中的 HUD 信息')
    for clip in selected:
        file=Path(clip.get('output',clip.get('file',''))).resolve()
        inside=file.is_relative_to(video_directory) or str(file).casefold() in relocated
        if not inside or file.suffix.lower() not in VIDEO_EXTENSIONS or str(file).casefold() not in recorded:raise ValueError('成片路径不属于对应导出目录')
    name_updates={}
    share_match_fields(manifest,selected,fields,force,lambda:write_json(path,manifest),on_activity)
    from hud_read_queue import ClipReadQueue
    workers=min(3,max(1,int(os.environ.get('APEX_HUD_WORKERS','1'))))
    queue=ClipReadQueue([(clip,fields,force) for clip in selected],_prepare_visual_clip,workers) if workers>1 or os.environ.get('APEX_ADAPTIVE_HUD')=='1' else nullcontext(None)
    with queue as prepared:
        for index,clip in enumerate(selected):
            check_cancel();file=Path(clip.get('output',clip.get('file','')))
            from hud_recovery import claim,stamp,committed
            claim(file,fields)
            def activity(details):
                if on_activity:on_activity({'type':'hud-info-activity','index':index+1,'total':len(selected),'file':str(file),**details})
            activity({'message':'检查已有识别结果','frames_done':0,'frames_total':0})
            identity=fingerprint(file)
            recognition=clip.setdefault('recognition',{});previous=recognition.get('hud_info',{})
            previous,stale=invalidate_changed_fields(previous,identity)
            if stale:
                recognition['hud_info']=previous
                # 即使新读取失败，也不能继续展示已确认属于旧视频的字段。
                from hud_recovery import active
                if not active():write_json(path,manifest)
            versions=previous.get('field_versions') or {field:previous.get('version') for field in previous.get('requested_fields',[])}
            pending=_pending_visual_fields(recognition,previous,identity,fields,force)
            if pending:
                options={'on_activity':activity} if on_activity else {}
                frozen=previous.get('profile',{})
                from hud_recovery import profile_reusable
                if previous.get('profile_source_identity',previous.get('source_identity'))==identity and frozen.get('layout_version')==LAYOUT_VERSION and frozen.get('layout_status')=='confirmed' and profile_reusable(recognition,pending):options['profile']=frozen
                detail_only=not force and 'rank' in pending and field_source_identity(previous,'rank')==identity and versions.get('rank')==field_version('rank') and previous.get('field_status',{}).get('rank')=='confirmed' and rank_detail_missing(previous.get('rank'))
                current=prepared.result(index,activity) if prepared else recognize_video(file,pending,**options)
                if fingerprint(file)!=identity or current.get('source_identity',identity)!=identity:raise ValueError('补充识别期间录像发生变化')
                if detail_only:
                    fresh=current.get('rank');saved=previous['rank']
                    current['rank']={**saved,'division':fresh['division'],**({'division_evidence':fresh['division_evidence']} if fresh.get('division_evidence') else {})} if fresh and fresh['tier']==saved['tier'] and fresh.get('division') else saved
                    current['field_status']['rank']='confirmed'
                info={**previous,**{field:current[field] for field in pending}}
                names=merge_name_observations(previous.get('name_observations',[]),current['name_observations'],pending)
                info.update(version=VERSION,source_identity=identity,profile=current['profile'],checked_frames=current['checked_frames'],
                    profile_source_identity=dict(identity),
                    name_observations=names,frame_times=current['frame_times'],
                    requested_fields=list(dict.fromkeys(previous.get('requested_fields',[])+pending)),
                    field_status={**previous.get('field_status',{}),**current['field_status']})
                info['field_versions']={**versions,**{field:field_version(field) for field in pending}}
                known=set(previous.get('requested_fields',[]))|set(versions)
                info['field_source_identities']={**{field:field_source_identity(previous,field) for field in FIELDS if field in known},
                    **{field:dict(identity) for field in pending}}
                info.pop('name_calibration_signatures',None)
                if 'account' in pending:
                    if current.get('account_visibility_search'):info['account_visibility_search']=current['account_visibility_search']
                    else:info.pop('account_visibility_search',None)
                if set(pending)&{'hero','weapons','rank'}:
                    if current.get('visual_field_search'):info['visual_field_search']=current['visual_field_search']
                    else:info.pop('visual_field_search',None)
                if 'hero' in pending:
                    info['hero_observations']=current.get('hero_observations',[])
                    for key in ['hero_portrait_observations','hero_review_conflicts']:
                        if key in current:info[key]=current[key]
                        else:info.pop(key,None)
                if 'rank' in pending:info['rank_observations']=current.get('rank_observations',[])
                # 新算法的未知结果也须覆盖旧段位回退；当前版本的普通补缺仍保留原语义。
                authoritative=[field for field in pending if force or field in {'hero','rank'} and versions.get(field)!=field_version(field)]
                if authoritative:info['refreshed_fields']=list(dict.fromkeys(previous.get('refreshed_fields',[])+authoritative))
                name_updates[id(clip)]=set(pending)
                recognition['hud_info']=info
                clip['recognition']=stamp(recognition,pending)
                write_json(path,manifest)
            else:activity({'message':'所选信息已确认，跳过读取','frames_done':0,'frames_total':0})
            committed(file,fields,path,pending)
            if on_progress:on_progress(index+1,len(selected),str(file))
            if prepared:prepared.advance(index)
    # 手动重读只使用本次所选片段的姓名证据，旧片段不能把误识别带回来。
    reconcile_manifest_names({'clips':selected} if force else manifest,fields,targets=selected,updates=name_updates,match_keys=recorded_match_keys(manifest,directory))
    write_json(path,manifest)
    return manifest


def _child_python(backend):
    executable=Path(sys.executable).resolve()
    if backend=='cuda':
        for candidate in [BASE/'runtime/cuda/python.exe',BASE/'.cuda-venv/Scripts/python.exe']:
            if candidate.is_file():return str(candidate)
        raise RuntimeError('未找到 CUDA Python 环境，请选择自动或 CPU')
    if backend=='cpu':
        for candidate in [executable.parent.parent/'cpu'/executable.name,BASE/'.venv/Scripts/python.exe']:
            if candidate.is_file():return str(candidate)
    return str(executable)


def _finish_hud_child(process,*,cooperative=False):
    if cooperative and process.poll() is None:
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:pass
    if process.poll() is None:
        # Windows venv 的 python.exe 可能只是转发启动器；必须同时收尾其真实子进程。
        if os.name=='nt':
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                           timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
        else:process.kill()
    process.wait(timeout=10)


def _run_hud_child(request,on_progress=None,on_activity=None,*,allow_partial=False):
    """原生访问冲突无法用 try/except 捕获；子进程只读取成片并更新软件元数据。"""
    flags=['-B','-X','utf8','-X','faulthandler']
    if sys.pycache_prefix:flags.extend(['-X','pycache_prefix='+sys.pycache_prefix])
    process=subprocess.Popen([_child_python(request['backend']),*flags,str(BASE/'hud_enrichment.py'),'--stdin','--direct'],
        cwd=BASE,env={**os.environ,'PYTHONUTF8':'1','PYTHONFAULTHANDLER':'1'},
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    messages=queue.Queue();tail=[];done=None
    def read_lines():
        try:
            for line in process.stdout:messages.put(line)
        finally:messages.put(None)
    reader=threading.Thread(target=read_lines,daemon=True);reader.start()
    try:
        process.stdin.write(json.dumps(request,ensure_ascii=False));process.stdin.close()
        while True:
            check_cancel()
            try:line=messages.get(timeout=.2)
            except queue.Empty:continue
            if line is None:break
            tail.append(line.strip());tail=tail[-30:]
            try:event=json.loads(line)
            except (ValueError,TypeError):continue
            if event.get('type')=='hud-info-progress' and on_progress:
                on_progress(event['index'],event['total'],event['file'])
            elif event.get('type')=='hud-info-activity' and on_activity:on_activity(event)
            elif event.get('type')=='hud-info-checkpoint' and on_activity:on_activity({**event,'index':0,'total':0,'file':''})
            elif event.get('type')=='hud-info-done':done=event
        code=process.wait()
        if code==75:
            raise TaskStopped()
        if code!=0:
            raise RuntimeError(f'补充识别子进程退出（{code} / 0x{code & 0xffffffff:08X}）：'+'\n'.join(tail)[-1500:])
        if done is None:raise RuntimeError('补充识别没有返回完成记录')
        if done.get('errors') and not allow_partial:raise RuntimeError('; '.join(e['message'] for e in done['errors']))
        return done
    except TaskStopped:
        _finish_hud_child(process,cooperative=True)
        raise
    finally:
        _finish_hud_child(process)
        reader.join(timeout=2)
        for stream in [process.stdin,process.stdout]:stream.close()


def enrich_manifest_isolated(directory,files=None,fields=None,on_progress=None,on_log=None,*,force=False,on_activity=None,checkpoint=None):
    """GPU 原生崩溃只影响补充子进程；已有成片保留，并用独立 CPU 进程续接。"""
    directory=Path(directory).resolve()
    manifest=json.loads((directory/'export.json').read_text('utf-8-sig'))
    files=files or manifest.get('outputs',[])
    backend=os.environ.get('APEX_OCR_BACKEND','cpu')
    from performance_options import inherited_resources
    request={'jobs':[{'directory':str(directory),'files':[str(f) for f in files]}],
        'fields':fields or FIELDS,'backend':backend,'gpu_load':os.environ.get('APEX_GPU_LOAD','low'),'force':force,
        **inherited_resources(),**({'checkpoint':checkpoint} if checkpoint else {})}
    from app_cancel import TaskStopped
    try:_run_hud_child(request,on_progress,on_activity)
    except TaskStopped:raise
    except Exception as error:
        if backend=='cpu':raise
        message='GPU补充识别异常，已导出视频保留，改用CPU补齐：'+str(error)
        if on_log:on_log(message)
        else:print(message,flush=True)
        if on_activity:on_activity({'type':'hud-info-activity','index':0,'total':len(files),'file':'','message':'GPU 异常，改用 CPU 继续识别','backend':'cpu','frames_done':0,'frames_total':0})
        _run_hud_child({**request,'backend':'cpu'},on_progress,on_activity)
    return json.loads((directory/'export.json').read_text('utf-8-sig'))


@contextmanager
def hud_worker_settings():
    import cv2
    threads=cv2.getNumThreads()
    before={key:os.environ.get(key) for key in ['APEX_HUD_WORKERS','APEX_OCR_POOL','APEX_DECODE_THREADS','APEX_FRAME_CACHE_MB','APEX_OCR_BACKEND','APEX_GPU_LOAD','APEX_TASK_STOP_FILE','APEX_ADAPTIVE_HUD','APEX_SCHEDULE_PRESET']}
    try:yield
    finally:
        cv2.setNumThreads(threads)
        for key,value in before.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


@hud_worker_settings()
@native_frame_session()
@persistent_job
def run_jobs(request,direct=False,emit=None):
    emit=emit or (lambda event:print(json.dumps(event,ensure_ascii=False),flush=True))
    use_policy=bool(request.get('adaptive_schedule','performance_preset' in request))
    os.environ['APEX_ADAPTIVE_HUD']='1' if use_policy else '0'
    os.environ['APEX_SCHEDULE_PRESET']=request.get('schedule_preset',request.get('performance_preset','high'))
    # Settings are frozen in this dedicated process, never hot-swapped by UI IPC.
    from performance_options import apply_resources,worker_limit
    if 'performance_preset' in request:
        request={**request,**apply_resources(request)}
    elif 'decode_threads' in request or 'frame_cache_mb' in request:
        request={**request,**apply_resources({**request,'performance_preset':'custom'})}
    # Capture concurrency once in the controller. Older live controllers send
    # no cpu_workers, so their later children retain the serial behavior.
    use_policy=use_policy or os.environ.get('APEX_ADAPTIVE_HUD')=='1'
    limit=max(1,os.cpu_count() or 1) if use_policy else (2 if request.get('backend','cpu')=='cpu' else 3)
    if not direct:
        default=min(limit,max(1,(os.cpu_count() or 4)//4))
        wanted=request.get('cpu_workers',os.environ.get('APEX_HUD_WORKERS',default))
        request={**request,'cpu_workers':worker_limit(request.get('backend','cpu'),max(1,int(wanted)))}
    os.environ['APEX_HUD_WORKERS']=str(min(limit,max(1,int(request.get('cpu_workers',1)))))
    # Reuse the existing bounded engine pool for sequential extra-field reads,
    # while preserving an explicit diagnostic opt-out.
    os.environ.setdefault('APEX_OCR_POOL','1')
    os.environ['APEX_OCR_BACKEND']=request.get('backend','cpu')
    os.environ['APEX_GPU_LOAD']=request.get('gpu_load','low')
    if request.get('stop_file'):os.environ['APEX_TASK_STOP_FILE']=str(request['stop_file'])
    check_cancel()
    if not request['jobs']:return _run_job_sequence(request,direct,emit)
    # One isolated process owns the entire batch so model sessions survive
    # directory/stage boundaries. Checkpoints filter already committed fields
    # before a CPU fallback; native failures remain isolated from Electron.
    if not direct:
        progress=lambda index,total,file:emit({'type':'hud-info-progress','index':index,'total':total,'file':file})
        fields=set(request.get('fields') or FIELDS)
        total=sum(len(job['files'])*(bool(set(job.get('fields',fields))&set(FIELDS))+bool(set(job.get('fields',fields))-set(FIELDS))) for job in request['jobs'])
        emit({'type':'hud-info-start','index':0,'total':total,'message':'准备读取所选信息'})
        try:
            result=_run_hud_child(request,progress,emit,allow_partial=True)
        except TaskStopped:raise
        except Exception:
            if request.get('backend','cpu')=='cpu':raise
            emit({'type':'hud-info-activity','index':0,'total':0,'file':'','message':'GPU 识别中断，保留已保存结果并用 CPU 继续','backend':'cpu'})
            result=_run_hud_child({**request,'backend':'cpu'},progress,emit,allow_partial=True)
        emit(result);return result
    from hud_batch import parallel_groups,run_batch
    if use_policy and parallel_groups(request):
        return run_batch(request,emit,lambda group,forward:_run_job_sequence(group,True,forward))
    return _run_job_sequence(request,direct,emit)


def _run_job_sequence(request,direct,emit):
    fields=list(dict.fromkeys(request.get('fields') or FIELDS))
    if any(field not in FIELDS+['statistics','opponents','event_weapons'] for field in fields):raise ValueError('识别字段无效')
    core=[field for field in fields if field in FIELDS];extra=[field for field in fields if field not in FIELDS]
    errors=[];updated=set();unconfirmed=set();offset=0
    total=sum(len(job['files'])*(bool(set(job.get('fields',fields))&set(FIELDS))+bool(set(job.get('fields',fields))-set(FIELDS))) for job in request['jobs'])
    emit({'type':'hud-info-start','index':0,'total':total,'message':'准备读取所选信息'})
    for job in request['jobs']:
        check_cancel()
        local_fields=job.get('fields',fields)
        core=[field for field in local_fields if field in FIELDS];extra=[field for field in local_fields if field not in FIELDS]
        count=len(job['files'])
        if core:
            try:
                enrich=enrich_manifest if direct else enrich_manifest_isolated
                result=enrich(job['directory'],job['files'],core,
                    lambda index,local_total,file:emit({'type':'hud-info-progress','index':offset+index,'total':total,'file':file}),
                    force=request.get('force',False),on_activity=lambda event:emit({**event,'index':offset+event['index'],'total':total}),
                    **({'checkpoint':request['checkpoint']} if not direct and request.get('checkpoint') else {}))
                updated.update(job['files']);wanted={str(Path(file).resolve()).casefold() for file in job['files']}
                for clip in result['clips']:
                    file=clip.get('output',clip.get('file',''))
                    if str(Path(file).resolve()).casefold() in wanted and any(field_unconfirmed(clip.get('recognition',{}).get('hud_info',{}),field) for field in core):unconfirmed.add(file)
            except Exception as error:
                from hud_recovery import failed
                for file in job['files']:failed(file,core,error)
                errors.append({'directory':job['directory'],'message':str(error)})
                emit({'type':'hud-info-error','index':offset,'total':total,'message':'HUD 信息尚未完成，继续下一项','failures':len(errors)})
            offset+=count
        if extra:
            errors_before=len(errors)
            try:
                if direct:
                    from repair_cached_statistics import repair,commit_repair,exported_clips,opponent_needs_review,needs_fields
                    directory=Path(job['directory']);statistics=directory/'statistics.json'
                    if not statistics.is_file():
                        # 导入的成片没有任务统计：把成片本身当源视频补片段级统计（不导出）。
                        # 同一目录常常有上百段，必须组内并行，否则只剩一条串行流。
                        from imported_statistics import build_statistics, apply_many
                        from concurrent.futures import ThreadPoolExecutor,as_completed
                        import threading
                        from hud_recovery import claim,commit_extra,failed as mark_failed
                        workers=min(6,max(1,int(os.environ.get('APEX_HUD_WORKERS','3'))))
                        emit_lock=threading.Lock();progress={'index':0};done={'value':0}
                        def report(file,event):
                            with emit_lock:
                                emit({'type':'hud-info-activity','index':offset+done['value'],'total':total,
                                      'file':file,'fields':extra,'backend':request.get('backend','cpu'),**event})
                        stored={}
                        def stored_profile(file):
                            key=str(directory)
                            if key not in stored:
                                try:
                                    data=json.loads((directory/'export.json').read_text('utf-8-sig'))
                                    stored[key]={str(Path(row.get('output','')).resolve()).casefold():
                                                 ((row.get('recognition') or {}).get('hud_info') or {}).get('profile')
                                                 for row in data.get('clips',[]) if row.get('output')}
                                except (OSError,ValueError):
                                    stored[key]={}
                            return stored[key].get(str(Path(file).resolve()).casefold())
                        def build(file):
                            check_cancel();claim(file,extra)
                            report(file,{'message':'采样成片并读取计分栏','frames_done':0,'frames_total':0})
                            return build_statistics(file,profile=stored_profile(file),
                                                    on_activity=lambda event:report(file,event))
                        results={}
                        from engine_pool import init_worker_pool
                        with ThreadPoolExecutor(max_workers=workers,initializer=init_worker_pool,thread_name_prefix='imported-stat') as pool:
                            futures={pool.submit(build,file):file for file in job['files']}
                            for future in as_completed(futures):
                                file=futures[future]
                                try:
                                    results[file]=future.result()
                                    updated.add(file);commit_extra(directory,file,extra,())
                                except Exception as error:
                                    mark_failed(file,extra,error)
                                    errors.append({'directory':str(directory),'message':Path(file).name+'：'+str(error)})
                                with emit_lock:
                                    done['value']+=1
                                    emit({'type':'hud-info-progress','index':offset+done['value'],'total':total,'file':file})
                        apply_many(directory/'export.json',results)
                        offset+=count
                        continue
                    original=json.loads(statistics.read_text('utf-8-sig'));clips=exported_clips(directory,original)
                    from hud_read_queue import ClipReadQueue
                    workers=min(3,max(1,int(os.environ.get('APEX_HUD_WORKERS','1'))))
                    bounds=[tuple(next((clip.get('segment',{}) for clip,identity in clips if identity['path'].casefold()==str(Path(file).resolve()).casefold()),{}).get(key) for key in ['start','end']) for file in job['files']]
                    if len(set(bounds))!=len(bounds):workers=1
                    records=[{'directory':str(directory),'files':[file],'fields':extra,'native':True,'force':request.get('force',False),'recheck_existing':request.get('force',False),'recheck_names':'opponents' in extra} for file in job['files']]
                    queue=ClipReadQueue(records,_prepare_extra_clip,workers) if workers>1 or os.environ.get('APEX_ADAPTIVE_HUD')=='1' else nullcontext(None)
                    with queue as prepared_extra:
                        for index,file in enumerate(job['files'],1):
                            check_cancel()
                            from hud_recovery import claim,commit_extra,failed,active as recovery_active
                            claim(file,extra)
                            def activity(event):emit({'type':'hud-info-activity','index':offset+index,'total':total,'file':file,'fields':extra,'backend':request.get('backend','cpu'),**event})
                            activity({'message':'读取成片原生画面，复核战果信息','frames_done':0,'frames_total':0})
                            try:
                                computed=()
                                if prepared_extra or recovery_active():
                                    item=prepared_extra.result(index-1,activity) if prepared_extra else _prepare_extra_clip(records[index-1],activity)
                                    result=commit_repair(item,on_activity=activity)
                                    computed=getattr(item,'computed_fields',())
                                else:result=repair(records[index-1],on_activity=activity)
                                updated.add(file)
                                if result:
                                    selected=next((clip for clip,identity in clips if identity['path'].casefold()==str(Path(file).resolve()).casefold()),None)
                                    bound=selected.get('segment',{}) if selected else {}
                                    fixed=next((segment for segment in result['segments'] if all(abs(segment[key]-bound.get(key,-1))<.001 for key in ['start','end'])),None)
                                    if fixed and (needs_fields(fixed,set(extra)) or 'statistics' in extra and request.get('force',False) and set(fixed.get('native_repaired_fields',[]))!={'kills','assists','damage'}):unconfirmed.add(file)
                                commit_extra(directory,file,extra,computed)
                            except Exception as error:
                                failed(file,extra,error)
                                errors.append({'directory':str(directory),'message':Path(file).name+'：'+str(error)})
                            emit({'type':'hud-info-progress','index':offset+index,'total':total,'file':file})
                            if prepared_extra:prepared_extra.advance(index-1)
                else:
                    payload={**request,'jobs':[job],'fields':extra}
                    progress=lambda index,local_total,file:emit({'type':'hud-info-progress','index':offset+index,'total':total,'file':file})
                    activity=lambda event:emit({**event,'index':offset+event['index'],'total':total})
                    try:result=_run_hud_child(payload,progress,activity,allow_partial=True)
                    except Exception:
                        if request.get('backend','cpu')=='cpu':raise
                        activity({'type':'hud-info-activity','index':0,'file':'','message':'GPU 复核中断，改用 CPU 继续','backend':'cpu'})
                        result=_run_hud_child({**payload,'backend':'cpu'},progress,activity,allow_partial=True)
                    updated.update(result.get('files_updated',[]));unconfirmed.update(result.get('unconfirmed_files',[]));errors.extend(result.get('errors',[]))
            except Exception as error:errors.append({'directory':job['directory'],'message':str(error)})
            if len(errors)>errors_before:emit({'type':'hud-info-error','index':offset,'total':total,'message':'部分战果信息需要重试','failures':len(errors)})
            offset+=count
    result={'type':'hud-info-done','updated':len(updated),'errors':errors,'unconfirmed':len(unconfirmed),'files_updated':sorted(updated),'unconfirmed_files':sorted(unconfirmed),'total':total}
    emit(result);return result


if __name__=='__main__':
    request=json.loads(sys.stdin.read() if '--stdin' in sys.argv else Path(sys.argv[1]).read_text('utf-8-sig'))
    from app_cancel import TaskStopped
    try:run_jobs(request,direct='--direct' in sys.argv)
    except TaskStopped:
        print(json.dumps({'type':'hud-info-stopped','message':'识别已停止，已读取的信息已保存'},ensure_ascii=False),flush=True)
        raise SystemExit(75)

