"""Import unchanged user artwork and content-aware vector crop metadata.

PNG pixels are never rewritten. Small detached alpha fragments are omitted by
the runtime clip paths; connected artwork, separate props and sparkles remain.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
STAGES = {
    'scan': ('01-scan.png', [(330, 603), (925, 598), (320, 1194), (910, 1198)]),
    'locate': ('02-locate.png', [(435, 568), (999, 568), (375, 1183), (976, 1197)]),
    'detail': ('03-inspect.png', [(410, 595), (910, 595), (400, 1193), (998, 1197)]),
    'weapons': ('04-identify.png', [(330, 594), (985, 593), (390, 1196), (1010, 1205)]),
    'export': ('05-export.png', [(370, 600), (948, 604), (360, 1207), (982, 1207)]),
    'verify': ('06-verify.png', [(426, 598), (997, 603), (405, 1184), (993, 1185)]),
    'save': ('07-save.png', [(340, 620), (995, 622), (440, 1204), (1040, 1218)]),
    'completed': ('08-finish.png', [(366, 612), (1028, 613), (432, 1170), (1020, 1170)]),
    'walk-left': ('walk-left.png', [(515, 1189)]),
    'walk-right': ('walk-right.png', [(739, 1203)]),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Verified handoff folder with source/ and extracted/')
    parser.add_argument('--idle', type=Path, help='Optional original single-pose home idle PNG; may be imported alone')
    args = parser.parse_args()
    if not args.source and not args.idle:
        parser.error('Provide --source or --idle')
    output = ROOT / 'electron-ui/public/mascots/blanca/playful'
    output.mkdir(parents=True, exist_ok=True)
    atlas_file, source_file = output / 'sprites.json', output / 'source.json'
    atlas = json.loads(atlas_file.read_text('utf-8')) if atlas_file.exists() else {'version': 1, 'size': 320, 'anchor': [160, 284], 'sprites': {}}
    provenance = {'source': 'User-provided Blanca playful v3 artwork; original PNG bytes preserved.',
                  'processing': 'Content-aware component clip paths, explicit foot anchors; no generated walking frames. Detached alpha components smaller than 64 source pixels omitted; clip edges expanded 4 pixels to retain fine edges.',
                  'limitations': 'Connected edge halos and original prop drawing imperfections may remain.', 'files': []}
    if source_file.exists():
        provenance = json.loads(source_file.read_text('utf-8'))
    stages = dict(STAGES) if args.source else {}
    if args.idle:
        stages['idle'] = ('idle.png', [(589, 1278)])
    for action, (filename, anchors) in stages.items():
        source = args.idle if action == 'idle' else args.source / ('source' if action.startswith('walk-') else 'extracted') / filename
        image = np.asarray(Image.open(source).convert('RGBA'))
        height, width = image.shape[:2]
        count, labels, stats, centers = cv2.connectedComponentsWithStats((image[:, :, 3] > 128).astype('uint8'))
        main_parts = sorted(range(1, count), key=lambda i: stats[i, 4], reverse=True)[:len(anchors)]
        main_parts.sort(key=lambda i: (centers[i, 1] > height / 2, centers[i, 0]))
        owners = {part: index for index, part in enumerate(main_parts)}
        for part in range(1, count):
            if stats[part, 4] < 64 or part in owners:
                continue
            def distance(index):
                x, y, w, h = stats[main_parts[index], :4]
                cx, cy = centers[part]
                dx, dy = max(x - cx, 0, cx - x - w), max(y - cy, 0, cy - y - h)
                # A floating prop belongs to the nearest full object boundary,
                # not to the closest face/centroid in a neighboring pose.
                return dx * dx + dy * dy + float(np.sum((centers[part] - centers[main_parts[index]]) ** 2)) * 1e-6
            owners[part] = min(range(len(main_parts)), key=distance)
        frames = []
        for index, anchor in enumerate(anchors):
            mask = np.isin(labels, [part for part, owner in owners.items() if owner == index]).astype('uint8')
            mask = cv2.dilate(mask, np.ones((9, 9), 'uint8'))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            paths = []
            for contour in contours:
                points = cv2.approxPolyDP(contour, .5, True).reshape(-1, 2)
                if len(points) > 2:
                    paths.append('M' + 'L'.join(f'{x},{y}' for x, y in points) + 'Z')
            ys, xs = np.where(mask)
            rect = [int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)]
            scale = .18 if len(anchors) == 1 else .36
            bounds = [round(160 + (rect[0] - anchor[0]) * scale, 2), round(284 + (rect[1] - anchor[1]) * scale, 2),
                      round(160 + (rect[2] - anchor[0]) * scale, 2), round(284 + (rect[3] - anchor[1]) * scale, 2)]
            if min(bounds[:2]) < 0 or max(bounds[2:]) > 320:
                raise ValueError(f'Artwork would be clipped: {action} frame {index + 1}: {bounds}')
            frames.append({'rect': rect, 'anchor': list(anchor), 'scale': scale, 'clip': ''.join(paths), 'bounds': bounds})
        atlas['sprites'][action] = {'file': filename, 'width': width, 'height': height, 'frames': frames}
        shutil.copy2(source, output / filename)
        checksum = hashlib.sha256(source.read_bytes()).hexdigest()
        assert hashlib.sha256((output / filename).read_bytes()).hexdigest() == checksum
        provenance['files'] = [entry for entry in provenance['files'] if entry['file'] != filename]
        provenance['files'].append({'file': filename, 'sha256': checksum, 'width': width, 'height': height, 'frames': len(frames)})
    (output / 'sprites.json').write_text(json.dumps(atlas, separators=(',', ':')), 'utf-8')
    (output / 'source.json').write_text(json.dumps(provenance, indent=2), 'utf-8')
    print(f'Imported {len(stages)} unchanged PNGs; {sum(len(entry["frames"]) for entry in atlas["sprites"].values())} total runtime crops; all imported content bounds fit the shared canvas.')


if __name__ == '__main__':
    main()
