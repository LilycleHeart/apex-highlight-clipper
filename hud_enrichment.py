"""交战边界之外的可选信息识别；同一实现支持原录像与已导出片段。"""
from pathlib import Path
from functools import lru_cache
import hashlib
import json

import cv2
from image_io import read_image
import numpy as np

from apex_clipper import BASE,fingerprint,probe,write_json,inactive_view,downed_score
from app_cancel import check_cancel
from hud_layout import detect_images
from player_names import player_name,consensus_name,canonical_name,name_key

VERSION='optional-hud-v3'
FIELDS=['account','weapons','teammates','hero','rank']


def stable(observations,key):
    values=[row[key] for row in observations if row.get(key)]
    result=consensus_name(values)
    if not result:return None
    result['method']='two_frame_'+key;return result


def name_value(views):
    choices=[]
    for text,confidence in views:
        name=player_name(text)
        if confidence>=.80 and name:choices.append({'name':name,'confidence':float(confidence)})
    return max(choices,key=lambda row:row['confidence']) if choices else None


def native_frames(source,start,end,moments=None):
    import av
    with av.open(str(source)) as container:
        stream=container.streams.video[0];stream.codec_context.thread_count=1
        seen=set()
        for second in moments if moments is not None else [start+(end-start)*f for f in [.15,.5,.85]]:
            check_cancel()
            container.seek(int(second/stream.time_base),stream=stream,backward=True,any_frame=False)
            frame=next((f for f in container.decode(stream) if f.pts is not None and float(f.pts*f.time_base)>=second),None)
            if frame is None or frame.pts in seen:continue
            seen.add(frame.pts);yield float(frame.pts*frame.time_base),frame.to_ndarray(format='bgr24')


def roi(image,profile,box):
    rw,rh=profile['reference_size'];x1,y1,x2,y2=box;h,w=image.shape[:2]
    return image[max(0,round(y1*h/rh)):min(h,round(y2*h/rh)),max(0,round(x1*w/rw)):min(w,round(x2*w/rw))]


@lru_cache(maxsize=8)
def voice_template(sx,sy):
    template=read_image(BASE/'templates/hud/voice.png',cv2.IMREAD_GRAYSCALE)
    if template is None:raise ValueError('缺少HUD语音图标模板')
    return cv2.resize(template,(max(1,round(template.shape[1]*sx)),max(1,round(template.shape[0]*sy))))


def name_patch(image,profile,bounds):
    # 给首尾字符留边距，再用固定语音图标确定名字右边界，避免图标被读成数字/字母。
    sx,sy=profile.get('hud_scale',[1,1]);rw,rh=profile['reference_size'];h,w=image.shape[:2]
    bounds=[bounds[0]-round(4*sx),bounds[1],bounds[2]+round(40*sx),bounds[3]]
    patch=roi(image,profile,bounds);template=voice_template(round(sx*w/rw,4),round(sy*h/rh,4))
    if patch.shape[0]>=template.shape[0] and patch.shape[1]>=template.shape[1]:
        gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED))
        if score>=.83 and x>=round(25*sx*w/rw):
            patch=patch[max(0,y-2):min(patch.shape[0],y+template.shape[0]+2),:max(1,x-2)]
    return patch


