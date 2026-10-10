"""数字框识别失败时，用独立图标定位和前景分离补读，不能降低置信门槛填数。"""
from pathlib import Path
import hashlib
import cv2
import numpy as np

BASE=Path(__file__).resolve().parent
def counter_recipe():
    digest=hashlib.sha256(Path(__file__).read_bytes())
    for file in sorted((BASE/'templates/statistics').glob('*.png')):digest.update(file.read_bytes())
    return digest.hexdigest()

def digit_view(patch):
    if patch is None or not patch.size:return None
    gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
    count,labels,stats,_=cv2.connectedComponentsWithStats((gray>180).astype(np.uint8))
    mask=np.zeros(gray.shape,np.uint8)
    for i,(x,y,w,h,area) in enumerate(stats[1:],1):
        # 排除贯穿整框的白色背景、底边和图标碎片；保留数字的独立笔画。
        if 4<=h<=gray.shape[0]-2 and area>=4 and w<=h*1.6:mask[labels==i]=255
    yy,xx=np.where(mask>0)
    if not len(xx):return None
    glyph=255-mask[yy.min():yy.max()+1,xx.min():xx.max()+1]
    glyph=cv2.resize(glyph,None,fx=4,fy=4)
    glyph=cv2.copyMakeBorder(glyph,8,8,8,8,cv2.BORDER_CONSTANT,value=255)
    return cv2.cvtColor(glyph,cv2.COLOR_GRAY2BGR)

class CounterFallback:
    def __init__(self):
        self.templates={key:cv2.imread(str(BASE/'templates/statistics'/f'{key}-gray.png'),0) for key in ['kills','assists','participation']}
        self.digits={key:cv2.imread(str(BASE/'templates/statistics'/f'digit-{key}.png'),0) for key in ['0','6','8']}
    def decode_numeric_alias(self,text,view):
        self.last_match_score=0.
        zero_aliases=['D','O','〇','日','口']
        if not text or not any(c in text for c in zero_aliases+['B']):return None
        gray=cv2.cvtColor(view,cv2.COLOR_BGR2GRAY);mask=gray<128;columns=np.where(mask.any(axis=0))[0];runs=[]
        for x in columns:
            if runs and x==runs[-1][-1]+1:runs[-1].append(x)
            else:runs.append([x])
        if len(runs)!=len(text):return None
        output=[];matched_scores=[]
        for character,run in zip(text,runs):
            if character.isdigit():output.append(character);continue
            if character not in zero_aliases+['B']:return None
            part=mask[:,run[0]:run[-1]+1];ys=np.where(part.any(axis=1))[0]
            glyph=cv2.resize(part[ys.min():ys.max()+1].astype(np.uint8),(24,32),interpolation=cv2.INTER_NEAREST)>0
            scores=[]
            for key,template in self.digits.items():
                if template is None:continue
                reference=template>128;scores.append((2*np.count_nonzero(glyph&reference)/max(1,np.count_nonzero(glyph)+np.count_nonzero(reference)),key))
            scores.sort(reverse=True)
            if len(scores)<2 or scores[0][0]<.95 or scores[0][0]-scores[1][0]<.05:return None
            allowed=['0'] if character in zero_aliases else ['6','8']
            if scores[0][1] not in allowed:return None
            output.append(scores[0][1]);matched_scores.append(scores[0][0])
        self.last_match_score=min(matched_scores) if matched_scores else 0.
        return ''.join(output)
    def patches(self,image,profile,delta):
        if image.shape[1]!=1280:return {}
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);dx,dy=delta;anchors={}
        for key,reference in [('kills',profile['kills']),('assists',[2202,94,2228,124]),('participation',[2260,94,2300,124])]:
            template=self.templates[key]
            if template is None:continue
            x1=max(0,round((reference[0]+dx)/2)-40);x2=min(image.shape[1],round((reference[2]+dx)/2)+25)
            y1=max(0,round((reference[1]+dy)/2)-8);y2=min(image.shape[0],round((reference[3]+dy)/2)+8)
            region=gray[y1:y2,x1:x2]
            if region.shape[0]<template.shape[0] or region.shape[1]<template.shape[1]:continue
            _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(region,template,cv2.TM_CCOEFF_NORMED))
            if score>=.84:anchors[key]=(x1+point[0],y1+point[1],x1+point[0]+template.shape[1],y1+point[1]+template.shape[0])
        result={}
        for key,next_key in [('kills','assists'),('assists','participation')]:
            if key in anchors and next_key in anchors:
                a,b=anchors[key],anchors[next_key];left,right=a[2],b[0]-2
                if 3<=right-left<=32:
                    result[key]=digit_view(image[a[1]:a[3],left:right])
        box=profile['damage'];x1,y1,x2,y2=[round((v+(dx if i%2==0 else dy))/2) for i,v in enumerate(box)]
        result['damage']=digit_view(image[y1:y2,x1:x2])
        return result
