"""交战边界之外的可选信息识别；同一实现支持原录像与已导出片段。"""
from collections import Counter
from pathlib import Path
import hashlib
import json
import re
import unicodedata

import cv2
from image_io import read_image
import numpy as np

from apex_clipper import BASE,fingerprint,probe,write_json,inactive_view,downed_score
from app_cancel import check_cancel
from hud_layout import detect_images

VERSION='optional-hud-v2'
FIELDS=['account','weapons','teammates','hero','rank']


def stable(observations,key):
    values=[row[key] for row in observations if row.get(key)]
    counts=Counter(value['name'].casefold() for value in values)
    if not counts:return None
    name,n=counts.most_common(1)[0]
    if n<2:return None
    selected=[value for value in values if value['name'].casefold()==name]
    result=dict(max(selected,key=lambda v:v['confidence']))
    result['confidence']=min(v['confidence'] for v in selected)
    result['method']='two_frame_'+key;return result


def name_value(views):
    choices=[]
    for text,confidence in views:
        name=unicodedata.normalize('NFKC',text).strip()
        name=re.sub(r'\s+[^\w\s]+$','',name)
        name=re.sub(r'[\s()（）♫♪◀▶]+$','',name)
        if confidence>=.80 and 2<=len(name)<=40 and any(c.isalpha() for c in name):
            if name.upper() not in ['MAX LEVEL','DEATHBOX RECOVERY','RECOVER BANNER','SPECTATING']:
                choices.append({'name':name,'confidence':float(confidence)})
    return max(choices,key=lambda row:row['confidence']) if choices else None


def native_frames(source,start,end):
    import av
    with av.open(str(source)) as container:
        stream=container.streams.video[0];stream.codec_context.thread_count=1
        seen=set()
        for fraction in [.15,.5,.85]:
            check_cancel();second=start+(end-start)*fraction
            container.seek(int(second/stream.time_base),stream=stream,backward=True,any_frame=False)
            frame=next((f for f in container.decode(stream) if f.pts is not None and float(f.pts*f.time_base)>=second),None)
            if frame is None or frame.pts in seen:continue
            seen.add(frame.pts);yield float(frame.pts*frame.time_base),frame.to_ndarray(format='bgr24')


def roi(image,profile,box):
    rw,rh=profile['reference_size'];x1,y1,x2,y2=box;h,w=image.shape[:2]
    return image[max(0,round(y1*h/rh)):min(h,round(y2*h/rh)),max(0,round(x1*w/rw)):min(w,round(x2*w/rw))]


def recognize_video(source,fields=None,start=0.,end=None,profile=None):
    fields=list(dict.fromkeys(fields or FIELDS));source=Path(source)
    before=fingerprint(source);meta,video=probe(source);end=min(float(meta['format']['duration']),end or float(meta['format']['duration']))
    frames=list(native_frames(source,start,end))
    if not frames:raise ValueError('片段中没有可读取的HUD画面')
    if not profile:profile=detect_images([image for _,image in frames],video['width'],video['height'])
    from weapon_reader import caption_views,recognize_text_views,MODEL_PATH
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
    observations=[];weapons=[];teams=[[],[]]
    shield=None
    for second,image in frames:
        check_cancel()
        if inactive_view(image):
            # 同交战可能包含本人倒地后的队友观战；不能把观战对象当成本人。
            from outcome_reader import friend_view
            if friend_view(image,True):continue
            if shield is None:shield=read_image(str(BASE/profile['downed_marker']),0)
            if downed_score(image,profile,shield)<profile['downed_marker_threshold']:continue
        row={'time':second};crops=[];slots=[]
        regions=[]
        if 'account' in fields:regions.append(('account',profile['account_roi']))
        if 'teammates' in fields:regions.extend((f'team_{i}',box) for i,box in enumerate(profile['teammate_rois']))
        if 'weapons' in fields:regions.extend((f'weapon_{i}',box) for i,box in enumerate(profile['weapon_name_boxes']))
        for key,box in regions:
            patch=roi(image,profile,box)
            if patch.size:
                slots.append((key,len(crops)));crops.extend(caption_views(patch))
        texts=reader(crops)[0] if crops else []
        for key,index in slots:
            views=texts[index:index+2]
            if key.startswith('weapon_'):
                label,match=recognize_text_views(views)
                if match and label['confidence']>=.86:weapons.append({**match,'confidence':label['confidence'],'time':second})
            else:
                value=name_value(views)
                if value:
                    if key=='account':row['account']=value
                    else:teams[int(key[-1])].append({'teammate':value})
        if rank_reader:row['rank']=rank_reader.inspect(image,profile)
        if hero_reader:row['hero']=hero_reader.inspect(image,profile)
        observations.append(row)
    result={'version':VERSION,'source_identity':before,'requested_fields':fields,'profile':profile,
        'checked_frames':len(frames),'frame_times':[time for time,_ in frames],'account':None,'teammates':[],
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
            info.update(version=VERSION,source_identity=identity,profile=current['profile'],checked_frames=current['checked_frames'],
                requested_fields=list(dict.fromkeys(previous.get('requested_fields',[])+pending)),
                field_status={**previous.get('field_status',{}),**current['field_status']})
            recognition['hud_info']=info;write_json(path,manifest)
        if on_progress:on_progress(index+1,len(selected),str(file))
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
