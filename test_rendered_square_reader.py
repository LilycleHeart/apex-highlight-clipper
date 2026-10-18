import copy
import unittest
from unittest.mock import Mock

import cv2
import numpy as np

from rendered_square_reader import read_rendered_tail,square_candidates


class RenderedSquareReaderTests(unittest.TestCase):
    def sample(self,*,height=10,score=False):
        image=np.zeros((40,180 if score else max(78,67+height),3),np.uint8)
        for x,letter in [(3,'A'),(20,'B'),(37,'O')]:
            cv2.putText(image,letter,(x,28),cv2.FONT_HERSHEY_SIMPLEX,.7,(225,225,225),1,cv2.LINE_AA)
        cv2.rectangle(image,(60,29-height),(59+height,28),(225,225,225),1)
        if score:cv2.putText(image,'+100',(84,28),cv2.FONT_HERSHEY_SIMPLEX,.7,(225,225,225),1,cv2.LINE_AA)
        return image

    def tokens(self,*,square=False,body='ABO',weak=False,score=False):
        values=[{'character':character,'left':left,'right':right,'confidence':.96 if index==0 else .99} for index,(character,left,right) in enumerate(zip(body,[8.,25.,42.],[13.,30.,47.]))]
        if weak:values[0]['confidence']=.7
        if square:values.append({'character':'o','left':65.,'right':69.,'confidence':.4})
        if score:
            values.extend({'character':character,'left':float(86+12*i),'right':float(91+12*i),'confidence':.99} for i,character in enumerate('+100'))
        return values

    def read(self,image,first=None,second=None):
        english=object();independent=object()
        call=Mock(side_effect=lambda original,model:copy.deepcopy(first if model is english else second))
        result=read_rendered_tail(image,english,independent,ctc=call)
        return result,call

    def test_no_geometric_candidate_never_calls_recognizers(self):
        ctc=Mock(side_effect=AssertionError('must not infer'))
        self.assertIsNone(read_rendered_tail(np.zeros((40,100,3),np.uint8),object(),object(),ctc=ctc))
        ctc.assert_not_called()

    def test_actual_round_letters_score_plus_and_icon_are_not_square_shapes(self):
        for label in ['O','0','+100']:
            image=np.zeros((40,100,3),np.uint8)
            cv2.putText(image,label,(4,28),cv2.FONT_HERSHEY_SIMPLEX,.7,(225,225,225),1,cv2.LINE_AA)
            self.assertEqual(square_candidates(image),[],label)
        image=np.zeros((40,100,3),np.uint8)
        cv2.polylines(image,[np.array([[40,16],[48,8],[56,16],[48,12]],np.int32)],False,(225,225,225),2)
        cv2.line(image,(5,28),(25,28),(225,225,225),1)
        self.assertEqual(square_candidates(image),[])

    def test_shape_maps_only_extra_terminal_emission_and_retains_real_O(self):
        image=self.sample();before=image.copy()
        result,called=self.read(image,self.tokens(square=True),self.tokens())
        self.assertIsNotNone(result)
        self.assertEqual(result['name'],'ABO□')
        self.assertEqual(result['confidence'],.96)
        self.assertGreaterEqual(result['shape_evidence']['score'],.82)
        self.assertEqual(result['views'][0]['square_mapping']['actual_emitted_character'],'o')
        self.assertEqual(result['views'][0]['square_mapping']['mapped_text'],'ABOo')
        self.assertIsNone(result['views'][1]['square_mapping'])
        self.assertEqual(result['views'][0]['body_tokens'][-1]['character'],'O')
        self.assertEqual(result['shape_evidence']['requires_distinct_native_pts'],2)
        self.assertEqual(result['shape_evidence']['method'],'native_trailing_rendered_square')
        self.assertEqual(result['shape_evidence']['raw_variants'],['ABOo','ABO'])
        self.assertNotIn('confirmed',result)
        self.assertTrue(np.array_equal(image,before))
        self.assertEqual(called.call_count,2)
        self.assertTrue(all(call.args[0] is image for call in called.call_args_list))

    def test_two_models_omitting_symbol_cannot_attach_a_background_square(self):
        self.assertIsNone(self.read(self.sample(),self.tokens(),self.tokens())[0])

    def test_missing_weak_nonlatin_or_disagreeing_body_is_rejected(self):
        for first,second in [(None,self.tokens()),(self.tokens(weak=True),self.tokens()),(self.tokens(body='甲乙口'),self.tokens(body='甲乙口')),(self.tokens(),self.tokens(body='ABP'))]:
            with self.subTest(first=first,second=second):
                self.assertIsNone(self.read(self.sample(),first,second)[0])

    def test_score_or_icon_beyond_the_square_cannot_enter_the_body(self):
        result,_=self.read(self.sample(score=True),self.tokens(square=True,score=True),self.tokens(square=True,score=True))
        self.assertIsNone(result)
        image=self.sample(score=True)
        result,_=self.read(image,self.tokens(square=True),self.tokens())
        self.assertIsNone(result)

    def test_full_height_mouth_shape_is_not_a_small_trailing_symbol(self):
        image=self.sample(height=19)
        self.assertTrue(square_candidates(image))
        self.assertIsNone(self.read(image,self.tokens(square=True),self.tokens())[0])


if __name__=='__main__':unittest.main()
