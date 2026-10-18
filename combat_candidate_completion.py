"""原生邻帧补证单粗帧候选；不改已确认路径、姓名、动作、时间或计数。"""
from pathlib import Path
from functools import lru_cache
import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import re
import sys

import cv2
import numpy as np

from apex_clipper import fingerprint,probe,inactive_view
from app_cancel import check_cancel
from combat_outcome_reader import (BASE as COMBAT_BASE,KINDS,PARSER_VERSION,TARGET_PREFIX,PrefixGate,load_profile,
    recognize_frame,parse_result_line,is_known_dialogue,_same_line_gate)
from hud_enrichment import native_frames
from hud_layout import outcome_profile
from outcome_reader import friend_view,spectator_view
from player_names import strip_clan_tag
from target_name_reader import ctc_evidence
from weapon_reader import new_engine,MODEL_PATH as PRIMARY_MODEL_PATH,MODEL_SHA as PRIMARY_MODEL_SHA

VERSION='native-event-completion-v1'
SAMPLE_OFFSETS=(-.08,.08,.24)
MIN_TEMPLATE_SCORE=.80
MIN_PREFIX_PERSISTENCE=.75
MAX_ASSOCIATION_GAP=1.1


def _recipe_file(path):
    path=Path(path)
    if not path.is_file():return {'missing':True}
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'sha256':digest,'size':path.stat().st_size}


def _module_file(name):
    module=sys.modules.get(name);path=getattr(module,'__file__',None)
    if path:return Path(path)
    spec=importlib.util.find_spec(name)
    return Path(spec.origin) if spec and spec.origin else Path(__file__).resolve().parent/(name+'.py')


