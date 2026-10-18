from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import combat_candidate_completion as completion
from combat_outcome_reader import parse_result_line


class CandidateCompletionTests(unittest.TestCase):
    def run_case(self,*,texts=None,confidence=.97,gate_score=.94,own=True,duplicate_pts=False,next_time=None,event_box=None,decode_offset=.01,template_dx=0,kind='knock',action='knock',association_conflict=False):
        texts=texts or ['擊倒 ALPHA+150']*3
        original={'kind':kind,'action':action,'time':1.,'last_seen':1.,'box':[50,80,250,96],'sample_size':[400,200],
            'confirmed':False,'ownership':'self','target_text':'KEEP_OLD','target_confidence':0.,'native_name_status':'unconfirmed'}
        context=[original]
        if next_time is not None:context.append({'kind':kind,'time':next_time,'last_seen':next_time+.5,'confirmed':True})
        image=np.zeros((200,400,3),np.uint8);requests=[];current=[0]
        pixels=np.random.default_rng(42).normal(size=(20,100)).astype(np.float32)
        box=event_box or [50,80,250,96]
        def frames(source,start,end,moments=None):
            current[0]=len(requests);requests.extend(moments)
            return iter([(1.01 if duplicate_pts else moments[0]+decode_offset,image)])
        def recognize(*args,**kwargs):
            text=texts[min(current[0],len(texts)-1)]
            event=parse_result_line(text) or {'kind':'knock','action':'knock','target_text':'ALPHA','text':text}
            event={**event,'text':text,'confidence':confidence,'text_confidence':confidence,'target_read_confidence':.9999,'box':box}
            return {'events':[event],'lines':[{'text':text,'box':box,'confidence':confidence}]}
        gate=SimpleNamespace(inspect=lambda image:[{'kind':kind,'action':'unknown' if kind=='assist' else kind,'score':gate_score,'box':[box[0]+template_dx,box[1],box[0]+template_dx+28,box[3]]}])
        english=({'type':'english_complete_prefix_grammar','ctc_prefix':'KNOCKED DOWN ','box':[50,80,140,96]},pixels)
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'clip.mp4';source.write_bytes(b'fixture')
            if association_conflict:
                identity=completion.fingerprint(source)
                original.update(target_text='ALPHA',native_name_status='confirmed',native_name_version=completion.PARSER_VERSION,
                    target_method='two_frame_native_name_consensus',native_name_source={'path':str(source),'size':identity['size'],'mtime_ms':identity['mtime_ns']//1000000},
                    native_name_evidence=[{'name':'ALPHA','confidence':.96,'time':second,'boundary_evidence':{'prefix_box':[50,80,78,96]}} for second in [.92,1.08]])
                context.append({**original,'time':1.5,'last_seen':2.,'confirmed':True,
                    'native_name_evidence':[{**read,'time':read['time']+.5} for read in original['native_name_evidence']]})
            with patch.object(completion,'probe',return_value=({'format':{'duration':5}},{})),patch.object(completion,'native_frames',side_effect=frames),patch.object(completion,'inactive_view',return_value=not own),patch.object(completion,'friend_view',return_value=False),patch.object(completion,'spectator_view',return_value=False),patch.object(completion,'PrefixGate',return_value=gate),patch.object(completion,'new_engine',return_value=SimpleNamespace(text_rec=object())) as create,patch.object(completion,'recognize_frame',side_effect=recognize),patch.object(completion,'_english_prefix',return_value=english):
                result=completion.complete_candidates(source,[original],context_events=context,profile={'reference_size':[400,200],'toast_roi':[0,0,400,200]})
        return result[0],original,requests,create.call_count

    def test_only_false_candidates_are_completed_and_original_fields_are_preserved(self):
        result,original,requests,_=self.run_case()
        self.assertTrue(result['confirmed']);self.assertFalse(original['confirmed']);self.assertEqual(len(requests),2)
        self.assertEqual(result['native_event_version'],completion.VERSION)
        self.assertEqual(result['native_event_recipe'],completion.recipe());self.assertIs(result['native_event_original_confirmed'],False)
        self.assertEqual(len({read['native_pts'] for read in result['native_event_evidence']}),2)
        for key,value in original.items():
            if key!='confirmed':self.assertEqual(result[key],value)
        self.assertTrue(all(not read['name_accuracy_verified'] for read in result['native_event_evidence']))
        confirmed={**original,'confirmed':True};missing={key:value for key,value in original.items() if key!='confirmed'}
        with patch.object(completion,'new_engine',side_effect=AssertionError('already-confirmed path')),patch.object(completion,'fingerprint',side_effect=AssertionError('no media read')),patch.object(completion,'recipe',side_effect=AssertionError('no recipe reads')):
            self.assertEqual(completion.complete_candidates('unused',[confirmed,missing],context_events=[]),[confirmed,missing])

    def test_recipe_is_lazy_cached_stable_and_does_not_construct_ocr(self):
        completion.recipe.cache_clear()
        try:
            with patch.object(completion,'new_engine',side_effect=AssertionError('recipe must not initialize OCR')),patch.object(completion,'_recipe_file',wraps=completion._recipe_file) as read:
                first=completion.recipe();reads=read.call_count;second=completion.recipe()
                self.assertEqual(first,second);self.assertTrue(first.startswith(completion.VERSION+':'))
                self.assertGreater(reads,10);self.assertEqual(read.call_count,reads)
                self.assertEqual(completion.recipe.cache_info().hits,1)
        finally:completion.recipe.cache_clear()

    def test_names_cannot_supply_missing_prefix_view_or_position_evidence(self):
        for settings in [{'confidence':.60},{'gate_score':.60},{'own':False},{'event_box':[50,130,250,146]},{'template_dx':70}]:
            with self.subTest(settings=settings):self.assertFalse(self.run_case(**settings)[0]['confirmed'])

    def test_duplicate_pts_and_different_targets_never_confirm(self):
        result,_,requests,_=self.run_case(duplicate_pts=True)
        self.assertFalse(result['confirmed']);self.assertLessEqual(len(requests),3)
        result,_,_,_=self.run_case(texts=['擊倒 ALPHA+150','擊倒 BRAVO+150','擊倒 CHARLIE+150'])
        self.assertFalse(result['confirmed'])

    def test_complete_context_prevents_borrowing_a_later_same_kind_event(self):
        result,_,requests,_=self.run_case(next_time=1.04)
        self.assertFalse(result['confirmed']);self.assertEqual(requests,[.92])
        result,_,_,_=self.run_case(next_time=1.20,decode_offset=.14)
        self.assertFalse(result['confirmed'])
        self.assertTrue(any(read.get('reason')=='decoded_outside_candidate_context' for read in result['native_event_evidence']))
        candidate={'kind':'knock','time':1.,'box':[50,80,250,96],'confirmed':False,'ownership':'self'}
        with self.assertRaisesRegex(ValueError,'完整相邻事件上下文'):
            completion.complete_candidates('unused',[candidate],context_events=[])

    def test_same_native_target_and_position_do_not_prove_an_independent_neighbour_event(self):
        result,original,requests,engines=self.run_case(association_conflict=True)
        self.assertFalse(result['confirmed']);self.assertEqual(result['native_event_status'],'unconfirmed')
        self.assertEqual(requests,[]);self.assertEqual(engines,0)
        conflict=result['native_event_association_conflict'][0]
        self.assertEqual(conflict['reason'],'independent_event_not_proven');self.assertTrue(conflict['duplicate_not_established'])
        self.assertEqual(conflict['confirmed_neighbour']['time'],1.5)
        self.assertEqual(result['native_name_status'],'confirmed');self.assertEqual(result['time'],original['time'])
        self.assertNotIn('native_event_confirmation',result)

    def test_another_known_assist_phase_cannot_confirm_the_original_candidate(self):
        result,original,_,_=self.run_case(kind='assist',action='knock',texts=['助攻，消滅 ALPHA+100']*3)
        self.assertFalse(result['confirmed']);self.assertEqual(result['action'],original['action'])

    def test_english_uses_its_own_full_grammar_evidence_not_a_weaker_chinese_gate(self):
        result,_,requests,_=self.run_case(texts=['KNOCKED DOWN ALPHA+150']*3,gate_score=.20)
        self.assertTrue(result['confirmed']);self.assertEqual(len(requests),2)
        self.assertEqual(result['native_event_confirmation']['type'],'english_full_grammar_with_native_prefix_persistence')
        self.assertTrue(all(read['same_row_fixed_template_score']==.20 for read in result['native_event_evidence']))
        self.assertEqual(self.run_case(texts=['KNOCKED DOWN ALPHA+150']*3,confidence=.89)[0]['confirmed'],False)

    def test_speaker_subtitles_and_negative_prefixes_are_not_own_toasts(self):
        for text in ['角色：我被擊倒 ALPHA','Announcer: KNOCKED DOWN ALPHA','I WAS KNOCKED DOWN ALPHA','YOU WERE ELIMINATED ALPHA']:
            with self.subTest(text=text):self.assertFalse(self.run_case(texts=[text]*3,gate_score=.99)[0]['confirmed'])

    def test_prefix_pixel_persistence_does_not_pass_blank_or_unrelated_content(self):
        pixels=np.random.default_rng(23).normal(size=(25,120)).astype(np.float32)
        other=np.random.default_rng(24).normal(size=(25,120)).astype(np.float32)
        a={'_prefix_pixels':pixels};same={'_prefix_pixels':pixels.copy()}
        self.assertGreater(completion._prefix_agreement(a,same)['score'],.99)
        self.assertLess(completion._prefix_agreement(a,{'_prefix_pixels':other})['score'],completion.MIN_PREFIX_PERSISTENCE)
        self.assertIsNone(completion._prefix_agreement({'_prefix_pixels':np.zeros_like(pixels)},{'_prefix_pixels':np.zeros_like(pixels)}))

    def test_source_change_is_rejected_even_when_classification_would_pass(self):
        event={'kind':'knock','time':1.,'box':[50,80,250,96],'confirmed':False,'ownership':'self'}
        with patch.object(completion,'fingerprint',side_effect=[{'size':1,'mtime_ns':0},{'size':2,'mtime_ns':1}]),patch.object(completion,'probe',return_value=({'format':{'duration':5}},{})),patch.object(completion,'PrefixGate',return_value=object()),patch.object(completion,'native_frames',return_value=iter([])):
            with self.assertRaisesRegex(ValueError,'原录像发生变化'):
                completion.complete_candidates('unused',[event],context_events=[event],profile={'reference_size':[400,200],'toast_roi':[0,0,400,200]})


if __name__=='__main__':unittest.main()
