import unittest
import cv2
import numpy as np
from pathlib import Path
from stat_counter_fallback import CounterFallback,digit_view,BASE
from sample_locations import SampleResolver
import tempfile
import json

class CounterTests(unittest.TestCase):
    def test_digit_span_skips_icon_edge_and_slash(self):
        from stat_counter_fallback import digit_span
        patch=np.zeros((30,40,3),np.uint8)
        patch[5:25,0:3]=255                        # 贴左缘的图标残边
        patch[6:24,12:20]=255;patch[9:21,14:18]=0   # 数字 0
        for y in range(4,26):patch[y,36-(y-4)//3]=255  # 斜分隔线
        left,right=digit_span(patch)
        self.assertGreaterEqual(left,3);self.assertLessEqual(left,12)
        self.assertGreaterEqual(right,20);self.assertLess(right,28)
        self.assertIsNone(digit_span(np.zeros((30,40,3),np.uint8)))

    def test_digit_separation_rejects_blank_background_and_keeps_a_text_line(self):
        from stat_counter_fallback import separated_digit_views
        self.assertEqual(separated_digit_views(np.zeros((40,90,3),np.uint8)),[])
        self.assertEqual(separated_digit_views(np.full((40,90,3),255,np.uint8)),[])
        image=np.zeros((40,90,3),np.uint8)
        for x,width in [(10,12),(30,5),(45,12)]:image[8:30,x:x+width]=255
        views=separated_digit_views(image)
        self.assertTrue(views);self.assertTrue(all(view['glyph_count']==3 for view in views))

    def test_small_regions_do_not_keep_entire_decoded_video_frames_alive(self):
        profile=json.loads((BASE/'profile-ultrawide.json').read_text('utf-8'))
        image=np.zeros((1080,2560,3),np.uint8)
        regions=CounterFallback().regions(image,profile,(0,0))
        self.assertIn('damage',regions)
        self.assertFalse(np.shares_memory(regions['damage'],image))
        self.assertLess(regions['damage'].nbytes,20000)

    def test_touching_glyphs_are_spaced_using_a_thin_projection_bridge(self):
        from stat_counter_fallback import separated_digit_views
        image=np.zeros((50,100,3),np.uint8)
        image[10:40,10:24]=255
        for x in [35,53]:
            cv2.line(image,(x,10),(x+18,10),(255,255,255),3)
            cv2.line(image,(x+18,10),(x+3,38),(255,255,255),3)
        views=separated_digit_views(image)
        self.assertTrue(views)
        self.assertTrue(all(view['glyph_count']==3 for view in views))
        self.assertTrue(all(view.get('touching_glyphs_separated') for view in views))
        # 分隔只移动现有笔画，不增加或抹掉数字前景。
        self.assertTrue(all(np.count_nonzero(view['image'][:,:,0]==0)==np.count_nonzero(image[:,:,0]) for view in views))

    def test_wide_solid_component_cannot_prove_one_short_glyph(self):
        from stat_counter_fallback import separated_digit_views
        image=np.zeros((50,100,3),np.uint8)
        image[10:40,10:24]=255;image[10:40,35:75]=255
        self.assertEqual(separated_digit_views(image),[])

    def test_empty_patch_does_not_invent_zero(self):
        self.assertIsNone(digit_view(np.zeros((15,12,3),np.uint8)))

    def test_right_divider_entering_below_top_does_not_become_a_numeric_suffix(self):
        image=np.zeros((28,30,3),np.uint8)
        image[5:22,7:11]=255
        expected=digit_view(image)
        cv2.line(image,(28,5),(16,27),(255,255,255),2)
        np.testing.assert_array_equal(digit_view(image),expected)

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
