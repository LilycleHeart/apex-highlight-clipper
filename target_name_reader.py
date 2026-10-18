"""难读的原生战果姓名：独立模型复核与实际字形证据，不使用昵称答案表。"""
from pathlib import Path
from functools import lru_cache
import hashlib
import json
import math
import os
import re
import unicodedata
import urllib.request

import cv2
import numpy as np

from latin_word_boundaries import complete_cross_pts_words

MODEL_PATH=Path(__file__).resolve().parent/'models/name_rec_v5_server.onnx'
MODEL_SHA='e09385400eaaaef34ceff54aeb7c4f0f1fe014c27fa8b9905d4709b65746562a'
MODEL_URL='https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_server.onnx'
LATIN_MODEL_PATH=MODEL_PATH.with_name('name_rec_en_v5.onnx')
LATIN_MODEL_SHA='c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8'
LATIN_MODEL_URL='https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/en_PP-OCRv5_rec_mobile.onnx'


def _digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


@lru_cache(maxsize=8)
def _reader_weight_digest(path,size,mtime_ns):
    return _digest(Path(path))


def _reader_model_sha(reader):
    path=getattr(getattr(reader,'session',None),'model_path',None)
    if not path:return None
    try:
        path=Path(path);stat=path.stat()
        return _reader_weight_digest(str(path.resolve()),stat.st_size,stat.st_mtime_ns)
    except OSError:return None


@lru_cache(maxsize=1)
def name_recipe():
    """绑定逐事件姓名证据的实现和实际权重；不创建模型或下载资源。"""
    from weapon_reader import MODEL_PATH as primary_path
    root=Path(__file__).resolve().parent
    sources=['combat_outcome_reader.py','target_name_reader.py','latin_word_boundaries.py','player_names.py',
        'weapon_reader.py','gpu_ocr_backend.py','engine_pool.py','gpu_load.py','image_io.py']
    values={'source/'+name:_digest(root/name) for name in sources}
    for path in [primary_path,MODEL_PATH,LATIN_MODEL_PATH,root/'models/numeric_rec_en_v4.onnx']:
        try:
            stat=path.stat();digest=_reader_weight_digest(str(path.resolve()),stat.st_size,stat.st_mtime_ns)
        except OSError:digest=None
        values['model/'+path.name]=digest
    return 'native-target-name-recipe-v1:'+hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def ensure_model(*,latin=False):
    """构建时准备并校验；用户运行时不下载。"""
    path,digest,url=(LATIN_MODEL_PATH,LATIN_MODEL_SHA,LATIN_MODEL_URL) if latin else (MODEL_PATH,MODEL_SHA,MODEL_URL)
    return ensure_model_asset(path,digest,url)


def ensure_model_asset(path,digest,url):
    """仅供构建器准备固定权重；识别器不会调用下载入口。"""
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.is_file():
        temporary=path.with_suffix('.part')
        try:
            with urllib.request.urlopen(url,timeout=30) as response,temporary.open('wb') as stream:
                total=0
                while data:=response.read(1024*1024):
                    total+=len(data)
                    if total>100*1024*1024:raise ValueError('姓名复核模型大小异常')
                    stream.write(data)
            if _digest(temporary)!=digest:raise ValueError('姓名复核模型校验失败')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if _digest(path)!=digest:raise ValueError('姓名复核模型校验失败')
    return path


@lru_cache(maxsize=2)
def model_available(*,latin=False):
    path,digest=(LATIN_MODEL_PATH,LATIN_MODEL_SHA) if latin else (MODEL_PATH,MODEL_SHA)
    return path.is_file() and _digest(path)==digest


def ctc_evidence(image,reader):
    """保留实际 CTC 发射、单字置信度及其原图坐标；不提供候选词。"""
    height,width=image.shape[:2];shape=reader.rec_image_shape
    normalized=reader.resize_norm_img(image,max(shape[2]/shape[1],width/height))
    probabilities=reader.session(normalized[None].astype(np.float32))[0][0];tokens=[];previous=0
    for step,index in enumerate(probabilities.argmax(-1)):
        if index and index!=previous:tokens.append([unicodedata.normalize('NFKC',reader.postprocess_op.character[int(index)]),step,step+1,float(probabilities[step,index])])
        elif index and tokens:tokens[-1][2]=step+1
        previous=index
    resized=min(normalized.shape[-1],math.ceil(shape[1]*width/height));factor=normalized.shape[-1]/len(probabilities)*width/resized
    return [{'character':character,'left':start*factor,'right':end*factor,'confidence':confidence} for character,start,end,confidence in tokens]