def recognize_video(source,fields=None,start=0.,end=None,profile=None):
    fields=list(dict.fromkeys(fields or FIELDS));source=Path(source)
    before=fingerprint(source);meta,video=probe(source);end=min(float(meta['format']['duration']),end or float(meta['format']['duration']))
    frames=list(native_frames(source,start,end))
    if not frames:raise ValueError('片段中没有可读取的HUD画面')
    if not profile:profile=detect_images([image for _,image in frames],video['width'],video['height'])
    from weapon_reader import caption_views,recognize_text_views,MODEL_PATH,WeaponTextReader
    reader=None
    if set(fields)&{'account','weapons','teammates'}:
        import os
        from engine_pool import pooled_engine
        from gpu_ocr_backend import create_ocr_engine
        backend=os.environ.get('APEX_OCR_BACKEND','cpu')
        reader=pooled_engine(('optional-hud',backend),lambda:create_ocr_engine(backend=backend,model_path=MODEL_PATH)).text_rec
    from rank_reader import RankReader
    rank_reader=RankReader() if 'rank' in fields else None
    from hero_reader import HeroReader
    hero_reader=HeroReader() if 'hero' in fields else None
    weapon_reader=WeaponTextReader(reader) if 'weapons' in fields else None
    observations=[];weapons=[];teams=[[],[]];frame_times=[]
    shield=None
    def inspect(second,image):
        nonlocal shield
        frame_times.append(second)
        check_cancel()
        if inactive_view(image):
            # 同交战可能包含本人倒地后的队友观战；不能把观战对象当成本人。
            from outcome_reader import friend_view
            if friend_view(image,True):return
            if shield is None:shield=read_image(str(BASE/profile['downed_marker']),0)
            if downed_score(image,profile,shield)<profile['downed_marker_threshold']:return
        row={'time':second,'teammates':[]};crops=[];slots=[];gun_crops=[];gun_slots=[]
        regions=[]
        if 'account' in fields:regions.append(('account',profile['account_roi']))
        if 'teammates' in fields:regions.extend((f'team_{i}',box) for i,box in enumerate(profile['teammate_rois']))
        if 'weapons' in fields:regions.extend((f'weapon_{i}',box) for i,box in enumerate(profile['weapon_name_boxes']))
        for key,box in regions:
            patch=roi(image,profile,box) if key.startswith('weapon_') else name_patch(image,profile,box)
            if patch.size:
                target=gun_crops if key.startswith('weapon_') else crops
                (gun_slots if key.startswith('weapon_') else slots).append((key,len(target)))
                target.extend(caption_views(patch))
        texts=reader(crops)[0] if crops else []
        for key,index in slots:
            value=name_value(texts[index:index+2])
            if value:
                if key=='account':row['account']=value
                else:
                    value['slot']=int(key[-1]);teams[value['slot']].append({'teammate':value});row['teammates'].append(value)
        gun_texts=weapon_reader(gun_crops)[0] if gun_crops else []
        row['weapon_ids']=[]
        for key,index in gun_slots:
            label,match=recognize_text_views(gun_texts[index:index+2])
            if match:
                weapons.append({**match,'confidence':label['confidence'],'time':second});row['weapon_ids'].append(match['id'])
        if rank_reader:row['rank']=rank_reader.inspect(image,profile)
        if hero_reader:row['hero']=hero_reader.inspect(image,profile)
        observations.append(row)
    for second,image in frames:inspect(second,image)
    # 未确认才在已有清晰 HUD 附近补最多三帧，避免三个固定时刻都落在遮挡/换枪动画。
    uncertain=any(not stable(observations,f) for f in ['account','hero','rank'] if f in fields)
    uncertain=uncertain or ('teammates' in fields and any(not stable(team,'teammate') for team in teams))
    ids={w['id'] for w in weapons}
    uncertain=uncertain or ('weapons' in fields and (not ids or any(len({w['time'] for w in weapons if w['id']==ident})<2 for ident in ids)))
    if uncertain:
        seeds=sorted(observations,key=lambda r:len(r.get('weapon_ids',[]))*3+sum(r.get(k,{}).get('confidence',0) for k in ['account','hero','rank'])+len(r.get('teammates',[])),reverse=True)
        times=[]
        for seed in seeds or [{'time':start+(end-start)*.15}]:
            for delta in [.4,-.4,.9]:
                second=max(start,min(end-.04,seed['time']+delta))
                if second>=start and all(abs(second-t)>.1 for t in frame_times+times):times.append(second)
                if len(times)==3:break
            if len(times)==3:break
        for second,image in native_frames(source,start,end,sorted(times)):inspect(second,image)
    names=[{k:v for k,v in row.items() if k in ['time','account','teammates']} for row in observations]
    result={'version':VERSION,'source_identity':before,'requested_fields':fields,'profile':profile,
        'checked_frames':len(frame_times),'frame_times':frame_times,'account':None,'teammates':[],'name_observations':names,
        'hero':None,'weapons':[],'rank':None,'field_status':{}}
    for field in ['account','hero','rank']:
        if field in fields:result[field]=stable(observations,field)
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


