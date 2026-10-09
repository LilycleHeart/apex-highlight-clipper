"""先确认已结束的观战，避免把结算/大厅一直细查到下一局。只用正面结束证据裁减。"""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from apex_clipper import write_json
from app_cancel import check_cancel
from outcome_reader import result_kind
from resume_io import RowJournal
from weapon_reader import new_engine, MODEL_SHA

def loading_geometry(image):
    h,w=image.shape[:2]
    bars=[image[round(h*.22):round(h*.72),:round(w*.08)],image[round(h*.22):round(h*.72),round(w*.92):]]
    return all(float(np.mean(np.max(b,axis=2)<16))>.93 for b in bars)

def loading_title(text):
    from outcome_reader import compact
    t=compact(text)
    return any(s in t for s in ['積分賽','排位賽','排位赛','积分赛','大逃殺','大逃杀','RANKEDLEAGUES'])


def subtract_windows(windows, excluded):
    result=[]
    for start,end in windows:
        pieces=[(start,end)]
        for left,right in excluded:
            pieces=[p for a,b in pieces for p in
                    ([(a,b)] if right<=a or left>=b else
                     ([(a,min(b,left))] if a<left else [])+([(max(a,right),b)] if right<b else []))]
        result.extend([a,b] for a,b in pieces if b>a)
    return result


def terminal_idle_ranges(rows,events,duration):
    """结束后仍留6秒；在下次本人HUD出现前6秒恢复细查，未知情况不裁减。"""
    result=[]
    for event in events:
        end=next((r['time'] for r in rows if r['time']>event['time'] and
                  (r.get('friend_spectate') or not r.get('inactive_view') and
                   (r.get('ammo') is not None or r.get('counter_offset') is not None))),duration)
        if event.get('kind')=='loading':
            # 加载也可能来自断线重连；再要求后续本人计分明显重置，不能只凭加载画面截队友续战。
            before=[r['damage'] for r in rows if r['time']<event['time'] and
                    not r.get('inactive_view') and r.get('damage') is not None][-3:]
            after=[r['damage'] for r in rows if r['time']>=end and
                   not r.get('inactive_view') and r.get('damage') is not None][:3]
            if len(before)<2 or len(after)<2 or max(after)>min(before)-25: continue
        start=event['time']+6; stop=max(0,end-6) if end<duration else duration
        if stop>start: result.append([start,stop])
    return result


