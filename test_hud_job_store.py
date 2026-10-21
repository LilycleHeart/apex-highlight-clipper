import copy
import errno
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from algorithm_versions import canonical, compatible, descriptor, digest
from hud_job_store import CorruptCheckpoint, IncompatibleCheckpoint, JobStore, algorithm_descriptor, compact_algorithms


def registry():
    return {field: descriptor(field, {'reader': 'reader-v1'}) for field in ('hero', 'rank')}


def clips():
    return [{'id': 'clip-a', 'source_identity': {'path': 'real.mp4', 'size': 10},
        'fields': ['hero', 'rank'], 'file': 'real.mp4', 'source': 'original.mp4',
        'directory': 'export', 'metadata': {'manifest': 'export.json'}}]


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JobStore(self.temp.name)
        self.registry = registry()
        self.clips = clips()

    def tearDown(self):
        self.temp.cleanup()

    def create(self, **kwargs):
        return self.store.create(self.clips, self.registry, **kwargs)['id']

    def test_compact_fields_share_complete_audit_without_expanding_on_load(self):
        self.clips.append({**copy.deepcopy(self.clips[0]), 'id': 'clip-b'})
        self.registry['hero']['audit_note'] = 'preserve non-semantic metadata'
        job_id = self.create()
        job = self.store.load(job_id)
        self.assertEqual(job['schema'], 1)
        self.assertEqual(set(job['algorithm_descriptors']), {value['signature'] for value in self.registry.values()})
        for clip_id, clip in job['clips'].items():
            for field, item in clip['fields'].items():
                algorithm = item['algorithm']
                self.assertEqual(algorithm['descriptor_ref'], self.registry[field]['signature'])
                self.assertTrue(compatible(algorithm, self.registry[field]))
                self.assertNotIn('models', algorithm)
                complete = algorithm_descriptor(job, clip_id, field)
                self.assertEqual(complete, self.registry[field])
                complete['models']['caller-only'] = True
                self.assertNotIn('caller-only', algorithm_descriptor(job, clip_id, field)['models'])
        # Distinct audit annotations with the same semantic signature stay inline.
        annotated = copy.deepcopy(self.registry['hero'])
        annotated['audit_note'] = 'another historical annotation'
        job['clips']['clip-b']['fields']['hero']['algorithm'] = annotated
        compact_algorithms(job)
        self.assertEqual(job['clips']['clip-b']['fields']['hero']['algorithm'], annotated)
        self.assertEqual(algorithm_descriptor(job, 'clip-a', 'hero'), self.registry['hero'])

    def test_legacy_read_is_unchanged_until_save_and_backup_retains_original(self):
        job_id = self.create(request={'force': True})
        legacy = self.store.load(job_id)
        for clip_id, clip in legacy['clips'].items():
            for field, item in clip['fields'].items():
                item['algorithm'] = algorithm_descriptor(legacy, clip_id, field)
        legacy.pop('algorithm_descriptors')
        legacy['clips']['clip-a']['fields']['hero'].update(state='done', receipt={'old': True})
        path = self.store._path(job_id)
        original = canonical({'payload': legacy, 'checksum': digest(legacy)}).encode('utf-8')
        path.write_bytes(original)
        self.assertEqual(self.store.load(job_id), legacy)
        self.assertEqual(path.read_bytes(), original)
        resumed = self.store.resume(job_id, self.clips, self.registry)
        self.assertEqual(resumed['clips']['clip-a']['fields']['hero']['state'], 'done')
        self.assertEqual(self.store.pending(job_id)[0]['fields'], ['rank'])
        self.assertIn('algorithm_descriptors', resumed)
        self.assertEqual(path.with_suffix('.json.bak').read_bytes(), original)
        for field in self.registry:
            self.assertEqual(algorithm_descriptor(resumed, 'clip-a', field), self.registry[field])
        self.store.claim(job_id, 'clip-a', ['rank'])
        completed = self.store.mark_committed(job_id, 'clip-a', ['rank'], receipt={'atomic': True})
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(completed['request'], {'force': True})

    def test_compact_audit_corruption_cannot_reuse_fields_even_with_valid_envelope_checksum(self):
        from hud_job_store import _read
        job_id = self.create()
        self.store.claim(job_id, 'clip-a', ['hero'])
        good = self.store.load(job_id)
        path = self.store._path(job_id)
        signature = self.registry['hero']['signature']
        def missing_table(job):job.pop('algorithm_descriptors')
        def missing_entry(job):job['algorithm_descriptors'].pop(signature)
        def wrong_reference(job):job['clips']['clip-a']['fields']['hero']['algorithm']['descriptor_ref'] = '0' * 64
        def wrong_summary(job):job['clips']['clip-a']['fields']['hero']['algorithm']['signature'] = '0' * 64
        def changed_model(job):job['algorithm_descriptors'][signature]['models']['injected'] = {'sha256': 'other-model'}
        for damage in (missing_table, missing_entry, wrong_reference, wrong_summary, changed_model):
            with self.subTest(damage=damage.__name__):
                bad = copy.deepcopy(good);damage(bad)
                path.write_text(canonical({'payload': bad, 'checksum': digest(bad)}), encoding='utf-8')
                with self.assertRaises(CorruptCheckpoint):_read(path)
                recovered = self.store.load(job_id)
                self.assertTrue(recovered['recovered_from_backup'])
                self.assertEqual(recovered['clips']['clip-a']['fields']['hero']['state'], 'pending')

    def test_cancel_resumes_only_uncommitted_fields_and_preserves_snapshot(self):
        job = self.create(request={'backend': 'cpu', 'force': True})
        self.store.claim(job, 'clip-a', ['hero'])
        self.store.mark_committed(job, 'clip-a', ['hero'], receipt={'atomic': True})
        self.store.claim(job, 'clip-a', ['rank'])
        self.store.pause(job)
        fresh = JobStore(self.temp.name)
        fresh.resume(job, self.clips, self.registry)
        pending = fresh.pending(job)
        self.assertEqual(pending[0]['fields'], ['rank'])
        self.assertEqual(pending[0]['file'], 'real.mp4')
        self.assertEqual(pending[0]['directory'], 'export')
        self.assertEqual(fresh.load(job)['request'], {'backend': 'cpu', 'force': True})

    def test_hard_process_exit_never_promotes_inflight(self):
        job = self.create()
        script = "from hud_job_store import JobStore; import os,sys; s=JobStore(sys.argv[1]); s.claim(sys.argv[2],'clip-a',['hero','rank']); os._exit(0)"
        subprocess.run([sys.executable, '-c', script, self.temp.name, job], cwd=Path(__file__).parent, check=True)
        self.assertEqual(self.store.summary(job)['fields']['inflight'], 2)
        self.store.resume(job, self.clips, self.registry)
        self.assertEqual(self.store.pending(job)[0]['fields'], ['hero', 'rank'])
        self.assertEqual(self.store.summary(job)['fields']['done'], 0)

    def test_different_models_invalidate_only_affected_field(self):
        job = self.create()
        self.store.claim(job, 'clip-a', ['hero', 'rank'])
        self.store.mark_committed(job, 'clip-a', ['hero', 'rank'], receipt={'atomic': True})
        updated = copy.deepcopy(self.registry)
        updated['rank'] = descriptor('rank', {'reader': 'reader-v2'})
        result = self.store.resume(job, self.clips, updated)
        self.assertEqual(self.store.pending(job)[0]['fields'], ['rank'])
        self.assertEqual(result['invalidated'], [{'clip': 'clip-a', 'field': 'rank', 'reason': 'algorithm-model-or-semantics-changed'}])

    def test_source_replacement_invalidates_all_fields_and_missing_source_is_blocked(self):
        job = self.create()
        self.store.claim(job, 'clip-a', ['hero', 'rank'])
        self.store.mark_committed(job, 'clip-a', ['hero', 'rank'], receipt={'atomic': True})
        changed = copy.deepcopy(self.clips)
        changed[0]['source_identity']['size'] = 11
        self.store.resume(job, changed, self.registry)
        self.assertEqual(len(self.store.load(job)['invalidated']), 2)
        self.store.resume(job, [], self.registry)
        with self.assertRaises(IncompatibleCheckpoint):
            self.store.claim(job, 'clip-a', ['hero'])

    def test_corrupt_primary_recovers_valid_backup_and_ignores_half_written_temp(self):
        job = self.create()
        self.store.claim(job, 'clip-a', ['hero'])
        root = Path(self.temp.name)
        (root / (job + '.json')).write_text('{half-write', encoding='utf-8')
        (root / (job + '.json.half.tmp')).write_text('{"clips": "fake done"}', encoding='utf-8')
        recovered = self.store.load(job)
        self.assertTrue(recovered['recovered_from_backup'])
        self.assertEqual(recovered['clips']['clip-a']['fields']['hero']['state'], 'pending')
        with patch.object(self.store, '_locked', wraps=self.store._locked) as lock:
            self.assertEqual(self.store.list_jobs(snapshot=True), [recovered])
        self.assertEqual([call.kwargs for call in lock.call_args_list], [{'snapshot': True}] * 2)
        self.store.resume(job, self.clips, self.registry)
        self.assertEqual(self.store.summary(job)['fields']['done'], 0)

    def test_ui_snapshot_releases_lock_before_validating_old_complete_revision(self):
        from hud_job_store import _read
        job = self.create()
        path = self.store._path(job)
        replacement = path.with_suffix('.next.tmp')
        fresh = self.store.load(job)
        fresh['status'] = 'running'
        replacement.write_text(canonical({'payload': fresh, 'checksum': digest(fresh)}), encoding='utf-8')
        def replace_before_parse(source, *, data=None):
            self.assertIsNotNone(data)
            self.assertFalse(self.store._thread_lock._is_owned())
            with self.store._locked():
                os.replace(replacement, path)
            return _read(source, data=data)
        with patch('hud_job_store._read', side_effect=replace_before_parse):
            previous = self.store._load(job, snapshot=True)
        self.assertEqual(previous['status'], 'pending')
        self.assertEqual(self.store.load(job)['status'], 'running')

    def test_ui_snapshot_summarizes_loaded_revision_without_a_second_load(self):
        from hud_recovery_snapshot import snapshot
        from hud_job_store import _read
        self.create()
        with patch('hud_recovery_snapshot.current_registry', return_value=self.registry), \
                patch.object(JobStore, 'load', side_effect=AssertionError('UI must reuse the loaded snapshot')), \
                patch('hud_job_store._read', wraps=_read) as read:
            result = snapshot({'root': self.temp.name, 'clips': []})
        self.assertEqual(read.call_count, 1)
        self.assertEqual(result['jobs'][0]['completed'], 0)
        self.assertEqual(result['jobs'][0]['total'], 2)

    @unittest.skipUnless(os.name == 'nt', 'Windows checkpoint lock')
    def test_ui_lock_wait_is_cancelable_without_canceling_checkpoint_pause(self):
        from app_cancel import TaskStopped
        job = self.create()
        self.store.claim(job, 'clip-a', ['hero'])
        with patch('app_cancel.check_cancel', side_effect=[None, TaskStopped()]), \
                patch('msvcrt.locking', side_effect=OSError(errno.EACCES, 'locked')) as locking, \
                patch('hud_job_store.time.sleep'):
            with self.assertRaises(TaskStopped):
                self.store.list_jobs(snapshot=True)
        self.assertEqual(locking.call_count, 1)
        with patch('app_cancel.check_cancel', side_effect=AssertionError('stop must still save checkpoint')):
            paused = self.store.pause(job)
        self.assertEqual(paused['clips']['clip-a']['fields']['hero']['state'], 'pending')

    def test_session_claim_and_commit_reuse_their_loaded_job(self):
        from hud_recovery import Session, clip_id
        self.clips[0]['id'] = clip_id('real.mp4')
        job = self.create()
        events = []
        session = Session(self.temp.name, job, self.registry, events.append)
        with patch.object(session.store, '_load', wraps=session.store._load) as load:
            session.claim('real.mp4', ['hero'])
            self.assertEqual(load.call_count, 1)
            load.reset_mock()
            with patch.object(session.store, '_save', side_effect=AssertionError('duplicate claim must not write')):
                session.claim('real.mp4', ['hero'])
            self.assertEqual(load.call_count, 1)
            load.reset_mock()
            output = Path(self.temp.name) / 'output.json'
            output.write_text('{}', encoding='utf-8')
            session.committed('real.mp4', ['hero'], output)
            self.assertEqual(load.call_count, 1)
        self.assertEqual(events[0]['fields']['done'], 1)
        self.assertEqual(events[0]['fields']['pending'], 1)

    def test_session_commit_snapshots_are_emitted_in_commit_order(self):
        from hud_recovery import Session, clip_id
        self.clips[0]['id'] = clip_id('real.mp4')
        job = self.create()
        events = []
        session = Session(self.temp.name, job, self.registry, events.append)
        session.claim('real.mp4', ['hero', 'rank'])
        output = Path(self.temp.name) / 'output.json'
        output.write_text('{}', encoding='utf-8')
        saved = threading.Event(); release = threading.Event()
        second_started = threading.Event(); second_saved = threading.Event()
        commit = session.store.mark_committed
        def delayed(*args, **kwargs):
            result = commit(*args, **kwargs)
            if args[2] == ['hero']:
                saved.set()
                if not release.wait(2):raise AssertionError('first commit was not released')
            else:second_saved.set()
            return result
        def second():
            second_started.set()
            session.committed('real.mp4', ['rank'], output)
        with patch.object(session.store, 'mark_committed', side_effect=delayed), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(session.committed, 'real.mp4', ['hero'], output)
            try:
                self.assertTrue(saved.wait(1))
                other = pool.submit(second)
                self.assertTrue(second_started.wait(1))
                self.assertFalse(second_saved.wait(.1))
            finally:release.set()
            first.result();other.result()
        self.assertEqual([event['fields']['done'] for event in events], [1, 2])

    def test_both_damaged_raise_without_overwriting_or_guessing(self):
        job = self.create()
        path = Path(self.temp.name) / (job + '.json')
        path.write_text('{}', encoding='utf-8')
        with self.assertRaises(CorruptCheckpoint):
            self.store.load(job)
        self.assertEqual(path.read_text(encoding='utf-8'), '{}')

    def test_atomic_replace_failure_leaves_primary_recoverable(self):
        job = self.create()
        real_replace = os.replace
        path = Path(self.temp.name) / (job + '.json')
        def replace(source, target):
            if Path(target) == path:
                raise OSError('simulated failed atomic replace')
            return real_replace(source, target)
        with patch('hud_job_store.os.replace', side_effect=replace):
            with self.assertRaises(OSError):
                self.store.claim(job, 'clip-a', ['hero'])
        self.assertEqual(self.store.summary(job)['fields']['pending'], 2)

    def test_new_force_is_distinct_but_upgrade_clicks_reuse_unfinished(self):
        self.assertNotEqual(self.create(), self.create())
        first = self.create(kind='upgrade', scope='library')
        self.assertEqual(self.create(kind='upgrade', scope='library'), first)
        self.store.claim(first, 'clip-a', ['hero'])
        self.store.mark_committed(first, 'clip-a', ['hero'], receipt={'atomic': True})
        remaining = copy.deepcopy(self.clips)
        remaining[0]['fields'] = ['rank']
        self.assertEqual(self.store.create(remaining, self.registry, kind='upgrade', scope='library')['id'], first)
        new_registry = copy.deepcopy(self.registry)
        new_registry['rank'] = descriptor('rank', {'reader': 'reader-v2'})
        self.assertNotEqual(self.store.create(remaining, new_registry, kind='upgrade', scope='library')['id'], first)

    def test_concurrent_fields_commit_without_lost_updates(self):
        job = self.create()
        def worker(field):
            store = JobStore(self.temp.name)
            store.claim(job, 'clip-a', [field])
            store.mark_committed(job, 'clip-a', [field], receipt={'output': field})
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(worker, ['hero', 'rank']))
        self.assertEqual(self.store.summary(job)['fields']['done'], 2)
        self.assertEqual(self.store.summary(job)['status'], 'completed')

    def test_unclaimed_or_receiptless_fields_cannot_be_committed(self):
        job = self.create()
        with self.assertRaises(ValueError):
            self.store.mark_committed(job, 'clip-a', ['hero'], receipt={'output': 'test'})
        self.store.claim(job, 'clip-a', ['hero'])
        with self.assertRaises(ValueError):
            self.store.mark_committed(job, 'clip-a', ['hero'], receipt={})
        self.assertEqual(self.store.summary(job)['fields']['done'], 0)


if __name__ == '__main__':
    unittest.main()
