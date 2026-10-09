"""全武器 HUD 名称识别：双槽高亮判定、原生 HUD、简繁英 OCR。"""
from __future__ import annotations
from difflib import SequenceMatcher
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import unicodedata
import urllib.request

import cv2
import numpy as np

BASE=Path(__file__).resolve().parent
MODEL_URL='https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile.onnx'
MODEL_SHA='5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5'
MODEL_PATH=BASE/'models'/'weapon_rec_v5.onnx'
TRANSLATION=str.maketrans('敵轉換衝鋒槍電專輕機噴獵獸擊長萊連發賓雙幫復仇標記莫彈徑',
                         '敌转换冲锋枪电专轻机喷猎兽击长莱连发宾双帮复仇标记莫弹径')

def load_catalog():
    return json.loads((BASE/'weapon-catalog.json').read_text(encoding='utf-8'))

def normalized(text):
    text=unicodedata.normalize('NFKC',text).translate(TRANSLATION).upper()
    return ''.join(c for c in text if c.isalnum())

def resolve_weapon_text(text, confidence=1.0, catalog=None):
    if confidence<.75: return None
    catalog=catalog or load_catalog()
    value=normalized(text)
    if len(value)<2: return None
    akimbo=('AKIMBO' in value or '双持' in value)
    clean=value.replace('AKIMBO','').replace('双持','')
    # 数字型号常见的 O/0、I/1 混淆，仅作用于型号字符串。
    if re.fullmatch(r'[RP][0-9OI]+',clean): clean=clean[0]+clean[1:].replace('O','0').replace('I','1')
    scores=[]
    for weapon in catalog['weapons']+catalog.get('supplemental_weapons',[]):
        aliases={normalized(a) for a in weapon['aliases']}
        score=0
        for alias in aliases:
            if clean==alias: score=1.0; break
            if len(alias)>=3 and alias in clean and len(alias)/len(clean)>=.70:
                score=max(score,.96)
            if min(len(alias),len(clean))>=4:
                similarity=SequenceMatcher(None,clean,alias).ratio()
                if similarity>=.84: score=max(score,similarity)
        if score: scores.append((score,weapon))
    scores.sort(key=lambda pair:pair[0],reverse=True)
    if not scores or (len(scores)>1 and scores[0][0]-scores[1][0]<.08): return None
    score,weapon=scores[0]
    if score<.95 and confidence<.86: return None
    if akimbo and weapon['id'] not in ['p2020','mozambique']: return None
    variant='akimbo' if akimbo else None
    if weapon['id']=='re45' and 'BURST' in clean: variant='burst'
    if weapon['id']=='hemlok' and 'BREACH' in clean: variant='breach'
    return {'id':weapon['id'],'name':('双持' if akimbo else '')+weapon['name'],
            'category':weapon['category'],'variant':variant,'text_match_score':score}

def active_slot(highlights, margin=25):
    # 先判定哪个槽高亮，不能用 OCR 置信度挑选背包里的另一把枪。
    if len(highlights)!=2 or abs(highlights[0]-highlights[1])<margin: return None
    return 0 if highlights[0]>highlights[1] else 1

def ensure_model():
    MODEL_PATH.parent.mkdir(parents=True,exist_ok=True)
    if not MODEL_PATH.exists():
        print('下载武器名称 OCR 模型（约16 MB，首次运行）…',flush=True)
        temp=MODEL_PATH.with_suffix('.part')
        with urllib.request.urlopen(MODEL_URL,timeout=45) as response, temp.open('wb') as output:
            while data:=response.read(1024*1024): output.write(data)
        if hashlib.sha256(temp.read_bytes()).hexdigest()!=MODEL_SHA:
            raise ValueError('下载的武器 OCR 模型 SHA256 校验不符')
        temp.replace(MODEL_PATH)
    if hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()!=MODEL_SHA:
        raise ValueError('武器 OCR 模型 SHA256 校验不符')
    return MODEL_PATH

def new_engine():
    backend=os.environ.get('APEX_OCR_BACKEND','cpu').lower()
    from engine_pool import pooled_engine
    model=ensure_model()
    def create():
        if backend!='cpu':
            from gpu_ocr_backend import create_full_ocr_engine
            return create_full_ocr_engine(backend=backend,model_path=str(model),rec_batch_num=24)
        from rapidocr_onnxruntime import RapidOCR
        return RapidOCR(rec_model_path=str(model),intra_op_num_threads=2,
                    inter_op_num_threads=1,rec_batch_num=24)
    return pooled_engine(('names',backend,os.environ.get('APEX_GPU_LOAD','fast'),MODEL_SHA),create)

