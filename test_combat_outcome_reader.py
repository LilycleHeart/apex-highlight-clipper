import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from apex_clipper import fingerprint
from app_cancel import TaskStopped
from combat_outcome_reader import parse_result_line,is_known_dialogue,group_lines,inspect_combat_outcomes,filter_combat_outcomes,_inspect_low_frequency

class ResultGrammarTests(unittest.TestCase):
    def test_three_positive_kinds_and_missing_player_name(self):
        for text,kind in [('擊倒 NIING+150合','knock'),('已消滅','elimination'),('已消滅 X','elimination'),('已消滅 �口□?','elimination'),('已消滅 A:B!','elimination'),('擊倒 X','knock'),('助攻，擊倒 秋火火火 +100','assist'),('助攻，消滅 秋火火火','assist')]:
            self.assertEqual(parse_result_line(text)['kind'],kind)

    def test_dialogue_damage_and_squad_wipe_are_not_own_results(self):
        for text in ['狂瑪吉：喔，要命，我被擊倒了。','蘿芭：我被擎倒了','我被擊倒了！','造成153點傷害','小隊抹殺+100（包子）']:
            self.assertIsNone(parse_result_line(text))
        self.assertTrue(is_known_dialogue('蘿芭：我被擎倒了'))

    def test_far_apart_subtitle_and_result_do_not_merge(self):
        def part(text,left,right): return {'text':text,'confidence':.99,'left':left,'right':right,'top':382,'bottom':398}
        lines=group_lines([part('蘿芭：我被擊倒了',400,520),part('已消滅',614,654),part('NIING',660,690)])
        self.assertEqual(len(lines),2); self.assertIsNotNone(parse_result_line(lines[1]['text']))

class ResultResumeTests(unittest.TestCase):
    def test_low_fps_upgrades_only_unconfirmed_candidate_on_separate_time_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'source.mp4'; source.write_bytes(b'fixture')
            cache={'source':fingerprint(source),'fps':1,'rows':[{'frame':'000011.jpg','time':10.5}]}
            native={'signature':'native','decisions':[{'candidate_index':0,'status':'kept'},{'candidate_index':1,'status':'review'}],
                'stats':{'checked_new_frames':3,'ocr_new_frames':1,'extra_sample_frames':0}}
            upgraded={'signature':'upgraded','decisions':[{'candidate_index':0,'status':'rejected'}],
                'stats':{'checked_new_frames':4,'ocr_new_frames':1,'extra_sample_frames':0}}
            candidates=[{'start':0,'end':2},{'start':10,'end':12}]
            with patch('combat_outcome_reader.inspect_combat_outcomes',side_effect=[native,upgraded]) as inspect,patch('combat_outcome_reader.probe',return_value=({},{})),patch('resume_media.sample_with_resume') as sample:
                result=_inspect_low_frequency(cache,root/'native-samples',candidates,{},root/'result.json')
                self.assertEqual(sample.call_args.kwargs['frame_ranges'],[[21,24]])
                self.assertEqual(sample.call_args.args[2],2)
                promoted=inspect.call_args_list[1].args[0]
                self.assertEqual(promoted['rows'],[])
                self.assertEqual(promoted['locale_reference_rows'],cache['rows'])
                self.assertEqual([d['status'] for d in result['decisions']],['kept','rejected'])

    def test_stop_resume_skips_confirmed_clip_and_only_reads_pending_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'source.mp4'; source.write_bytes(b'fixture'); samples=root/'samples'; samples.mkdir()
            for i in range(1,9):
                cv2.imwrite(str(samples/f'{i:06d}.jpg'),np.full((540,1280,3),i,dtype=np.uint8))
            cache={'source':fingerprint(source),'fps':2,'rows':[{'frame':f'{i:06d}.jpg','time':(i-.5)/2,'inactive_view':False} for i in range(1,9)]}
            profile={'prefix_templates':[],'reference_size':[2560,1080],'toast_roi':[860,680,1700,832],
                'calibration':{'minimum_fps':2,'negative_decision_enabled':True,'require_traditional_ui':False}}
            candidates=[{'start':0,'end':2},{'start':2,'end':4}]; calls=[]
            def recognize(image,*args,**kwargs):
                n=int(image[0,0,0]); calls.append(n)
                if n==5 and len(calls)==2: raise TaskStopped()
                event={'kind':'knock','text':'擊倒 X','target_text':'X','confidence':.99,'box':[580,382,650,398]}
                return {'events':[event] if n==1 else [],'lines':[],'ambiguous_lines':[],'known_dialogue':[]}
            with patch('combat_outcome_reader.PrefixGate.inspect',return_value=[{'kind':'knock','score':.8,'box':[583,382,610,399]}]),patch('combat_outcome_reader.new_engine',return_value=object()),patch('combat_outcome_reader.recognize_frame',side_effect=recognize):
                with self.assertRaises(TaskStopped): inspect_combat_outcomes(cache,samples,candidates,profile,root/'result.json')
                report=inspect_combat_outcomes(cache,samples,candidates,profile,root/'result.json')
                self.assertEqual(calls.count(1),1)
                self.assertEqual([d['status'] for d in report['decisions']],['kept','rejected'])
                self.assertTrue(report['decisions'][0]['coverage']['stopped_after_positive'])
                again=inspect_combat_outcomes(cache,samples,candidates,profile,root/'result.json')
                self.assertEqual(again,report)

    def test_filter_preserves_downed_tail_and_routes_uncertain_to_review(self):
        candidates=[{'start':414.75,'end':504.25,'protected_reasons':['friend_team_continuation']},{'start':10,'end':20},{'start':30,'end':40}]
        report={'decisions':[{'candidate_index':i,'status':status,'reason':'fixture'} for i,status in enumerate(['kept','rejected','review'])]}
        kept,rejected,review=filter_combat_outcomes(candidates,report)
        self.assertEqual(kept[0]['end'],504.25); self.assertEqual(len(rejected),1); self.assertEqual(len(review),1)

if __name__=='__main__': unittest.main()
