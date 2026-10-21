"""Small JSON metadata bridge; never constructs OCR/decode runtimes."""
import json
from pathlib import Path
import sys

from algorithm_versions import FIELDS, classify_fields, current_registry
from hud_job_store import JobStore, media_identity,commit_receipt
from hud_recovery import clip_id


def snapshot(request):
    registry = current_registry(); store = JobStore(request['root'])
    allowed = {clip_id(row['file']): row for row in request.get('clips', [])}
    if request.get('action') == 'load':
        job = store.load(request['id'])
        if any(key not in allowed for key in job['clips']):
            raise ValueError('任务包含尚未载入片段库的成片，请先载入相应记录')
        return job
    clips = []; manifests = {}
    for key, row in allowed.items():
        directory = row['directory']
        if directory not in manifests:
            try: manifests[directory] = json.loads((Path(directory) / 'export.json').read_text('utf-8-sig'))
            except (OSError, ValueError): manifests[directory] = {}
        saved = next((item for item in manifests[directory].get('clips', [])
            if clip_id(item.get('output', item.get('file', ''))) == key), {})
        recognition = saved.get('recognition', {})
        status = classify_fields({**recognition.get('hud_info', {}), **recognition}, FIELDS, registry)
        fields = []
        for field in FIELDS:
            previous = recognition.get('field_algorithms', {}).get(field, {})
            state = status[field]
            reason='当前算法资源不完整，版本兼容性未知' if not registry[field]['complete'] else None
            if field in {'statistics','opponents','event_weapons'} and previous:
                try: actual={**commit_receipt(Path(directory)/'statistics.json'),'segment':saved['segment']}
                except (OSError,KeyError):actual=None
                if recognition.get('field_inputs',{}).get(field)!=actual:
                    state='unknown';reason='输入统计记录或片段映射已改变，需要重新核实'
            fields.append({'field': field, 'label': {'account':'账号','weapons':'武器','teammates':'队友','hero':'英雄','rank':'段位','statistics':'战绩','opponents':'敌人姓名','event_weapons':'事件武器'}[field], 'status': state if isinstance(state, str) else state['status'],
                'version': previous.get('semantic_version'), 'currentVersion': registry[field].get('semantic_version'),
                'updatedAt': previous.get('updated_at'), 'fingerprint': previous.get('signature'),
                'currentSignature': registry[field].get('signature'),
                'reason': reason})
        clips.append({'file': row['file'], 'fields': fields})
    jobs = []
    for job in store.list_jobs(unfinished_only=True,snapshot=True):
        summary = store.summary_from_job(job); counts = summary['fields']; issues = []; warnings = []
        for key, clip in job['clips'].items():
            try:
                if key not in allowed: issues.append('素材尚未载入片段库')
                elif media_identity(clip['file']) != clip['source_identity']: warnings.append('部分素材已变化，继续将重算对应字段')
            except OSError: issues.append('素材不可用')
            if any(not registry[field]['complete'] for field in clip['fields']): issues.append('当前算法资源不完整')
        # Changed semantic fields can be reset individually on explicit resume.
        jobs.append({'id': job['id'], 'status': 'interrupted' if job['status'] in {'pending', 'running'} else job['status'],
            'compatible': not issues, 'completed': counts['done'], 'total': sum(counts.values()),
            'inFlight': counts['inflight'], 'updatedAt': summary['updated_at'],
            'invalidReason': issues[0] if issues else warnings[0] if warnings else None,
            'files': [row['file'] for row in job['clips'].values()],
            'fields': list(dict.fromkeys(field for row in job['clips'].values() for field in row['fields']))})
    return {'clips': clips, 'jobs': jobs}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(snapshot(json.loads(sys.stdin.read())), ensure_ascii=False))