def patch_from_hud(hud, box, reference, native_crop):
    x0,y0,cw,ch=native_crop
    x1,y1,x2,y2=box
    patch=hud[round(y1-y0):round(y2-y0),round(x1-x0):round(x2-x0)]
    if not patch.size: raise ValueError('武器名称区域超出原生 HUD')
    return patch

def caption_image(patch):
    hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
    values=hsv[:,:,2][hsv[:,:,1]<100]
    if values.size<8: return cv2.resize(patch,None,fx=2,fy=2)
    threshold=max(80,float(np.percentile(values,95))*.67)
    mask=(hsv[:,:,1]<100)&(hsv[:,:,2]>threshold)
    ys,xs=np.nonzero(mask)
    if len(xs)<8: return cv2.resize(patch,None,fx=2,fy=2)
    image=np.where(mask,0,255).astype(np.uint8)
    image=image[ys.min():ys.max()+1,xs.min():xs.max()+1]
    image=cv2.copyMakeBorder(image,4,4,4,4,cv2.BORDER_CONSTANT,value=255)
    return cv2.cvtColor(cv2.resize(image,None,fx=3,fy=3),cv2.COLOR_GRAY2BGR)

def highlight_score(patch):
    hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
    values=hsv[:,:,2][hsv[:,:,1]<70]
    # 使用文字前景而非固定百分位，避免 G7 等短名称被大面积背景吞掉。
    if not values.size: return 0
    foreground=values[values>max(80,float(np.percentile(values,25))+25)]
    return float(np.percentile(foreground,90)) if foreground.size>=4 else 0

def caption_views(patch):
    masked=caption_image(patch)
    hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
    values=hsv[:,:,2][hsv[:,:,1]<100]
    if values.size<8: return [masked,cv2.resize(patch,None,fx=2,fy=2)]
    mask=(hsv[:,:,1]<100)&(hsv[:,:,2]>max(80,float(np.percentile(values,95))*.67))
    ys,xs=np.nonzero(mask)
    if len(xs)<8: return [masked,cv2.resize(patch,None,fx=2,fy=2)]
    # 保留抗锯齿，二值化会损伤“獒”等复杂字的细小笔画。
    raw=patch[ys.min():ys.max()+1,xs.min():xs.max()+1]
    color=tuple(int(c) for c in np.median(patch.reshape(-1,3),axis=0))
    raw=cv2.copyMakeBorder(raw,4,4,4,4,cv2.BORDER_CONSTANT,value=color)
    return [masked,cv2.resize(raw,None,fx=3,fy=3)]

def recognize_text_views(views,catalog=None):
    catalog=catalog or load_catalog()
    matches=[]
    for text,confidence in views:
        match=resolve_weapon_text(text,float(confidence),catalog)
        if match: matches.append((float(confidence)*match['text_match_score'],text,float(confidence),match))
    if matches and len({m[3]['id'] for m in matches})==1:
        _,text,confidence,match=max(matches,key=lambda m:m[0])
        return {'text':text,'confidence':confidence},match
    text,confidence=max(views,key=lambda item:item[1])
    return {'text':text,'confidence':float(confidence)},None

def native_hud(path, row, cache, profile, ffmpeg):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        image=cv2.imread(str(path))
        if image is not None: return image
        raise ValueError(f'原生 HUD 图片损坏: {path}')
    source=Path(cache['source']['path'])
    st=source.stat()
    if st.st_size!=cache['source']['size'] or st.st_mtime_ns!=cache['source']['mtime_ns']:
        raise ValueError('源录像已变化，不能补取 HUD')
    probe_path=str(Path(ffmpeg).with_name('ffprobe.exe' if Path(ffmpeg).suffix.lower()=='.exe' else 'ffprobe'))
    meta=subprocess.run([probe_path,
                         '-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(source)],
                        capture_output=True,encoding='utf-8',errors='replace',
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess,'CREATE_NO_WINDOW') else 0)
    if meta.returncode: raise RuntimeError(meta.stderr)
    stream=json.loads(meta.stdout)['streams'][0]
    rw,rh=profile['reference_size']; width,height=stream['width'],stream['height']
    x,y,w,h=profile['weapon_native_crop']
    x=round(x*width/rw/2)*2; y=round(y*height/rh/2)*2
    w=round(w*width/rw/2)*2; h=round(h*height/rh/2)*2
    result=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-ss',str(row['time']),
                           '-i',str(source),'-frames:v','1','-vf',f'crop={w}:{h}:{x}:{y}','-q:v','2','-n',str(path)],
                          capture_output=True,encoding='utf-8',errors='replace',
                          creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess,'CREATE_NO_WINDOW') else 0)
    if result.returncode: raise RuntimeError(result.stderr)
    image=cv2.imread(str(path))
    if image is None: raise ValueError(f'无法读取原生 HUD: {path}')
    return image

