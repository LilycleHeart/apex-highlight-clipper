"""Connect durable checkpoints to the existing read/atomic-commit pipeline."""
from contextlib import contextmanager
from functools import wraps
import json
from pathlib import Path
import threading

from algorithm_versions import FIELDS, current_registry, stamp_fields, compatible, digest
from hud_job_store import JobStore, media_identity, commit_receipt

_active = None
_guard = threading.RLock()


def clip_id(file):
    return str(Path(file).resolve()).casefold()


def records(request, registry):
    selected = request.get('selection') or {}
    result = []
    for job in request['jobs']:
        for file in job['files']:
            fields = selected.get(clip_id(file), job.get('fields', request.get('fields') or FIELDS))
            if fields:
                extra=set(fields)&{'statistics','opponents','event_weapons'};inputs={}
                # 导入的成片没有 statistics.json：战绩数字改由成片画面重新统计，不需要输入身份。
                source=Path(job['directory'])/'statistics.json'
                if extra and source.is_file():
                    manifest=json.loads((source.parent/'export.json').read_text('utf-8-sig'))
                    clip=next(row for row in manifest['clips'] if clip_id(row.get('output',row.get('file','')))==clip_id(file))
                    identity={**commit_receipt(source),'segment':clip['segment']}
                    inputs={field:identity for field in extra}
                result.append({'id': clip_id(file), 'file': str(Path(file).resolve()),
                    'directory': str(Path(job['directory']).resolve()),
                    'source_identity': media_identity(file), 'fields': list(fields),'input_identities':inputs})
    return result


def grouped_pending(store, job):
    groups = {}
    for row in store.pending(job['id']):
        key = (row['directory'], tuple(row['fields']))
        groups.setdefault(key, []).append(row['file'])
    return [{'directory': directory, 'files': files, 'fields': list(fields)}
        for (directory, fields), files in groups.items()]


def unfinished_request(request, checkpoint):
    """A crash/fallback may already have committed a subset of a child group."""
    saved = JobStore(checkpoint['root']).load(checkpoint['id']); groups = {}
    for job in request['jobs']:
        for file in job['files']:
            row = saved['clips'][clip_id(file)]
            fields = tuple(field for field in job.get('fields', request['fields'])
                if row['fields'][field]['state'] != 'done')
            if fields: groups.setdefault((job['directory'], fields), []).append(file)
    return {**request, 'jobs': [{'directory': directory, 'files': files, 'fields': list(fields)}
        for (directory, fields), files in groups.items()]}


class Session:
    def __init__(self, root, job_id, registry, emit=None):
        self.store = JobStore(root); self.id = job_id; self.registry = registry; self.emit=emit

    def claim(self, file, fields):
        with _guard:
            self.store.claim(self.id, clip_id(file), fields, pending_only=True)

    def fail(self, file, fields, error):
        with _guard:
            row = self.store.load(self.id)['clips'][clip_id(file)]
            unfinished = [field for field in fields if row['fields'][field]['state'] != 'done']
            if unfinished: self.store.fail(self.id, clip_id(file), unfinished, error)

    def committed(self, file, fields, path, computed_fields=()):
        receipt={**commit_receipt(path),'computed_fields':list(computed_fields)}
        with _guard:
            job=self.store.mark_committed(self.id, clip_id(file), fields, receipt=receipt)
            if self.emit:self.emit({'type':'hud-info-checkpoint','job_id':self.id,**self.store.summary_from_job(job)})


def claim(file, fields):
    if _active: _active.claim(file, fields)


def active():
    return _active is not None


def semantic_current(recognition, field):
    if not _active: return None
    from algorithm_versions import classify_field
    if field not in recognition.get('field_algorithms', {}): return None
    return classify_field(recognition, field, _active.registry) == 'current'


def profile_reusable(recognition,fields):
    return not _active or all(semantic_current(recognition,field) is True for field in fields)


def failed(file, fields, error):
    if _active: _active.fail(file, fields, error)


def stamp(recognition, fields):
    return stamp_fields(recognition, fields, _active.registry) if _active else recognition


def committed(file, fields, path, computed_fields=()):
    if _active: _active.committed(file, fields, path, computed_fields)


def commit_extra(directory, file, fields, computed_fields=()):
    """A successful repair is durable before provenance/checkpoint advancement."""
    if not _active: return
    from apex_clipper import write_json
    path = Path(directory) / 'export.json'
    manifest = json.loads(path.read_text('utf-8-sig'))
    clip = next(row for row in manifest['clips'] if clip_id(row.get('output', row.get('file'))) == clip_id(file))
    if computed_fields:
        clip['recognition'] = stamp(clip.get('recognition', {}), computed_fields)
        inputs=clip['recognition'].setdefault('field_inputs',{})
        saved=_active.store.load(_active.id)['clips'][clip_id(file)]['fields']
        inputs.update({field:saved[field].get('input_identity') for field in computed_fields})
        write_json(path, manifest)
    committed(file, fields, path,computed_fields)


