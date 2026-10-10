"""候选交战中的本人中心结果提示；区别于公共击杀播报及对白字幕。"""
import json
import hashlib
import math
import re
import unicodedata
from pathlib import Path
import cv2
import numpy as np
from apex_clipper import BASE,write_json,fingerprint,probe,inactive_view
from weapon_reader import new_engine,MODEL_SHA

KINDS={'knock','assist','elimination'}
RULE_VERSION='own-center-result-v4'


def load_profile():
    profile=json.loads((BASE/'combat-outcome-profile.json').read_text(encoding='utf-8'))
    # 私有实拍夹具与公开运行配置分离；已有机器保持原签名及诊断脚本兼容。
    fixture_path=BASE/'combat-outcome-fixtures.local.json'
    if fixture_path.is_file():
        fixtures=json.loads(fixture_path.read_text(encoding='utf-8'))
        for key in ['positive_examples','negative_examples']:
            if key in fixtures: profile[key]=fixtures[key]
        profile['calibration'].update(fixtures.get('calibration_metadata',{}))
        for entry in profile.get('prefix_templates',[]):
            entry.update(fixtures.get('template_metadata',{}).get(entry['path'],{}))
    return profile


def parse_result_line(text):
    """只接受本人toast的行首语法；玩家名拼错不影响事件种类。"""
    clean=unicodedata.normalize('NFKC',text).strip()
    clean=re.sub(r'\s+',' ',clean)
    patterns=[
        ('assist',r'^(?:助攻\s*[,，:]?\s*(?:擊倒|击倒|消滅|消灭)?|ASSIST\s*[: ,]*\s*(?:KNOCK(?:ED)? DOWN|ELIMINAT(?:ION|ED))?)\s*(.*)$'),
        ('knock',r'^(?:(?:已)?(?:擊倒|击倒)|KNOCKED DOWN)\s*(.*)$'),
        ('elimination',r'^(?:已消滅|已消灭|ELIMINATED)\s*(.*)$'),
    ]
    for kind,pattern in patterns:
        match=re.match(pattern,clean,re.IGNORECASE)
        if not match: continue
        target=re.sub(r'\s*[+＋]\s*[0-9OIl]{2,4}.*$','',match.group(1)).strip()
        action=('elimination' if re.search(r'消[滅灭]|ELIMINAT',clean,re.IGNORECASE) else
                'knock' if re.search(r'[擊击]倒|KNOCK',clean,re.IGNORECASE) else 'unknown')
        if kind=='assist':target=re.sub(r'^(?:[擊击擎驛驿]倒|消[滅灭減减])\s*','',target)
        if kind=='assist':
            suffix=re.sub(r'^(?:助攻|ASSIST)\s*[,，:]?\s*','',clean,flags=re.I)
            if re.match(r'^.倒',suffix):action='knock';target=re.sub(r'^.倒\s*','',target)
            elif re.match(r'^消.',suffix):action='elimination';target=re.sub(r'^消.\s*','',target)
        return {'kind':kind,'action':action,'target_text':target,'text':clean}
    return None


def is_known_dialogue(text):
    text=unicodedata.normalize('NFKC',text)
    if ':' in text and not re.match(r'^(?:助攻|ASSIST|已消滅|已消灭|擊倒|击倒|KNOCKED|ELIMINATED)',text,re.IGNORECASE): return True
    cue=re.search(r'擊倒|击倒|消滅|消灭|助攻|KNOCK|ELIMINAT',text,re.IGNORECASE)
    if not cue: return False
    prefix=text[:cue.start()]
    return bool(':' in prefix or re.search(r'我被|你被|被人|I(?: AM| WAS)? |YOU(?: ARE| WERE)? ',prefix,re.IGNORECASE)
                or (not parse_result_line(text) and re.search(r'[。!?！？]',text)))


