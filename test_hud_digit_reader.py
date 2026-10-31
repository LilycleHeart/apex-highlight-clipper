import hashlib
import unittest
from unittest.mock import patch

import numpy as np

import hud_digit_reader
from hud_digit_reader import CHECK_MINIMUM, MODEL_MINIMUM, HudDigitReader, agreed, decode, prepare


def probs_for(labels, confidence=.99, steps=64):
    """按时间步给出 CTC 输出：labels 中 0 为空白，1..10 对应数字 0..9。"""
    probs = np.full((steps, 11), (1 - confidence) / 10, np.float32)
    path = list(labels) + [0] * (steps - len(labels))
    for step, label in enumerate(path):
        probs[step, label] = confidence
    return probs


class HudDigitReaderTests(unittest.TestCase):
    def test_prepare_scales_any_crop_to_the_model_canvas(self):
        for shape in [(28, 64, 3), (84, 192, 3), (41, 95, 3), (20, 13)]:
            canvas = prepare(np.full(shape, 255, np.uint8))
            self.assertEqual(canvas.shape, (28, 64))
            self.assertAlmostEqual(float(canvas[:, 0].mean()), 1., places=3)
        # 窄裁片左对齐，右侧补 0。
        self.assertEqual(float(prepare(np.full((28, 12, 3), 255, np.uint8))[:, 20:].max()), 0.)

    def test_ctc_decode_collapses_repeats_and_keeps_digits_split_by_blank(self):
        probs = np.stack([probs_for([4, 4, 0, 1, 1, 0, 9]), probs_for([2, 0, 2]), probs_for([])])
        self.assertEqual([text for text, _ in decode(probs)], ['308', '11', ''])
        self.assertEqual(decode(probs)[2][1], 0.)

    def test_reading_needs_both_models_to_agree(self):
        primary = [('718', .99), ('718', .99), ('718', MODEL_MINIMUM - .01), ('718', .99), ('', 0.), ('771', .98), ('771', .95)]
        check = [('718', .95), ('78', .99), ('718', .99), ('718', CHECK_MINIMUM - .01), ('5', .99), ('π', .9), ('π', .9)]
        # 复核模型把数字读成符号时只采用主模型的高置信读数；读出不同数字一律不采用。
        self.assertEqual(agreed(primary, check), [('718', .95), ('', 0.), ('', 0.), ('', 0.), ('', 0.), ('771', .98), ('', 0.)])

    def test_reader_only_checks_crops_the_main_model_read(self):
        session = type('Session', (), {})()
        session.run = lambda outputs, feeds: [np.stack([probs_for([8, 2]), probs_for([])])]
        seen = []
        def check(images):
            seen.append(len(images))
            # 复核模型把伤害右侧的分隔斜线读成末尾的「/」时去掉再比对。
            return [('71/', .97)], 0.
        with patch('hud_digit_reader._session', return_value=session), patch('hud_digit_reader._check', return_value=check):
            values, _ = HudDigitReader()([np.zeros((28, 30, 3), np.uint8)] * 2)
        self.assertEqual(seen, [1])
        self.assertEqual(values, [('71', .97), ('', 0.)])

    def test_bundled_model_matches_its_recorded_checksum(self):
        data = hud_digit_reader.MODEL_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), hud_digit_reader.MODEL_SHA256)
        hud_digit_reader._session.cache_clear()
        probs = hud_digit_reader._session().run(None, {'x': np.zeros((1, 1, 28, 64), np.float32)})[0]
        self.assertEqual(probs.shape[0], 1)
        self.assertEqual(probs.shape[-1], 11)


if __name__ == '__main__':
    unittest.main()
