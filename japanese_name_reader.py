"""日文姓名按实际字形复核大小假名；不使用词语或昵称答案表。"""
from functools import lru_cache
from pathlib import Path
import os
import re
import unicodedata

import cv2
import numpy as np

from player_names import player_name
from target_name_reader import ctc_tokens,ensure_model_asset,_digest

VERSION='player-names-v12'
MODEL_PATH=Path(__file__).resolve().parent/'models/name_rec_japanese_v4.onnx'
MODEL_SHA='e1075a67dba758ecfc7ebc78a10ae61c95ac8fb66a9c86fab5541e33f085cb7a'
MODEL_URL='https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv4/rec/japan_PP-OCRv4_rec_mobile.onnx'


def ensure_model():return ensure_model_asset(MODEL_PATH,MODEL_SHA,MODEL_URL)


@lru_cache(maxsize=1)
def model_available():return MODEL_PATH.is_file() and _digest(MODEL_PATH)==MODEL_SHA


def has_kana(value):return any('\u3041'<=char<='\u3096' or '\u30a1'<=char<='\u30fa' for char in value)


@lru_cache(maxsize=1)
def small_kana_pairs():
    pairs={}
    for code in range(0x3041,0x3100):
        char=chr(code);name=unicodedata.name(char,'')
        if ' LETTER SMALL ' in name:
            try:pairs[char]=unicodedata.lookup(name.replace(' LETTER SMALL ',' LETTER '))
            except KeyError:pass
    return pairs


def kana_family(value):return ''.join(small_kana_pairs().get(char,char) for char in value)


def glyph_metrics(image,tokens):
    if any(len(token[0])!=1 for token in tokens):return []
    edges=[0]+[round((left[2]+right[1])/2) for left,right in zip(tokens,tokens[1:])]+[image.shape[1]]
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    mask=(hsv[:,:,1]<100)&(hsv[:,:,2]>max(100,float(np.percentile(hsv[:,:,2],95))*.67))
    metrics=[]
    for index,token in enumerate(tokens):
        left=max(0,edges[index]);right=min(image.shape[1],edges[index+1]);ys,xs=np.where(mask[:,left:right])
        if not xs.size:metrics.append(None);continue
        metrics.append({'character':token[0],'box':[int(xs.min()+left),int(ys.min()),int(xs.max()+left+1),int(ys.max()+1)]})
    return metrics


def size_evidence(metrics,index):
    """只比较同一行的字号与基线，不按日文词义纠正字符。"""
    if index>=len(metrics) or metrics[index] is None:return None
    references=[item['box'] for i,item in enumerate(metrics) if i!=index and item and item['character'] not in small_kana_pairs() and ('\u3041'<=item['character']<='\u30fa' or '\u3400'<=item['character']<='\u9fff')]
    if len(references)<2:return None
    height=float(np.percentile([box[3]-box[1] for box in references],75))
    top=float(np.percentile([box[1] for box in references],25));baseline=float(np.median([box[3] for box in references]))
    if height<=0:return None
    box=metrics[index]['box'];ratio=(box[3]-box[1])/height
    aligned=abs(box[3]-baseline)<=height*.15
    observed='small' if aligned and ratio<=.86 and box[1]-top>=height*.10 else 'large' if aligned and ratio>=.93 and abs(box[1]-top)<=height*.15 else 'ambiguous'
    return {'index':index,'box':box,'reference_height':height,'reference_top':top,'baseline':baseline,'height_ratio':ratio,'observed_size':observed,'method':'same_line_kana_size'}


class JapaneseNameReader:
    def __init__(self,primary):self.primary=primary;self.reader=None

    def __call__(self,views,value):
        if not has_kana(value['name']) or not all(hasattr(self.primary,key) for key in ['session','resize_norm_img','rec_image_shape','postprocess_op']):return value
        if not model_available():raise ValueError('缺少或损坏日文姓名复核模型，请修复安装。')
        if self.reader is None:
            from gpu_ocr_backend import create_ocr_engine
            self.reader=create_ocr_engine(backend=os.environ.get('APEX_OCR_BACKEND','cpu'),model_path=MODEL_PATH,rec_batch_num=1).text_rec
        color,gray=views;tokens=ctc_tokens(color,self.primary);raw=''.join(token[0] for token in tokens)
        if any(len(token[0])!=1 for token in tokens):return value
        tag=re.match(r'^\[?[^\[\]\s]{1,6}\]\s*',raw)
        if tag:
            start=tag.end()
            if start>=len(tokens):return value
            left=max(0,round((tokens[start-1][2]+tokens[start][1])/2)-3)
            color,gray=color[:,left:],gray[:,left:]
        reads=[{'name':player_name(text),'confidence':float(confidence)} for text,confidence in self.reader([color,gray])[0]]
        families={kana_family(read['name']) for read in reads if read['name']}
        if len(families)!=1 or any(not read['name'] or read['confidence']<.85 for read in reads) or max(read['confidence'] for read in reads)<.90:
            return {**value,'japanese_review_attempts':reads}
        family=next(iter(families));candidate=max(reads,key=lambda read:read['confidence'])['name']
        primary_reads=[{'name':player_name(text),'confidence':float(confidence)} for text,confidence in self.primary([color,gray])[0]]
        same_family=family==kana_family(value['name'])
        if not same_family and not (all(read['name']==candidate and read['confidence']>=.90 for read in reads) and all(read['name']==candidate and read['confidence']>=.85 for read in primary_reads)):return {**value,'japanese_review_attempts':reads}
        tokens=ctc_tokens(color,self.reader)
        if kana_family(''.join(token[0] for token in tokens))!=family:return {**value,'japanese_review_attempts':reads}
        metrics=glyph_metrics(color,tokens);proof=[];characters=list(candidate)
        observed_reads=[*reads,*([value] if same_family else []),*[read for read in primary_reads if read['confidence']>=.85 and kana_family(read['name'])==family]]
        observed_names=[read['name'] for read in observed_reads]
        if any(len(name)!=len(characters) for name in observed_names):return {**value,'japanese_review_attempts':reads}
        # 尺寸仍有争议的其他假名不能充当“大字”的字号标尺。
        for index,item in enumerate(metrics):
            small=[name[index] for name in observed_names if name[index] in small_kana_pairs()]
            if item and small:item['character']=small[0]
        supports=[]
        for index,char in enumerate(characters):
            variants={name[index] for name in observed_names}
            # 只在模型实际读到大小假名变体时核验；不能因“い”等字天然较矮就改成小假名。
            small=[variant for variant in variants if variant in small_kana_pairs()]
            if not small:continue
            observed=size_evidence(metrics,index)
            if not observed or observed['observed_size']=='ambiguous':
                return {**value,'japanese_review_attempts':reads,'japanese_size_attempt':observed,'japanese_review_pending':True}
            desired=small[0] if observed['observed_size']=='small' else small_kana_pairs()[small[0]]
            if desired not in variants:
                return {**value,'japanese_review_attempts':reads,'japanese_size_attempt':observed,'japanese_review_pending':True}
            characters[index]=desired;proof.append(observed);supports.append(max(read['confidence'] for read in observed_reads if read['name'][index]==desired))
        candidate=''.join(characters)
        evidence={'model':MODEL_SHA,'views':reads,'primary_body_views':primary_reads,'glyphs':proof}
        return {**value,'name':candidate,'raw_name':value.get('raw_name',value['name']),'confidence':min(value['confidence'],*(read['confidence'] for read in reads),*supports),'reader':'japanese_name_review','japanese_evidence':evidence}
