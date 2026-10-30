"""候选交战中的本人中心结果提示；区别于公共击杀播报及对白字幕。"""
import json
import hashlib
import math
import os
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
import cv2
from image_io import read_image
import numpy as np
from apex_clipper import BASE,write_json,fingerprint,probe,inactive_view
from weapon_reader import new_engine,MODEL_SHA

KINDS={'knock','assist','elimination'}
RULE_VERSION='own-center-result-v4'
# 本人提示的帧级确认规则；只影响统计/敌人名识别版本，不改变任务级筛选规则版本。
CONFIRMATION_VERSION='prefix-confirmation-v2'
PARSER_VERSION='target-name-v15'
# 没有像素模板的界面语言改用「行首语法 + 相邻帧一致」确认；只改这一阶段的检查点，不使全库字段失效。
TOAST_GRAMMAR_VERSION='toast-grammar-v1'
# 只收录有真实录像证据的语言；繁中走像素模板，英文走原有英文语法分支。
GRAMMAR_LOCALES={'zh-CN','ru'}

TARGET_PREFIX=re.compile(r'^(?:ASSIST[,.:\s]*)?(?:KN[O0]CKED\s*D[O0]WN|ELIMINATED)\s*|^(?:助攻[,，:：\s]*)?(?:[擊击撃擎驛驿]倒|(?:已)?消[滅灭減减]|淘汰)\s*',re.I)


def read_target_span(image,line,reader,prefix_box=None,*,independent_names=False,tail_review=None):
    """按 CTC 位置单独裁出姓名，避免动作前缀与积分掩盖姓名中的细笔画。"""
    if reader is None or not all(hasattr(reader,key) for key in ['session','resize_norm_img','rec_image_shape','postprocess_op']):return None
    x1,y1,x2,y2=line['box'];h,w=image.shape[:2]
    patch=image[max(0,int(y1)-3):min(h,int(y2)+4),max(0,int(x1)-4):min(w,int(x2)+5)]
    if not patch.size:return None
    ph,pw=patch.shape[:2];ratio=max(reader.rec_image_shape[2]/reader.rec_image_shape[1],pw/ph)
    normalized=reader.resize_norm_img(patch,ratio)
    probabilities=reader.session(normalized[None].astype(np.float32))[0][0]
    characters=[];positions=[];previous=0
    for time,index in enumerate(probabilities.argmax(-1)):
        if index and index!=previous:
            token=unicodedata.normalize('NFKC',reader.postprocess_op.character[int(index)])
            if len(token)!=1:return None
            characters.append(token);positions.append([time,time+1])
        elif index and positions:positions[-1][1]=time+1
        previous=index
    text=''.join(characters);prefix=TARGET_PREFIX.match(text)
    if not prefix:return None
    start=prefix.end();suffix=text.find('+',start);end=suffix if suffix>=0 else len(characters)
    while start<end and text[start].isspace():start+=1
    while end>start and text[end-1].isspace():end-=1
    if start>=end:return None
    latin=text[start:end].isascii()
    resized_width=min(normalized.shape[-1],math.ceil(reader.rec_image_shape[1]*pw/ph))
    factor=normalized.shape[-1]/len(probabilities)*pw/resized_width
    left=(positions[start-1][1]+positions[start][0])/2 if start else positions[start][0]-.5
    right=(positions[end-1][1]+positions[end][0])/2 if end<len(positions) else positions[end-1][1]+.5
    left_pixel=max(0,math.floor(left*factor));right_pixel=min(pw,math.ceil(right*factor))
    if prefix_box is not None:
        # 字符被整行模型跳过时，CTC 的字符中点会切掉姓名首尾。已匹配的动作图形提供独立左边界。
        left_pixel=max(0,round(prefix_box[2])-max(0,int(x1)-4)+1)
        if suffix>=0:right_pixel=min(pw,max(right_pixel,math.floor((positions[suffix][0]-.75)*factor)))
        else:right_pixel=pw
    if latin and suffix<0:
        # 句末点号常在文字检测框外；保留原像素供独立复核，不能在框边将其截断。
        name_right=min(w,max(0,int(x1)-4)+right_pixel+round(ph*.6))
        patch=image[max(0,int(y1)-3):min(h,int(y2)+4),max(0,int(x1)-4):name_right]
        right_pixel=patch.shape[1]
    name=patch[:,left_pixel:right_pixel]
    if not name.size:return None
    def finish(read):
        mobile_name=clean_target_name(text[start:end])
        boundary={'method':'native_ctc_name_crop','box':[max(0,int(x1)-4)+left_pixel,max(0,int(y1)-3),max(0,int(x1)-4)+right_pixel,min(h,int(y2)+4)],
            'ctc_name':mobile_name,'ctc_first_x':float(max(0,int(x1)-4)+positions[start][0]*factor),
            'ctc_last_x':float(max(0,int(x1)-4)+positions[end-1][1]*factor),
            'prefix_anchor':'template' if prefix_box is not None else 'ctc',
            'prefix_box':list(prefix_box) if prefix_box is not None else None}
        clan=re.match(r'^[\[【]([^\[\]【】\s]{1,6})[\]】]',mobile_name)
        if clan:boundary['clan_tag']=clan[1]
        # 内部方括号前的额外姓名字符须同时在完整行 CTC 和已匹配动作之后；
        # 裁片才冒出的动作残笔不能获得这个证明。
        if read and prefix_box is not None and read.get('name')==mobile_name and re.match(r'^[^\[【]+[\[【]',mobile_name) and boundary['ctc_first_x']>=prefix_box[2]:
            boundary['verified_leading_name']=True
        candidate=read.get('name') if read else (parse_result_line(line.get('text','')) or {}).get('target_text') or mobile_name
        review=tail_review(name,candidate) if tail_review and candidate and not latin else None
        if review and review.get('conflict'):
            return {'name':'','confidence':0.,'views':[],'method':'native_ascii_tail_conflict','boundary_evidence':boundary,'tail_evidence':review}
        return {**read,'boundary_evidence':boundary,**({'tail_evidence':review} if review else {})} if read is not None else None
    name_reader=reader
    if latin:
        # 包内已有英文识别模型；拉丁昵称不用在上万个中日韩字符之间竞争。
        name_reader=getattr(reader,'_apex_latin_reader',None)
        if name_reader is None:
            from gpu_ocr_backend import create_ocr_engine
            backend=getattr(reader.session,'backend',os.environ.get('APEX_OCR_BACKEND','cpu'))
            name_reader=create_ocr_engine(backend=backend,model_path=BASE/'models/numeric_rec_en_v4.onnx',rec_batch_num=1).text_rec
            reader._apex_latin_reader=name_reader
    # 最大通道保留红/黄姓名，避免白色前缀、积分主导名字的读数。
    gray=np.max(name,axis=2).astype(np.uint8);reads=[]
    views=[name,cv2.cvtColor(255-gray,cv2.COLOR_GRAY2BGR),cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)]
    if prefix_box is not None and not latin:
        # 红字的色度在录屏中可能被压缩；亮度通道仍保留较细的字边，避免三个视图都依赖同一模糊色度。
        luma=cv2.cvtColor(name,cv2.COLOR_BGR2GRAY);low,high=np.percentile(luma,[3,97])
        if high-low>=8:
            normalized=np.clip((luma.astype(np.float32)-low)*255/(high-low),0,255).astype(np.uint8)
            views.extend([cv2.cvtColor(normalized,cv2.COLOR_GRAY2BGR),cv2.cvtColor(255-normalized,cv2.COLOR_GRAY2BGR)])
    for view in views:
        value,confidence=name_reader([view])[0][0]
        reads.append({'name':clean_target_name(value),'confidence':float(confidence)})
    from player_names import name_key
    threshold=.90 if latin else .80
    valid=[read for read in reads if read['name'] and read['confidence']>=threshold]
    groups={name_key(read['name']):[other for other in valid if name_key(other['name'])==name_key(read['name'])] for read in valid}
    agreed=max(groups.values(),key=lambda group:(len(group),min(read['confidence'] for read in group)),default=[])
    confirmed=len(agreed)>=2
    if latin and independent_names:
        if callable(independent_names):independent=independent_names(name,text[start:end])
        else:independent=None
        if independent:return finish(independent)
    # 未确认的中文裁片不能抹去原整行读数；保留原证据供后续原生多帧复核。
    if not latin and not confirmed:
        if independent_names:
            if callable(independent_names):independent=independent_names(name,text[start:end])
            else:
                from target_name_reader import read_name_patch
                independent=read_name_patch(name,text[start:end])
            if independent:return finish(independent)
        return finish(None)
    best=max(agreed or reads,key=lambda read:read['confidence'])
    return finish({'name':best['name'] if confirmed else '', 'confidence':min(read['confidence'] for read in agreed) if confirmed else 0.,'views':reads,'method':'ctc_span_two_views'})


