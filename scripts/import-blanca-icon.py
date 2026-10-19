"""Trace the supplied icon to real SVG paths, then render native app icons.

Asset-authoring dependencies only: pip install vtracer resvg-py
The supplied source is read without modification; no bitmap is embedded in SVG.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image
import resvg_py
import vtracer

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    args = parser.parse_args()
    source = args.source.read_bytes()
    image = Image.open(io.BytesIO(source)).convert('RGBA')
    pixels = np.asarray(image)
    count, labels, stats, _ = cv2.connectedComponentsWithStats((pixels[:, :, 3] > 128).astype('uint8'))
    if count < 2:
        raise ValueError('Icon source has no visible subject')
    subject = 1 + int(np.argmax(stats[1:, 4]))
    mask = cv2.dilate((labels == subject).astype('uint8'), np.ones((5, 5), 'uint8'))
    clean = pixels.copy()
    clean[:, :, 3] = np.where(mask, clean[:, :, 3], 0)
    clean = Image.fromarray(clean)
    clean = clean.crop(clean.getbbox())
    clean.thumbnail((736, 736), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (768, 768))
    canvas.alpha_composite(clean, ((768 - clean.width) // 2, (768 - clean.height) // 2))
    trace_input = io.BytesIO()
    canvas.save(trace_input, format='PNG')
    settings = dict(colormode='color', hierarchical='stacked', mode='spline', filter_speckle=8,
                    color_precision=6, layer_difference=16, corner_threshold=60,
                    length_threshold=4.0, max_iterations=10, splice_threshold=45, path_precision=2)
    svg = vtracer.convert_raw_image_to_svg(trace_input.getvalue(), img_format='png', **settings)
    tree = ET.fromstring(svg)
    paths = tree.findall('.//{http://www.w3.org/2000/svg}path')
    assert paths and not tree.findall('.//{http://www.w3.org/2000/svg}image')
    output = ROOT / 'electron-ui/public/brand'
    (output / 'cat-clapperboard.svg').write_text(svg, 'utf-8')
    raster = resvg_py.svg_to_bytes(svg_string=svg, width=512, height=512)
    (output / 'cat-clapperboard.png').write_bytes(raster)
    Image.open(io.BytesIO(raster)).save(output / 'cat-clapperboard.ico', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    (output / 'icon-source.json').write_text(json.dumps({
        'source': 'User-provided Blanca holding a clapperboard, transparent PNG; source left unchanged.',
        'sha256': hashlib.sha256(source).hexdigest(), 'source_size': image.size,
        'processing': 'Detached alpha noise excluded; subject fitted into a square with padding; spline color trace. SVG contains paths, no embedded raster. PNG/ICO rendered from the SVG.',
        'trace_settings': settings, 'paths': len(paths),
    }, indent=2), 'utf-8')
    print(f'Created SVG with {len(paths)} vector paths ({len(svg.encode())} bytes), plus 512px PNG and seven ICO sizes.')


if __name__ == '__main__':
    main()
