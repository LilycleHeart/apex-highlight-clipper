"""Classify a visibly rendered trailing square without guessing its Unicode origin.

This module returns one-frame evidence. The caller must bind it to the source,
native PTS and name crop, and require independent native frames for consensus.
It never creates a recognizer or changes the BGR pixels passed to one.
"""
import copy
import hashlib
import math
import re
import statistics

import cv2
import numpy as np

VERSION='rendered-tail-square-v1'
_BODY=re.compile(r'[A-Za-z0-9]+(?:[ _.-][A-Za-z0-9]+)*')


def _signal(image):
    b,g,r=cv2.split(image.astype(np.int16))
    red=np.maximum(0,r-np.maximum(g,b)).astype(np.float32)
    red=np.maximum(0,red-cv2.morphologyEx(red,cv2.MORPH_OPEN,np.ones((7,7),np.uint8)))
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY).astype(np.float32)
    neutral=np.maximum(0,gray-cv2.morphologyEx(gray,cv2.MORPH_OPEN,np.ones((7,7),np.uint8)))
    neutral=np.where(cv2.cvtColor(image,cv2.COLOR_BGR2HSV)[:,:,1]<=70,neutral,0)
    signal=np.maximum(red,neutral).astype(np.float32)
    return signal,max(20.,float(signal.max())*.25)


def _valid_image(image):
    return isinstance(image,np.ndarray) and image.dtype==np.uint8 and image.ndim==3 and image.shape[2]==3 and 8<=image.shape[0]<=128 and 20<=image.shape[1]<=1024


