import io
import json
import os
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
    def wait(self):return self.code


class HudProcessTests(unittest.TestCase):
    def test_multi_job_progress_is_global_and_activity_survives_child_protocol(self):
        request={'backend':'cpu','fields':['weapons'],'force':True,'jobs':[{'directory':'first','files':['a','b']},{'directory':'second','files':['c']}]}
        events=[]
        def enrich(directory,files,fields,on_progress,*,force,on_activity):
            self.assertTrue(force)
            for index,file in enumerate(files,1):
                on_activity({'type':'hud-info-activity','index':index,'total':len(files),'file':file,'message':'识别武器','frames_done':1,'frames_total':3})
                on_progress(index,len(files),file)
        with patch('hud_enrichment.enrich_manifest_isolated',side_effect=enrich):result=run_jobs(request,emit=events.append)
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
            def __init__(self):self.stdin=io.StringIO();self.stdout=io.StringIO('');self.killed=False
            def poll(self):return 0 if self.killed else None
            def kill(self):self.killed=True
            def wait(self):return 0
        proc=Process()
        with patch('hud_enrichment.subprocess.Popen',return_value=proc),patch('hud_enrichment.check_cancel',side_effect=TaskStopped()):
            with self.assertRaises(TaskStopped):_run_hud_child({'backend':'cpu','jobs':[]})
        self.assertTrue(proc.killed)


if __name__=='__main__':unittest.main()
