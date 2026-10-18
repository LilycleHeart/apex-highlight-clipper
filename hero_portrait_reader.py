"""技能被遮挡时核对本人 HUD 的固定头像；不读取或保存玩家名称。"""
from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from image_io import read_image

VERSION='self-hero-portrait-v1'
BASE=Path(__file__).resolve().parent


def portrait_patch(image,profile):
    from hud_enrichment import roi
    x,y,_,_=profile['account_roi'];sx,sy=profile.get('hud_scale',[1.,1.])
    patch=roi(image,profile,[x-83*sx,y-4*sy,x-20*sx,y+50*sy])
    if not patch.size:return None
    return cv2.resize(patch,(56,48),interpolation=cv2.INTER_AREA)


def portrait_features(patch):
    gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY).astype(np.float32)
    mask=np.zeros(gray.shape,np.uint8);cv2.ellipse(mask,(28,24),(23,22),0,0,360,255,-1);selected=mask>0
    if float(gray[selected].std())<8:return None
    edge=cv2.Laplacian(gray,cv2.CV_32F)
    def normalized(image):
        value=image[selected];value=value-value.mean();return value/max(1e-6,float(np.linalg.norm(value)))
    return normalized(gray),normalized(edge)


def first_order_features(patch):
    gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY).astype(np.float32)
    mask=np.zeros(gray.shape,np.uint8);cv2.ellipse(mask,(28,24),(23,22),0,0,360,255,-1);selected=mask>0
    if float(gray[selected].std())<8:return None
    result=[]
    for plane in [gray,cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3),cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3)]:
        value=plane[selected];value=value-value.mean();result.append(value/max(1e-6,float(np.linalg.norm(value))))
    return result


class HeroPortraitReader:
    def __init__(self):
        root=BASE/'assets/legends/portraits';raw=(root/'sources.json').read_bytes();manifest=json.loads(raw)
        self.signature=hashlib.sha256(VERSION.encode()+raw+Path(__file__).read_bytes()).hexdigest();self.templates=[];self.first_order_templates=[]
        for item in manifest['templates']:
            file=(root/item['file']).resolve()
            if not file.is_relative_to(root.resolve()) or hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('英雄头像资源校验失败')
            image=read_image(file)
            if image is None or image.shape[:2]!=(48,56):raise ValueError('英雄头像资源尺寸不正确')
            features=portrait_features(image)
            if features is None:raise ValueError('英雄头像资源缺少可核对的图形')
            self.templates.append((item,features))
            self.first_order_templates.append((item,first_order_features(image)))

    def inspect(self,image,profile):
        patch=portrait_patch(image,profile)
        if patch is None:return None
        return self.inspect_patch(patch)

    def inspect_patch(self,patch):
        features=portrait_features(patch)
        if features is None:return None
        scores={}
        for item,reference in self.templates:
            gray=float(features[0]@reference[0]);edge=float(features[1]@reference[1]);score=min(gray,edge)
            if score>scores.get(item['id'],{}).get('score',-2):scores[item['id']]={'score':score,'gray':gray,'edge':edge,'template':item['file'],'template_sha256':item['sha256']}
        ordered=sorted(scores.items(),key=lambda value:-value[1]['score'])
        if len(ordered)<2:return None
        ident,best=ordered[0];margin=best['score']-ordered[1][1]['score']
        if best['score']<.90 or margin<.08:return self.inspect_first_order(patch)
        return {'id':ident,'confidence':round(best['score'],4),'method':'self_portrait_template','portrait_evidence':{**best,'margin':margin,'recipe':self.signature}}

    def inspect_first_order(self,patch):
        # 压缩与缩放会改变二阶边缘；改用完整亮度及两个方向的一阶形状分别核对。
        features=first_order_features(patch)
        if features is None:return None
        scores={}
        for item,reference in self.first_order_templates:
            values=[float(a@b) for a,b in zip(features,reference)];score=min(values)
            if score>scores.get(item['id'],{}).get('score',-2):scores[item['id']]={'score':score,'gray':values[0],'gradient_x':values[1],'gradient_y':values[2],'template':item['file'],'template_sha256':item['sha256']}
        ordered=sorted(scores.items(),key=lambda value:-value[1]['score'])
        if len(ordered)<2:return None
        ident,best=ordered[0];margin=best['score']-ordered[1][1]['score']
        if best['score']<.92 or best['gray']<.95 or margin<.12:return None
        return {'id':ident,'confidence':round(best['score'],4),'method':'self_portrait_first_order','portrait_evidence':{**best,'margin':margin,'recipe':self.signature}}


