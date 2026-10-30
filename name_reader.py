"""玩家名保留抗锯齿；拉丁字符使用随程序提供的英文识别模型。"""
from pathlib import Path
import math
import os
import re

import cv2
import numpy as np

from player_names import player_name,name_key
from weapon_reader import caption_views


def name_value(views,*,allow_rendered_square=False):
    choices=[]
    for text,confidence in views:
        name=player_name(text,allow_rendered_square=allow_rendered_square)
        if confidence>=.80 and name:choices.append({'name':name,'confidence':float(confidence)})
    for value in choices:value['view_agreement']=sum(name_key(other['name'])==name_key(value['name']) for other in choices)
    return max(choices,key=lambda row:(row['view_agreement'],row['confidence'])) if choices else None


def rendered_square(patch):
    """验证昵称行中实际绘制的较小空心方框；不能把 OCR 的缺字占位当成字形证据。"""
    hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV);height=patch.shape[0]
    for level in [100,120,140]:
        mask=((hsv[:,:,1]<90)&(hsv[:,:,2]>level)).astype(np.uint8)*255
        contours,hierarchy=cv2.findContours(mask,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is None:continue
        for index,contour in enumerate(contours):
            child=hierarchy[0,index,2]
            if child<0:continue
            _,_,width,tall=cv2.boundingRect(contour)
            area=cv2.contourArea(contour)
            if 5<=tall<=height*.8 and .8<=width/tall<=1.2 and area>=.85*(width-1)*(tall-1) and cv2.contourArea(contours[child])>=area*.25:return True
    return False


def review_latin_glyphs(views,reader,multilingual,value):
    """整词模型可能把数字当成常见单词字母；用独立字形和邻字重新读取。"""
    if 'I' not in value['name'] or not all(hasattr(reader,key) for key in ['session','resize_norm_img','rec_image_shape','postprocess_op']):return value
    image=views[0];height,width=image.shape[:2];shape=reader.rec_image_shape
    normalized=reader.resize_norm_img(image,max(shape[2]/shape[1],width/height))
    probabilities=reader.session(normalized[None].astype(np.float32))[0][0];tokens=[];previous=0
    for step,index in enumerate(probabilities.argmax(-1)):
        if index and index!=previous:tokens.append([reader.postprocess_op.character[int(index)],step,step+1])
        elif index and tokens:tokens[-1][2]=step+1
        previous=index
    text=''.join(token[0] for token in tokens)
    if player_name(text)!=value['name']:return value
    resized=min(normalized.shape[-1],math.ceil(shape[1]*width/height));factor=normalized.shape[-1]/len(probabilities)*width/resized
    edges=[0]+[round((left[2]+right[1])/2*factor) for left,right in zip(tokens,tokens[1:])]+[width]
    chars=list(text);evidence=[];attempts=[]
    for index,char in enumerate(chars):
        if char!='I':continue
        crops=[];contexts=[]
        for view in views:
            background=tuple(int(channel) for channel in np.median(np.concatenate([view[:4],view[-4:]],axis=0),axis=(0,1)))
            crop=view[:,max(0,edges[index]):min(width,edges[index+1])]
            if not crop.size:break
            crops.append(cv2.copyMakeBorder(crop,0,0,9,9,cv2.BORDER_CONSTANT,value=background))
            for start,end in [(max(0,index-1),index+1),(index,min(len(chars),index+2))]:
                crop=view[:,max(0,edges[start]):min(width,edges[end])]
                contexts.append((start,end,cv2.copyMakeBorder(crop,0,0,9,9,cv2.BORDER_CONSTANT,value=background)))
        if len(crops)!=2:continue
        isolated=[reader(crops)[0],multilingual(crops)[0]]
        attempts.append({'index':index,'isolated_reads':isolated})
        candidate=isolated[0][0][0]
        if len(candidate)!=1 or not candidate.isascii() or not candidate.isalnum() or candidate==char or any(read!=candidate or confidence<.85 for read,confidence in isolated[0]):continue
        if any(read!=candidate or confidence<.85 for read,confidence in isolated[1]):
            from engine_pool import pooled_engine
            from gpu_ocr_backend import create_ocr_engine
            backend=os.environ.get('APEX_OCR_BACKEND','cpu')
            independent=pooled_engine(('latin-glyph-independent-v1',backend),lambda:create_ocr_engine(backend=backend,rec_batch_num=1)).text_rec
            isolated.append(independent(crops)[0])
        confirming=[model for model in isolated if all(read==candidate and confidence>=.85 for read,confidence in model)]
        if len(confirming)<2:continue
        context_reads=[reader([crop for _,_,crop in contexts])[0],multilingual([crop for _,_,crop in contexts])[0]]
        agreed=[]
        for offset,(start,end,_) in enumerate(contexts):
            expected=text[start:index]+candidate+text[index+1:end]
            if all(model[offset][0]==expected and model[offset][1]>=.88 for model in context_reads):agreed.append(offset)
        chars[index]=candidate;evidence.append({'index':index,'line_character':char,'isolated_reads':isolated,'confirming_models':confirming,'context_reads':[{ 'range':list(contexts[offset][:2]),'reads':[model[offset] for model in context_reads]} for offset in agreed]})
    if evidence:return {**value,'raw_name':value['name'],'name':player_name(''.join(chars)),'confidence':min(value['confidence'],*(read[1] for item in evidence for model in item['confirming_models'] for read in model)),'glyph_evidence':evidence,'reader':'latin_name_glyph_review'}
    if attempts:
        pending=any(len({text for model in item['isolated_reads'] for text,_ in model})==1 and item['isolated_reads'][0][0][0]!=text[item['index']] and all(confidence>=.75 for model in item['isolated_reads'] for _,confidence in model) for item in attempts)
        return {**value,'glyph_review_attempts':attempts,'glyph_review_pending':pending}
    return value


def visible_latin_proof(patch,value,primary):
    """仅复核实际读数；标签单独裁开，独立模型不能向识别器提供昵称答案。"""
    if not value['name'].isascii() or value.get('confidence',0)<.85 or value.get('view_agreement',0)<2 or value.get('glyph_review_pending'):return None
    if not all(hasattr(primary,key) for key in ['session','resize_norm_img','rec_image_shape','postprocess_op']):return None
    from target_name_reader import ctc_tokens,model_available,LATIN_MODEL_PATH,LATIN_MODEL_SHA
    if not model_available(latin=True):return None
    _,color=caption_views(patch);gray=cv2.cvtColor(cv2.cvtColor(color,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
    tokens=ctc_tokens(color,primary);raw=''.join(token[0] for token in tokens)
    if any(len(token[0])!=1 for token in tokens):return None
    tag=re.match(r'^[.,]{0,2}\[?[^\[\]\s]{1,6}\]\s*',raw)
    if tag and tag.end()<len(tokens):
        start=tag.end();left=max(0,round((tokens[start-1][2]+tokens[start][1])/2)-3);color,gray=color[:,left:],gray[:,left:]
    if str(value.get('reader','')).startswith('latin_name'):
        reads=[{'name':player_name(text),'confidence':float(confidence)} for text,confidence in primary([color,gray])[0]]
        if all(read['name']==value['name'] and read['confidence']>=.95 for read in reads):
            from weapon_reader import MODEL_SHA
            return {'method':'independent_visible_multilingual_name','model':MODEL_SHA,'views':reads}
    from engine_pool import pooled_engine
    from gpu_ocr_backend import create_ocr_engine
    backend=os.environ.get('APEX_OCR_BACKEND','cpu')
    independent=pooled_engine(('visible-latin-name-v1',backend,LATIN_MODEL_SHA),lambda:create_ocr_engine(backend=backend,model_path=LATIN_MODEL_PATH,rec_batch_num=1)).text_rec
    reads=[{'name':player_name(text),'confidence':float(confidence)} for text,confidence in independent([color,gray])[0]]
    if not all(read['name']==value['name'] and read['confidence']>=.95 for read in reads):return None
    return {'method':'independent_visible_latin_name','model':LATIN_MODEL_SHA,'views':reads}


class NameReader:
    def __init__(self,recognizer):
        self.recognizer=recognizer
        self.japanese=None

    def __call__(self,patches):
        views=[]
        for patch in patches:
            masked,color=caption_views(patch)
            # 两个保留细笔画的视图，避免二值化吞掉重复字母或封闭轮廓。
            gray=cv2.cvtColor(cv2.cvtColor(color,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
            views.extend([masked,color,gray])
        texts=self.recognizer(views)[0] if views else []
        results=[name_value(texts[i:i+3]) for i in range(0,len(texts),3)]
        for index,value in enumerate(results):
            if value is not None:continue
            candidate=name_value(texts[index*3:index*3+3],allow_rendered_square=True)
            if candidate and '□' in candidate['name'] and candidate['confidence']>=.85 and candidate['view_agreement']>=2 and rendered_square(patches[index]):
                results[index]={**candidate,'raw_name':candidate['name'],'rendered_placeholder':True}
        latin=[];indices=[]
        for index,value in enumerate(results):
            valid=[player_name(text) for text,confidence in texts[index*3:index*3+3] if confidence>=.80 and player_name(text)]
            # 中文、日文等自由名称继续由多语言模型读取，不能交给英文模型猜写。
            if valid and all(name.isascii() for name in valid):
                indices.append(index);latin.extend(views[index*3+1:index*3+3])
        if latin:
            from engine_pool import pooled_engine
            from gpu_ocr_backend import create_ocr_engine
            backend=os.environ.get('APEX_OCR_BACKEND','cpu')
            reader=pooled_engine(('latin-player-names-v1',backend),lambda:create_ocr_engine(
                backend=backend,model_path=Path(__file__).resolve().parent/'models/numeric_rec_en_v4.onnx',rec_batch_num=1)).text_rec
            reads=reader(latin)[0]
            for offset,index in enumerate(indices):
                value=name_value(reads[offset*2:offset*2+2])
                if value and value['confidence']>=.85:
                    results[index]=review_latin_glyphs(views[index*3+1:index*3+3],reader,self.recognizer,{**value,'reader':'latin_name'})
        # 一两个字符的短名缺少上下文，多语言模型常把 TI 读成 π/T；改由英文名模型读加边距放大的
        # 原图，两种放大倍数须读出同一合法拼写，跨帧共识仍由调用方完成。
        short=[index for index,value in enumerate(results) if value is None and patches[index].size and patches[index].shape[1]<=patches[index].shape[0]*3]
        if short:
            from target_name_reader import model_available,LATIN_MODEL_PATH
            if model_available(latin=True):
                from engine_pool import pooled_engine
                from gpu_ocr_backend import create_ocr_engine
                backend=os.environ.get('APEX_OCR_BACKEND','cpu')
                reader=pooled_engine(('short-player-names-v1',backend),lambda:create_ocr_engine(backend=backend,model_path=LATIN_MODEL_PATH,rec_batch_num=1)).text_rec
                crops=[]
                for index in short:
                    patch=patches[index];background=tuple(int(c) for c in np.median(patch.reshape(-1,3),axis=0))
                    padded=cv2.copyMakeBorder(patch,2,2,2,2,cv2.BORDER_CONSTANT,value=background)
                    crops.extend(cv2.resize(padded,None,fx=factor,fy=factor,interpolation=cv2.INTER_CUBIC) for factor in [2,4])
                reads=reader(crops)[0]
                for offset,index in enumerate(short):
                    pair=reads[offset*2:offset*2+2];names={player_name(text) for text,_ in pair}
                    if len(names)==1 and next(iter(names)) and all(confidence>=.85 for _,confidence in pair):
                        results[index]={'name':next(iter(names)),'confidence':float(min(c for _,c in pair)),'view_agreement':2,'reader':'short_latin_name'}
        from japanese_name_reader import has_kana,JapaneseNameReader
        for index,value in enumerate(results):
            if value and has_kana(value['name']):
                if self.japanese is None:self.japanese=JapaneseNameReader(self.recognizer)
                results[index]=self.japanese(views[index*3+1:index*3+3],value)
        return results
