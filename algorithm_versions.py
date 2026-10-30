"""Recognition semantics and per-field provenance, without loading OCR runtimes.

Source-code hashes and application/performance versions intentionally do not enter
these signatures. A rule change must bump its owning component's explicit VERSION
(or METHOD/PARSER_VERSION), or change a tracked semantic resource/configuration.
Legacy recipes that include implementation hashes are not semantic signatures.
"""
from __future__ import annotations

import ast
import copy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import re

SCHEMA = 1
FIELDS = ('account', 'weapons', 'teammates', 'hero', 'rank', 'statistics', 'opponents', 'event_weapons')
PERFORMANCE_KEYS = frozenset({'backend', 'device', 'gpu_load', 'cpu_workers', 'workers',
    'performance_mode', 'performance_preset', 'performance', 'decode_threads',
    'frame_cache_mib', 'frame_cache_mb', 'cache_limit', 'batch_size', 'batch',
    'app_version', 'application_version', 'parallel_clips', 'adaptive'})


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def semantic_only(value):
    """Strip known execution-only settings; callers supply per-field semantics."""
    if isinstance(value, dict):
        return {key: semantic_only(item) for key, item in value.items() if key not in PERFORMANCE_KEYS}
    if isinstance(value, (list, tuple)):
        return [semantic_only(item) for item in value]
    return value


@lru_cache(maxsize=128)
def _file_hash(path, size, mtime_ns):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def resource(path):
    path = Path(path)
    try:
        stat = path.stat()
        return {'sha256': _file_hash(str(path.resolve()), stat.st_size, stat.st_mtime_ns), 'size': stat.st_size}
    except OSError:
        return {'missing': True}


def _effective_combat_config(root):
    """Same semantic overrides as load_profile, excluding private sample paths."""
    try:
        profile = json.loads((root / 'combat-outcome-profile.json').read_text(encoding='utf-8'))
        local = root / 'combat-outcome-fixtures.local.json'
        if local.is_file():
            fixtures = json.loads(local.read_text(encoding='utf-8'))
            # Positive/negative examples are validation inputs, never read by the
            # recognition decision path. Only calibration/template overrides act.
            profile.setdefault('calibration', {}).update(fixtures.get('calibration_metadata', {}))
            for entry in profile.get('prefix_templates', []):
                entry.update(fixtures.get('template_metadata', {}).get(entry['path'], {}))
        for key in ('positive_examples', 'negative_examples', 'notes', 'note', 'coordinate_format'):
            profile.pop(key, None)
        profile['calibration'] = {key: value for key, value in profile.get('calibration', {}).items()
            if key in {'gate_threshold', 'minimum_fps', 'negative_decision_enabled', 'require_traditional_ui'}}
        return profile
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        return {'missing': True}


def _base_hud_profile(root):
    """The effective shared layout input, excluding display-only annotations."""
    try:
        profile = json.loads((root / 'profile-ultrawide.json').read_text(encoding='utf-8'))
        if not isinstance(profile, dict):
            return {'missing': True}
        return semantic_only({key: value for key, value in profile.items()
            if key not in {'name', 'notes', 'note', 'description'}})
    except (OSError, UnicodeError, ValueError):
        return {'missing': True}


def _rapidocr_semantics(package):
    """Read this package's simple scalar/list YAML without loading its runtime.

    Preserve unknown semantic settings verbatim, so a new vendor setting cannot
    silently disappear from the signature. Paths/providers/threading/batching are
    represented by actual weight digests or intentionally execution-only.
    """
    excluded = {'intra_op_num_threads', 'inter_op_num_threads', 'use_cuda', 'use_dml',
        'model_path', 'rec_batch_num', 'cls_batch_num', 'print_verbose'}
    result = {}
    section = None
    try:
        for raw in (package / 'config.yaml').read_text(encoding='utf-8').splitlines():
            line = raw.split('#', 1)[0].strip()
            if not line or ':' not in line:
                continue
            key, value = line.split(':', 1)
            if not raw[:1].isspace() and not value.strip():
                section = key
                continue
            if key not in excluded:
                result.setdefault(section or 'global', {})[key] = value.strip()
        return result
    except (OSError, UnicodeError):
        return {'missing': True}


def module_constants(path):
    """Read explicit literals without importing modules or constructing readers."""
    try:
        tree = ast.parse(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, SyntaxError, UnicodeError):
        return {}
    values = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError, SyntaxError):
                    pass
    return values


