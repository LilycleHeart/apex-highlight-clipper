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
from numeric_reader import METHOD


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
        with patch('repair_cached_statistics.exported_view',return_value=(source,{'path':str(source)},0.,10.,{})),patch('apex_clipper.fingerprint',return_value={}),patch('combat_statistics.counter_endpoints',side_effect=[[empty],[prior]]) as read:
            endpoint=exported_endpoint([],{'start':100.,'end':110.},{})
        result=reconciled_counts(endpoint,[],{'checked_frames':0,'expected_frames':0,'ambiguous_frames':[]})
        self.assertEqual(read.call_count,2)
        self.assertEqual(result['counts']['damage'],50)
        self.assertTrue(result['partial']['damage'])
        self.assertTrue(any('片尾计分栏未完整读取' in note for note in result['notes']))
        self.assertAlmostEqual(endpoint['end_frames'][-1]['time'],109.96)

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
