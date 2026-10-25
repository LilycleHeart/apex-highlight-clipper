import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apex_clipper import fingerprint, tool
from hud_enrichment import FIELDS, VERSION, enrich_manifest, field_version
import library_records


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), 'utf-8')


class LibraryRecordTests(unittest.TestCase):
    def task_fixture(self, root):
        """v2 布局：任务记录在数据目录，成片在输出目录。"""
        output = root / 'output'; videos = output / '任务 A'; videos.mkdir(parents=True)
        destination = root / 'data/tasks/a/items/1'; destination.mkdir(parents=True)
        clip = videos / '第1段 2杀.mp4'; clip.write_bytes(b'exported clip bytes')
        other = videos / '第2段 0杀.mp4'; other.write_bytes(b'another clip')
        identity = fingerprint(clip)
        info = {'version': VERSION, 'field_versions': {field: field_version(field) for field in FIELDS},
                'source_identity': identity, 'profile_source_identity': dict(identity),
                'field_source_identities': {field: dict(identity) for field in FIELDS},
                'requested_fields': FIELDS, 'field_status': {field: 'confirmed' for field in FIELDS},
                'account': {'name': 'SAMPLE', 'confidence': .99}, 'teammates': [], 'hero': {'id': 'loba', 'name': '罗芭'},
                'weapons': [{'id': 'r99', 'name': 'R99'}], 'rank': {'tier': 'gold', 'division': 'II'}}
        manifest = {'source': {'path': str(root / 'recording.mp4')}, 'metadata_directory': str(destination),
                    'video_directory': str(videos), 'outputs': [str(clip), str(other)],
                    'clips': [{'output': str(clip), 'segment': {'start': 0, 'end': 10}, 'summary': {'kills': 2},
                               'output_identity': identity, 'recognition': {'hud_info': info}},
                              {'output': str(other), 'segment': {'start': 20, 'end': 30}, 'summary': {'kills': 0},
                               'output_identity': fingerprint(other), 'recognition': {}}]}
        write(destination / 'export.json', manifest)
        task = {'version': 2, 'directory': str(root / 'data/tasks/a'), 'items': [{
            'source': str(root / 'recording.mp4'), 'destination': str(destination), 'video_directory': str(videos),
            'status': 'complete', 'record': {'status': 'complete', 'directory': str(destination),
                                             'outputs': [str(clip), str(other)],
                                             'output_identities': [identity, fingerprint(other)]}}]}
        write(root / 'data/tasks/a/task.json', task)
        return root / 'data/tasks/a/task.json', destination, clip, other

    def test_moved_clip_keeps_hud_information_and_resume_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); task_path, destination, clip, other = self.task_fixture(root)
            sorted_dir = root / 'output/整理/高光'; sorted_dir.mkdir(parents=True)
            moved = sorted_dir / clip.name; shutil.move(str(clip), str(moved))
            result = library_records.relocate({'tasks': [str(task_path)],
                                               'moves': [{'from': str(clip), 'to': str(moved), 'size': moved.stat().st_size}]})
            self.assertEqual(len(result['changed']), 2)
            manifest = json.loads((destination / 'export.json').read_text('utf-8'))
            self.assertEqual(manifest['clips'][0]['output'], str(moved))
            self.assertEqual(manifest['clips'][0]['output_identity'], fingerprint(moved))
            self.assertEqual(manifest['relocated_outputs'], [str(moved)])
            self.assertEqual(manifest['clips'][0]['moved_from'], [str(clip)])
            self.assertNotIn('moved_from', manifest['clips'][1])
            self.assertEqual(manifest['clips'][1]['output'], str(other))
            self.assertEqual(manifest['source'], {'path': str(root / 'recording.mp4')})
            self.assertTrue((destination / 'export.json.before-relocation').is_file())
            hud = manifest['clips'][0]['recognition']['hud_info']
            self.assertEqual(hud['field_source_identities']['hero'], fingerprint(moved))
            self.assertEqual(hud['profile_source_identity'], fingerprint(moved))
            # 识别信息不因位置改变失效：补缺模式不再重读已确认字段。
            with patch('hud_enrichment.recognize_video') as read:
                enriched = enrich_manifest(destination, [str(moved)], FIELDS)
            read.assert_not_called()
            self.assertEqual(enriched['clips'][0]['recognition']['hud_info']['hero']['id'], 'loba')
            # 续接时不把已搬走的成片当成缺失而重新导出。
            from app_task import outputs_intact
            record = json.loads(task_path.read_text('utf-8'))['items'][0]['record']
            self.assertTrue(outputs_intact(record))
            self.assertEqual(record['relocated_outputs'], [str(moved)])

    def test_unverified_moves_are_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); task_path, destination, clip, other = self.task_fixture(root)
            before = (destination / 'export.json').read_bytes()
            copy = root / 'output/copy.mp4'; shutil.copy2(clip, copy)
            with self.assertRaisesRegex(ValueError, '原位置'):
                library_records.relocate({'tasks': [str(task_path)], 'moves': [{'from': str(clip), 'to': str(copy)}]})
            moved = root / 'output/moved.mp4'; shutil.move(str(clip), str(moved))
            with self.assertRaisesRegex(ValueError, '大小'):
                library_records.relocate({'tasks': [str(task_path)], 'moves': [{'from': str(clip), 'to': str(moved), 'size': 1}]})
            with self.assertRaisesRegex(ValueError, '同一个片段'):
                library_records.relocate({'tasks': [str(task_path)], 'moves': [{'from': str(clip), 'to': str(moved)},
                                                                               {'from': str(root / 'gone.mp4'), 'to': str(moved)}]})
            self.assertEqual((destination / 'export.json').read_bytes(), before)

    def test_moved_legacy_task_folder_is_rebased(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); old = root / 'old/任务 B'; videos = old / '录像1'; videos.mkdir(parents=True)
            clip = videos / 'clip.mp4'; clip.write_bytes(b'clip')
            write(videos / 'export.json', {'outputs': [str(clip)], 'clips': [{'output': str(clip), 'output_identity': fingerprint(clip)}],
                                           'source': {'path': str(root / 'recording.mp4')}})
            write(old / 'task.json', {'version': 1, 'directory': str(old), 'items': [{'source': str(root / 'recording.mp4'),
                  'destination': str(videos), 'record': {'directory': str(videos), 'outputs': [str(clip)]}}]})
            new_parent = root / 'new'; new_parent.mkdir(); shutil.move(str(old), str(new_parent))
            moved = new_parent / '任务 B'
            library_records.rebase({'tasks': [str(moved / 'task.json')]})
            task = json.loads((moved / 'task.json').read_text('utf-8'))
            self.assertEqual(task['directory'], str(moved))
            self.assertEqual(task['items'][0]['record']['outputs'], [str(moved / '录像1/clip.mp4')])
            self.assertEqual(task['items'][0]['source'], str(root / 'recording.mp4'))
            manifest = json.loads((moved / '录像1/export.json').read_text('utf-8'))
            self.assertEqual(manifest['clips'][0]['output'], str(moved / '录像1/clip.mp4'))

    @unittest.skipUnless(shutil.which('ffmpeg') or os.environ.get('APEX_FFMPEG_DIR'), '需要 ffmpeg 生成样例')
    def test_imported_clip_supports_visual_fields_and_removal_keeps_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); clip = root / '自己剪的/精彩.mkv'; clip.parent.mkdir()
            subprocess.run([tool('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i', 'color=c=gray:s=64x36:d=1', '-c:v', 'mpeg4', str(clip)], check=True)
            result = library_records.import_clips({'data_root': str(root / 'data'), 'files': [str(clip), str(clip), str(root / 'missing.mp4')]})
            self.assertEqual(result['added'], [str(clip)]); self.assertEqual(len(result['rejected']), 1)
            directory = Path(result['manifest']).parent
            fresh = {'profile': {}, 'checked_frames': 3, 'frame_times': [1, 2, 3], 'name_observations': [],
                     'field_status': {'hero': 'confirmed'}, 'hero': {'id': 'loba', 'name': '罗芭'}}
            with patch('hud_enrichment.recognize_video', return_value=fresh):
                enriched = enrich_manifest(directory, [str(clip)], ['hero'])
            self.assertEqual(enriched['clips'][0]['recognition']['hud_info']['hero']['id'], 'loba')
            with self.assertRaisesRegex(ValueError, '画面'):
                enrich_manifest(directory, [str(clip)], ['statistics'])
            library_records.remove_imported({'data_root': str(root / 'data'), 'files': [str(clip)]})
            self.assertEqual(json.loads(Path(result['manifest']).read_text('utf-8'))['clips'], [])
            self.assertTrue(clip.is_file())


if __name__ == '__main__':
    unittest.main()
