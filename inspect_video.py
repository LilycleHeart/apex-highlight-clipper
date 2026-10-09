from pathlib import Path
import argparse
import cv2
from PIL import Image, ImageDraw

def main():
    p = argparse.ArgumentParser()
    p.add_argument('video')
    p.add_argument('--step', type=float, default=20)
    p.add_argument('--start', type=float, default=0)
    p.add_argument('--end', type=float)
    p.add_argument('--out', default='validation/overview')
    a = p.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(a.video)
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT)/cap.get(cv2.CAP_PROP_FPS)
    end = min(a.end or duration, duration)
    tiles = []
    t = a.start
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t*1000)
        ok, frame = cap.read()
        if not ok: break
        cv2.imwrite(str(out/f'{t:08.2f}.jpg'), frame)
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        img.thumbnail((640, 270))
        tile = Image.new('RGB', (640, 296), '#141820'); tile.paste(img)
        ImageDraw.Draw(tile).text((8, 274), f'{t//60:02.0f}:{t%60:05.2f} ({t:.2f}s)', fill='white')
        tiles.append(tile)
        t += a.step
    cap.release()
    for j in range(0,len(tiles),12):
        group=tiles[j:j+12]
        sheet=Image.new('RGB',(1920,296*((len(group)+2)//3)), '#141820')
        for k,tile in enumerate(group): sheet.paste(tile,((k%3)*640,(k//3)*296))
        sheet.save(out/f'sheet_{j//12+1}.jpg',quality=90)
    print(f'{len(tiles)} samples, duration {duration:.3f}s -> {out}')

if __name__ == '__main__': main()
