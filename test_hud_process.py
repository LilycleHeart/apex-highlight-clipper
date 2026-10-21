import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app_cancel import TaskStopped
from hud_enrichment import enrich_manifest_isolated,_run_hud_child,run_jobs


class Input(io.StringIO):
    def close(self):
        if not self.closed:self.payload=self.getvalue()
        super().close()


class Child:
    def __init__(self,code,output):self.code=code;self.stdin=Input();self.stdout=io.StringIO(output)
    def poll(self):return self.code
    def wait(self,timeout=None):return self.code


class HudProcessTests(unittest.TestCase):
    def test_multi_job_progress_is_global_and_activity_survives_child_protocol(self):
        request={'backend':'cpu','fields':['weapons'],'force':True,'jobs':[{'directory':'first','files':['a','b']},{'directory':'second','files':['c']}]}
        events=[]
        def child(payload,on_progress=None,on_activity=None,**options):
            self.assertTrue(payload['force'])
            # The controller hands the whole batch to one child; the child owns
            # global offsets and reports every file of both directories.
            self.assertEqual([len(job['files']) for job in payload['jobs']],[2,1])
            for index,file in enumerate(['a','b','c'],1):
                on_activity({'type':'hud-info-activity','index':index,'total':3,'file':file,'message':'识别武器','frames_done':1,'frames_total':3})
                on_progress(index,3,file)
            return {'type':'hud-info-done','updated':3,'errors':[],'total':3}
        with patch('hud_enrichment._run_hud_child',side_effect=child):result=run_jobs(request,emit=events.append)
        progress=[e for e in events if e['type']=='hud-info-progress'];activity=[e for e in events if e['type']=='hud-info-activity']
        self.assertEqual([e['index'] for e in progress],[1,2,3]);self.assertTrue(all(e['total']==3 for e in progress+activity))
        self.assertEqual([e['file'] for e in activity],['a','b','c']);self.assertEqual(result['updated'],3)
        child=Child(0,json.dumps(activity[0])+'\n'+json.dumps({'type':'hud-info-done','errors':[]})+'\n')
        forwarded=[]
        with patch('hud_enrichment.subprocess.Popen',return_value=child):_run_hud_child({'backend':'cpu'},on_activity=forwarded.append)
        self.assertEqual(forwarded,[activity[0]])

    def test_native_gpu_exit_retries_cpu_using_exported_clips_only(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'APEX_OCR_BACKEND':'dml'}):
            root=Path(tmp);video=root/'clip.mp4';video.write_bytes(b'exported')
            manifest={'outputs':[str(video)],'clips':[]};(root/'export.json').write_text(json.dumps(manifest),'utf-8')
            logs=[]
            children=[Child(3221225477,'Windows fatal exception: access violation\n'),Child(0,json.dumps({'type':'hud-info-done','errors':[]})+'\n')]
            with patch('hud_enrichment.subprocess.Popen',side_effect=children) as child:
                result=enrich_manifest_isolated(root,fields=['account'],on_log=logs.append,force=True)
                # 请求必须冻结，第二次重试不能回写第一次的后端记录。
                self.assertEqual(child.call_count,2)
                first,last=[json.loads(p.stdin.payload) for p in children]
                self.assertEqual(first['backend'],'dml');self.assertEqual(last['backend'],'cpu')
                self.assertTrue(first['force']);self.assertTrue(last['force'])
                self.assertEqual(last['jobs'][0]['files'],[str(video)])
            self.assertEqual(result,manifest);self.assertEqual(video.read_bytes(),b'exported')
            self.assertTrue(any('改用CPU' in text for text in logs))

    def test_stop_terminates_child_without_retrying_or_losing_stop_signal(self):
        class Process:
            pid=123
            def __init__(self):self.stdin=io.StringIO();self.stdout=io.StringIO('');self.killed=False;self.wait_timeouts=[]
            def poll(self):return 0 if self.killed else None
            def kill(self):self.killed=True
            def wait(self,timeout=None):
                self.wait_timeouts.append(timeout)
                if not self.killed:raise subprocess.TimeoutExpired('fixture',timeout)
                return 0
        proc=Process()
        def terminate_tree(command,**kwargs):
            self.assertEqual(command,['taskkill','/PID','123','/T','/F'])
            proc.kill()
        with patch('hud_enrichment.subprocess.Popen',return_value=proc),patch('hud_enrichment.subprocess.run',side_effect=terminate_tree),patch('hud_enrichment.check_cancel',side_effect=TaskStopped()):
            with self.assertRaises(TaskStopped):_run_hud_child({'backend':'cpu','jobs':[]})
        self.assertTrue(proc.killed)
        self.assertEqual(proc.wait_timeouts,[15,10,10])


if __name__=='__main__':unittest.main()
