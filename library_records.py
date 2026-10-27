"""片段库记录维护：成片被移动、任务文件夹被移动、导入非本软件处理的片段。

只改写识别记录里指向成片的路径与文件身份；不移动、不删除、不改写任何视频。
由桌面主进程在没有识别任务运行时调用；所有写入原子替换，首次改写前保留备份。
"""
import hashlib
import json
import os
from pathlib import Path
import sys

from apex_clipper import fingerprint, probe, write_json

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.mov', '.ts', '.m4v'}
IMPORTED_VERSION = 1
# 视觉 HUD 字段可以只靠成片画面读取；战绩/敌人姓名需要原录像与交战分析，导入片段不提供。
IMPORTED_FIELDS = ['account', 'weapons', 'teammates', 'hero', 'rank']


def key(path):
    """Windows 路径不区分大小写；在其他平台上也按同样规则比较测试夹具。"""
    return os.path.normcase(os.path.normpath(str(path))).replace('\\', '/').casefold()


def load(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def save(path, value):
    """首次改写前保留原文件，之后只做原子替换。"""
    path = Path(path); backup = path.with_name(path.name + '.before-relocation')
    if path.is_file() and not backup.exists():
        backup.write_bytes(path.read_bytes())
    write_json(path, value)


def media_stat(path):
    stat = Path(path).stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'mtime_ms': stat.st_mtime_ns // 1_000_000}


def clip_fingerprint(path, block=256 * 1024):
    """大小 + 头尾各 256KB 的 SHA-256。

    移动、改名、复制都不改变内容；重新编码或剪辑会变，因此可以安全地用来
    判断「这个文件是不是某条整理记录里的那段成片」。
    """
    path = Path(path)
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        head = stream.read(block)
        digest.update(head)
        if stat.st_size > block * 2:
            stream.seek(-block, os.SEEK_END)
            digest.update(stream.read(block))
    return {'size': stat.st_size, 'content': digest.hexdigest()}


def fingerprint_of(clip):
    """记录里已有的内容指纹；旧记录没有时返回 None。"""
    value = clip.get('content_hash') or clip.get('content_fingerprint')
    if isinstance(value, dict) and isinstance(value.get('content'), str) and len(value['content']) == 64:
        return value
    return None


def tasks_index(root):
    """扫描所有整理清单，建立 content_hash -> (manifest 路径, clip) 索引。"""
    index = {}
    tasks = Path(root) / 'tasks'
    if not tasks.is_dir():
        return index
    for manifest_path in tasks.rglob('export.json'):
        try:
            manifest = load(manifest_path)
        except (OSError, ValueError):
            continue
        if manifest.get('mode') == 'imported' or manifest.get('source') is None:
            continue
        for clip in manifest.get('clips', []):
            value = fingerprint_of(clip)
            if value:
                index.setdefault(value['content'], []).append((manifest_path, clip))
    return index

def rewrite(value, moves, stats):
    """把指向旧成片的路径换成新路径；成片身份同时更新时间，大小不符时保持原样不认领。"""
    if isinstance(value, str):
        target = moves.get(key(value))
        return target if target is not None else value
    if isinstance(value, list):
        return [rewrite(item, moves, stats) for item in value]
    if not isinstance(value, dict):
        return value
    if isinstance(value.get('path'), str) and key(value['path']) in moves and 'size' in value:
        target = moves[key(value['path'])]; current = stats[key(target)]
        if value.get('size') != current['size']:
            return {name: rewrite(item, moves, stats) if name != 'path' else item for name, item in value.items()}
        fresh = {name: rewrite(item, moves, stats) for name, item in value.items()}
        fresh['path'] = target
        if 'mtime_ns' in value: fresh['mtime_ns'] = current['mtime_ns']
        if 'mtime_ms' in value: fresh['mtime_ms'] = current['mtime_ms']
        return fresh
    return {name: rewrite(item, moves, stats) for name, item in value.items()}


def originals(manifest, moves):
    """清单中按原样书写的旧路径与新路径。"""
    return [(clip['output'], moves[key(clip['output'])]) for clip in manifest.get('clips', [])
            if isinstance(clip.get('output'), str) and key(clip['output']) in moves]


def relocated_manifest(manifest, moves, stats):
    """成片清单：路径与身份改到新位置，并登记为允许在原视频目录之外的已登记成片。"""
    recorded = {key(path) for path in manifest.get('outputs', []) if isinstance(path, str)}
    applied = [target for source, target in moves.items() if source in recorded]
    if not applied:
        return manifest, []
    updated = {**manifest}
    for name in ('outputs', 'clips', 'relocated_outputs'):
        if name in updated: updated[name] = rewrite(updated[name], moves, stats)
    # 记住旧路径：统计记录（statistics.json）不改写，其中绑定旧路径的证据仍属于这段成片。
    previous = {key(target): source_path for source_path, target in originals(manifest, moves)}
    for clip in updated.get('clips', []):
        old = previous.get(key(clip.get('output', '')))
        if old:
            clip['moved_from'] = list(dict.fromkeys([*clip.get('moved_from', []), old]))
    kept = [path for path in updated.get('relocated_outputs', []) if isinstance(path, str) and Path(path).is_file()]
    updated['relocated_outputs'] = list(dict.fromkeys(kept + applied))
    return updated, applied


def verify_moves(moves):
    """新位置必须是现有视频文件，且大小与记录一致；任何一项不符则整批拒绝。"""
    checked = {}; stats = {}
    for move in moves:
        source, target = move['from'], move['to']
        if not isinstance(source, str) or not isinstance(target, str) or not Path(target).is_absolute():
            raise ValueError('搬移记录无效')
        path = Path(target)
        if path.suffix.lower() not in VIDEO_EXTENSIONS or not path.is_file():
            raise ValueError('搬移后的片段不存在：' + path.name)
        if Path(source).exists():
            raise ValueError('原位置的片段仍在，不能改写记录：' + Path(source).name)
        stat = media_stat(path)
        if move.get('size') is not None and move['size'] != stat['size']:
            raise ValueError('搬移后的片段大小与记录不符：' + path.name)
        if isinstance(move.get('duration'), (int, float)):
            # 只凭大小匹配时，再用时长确认是同一段视频。
            if abs(float(probe(path)[0]['format']['duration']) - move['duration']) > .5:
                raise ValueError('搬移后的片段时长与记录不符：' + path.name)
        if key(source) in checked and key(checked[key(source)]) != key(target):
            raise ValueError('同一片段匹配到多个新位置')
        checked[key(source)] = target; stats[key(target)] = stat
    if len({key(target) for target in checked.values()}) != len(checked):
        raise ValueError('多个记录匹配到同一个片段')
    return checked, stats


def relocate(request):
    moves, stats = verify_moves(request.get('moves', []))
    changed = []
    for file in dict.fromkeys(request.get('tasks', [])):
        task_path = Path(file); task = load(task_path); task_changed = False
        for item in task.get('items', []):
            record = item.get('record')
            if not isinstance(record, dict):
                continue
            destination = Path(item.get('destination') or record.get('directory') or '')
            manifest_path = destination / 'export.json'
            if manifest_path.is_file():
                manifest = load(manifest_path)
                updated, applied = relocated_manifest(manifest, moves, stats)
                if applied:
                    save(manifest_path, updated); changed.append(str(manifest_path))
            outputs = {key(path) for path in record.get('outputs', []) if isinstance(path, str)}
            applied = [target for source, target in moves.items() if source in outputs]
            if applied:
                for name in ('outputs', 'output_identities'):
                    if name in record: record[name] = rewrite(record[name], moves, stats)
                kept = [path for path in record.get('relocated_outputs', []) if isinstance(path, str) and Path(path).is_file()]
                record['relocated_outputs'] = list(dict.fromkeys(kept + applied))
                task_changed = True
        if task_changed:
            save(task_path, task); changed.append(str(task_path))
    for file in dict.fromkeys(request.get('manifests', [])):
        manifest_path = Path(file); manifest = load(manifest_path)
        updated, applied = relocated_manifest(manifest, moves, stats)
        if applied:
            save(manifest_path, updated); changed.append(str(manifest_path))
    return {'changed': changed, 'moved': len(moves)}


def replace_prefix(value, old, new):
    if isinstance(value, str):
        text = value.replace('\\', '/'); prefix = old.replace('\\', '/').rstrip('/')
        if text.casefold() == prefix.casefold() or text.casefold().startswith(prefix.casefold() + '/'):
            rest = value[len(prefix):]
            separator = '\\' if '\\' in new else '/'
            return new.rstrip('\\/') + rest.replace('/', separator).replace('\\', separator)
        return value
    if isinstance(value, list):
        return [replace_prefix(item, old, new) for item in value]
    if isinstance(value, dict):
        return {name: replace_prefix(item, old, new) for name, item in value.items()}
    return value


def rebase(request):
    """旧版任务把 task.json 与成片放在同一文件夹；整个文件夹被移动后，把其中路径换到新位置。"""
    changed = []
    for file in dict.fromkeys(request.get('tasks', [])):
        task_path = Path(file).resolve(); task = load(task_path)
        if task.get('version') != 1 or not isinstance(task.get('directory'), str):
            continue
        old = task['directory']; new = str(task_path.parent)
        if key(old) == key(new):
            continue
        # 只接受同名文件夹整体移动；名字不同可能是复制或另一任务，不能盲改。
        if Path(old.replace('\\', '/')).name.casefold() != task_path.parent.name.casefold():
            continue
        for item in task.get('items', []):
            destination = item.get('destination')
            if not isinstance(destination, str):
                continue
            moved = Path(replace_prefix(destination, old, new))
            if not moved.is_dir() or not moved.resolve().is_relative_to(task_path.parent):
                continue
            for name in ('export.json', 'analysis.json', 'statistics.json', 'quality-filter.json',
                         'review-candidates.json', 'rejected-candidates.json'):
                path = moved / name
                if path.is_file():
                    save(path, replace_prefix(load(path), old, new)); changed.append(str(path))
        save(task_path, replace_prefix(task, old, new)); changed.append(str(task_path))
    return {'changed': changed}


def imported_store(root):
    directory = Path(root).resolve() / 'imported'
    return directory, directory / 'export.json'


def load_imported(root):
    directory, path = imported_store(root)
    if path.is_file():
        manifest = load(path)
        if manifest.get('mode') != 'imported' or manifest.get('version') != IMPORTED_VERSION:
            raise ValueError('已有片段记录格式不正确')
        return directory, path, manifest
    return directory, path, {'mode': 'imported', 'version': IMPORTED_VERSION, 'metadata_directory': str(directory),
                             'video_directory': str(directory), 'source': None, 'outputs': [], 'relocated_outputs': [], 'clips': []}


def import_clips(request):
    """登记未经本软件处理的片段；只读视频信息，不复制、不改名。

    添加前先用内容指纹查一遍整理记录：命中说明这段成片本来就是本软件整理的，
    认回原记录（保留识别与统计），不再登记成导入片段。
    """
    directory, path, manifest = load_imported(request['data_root'])
    known = {key(item) for item in manifest['outputs']}; added = []; rejected = []; restored = []
    index = tasks_index(request['data_root'])
    # 自动扫描时超长的视频多半是原录像；记住它的大小和时间，未变化就不再重复读取。
    limit = request.get('max_duration'); skipped = manifest.setdefault('skipped_long', [])
    skipped_keys = {(item.get('path_key'), item.get('size'), item.get('mtime_ns')) for item in skipped if isinstance(item, dict)}
    for raw in request.get('files', []):
        file = Path(raw)
        if not file.is_absolute() or file.suffix.lower() not in VIDEO_EXTENSIONS or not file.is_file():
            rejected.append({'file': str(raw), 'reason': '不是可读取的视频文件'}); continue
        if key(file) in known:
            continue
        stat = media_stat(file)
        if limit and (key(file), stat['size'], stat['mtime_ns']) in skipped_keys:
            rejected.append({'file': str(file), 'reason': '超过自动加入的时长上限', 'skipped': True}); continue
        # 认回只需要文件内容，不必先解码；这样移动/复制过的成片即使暂时读不出时长也能归位。
        content = clip_fingerprint(file)
        matches = index.get(content['content']) or []
        if matches:
            target_dir = str(file.parent).casefold()
            def distance(pair):
                old_dir = str(Path(pair[1].get('output') or '').parent).casefold()
                return 0 if old_dir == target_dir else 1
            manifest_path, clip = sorted(matches, key=distance)[0]
            try:
                saved = load(manifest_path)
            except (OSError, ValueError):
                saved = None
            if saved is not None and isinstance(clip.get('output'), str):
                moves = {key(clip['output']): str(file)}
                stats = {key(str(file)): media_stat(file)}
                updated, applied = relocated_manifest(saved, moves, stats)
                if applied:
                    save(manifest_path, updated)
                    restored.append(str(file))
                    known.add(key(str(file)))
                    continue
        try:
            metadata, video = probe(file); duration = float(metadata['format']['duration'])
        except Exception as error:
            rejected.append({'file': str(file), 'reason': str(error)[:200]}); continue
        if not video or duration <= 0:
            rejected.append({'file': str(file), 'reason': '没有可播放的视频流'}); continue
        if limit and duration > limit:
            skipped.append({'path_key': key(file), 'size': stat['size'], 'mtime_ns': stat['mtime_ns']})
            rejected.append({'file': str(file), 'reason': '超过自动加入的时长上限', 'skipped': True}); continue
        identity = fingerprint(file)
        manifest['clips'].append({'output': str(file), 'segment': {'start': 0., 'end': duration}, 'summary': {},
                                  'metadata': metadata, 'output_identity': identity, 'recognition': {},
                                  'content_hash': content, 'imported': True})
        manifest['outputs'].append(str(file)); manifest['relocated_outputs'].append(str(file))
        known.add(key(file)); added.append(str(file))
    if added or len(skipped) != len(skipped_keys):
        directory.mkdir(parents=True, exist_ok=True); write_json(path, manifest)
    return {'added': added, 'restored': restored, 'rejected': rejected, 'manifest': str(path)}


def remove_imported(request):
    """移出片段库：只删除登记，视频文件保留在原处。"""
    directory, path, manifest = load_imported(request['data_root'])
    wanted = {key(file) for file in request.get('files', [])}
    before = len(manifest['outputs'])
    manifest['outputs'] = [file for file in manifest['outputs'] if key(file) not in wanted]
    manifest['relocated_outputs'] = [file for file in manifest.get('relocated_outputs', []) if key(file) not in wanted]
    manifest['clips'] = [clip for clip in manifest['clips'] if key(clip.get('output', '')) not in wanted]
    if len(manifest['outputs']) != before:
        write_json(path, manifest)
    return {'removed': before - len(manifest['outputs'])}


COMMANDS = {'relocate': relocate, 'rebase': rebase, 'import': import_clips, 'remove-imported': remove_imported}

if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    request = json.loads(sys.stdin.read())
    command = COMMANDS.get(request.get('command'))
    if command is None:
        raise SystemExit('未知的片段库命令')
    print(json.dumps(command(request), ensure_ascii=False))
