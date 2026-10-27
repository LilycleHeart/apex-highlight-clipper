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
    if profile and list(profile.get('reference_size') or []) != [video['width'], video['height']]:
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
        events = [{'kind': e.get('kind'), 'time': e.get('time'), 'text': e.get('text'),
                   'confidence': e.get('confidence'), 'target': e.get('target_text')}
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
