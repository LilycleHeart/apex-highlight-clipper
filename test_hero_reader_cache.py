from collections import OrderedDict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import hero_reader as hero


class HeroReaderCacheTests(unittest.TestCase):
    def reader(self):
        reader=hero.HeroReader.__new__(hero.HeroReader)
        glyph=np.zeros((30,25),np.uint8);glyph[4:26,10:15]=255;glyph[12:17,3:22]=255
        reader.templates=[('pathfinder','tactical',glyph)]
        reader.contrast_templates=[];reader._scaled=OrderedDict()
        return reader,glyph

    def test_repeated_inspection_reuses_scaled_templates_and_keeps_exact_scores(self):
        reader,glyph=self.reader();image=np.zeros((100,180,3),np.uint8)
        resized=cv2.resize(glyph,(33,40),interpolation=cv2.INTER_AREA)
        image[30:70,74:107]=resized[:,:,None]
        profile={'reference_size':[180,100],'hero_tactical_roi':[0,0,180,100],'hero_ultimate_roi':[0,0,180,100]}
        with patch('hero_reader.cv2.resize',wraps=cv2.resize) as resize,patch('hero_reader.cv2.matchTemplate',wraps=cv2.matchTemplate) as match:
            first=reader.inspect(image,profile);scores=reader.last_scores.copy();calls=resize.call_count
            matches=match.call_count
            second=reader.inspect(image,profile)
            self.assertEqual(resize.call_count,calls);self.assertGreater(calls,0)
            self.assertEqual(match.call_count,matches);self.assertGreater(matches,0)
        self.assertEqual(first,second);self.assertEqual(reader.last_scores,scores)
        self.assertEqual(first['id'],'pathfinder')

    def test_shape_changes_invalidate_scaled_variants_and_cache_stays_bounded(self):
        reader,_=self.reader()
        for height in range(100,106):
            reader._prepared('tactical',(height,180,3),{'reference_size':[180,100]},(height,180,3))
        self.assertEqual(len(reader._scaled),4)
        self.assertTrue(all(key[1][0]>=102 for key in reader._scaled))

    def test_asset_edits_invalidate_shared_template_bank(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(hero,'BASE',Path(tmp)):
            root=Path(tmp)/'assets/legends';root.mkdir(parents=True)
            (root/'sources.json').write_text(json.dumps({'legends':[{'id':'pathfinder','abilities':{'tactical':{'file':'glyph.png'}}}]}),'utf-8')
            image=np.zeros((20,20,4),np.uint8);image[4:16,4:16,3]=255
            cv2.imwrite(str(root/'glyph.png'),image)
            first=hero.HeroReader();second=hero.HeroReader()
            self.assertIs(first._scaled,second._scaled)
            image[2:18,2:18,3]=255;cv2.imwrite(str(root/'glyph.png'),image)
            third=hero.HeroReader()
            self.assertIsNot(first._scaled,third._scaled)
            self.assertNotEqual(first.templates[0][2].shape,third.templates[0][2].shape)


if __name__=='__main__':unittest.main()