def enrich_weapon_labels(cache, samples, profile, ffmpeg,optimize=True,checkpoint=None,segments=None):
    config={k:profile[k] for k in ['weapon_name_boxes','weapon_name_metrics','weapon_native_crop']}
    signature=hashlib.sha256(json.dumps({'version':3,'model':MODEL_SHA,'profile':config,
                                        'catalog':load_catalog()},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if cache.get('weapon_label_signature')==signature: return cache
    if segments is not None:
        signature=hashlib.sha256(json.dumps({'base':signature,'scope':[(s['start'],s['end']) for s in segments]},sort_keys=True).encode()).hexdigest()
        if cache.get('weapon_label_signature')==signature: return cache
    rows=cache['rows']
    # 只补读可能开枪的附近采样；命名不会扫描整段录像再次做完整 OCR。
    selected=set()
    previous=None
    for i,row in enumerate(rows):
        if row.get('inactive_view'): previous=None; continue
        if row.get('ammo') is None: continue
        if previous is not None:
            before=rows[previous]
            if 0<before['ammo']-row['ammo']<=50 and row['time']-before['time']<=1.1:
                selected.update(j for j in range(max(0,i-1),min(len(rows),i+2)) if not rows[j].get('inactive_view'))
        previous=i
    if segments is not None:
        # 邻近的一秒保留名称共识上下文，避免在片段边界少一帧而变成未知枪。
        selected={i for i in selected if any(s['start']-1<=rows[i]['time']<=s['end']+1 for s in segments)}
    if not selected:
        cache['weapon_label_signature']=signature; return cache
    journal=None; restored=set()
    if checkpoint:
        from resume_io import RowJournal
        identity=hashlib.sha256(json.dumps({'source':cache.get('source'),'fps':cache['fps'],'signature':signature,'selected':sorted(selected)},sort_keys=True).encode()).hexdigest()
        journal=RowJournal(Path(checkpoint).with_suffix('.weapons.jsonl'),identity,
            lambda entry,i:entry.get('index') in selected and isinstance(entry.get('data'),dict) and all(k in entry['data'] for k in ['weapon_labels','active_weapon_slot','current_weapon','current_weapon_confidence']))
        for entry in journal.rows:
            rows[entry['index']].update(entry['data']); restored.add(entry['index'])
        if restored: print(f'枪名续接：保留 {len(restored)} 帧',flush=True)
    order=sorted(selected-restored)
    if not order:
        cache['weapon_label_signature']=signature; return cache
    engine=new_engine(); catalog=load_catalog()
    from ocr_cache import ExactTextCache
    recognize=ExactTextCache(engine.text_rec) if optimize else engine.text_rec
    rw,rh=profile['reference_size']; cx,cy,cw,ch=profile['weapon_native_crop']
    for offset in range(0,len(order),24):
        if checkpoint:
            from app_cancel import check_cancel
            check_cancel()
        batch=order[offset:offset+24]; crops=[]; metrics=[]
        for index in batch:
            row=rows[index]
            hud=native_hud(Path(samples)/'hud'/row['frame'],row,cache,profile,ffmpeg)
            hud=cv2.resize(hud,(cw,ch))
            highlights=[]
            for box,metric in zip(profile['weapon_name_boxes'],profile['weapon_name_metrics']):
                patch=patch_from_hud(hud,box,[rw,rh],[cx,cy,cw,ch])
                crops.extend(caption_views(patch))
                highlights.append(highlight_score(patch_from_hud(hud,metric,[rw,rh],[cx,cy,cw,ch])))
            metrics.append(highlights)
        result,_=recognize(crops)
        for j,index in enumerate(batch):
            row=rows[index]; labels=[]; matches=[]
            for k in range(2):
                label,match=recognize_text_views(result[j*4+k*2:j*4+k*2+2],catalog)
                label['highlight']=metrics[j][k]; labels.append(label); matches.append(match)
            slot=active_slot(metrics[j]); match=matches[slot] if slot is not None else None
            row['weapon_labels']=labels; row['active_weapon_slot']=slot
            row['current_weapon']=match
            row['current_weapon_confidence']=labels[slot]['confidence'] if match else 0
        if journal:
            fields=['weapon_labels','active_weapon_slot','current_weapon','current_weapon_confidence']
            journal.append([{'index':index,'data':{key:rows[index][key] for key in fields}} for index in batch])
        print(f'原生武器名称 OCR: {min(offset+24,len(order))}/{len(order)} 帧',flush=True)
    cache['weapon_label_signature']=signature
    if optimize: cache['weapon_ocr_reuse']=recognize.stats()
    return cache