def ctc_tokens(image,reader):
    """保留模型实际发出的字符及其像素位置，用于隔离标签和词间空白。"""
    return [(token['character'],token['left'],token['right']) for token in ctc_evidence(image,reader)]


def terminal_closed_counters(image,left,right):
    """在原有红色像素中核实末字的两个封闭内孔；不闭运算、不补笔画。"""
    height,width=image.shape[:2];left=max(0,int(math.floor(left)));right=min(width,int(math.ceil(right)))
    if right-left<4:return None
    b,g,r=cv2.split(image.astype(np.int16));signal=np.maximum(0,r-np.maximum(g,b)).astype(np.float32)
    signal=np.maximum(0,signal-cv2.morphologyEx(signal,cv2.MORPH_OPEN,np.ones((7,7),np.uint8)))
    region=signal[:,left:right];maximum=float(region.max())
    if maximum<25:return None
    _,_,stats,_=cv2.connectedComponentsWithStats((region>=max(20,maximum*.40)).astype(np.uint8))
    bodies=[stat for stat in stats[1:] if stat[3]>=height*.25 and stat[2]>=3 and stat[4]>=8]
    if not bodies:return None
    body=max(bodies,key=lambda stat:stat[0]+stat[2]);bx,by,bw,bh,_=map(int,body)
    if bx<=0 or bx+bw>=right-left:return None
    observations=[]
    for fraction in [.25,.40]:
        mask=(region>=max(15,maximum*fraction)).astype(np.uint8)
        contours,hierarchy=cv2.findContours(mask,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is None:return None
        holes=[]
        for contour,info in zip(contours,hierarchy[0]):
            if info[3]<0:continue
            x,y,w,h=cv2.boundingRect(contour);area=float(cv2.contourArea(contour))
            if area>=1 and bx<=x and by<=y and x+w<=bx+bw and y+h<=by+bh:
                holes.append({'box':[left+x,y,w,h],'area':area,'center':[left+x+w/2,y+h/2]})
        if len(holes)!=2:return None
        holes.sort(key=lambda hole:hole['center'][1]);first,second=holes
        if second['center'][1]-first['center'][1]<bh*.20 or abs(first['center'][0]-second['center'][0])>bw*.35:return None
        observations.append({'threshold_fraction':fraction,'holes':holes})
    return {'method':'native_two_enclosed_counters','box':[left+bx,by,bw,bh],'observations':observations}


def review_mixed_ascii_tail(image,candidate,primary,independent=None,*,load_independent=None):
    """独立末段读数和不相容的原生字形只能否决整名，不能拼接替换姓名。"""
    target=re.search(r'[A-Za-z0-9]{3,}$',candidate)
    if not target or candidate.isascii() or target[0][-1] not in 'CEFGHIJKLMNSTUVWXYZ':return None
    emitted=ctc_evidence(image,primary)
    if not emitted or any(len(token['character'])!=1 for token in emitted):return None
    text=''.join(token['character'] for token in emitted);run=re.search(r'[A-Za-z0-9]{3,}$',text)
    if not run or len(run[0])!=len(target[0]) or run[0][:-1].casefold()!=target[0][:-1].casefold():return None
    if emitted[-1]['character']==target[0][-1] and emitted[-1]['confidence']>=.85:return None
    start=run.start();left=(emitted[start-1]['right']+emitted[start]['left'])/2 if start else 0
    last_left=(emitted[-2]['right']+emitted[-1]['left'])/2
    # CTC 发射点在字形内部；保留右侧现有像素和相邻字间谷底的余量。
    shape=terminal_closed_counters(image,max(left,last_left-2),image.shape[1])
    if not shape:return None
    if independent is None:independent=load_independent() if load_independent else None
    if independent is None:return None
    suffix=image[:,max(0,int(math.floor(left))):]
    background=tuple(int(c) for c in np.median(np.concatenate([suffix[:3],suffix[-3:]],axis=0),axis=(0,1)))
    observations=[]
    for padding in [0,2]:
        view=cv2.copyMakeBorder(suffix,0,0,padding,padding,cv2.BORDER_CONSTANT,value=background) if padding else suffix
        tokens=ctc_evidence(view,independent);value=''.join(token['character'] for token in tokens)
        confidence=float(np.mean([token['confidence'] for token in tokens])) if tokens else 0.
        observations.append({'name':value,'confidence':confidence,'terminal_confidence':tokens[-1]['confidence'] if tokens else 0.,'padding':padding})
    alternative=observations[0]['name']
    conflict=bool(len(alternative)==len(target[0]) and alternative[:-1].casefold()==target[0][:-1].casefold() and alternative[-1].isdigit() and all(read['name']==alternative and read['confidence']>=.80 and read['terminal_confidence']>=.95 for read in observations))
    return {'conflict':conflict,'method':'independent_ascii_tail_and_native_counters','candidate_suffix':target[0],
        'native_primary_suffix':run[0],'native_terminal_confidence':emitted[-1]['confidence'],'suffix_box':[max(0,int(math.floor(left))),0,image.shape[1],image.shape[0]],
        'independent_reads':observations,'shape_evidence':shape}


def foreground_views(image):
    """保留红色字形的完整范围；亮度细节用于复核被色度压缩粘连的小点。"""
    height,width=image.shape[:2]
    b,g,r=cv2.split(image.astype(np.int16));red=np.maximum(0,r-np.maximum(g,b)).astype(np.uint8)
    red=np.maximum(0,red.astype(np.float32)-cv2.morphologyEx(red,cv2.MORPH_OPEN,np.ones((7,7),np.uint8)).astype(np.float32))
    if red.max()<20:return []
    _,_,stats,_=cv2.connectedComponentsWithStats((red>=max(20,red.max()*.25)).astype(np.uint8))
    letters=[stat for stat in stats[1:] if stat[3]>=height*.3 and stat[4]>=8]
    if not letters:return []
    top=max(0,round(float(np.median([s[1] for s in letters])))-2);bottom=min(height,round(float(np.median([s[1]+s[3] for s in letters])))+2)
    _,xs=np.where(red[top:bottom]>=max(15,red.max()*.15))
    if not xs.size:return []
    left=max(0,int(xs.min())-2);right=min(width,int(xs.max())+3)
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    luma=np.maximum(0,gray.astype(np.float32)-cv2.medianBlur(gray,7).astype(np.float32))[top:bottom,left:right]
    scale=max(20,float(np.percentile(luma,98)));luma=np.clip(luma*255/scale,0,255).astype(np.uint8)
    return [image[top:bottom,left:right],cv2.cvtColor(luma,cv2.COLOR_GRAY2BGR),cv2.cvtColor(255-luma,cv2.COLOR_GRAY2BGR)]


def trailing_dots(image,tokens):
    """计数基线上的独立点形，不能把色度压缩粘连的多个点当成一个句号。"""
    alphas=[token for token in tokens if token[0].isalnum()]
    if not alphas:return None
    height,width=image.shape[:2];start=alphas[-1][2]
    b,g,r=cv2.split(image.astype(np.int16));red=np.maximum(0,r-np.maximum(g,b)).astype(np.float32)
    red=np.maximum(0,red-cv2.morphologyEx(red,cv2.MORPH_OPEN,np.ones((7,7),np.uint8)))
    _,_,stats,_=cv2.connectedComponentsWithStats((red>=max(20,red.max()*.25)).astype(np.uint8))
    letters=[s for s in stats[1:] if s[3]>=height*.3 and s[4]>=8]
    if not letters:return None
    baseline=float(np.median([s[1]+s[3] for s in letters]));font=float(np.median([s[3] for s in letters]))
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);signal=np.maximum(0,gray.astype(np.float32)-cv2.medianBlur(gray,7).astype(np.float32))
    _,_,stats,_=cv2.connectedComponentsWithStats((signal>=8).astype(np.uint8))
    points=[s for s in stats[1:] if s[0]>=start and s[2]<=font*.6 and s[3]<=font*.35 and s[4]>=2 and abs(s[1]+s[3]-baseline)<=max(3,font*.2) and np.max(red[s[1]:s[1]+s[3],s[0]:s[0]+s[2]])>=15]
    if not points:return None
    left=max(0,min(s[0] for s in points)-1);right=min(width,max(s[0]+s[2] for s in points)+1);top=min(s[1] for s in points);bottom=max(s[1]+s[3] for s in points)
    curve=signal[top:bottom,left:right].max(axis=0);peaks=[]
    for x in range(1,len(curve)-1):
        if curve[x]>=8 and curve[x]>=curve[x-1] and curve[x]>curve[x+1] and curve[x]-max(float(curve[max(0,x-2):x].min()),float(curve[x+1:min(len(curve),x+3)].min()))>=1.5:
            if peaks and x-peaks[-1][0]<max(2,font*.12):
                if curve[x]>peaks[-1][1]:peaks[-1]=(x,float(curve[x]))
            else:peaks.append((x,float(curve[x])))
    if not 2<=len(peaks)<=6:return None
    distances=np.diff([peak[0] for peak in peaks]);pitch=float(np.median(distances))
    if not font*.12<=pitch<=font*.35 or any(abs(distance-pitch)>max(1.,pitch*.3) for distance in distances):return None
    return {'count':len(peaks),'box':[int(left),int(top),int(right),int(bottom)],'centers':[float(left+x) for x,_ in peaks],'font_height':font,'method':'native_luma_dot_shapes'}


