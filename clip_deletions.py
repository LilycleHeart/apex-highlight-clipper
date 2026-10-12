"""Respect clips deliberately recycled by the desktop library, across upgrades."""
from functools import lru_cache
import json
import os
from pathlib import Path


@lru_cache(maxsize=4)
def _removed(path):
    try:
        saved=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if isinstance(saved,dict) and saved.get('version')==1:
            return {os.path.normcase(str(Path(file).resolve())) for file in saved.get('files',[]) if isinstance(file,str) and Path(file).is_absolute()}
    except (OSError,ValueError,TypeError):pass
    return set()


def is_removed(file):
    location=os.environ.get('APEX_CLIP_DELETIONS')
    if not location:
        from app_task import data_root
        location=str(data_root()/'clip-deletions.json')
    target=Path(file)
    return not target.exists() and os.path.normcase(str(target.resolve())) in _removed(location)
