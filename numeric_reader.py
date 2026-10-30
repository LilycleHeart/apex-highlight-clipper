"""固定计分数字由至少两个现有模型一致确认，不采用单个模型的高分猜测。"""
from collections import Counter
from pathlib import Path
import re
import time

from ocr_cache import ExactTextCache

METHOD='numeric-three-model-v5'


class NumericModelCache(ExactTextCache):
    """固定单图推理的原始模型读数；不同模型不共享票数或几何证据。"""
    def __init__(self,recognizer):
        super().__init__(recognizer,capacity=512)

    def __call__(self,images):
        values,elapsed=super().__call__(images)
        # 数字分离复核还有 .94/.97 门槛，补齐通用缓存已有的临界值保护。
        for image,(_,confidence) in zip(images,values):
            if any(abs(float(confidence)-threshold)<=.002 for threshold in (.94,.97)):
                self.cache.pop(self.key(image),None)
        return values,elapsed


def agreed_number(reads):
    valid=[(str(int(text)),float(confidence)) for text,confidence in reads if isinstance(text,str) and re.fullmatch(r'\d+',text.strip()) and confidence>=.88]
    counts=Counter(text for text,_ in valid)
    if not counts:return '',0.
    winner=max(counts,key=counts.get)
    if counts[winner]<2 or sum(count==counts[winner] for count in counts.values())>1:return '',0.
    # 两个模型已独立通过阈值时，第三个同字但低分的读数不能撤销这份证据。
    # 置信度取所需两票的较低值，仍不采用单模型的高分。
    confidence=sorted((confidence for text,confidence in valid if text==winner),reverse=True)[1]
    return winner,confidence


class NumericReader:
    def __init__(self,backend):
        from gpu_ocr_backend import create_ocr_engine
        from weapon_reader import MODEL_PATH
        from stat_counter_fallback import CounterFallback
        self.readers=[NumericModelCache(create_ocr_engine(backend=backend,model_path=model,rec_batch_num=1).text_rec)
                      for model in [None,MODEL_PATH,Path(__file__).resolve().parent/'models/numeric_rec_en_v4.onnx']]
        self.glyphs=CounterFallback()

    def __call__(self,images):
        from stat_counter_fallback import separated_digit_views
        started=time.perf_counter();reads=[reader(images)[0] for reader in self.readers];result=[];self.last_digit_reviews=[]
        for index,image in enumerate(images):
            values=[]
            for model in reads:
                text,confidence=model[index]
                if not re.fullmatch(r'\d+',text.strip()):
                    alias=self.glyphs.decode_numeric_alias(text,image)
                    if alias is not None:text,confidence=alias,self.glyphs.last_match_score
                values.append((text,confidence))
            original=agreed_number(values)
            if not original[0]:
                # 计分栏细体单个 0 常被三个模型读成 0/D/口 且置信度低于 .88；
                # 至少两个模型读成 0 的同形字、且像素字形是唯一一个居中闭合环时，才接受为 0。
                from stat_counter_fallback import ZERO_ALIASES,zero_glyph_proof
                zero_like=sum(1 for text,_ in values if isinstance(text,str) and text.strip() in ZERO_ALIASES)
                proof=zero_glyph_proof(image) if zero_like>=2 else None
                if proof:
                    result.append(('0',.9));self.last_digit_reviews.append({'index':index,'previous':'','text':'0','confidence':.9,'method':'zero_glyph_ring','model_reads':values,**proof})
                    continue
            proposals={};proofs=separated_digit_views(image)
            counts={proof['glyph_count'] for proof in proofs if proof['glyph_count']>len(original[0])}
            for proof in proofs if counts else []:
                reviews=[reader([proof['image']])[0][0] for reader in self.readers]
                text,confidence=agreed_number(reviews)
                if len(text) not in counts:continue
                same=[float(value) for word,value in reviews if word.strip()==text]
                if not (sum(value>=.94 for value in same)>=2 or len(same)==3 and min(same)>=.90 and max(same)>=.97):continue
                remaining=iter(text)
                if not all(any(character==other for other in remaining) for character in original[0]):continue
                geometry=next(value for value in proofs if value['glyph_count']==len(text))
                if confidence>proposals.get(text,(0,None))[0]:proposals[text]=(confidence,{**{key:value for key,value in geometry.items() if key!='image'},'model_view_threshold':proof['threshold'],'model_reads':reviews})
            if len(proposals)==1:
                text,(confidence,proof)=next(iter(proposals.items()));result.append((text,confidence))
                self.last_digit_reviews.append({'index':index,'previous':original[0],'text':text,'confidence':confidence,**proof})
            elif proposals:result.append(('',0.))
            else:result.append(original)
        return result,time.perf_counter()-started
