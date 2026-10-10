import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app_task import open_task,save_task,outputs_intact,task_lock
from resume_io import RowJournal
from apex_clipper import BASE,fingerprint

class JournalTests(unittest.TestCase):
    def test_uncommitted_and_torn_tail_is_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'rows.jsonl'; log=RowJournal(path,'source1')
            log.append([{'frame':1},{'frame':2}])
            with path.open('ab') as stream: stream.write(b'{"frame":3}\n{"frame":')
            recovered=RowJournal(path,'source1')
            self.assertEqual(recovered.rows,[{'frame':1},{'frame':2}])
            recovered.append([{'frame':3}]); self.assertEqual(len(RowJournal(path,'source1').rows),3)

    def test_corrupt_committed_row_rewinds_to_valid_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'rows.jsonl'; log=RowJournal(path,'source1'); log.append([{'frame':1},{'frame':2}])
            path.write_bytes(b'{"frame":1}\nwrong\n')
            self.assertEqual(RowJournal(path,'source1').rows,[{'frame':1}])

    def test_changed_signature_does_not_reuse_old_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'rows.jsonl'; log=RowJournal(path,'old'); log.append([{'frame':1}])
            self.assertEqual(RowJournal(path,'new').rows,[])
            self.assertTrue(list(Path(temp).glob('*.previous-*')))

class TaskTests(unittest.TestCase):
    def test_new_task_rejects_half_fps_but_old_record_can_resume(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'APEX_DISABLE_LAST_TASK':'1'}):
            source=Path(temp)/'video.mp4'; source.write_bytes(b'fixture')
            request={'files':[str(source)],'output':temp,'backend':'cpu','fps':.5}
            with self.assertRaisesRegex(ValueError,'1'): open_task(request)
            path,task,_,options=open_task({**request,'fps':1})
            self.assertEqual(options['fps'],1)
            task['request']['fps']=.5; task.pop('result_filter_version'); task.pop('smart_cache_version'); save_task(path,task)
            _,_,_,options=open_task({'resume_task':str(path),'fps':2})
            self.assertEqual(options['fps'],.5)

    def test_resume_uses_same_directory_and_original_edit_options(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'APEX_DISABLE_LAST_TASK':'1'}):
            source=Path(temp)/'video.mp4'; source.write_bytes(b'fixture')
            path,task,request,options=open_task({'files':[str(source)],'output':temp,'backend':'cpu','gap':25,'delete_source':True})
            save_task(path,task)
            resumed,again,request,options=open_task({'resume_task':str(path),'backend':'dml','gpu_load':'low','gap':99,'delete_source':False})
            self.assertEqual(resumed,path); self.assertEqual(options['gap'],25)
            self.assertTrue(options['delete_source']); self.assertEqual(request['backend'],'dml')
            self.assertEqual(again['smart_cache_version'],'indexed-v2')
            self.assertEqual(again['result_filter_version'],'own-center-result-v4')

    def test_old_task_keeps_old_smart_cache_namespace(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'APEX_DISABLE_LAST_TASK':'1'}):
            source=Path(temp)/'video.mp4'; source.write_bytes(b'fixture')
            path,task,_,_=open_task({'files':[str(source)],'output':temp,'backend':'cpu','scan_mode':'smart'})
            task.pop('smart_cache_version'); task.pop('result_filter_version'); save_task(path,task)
            _,again,_,_=open_task({'resume_task':str(path),'smart_cache_version':'evidence-v3'})
            self.assertEqual(again.get('smart_cache_version','smart-v2'),'smart-v2')
            self.assertNotIn('result_filter_version',again)

    def test_completed_outputs_can_be_skipped_after_source_is_gone(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'clip.mp4'; output.write_bytes(b'clip')
            record={'status':'complete','source':str(Path(temp)/'missing.mp4'),'outputs':[str(output)],
                'output_identities':[fingerprint(output)],'directory':temp}
            self.assertTrue(outputs_intact(record))
            output.write_bytes(b'changed output')
            self.assertFalse(outputs_intact(record))

    def test_second_process_cannot_take_the_same_task_lock(self):
        with tempfile.TemporaryDirectory() as temp,task_lock(temp),self.assertRaises(RuntimeError):
            with task_lock(temp): pass

if __name__=='__main__': unittest.main()
