import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from repair_cached_statistics import PreparedRepair,commit_repair,correction_key,prepare_repair


class ParallelRepairTests(unittest.TestCase):
    def fixture(self,root,index,value):
        directory=root/'metadata';directory.mkdir(exist_ok=True);original=directory/'statistics.json'
        if not original.exists():original.write_text(json.dumps({'segments':[{'start':0,'end':1},{'start':2,'end':3}]}),'utf-8')
        raw=original.read_bytes();report=json.loads(raw)
        for segment in report['segments']:segment['counts']={'damage':0}
        report['segments'][index]['counts']['damage']=value
        report['segments'][index]['native_repaired_fields']=['damage']
        report.update(version='fixture',counter_recipe='recipe',repair_signature=hashlib.sha256(raw+b'fixture'+b'recipe').hexdigest(),correction_context=str(directory.resolve()).replace('\\','/').lower())
        target=root/'data/recognition-corrections'/(correction_key(raw,directory)+'.json')
        return PreparedRepair(directory,hashlib.sha256(raw).hexdigest(),target,report,(index,))

    def test_two_prepared_clips_rebase_other_segments_instead_of_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Repair targets are built from resolved paths; match that form so an
            # 8.3 short-name temp directory does not look like a moved location.
            root=Path(tmp).resolve();first=self.fixture(root,0,100);second=self.fixture(root,1,200)
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'data')}):
                commit_repair(first);result=commit_repair(second)
            self.assertEqual([segment['counts']['damage'] for segment in result['segments']],[100,200])
            self.assertEqual(result['verification_mode'],'native-existing')
            self.assertEqual(first.report['segments'][1]['counts']['damage'],0)

    def test_changed_original_is_rejected_without_writing_a_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepared=self.fixture(root,0,100)
            (prepared.directory/'statistics.json').write_text('{"changed":true}','utf-8')
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'data')}),self.assertRaisesRegex(ValueError,'已变化'):
                commit_repair(prepared)
            self.assertFalse(prepared.target.exists())

    def test_media_changed_while_waiting_for_ordered_commit_is_rejected(self):
        from apex_clipper import fingerprint
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepared=self.fixture(root,0,100);video=root/'clip.mp4';video.write_bytes(b'before')
            prepared=replace(prepared,media_identities=(fingerprint(video),));video.write_bytes(b'changed')
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'data')}),self.assertRaisesRegex(ValueError,'成片.*变化'):
                commit_repair(prepared)
            self.assertFalse(prepared.target.exists())

    def test_prepare_uses_a_native_frame_scope_without_taking_the_write_lock(self):
        with patch('repair_cached_statistics._repair',return_value=object()) as compute,patch('repair_cached_statistics.correction_lock') as lock:
            prepare_repair({'directory':'fixture'})
            compute.assert_called_once_with({'directory':'fixture'},None,deferred=True);lock.assert_not_called()

    def test_nonforced_prepare_preserves_existing_partial_recheck_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepared=self.fixture(root,0,100);raw=(prepared.directory/'statistics.json').read_bytes()
            report=copy.deepcopy(prepared.report)
            for segment in report['segments']:
                segment.update(counts={'kills':None,'assists':None,'damage':None},partial={},repair_applied=True,repair_fields=['statistics'])
            prepared.target.parent.mkdir(parents=True);prepared.target.write_text(json.dumps(report),'utf-8')
            record={'directory':str(prepared.directory),'native':True,'fields':['statistics']}
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'data')}),patch('repair_cached_statistics.exported_clips',return_value=[]),patch('repair_cached_statistics._repair') as compute:
                prepare_repair(record)
            self.assertTrue(compute.call_args.args[0]['recheck_existing'])


if __name__=='__main__':unittest.main()
