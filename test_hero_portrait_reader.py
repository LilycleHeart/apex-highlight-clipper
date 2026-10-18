from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

import numpy as np

from hero_portrait_reader import confirm_video_portrait,portrait_features


class HeroPortraitTests(unittest.TestCase):
    def run_frames(self,times,values,spectator=False):
        image=np.zeros((1080,1920,3),np.uint8);reader=Mock();reader.signature='fixture'
        reader.inspect.side_effect=values
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'clip.mp4';source.write_bytes(b'fixture')
            with patch('hero_portrait_reader.portrait_reader',return_value=reader),patch('hud_enrichment.native_frames',return_value=iter((time,image) for time in times)),patch('apex_clipper.probe',return_value=({'format':{'duration':10}},{})),patch('apex_clipper.inactive_view',return_value=False),patch('outcome_reader.spectator_view',return_value=spectator):
                result=confirm_video_portrait(source,{'layout_status':'confirmed'})
        return result,reader

    def value(self,ident='pathfinder'):
        return {'id':ident,'confidence':.99,'portrait_evidence':{'score':.99}}

    def test_one_decoded_frame_cannot_be_counted_twice(self):
        result,_=self.run_frames([1.,1.,1.],[self.value()])
        self.assertIsNone(result['hero'])

    def test_conflicting_clear_portraits_are_not_reduced_to_a_majority(self):
        result,_=self.run_frames([1.,2.,3.],[self.value(),self.value(),self.value('loba')])
        self.assertIsNone(result['hero'])

    def test_spectator_frames_cannot_confirm_an_otherwise_matching_portrait(self):
        result,reader=self.run_frames([1.,2.,3.],[],spectator=True)
        self.assertIsNone(result['hero']);reader.inspect.assert_not_called()

    def test_lone_clear_portrait_uses_adjacent_distinct_frames(self):
        image=np.zeros((1080,1920,3),np.uint8);reader=Mock();reader.signature='fixture'
        reader.inspect.side_effect=[None,self.value(),None,self.value(),self.value()]
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'clip.mp4';source.write_bytes(b'fixture')
            with patch('hero_portrait_reader.portrait_reader',return_value=reader),patch('hud_enrichment.native_frames',side_effect=[iter((time,image) for time in [1.,2.,3.]),iter((time,image) for time in [1.96,2.04])]),patch('apex_clipper.probe',return_value=({'format':{'duration':10}},{})),patch('apex_clipper.inactive_view',return_value=False),patch('outcome_reader.spectator_view',return_value=False):
                result=confirm_video_portrait(source,{'layout_status':'confirmed'})
        self.assertEqual(result['hero']['id'],'pathfinder');self.assertEqual(result['hero']['votes'],3)

    def test_blank_and_uniform_overlays_have_no_portrait_features(self):
        self.assertIsNone(portrait_features(np.zeros((48,56,3),np.uint8)))
        self.assertIsNone(portrait_features(np.full((48,56,3),255,np.uint8)))


if __name__=='__main__':unittest.main()
