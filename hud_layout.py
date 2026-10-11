"""按 HUD 锚点适配原始分辨率及拉伸比例；不改变录像或全片采样。"""
from copy import deepcopy
from pathlib import Path
import json

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent
VERSION = 'anchored-hud-v1'


def point(profile, x, y, horizontal='right', vertical='top'):
    width, height = profile['reference_size']
    sx, sy = profile.get('hud_scale', [height / 1080, height / 1080])
    px = x*sx if horizontal == 'left' else width-(2560-x)*sx if horizontal == 'right' else width/2+(x-1280)*sx
    py = y*sy if vertical == 'top' else height-(1080-y)*sy if vertical == 'bottom' else height/2+(y-540)*sy
    return [round(px), round(py)]


def box(profile, values, horizontal='right', vertical='top'):
    return point(profile,*values[:2],horizontal,vertical) + point(profile,*values[2:],horizontal,vertical)


def make_profile(width, height, vertical_scale=1., horizontal_scale=1., base=None):
    original = base or json.loads((BASE/'profile-ultrawide.json').read_text('utf-8'))
    profile = deepcopy(original)
    profile['reference_size'] = [width,height]
    profile['hud_scale'] = [height/1080*horizontal_scale,height/1080*vertical_scale]
    profile['layout_version'] = VERSION
    profile['layout'] = '4:3-stretched' if abs(vertical_scale-.75)<.05 else 'native'
    profile['name'] = f'Auto {width}x{height} / {profile["layout"]}'
    for key in ('damage','kills','counter_marker_search'):
        profile[key] = box(profile, original[key])
    profile['assists'] = box(profile,[2202,94,2228,124])
    profile['participation'] = box(profile,[2260,94,2300,124])
    profile['counter_marker_origin'] = point(profile,*original['counter_marker_origin'])
    for key in ('ammo','weapon','weapon_icon'):
        profile[key] = box(profile,original[key],vertical='bottom')
    for key in ('weapon_name_boxes','weapon_name_metrics'):
        profile[key] = [box(profile,b,vertical='bottom') for b in original[key]]
    for key in ('spectator','downed_marker_search'):
        profile[key] = box(profile,original[key],horizontal='center',vertical='bottom')
    profile['banner'] = box(profile,original['banner'],horizontal='center',vertical='center')
    # Native sidecar crops use the same bottom-right quarter as the existing decoder.
    cx=round(width*.75/2)*2;cy=round(height*5/6/2)*2
    profile['weapon_native_crop'] = [cx,cy,width-cx,height-cy]
    profile['rank_roi'] = box(profile,[2440,0,2560,108],vertical='top')
    profile['account_roi'] = box(profile,[175,958,337,989],horizontal='left',vertical='bottom')
    profile['teammate_rois'] = [box(profile,b,horizontal='left',vertical='bottom') for b in
        [[136,780,292,808],[136,845,292,873]]]
    profile['hero_tactical_roi'] = box(profile,[555,967,653,1035],horizontal='left',vertical='bottom')
    profile['hero_ultimate_roi'] = box(profile,[1243,928,1323,1028],horizontal='center',vertical='bottom')
    return profile


def template_for(profile, template):
    sx,sy=profile.get('hud_scale',[1.,1.])
    if abs(sx-1)<.001 and abs(sy-1)<.001:return template
    return cv2.resize(template,(max(1,round(template.shape[1]*sx)),max(1,round(template.shape[0]*sy))),interpolation=cv2.INTER_CUBIC)


def detect_images(images, width, height, base=None):
    from apex_clipper import counter_offset
    original = base or json.loads((BASE/'profile-ultrawide.json').read_text('utf-8'))
    marker=cv2.imread(str(BASE/original['counter_marker']),cv2.IMREAD_GRAYSCALE)
    candidates=[make_profile(width,height,base=original),make_profile(width,height,.75,base=original)]
    if width/height<1.55:candidates.append(make_profile(width,height,.75,.75,base=original))
    evidence=[]
    for profile in candidates:
        scores=[]
        for image in images:
            try:_,score=counter_offset(image,profile,marker)
            except cv2.error:score=0.
            scores.append(float(score))
        evidence.append((max(scores,default=0.),profile,scores))
    evidence.sort(key=lambda entry:entry[0],reverse=True)
    score,profile,scores=evidence[0]
    if score<.78 or len(evidence)>1 and score-evidence[1][0]<.025:
        # Do not silently select stretched geometry when there was no in-game HUD.
        profile=candidates[0];score=next(entry[0] for entry in evidence if entry[1] is profile)
        profile['layout_status']='unconfirmed'
    else:profile['layout_status']='confirmed'
    profile['layout_score']=round(score,4)
    return profile


def detect_video(source, video, duration, base=None):
    """最多四次直接 seek；只在看不到 HUD 时继续，不遍历视频帧。"""
    import av
    images=[]
    times=list(dict.fromkeys([min(5,duration*.1),min(90,duration*.2),duration*.25,duration*.55]))
    with av.open(str(source)) as container:
        stream=container.streams.video[0];stream.codec_context.thread_count=1
        for second in times:
            container.seek(int(second/stream.time_base),stream=stream,backward=True,any_frame=False)
            frame=next((f for f in container.decode(stream) if float(f.pts*f.time_base)>=second),None)
            if frame is None:continue
            images.append(frame.to_ndarray(format='bgr24'))
            profile=detect_images(images,video['width'],video['height'],base)
            if profile['layout_status']=='confirmed':break
    if not images:raise ValueError('无法读取用于自动适配的录像画面')
    profile['layout_probe_frames']=len(images)
    return profile


def outcome_profile(hud, original):
    if not hud.get('layout_version'):return original
    profile=deepcopy(original);profile['reference_size']=hud['reference_size']
    profile['toast_roi']=box(hud,original['toast_roi'],'center','center')
    profile['context_padding_left']=round(original.get('context_padding_left',100)*hud['hud_scale'][0])
    profile['hud_scale']=hud['hud_scale'];profile['layout_version']=VERSION
    return profile
