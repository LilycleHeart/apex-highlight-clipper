import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from numeric_reader import agreed_number


class NumericConsensusTests(unittest.TestCase):
    def digit_reader(self):
        from numeric_reader import NumericReader
        reader=NumericReader.__new__(NumericReader);reader.glyphs=SimpleNamespace(decode_numeric_alias=lambda *args:None)
        def read(images):return [('70',.99) if not image[0,0,0] else ('710' if image[0,0,0]==1 else '720',.98) for image in images],0.
        reader.readers=[read,read,read];return reader

    def test_longer_read_requires_models_and_the_same_number_of_visible_glyphs(self):
        image=np.zeros((20,40,3),np.uint8);view=np.ones_like(image)
        proof={'image':view,'glyph_count':3,'threshold':240,'boxes':[[0,0,5,10],[7,0,9,10],[11,0,16,10]]}
        with patch('stat_counter_fallback.separated_digit_views',return_value=[proof]):
            reader=self.digit_reader();result,_=reader([image]);self.assertEqual(result,[('710',.98)])
            self.assertEqual(reader.last_digit_reviews[0]['previous'],'70')
        with patch('stat_counter_fallback.separated_digit_views',return_value=[{**proof,'glyph_count':4}]):
            self.assertEqual(self.digit_reader()([image])[0],[('70',.99)])

    def test_conflicting_geometry_supported_words_are_not_picked_by_magnitude(self):
        image=np.zeros((20,40,3),np.uint8)
        proofs=[{'image':np.full_like(image,level),'glyph_count':3,'threshold':220+level,'boxes':[]} for level in [1,2]]
        with patch('stat_counter_fallback.separated_digit_views',return_value=proofs):
            self.assertEqual(self.digit_reader()([image])[0],[('',0.)])

    def test_three_independent_model_reads_can_use_geometry_from_another_threshold(self):
        image=np.zeros((20,40,3),np.uint8);view=np.ones_like(image)
        proofs=[{'image':view,'glyph_count':count,'threshold':level,'boxes':[]} for count,level in [(2,200),(3,240)]]
        reader=self.digit_reader()
        def model(confidence,word='710'):
            return lambda images:([('70',.99) if not value[0,0,0] else (word,confidence) for value in images],0.)
        reader.readers=[model(.93),model(.93),model(.98)]
        with patch('stat_counter_fallback.separated_digit_views',return_value=proofs):
            self.assertEqual(reader([image])[0],[('710',.93)])
            reader.readers[-1]=model(.98,'720')
            self.assertEqual(reader([image])[0],[('70',.99)])

    def test_two_models_override_one_confident_wrong_digit(self):
        text,confidence=agreed_number([('1881',.99),('1981',.975),('1981',.994)])
        self.assertEqual(text,'1981');self.assertEqual(confidence,.975)

    def test_two_strong_readings_are_not_revoked_by_a_weaker_agreeing_model(self):
        text,confidence=agreed_number([('0',.948),('0',.895),('0',.973)])
        self.assertEqual(text,'0');self.assertEqual(confidence,.948)
        # 一张高分不能抬高另外两张低分；消费者仍会拒绝未过阈值的两票。
        self.assertEqual(agreed_number([('0',.895),('0',.894),('0',.999)]),('0',.895))

    def test_one_model_or_split_votes_cannot_confirm_a_number(self):
        self.assertEqual(agreed_number([('18',.999),('',0),('8',.99)]),('',0.))
        self.assertEqual(agreed_number([('18',.999),('8',.99),('18',.5)]),('',0.))
        self.assertEqual(agreed_number([('18',.99),('18',.99),('8',.99),('8',.99)]),('',0.))

    def test_empty_and_nonnumeric_crops_do_not_invent_zero(self):
        self.assertEqual(agreed_number([('',0),('B',.99),('²',.99)]),('',0.))


if __name__=='__main__':unittest.main()