@lru_cache(maxsize=1)
def portrait_reader():return HeroPortraitReader()


def confirm_video_portrait(source,profile,start=0.,end=None,moments=None,on_activity=None):
    from apex_clipper import fingerprint,probe,inactive_view,downed_score
    from hud_enrichment import native_frames
    from outcome_reader import spectator_view
    from hero_reader import NAMES
    source=Path(source);before=fingerprint(source)
    if profile.get('layout_status')!='confirmed':return {'hero':None,'observations':[]}
    duration=float(probe(source)[0]['format']['duration']);end=min(duration,end or duration)
    moments=list(moments if moments is not None else [start+(end-start)*fraction for fraction in [.15,.5,.85,.05,.35,.65]])[:6]
    reader=portrait_reader();observations=[];seen=set();shield=None
    for second,image in native_frames(source,start,end,moments):
        if not start<=second<end or second in seen:continue
        seen.add(second);inactive=inactive_view(image)
        if spectator_view(image,inactive):observations.append({'time':second,'excluded_view':True});continue
        if inactive:
            if shield is None:shield=read_image(BASE/profile['downed_marker'],0)
            if downed_score(image,profile,shield)<profile['downed_marker_threshold']:observations.append({'time':second,'excluded_view':True});continue
        value=reader.inspect(image,profile);observations.append({'time':second,'hero':value})
        if on_activity:on_activity({'message':'核对本人英雄头像','frames_done':len(seen),'frames_total':len(moments)})
        accepted=[row['hero'] for row in observations if row.get('hero')]
        if len(seen)>=3 and len(accepted)>=2:break
    visible=[row for row in observations if row.get('hero')]
    if len(visible)==1:
        seed=visible[0]['time'];pair=[seed+offset for offset in [-.04,.04] if start<=seed+offset<end]
        for second,image in native_frames(source,start,end,pair):
            if not start<=second<end or second in seen:continue
            seen.add(second);inactive=inactive_view(image)
            if spectator_view(image,inactive):observations.append({'time':second,'excluded_view':True});continue
            if inactive:
                if shield is None:shield=read_image(BASE/profile['downed_marker'],0)
                if downed_score(image,profile,shield)<profile['downed_marker_threshold']:observations.append({'time':second,'excluded_view':True});continue
            value=reader.inspect(image,profile);observations.append({'time':second,'hero':value,'sample_type':'adjacent_confirmation'})
            if on_activity:on_activity({'message':'相邻原生帧核对英雄头像','frames_done':len(seen),'frames_total':len(moments)+len(pair)})
    if fingerprint(source)!=before:raise ValueError('核对头像期间录像发生变化')
    accepted=[row['hero'] for row in observations if row.get('hero')]
    counts=Counter(value['id'] for value in accepted);hero=None
    if len(counts)==1 and next(iter(counts.values()))>=2:
        ident=next(iter(counts));hero={'id':ident,'name':NAMES.get(ident,ident),'confidence':min(value['confidence'] for value in accepted),'method':'two_frame_self_portrait','votes':len(accepted),'portrait_evidence':{'recipe':reader.signature,'frames':[{'time':row['time'],**row['hero']['portrait_evidence']} for row in observations if row.get('hero')]}}
    return {'hero':hero,'observations':observations}