def finalize_names(store,job_id):
    from apex_clipper import write_json
    from app_cancel import check_cancel
    from hud_enrichment import reconcile_manifest_names,recorded_match_keys
    job=store.load(job_id)
    for key,group in job.get('finalization',{}).items():
        if group['state']=='done':continue
        if any(job['clips'][clip]['fields'][field]['state']!='done' for clip,fields in group['clips'].items() for field in fields):continue
        check_cancel();directory=Path(group['directory']);path=directory/'export.json'
        manifest=json.loads(path.read_text('utf-8-sig'));selected=[];updates={}
        for clip in manifest['clips']:
            identity=clip_id(clip.get('output',clip.get('file','')))
            if identity not in group['clips']:continue
            selected.append(clip)
            updates[id(clip)]={field for field in group['clips'][identity]
                if field in job['clips'][identity]['fields'][field].get('receipt',{}).get('computed_fields',[])}
        if len(selected)!=len(group['clips']):raise ValueError('姓名归并范围缺少原始片段')
        if any(updates.values()):
            fields=set().union(*updates.values())
            reconcile_manifest_names({'clips':selected} if job['request'].get('force') else manifest,
                fields,targets=selected,updates=updates,match_keys=recorded_match_keys(manifest,directory))
            write_json(path,manifest)
        store.mark_finalized(job_id,key,receipt=commit_receipt(path))


def persistent_job(function):
    @wraps(function)
    def run(request, direct=False, emit=None):
        global _active
        raw_emit = emit or (lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
        event_lock=threading.RLock()
        def emit(event):
            with event_lock:raw_emit(event)
        request = dict(request); checkpoint = request.get('checkpoint')
        owner = bool(request.get('recovery_root')) and not checkpoint
        store = None; job = None
        if owner:
            registry = current_registry()
            store = JobStore(request['recovery_root'])
            if request.get('resume_job'):
                saved = store.load(request['resume_job'])
                # Resume the saved selection. New performance choices may replace
                # execution settings, but cannot broaden the saved field scope.
                request['jobs'] = saved['request']['jobs']
                request['fields'] = saved['request']['fields']
                request['selection'] = saved['request'].get('selection', {})
                request['force'] = saved['request'].get('force', False)
                rows = records(request, registry)
                job = store.resume(saved['id'], rows, registry, request=request)
            else:
                rows = records(request, registry)
                job = store.create(rows, registry, kind=request.get('job_kind', 'force' if request.get('force') else 'normal'),
                    scope=request.get('job_scope', 'library'), request=request)
                if job.get('reused'):
                    saved_request=job['request']
                    request.update({key:saved_request[key] for key in ('jobs','fields','selection','force') if key in saved_request})
                    job = store.resume(job['id'], records(request,registry), registry, request=request)
            request['jobs'] = grouped_pending(store, job)
            groups={}
            for key,row in job['clips'].items():
                names=[field for field in row['fields'] if field in {'account','teammates'}]
                if names:
                    identity=digest(row['directory']);group=groups.setdefault(identity,{'directory':row['directory'],'clips':{}})
                    group['clips'][key]=names
            job=store.configure_finalization(job['id'],groups)
            checkpoint = {'root': request['recovery_root'], 'id': job['id'], 'registry': registry}
            request['checkpoint'] = checkpoint
            if emit: emit({'type': 'hud-info-checkpoint', 'job_id': job['id'], **store.summary_from_job(job)})
        previous = _active
        if checkpoint:
            if not owner:
                actual=current_registry()
                selected={field for job in request['jobs'] for field in job.get('fields',request['fields'])}
                if any(not compatible(checkpoint['registry'][field],actual[field]) for field in selected):
                    raise ValueError('工作进程实际模型或语义配置与检查点不同，未读取或改写任何结果；请检查运行时资源后重试')
                request = unfinished_request(request, checkpoint)
            _active = Session(checkpoint['root'], checkpoint['id'], checkpoint['registry'],emit)
        try:
            result=function(request, direct=direct, emit=emit)
            if owner:finalize_names(store,job['id'])
            return result
        finally:
            _active = previous
            # The outer controller has waited for every child/read worker before
            # this point. Pending native work is never reported as committed.
            if owner and store and job:
                job=store.pause(job['id'])
                if emit: emit({'type': 'hud-info-checkpoint', 'job_id': job['id'], **store.summary_from_job(job)})
    return run
