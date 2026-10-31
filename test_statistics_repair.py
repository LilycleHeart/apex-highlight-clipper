import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import multiprocessing
from unittest.mock import patch
from apex_clipper import fingerprint
from repair_cached_statistics import repair,correction_key,correction_lock,early_export_baseline_fields
from hud_digit_reader import METHOD


def hold_correction_lock(path,ready,release):
    with correction_lock(path):
        ready.set();release.wait(10)


class StatisticsRepairTests(unittest.TestCase):

    def test_hidden_terminal_hud_recovers_only_a_lower_bound(self):
        from repair_cached_statistics import exported_endpoint
        from combat_statistics import reconciled_counts
        fields=['kills','assists','damage']
        baseline=dict.fromkeys(fields,0);baseline['damage']=100
        empty={'baseline':baseline,'last_hud':dict.fromkeys(fields),'last_hud_update':dict.fromkeys(fields),
               'unconfirmed_latest':{},'baseline_frames':[{'time':t,'native_time':t,'native_verified':True,**baseline} for t in [.02,.06]],
               'end_frames':[{'time':t,'native_time':t,'native_verified':True} for t in [9.5,9.96]]}
        prior=copy.deepcopy(empty);prior['last_hud']={'kills':None,'assists':None,'damage':150}
        prior['end_frames']=[{'time':t,'native_time':t,'native_verified':True,'damage':150} for t in [8.42,8.5]]
        source=Path('exported.mp4')
        with patch('repair_cached_statistics.exported_view',return_value=(source,{'path':str(source)},0.,10.,{})),patch('apex_clipper.fingerprint',return_value={}),patch('repair_cached_statistics.last_counter_time',return_value=None),patch('combat_statistics.counter_endpoints',side_effect=[[empty],[prior]]) as read:
            endpoint=exported_endpoint([],{'start':100.,'end':110.},{})
        result=reconciled_counts(endpoint,[],{'checked_frames':0,'expected_frames':0,'ambiguous_frames':[]})
        self.assertEqual(read.call_count,2)
        self.assertEqual(result['counts']['damage'],50)
        self.assertTrue(result['partial']['damage'])
        self.assertTrue(any('片尾计分栏未完整读取' in note for note in result['notes']))
        self.assertAlmostEqual(endpoint['end_frames'][-1]['time'],109.96)

    def terminal_fixture(self):
        fields=['kills','assists','damage']
        baseline={'kills':2,'assists':4,'damage':923}
        frames=lambda times,values:[{'time':t,'native_time':t,'native_verified':True,'marker_score':.9,**values} for t in times]
        empty={'baseline':dict(baseline),'last_hud':dict.fromkeys(fields),'last_hud_update':dict.fromkeys(fields),'unconfirmed_latest':{},
               'baseline_frames':frames([0.,.04,.08],baseline),'end_frames':[{'time':t,'native_time':t,'native_verified':False,'excluded_view':True} for t in [95.5,95.84]]}
        def check(values,unconfirmed,times):
            result=copy.deepcopy(empty);result['last_hud']={**dict.fromkeys(fields),**values};result['unconfirmed_latest']=unconfirmed
            result['last_hud_update']=dict.fromkeys(fields,times[0]);result['end_frames']=frames(times,values);return result
        return empty,check

    def test_terminal_lookback_reads_the_last_own_counter_and_waits_out_a_counter_roll(self):
        # 阵亡前伤害数字正在滚动：最后一帧本人画面只确认了击杀和助攻，伤害往前再找一个稳定读数，较近的未确认值保留。
        from repair_cached_statistics import exported_endpoint
        from combat_statistics import reconciled_counts
        empty,check=self.terminal_fixture()
        rolling=check({'kills':3,'assists':7},{'damage':1565},[91.8,91.88])
        steady=check({'kills':3,'assists':7,'damage':1532},{},[91.5,91.58])
        source=Path('exported.mp4')
        with patch('repair_cached_statistics.exported_view',return_value=(source,{'path':str(source)},0.,95.88,{})),patch('apex_clipper.fingerprint',return_value={}),\
             patch('repair_cached_statistics.last_counter_time',return_value=91.88),patch('combat_statistics.counter_endpoints',side_effect=[[empty],[rolling],[steady]]) as read:
            endpoint=exported_endpoint([],{'start':0.,'end':95.88},{})
        self.assertEqual(read.call_count,3)
        self.assertEqual([round(row['time'],2) for row in read.call_args_list[1].args[0]['rows']],[91.8,91.88])
        self.assertEqual([round(row['time'],2) for row in read.call_args_list[2].args[0]['rows']],[91.5,91.58])
        self.assertEqual(endpoint['last_hud'],{'kills':3,'assists':7,'damage':1532})
        self.assertEqual(endpoint['unconfirmed_latest'],{'damage':1565});self.assertTrue(endpoint['terminal_hud_hidden'])
        self.assertTrue(endpoint['end_frames'][-1].get('excluded_view'))
        result=reconciled_counts(endpoint,[],{'checked_frames':0,'expected_frames':0,'ambiguous_frames':[]})
        self.assertEqual((result['counts']['kills'],result['counts']['damage']),(1,609));self.assertTrue(result['partial']['damage'])

    def test_terminal_lookback_does_not_chase_fields_that_were_never_read(self):
        from repair_cached_statistics import exported_endpoint,lookback_moments
        empty,check=self.terminal_fixture()
        source=Path('exported.mp4')
        with patch('repair_cached_statistics.exported_view',return_value=(source,{'path':str(source)},0.,95.88,{})),patch('apex_clipper.fingerprint',return_value={}),\
             patch('repair_cached_statistics.last_counter_time',return_value=91.88),patch('combat_statistics.counter_endpoints',side_effect=[[empty],[check({'damage':1689},{},[91.8,91.88])]]) as read:
            endpoint=exported_endpoint([],{'start':0.,'end':95.88},{})
        self.assertEqual(read.call_count,2);self.assertEqual(endpoint['last_hud'],{'kills':None,'assists':None,'damage':1689})
        # 片尾这几秒都找不到本人计分图标时，仍按原来的固定距离回看。
        self.assertEqual([round(95.88-t,2) for t in lookback_moments(None,0.,95.88)],[1.5,3.,6.,12.,24.,48.])
        self.assertEqual([round(t,2) for t in lookback_moments(91.88,0.,95.88)][:6],[91.88,91.58,91.28,90.88,90.38,89.38])

    def test_stable_lead_run_ignores_fading_counter_reads(self):
        from repair_cached_statistics import stable_lead_run
        rows=lambda pairs:[{'native_time':t,'native_verified':True,'damage':v} for t,v in pairs]
        # 计分栏淡入时 771 连续两帧读成 71：要三帧、0.6 秒以上的同一读数才采用。
        self.assertEqual(stable_lead_run(rows([(.12,71),(.2,71),(.3,None),(.6,771),(.8,None),(1.,771),(1.3,771)]),'damage')[0],771)
        self.assertEqual(stable_lead_run(rows([(1.2,218),(1.4,218),(2.2,218)]),'damage')[0],218)
        self.assertEqual(stable_lead_run(rows([(.12,71),(.2,71),(.3,71)]),'damage'),(None,[]))
        # 计数只增不减：比之前读数小的一段不能当起点。
        self.assertEqual(stable_lead_run(rows([(.2,900),(.3,900),(.5,90),(.8,90),(1.2,90),(1.5,900),(2.,900),(2.4,900)]),'damage')[0],900)
        self.assertEqual(stable_lead_run(rows([(.2,5),(.4,5),(.6,5)])+[{'native_time':1.,'native_verified':False,'damage':5}],'damage'),(None,[]))
        value,run=stable_lead_run(rows([(2.4,6),(3.3,6),(4.,6),(13.,189)]),'damage');self.assertEqual((value,len(run)),(6,3))

    def test_exported_lead_baseline_is_a_lower_bound_start_only_for_missing_fields(self):
        from repair_cached_statistics import exported_lead_baseline,native_verified_fields
        from combat_statistics import reconciled_counts
        lead=[{'frame':f'native:export:{t:.5f}','time':t,'native_time':t,'native_verified':True,'marker_score':.95,'kills':1,'assists':5,**({'damage':v} if v else {})}
              for t,v in [(.12,71),(.2,71),(.4,None),(.6,771),(1.,771),(1.3,771)]]
        def endpoint():
            return {'baseline':{'kills':1,'assists':5,'damage':None},'last_hud':{'kills':1,'assists':5,'damage':868},'unconfirmed_latest':{},
                    'baseline_frames':[{'time':t,'native_time':t,'native_verified':True,'marker_score':.95,'kills':1,'assists':5} for t in [0.,.04,.09]],
                    'end_frames':[{'time':t,'native_time':t,'native_verified':True,'kills':1,'assists':5,'damage':868} for t in [24.5,25.]],
                    'export_baseline_fields':['kills','assists'],'native_view_version':'self-hud-view-v3','native_numeric_method':METHOD,'native_counter_scope':'exported_visible_delta'}
        current=endpoint()
        with patch('apex_clipper.fingerprint',return_value={}),patch('combat_statistics.counter_endpoints',return_value=[{'baseline_frames':lead}]) as read:
            exported_lead_baseline(current,Path('clip.mp4'),0.,29.,{},['damage'])
        self.assertEqual(read.call_args.kwargs['lead_rows'],len(read.call_args.args[0]['rows']))
        self.assertEqual(current['baseline']['damage'],771);self.assertEqual(current['baseline_lower_bound_fields'],['damage'])
        self.assertEqual(current['export_baseline_fields'],['kills','assists','damage'])
        self.assertIn('damage',native_verified_fields(current))
        result=reconciled_counts(current,[],{'checked_frames':0,'expected_frames':0,'ambiguous_frames':[]})
        self.assertEqual(result['counts']['damage'],97);self.assertTrue(result['partial']['damage']);self.assertFalse(result['partial']['kills'])
        # 导出时已有统计的字段不在 fields 里：不读成片开头，原记录照旧沿用。
        untouched=endpoint()
        with patch('combat_statistics.counter_endpoints',side_effect=AssertionError('no lead read')):
            exported_lead_baseline(untouched,Path('clip.mp4'),0.,29.,{},[])
        self.assertIsNone(untouched['baseline']['damage'])

    def test_weapon_only_repair_preserves_counters_and_maps_local_event_time(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,original,_=self.fixture(root)
            report=json.loads(original.read_text('utf-8'));segment=report['segments'][0]
            segment.update(start=100.,end=120.,events=[{'kind':'knock','action':'knock','time':105.,'last_seen':105.5,'ownership':'self','confirmed':True}])
            original.write_text(json.dumps(report),'utf-8');before=copy.deepcopy(segment)
            source=root/'source.mp4';identity={'path':str(source),'size':source.stat().st_size,'mtime_ms':source.stat().st_mtime_ns//1000000}
            def observed(source,events,profile,**kwargs):
                self.assertAlmostEqual(events[0]['time'],5.04)
                event=copy.deepcopy(events[0]);event['weapon_context']={'event':{key:event[key] for key in ['kind','action','time']},'source':identity,'status':'observed'}
                return [event]
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('combat_statistics.counter_endpoints',side_effect=AssertionError('weapon context must not read counters')),patch('repair_cached_statistics.exported_view',return_value=(source,identity,.04,20.,{})),patch('event_weapon_reader.recheck_event_weapons',side_effect=observed):
                fixed=repair({**record,'fields':['event_weapons']})['segments'][0]
            self.assertEqual(fixed['counts'],before['counts']);self.assertEqual(fixed['partial'],before['partial'])
            self.assertEqual(fixed['events'][0]['time'],105.)
            self.assertEqual(fixed['events'][0]['last_seen'],105.5)
            self.assertEqual(fixed['events'][0]['weapon_context']['event']['time'],105.)
            self.assertAlmostEqual(fixed['events'][0]['weapon_context']['event']['source_time'],5.04)

    def test_center_only_lower_bound_recomputes_without_filling_zero(self):
        for total in [2,0]:
            with self.subTest(total=total),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);record,original,fresh=self.fixture(root)
                report=json.loads(original.read_text('utf-8'));segment=report['segments'][0]
                segment['counts']['kills']=3
                segment['events']=[{'kind':'elimination','action':'elimination','time':float(i+1),'confirmed':True,'ownership':'self'} for i in range(total)]
                original.write_text(json.dumps(report),'utf-8')
                with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('combat_statistics.counter_endpoints',return_value=[fresh]):
                    fixed=repair({**record,'native':True,'recheck_existing':False})['segments'][0]
                self.assertEqual(fixed['counts']['kills'],total or None)
                self.assertTrue(fixed['partial']['kills'])
                self.assertIn('kills',fixed['center_recomputed_fields'])
                self.assertEqual(fixed['counts']['damage'],2076)

    def test_action_only_pending_keeps_complete_neighbor_context(self):
        from repair_cached_statistics import recheck_event_names,needs_fields,opponent_needs_review
        from combat_outcome_reader import PARSER_VERSION
        from target_name_reader import name_recipe
        pending={'kind':'assist','time':1.,'native_name_status':'confirmed','native_name_version':PARSER_VERSION,'native_name_recipe':name_recipe()}
        neighbor={**pending,'time':1.5,'native_action_status':'confirmed','native_action_version':PARSER_VERSION}
        self.assertTrue(opponent_needs_review(pending));self.assertFalse(opponent_needs_review(neighbor))
        self.assertFalse(opponent_needs_review({**pending,'kind':'knock'}))
        self.assertFalse(opponent_needs_review({**pending,'kind':'elimination'}))
        self.assertTrue(needs_fields({'events':[pending]},['opponents']))
        self.assertFalse(needs_fields({'events':[neighbor]},['opponents']))
        fresh={**pending,'native_action_status':'confirmed','native_action_version':PARSER_VERSION}
        events=[pending,neighbor]
        identity={'path':str(Path('recorded.mp4').resolve()),'size':7,'mtime_ns':123000000}
        with patch('apex_clipper.fingerprint',return_value=identity),patch('combat_outcome_reader.native_target_names',return_value=[fresh]) as reader:
            result=recheck_event_names(Path('recorded.mp4'),events,None,False,None)
        self.assertEqual([event['time'] for event in reader.call_args.args[1]],[pending['time']])
        self.assertEqual(reader.call_args.kwargs['context_events'],events)
        self.assertEqual(result[0]['native_action_status'],'confirmed');self.assertIs(result[1],neighbor)
        self.assertEqual(result[0]['native_name_source'],{'path':identity['path'],'size':7,'mtime_ms':123})

    def test_candidate_completion_uses_fresh_phase_and_full_context_without_reclassifying_other_events(self):
        from repair_cached_statistics import recheck_event_names,opponent_needs_review
        from combat_outcome_reader import PARSER_VERSION
        from target_name_reader import name_recipe
        candidate={'kind':'knock','time':1.,'confirmed':False,'ownership':'self','native_name_status':'confirmed','native_name_version':PARSER_VERSION,'native_name_recipe':name_recipe()}
        neighbor={**candidate,'time':2.,'confirmed':True}
        self.assertTrue(opponent_needs_review(candidate))
        identity={'path':str(Path('unused.mp4').resolve()),'size':7,'mtime_ns':123000000}
        with patch('apex_clipper.fingerprint',return_value=identity),patch('combat_outcome_reader.native_target_names',side_effect=lambda source,events,**kwargs:events),patch('combat_candidate_completion.complete_candidates',side_effect=lambda source,events,**kwargs:[{**events[0],'confirmed':True,'native_event_status':'confirmed'}]) as complete:
            result=recheck_event_names(Path('unused.mp4'),[candidate,neighbor],None,False,None)
        context=complete.call_args.kwargs['context_events']
        self.assertEqual([event['time'] for event in context],[1.,2.]);self.assertFalse(context[0]['confirmed'])
        self.assertEqual(context[0]['native_name_source']['path'],identity['path'])
        self.assertTrue(result[0]['confirmed']);self.assertFalse(candidate['confirmed']);self.assertIs(result[1],neighbor)

    def test_name_recipe_change_rechecks_a_confirmed_name_and_withdraws_stale_evidence(self):
        from repair_cached_statistics import recheck_event_names,opponent_needs_review
        from combat_outcome_reader import PARSER_VERSION
        old={'kind':'knock','time':1.,'confirmed':True,'ownership':'self','native_name_status':'confirmed','native_name_version':PARSER_VERSION,
            'native_name_recipe':'old-helper','native_name_evidence':[{'name':'OLDNAME','confidence':.99}],'target_text':'OLDNAME'}
        identity={'path':str(Path('unused.mp4').resolve()),'size':7,'mtime_ns':123000000}
        with patch('target_name_reader.name_recipe',return_value='current-helper'),patch('apex_clipper.fingerprint',return_value=identity),patch('combat_outcome_reader.native_target_names',side_effect=lambda source,events,**kwargs:events) as reader:
            self.assertTrue(opponent_needs_review(old))
            result=recheck_event_names(Path('unused.mp4'),[old],None,False,None)[0]
            self.assertEqual(result['native_name_status'],'unconfirmed');self.assertEqual(result['native_name_evidence'],[])
            self.assertEqual(result['native_name_recipe'],'current-helper');reader.assert_called_once()
            reader.reset_mock()
            current={**old,'native_name_recipe':'current-helper'}
            self.assertFalse(opponent_needs_review(current))
            self.assertIs(recheck_event_names(Path('unused.mp4'),[current],None,False,None)[0],current)
            reader.assert_not_called()
        self.assertEqual(old['native_name_status'],'confirmed');self.assertEqual(len(old['native_name_evidence']),1)

    def test_explicit_native_retry_cannot_keep_a_prior_name_when_no_new_frames_are_read(self):
        from repair_cached_statistics import recheck_event_names
        from combat_outcome_reader import PARSER_VERSION
        old={'kind':'knock','time':1.,'confirmed':True,'native_name_status':'confirmed','native_name_version':PARSER_VERSION,'target_text':'RAW_OLD'}
        identity={'path':str(Path('unused.mp4').resolve()),'size':7,'mtime_ns':123000000}
        with patch('apex_clipper.fingerprint',return_value=identity),patch('combat_outcome_reader.native_target_names',side_effect=lambda source,events,**kwargs:events):
            result=recheck_event_names(Path('unused.mp4'),[old],None,True,None)
        self.assertEqual(result[0]['native_name_status'],'unconfirmed');self.assertEqual(result[0]['target_text'],'RAW_OLD')
        self.assertEqual(old['native_name_status'],'confirmed')

    def test_names_and_classification_cannot_be_combined_across_a_media_change(self):
        from repair_cached_statistics import recheck_event_names
        old={'kind':'knock','time':1.,'confirmed':True}
        identity={'path':str(Path('unused.mp4').resolve()),'size':7,'mtime_ns':123000000}
        with patch('apex_clipper.fingerprint',side_effect=[identity,{**identity,'size':8}]),patch('combat_outcome_reader.native_target_names',side_effect=lambda source,events,**kwargs:events):
            with self.assertRaisesRegex(ValueError,'不能组合新旧画面证据'):
                recheck_event_names(Path('unused.mp4'),[old],None,True,None)

    def test_two_native_reads_of_a_counter_regression_do_not_certify_a_delta(self):
        from repair_cached_statistics import native_verified_fields
        endpoint={'native_view_version':'self-hud-view-v3','native_numeric_method':METHOD,'baseline':{'damage':329},'last_hud':{'damage':70},'baseline_frames':[{'native_time':time,'native_verified':True,'damage':329} for time in [.1,.2]],'end_frames':[{'native_time':time,'native_verified':True,'damage':70} for time in [10.,10.1]]}
        self.assertNotIn('damage',native_verified_fields(endpoint))

    def test_unreadable_first_frame_does_not_hide_an_early_verified_baseline(self):
        endpoint={'baseline':{'damage':225},'baseline_frames':[{'native_time':.02,'native_verified':True},*({'native_time':t,'native_verified':True,'damage':225} for t in [.06,.10])]}
        self.assertEqual(early_export_baseline_fields(endpoint,.02),['damage'])

    def test_later_majority_cannot_replace_a_different_first_read_or_expand_the_window(self):
        endpoint={'baseline':{'damage':225},'baseline_frames':[{'native_time':t,'native_verified':True,'damage':value} for t,value in [(.02,224),(.06,225),(.10,225)]]}
        self.assertEqual(early_export_baseline_fields(endpoint,.02),[])
        endpoint['baseline_frames']=endpoint['baseline_frames'][1:]
        self.assertEqual(early_export_baseline_fields(endpoint,-.03),[])
        for frame in endpoint['baseline_frames']:frame['native_verified']=False
        self.assertEqual(early_export_baseline_fields(endpoint,.02),[])


    def test_native_reread_never_fills_missing_endpoints_with_old_spectator_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,original,fresh=self.fixture(root)
            fresh['baseline']['damage']=None;fresh['last_hud']['damage']=868
            for frame in fresh['baseline_frames']:frame['damage']=None
            for frame in fresh['end_frames']:frame['damage']=868
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('combat_statistics.counter_endpoints',return_value=[fresh]):
                result=repair(record)
            segment=result['segments'][0]
            self.assertIsNone(segment['endpoint']['baseline']['damage'])
            self.assertEqual(segment['endpoint']['last_hud']['damage'],868)
            self.assertNotIn('damage',segment.get('native_repaired_fields',[]))
            self.assertEqual(segment['counts']['damage'],2076)

    def test_correction_lock_excludes_another_process_and_releases(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'record.lock';context=multiprocessing.get_context('spawn');ready=context.Event();release=context.Event()
            process=context.Process(target=hold_correction_lock,args=(str(path),ready,release));process.start()
            try:
                self.assertTrue(ready.wait(10))
                with self.assertRaises(RuntimeError):
                    with correction_lock(path,timeout=.2):pass
            finally:
                release.set();process.join(10)
                if process.is_alive():process.terminate();process.join(5)
            self.assertEqual(process.exitcode,0)
            with correction_lock(path,timeout=1):pass

    def test_identical_statistics_in_different_records_have_separate_corrections(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,original,fresh=self.fixture(root);other=original.parent.with_name('task-copy');other.mkdir();(other/'statistics.json').write_bytes(original.read_bytes())
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('combat_statistics.counter_endpoints',side_effect=lambda *args,**kwargs:[copy.deepcopy(fresh)]):
                repair(record);repair({**record,'directory':str(other)})
            files=list((root/'software/recognition-corrections').glob('*.json'));self.assertEqual(len(files),2)
            self.assertEqual(len({json.loads(file.read_text('utf-8'))['correction_context'] for file in files}),2)

    def test_native_lower_bound_can_replace_a_known_bad_nonempty_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,original,fresh=self.fixture(root);fresh['unconfirmed_latest']={'damage':2300}
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('combat_statistics.counter_endpoints',return_value=[fresh]):result=repair(record)
            self.assertEqual(result['segments'][0]['counts']['damage'],196);self.assertTrue(result['segments'][0]['partial']['damage'])

    def test_missing_mode_retries_pending_native_fields_and_preserves_verified_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,original,fresh=self.fixture(root);report=json.loads(original.read_text('utf-8'))
            report['segments'][0]['counts'].update(kills=0,assists=0)
            report['segments'][0]['partial'].update(kills=False,assists=False)
            original.write_text(json.dumps(report),'utf-8');raw=original.read_bytes()
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('combat_statistics.counter_endpoints',return_value=[copy.deepcopy(fresh)]):
                first=repair(record)
                self.assertEqual(first['segments'][0]['counts']['damage'],196)
                self.assertIn('kills',first['segments'][0]['counter_verification_pending'])
                second=copy.deepcopy(fresh);second['baseline']['kills']=0;second['last_hud']['kills']=1
                second['baseline']['damage']=second['last_hud']['damage']=None
                for group,value in [('baseline_frames',0),('end_frames',1)]:
                    for frame in second[group]:frame['kills']=value;frame['damage']=None
                with patch('combat_statistics.counter_endpoints',return_value=[second]) as reread:
                    updated=repair({**record,'native':True,'fields':['statistics'],'recheck_existing':False})
                self.assertTrue(reread.called);self.assertEqual(updated['segments'][0]['counts']['kills'],1)
                self.assertEqual(updated['segments'][0]['counts']['damage'],196)
            self.assertEqual(original.read_bytes(),raw)

    def test_selected_repairs_preserve_unselected_and_previously_corrected_segments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,original,fresh=self.fixture(root);report=json.loads(original.read_text('utf-8'))
            other=copy.deepcopy(report['segments'][0]);other.update(start=30,end=50);report['segments'].append(other);original.write_text(json.dumps(report),'utf-8');raw=original.read_bytes()
            files=[root/'videos/a.mp4',root/'videos/b.mp4']
            for file in files:file.write_bytes(b'export fixture')
            manifest={'source':report['source'],'video_directory':str(root/'videos'),'outputs':list(map(str,files)),'clips':[{'output':str(file),'segment':{'start':segment['start'],'end':segment['end']}} for file,segment in zip(files,report['segments'])]}
            original.with_name('export.json').write_text(json.dumps(manifest),'utf-8')
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('repair_cached_statistics.exported_endpoint',side_effect=lambda *args:copy.deepcopy(fresh)):
                first=repair({**record,'files':[str(files[0])]})
                self.assertEqual(first['segments'][1],other)
                with patch('stat_counter_fallback.counter_recipe',return_value='new-recipe'):
                    second=repair({**record,'files':[str(files[1])]})
            self.assertEqual([segment['counts']['damage'] for segment in second['segments']],[196,196]);self.assertEqual(original.read_bytes(),raw)

    def test_enemy_only_refresh_does_not_read_or_change_counters(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,original,fresh=self.fixture(root);report=json.loads(original.read_text('utf-8'))
            report['segments'][0]['events']=[{'kind':'knock','time':1.,'target_text':'old','confirmed':True}];original.write_text(json.dumps(report),'utf-8')
            event={'kind':'knock','time':1.,'target_text':'new','confirmed':True,'native_name_status':'confirmed'}
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('combat_statistics.counter_endpoints',side_effect=AssertionError('enemy only')),patch('repair_cached_statistics.recheck_event_names',return_value=[event]):
                result=repair({**record,'fields':['opponents'],'force':True})
            self.assertEqual(result['segments'][0]['counts']['damage'],2076);self.assertEqual(result['segments'][0]['events'][0]['target_text'],'new')
            self.assertEqual(result['segments'][0]['repair_fields'],['opponents'])

    def test_exported_clips_retries_while_sibling_commit_replaces_manifest(self):
        # 同组片段提交时会原子替换 export.json；替换瞬间的读失败不能让后续片段报「不在导出记录中」。
        from repair_cached_statistics import exported_clips
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();clip=root/'clip.mp4';clip.write_bytes(b'x')
            (root/'export.json').write_text(json.dumps({'source':{'a':1},'outputs':[str(clip)],'clips':[{'output':str(clip)}]}),'utf-8')
            original=Path.read_text;calls={'n':0}
            def flaky(self,*args,**kwargs):
                if self.name=='export.json' and calls['n']<2:calls['n']+=1;raise PermissionError('replacing')
                return original(self,*args,**kwargs)
            with patch.object(Path,'read_text',flaky),patch('repair_cached_statistics.time.sleep'):
                self.assertEqual(len(exported_clips(root,{'source':{'a':1}})),1)

    def test_exported_view_redetects_layout_when_saved_profile_is_not_reusable(self):
        # 强制重识别会作废旧布局；默认几何没有确认标记，事件武器会全部判为「布局未确认」，必须按成片重新检测。
        from repair_cached_statistics import exported_view
        clip={'segment':{'start':0,'end':10},'recognition':{'hud_info':{'profile':{'layout_version':'v','layout_status':'confirmed'}}}}
        detected={'layout_version':'anchored-hud-v2','layout_status':'confirmed'}
        with patch('apex_clipper.probe',return_value=({'format':{'duration':10}},{'width':2560,'height':1080})),\
             patch('hud_recovery.active',return_value=True),patch('hud_recovery.profile_reusable',return_value=False),\
             patch('hud_layout.detect_video',return_value=detected) as detect:
            view=exported_view([(clip,{'path':'clip.mp4'})],{'start':0,'end':10},{})
        self.assertEqual(view[4]['layout_status'],'confirmed');detect.assert_called_once()

    def test_export_only_recheck_uses_original_match_start_zero_with_native_export_end(self):
        # 成片开头计分栏未显示：起点取导出时完整原片判定的开局 0，终点取成片片尾双帧原生读数。
        # 原片已删、或原片仍在但采样缓存已清理，本次都只能看成片首尾，不能把导出时的计数清空。
        for deleted in [True,False]:
            with self.subTest(source_deleted=deleted):self.export_only_recheck(deleted)

    def export_only_recheck(self,deleted):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,original,fresh=self.fixture(root)
            report=json.loads(original.read_text('utf-8'));segment=report['segments'][0]
            segment['counts'].update(kills=None,damage=None);segment['partial'].update(kills=True,damage=True)
            segment['endpoint']={'baseline':{'kills':0,'assists':0,'damage':0},'last_hud':{},'initial_hidden_zero':True,'baseline_frames':[]}
            original.write_text(json.dumps(report),'utf-8')
            if deleted:Path(report['source']['path']).unlink()
            (Path(record['analysis_cache'])/'hud.json').unlink()
            exported=root/'videos/clip.mp4';exported.write_bytes(b'export fixture')
            manifest={'metadata_directory':record['directory'],'video_directory':str(root/'videos'),'source':report['source'],'outputs':[str(exported)],'clips':[{'output':str(exported),'segment':{'start':0,'end':20}}]}
            original.with_name('export.json').write_text(json.dumps(manifest),'utf-8')
            fresh['baseline']=dict.fromkeys(['kills','assists','damage'])
            fresh['last_hud']={'kills':2,'assists':None,'damage':384}
            fresh['baseline_frames']=[{'native_time':t,'native_verified':True} for t in [.04,.08]]
            fresh['end_frames']=[{'native_time':t,'native_verified':True,'kills':2,'damage':384} for t in [19.5,19.9]]
            fresh.update(native_counter_scope='exported_visible_delta',export_baseline_fields=[])
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('repair_cached_statistics.exported_endpoint',return_value=copy.deepcopy(fresh)):
                fixed=repair({**record,'native':True,'force':True})['segments'][0]
            self.assertEqual((fixed['counts']['kills'],fixed['counts']['damage']),(2,384))
            self.assertTrue(fixed['partial']['kills']);self.assertEqual(fixed['export_baseline_from_original'],{'damage':0,'kills':0})
            # 导出时起点没有开局隐藏证据、也没有多帧一致：不能当 0。
            segment['endpoint']={'baseline':{'kills':0,'damage':0},'initial_hidden_zero':False,'baseline_frames':[]}
            original.write_text(json.dumps(report),'utf-8')
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe2'),patch('repair_cached_statistics.exported_endpoint',return_value=copy.deepcopy(fresh)):
                fixed=repair({**record,'native':True,'force':True})['segments'][0]
            self.assertIsNone(fixed['counts']['kills'])

    def test_deleted_source_force_recheck_keeps_export_counts_as_lower_bound(self):
        # 导出后删除原片：强制重识别只能看成片首尾，读不到起点时不能把导出时的完整统计清空。
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,original,fresh=self.fixture(root)
            report=json.loads(original.read_text('utf-8'));report['segments'][0]['counts'].update(kills=2)
            report['segments'][0]['partial'].update(kills=False)
            original.write_text(json.dumps(report),'utf-8');raw=original.read_bytes()
            Path(report['source']['path']).unlink();(Path(record['analysis_cache'])/'hud.json').unlink()
            exported=root/'videos/clip.mp4';exported.write_bytes(b'export fixture')
            manifest={'metadata_directory':record['directory'],'video_directory':str(root/'videos'),'source':report['source'],'outputs':[str(exported)],'clips':[{'output':str(exported),'segment':{'start':0,'end':20}}]}
            original.with_name('export.json').write_text(json.dumps(manifest),'utf-8')
            for group in ['baseline','last_hud']:fresh[group]=dict.fromkeys(['kills','assists','damage'])
            for group in ['baseline_frames','end_frames']:
                for frame in fresh[group]:frame.pop('damage')
            fresh.update(native_counter_scope='exported_visible_delta',export_baseline_fields=[])
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('repair_cached_statistics.exported_endpoint',return_value=fresh):
                segment=repair({**record,'native':True,'force':True})['segments'][0]
            self.assertEqual(segment['counts']['damage'],2076);self.assertEqual(segment['counts']['kills'],2)
            self.assertTrue(segment['partial']['damage']);self.assertTrue(segment['partial']['kills'])
            self.assertEqual(segment['source_lower_bound_fields'],['damage','kills'])
            self.assertNotIn('damage',segment.get('native_repaired_fields',[]))
            self.assertEqual(original.read_bytes(),raw)

    def fixture(self,root,native=True):
        destination=root/'videos/task';destination.mkdir(parents=True)
        source=root/'source.mp4';source.write_bytes(b'unchanged source')
        identity=fingerprint(source);cache=root/'cache';cache.mkdir()
        (cache/'hud.json').write_text(json.dumps({'source':identity,'rows':[]}),'utf-8')
        report={'version':'old','source':identity,'segments':[{'start':0,'end':20,'counts':{'kills':None,'assists':None,'damage':2076},'partial':{'kills':True,'assists':True,'damage':False},'events':[],'coverage':{'checked_frames':0,'expected_frames':0,'ambiguous_frames':[]},'endpoint':{'baseline':{'damage':208},'last_hud':{'damage':228}}}]}
        original=destination/'statistics.json';original.write_text(json.dumps(report),'utf-8')
        fresh={'native_view_version':'self-hud-view-v3','native_numeric_method':METHOD,'baseline':{'kills':None,'assists':None,'damage':2088},'last_hud':{'kills':None,'assists':None,'damage':2284},'baseline_frames':[{'native_time':t,'native_verified':native,'damage':2088} for t in [.1,.2]],'end_frames':[{'native_time':t,'native_verified':native,'damage':2284} for t in [16.5,16.6]],'unconfirmed_latest':{}}
        record={'directory':str(destination),'analysis_cache':str(cache),'sample_directory':str(cache/'samples'),'recheck_existing':True}
        return record,original,fresh

    def test_native_recheck_corrects_nonempty_count_outside_video_folder_and_never_downgrades(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,original,fresh=self.fixture(root);raw=original.read_bytes()
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('combat_statistics.counter_endpoints',return_value=[copy.deepcopy(fresh)]):
                result=repair(record)
                self.assertEqual(result['segments'][0]['counts']['damage'],196)
                self.assertEqual(result['segments'][0]['native_repaired_fields'],['damage'])
                with patch('combat_statistics.counter_endpoints',side_effect=AssertionError('must reuse stronger verified result')):
                    self.assertEqual(repair({**record,'recheck_existing':False})['segments'][0]['counts']['damage'],196)
            expected=root/'software/recognition-corrections'/(correction_key(raw,original.parent)+'.json')
            self.assertTrue(expected.is_file());self.assertEqual(original.read_bytes(),raw)
            self.assertFalse(original.with_name('statistics-corrected.json').exists())

    def test_preview_only_evidence_does_not_overwrite_nonempty_historical_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,original,fresh=self.fixture(root,native=False)
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('combat_statistics.counter_endpoints',return_value=[fresh]):
                result=repair(record)
            self.assertEqual(result['segments'][0]['counts']['damage'],2076)
            self.assertFalse(result['segments'][0].get('native_repaired_fields'))

    def test_forced_or_new_recipe_unknown_does_not_restore_a_prior_verified_value(self):
        for force in [True,False]:
            with self.subTest(force=force),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);record,original,fresh=self.fixture(root);raw=original.read_bytes()
                with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='previous-recipe'),patch('combat_statistics.counter_endpoints',return_value=[copy.deepcopy(fresh)]):
                    first=repair(record)
                self.assertEqual(first['segments'][0]['counts']['damage'],196)
                fresh['baseline']['damage']=None
                for frame in fresh['baseline_frames']:frame['damage']=None
                recipe='previous-recipe' if force else 'updated-recipe'
                with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value=recipe),patch('combat_statistics.counter_endpoints',return_value=[fresh]):
                    second=repair({**record,'force':force})['segments'][0]
                self.assertIsNone(second['endpoint']['baseline']['damage'])
                self.assertIsNone(second['counts']['damage'])
                self.assertTrue(second['partial']['damage'])
                self.assertNotIn('damage',second.get('native_repaired_fields',[]))
                self.assertIn('damage',second['counter_verification_pending'])
                self.assertEqual(original.read_bytes(),raw)

    def test_missing_original_and_cache_use_recorded_export_without_touching_original_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,original,fresh=self.fixture(root)
            raw=original.read_bytes();report=json.loads(raw);Path(report['source']['path']).unlink()
            (Path(record['analysis_cache'])/'hud.json').unlink()
            exported=root/'videos/clip.mp4';exported.write_bytes(b'export fixture')
            manifest={'metadata_directory':record['directory'],'video_directory':str(root/'videos'),'source':report['source'],'outputs':[str(exported)],'clips':[{'output':str(exported),'segment':{'start':0,'end':20}}]}
            original.with_name('export.json').write_text(json.dumps(manifest),'utf-8')
            fresh.update(native_counter_scope='exported_visible_delta',export_baseline_fields=['damage'],exported_video_identity={'path':str(exported),'size':exported.stat().st_size,'mtime_ms':exported.stat().st_mtime_ns//1_000_000})
            with patch.dict(os.environ,{'APEX_DATA_ROOT':str(root/'software')}),patch('stat_counter_fallback.counter_recipe',return_value='recipe'),patch('repair_cached_statistics.exported_endpoint',return_value=fresh),patch('combat_statistics.counter_endpoints',side_effect=AssertionError('must use export proof')):
                result=repair(record)
            self.assertEqual(result['segments'][0]['counts']['damage'],196)
            self.assertEqual(original.read_bytes(),raw)
            self.assertTrue(all(path.parent==root/'software/recognition-corrections' for path in(root/'software/recognition-corrections').glob('*.json')))

    def zero_rows(self,times):
        return [{'frame':f'native:export:{t:.5f}','time':t,'native_verified':True,'native_time':t,'kills':0,'assists':0,'damage':0,'zero_evidence':{'method':'test'}} for t in times]

    def test_exported_clip_zero_start_counts_as_export_baseline(self):
        # 成片开头计分栏没出现、小队数行在：起点三项按 0，与开头 80 毫秒内的原生读数同样作为成片起点。
        from repair_cached_statistics import zero_exported_counters,native_verified_fields
        endpoint={'baseline':dict.fromkeys(['kills','assists','damage']),'last_hud':{'kills':2,'assists':1,'damage':384},'unconfirmed_latest':{},
                  'baseline_frames':[{'time':t,'native_time':t,'native_verified':True,'marker_score':.55} for t in [0.,.04,.08]],
                  'end_frames':[{'time':t,'native_time':t,'native_verified':True,'kills':2,'assists':1,'damage':384} for t in [24.5,24.75,25.]],
                  'export_baseline_fields':[],'native_view_version':'self-hud-view-v3','native_numeric_method':METHOD,'native_counter_scope':'exported_visible_delta'}
        with patch('repair_cached_statistics.exported_zero_frames',side_effect=[self.zero_rows([.31,.81])]) as probe:
            zero_exported_counters(endpoint,Path('clip.mp4'),0.,25.,{})
        self.assertEqual(probe.call_count,1)  # 片尾已读到计数，不再核对
        self.assertEqual(endpoint['baseline'],{'kills':0,'assists':0,'damage':0})
        self.assertEqual(endpoint['export_baseline_fields'],['kills','assists','damage']);self.assertTrue(endpoint['initial_hidden_zero'])
        self.assertEqual(sorted(native_verified_fields(endpoint)),['assists','damage','kills'])
        # 开头已经找到计分图标（只是数字没读出来）时不能判 0。
        visible={**endpoint,'baseline':dict.fromkeys(['kills','assists','damage']),'export_baseline_fields':[],
                 'baseline_frames':[{'time':0.,'native_time':0.,'native_verified':True,'marker_score':.92}]}
        with patch('repair_cached_statistics.exported_zero_frames',side_effect=AssertionError('icon visible')):
            zero_exported_counters(visible,Path('clip.mp4'),0.,25.,{})
        self.assertIsNone(visible['baseline']['damage'])

    def test_exported_clip_zero_end_replaces_unread_own_view_tail_only(self):
        from repair_cached_statistics import zero_exported_counters
        from combat_statistics import reconciled_counts
        base={'baseline':{'kills':0,'assists':0,'damage':0},'last_hud':dict.fromkeys(['kills','assists','damage']),'unconfirmed_latest':{},
              'baseline_frames':[{'time':t,'native_time':t,'native_verified':True,'kills':0,'assists':0,'damage':0} for t in [0.,.04]],
              'end_frames':[{'time':t,'native_time':t,'native_verified':True,'marker_score':.5} for t in [9.5,9.75,9.96]],'export_baseline_fields':['kills','assists','damage']}
        coverage={'checked_frames':0,'expected_frames':0,'ambiguous_frames':[]}
        own=copy.deepcopy(base)
        with patch('repair_cached_statistics.exported_zero_frames',return_value=self.zero_rows([9.7,9.96])) as probe:
            zero_exported_counters(own,Path('clip.mp4'),0.,10.,{})
        self.assertTrue(probe.call_args.kwargs.get('descending'))
        self.assertEqual([row['native_time'] for row in own['end_frames']],[9.7,9.96])
        result=reconciled_counts(own,[],coverage)
        self.assertEqual(result['counts']['damage'],0);self.assertFalse(result['partial']['damage'])
        dead=copy.deepcopy(base);dead['excluded_terminal_view']=True
        dead['end_frames']=[{'time':9.96,'native_time':9.96,'native_verified':False,'excluded_view':True}]
        with patch('repair_cached_statistics.exported_zero_frames',return_value=self.zero_rows([4.,7.])):
            zero_exported_counters(dead,Path('clip.mp4'),0.,10.,{})
        result=reconciled_counts(dead,[],coverage)
        # 阵亡后观战的片尾仍按下限：观战期间本人可能还有延迟伤害。
        self.assertEqual(result['counts']['damage'],0);self.assertTrue(result['partial']['damage'])