def word_cuts(image,primary,tokens,text,english=None,independent=None):
    """额外空格须由两个实际视图在同一像素位置读到，不能凭词义猜分词。"""
    from player_names import name_key,close_name
    background=tuple(int(c) for c in np.median(np.concatenate([image[:3],image[-3:]],axis=0),axis=(0,1)))
    observations=[]
    for reader,pad in [(primary,0),(primary,2),(primary,4),(english,0),(independent,0)]:
        if reader is None:continue
        view=cv2.copyMakeBorder(image,0,0,pad,pad,cv2.BORDER_CONSTANT,value=background) if pad else image
        emitted=tokens if reader is primary and not pad else ctc_tokens(view,reader)
        observed=''.join(token[0] for token in emitted)
        if name_key(observed)!=name_key(text) and not close_name(observed,text):continue
        observations.append([round((emitted[i-1][2]+emitted[i+1][1])/2)-pad for i,token in enumerate(emitted) if token[0]==' ' and 0<i<len(emitted)-1])
    cuts=[]
    # CTC 发射位置位于字形内部；在附近实际较暗的字间谷底裁切，避免切掉宽字母的右笔画。
    b,g,r=cv2.split(image.astype(np.int16));red=np.maximum(0,r-np.maximum(g,b)).astype(np.float32)
    red=np.maximum(0,red-cv2.morphologyEx(red,cv2.MORPH_OPEN,np.ones((7,7),np.uint8)))
    curve=red[max(0,image.shape[0]//5):max(1,image.shape[0]*4//5)].max(axis=0)
    def gap(value):
        left=max(0,value-2);right=min(len(curve),value+max(3,round(image.shape[0]*.22)))
        if right-left<2:return value
        pairs=(curve[left:right-1]+curve[left+1:right])*.5
        return left+int(pairs.argmin())+1
    observations=[[gap(value) for value in values if 0<value<image.shape[1]] for values in observations]
    for values in observations:
        for value in values:
            if sum(any(abs(other-value)<=3 for other in other_view) for other_view in observations)>=2 and not any(abs(other-value)<=3 for other in cuts):cuts.append(value)
    return sorted(cut for cut in cuts if 0<cut<image.shape[1])


def read_latin_name_patch(image,primary,english,independent):
    """按原模型实际读到的空格分词；每个词必须由两套英文模型独立同意。"""
    from combat_outcome_reader import clean_target_name
    from player_names import name_key
    tokens=ctc_tokens(image,primary);text=''.join(t[0] for t in tokens)
    tag=re.match(r'^[\[({【]?[^\[\]\s]{1,6}[\]】]\s*',text)
    if tag:
        start=tag.end()
        if start>=len(tokens):return None
        left=round((tokens[start-1][2]+tokens[start][1])/2)
        image=image[:,left:];tokens=ctc_tokens(image,primary);text=''.join(t[0] for t in tokens)
    original=clean_target_name(text)
    if not original or not original.isascii():return None
    cuts=word_cuts(image,primary,tokens,text,english,independent)
    if len(cuts)>3:return None
    edges=[0,*cuts,image.shape[1]];words=[];evidence=[]
    for left,right in zip(edges,edges[1:]):
        word=image[:,left:right]
        if not word.size:return None
        background=tuple(int(c) for c in np.median(np.concatenate([word[:3],word[-3:]],axis=0),axis=(0,1)))
        # 录屏色度压缩会粘连红字的斜笔画；普通亮度保留高通视图可能削弱的完整笔画。
        # 每个候选仍须由两套模型独立同意，不能把预处理视图当成不同原生帧。
        gray=cv2.cvtColor(word,cv2.COLOR_BGR2GRAY)
        views=[word,*[cv2.copyMakeBorder(word,0,0,pad,pad,cv2.BORDER_CONSTANT,value=background) for pad in [2,4]],
            cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR),cv2.cvtColor(255-gray,cv2.COLOR_GRAY2BGR),*foreground_views(word)]
        models=[[{'name':clean_target_name(name),'confidence':float(confidence)} for name,confidence in reader(views)[0]] for reader in [english,independent]]
        punctuation=trailing_dots(word,ctc_tokens(word,primary)) if right==edges[-1] else None
        if punctuation:
            for model in models:
                for read in model:
                    if read['name'] and re.search(r'[A-Za-z0-9]\.*$',read['name']):
                        read['raw_name']=read['name'];read['name']=read['name'].rstrip('.')+'.'*punctuation['count']
        candidates={read['name'] for read in models[0] if read['name'] and read['confidence']>=.80 and any(other['name']==read['name'] and other['confidence']>=.80 and max(read['confidence'],other['confidence'])>=.90 for other in models[1])}
        if not candidates:return None
        choice=max(candidates,key=lambda name:(sum(read['name']==name and read['confidence']>=.80 for model in models for read in model),min(max(read['confidence'] for read in model if read['name']==name) for model in models)))
        if cuts and any(char.isspace() for char in choice):return None
        confidence=min(max(read['confidence'] for read in model if read['name']==choice) for model in models)
        words.append(choice);evidence.append({'name':choice,'confidence':confidence,'box':[left,0,right,image.shape[0]],'models':models,**({'punctuation_evidence':punctuation} if punctuation else {})})
    name=' '.join(words)
    if name_key(name)!=name_key(original):return None
    return {'name':name,'confidence':min(word['confidence'] for word in evidence),'views':evidence,'method':'independent_latin_word_views','mobile_name':original}


def leading_square(image,first_emission):
    """只检查模型未解码的前导区域；不能把汉字内部的口形笔画当作方块。"""
    height,width=image.shape[:2]
    if first_emission<height*.5:return None
    b,g,r=cv2.split(image.astype(np.int16));signal=np.maximum(0,r-np.maximum(g,b)).astype(np.float32)
    signal=np.maximum(0,signal-cv2.morphologyEx(signal,cv2.MORPH_OPEN,np.ones((7,7),np.uint8)))
    limit=min(width//2,round(first_emission)+2)
    if limit<6 or signal.max()<15:return None
    region=cv2.GaussianBlur(signal[:,:limit],(3,3),0);candidates=[]
    for side in range(max(6,round(height*.2)),min(limit,round(height*.5))+1):
        template=np.zeros((side,side),np.float32);cv2.rectangle(template,(0,0),(side-1,side-1),1,max(1,round(side*.18)))
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,template,cv2.TM_CCORR_NORMED))
        if x+side<=first_emission*.7 and height*.6<=y+side<=height*.9:candidates.append({'score':score,'box':[x,y,side,side]})
    candidate=max(candidates,key=lambda item:item['score']) if candidates else None
    return candidate if candidate and candidate['score']>=.82 else None


