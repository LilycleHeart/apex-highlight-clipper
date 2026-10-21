"""Durable per-clip/per-field re-recognition checkpoints (standard library only).

Recognition outputs remain owned by their existing atomic commit routines. Call
mark_committed only AFTER those routines return successfully; a crash in between
may repeat a read, but can never turn an uncommitted read into a completed field.
All mutations serialize across threads/processes and atomically replace JSON.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid

from algorithm_versions import canonical, compatible, digest, utc_now

SCHEMA = 1
STATES = frozenset({'pending', 'inflight', 'done', 'failed'})
_DESCRIPTOR_BODY = ('algorithm_id', 'components', 'models', 'resources', 'semantic_config')
_ALGORITHM_SUMMARY = ('schema', 'algorithm_id', 'semantic_version', 'signature', 'complete')
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


class CorruptCheckpoint(ValueError):
    pass


class IncompatibleCheckpoint(ValueError):
    pass


def media_identity(path):
    """Match existing source fingerprint style without reading the entire video."""
    path = Path(path).resolve()
    stat = path.stat()
    return {'path': str(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'ino': stat.st_ino}


def commit_receipt(path):
    path = Path(path).resolve()
    with path.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'sha256': sha}


def _validate_descriptor(descriptor):
    if (not isinstance(descriptor, dict) or descriptor.get('schema') != SCHEMA
            or not isinstance(descriptor.get('algorithm_id'), str)
            or not isinstance(descriptor.get('complete'), bool)
            or not isinstance(descriptor.get('semantic_version'), str)
            or any(not isinstance(descriptor.get(key), dict) for key in _DESCRIPTOR_BODY[1:])):
        raise CorruptCheckpoint('Incomplete algorithm audit descriptor')
    if descriptor.get('signature') != digest({key: descriptor[key] for key in _DESCRIPTOR_BODY}):
        raise CorruptCheckpoint('Algorithm descriptor signature mismatch')
    return descriptor


def _algorithm_summary(descriptor):
    return {key: descriptor[key] for key in _ALGORITHM_SUMMARY}


def algorithm_descriptor(job, clip_id, field):
    """Return one complete audit descriptor without expanding the whole job."""
    algorithm = job['clips'][str(clip_id)]['fields'][field]['algorithm']
    if 'descriptor_ref' not in algorithm:
        return copy.deepcopy(_validate_descriptor(algorithm))
    reference = algorithm['descriptor_ref']
    table = job.get('algorithm_descriptors', {})
    descriptor = table.get(reference) if isinstance(reference, str) and isinstance(table, dict) else None
    _validate_descriptor(descriptor)
    if algorithm != {**_algorithm_summary(descriptor), 'descriptor_ref': descriptor['signature']}:
        raise CorruptCheckpoint('Algorithm reference does not match its audit descriptor')
    return copy.deepcopy(descriptor)


def _validate(payload):
    if not isinstance(payload, dict) or payload.get('schema') != SCHEMA or not isinstance(payload.get('clips'), dict):
        raise CorruptCheckpoint('Unsupported or damaged checkpoint schema')
    if not isinstance(payload.get('id'), str) or payload.get('status') not in {'pending', 'running', 'paused', 'completed'}:
        raise CorruptCheckpoint('Damaged job identity or status')
    descriptors = payload.get('algorithm_descriptors', {})
    if not isinstance(descriptors, dict):
        raise CorruptCheckpoint('Damaged algorithm audit table')
    checked = {}
    for signature, descriptor in descriptors.items():
        _validate_descriptor(descriptor)
        if signature != descriptor['signature']:
            raise CorruptCheckpoint('Algorithm audit table key mismatch')
        checked[signature] = descriptor
    summaries = {signature: {**_algorithm_summary(descriptor), 'descriptor_ref': signature}
        for signature, descriptor in descriptors.items()}
    for clip in payload['clips'].values():
        if not isinstance(clip, dict) or not isinstance(clip.get('fields'), dict):
            raise CorruptCheckpoint('Damaged clip checkpoint')
        for field in clip['fields'].values():
            if not isinstance(field, dict) or field.get('state') not in STATES or not isinstance(field.get('algorithm'), dict):
                raise CorruptCheckpoint('Damaged field checkpoint')
            algorithm = field['algorithm']
            if 'descriptor_ref' in algorithm:
                reference = algorithm['descriptor_ref']
                if not isinstance(reference, str) or algorithm != summaries.get(reference):
                    raise CorruptCheckpoint('Missing or mismatched algorithm audit reference')
            else:
                signature = algorithm.get('signature')
                if not isinstance(signature, str) or algorithm != checked.get(signature):
                    _validate_descriptor(algorithm)
                    checked[signature] = algorithm
    return payload


def compact_algorithms(job):
    """Compact only an explicitly saved job; schema 1 and compatibility stay intact."""
    _validate(job)
    table = dict(job.get('algorithm_descriptors', {}))
    for clip in job['clips'].values():
        for item in clip['fields'].values():
            algorithm = item['algorithm']
            if 'descriptor_ref' in algorithm:
                continue
            signature = algorithm['signature']
            if signature not in table:
                table[signature] = copy.deepcopy(algorithm)
            elif table[signature] != algorithm:
                # Same semantic signature can carry distinct audit annotations.
                # Retain those uncommon records inline instead of losing detail.
                continue
            item['algorithm'] = {**_algorithm_summary(algorithm), 'descriptor_ref': signature}
    job['algorithm_descriptors'] = table
    return job


def _read(path, *, data=None):
    try:
        text = data.decode('utf-8') if data is not None else Path(path).read_text(encoding='utf-8')
        envelope = json.loads(text)
        payload = envelope['payload']
        if envelope.get('checksum') != digest(payload):
            raise CorruptCheckpoint('Checkpoint checksum mismatch')
        return _validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise CorruptCheckpoint(str(error)) from error


def _replace_bytes(path, data):
    path = Path(path)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        if os.name != 'nt':
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


class JobStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with _LOCKS_GUARD:
            self._thread_lock = _LOCKS.setdefault(str(self.root), threading.RLock())

    @contextmanager
    def _locked(self, *, snapshot=False):
        with self._thread_lock:
            # OS advisory locks are released on hard process exit; no stale PID
            # deletion heuristics or potentially unsafe lock-file stealing.
            with (self.root / '.jobs.lock').open('a+b') as lock:
                if lock.seek(0, os.SEEK_END) == 0:
                    lock.write(b'\0')
                    lock.flush()
                lock.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    if not snapshot:
                        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                    else:
                        from app_cancel import check_cancel
                        deadline = time.monotonic() + 15
                        while True:
                            check_cancel()
                            try:
                                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                                break
                            except OSError as error:
                                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                                    raise
                                if time.monotonic() >= deadline:
                                    raise TimeoutError('识别检查点正在写入，请稍后刷新') from error
                                time.sleep(.05)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    lock.seek(0)
                    if os.name == 'nt':
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _path(self, job_id):
        if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
            raise ValueError('Invalid job id')
        return self.root / (job_id + '.json')

    def _load(self, job_id, *, snapshot=False):
        path = self._path(job_id)
        def read(path):
            if not snapshot:
                return _read(path)
            # Windows readers can block os.replace while their file is open.
            # Copy bytes under the normal writer lock, then parse and verify the
            # large immutable snapshot after releasing it.
            with self._locked(snapshot=True):
                try:
                    data = path.read_bytes()
                except OSError as error:
                    raise CorruptCheckpoint(str(error)) from error
            return _read(path, data=data)
        try:
            return read(path)
        except CorruptCheckpoint as primary_error:
            try:
                result = read(path.with_suffix('.json.bak'))
            except CorruptCheckpoint:
                raise CorruptCheckpoint('Both primary checkpoint and backup are unavailable or damaged: ' + str(primary_error)) from primary_error
            result['recovered_from_backup'] = True
            # Partial *.tmp files are never treated as completed writes.
            return result

    def _save(self, job):
        compact_algorithms(job)
        job['updated_at'] = utc_now()
        path = self._path(job['id'])
        # Keep only the last VALID durable primary. A damaged primary must not
        # overwrite the valid backup used for recovery.
        if path.exists():
            try:
                _read(path)
                _replace_bytes(path.with_suffix('.json.bak'), path.read_bytes())
            except CorruptCheckpoint:
                pass
        encoded = canonical({'payload': job, 'checksum': digest(job)}).encode('utf-8')
        _replace_bytes(path, encoded)

    def load(self, job_id):
        with self._locked():
            return copy.deepcopy(self._load(job_id))

    def list_jobs(self, *, unfinished_only=False, snapshot=False):
        # UI snapshots hold the writer lock only while copying each file's bytes.
        # Mutating callers retain the existing transaction-wide lock.
        with nullcontext() if snapshot else self._locked():
            jobs = []
            # Include backups whose primary disappeared; ignore incomplete temps.
            ids = {path.name[:32] for pattern in ('*.json', '*.json.bak') for path in self.root.glob(pattern)}
            for job_id in ids:
                try:
                    job = self._load(job_id, snapshot=snapshot)
                except (CorruptCheckpoint, ValueError):
                    continue
                if not unfinished_only or job['status'] != 'completed':
                    jobs.append(job)
            return sorted(jobs, key=lambda job: job['created_at'], reverse=True)

    @staticmethod
    def _work(clips, registry):
        result = {}
        for clip in clips:
            clip_id = str(clip['id'])
            if clip_id in result:
                raise ValueError('Duplicate clip id')
            fields = list(dict.fromkeys(clip['fields']))
            if not fields:
                continue
            if not clip.get('source_identity'):
                raise ValueError('A real source identity is required for resumable work')
            result[clip_id] = {'source_identity': copy.deepcopy(clip['source_identity']),
                'fields': {field: {'state': 'pending', 'algorithm': copy.deepcopy(registry[field]),
                    'input_identity':copy.deepcopy(clip.get('input_identities',{}).get(field))} for field in fields},
                'metadata': copy.deepcopy(clip.get('metadata', {})),
                **{key: copy.deepcopy(clip[key]) for key in ('file', 'source', 'directory', 'start', 'end') if key in clip}}
        return result

    @staticmethod
    def _covers(saved, work):
        """A second upgrade click may now select only the remaining old fields."""
        for clip_id, fresh in work.items():
            old = saved.get('clips', {}).get(clip_id)
            if not old or old.get('source_identity') != fresh['source_identity']:
                return False
            for field, item in fresh['fields'].items():
                previous = old['fields'].get(field)
                if not previous or not compatible(previous['algorithm'], item['algorithm']):
                    return False
        return True

    def create(self, clips, registry, *, kind='force', scope='', request=None):
        """Force always creates a new run. Upgrade deduplicates compatible work.

        Persist only an execution request snapshot (paths/fields/options) supplied
        by the caller; do not pass credentials or mutable global app state.
        An active older force run is not cancelled or overwritten implicitly.
        """
        if kind not in {'force', 'upgrade', 'normal'}:
            raise ValueError('Unknown recognition job kind')
        work = self._work(clips, registry)
        if not work:
            raise ValueError('No recognition fields selected')
        selection = digest({clip: {'source_identity': row['source_identity'],
            'fields': {field: item['algorithm'].get('signature') for field, item in row['fields'].items()}}
            for clip, row in work.items()})
        with self._locked():
            if kind in {'upgrade', 'normal'}:
                ids = {path.name[:32] for pattern in ('*.json', '*.json.bak') for path in self.root.glob(pattern)}
                for saved_id in ids:
                    try:
                        saved = self._load(saved_id)
                    except (CorruptCheckpoint, ValueError):
                        continue
                    if saved.get('status') != 'completed' and saved.get('kind') == kind and saved.get('scope') == scope and self._covers(saved, work):
                        return {**copy.deepcopy(saved), 'reused': True}
            now = utc_now()
            job = {'schema': SCHEMA, 'id': uuid.uuid4().hex, 'kind': kind, 'scope': scope,
                'selection': selection, 'status': 'pending', 'created_at': now,
                'clips': work, 'request': copy.deepcopy(request or {})}
            self._save(job)
            return copy.deepcopy(job)

    def find_unfinished(self, *, scope=None, kind=None):
        return [job for job in self.list_jobs(unfinished_only=True)
            if (scope is None or job.get('scope') == scope) and (kind is None or job.get('kind') == kind)]

    def resume(self, job_id, clips, registry, *, request=None):
        """Explicit resume after worker termination, never while it is still alive.

        In-flight and failed reads become pending. Only fields with matching media
        AND complete semantic descriptors keep their committed state. Changed or
        unavailable fields remain visible with an invalidation reason.
        """
        actual = self._work(clips, registry)
        with self._locked():
            job = self._load(job_id)
            invalidated = []
            for clip_id, old in job['clips'].items():
                fresh = actual.get(clip_id)
                for field, item in old['fields'].items():
                    current = fresh and fresh['fields'].get(field)
                    reason = None
                    if current is None:
                        reason = 'source-or-field-unavailable'
                    elif old.get('source_identity') != fresh.get('source_identity'):
                        reason = 'source-changed'
                    elif item.get('input_identity')!=current.get('input_identity'):
                        reason = 'field-input-changed'
                    elif not compatible(item['algorithm'], current['algorithm']):
                        reason = 'algorithm-model-or-semantics-changed'
                    if reason:
                        item.update(state='pending', invalidated=reason)
                        item.pop('receipt', None)
                        item.pop('completed_at', None)
                        invalidated.append({'clip': clip_id, 'field': field, 'reason': reason})
                    elif item['state'] != 'done':
                        item.update(state='pending')
                    item.pop('error', None)
                    item.pop('started_at', None)
                    if current is not None:
                        item['algorithm'] = copy.deepcopy(current['algorithm'])
                        item['input_identity'] = copy.deepcopy(current.get('input_identity'))
                if fresh:
                    old['source_identity'] = copy.deepcopy(fresh['source_identity'])
                    old.update({key: copy.deepcopy(fresh[key]) for key in ('file', 'source', 'directory', 'start', 'end', 'metadata') if key in fresh})
            job['status'] = 'completed' if self._all_done(job) else 'pending'
            job['invalidated'] = invalidated
            if request is not None:
                job['request'] = copy.deepcopy(request)
            self._save(job)
            return copy.deepcopy(job)

    @staticmethod
    def _all_done(job):
        return (all(item['state'] == 'done' for clip in job['clips'].values() for item in clip['fields'].values())
            and all(group['state']=='done' for group in job.get('finalization',{}).values()))

    def configure_finalization(self,job_id,groups):
        with self._locked():
            job=self._load(job_id);saved=job.setdefault('finalization',{})
            for key,group in groups.items():saved.setdefault(key,{**copy.deepcopy(group),'state':'pending'})
            if any(row.get('reason') for row in job.get('invalidated',[])):
                for group in saved.values():group['state']='pending'
            job['status']='completed' if self._all_done(job) else 'pending'
            self._save(job)
            return copy.deepcopy(job)

    def mark_finalized(self,job_id,key,*,receipt):
        if not receipt:raise ValueError('A durable finalization receipt is required')
        with self._locked():
            job=self._load(job_id);group=job['finalization'][key]
            if any(job['clips'][clip_id]['fields'][field]['state']!='done'
                for clip_id,fields in group['clips'].items() for field in fields):
                raise ValueError('Finalization requires committed input fields')
            group.update(state='done',receipt=copy.deepcopy(receipt))
            job['status']='completed' if self._all_done(job) else 'running'
            self._save(job)

    def pending(self, job_id):
        job = self.load(job_id)
        return [{'id': clip_id, 'source_identity': clip['source_identity'],
            'fields': [field for field, item in clip['fields'].items() if item['state'] in {'pending', 'failed'}],
            'metadata': clip.get('metadata', {}),
            **{key: copy.deepcopy(clip[key]) for key in ('file', 'source', 'directory', 'start', 'end') if key in clip}} for clip_id, clip in job['clips'].items()
            if any(item['state'] in {'pending', 'failed'} for item in clip['fields'].values())]

    def claim(self, job_id, clip_id, fields, *, pending_only=False):
        fields = list(dict.fromkeys(fields))
        with self._locked():
            job = self._load(job_id)
            clip = job['clips'][str(clip_id)]
            if pending_only:
                fields = [field for field in fields if clip['fields'][field]['state'] in {'pending', 'failed'}]
                if not fields:
                    return copy.deepcopy(clip)
            if not fields or any(clip['fields'][field]['state'] not in {'pending', 'failed'} for field in fields):
                raise ValueError('Fields are already running or committed')
            for field in fields:
                item = clip['fields'][field]
                if item.get('invalidated') == 'source-or-field-unavailable':
                    raise IncompatibleCheckpoint('Missing source or field must be resolved before resume')
                if not item['algorithm'].get('complete'):
                    raise IncompatibleCheckpoint('Algorithm resources are missing; cannot create a resumable read')
                item.update(state='inflight', started_at=utc_now())
                item.pop('error', None)
                item.pop('invalidated', None)
            job['status'] = 'running'
            self._save(job)
            return copy.deepcopy(clip)

    def mark_committed(self, job_id, clip_id, fields, *, receipt):
        """Receipt identifies durable output; this call NEVER performs recognition."""
        if not isinstance(receipt, dict) or not receipt:
            raise ValueError('A successful atomic output commit receipt is required')
        fields = list(dict.fromkeys(fields))
        with self._locked():
            job = self._load(job_id)
            clip = job['clips'][str(clip_id)]
            if not fields or any(clip['fields'][field]['state'] != 'inflight' for field in fields):
                raise ValueError('Only claimed fields may be committed')
            for field in fields:
                clip['fields'][field].update(state='done', completed_at=utc_now(), receipt=copy.deepcopy(receipt))
            job['status'] = 'completed' if self._all_done(job) else 'running'
            self._save(job)
            return copy.deepcopy(job)

    def fail(self, job_id, clip_id, fields, error):
        with self._locked():
            job = self._load(job_id)
            for field in fields:
                item = job['clips'][str(clip_id)]['fields'][field]
                if item['state'] == 'done':
                    raise ValueError('A committed field cannot be failed')
                item.update(state='failed', error=str(error))
            job['status'] = 'paused'
            self._save(job)
            return copy.deepcopy(job)

    def pause(self, job_id):
        """Call after workers have stopped; in-flight work is safe to retry."""
        with self._locked():
            job = self._load(job_id)
            for clip in job['clips'].values():
                for item in clip['fields'].values():
                    if item['state'] == 'inflight':
                        item.update(state='pending')
                        item.pop('started_at', None)
            job['status'] = 'completed' if self._all_done(job) else 'paused'
            self._save(job)
            return copy.deepcopy(job)

    def summary(self, job_id):
        return self.summary_from_job(self.load(job_id))

    @staticmethod
    def summary_from_job(job):
        counts = {state: 0 for state in STATES}
        done_clips = 0
        for clip in job['clips'].values():
            for item in clip['fields'].values():
                counts[item['state']] += 1
            done_clips += all(item['state'] == 'done' for item in clip['fields'].values())
        return {'id': job['id'], 'kind': job['kind'], 'status': job['status'],
            'clips': len(job['clips']), 'completed_clips': done_clips,
            'fields': counts, 'updated_at': job['updated_at'],
            'invalidated': job.get('invalidated', []), 'recovered_from_backup': job.get('recovered_from_backup', False)}
