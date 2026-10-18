import unittest
from unittest.mock import patch
import numpy as np

import japanese_name_reader as names


class KanaReviewTests(unittest.TestCase):
    def test_small_kana_family_preserves_other_character_differences(self):
        self.assertEqual(names.kana_family('あゃの'),names.kana_family('あやの'))
        self.assertNotEqual(names.kana_family('あゃの'),names.kana_family('あらの'))
        self.assertTrue(names.has_kana('山の上'));self.assertFalse(names.has_kana('ABCD中文'))

    def sample(self,small):
        image=np.zeros((60,63,3),np.uint8)
        for index in range(3):image[20 if small and index==1 else 10:50,5+index*21:16+index*21]=255
        class Reader:
            session=object();resize_norm_img=object();rec_image_shape=[3,48,320];postprocess_op=object()
            def __init__(self,text):self.text=text
            def __call__(self,images):return [(self.text,.99) for _ in images],0.
        primary=Reader('あやの');independent=Reader('あゃの');review=names.JapaneseNameReader(primary);review.reader=independent
        def tokens(image,reader):return [(char,9+i*21,12+i*21) for i,char in enumerate(reader.text)]
        with patch.object(names,'model_available',return_value=True),patch.object(names,'ctc_tokens',side_effect=tokens):
            return review([image,image],{'name':'あやの','confidence':.98})

    def test_full_size_glyph_is_not_changed_by_a_confident_word_model(self):
        value=self.sample(False)
        self.assertEqual(value['name'],'あやの')
        self.assertEqual(value['japanese_evidence']['glyphs'][0]['observed_size'],'large')
        self.assertFalse(value.get('japanese_review_pending'))

    def test_small_glyph_requires_actual_size_evidence_and_keeps_raw_reading(self):
        value=self.sample(True)
        self.assertEqual(value['name'],'あゃの');self.assertEqual(value['raw_name'],'あやの')
        self.assertEqual(value['japanese_evidence']['glyphs'][0]['observed_size'],'small')

    def test_blank_or_missing_reference_glyphs_cannot_determine_size(self):
        self.assertIsNone(names.size_evidence([],0))
        self.assertIsNone(names.size_evidence([{'character':'ゃ','box':[0,0,10,10]}],0))


if __name__=='__main__':unittest.main()
