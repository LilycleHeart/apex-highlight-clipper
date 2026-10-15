"""交战边界之外的可选信息识别；同一实现支持原录像与已导出片段。"""
from pathlib import Path
from functools import lru_cache
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
from app_cancel import check_cancel
from hud_layout import detect_images
from player_names import player_name,consensus_name,canonical_name,name_key

VERSION='optional-hud-v5'
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
    for value in choices:value['view_agreement']=sum(name_key(other['name'])==name_key(value['name']) for other in choices)
    return max(choices,key=lambda row:(row['view_agreement'],row['confidence'])) if choices else None


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
    bounds=[bounds[0]-round(8*sx),bounds[1]-round(2*sy),bounds[2]+round(48*sx),bounds[3]+round(2*sy)]
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


def recognize_video(source,fields=None,start=0.,end=None,profile=None,on_activity=None):
    fields=list(dict.fromkeys(fields or FIELDS));source=Path(source)
    def notify(message,frames_done=0,frames_total=3):
        if on_activity:on_activity({'message':message,'fields':fields,'frames_done':frames_done,'frames_total':frames_total,'backend':os.environ.get('APEX_OCR_BACKEND','cpu')})
    notify('检查片段并读取 HUD 画面')
    before=fingerprint(source);meta,video=probe(source);end=min(float(meta['format']['duration']),end or float(meta['format']['duration']))
    frames=list(native_frames(source,start,end))
    if not frames:raise ValueError('片段中没有可读取的HUD画面')
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
    for second,image in frames:
        inspect(second,image);notify('识别所选 HUD 信息',len(frame_times),len(frames))
    # 未确认才在已有清晰 HUD 附近补最多三帧，避免三个固定时刻都落在遮挡/换枪动画。
    uncertain=any(not stable(observations,f) for f in ['account','hero','rank'] if f in fields)
    uncertain=uncertain or ('teammates' in fields and any(not stable(team,'teammate') for team in teams))
    ids={w['id'] for w in weapons}
    uncertain=uncertain or ('weapons' in fields and (not ids or any(len({w['time'] for w in weapons if w['id']==ident})<2 for ident in ids)))
    if uncertain:
        seeds=sorted(observations,key=lambda r:len(r.get('weapon_ids',[]))*3+sum((r.get(k) or {}).get('confidence',0) for k in ['account','hero','rank'])+len(r.get('teammates',[])),reverse=True)
        times=[]
        for seed in seeds or [{'time':start+(end-start)*.15}]:
            for delta in [.4,-.4,.9]:
                second=max(start,min(end-.04,seed['time']+delta))
                if second>=start and all(abs(second-t)>.1 for t in frame_times+times):times.append(second)
                if len(times)==3:break
            if len(times)==3:break
        planned=len(frame_times)+len(times);notify('复核未确认的信息',len(frame_times),planned)
        for second,image in native_frames(source,start,end,sorted(times)):
            inspect(second,image);notify('复核未确认的信息',len(frame_times),planned)
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
    for clip in clips:
        info=clip.get('recognition',{}).get('hud_info',{})
        if info.get('version')!=VERSION:continue
        key=clip.get('recognition',{}).get('match_key') or match_keys.get(id(clip)) or str(clip.get('output',clip.get('file','')))
        for row in info.get('name_observations',[]):
            versions=info.get('field_versions',{})
            if row.get('account') and versions.get('account',info.get('version'))==VERSION:accounts.append(row['account'])
            if versions.get('teammates',info.get('version'))==VERSION:
                for value in row.get('teammates',[]):teams.setdefault((key,value['slot']),[]).append(value)
    account=consensus_name(accounts,minimum=3)
    references={key:consensus_name(values,minimum=3) for key,values in teams.items()}
    for clip in clips if targets is None else targets:
        info=clip.get('recognition',{}).get('hud_info',{})
        if info.get('version')!=VERSION:continue
        writable=fields if updates is None else fields&updates.get(id(clip),set())
        if 'account' in writable:
            values=[canonical_name(row.get('account'),account,same_player=True) for row in info.get('name_observations',[])]
            info['account']=consensus_name(values) or canonical_name(info.get('account'),account,same_player=True)
        key=clip.get('recognition',{}).get('match_key') or match_keys.get(id(clip)) or str(clip.get('output',clip.get('file','')))
        if 'teammates' in writable:
            raw={}
            for row in info.get('name_observations',[]):
                for value in row.get('teammates',[]):raw.setdefault(value['slot'],[]).append(value)
            known={v.get('slot'):v for v in info.get('teammates',[])};resolved=[]
            for slot in dict.fromkeys([*known,*raw]):
                reference=references.get((key,slot))
                value=consensus_name([canonical_name(v,reference,same_player=True) for v in raw.get(slot,[])]) or canonical_name(known.get(slot),reference,same_player=True)
                if value:resolved.append(value)
            info['teammates']=resolved


