import unittest
from planning_evidence import classify_seed_strength,focused_windows
from early_round_end import subtract_windows,terminal_idle_ranges,loading_title
from smart_scan import merge_windows

class FocusedPlanningTests(unittest.TestCase):
    def test_ocr_rebound_is_local_uncertainty_not_new_fight(self):
        rows=[{'time':t,'damage':v} for t,v in [(0,484),(2,464),(4,484),(6,600),(8,0),(10,20)]]
        seeds=[{'start':2,'end':4,'reason':'damage'},{'start':4,'end':6,'reason':'damage'},{'start':8,'end':10,'reason':'damage'}]
        self.assertEqual([s['reason'] for s in classify_seed_strength(rows,seeds)],['counter_rebound_or_uncertain','damage','damage'])

    def test_uncertainty_does_not_bridge_long_idle_but_keeps_local_evidence(self):
        seeds=[{'start':10,'end':12,'reason':'damage'},{'start':45,'end':47,'reason':'counter_rebound_or_uncertain'},
               {'start':80,'end':82,'reason':'damage'}]
        windows=focused_windows([],seeds,100,merge_windows)
        self.assertFalse(any(a<=30<=b for a,b in windows))
        self.assertTrue(any(a<=46<=b for a,b in windows))

    def test_true_long_ttk_chain_keeps_continuous_window(self):
        seeds=[{'start':10,'end':20,'reason':'damage'},{'start':54,'end':60,'reason':'ammo_change'}]
        self.assertIn([7,64.1],focused_windows([],seeds,100,merge_windows))

    def test_unknown_team_tail_not_excluded(self):
        self.assertEqual(terminal_idle_ranges([],[],100),[])
        self.assertEqual(terminal_idle_ranges([{'time':70,'inactive_view':False,'ammo':20}],[{'time':30}],100),[[36,64]])
        self.assertEqual(subtract_windows([[0,100]],[[36,64]]),[[0,36],[64,100]])
        self.assertEqual(terminal_idle_ranges([{'time':60,'inactive_view':True,'friend_spectate':True}],
                                             [{'time':30}],100),[[36,54]])

    def test_loading_title_is_specific(self):
        self.assertTrue(loading_title('積分賽 - 空投區'))
        self.assertFalse(loading_title('冠軍 我被擊倒了'))

    def test_loading_without_counter_reset_cannot_cut_reconnect(self):
        rows=[{'time':t,'damage':d,'ammo':20} for t,d in [(0,100),(2,100),(70,100),(72,140)]]
        self.assertEqual(terminal_idle_ranges(rows,[{'time':30,'kind':'loading'}],100),[])
        rows[-2]['damage']=0;rows[-1]['damage']=40
        self.assertEqual(terminal_idle_ranges(rows,[{'time':30,'kind':'loading'}],100),[[36,64]])

    def test_rejected_only_does_not_start_weapon_ocr(self):
        import json
        from unittest.mock import patch
        from apex_clipper import BASE
        from weapon_reader import enrich_weapon_labels
        profile=json.loads((BASE/'profile-ultrawide.json').read_text(encoding='utf-8'))
        cache={'fps':2,'rows':[{'time':10,'ammo':20},{'time':10.5,'ammo':18}]}
        with patch('weapon_reader.new_engine',side_effect=AssertionError('无保留片段不应加载枪名模型')):
            enrich_weapon_labels(cache,BASE,profile,'unused',segments=[])
        self.assertIn('weapon_label_signature',cache)

    def test_only_unstarted_uncached_same_rule_tasks_upgrade(self):
        from app_task import planner_for_item
        task={'smart_cache_version':'evidence-v3','result_filter_version':'own-center-result-v4'}
        self.assertEqual(planner_for_item(task,{},True,False),'focused-v6')
        self.assertEqual(planner_for_item(task,{},False,False),'evidence-v3')
        self.assertEqual(planner_for_item(task,{},True,True),'evidence-v3')
        self.assertEqual(planner_for_item({'smart_cache_version':'evidence-v3'},{},True,False),'evidence-v3')
        self.assertEqual(planner_for_item(task,{'smart_cache_version':'focused-v6'},False,True),'focused-v6')

if __name__=='__main__':unittest.main()
