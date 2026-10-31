"""本人计分栏没出现时，核对右上角「剩余小队数」那一行，确认击杀、助攻、伤害是否都还是 0。

Apex 在本人本局还没造成伤害时，右上角只显示小队数那一行，下面的击杀/助攻/伤害行不出现；
同一局里计分栏短暂消失（打开地图、背包等）时，整块右上角都不显示，小队数那一行也不在。
所以只有「找不到计分图标、小队数那一行可见、计分行没有任何数字」才说明当时三项都是 0，
并且要两帧不同的画面都这样才采用。只读游戏界面的固定文字；计分行只看有没有数字，
不保存读到的其他文字，也不读取玩家名称。
"""
import re
import unicodedata

import cv2

VERSION = 'squads-row-zero-v1'
FIELDS = ('kills', 'assists', 'damage')
# 简繁中文「剩余小队数 / 剩餘小隊數」与英文「SQUADS LEFT」；中间留出 OCR 认错一两个字的余地。
LABEL = re.compile(r'剩.{0,3}[数數]|SQUADS?\s*(?:LEFT|REMAIN)', re.I)
POINTS = re.compile(r'^[+\-−]?\d{1,5}RP$', re.I)
# 小队数行要读得确定；计分行只要像是有数字就不判 0，门槛放低，宁可漏判也不误判。
LABEL_CONFIDENCE = .6
DIGIT_CONFIDENCE = .4


def regions(profile):
    """(识别区, 计分行)，均为 profile 参考坐标，由本 profile 的击杀/伤害框推出。

    小队数行在计分行正上方；计分行下方还可能有性能/网络信息文字，所以计分行的下沿收得较紧。
    """
    kills, damage = profile['kills'], profile['damage']
    row = max(1., float(kills[3] - kills[1]))
    top, bottom = min(kills[1], damage[1]), max(kills[3], damage[3])
    counter = [kills[0] - 4.6 * row, top - .45 * row, damage[2] + 1.8 * row, bottom + .2 * row]
    left, _, width, _ = profile.get('content_box') or [0, 0, *profile['reference_size']]
    search = [counter[0] - .4 * row, 0, left + width, bottom + row]
    return search, counter


def _engine():
    from weapon_reader import new_engine
    from rapidocr_onnxruntime.ch_ppocr_det.utils import DetPreProcess
    engine = new_engine()
    engine.text_det.get_preprocess = lambda max_wh: DetPreProcess(960, 'max', engine.text_det.mean, engine.text_det.std)
    return engine


def read(image, profile, engine=None):
    """右上角状态：zero（小队数行在、计分行无数字）、digits（计分行有数字）或 hidden（小队数行不在）。

    调用方须先确认这一帧找不到计分图标。
    """
    search, counter = regions(profile)
    rw, rh = profile['reference_size']
    h, w = image.shape[:2]
    fx, fy = w / rw, h / rh
    x1, y1 = max(0, round(search[0] * fx)), max(0, round(search[1] * fy))
    x2, y2 = min(w, round(search[2] * fx)), min(h, round(search[3] * fy))
    crop = image[y1:y2, x1:x2]
    if not crop.size:
        return {'state': 'hidden', 'label': None, 'digits': 0}
    # 采样图或低分辨率录像里的文字较小，按 1080p 本人 HUD 的字号放大后再识别。
    hud_y = profile.get('hud_scale', [rh / 1080, rh / 1080])[1]
    scale = min(3., max(1., 1 / max(1e-6, fy * hud_y)))
    if scale > 1.01:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    result, _ = (engine or _engine())(crop, use_cls=False)
    label, digits = None, 0
    for points, text, confidence in result or []:
        confidence = float(confidence)
        if confidence < DIGIT_CONFIDENCE:
            continue
        xs = [p[0] / scale + x1 for p in points]
        ys = [p[1] / scale + y1 for p in points]
        left, middle = min(xs) / fx, (min(ys) + max(ys)) / 2 / fy
        value = unicodedata.normalize('NFKC', text).strip()
        if middle < counter[1]:
            if confidence >= LABEL_CONFIDENCE and LABEL.search(value):
                label = label or value
        elif middle <= counter[3] and counter[0] <= left < counter[2] and re.search(r'\d', value) \
                and not POINTS.match(value.replace(' ', '')):
            digits += 1
    state = 'digits' if digits else 'zero' if label else 'hidden'
    return {'state': state, 'label': label, 'digits': digits}


def zero_frames(frames, profile, *, needed=2, latest=None, engine=None):
    """在给定的画面序列里找「三项计数都是 0」的证据，不足 needed 帧时返回空列表。

    frames 依核对顺序给出 (time, image, provenance)。image 为 None 时：provenance 带 excluded_view
    表示观战等非本人画面，否则只是这一帧没读出来。观战、阵亡等非本人画面里本人不会造成伤害，
    跳过即可；遇到计分图标，或小队数行下面的计分行有数字，就停下，之后的画面不能再证明此前的计数。
    大厅等画面在计分行的位置也可能有数字，但那时没有小队数行，不算计分栏出现。
    latest（秒）用于由近到远核对片尾：最近的本人画面若右上角整块不显示且超出这段容差，
    此后计数可能已经变化，不能再用更早的画面证明片尾是 0。
    返回的证据行三项计数均记为 0，并带 zero_evidence 说明来源。
    """
    from apex_clipper import BASE, counter_offset, inactive_view
    from image_io import read_image
    marker = None
    found, seen, first = [], set(), None
    for time, image, provenance in frames:
        provenance = dict(provenance or {})
        if image is None or inactive_view(image):
            continue
        if first is None:
            first = time
        if marker is None:
            marker = read_image(str(BASE / profile['counter_marker']), 0)
        delta, score = counter_offset(image, profile, marker)
        if delta is not None:
            break
        engine = engine or _engine()
        panel = read(image, profile, engine)
        if panel['state'] == 'digits' and panel['label']:
            break
        if panel['state'] != 'zero':
            if latest is not None and not found and abs(time - first) >= latest:
                break
            continue
        stamp = provenance.get('native_time', time)
        if stamp in seen:
            continue
        seen.add(stamp)
        found.append({**provenance, 'time': time, 'marker_score': float(score), **dict.fromkeys(FIELDS, 0),
                      'zero_evidence': {'method': VERSION, 'label': panel['label']}})
        if len(found) >= needed:
            break
    return found if len(found) >= needed else []
