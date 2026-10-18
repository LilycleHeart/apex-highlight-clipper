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
    def test_whole_line_mean_and_conflicting_crop_cannot_certify_a_mixed_name(self):
        from combat_outcome_reader import native_name_consensus
        def read(frame,name,ctc):
            return {'name':name,'confidence':.96,'frame':frame,'boundary_evidence':{'method':'native_ctc_name_crop','box':[0,0,100,35],
                'ctc_name':ctc,'ctc_first_x':3,'ctc_last_x':97}}
        values=[read('one','甲乙3661','甲3561'),read('two','甲乙3661','甲乙3561')]
        values.extend({'name':'甲乙3561','confidence':.99,'frame':str(i)} for i in [3,4])
        self.assertIsNone(native_name_consensus(values))
        good=[read('one','甲乙3561','甲乙3561'),read('two','甲乙3561','甲乙3561')]
        self.assertEqual(native_name_consensus(good)['name'],'甲乙3561')
        cropped_short=[read('one','乙3561','乙3561'),read('two','乙3561','乙3561')]
        unresolved_long=[read('three','甲乙3561','乙3561'),read('four','甲乙3561','乙3561')]
        self.assertIsNone(native_name_consensus([*cropped_short,*unresolved_long]))
        middle_missing=[read('one','甲3561','甲3561'),read('two','甲3561','甲3561')]
        self.assertIsNone(native_name_consensus([*middle_missing,read('three','甲乙3561','甲3561')]))

    def test_verified_cross_frame_words_cannot_be_replaced_by_a_higher_single_frame_score(self):
        from combat_outcome_reader import unique_native_name_reads,native_name_consensus
        old={'name':'ALPHABETA','confidence':.99,'frame':'1.0','word_evidence':[{'name':'ALPHABETA'}]}
        fresh={'name':'ALPHA BETA','confidence':.91,'frame':'1.0','cross_pts_word_evidence':{'packet_sha256':'fixture'}}
        with patch('target_name_reader.complete_cross_pts_words',side_effect=lambda read:read is fresh):
            self.assertEqual(unique_native_name_reads([fresh,old]),[fresh])
            self.assertEqual(unique_native_name_reads([old,fresh]),[fresh])
        invalid=[{**fresh,'frame':str(i)} for i in range(2)]
        self.assertEqual(unique_native_name_reads(invalid),[])
        self.assertIsNone(native_name_consensus(invalid))

    def test_complete_independent_word_crops_resolve_coarse_spacing_and_score_fragments(self):
        from combat_outcome_reader import native_name_consensus
        def proved(frame,name='ALPHA BETA'):
            words=name.split();proof=[{'name':word,'box':[i*50,0,(i+1)*50,30],'models':[[{'name':word,'confidence':.97}],[{'name':word,'confidence':.98}]]} for i,word in enumerate(words)]
            width=len(words)*50
            return {'name':name,'confidence':.96,'frame':frame,'word_evidence':proof,
                'boundary_evidence':{'method':'native_ctc_name_crop','box':[0,0,width,30],'ctc_name':name.replace(' ',''),'ctc_first_x':3,'ctc_last_x':width-4}}
        rough=[{'name':name,'confidence':.98,'frame':str(i)} for i,name in enumerate(['ALPHABETA']*4+['ALPHABETAE','ALPHABETA100'])]
        physical=[proved('10'),proved('11')]
        self.assertEqual(native_name_consensus([*rough,*physical])['name'],'ALPHA BETA')
        self.assertIsNone(native_name_consensus([*rough,physical[0],physical[0]]))
        self.assertIsNone(native_name_consensus([*physical,proved('12','ALPHABETAE'),proved('13','ALPHABETAE')]))

    def test_assist_action_requires_complete_prefix_and_ignores_action_words_in_target(self):
        for text in ['助攻，倒PLAYER+100','助攻，X倒PLAYER+100','助攻，消A玩家+100','ASSIST PLAYER_ELIMINATED']:
            self.assertEqual(parse_result_line(text)['action'],'unknown')
        self.assertEqual(parse_result_line('擊倒 消滅玩家+150')['action'],'knock')
        self.assertEqual(parse_result_line('助攻，擊倒 PLAYER+100')['action'],'knock')
        self.assertEqual(parse_result_line('助攻，消滅 PLAYER+100')['action'],'elimination')

    def test_assist_template_filename_cannot_prove_action(self):
        from combat_outcome_reader import PrefixGate
        gate=PrefixGate.__new__(PrefixGate)
        gate.profile={'reference_size':[100,50],'toast_roi':[0,0,100,50]}
        template=np.arange(200,dtype=np.uint8).reshape(10,20)
        gate.templates=[({'kind':'assist','path':'assist-elimination-tc.png','sample_size':[100,50]},template)]
        image=np.zeros((50,100,3),np.uint8);image[10:20,30:50]=template[:,:,None]
        self.assertTrue(all(match['action']=='unknown' for match in gate.inspect(image)))

    def test_native_assist_action_needs_two_distinct_complete_uncontested_prefixes(self):
        from combat_outcome_reader import native_action_consensus
        read={'action':'knock','text':'助攻，擊倒 PLAYER+100','confidence':.96,'frame':'1.0'}
        self.assertIsNone(native_action_consensus([read,read]))
        second={**read,'frame':'1.3'}
        self.assertEqual(native_action_consensus([read,second]),'knock')
        conflicting={**read,'frame':'1.6','action':'elimination','text':'助攻，消滅 PLAYER'}
        self.assertIsNone(native_action_consensus([read,second,conflicting]))
        unknown=[{**read,'frame':str(i),'action':'elimination','text':'助攻，倒PLAYER+100'} for i in [1,2]]
        self.assertIsNone(native_action_consensus(unknown))

    def test_action_stroke_before_observed_clan_cannot_override_four_bare_name_reads(self):
        from combat_outcome_reader import native_name_consensus
        values=[{'name':'ALPHA BETA','raw_name':'[TEAM] ALPHA BETA','confidence':.95} for _ in range(4)]
        values.extend({'name':'I[TEAM] ALPHABETA','confidence':.97} for _ in range(2))
        self.assertEqual(native_name_consensus(values)['name'],'ALPHA BETA')
        # 没有实际首部标签，或 CTC/动作边界证明它属于姓名时，不能凭括号删字符。
        untagged=[{'name':'I[TEAM] ALPHABETA','confidence':.97} for _ in range(2)]
        self.assertEqual(native_name_consensus(untagged)['name'],'I[TEAM] ALPHABETA')
        anchored=[{**value,'boundary_evidence':{'verified_leading_name':True}} for value in untagged]
        self.assertIsNone(native_name_consensus([*values[:4],*anchored]))

    def test_longer_string_without_crop_evidence_does_not_delete_shorter_votes(self):
        from combat_outcome_reader import native_name_consensus
        short={'name':'TAIL1234','confidence':.96};long={'name':'XTAIL1234','confidence':.94}
        self.assertIsNone(native_name_consensus([short,short,short,long,long]))
        proved={**long,'word_evidence':[{'name':'XTAIL1234','box':[0,0,80,30],'models':[[{'name':'XTAIL1234','confidence':.96}],[{'name':'XTAIL1234','confidence':.97}]]}]}
        self.assertIsNone(native_name_consensus([short,short,short,proved,proved]))
        proved['boundary_evidence']={'method':'native_ctc_name_crop','box':[0,0,80,30],'ctc_name':'XTAIL1234','ctc_first_x':2,'ctc_last_x':78}
        self.assertEqual(native_name_consensus([short,short,short,proved,proved])['name'],'XTAIL1234')

    def test_complete_clan_words_outweigh_a_long_bracket_misread_without_full_extent(self):
        from combat_outcome_reader import native_name_consensus
        def read(frame):
            words=[{'name':name,'box':[i*40,0,(i+1)*40,30],'models':[[{'name':name,'confidence':.98}],[{'name':name,'confidence':.97}]]} for i,name in enumerate(['[TEAM]','BETA'])]
            return {'name':'BETA','raw_name':'[TEAM] BETA','confidence':.96,'frame':frame,'word_evidence':words,
                'boundary_evidence':{'method':'native_ctc_name_crop','box':[0,0,80,30],'ctc_name':'[TEAM]BETA','ctc_first_x':2,'ctc_last_x':78}}
        wrong={'name':'ITEAMIBETA','confidence':.98,'frame':'wrong','word_evidence':[{'name':'ITEAMIBETA','box':[0,0,80,30],'models':[[{'name':'ITEAMIBETA','confidence':.98}],[{'name':'ITEAMIBETA','confidence':.98}]]}],
            'boundary_evidence':{'method':'native_ctc_name_crop','box':[0,0,80,30],'ctc_name':'ITEAMIBETA','ctc_first_x':-2,'ctc_last_x':78}}
        self.assertEqual(native_name_consensus([read('one'),read('two'),wrong])['name'],'BETA')
        contradictory=read('two');contradictory['boundary_evidence']['ctc_name']='[OTHER]BETA'
        self.assertIsNone(native_name_consensus([read('one'),contradictory,wrong,dict(wrong,frame='other')]))

    def test_independent_terminal_shape_veto_applies_to_a_different_wrong_variant(self):
        from combat_outcome_reader import native_name_consensus
        evidence={'name':'甲123E','confidence':0.,'frame':'proof','boundary_evidence':{'method':'native_ctc_name_crop','box':[0,0,90,40]},
            'tail_evidence':{'conflict':True,'method':'independent_ascii_tail_and_native_counters','candidate_suffix':'123E','native_primary_suffix':'1238',
                'independent_reads':[{'name':'1238','confidence':.96,'terminal_confidence':.99,'padding':pad} for pad in [0,2]],
                'shape_evidence':{'method':'native_two_enclosed_counters','box':[70,8,12,24],
                    'observations':[{'threshold_fraction':threshold,'holes':[{'area':4.},{'area':5.}]} for threshold in [.25,.40]]}}}
        values=[{'name':'甲123日','confidence':.98,'frame':str(i)} for i in range(2)]
        self.assertIsNone(native_name_consensus([*values,evidence]))
        evidence['tail_evidence']['independent_reads'][1]['terminal_confidence']=.70
        self.assertEqual(native_name_consensus([*values,evidence])['name'],'甲123日')

    def test_visible_terminal_conflict_cannot_supply_a_consensus_vote(self):
        from combat_outcome_reader import native_name_consensus
        value={'name':'测试123E','confidence':.97,'tail_evidence':{'conflict':True}}
        self.assertIsNone(native_name_consensus([value,value]))

    def test_visible_name_punctuation_and_spaces_are_not_trimmed_or_counted_as_the_same_spelling(self):
        from combat_outcome_reader import native_name_consensus
        self.assertEqual(parse_result_line('KNOCKED DOWN ALPHA BETA... +150')['target_text'],'ALPHA BETA...')
        values=[{'name':name,'confidence':.96} for name in ['ALPHA BETA...','ALPHA BETA.','ALPHABETA...']]
        self.assertIsNone(native_name_consensus(values))
        self.assertIsNone(native_name_consensus([*values,values[0]]))
        self.assertEqual(native_name_consensus([values[0],values[0],values[1]])['name'],'ALPHA BETA...')

    def test_observed_square_glyph_cannot_be_dropped_by_more_truncated_reads(self):
        from combat_outcome_reader import native_name_consensus
        full={'name':'□EXAMPLE','confidence':.97,'shape_evidence':{'score':.9,'box':[1,10,8,8]}}
        self.assertIsNone(native_name_consensus([full,{'name':'EXAMPLE','confidence':.99},{'name':'EXAMPLE','confidence':.99}]))
        self.assertEqual(native_name_consensus([full,full,{'name':'EXAMPLE','confidence':.99}])['name'],'□EXAMPLE')
        chinese={'name':'□测试','confidence':.97,'shape_evidence':{'score':.9,'box':[1,10,8,8]}}
        self.assertEqual(native_name_consensus([chinese,chinese,*[{'name':'测','confidence':.99} for _ in range(3)]])['name'],'□测试')

    def test_tied_full_spellings_remain_unconfirmed(self):
        from combat_outcome_reader import native_name_consensus
        values=[{'name':name,'confidence':.96} for name in ['ALPHA1234','ALPHA1234','ALPHA1235','ALPHA1235']]
        self.assertIsNone(native_name_consensus(values))

    def test_two_truncated_names_do_not_override_a_clear_longer_prefix(self):
        from combat_outcome_reader import native_name_consensus
        values=[{'name':name,'confidence':.93} for name in ['哥5380','哥5380','鑫哥5380']]
        self.assertIsNone(native_name_consensus(values))
        values=[{'name':name,'confidence':.93} for name in ['鑫哥5380','鑫哥5380','哥5380']]
        self.assertEqual(native_name_consensus(values)['name'],'鑫哥5380')

    def test_japanese_glyph_alias_only_normalizes_action_prefix(self):
        value=parse_result_line('撃倒 撃田+150')
        self.assertEqual((value['kind'],value['target_text']),('knock','撃田'))
        self.assertEqual(parse_result_line('助攻，撃倒 PLAYER+100')['action'],'knock')
        self.assertIsNone(parse_result_line('角色：我被撃倒了'))
        self.assertTrue(is_known_dialogue('角色：我被撃倒了'))

    def test_numeric_enemy_account_is_not_discarded_as_points(self):
        self.assertEqual(parse_result_line('擊倒 3213124124325+150')['target_text'],'3213124124325')
        self.assertEqual(parse_result_line('KNOCKED DOWN 12345678 +150')['target_text'],'12345678')
        self.assertEqual(parse_result_line('擊倒 +150')['target_text'],'')

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
    def test_word_fallback_only_uses_cached_native_crops_of_the_selected_event(self):
        self._assert_cached_word_fallback(['ALPHABETA','ALPHA BETA'])

    def test_word_fallback_keeps_actual_clan_and_hyphen_inputs(self):
        self._assert_cached_word_fallback(['[TEAM]ALPHABETA','[TEAM]ALPHA BETA'],'TEAM')
        self._assert_cached_word_fallback(['2SHOTS OF A-B','2 SHOTS OF A-B'])

    def _assert_cached_word_fallback(self,read_names,clan=None):
        from combat_outcome_reader import native_target_names
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'clip.mp4';source.write_bytes(b'fixture');image=np.zeros((100,300,3),np.uint8);moments=[]
            original={'kind':'knock','time':1.,'last_seen':1.4,'target_text':'OLD','confirmed':True}
            neighbor={'kind':'knock','time':1.5,'last_seen':2.,'target_text':'OTHER','confirmed':True}
            def frames(source,start,end,requested=None):moments.extend(requested);return iter([(requested[0]+.01,image)])
            names=iter(read_names)
            def recognize(*args,**kwargs):
                return {'events':[{'kind':'knock','target_text':next(names),'text_confidence':.97,
                    'target_boundary_evidence':{'method':'native_ctc_name_crop','box':[32,30,160,60],'ctc_name':'ALPHABETA','prefix_anchor':'template','prefix_box':[1,30,31,60],**({'clan_tag':clan} if clan else {})}}]}
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('combat_outcome_reader.probe',return_value=({'format':{'duration':5}},{})),patch('combat_outcome_reader.inactive_view',return_value=False),patch('combat_outcome_reader.new_engine',return_value=object()),patch('combat_outcome_reader.recognize_frame',side_effect=recognize),patch('target_name_reader.model_available',return_value=False),patch('target_name_reader.TargetNameReader.refine_latin_words',return_value=[]) as refine:
                value=native_target_names(source,[original],context_events=[original,neighbor])[0]
            self.assertEqual(len(moments),2);refine.assert_called_once()
            probes=refine.call_args.args[0]
            self.assertEqual(len(probes),2);self.assertEqual(len({item['native_pts'] for item in probes}),2)
            self.assertTrue(all(item['source']==fingerprint(source) and item['event_key'][0:2]==['knock',1.] and item['context_bounds'][1]<1.5 and item['image'].shape==(30,128,3) for item in probes))
            self.assertEqual(value['native_name_status'],'unconfirmed');self.assertEqual(value['time'],1.)

    def test_native_action_uses_full_neighbor_context_when_only_one_event_is_selected(self):
        from combat_outcome_reader import native_target_names
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'clip.mp4';source.write_bytes(b'fixture');image=np.zeros((500,1000,3),np.uint8);requested=[]
            selected={'kind':'assist','time':1.,'last_seen':1.,'action':'unknown','text':'助攻，倒 ALPHA','target_text':'ALPHA'}
            next_event={'kind':'assist','time':1.2,'last_seen':2.,'action':'elimination','native_name_status':'confirmed','target_text':'BRAVO'}
            def frames(source,start,end,moments=None):requested.extend(moments);return iter([(moments[0]+.01,image)])
            read={'events':[{'kind':'assist','action':'knock','text':'助攻，擊倒 ALPHA','target_text':'ALPHA','confidence':.97,'text_confidence':.97}]}
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('combat_outcome_reader.probe',return_value=({'format':{'duration':5}},{})),patch('combat_outcome_reader.inactive_view',return_value=False),patch('combat_outcome_reader.new_engine',return_value=object()),patch('combat_outcome_reader.recognize_frame',return_value=read),patch('target_name_reader.model_available',return_value=False):
                result=native_target_names(source,[selected],context_events=[selected,next_event])
            self.assertTrue(all(second<1.2 for second in requested));self.assertEqual(len(requested),1)
            self.assertEqual(result[0]['native_action_status'],'unconfirmed')

    def test_native_action_checks_terminal_phase_of_a_short_merged_assist(self):
        from combat_outcome_reader import native_target_names
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'clip.mp4';source.write_bytes(b'fixture');image=np.zeros((500,1000,3),np.uint8);current=[0.]
            original={'kind':'assist','time':1.,'last_seen':2.,'action':'elimination','text':'助攻，擊倒 ALPHA','target_text':'ALPHA','confirmed':True}
            def frames(source,start,end,moments=None):current[0]=moments[0];return iter([(moments[0]+.01,image)])
            def recognize(*args,**kwargs):
                action='elimination' if current[0]>=2. else 'knock';word='消滅' if action=='elimination' else '擊倒'
                return {'events':[{'kind':'assist','action':action,'text':f'助攻，{word} ALPHA','target_text':'ALPHA','confidence':.97,'text_confidence':.97}]}
            duration=[5.]
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('combat_outcome_reader.probe',side_effect=lambda source:({'format':{'duration':duration[0]}},{})),patch('combat_outcome_reader.inactive_view',return_value=False),patch('combat_outcome_reader.new_engine',return_value=object()),patch('combat_outcome_reader.recognize_frame',side_effect=recognize):
                result=native_target_names(source,[original])[0]
                self.assertEqual(result['action'],'elimination');self.assertEqual(result['native_action_status'],'confirmed')
                self.assertEqual(result['native_action_phases'],{'start':'knock','terminal':'elimination'})
                self.assertEqual(result['native_action_terminal_window'],'post_last_seen')
                duration[0]=2.2
                pending=native_target_names(source,[original])[0]
            self.assertEqual(pending['action'],'elimination');self.assertEqual(pending['native_action_status'],'unconfirmed_merged_track')
            self.assertEqual((pending['time'],pending['last_seen']),(1.,2.))

    def test_native_terminal_reads_precede_the_observed_toast_fade(self):
        from combat_outcome_reader import native_target_names
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'clip.mp4';source.write_bytes(b'fixture');image=np.zeros((500,1000,3),np.uint8);current=[0.];requested=[]
            event={'kind':'assist','time':1.,'last_seen':5.,'action':'elimination','text':'助攻，消滅 ALPHA','target_text':'ALPHA','confirmed':True}
            def frames(source,start,end,moments=None):current[0]=moments[0];requested.extend(moments);return iter([(moments[0]+.01,image)])
            def recognize(*args,**kwargs):
                if current[0]>=5.:return {'events':[]}
                action='elimination' if current[0]>=4.5 else 'knock';word='消滅' if action=='elimination' else '擊倒'
                return {'events':[{'kind':'assist','action':action,'text':f'助攻，{word} ALPHA','target_text':'ALPHA','confidence':.97,'text_confidence':.97}]}
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('combat_outcome_reader.probe',return_value=({'format':{'duration':8}},{})),patch('combat_outcome_reader.inactive_view',return_value=False),patch('combat_outcome_reader.new_engine',return_value=object()),patch('combat_outcome_reader.recognize_frame',side_effect=recognize):
                result=native_target_names(source,[event])[0]
            self.assertEqual(result['action'],'elimination');self.assertEqual(result['native_action_status'],'confirmed')
            self.assertEqual(result['native_action_terminal_requested'],[4.68,4.92]);self.assertEqual(result['native_action_terminal_window'],'pre_last_seen')
            self.assertTrue(all(second<5. for second in requested))

    def test_native_assist_corrects_action_pairs_phases_and_preserves_event_identity(self):
        from combat_outcome_reader import native_target_names
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'clip.mp4';source.write_bytes(b'fixture');image=np.zeros((500,1000,3),np.uint8)
            originals=[{'kind':'assist','action':'elimination','time':1.,'last_seen':2.,'confirmed':True,'target_text':'OLD'},
                       {'kind':'assist','action':'elimination','time':4.,'last_seen':5.,'confirmed':True,'target_text':'OLD'}]
            current=[0.]
            def frames(source,start,end,moments=None):current[0]=moments[0];return iter([(moments[0]+.01,image)])
            def read(*args,**kwargs):
                action='knock' if current[0]<4 else 'elimination';word='擊倒' if action=='knock' else '消滅'
                return {'events':[{'kind':'assist','action':action,'text':f'助攻，{word} ALPHA BETA','target_text':'ALPHA BETA','confidence':.97,'text_confidence':.97}]}
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('combat_outcome_reader.probe',return_value=({'format':{'duration':8}},{})),patch('combat_outcome_reader.inactive_view',return_value=False),patch('combat_outcome_reader.new_engine',return_value=object()),patch('combat_outcome_reader.recognize_frame',side_effect=read):
                result=native_target_names(source,originals)
            self.assertEqual([event['action'] for event in result],['knock','elimination'])
            self.assertEqual(result[0]['native_action_pair'],result[1]['native_action_pair'])
            for old,new in zip(originals,result):
                for key in ['kind','time','last_seen','confirmed']:self.assertEqual(new[key],old[key])
            self.assertEqual(originals[0]['action'],'elimination')

    def test_native_target_only_removes_clan_fragment_when_another_frame_has_brackets(self):
        from combat_outcome_reader import native_target_names
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'clip.mp4';source.write_bytes(b'fixture');image=np.zeros((500,1000,3),np.uint8)
            original={'kind':'knock','time':1.,'target_text':'UWU顾北辰'};names=[]
            def frames(source,start,end,moments=None):return iter([(moments[0]+.01,image)])
            def recognize(*args,**kwargs):return {'events':[{'kind':'knock','target_text':names.pop(0),'text_confidence':.97}]}
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('combat_outcome_reader.probe',return_value=({'format':{'duration':5}},{})),patch('combat_outcome_reader.inactive_view',return_value=False),patch('combat_outcome_reader.new_engine',return_value=object()),patch('combat_outcome_reader.recognize_frame',side_effect=recognize):
                names[:]=['UWU顾北辰']*3
                self.assertEqual(native_target_names(source,[original])[0]['target_text'],'UWU顾北辰')
                names[:]=['UWU顾北辰','UWU顾北辰','[UWU]顾北辰']
                self.assertEqual(native_target_names(source,[original])[0]['target_text'],'顾北辰')
                names[:]=['UWU顾北辰','UWU顾北辰','[UWU】顾北辰']
                self.assertEqual(native_target_names(source,[original])[0]['target_text'],'顾北辰')

    def test_native_target_recheck_preserves_event_timing_and_classification(self):
        from combat_outcome_reader import native_target_names
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'clip.mp4';source.write_bytes(b'fixture')
            image=np.zeros((1080,2560,3),np.uint8)
            original={'kind':'knock','time':1.,'last_seen':2.,'confirmed':True,'target_text':'小湖干','frame':'000003.jpg'}
            def frames(source,start,end,moments=None):return iter([(moments[0]+.01,image)])
            result={'events':[{'kind':'knock','target_text':'小胡子鲨鱼','text_confidence':.97}], 'lines':[]}
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('combat_outcome_reader.probe',return_value=({'format':{'duration':5}},{})),patch('combat_outcome_reader.inactive_view',return_value=False),patch('combat_outcome_reader.new_engine',return_value=object()),patch('combat_outcome_reader.recognize_frame',return_value=result):
                fresh=native_target_names(source,[original])[0]
            self.assertEqual(fresh['target_text'],'小胡子鲨鱼')
            for key in ['kind','time','last_seen','confirmed','frame']:self.assertEqual(fresh[key],original[key])
            self.assertEqual(original['target_text'],'小湖干')

    def test_missing_prefix_refines_nearby_but_unrelated_names_do_not_trigger_extra_reads(self):
        from combat_outcome_reader import native_target_names
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'clip.mp4';source.write_bytes(b'fixture');image=np.zeros((500,1000,3),np.uint8)
            original={'kind':'knock','time':1.,'confirmed':True,'target_text':'old'}
            def frames(source,start,end,moments=None):return iter([(moments[0]+.001,image)])
            names=[]
            def read(*args,**kwargs):return {'events':[{'kind':'knock','target_text':names.pop(0),'text_confidence':.97}]}
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('combat_outcome_reader.probe',return_value=({'format':{'duration':5}},{})),patch('combat_outcome_reader.inactive_view',return_value=False),patch('combat_outcome_reader.new_engine',return_value=object()),patch('combat_outcome_reader.recognize_frame',side_effect=read) as recognize:
                names[:]=['tail1234','tail1234','Xtail1234']+['Xtail1234']*5
                fresh=native_target_names(source,[original])[0]
                self.assertEqual(fresh['target_text'],'Xtail1234');self.assertEqual(fresh['native_name_status'],'confirmed');self.assertEqual(recognize.call_count,8)
                recognize.reset_mock();names[:]=['ALPHA1234','BRAVO5678','CHARLIE9012']
                fresh=native_target_names(source,[original])[0];self.assertEqual(fresh['native_name_status'],'unconfirmed');self.assertEqual(recognize.call_count,3)

    def test_native_target_never_borrows_another_kind_or_another_row(self):
        from combat_outcome_reader import native_target_names
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'clip.mp4';source.write_bytes(b'fixture');image=np.zeros((500,1000,3),np.uint8)
            original={'kind':'knock','time':1.,'confirmed':True,'target_text':'kept_name'}
            def frames(source,start,end,moments=None):return iter([(moments[0]+.01,image)])
            result={'events':[{'kind':'assist','target_text':'wrong_kind','text_confidence':.99},{'kind':'knock','target_text':'other_a','text_confidence':.99},{'kind':'knock','target_text':'other_b','text_confidence':.99}]}
            with patch('hud_enrichment.native_frames',side_effect=frames),patch('combat_outcome_reader.probe',return_value=({'format':{'duration':5}},{})),patch('combat_outcome_reader.inactive_view',return_value=False),patch('combat_outcome_reader.new_engine',return_value=object()),patch('combat_outcome_reader.recognize_frame',return_value=result):
                fresh=native_target_names(source,[original])[0]
            self.assertEqual(fresh['target_text'],'kept_name');self.assertEqual(fresh['native_name_status'],'unconfirmed')

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