def _shape(mask,box):
    x,y,w,h=map(int,box)
    if not 6<=w<=64 or not 6<=h<=64 or not .85<=w/h<=1.15:return None
    glyph=mask[y:y+h,x:x+w]
    contours,hierarchy=cv2.findContours(glyph*255,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:return None
    exterior=[value for index,value in enumerate(contours) if hierarchy[0][index][3]<0]
    if len(exterior)!=1 or sum(row[3]>=0 for row in hierarchy[0])!=1:return None
    polygon=cv2.approxPolyDP(exterior[0],max(.75,min(w,h)*.08),True)
    if len(polygon)!=4 or not cv2.isContourConvex(polygon):return None
    edges=[float(glyph[0].mean()),float(glyph[-1].mean()),float(glyph[:,0].mean()),float(glyph[:,-1].mean())]
    score=min(edges)
    if score<.82:return None
    corners=[float(part.mean()) for part in [glyph[:2,:2],glyph[:2,-2:],glyph[-2:,:2],glyph[-2:,-2:]]]
    if min(corners)<.5:return None
    middle=glyph[h//3:max(h//3+1,h*2//3),w//3:max(w//3+1,w*2//3)]
    if float(middle.mean())>.05:return None
    return {'box':[x,y,w,h],'score':score,'score_method':'minimum_four_edge_coverage','edge_coverage':edges,'corner_coverage':corners,'outer_polygon':polygon.reshape(-1,2).tolist(),'holes':1,'center_foreground_fraction':float(middle.mean())}


def square_candidates(image):
    """Cheap pixel-only candidates, in name-crop coordinates as [x,y,w,h].

    This is deliberately not a name or language decision. A CJK mouth or a UI
    rectangle can be a candidate; read_rendered_tail must reject that context.
    """
    if not _valid_image(image):return []
    signal,threshold=_signal(image)
    if float(signal.max())<20:return []
    mask=(signal>=threshold).astype(np.uint8)
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    result=[]
    for x,y,w,h,area in stats[1:]:
        if area<8:continue
        shape=_shape(mask,[x,y,w,h])
        if shape is not None:result.append({**shape,'signal_threshold':threshold})
    return result


def _number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _tokens(tokens,width):
    if not isinstance(tokens,list) or not tokens:return False
    previous=-1.
    for token in tokens:
        if not isinstance(token,dict) or not isinstance(token.get('character'),str) or len(token['character'])!=1:return False
        left,right,confidence=token.get('left'),token.get('right'),token.get('confidence')
        if not all(_number(value) for value in [left,right,confidence]) or not 0<=left<right<=width or left<previous or not 0<=confidence<=1:return False
        previous=right
    return True


def _body(tokens,candidate,image,stats):
    actual=copy.deepcopy(tokens)
    while actual and actual[-1]['character'].isspace():actual.pop()
    if not actual:return None
    x,y,w,h=candidate['box'];end=x+w
    last=actual[-1];center=(last['left']+last['right'])/2;mapping=None
    if x-1<=center<=end+1:
        mapping={'actual_emitted_character':last['character'],'actual_token':copy.deepcopy(last),'mapped_text':''.join(token['character'] for token in tokens),'decision':'emission_center_inside_proved_square'}
        actual.pop()
        if any((token['left']+token['right'])/2>=x-1 for token in actual):return None
    elif last['right']>x:return None
    while actual and actual[-1]['character'].isspace():actual.pop()
    text=''.join(token['character'] for token in actual)
    if not _BODY.fullmatch(text or '') or not actual:return None
    values=[token['confidence'] for token in actual if not token['character'].isspace()]
    if min(values)<.8 or statistics.mean(values)<.9:return None
    first,right=actual[0]['left'],actual[-1]['right']
    if not 0<=x-right<=h*1.5 or first>image.shape[0]*.5:return None
    bodies=[row for row in stats[1:] if row[0]+row[2]>first and row[0]<right and row[3]>=image.shape[0]*.25 and row[4]>=8]
    if len(bodies)<2:return None
    letter_height=statistics.median(float(row[3]) for row in bodies)
    baseline=statistics.median(float(row[1]+row[3]) for row in bodies)
    # A full-height CJK 口 is not a small trailing placeholder. The body itself
    # must independently be Latin; no CJK character is translated or removed.
    if not .35*letter_height<=h<.85*letter_height or abs(y+h-baseline)>max(2.,letter_height*.12):return None
    if image.shape[1]-end>letter_height*.75:return None
    if any(row[0]>=end and row[3]>=max(6,h*.5) and row[4]>=8 for row in stats[1:]):return None
    return {'name':text,'body_tokens':actual,'minimum_character_confidence':min(values),'mean_character_confidence':statistics.mean(values),'letter_height':letter_height,'baseline':baseline,'square_mapping':mapping}


def read_rendered_tail(image,english,independent,*,ctc):
    """Return actual Latin body + visible □, with one-frame shape/CTC evidence.

    The models are supplied by the caller. Zero candidates make no ctc calls.
    Every model sees the original BGR image once; no dictionary, old name or
    expected body is accepted as an argument. O/o/0 or other final emissions
    can be shape-classified only at the actual square pixels. The preceding
    real round O remains part of the independently agreed Latin body.
    """
    candidates=square_candidates(image)
    if not candidates or english is None or independent is None or not callable(ctc):return None
    observed=[ctc(image,model) for model in [english,independent]]
    if any(not _tokens(tokens,image.shape[1]) for tokens in observed):return None
    signal,threshold=_signal(image)
    _,_,stats,_=cv2.connectedComponentsWithStats((signal>=threshold).astype(np.uint8))
    accepted=[]
    for candidate in candidates:
        bodies=[_body(tokens,candidate,image,stats) for tokens in observed]
        if any(body is None for body in bodies) or bodies[0]['name']!=bodies[1]['name'] or not any(body['square_mapping'] for body in bodies):continue
        views=[{'actual_text':''.join(token['character'] for token in tokens),'actual_ctc_tokens':copy.deepcopy(tokens),**copy.deepcopy(body)} for tokens,body in zip(observed,bodies)]
        shape={'version':VERSION,'method':'native_trailing_rendered_square','position':'trailing','rendered_symbol':'rendered-square','original_unicode':'unknown','coordinate_space':'name_crop','crop_sha256':hashlib.sha256(image.tobytes()).hexdigest(),'crop_size':[image.shape[1],image.shape[0]],**copy.deepcopy(candidate),'body_geometry':[{'letter_height':body['letter_height'],'baseline':body['baseline']} for body in bodies],'body_ctc_views':copy.deepcopy(views),'raw_variants':list(dict.fromkeys(view['actual_text'] for view in views)),'requires_distinct_native_pts':2}
        accepted.append({'name':bodies[0]['name']+'□','confidence':min(body['minimum_character_confidence'] for body in bodies),'shape_evidence':shape,'views':views})
    return accepted[0] if len(accepted)==1 else None
