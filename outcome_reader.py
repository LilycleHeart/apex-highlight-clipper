"""只在赛后界面候选附近确认全灭/结束文字，用于边界和新局基线校正。"""
import hashlib
import json
from pathlib import Path
import unicodedata
import cv2
import numpy as np
from weapon_reader import new_engine,MODEL_SHA

def compact(text):
    text=unicodedata.normalize('NFKC',text).upper()
    return ''.join(c for c in text if c.isalnum())

def result_kind(text,inactive):
    value=compact(text)
    if any(x in value for x in ['YOUARETHECHAMPION','你已成为冠军','你已成為冠軍','你是冠军','你是冠軍']): return 'win'
    if inactive and any(x in value for x in ['小队全灭','小隊全滅','游戏结束','遊戲結束','SQUADELIMINATED','GAMEOVER']): return 'end'
    return None

def friend_view(image,inactive):
    if not inactive: return False
    h,w=image.shape[:2]
    banner=image[round(h*.93):round(h*.98),round(w*.36):round(w*.64)]
    hsv=cv2.cvtColor(banner,cv2.COLOR_BGR2HSV)
    green=(hsv[:,:,0]>=24)&(hsv[:,:,0]<=95)&(hsv[:,:,1]>100)&(hsv[:,:,2]>100)
    _,xx=np.nonzero(green)
    return bool(len(xx)>=80 and xx.max()-xx.min()>=banner.shape[1]*.40)

def enrich_outcomes(cache,samples,checkpoint=None):
    signature=hashlib.sha256(('outcome-v3-'+MODEL_SHA).encode()).hexdigest()
    if cache.get('outcome_signature')==signature: return cache
    rows=cache['rows']; chosen=set()
    for i,r in enumerate(rows):
        r['round_ended']=False
        r['friend_spectate']=False
        if r.get('inactive_view'):
            image=cv2.imread(str(Path(samples)/r['frame']))
            if image is None: raise ValueError('缺少观战检查采样')
            r['friend_spectate']=friend_view(image,True)
        if r.get('inactive_view') and (i==0 or not rows[i-1].get('inactive_view')):
            chosen.update(range(max(0,i-2),min(len(rows),i+10)))
    if not chosen:
        cache['outcome_events']=[]; cache['outcome_signature']=signature; return cache
    journal=None; observations={}
    if checkpoint:
        from resume_io import RowJournal
        identity=hashlib.sha256(json.dumps({'source':cache.get('source'),'fps':cache['fps'],'signature':signature,'selected':sorted(chosen)},sort_keys=True).encode()).hexdigest()
        journal=RowJournal(Path(checkpoint).with_suffix('.outcomes.jsonl'),identity,
            lambda entry,i:entry.get('index') in chosen and entry.get('kind') in [None,'end','win'] and isinstance(entry.get('text'),str))
        observations={entry['index']:entry for entry in journal.rows}
        if observations: print(f'结束画面续接：保留 {len(observations)} 帧',flush=True)
    pending=sorted(chosen-set(observations))
    if pending:
        engine=new_engine()
        from rapidocr_onnxruntime.ch_ppocr_det.utils import DetPreProcess
        engine.text_det.get_preprocess=lambda max_wh: DetPreProcess(512,'max',engine.text_det.mean,engine.text_det.std)
    found=[]
    for index in pending:
        if checkpoint:
            from app_cancel import check_cancel
            check_cancel()
        r=rows[index]; image=cv2.imread(str(Path(samples)/r['frame']))
        if image is None: raise ValueError('缺少结尾检查采样')
        h,w=image.shape[:2]; region=image[round(h*.18):round(h*.67),round(w*.20):round(w*.80)]
        result,_=engine(region,use_cls=False)
        lines=[(x[1],float(x[2])) for x in result or []]
        text=' '.join(t for t,c in lines if c>=.60)
        kind=result_kind(text,r.get('inactive_view',False))
        observations[index]={'index':index,'kind':kind,'text':text}
        if journal: journal.append([observations[index]])
    for index in sorted(observations):
        r=rows[index]; entry=observations[index]; kind,text=entry['kind'],entry['text']
        if kind:
            r['round_ended']=True
            if not found or r['time']-found[-1]['time']>12:
                found.append({'time':r['time'],'kind':kind,'text':text,'frame':r['frame']})
    cache['outcome_events']=found; cache['outcome_signature']=signature
    return cache

def cap_segment_ends(segments,outcomes,tail=2):
    result=[]
    for s in segments:
        item=dict(s)
        endings=[e for e in outcomes if s['last_signal']<=e['time']<s['end']]
        if endings:
            end=min(endings,key=lambda e:e['time'])
            item['end']=min(s['end'],end['time']+tail)
            item['end_evidence']=end
        result.append(item)
    return result

def preserve_team_continuation(segments,rows,outcomes,duration,tail=2):
    result=[]
    for segment in segments:
        item=dict(segment)
        transitions=[r for r in rows if segment['last_signal']<=r['time']<=segment['end']+2
                     and r.get('friend_spectate')]
        if transitions:
            start=transitions[0]['time']
            end_event=next((e for e in outcomes if e['time']>=start),None)
            exit_row=next((r for r in rows if r['time']>start+1 and not r.get('inactive_view')),None)
            # 先返回本人视角时，不能跨越新局/复活后的长空档等待远处的结束画面。
            if end_event and (exit_row is None or end_event['time']<=exit_row['time']+3):
                item['end']=max(item['end'],min(duration,end_event['time']+tail))
                item['team_end_evidence']=end_event
            else:
                # 录像边界内没有全灭/夺冠证据，保留友方视角到本次观战退出或文件末。
                item['end']=max(item['end'],min(duration,exit_row['time']+15 if exit_row else duration))
                item['team_end_needs_review']=True
            item.setdefault('protected_reasons',[]).append('friend_team_continuation')
        if result and item['start']<=result[-1]['end']:
            result[-1]['end']=max(result[-1]['end'],item['end'])
            result[-1]['last_signal']=max(result[-1]['last_signal'],item['last_signal'])
            result[-1]['protected_reasons']=list(set(result[-1].get('protected_reasons',[])+item.get('protected_reasons',[])))
        else: result.append(item)
    return result
