"""用同一提示的原生裁片和实际 CTC 空白复核拉丁词边界。"""
import copy
import hashlib
import itertools
import json
import math
import re
import statistics

import cv2
import numpy as np

VERSION='cross-pts-latin-words-v1'
WORD_MODEL_SHAS=('e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318',
    'c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8')
_WORD=r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*'
_CLAN=r'\[[A-Za-z0-9]{1,6}\]'


def supports_word_spacing(name):
    """受证据门禁支持的文字语法；头部标签与词内连字符须保留原样复核。"""
    return bool(isinstance(name,str) and len(name)<=48 and re.fullmatch(r'(?:'+_CLAN+r' *)?'+_WORD+r'(?: +'+_WORD+r')*',name))


def _word_valid(name,first=False):
    return isinstance(name,str) and bool(re.fullmatch((r'(?:'+_CLAN+r'(?:'+_WORD+r')?|'+_WORD+r')') if first else _WORD,name))


def _boundary_clan_valid(boundary):
    return 'clan_tag' not in boundary or bool(isinstance(boundary['clan_tag'],str) and re.fullmatch(r'[A-Za-z0-9]{1,6}',boundary['clan_tag']))


def _spacing_tokens(tokens):
    return supports_word_spacing(''.join(token['character'] for token in tokens))


def _number(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _json(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def _hash(value):return hashlib.sha256(_json(value).encode()).hexdigest()


def _box(value):
    return isinstance(value,(list,tuple)) and len(value)==4 and all(_number(n) for n in value) and value[2]>value[0] and value[3]>value[1]


def _source(value):
    if not isinstance(value,dict) or not isinstance(value.get('path'),str) or not value['path']:return None
    size=value.get('size');stamp=value.get('mtime_ns',value.get('mtime_ms'))
    if not isinstance(size,int) or isinstance(size,bool) or size<0 or not isinstance(stamp,int) or isinstance(stamp,bool) or stamp<0:return None
    return value['path'].replace('\\','/').casefold(),size,stamp//1000000 if 'mtime_ns' in value else stamp


def _foreground(image):
    b,g,r=cv2.split(image.astype(np.int16));red=np.maximum(0,r-np.maximum(g,b)).astype(np.float32)
    red=np.maximum(0,red-cv2.morphologyEx(red,cv2.MORPH_OPEN,np.ones((7,7),np.uint8)))
    peak=float(red.max());threshold=max(20.,peak*.25)
    _,_,stats,_=cv2.connectedComponentsWithStats((red>=threshold).astype(np.uint8))
    letters=[s for s in stats[1:] if s[3]>=image.shape[0]*.3 and s[4]>=8 and s[2]<=image.shape[0]*1.8]
    if peak>=20 and len(letters)>=2:return red,{'peak':peak,'threshold':threshold,'letter_components':len(letters)}
    # 助攻姓名也会使用白/灰色。只对中性亮字的现有笔画计算空白，
    # 原始 BGR 裁片仍原样送给两套文字模型。
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY).astype(np.float32)
    low_sat=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)[:,:,1]<=70
    neutral=np.maximum(0,gray-cv2.morphologyEx(gray,cv2.MORPH_OPEN,np.ones((7,7),np.uint8)))
    neutral=np.where(low_sat,neutral,0).astype(np.float32)
    peak=float(neutral.max());threshold=max(20.,peak*.25)
    _,_,stats,_=cv2.connectedComponentsWithStats((neutral>=threshold).astype(np.uint8))
    letters=[s for s in stats[1:] if s[3]>=image.shape[0]*.3 and s[4]>=8 and s[2]<=image.shape[0]*1.8]
    if peak<20 or len(letters)<2:return None
    return neutral,{'peak':peak,'threshold':threshold,'letter_components':len(letters),'method':'neutral_luma_highpass'}


