import unittest
from unittest.mock import patch

import numpy as np

from hud_layout import make_profile
import squads_panel


class FakeEngine:
    """按参考坐标给出文字框；换算成识别区裁图内的坐标后返回，模拟 RapidOCR 的输出。"""
    def __init__(self, profile, lines):
        self.profile, self.lines = profile, lines

    def __call__(self, crop, use_cls=False):
        search, _ = squads_panel.regions(self.profile)
        scale = crop.shape[1] / (search[2] - search[0])
        result = []
        for text, (x1, y1, x2, y2), confidence in self.lines:
            box = [[(x - search[0]) * scale, (y - search[1]) * scale] for x, y in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]]
            result.append((box, text, confidence))
        return result, 0.


# 2560x1080 本人 HUD 上实测的位置：小队数行、其右侧人数、RP、计分行下方的性能/网络信息。
LABEL = ('18剩餘小隊數', (2233, 54, 2363, 78), .97)
PLAYERS = ('54', (2376, 54, 2426, 79), 1.)
POINTS = ('-65RP', (2470, 105, 2533, 130), .98)
NETWORK = ('FPS:169 10:87/31 loss0/0', (2205, 136, 2401, 152), .9)


class SquadsPanelTests(unittest.TestCase):
    def state(self, lines, width=2560, height=1080, image_height=None):
        profile = make_profile(width, height)
        image = np.zeros((image_height or height, round(width * (image_height or height) / height), 3), np.uint8)
        return squads_panel.read(image, profile, FakeEngine(profile, lines))

    def test_squads_row_without_counter_digits_is_zero(self):
        result = self.state([LABEL, PLAYERS, POINTS, NETWORK])
        self.assertEqual(result['state'], 'zero')
        self.assertEqual(result['label'], '18剩餘小隊數')

    def test_counter_digits_or_hidden_panel_are_not_zero(self):
        self.assertEqual(self.state([LABEL, PLAYERS, ('280', (2334, 96, 2401, 120), .98), POINTS])['state'], 'digits')
        # 计分行位置上带数字的任何文字（包括击杀信息里的名字）都不能当作 0。
        self.assertEqual(self.state([LABEL, ('Player123', (2244, 80, 2431, 102), .9)])['state'], 'digits')
        self.assertEqual(self.state([PLAYERS, POINTS, NETWORK])['state'], 'hidden')
        self.assertEqual(self.state([])['state'], 'hidden')

    def test_name_text_without_digits_and_overlays_do_not_block_zero(self):
        name = ('Colfearcat Avada Kedewg', (2244, 78, 2431, 103), .77)
        self.assertEqual(self.state([LABEL, name, POINTS, NETWORK])['state'], 'zero')

    def test_label_variants_and_other_resolutions(self):
        for text in ['20剩余小队数', '19剩除小除数', 'SQUADS LEFT']:
            self.assertEqual(self.state([(text, LABEL[1], .9)])['state'], 'zero', text)
        # 16:9 画面 HUD 靠右锚定：同样的行在 1920 宽画面里左移 640 像素。
        shifted = [(text, (x1 - 640, y1, x2 - 640, y2), c) for text, (x1, y1, x2, y2), c in [LABEL, ('280', (2334, 96, 2401, 120), .98)]]
        self.assertEqual(self.state(shifted[:1], width=1920)['state'], 'zero')
        self.assertEqual(self.state(shifted, width=1920)['state'], 'digits')
        # 采样图只有一半分辨率时先放大，坐标仍按参考尺寸换算。
        self.assertEqual(self.state([LABEL, PLAYERS], image_height=540)['state'], 'zero')

    def frames(self, states, excluded=()):
        for index, state in enumerate(states):
            image = None if index in excluded else np.full((1080, 2560, 3), index, np.uint8)
            provenance = {'native_verified': True, 'native_time': float(index)} if image is not None else {'excluded_view': True}
            yield float(index), image, {**provenance, 'state': state}

    def zero(self, states, excluded=(), **options):
        sequence = list(states)
        def counter(image, profile, template):
            visible = sequence[int(image[0, 0, 0])] == 'visible'
            return ((0, 0), .95) if visible else (None, .5)
        def panel(image, profile, engine):
            state = sequence[int(image[0, 0, 0])]
            if state == 'lobby':  # 大厅货币等数字：计分行位置有数字但没有小队数行
                return {'state': 'digits', 'label': None, 'digits': 1}
            return {'state': state, 'label': '剩餘小隊數', 'digits': int(state == 'digits')}
        with patch('apex_clipper.counter_offset', side_effect=counter), patch('apex_clipper.inactive_view', return_value=False), \
             patch('image_io.read_image', return_value=np.zeros((4, 4), np.uint8)), patch('squads_panel.read', side_effect=panel):
            return squads_panel.zero_frames(self.frames(sequence, excluded), make_profile(2560, 1080), engine=object(), **options)

    def test_two_distinct_zero_frames_are_required_and_recorded_as_zero(self):
        rows = self.zero(['hidden', 'zero', 'zero'])
        self.assertEqual([row['native_time'] for row in rows], [1., 2.])
        self.assertTrue(all(row['kills'] == row['assists'] == row['damage'] == 0 for row in rows))
        self.assertEqual(rows[0]['zero_evidence']['method'], squads_panel.VERSION)
        self.assertEqual(self.zero(['zero']), [])

    def test_counter_stops_the_search_but_other_views_and_lobby_digits_do_not(self):
        self.assertEqual(self.zero(['zero', 'digits', 'zero']), [])
        self.assertEqual(self.zero(['zero', 'visible', 'zero']), [])
        # 观战、阵亡画面里本人不会造成伤害，跳过；大厅里计分行位置的数字没有小队数行，也不算计分栏。
        self.assertEqual(len(self.zero(['zero', 'zero', 'zero'], excluded={1})), 2)
        self.assertEqual(len(self.zero(['lobby', 'hidden', 'zero', 'zero'])), 2)

    def test_latest_frames_must_show_zero_for_the_end_of_a_clip(self):
        self.assertEqual(len(self.zero(['hidden', 'zero', 'zero'], latest=1.5)), 2)
        self.assertEqual(self.zero(['hidden', 'hidden', 'hidden', 'zero', 'zero'], latest=1.5), [])
        self.assertEqual(len(self.zero(['zero', 'hidden', 'hidden', 'hidden', 'zero'], latest=1.5)), 2)


if __name__ == '__main__':
    unittest.main()