@lru_cache(maxsize=1)
def recipe():
    """首次请求时只读源码、配置和权重身份；进程内缓存，不创建 OCR 会话。"""
    names=['combat_candidate_completion','combat_outcome_reader','target_name_reader','latin_word_boundaries','weapon_reader',
        'gpu_ocr_backend','engine_pool','gpu_load','hud_layout','hud_enrichment','outcome_reader',
        'apex_clipper','player_names','image_io']
    files={'source/'+name:_recipe_file(_module_file(name)) for name in names}
    base=Path(COMBAT_BASE)
    for name in ['combat-outcome-profile.json','combat-outcome-fixtures.local.json']:
        files['config/'+name]=_recipe_file(base/name)
    for entry in load_profile().get('prefix_templates',[]):
        for field in ['path','gray','mask']:
            if entry.get(field):files['prefix/'+entry[field]]=_recipe_file(base/entry[field])
    files['weights/primary-recognizer']={'declared_sha256':PRIMARY_MODEL_SHA,**_recipe_file(PRIMARY_MODEL_PATH)}
    files['weights/latin-recognizer']=_recipe_file(base/'models/numeric_rec_en_v4.onnx')
    rapid=_module_file('rapidocr_onnxruntime').parent
    config=rapid/'config.yaml';files['rapidocr/config.yaml']=_recipe_file(config)
    if config.is_file():
        import yaml
        settings=yaml.safe_load(config.read_text('utf-8')) or {}
        detector=settings.get('Det',{}).get('model_path')
        if detector:files['weights/detector']=_recipe_file(rapid/detector)
    for name in ['main.py','ch_ppocr_det/text_detect.py','ch_ppocr_det/utils.py',
                 'ch_ppocr_rec/text_recognize.py','ch_ppocr_rec/utils.py','utils/infer_engine.py']:
        files['rapidocr/'+name]=_recipe_file(rapid/name)
    runtime={}
    for name in ['rapidocr-onnxruntime','onnxruntime','onnxruntime-directml','opencv-python','opencv-python-headless','numpy','av']:
        try:runtime[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:runtime[name]=None
    payload={'version':VERSION,'files':files,'runtime':runtime}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return VERSION+':'+digest


def _identity(event):
    return event.get('kind'),event.get('time'),tuple(event.get('box') or [])


def _target(text):
    return re.sub(r'\s+',' ',strip_clan_tag(text)).strip().casefold()


def _native_name_support(event,source,identity):
    """只比较当前源图已读出的完整姓名；不向 OCR 提供名称先验。"""
    provenance=event.get('native_name_source') or {}
    if (event.get('native_name_status')!='confirmed' or event.get('native_name_version')!=PARSER_VERSION or
        event.get('target_method')!='two_frame_native_name_consensus' or
        str(provenance.get('path','')).replace('\\','/').casefold()!=str(source).replace('\\','/').casefold() or
        provenance.get('size')!=identity['size'] or provenance.get('mtime_ms')!=identity['mtime_ns']//1000000):return None
    name=_target(event.get('target_text') or '')
    if not name:return None
    reads=[]
    for read in event.get('native_name_evidence',[]):
        second=read.get('time');boundary=read.get('boundary_evidence') or {}
        box=boundary.get('prefix_box') or boundary.get('box')
        if (_target(read.get('name') or '')!=name or read.get('confidence',0)<.8 or
            not isinstance(second,(int,float)) or not math.isfinite(second) or
            not isinstance(box,(list,tuple)) or len(box)!=4 or
            not all(isinstance(n,(int,float)) and math.isfinite(n) for n in box) or box[2]<=box[0] or box[3]<=box[1]):continue
        reads.append({'native_pts':second,'box':list(box),'anchor':'prefix' if boundary.get('prefix_box') else 'name_crop'})
    if len({read['native_pts'] for read in reads})<2:return None
    return {'current_target':name,'reads':reads}


def _association_conflicts(candidate,context,source,identity):
    """相邻同目标/原生位置只说明独立性未建立，不能据此断言或合并重复轨迹。"""
    own=_native_name_support(candidate,source,identity)
    if own is None:return []
    conflicts=[]
    for neighbour in context:
        if (_identity(neighbour)==_identity(candidate) or neighbour.get('confirmed') is not True or
            neighbour.get('ownership')!='self' or neighbour.get('kind')!=candidate['kind'] or
            neighbour.get('action')!=candidate.get('action')):continue
        gap=max(0.,float(candidate['time'])-float(neighbour.get('last_seen',neighbour['time'])),
            float(neighbour['time'])-float(candidate.get('last_seen',candidate['time'])))
        if gap>MAX_ASSOCIATION_GAP:continue
        other=_native_name_support(neighbour,source,identity)
        if other is None or own['current_target']!=other['current_target']:continue
        geometry=None
        for left in own['reads']:
            for right in other['reads']:
                if left['anchor']!=right['anchor']:continue
                a=left['box'];b=right['box'];font=max(a[3]-a[1],b[3]-b[1])
                if abs(a[0]-b[0])<=max(10.,font*.5) and abs((a[1]+a[3]-b[1]-b[3])/2)<=max(10.,font*.3):
                    geometry={'candidate':left,'confirmed_neighbour':right};break
            if geometry:break
        if geometry is None:continue
        conflicts.append({'reason':'independent_event_not_proven','duplicate_not_established':True,
            'kind':candidate['kind'],'action':candidate.get('action'),'current_target':own['current_target'],
            'candidate':{'time':candidate['time'],'last_seen':candidate.get('last_seen',candidate['time']),
                'native_pts':sorted({read['native_pts'] for read in own['reads']})},
            'confirmed_neighbour':{'time':neighbour['time'],'last_seen':neighbour.get('last_seen',neighbour['time']),
                'box':neighbour.get('box'),'prefix_box':neighbour.get('prefix_box'),
                'native_pts':sorted({read['native_pts'] for read in other['reads']})},
            'event_interval_gap':gap,'max_association_gap':MAX_ASSOCIATION_GAP,'native_geometry':geometry,
            'missing_evidence':'No disappearance, new onset, or separate simultaneous row establishes an independent event.'})
    return conflicts


def _near_candidate(event,candidate,size):
    hint=candidate.get('box')
    if not hint:return False
    width,height=size
    sw,sh=candidate.get('sample_size') or [1280,1280*height/width]
    x1,y1,x2,y2=[float(value)*([width/sw,height/sh][index%2]) for index,value in enumerate(hint)]
    box=event['box'];font=max(1.,y2-y1)
    return abs((box[1]+box[3]-y1-y2)/2)<=max(10.,font) and abs(box[0]-x1)<=max(12.,font*.75)


def _english_prefix(image,event,reader):
    """实际完整行 CTC 划出前缀像素；它不是独立英文静态模板。"""
    if reader is None:return None
    x1,y1,x2,y2=event['box'];height,width=image.shape[:2]
    px=max(0,int(x1)-4);py=max(0,int(y1)-3)
    patch=image[py:min(height,int(y2)+4),px:min(width,int(x2)+5)]
    if not patch.size:return None
    tokens=ctc_evidence(patch,reader)
    if not tokens or any(len(token['character'])!=1 for token in tokens):return None
    text=''.join(token['character'] for token in tokens);prefix=TARGET_PREFIX.match(text);parsed=parse_result_line(text)
    if not prefix or not parsed or parsed['kind']!=event['kind'] or parsed['action']!=event['action'] or not prefix[0].isascii():return None
    end=prefix.end()
    if not 0<end<len(tokens):return None
    letters=[token['confidence'] for token in tokens[:end] if token['character'].isalpha()]
    if not letters or float(np.mean(letters))<.85:return None
    right=px+round((tokens[end-1]['right']+tokens[end]['left'])/2)
    box=[max(0,int(x1)-2),max(0,int(y1)-2),min(width,right),min(height,int(y2)+3)]
    crop=image[box[1]:box[3],box[0]:box[2]]
    if crop.shape[0]<8 or crop.shape[1]<20:return None
    gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY).astype(np.float32)
    signal=np.maximum(0,gray-cv2.morphologyEx(gray,cv2.MORPH_OPEN,np.ones((7,7),np.uint8)))
    if np.count_nonzero(signal>=20)<20:return None
    return ({'type':'english_complete_prefix_grammar','ctc_prefix':prefix[0],
        'ctc_prefix_mean_letter_confidence':float(np.mean(letters)),'box':box,
        'crop_sha256':hashlib.sha256(crop.tobytes()).hexdigest(),
        'role':'grammar supplies semantics; native pixels only corroborate persistence'},signal)


def _prefix_agreement(left,right):
    a=left['_prefix_pixels'];b=right['_prefix_pixels'];best=None
    if abs(a.shape[0]-b.shape[0])>4 or abs(a.shape[1]-b.shape[1])>max(6,a.shape[1]*.08):return None
    for dy in range(-3,4):
        for dx in range(-3,4):
            x1=max(3,dx+3);y1=max(3,dy+3)
            x2=min(a.shape[1]-3,b.shape[1]+dx-3);y2=min(a.shape[0]-3,b.shape[0]+dy-3)
            if x2-x1<a.shape[1]*.80 or y2-y1<a.shape[0]*.60:continue
            aa=a[y1:y2,x1:x2];bb=b[y1-dy:y2-dy,x1-dx:x2-dx]
            aa=aa-float(aa.mean());bb=bb-float(bb.mean())
            denominator=float(np.sqrt(np.sum(aa*aa)*np.sum(bb*bb)))
            if denominator<=0:continue
            score=float(np.sum(aa*bb)/denominator)
            if best is None or score>best['score']:best={'score':score,'dx':dx,'dy':dy}
    return best


def _classify(image,candidate,profile,gate,engine):
    inactive=inactive_view(image);friend=friend_view(image,inactive);spectator=spectator_view(image,inactive)
    own={'inactive':inactive,'friend_spectate':friend,'spectator':spectator}
    if inactive or friend or spectator:return {'own_view':own,'accepted':False,'reason':'excluded_view'},None
    matches=gate.inspect(image);read=recognize_frame(image,profile,engine,prefix_matches=matches)
    choices=[]
    for event in read['events']:
        parsed=parse_result_line(event.get('text',''))
        if not parsed or is_known_dialogue(event['text']) or parsed['kind']!=candidate['kind'] or parsed['action']=='unknown':continue
        if candidate.get('action') in {'knock','elimination'} and parsed['action']!=candidate['action']:continue
        if not _near_candidate(event,candidate,[image.shape[1],image.shape[0]]):continue
        target=_target(parsed.get('target_text',''))
        if not target:continue
        english=bool(re.match(r'^(?:ASSIST|KNOCKED DOWN|ELIMINATED)\b',parsed['text'],re.I))
        confidence=float(event.get('confidence',0));score=_same_line_gate(event,matches)
        record={'kind':parsed['kind'],'action':parsed['action'],'text':event['text'],'box':event['box'],
            'prefix_confidence':confidence,'text_confidence':float(event.get('text_confidence',confidence)),
            'association_target':target,'name_accuracy_verified':False,'own_view':own,
            'same_row_fixed_template_score':score,'accepted':False}
        pixels=None
        if english and confidence>=.90:
            proof=_english_prefix(image,event,getattr(engine,'text_rec',None))
            if proof:record['prefix_evidence'],pixels=proof;record['accepted']=True
        elif not english and confidence>=.85 and score>=MIN_TEMPLATE_SCORE:
            supported=[match for match in matches if match['kind']==parsed['kind'] and match['score']>=MIN_TEMPLATE_SCORE and abs((match['box'][1]+match['box'][3]-event['box'][1]-event['box'][3])/2)<=10 and abs(match['box'][0]-event['box'][0])<=10]
            if supported:
                record['prefix_evidence']={'type':'same_row_fixed_prefix_template','matches':supported};record['same_row_fixed_template_score']=max(match['score'] for match in supported);record['accepted']=True
        choices.append((record,pixels))
    accepted=[choice for choice in choices if choice[0]['accepted']]
    if len(accepted)!=1:return {'own_view':own,'accepted':False,'reason':'ambiguous_or_weak_classification','raw_lines':read['lines'],'raw_events':read['events'],'prefix_matches':matches},None
    record,pixels=accepted[0];record['raw_lines']=read['lines'];record['prefix_matches']=matches
    return record,pixels


def _compatible(left,right):
    if left['native_pts']==right['native_pts'] or abs(left['native_pts']-right['native_pts'])>1.1:return None
    if (left['kind'],left['action'],left['association_target'])!=(right['kind'],right['action'],right['association_target']):return None
    if abs((left['box'][1]+left['box'][3]-right['box'][1]-right['box'][3])/2)>10:return None
    a=left['prefix_evidence'];b=right['prefix_evidence']
    if a['type']!=b['type']:return None
    if a['type']=='english_complete_prefix_grammar':
        if abs(a['box'][0]-b['box'][0])>8 or abs(a['box'][1]-b['box'][1])>8:return None
        agreement=_prefix_agreement(left,right)
        if not agreement or agreement['score']<MIN_PREFIX_PERSISTENCE:return None
        return {'type':'english_full_grammar_with_native_prefix_persistence','pixel_agreement':agreement,'min_pixel_persistence':MIN_PREFIX_PERSISTENCE,'not_an_independent_semantic_vote':True}
    return {'type':'two_native_full_grammar_and_fixed_template_observations'}


def complete_candidates(source,events,*,context_events,profile=None,hud_profile=None,on_activity=None):
    """事件时间采用 source 原生时间轴；context_events 必须是同一时间轴的完整列表。

    返回副本，只可能置原 confirmed=False 的本人候选为 confirmed 并保存
    native_event_* 证据。所有姓名字段、kind/action/time/counts 都原样保留。
    """
    result=copy.deepcopy(events)
    pending=[index for index,event in enumerate(events) if event.get('confirmed') is False and event.get('ownership')=='self' and event.get('kind') in KINDS]
    if not pending:return result
    if context_events is None or any(_identity(events[index]) not in {_identity(event) for event in context_events} for index in pending):raise ValueError('候选补全需要包含所选事件的完整相邻事件上下文')
    current_recipe=recipe()
    source=Path(source);before=fingerprint(source);metadata,video=probe(source)
    duration=max(float(metadata['format']['duration']),float(video.get('start_time') or 0)+float(video.get('duration') or 0))
    profile=copy.deepcopy(profile or load_profile())
    if hud_profile and hud_profile.get('layout_version'):profile=outcome_profile(hud_profile,profile)
    gate=PrefixGate(profile);engine=None
    try:
        for index in pending:
            candidate=events[index];target=result[index];center=float(candidate['time'])
            previous=max((float(event.get('last_seen',event['time'])) for event in context_events if event.get('kind')==candidate['kind'] and event['time']<center),default=-.03)
            following=min((float(event['time']) for event in context_events if event.get('kind')==candidate['kind'] and event['time']>center),default=duration)
            bounds=[max(0.,previous+.03),min(duration-.03,following-.03)]
            observations=[];positives=[];seen=set();pair=None
            conflicts=_association_conflicts(candidate,context_events,source,before)
            target.pop('native_event_association_conflict',None)
            target.pop('native_event_confirmation',None)
            for offset in [] if conflicts else SAMPLE_OFFSETS:
                check_cancel();requested=round(center+offset,5)
                if not bounds[0]<=requested<bounds[1]:continue
                frame=next(native_frames(source,0,duration,[requested]),None)
                if frame is None:continue
                second,image=frame
                if second in seen:continue
                seen.add(second)
                if not bounds[0]<=second<bounds[1]:observations.append({'requested_time':requested,'native_pts':second,'accepted':False,'reason':'decoded_outside_candidate_context'});continue
                if not 0<=second-requested<.15:observations.append({'requested_time':requested,'native_pts':second,'accepted':False,'reason':'decode_gap'});continue
                if engine is None:engine=new_engine()
                record,pixels=_classify(image,candidate,profile,gate,engine)
                record.update(requested_time=requested,native_pts=second,frame=str(second));observations.append(record)
                if record['accepted']:
                    item={**record,'_prefix_pixels':pixels};positives.append(item)
                    for prior in positives[:-1]:
                        proof=_compatible(prior,item)
                        if proof:pair={'pts':[prior['native_pts'],item['native_pts']],**proof};break
                if on_activity:on_activity({'message':'补证单帧战果候选','candidate_index':index,'native_pts':second,'confirmed':bool(pair)})
                if pair:break
            target.update(native_event_version=VERSION,native_event_recipe=current_recipe,native_event_original_confirmed=False,native_event_status='confirmed' if pair else 'unconfirmed',native_event_evidence=observations,
                native_event_source={'path':str(source),'size':before['size'],'mtime_ms':before['mtime_ns']//1000000},native_event_context_bounds=bounds)
            if conflicts:target['native_event_association_conflict']=conflicts
            if pair:target['confirmed']=True;target['native_event_confirmation']=pair
    finally:
        if fingerprint(source)!=before:raise ValueError('补证战果候选期间原录像发生变化')
    return result
