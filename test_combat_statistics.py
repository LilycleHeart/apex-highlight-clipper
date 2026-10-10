import unittest
from unittest.mock import patch
from combat_statistics import unique_toasts,reconciled_counts,parse_settlement,last_team_settlement,overlay_summaries
from combat_outcome_reader import parse_result_line
from outcome_reader import result_kind

class StatisticsTests(unittest.TestCase):
    def event(self,kind,target,time,frame,action=None):
        return dict(kind=kind,target_text=target,time=time,frame=frame,text=('助攻，消滅 ' if kind=='assist' else '已消滅 ' if kind=='elimination' else '擊倒 ')+target,
                    action=action or kind,confidence=.99,ownership='self')

    def test_same_prompt_many_frames_counts_once_and_two_targets_stay_separate(self):
        raw=[self.event('knock','NAGISA',t,str(i)) for i,t in enumerate([1,1.5,2])]
        raw += [self.event('knock','OTHER',t,str(i+3)) for i,t in enumerate([2.5,3])]
        self.assertEqual(len(unique_toasts(raw)),2)
        self.assertTrue(all(e['confirmed'] for e in unique_toasts(raw)))

    def test_assist_knock_then_elimination_same_target_is_one(self):
        a=self.event('assist','PLAYER',1,'a','knock');b=self.event('assist','PLAYER',10,'b','elimination')
        self.assertEqual(len(unique_toasts([a,b])),1)
        self.assertEqual(unique_toasts([a,b])[0]['action'],'elimination')

    def test_partial_names_use_continuous_prefix_not_false_extra_knocks(self):
        a=self.event('knock','',1,'a');b=self.event('knock','NAGISA',1.5,'b')
        for event in [a,b]:event['prefix_box']=[570,382,597,399]
        self.assertEqual(len(unique_toasts([a,b])),1)
        self.assertTrue(unique_toasts([a,b])[0]['confirmed'])

    def test_points_and_assist_ocr_variants_do_not_become_target_names(self):
        self.assertEqual(parse_result_line('擊倒 NAGISA+150合')['target_text'],'NAGISA')
        parsed=parse_result_line('助攻，擎倒 DAFT+1OO合')
        self.assertEqual((parsed['action'],parsed['target_text']),('knock','DAFT'))

    def endpoint(self):return {'baseline':{'kills':3,'assists':4,'damage':1250},'last_hud':{'kills':4,'assists':8,'damage':2280},'last_hud_update':{'kills':100}}
    def coverage(self):return {'checked_frames':10,'expected_frames':10,'ambiguous_frames':[],'calibrated_style_confirmed':True}

    def test_second_clip_two_assists_is_exact_two(self):
        endpoint={'baseline':{'kills':2,'assists':1,'damage':417},'last_hud':{'kills':3,'assists':3,'damage':732}}
        result=reconciled_counts(endpoint,[],self.coverage())
        self.assertEqual(result['counts']['assists'],2);self.assertFalse(result['partial']['assists'])

    def test_only_final_settlement_can_add_two_missed_kills(self):
        result=reconciled_counts(self.endpoint(),[],self.coverage(),{'totals':{'kills':6,'assists':7}})
        self.assertEqual(result['counts']['kills'],3);self.assertFalse(result['partial']['kills'])
        self.assertEqual(result['counts']['assists'],3)
        self.assertEqual(reconciled_counts(self.endpoint(),[],self.coverage())['counts']['kills'],1)

    def test_no_settlement_uses_confirmed_center_eliminations_without_faking_complete_counts(self):
        raw=[self.event('elimination',target,t,str(i)) for i,(target,t) in enumerate([('A',102),('A',102.5),('B',104),('B',104.5)])]
        result=reconciled_counts(self.endpoint(),unique_toasts(raw),self.coverage(),{'totals':None})
        self.assertEqual(result['counts']['kills'],3);self.assertTrue(result['partial']['kills'])
        self.assertIsNone(result['counts']['assists'])

    def test_non_winning_fight_never_reads_settlement(self):
        with patch('weapon_reader.new_engine',side_effect=AssertionError('普通交战不能查结算')):
            self.assertIsNone(last_team_settlement({'outcome_events':[]},'.',[{'start':0,'end':10}]))
        self.assertEqual(result_kind('你是 冠軍',True),'win')

    def test_settlement_reads_count_not_rp_and_accepts_mixed_chinese(self):
        def box(text,x,y,confidence=.99):return ([[x,y],[x+20,y],[x+20,y+10],[x,y+10]],text,confidence)
        values=parse_settlement([box('總戰門RP',0,0),box('擊殺数',0,20),box('6',100,20),box('132RP',140,20),box('助攻',0,40),box('7',100,40),box('154RP',140,40)])
        self.assertEqual(values,{'kills':6,'assists':7})

    def test_export_summary_uses_corrected_statistics_and_rejects_wrong_bounds(self):
        stats={'version':'test','segments':[{'start':1,'end':2,'counts':{'kills':3,'assists':2},'partial':{'kills':False},'notes':[]}]}
        result=overlay_summaries([{'kills':1}],[{'start':1,'end':2}],stats)
        self.assertEqual(result[0]['kills'],3)
        with self.assertRaises(ValueError):overlay_summaries([{}],[{'start':1,'end':3}],stats)

if __name__=='__main__':unittest.main()
