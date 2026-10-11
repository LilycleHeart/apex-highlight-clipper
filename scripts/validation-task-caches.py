"""只读：列出未完成任务可能使用的缓存代次，供 Windows 清理器保护断点。"""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_options import parse_options
from app_task import task_cache_root


def protected_caches(files):
    protected = set()
    for file in files:
        task = json.loads(Path(file).read_text('utf-8-sig'))
        cache_root=task_cache_root(task)
        options = parse_options(task['request'], legacy=True)
        for item in task['items']:
            if item['status'] == 'complete' or not item.get('source_identity'):
                continue
            planner = item.get('smart_cache_version', task.get('smart_cache_version', 'smart-v2'))
            config = {'source': item['source_identity'], 'profile': item.get('hud_profile',task['profile']), 'fps': options['fps']}
            if options['scan_mode'] in ('smart', 'indexed'):
                config.update(scan_mode=planner, gap=options['gap'], pre=options['pre'], post=options['post'])
            if planner == 'indexed-v2':
                config['fine_pipeline'] = 'continuous-v1'
            for stamp in (config, {**config, 'cache_version': 'resume-v1'}):
                digest = hashlib.sha256(json.dumps(stamp, sort_keys=True).encode()).hexdigest()[:16]
                protected.add(digest)
                while True:
                    marker = cache_root / digest / '.images-pruned.json'
                    if not marker.is_file():
                        break
                    generation = json.loads(marker.read_text('utf-8-sig'))['generation']
                    digest = hashlib.sha256((digest + generation).encode()).hexdigest()[:16]
                    if digest in protected:
                        break
                    protected.add(digest)
    return sorted(protected)


if __name__ == '__main__':
    print(json.dumps(protected_caches(json.load(sys.stdin))))
