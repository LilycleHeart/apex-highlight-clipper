"""复用现有本人视角采样的段位识别；有界模板匹配，不采样全片或调用 OCR。"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
from image_io import read_image
import numpy as np

BASE = Path(__file__).resolve().parent
VERSION = 'hud-rank-v6'
NAMES = {'rookie':'菜鸟','bronze':'青铜','silver':'白银','gold':'黄金','platinum':'白金',
         'diamond':'钻石','master':'大师','predator':'猎杀','unranked':'匹配'}

def empty_badge_region(roi):
    """仅把清楚的空白区域当作无图标；有轮廓但不认识的徽章仍待确认。"""
    gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
    contrast=float(np.percentile(gray,95)-np.percentile(gray,5))
    edges=float(np.count_nonzero(cv2.Canny(gray,40,100)))/gray.size
    return {'contrast':round(contrast,3),'edge_fraction':round(edges,4)} if contrast<24 and edges<.02 else None

_MODE_CLOCK=None

def mode_clock_evidence(roi):
    """右上角出现模式时钟（控制/混战等），说明这不是大逃杀排位画面。

    只在已确认布局的本人 HUD 区域里比对，阈值保持偏低但要求形状高度一致，
    避免把排位徽章的外环误判成时钟。
    """
    global _MODE_CLOCK
    if _MODE_CLOCK is None:
        path=BASE/'assets/modes/mode-clock.png'
        _MODE_CLOCK=read_image(str(path),cv2.IMREAD_COLOR) if path.is_file() else False
    template=_MODE_CLOCK
    if template is False or roi.size==0:return None
    th,tw=template.shape[:2]
    if roi.shape[0]<th or roi.shape[1]<tw:return None
    _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED))
    return {'score':round(float(score),3),'point':[int(point[0]),int(point[1])]} if score>=.62 else None

def palette_matches(template,patch):
    """同形徽章仍需符合其调色板；颜色证据不足时继续使用形状门槛。"""
    reference=cv2.cvtColor(template,cv2.COLOR_BGR2HSV);observed=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
    mask=(reference[:,:,1]>60)&(reference[:,:,2]>110)
    colored=mask&(observed[:,:,1]>60)&(observed[:,:,2]>110)
    if np.count_nonzero(colored)<max(8,np.count_nonzero(mask)*.25):return True
    def hue(image,selection):
        angles=image[:,:,0][selection].astype(float)*np.pi/90
        weights=image[:,:,1][selection].astype(float)*image[:,:,2][selection]
        return np.arctan2(np.sum(np.sin(angles)*weights),np.sum(np.cos(angles)*weights))*90/np.pi%180
    difference=abs(hue(reference,mask)-hue(observed,colored))
    return min(difference,180-difference)<=18

class RankReader:
    def __init__(self):
        self.templates = [];self.native_centers={}
        for key in NAMES:
            image = read_image(str(BASE/'assets/ranks'/f'{key}.png'), cv2.IMREAD_UNCHANGED) if (BASE/'assets/ranks'/f'{key}.png').exists() else None
            if image is None: continue
            h,w=image.shape[:2]
            # 只比对徽章中心的段位图形，避开外环、分级文字和动态背景。
            center=image[round(h*.27):round(h*.67),round(w*.28):round(w*.72),:3]
            self.native_centers[key]=center.copy()
            scaled=[]
            for size in range(11,31):
                scaled.append(cv2.resize(center,(round(center.shape[1]/center.shape[0]*size),size)))
            self.templates.append((key,scaled))

    def inspect(self,image,profile=None):
        h,w=image.shape[:2]
        # 已适配的超宽 HUD，按画面比例折算；禁止在整帧搜索以免命中敌人徽章。
        if profile and profile.get('rank_roi'):
            rw,rh=profile['reference_size'];x1,y1,x2,y2=profile['rank_roi']
            roi=image[round(y1*h/rh):round(y2*h/rh),round(x1*w/rw):round(x2*w/rw)]
        else:
            if abs(w/h-2560/1080)>.03: return None
            roi=image[:round(h*.091),round(w*.953):]
        if not roi.size:return None
        native=roi
        # 其他模式（控制/混战等）在段位位置放的是模式时钟，没有段位可读；
        # 先认出这个标志，避免把「该模式本来就没有段位」报成识别失败。
        clock=mode_clock_evidence(native) if profile and profile.get('layout_status')=='confirmed' else None
        if clock is not None:
            return {'tier':None,'name':None,'division':None,'confidence':clock['score'],
                    'method':'mode_clock_detected','mode':'other','evidence':clock}
        # 用户规则：已校准的本人 HUD 右上角没有图标时归为匹配。
        # 仍由调用者按不同原生帧形成共识；布局未确认不能从空白画面猜模式。
        absence=empty_badge_region(native) if profile and profile.get('layout_status')=='confirmed' else None
        if absence is not None:
            return {'tier':'unranked','name':NAMES['unranked'],'division':None,'confidence':.8,
                    'method':'no_badge_matching_rule','absence_evidence':absence}
        if profile and profile.get('hud_scale'):
            sx,sy=profile['hud_scale'];rw,rh=profile['reference_size']
            roi=cv2.resize(roi,None,fx=.5/sx*rw/w,fy=.5/sy*rh/h)
        else:roi=cv2.resize(roi,(60,49))
        scores=[]
        for key,templates in self.templates:
            best=(-1,None,None)
            for template in templates:
                th,tw=template.shape[:2]
                if th>roi.shape[0] or tw>roi.shape[1]: continue
                _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED))
                x,y=point
                if not palette_matches(template,roi[y:y+th,x:x+tw]):continue
                if score>best[0]: best=(score,point,(tw,th))
            scores.append((best[0],key,best[1],best[2]))
        scores.sort(reverse=True)
        if len(scores)<2:return None
        if scores[0][0]<.80 or scores[0][0]-scores[1][0]<.12:
            return self.inspect_native(native,(roi.shape[1]*2,roi.shape[0]*2)) if scores[0][0]>=.70 else None
        score,key,point,size=scores[0]
        division=None
        if key not in ['rookie','master','predator','unranked']:
            x,y=point;tw,th=size;cx=x+tw/2
            # 徽章匹配可缩小，罗马数字必须回到原生像素读取，不能先把三根细线缩成两根。
            sx=native.shape[1]/roi.shape[1];sy=native.shape[0]/roi.shape[0]
            patch=native[round((y+th+2)*sy):min(native.shape[0],round((y+th+12)*sy)),max(0,round((cx-7)*sx)):min(native.shape[1],round((cx+7)*sx))]
            division=read_division(patch)
            if division is None:
                refined=self.inspect_native(native,(roi.shape[1]*2,roi.shape[0]*2))
                if refined and refined['tier']==key:division=refined.get('division')
        return {'tier':key,'name':NAMES[key],'division':division,'confidence':round(score,3),'method':'hud_badge_template'}

    def inspect_native(self,native,size):
        # 原路径未确认才保留原生细节复核，原有已确认分支不变。
        roi=cv2.resize(native,size);scores=[]
        for key,center in self.native_centers.items():
            best=(-1,None,None)
            for height in range(22,61):
                template=cv2.resize(center,(round(center.shape[1]/center.shape[0]*height),height));th,tw=template.shape[:2]
                if th>roi.shape[0] or tw>roi.shape[1]:continue
                _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED))
                if score>best[0] and palette_matches(template,roi[y:y+th,x:x+tw]):best=(score,(x,y),(tw,th))
            scores.append((best[0],key,best[1],best[2]))
        scores.sort(reverse=True)
        if len(scores)<2 or scores[0][0]<.80 or scores[0][0]-scores[1][0]<.12:return None
        score,key,point,(tw,th)=scores[0];x,y=point;division=None
        if key not in ['rookie','master','predator','unranked']:
            sx=native.shape[1]/roi.shape[1];sy=native.shape[0]/roi.shape[0];cx=x+tw/2
            patch=native[round((y+th+4)*sy):min(native.shape[0],round((y+th+24)*sy)),max(0,round((cx-14)*sx)):min(native.shape[1],round((cx+14)*sx))]
            division=read_division(patch)
        return {'tier':key,'name':NAMES[key],'division':division,'confidence':round(score,3),'method':'hud_badge_native_template','badge_resolution':'native'}

    def confirm_division(self,source,profile,rank,observations,start=0.,end=None,on_activity=None):
        """只在分级尚未双帧确认时，核对已有实际字形附近的原生画面。"""
        if not rank or rank.get('division') or rank['tier'] in ['rookie','master','predator','unranked']:return rank
        from apex_clipper import fingerprint,probe,inactive_view,downed_score
        from hud_enrichment import native_frames
        from outcome_reader import spectator_view
        source=Path(source);before=fingerprint(source);duration=float(probe(source)[0]['format']['duration']);end=min(duration,end or duration)
        evidence=[{'time':row['time'],'rank':row['rank']} for row in observations if row.get('rank') and row['rank']['tier']==rank['tier'] and row['rank'].get('division')]
        if not evidence:return rank
        seen={row['time'] for row in observations if 'rank' in row};seeds=sorted(evidence,key=lambda row:row['rank']['confidence'],reverse=True)[:2];shield=None;conflict=False
        moments=[row['time']+offset for row in seeds for offset in [-.04,.04] if start<=row['time']+offset<end]
        for second,image in native_frames(source,start,end,moments):
            if not start<=second<end or second in seen:continue
            seen.add(second);inactive=inactive_view(image)
            if spectator_view(image,inactive):continue
            if inactive:
                if shield is None:shield=read_image(BASE/profile['downed_marker'],0)
                if downed_score(image,profile,shield)<profile['downed_marker_threshold']:continue
            value=self.inspect(image,profile)
            if value and value['tier']!=rank['tier']:conflict=True
            if value and value['tier']==rank['tier'] and value.get('division'):evidence.append({'time':second,'rank':value})
            if on_activity:on_activity({'message':'相邻原生帧核对罗马分级','frames_done':len(evidence),'frames_total':len(seeds)+len(moments)})
        if fingerprint(source)!=before:raise ValueError('核对分级期间录像发生变化')
        counts=Counter(row['rank']['division'] for row in evidence)
        if not conflict and len(counts)==1 and len({row['time'] for row in evidence})>=2:
            return {**rank,'division':next(iter(counts)),'division_evidence':[{'time':row['time'],'division':row['rank']['division'],'confidence':row['rank']['confidence']} for row in evidence]}
        return rank

def read_division(patch):
    """只接受清晰的罗马分级，杯口边框与模糊文字不强行推断。"""
    if not patch.size: return None
    # 在统一的原生 HUD 尺度读取；仅放大小图，不再缩小细字。
    if patch.shape[0]<16:patch=cv2.resize(patch,None,fx=2,fy=2,interpolation=cv2.INTER_NEAREST)
    readings=[]
    for threshold in [120,155,190]:
        value=_division_components((np.min(patch,2)>threshold).astype(np.uint8))
        if value:readings.append(value)
    counts=Counter(readings)
    return next(iter(counts)) if len(counts)==1 and next(iter(counts.values()))>=2 else None


def _division_components(mask):
    n,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    components=[];glyph_boxes=[];fragment_mask=np.zeros_like(mask)
    for label,(x,y,w,h,area) in enumerate(stats[1:],1):
        if x==0 or x+w==mask.shape[1] or y==0: continue
        if h<5 or h>mask.shape[0]*.8 or w>mask.shape[1]*.8 or area<8:
            if h>=2 and w<=max(3,h*.65) and area>=3:fragment_mask[labels==label]=1
            continue
        glyph_boxes.append((x,y,w,h))
        glyph=mask[y:y+h,x:x+w];trim=max(1,round(h*.23));body=glyph[trim:h-trim]
        spans=[]
        for line in body:
            points=np.flatnonzero(line)
            if len(points):spans.append((points[0],points[-1]))
        if not spans:return None
        if w<=h*1.15 and w>=3 and spans[0][1]-spans[0][0]>=spans[-1][1]-spans[-1][0]+2:
            components.append((x,'V'));continue
        # 衬线顶部可把 II/III 连起来；只在字干中段分离，保留全部原生竖线。
        n,_,parts,_=cv2.connectedComponentsWithStats(body)
        letters=[]
        for px,py,pw,ph,pa in parts[1:]:
            if ph<body.shape[0]*.7 or pa<3:return None
            piece=body[py:py+ph,px:px+pw]
            centers=[np.flatnonzero(line).mean() for line in piece if line.any()]
            if pw<=max(3,h*.45) and max(centers)-min(centers)<=max(1,h*.13):letters.append((px,'I'))
            else:
                widths=[np.ptp(np.flatnonzero(line)) for line in piece if line.any()]
                if pw>=3 and widths[0]>=widths[-1]+1:letters.append((px,'V'))
                else:return None
        components.extend((x+px,letter) for px,letter in letters)
    # 高阈值可能把较暗的字干切断；不能丢掉这些同一文字行的残笔后把 III 算成 I。
    # 仅废弃损坏的二值图，仍要求另外两个完整阈值一致，不能多数投票压过真实冲突。
    # 只沿竖向连接相隔一两像素的残笔，识别同一字干被切成多段的情况。
    fragments=cv2.connectedComponentsWithStats(cv2.morphologyEx(fragment_mask,cv2.MORPH_CLOSE,np.ones((3,1),np.uint8)))[2][1:]
    for x,y,w,h,area in fragments:
        for gx,gy,gw,gh in glyph_boxes:
            overlap=max(0,min(y+h,gy+gh)-max(y,gy))
            gap=max(gx-(x+w),x-(gx+gw),0)
            if h>=gh*.45 and overlap>=h*.7 and gap<=gh:return None
    text=''.join(v for _,v in sorted(components))
    return text if text in ['I','II','III','IV'] else None

def recognize_segments(cache,samples,segments,checkpoint):
    """每段最多三个已有采样；双帧一致才确认，结果保存并可续接复用。"""
    from apex_clipper import write_json,fingerprint
    from app_cancel import check_cancel
    rows=[r for r in cache['rows'] if not r.get('inactive_view') and not r.get('friend_spectate')]
    signature=hashlib.sha256(json.dumps({'version':VERSION,'source':cache['source'],
        'bounds':[(s['start'],s['end']) for s in segments],
        'profile':cache.get('profile'),
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
                image=read_image(str(Path(samples)/row['frame']))
                observations[row['frame']]=reader.inspect(image,cache.get('profile')) if image is not None else None
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
