import base64
import math
import unittest
from apex_clipper import align_segments, ammo_number, detect_events, downed_intervals, segments_from_events, segment_summary, informative_filename, classify_combat_candidates

ICON=base64.b64encode(bytes([0b10101010]*336)).decode()
OTHER=base64.b64encode(bytes([0b01010101]*336)).decode()

def row(t, ammo, icon=ICON, damage=0, kills=0, inactive=False):
    return {'time':t,'ammo':ammo,'weapon_icon':icon,'damage':damage,'kills':kills,'inactive_view':inactive}

class SegmentationTests(unittest.TestCase):
    def test_mid_round_opening_counter_is_not_credited_as_new_kills_or_damage(self):
        events=detect_events([row(0,28,damage=900,kills=4),row(.5,24,damage=900,kills=4),
                              row(1,20,damage=950,kills=4),row(1.5,20,damage=950,kills=4)])
        self.assertFalse(any(e['kind']=='kill' for e in events))
        self.assertEqual(sum(e['after']-e['before'] for e in events if e['kind']=='hit'),50)

    def test_new_round_first_kill_equal_to_last_round_is_credited_after_gameover(self):
        rows=[row(0,20,damage=150,kills=1),row(.5,20,damage=150,kills=1),
              row(5,None,damage=None,kills=None,inactive=True),
              row(30,20,damage=None,kills=None),row(30.5,15,damage=150,kills=1),
              row(31,10,damage=150,kills=1),row(31.5,10,damage=150,kills=1)]
        rows[2]['round_ended']=True
        events=detect_events(rows)
        kills=[e for e in events if e['kind']=='kill']
        self.assertEqual(sum(e['after']-(e['before'] or 0) for e in kills),1)

    def test_inventory_gap_is_not_a_new_round(self):
        rows=[row(0,20,damage=150,kills=1),row(.5,20,damage=150,kills=1),
              row(5,None,damage=None,kills=None,inactive=True),row(30,20,damage=150,kills=1),
              row(30.5,15,damage=150,kills=1),row(31,10,damage=150,kills=1)]
        self.assertFalse(any(e['kind']=='kill' for e in detect_events(rows)))

    def test_sparse_fire_with_only_one_17_damage_update_needs_review(self):
        events=[{'time':t,'kind':'shoot'} for t in [318,319,337,338,339,349,350]]
        events.append({'time':341,'kind':'hit','before':330,'after':347})
        confirmed,review=classify_combat_candidates(events,[{'start':308,'end':365}])
        self.assertEqual(confirmed,[])
        self.assertEqual(review[0]['combat_evidence']['hit_updates'],1)

    def test_zero_kill_with_repeated_hits_is_kept(self):
        events=[{'time':100,'kind':'hit','before':0,'after':17},
                {'time':103,'kind':'hit','before':17,'after':34}]
        confirmed,review=classify_combat_candidates(events,[{'start':90,'end':118}])
        self.assertEqual(len(confirmed),1)
        self.assertEqual(review,[])

    def test_downed_without_kill_or_hits_is_still_kept(self):
        confirmed,review=classify_combat_candidates([], [{'start':90,'end':140,
                                                        'protected_reasons':['downed_until_terminal']}])
        self.assertEqual(len(confirmed),1)
        self.assertEqual(review,[])

    def test_distant_isolated_hit_updates_do_not_count_as_continuous_exchange(self):
        events=[{'time':100,'kind':'hit','before':0,'after':17},
                {'time':130,'kind':'hit','before':17,'after':34}]
        confirmed,review=classify_combat_candidates(events,[{'start':90,'end':145}])
        self.assertEqual(confirmed,[])
        self.assertEqual(len(review),1)

    def test_filename_stats_use_this_fight_increments_not_total_score(self):
        events=[{'time':10,'kind':'hit','before':330,'after':347},
                {'time':11,'kind':'shoot','weapon':'死敌'},
                {'time':30,'kind':'kill','before':2,'after':4},
                {'time':31,'kind':'hit','before':347,'after':759},
                {'time':32,'kind':'shoot','weapon':'CAR'}]
        a=segment_summary(events,{'start':5,'end':20})
        b=segment_summary(events,{'start':25,'end':40})
        self.assertEqual((a['kills'],a['damage'],a['weapons']),(0,17,['死敌']))
        self.assertEqual((b['kills'],b['damage'],b['weapons']),(2,412,['CAR']))
        self.assertEqual(informative_filename('Replay 2026-10-07 20-55-10.mp4',2,a),
                         '2026年10月7日 20点55分 第2段 0杀 死敌 17伤.mp4')

    def test_downed_revived_and_downed_again_stays_until_squad_wipe(self):
        rows=[{'time':t/2,'downed':(464<=t/2<=481 or 488<=t/2<=501),
               'inactive_view':502<=t/2} for t in range(920,1010)]
        protected=downed_intervals(rows,548)
        self.assertEqual(len(protected),1)
        self.assertEqual(protected[0]['terminal_time'],502)
        result=segments_from_events([{'time':424},{'time':434},{'time':455},{'time':463}],548,
                                    protected_intervals=protected)
        self.assertEqual(result[0]['end'],504)

    def test_recovered_player_does_not_extend_to_unrelated_later_wipe(self):
        rows=[{'time':t/2,'downed':100<=t/2<=110,'inactive_view':t/2>=180}
              for t in range(190,380)]
        protected=downed_intervals(rows,200)
        self.assertEqual(protected[0]['end'],125)
        self.assertIsNone(protected[0]['terminal_time'])

    def test_one_false_downed_frame_and_spectator_shield_are_ignored(self):
        rows=[{'time':t,'downed':t==5,'inactive_view':False} for t in range(10)]
        self.assertEqual(downed_intervals(rows,20),[])
        rows=[{'time':t/2,'downed':True,'inactive_view':True} for t in range(10)]
        self.assertEqual(downed_intervals(rows,20),[])

    def test_downed_extension_does_not_restore_previous_idle_gap(self):
        protected=[{'start':463,'end':504,'last_downed':501,'reason':'downed_until_terminal'}]
        events=[{'time':t} for t in [318,337,350,424,434,455,463]]
        result=segments_from_events(events,548,protected_intervals=protected)
        self.assertEqual([(s['start'],s['end']) for s in result],[(308,365),(414,504)])

    def test_default_keeps_24_second_pull_but_splits_74_second_idle(self):
        result=segments_from_events([{'time':t} for t in [170.25,177.25,201.25,209.75,318.75,350.25,424.75,434.25,442.75,455.75,463.75]],548.46)
        self.assertEqual([(s['start'],s['end']) for s in result],
                         [(160.25,224.75),(308.75,365.25),(414.75,478.75)])

    def test_long_pull_is_kept_and_duration_has_no_cap(self):
        events=[{'time':t} for t in [100,145,200,270,310,430]]
        result=segments_from_events(events,500,gap=75,pre=25,post=40)
        self.assertEqual([(s['start'],s['end']) for s in result],[(75,350),(405,470)])

    def test_buffers_and_keyframes_do_not_duplicate_time(self):
        result=align_segments([{'start':1.1,'end':3.1},{'start':3.9,'end':5.5}], [0,2,4,6,8],8)
        self.assertEqual([(s['start'],s['end']) for s in result],[(0,6)])

    def test_empty_has_no_clip(self):
        self.assertEqual(segments_from_events([],500),[])

    def test_invalid_segment_fails(self):
        with self.assertRaises(ValueError): align_segments([{'start':float('nan'),'end':3}],[0,2],10)
        with self.assertRaises(ValueError): segments_from_events([],500,gap=-1)

    def test_ammo_glyph_is_only_corrected_at_sufficient_confidence(self):
        self.assertEqual(ammo_number('2日',.78),20)
        self.assertIsNone(ammo_number('2日',.50))

    def test_weapon_switch_does_not_count_as_shooting(self):
        self.assertEqual(detect_events([row(0,28),row(.5,20,OTHER),row(1,20,OTHER)]),[])

    def test_true_fire_is_detected(self):
        events=detect_events([row(0,28),row(.5,23),row(1,19),row(1.5,19)])
        self.assertEqual([e['kind'] for e in events],['shoot','shoot'])

    def test_single_frame_counter_misread_is_rejected(self):
        events=detect_events([row(0,28,damage=330),row(.5,28,damage=330),
                              row(1,28,damage=880),row(1.5,28,damage=330),row(2,28,damage=330)])
        self.assertEqual(events,[])

    def test_spectator_is_excluded(self):
        self.assertEqual(detect_events([row(0,28,inactive=True),row(.5,20,inactive=True),row(1,10,inactive=True)]),[])

if __name__=='__main__': unittest.main()
