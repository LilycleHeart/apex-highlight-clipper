import base64
import os
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from event_weapon_reader import context_from_observations, recheck_event_weapons, recipe, VERSION


class EventWeaponContextTests(unittest.TestCase):
    def row(self, second, ident='nemesis', slot=0, ammo=24):
        return {'actual_pts': second, 'slot': slot,
                'weapon': {'id': ident, 'name': {'nemesis': '死敌', 'car': 'CAR'}[ident]},
                'confidence': .96, 'name_view_agreement': 2,
                'ammo': {'value': ammo, 'confidence': .99},
                'weapon_icon': base64.b64encode(b'\xaa' * 336).decode()}

    def test_batch_reuses_counter_reader_and_recipe_without_merging_frame_evidence(self):
        from combat_statistics import final_counter_reader
        from engine_pool import clear_pool, pooled_engine
        class Reader:
            def __init__(self, backend):self.calls = 0
            def __call__(self, images):
                self.calls += 1
                return [('24', .99) for _ in images], 0.
        profile = {'layout_status': 'confirmed', 'reference_size': [2560, 1080]}
        identity = {'path': 'sample.mp4', 'size': 1, 'mtime_ms': 2}
        event = {'kind': 'knock', 'action': 'knock', 'time': 1., 'ownership': 'self', 'confirmed': True}
        current = {**event, 'time': 4., 'weapon_context': {
            'version': VERSION, 'recipe': recipe(profile), 'source': identity,
            'event': {'kind': 'knock', 'action': 'knock', 'time': 4.}, 'status': 'observed'}}
        image = np.zeros((20, 30, 3), np.uint8)
        def observe(second, frame, profile, weapon_reader, numeric_reader):
            self.assertIs(numeric_reader, shared)
            self.assertEqual(numeric_reader([frame])[0], [('24', .99)])
            return self.row(second)
        clear_pool()
        self.addCleanup(clear_pool)
        with patch.dict(os.environ, {'APEX_OCR_POOL': '1', 'APEX_OCR_BACKEND': 'cpu'}), \
                patch('numeric_reader.NumericReader', Reader):
            shared = final_counter_reader()
            shared([image])
            pooled_engine(('names', 'cpu'), object)
            with patch('apex_clipper.fingerprint', return_value={**identity, 'mtime_ns': 2_000_000}), \
                    patch('apex_clipper.probe', return_value=({'format': {'duration': 10.}}, {'width': 2560, 'height': 1080})), \
                    patch('hud_enrichment.native_frames', return_value=iter([(1., image), (1.12, image)])), \
                    patch('gpu_ocr_backend.create_ocr_engine', return_value=SimpleNamespace(text_rec=object())), \
                    patch('weapon_reader.WeaponTextReader', return_value=object()), \
                    patch('event_weapon_reader._read_observation', side_effect=observe), \
                    patch('event_weapon_reader.recipe', wraps=recipe) as signature:
                checked = recheck_event_weapons('sample.mp4', [event, current], profile)
            signature.assert_called_once_with(profile)
            self.assertEqual(shared.recognizer.calls, 1)
            self.assertEqual(shared.stats()['exact_reuse'], 2)
            self.assertEqual([row['actual_pts'] for row in checked[0]['weapon_context']['evidence']], [1., 1.12])
            self.assertEqual(checked[1], current)

    def test_newly_confirmed_event_rechecks_previously_ineligible_unknown_only(self):
        profile = {'layout_status': 'confirmed', 'reference_size': [2560, 1080]}
        identity = {'path': 'sample.mp4', 'size': 1, 'mtime_ms': 2}
        location = {'kind': 'knock', 'action': 'knock', 'time': 5.}
        event = {**location, 'ownership': 'self', 'confirmed': False,
                 'weapon_context': {'version': VERSION, 'recipe': recipe(profile),
                                    'source': identity, 'event': location, 'status': 'unknown',
                                    'reason': 'unconfirmed_or_unsupported_event'}}
        with patch('apex_clipper.fingerprint', return_value={**identity, 'mtime_ns': 2_000_000}), \
                patch('apex_clipper.probe', return_value=({'format': {'duration': 10.}}, {'width': 2560, 'height': 1080})) as probe, \
                patch('hud_enrichment.native_frames', return_value=iter([])) as decode, \
                patch('engine_pool.pooled_engine', return_value=None):
            self.assertEqual(recheck_event_weapons('sample.mp4', [event], profile), [event])
            probe.assert_not_called()
            decode.assert_not_called()
            event['confirmed'] = True
            checked = recheck_event_weapons('sample.mp4', [event], profile)
            decode.assert_called_once()
            self.assertNotEqual(checked[0]['weapon_context']['reason'], 'unconfirmed_or_unsupported_event')
            # 当前已观察到的武器证据照常复用，不因这个资格修复重复采样。
            event['weapon_context'].update(status='observed', scope='nearby_firing', reason='same_slot_name_icon_and_ammo_decrease')
            probe.reset_mock()
            decode.reset_mock()
            self.assertEqual(recheck_event_weapons('sample.mp4', [event], profile), [event])
            probe.assert_not_called()
            decode.assert_not_called()

    def test_switch_at_toast_does_not_change_prior_firing_into_kill_attribution(self):
        event = {'kind': 'knock', 'action': 'knock', 'time': 10., 'ownership': 'self'}
        rows = [self.row(9., ammo=24), self.row(9.5, ammo=19),
                self.row(10., 'car', 1, 30), self.row(10.12, 'car', 1, 30)]
        original = deepcopy(event)
        result = context_from_observations(event, rows)
        self.assertEqual(result['scope'], 'nearby_firing')
        self.assertEqual(result['weapon']['id'], 'nemesis')
        self.assertEqual(result['shots'][0]['ammo_drop'], 5)
        self.assertFalse(result['kill_attribution'])
        self.assertEqual(event, original)
        # 已有当前证据必须复用，不能为了再次展示而探测或重读录像。
        identity = {'path': 'sample.mp4', 'size': 1, 'mtime_ms': 2}
        event['weapon_context'] = {**result, 'version': VERSION, 'recipe': recipe({}),
                                   'source': identity, 'event': {'kind': 'knock', 'action': 'knock', 'time': 10.}}
        with patch('apex_clipper.fingerprint', return_value={**identity, 'mtime_ns': 2_000_000}), \
                patch('apex_clipper.probe', side_effect=AssertionError('should reuse current evidence')):
            self.assertEqual(recheck_event_weapons('sample.mp4', [event], {}), [event])

    def test_switch_reload_or_observer_cannot_be_reported_as_firing(self):
        event = {'time': 10.}
        cases = [
            [self.row(9., slot=0, ammo=24), self.row(9.5, slot=1, ammo=19)],
            [self.row(9., ammo=24), self.row(9.5, ammo=0)],
            [self.row(9., ammo=19), self.row(9.5, ammo=24)],
            [self.row(9., ammo=24), {**self.row(9.5, ammo=19), 'excluded_view': True}],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                self.assertEqual(context_from_observations(event, rows)['scope'], 'unknown')
        held = context_from_observations(event, [self.row(10., 'car', 1, 30), self.row(10.12, 'car', 1, 30)])
        self.assertEqual(held['scope'], 'held_at_event')
        self.assertFalse(held['kill_attribution'])


if __name__ == '__main__':
    unittest.main()
