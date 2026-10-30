"""给导入的成片补片段级统计：采样成片、读计分栏与战果提示，不导出。

导入片段没有原录像，只能把成片本身当作源视频跑「整理」的后半段；
交战分段与导出都跳过，统计结果写回导入清单的 clip。
"""
import json
import shutil
import tempfile
from pathlib import Path

from apex_clipper import fingerprint, probe, read_hud

FPS = 2.
BASE_PROFILE = json.loads((Path(__file__).resolve().parent / 'profile-ultrawide.json').read_text(encoding='utf-8'))


def build_statistics(source, profile=None, on_activity=None):
    from continuous_sampler import sample_continuous_with_resume
    from hud_layout import detect_video
    from combat_statistics import collect_statistics

    source = Path(source)
    meta, video = probe(source)
    duration = float(meta['format']['duration'])
    if profile and (list(profile.get('reference_size') or []) != [video['width'], video['height']]
                    or profile.get('layout_status') != 'confirmed'):
        # 未确认的旧布局不能沿用；detect_video 会多取几帧重新确认。
        profile = None
    profile = profile or detect_video(source, video, duration, BASE_PROFILE)
    work = Path(tempfile.mkdtemp(prefix='ahc-imported-stat-'))
    try:
        if on_activity:
            on_activity({'message': '采样成片画面', 'frames_done': 0, 'frames_total': 0})
        samples = work / 'samples'
        total = max(1, int(duration * FPS + .5))
        sample_continuous_with_resume(source, samples, FPS, False, frame_ranges=[[1, total]])
        if on_activity:
            on_activity({'message': '读取计分栏', 'frames_done': total // 2, 'frames_total': total})
        rows = read_hud(samples, profile, FPS, work / 'hud.json', resume=False)
        cache = {'source': fingerprint(source), 'fps': FPS, 'rows': rows, 'outcome_events': []}
        segments = [{'start': 0., 'end': duration}]
        statistics = collect_statistics(cache, samples, segments, profile, work / 'statistics-report.json')
        segment = statistics['segments'][0]
        # 这里只保留已确认的本人战果；显式记下归属，事件武器复核据此判断是否需要读画面。
        events = [{'kind': e.get('kind'), 'time': e.get('time'), 'text': e.get('text'),
                   'confidence': e.get('confidence'), 'target': e.get('target_text'),
                   'ownership': e.get('ownership'), 'confirmed': True}
                  for e in (segment.get('events') or []) if e.get('confirmed') and e.get('kind') in {'knock', 'assist', 'elimination'}]
        return {
            'counts': segment.get('counts') or {},
            'events': events,
            'partial': segment.get('partial') or {},
            'coverage': segment.get('coverage') or {},
            'fps': FPS,
            'duration': round(duration, 3),
            'source': fingerprint(source),
            'version': 1,
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def confirmed_profile(source, profile=None):
    """导入片段的 HUD 布局：沿用已确认且尺寸一致的记录，否则按成片重新检测。"""
    from hud_layout import detect_video
    meta, video = probe(Path(source))
    if profile and list(profile.get('reference_size') or []) == [video['width'], video['height']] and profile.get('layout_status') == 'confirmed':
        return profile
    return detect_video(Path(source), video, float(meta['format']['duration']), BASE_PROFILE)


def video_origin(source):
    """成片首帧 PTS；统计时间从首帧算起，原生帧读取用的是 PTS。"""
    _, video = probe(Path(source))
    try:
        origin = float(video.get('start_time') or 0)
    except (TypeError, ValueError):
        origin = 0.
    return origin if origin == origin and abs(origin) != float('inf') else 0.


def carry_weapon_contexts(previous, statistics):
    """重算统计后，同一时刻同类战果沿用已核对的武器证据；时刻变了就不再沿用。"""
    saved = {(e.get('kind'), e.get('time')): e['weapon_context'] for e in (previous or {}).get('events') or [] if e.get('weapon_context')}
    for event in statistics.get('events') or []:
        context = saved.get((event.get('kind'), event.get('time')))
        if context: event['weapon_context'] = context
    return statistics


def attach_event_weapons(source, statistics, profile=None, force=False, on_activity=None):
    """给导入片段的本人战果补持枪/射击证据；同任务片段一样只记录观察，不做击杀武器归因。"""
    from event_weapon_reader import recheck_event_weapons
    events = statistics.get('events') or []
    if not events:
        return statistics
    profile = confirmed_profile(source, profile)
    origin = video_origin(source)
    local = []
    for event in events:
        # 早期导入统计未写归属；它们只来自本人中心战果提示，读取时补上同样的含义。
        row = {**event, 'ownership': event.get('ownership') or 'self', 'confirmed': event.get('confirmed', True),
               'time': event['time'] + origin}
        if row.get('weapon_context'):
            saved = dict(row['weapon_context'].get('event') or {})
            saved['time'] = saved.get('source_time', saved.get('time'))
            saved.pop('source_time', None)
            row['weapon_context'] = {**row['weapon_context'], 'event': saved}
        local.append(row)
    checked = recheck_event_weapons(source, local, profile, force=force, on_activity=on_activity)
    result = []
    for original, row, event in zip(events, local, checked):
        merged = {**original, 'ownership': row['ownership'], 'confirmed': row['confirmed']}
        context = event.get('weapon_context')
        if context:
            merged['weapon_context'] = {**context, 'event': {**context['event'], 'time': original['time'], 'source_time': event['time']}}
        result.append(merged)
    return {**statistics, 'events': result}


def apply_to_manifest(manifest_path, source, statistics):
    return apply_many(manifest_path, {source: statistics})


def apply_many(manifest_path, results):
    """一次写回多条片段的统计，避免每段都重读写整个导入清单。"""
    if not results:
        return 0
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text('utf-8-sig'))
    wanted = {str(Path(source).resolve()).casefold(): value for source, value in results.items()}
    changed = 0
    for clip in manifest.get('clips', []):
        output = clip.get('output')
        if isinstance(output, str):
            value = wanted.get(str(Path(output).resolve()).casefold())
            if value is not None:
                clip['statistics'] = value
                changed += 1
    if changed:
        from apex_clipper import write_json
        write_json(manifest_path, manifest)
    return changed
