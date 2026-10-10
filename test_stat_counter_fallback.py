import unittest
import cv2
import numpy as np
from pathlib import Path
from stat_counter_fallback import CounterFallback,digit_view,BASE
from sample_locations import SampleResolver
import tempfile
import json

class CounterTests(unittest.TestCase):
    def test_empty_patch_does_not_invent_zero(self):
        self.assertIsNone(digit_view(np.zeros((15,12,3),np.uint8)))
    def test_numeric_alias_requires_exact_glyph_and_rejects_eight_as_six(self):
        reader=CounterFallback()
        zero=cv2.imread(str(BASE/'templates/statistics/digit-0.png'),0)
        eight=cv2.imread(str(BASE/'templates/statistics/digit-8.png'),0)
        def view(mask):return cv2.cvtColor(cv2.copyMakeBorder(255-mask,8,8,8,8,cv2.BORDER_CONSTANT,value=255),cv2.COLOR_GRAY2BGR)
        self.assertEqual(reader.decode_numeric_alias('D',view(zero)),'0')
        self.assertEqual(reader.decode_numeric_alias('B',view(eight)),'8')
    def test_original_samples_found_only_when_source_identity_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);primary=root/'gap-fill/samples';primary.mkdir(parents=True);(root/'samples').mkdir()
            (root/'samples/000001.jpg').write_bytes(b'frame');source={'path':'A.mp4','size':1}
            (root/'hud.json').write_text(json.dumps({'source':source}),encoding='utf-8')
            self.assertTrue(SampleResolver({'source':source},primary).path('000001.jpg').is_file())
            self.assertFalse(SampleResolver({'source':{'path':'B.mp4'}},primary).path('000001.jpg').is_file())
            self.assertFalse(SampleResolver({'source':source},primary).path('../private.jpg').is_file())
