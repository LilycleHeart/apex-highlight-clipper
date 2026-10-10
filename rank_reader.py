"""复用现有本人视角采样的段位识别；有界模板匹配，不采样全片或调用 OCR。"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent
VERSION = 'hud-rank-v1'
NAMES = {'rookie':'菜鸟','bronze':'青铜','silver':'白银','gold':'黄金','platinum':'白金',
         'diamond':'钻石','master':'大师','predator':'猎杀'}

class RankReader:
    def __init__(self):
        self.templates = []
        for key in NAMES:
            image = cv2.imread(str(BASE/'assets/ranks'/f'{key}.png'), cv2.IMREAD_UNCHANGED) if (BASE/'assets/ranks'/f'{key}.png').exists() else None
            if image is None: continue
            h,w=image.shape[:2]
            # 只比对徽章中心的段位图形，避开外环、分级文字和动态背景。
            center=image[round(h*.27):round(h*.67),round(w*.28):round(w*.72),:3]
            scaled=[]
            for size in range(11,31):
                scaled.append(cv2.resize(center,(round(center.shape[1]/center.shape[0]*size),size)))
            self.templates.append((key,scaled))

    def inspect(self,image):
        h,w=image.shape[:2]
        # 已适配的超宽 HUD，按画面比例折算；禁止在整帧搜索以免命中敌人徽章。
        if abs(w/h-2560/1080)>.03: return None
        roi=image[:round(h*.091),round(w*.953):]
        roi=cv2.resize(roi,(60,49))
        scores=[]
        for key,templates in self.templates:
            best=(-1,None,None)
            for template in templates:
                th,tw=template.shape[:2]
                if th>roi.shape[0] or tw>roi.shape[1]: continue
                _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED))
                if score>best[0]: best=(score,point,(tw,th))
            scores.append((best[0],key,best[1],best[2]))
        scores.sort(reverse=True)
        if len(scores)<2 or scores[0][0]<.80 or scores[0][0]-scores[1][0]<.12: return None
        score,key,point,size=scores[0]
        division=None
        if key not in ['rookie','master','predator']:
            x,y=point;tw,th=size;cx=x+tw/2
            patch=roi[min(49,y+th+2):min(49,y+th+12),max(0,round(cx-7)):min(60,round(cx+7))]
            division=read_division(patch)
        return {'tier':key,'name':NAMES[key],'division':division,'confidence':round(score,3),'method':'hud_badge_template'}

def read_division(patch):
    """只接受清晰的罗马分级，杯口边框与模糊文字不强行推断。"""
    if not patch.size: return None
    mask=(np.min(patch,2)>145).astype(np.uint8)
    n,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    components=[]
    for x,y,w,h,area in stats[1:]:
        if h<3 or h>8 or w>6 or area<4: continue
        if x==0 or x+w==mask.shape[1] or y==0: continue
        glyph=mask[y:y+h,x:x+w]
        if w<=max(2,h*.65) and np.max(glyph[1:-1].sum(axis=1),initial=0)<=2: components.append((x,'I'))
        elif w>=3 and glyph[0].sum()>=2 and glyph[-1].sum()<=2 and glyph[h//2].sum()>=1: components.append((x,'V'))
        else: return None
    text=''.join(v for _,v in sorted(components))
    return text if text in ['I','II','III','IV'] else None

def recognize_segments(cache,samples,segments,checkpoint):
    """每段最多三个已有采样；双帧一致才确认，结果保存并可续接复用。"""
    from apex_clipper import write_json,fingerprint
    from app_cancel import check_cancel
    rows=[r for r in cache['rows'] if not r.get('inactive_view') and not r.get('friend_spectate')]
    signature=hashlib.sha256(json.dumps({'version':VERSION,'source':cache['source'],
        'bounds':[(s['start'],s['end']) for s in segments],
        'assets':json.loads((BASE/'assets/ranks/sources.json').read_text(encoding='utf-8'))},sort_keys=True).encode()).hexdigest()
    checkpoint=Path(checkpoint)
    if checkpoint.exists():
        saved=json.loads(checkpoint.read_text(encoding='utf-8'))
        if saved.get('signature')==signature and saved.get('complete'): return saved
    reader=RankReader();observations={};results=[]
    for segment in segments:
        check_cancel()
        inside=[r for r in rows if segment['start']<=r['time']<segment['end'] and (Path(samples)/r['frame']).is_file()]
        chosen=[]
        if inside:
            for target in [inside[0]['time'],(inside[0]['time']+inside[-1]['time'])/2,inside[-1]['time']]:
                row=min(inside,key=lambda r:abs(r['time']-target))
                if row not in chosen: chosen.append(row)
        evidence=[]
        for row in chosen:
            if row['frame'] not in observations:
                image=cv2.imread(str(Path(samples)/row['frame']))
                observations[row['frame']]=reader.inspect(image) if image is not None else None
            rank=observations[row['frame']]
            if rank: evidence.append({**rank,'time':row['time'],'frame':row['frame']})
        counts=Counter(r['tier'] for r in evidence);rank=None
        if len(counts)==1 and next(iter(counts.values()))>=2:
            tier=next(iter(counts));confirmed=[r for r in evidence if r['tier']==tier]
            divisions=Counter(r['division'] for r in confirmed if r['division'])
            division=next(iter(divisions)) if len(divisions)==1 and next(iter(divisions.values()))>=2 else None
            rank={'tier':tier,'name':NAMES[tier],'division':division,
                  'confidence':min(r['confidence'] for r in confirmed),'method':'two_frame_hud_badge',
                  'scope':'self_current_rank'}
        results.append({'start':segment['start'],'end':segment['end'],'rank':rank,'evidence':evidence,
                        'checked_frames':len(chosen),'status':'confirmed' if rank else 'unknown'})
    report={'version':VERSION,'signature':signature,'complete':True,'source':cache['source'],'segments':results,
            'checked_frames':len(observations),'new_sample_frames':0,'ocr_calls':0}
    if fingerprint(Path(cache['source']['path']))!=cache['source']: raise ValueError('识别段位时源录像发生变化')
    write_json(checkpoint,report)
    return report
