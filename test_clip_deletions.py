import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apex_clipper import fingerprint, align_segments
from app_task import outputs_intact
from clip_deletions import _removed
from resume_media import digest, export_with_resume


class ClipDeletionTests(unittest.TestCase):
    def tearDown(self):_removed.cache_clear()

    def test_intentional_deletion_is_intact_but_unexpected_missing_output_is_not(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();clip=root/'clip.mp4';clip.write_bytes(b'clip')
            record={'status':'complete','outputs':[str(clip)],'output_identities':[fingerprint(clip)]}
            ledger=root/'clip-deletions.json';ledger.write_text(json.dumps({'version':1,'files':[str(clip)]}),encoding='utf-8')
            with patch.dict(os.environ,{'APEX_CLIP_DELETIONS':str(ledger)}):
                self.assertTrue(outputs_intact(record));clip.unlink();self.assertTrue(outputs_intact(record))
                missing=root/'other.mp4';self.assertFalse(outputs_intact({**record,'outputs':[str(missing)]}))
                clip.write_bytes(b'new');self.assertFalse(outputs_intact(record))

    def test_resume_does_not_regenerate_deleted_clip_or_shift_remaining_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();source=root/'source.mp4';source.write_bytes(b'source');output=root/'videos';output.mkdir();meta=root/'metadata';meta.mkdir()
            targets=[output/'1.mp4',output/'2.mp4'];targets[1].write_bytes(b'clip')
            segments=[{'start':0,'end':1},{'start':4,'end':5}];keys=[0,2,4,6];aligned=align_segments(segments,keys,8);summaries=[{},{}]
            clips=[{'output':str(file),'segment':segment,'summary':{},'metadata':{'format':{'duration':'2'}},'output_identity':fingerprint(file) if file.exists() else {}} for file,segment in zip(targets,aligned)]
            state={'signature':digest({'source':fingerprint(source),'segments':aligned,'targets':[str(file) for file in targets],'summaries':summaries}),'clips':clips,'commands':[]}
            (meta/'export-checkpoint.json').write_text(json.dumps(state),encoding='utf-8');ledger=root/'clip-deletions.json';ledger.write_text(json.dumps({'version':1,'files':[str(targets[0])]}),encoding='utf-8')
            with patch.dict(os.environ,{'APEX_CLIP_DELETIONS':str(ledger)}),patch('apex_clipper.probe',return_value=({'format':{'duration':'8'}},{})),patch('apex_clipper.keyframes',return_value=keys),patch('apex_clipper.segment_summary',return_value={}),patch('apex_clipper.informative_filename',side_effect=lambda source,index,summary:f'{index}.mp4'),patch('apex_clipper.run') as run:
                result=export_with_resume(source,segments,output,metadata_dir=meta)
            self.assertEqual(result,[targets[1]]);run.assert_not_called();self.assertFalse(targets[0].exists())
            manifest=json.loads((meta/'export.json').read_text(encoding='utf-8'));self.assertEqual(manifest['outputs'],[str(targets[1])]);self.assertEqual(manifest['clips'][0]['segment']['start'],4)
