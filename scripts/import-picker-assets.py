"""Import original game portraits/class/ammo artwork for library filter pickers."""
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
LEGENDS = ['Bangalore', 'Revenant', 'Fuse', 'Mad Maggie', 'Ballistic', 'Pathfinder',
           'Wraith', 'Octane', 'Horizon', 'Ash', 'Alter', 'Axle', 'Bloodhound',
           'Crypto', 'Valkyrie', 'Seer', 'Vantage', 'Sparrow', 'Gibraltar',
           'Lifeline', 'Mirage', 'Loba', 'Newcastle', 'Conduit', 'Caustic',
           'Wattson', 'Rampart', 'Catalyst']


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://apexlegends.fandom.com/'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main():
    entries = [{'id': name.lower().replace(' ', '-'), 'title': f'File:Portrait {name} square.png',
                'group': 'legends', 'extension': 'png'} for name in LEGENDS]
    entries += [{'id': name.lower(), 'title': f'File:{name}.svg', 'group': 'classes', 'extension': 'svg'}
                for name in ['Assault', 'Skirmisher', 'Recon', 'Support', 'Controller']]
    entries += [{'id': key, 'title': f'File:{title}.svg', 'group': 'ammo', 'extension': 'svg'} for key, title in
                [('light', 'Light Rounds'), ('heavy', 'Heavy Rounds'), ('energy', 'Energy Ammo'),
                 ('shotgun', 'Shotgun Shells'), ('sniper', 'Sniper Ammo'), ('arrows', 'Arrows')]]
    query = urllib.parse.urlencode({'action': 'query', 'format': 'json', 'prop': 'imageinfo',
                                  'iiprop': 'url', 'titles': '|'.join(entry['title'] for entry in entries)})
    pages = json.loads(fetch(API + query))['query']['pages'].values()
    infos = {page['title']: page.get('imageinfo', [{}])[0] for page in pages}

    def download(entry):
        info = infos.get(entry['title'], {})
        if not info.get('url'):
            raise ValueError('Missing picker asset: ' + entry['title'])
        relative = f"{entry['group']}/{entry['id']}.{entry['extension']}"
        target = DEST / relative
        url = info['url'].split('/revision/')[0] + '?format=original'
        try:
            raw = target.read_bytes() if target.is_file() else fetch(url)
        except Exception as error:
            raise ValueError('Cannot import ' + entry['title'] + ': ' + str(error)) from error
        if entry['extension'] == 'png':
            if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Invalid portrait PNG: ' + entry['title'])
        else:
            svg = ET.fromstring(raw)
            if not svg.tag.endswith('}svg'):
                raise ValueError('Invalid picker SVG: ' + entry['title'])
            for node in svg.iter():
                if node.tag.split('}')[-1] in {'script', 'foreignObject', 'image'}:
                    raise ValueError('Unsupported SVG content: ' + entry['title'])
                for key, value in node.attrib.items():
                    if key.lower().startswith('on') or key.endswith('}href') and not value.startswith('#'):
                        raise ValueError('Active/external SVG reference: ' + entry['title'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return {'id': entry['id'], 'file': relative, 'title': entry['title'], 'url': url,
                'source_page': info['descriptionurl'], 'sha256': hashlib.sha256(raw).hexdigest()}

    with ThreadPoolExecutor(max_workers=4) as pool:
        assets = list(pool.map(download, entries))
    sources = {
        'description': 'Original EA/Respawn game artwork mirrored by the community Apex Wiki. Not an official SVG asset distribution. Files preserved unchanged.',
        'classification_source': 'https://www.ea.com/games/apex-legends/apex-legends/game-objects/characters-hub',
        'selection_layout_reference': 'https://www.4gamer.net/games/449/G044914/20260501051/',
        'assets': assets,
    }
    (DEST / 'picker-sources.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(f'Imported {len(assets)} picker assets')


if __name__ == '__main__':
    main()