class TargetNameReader:
    """单次成片复核持有一个模型；即使关闭全局引擎池也不逐帧重载。"""
    def __init__(self,primary=None):self.reader=None;self.primary=primary;self.latin_reader=None

    def refine_latin_words(self,probes):
        """仅使用本事件已解码裁片；失败时不补姓名，不读取录像或创建额外主模型。"""
        from latin_word_boundaries import prepare_probes,refine_prepared,WORD_MODEL_SHAS
        prepared=prepare_probes(probes)
        if not prepared or self.primary is None:return []
        english=getattr(self.primary,'_apex_latin_reader',None)
        if english is None or _reader_model_sha(english)!=WORD_MODEL_SHAS[0] or not model_available(latin=True):return []
        if self.latin_reader is None:
            from gpu_ocr_backend import create_ocr_engine
            self.latin_reader=create_ocr_engine(backend=os.environ.get('APEX_OCR_BACKEND','cpu'),model_path=LATIN_MODEL_PATH,rec_batch_num=1).text_rec
        if _reader_model_sha(self.latin_reader)!=WORD_MODEL_SHAS[1]:return []
        return refine_prepared(prepared,self.primary,english,self.latin_reader,ctc=ctc_evidence,foreground_views=foreground_views)

    def review_tail(self,image,candidate):
        if self.primary is None or candidate.isascii() or not re.search(r'[A-Za-z0-9]{2,}[CEFGHIJKLMNSTUVWXYZ]$',candidate):return None
        if not model_available(latin=True):return None
        def load():
            if self.latin_reader is None:
                from gpu_ocr_backend import create_ocr_engine
                self.latin_reader=create_ocr_engine(backend=os.environ.get('APEX_OCR_BACKEND','cpu'),model_path=LATIN_MODEL_PATH,rec_batch_num=1).text_rec
            return self.latin_reader
        return review_mixed_ascii_tail(image,candidate,self.primary,load_independent=load)

    def read_latin_only(self,image,mobile_text):
        # 原生首轮也核实拉丁词间空白和标点；不等待错误双帧共识先通过。
        return self(image,mobile_text) if mobile_text.isascii() else None

    def __call__(self,image,mobile_text):
        if mobile_text.isascii() and self.primary is not None:
            english=getattr(self.primary,'_apex_latin_reader',None)
            if english is None or not model_available(latin=True):return None
            if self.latin_reader is None:
                from gpu_ocr_backend import create_ocr_engine
                self.latin_reader=create_ocr_engine(backend=os.environ.get('APEX_OCR_BACKEND','cpu'),model_path=LATIN_MODEL_PATH,rec_batch_num=1).text_rec
            return read_latin_name_patch(image,self.primary,english,self.latin_reader)
        if not model_available():return None
        if self.reader is None:
            from gpu_ocr_backend import create_ocr_engine
            self.reader=create_ocr_engine(backend=os.environ.get('APEX_OCR_BACKEND','cpu'),model_path=MODEL_PATH,rec_batch_num=1).text_rec
        return read_name_patch(image,mobile_text,reader=self.reader)