def with_target_read(event,line):
    read=line.get('target_read')
    if not event or read is None:return event
    return {**event,'target_text':read['name'] or event.get('target_text',''),
        'target_read_confidence':read['confidence'],'target_method':read['method'],
        **({'target_boundary_evidence':read['boundary_evidence']} if read.get('boundary_evidence') else {}),
        **({'target_tail_evidence':read['tail_evidence']} if read.get('tail_evidence') else {}),
        **({'target_shape_evidence':read['symbol_evidence']} if read.get('symbol_evidence') else {}),
        **({'target_word_evidence':read['views']} if read['method']=='independent_latin_word_views' else {})}


def same_english_target(left,right):
    left=''.join(c for c in left.upper() if c.isalnum());right=''.join(c for c in right.upper() if c.isalnum())
    return bool(left and right and (left==right or min(len(left),len(right))>=4 and SequenceMatcher(None,left,right).ratio()>=.82))


def restore_english_events(observations):
    """语法修复只重解析已保存的OCR行，不再次采样或推理。"""
    for item in observations.values():
        if item.get('status')=='excluded_view':continue
        candidates=[e for e in item.get('possible_events',[]) if e.get('confirmation_basis')!='english_toast_grammar']
        item['events']=[e for e in item.get('events',[]) if e.get('confirmation_basis')!='english_toast_grammar']
        for line in item.get('lines',[]):
            event=with_target_read(parse_result_line(line['text']),line)
            if not event or not re.match(r'^(?:ASSIST|KNOCKED DOWN|ELIMINATED)\b',event['text'],re.I):continue
            if line['prefix_confidence']<.90 or len(event.get('target_text',''))<2:continue
            if any(e['kind']==event['kind'] and same_english_target(e.get('target_text',''),event.get('target_text','')) for e in candidates):continue
            candidates.append({**event,'confidence':line['prefix_confidence'],'text_confidence':line['confidence'],
                'box':line['box'],'time':item['time'],'frame':item['frame'],'ownership':'self','confirmation_basis':'english_toast_grammar'})
        item['possible_events']=candidates
    for item in observations.values():
        for event in item.get('possible_events',[]):
            if event.get('confirmation_basis')!='english_toast_grammar':continue
            if any(previous['time']!=item['time'] and abs(previous['time']-item['time'])<=1.1 and
                any(e['kind']==event['kind'] and same_english_target(e.get('target_text',''),event.get('target_text','')) for e in previous.get('possible_events',[])) for previous in observations.values()):
                if not any(e['kind']==event['kind'] and same_english_target(e.get('target_text',''),event.get('target_text','')) for e in item['events']):item['events'].append({**event,'confirmation':'two_frame_english_toast'})
                item['status']='self_event'


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


def clean_target_name(text,*,allow_rendered_square=False):
    """只保留姓名；OCR 的固定提示、积分、对白不能作为玩家名展示。"""
    if not isinstance(text,str):return ''
    target=re.sub(r'\s+',' ',unicodedata.normalize('NFKC',text)).strip()
    # 也处理旧缓存曾把完整动作前缀写进 target_text 的情况。
    prefix=r'^(?:(?:ASSIST|助攻)\s*[,.:，：]*\s*|KN[O0]CK(?:ED)?\s*D[O0]WN\s*|ELIMINAT(?:ED|ION)\s*|(?:已)?[擊击擎驛驿]倒\s*|(?:已)?消[滅灭減减]\s*|淘汰\s*)'
    for _ in range(3):
        stripped=re.sub(prefix,'',target,flags=re.I)
        if stripped==target:break
        target=stripped
    target=re.sub(r'\s*\+\s*[0-9OoIiLlSsBbZz]{1,5}(?:\s|$|[^A-Za-z0-9]).*$','',target).strip(' ,:;，：；')
    compact=re.sub(r'\s+','',target).upper()
    if not target or len(target)>48 or not (any(c.isalpha() for c in target) or re.fullmatch(r'\d{5,20}',target)):return ''
    if re.search(r'[\x00-\x1f\ufffd<>:=+!?！？。]',target) or '□' in target and not allow_rendered_square:return ''
    if re.search(r'DAMAGE|INFLICT|SHIELDBROKEN|YOUSPOTTED|SPOTTEDANENEMY|PRESS|HOLD|TOGGLE|RELOAD|ELIMINAT|KNOCK|KN0CK|ASSIST|SQUAD|擊倒|击倒|造成|傷害|伤害|護盾|护盾|按住|按下|切換|切换|你發現|你发现|我被|你被',compact,re.I):return ''
    # 被截断的动作词（真实缓存有 ASSIST.KNO）没有可用姓名。
    if re.fullmatch(r'KN[O0]?(?:C(?:K(?:ED)?)?)?|D[O0]WN|ELIM|ELIMIN|ELIMINA|ELIMINATE|XP|RP',compact):return ''
    return target


# 俄语界面：默认识别模型不含西里尔字母，会把大写提示读成形近的拉丁字母（НОКАУТ→HOKAYT）。
# 只认真实录像里出现过的本人提示行首，且区分大小写，避免「Нокаут-щит」等物品名误触发。
_CYRILLIC_LOOKALIKE=str.maketrans('АВЕКМНОРСТУХЗДИЙЛПЯЬЫ','ABEKMHOPCTYX3AN' 'NANRbb')
RU_ASSIST_KNOCK=re.compile(r'^C[O0]A[EF][MNH][CG]T[BV][NM][EF]\s*[BV]\s*H[O0]KA[YV]T[EF]\s*')
RU_KNOCK=re.compile(r'^H[O0]KA[YV]T(?![-—–])\s*')  # 识别常把名字直接连在后面；「-щит」是物品名
RESULT_CUE=r'擊倒|击倒|消滅|消灭|淘汰|助攻|KNOCK|ELIMINAT|H[O0]KA[YV]T|C[O0]A[EF][MNH][CG]T[BV]'


def result_locale(text):
    """只按行首动作词判断提示语言，用于选择确认方式；不改变事件种类。"""
    if re.match(r'^(?:ASSIST|KNOCKED DOWN|ELIMINATED)\b',text,re.I):return 'en'
    if RU_ASSIST_KNOCK.match(text) or RU_KNOCK.match(text):return 'ru'
    if re.search(r'^(?:助攻\s*[,，:：]?\s*)?(?:擊倒|已消滅)',text):return 'zh-TW'
    if re.search(r'^(?:助攻\s*[,，:：]?\s*)?(?:击倒|已消灭|淘汰)',text):return 'zh-CN'
    return 'zh'


