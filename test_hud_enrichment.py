import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from apex_clipper import fingerprint
from hud_enrichment import enrich_manifest,FIELDS,VERSION,field_version


class HudEnrichmentTests(unittest.TestCase):

    def test_missing_rank_division_keeps_confirmed_tier_and_remains_pending(self):
        from hud_enrichment import field_unconfirmed
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root);info=manifest['clips'][0]['recognition']['hud_info'];info['rank']['division']=None
            (root/'export.json').write_text(json.dumps(manifest),'utf-8');fresh=self.fresh(['rank'],rank=None)
            with patch('hud_enrichment.recognize_video',return_value=fresh) as read:
                result=enrich_manifest(root,[str(files[0])],['rank'])
            current=result['clips'][0]['recognition']['hud_info'];read.assert_called_once_with(files[0],['rank'])
            self.assertEqual(current['rank']['tier'],'gold');self.assertIsNone(current['rank']['division']);self.assertTrue(field_unconfirmed(current,'rank'))
            self.assertEqual(current['weapons'],info['weapons'])

    def test_unchanged_media_reuses_its_confirmed_current_layout(self):
        from hud_layout import VERSION as LAYOUT_VERSION
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root);info=manifest['clips'][0]['recognition']['hud_info'];layout={'layout_version':LAYOUT_VERSION,'layout_status':'confirmed','reference_size':[1920,1080]};info['profile']=layout
            (root/'export.json').write_text(json.dumps(manifest),'utf-8');fresh=self.fresh(['account'],account={'name':'SAMPLE','confidence':.99})
            with patch('hud_enrichment.recognize_video',return_value=fresh) as read:enrich_manifest(root,[str(files[0])],['account'],force=True)
            read.assert_called_once_with(files[0],['account'],profile=layout)

    def test_changed_media_does_not_reuse_old_layout(self):
        from hud_layout import VERSION as LAYOUT_VERSION
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root);info=manifest['clips'][0]['recognition']['hud_info'];info['profile']={'layout_version':LAYOUT_VERSION,'layout_status':'confirmed'};info['source_identity']['size']+=1
            (root/'export.json').write_text(json.dumps(manifest),'utf-8');fresh=self.fresh(['account'],account=None)
            with patch('hud_enrichment.recognize_video',return_value=fresh) as read:enrich_manifest(root,[str(files[0])],['account'],force=True)
            read.assert_called_once_with(files[0],['account'])

    def test_name_visibility_rejects_blank_and_large_boundary_overlay(self):
        from hud_enrichment import name_patch_quality
        image=np.zeros((20,100,3),np.uint8)
        self.assertFalse(name_patch_quality(image)['clear'])
        for x in [10,25,40,55]:image[4:15,x:x+4]=255
        self.assertTrue(name_patch_quality(image)['clear'])
        image[:,65:]=255
        self.assertFalse(name_patch_quality(image)['clear'])
        self.assertTrue(name_patch_quality(image,text_right=60)['clear'])
        self.assertFalse(name_patch_quality(image,text_right=85)['clear'])

    def test_visibility_search_is_bounded_and_skips_existing_read_times(self):
        from hud_enrichment import account_search_moments
        times=account_search_moments([{'time':20.,'account':{'confidence':.9}}],[18.2,20.],0.,40.)
        self.assertLessEqual(len(times),8);self.assertTrue(all(0<=time<40 for time in times));self.assertNotIn(18.2,times)
        self.assertEqual(account_search_moments([],[],1.,1.),[])

    def test_repeated_decoder_pts_does_not_create_two_name_votes(self):
        from hud_enrichment import recognize_video
        from hud_layout import make_profile
        image=np.zeros((1080,1920,3),np.uint8);profile=make_profile(1920,1080);profile['layout_status']='confirmed'
        text=np.zeros((20,100,3),np.uint8)
        for x in [10,25,40,55]:text[4:15,x:x+4]=255
        def frames(*args,moments=None):return iter([(1.,image)]*3)
        read=lambda images:[{'name':'PLAYER_ONE','confidence':.99,'view_agreement':2} for _ in images]
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'clip.mp4';source.write_bytes(b'fixture')
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('hud_enrichment.probe',return_value=({'format':{'duration':10}},{'width':1920,'height':1080})),patch('hud_enrichment.inactive_view',return_value=False),patch('engine_pool.pooled_engine',return_value=SimpleNamespace(text_rec=object())),patch('hud_enrichment.NameReader',return_value=read),patch('hud_enrichment.name_patch',return_value=text),patch('hud_enrichment.detect_images',return_value=profile):
                result=recognize_video(source,['account'],profile=profile)
        self.assertEqual(result['checked_frames'],1);self.assertIsNone(result['account'])

    def test_extra_account_frames_do_not_reidentify_other_fields(self):
        from hud_enrichment import recognize_video
        from hud_layout import make_profile
        image=np.zeros((1080,1920,3),np.uint8);profile=make_profile(1920,1080);profile['layout_status']='confirmed';count=0
        text=np.zeros((20,100,3),np.uint8)
        for x in [10,25,40,55]:text[4:15,x:x+4]=255
        def frames(source,start,end,moments=None):return iter((time,image) for time in (moments if moments is not None else [1.,4.,8.]))
        def read(images):
            nonlocal count
            count+=1
            return [None if count<=6 else {'name':'PLAYER_ONE','confidence':.99,'view_agreement':2} for _ in images]
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'clip.mp4';source.write_bytes(b'fixture')
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('hud_enrichment.probe',return_value=({'format':{'duration':10}},{'width':1920,'height':1080})),patch('hud_enrichment.inactive_view',return_value=False),patch('engine_pool.pooled_engine',return_value=SimpleNamespace(text_rec=object())),patch('hud_enrichment.NameReader',return_value=read),patch('hud_enrichment.name_patch',return_value=text),patch('hud_enrichment.detect_images',return_value=profile),patch('hero_reader.HeroReader') as hero:
                hero.return_value.inspect.return_value={'name':'探路者','id':'pathfinder','confidence':.99}
                result=recognize_video(source,['account','hero'],profile=profile)
            self.assertEqual(hero.return_value.inspect.call_count,6)
        self.assertEqual(result['checked_frames'],8);self.assertEqual(result['account']['name'],'PLAYER_ONE');self.assertEqual(result['hero']['id'],'pathfinder')

    def test_missing_rank_search_keeps_confirmed_hero_and_requires_distinct_frames(self):
        from hud_enrichment import recognize_video
        from hud_layout import make_profile
        image=np.zeros((1080,1920,3),np.uint8);profile=make_profile(1920,1080)
        def frames(source,start,end,moments=None):return iter((time,image) for time in (moments if moments is not None else [1.5,5.,8.5]))
        rank={'name':'钻石','tier':'diamond','division':'IV','confidence':.95}
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'clip.mp4';source.write_bytes(b'fixture')
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('hud_enrichment.probe',return_value=({'format':{'duration':10}},{'width':1920,'height':1080})),patch('hud_enrichment.inactive_view',return_value=False),patch('hero_reader.HeroReader') as hero,patch('rank_reader.RankReader') as ranks:
                hero.return_value.inspect.return_value={'name':'探路者','id':'pathfinder','confidence':.99}
                ranks.return_value.inspect.side_effect=[None]*6+[rank,rank]
                result=recognize_video(source,['hero','rank'],profile=profile)
        self.assertEqual(hero.return_value.inspect.call_count,6)
        self.assertEqual(ranks.return_value.inspect.call_count,8)
        self.assertEqual(result['rank']['tier'],'diamond');self.assertEqual(result['rank']['votes'],2)
        self.assertEqual(result['hero']['id'],'pathfinder')
        self.assertTrue(all(row['fields']==['rank'] for row in result['visual_field_search']))
        self.assertEqual(len(result['frame_times']),len(set(result['frame_times'])))

    def test_visual_search_frame_remains_available_to_account_without_duplicate_votes(self):
        from hud_enrichment import recognize_video
        from hud_layout import make_profile
        image=np.zeros((1080,1920,3),np.uint8);profile=make_profile(1920,1080);profile['layout_status']='confirmed';count=0
        text=np.zeros((20,100,3),np.uint8)
        for x in [10,25,40,55]:text[4:15,x:x+4]=255
        def frames(source,start,end,moments=None):return iter((time,image) for time in (moments if moments is not None else [1.5,5.,8.5]))
        def read(images):
            nonlocal count
            count+=1
            return [None if count<=6 else {'name':'PLAYER_ONE','confidence':.99,'view_agreement':2} for _ in images]
        rank={'name':'钻石','tier':'diamond','division':'IV','confidence':.95}
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'clip.mp4';source.write_bytes(b'fixture')
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('hud_enrichment.probe',return_value=({'format':{'duration':10}},{'width':1920,'height':1080})),patch('hud_enrichment.inactive_view',return_value=False),patch('engine_pool.pooled_engine',return_value=SimpleNamespace(text_rec=object())),patch('hud_enrichment.NameReader',return_value=read),patch('hud_enrichment.name_patch',return_value=text),patch('hud_enrichment.detect_images',return_value=profile),patch('rank_reader.RankReader') as ranks:
                ranks.return_value.inspect.side_effect=[None]*6+[rank,rank]
                result=recognize_video(source,['account','rank'],profile=profile)
        self.assertEqual(result['account']['name'],'PLAYER_ONE');self.assertEqual(result['account']['votes'],2)
        self.assertEqual(result['rank']['votes'],2)
        self.assertEqual(len(result['frame_times']),len(set(result['frame_times'])))
        self.assertEqual(len([row for row in result['name_observations'] if row['time']==.5 and row.get('account')]),1)

    def test_one_clear_search_read_is_paired_even_if_an_occluded_old_read_agrees(self):
        from hud_enrichment import recognize_video
        from hud_layout import make_profile
        profile=make_profile(1920,1080);profile['layout_status']='confirmed'
        def frame(time):
            image=np.zeros((1080,1920,3),np.uint8);image[0,0,0]=min(255,round(time*100));return image
        def frames(source,start,end,moments=None):return iter((time,frame(time)) for time in (moments if moments is not None else [1.5,5.,8.5]))
        def crop(image,*args,**kwargs):
            code=int(image[0,0,0]);patch_image=np.zeros((20,100,3),np.uint8)
            if code in [86,90,94,150]:
                for x in [10,25,40,55]:patch_image[4:15,x:x+4]=255
            if code==150:patch_image[:,65:]=255
            patch_image[0,0,0]=code;return patch_image
        def read(images):return [{'name':'PLAYER_ONE','confidence':.99,'view_agreement':2} if int(image[0,0,0]) in [86,90,94,150] else None for image in images]
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'clip.mp4';source.write_bytes(b'fixture')
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('hud_enrichment.probe',return_value=({'format':{'duration':10}},{'width':1920,'height':1080})),patch('hud_enrichment.inactive_view',return_value=False),patch('engine_pool.pooled_engine',return_value=SimpleNamespace(text_rec=object())),patch('hud_enrichment.NameReader',return_value=read),patch('hud_enrichment.name_patch',side_effect=crop),patch('hud_enrichment.detect_images',return_value=profile):
                result=recognize_video(source,['account'],profile=profile)
        verified=[row for row in result['name_observations'] if row.get('account',{}).get('name_visibility',{}).get('verified')]
        self.assertGreaterEqual(len({row['time'] for row in verified}),2)
        self.assertEqual(result['account']['name'],'PLAYER_ONE')

    def test_adaptive_sampling_rechecks_each_visible_missing_field_before_reusing_seed(self):
        from hud_enrichment import adaptive_moments
        observations=[{'time':6.,'weapon_ids':['nemesis','prowler'],'teammates':[]},
                      {'time':20.,'weapon_ids':[],'teammates':[]},
                      {'time':35.,'hero':{'name':'罗芭','confidence':.95},'weapon_ids':[],'teammates':[]}]
        weapons=[{'id':ident,'time':6.,'confidence':.95} for ident in ['nemesis','prowler']]
        times=adaptive_moments(observations,['weapons','hero'],[[],[]],weapons,[6.,20.,35.],0.,40.)
        self.assertEqual(len(times),3)
        self.assertTrue(any(abs(time-6.)<1 for time in times))
        self.assertTrue(any(abs(time-35.)<1 for time in times))

    def test_single_visible_missing_field_keeps_all_rechecks_near_its_evidence(self):
        from hud_enrichment import adaptive_moments
        observations=[{'time':6.},{'time':20.},{'time':35.,'hero':{'name':'暴雷','confidence':.9}}]
        times=adaptive_moments(observations,['hero'],[[],[]],[],[6.,20.,35.],0.,40.)
        self.assertEqual(len(times),3)
        self.assertTrue(all(abs(time-35.)<1 for time in times))

    def test_unconfirmed_hero_shape_only_guides_sampling_without_becoming_a_result(self):
        from hud_enrichment import adaptive_moments,stable
        observations=[{'time':6.,'hero_hint':.73},{'time':20.,'hero_hint':.69},{'time':35.,'hero_hint':.82}]
        times=adaptive_moments(observations,['hero'],[[],[]],[],[6.,20.,35.],0.,40.)
        self.assertTrue(all(abs(time-35.)<1 for time in times))
        self.assertIsNone(stable(observations,'hero'))

    def test_weak_shape_hints_keep_diverse_sample_positions(self):
        from hud_enrichment import adaptive_moments
        observations=[{'time':6.,'hero_hint':.73},{'time':20.,'hero_hint':.72},{'time':35.,'hero_hint':.77}]
        times=adaptive_moments(observations,['hero'],[[],[]],[],[6.,20.,35.],0.,40.)
        self.assertEqual(times,[6.4,20.4,35.4])

    def test_stop_marker_aborts_before_any_job_is_opened(self):
        import os
        from hud_enrichment import run_jobs
        from app_cancel import TaskStopped
        with tempfile.TemporaryDirectory() as temporary:
            marker=Path(temporary)/'stop';marker.write_text('stop','utf-8')
            with patch.dict(os.environ,{},clear=False),patch('hud_enrichment.enrich_manifest',side_effect=AssertionError('must stop first')):
                with self.assertRaises(TaskStopped):run_jobs({'stop_file':str(marker),'jobs':[{'directory':'metadata','files':['clip.mp4']}],'fields':['account']},direct=True,emit=lambda event:None)

    def test_extra_only_jobs_never_reidentify_other_hud_fields_and_report_progress(self):
        from hud_enrichment import run_jobs
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root)
            segment={'start':0,'end':10,'counts':{'kills':0,'assists':0,'damage':196},'partial':{'kills':False,'assists':False,'damage':False},'native_repaired_fields':['kills','assists','damage'],'events':[]}
            from outcome_reader import SELF_VIEW_VERSION
            from numeric_reader import METHOD
            baseline={'kills':0,'assists':0,'damage':0}
            segment['endpoint']={'native_view_version':SELF_VIEW_VERSION,'native_numeric_method':METHOD,
                'native_counter_scope':'exported_visible_delta','export_baseline_fields':['kills','assists','damage'],
                'baseline':baseline,'last_hud':dict(segment['counts']),
                'baseline_frames':[{'native_time':time,'native_verified':True,**baseline} for time in [.02,.06]],
                'end_frames':[{'native_time':time,'native_verified':True,**segment['counts']} for time in [9.9,9.94]]}
            (root/'statistics.json').write_text(json.dumps({'segments':[segment]}),'utf-8')
            events=[]
            with patch('hud_enrichment.enrich_manifest',side_effect=AssertionError('must not reread HUD')),patch('repair_cached_statistics.repair',return_value={'segments':[segment]}) as repair:
                result=run_jobs({'jobs':[{'directory':str(root),'files':[str(files[0])]}],'fields':['statistics'],'force':True},direct=True,emit=events.append)
            self.assertEqual(result['updated'],1);self.assertEqual(result['unconfirmed'],0)
            self.assertEqual(repair.call_args.args[0]['files'],[str(files[0])]);self.assertTrue(repair.call_args.args[0]['force'])
            self.assertEqual([e['index'] for e in events if e['type']=='hud-info-progress'],[1])

    def test_extra_child_native_failure_falls_back_to_cpu(self):
        from hud_enrichment import run_jobs
        done={'updated':1,'files_updated':['clip.mp4'],'unconfirmed_files':[],'errors':[]}
        with patch('hud_enrichment._run_hud_child',side_effect=[RuntimeError('native exit'),done]) as child:
            result=run_jobs({'jobs':[{'directory':'metadata','files':['clip.mp4']}],'fields':['opponents'],'backend':'dml'},emit=lambda event:None)
        self.assertEqual([call.args[0]['backend'] for call in child.call_args_list],['dml','cpu']);self.assertEqual(result['updated'],1)

    def fixture(self,root):
        files=[root/'selected.mp4',root/'other.mp4']
        clips=[]
        for file in files:
            file.write_bytes(b'exported video fixture')
            account={'name':'old_wrong_account','confidence':.95}
            teammate={'name':'kept_teammate','confidence':.95,'slot':0}
            info={'version':VERSION,'field_versions':{field:field_version(field) for field in FIELDS},'source_identity':fingerprint(file),'requested_fields':FIELDS,
                'field_status':{field:'confirmed' for field in FIELDS},'account':account,
                'teammates':[teammate],'hero':{'id':'pathfinder','name':'探路者'},
                'weapons':[{'id':'r99','name':'R99'}],'rank':{'tier':'gold','division':'I'},
                'name_observations':[{'time':i,'account':account,'teammates':[teammate]} for i in [1,2,3]]}
            clips.append({'output':str(file),'segment':{'start':0,'end':10},
                'summary':{'kills':2,'damage':123,'weapons':['R99']},'recognition':{'hud_info':info}})
        manifest={'video_directory':str(root),'outputs':[str(file) for file in files],'clips':clips}
        (root/'export.json').write_text(json.dumps(manifest),encoding='utf-8')
        return files,manifest

    def fresh(self,fields,**values):
        return {'profile':{},'checked_frames':3,'frame_times':[1,2,3],'name_observations':[],
            'field_status':{field:'confirmed' if values[field] else 'unknown' for field in fields},**values}

    def test_missing_skips_confirmed_and_only_reads_unknown_selected_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root)
            with patch('hud_enrichment.recognize_video') as read:
                enrich_manifest(root,[str(files[0])],['weapons','rank'])
                read.assert_not_called()
            manifest['clips'][0]['recognition']['hud_info']['field_status']['weapons']='unknown'
            (root/'export.json').write_text(json.dumps(manifest),encoding='utf-8')
            fresh=self.fresh(['weapons'],weapons=[{'id':'r301','name':'R301'}])
            with patch('hud_enrichment.recognize_video',return_value=fresh) as read:
                result=enrich_manifest(root,[str(files[0])],['weapons','rank'])
                read.assert_called_once_with(files[0],['weapons'])
            info=result['clips'][0]['recognition']['hud_info']
            self.assertEqual(info['weapons'],fresh['weapons']);self.assertEqual(info['rank'],{'tier':'gold','division':'I'})
            self.assertEqual(result['clips'][1],manifest['clips'][1])

    def test_new_name_reader_version_does_not_invalidate_other_confirmed_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root)
            info=manifest['clips'][0]['recognition']['hud_info'];info['field_versions'].update(account='old-name-reader',teammates='old-name-reader')
            before=copy.deepcopy(manifest);(root/'export.json').write_text(json.dumps(manifest),'utf-8')
            fresh=self.fresh(['account','teammates'],account={'name':'NEW_ACCOUNT','confidence':.98},teammates=[{'name':'NEW_TEAM','confidence':.98,'slot':0}])
            with patch('hud_enrichment.recognize_video',return_value=fresh) as read:
                result=enrich_manifest(root,[str(files[0])],FIELDS)
            read.assert_called_once_with(files[0],['account','teammates'])
            current=result['clips'][0]['recognition']['hud_info']
            for field in ['weapons','hero','rank']:self.assertEqual(current[field],before['clips'][0]['recognition']['hud_info'][field])
            self.assertEqual(result['clips'][1],before['clips'][1])

    def test_legacy_same_source_partial_refresh_keeps_other_field_bindings_and_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root);before=copy.deepcopy(manifest)
            account=self.fresh(['account'],account={'name':'NEW_ACCOUNT','confidence':.98})
            with patch('hud_enrichment.recognize_video',return_value=account):
                first=enrich_manifest(root,[str(files[0])],['account'],force=True)
            previous=first['clips'][0]['recognition']['hud_info'];identity=fingerprint(files[0])
            self.assertEqual(previous['field_source_identities'],{field:identity for field in FIELDS})
            hero=self.fresh(['hero'],hero={'id':'fuse','name':'暴雷'})
            with patch('hud_enrichment.recognize_video',return_value=hero):
                second=enrich_manifest(root,[str(files[0])],['hero'],force=True)
            current=second['clips'][0]['recognition']['hud_info']
            self.assertEqual(current['account'],previous['account'])
            self.assertEqual(current['name_observations'],previous['name_observations'])
            for field in ['weapons','teammates','rank']:
                self.assertEqual(current[field],before['clips'][0]['recognition']['hud_info'][field])
                self.assertEqual(current['field_source_identities'][field],identity)
            self.assertEqual(second['clips'][1],before['clips'][1])

    def test_replaced_media_partial_refresh_invalidates_others_and_missing_reads_them(self):
        from hud_layout import VERSION as LAYOUT_VERSION
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root);before=copy.deepcopy(manifest)
            info=manifest['clips'][0]['recognition']['hud_info'];old_identity=info['source_identity']
            info.update(profile={'layout_version':LAYOUT_VERSION,'layout_status':'confirmed'},
                hero_observations=[{'hero':info['hero']}],hero_portrait_observations=[{'hero':info['hero']}],
                rank_observations=[{'rank':info['rank']}],account_visibility_search=[{'account':info['account']}],
                visual_field_search=[{'fields':['hero','rank']}])
            (root/'export.json').write_text(json.dumps(manifest),'utf-8');files[0].write_bytes(b'replacement video')
            identity=fingerprint(files[0]);fresh=self.fresh(['account'],account=None)
            with patch('hud_enrichment.recognize_video',return_value=fresh) as reader:
                result=enrich_manifest(root,[str(files[0])],['account'])
                reader.assert_called_once_with(files[0],['account'])
            current=result['clips'][0]['recognition']['hud_info']
            self.assertEqual(current['source_identity'],identity)
            self.assertEqual(current['field_source_identities']['account'],identity)
            for field in ['weapons','teammates','hero','rank']:
                self.assertFalse(current[field]);self.assertEqual(current['field_status'][field],'stale')
                self.assertEqual(current['field_source_identities'][field],old_identity)
            self.assertTrue({'rank','weapons'}<=set(current['refreshed_fields']))
            self.assertEqual(current['name_observations'],[])
            for key in ['hero_observations','hero_portrait_observations','rank_observations','visual_field_search','account_visibility_search']:
                self.assertFalse(current.get(key))
            self.assertEqual(result['clips'][1],before['clips'][1])
            fresh=self.fresh(['hero','rank'],hero={'id':'fuse','name':'暴雷'},rank={'tier':'diamond','division':'III'})
            with patch('hud_enrichment.recognize_video',return_value=fresh) as reader:
                result=enrich_manifest(root,[str(files[0])],['hero','rank'])
                reader.assert_called_once_with(files[0],['hero','rank'])
            current=result['clips'][0]['recognition']['hud_info']
            for field in ['hero','rank']:
                self.assertEqual(current[field],fresh[field]);self.assertEqual(current['field_source_identities'][field],identity)
                self.assertEqual(current['field_status'][field],'confirmed')

    def test_replaced_media_failed_read_keeps_old_fields_invalidated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root);files[0].write_bytes(b'replacement video')
            with patch('hud_enrichment.recognize_video',side_effect=RuntimeError('reader failed')):
                with self.assertRaisesRegex(RuntimeError,'reader failed'):
                    enrich_manifest(root,[str(files[0])],['account'])
            info=json.loads((root/'export.json').read_text('utf-8'))['clips'][0]['recognition']['hud_info']
            self.assertTrue(all(not info[field] for field in FIELDS))
            self.assertTrue(all(info['field_status'][field]=='stale' for field in FIELDS))
            self.assertEqual(info['name_observations'],[])
            self.assertTrue({'rank','weapons'}<=set(info['refreshed_fields']))

    def test_names_from_explicit_stale_field_or_replaced_unselected_media_are_not_reconciled(self):
        from hud_enrichment import reconcile_manifest_names
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root)
            first=manifest['clips'][0]['recognition']['hud_info'];identity=fingerprint(files[0])
            first['field_source_identities']={field:identity for field in FIELDS}
            first['field_source_identities']['account']={**identity,'size':identity['size']+1}
            files[1].write_bytes(b'replacement unselected video')
            with patch('hud_enrichment.consensus_name',return_value=None) as consensus:
                reconcile_manifest_names(manifest,['account'])
            self.assertEqual(consensus.call_args_list[0].args[0],[])
            self.assertFalse(any(value.get('name')=='old_wrong_account' for call in consensus.call_args_list for value in call.args[0]))
            # The global identity never makes an explicit old per-field binding current.
            (root/'export.json').write_text(json.dumps(manifest),'utf-8')
            with patch('hud_enrichment.recognize_video',return_value=self.fresh(['account'],account=None)) as reader:
                result=enrich_manifest(root,[str(files[0])],['account'])
                reader.assert_called_once_with(files[0],['account'])
            self.assertIsNone(result['clips'][0]['recognition']['hud_info']['account'])

    def test_rank_reader_version_rereads_only_selected_rank_and_unknown_is_authoritative(self):
        import rank_reader
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root);before=copy.deepcopy(manifest)
            manifest['clips'][0]['recognition']['rank']={'tier':'gold','division':'I'}
            (root/'export.json').write_text(json.dumps(manifest),'utf-8');fresh=self.fresh(['rank'],rank=None)
            with patch.object(rank_reader,'VERSION','new-rank-reader'),patch('hud_enrichment.recognize_video',return_value=fresh) as read:
                result=enrich_manifest(root,[str(files[0])],['rank'])
                read.assert_called_once_with(files[0],['rank'])
                self.assertEqual(result['clips'][0]['recognition']['hud_info']['field_versions']['rank'],field_version('rank'))
            current=result['clips'][0]['recognition']['hud_info'];old=before['clips'][0]['recognition']['hud_info']
            self.assertIsNone(current['rank']);self.assertEqual(current['field_status']['rank'],'unknown');self.assertIn('rank',current['refreshed_fields'])
            for field in ['account','teammates','weapons','hero']:
                self.assertEqual(current[field],old[field]);self.assertEqual(current['field_versions'][field],old['field_versions'][field])
            self.assertEqual(result['clips'][1],before['clips'][1])

    def test_visual_recipes_include_reader_and_asset_bytes_and_reuse_process_cache(self):
        from hud_enrichment import visual_field_recipe
        import hero_portrait_reader
        original=Path.read_bytes;rank_version=field_version('rank');hero_version=field_version('hero')
        with patch.object(Path,'read_bytes',side_effect=AssertionError('缓存命中不应重新读取资源')):
            self.assertEqual(field_version('rank'),rank_version);self.assertEqual(field_version('hero'),hero_version)
        with patch.object(hero_portrait_reader,'VERSION','new-portrait-reader'):
            self.assertNotEqual(field_version('hero'),hero_version)
        def changed(file):return original(file)+(b'changed' if file.name=='sources.json' and file.parent.name=='portraits' else b'')
        visual_field_recipe.cache_clear()
        try:
            with patch.object(Path,'read_bytes',new=changed):
                self.assertNotEqual(field_version('hero'),hero_version)
                self.assertEqual(field_version('rank'),rank_version)
        finally:visual_field_recipe.cache_clear()

    def test_refresh_replaces_confirmed_only_in_scope_and_drops_stale_name_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root);before=copy.deepcopy(manifest)
            fields=['account','weapons','rank'];fresh=self.fresh(fields,account=None,weapons=[],rank=None)
            with patch('hud_enrichment.recognize_video',return_value=fresh) as read:
                result=enrich_manifest(root,[str(files[0])],fields,force=True)
                read.assert_called_once_with(files[0],fields)
            clip=result['clips'][0];info=clip['recognition']['hud_info'];old=before['clips'][0]['recognition']['hud_info']
            self.assertIsNone(info['account']);self.assertEqual(info['weapons'],[]);self.assertIsNone(info['rank'])
            self.assertEqual(info['refreshed_fields'],fields)
            self.assertFalse(any(row.get('account') for row in info['name_observations']))
            self.assertTrue(any(row.get('teammates') for row in info['name_observations']))
            self.assertEqual(info['teammates'],old['teammates']);self.assertEqual(info['hero'],old['hero'])
            self.assertEqual(clip['summary'],before['clips'][0]['summary']);self.assertEqual(clip['segment'],before['clips'][0]['segment'])
            self.assertEqual(result['clips'][1],before['clips'][1])
            self.assertTrue(all(file.read_bytes()==b'exported video fixture' for file in files))

    def test_missing_preserves_confirmed_account_even_with_stronger_name_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root)
            for index,name in enumerate(['YURI Liiumeordis','[YURI] Liliumcordis']):
                info=manifest['clips'][index]['recognition']['hud_info']
                account={'name':name,'confidence':.85 if index==0 else .95}
                info['account']=account
                info['name_observations']=[{'time':i,'account':account} for i in range(3 if index==0 else 6)]
            before=copy.deepcopy(manifest)
            (root/'export.json').write_text(json.dumps(manifest),encoding='utf-8')
            with patch('hud_enrichment.recognize_video') as read:
                result=enrich_manifest(root,[str(files[0])],['account'])
                read.assert_not_called()
            self.assertEqual(result,before)


if __name__=='__main__':unittest.main()
