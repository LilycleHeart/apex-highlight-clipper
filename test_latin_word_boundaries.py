import copy
import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

import latin_word_boundaries as words
import target_name_reader as reader


class WordModel:
    def __init__(self):self.calls=0
    def __call__(self,images):
        self.calls+=1
        return [(('AB' if image.shape[1]<60 else 'CD'),.97) for image in images],0.


class CrossPtsLatinWordsTests(unittest.TestCase):
    def test_white_and_gray_word_pixels_keep_the_original_red_signal_and_thresholds(self):
        for color in [(255,255,255),(150,150,150)]:
            image=np.zeros((36,120,3),np.uint8)
            cv2.putText(image,'AB CD',(2,26),cv2.FONT_HERSHEY_SIMPLEX,.7,color,2,cv2.LINE_AA)
            signal,proof=words._foreground(image)
            self.assertEqual(proof['method'],'neutral_luma_highpass')
            self.assertEqual(proof['threshold'],max(20.,proof['peak']*.25))
            self.assertGreaterEqual(proof['letter_components'],2)
        image=self.probes()[0]['image'];b,g,r=cv2.split(image.astype(np.int16))
        expected=np.maximum(0,r-np.maximum(g,b)).astype(np.float32)
        expected=np.maximum(0,expected-cv2.morphologyEx(expected,cv2.MORPH_OPEN,np.ones((7,7),np.uint8)))
        actual,proof=words._foreground(image)
        np.testing.assert_array_equal(actual,expected);self.assertNotIn('method',proof)
        self.assertIsNone(words._foreground(np.full((36,120,3),150,np.uint8)))
        colored=np.zeros((36,120,3),np.uint8)
        cv2.putText(colored,'AB CD',(2,26),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,0,0),2,cv2.LINE_AA)
        self.assertIsNone(words._foreground(colored))

    def probes(self):
        image=np.zeros((36,120,3),np.uint8)
        cv2.putText(image,'AB',(2,26),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,0,230),2,cv2.LINE_AA)
        cv2.putText(image,'CD',(72,26),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,0,230),2,cv2.LINE_AA)
        return [{'source':{'path':'C:\\fixture.mp4','size':10,'mtime_ns':1000000},'event_key':('knock',10.,(50,80,150,96)),'phase':'start',
            'native_pts':second,'requested_time':second-.01,'context_bounds':[.8,2.],
            'boundary':{'method':'native_ctc_name_crop','box':[38,80,158,116],'prefix_anchor':'template','prefix_box':[10,80,37,114],'ctc_name':'AX CD','ctc_first_x':40.,'ctc_last_x':141.},
            'image':image.copy(),'crop_sha256':hashlib.sha256(image.tobytes()).hexdigest(),'name':'ABCD','confidence':.96-index*.01} for index,second in enumerate([1.,1.2])]

    def run_refinement(self,probes=None):
        primary=SimpleNamespace();english=WordModel();independent=WordModel();primary._apex_latin_reader=english
        model=reader.TargetNameReader(primary);model.latin_reader=independent
        def ctc(image,recognizer):
            return [{'character':character,'left':left,'right':right,'confidence':.99} for character,left,right in [('A',2.,14.),('X' if recognizer is primary else 'B',17.,29.),(' ',48.,56.),('C',74.,86.),('D',90.,103.)]]
        def identity(recognizer):return words.WORD_MODEL_SHAS[0 if recognizer is english else 1]
        with patch.object(reader,'model_available',return_value=True),patch.object(reader,'_reader_model_sha',side_effect=identity),patch.object(reader,'ctc_evidence',side_effect=ctc) as tokens,patch.object(reader,'foreground_views',return_value=[]),patch('gpu_ocr_backend.create_ocr_engine',side_effect=AssertionError('reuse current readers')):
            result=model.refine_latin_words(self.probes() if probes is None else probes)
        return result,english,independent,tokens.call_count

    def structured_refinement(self,spelling,primary_spelling=None):
        names=spelling.split(' ');height=36;cursor=2;tokens=[];pieces=[]
        for index,name in enumerate(names):
            width=cv2.getTextSize(name,cv2.FONT_HERSHEY_SIMPLEX,.7,2)[0][0]
            pieces.append((name,cursor));step=width/len(name)
            tokens.extend({'character':char,'left':cursor+i*step,'right':cursor+(i+1)*step,'confidence':.99} for i,char in enumerate(name))
            cursor+=width
            if index<len(names)-1:tokens.append({'character':' ','left':cursor,'right':cursor+20.,'confidence':.99});cursor+=20
        image=np.zeros((height,cursor+2,3),np.uint8)
        for name,left in pieces:cv2.putText(image,name,(left,26),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,0,230),2,cv2.LINE_AA)
        probes=self.probes()
        for probe in probes:
            probe.update(name=spelling,image=image.copy(),crop_sha256=hashlib.sha256(image.tobytes()).hexdigest())
            probe['boundary'].update(box=[38,80,38+image.shape[1],116],ctc_name=primary_spelling or spelling)
            if spelling.startswith('['):probe['boundary']['clan_tag']=(primary_spelling or spelling)[1:].split(']')[0]
        class ScriptedModel:
            def __init__(self):self.calls=0
            def __call__(self,images):
                name=names[self.calls%len(names)];self.calls+=1
                return [(name,.97) for _ in images],0.
        primary=SimpleNamespace();english=ScriptedModel();independent=ScriptedModel();primary._apex_latin_reader=english
        model=reader.TargetNameReader(primary);model.latin_reader=independent
        def ctc(image,recognizer):
            result=copy.deepcopy(tokens)
            if recognizer is primary and primary_spelling:
                self.assertEqual(len(primary_spelling),len(spelling))
                for token,char in zip(result,primary_spelling):token['character']=char
            return result
        with patch.object(reader,'model_available',return_value=True),patch.object(reader,'_reader_model_sha',side_effect=lambda r:words.WORD_MODEL_SHAS[0 if r is english else 1]),patch.object(reader,'ctc_evidence',side_effect=ctc),patch.object(reader,'foreground_views',return_value=[]):
            result=model.refine_latin_words(probes)
        return result

    def test_actual_interface_keeps_primary_and_reads_both_pts_with_two_models(self):
        probes=self.probes();boundaries=copy.deepcopy([p['boundary'] for p in probes]);pixels=[p['image'].tobytes() for p in probes]
        result,english,independent,tokens=self.run_refinement(probes)
        self.assertEqual(len(result),2);self.assertEqual({r['name'] for r in result},{'AB CD'})
        self.assertTrue(all(reader.complete_cross_pts_words(r) for r in result));self.assertEqual(tokens,6)
        self.assertEqual(english.calls,4);self.assertEqual(independent.calls,4)
        self.assertEqual([p['boundary'] for p in probes],boundaries);self.assertEqual([p['image'].tobytes() for p in probes],pixels)
        for read in result:
            self.assertEqual(read['boundary_evidence']['ctc_name'],'AX CD')
            self.assertEqual(''.join(t['character'] for t in read['cross_pts_word_evidence']['packet']['frames'][0]['full_crop_observations'][0]['tokens']),'AX CD')
            self.assertEqual(read['native_word_binding']['source'],probes[0]['source'])

    def test_invalid_probe_scope_or_white_foreground_never_loads_or_reads_models(self):
        mutations=[lambda p:p[1].update(event_key=('knock',11.)),lambda p:p[1].update(phase='terminal'),lambda p:p[1].update(source={'path':'other','size':10,'mtime_ns':1000000}),
            lambda p:p[1].update(native_pts=1.,requested_time=.99),lambda p:p[1].update(requested_time=.5),lambda p:p[1]['boundary'].update(clan_tag='BAD-TAG'),lambda p:p[1].update(name='AB.CD'),lambda p:p[1].update(name='甲乙')]
        for mutate in mutations:
            probes=self.probes();mutate(probes)
            with self.subTest(mutation=mutate),patch.object(reader,'_reader_model_sha',side_effect=AssertionError('no weight reads')),patch.object(reader,'ctc_evidence',side_effect=AssertionError('no OCR')):
                self.assertEqual(reader.TargetNameReader(object()).refine_latin_words(probes),[])
        probes=self.probes()
        for probe in probes:
            probe['image'][:]=255;probe['crop_sha256']=hashlib.sha256(probe['image'].tobytes()).hexdigest()
        with patch.object(reader,'ctc_evidence',side_effect=AssertionError('no OCR')):self.assertEqual(reader.TargetNameReader(object()).refine_latin_words(probes),[])

    def test_complete_validator_binds_current_read_and_all_paired_proofs(self):
        base=self.run_refinement()[0][0]
        external=[lambda r:r['native_word_binding'].update(event_key=['other']),lambda r:r['native_word_binding']['source'].update(size=11),lambda r:r['native_word_binding'].update(phase='terminal'),lambda r:r.update(time=1.1),lambda r:r.update(time=True),lambda r:r.update(frame='different'),lambda r:r['boundary_evidence']['box'].__setitem__(0,39),lambda r:r['native_word_binding'].update(crop_sha256='0'*64)]
        for mutate in external:
            changed=copy.deepcopy(base);mutate(changed);self.assertFalse(reader.complete_cross_pts_words(changed))
        packet_mutations=[lambda p:p['frames'][1].update(native_pts=1.),lambda p:p.update(word_models=[words.WORD_MODEL_SHAS[0]]*2),
            lambda p:p['frames'][0]['words'][0]['box'].__setitem__(0,1),lambda p:p['frames'][0]['words'][0]['models'].__setitem__(1,[]),
            lambda p:p['frames'][0]['foreground'].update(letter_components=0),lambda p:p['cut_proof'][0]['actual_spaces'][0].update(token_index=0),
            lambda p:p['frames'][0]['full_crop_observations'][2]['tokens'][0].update(character='Z'),lambda p:p['cut_proof'][0]['valleys'][0].update(signal=255)]
        for mutate in packet_mutations:
            changed=copy.deepcopy(base);packet=changed['cross_pts_word_evidence']['packet'];mutate(packet);changed['cross_pts_word_evidence']['packet_sha256']=words._hash(packet)
            self.assertFalse(reader.complete_cross_pts_words(changed))

    def test_three_best_probes_bound_full_crop_reads(self):
        probes=self.probes()
        for index,second in enumerate([1.4,1.6]):
            probe=copy.deepcopy(probes[0]);probe.update(native_pts=second,requested_time=second-.01,confidence=.9-index*.01);probes.append(probe)
        result,_,_,tokens=self.run_refinement(probes)
        self.assertEqual(len(result),2);self.assertEqual(tokens,9)

    def test_isolated_high_confidence_probe_does_not_displace_a_pairable_cluster(self):
        probes=self.probes()
        third=copy.deepcopy(probes[0]);third.update(native_pts=1.4,requested_time=1.39,confidence=.90)
        isolated=copy.deepcopy(probes[0]);isolated.update(native_pts=3.,requested_time=2.99,confidence=.999)
        probes.extend([third,isolated])
        for probe in probes:probe['context_bounds']=[.8,4.]
        prepared=words.prepare_probes(probes)
        self.assertEqual({probe['native_pts'] for probe in prepared},{1.,1.2,1.4})
        result,_,_,tokens=self.run_refinement(probes)
        self.assertEqual(len(result),2);self.assertEqual(tokens,9)

    def test_single_observed_internal_space_cannot_be_silently_merged(self):
        prepared=words.prepare_probes(self.probes())
        tokens=[{'character':character,'left':left,'right':right,'confidence':.99} for character,left,right in [('A',2.,14.),('B',17.,29.),(' ',48.,56.),('C',74.,86.),('D',90.,103.)]]
        for probe in prepared:probe['_full']=[{'model':label,'tokens':copy.deepcopy(tokens)} for label in ['primary',*words.WORD_MODEL_SHAS]]
        prepared[0]['_full'][1]['tokens'].insert(1,{'character':' ','left':14.,'right':17.,'confidence':.51})
        self.assertIsNone(words._plan(prepared))

    def test_native_gap_left_of_delayed_ctc_space_is_checked_in_the_same_bounded_window(self):
        prepared=words.prepare_probes(self.probes())
        tokens=[{'character':char,'left':left,'right':right,'confidence':.99} for char,left,right in [('A',2.,20.),(' ',50.,60.),('B',94.,105.)]]
        for probe in prepared:
            probe['_red'][:]=100.;probe['_red'][:,49:52]=0.
            probe['_foreground'].update(peak=100.,threshold=25.)
            probe['_full']=[{'model':label,'tokens':copy.deepcopy(tokens)} for label in ['primary',*words.WORD_MODEL_SHAS]]
        cuts,proof=words._plan(prepared)
        self.assertEqual(cuts,[[50],[50]])
        self.assertTrue(all(v['signal']==0 for v in proof[0]['valleys']))
        for probe in prepared:probe['_red'][:]=100.;probe['_red'][:,39:42]=0.
        self.assertIsNone(words._plan(prepared))

    def test_packet_validator_rejects_an_omitted_internal_space(self):
        changed=copy.deepcopy(self.run_refinement()[0][0]);packet=changed['cross_pts_word_evidence']['packet'];frame=packet['frames'][0]
        frame['full_crop_observations'][0]['tokens'].insert(1,{'character':' ','left':14.,'right':17.,'confidence':.51})
        for cut in packet['cut_proof']:
            for support in cut['actual_spaces']:
                if support['native_pts']==frame['native_pts'] and support['model']=='primary':support['token_index']+=1
        changed['cross_pts_word_evidence']['packet_sha256']=words._hash(packet)
        self.assertFalse(reader.complete_cross_pts_words(changed))

    def test_supported_grammar_keeps_only_internal_hyphens_and_one_head_clan(self):
        for name in ['7 SHIFT OF BETA-GAMMA AGAIN','[TAG] ALPHA BETA','[TAG]ALPHA BETA','ONE TWO THREE FOUR FIVE SIX']:
            self.assertTrue(words.supports_word_spacing(name),name)
        for name in ['ALPHA- BETA','ALPHA--BETA','-ALPHA BETA','ALPHA [TAG]BETA','[TAG]','[TAG] [TAG]ALPHA','[TAG ALPHA','TAG]ALPHA','[TOOLONG]ALPHA','ALPHA.BETA','甲乙',' ALPHA','ALPHA ']:
            self.assertFalse(words.supports_word_spacing(name),name)

    def test_numeric_first_word_hyphen_and_six_words_keep_two_model_proof(self):
        for spelling in ['7 SHIFT OF BETA-GAMMA AGAIN','ONE TWO THREE FOUR FIVE SIX']:
            reads=self.structured_refinement(spelling)
            self.assertEqual(len(reads),2,spelling);self.assertEqual({r['name'] for r in reads},{spelling})
            self.assertTrue(all(reader.complete_cross_pts_words(r) for r in reads))
        self.assertIsNone(words._agreement([[{'name':'A-B','confidence':.97}],[{'name':'AB','confidence':.97}]]))
        self.assertIsNone(words._agreement([[{'name':'7','confidence':.89}],[{'name':'7','confidence':.89}]]))

    def test_clan_is_independently_read_and_raw_binding_survives_existing_stripping(self):
        from player_names import strip_clan_tag
        for spelling,primary in [('[TAG] ALPHA BETA','[OLD] ALPHA BETA'),('[TAG]ALPHA BETA','[OLD]ALPHA BETA')]:
            reads=self.structured_refinement(spelling,primary)
            self.assertEqual(len(reads),2,spelling)
            for original in reads:
                self.assertEqual(original['name'],spelling);self.assertEqual(original['raw_name'],spelling)
                self.assertEqual(original['boundary_evidence']['ctc_name'],primary)
                self.assertTrue(reader.complete_cross_pts_words(original))
                bare=copy.deepcopy(original);bare['name']=strip_clan_tag(spelling)
                self.assertTrue(reader.complete_cross_pts_words(bare))
                bare['raw_name']='[TAG] OTHER'
                self.assertFalse(reader.complete_cross_pts_words(bare))
        self.assertIsNone(words._agreement([[{'name':'[TAG]ALPHA','confidence':.97}],[{'name':'[TAG]ALPHA','confidence':.97}]],first=False))


if __name__=='__main__':unittest.main()
