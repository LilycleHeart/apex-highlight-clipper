import copy
import json
from pathlib import Path
import tempfile
import unittest

from algorithm_versions import (FIELDS, affected_clips, classify_field, classify_fields,
    compatible, current_registry, descriptor, stamp_fields)


def registry(version='hud-v1'):
    return {field: descriptor(field, {'reader': version}, models={'model': {'sha256': 'actual-weight'}}) for field in FIELDS}


class AlgorithmVersionTests(unittest.TestCase):
    def test_mixed_fields_and_unknown_history_are_not_promoted(self):
        old, current = registry(), registry('hud-v2')
        info = stamp_fields({}, ['hero'], old, updated_at='old-time')
        info = stamp_fields(info, ['rank'], current, updated_at='now')
        self.assertEqual(classify_fields(info, ['hero', 'rank', 'account'], current),
            {'hero': 'old', 'rank': 'current', 'account': 'unknown'})
        self.assertEqual(info['field_algorithms']['hero']['updated_at'], 'old-time')
        self.assertEqual(classify_field({'version': 'hud-v2'}, 'account', current), 'unknown')

    def test_legacy_recipe_hash_difference_does_not_prove_semantic_change(self):
        current = {'hero': descriptor('hero', {'reader': 'portrait-v2'})}
        self.assertEqual(classify_field({'field_versions': {'hero': 'portrait-v2:abcd'}}, 'hero', current), 'unknown')
        self.assertEqual(classify_field({'field_versions': {'hero': 'portrait-v1:abcd'}}, 'hero', current), 'old')

    def test_application_and_performance_changes_do_not_change_signature(self):
        first = descriptor('hero', {'reader': 'v1'}, semantic_config={'threshold': .8, 'backend': 'cpu', 'cpu_workers': 2, 'app_version': '1'})
        next_ = descriptor('hero', {'reader': 'v1'}, semantic_config={'threshold': .8, 'backend': 'dml', 'cpu_workers': 8, 'app_version': '2'})
        self.assertEqual(first['signature'], next_['signature'])
        self.assertNotEqual(first['signature'], descriptor('hero', {'reader': 'v1'}, semantic_config={'threshold': .9})['signature'])

    def test_models_assets_and_component_versions_are_semantic(self):
        first = descriptor('rank', {'rank': 'rank-v1'}, models={'model': {'sha256': 'a'}})
        second = descriptor('rank', {'rank': 'rank-v1'}, models={'model': {'sha256': 'b'}})
        self.assertFalse(compatible(first, second))
        self.assertEqual(classify_field(stamp_fields({}, ['rank'], {'rank': first}), 'rank', {'rank': second}), 'old')

    def test_upgrade_selection_skips_current_and_optionally_includes_unknown(self):
        current = registry('reader-v2')
        info = stamp_fields({}, ['rank'], current)
        info = stamp_fields(info, ['hero'], registry('reader-v1'))
        clips = [{'id': 'one', 'info': info, 'fields': ['hero', 'rank', 'account']}]
        self.assertEqual(affected_clips(clips, current)[0]['fields'], ['hero'])
        self.assertEqual(affected_clips(clips, current, include_unknown=True)[0]['fields'], ['hero', 'account'])
        self.assertEqual(affected_clips([{'id': 'new', 'info': stamp_fields({}, FIELDS, current)}], current), [])

    def test_missing_resource_is_unknown_and_cannot_resume(self):
        current = registry()
        missing = copy.deepcopy(current)
        missing['hero'] = descriptor('hero', {'reader': 'hud-v1'}, models={'model': {'missing': True}})
        self.assertFalse(compatible(current['hero'], missing['hero']))
        self.assertEqual(classify_field(stamp_fields({}, ['hero'], current), 'hero', missing), 'unknown')

    def test_registry_reads_real_assets_and_explicit_versions_without_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, source in {
                'hud_enrichment': "VERSION='optional-hud-v11'\n",
                'japanese_name_reader': "VERSION='player-names-v12'\n",
                'hero_portrait_reader': "VERSION='self-hero-portrait-v1'\n",
                'rank_reader': "VERSION='hud-rank-v6'\n",
                'hud_layout': "VERSION='anchored-hud-v2'\n",
                'combat_statistics': "VERSION='combat-statistics-v15'\n",
                'combat_outcome_reader': "PARSER_VERSION='target-name-v15'\nRULE_VERSION='own-center-result-v4'\n",
                'numeric_reader': "METHOD='numeric-three-model-v4'\n",
                'hud_digit_reader': "METHOD='hud-digits-v1'\n",
                'outcome_reader': "SELF_VIEW_VERSION='self-hud-view-v3'\n",
                'event_weapon_reader': "VERSION='event-weapon-context-v1'\n",
                'combat_candidate_completion': "VERSION='native-event-completion-v1'\n",
            }.items():
                (root / (name + '.py')).write_text(source, encoding='utf-8')
            for folder in ('assets/legends', 'assets/ranks', 'assets/counters', 'templates/hud', 'templates/statistics', 'templates/combat-outcomes'):
                path = root / folder
                path.mkdir(parents=True)
                (path / 'test.png').write_bytes(b'pixel-test')
            (root / 'assets/counters/hud_digits_v1.onnx').write_bytes(b'real-test-model')
            (root / 'models').mkdir()
            models = {}
            for name in ('weapon_rec_v5.onnx', 'name_rec_japanese_v4.onnx', 'name_rec_en_v5.onnx',
                    'numeric_rec_en_v4.onnx', 'ppocrv6_rec_small.onnx', 'name_rec_v5_server.onnx', 'rapidocr_rec', 'rapidocr_det'):
                path = root / 'models' / name
                path.write_bytes(b'real-test-model')
                models[name] = path
            for name in ('weapon-catalog.json', 'combat-outcome-profile.json'):
                (root / name).write_text('{}', encoding='utf-8')
            (root / 'config.yaml').write_text('Rec:\n    rec_img_shape: [3, 48, 320]\n', encoding='utf-8')
            (root / 'profile-ultrawide.json').write_text('{"reference_size":[2560,1080]}', encoding='utf-8')
            first = current_registry(root, model_paths=models)
            self.assertTrue(all(row['complete'] for row in first.values()))
            with (root / 'hud_enrichment.py').open('a', encoding='utf-8') as source:
                source.write('# performance implementation change\n')
            self.assertEqual(first, current_registry(root, model_paths=models))
            (root / 'assets/ranks/test.png').write_bytes(b'new-pixel-test')
            next_ = current_registry(root, model_paths=models)
            self.assertNotEqual(first['rank']['signature'], next_['rank']['signature'])
            self.assertEqual(first['hero']['signature'], next_['hero']['signature'])

    def test_shared_profile_semantics_and_marker_pixels_invalidate_but_label_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = {'name': 'display label', 'reference_size': [2560, 1080],
                'downed_marker_threshold': .86, 'counter_marker': 'marker.png'}
            path = root / 'profile-ultrawide.json'
            path.write_text(json.dumps(profile), encoding='utf-8')
            (root / 'marker.png').write_bytes(b'original-pixels')
            first = current_registry(root)
            profile.update(name='renamed label', notes=['documentation only'], cpu_workers=8)
            path.write_text(json.dumps(profile), encoding='utf-8')
            self.assertEqual(first, current_registry(root))
            profile['downed_marker_threshold'] = .90
            path.write_text(json.dumps(profile), encoding='utf-8')
            changed = current_registry(root)
            self.assertTrue(all(first[field]['signature'] != changed[field]['signature'] for field in FIELDS))
            (root / 'marker.png').write_bytes(b'revised-marker-pixels')
            pixels = current_registry(root)
            self.assertTrue(all(changed[field]['signature'] != pixels[field]['signature'] for field in FIELDS))


if __name__ == '__main__':
    unittest.main()
