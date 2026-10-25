"""按 HUD 锚点适配原始分辨率及拉伸比例；不改变录像或全片采样。"""
from copy import deepcopy
from pathlib import Path
import json

import cv2
from image_io import read_image
import numpy as np

BASE = Path(__file__).resolve().parent
VERSION = 'anchored-hud-v2'
# 标准界面的锚点区域（参考坐标 2560x1080）；与旧版 make_profile 完全一致，已有缓存不受影响。
STANDARD_LAYOUT = {
    'assists': [2202,94,2228,124], 'participation': [2260,94,2300,124],
    'rank_roi': [2440,0,2560,108], 'account_roi': [175,958,337,989],
    'teammate_rois': [[136,780,292,808],[136,845,292,873]],
    'hero_tactical_roi': [555,967,653,1035], 'hero_ultimate_roi': [1243,928,1323,1028],
}
# 游戏「界面配置模式：精简」：HUD 整体约放大 1.25 倍，计分栏改为「击杀/助攻/参与」一体条，
# 各组位置也重排，不能由标准坐标推出。以下坐标在 1280x720（4:3 拉伸）真实录像上实测，
# 以放大后的参考坐标表达，仍按各自屏幕边锚定，可随分辨率与拉伸换算。
COMPACT_SCALE = 1.25
COMPACT_LAYOUT = {
    'counter_marker_origin': [2313,134], 'damage': [2347,134,2387,162],
    'kills': [2047,132,2083,162], 'assists': [2104,130,2134,164], 'participation': [2160,132,2200,162],
    'ammo': [2385,955,2465,1010], 'weapon': [2350,1046,2510,1078], 'weapon_icon': [2215,955,2380,1003],
    'weapon_name_boxes': [[2185,1046,2345,1078],[2350,1046,2510,1078]],
    'weapon_name_metrics': [[2200,1048,2330,1078],[2365,1048,2495,1078]],
    'rank_roi': [2410,10,2530,170], 'account_roi': [133,986,296,1020],
    'teammate_rois': [[124,798,280,828],[124,876,280,906]],
    'hero_tactical_roi': [555,967,653,1035], 'hero_ultimate_roi': [1228,930,1335,1035],
}
# 拉伸录像常见的游戏渲染比例。HUD 排在 16:9 安全区内，比 16:9 窄的画面按宽度缩小。
STRETCH_RENDERS = ((16,9),(16,10),(4,3))
# 候选集合（比例×界面）的版本。旧任务冻结的布局若来自更早的检测，续接时重新检测一次；
# 标准布局几何不变时结果与缓存一致，不会触发重识别。
DETECTOR_VERSION = 'fit-scale-candidates-v1'


def point(profile, x, y, horizontal='right', vertical='top'):
    width, height = profile['reference_size']
    sx, sy = profile.get('hud_scale', [height / 1080, height / 1080])
    px = x*sx if horizontal == 'left' else width-(2560-x)*sx if horizontal == 'right' else width/2+(x-1280)*sx
    py = y*sy if vertical == 'top' else height-(1080-y)*sy if vertical == 'bottom' else height/2+(y-540)*sy
    return [round(px), round(py)]


def box(profile, values, horizontal='right', vertical='top'):
    return point(profile,*values[:2],horizontal,vertical) + point(profile,*values[2:],horizontal,vertical)


def make_profile(width, height, vertical_scale=1., horizontal_scale=1., base=None, ui='standard', layout=None):
    original = base or json.loads((BASE/'profile-ultrawide.json').read_text('utf-8'))
    compact = ui == 'compact'
    # 精简界面的坐标以放大后的参考单位表示；标准界面保持原有键和数值不变。
    source = {**original, **STANDARD_LAYOUT, **(COMPACT_LAYOUT if compact else {})}
    k = COMPACT_SCALE if compact else 1.
    profile = deepcopy(original)
    profile['reference_size'] = [width,height]
    profile['hud_scale'] = [height/1080*horizontal_scale*k,height/1080*vertical_scale*k]
    profile['layout_version'] = VERSION
    profile['layout'] = layout or ('4:3-stretched' if abs(vertical_scale-.75)<.05 else 'native')
    if compact:
        profile['ui_layout'] = 'compact'; profile['layout'] += '/compact'
    profile['name'] = f'Auto {width}x{height} / {profile["layout"]}'
    for key in ('damage','kills'):
        profile[key] = box(profile, source[key])
    # Counter panels can move vertically independently of the stretched HUD.
    # Locate the icon first, then counter_offset translates the numeric boxes.
    search=original['counter_marker_search']
    profile['counter_marker_search']=box(profile,[search[0]-40,max(0,search[1]-64),search[2]+60,search[3]+80])
    profile['assists'] = box(profile,source['assists'])
    profile['participation'] = box(profile,source['participation'])
    profile['counter_marker_origin'] = point(profile,*source['counter_marker_origin'])
    for key in ('ammo','weapon','weapon_icon'):
        profile[key] = box(profile,source[key],vertical='bottom')
    for key in ('weapon_name_boxes','weapon_name_metrics'):
        profile[key] = [box(profile,b,vertical='bottom') for b in source[key]]
    for key in ('spectator','downed_marker_search'):
        profile[key] = box(profile,original[key],horizontal='center',vertical='bottom')
    profile['banner'] = box(profile,original['banner'],horizontal='center',vertical='center')
    # Native sidecar crops use the same bottom-right quarter as the existing decoder.
    cx=round(width*.75/2)*2;cy=round(height*5/6/2)*2
    profile['weapon_native_crop'] = [cx,cy,width-cx,height-cy]
    profile['rank_roi'] = box(profile,source['rank_roi'],vertical='top')
    profile['account_roi'] = box(profile,source['account_roi'],horizontal='left',vertical='bottom')
    profile['teammate_rois'] = [box(profile,b,horizontal='left',vertical='bottom') for b in source['teammate_rois']]
    profile['hero_tactical_roi'] = box(profile,source['hero_tactical_roi'],horizontal='left',vertical='bottom')
    profile['hero_ultimate_roi'] = box(profile,source['hero_ultimate_roi'],horizontal='center',vertical='bottom')
    return profile