def parse_result_line(text):
    """只接受本人toast的行首语法；玩家名拼错不影响事件种类。"""
    clean=unicodedata.normalize('NFKC',text).strip()
    clean=re.sub(r'\s+',' ',clean)
    russian=clean.translate(_CYRILLIC_LOOKALIKE)
    for kind,action,pattern in [('assist','knock',RU_ASSIST_KNOCK),('knock','knock',RU_KNOCK)]:
        match=pattern.match(russian)
        if match:
            target=clean[match.end():].strip()
            return {'kind':kind,'action':action,'target_text':clean_target_name(target),'target_raw':target,'text':clean,'locale':'ru'}
    # OCR 常把同形的繁体“擊”读作日文“撃”；仅归一行首动作，不改昵称字符。
    clean=re.sub(r'^(助攻\s*[,，:：]?\s*)?撃倒',lambda match:(match[1] or '')+'擊倒',clean)
    # Apex英文HUD常被OCR连成一词，且DOWN的O会读成0；仅修正行首固定语法。
    clean=re.sub(r'^KN[O0]CKED\s*D[O0]WN\s*','KNOCKED DOWN ',clean,flags=re.I)
    clean=re.sub(r'^(ELIMINATED|ASSIST)\s*',lambda match:match.group(1).upper()+' ',clean,flags=re.I)
    clean=re.sub(r'^(ASSIST)\s*[,.:]*\s*KN[O0]CK(?:ED)?\s*D[O0]WN\s*',r'ASSIST KNOCKED DOWN ',clean,flags=re.I)
    clean=re.sub(r'^(ASSIST)\s*[,.:]*\s*ELIMINAT(?:ION|ED)\s*',r'ASSIST ELIMINATED ',clean,flags=re.I)
    patterns=[
        ('assist',r'^(?:助攻\s*[,，:]?\s*|ASSIST\s*[: ,]*\s*)\s*(.*)$'),
        ('knock',r'^(?:(?:已)?(?:擊倒|击倒)|KNOCKED DOWN)\s*(.*)$'),
        ('elimination',r'^(?:已消滅|已消灭|ELIMINATED)\s*(.*)$'),
    ]
    for kind,pattern in patterns:
        match=re.match(pattern,clean,re.IGNORECASE)
        if not match: continue
        target=match.group(1).strip()
        action=kind if kind!='assist' else 'unknown'
        if kind=='assist':
            # 只读助攻之后的完整动作前缀；昵称里出现动作词不能改变动作。
            # 简体界面的助攻消灭显示为「助攻，淘汰 <名字>」。
            for observed,syntax in [('knock',r'^(?:[擊击撃擎驛驿]倒|KNOCK(?:ED)? DOWN)\s*'),('elimination',r'^(?:(?:已)?消[滅灭減减]|淘汰|ELIMINAT(?:ION|ED))\s*')]:
                prefix=re.match(syntax,target,re.I)
                if prefix:action=observed;target=target[prefix.end():];break
        return {'kind':kind,'action':action,'target_text':clean_target_name(target),'target_raw':target,'text':clean,'locale':result_locale(clean)}
    return None


def is_known_dialogue(text):
    text=unicodedata.normalize('NFKC',text)
    if ':' in text and not re.match(r'^(?:助攻|ASSIST|已消滅|已消灭|擊倒|击倒|KNOCKED|ELIMINATED)',text,re.IGNORECASE): return True
    cue=re.search(RESULT_CUE+r'|撃倒',text,re.IGNORECASE)
    if not cue: return False
    prefix=text[:cue.start()]
    return bool(':' in prefix or re.search(r'我被|你被|被人|I(?: AM| WAS)? |YOU(?: ARE| WERE)? ',prefix,re.IGNORECASE)
                or (not parse_result_line(text) and re.search(r'[。!?！？]',text)))