class PrefixGate:
    def __init__(self,profile):
        self.profile=profile; self.templates=[]
        for entry in profile.get('prefix_templates',[]):
            image=cv2.imread(str(BASE/entry['gray']),cv2.IMREAD_GRAYSCALE)
            if image is None: raise ValueError('缺少本人结果提示模板')
            self.templates.append((entry,image))

    def inspect(self,image):
        region,roi=roi_image(image,self.profile); gray=cv2.cvtColor(region,cv2.COLOR_BGR2GRAY)
        found=[]
        for entry,template in self.templates:
            ratio=image.shape[1]/entry['sample_size'][0]
            if ratio!=1: template=cv2.resize(template,None,fx=ratio,fy=ratio)
            result=cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED)
            action='knock' if 'knock' in entry.get('path','') else 'elimination' if 'elimination' in entry.get('path','') else entry['kind']
            # 同时出现多个同类提示时保留多个行位置，避免只支持最高匹配的一行。
            for n in range(4):
                _,score,_,loc=cv2.minMaxLoc(result)
                if n and score<self.profile.get('calibration',{}).get('gate_threshold',.65):break
                found.append({'kind':entry['kind'],'action':action,'score':float(score),'box':[loc[0]+roi[0],loc[1]+roi[1],loc[0]+roi[0]+template.shape[1],loc[1]+roi[1]+template.shape[0]]})
                x,y=loc;th,tw=template.shape
                result[max(0,y-th//2):min(result.shape[0],y+th//2+1),max(0,x-tw//2):min(result.shape[1],x+tw//2+1)]=-2
        return found


def group_lines(detections):
    """合并同一行的不同颜色/分词框，保留字幕说话者和否定前缀。"""
    lines=[]
    for item in sorted(detections,key=lambda x:(x['top'],x['left'])):
        cy=(item['top']+item['bottom'])/2; height=max(1,item['bottom']-item['top'])
        possible=[line for line in lines if abs(cy-line['cy'])<=min(height,line['height'])*.65]
        if possible:
            line=min(possible,key=lambda line:abs(cy-line['cy'])); line['items'].append(item)
            line['cy']=sum((i['top']+i['bottom'])/2 for i in line['items'])/len(line['items'])
            line['height']=max(height,line['height'])
        else: lines.append({'cy':cy,'height':height,'items':[item]})
    result=[]
    for line in lines:
        items=sorted(line['items'],key=lambda x:x['left'])
        groups=[]
        for item in items:
            if groups and item['left']-groups[-1][-1]['right']<=80: groups[-1].append(item)
            else: groups.append([item])
        for items in groups:
            result.append({'text':' '.join(i['text'] for i in items),'confidence':min(i['confidence'] for i in items),
                'prefix_confidence':items[0]['confidence'],
                'box':[min(i['left'] for i in items),min(i['top'] for i in items),max(i['right'] for i in items),max(i['bottom'] for i in items)],
                'parts':items})
    return result


def roi_image(image,profile):
    h,w=image.shape[:2]; rw,rh=profile['reference_size']; x1,y1,x2,y2=profile['toast_roi']
    box=[round(x1*w/rw),round(y1*h/rh),round(x2*w/rw),round(y2*h/rh)]
    return image[box[1]:box[3],box[0]:box[2]],box


def recognize_frame(image,profile,engine=None,expand_context=False):
    engine=engine or new_engine()
    from rapidocr_onnxruntime.ch_ppocr_det.utils import DetPreProcess
    engine.text_det.get_preprocess=lambda max_wh: DetPreProcess(960,'max',engine.text_det.mean,engine.text_det.std)
    region,roi=roi_image(image,profile)
    if expand_context:
        pad=round(profile.get('context_padding_left',100)*image.shape[1]/profile['reference_size'][0])
        roi[0]=max(0,roi[0]-pad); region=image[roi[1]:roi[3],roi[0]:roi[2]]
    scaled=cv2.resize(region,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
    recognized,_=engine(scaled,use_cls=False)
    detections=[]
    for points,text,confidence in recognized or []:
        xs=[p[0]/2+roi[0] for p in points]; ys=[p[1]/2+roi[1] for p in points]
        detections.append({'text':text,'confidence':float(confidence),'left':min(xs),'right':max(xs),'top':min(ys),'bottom':max(ys)})
    lines=group_lines(detections); events=[]; ambiguous=[]; dialogue=[]
    if not expand_context and any(line['box'][0]<=roi[0]+4 and not is_known_dialogue(line['text'])
        and re.search(r'擊倒|击倒|消滅|消灭|助攻|KNOCK|ELIMINAT',line['text'],re.IGNORECASE) for line in lines):
        return recognize_frame(image,profile,engine,expand_context=True)
    for line in lines:
        if is_known_dialogue(line['text']): dialogue.append(line); continue
        parsed=parse_result_line(line['text'])
        if parsed and line['prefix_confidence']>=.65:
            events.append({**parsed,'confidence':line['prefix_confidence'],'text_confidence':line['confidence'],'box':line['box']})
        elif re.search(r'擊倒|击倒|消滅|消灭|助攻|KNOCK|ELIMINAT',line['text'],re.IGNORECASE):
            ambiguous.append(line)
    return {'lines':lines,'events':events,'ambiguous_lines':ambiguous,'known_dialogue':dialogue,'context_expanded':expand_context}


def candidate_indices(candidate,fps):
    first=max(1,math.ceil(candidate['start']*fps+.5))
    last=math.ceil(candidate['end']*fps+.5)-1
    return list(range(first,last+1))


def ranges_from_indices(indices):
    result=[]
    for value in sorted(set(indices)):
        if result and value==result[-1][1]+1: result[-1][1]=value
        else: result.append([value,value])
    return result


def _same_line_gate(event,matches):
    box=event['box']; cy=(box[1]+box[3])/2
    # 助攻优先；不能把“助攻，擊倒”中的擊倒当另一个本人独立击倒。
    relevant=[m for m in matches if m['kind']==event['kind'] and
              abs((m['box'][1]+m['box'][3])/2-cy)<=10 and
              box[0]-5<=m['box'][0]<=box[2]+5]
    return max((m['score'] for m in relevant),default=0.)


def _locale_confirmed(cache,observations,profile):
    if not profile.get('calibration',{}).get('require_traditional_ui',True): return True
    traditional=r'[擊滅敵槍衝鋒輕獵獸轉換瑪蘿]'
    for row in cache['rows']+cache.get('locale_reference_rows',[]):
        if any(re.search(traditional,label.get('text','')) for label in row.get('weapon_labels',[])): return True
    for row in observations.values():
        if any(re.search(traditional,line['text']) for line in row.get('known_dialogue',[])): return True
        if any(re.match(r'^(助攻|擊倒|已消滅)',event['text']) for event in row.get('events',[])): return True
    return False


def inspect_combat_outcomes(cache,samples,candidates,profile=None,checkpoint=None,_allow_upgrade=True,_only_existing=False,_stop_after_positive=True):
    """先在已有帧寻找任一强正例；只为未确认候选补齐画面并核查不存在。"""
    from app_cancel import check_cancel
    from resume_io import RowJournal
    from ui_observer import preview
    profile=profile or load_profile(); samples=Path(samples); fps=cache['fps']
    if fps<2 and _allow_upgrade and _stop_after_positive:
        return _inspect_low_frequency(cache,samples,candidates,profile,checkpoint)
    source=Path(cache['source']['path']); identity=fingerprint(source)
    if identity!=cache['source']: raise ValueError('原录像发生变化，不能复用结果提示')
    checkpoint=Path(checkpoint) if checkpoint else samples.parent/'combat-outcomes.json'
    checkpoint.parent.mkdir(parents=True,exist_ok=True)
    templates={str(BASE/e['gray']):hashlib.sha256((BASE/e['gray']).read_bytes()).hexdigest() for e in profile.get('prefix_templates',[])}
    signature=hashlib.sha256(json.dumps({'version':RULE_VERSION,'source':identity,'fps':fps,'samples':str(samples.resolve()),
        'profile':profile,'templates':templates,'model':MODEL_SHA,'only_existing':_only_existing,'stop_after_positive':_stop_after_positive,'reader_version':'toast-lines-v6',
        'bounds':[(c['start'],c['end']) for c in candidates]},sort_keys=True).encode()).hexdigest()
    if checkpoint.exists():
        saved=json.loads(checkpoint.read_text(encoding='utf-8'))
        if saved.get('signature')==signature and saved.get('complete'): return saved
    wanted={i for c in candidates for i in candidate_indices(c,fps)}
    journal=RowJournal(checkpoint.with_suffix('.toast-rows.jsonl'),signature,
        lambda r,index:r.get('index') in wanted and r.get('time')==(r['index']-.5)/fps and r.get('status') in ['negative','ambiguous','excluded_view','self_event'])
    observations={r['index']:r for r in journal.rows}
    hud_rows={int(r['frame'][:-4]):r for r in cache['rows']}
    gate=PrefixGate(profile); engine=None; checked_new=0; ocr_new=0; sampled_new=0
    extra_root=checkpoint.parent/('combat-outcome-samples-'+signature[:12])
    decisions=[]
    def observe(index,path):
        nonlocal engine,checked_new,ocr_new
        if index in observations: return observations[index]
        check_cancel(); image=cv2.imread(str(path))
        if image is None: raise ValueError('结果提示画面缺失或损坏')
        own=not hud_rows[index].get('inactive_view') if index in hud_rows else not inactive_view(image)
        if index in hud_rows and hud_rows[index].get('friend_spectate'): own=False
        item={'index':index,'frame':path.name,'time':(index-.5)/fps,'events':[],'status':'negative'}
        item['sample_size']=[image.shape[1],image.shape[0]]
        if not own:
            item['status']='excluded_view'
        else:
            matches=gate.inspect(image); best=max((m['score'] for m in matches),default=0.)
            item['gate']=matches
            threshold=profile.get('calibration',{}).get('gate_threshold',.65)
            if best>=threshold:
                if engine is None: engine=new_engine()
                result=recognize_frame(image,profile,engine); ocr_new+=1
                if not _stop_after_positive:
                    # 统计阶段：文字常把“擊”读成“擎/驿”或漏掉，但必须由行首的强图形匹配支持修正。
                    for line in result['lines']:
                        if parse_result_line(line['text']):continue
                        supports=[m for m in matches if m['score']>=.88 and abs(m['box'][0]-line['box'][0])<=8 and
                                  abs((m['box'][1]+m['box'][3]-line['box'][1]-line['box'][3])/2)<=8]
                        for match in sorted(supports,key=lambda m:-m['score']):
                            fixed=line['text']
                            if match['kind']=='knock' and re.match(r'^(?:[擎驛驿擊击]倒|倒)',fixed):
                                fixed=re.sub(r'^(?:[擎驛驿擊击]倒|倒)','擊倒',fixed)
                            else:continue
                            parsed=parse_result_line(fixed)
                            if parsed and not is_known_dialogue(fixed):
                                result['events'].append({**parsed,'confidence':max(line['prefix_confidence'],.86),
                                    'text_confidence':line['confidence'],'box':line['box'],'prefix_repair':'strong_prefix_template'})
                                break
                item.update(lines=result['lines'],known_dialogue=result['known_dialogue'])
                possible=[]
                for event in result['events']:
                    support=_same_line_gate(event,matches)
                    matching=[m for m in matches if m['kind']==event['kind'] and abs((m['box'][1]+m['box'][3])/2-(event['box'][1]+event['box'][3])/2)<=10 and event['box'][0]-5<=m['box'][0]<=event['box'][2]+5]
                    if matching:
                        strongest=max(matching,key=lambda m:m['score']);event['prefix_box']=strongest['box']
                        if event['kind']=='assist' and event.get('action')=='unknown':event['action']=strongest.get('action','unknown')
                    if event['confidence']>=.85 and support>=threshold:
                        item['events'].append({**event,'time':item['time'],'frame':item['frame'],'template_score':support,'ownership':'self'})
                    elif event['confidence']>=.65 and support>=.9:
                        potential={**event,'time':item['time'],'frame':item['frame'],'template_score':support,'ownership':'self'}
                        possible.append(potential)
                        if any(abs(previous['time']-item['time'])<=1.1 and previous['time']!=item['time'] and
                               any(e['kind']==event['kind'] for e in previous.get('possible_events',[])) for previous in observations.values()):
                            item['events'].append({**potential,'confirmation':'two_frame_prefix'})
                if possible: item['possible_events']=possible
                if item['events']: item['status']='self_event'
                elif possible or result['ambiguous_lines'] or best>=.84 and not result['known_dialogue']:
                    item['status']='ambiguous'
        observations[index]=item; journal.append([item]); checked_new+=1
        preview(path,item['time'])
        return item
    for position,candidate in enumerate(candidates):
        check_cancel(); indices=candidate_indices(candidate,fps); found=[]
        present={i:samples/f'{i:06d}.jpg' for i in indices if (samples/f'{i:06d}.jpg').is_file()}
        # 时间顺序优先：前部一旦有本人结果，整个候选立即确认，不扫描其余内容。
        for index in indices:
            if index not in present: continue
            item=observe(index,present[index])
            if item['events']:
                found.extend(item['events'])
                if _stop_after_positive: break
        if not found or not _stop_after_positive:
            missing=[i for i in indices if i not in present]
            if missing and not _only_existing:
                from resume_media import sample_with_resume
                from adaptive_evidence import decode_policy
                _,video=probe(source)
                import os
                use_cuda=cache.get('backend')=='dml' or os.environ.get('APEX_OCR_BACKEND')=='dml'
                cuda,threads,_=decode_policy(video,use_cuda)
                extra=extra_root/f'candidate-{position+1:03d}'
                sample_with_resume(source,extra,fps,cuda,frame_ranges=ranges_from_indices(missing),**({'cpu_threads':threads} if threads else {}))
                sampled_new+=len(missing)
                for index in missing:
                    item=observe(index,extra/f'{index:06d}.jpg')
                    if item['events']:
                        found.extend(item['events'])
                        if _stop_after_positive: break
        covered=[observations[i] for i in indices if i in observations]
        uncertain=[r for r in covered if r['status']=='ambiguous']
        calibration=profile.get('calibration',{})
        supported_style=(_locale_confirmed(cache,observations,profile) and all(r.get('sample_size')==[1280,540] for r in covered))
        reliable_absence=(len(covered)==len(indices) and fps>=calibration.get('minimum_fps',2)
                          and calibration.get('negative_decision_enabled',False) and not uncertain and supported_style)
        if found: status='kept'; reason='已确认本人击倒、助攻或消灭提示'
        elif reliable_absence: status='rejected'; reason='完整检查候选后未发现本人击倒、助攻或消灭提示'
        else: status='review'; reason='提示模糊、采样覆盖不足或尚未校准，需复核本人结果'
        decisions.append({'candidate_index':position,'status':status,'reason':reason,'events':found,
            'coverage':{'expected_frames':len(indices),'checked_frames':len(covered),'fps':fps,
                        'ambiguous_frames':[r['frame'] for r in uncertain],'reliable_absence':reliable_absence,
                        'calibrated_style_confirmed':supported_style,
                        'stopped_after_positive':bool(found) and _stop_after_positive}})
        print(f'本人战果提示: {position+1}/{len(candidates)} 段，{status}，新增文字识别 {ocr_new} 帧',flush=True)
    report={'signature':signature,'version':RULE_VERSION,'complete':True,'source':identity,
        'policy':sorted(KINDS),'decisions':decisions,'stats':{'checked_new_frames':checked_new,'ocr_new_frames':ocr_new,'extra_sample_frames':sampled_new,'restored_frames':len(journal.rows)-checked_new}}
    if fingerprint(source)!=identity: raise ValueError('识别结果提示时源录像发生变化')
    write_json(checkpoint,report)
    return report


def _inspect_low_frequency(cache,samples,candidates,profile,checkpoint):
    """先用低频已采帧找正例；仅未确认候选建立独立2Hz网格，不混用编号。"""
    from resume_media import sample_with_resume
    from adaptive_evidence import decode_policy
    import os
    checkpoint=Path(checkpoint) if checkpoint else Path(samples).parent/'combat-outcomes.json'
    native=inspect_combat_outcomes(cache,samples,candidates,profile,checkpoint.with_name(checkpoint.stem+'-native.json'),
        _allow_upgrade=False,_only_existing=True)
    pending=[d['candidate_index'] for d in native['decisions'] if d['status']!='kept']
    if not pending:
        report={**native,'scan_fps':cache['fps'],'upgrade_fps':None}; write_json(checkpoint,report); return report
    source=Path(cache['source']['path']); _,video=probe(source)
    cuda,threads,_=decode_policy(video,os.environ.get('APEX_OCR_BACKEND')=='dml')
    selected=[candidates[i] for i in pending]
    ranges=ranges_from_indices(i for c in selected for i in candidate_indices(c,2))
    token=hashlib.sha256(json.dumps({'source':cache['source'],'bounds':ranges,'native':native['signature']},sort_keys=True).encode()).hexdigest()[:12]
    upgraded_samples=checkpoint.parent/('combat-outcome-2hz-'+token)
    sample_with_resume(source,upgraded_samples,2,cuda,frame_ranges=ranges,**({'cpu_threads':threads} if threads else {}))
    upgraded_cache={**cache,'fps':2,'rows':[],'locale_reference_rows':cache['rows']}
    upgraded=inspect_combat_outcomes(upgraded_cache,upgraded_samples,selected,profile,
        checkpoint.with_name(checkpoint.stem+'-2hz.json'),_allow_upgrade=False)
    decisions=[dict(d) for d in native['decisions']]
    for d in upgraded['decisions']:
        original=pending[d['candidate_index']]; decisions[original]={**d,'candidate_index':original}
    report={**upgraded,'source':cache['source'],'decisions':decisions,'scan_fps':cache['fps'],'upgrade_fps':2,
        'signature':hashlib.sha256((native['signature']+upgraded['signature']).encode()).hexdigest(),
        'stats':{key:native['stats'].get(key,0)+upgraded['stats'].get(key,0) for key in native['stats']}}
    report['stats']['extra_sample_frames']+=sum(b-a+1 for a,b in ranges)
    write_json(checkpoint,report); return report


def filter_combat_outcomes(candidates,report):
    kept=[]; rejected=[]; review=[]
    for decision in report['decisions']:
        candidate=dict(candidates[decision['candidate_index']])
        candidate['own_result_filter']=decision
        candidate['classification']=decision['status']
        if decision['status']=='kept': kept.append(candidate)
        elif decision['status']=='rejected': rejected.append(candidate)
        else:
            candidate['review_reason']=decision['reason']; review.append(candidate)
    return kept,rejected,review
