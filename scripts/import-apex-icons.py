"""下载游戏 HUD 图标的 Wiki SVG 镜像，保留原文件和逐项来源。"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'electron-ui/public/apex-icons'
API = 'https://apexlegends.fandom.com/api.php?'

def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 ApexHighlightClipperAssetImporter/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()

def main():
    catalog = json.loads((ROOT / 'weapon-catalog.json').read_text(encoding='utf-8'))
    special = {'bocek': 'Bocek Compound Bow', 'mastiff': 'Mastiff Shotgun'}
    entries = [{'id': w['id'], 'name': w['name'], 'aliases': w['aliases'],
                'title': 'File:' + special.get(w['id'], w['english_name']) + ' Icon.svg', 'group': 'weapons'}
               for w in catalog['weapons']]
    entries += [{'id': key, 'title': 'File:' + title, 'group': 'stats'} for key, title in
                [('kills', 'Kills Icon.svg'), ('assists', 'Assists Icon.svg'), ('damage', 'Damage.svg'),
                 ('knockdowns', 'Knockdown Shield.svg')]]
    params = dict(action='query', titles='|'.join(e['title'] for e in entries), prop='imageinfo',
                  iiprop='url|extmetadata', format='json')
    pages = json.loads(fetch(API + urllib.parse.urlencode(params)))['query']['pages'].values()
    infos = {p['title']: p.get('imageinfo', [{}])[0] for p in pages}
    def download(entry):
        info = infos.get(entry['title'], {})
        url = info.get('url')
        if not url:
            raise ValueError('图标来源缺失: ' + entry['title'])
        raw = fetch(url)
        svg = ET.fromstring(raw)
        if not svg.tag.endswith('}svg'):
            raise ValueError('图标不是 SVG: ' + entry['title'])
        for node in svg.iter():
            if node.tag.split('}')[-1] in ['script', 'foreignObject', 'image']:
                raise ValueError('SVG 含不支持的外部内容: ' + entry['title'])
            for key, value in node.attrib.items():
                if key.lower().startswith('on') or key.endswith('}href') and not value.startswith('#'):
                    raise ValueError('SVG 含活动或外部引用: ' + entry['title'])
        target = DEST / entry['group'] / (entry['id'] + '.svg')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return {**entry, 'file': str(target.relative_to(DEST)).replace('\\', '/'),
                'url': url, 'source_page': info['descriptionurl'],
                'sha256': hashlib.sha256(raw).hexdigest(), 'metadata': info.get('extmetadata', {})}
    with ThreadPoolExecutor(max_workers=4) as pool:
        assets = list(pool.map(download, entries))
    report = {'description': 'Apex 游戏 HUD 图形的社区 Wiki SVG 镜像；并非 EA 官方发布的 SVG 资源包。原始 SVG 字节完整保留。',
              'assets': assets}
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / 'sources.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    mapping = [{k: a[k] for k in ['id', 'name', 'aliases', 'file']} for a in assets if a['group'] == 'weapons']
    (ROOT / 'electron-ui/src/weaponIcons.json').write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Imported {len(mapping)} weapon SVGs and {len(assets)-len(mapping)} HUD SVGs')
    ranks = [('rookie', '菜鸟', 'Ranked Tier0 Rookie.png'), ('bronze', '青铜', 'Ranked Tier1 Bronze.png'),
             ('silver', '白银', 'Ranked Tier2 Silver.png'), ('gold', '黄金', 'Ranked Tier3 Gold.png'),
             ('platinum', '白金', 'Ranked Tier4 Platinum.png'), ('diamond', '钻石', 'Ranked Tier5 Diamond.png'),
             ('master', '大师', 'Ranked Tier6 Master.png'), ('predator', '猎杀', 'Ranked Tier7 Apex Predator.png')]
    rank_params = dict(action='query', titles='|'.join('File:' + r[2] for r in ranks), prop='imageinfo', iiprop='url', format='json')
    rank_pages = json.loads(fetch(API + urllib.parse.urlencode(rank_params)))['query']['pages'].values()
    rank_infos = {p['title']: p.get('imageinfo', [{}])[0] for p in rank_pages}
    rank_assets = []
    for key, name, title in ranks:
        info = rank_infos.get('File:' + title, {})
        if not info.get('url'):
            if key == 'rookie':
                info = dict(url='https://api.mozambiquehe.re/assets/ranks/rookie4.png', descriptionurl='https://apexlegendsapi.com/')
            else:
                raise ValueError('段位徽章缺失: ' + key)
        raw = fetch(info['url'])
        target = ROOT / 'assets/ranks' / (key + '.png')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        ui_target = DEST / 'ranks' / target.name
        ui_target.parent.mkdir(parents=True, exist_ok=True)
        ui_target.write_bytes(raw)
        rank_assets.append(dict(id=key, name=name, file=target.name, url=info['url'], source_page=info['descriptionurl'], sha256=hashlib.sha256(raw).hexdigest()))
    (ROOT / 'assets/ranks/sources.json').write_text(json.dumps(rank_assets, ensure_ascii=False, indent=2), encoding='utf-8')
    report['ranks'] = rank_assets
    (DEST / 'sources.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__ == '__main__':
    main()