def reconcile_manifest_names(manifest):
    """本人按原录像、队友按同一局的槽位确认；不跨局套用队友姓名。"""
    clips=manifest.get('clips',[]);accounts=[];teams={}
    for clip in clips:
        info=clip.get('recognition',{}).get('hud_info',{})
        if info.get('version')!=VERSION:continue
        key=clip.get('recognition',{}).get('match_key') or str(clip.get('output',clip.get('file','')))
        for row in info.get('name_observations',[]):
            if row.get('account'):accounts.append(row['account'])
            for value in row.get('teammates',[]):teams.setdefault((key,value['slot']),[]).append(value)
    account=consensus_name(accounts,minimum=3)
    references={key:consensus_name(values,minimum=3) for key,values in teams.items()}
    for clip in clips:
        info=clip.get('recognition',{}).get('hud_info',{})
        if info.get('version')!=VERSION:continue
        values=[canonical_name(row.get('account'),account) for row in info.get('name_observations',[])]
        info['account']=consensus_name(values) or canonical_name(info.get('account'),account)
        key=clip.get('recognition',{}).get('match_key') or str(clip.get('output',clip.get('file','')))
        for n,value in enumerate(info.get('teammates',[])):
            info['teammates'][n]=canonical_name(value,references.get((key,value.get('slot'))))


def enrich_manifest(directory,files=None,fields=None,on_progress=None):
    """只追加识别元数据，保持所有视频字节、名称与已冻结交战/计数不变。"""
    directory=Path(directory).resolve();path=directory/'export.json';manifest=json.loads(path.read_text('utf-8-sig'))
    if manifest.get('metadata_directory') and Path(manifest['metadata_directory']).resolve()!=directory:raise ValueError('成片元数据目录不匹配')
    video_directory=Path(manifest.get('video_directory',directory)).resolve()
    wanted={str(Path(file).resolve()).casefold() for file in files} if files else None
    selected=[clip for clip in manifest['clips'] if not wanted or str(Path(clip.get('output',clip.get('file',''))).resolve()).casefold() in wanted]
    selected_paths={str(Path(clip.get('output',clip.get('file',''))).resolve()).casefold() for clip in selected}
    if wanted and selected_paths!=wanted:raise ValueError('所选视频不在对应导出清单中')
    recorded={str(Path(file).resolve()).casefold() for file in manifest.get('outputs',[])}
    for clip in selected:
        file=Path(clip.get('output',clip.get('file',''))).resolve()
        if not file.is_relative_to(video_directory) or file.suffix.lower()!='.mp4' or str(file).casefold() not in recorded:raise ValueError('成片路径不属于对应导出目录')
    for index,clip in enumerate(selected):
        check_cancel();file=Path(clip.get('output',clip.get('file','')));identity=fingerprint(file)
        recognition=clip.setdefault('recognition',{});previous=recognition.get('hud_info',{})
        pending=[field for field in (fields or FIELDS) if previous.get('version')!=VERSION or previous.get('source_identity')!=identity or field not in previous.get('requested_fields',[]) or previous.get('field_status',{}).get(field)!='confirmed']
        if pending:
            current=recognize_video(file,pending)
            info={**previous,**{field:current[field] for field in pending}}
            names=current['name_observations'] if set(pending)&{'account','teammates'} else previous.get('name_observations',[])
            info.update(version=VERSION,source_identity=identity,profile=current['profile'],checked_frames=current['checked_frames'],
                name_observations=names,frame_times=current['frame_times'],
                requested_fields=list(dict.fromkeys(previous.get('requested_fields',[])+pending)),
                field_status={**previous.get('field_status',{}),**current['field_status']})
            recognition['hud_info']=info;write_json(path,manifest)
        if on_progress:on_progress(index+1,len(selected),str(file))
    reconcile_manifest_names(manifest);write_json(path,manifest)
    return manifest


if __name__=='__main__':
    import os,sys
    request=json.loads(Path(sys.argv[1]).read_text('utf-8-sig'))
    os.environ['APEX_OCR_BACKEND']=request.get('backend','cpu')
    os.environ['APEX_GPU_LOAD']=request.get('gpu_load','low')
    errors=[];done=0
    for job in request['jobs']:
        try:
            enrich_manifest(job['directory'],job['files'],request.get('fields'),
                lambda index,total,file:print(json.dumps({'type':'hud-info-progress','index':index,'total':total,'file':file}),flush=True))
            done+=len(job['files'])
        except Exception as error:errors.append({'directory':job['directory'],'message':str(error)})
    print(json.dumps({'type':'hud-info-done','updated':done,'errors':errors},ensure_ascii=False),flush=True)
