"""战果附近的持枪/射击证据；不将时间邻近关系写成击杀武器归因。"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path


VERSION = 'event-weapon-context-v1'
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


def _usable(row):
    weapon = row.get('weapon')
    return (not row.get('excluded_view') and weapon and row.get('slot') in (0, 1)
            and row.get('confidence', 0) >= .80 and row.get('name_view_agreement', 0) >= 2)


def _same_weapon(a, b):
    if not _usable(a) or not _usable(b):
        return False
    return (a['slot'] == b['slot'] and a['weapon']['id'] == b['weapon']['id']
            and a['weapon'].get('variant') == b['weapon'].get('variant'))


def _icon_similarity(a, b):
    from apex_clipper import icon_similarity
    if not a.get('weapon_icon') or not b.get('weapon_icon'):
        return 0.
    return float(icon_similarity(a['weapon_icon'], b['weapon_icon']))


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
    return {**base, 'reason': 'insufficient_or_conflicting_hud_evidence'}


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
        return {**row, 'reason': 'ambiguous_active_slot'}
    patch = roi(image, profile, profile['weapon_name_boxes'][slot])
    values = weapon_reader(caption_views(patch))[0]
    label, weapon = recognize_text_views(values)
    reads = [{'text': text, 'confidence': float(confidence)} for text, confidence in values]
    agreement = sum((resolve_weapon_text(text, float(confidence)) or {}).get('id') == weapon['id']
                    for text, confidence in values) if weapon else 0
    text, confidence = numeric_reader([crop(image, profile['ammo'], profile['reference_size'])])[0][0]
    number = int(text) if text.isascii() and text.isdigit() and float(confidence) >= .88 else None
    row.update(weapon=weapon, raw_name=label['text'], confidence=float(label['confidence']),
               name_views=reads, name_view_agreement=agreement,
               ammo={'text': text, 'value': number, 'confidence': float(confidence)},
               weapon_icon=icon_signature(image, profile))
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
    if fingerprint(source) != before:
        raise ValueError('武器复核期间录像发生变化，不能保存关联证据')
    return results