def prepare_probes(probes):
    """最多六张输入，只复制最多三张原生裁片；此阶段不建模型。"""
    if not isinstance(probes,(list,tuple)) or not 2<=len(probes)<=6:return []
    valid=[];identities=set()
    for probe in probes:
        if not isinstance(probe,dict):return []
        try:identity=(_source(probe.get('source')),_json(probe['event_key']),probe['phase'])
        except (KeyError,TypeError,ValueError):return []
        if identity[0] is None or not isinstance(identity[2],str) or not identity[2]:return []
        identities.add(identity)
        name=probe.get('name','');boundary=probe.get('boundary') or {};box=boundary.get('box');anchor=boundary.get('prefix_box');image=probe.get('image')
        if not _number(probe.get('confidence')) or not 0<=probe['confidence']<=1:continue
        if not supports_word_spacing(name):continue
        if not _boundary_clan_valid(boundary) or boundary.get('prefix_anchor')!='template' or boundary.get('method')!='native_ctc_name_crop' or not _box(box) or not _box(anchor) or anchor[2]+1!=box[0]:continue
        if not isinstance(image,np.ndarray) or image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3:continue
        height,width=image.shape[:2]
        if not 8<=height<=128 or not 20<=width<=1024 or [width,height]!=[box[2]-box[0],box[3]-box[1]]:continue
        if not re.fullmatch(r'[a-f0-9]{64}',str(probe.get('crop_sha256',''))) or hashlib.sha256(image.tobytes()).hexdigest()!=probe['crop_sha256']:continue
        second=probe.get('native_pts');requested=probe.get('requested_time');bounds=probe.get('context_bounds')
        if not _number(second) or not _number(requested) or not isinstance(bounds,(list,tuple)) or len(bounds)!=2 or not all(_number(n) and n>=0 for n in bounds):continue
        if not bounds[0]<=requested<=second<bounds[1] or not second-requested<.15:continue
        foreground=_foreground(image)
        if foreground is None:continue
        item={key:copy.deepcopy(value) for key,value in probe.items() if key!='image'}
        item['image']=image;item['_red'],item['_foreground']=foreground
        valid.append(item)
    if len(identities)!=1:return []
    unique={}
    for probe in valid:
        second=probe['native_pts'];confidence=probe.get('confidence',0)
        if not _number(confidence):confidence=0
        if second not in unique or confidence>unique[second].get('confidence',0):unique[second]=probe
    # 一张高分但无法与其余裁片组成原生两帧证据的图，不能挤掉可用伙伴。
    # 最多六选三，只比较已有锚点/PTS/尺寸，不提前调用 OCR。
    candidates=list(unique.values())
    if len(candidates)<2:return []
    def strength(group):
        return (sum(_pair_scope(pair) for pair in itertools.combinations(group,2)),sum(p['confidence'] for p in group),min(p['confidence'] for p in group))
    selected=max(itertools.combinations(candidates,min(3,len(candidates))),key=strength,default=())
    if not selected or strength(selected)[0]==0:return []
    selected=sorted(selected,key=lambda p:p['confidence'],reverse=True)
    for item in selected:item['image']=item['image'].copy()
    return selected if len(selected)>=2 else []


def _tokens_valid(tokens,width):
    if not isinstance(tokens,list) or not tokens:return False
    previous=-1.
    for token in tokens:
        if not isinstance(token,dict) or not isinstance(token.get('character'),str) or len(token['character'])!=1:return False
        left,right,confidence=token.get('left'),token.get('right'),token.get('confidence')
        if not all(_number(n) for n in [left,right,confidence]) or not 0<=left<right<=width or left<previous or not 0<=confidence<=1:return False
        previous=right
    return True


def _pair_scope(pair):
    if pair[0]['context_bounds']!=pair[1]['context_bounds'] or not 0<abs(pair[0]['native_pts']-pair[1]['native_pts'])<=1.1:return False
    if abs(pair[0]['image'].shape[0]-pair[1]['image'].shape[0])>2:return False
    a,b=[p['boundary']['prefix_box'] for p in pair]
    return abs(a[0]-b[0])<=4 and abs(a[1]-b[1])<=3 and abs((a[2]-a[0])-(b[2]-b[0]))<=3


