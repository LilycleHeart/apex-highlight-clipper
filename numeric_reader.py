"""固定计分数字由至少两个现有模型一致确认，不采用单个模型的高分猜测。"""
from collections import Counter
from pathlib import Path
import re
import time

METHOD='numeric-three-model-v4'


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
        self.readers=[create_ocr_engine(backend=backend,model_path=model,rec_batch_num=1).text_rec
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
            original=agreed_number(values);proposals={};proofs=separated_digit_views(image)
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