def read_name_patch(image,mobile_text,*,reader=None):
    if not model_available():return None
    from combat_outcome_reader import clean_target_name
    from engine_pool import pooled_engine
    from gpu_ocr_backend import create_ocr_engine
    backend=os.environ.get('APEX_OCR_BACKEND','cpu')
    if reader is None:reader=pooled_engine(('native-target-name-server-v1',backend,MODEL_SHA),lambda:create_ocr_engine(backend=backend,model_path=MODEL_PATH,rec_batch_num=1)).text_rec
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);views=[cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR),cv2.cvtColor(255-gray,cv2.COLOR_GRAY2BGR)];reads=reader(views)[0]
    names=[clean_target_name(text) for text,_ in reads]
    # 独立模型两视图及原模型的实际字符读数都必须一致。
    if len(set(names))!=1 or not names[0] or min(confidence for _,confidence in reads)<.90 or names[0]!=clean_target_name(mobile_text):return None
    height,width=image.shape[:2];shape=reader.rec_image_shape;normalized=reader.resize_norm_img(views[0],max(shape[2]/shape[1],width/height));probabilities=reader.session(normalized[None].astype(np.float32))[0][0];active=np.where(probabilities.argmax(-1)>0)[0]
    if not active.size:return None
    resized=min(normalized.shape[-1],math.ceil(shape[1]*width/height));first=float(active[0]*normalized.shape[-1]/len(probabilities)*width/resized)
    symbol=leading_square(image,first)
    # 有未解码的前导字形时，不能把缺字姓名当作完整结果。
    if first>=height*.5 and symbol is None:return None
    return {'name':('□' if symbol else '')+names[0],'confidence':min(confidence for _,confidence in reads),'views':[{'name':name,'confidence':float(confidence)} for name,(_,confidence) in zip(names,reads)],'method':'independent_native_name_views','symbol_evidence':symbol,'mobile_name':clean_target_name(mobile_text)}