def _space_window(midpoint,width,height):
    radius=max(3,round(height*.22))
    return max(0,round(midpoint)-radius),min(width,round(midpoint)+radius)


def _plan(pair):
    if not _pair_scope(pair):return None
    observations=[]
    for probe in pair:
        height,width=probe['image'].shape[:2];curve=probe['_red'][height//5:max(1,height*4//5)].max(axis=0)
        for full in probe['_full']:
            tokens=full['tokens']
            if not _spacing_tokens(tokens):continue
            for i,token in enumerate(tokens):
                if token['character']!=' ' or i==0 or i==len(tokens)-1:continue
                midpoint=(tokens[i-1]['right']+tokens[i+1]['left'])/2
                left,right=_space_window(midpoint,width,height)
                if right-left<2:continue
                cut=left+int(((curve[left:right-1]+curve[left+1:right])*.5).argmin())+1
                observations.append({'native_pts':probe['native_pts'],'model':full['model'],'token_index':i,'ctc_midpoint':midpoint,'source_x':probe['boundary']['box'][0]+cut})
    clusters=[]
    for value in sorted(observations,key=lambda x:x['source_x']):
        if clusters and abs(value['source_x']-statistics.median(v['source_x'] for v in clusters[-1]))<=3:clusters[-1].append(value)
        else:clusters.append([value])
    proof=[];cuts=[[],[]]
    for cluster in clusters:
        # 单模型读到的内部空白仍是未解决的边界反证；不能将其丢掉后，
        # 用更宽裁片读出的连字证明原姓名没有空格。尝试另一原生帧组合。
        if len({(v['native_pts'],v['model']) for v in cluster})<2:return None
        source_x=round(statistics.median(v['source_x'] for v in cluster));valleys=[]
        for index,probe in enumerate(pair):
            curve=probe['_red'].max(axis=0);center=source_x-probe['boundary']['box'][0];left=max(0,center-3);right=min(len(curve),center+3)
            if right-left<2:return None
            x=left+int(curve[left:right].argmin())
            if not curve[x]<probe['_foreground']['threshold']:return None
            cuts[index].append(x+1);valleys.append({'native_pts':probe['native_pts'],'cut':x+1,'valley_x':x,'signal':float(curve[x])})
        proof.append({'source_x':source_x,'actual_spaces':cluster,'valleys':valleys})
    if not 1<=len(proof)<=8:return None
    for probe,values in zip(pair,cuts):
        edges=[0,*values,probe['image'].shape[1]]
        if any(right-left<4 for left,right in zip(edges,edges[1:])):return None
    return cuts,proof


def _agreement(models,first=False):
    if not isinstance(models,list) or len(models)!=2:return None
    candidates={v['name'] for v in models[0] if _word_valid(v.get('name'),first) and _number(v.get('confidence')) and v['confidence']>=.8 and any(w.get('name')==v['name'] and _number(w.get('confidence')) and w['confidence']>=.8 and max(v['confidence'],w['confidence'])>=.9 for w in models[1])}
    if len(candidates)!=1:return None
    word=next(iter(candidates));return word,min(max(v['confidence'] for v in model if v.get('name')==word and _number(v.get('confidence'))) for model in models)


def _full_proof(fulls,words,width,height):
    name=''.join(w['name'] for w in words);proof=[]
    for full in fulls:
        if full['model'] not in WORD_MODEL_SHAS or not _tokens_valid(full['tokens'],width):continue
        tokens=full['tokens']
        if not _spacing_tokens(tokens):continue
        letters=[t for t in tokens if not t['character'].isspace()]
        if ''.join(t['character'] for t in letters)!=name or not letters:continue
        if letters[0]['confidence']<.8 or letters[-1]['confidence']<.8 or letters[0]['left']>height*.5 or width-letters[-1]['right']>height*.5:continue
        cursor=0;ranges=[]
        for word in words:
            run=letters[cursor:cursor+len(word['name'])];cursor+=len(word['name']);left,_,right,_=word['box']
            if not run or run[0]['left']<left-3 or run[-1]['right']>right+3:break
            ranges.append([run[0]['left'],run[-1]['right']])
        if len(ranges)==len(words):proof.append({'model':full['model'],'actual_text':''.join(t['character'] for t in tokens),'tokens':copy.deepcopy(tokens),'word_ranges':ranges})
    return proof


def _binding(source,event_key,phase,frame):
    return {'source':copy.deepcopy(source),'event_key':copy.deepcopy(event_key),'phase':phase,'native_pts':frame['native_pts'],'requested_time':frame['requested_time'],
        'context_bounds':list(frame['context_bounds']),'boundary_sha256':_hash(frame['boundary']),'crop_sha256':frame['crop_sha256']}


def refine_prepared(probes,primary,english,independent,*,ctc,foreground_views):
    """复用当前读者；最多三张完整裁片、三组两帧组合，不读取录像。"""
    readers=[primary,english,independent];labels=['primary',*WORD_MODEL_SHAS]
    for probe in probes:
        probe['_full']=[{'model':label,'tokens':ctc(probe['image'],reader)} for label,reader in zip(labels,readers)]
        if any(not _tokens_valid(full['tokens'],probe['image'].shape[1]) for full in probe['_full']):return []
    cache={}
    for pair in itertools.islice(itertools.combinations(probes,2),3):
        plan=_plan(pair)
        if plan is None:continue
        cuts,cut_proof=plan;frames=[]
        for probe,values in zip(pair,cuts):
            height,width=probe['image'].shape[:2];edges=[0,*values,width];words=[]
            for left,right in zip(edges,edges[1:]):
                key=(probe['native_pts'],probe['crop_sha256'],left,right)
                if key not in cache:
                    patch=probe['image'][:,left:right];background=tuple(int(v) for v in np.median(np.concatenate([patch[:3],patch[-3:]]),axis=(0,1)))
                    views=[patch,*[cv2.copyMakeBorder(patch,0,0,pad,pad,cv2.BORDER_CONSTANT,value=background) for pad in [2,4]],*foreground_views(patch)]
                    cache[key]=[[{'name':text,'confidence':float(confidence)} for text,confidence in reader(views)[0]] for reader in [english,independent]]
                models=cache[key];agreed=_agreement(models,first=not words)
                if agreed is None:break
                name,confidence=agreed;words.append({'name':name,'confidence':confidence,'box':[left,0,right,height],'models':copy.deepcopy(models)})
            if len(words)!=len(edges)-1:break
            full=_full_proof(probe['_full'],words,width,height)
            if not full:break
            frames.append({'native_pts':probe['native_pts'],'requested_time':probe['requested_time'],'context_bounds':list(probe['context_bounds']),
                'boundary':copy.deepcopy(probe['boundary']),'crop_sha256':probe['crop_sha256'],'crop_size':[width,height],
                'foreground':probe['_foreground'],'cuts':values,'words':words,'full_crop_observations':copy.deepcopy(probe['_full']),'independent_full_crop':full})
        if len(frames)!=2 or ' '.join(w['name'] for w in frames[0]['words'])!=' '.join(w['name'] for w in frames[1]['words']):continue
        spelling=' '.join(w['name'] for w in frames[0]['words'])
        if not supports_word_spacing(spelling):continue
        packet={'version':VERSION,'source':copy.deepcopy(pair[0]['source']),'event_key':copy.deepcopy(pair[0]['event_key']),'phase':pair[0]['phase'],
            'word_models':list(WORD_MODEL_SHAS),'frames':frames,'cut_proof':cut_proof}
        digest=_hash(packet);result=[]
        for frame in frames:
            result.append({'name':spelling,**({'raw_name':spelling} if re.match(_CLAN,spelling) else {}),'confidence':min(w['confidence'] for w in frame['words']),'time':frame['native_pts'],'requested_time':frame['requested_time'],'frame':str(frame['native_pts']),
                'boundary_evidence':copy.deepcopy(frame['boundary']),'word_evidence':copy.deepcopy(frame['words']),
                'native_word_binding':_binding(packet['source'],packet['event_key'],packet['phase'],frame),
                'cross_pts_word_evidence':{'packet':copy.deepcopy(packet),'packet_sha256':digest}})
        if all(complete_cross_pts_words(read) for read in result):return result
    return []


def complete_cross_pts_words(read):
    """完整验证两 PTS 实际词证据；全裁片 v5 是边界佐证，不是第三模型票。"""
    try:return _complete(read)
    except (KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError):return False


def _complete(read):
    if not _number(read.get('time')) or not _number(read.get('confidence')):return False
    evidence=read.get('cross_pts_word_evidence') or {};packet=evidence.get('packet') or {}
    if packet.get('version')!=VERSION or evidence.get('packet_sha256')!=_hash(packet) or packet.get('word_models')!=list(WORD_MODEL_SHAS):return False
    if _source(packet.get('source')) is None or not packet.get('event_key') or not isinstance(packet.get('phase'),str) or not packet['phase']:return False
    frames=packet.get('frames')
    if not isinstance(frames,list) or len(frames)!=2:return False
    points=[frame['native_pts'] for frame in frames]
    if not all(_number(n) for n in points) or not 0<abs(points[0]-points[1])<=1.1:return False
    if frames[0]['context_bounds']!=frames[1]['context_bounds']:return False
    spellings=[]
    for frame in frames:
        second,requested,bounds=frame['native_pts'],frame['requested_time'],frame['context_bounds']
        if not _number(requested) or len(bounds)!=2 or not all(_number(n) and n>=0 for n in bounds) or not bounds[0]<=requested<=second<bounds[1] or not second-requested<.15:return False
        width,height=frame['crop_size'];boundary=frame['boundary'];box=boundary['box'];anchor=boundary['prefix_box']
        if not _box(box) or not _box(anchor) or boundary.get('method')!='native_ctc_name_crop' or boundary.get('prefix_anchor')!='template' or not _boundary_clan_valid(boundary) or anchor[2]+1!=box[0] or [width,height]!=[box[2]-box[0],box[3]-box[1]]:return False
        if not 20<=width<=1024 or not 8<=height<=128 or not re.fullmatch(r'[a-f0-9]{64}',frame['crop_sha256']):return False
        foreground=frame['foreground']
        if foreground.get('method') not in [None,'neutral_luma_highpass']:return False
        if not _number(foreground['peak']) or not 20<=foreground['peak']<=255 or foreground['threshold']!=max(20.,foreground['peak']*.25) or foreground['letter_components']<2:return False
        cuts=frame['cuts']
        if not isinstance(cuts,list) or not 1<=len(cuts)<=8 or any(not isinstance(x,int) or isinstance(x,bool) for x in cuts):return False
        edges=[0,*cuts,width]
        if any(right-left<4 for left,right in zip(edges,edges[1:])) or len(frame['words'])!=len(edges)-1:return False
        for index,(word,left,right) in enumerate(zip(frame['words'],edges,edges[1:])):
            if word['box']!=[left,0,right,height] or any(not isinstance(v,int) or isinstance(v,bool) for v in word['box']):return False
            agreed=_agreement(word['models'],first=index==0)
            if agreed is None or (word['name'],word['confidence'])!=agreed:return False
        spelling=' '.join(w['name'] for w in frame['words'])
        if not supports_word_spacing(spelling):return False
        spellings.append(spelling)
        observations=frame['full_crop_observations']
        if [full['model'] for full in observations]!=['primary',*WORD_MODEL_SHAS] or any(not _tokens_valid(full['tokens'],width) for full in observations):return False
        if frame['independent_full_crop']!=_full_proof(observations,frame['words'],width,height) or not frame['independent_full_crop']:return False
    if spellings[0]!=spellings[1]:return False
    spelling=spellings[0]
    if read.get('name')!=spelling:
        from player_names import strip_clan_tag
        if not re.match(_CLAN,spelling) or read.get('raw_name')!=spelling or read.get('name')!=strip_clan_tag(spelling):return False
    elif read.get('raw_name',spelling)!=spelling:return False
    a,b=[frame['boundary']['prefix_box'] for frame in frames]
    if abs(a[0]-b[0])>4 or abs(a[1]-b[1])>3 or abs((a[2]-a[0])-(b[2]-b[0]))>3 or abs(frames[0]['crop_size'][1]-frames[1]['crop_size'][1])>2:return False
    proof=packet['cut_proof']
    if len(proof)!=len(frames[0]['cuts']) or len(proof)!=len(frames[1]['cuts']):return False
    covered_spaces=set()
    for index,cut in enumerate(proof):
        supports=cut['actual_spaces'];seen=set()
        for support in supports:
            frame=next((f for f in frames if f['native_pts']==support['native_pts']),None)
            if frame is None:return False
            full=next((v for v in frame['full_crop_observations'] if v['model']==support['model']),None)
            if full is None:return False
            i=support['token_index'];tokens=full['tokens']
            if not isinstance(i,int) or isinstance(i,bool) or not 0<i<len(tokens)-1 or tokens[i]['character']!=' ':return False
            if support['ctc_midpoint']!=(tokens[i-1]['right']+tokens[i+1]['left'])/2 or abs(support['source_x']-cut['source_x'])>3:return False
            midpoint=support['ctc_midpoint'];width,height=frame['crop_size'];local=support['source_x']-frame['boundary']['box'][0]
            left,right=_space_window(midpoint,width,height)
            if not left<local<right:return False
            seen.add((support['native_pts'],support['model']))
            covered_spaces.add((support['native_pts'],support['model'],i))
        if len(seen)<2 or cut['source_x']!=round(statistics.median(s['source_x'] for s in supports)):return False
        if len(cut['valleys'])!=2:return False
        for frame,valley in zip(frames,cut['valleys']):
            if valley['native_pts']!=frame['native_pts'] or valley['cut']!=frame['cuts'][index] or valley['valley_x']+1!=valley['cut']:return False
            if not _number(valley['signal']) or not 0<=valley['signal']<frame['foreground']['threshold'] or abs(frame['boundary']['box'][0]+valley['valley_x']-cut['source_x'])>3:return False
    # 完整裁片里真实发出的空白必须逐个被保留在两帧边界证明中。
    # 只比去空格后的字母会认证 BACKWITH 之类的错误吞词。
    actual_spaces=set()
    for frame in frames:
        for full in frame['full_crop_observations']:
            tokens=full['tokens']
            if not _spacing_tokens(tokens):continue
            actual_spaces.update((frame['native_pts'],full['model'],i) for i,token in enumerate(tokens) if token['character']==' ' and 0<i<len(tokens)-1)
    if covered_spaces!=actual_spaces:return False
    match=[frame for frame in frames if read.get('time')==frame['native_pts']]
    if len(match)!=1:return False
    frame=match[0]
    return bool(read.get('frame')==str(frame['native_pts']) and read.get('requested_time')==frame['requested_time'] and read.get('confidence')==min(w['confidence'] for w in frame['words']) and read.get('boundary_evidence')==frame['boundary'] and read.get('word_evidence')==frame['words'] and read.get('native_word_binding')==_binding(packet['source'],packet['event_key'],packet['phase'],frame))