class PrefixGate:
    def __init__(self,profile):
        self.profile=profile; self.templates=[]
        for entry in profile.get('prefix_templates',[]):
            image=read_image(str(BASE/entry['gray']),cv2.IMREAD_GRAYSCALE)
            if image is None: raise ValueError('缺少本人结果提示模板')
            self.templates.append((entry,image))

    def inspect(self,image):
        region,roi=roi_image(image,self.profile); gray=cv2.cvtColor(region,cv2.COLOR_BGR2GRAY)
        found=[]
        for entry,template in self.templates:
            if self.profile.get('hud_scale'):
                rw,rh=self.profile['reference_size'];sx,sy=self.profile['hud_scale']
                fx=image.shape[1]/rw*2*sx;fy=image.shape[0]/rh*2*sy
            else:fx=fy=image.shape[1]/entry['sample_size'][0]
            if fx!=1 or fy!=1: template=cv2.resize(template,None,fx=fx,fy=fy)
            if template.shape[0]>gray.shape[0] or template.shape[1]>gray.shape[1]:continue
            result=cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED)
            # 两张助攻模板只包含共用的“助攻”字形，路径名不能证明后续动作。
            action='unknown' if entry['kind']=='assist' else entry['kind']
            # 同时出现多个同类提示时保留多个行位置，避免只支持最高匹配的一行。
            for n in range(4):
                _,score,_,loc=cv2.minMaxLoc(result)
                if n and score<self.profile.get('calibration',{}).get('gate_threshold',.65):break
                found.append({'kind':entry['kind'],'action':action,'score':float(score),'box':[loc[0]+roi[0],loc[1]+roi[1],loc[0]+roi[0]+template.shape[1],loc[1]+roi[1]+template.shape[0]]})
                x,y=loc;th,tw=template.shape
                result[max(0,y-th//2):min(result.shape[0],y+th//2+1),max(0,x-tw//2):min(result.shape[1],x+tw//2+1)]=-2
        return found


def text_line_gate(image,profile):
    """未知语言只用廉价文字行筛选触发OCR，不把几何命中当战果。"""
    region,_=roi_image(image,profile)
    if not region.size:return False
    hsv=cv2.cvtColor(region,cv2.COLOR_BGR2HSV)
    mask=((hsv[:,:,2]>180)&(hsv[:,:,1]<90)).astype(np.uint8)
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    glyphs=[(x,y,w,h) for x,y,w,h,area in stats[1:] if 3<=h<=26 and 1<=w<=30 and 4<=area<=350]
    return any(sum(abs(y+h/2-(yy+hh/2))<=3 for _,yy,_,hh in glyphs)>=8 for _,y,_,h in glyphs)


def short_text_hint(image,profile):
    """「已消灭」这类三四个字的短提示达不到 text_line_gate 的字数；按提示区高度找一排浅色字形。"""
    region,_=roi_image(image,profile)
    if not region.size:return False
    hsv=cv2.cvtColor(region,cv2.COLOR_BGR2HSV)
    mask=((hsv[:,:,2]>185)&(hsv[:,:,1]<80)).astype(np.uint8)
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    height=region.shape[0];low=max(4,int(height*.10));high=max(low+2,int(height*.35))
    glyphs=[(y,h) for x,y,w,h,area in stats[1:] if low<=h<=high and 2<=w<=high*1.5 and area>=6]
    return any(sum(abs(y+h/2-(yy+hh/2))<=max(3,h*.5) and abs(hh-h)<=max(2,h*.4) for yy,hh in glyphs)>=3 for y,h in glyphs)


def same_toast_slot(left,right):
    """非拉丁名字的识别常逐帧不同；同种提示停在同一行位置即视为同一条。"""
    a,b=left.get('box'),right.get('box')
    if not a or not b:return False
    height=max(1,a[3]-a[1])
    return abs(a[0]-b[0])<=height*1.5 and abs((a[1]+a[3])/2-(b[1]+b[3])/2)<=height*.6


def grammar_confirmable(event):
    """无像素模板时：必须是行首语法、不是紧随对白的换行；名字读不清时，余下部分也不能像一句字幕。"""
    if event.get('after_dialogue'):return False
    if event.get('target_text'):return True
    raw=(event.get('target_raw') or '').strip()
    return not raw or len(raw)<=24 and not re.search(r'[。！？!?，,：:；;、]',raw)


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


def recognize_frame(image,profile,engine=None,expand_context=False,prefix_matches=None,*,independent_names=False,tail_review=None):
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
        and re.search(RESULT_CUE,line['text'],re.IGNORECASE) for line in lines):
        return recognize_frame(image,profile,engine,expand_context=True,prefix_matches=prefix_matches,independent_names=independent_names,tail_review=tail_review)
    for line in lines:
        if is_known_dialogue(line['text']): dialogue.append(line); continue
        parsed=parse_result_line(line['text'])
        if parsed and line['prefix_confidence']>=.65:
            supports=[match for match in prefix_matches or [] if match['kind']==parsed['kind'] and parsed['kind']!='assist' and match['score']>=.75 and abs(match['box'][0]-line['box'][0])<=10 and abs((match['box'][1]+match['box'][3]-line['box'][1]-line['box'][3])/2)<=max(10,(line['box'][3]-line['box'][1])*.4)]
            if parsed['kind']=='assist' and parsed.get('action')=='knock':
                # 助攻共用模板不含“擊倒”；只有后面实际匹配到的完整擊倒图形
                # 才能作为姓名左边界，避免把“倒”的残竖笔裁成 I。
                font=max(1,line['box'][3]-line['box'][1])
                supports=[match for match in prefix_matches or [] if match['kind']=='knock' and match['score']>=.80 and font*.8<=match['box'][0]-line['box'][0]<=font*4.5 and match['box'][2]<line['box'][2] and abs((match['box'][1]+match['box'][3]-line['box'][1]-line['box'][3])/2)<=max(10,font*.4)]
            hint=max(supports,key=lambda match:match['score'])['box'] if supports else None
            read=read_target_span(image,line,getattr(engine,'text_rec',None),hint,independent_names=independent_names,tail_review=tail_review)
            if read is not None:line['target_read']=read;parsed=with_target_read(parsed,line)
            if line['confidence']<.80 and parsed.get('target_read_confidence',0)<.90:parsed['target_text']=''
            events.append({**parsed,'confidence':line['prefix_confidence'],'text_confidence':line['confidence'],'box':line['box']})
        elif re.search(RESULT_CUE,line['text'],re.IGNORECASE):
            ambiguous.append(line)
    for event in events:
        # 紧挨在对白行下方的同色行可能是换行后的字幕，不能当本人提示。
        event['after_dialogue']=any(0<=event['box'][1]-d['box'][3]<=max(6,(d['box'][3]-d['box'][1])*.8) and abs(event['box'][0]-d['box'][0])<=(d['box'][3]-d['box'][1])*3 for d in dialogue)
    return {'lines':lines,'events':events,'ambiguous_lines':ambiguous,'known_dialogue':dialogue,'context_expanded':expand_context}


def unique_native_name_reads(reads):
    """同一 PTS 只有一票；字形矛盾及独立证据优先于单模型平均分。"""
    unique={};strengths={}
    for index,read in enumerate(reads):
        cross=False
        if read.get('cross_pts_word_evidence'):
            from target_name_reader import complete_cross_pts_words
            cross=complete_cross_pts_words(read)
            if not cross:continue
        strength=(bool(read.get('tail_evidence',{}).get('conflict')),bool(read.get('shape_evidence')),cross,bool(read.get('word_evidence')),read.get('confidence',0))
        key=('frame',read['frame']) if read.get('frame') is not None else ('read',index)
        if key not in unique or strength>strengths[key]:unique[key]=read;strengths[key]=strength
    return list(unique.values())


def native_tail_constraints(reads):
    """原生字形的独立反证可否决同一尾段的另一错读，不能合成姓名。"""
    constraints=[]
    for read in unique_native_name_reads(reads):
        proof=read.get('tail_evidence') or {};shape=proof.get('shape_evidence') or {};boundary=read.get('boundary_evidence') or {}
        if proof.get('conflict') is not True or proof.get('method')!='independent_ascii_tail_and_native_counters':continue
        independent=proof.get('independent_reads') or []
        if len(independent)<2 or len({item.get('padding') for item in independent})<2:continue
        alternative=independent[0].get('name','');candidate=proof.get('candidate_suffix','')
        if not re.fullmatch(r'[A-Za-z0-9]{3,}',alternative) or not alternative[-1].isdigit():continue
        if len(candidate)!=len(alternative) or candidate[:-1].casefold()!=alternative[:-1].casefold() or proof.get('native_primary_suffix')!=alternative:continue
        if not all(item.get('name')==alternative and item.get('confidence',0)>=.80 and item.get('terminal_confidence',0)>=.95 for item in independent):continue
        observations=shape.get('observations') or []
        if shape.get('method')!='native_two_enclosed_counters' or len(observations)<2:continue
        if len({item.get('threshold_fraction') for item in observations})<2 or any(len(item.get('holes',[]))!=2 for item in observations):continue
        box=boundary.get('box');region=shape.get('box')
        if boundary.get('method')!='native_ctc_name_crop' or not box or not region or len(box)!=4 or len(region)!=4:continue
        if any(not isinstance(value,(int,float)) or not math.isfinite(value) for value in [*box,*region]):continue
        x,y,w,h=region
        if box[2]<=box[0] or box[3]<=box[1] or min(x,y)<0 or min(w,h)<=0 or x+w>box[2]-box[0] or y+h>box[3]-box[1]:continue
        if any(any(hole.get('area',0)<=0 for hole in item['holes']) for item in observations):continue
        constraints.append((alternative[:-1].casefold(),alternative[-1]))
    return constraints


def native_name_consensus(reads):
    from player_names import consensus_name,name_key,strip_clan_tag
    from collections import Counter
    tail_constraints=native_tail_constraints(reads)
    reads=[read for read in unique_native_name_reads(reads) if not read.get('tail_evidence',{}).get('conflict')]
    # 其他原生帧确实读到首部 [TAG] 时，额外字符后的同一标签不能
    # 认证那个前导字符，更不能靠较长字符串压掉实际读到的裸名。
    tags=set()
    for read in reads:
        match=re.match(r'^[\[【]([^\[\]【】\s]{1,6})[\]】]\s*(.+)$',read.get('raw_name',read.get('name','')))
        if match:tags.add((name_key(match[1]),name_key(match[2])))
    def misplaced_clan(read):
        match=re.match(r'^([^\[【]+)[\[【]([^\[\]【】\s]{1,6})[\]】]\s*(.+)$',read.get('name',''))
        return bool(match and (name_key(match[2]),name_key(match[3])) in tags and not read.get('boundary_evidence',{}).get('verified_leading_name'))
    reads=[read for read in reads if not misplaced_clan(read)]
    symbols={name_key(read.get('name')):{other['name'] for other in reads if other.get('shape_evidence') and '□' in other.get('name','') and name_key(other['name'])==name_key(read.get('name'))} for read in reads if read.get('shape_evidence') and '□' in read.get('name','')}
    reads=[read for read in reads if name_key(read.get('name')) not in symbols or read['name'] in symbols[name_key(read['name'])]]
    def extends(longer,shorter):
        return bool(shorter and len(longer)>len(shorter) and (longer.endswith(shorter) or longer.startswith(shorter)))
    def omitted_cjk(longer,shorter):
        if not shorter or not 0<len(longer)-len(shorter)<=2:return False
        stream=iter(longer)
        return all(any(value==char for value in stream) for char in shorter)
    def word_proof(read):
        words=read.get('word_evidence',[])
        if not words or strip_clan_tag(read['name']).casefold()!=strip_clan_tag(' '.join(word.get('name','') for word in words)).casefold():return False
        return all(word.get('box') and len(word.get('models',[]))>=2 and all(any(value.get('name')==word['name'] and value.get('confidence',0)>=.80 for value in model) for model in word['models']) for word in words)
    def physical_extent(read):
        # 真实方块形状，或保留词裁片及两模型读数的独立复核，才能证明多出的字形。
        return bool(read.get('shape_evidence') or complete_words(read))
    def complete_words(read):
        boundary=read.get('boundary_evidence',{});box=boundary.get('box');words=read.get('word_evidence',[])
        if not word_proof(read) or boundary.get('method')!='native_ctc_name_crop' or not box:return False
        if read.get('cross_pts_word_evidence'):
            from target_name_reader import complete_cross_pts_words
            return complete_cross_pts_words(read)
        if any(left['box'][2]!=right['box'][0] for left,right in zip(words,words[1:])):return False
        full=' '.join(word['name'] for word in words)
        if re.match(r'^[\[【]',full):
            compact=lambda text:re.sub(r'\s+','',text or '').casefold()
            if compact(full)!=compact(read.get('raw_name')) or compact(full)!=compact(boundary.get('ctc_name')):return False
        # 两模型逐词覆盖整个真实裁片，且全行 CTC 的姓名字符/发射范围相符；
        # 这才能反证单模型的空格吞并、动作残字或积分尾巴，不能凭长短选字。
        return bool(name_key(boundary.get('ctc_name'))==name_key(read['name']) and box[0]<=boundary.get('ctc_first_x',-1)<boundary.get('ctc_last_x',-1)<=box[2] and words[0]['box'][0]==0 and words[-1]['box'][2]==box[2]-box[0] and all(word['box'][1]==0 and word['box'][3]==box[3]-box[1] for word in words))
    # 中文没有拉丁名字的独立双模型词证据，整行动作/数字的高均分
    # 不能替代中文字形。已经有实际裁片时，
    # 未隔离姓名的行回退读数、与原生整行 CTC 相冲突的单模型裁片，
    # 都不能给整名投票；独立完整词证据或可见符号证明可以解决该冲突。
    raw_reads=list(reads)
    cjk_cropped=any(any('\u3400'<=char<='\u9fff' for char in read.get('name','')) for read in reads) and any(read.get('boundary_evidence',{}).get('method')=='native_ctc_name_crop' for read in reads)
    if cjk_cropped:
        qualified=[]
        for read in reads:
            if physical_extent(read):qualified.append(read);continue
            boundary=read.get('boundary_evidence') or {}
            if boundary.get('method')=='native_ctc_name_crop' and name_key(boundary.get('ctc_name'))==name_key(read['name']):qualified.append(read)
        reads=qualified
    complete=[read for read in reads if read.get('confidence',0)>=.85 and complete_words(read)]
    proved=Counter(strip_clan_tag(read['name']).casefold() for read in complete)
    settled=[spelling for spelling,count in proved.items() if count>=2]
    def family(left,right):return name_key(left)==name_key(right) or extends(name_key(left),name_key(right)) or extends(name_key(right),name_key(left))
    if any(left!=right and family(left,right) for left in settled for right in settled):return None
    reads=[read for read in reads if physical_extent(read) or not any(family(read['name'],spelling) and strip_clan_tag(read['name']).casefold()!=spelling for spelling in settled)]
    truncated={name_key(read.get('name')) for read in reads if any(other.get('confidence',0)>=.85 and physical_extent(other) and extends(name_key(other.get('name')),name_key(read.get('name'))) for other in reads)}
    valid=[read for read in reads if name_key(read.get('name')) not in truncated]
    # 同一姓名的点号、下划线和词间空格也属于拼写，不能用只含字母数字的键吞掉差异。
    spacing={}
    for read in valid:
        if read.get('confidence',0)<.80:continue
        spelling=strip_clan_tag(read['name']).casefold()
        spacing.setdefault(re.sub(r'\s+','',spelling),set()).add(spelling)
    if any(len(variants)>1 for variants in spacing.values()):return None
    spellings=Counter(strip_clan_tag(read['name']).casefold() for read in valid if read.get('confidence',0)>=.80)
    reliable=[key for key,count in spellings.items() if count>=2]
    if not reliable:return None
    key=max(reliable,key=lambda key:(spellings[key],sum(read.get('confidence',0) for read in valid if strip_clan_tag(read['name']).casefold()==key)))
    if sum(count==spellings[key] for count in spellings.values())>1:return None
    if any(strip_clan_tag(read['name']).casefold()!=key and family(read['name'],key) for read in complete):return None
    # 字符串包含只说明拼写冲突，不能证明姓名哪端被裁掉。没有图像边界
    # 证据时保留原读数并等待后续原生帧，不能直接删除短读数。
    if any(read.get('confidence',0)>=.85 and extends(name_key(read.get('name')),name_key(key)) for read in valid):return None
    value=consensus_name([read for read in valid if strip_clan_tag(read['name']).casefold()==key])
    if value:
        if cjk_cropped and not any(spelling==strip_clan_tag(value['name']).casefold() for spelling in settled):
            if any(read.get('confidence',0)>=.85 and omitted_cjk(name_key(read.get('name')),name_key(value['name'])) for read in raw_reads):return None
        counts=Counter(name_key(read['name']) for read in valid if read.get('confidence',0)>=.80)
        if sum(count==counts[name_key(value['name'])] for count in counts.values())>1:return None
        spelling=strip_clan_tag(value['name']).casefold()
        for stem,terminal in tail_constraints:
            match=re.search(re.escape(stem)+r'(.)$',spelling)
            if match and match[1]!=terminal:return None
    return value


def native_action_consensus(reads):
    """完整助攻动作语法须来自两张不同 PTS；模板、姓名及未知动作不补票。"""
    unique={read.get('frame',read.get('time')):read for read in reads}
    known=[]
    for read in unique.values():
        parsed=parse_result_line(read.get('text',''))
        if read.get('confidence',0)>=.85 and parsed and parsed['kind']=='assist' and parsed['action'] in {'knock','elimination'} and parsed['action']==read.get('action'):
            known.append(read)
    return known[0]['action'] if len(known)>=2 and len({read['action'] for read in known})==1 else None


def pair_native_assist_actions(events,*,time_basis='event_timeline'):
    """只链接原生证实的同目标两个阶段；不合并事件或改动统计。"""
    from player_names import strip_clan_tag
    pending=[]
    for event in events:event.pop('native_action_pair',None)
    for event in sorted(events,key=lambda item:item['time']):
        if event.get('kind')!='assist' or event.get('native_action_status')!='confirmed' or event.get('native_name_status')!='confirmed':continue
        if event.get('action')=='knock':pending.append(event);continue
        if event.get('action')!='elimination':continue
        prior=next((other for other in reversed(pending) if 0<event['time']-other.get('last_seen',other['time'])<=25 and strip_clan_tag(other.get('target_text')).casefold()==strip_clan_tag(event.get('target_text')).casefold()),None)
        if prior is not None:
            pair={'knock_time':prior['time'],'elimination_time':event['time'],'time_basis':time_basis,'method':'same_target_native_action_phases'}
            prior['native_action_pair']=pair;event['native_action_pair']=pair;pending.remove(prior)


def native_target_names(source,events,profile=None,on_activity=None,*,hud_profile=None,context_events=None):
    """先读三张原生帧，缺首尾字冲突时最多补五张；不改事件种类或时间。"""
    from hud_enrichment import native_frames
    from player_names import consensus_name,name_key,strip_clan_tag
    from latin_word_boundaries import supports_word_spacing
    from target_name_reader import name_recipe
    from outcome_reader import spectator_view
    from app_cancel import check_cancel
    source=Path(source);before=fingerprint(source);metadata,video=probe(source)
    try:video_end=float(video.get('start_time') or 0)+float(video.get('duration') or 0)
    except (TypeError,ValueError):video_end=0.
    duration=max(float(metadata['format']['duration']),video_end if math.isfinite(video_end) else 0.);profile=profile or load_profile()
    if hud_profile and hud_profile.get('layout_version'):
        from hud_layout import outcome_profile
        profile=outcome_profile(hud_profile,profile)
    context=events if context_events is None else context_events
    results=[dict(event) for event in events];plans={};evidence=[[] for _ in events];actions=[[] for _ in events]
    word_probes=[[] for _ in events];probe_bytes=0
    for index,event in enumerate(events):
        if event.get('kind') not in KINDS:continue
        following=min((other['time'] for other in context if other.get('kind')==event.get('kind') and other['time']>event['time']),default=duration)
        for delta in [.08,.40,.72]:
            second=round(event['time']+delta,5)
            if 0<=second<min(duration-.03,following-.03):plans.setdefault(second,[]).append(index)
    if not plans:return results
    engine=None;independent_reader=None;gate=PrefixGate(profile);completed=0;total=len(plans)+25*len(events)
    def inspect(requested,indices,*,independent_names=False,action_phase='start',collect_names=True):
        nonlocal engine,completed,independent_reader,probe_bytes
        check_cancel()
        frame=next(native_frames(source,0,duration,[requested]),None)
        if on_activity:on_activity({'frames_done':completed,'frames_total':total,'message':'原生画面复核战果姓名'})
        completed+=1
        if frame is None:return
        second,image=frame
        # 解码 PTS 只能在所请求时刻后一个帧间隔内；跨过缺损时间段不能关联到别的战果。
        if not 0<=second-requested<.15:return
        if spectator_view(image,inactive_view(image)):return
        if engine is None:engine=new_engine()
        if independent_reader is None:
            from target_name_reader import TargetNameReader
            independent_reader=TargetNameReader(getattr(engine,'text_rec',None))
        name_reader=(independent_reader if independent_names else independent_reader.read_latin_only) if collect_names else None
        read=recognize_frame(image,profile,engine,prefix_matches=gate.inspect(image),independent_names=name_reader,tail_review=independent_reader.review_tail if collect_names else None)
        for index in indices:
            original=events[index];choices=[event for event in read['events'] if event['kind']==original['kind']]
            if len(choices)>1 and original.get('sample_size') and original.get('box'):
                rw,rh=original['sample_size'];box=original['box'];cy=(box[1]+box[3])/2*image.shape[0]/rh
                choices=[event for event in choices if abs((event['box'][1]+event['box'][3])/2-cy)<=max(8,(box[3]-box[1])*image.shape[0]/rh)]
            if len(choices)>1:
                choices=[event for event in choices if name_key(event.get('target_text'))==name_key(original.get('target_text'))]
            if len(choices)!=1:continue
            event=choices[0]
            if original.get('kind')=='assist':
                previous=max((other['time'] for other in context if other.get('kind')=='assist' and other['time']<original['time']),default=-1.)
                following=min((other['time'] for other in context if other.get('kind')=='assist' and other['time']>original['time']),default=duration)
                end=max(original['time']+.8,original.get('last_seen',original['time']))+.25
                in_start=max(0.,previous+.03,original['time']-.65)<=second<min(following-.03,end,original['time']+3.)
                in_terminal=action_phase.startswith('terminal') and max(0.,original['time'],original.get('last_seen',original['time'])-.4)<=second<following-.03
                if in_start or in_terminal:
                    actions[index].append({'action':event.get('action','unknown'),'text':event.get('text',''),'confidence':event.get('confidence',0),
                        'time':second,'requested_time':requested,'frame':str(second),'phase':action_phase,'box':event.get('box'),'method':'native_complete_action_grammar'})
            if not collect_names:continue
            name=clean_target_name(event.get('target_text',''),allow_rendered_square=bool(event.get('target_shape_evidence')))
            confidence=event.get('target_read_confidence',event.get('text_confidence',0))
            if name:evidence[index].append({'name':name,'confidence':confidence,'time':second,'requested_time':requested,'frame':str(second),**({'shape_evidence':event['target_shape_evidence']} if event.get('target_shape_evidence') else {}),**({'word_evidence':event['target_word_evidence']} if event.get('target_word_evidence') else {}),**({'boundary_evidence':event['target_boundary_evidence']} if event.get('target_boundary_evidence') else {}),**({'tail_evidence':event['target_tail_evidence']} if event.get('target_tail_evidence') else {})})
            boundary=event.get('target_boundary_evidence') or {};box=boundary.get('box')
            if not name or confidence<.80 or not supports_word_spacing(name) or boundary.get('prefix_anchor')!='template' or not box:continue
            previous=max((other.get('last_seen',other['time']) for other in context if other.get('kind')==original.get('kind') and other['time']<original['time']),default=-1.)
            following=min((other['time'] for other in context if other.get('kind')==original.get('kind') and other['time']>original['time']),default=duration)
            bounds=[max(0.,previous+.03,original['time']-.65),min(duration-.03,following-.03,original['time']+1.5)]
            if not bounds[0]<=requested<=second<bounds[1] or any(probe['native_pts']==second for probe in word_probes[index]):continue
            left,top,right,bottom=map(int,box)
            if not 0<=left<right<=image.shape[1] or not 0<=top<bottom<=image.shape[0]:continue
            patch=image[top:bottom,left:right];size=patch.nbytes
            if size>256*1024:continue
            probe={'source':dict(before),'event_key':[original.get(key) for key in ['kind','time','last_seen','box','prefix_box']],
                'phase':'start','native_pts':second,'requested_time':requested,'context_bounds':bounds,'boundary':dict(boundary),
                'image':patch.copy(),'crop_sha256':hashlib.sha256(patch.tobytes()).hexdigest(),'name':name,'confidence':confidence}
            pool=word_probes[index]
            if len(pool)>=6:
                score=lambda value:(len(strip_clan_tag(value['name']).split()),value['confidence'])
                weakest_index=min(range(len(pool)),key=lambda position:score(pool[position]));weakest=pool[weakest_index]
                if score(probe)<=score(weakest):continue
                pool.pop(weakest_index);probe_bytes-=weakest['image'].nbytes
            if probe_bytes+size<=8*1024*1024:pool.append(probe);probe_bytes+=size
    for requested in sorted(plans):inspect(requested,plans[requested])
    extra={}
    for index,reads in enumerate(evidence):
        if native_name_consensus(reads):continue
        strong=[read for read in reads if read['confidence']>=.85 and len(name_key(read['name']))>=4]
        if not strong:continue
        seed=max(strong,key=lambda read:(len(name_key(read['name'])),read['confidence']));key=name_key(seed['name'])
        truncated=[read for read in strong if 0<len(key)-len(name_key(read['name']))<=2 and (key.endswith(name_key(read['name'])) or key.startswith(name_key(read['name'])))]
        # 必须有同一首尾片段的实际读数冲突，不能追随另一条无关战果。
        if not truncated:continue
        original=events[index]
        previous=max((other['time'] for other in context if other.get('kind')==original.get('kind') and other['time']<original['time']),default=0.)
        following=min((other['time'] for other in context if other.get('kind')==original.get('kind') and other['time']>original['time']),default=duration)
        for delta in [-.08,-.06,-.04,-.02,.02]:
            second=round(seed['requested_time']+delta,5)
            if max(0.,previous+.03)<=second<min(duration-.03,following-.03) and second not in plans:extra.setdefault(second,[]).append(index)
    for requested in sorted(extra):inspect(requested,extra[requested])
    # 稀疏事件时间可能晚于提示出现；英文先在本事件附近补读，中文继续使用末端窗口。
    late={}
    from target_name_reader import model_available
    for index,reads in enumerate(evidence):
        if native_name_consensus(reads):continue
        event=events[index]
        names=[event.get('target_text','')]+[read['name'] for read in reads]
        nonlatin=any(any(char.isalpha() and not char.isascii() for char in name) for name in names)
        if not nonlatin:
            from player_names import close_name
            reliable=[read['name'] for read in reads if read['confidence']>=.85]
            if len(reliable)>=2 and not any(close_name(left,right) for i,left in enumerate(reliable) for right in reliable[i+1:]):continue
        if not model_available(latin=not nonlatin):continue
        end=min(event.get('last_seen',event['time']+.8),event['time']+1.25)
        following=min((other['time'] for other in context if other.get('kind')==event.get('kind') and other['time']>event['time']),default=duration)
        previous=max((other['time'] for other in context if other.get('kind')==event.get('kind') and other['time']<event['time']),default=0.)
        moments=[end+delta for delta in [.08,.10,.12,.14,.16,.18,.20,.22]] if nonlatin else [event['time']+delta for delta in [-.60,-.55,-.50,-.45,-.40,-.35,-.30,-.25,.76,.80,.84,.88]]
        for moment in moments:
            second=round(moment,5)
            if max(0.,previous+.03)<=second<min(duration-.03,following-.03) and second not in plans and second not in extra:late.setdefault(second,[]).append(index)
    for requested in sorted(late):inspect(requested,late[requested],independent_names=True)
    # 两套模型已读到完整词，但原生帧之间仍有拼写冲突时，只在这些实际证据附近补读。
    refinements={}
    for index,reads in enumerate(evidence):
        if native_name_consensus(reads):continue
        seeds={}
        for read in sorted(reads,key=lambda read:read['confidence'],reverse=True):
            if read.get('word_evidence') and read['confidence']>=.80:seeds.setdefault(read['name'],read)
        event=events[index]
        previous=max((other['time'] for other in context if other.get('kind')==event.get('kind') and other['time']<event['time']),default=0.)
        following=min((other['time'] for other in context if other.get('kind')==event.get('kind') and other['time']>event['time']),default=duration)
        for seed in list(seeds.values())[:2]:
            for delta in [-.04,-.02,.02,.04]:
                second=round(seed['time']+delta,5)
                if max(0.,previous+.03,event['time']-.65)<=second<min(duration-.03,following-.03,event['time']+1.5) and second not in plans and second not in extra and second not in late:refinements.setdefault(second,[]).append(index)
    for requested in sorted(refinements):inspect(requested,refinements[requested],independent_names=True)
    for index,reads in enumerate(evidence):
        if native_name_consensus(reads) or len(word_probes[index])<2 or independent_reader is None:continue
        spacing={}
        for read in reads:
            if read.get('confidence',0)<.80:continue
            name=read.get('name','');spelling=strip_clan_tag(name).casefold()
            if supports_word_spacing(name):spacing.setdefault(re.sub(r'\s+','',spelling),set()).add(spelling)
        if not any(len(variants)>1 for variants in spacing.values()):continue
        if on_activity:on_activity({'frames_done':completed,'frames_total':total,'message':'核对姓名词间空白与原生字形'})
        fresh=independent_reader.refine_latin_words(word_probes[index])
        for read in fresh:
            binding=read.get('native_word_binding') or {}
            cached_probe=next((item for item in word_probes[index] if item['native_pts']==read.get('time')),None)
            if cached_probe is None or any(binding.get(key)!=cached_probe[key] for key in ['source','event_key','phase','native_pts','requested_time','context_bounds','crop_sha256']):continue
            if read.get('boundary_evidence')!=cached_probe['boundary']:continue
            evidence[index].append(read)
    # 裁片只在本次事件范围内复核，不能进入全局模型池或断点结果。
    word_probes.clear()
    terminal={};terminal_needed=set();terminal_requested={};terminal_actions={};terminal_windows={}
    for index,event in enumerate(events):
        if event.get('kind')!='assist':continue
        prior=parse_result_line(event.get('text','')) or {}
        start_action=native_action_consensus(actions[index])
        merged=event.get('last_seen',event['time'])-event['time']>3. or event.get('action')=='elimination' and prior.get('action') in {'knock','elimination'} and start_action=='knock'
        if not merged:continue
        terminal_needed.add(index);terminal_requested[index]=[]
        following=min((other['time'] for other in context if other.get('kind')=='assist' and other['time']>event['time']),default=duration)
        for delta in [-.32,-.08]:
            second=round(event.get('last_seen',event['time'])+delta,5)
            if max(0.,event['time']+.03)<=second<min(duration-.03,following-.03):terminal.setdefault(second,[]).append(index);terminal_requested[index].append(second)
    for requested in sorted(terminal):inspect(requested,terminal[requested],action_phase='terminal_pre',collect_names=False)
    after={}
    for index in terminal_needed:
        event=events[index];action=native_action_consensus([read for read in actions[index] if read.get('phase')=='terminal_pre'])
        # last_seen 本身可能是消灭的第一张稀疏帧；之前仍读到击倒时，须在
        # last_seen 之后核对，不能把合法的短击倒→消灭轨迹降回击倒。
        if action and not(action=='knock' and event.get('action')=='elimination'):
            terminal_actions[index]=action;terminal_windows[index]='pre_last_seen';continue
        following=min((other['time'] for other in context if other.get('kind')=='assist' and other['time']>event['time']),default=duration)
        for delta in [.08,.40]:
            second=round(event.get('last_seen',event['time'])+delta,5)
            if 0<=second<min(duration-.03,following-.03):after.setdefault(second,[]).append(index);terminal_requested[index].append(second)
    for requested in sorted(after):inspect(requested,after[requested],action_phase='terminal_post',collect_names=False)
    for index in terminal_needed:
        if index not in terminal_actions:
            terminal_actions[index]=native_action_consensus([read for read in actions[index] if read.get('phase')=='terminal_post'])
            terminal_windows[index]='post_last_seen' if terminal_actions[index] else 'pending'
    total=completed
    for index,(event,reads,action_reads) in enumerate(zip(results,evidence,actions)):
        reads=unique_native_name_reads(reads)
        # 同一结果的其他画面确实读到 [TAG] 时，才能去掉漏读括号的 TAG 前缀。
        tagged=[]
        for read in reads:
            match=re.match(r'^[\[【]([^\[\]【】\s]{1,6})[\]】]\s*(.+)$',read['name'])
            if match:
                tagged.append((name_key(match[1]),name_key(match[2]),match[2]))
                read.setdefault('raw_name',read['name']);read['name']=match[2]
        for read in reads:
            for tag,bare,spelling in tagged:
                if name_key(read['name'])==tag+bare:
                    read['raw_name']=read['name'];read['name']=spelling;break
        value=native_name_consensus(reads)
        event['native_name_evidence']=reads
        event['native_name_status']='confirmed' if value else 'unconfirmed'
        event['native_name_version']=PARSER_VERSION
        event['native_name_recipe']=name_recipe()
        if event.get('kind')=='assist':
            event['native_action_evidence']=list({read['frame']:read for read in action_reads}.values())
            event['native_action_version']=PARSER_VERSION
            start_action=native_action_consensus([read for read in action_reads if read.get('phase','start')=='start'])
            merged=index in terminal_needed
            action=terminal_actions[index] if merged else start_action
            event['native_action_status']='confirmed' if action else 'unconfirmed_merged_track' if merged else 'unconfirmed'
            event['native_action_phases']={'start':start_action or 'unknown'}
            if merged:
                event['native_action_phases']['terminal']=action or 'unknown';event['native_action_terminal_requested']=terminal_requested[index];event['native_action_terminal_window']=terminal_windows[index]
            if action or not merged:
                if event.get('action')!=(action or 'unknown'):event['native_action_previous']=event.get('action','unknown')
                event['action']=action or 'unknown'
        if value:
            event.update(target_text=value['name'],target_confidence=value['confidence'],target_method='two_frame_native_name_consensus')
            shapes=[read for read in reads if read.get('shape_evidence') and read['name']==value['name']]
            if '□' in value['name'] and len({read['frame'] for read in shapes})>=2:event['target_shape_evidence']=[{'time':read['time'],**read['shape_evidence']} for read in shapes]
            else:event.pop('target_shape_evidence',None)
    pair_native_assist_actions(results,time_basis='native_source')
    if fingerprint(source)!=before:raise ValueError('复核战果姓名期间原录像发生变化')
    if on_activity:on_activity({'frames_done':total,'frames_total':total,'message':'原生战果姓名复核完成'})
    return results


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


def calibrated_sample_size(profile):
    """像素模板在标准界面上按 HUD 缩放；2Hz 采样宽 1280，高度随录像比例。精简界面尚未校准。"""
    if profile.get('ui_layout')=='compact':return None
    if not profile.get('layout_version'):return [1280,540]
    width,height=profile['reference_size']
    return [1280,round(1280*height/width/2)*2]


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
    profile=profile or load_profile()
    if cache.get('profile',{}).get('layout_version'):
        from hud_layout import outcome_profile
        profile=outcome_profile(cache['profile'],profile)
    samples=Path(samples); fps=cache['fps']
    if fps<2 and _allow_upgrade and _stop_after_positive:
        return _inspect_low_frequency(cache,samples,candidates,profile,checkpoint)
    source=Path(cache['source']['path']); identity=fingerprint(source)
    if identity!=cache['source']: raise ValueError('原录像发生变化，不能复用结果提示')
    checkpoint=Path(checkpoint) if checkpoint else samples.parent/'combat-outcomes.json'
    checkpoint.parent.mkdir(parents=True,exist_ok=True)
    templates={str(BASE/e['gray']):hashlib.sha256((BASE/e['gray']).read_bytes()).hexdigest() for e in profile.get('prefix_templates',[])}
    signature=hashlib.sha256(json.dumps({'version':RULE_VERSION,'source':identity,'fps':fps,'samples':str(samples.resolve()),
        'profile':profile,'templates':templates,'model':MODEL_SHA,'only_existing':_only_existing,'stop_after_positive':_stop_after_positive,'reader_version':'toast-lines-v8','grammar':TOAST_GRAMMAR_VERSION,'confirmation':CONFIRMATION_VERSION,
        'bounds':[(c['start'],c['end']) for c in candidates]},sort_keys=True).encode()).hexdigest()
    if checkpoint.exists():
        saved=json.loads(checkpoint.read_text(encoding='utf-8'))
        if saved.get('signature')==signature and saved.get('complete') and saved.get('parser_version')==PARSER_VERSION and saved.get('grammar_version')==TOAST_GRAMMAR_VERSION: return saved
    wanted={i for c in candidates for i in candidate_indices(c,fps)}
    journal=RowJournal(checkpoint.with_suffix('.toast-rows.jsonl'),signature,
        lambda r,index:r.get('index') in wanted and r.get('time')==(r['index']-.5)/fps and r.get('status') in ['negative','ambiguous','excluded_view','self_event'])
    observations={r['index']:r for r in journal.rows}
    restore_english_events(observations)
    hud_rows={int(r['frame'][:-4]):r for r in cache['rows']}
    gate=PrefixGate(profile); engine=None; checked_new=0; ocr_new=0; sampled_new=0
    extra_root=checkpoint.parent/('combat-outcome-samples-'+signature[:12])
    decisions=[]
    def observe(index,path):
        nonlocal engine,checked_new,ocr_new
        if index in observations: return observations[index]
        check_cancel(); image=read_image(str(path))
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
            generic=bool(profile.get('layout_version') and (text_line_gate(image,profile) or short_text_hint(image,profile)))
            if best>=threshold or generic:
                if engine is None: engine=new_engine()
                result=recognize_frame(image,profile,engine,prefix_matches=matches); ocr_new+=1
                if not _stop_after_positive:
                    # 统计阶段：文字常把“擊”读成“擎/驿”或漏掉，但必须由行首的强图形匹配支持修正。
                    for line in result['lines']:
                        if parse_result_line(line['text']):continue
                        supports=[m for m in matches if m['score']>=.88 and abs(m['box'][0]-line['box'][0])<=8 and
                                  abs((m['box'][1]+m['box'][3]-line['box'][1]-line['box'][3])/2)<=8]
                        for match in sorted(supports,key=lambda m:-m['score']):
                            fixed=line['text']
                            if match['kind']=='knock' and re.match(r'^(?:[擎驛驿擊击撃攀摩]倒|倒)',fixed):
                                fixed=re.sub(r'^(?:[擎驛驿擊击撃攀摩]倒|倒)','擊倒',fixed)
                            else:continue
                            parsed=parse_result_line(fixed)
                            if parsed and not is_known_dialogue(fixed):
                                result['events'].append({**parsed,'confidence':max(line['prefix_confidence'],.86),
                                    'text_confidence':line['confidence'],'box':line['box'],'prefix_repair':'strong_prefix_template'})
                                break
                item.update(lines=result['lines'],known_dialogue=result['known_dialogue'])
                possible=[]
                for event in result['events']:
                    event={**event,'sample_size':item['sample_size']}
                    support=_same_line_gate(event,matches)
                    matching=[m for m in matches if m['kind']==event['kind'] and abs((m['box'][1]+m['box'][3])/2-(event['box'][1]+event['box'][3])/2)<=10 and event['box'][0]-5<=m['box'][0]<=event['box'][2]+5]
                    if matching:
                        strongest=max(matching,key=lambda m:m['score']);event['prefix_box']=strongest['box']
                    english=bool(re.match(r'^(?:ASSIST|KNOCKED DOWN|ELIMINATED)\b',event['text'],re.I))
                    if english and event['confidence']>=.90 and len(event.get('target_text',''))>=2 and support<threshold:
                        potential={**event,'time':item['time'],'frame':item['frame'],'ownership':'self','confirmation_basis':'english_toast_grammar'}
                        possible.append(potential)
                        if any(previous['time']!=item['time'] and abs(previous['time']-item['time'])<=1.1 and
                            any(e['kind']==event['kind'] and same_english_target(e.get('target_text',''),event.get('target_text','')) for e in previous.get('possible_events',[])) for previous in observations.values()):
                            item['events'].append({**potential,'confirmation':'two_frame_english_toast'})
                        continue
                    locale=event.get('locale') or (parse_result_line(event['text']) or {}).get('locale')
                    if locale in GRAMMAR_LOCALES and support<threshold and event['confidence']>=.75 and grammar_confirmable(event):
                        # 简体、俄语等没有像素模板的界面：行首语法 + 相邻帧同一条提示；或单帧极高置信度且读到名字。
                        potential={**event,'time':item['time'],'frame':item['frame'],'template_score':support,'ownership':'self','confirmation_basis':'toast_grammar'}
                        possible.append(potential)
                        confirmed=any(previous['time']!=item['time'] and abs(previous['time']-item['time'])<=1.1 and
                            any(other.get('confirmation_basis')=='toast_grammar' and other['kind']==event['kind'] and
                                (same_english_target(other.get('target_text',''),event.get('target_text','')) or same_toast_slot(other,event))
                                for other in previous.get('possible_events',[])) for previous in observations.values())
                        if confirmed:item['events'].append({**potential,'confirmation':'two_frame_toast_grammar'})
                        elif event['confidence']>=.93 and len(event.get('target_text') or '')>=2:
                            item['events'].append({**potential,'confirmation':'strong_single_toast_grammar'})
                        continue
                    if event['confidence']>=.85 and support>=threshold:
                        item['events'].append({**event,'time':item['time'],'frame':item['frame'],'template_score':support,'ownership':'self'})
                    elif event['confidence']>=.65 and support>=.85:
                        # 真实录像中同一条击倒提示连续多帧的行首图形得分稳定在 0.87–0.90，而 OCR 置信度只有 0.6–0.8；
                        # 相邻帧同一行首位置（同一条提示）均达标才确认，单帧仍不算。
                        potential={**event,'time':item['time'],'frame':item['frame'],'template_score':support,'ownership':'self'}
                        possible.append(potential)
                        if any(abs(previous['time']-item['time'])<=1.1 and previous['time']!=item['time'] and
                               any(e['kind']==event['kind'] and (min(support,e.get('template_score',0))>=.9 or same_toast_slot(e,event)) for e in previous.get('possible_events',[])) for previous in observations.values()):
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
                use_cuda=cache.get('backend') in {'dml','cuda'} or os.environ.get('APEX_OCR_BACKEND') in {'dml','cuda'}
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
        supported_style=(_locale_confirmed(cache,observations,profile) and all(r.get('sample_size')==calibrated_sample_size(profile) for r in covered))
        reliable_absence=(len(covered)==len(indices) and fps>=calibration.get('minimum_fps',2)
                          and calibration.get('negative_decision_enabled',False) and not uncertain and supported_style)
        if found: status='kept'; reason='已确认本人击倒、助攻或消灭提示'
        elif reliable_absence: status='rejected'; reason='完整检查候选后未发现本人击倒、助攻或消灭提示'
        else: status='review'; reason='提示模糊、采样覆盖不足或尚未校准，需复核本人结果'
        counter=None
        if not found and not _only_existing and 'own_kill' in candidate.get('combat_evidence',{}).get('accepted_reasons',[]):
            # 本人 HUD 击杀数在交战内确认增长，与界面语言无关；文字提示读不到时用它保留交战，
            # 但不当成可计数的提示事件。
            status='kept';reason='本人击杀计数增长（界面语言的结果提示未识别）';counter='own_kill_counter'
        decisions.append({'candidate_index':position,'status':status,'reason':reason,'events':found,**({'counter_basis':counter} if counter else {}),
            'coverage':{'expected_frames':len(indices),'checked_frames':len(covered),'fps':fps,
                        'ambiguous_frames':[r['frame'] for r in uncertain],'reliable_absence':reliable_absence,
                        'calibrated_style_confirmed':supported_style,
                        'stopped_after_positive':bool(found) and _stop_after_positive}})
        print(f'本人战果提示: {position+1}/{len(candidates)} 段，{status}，新增文字识别 {ocr_new} 帧',flush=True)
    report={'signature':signature,'version':RULE_VERSION,'parser_version':PARSER_VERSION,'grammar_version':TOAST_GRAMMAR_VERSION,'complete':True,'source':identity,
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
    cuda,threads,_=decode_policy(video,os.environ.get('APEX_OCR_BACKEND') in {'dml','cuda'})
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