def inspect_early_round_ends(coarse,samples,checkpoint):
    """只查倒地/友方观战后的关键帧，每次观战最多32次OCR；无法确认则保守保留。"""
    checkpoint=Path(checkpoint); samples=Path(samples); rows=coarse['rows']
    signature=hashlib.sha256(json.dumps({'version':3,'model':MODEL_SHA,'source':coarse['source'],
        'rows':[(r['frame'],r['time'],r.get('downed'),r.get('friend_spectate'),r.get('inactive_view'),
                 r.get('ammo'),r.get('counter_offset')) for r in rows]},sort_keys=True).encode()).hexdigest()
    if checkpoint.exists():
        saved=json.loads(checkpoint.read_text(encoding='utf-8'))
        if saved.get('signature')==signature and saved.get('complete'): return saved
    journal=RowJournal(checkpoint.with_suffix('.jsonl'),signature,
        lambda e,i:isinstance(e.get('index'),int) and 0<=e['index']<len(rows) and e.get('kind') in [None,'end','win','loading'])
    known={e['index']:e for e in journal.rows}; events=[]; engine=None
    last_downed=None; watching=False; ended=False; checked=0; calls=0; starts=[]
    for index,row in enumerate(rows):
        check_cancel(); t=row['time']; inactive=row.get('inactive_view',False)
        if not inactive and (row.get('ammo') is not None or row.get('counter_offset') is not None):
            if ended: ended=False
            if watching: watching=False; checked=0
        if row.get('downed'): last_downed=t
        if inactive and not ended and (row.get('friend_spectate') or last_downed is not None and t-last_downed<=15):
            if not watching: starts.append(t)
            watching=True
        if not watching or ended or checked>=32: continue
        # 加载画面不一定满足观战底栏条件；先用严格的两侧黑边作廉价候选。
        image=cv2.imread(str(samples/row['frame']))
        if image is None: raise ValueError('缺少粗查结束画面')
        loading=loading_geometry(image)
        if not inactive and not loading: continue
        checked+=1
        if index in known: entry=known[index]
        else:
            if engine is None:
                from rapidocr_onnxruntime.ch_ppocr_det.utils import DetPreProcess
                engine=new_engine()
                engine.text_det.get_preprocess=lambda max_wh:DetPreProcess(512,'max',engine.text_det.mean,engine.text_det.std)
            h,w=image.shape[:2]
            region=image[round(h*.04):round(h*.22),:round(w*.40)] if loading else image[round(h*.18):round(h*.67),round(w*.20):round(w*.80)]
            results,_=engine(region,use_cls=False); calls+=1
            text=' '.join(x[1] for x in results or [] if float(x[2])>=.75)
            entry={'index':index,'kind':('loading' if loading_title(text) else None) if loading else result_kind(text,True),'text':text}
            journal.append([entry]); known[index]=entry
            from ui_observer import preview
            preview(samples/row['frame'],t)
        if entry['kind']:
            events.append({'time':t,'frame':row['frame'],'kind':entry['kind'],'text':entry['text']})
            ended=True; watching=False; last_downed=None
    # 全灭横幅有时在两张关键帧之间闪过。只给尚未确认的观战入口补一个12秒小窗口。
    from apex_clipper import probe,inactive_view
    from resume_media import sample_with_resume
    from adaptive_evidence import decode_policy
    from smart_scan import frame_ranges
    import os
    source=coarse['source']['path']; meta,video=probe(source); duration=float(meta['format']['duration'])
    dense=[]; extra_frames=0
    for start in starts:
        next_self=next((r['time'] for r in rows if r['time']>start and not r.get('inactive_view') and
                       (r.get('ammo') is not None or r.get('counter_offset') is not None)),duration)
        observed=[e for e in events if start-4<=e['time']<=next_self]
        if any(e['kind'] in ['end','win'] for e in observed): continue
        # 已很快进入加载画面时，再追一闪而过的横幅反而得不偿失。
        if observed and min(e['time'] for e in observed)-start<=30: continue
        left=max(0,start-4); right=min(duration,start+8,next_self)
        if right<=left: continue
        folder=checkpoint.parent/(checkpoint.stem+f'-entry-{start:.6f}')
        cuda,threads,_=decode_policy(video,os.environ.get('APEX_OCR_BACKEND')=='dml')
        ranges=frame_ranges([[left,right]],duration,2)
        sample_with_resume(source,folder,2,cuda,frame_ranges=ranges,**({'cpu_threads':threads} if threads else {}))
        extra_frames+=sum(b-a+1 for a,b in ranges)
        dense_log=RowJournal(folder/'terminal.jsonl',signature,
            lambda e,i: isinstance(e.get('index'),int) and e.get('kind') in [None,'end','win'])
        saved={e['index']:e for e in dense_log.rows}
        for first,last in ranges:
            for index in range(first,last+1):
                check_cancel(); at=(index-.5)/2
                if index in saved: entry=saved[index]
                else:
                    image=cv2.imread(str(folder/f'{index:06d}.jpg'))
                    if image is None: raise ValueError('缺少观战入口补查画面')
                    if not inactive_view(image): entry={'index':index,'kind':None,'text':''}
                    else:
                        if engine is None: engine=new_engine()
                        from rapidocr_onnxruntime.ch_ppocr_det.utils import DetPreProcess
                        engine.text_det.get_preprocess=lambda max_wh:DetPreProcess(512,'max',engine.text_det.mean,engine.text_det.std)
                        h,w=image.shape[:2]; result,_=engine(image[round(h*.18):round(h*.67),round(w*.20):round(w*.80)],use_cls=False)
                        text=' '.join(x[1] for x in result or [] if float(x[2])>=.75); calls+=1
                        entry={'index':index,'kind':result_kind(text,True),'text':text}
                    dense_log.append([entry])
                if entry['kind']:
                    events.append({'time':at,'frame':f'{index:06d}.jpg','sample_directory':str(folder),
                                   'kind':entry['kind'],'text':entry['text']})
                    break
            else: continue
            break
        dense.append({'start':left,'end':right,'samples':str(folder)})
    events.sort(key=lambda e:e['time'])
    report={'signature':signature,'complete':True,'events':events,'ocr_new_frames':calls,
            'entry_samples':dense,'entry_sample_frames':extra_frames}
    write_json(checkpoint,report)
    return report