def descriptor(field, components, *, models=None, resources=None, semantic_config=None):
    """Build a stable, fully inspectable semantic descriptor for one field."""
    body = {'algorithm_id': 'ahc/' + field, 'components': dict(components),
        'models': dict(models or {}), 'resources': dict(resources or {}),
        'semantic_config': semantic_only(semantic_config or {})}
    complete = bool(components) and all(isinstance(version, str) and version for version in components.values())
    complete = complete and not any(item.get('missing') for item in list(body['models'].values()) + list(body['resources'].values()))
    return {'schema': SCHEMA, **body,
        'semantic_version': ';'.join(str(value) for _, value in sorted(components.items())),
        'signature': digest(body), 'complete': bool(complete)}


def current_registry(root=None, semantic_config=None, model_paths=None):
    """Current eight-field registry. model_paths may override/add runtime weights.

    Keys in model_paths are filenames, plus ``rapidocr_rec``/``rapidocr_det``.
    Missing weights are reported explicitly; an incomplete descriptor is never
    accepted as proof that an old result or checkpoint is compatible.
    """
    root = Path(root or Path(__file__).resolve().parent)
    config = semantic_config or {}
    paths = dict(model_paths or {})
    constants = {name: module_constants(root / (name + '.py')) for name in [
        'hud_enrichment', 'japanese_name_reader', 'hero_portrait_reader', 'rank_reader',
        'hud_layout', 'combat_statistics', 'combat_outcome_reader', 'numeric_reader',
        'outcome_reader', 'event_weapon_reader', 'combat_candidate_completion']}
    if 'rapidocr_rec' not in paths:
        try:
            spec = importlib.util.find_spec('rapidocr_onnxruntime')
        except (ImportError, ValueError):
            spec = None
        paths['rapidocr_rec'] = (Path(spec.origin).parent / 'models/ch_PP-OCRv4_rec_infer.onnx') if spec and spec.origin else root / 'models/ch_PP-OCRv4_rec_infer.onnx'
    rapidocr_config = _rapidocr_semantics(Path(paths['rapidocr_rec']).parent.parent)
    combat_config = _effective_combat_config(root)
    base_profile = _base_hud_profile(root)
    profile_assets = {}
    for key in ('counter_marker', 'downed_marker'):
        relative = base_profile.get(key)
        if isinstance(relative, str):
            path = (root / relative).resolve()
            profile_assets['base-profile/' + key] = resource(path) if path.is_relative_to(root.resolve()) else {'missing': True}
    model = lambda name: resource(paths.get(name, root / 'models' / name))
    def version(name, key='VERSION'):
        return constants[name].get(key)
    def tree(relative):
        base = root / relative
        files = sorted(file for file in base.rglob('*') if file.is_file() and file.suffix.lower() in {'.png', '.json'})
        return {str(file.relative_to(root)).replace('\\', '/'): resource(file) for file in files} or {relative: {'missing': True}}
    layout = {'hud_layout': version('hud_layout')}
    hud = {**layout, 'hud_enrichment': version('hud_enrichment')}
    names = {**hud, 'japanese_names': version('japanese_name_reader')}
    name_weights = {name: model(name) for name in ['weapon_rec_v5.onnx', 'name_rec_japanese_v4.onnx', 'name_rec_en_v5.onnx', 'numeric_rec_en_v4.onnx', 'rapidocr_rec']}
    numeric_weights = {name: model(name) for name in ['weapon_rec_v5.onnx', 'numeric_rec_en_v4.onnx', 'rapidocr_rec']}
    definitions = {
        'account': (names, name_weights, tree('templates/hud')),
        'teammates': (names, name_weights, tree('templates/hud')),
        'weapons': (hud, {'weapon_rec_v5.onnx': model('weapon_rec_v5.onnx')}, {'weapon-catalog.json': resource(root / 'weapon-catalog.json')}),
        'hero': ({**hud, 'hero_portrait': version('hero_portrait_reader')}, {}, tree('assets/legends')),
        'rank': ({**hud, 'rank': version('rank_reader')}, {}, {**tree('assets/ranks'), **(tree('assets/modes') if (root / 'assets/modes').is_dir() else {})}),
        'statistics': ({**layout, 'statistics': version('combat_statistics'), 'numeric': version('numeric_reader', 'METHOD'), 'self_view': version('outcome_reader', 'SELF_VIEW_VERSION'), **({'toast_confirmation': version('combat_outcome_reader', 'CONFIRMATION_VERSION')} if version('combat_outcome_reader', 'CONFIRMATION_VERSION') else {})}, numeric_weights, tree('templates/statistics')),
        'opponents': ({**layout, 'parser': version('combat_outcome_reader', 'PARSER_VERSION'), 'combat_rules': version('combat_outcome_reader', 'RULE_VERSION'), **({'toast_confirmation': version('combat_outcome_reader', 'CONFIRMATION_VERSION')} if version('combat_outcome_reader', 'CONFIRMATION_VERSION') else {}), 'event_completion': version('combat_candidate_completion')}, {**numeric_weights, **{name: model(name) for name in ['name_rec_v5_server.onnx', 'name_rec_en_v5.onnx']}}, tree('templates/combat-outcomes')),
        'event_weapons': ({**layout, 'event_weapons': version('event_weapon_reader')}, numeric_weights, {'weapon-catalog.json': resource(root / 'weapon-catalog.json')}),
    }
    registry = {}
    for field, (components, weights, assets) in definitions.items():
        # make_profile/detect_images and the repair fallback share this input.
        # A changed ROI/threshold must invalidate the semantic dependency even
        # when hud_layout.VERSION was not bumped; changing only its label cannot.
        assets = {**assets, **profile_assets}
        # Detector weights are optional only when this field does not use a full OCR engine.
        if field == 'opponents':
            assets = {**assets, 'detector': resource(paths.get('rapidocr_det', Path(paths['rapidocr_rec']).with_name('ch_PP-OCRv4_det_infer.onnx')))}
        settings = {'field': config.get(field, {}), 'base_hud_profile': base_profile}
        if weights:
            # Recognition-only fields use Rec settings; opponents also uses the
            # full detector. CPU/GPU provider selection is not semantics.
            settings['rapidocr'] = rapidocr_config if field == 'opponents' else {'Rec': rapidocr_config.get('Rec', {})}
        if field == 'opponents':
            settings['combat_profile'] = combat_config
            settings['candidate_rules'] = {key: constants['combat_candidate_completion'].get(key) for key in
                ('SAMPLE_OFFSETS', 'MIN_TEMPLATE_SCORE', 'MIN_PREFIX_PERSISTENCE', 'MAX_ASSOCIATION_GAP')}
            for entry in combat_config.get('prefix_templates', []):
                for key in ('path', 'gray', 'mask'):
                    if entry.get(key):
                        assets['effective-prefix/' + entry[key]] = resource(root / entry[key])
        registry[field] = descriptor(field, components, models=weights, resources=assets, semantic_config=settings)
        if base_profile.get('missing') or weights and rapidocr_config.get('missing') or field == 'opponents' and combat_config.get('missing'):
            registry[field]['complete'] = False
    return registry