def merge_name_observations(previous,current,fields):
    """替换重读字段的观察证据，保留未选字段，避免旧姓名重新覆盖新结果。"""
    rows=[]
    for observations,fresh in [(previous,False),(current,True)]:
        for row in observations:
            names={key:row[key] for key in ['account','teammates']
                if row.get(key) and (key in fields)==fresh}
            if names:rows.append({'time':row.get('time'),**names})
    return rows


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
    for clip in selected:
        file=Path(clip.get('output',clip.get('file',''))).resolve()
        if not file.is_relative_to(video_directory) or file.suffix.lower()!='.mp4' or str(file).casefold() not in recorded:raise ValueError('成片路径不属于对应导出目录')
    name_updates={}
    for index,clip in enumerate(selected):
        check_cancel();file=Path(clip.get('output',clip.get('file','')))
        def activity(details):
            if on_activity:on_activity({'type':'hud-info-activity','index':index+1,'total':len(selected),'file':str(file),**details})
        activity({'message':'检查已有识别结果','frames_done':0,'frames_total':0})
        identity=fingerprint(file)
        recognition=clip.setdefault('recognition',{});previous=recognition.get('hud_info',{})
        versions=previous.get('field_versions') or {field:previous.get('version') for field in previous.get('requested_fields',[])}
        pending=[field for field in fields if force or versions.get(field)!=VERSION or previous.get('source_identity')!=identity or field not in previous.get('requested_fields',[]) or previous.get('field_status',{}).get(field)!='confirmed']
        if pending:
            current=recognize_video(file,pending,**({'on_activity':activity} if on_activity else {}))
            info={**previous,**{field:current[field] for field in pending}}
            names=merge_name_observations(previous.get('name_observations',[]),current['name_observations'],pending)
            info.update(version=VERSION,source_identity=identity,profile=current['profile'],checked_frames=current['checked_frames'],
                name_observations=names,frame_times=current['frame_times'],
                requested_fields=list(dict.fromkeys(previous.get('requested_fields',[])+pending)),
                field_status={**previous.get('field_status',{}),**current['field_status']})
            info['field_versions']={**versions,**{field:VERSION for field in pending}}
            if force:info['refreshed_fields']=list(dict.fromkeys(previous.get('refreshed_fields',[])+pending))
            name_updates[id(clip)]=set(pending)
            recognition['hud_info']=info;write_json(path,manifest)
        else:activity({'message':'所选信息已确认，跳过读取','frames_done':0,'frames_total':0})
        if on_progress:on_progress(index+1,len(selected),str(file))
    # 手动重读只使用本次所选片段的姓名证据，旧片段不能把误识别带回来。
    reconcile_manifest_names({'clips':selected} if force else manifest,fields,targets=selected,updates=name_updates,match_keys=recorded_match_keys(manifest,directory))
    write_json(path,manifest)
    return manifest


def _child_python(backend):
    executable=Path(sys.executable).resolve()
    if backend=='cpu':
        for candidate in [executable.parent.parent/'cpu'/executable.name,BASE/'.venv/Scripts/python.exe']:
            if candidate.is_file():return str(candidate)
    return str(executable)


def _run_hud_child(request,on_progress=None,on_activity=None):
    """原生访问冲突无法用 try/except 捕获；子进程只读取成片并更新软件元数据。"""
    process=subprocess.Popen([_child_python(request['backend']),'-X','faulthandler',str(BASE/'hud_enrichment.py'),'--stdin','--direct'],
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
            elif event.get('type')=='hud-info-done':done=event
        code=process.wait()
        if code!=0:
            raise RuntimeError(f'补充识别子进程退出（{code} / 0x{code & 0xffffffff:08X}）：'+'\n'.join(tail)[-1500:])
        if done is None:raise RuntimeError('补充识别没有返回完成记录')
        if done.get('errors'):raise RuntimeError('; '.join(e['message'] for e in done['errors']))
        return done
    finally:
        if process.poll() is None:process.kill()
        process.wait()
        reader.join(timeout=2)
        for stream in [process.stdin,process.stdout]:stream.close()


def enrich_manifest_isolated(directory,files=None,fields=None,on_progress=None,on_log=None,*,force=False,on_activity=None):
    """GPU 原生崩溃只影响补充子进程；已有成片保留，并用独立 CPU 进程续接。"""
    directory=Path(directory).resolve()
    manifest=json.loads((directory/'export.json').read_text('utf-8-sig'))
    files=files or manifest.get('outputs',[])
    backend=os.environ.get('APEX_OCR_BACKEND','cpu')
    request={'jobs':[{'directory':str(directory),'files':[str(f) for f in files]}],
        'fields':fields or FIELDS,'backend':backend,'gpu_load':os.environ.get('APEX_GPU_LOAD','low'),'force':force}
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


def run_jobs(request,direct=False,emit=None):
    emit=emit or (lambda event:print(json.dumps(event,ensure_ascii=False),flush=True))
    os.environ['APEX_OCR_BACKEND']=request.get('backend','cpu')
    os.environ['APEX_GPU_LOAD']=request.get('gpu_load','low')
    errors=[];done=0;offset=0;total=sum(len(job['files']) for job in request['jobs'])
    for job in request['jobs']:
        try:
            enrich=enrich_manifest if direct else enrich_manifest_isolated
            enrich(job['directory'],job['files'],request.get('fields'),
                lambda index,local_total,file:emit({'type':'hud-info-progress','index':offset+index,'total':total,'file':file}),
                force=request.get('force',False),on_activity=lambda event:emit({**event,'index':offset+event['index'],'total':total}))
            done+=len(job['files'])
        except Exception as error:
            errors.append({'directory':job['directory'],'message':str(error)})
            emit({'type':'hud-info-error','index':offset,'total':total,'message':'本组片段尚未完成，继续下一组','failures':len(errors)})
        offset+=len(job['files'])
    result={'type':'hud-info-done','updated':done,'errors':errors,'total':total}
    emit(result);return result


if __name__=='__main__':
    request=json.loads(sys.stdin.read() if '--stdin' in sys.argv else Path(sys.argv[1]).read_text('utf-8-sig'))
    run_jobs(request,direct='--direct' in sys.argv)
