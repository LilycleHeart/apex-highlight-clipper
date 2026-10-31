import copy
import unittest
from unittest.mock import patch
from combat_statistics import unique_toasts,reconciled_counts,parse_settlement,last_team_settlement,overlay_summaries
from combat_outcome_reader import parse_result_line
from combat_outcome_reader import restore_english_events
from outcome_reader import result_kind

class StatisticsTests(unittest.TestCase):
    def test_repeated_requests_for_one_decoded_pts_are_not_two_counter_frames(self):
        from combat_statistics import stable_value
        rows=[{'frame':'a','native_time':1.,'damage':2088},{'frame':'b','native_time':1.,'damage':2088}]
        self.assertIsNone(stable_value(rows,'damage'))
        rows.append({'frame':'c','native_time':1.5,'damage':2088})
        self.assertEqual(stable_value(rows,'damage'),2088)

    def test_unconfirmed_latest_counter_is_a_lower_bound_until_settlement_confirms_it(self):
        endpoint=self.endpoint();endpoint['unconfirmed_latest']={'kills':5}
        result=reconciled_counts(endpoint,[],self.coverage())
        self.assertTrue(result['partial']['kills'])
        confirmed=reconciled_counts(endpoint,[],self.coverage(),{'totals':{'kills':5,'assists':8}})
        self.assertEqual(confirmed['counts']['kills'],2);self.assertFalse(confirmed['partial']['kills'])

    def test_terminal_spectator_view_keeps_last_own_counters_as_lower_bounds(self):
        endpoint=self.endpoint();endpoint['excluded_terminal_view']=True
        result=reconciled_counts(endpoint,[],self.coverage())
        self.assertEqual(result['counts']['damage'],1030)
        self.assertTrue(all(result['partial'][key] for key in ['kills','assists','damage']))

    def test_missing_terminal_digit_is_a_lower_bound_without_invalidating_other_fields(self):
        endpoint=self.endpoint()
        endpoint['end_frames']=[{'native_time':time,**endpoint['last_hud']} for time in [10.,10.1]]
        endpoint['end_frames'].append({'native_time':10.2,'kills':4,'assists':8})
        result=reconciled_counts(endpoint,[],self.coverage())
        self.assertEqual(result['counts']['damage'],1030);self.assertTrue(result['partial']['damage'])
        self.assertFalse(result['partial']['kills']);self.assertFalse(result['partial']['assists'])
        self.assertTrue(any('片尾计分栏' in note for note in result['notes']))

    def test_smaller_late_read_cannot_make_the_earlier_larger_value_a_lower_bound(self):
        endpoint=self.endpoint();endpoint['baseline']['kills']=7;endpoint['last_hud']['kills']=18;endpoint['unconfirmed_latest']={'kills':8}
        result=reconciled_counts(endpoint,[],self.coverage())
        self.assertIsNone(result['counts']['kills']);self.assertTrue(result['partial']['kills'])

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

    def test_enemy_name_uses_repeated_spelling_instead_of_first_bad_ocr(self):
        raw=[self.event('knock',name,t,str(i)) for i,(name,t) in enumerate([('NAG1SA',1),('NAGISA',1.5),('NAGISA',2)])]
        self.assertEqual(unique_toasts(raw)[0]['target_text'],'NAGISA')
        uncertain=[self.event('knock',name,t,str(i)) for i,(name,t) in enumerate([('NAG1SA',1),('NAGISA',1.5)])]
        self.assertEqual(unique_toasts(uncertain)[0]['target_text'],'')

    def test_refined_target_is_not_replaced_by_raw_line_spelling(self):
        raw=[self.event('knock','PLAYER_BB63',time,str(i)) for i,time in enumerate([1,1.5])]
        for event in raw:event.update(target_text='PLAYER_8863',target_method='ctc_span_two_views',target_read_confidence=.995)
        result=unique_toasts(raw)
        self.assertEqual(len(result),1);self.assertTrue(result[0]['confirmed'])
        self.assertEqual(result[0]['target_text'],'PLAYER_8863')
        self.assertEqual(result[0]['text_confidence'],.995)

    def test_uncertain_target_hints_track_event_but_cannot_confirm_name(self):
        raw=[self.event('knock','PLAYER_HINT',time,str(i)) for i,time in enumerate([1,1.5])]
        for event in raw:event.update(target_method='ctc_span_two_views',target_read_confidence=0.)
        result=unique_toasts(raw)
        self.assertEqual(len(result),1);self.assertTrue(result[0]['confirmed'])
        self.assertEqual(result[0]['target_text'],'')

    def test_cached_english_line_restoration_keeps_verified_target_read(self):
        observations={}
        for i,time in enumerate([1.,1.5]):
            line={'text':'ASSIST.KNOCKEDDOWNPLAYERBB63+100','confidence':.97,'prefix_confidence':.97,
                'box':[100,200,400,220],'target_read':{'name':'PLAYER8863','confidence':.995,'method':'ctc_span_two_views'}}
            observations[i]={'time':time,'frame':str(i),'events':[],'lines':[line]}
        restore_english_events(observations)
        events=[event for item in observations.values() for event in item['events']]
        self.assertEqual(unique_toasts(events)[0]['target_text'],'PLAYER8863')

    def endpoint(self):return {'baseline':{'kills':3,'assists':4,'damage':1250},'last_hud':{'kills':4,'assists':8,'damage':2280},'last_hud_update':{'kills':100}}
    def coverage(self):return {'checked_frames':10,'expected_frames':10,'ambiguous_frames':[],'calibrated_style_confirmed':True,'reliable_absence':True}

    def test_second_clip_two_assists_is_exact_two(self):
        endpoint={'baseline':{'kills':2,'assists':1,'damage':417},'last_hud':{'kills':3,'assists':3,'damage':732}}
        result=reconciled_counts(endpoint,[],self.coverage())
        self.assertEqual(result['counts']['assists'],2);self.assertFalse(result['partial']['assists'])

    def test_hud_assist_delta_has_priority_over_three_separate_phase_toasts(self):
        events=[]
        for action,target,time in [('knock','FIRST',1),('elimination','FIRST',8),('knock','SECOND',11)]:
            event=self.event('assist',target,time,str(time),action)
            event.update(confirmed=True,native_action_status='confirmed')
            if target=='FIRST':event['native_action_pair']={'knock_time':1,'elimination_time':8}
            events.append(event)
        before=copy.deepcopy(events);endpoint=self.endpoint();endpoint['last_hud']['assists']=6
        result=reconciled_counts(endpoint,events,self.coverage())
        self.assertEqual(result['counts']['assists'],2);self.assertFalse(result['partial']['assists'])
        endpoint['baseline']['assists']=None;endpoint['last_hud']['assists']=None
        missing=reconciled_counts(endpoint,events,self.coverage())
        self.assertEqual(missing['counts']['assists'],1);self.assertTrue(missing['partial']['assists'])
        self.assertEqual(events,before)

    def test_native_pending_assist_action_never_falls_back_to_cached_elimination(self):
        endpoint=self.endpoint();endpoint['baseline']['assists']=None
        event={**self.event('assist','PLAYER',1,'a','elimination'),'confirmed':True}
        for status in [None,'','unconfirmed','unconfirmed_merged_track']:
            with self.subTest(status=status):
                pending={**event,'native_action_status':status}
                for settlement in [None,{'totals':None}]:
                    result=reconciled_counts(endpoint,[pending],self.coverage(),settlement)
                    self.assertIsNone(result['counts']['assists']);self.assertTrue(result['partial']['assists'])
        event.update(native_action_status='confirmed',action='knock')
        self.assertIsNone(reconciled_counts(endpoint,[event],self.coverage())['counts']['assists'])
        event.update(action='elimination',text='助攻，擊倒 PLAYER+100')
        self.assertEqual(reconciled_counts(endpoint,[event],self.coverage())['counts']['assists'],1)

    def test_legacy_assist_lower_bound_uses_complete_action_grammar_not_aggregate_or_nickname(self):
        endpoint=self.endpoint();endpoint['baseline']['assists']=None
        knock={**self.event('assist','ELIMINATED_PLAYER',1,'a','elimination'),
               'confirmed':True,'text':'ASSIST KNOCKED DOWN ELIMINATED_PLAYER+100'}
        unknown={**knock,'text':'助攻 PLAYER_ELIMINATED'}
        for event in [knock,unknown,{**knock,'confirmed':False}]:
            self.assertIsNone(reconciled_counts(endpoint,[event],self.coverage())['counts']['assists'])
        elimination={**knock,'action':'knock','text':'ASSIST ELIMINATED PLAYER'}
        self.assertEqual(reconciled_counts(endpoint,[elimination],self.coverage())['counts']['assists'],1)
        self.assertIsNone(reconciled_counts(endpoint,[{**elimination,'ownership':'other'}],self.coverage())['counts']['assists'])

    def test_legacy_merged_assist_cannot_use_eventual_action_when_saved_text_is_knock(self):
        first=self.event('assist','PLAYER',1,'a','knock');first['text']='助攻，擊倒 PLAYER+100'
        last=self.event('assist','PLAYER',8,'b','elimination');last['confidence']=.98
        events=unique_toasts([first,last]);self.assertEqual(events[0]['action'],'elimination')
        self.assertEqual(events[0]['text'],first['text'])
        endpoint=self.endpoint();endpoint['baseline']['assists']=None
        self.assertIsNone(reconciled_counts(endpoint,events,self.coverage())['counts']['assists'])
        events[0]['native_action_status']='confirmed'
        self.assertEqual(reconciled_counts(endpoint,events,self.coverage())['counts']['assists'],1)

    def test_unconfirmed_self_knock_prevents_complete_coverage_from_inventing_zero(self):
        pending={**self.event('knock','PLAYER',1,'a'),'confirmed':False}
        coverage={**self.coverage(),'reliable_absence':True};before=copy.deepcopy(pending)
        result=reconciled_counts(self.endpoint(),[pending],coverage)
        self.assertIsNone(result['counts']['knockdowns']);self.assertTrue(result['partial']['knockdowns'])
        confirmed={**self.event('knock','OTHER',2,'b'),'confirmed':True}
        result=reconciled_counts(self.endpoint(),[pending,confirmed],coverage)
        self.assertEqual(result['counts']['knockdowns'],1);self.assertTrue(result['partial']['knockdowns'])
        absent=reconciled_counts(self.endpoint(),[],coverage)
        self.assertEqual(absent['counts']['knockdowns'],0);self.assertFalse(absent['partial']['knockdowns'])
        other=reconciled_counts(self.endpoint(),[{**pending,'ownership':'other'}],coverage)
        self.assertEqual(other['counts']['knockdowns'],0);self.assertFalse(other['partial']['knockdowns'])
        self.assertEqual(pending,before)

    def test_unsettled_assist_suppression_requires_own_confirmed_elimination(self):
        assist={**self.event('assist','PLAYER',101,'a','elimination'),'confirmed':True,'native_action_status':'confirmed'}
        elimination={**self.event('elimination','PLAYER',102,'b'),'confirmed':True,'ownership':'other'}
        result=reconciled_counts(self.endpoint(),[assist,elimination],self.coverage(),{'totals':None})
        self.assertEqual(result['counts']['assists'],1);self.assertTrue(result['partial']['assists'])
        elimination['ownership']='self'
        self.assertIsNone(reconciled_counts(self.endpoint(),[assist,elimination],self.coverage(),{'totals':None})['counts']['assists'])

    def exported_endpoint(self):
        endpoint=self.endpoint()
        endpoint.update(native_counter_scope='exported_visible_delta',native_view_version='self-hud-view-v3',
                        native_numeric_method='numeric-three-model-v4',export_baseline_fields=['kills','assists','damage'])
        endpoint['baseline_frames']=[{'native_time':time,'native_verified':True,**endpoint['baseline']} for time in [.01,.05]]
        endpoint['end_frames']=[{'native_time':time,'native_verified':True,**endpoint['last_hud']} for time in [10.,10.04]]
        return endpoint

    def test_complete_native_export_delta_survives_missing_later_round_settlement(self):
        endpoint=self.exported_endpoint();extra={**self.event('elimination','PLAYER',104,'a'),'confirmed':True}
        before=copy.deepcopy(endpoint)
        result=reconciled_counts(endpoint,[extra],self.coverage(),{'totals':None})
        self.assertEqual(result['counts'],{'kills':1,'assists':4,'damage':1030,'knockdowns':0})
        self.assertTrue(all(not result['partial'][key] for key in ['kills','assists','damage']))
        self.assertEqual(endpoint,before)

    def test_export_delta_exception_requires_real_distinct_pts_and_complete_terminal_field(self):
        event={**self.event('assist','PLAYER',101,'a','elimination'),'confirmed':True,'native_action_status':'confirmed'}
        cases={}
        original=self.exported_endpoint();original['native_counter_scope']='original';cases['original_scope']=original
        missing=self.exported_endpoint();missing['baseline_frames']=[];cases['version_and_values_only']=missing
        duplicate=self.exported_endpoint();duplicate['end_frames'][1]['native_time']=10.;cases['same_decoded_pts']=duplicate
        pending=self.exported_endpoint();pending['unconfirmed_latest']={'assists':8};cases['pending_terminal_read']=pending
        hidden=self.exported_endpoint();hidden['end_frames'].append({'native_time':10.08,'native_verified':True,'kills':4,'damage':2280});cases['unreadable_terminal_assists']=hidden
        excluded=self.exported_endpoint();excluded['excluded_terminal_view']=True;cases['terminal_spectator']=excluded
        for reason,endpoint in cases.items():
            with self.subTest(reason=reason):
                result=reconciled_counts(endpoint,[event],self.coverage(),{'totals':None})
                self.assertEqual(result['counts']['assists'],1);self.assertTrue(result['partial']['assists'])
        mixed=reconciled_counts(hidden,[event],self.coverage(),{'totals':None})
        self.assertEqual(mixed['counts']['kills'],1);self.assertFalse(mixed['partial']['kills'])
        self.assertEqual(mixed['counts']['damage'],1030);self.assertFalse(mixed['partial']['damage'])

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

    def test_center_events_raise_only_partial_counter_bounds_without_adding_overlapping_evidence(self):
        events=unique_toasts([self.event(kind,target,time,str(index)) for index,(kind,target,time) in enumerate([
            ('elimination','FIRST',1.),('elimination','FIRST',1.5),('elimination','SECOND',4.),('elimination','SECOND',4.5),
            ('assist','THIRD',6.),('assist','THIRD',6.5),('assist','FOURTH',8.),('assist','FOURTH',8.5)])])
        endpoint=self.endpoint();endpoint['last_hud']['assists']=5
        endpoint['end_frames']=[{'native_time':10.,**endpoint['last_hud']},{'native_time':11.}]
        before=copy.deepcopy(events);result=reconciled_counts(endpoint,events,self.coverage())
        self.assertEqual((result['counts']['kills'],result['counts']['assists']),(2,2))
        self.assertTrue(result['partial']['kills']);self.assertTrue(result['partial']['assists'])
        endpoint['end_frames'].pop();complete=reconciled_counts(endpoint,events,self.coverage())
        self.assertEqual((complete['counts']['kills'],complete['counts']['assists']),(1,1))
        self.assertEqual(events,before)

    def test_missing_hud_center_fallback_is_not_added_again_for_unreadable_settlement(self):
        events=unique_toasts([self.event('elimination',target,time,str(index)) for index,(target,time) in enumerate([
            ('FIRST',102.),('FIRST',102.5),('SECOND',104.),('SECOND',104.5)])])
        endpoint=self.endpoint();endpoint['baseline']['kills']=None
        result=reconciled_counts(endpoint,events,self.coverage(),{'totals':None})
        self.assertEqual(result['counts']['kills'],2);self.assertTrue(result['partial']['kills'])

    def test_center_fallback_excludes_other_views_and_experience_does_not_become_damage(self):
        events=[]
        for kind in ['elimination','knock','assist']:
            event={**self.event(kind,'PLAYER+150',1.,kind),'confirmed':True,'ownership':'other'};events.append(event)
        endpoint={'baseline':{},'last_hud':{}}
        result=reconciled_counts(endpoint,events,{**self.coverage(),'reliable_absence':False})
        self.assertTrue(all(value is None for value in result['counts'].values()))
        events[1]['ownership']='self';own=reconciled_counts(endpoint,events,{**self.coverage(),'reliable_absence':False})
        self.assertEqual(own['counts']['knockdowns'],1);self.assertIsNone(own['counts']['damage'])

    def test_no_negative_coverage_or_zero_frames_cannot_claim_complete_knockdowns(self):
        for coverage in [{**self.coverage(),'reliable_absence':False},{**self.coverage(),'expected_frames':0,'checked_frames':0},
                         {**self.coverage(),'stopped_after_positive':True}]:
            result=reconciled_counts(self.endpoint(),[],coverage)
            self.assertIsNone(result['counts']['knockdowns']);self.assertTrue(result['partial']['knockdowns'])

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

    def test_start_reading_uses_earliest_confirmed_value_and_flags_lower_bounds(self):
        from combat_statistics import earliest_consistent
        rows=lambda values,first=.25:[{'frame':str(i),'time':first+i*.5,**({'damage':v} if v is not None else {})} for i,v in enumerate(values)]
        self.assertEqual(earliest_consistent(rows([481,461,461]),'damage',0),(461,False))  # 偏大的早期读数是误读
        self.assertEqual(earliest_consistent(rows([461,None,461]),'damage',0),(461,False))
        self.assertEqual(earliest_consistent(rows([100,150,150]),'damage',0),(150,True))   # 开头已有增量
        self.assertEqual(earliest_consistent(rows([300,300],first=20.),'damage',0),(300,True))  # 晚于段首才回到本人视角
        same=[{'frame':'a','time':1.,'native_time':1.,'damage':5},{'frame':'b','time':1.,'native_time':1.,'damage':5}]
        self.assertEqual(earliest_consistent(same,'damage',0),(None,False))

    def test_zero_window_follows_own_hidden_view_only(self):
        from combat_statistics import zero_window,probe_rows
        row=lambda t,**flags:{'frame':f'{t}','time':t,'counter_marker_score':flags.pop('score',.5),**flags}
        rows=[row(0,inactive_view=True),row(.5),row(1.),row(1.5,score=.9),row(2.)]
        self.assertEqual([r['time'] for r in zero_window(rows,0,10)],[.5,1.])
        # 观战、阵亡、大厅等非本人画面里不会造成伤害，跳过后继续看之后的本人画面。
        rows=[row(0),row(.5,inactive_view=True),row(1.)]
        self.assertEqual([r['time'] for r in zero_window(rows,0,10)],[0,1.])
        tail=[row(5.),row(6.),row(7.,inactive_view=True),row(8.,friend_spectate=True)]
        self.assertEqual([r['time'] for r in zero_window(tail,0,10,reverse=True)],[6.,5.])
        self.assertEqual(zero_window([row(0,round_ended=True),row(1.,score=.9)],0,10),[])
        self.assertEqual([r['time'] for r in zero_window([row(1.),row(2.,round_ended=True),row(3.)],0,10)],[1.])
        lobby=[row(float(t),inactive_view=t<40) for t in range(400)]
        window=zero_window(lobby,0,400)
        self.assertEqual((window[0]['time'],window[-1]['time']),(40.,340.))
        picked=probe_rows([row(t*.5) for t in range(40)])
        self.assertEqual([r['time'] for r in picked],[0,.5,1.,6.,11.,16.])
        late=[r['time'] for r in probe_rows(window)]
        self.assertTrue(all(b-a>=10 for a,b in zip(late,late[1:]) if a>=100))

    def test_hidden_counter_is_zero_only_with_squads_row_evidence(self):
        import tempfile
        from pathlib import Path
        from hud_layout import make_profile
        from combat_statistics import counter_endpoints
        rows=[{'frame':f'{i+1:06d}.jpg','time':i*.5+.25,'counter_marker_score':.5,'inactive_view':False} for i in range(40)]
        cache={'source':{'path':'missing.mp4'},'fps':2.,'rows':rows}
        evidence=[{'frame':rows[i]['frame'],'time':rows[i]['time'],'native_verified':False,'kills':0,'assists':0,'damage':0,'zero_evidence':{'method':'test'}} for i in (0,1)]
        calls=[]
        def zero(frames,profile,**options):
            calls.append(options);return evidence if len(calls)==1 and found else []
        with tempfile.TemporaryDirectory() as temporary:
            for found in [False,True]:
                calls.clear()
                with patch('squads_panel.zero_frames',side_effect=zero),patch('combat_statistics.counter_digit_reader',return_value=lambda images:([],0.)):
                    endpoint=counter_endpoints(cache,Path(temporary),[{'start':0.,'end':20.}],make_profile(2560,1080))[0]
                if not found:
                    # 录像开头、计分栏一直没出现，但没有小队数行证据：不再凭时间位置当作 0。
                    self.assertTrue(all(value is None for value in endpoint['baseline'].values()))
                    self.assertFalse(endpoint['initial_hidden_zero']);self.assertNotIn('zero_evidence',endpoint)
                else:
                    self.assertEqual(endpoint['baseline'],{'kills':0,'assists':0,'damage':0})
                    self.assertTrue(endpoint['initial_hidden_zero']);self.assertEqual(endpoint['zero_evidence']['start'],2)
                    self.assertEqual([row['time'] for row in endpoint['baseline_frames']],[.25,.75])
                self.assertEqual(calls[-1],{'latest':1.5})  # 段内一直没出现计分栏，段尾也要核对

    def test_lower_bound_start_and_zero_notes_reach_counts(self):
        endpoint=self.endpoint();endpoint['baseline_lower_bound_fields']=['damage'];endpoint['zero_evidence']={'start':0,'end':2}
        result=reconciled_counts(endpoint,[],self.coverage())
        self.assertEqual(result['counts']['damage'],1030);self.assertTrue(result['partial']['damage']);self.assertFalse(result['partial']['kills'])
        self.assertTrue(any('起点取之后' in note for note in result['notes']));self.assertTrue(any('段尾右上角' in note for note in result['notes']))

    def test_terminal_reading_lower_than_an_earlier_one_is_only_a_lower_bound(self):
        # 段尾两帧都读成 426，此前两帧是 428：计数不会减少，末值 426 只能当下限。
        import tempfile
        from pathlib import Path
        import cv2,numpy as np
        from hud_layout import make_profile
        from combat_statistics import counter_endpoints
        values=[0,0,0,0,428,428,426,426]
        with tempfile.TemporaryDirectory() as temporary:
            rows=[]
            for index,value in enumerate(values):
                name=f'{index+1:06d}.jpg';cv2.imwrite(str(Path(temporary)/name),np.full((40,40,3),index*20,np.uint8))
                rows.append({'frame':name,'time':index*5+1.,'counter_marker_score':.95,'inactive_view':False})
            cache={'source':{'path':'missing.mp4'},'fps':.2,'rows':rows}
            read=lambda images:([(str(values[round(float(image.mean())/20)]),1.) for image in images],0.)
            with patch('combat_statistics.counter_offset',return_value=((0,0),.95)),\
                 patch('stat_counter_fallback.CounterFallback.regions',side_effect=lambda image,profile,delta:{'damage':image}),\
                 patch('combat_statistics.counter_digit_reader',return_value=read):
                endpoint=counter_endpoints(cache,Path(temporary),[{'start':0.,'end':40.}],make_profile(2560,1080))[0]
        self.assertEqual(endpoint['last_hud']['damage'],426);self.assertEqual(endpoint['unconfirmed_latest'],{'damage':428})
        self.assertEqual(endpoint['terminal_regression_fields'],['damage'])
        result=reconciled_counts(endpoint,[],self.coverage())
        self.assertEqual(result['counts']['damage'],426);self.assertTrue(result['partial']['damage'])
        self.assertTrue(any('段尾较早读数大于末值' in note for note in result['notes']))

if __name__=='__main__':unittest.main()