def stamp_fields(info, fields, registry, *, updated_at=None):
    """Copy info and stamp ONLY successfully committed fields, retaining mixtures."""
    result = copy.deepcopy(info)
    stamps = result.setdefault('field_algorithms', {})
    when = updated_at or utc_now()
    for field in fields:
        stamps[field] = {**copy.deepcopy(registry[field]), 'updated_at': when}
    return result


def compatible(saved, current):
    return bool(isinstance(saved, dict) and saved.get('schema') == SCHEMA and saved.get('complete')
        and current.get('complete') and saved.get('algorithm_id') == current.get('algorithm_id')
        and saved.get('signature') == current.get('signature'))


def classify_field(info, field, registry):
    current = registry[field]
    saved = info.get('field_algorithms', {}).get(field)
    if isinstance(saved, dict):
        if compatible(saved, current):
            return 'current'
        if saved.get('schema') == SCHEMA and saved.get('complete') and current.get('complete') and saved.get('algorithm_id') == current['algorithm_id'] and saved.get('signature'):
            return 'old'
        return 'unknown'
    # Historical source-derived hashes prove neither model equality nor a semantic
    # change. Only a known explicit component version difference proves "old".
    legacy = info.get('field_versions', {}).get(field)
    if not isinstance(legacy, str):
        return 'unknown'
    tokens = re.findall(r'[A-Za-z][A-Za-z0-9-]*-v\d+', legacy)
    expected = list(current.get('components', {}).values())
    for token in tokens:
        prefix = token.rsplit('-v', 1)[0]
        matches = [version for version in expected if isinstance(version, str) and version.rsplit('-v', 1)[0] == prefix]
        if matches and token not in matches:
            return 'old'
    return 'unknown'


def classify_fields(info, fields, registry):
    return {field: classify_field(info, field, registry) for field in fields}


def affected_clips(clips, registry, *, include_unknown=False, fields=None):
    """Input rows use {id, info}; return affected fields without guessing history."""
    result = []
    for clip in clips:
        info = clip.get('info', clip.get('hud_info', {})) or {}
        requested = list(fields or clip.get('fields') or FIELDS)
        statuses = classify_fields(info, requested, registry)
        old = [field for field, state in statuses.items() if state == 'old']
        unknown = [field for field, state in statuses.items() if state == 'unknown']
        affected = old + (unknown if include_unknown else [])
        if affected:
            result.append({**clip, 'fields': affected, 'old_fields': old, 'unknown_fields': unknown})
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Describe current recognition semantics without running OCR')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    print(json.dumps(current_registry(parser.parse_args().root), ensure_ascii=False, indent=2))
