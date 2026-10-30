"""战果附近的持枪/射击证据；不将时间邻近关系写成击杀武器归因。"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path


VERSION = 'event-weapon-context-v2'
BASE = Path(__file__).resolve().parent
KINDS = {'knock', 'elimination', 'assist'}


def recipe(profile=None):
    digest = hashlib.sha256(VERSION.encode())
    for name in ['event_weapon_reader.py', 'weapon_reader.py', 'numeric_reader.py',
                 'stat_counter_fallback.py', 'outcome_reader.py', 'weapon-catalog.json']:
        digest.update((BASE / name).read_bytes())
    relevant = {key: (profile or {}).get(key) for key in [
        'reference_size', 'layout_status', 'layout_version', 'weapon_name_boxes',
        'weapon_name_metrics', 'weapon_icon', 'ammo']}
    digest.update(json.dumps(relevant, sort_keys=True).encode())
    return digest.hexdigest()


def source_identity(source):
    from apex_clipper import fingerprint
    value = fingerprint(Path(source))
    return {'path': value['path'], 'size': value['size'],
            'mtime_ms': value['mtime_ns'] // 1_000_000}


def _event_location(event):
    return {key: event.get(key) for key in ['kind', 'action', 'time']}


def weapon_context_current(event, identity, profile, *, signature=None):
    value = event.get('weapon_context') or {}
    second = event.get('time')
    if (value.get('status') == 'unknown' and value.get('reason') == 'unconfirmed_or_unsupported_event'
            and event.get('kind') in KINDS and event.get('ownership') == 'self'
            and event.get('confirmed') is not False and isinstance(second, (int, float))
            and not isinstance(second, bool) and math.isfinite(second)):
        # 先前没有读取画面的原因已消失；不能把“当时未确认”当作武器复核结论。
        return False
    return (value.get('version') == VERSION and value.get('recipe') == (recipe(profile) if signature is None else signature)
            and value.get('source') == identity
            and value.get('event') == _event_location(event)
            and value.get('status') in {'observed', 'unknown'})


# 枪名封闭词表分类（WeaponTextReader.constrained）的接受分数是 0.75；它本就要求不同画面再确认，
# 这里仍要求同一画面两个视图一致、且双帧同槽同枪，不能因门槛高于分类器输出而把它们全部丢弃。
NAME_CONFIDENCE = .75


def _view_supports(text, confidence, weapon):
    """同一画面另一个视图是否支持已读出的枪名。

    细笔画的二字枪名在二值化视图里常只剩首字（「獵獸」→「獵」），完整词表匹配会失败；
    单个非 ASCII 首字与已确认枪名的该名称首字一致、且置信度不低，仍算该视图的支持。
    """
    from weapon_reader import resolve_weapon_text, normalized, load_catalog
    if not weapon:
        return False
    if (resolve_weapon_text(text, confidence) or {}).get('id') == weapon['id']:
        return True
    # 支持视图只用来佐证主视图已确认的同一枪名，不单独产生结论：
    # 逐字读到与该枪别名完全相同的文字，或只剩二/三字中文名的首字，均算支持（置信度不低于 0.6）。
    clean = normalized(text)
    if not clean or confidence < .6:
        return False
    catalog = load_catalog()
    entry = next((w for w in catalog['weapons'] + catalog.get('supplemental_weapons', []) if w['id'] == weapon['id']), None)
    aliases = {normalized(alias) for alias in (entry or {}).get('aliases', [])}
    # 名称框左边缘的底板描边常被读成首个多余字符（如「l獵獸」「』獵默」）；只去掉一个非汉字前缀后再比对。
    stripped = clean[1:] if len(clean) >= 3 and clean[0].isascii() else clean
    if clean in aliases or stripped in aliases:
        return True
    clean = stripped
    if len(clean) != 1 or clean.isascii():
        return False
    names = {name for name in aliases if 2 <= len(name) <= 3 and not name.isascii()}
    return any(name.startswith(clean) for name in names)


def _usable(row):
    weapon = row.get('weapon')
    return (not row.get('excluded_view') and weapon and row.get('slot') in (0, 1)
            and row.get('confidence', 0) >= NAME_CONFIDENCE and row.get('name_view_agreement', 0) >= 2)


def _same_weapon(a, b):
    if not _usable(a) or not _usable(b):
        return False
    return (a['slot'] == b['slot'] and a['weapon']['id'] == b['weapon']['id']
            and a['weapon'].get('variant') == b['weapon'].get('variant'))


def icon_mask(frame, profile):
    """武器图标白色前景掩膜：开枪闪光与半透明背景只改变边缘纹理，不改变图标本身的亮色形状。

    真实录像实测：同一把枪相邻帧掩膜相似度 0.92–0.99（边缘签名会掉到 0.76），不同枪约 0.49。
    """
    import base64
    import cv2
    import numpy as np
    from apex_clipper import crop
    image = cv2.resize(crop(frame, profile['weapon_icon'], profile['reference_size']), (96, 28))
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] < 80) & (hsv[:, :, 2] > 170)) | ((hsv[:, :, 1] >= 80) & (hsv[:, :, 2] > 200))
    return base64.b64encode(np.packbits(mask).tobytes()).decode('ascii')


def _icon_similarity(a, b):
    from apex_clipper import icon_similarity
    if not a.get('weapon_icon') or not b.get('weapon_icon'):
        return 0.
    edge = float(icon_similarity(a['weapon_icon'], b['weapon_icon']))
    if a.get('weapon_icon_mask') and b.get('weapon_icon_mask'):
        # 掩膜同形门槛更严（0.88），边缘签名照旧 0.80；任一满足即同一图标。
        mask = float(icon_similarity(a['weapon_icon_mask'], b['weapon_icon_mask']))
        if mask >= .88:
            return max(edge, .80)
    return edge


def context_from_observations(event, observations):
    """只关联双帧可核对的当前槽；事件本身的 weapon 字段保持原样。"""
    second = event['time']
    rows = sorted({row['actual_pts']: row for row in observations
                   if second - 1.5 <= row['actual_pts'] <= second + .25}.values(),
                  key=lambda row: row['actual_pts'])
    base = {'status': 'unknown', 'scope': 'unknown', 'label': '相关武器未确认',
            'weapon': None, 'kill_attribution': False, 'evidence': rows}
    if any(row.get('excluded_view') for row in rows):
        return {**base, 'reason': 'view_change_or_inactive'}
    shots = []
    for before, after in zip(rows, rows[1:]):
        interval = after['actual_pts'] - before['actual_pts']
        # 提示时刻解码到的第一张帧允许最多40毫秒PTS舍入；不取提示后的新射击。
        if after['actual_pts'] > second + .04 or not 0 < interval <= .75:
            continue
        if not _same_weapon(before, after):
            continue
        similarity = _icon_similarity(before, after)
        left, right = before.get('ammo') or {}, after.get('ammo') or {}
        a, b = left.get('value'), right.get('value')
        if (not isinstance(a, int) or isinstance(a, bool) or not isinstance(b, int)
                or isinstance(b, bool) or min(left.get('confidence', 0), right.get('confidence', 0)) < .88):
            continue
        # 装填/换枪造成的0、弹数增加和不连续跳变不能算开枪。
        if not (0 < b < a <= 1000 and a - b <= 50 and similarity >= .80):
            continue
        shots.append({'weapon': after['weapon'], 'before_pts': before['actual_pts'],
                      'after_pts': after['actual_pts'], 'slot': after['slot'],
                      'ammo_before': a, 'ammo_after': b, 'ammo_drop': a - b,
                      'icon_similarity': round(similarity, 4)})
    identities = {(shot['weapon']['id'], shot['weapon'].get('variant')) for shot in shots}
    if len(identities) > 1:
        return {**base, 'reason': 'multiple_firing_weapons', 'shots': shots}
    if shots:
        weapon = shots[-1]['weapon']
        return {**base, 'status': 'observed', 'scope': 'nearby_firing', 'weapon': weapon,
                'label': '战果前射击：' + weapon['name'], 'shots': shots,
                'reason': 'same_slot_name_icon_and_ammo_decrease'}
    at_event = [row for row in rows if second - .04 <= row['actual_pts'] <= second + .25]
    if len(at_event) >= 2 and all(_same_weapon(at_event[0], row) for row in at_event[1:]):
        if all(_icon_similarity(at_event[0], row) >= .80 for row in at_event[1:]):
            weapon = at_event[0]['weapon']
            return {**base, 'status': 'observed', 'scope': 'held_at_event', 'weapon': weapon,
                    'label': '当时持枪：' + weapon['name'], 'reason': 'two_frame_active_hud_slot'}
    # 事件时刻的两帧有一帧被换枪动画、遮挡或误读打断时，再看事件前 1.5 秒内的可用帧：
    # 至少两帧同槽同枪、图标一致，中间没有切到另一把枪或离开本人视角，才记为「战果前持枪」。
    usable = [row for row in rows if _usable(row) and row['actual_pts'] <= second + .25]
    if len(usable) >= 2:
        last = usable[-1]
        same = [row for row in usable if _same_weapon(last, row) and _icon_similarity(last, row) >= .80]
        others = [row for row in usable if not _same_weapon(last, row)]
        window = [row for row in rows if same[0]['actual_pts'] <= row['actual_pts'] <= second + .25] if len(same) >= 2 else []
        if len(same) >= 2 and not others and not any(row.get('excluded_view') for row in window):
            weapon = last['weapon']
            return {**base, 'status': 'observed', 'scope': 'held_before_event', 'weapon': weapon,
                    'label': '战果前持枪：' + weapon['name'], 'reason': 'two_frame_active_hud_slot_before_event'}
    consensus = _single_view_consensus(rows, second)
    if consensus:
        weapon = consensus['weapon']
        return {**base, 'status': 'observed', 'scope': 'held_before_event', 'weapon': weapon,
                'label': '战果前持枪：' + weapon['name'], 'reason': 'three_frame_single_view_consensus'}
    return {**base, 'reason': 'insufficient_or_conflicting_hud_evidence'}


EXTENDED_BEFORE = 6.
EXTENDED_AFTER = 3.


def _read(row):
    """枪名至少一个视图读对、当前槽明确的帧（未必双视图一致）。"""
    return (not row.get('excluded_view') and row.get('weapon') and row.get('slot') in (0, 1)
            and row.get('confidence', 0) >= NAME_CONFIDENCE and row.get('name_view_agreement', 0) >= 1)


def context_near_event(event, observations):
    """事件前后几帧都落在处决/开箱/换枪/模糊时，向前 6 秒、向后 3 秒继续找本人武器栏。

    从事件时刻向两侧取最近的可读帧组成一串，遇到另一把枪即停止；这一串须同槽同枪、图标同形，
    且事件前后各至少一帧，或事件前至少两帧；总计至少两帧双视图一致或三帧单视图一致。
    这只说明战果前后手里的枪，不归因击杀。
    """
    second = event['time']
    rows = sorted({row['actual_pts']: row for row in observations
                   if second - EXTENDED_BEFORE <= row['actual_pts'] <= second + EXTENDED_AFTER}.values(),
                  key=lambda row: row['actual_pts'])
    base = {'status': 'unknown', 'scope': 'unknown', 'label': '相关武器未确认',
            'weapon': None, 'kill_attribution': False, 'evidence': rows}
    reads = [row for row in rows if _read(row)]
    before = [row for row in reads if row['actual_pts'] <= second + .25][::-1]
    after = [row for row in reads if row['actual_pts'] > second + .25]
    anchor = (before or after or [None])[0]
    if anchor is None:
        return {**base, 'reason': 'insufficient_or_conflicting_hud_evidence'}

    def same(row):
        return (row['slot'] == anchor['slot'] and row['weapon']['id'] == anchor['weapon']['id']
                and row['weapon'].get('variant') == anchor['weapon'].get('variant')
                and _icon_similarity(anchor, row) >= .80)

    chain = []
    for side in (before, after):
        for row in side:
            if not same(row):
                break
            chain.append(row)
    chain_before = [row for row in chain if row['actual_pts'] <= second + .25]
    chain_after = [row for row in chain if row['actual_pts'] > second + .25]
    strong = sum(1 for row in chain if row.get('name_view_agreement', 0) >= 2)
    enough = strong >= 2 or len(chain) >= 3
    straddles = bool(chain_before) and (bool(chain_after) or len(chain_before) >= 2)
    if not chain or not enough or not straddles:
        return {**base, 'reason': 'insufficient_or_conflicting_hud_evidence'}
    # 这一串内不能有本人视角中断（观战/倒地），否则无法确定期间没有换枪。
    first, last = min(row['actual_pts'] for row in chain), max(row['actual_pts'] for row in chain)
    if any(row.get('excluded_view') for row in rows if first <= row['actual_pts'] <= last):
        return {**base, 'reason': 'view_change_or_inactive'}
    weapon = anchor['weapon']
    return {**base, 'status': 'observed', 'scope': 'held_near_event', 'weapon': weapon,
            'label': '战果前后持枪：' + weapon['name'], 'reason': 'same_slot_chain_near_event'}


def _single_view_consensus(rows, second):
    """每帧只有一个视图读对枪名时，用不同画面互相确认：至少三帧同槽同枪、图标同形，期间无其他枪名、无观战。

    枪名封闭词表分类本就要求「不同画面确认」；三帧独立画面一致比单帧双视图更严格，不会凭单帧产生枪名。
    """
    window = [row for row in rows if row['actual_pts'] <= second + .25]
    if any(row.get('excluded_view') for row in window):
        return None
    read = [row for row in window if row.get('weapon') and row.get('slot') in (0, 1)
            and row.get('confidence', 0) >= NAME_CONFIDENCE and row.get('name_view_agreement', 0) >= 1]
    if len(read) < 3:
        return None
    last = read[-1]
    if any(row['slot'] != last['slot'] or row['weapon']['id'] != last['weapon']['id']
           or row['weapon'].get('variant') != last['weapon'].get('variant') for row in read):
        return None
    if any(_icon_similarity(last, row) < .80 for row in read):
        return None
    return last


def _background_slot(patches, margin=30):
    """文字亮度相近时，按名称底板亮度判定当前槽：真实 HUD 当前槽为点亮的弹药色底板，另一槽为暗底。"""
    import cv2
    import numpy as np
    values = []
    for patch in patches:
        if patch is None or not patch.size:
            return None, []
        values.append(float(np.median(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[:, :, 2])))
    if len(values) != 2 or abs(values[0] - values[1]) < margin:
        return None, [round(v, 1) for v in values]
    return (0 if values[0] > values[1] else 1), [round(v, 1) for v in values]


def _read_observation(second, image, profile, weapon_reader, numeric_reader):
    from apex_clipper import crop, icon_signature, inactive_view
    from outcome_reader import spectator_view
    from hud_enrichment import roi
    from weapon_reader import caption_views, recognize_text_views, resolve_weapon_text, active_slot, highlight_score
    row = {'actual_pts': second}
    inactive = inactive_view(image)
    if inactive or spectator_view(image, inactive):
        return {**row, 'excluded_view': True}
    highlights = [highlight_score(roi(image, profile, box)) for box in profile['weapon_name_metrics']]
    slot = active_slot(highlights)
    row.update(slot=slot, highlights=highlights)
    if slot is None:
        slot, backgrounds = _background_slot([roi(image, profile, box) for box in profile['weapon_name_boxes']])
        row.update(slot=slot, slot_backgrounds=backgrounds)
        if slot is not None and max(highlights) > 0:
            row['slot_basis'] = 'name_panel_background'
        else:
            row['slot'] = None
            return {**row, 'reason': 'ambiguous_active_slot'}
    patch = roi(image, profile, profile['weapon_name_boxes'][slot])
    values = weapon_reader(caption_views(patch))[0]
    label, weapon = recognize_text_views(values)
    reads = [{'text': text, 'confidence': float(confidence)} for text, confidence in values]
    agreement = sum(_view_supports(text, float(confidence), weapon) for text, confidence in values) if weapon else 0
    text, confidence = numeric_reader([crop(image, profile['ammo'], profile['reference_size'])])[0][0]
    number = int(text) if text.isascii() and text.isdigit() and float(confidence) >= .88 else None
    row.update(weapon=weapon, raw_name=label['text'], confidence=float(label['confidence']),
               name_views=reads, name_view_agreement=agreement,
               ammo={'text': text, 'value': number, 'confidence': float(confidence)},
               weapon_icon=icon_signature(image, profile), weapon_icon_mask=icon_mask(image, profile))
    return row


def recheck_event_weapons(source, events, profile, force=False, on_activity=None):
    """每条未核对战果最多四帧；时间均相对当前输入视频，调用方负责原片/成片换算。"""
    from apex_clipper import fingerprint, probe
    from app_cancel import check_cancel
    source = Path(source)
    before = fingerprint(source)
    identity = {'path': before['path'], 'size': before['size'], 'mtime_ms': before['mtime_ns'] // 1_000_000}
    results = deepcopy(events)
    if not events:
        return results
    signature = recipe(profile)
    selected = [index for index, event in enumerate(events)
                if force or not weapon_context_current(event, identity, profile, signature=signature)]
    if not selected:
        return results
    eligible = []
    for index in selected:
        event = events[index]
        context = {'version': VERSION, 'recipe': signature, 'source': identity,
                   'event': _event_location(event), 'status': 'unknown', 'scope': 'unknown',
                   'weapon': None, 'label': '相关武器未确认', 'kill_attribution': False, 'evidence': []}
        results[index]['weapon_context'] = context
        second = event.get('time')
        if (event.get('kind') not in KINDS or event.get('ownership') != 'self'
                or event.get('confirmed') is False or isinstance(second, bool)
                or not isinstance(second, (int, float)) or not math.isfinite(second)):
            context['reason'] = 'unconfirmed_or_unsupported_event'
        elif not profile or profile.get('layout_status') != 'confirmed':
            context['reason'] = 'unconfirmed_layout'
        else:
            eligible.append(index)
    if not eligible:
        return results
    metadata, video = probe(source)
    end = float(metadata['format']['duration'])
    if list(profile.get('reference_size', [])) != [video['width'], video['height']]:
        for index in eligible:
            results[index]['weapon_context']['reason'] = 'layout_size_mismatch'
        return results
    moments = sorted({events[index]['time'] + offset for index in eligible
                      for offset in [-1., -.5, 0., .12]
                      if 0 <= events[index]['time'] + offset < end})
    from engine_pool import pooled_engine
    from gpu_ocr_backend import create_ocr_engine
    from weapon_reader import WeaponTextReader, MODEL_PATH, MODEL_SHA
    from combat_statistics import final_counter_reader
    from hud_enrichment import native_frames
    backend = os.environ.get('APEX_OCR_BACKEND', 'cpu')
    # The same three-model reader already handles counters. Keep its bounded,
    # exact-pixel cache while each observation retains its own decoded PTS.
    # Refresh it before inserting the weapon reader into the two-entry pool.
    numeric_reader = final_counter_reader()
    weapon_reader = pooled_engine(('event-weapon-reader', backend, MODEL_SHA),
        lambda: WeaponTextReader(create_ocr_engine(backend=backend, model_path=MODEL_PATH, rec_batch_num=1).text_rec))
    observations = []
    for second, image in native_frames(source, 0, end, moments):
        check_cancel()
        observations.append(_read_observation(second, image, profile, weapon_reader, numeric_reader))
        if on_activity:
            on_activity({'message': '核对战果附近持枪和弹药变化', 'frames_done': len(observations), 'frames_total': len(moments)})
    for index in eligible:
        results[index]['weapon_context'].update(context_from_observations(events[index], observations))
    # 近处四帧没有结论的战果：按 0.5 秒间隔向前 6 秒、向后 3 秒补读，只补读这些事件。
    pending = [index for index in eligible if results[index]['weapon_context']['status'] != 'observed'
               and results[index]['weapon_context'].get('reason') != 'multiple_firing_weapons']
    if pending:
        seen = {round(row['actual_pts'], 3) for row in observations}
        extra = sorted({round(events[index]['time'] + offset / 2, 3) for index in pending
                        for offset in range(-int(EXTENDED_BEFORE * 2), int(EXTENDED_AFTER * 2) + 1)
                        if 0 <= events[index]['time'] + offset / 2 < end} - {round(m, 3) for m in moments})
        for second, image in native_frames(source, 0, end, extra):
            check_cancel()
            if round(second, 3) in seen:
                continue
            seen.add(round(second, 3))
            observations.append(_read_observation(second, image, profile, weapon_reader, numeric_reader))
            if on_activity:
                on_activity({'message': '扩大范围核对战果前后持枪', 'frames_done': len(observations), 'frames_total': len(moments) + len(extra)})
        for index in pending:
            near = context_near_event(events[index], observations)
            if near['status'] == 'observed':
                results[index]['weapon_context'].update(near)
            else:
                results[index]['weapon_context']['extended_reason'] = near.get('reason')
    if fingerprint(source) != before:
        raise ValueError('武器复核期间录像发生变化，不能保存关联证据')
    return results
