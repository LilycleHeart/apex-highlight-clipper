import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace

import numpy as np
import cv2

import target_name_reader as reader


class TargetNameReaderTests(unittest.TestCase):
    def test_closed_counters_require_existing_enclosed_native_pixels(self):
        image=np.zeros((40,64,3),np.uint8)
        cv2.rectangle(image,(48,9),(59,31),(0,0,220),2);cv2.line(image,(48,20),(59,20),(0,0,220),2)
        proof=reader.terminal_closed_counters(image,44,64)
        self.assertEqual([len(view['holes']) for view in proof['observations']],[2,2])
        image[:,58:61]=0
        self.assertIsNone(reader.terminal_closed_counters(image,44,64))

    def test_mixed_tail_conflict_never_replaces_full_name_or_uses_weak_last_glyph(self):
        image=np.zeros((40,64,3),np.uint8)
        cv2.rectangle(image,(48,9),(59,31),(0,0,220),2);cv2.line(image,(48,20),(59,20),(0,0,220),2)
        primary=object();independent=object()
        def tokens(text,weak=1.):
            return [{'character':character,'left':2+12*i,'right':8+12*i,'confidence':weak if i==len(text)-1 else .99} for i,character in enumerate(text)]
        weak=[.99]
        def emitted(image,model):return tokens('甲1238',.45) if model is primary else tokens('1238',weak[0])
        with patch.object(reader,'ctc_evidence',side_effect=emitted):
            result=reader.review_mixed_ascii_tail(image,'甲123E',primary,independent)
            self.assertTrue(result['conflict']);self.assertNotIn('name',result)
            self.assertIsNone(reader.review_mixed_ascii_tail(image,'甲123B',primary,independent))
            weak[0]=.70
            self.assertFalse(reader.review_mixed_ascii_tail(image,'甲123E',primary,independent)['conflict'])
            with patch.object(reader,'terminal_closed_counters',return_value=None):
                load=Mock(side_effect=AssertionError('no independent model for unsupported pixels'))
                self.assertIsNone(reader.review_mixed_ascii_tail(image,'甲123E',primary,load_independent=load))
                load.assert_not_called()

    def test_dot_count_comes_from_separate_baseline_shapes_not_a_fixed_ellipsis(self):
        tokens=[('A',5.,20.),('B',21.,34.),('C',35.,49.)]
        def sample(positions,y=25):
            image=np.zeros((40,180,3),np.uint8);cv2.putText(image,'ABC',(2,28),cv2.FONT_HERSHEY_SIMPLEX,.7,(40,40,220),1,cv2.LINE_AA)
            for x in positions:image[y:y+2,x:x+2]=(40,40,180)
            return image
        for count in [2,3,4]:self.assertEqual(reader.trailing_dots(sample([65+4*i for i in range(count)]),tokens)['count'],count)
        self.assertIsNone(reader.trailing_dots(sample([65,69,81]),tokens))
        self.assertIsNone(reader.trailing_dots(sample([65,69,73],y=10),tokens))
        image=sample([]);image[25:27,65:79]=(40,40,180)
        self.assertIsNone(reader.trailing_dots(image,tokens))

    def test_one_model_is_retained_for_the_clip_when_global_pool_is_disabled(self):
        recognizer=object();image=np.zeros((40,80,3),np.uint8)
        with patch.dict('os.environ',{'APEX_OCR_POOL':'0'}),patch.object(reader,'model_available',return_value=True),patch('gpu_ocr_backend.create_ocr_engine',return_value=SimpleNamespace(text_rec=recognizer)) as create,patch.object(reader,'read_name_patch',return_value=None) as read:
            model=reader.TargetNameReader();model(image,'甲乙');model(image,'丙丁')
        create.assert_called_once();self.assertTrue(all(call.kwargs['reader'] is recognizer for call in read.call_args_list))

    def test_blank_area_or_character_area_cannot_supply_a_leading_square(self):
        image=np.zeros((40,80,3),np.uint8)
        self.assertIsNone(reader.leading_square(image,25))
        image[:,:,2]=200
        self.assertIsNone(reader.leading_square(image,8))
        self.assertIsNone(reader.leading_square(image,25))

    def test_missing_optional_runtime_model_does_not_download_or_return_an_answer(self):
        with patch.object(reader,'model_available',return_value=False),patch('urllib.request.urlopen',side_effect=AssertionError('runtime download')):
            self.assertIsNone(reader.read_name_patch(np.zeros((40,80,3),np.uint8),'测试'))

    def test_invalid_download_is_rejected_without_leaving_a_partial_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'model.onnx'
            with patch.object(reader,'MODEL_PATH',path),patch('urllib.request.urlopen',return_value=io.BytesIO(b'invalid model')):
                with self.assertRaisesRegex(ValueError,'校验失败'):reader.ensure_model()
            self.assertFalse(path.exists());self.assertFalse(path.with_suffix('.part').exists())


if __name__=='__main__':unittest.main()
