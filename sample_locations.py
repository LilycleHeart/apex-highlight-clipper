"""同一源录像的原采样/补查采样定位，不跨录像猜测帧编号。"""
import json
from pathlib import Path
import re

class SampleResolver:
    def __init__(self,cache,samples):
        self.roots=[Path(samples)]
        for parent in list(Path(samples).parents)[:3]:
            try:
                saved=json.loads((parent/'hud.json').read_text(encoding='utf-8'))
                if saved.get('source')==cache['source'] and parent/'samples' not in self.roots:self.roots.append(parent/'samples')
            except (OSError,ValueError):pass
    def path(self,frame):
        if not isinstance(frame,str) or not re.fullmatch(r'\d+[.]jpg',frame):return self.roots[0]/'_invalid-frame'
        return next((root/frame for root in self.roots if (root/frame).is_file()),self.roots[0]/frame)
