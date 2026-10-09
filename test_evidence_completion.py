import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from apex_clipper import fingerprint,write_json
from evidence_completion import missing_ranges,merge_rows,complete_missing
from adaptive_evidence import evidence_windows,decode_policy
from smart_scan import merge_windows
from smart_scan import smart_read
from app_cancel import TaskStopped

def row(i): return {'frame':f'{i:06d}.jpg','time':(i-.5)/2,'ammo':i,'damage':i}

class EvidenceCompletionTests(unittest.TestCase):
    def test_low_gpu_decoder_uses_bounded_cpu_only_for_supported_setup(self):
        with patch('adaptive_evidence.os.cpu_count',return_value=16),patch('gpu_load.get_gpu_policy',return_value={'name':'low'}):
            self.assertEqual(decode_policy({'codec_name':'h264','pix_fmt':'yuv420p'},True),(False,4,'cpu4_low_gpu'))
            self.assertEqual(decode_policy({'codec_name':'h264','pix_fmt':'yuvj420p'},True),(False,4,'cpu4_low_gpu'))
            self.assertEqual(decode_policy({'codec_name':'hevc','pix_fmt':'yuv420p'},True),(True,None,'cuda'))
        with patch('adaptive_evidence.os.cpu_count',return_value=8),patch('gpu_load.get_gpu_policy',return_value={'name':'low'}):
            self.assertEqual(decode_policy({'codec_name':'h264','pix_fmt':'yuv420p'},True),(True,None,'cuda'))
    def test_disjoint_ranges_and_absolute_time_validation(self):
        self.assertEqual(missing_ranges(10,[row(i) for i in [1,2,5,6,10]],2),[[3,4],[7,9]])
        with self.assertRaises(ValueError): missing_ranges(10,[row(1),row(1)],2)
        with self.assertRaises(ValueError): missing_ranges(10,[dict(row(1),time=0)],2)

    def test_merge_deduplicates_and_preserves_enrichment(self):
        existing=[dict(row(2),current_weapon={'id':'car'},round_ended=True)]
        merged=merge_rows(existing,[row(1),row(2),row(3)],3,2)
        self.assertEqual(len(merged),3)
        self.assertEqual(merged[1]['current_weapon'],{'id':'car'})
        self.assertTrue(merged[1]['round_ended'])

    def test_interrupted_gap_fill_keeps_original_and_resume_only_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'source.mp4'; source.write_bytes(b'fixture')
            samples=root/'original'; (samples/'hud').mkdir(parents=True)
            existing=[dict(row(1),current_weapon={'id':'car'}),row(4)]
            for r in existing:
                for prefix in [samples,samples/'hud']: (prefix/r['frame']).write_bytes(b'old')
            output=root/'hud.json'; cache={'source':fingerprint(source),'fps':2,'rows':existing,'outcome_signature':'old','weapon_label_signature':'old'}
            write_json(output,cache); original=output.read_bytes(); attempts=[]
            def sample(source,out,fps,cuda,frame_ranges):
                attempts.append(frame_ranges)
                if len(attempts)==1: raise TaskStopped()
                (out/'hud').mkdir(parents=True,exist_ok=True)
                for i in [2,3]:
                    for prefix in [out,out/'hud']: (prefix/row(i)['frame']).write_bytes(b'new')
            with patch('evidence_completion.probe',return_value=({'format':{'duration':'2'}},{})),patch('evidence_completion.sample_with_resume',side_effect=sample),patch('evidence_completion.read_hud',return_value=[row(2),row(3)]) as reader:
                with self.assertRaises(TaskStopped): complete_missing(source,root,samples,{},2,output)
                self.assertEqual(output.read_bytes(),original)
                result,folder=complete_missing(source,root,samples,{},2,output)
                self.assertEqual(attempts,[[[2,3]],[[2,3]]])
                self.assertEqual(len(result['rows']),4)
                self.assertEqual(result['rows'][0]['current_weapon'],{'id':'car'})
                self.assertNotIn('outcome_signature',result)
                # 模拟主调用已更新hud而尚未提交smart plan：完成标记仍可直接恢复。
                write_json(output,result)
                again,_=complete_missing(source,root,folder,{},2,output)
                self.assertEqual(again,result); self.assertEqual(reader.call_count,1)

    def test_planner_keeps_head_and_long_ttk_bridge(self):
        seeds=[{'start':140,'end':196,'reason':'damage'},{'start':233,'end':243,'reason':'damage'}]
        windows=evidence_windows([],seeds,360,merge_windows,35)
        self.assertEqual(windows,[[0,1.5],[137,246]])

    def test_downed_to_spectating_keeps_possible_brief_friend_banner(self):
        rows=[{'time':t,'downed':t==70,'inactive_view':74<=t<230,'ammo':20 if t>=230 else None} for t in range(70,240,2)]
        windows=evidence_windows(rows,[{'start':68,'end':70,'reason':'team_or_downed'}],300,merge_windows)
        self.assertTrue(any(a<=82.75 and b>=230 for a,b in windows))

    def test_smart_audit_failure_commits_before_gap_fill_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'source.mp4'; source.write_bytes(b'fixture')
            output=root/'hud.json'; coarse={'rows':[dict(row(1),inactive_view=False,downed=False)],'numeric_frames':1}
            def reader(samples,profile,fps,path,**kwargs):
                cache={'source':fingerprint(source),'fps':fps,'rows':[row(1)],'outcome_events':[]}
                write_json(path,cache); return cache['rows']
            with patch('smart_scan.probe',return_value=({'format':{'duration':'30'}},{})),patch('smart_scan.coarse_scan',return_value=coarse),patch('smart_scan.refine_coarse',return_value=coarse),patch('smart_scan.sample_with_resume') as sample,patch('smart_scan.read_hud',side_effect=reader),patch('smart_scan.enrich_outcomes',side_effect=lambda c,*a,**k:c),patch('smart_scan.audit_counters',return_value={'passed':False}),patch('evidence_completion.complete_missing',side_effect=TaskStopped()) as complete:
                with self.assertRaises(TaskStopped): smart_read(source,root,root/'samples',{},2,output)
                plan=json.loads((root/'smart-plan.json').read_text(encoding='utf-8'))
                self.assertTrue(plan['need_full_fallback']); self.assertEqual(plan['strategy'],'evidence-v3')
                sample.reset_mock()
                complete.side_effect=None; complete.return_value=({'rows':[row(1)],'evidence_completion':{'reused_frames':1,'added_frames':59}},root/'gap-fill/samples')
                smart_read(source,root,root/'samples',{},2,output)
                self.assertEqual(sample.call_count,0)

if __name__=='__main__': unittest.main()
