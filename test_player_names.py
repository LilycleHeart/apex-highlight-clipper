import unittest
import tempfile
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from player_names import player_name,consensus_name,canonical_name
from hud_enrichment import reconcile_manifest_names,recorded_match_keys,VERSION


class PlayerNameTests(unittest.TestCase):
    def test_all_fields_unknown_still_complete_bounded_reads(self):
        from hud_enrichment import recognize_video,FIELDS
        from hud_layout import make_profile
        image=np.zeros((1080,1920,3),dtype=np.uint8)
        profile=make_profile(1920,1080)
        def frames(source,start,end,moments=None):
            return iter((time,image) for time in (moments or [1.,4.,8.]))
        def empty(crops):return [('',0.) for _ in crops],0.
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'clip.mp4';source.write_bytes(b'fixture')
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('hud_enrichment.probe',return_value=({'format':{'duration':10}},{})),patch('hud_enrichment.inactive_view',return_value=False),patch('engine_pool.pooled_engine',return_value=SimpleNamespace(text_rec=empty)),patch('weapon_reader.WeaponTextReader',return_value=empty),patch('hero_reader.HeroReader') as hero,patch('rank_reader.RankReader') as rank:
                hero.return_value.inspect.return_value=None;rank.return_value.inspect.return_value=None
                activity=[];result=recognize_video(source,FIELDS,profile=profile,on_activity=activity.append)
        self.assertEqual(result['checked_frames'],6)
        self.assertTrue(all(v=='unknown' for v in result['field_status'].values()))
        self.assertEqual(activity[-1]['frames_done'],6)

    def test_same_player_evidence_can_correct_confident_ocr_without_merging_other_players(self):
        weak={'name':'[YURI] Liiumeordis','confidence':.96}
        real={'name':'[YURI] Liliumcordis','confidence':.95,'votes':8}
        self.assertEqual(canonical_name(weak,real)['name'],'Liiumeordis')
        self.assertEqual(canonical_name(weak,real,same_player=True)['name'],'Liliumcordis')
        self.assertEqual(canonical_name({'name':'落生','confidence':.97},{'name':'落生烬','confidence':.95,'votes':12},same_player=True)['name'],'落生烬')
        self.assertEqual(canonical_name({'name':'[YURI] LilycleHeart','confidence':.99},real,same_player=True)['name'],'LilycleHeart')

    def test_fixed_hud_text_and_conflicting_names_are_not_confirmed(self):
        for text in ['MAX LEVEL','下個等級 749 進化','造成150伤害','KNOCKED DOWN','\ufffd口□']:
            self.assertEqual(player_name(text),'')
        values=[{'name':name,'confidence':.95} for name in ['PLAYER_ONE','PLAYER_ONE','OTHER_NAME','OTHER_NAME']]
        self.assertIsNone(consensus_name(values))
        for value in ['YURI] Liliumcordis','[YURI]Liliumcordis','[YURI Liliumcordis']:
            self.assertEqual(player_name(value),'Liliumcordis')
        self.assertEqual(player_name('[BILI天才美少女软软'),'天才美少女软软')

    def test_numeric_ids_and_edge_placeholder_do_not_hide_readable_teammates(self):
        self.assertEqual(player_name('1234567890'),'1234567890')
        self.assertEqual(player_name('□Player_One'),'Player_One')
        self.assertEqual(player_name('Player□One'),'')
        self.assertEqual(player_name('123'),'')

    def test_account_aliases_reconcile_with_real_repeated_name_and_teammates_stay_per_match(self):
        real={'name':'[YURI] Liliumcordis','confidence':.95}
        weak={'name':'YURI] Liiumeordis','confidence':.85}
        def clip(key,value,team):
            return {'recognition':{'match_key':key,'hud_info':{'version':VERSION,'account':value,'teammates':[team],
                'name_observations':[{'account':value,'teammates':[team]} for _ in range(3)]}}}
        team={'name':'badya','confidence':.95,'slot':0}
        manifest={'clips':[clip('a',real,team),clip('a',weak,team),clip('b',real,{'name':'other','confidence':.95,'slot':0})]}
        reconcile_manifest_names(manifest)
        self.assertEqual(manifest['clips'][1]['recognition']['hud_info']['account']['name'],'Liliumcordis')
        self.assertEqual(manifest['clips'][2]['recognition']['hud_info']['teammates'][0]['name'],'other')
        self.assertEqual(canonical_name({'name':'PLAYER_TWO','confidence':.99},{'name':'PLAYER_ONE','confidence':.99,'votes':6})['name'],'PLAYER_TWO')

    def test_same_match_corrects_raw_frames_despite_one_low_confidence_frame(self):
        def clip(name,confidences):
            return {'recognition':{'match_key':'same-match','hud_info':{'version':VERSION,
                'teammates':[{'name':name,'slot':1,'confidence':min(confidences),'votes':len(confidences)}],
                'name_observations':[{'teammates':[{'name':name,'slot':1,'confidence':confidence}]} for confidence in confidences]}}}
        clips=[clip('[BILI]天才美少女软软',[.84,.97,.98]),clip('[BIL]天才美少女软软',[.96,.97,.98]),clip('[BILI]天才美少软软',[.99,.99,.99])]
        reconcile_manifest_names({'clips':clips})
        self.assertEqual([c['recognition']['hud_info']['teammates'][0]['name'] for c in clips],['天才美少女软软']*3)

    def test_legacy_clips_use_verified_analysis_rounds_without_crossing_round_end(self):
        def clip(start,name,frames):
            value={'name':name,'slot':0,'confidence':.97}
            return {'segment':{'start':start,'end':start+10},'recognition':{'hud_info':{'version':VERSION,
                'teammates':[value],'name_observations':[{'teammates':[value]} for _ in range(frames)]}}}
        clips=[clip(0,'PLAYER_ONE',6),clip(20,'PLAYER_0NE',3),clip(40,'PLAYER_ONF',3)]
        source={'path':'original.mp4','size':100,'mtime_ns':1};manifest={'source':source,'clips':clips}
        analysis={'source':source,'outcome_events':[{'time':35}], 'segments':[c['segment'] for c in clips]}
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'analysis.json';path.write_text(json.dumps(analysis),'utf-8')
            keys=recorded_match_keys(manifest,temporary)
            self.assertEqual(keys[id(clips[0])],keys[id(clips[1])])
            self.assertNotEqual(keys[id(clips[0])],keys[id(clips[2])])
            reconcile_manifest_names(manifest,match_keys=keys)
            self.assertEqual([c['recognition']['hud_info']['teammates'][0]['name'] for c in clips],['PLAYER_ONE','PLAYER_ONE','PLAYER_ONF'])
            analysis['source']={**source,'mtime_ns':2};path.write_text(json.dumps(analysis),'utf-8')
            self.assertEqual(recorded_match_keys(manifest,temporary),{})
            path.write_text('[]','utf-8')
            self.assertEqual(recorded_match_keys(manifest,temporary),{})