def layout_candidates(width, height, base=None):
    """列出录像可能的 HUD 几何：游戏渲染比例（原生/拉伸）× 界面模式（标准/精简）。"""
    candidates=[];seen=set();aspect=width/height
    def add(vertical,horizontal,ui,layout=None):
        profile=make_profile(width,height,vertical,horizontal,base=base,ui=ui,layout=layout)
        key=(ui,round(profile['hud_scale'][0],3),round(profile['hud_scale'][1],3))
        if key not in seen:seen.add(key);candidates.append(profile)
    for ui in ('standard','compact'):
        # 旧版候选顺序保持在前，平分时仍优先原有结果。
        add(1.,1.,ui);add(.75,1.,ui)
        if aspect<1.55:add(.75,.75,ui)
        for render in [None,*STRETCH_RENDERS]:
            ratio=aspect if render is None else render[0]/render[1]
            if ratio>aspect+.01:continue  # 更宽的画面放进窄录像会留黑边，不是拉伸
            unit=min(1.,ratio/(16/9))
            label='native' if render is None or abs(ratio-aspect)<.01 else f'{render[0]}:{render[1]}-stretched'
            add(unit,unit*aspect/ratio,ui,label)
    return candidates


def template_for(profile, template):
    sx,sy=profile.get('hud_scale',[1.,1.])
    if abs(sx-1)<.001 and abs(sy-1)<.001:return template
    return cv2.resize(template,(max(1,round(template.shape[1]*sx)),max(1,round(template.shape[0]*sy))),interpolation=cv2.INTER_CUBIC)


def detect_images(images, width, height, base=None):
    from apex_clipper import counter_offset
    original = base or json.loads((BASE/'profile-ultrawide.json').read_text('utf-8'))
    marker=read_image(str(BASE/original['counter_marker']),cv2.IMREAD_GRAYSCALE)
    candidates=layout_candidates(width,height,base=original)
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
    """最多八次直接 seek；确认 HUD 后即停止，不遍历视频帧。"""
    import av
    images=[]
    times=list(dict.fromkeys([min(5,duration*.1),min(90,duration*.2),duration*.25,duration*.55]))
    if duration>=600:times+=list(dict.fromkeys(duration*part for part in [.4,.7,.85,.95]))
    with av.open(str(source)) as container:
        stream=container.streams.video[0];stream.codec_context.thread_count=1
        for second in times:
            from app_cancel import check_cancel
            check_cancel()
            container.seek(int(second/stream.time_base),stream=stream,backward=True,any_frame=False)
            frame=next((f for f in container.decode(stream) if float(f.pts*f.time_base)>=second),None)
            if frame is None:continue
            images.append(frame.to_ndarray(format='bgr24'))
            profile=detect_images(images,video['width'],video['height'],base)
            if profile['layout_status']=='confirmed':break
    if not images:raise ValueError('无法读取用于自动适配的录像画面')
    profile['layout_probe_frames']=len(images)
    return profile


def ensure_activity_is_readable(profile, events, plan):
    """Unavailable HUD counters must not certify an active recording as empty."""
    if profile.get('layout_status')=='unconfirmed' and not events and plan.get('seed_count',0)>0:
        raise ValueError('未能确认录像的 HUD 布局，无法可靠定位交战；本次未导出，请保留原录像并重新适配。')


def needs_layout_retry(record, profile):
    return bool(record and not record.get('outputs') and profile and
                profile.get('layout_status')=='unconfirmed' and profile.get('layout_version')!=VERSION)


def outcome_profile(hud, original):
    if not hud.get('layout_version'):return original
    profile=deepcopy(original);profile['reference_size']=hud['reference_size']
    profile['toast_roi']=box(hud,original['toast_roi'],'center','center')
    profile['context_padding_left']=round(original.get('context_padding_left',100)*hud['hud_scale'][0])
    profile['hud_scale']=hud['hud_scale'];profile['layout_version']=VERSION
    if hud.get('ui_layout'):profile['ui_layout']=hud['ui_layout']
    return profile
