"""导入用户原PNG与音频；只另建透明轮廓SVG，不改原图像像素。"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import wave
import zipfile
import cv2
import numpy as np
from PIL import Image
from io import BytesIO

ROOT=Path(__file__).resolve().parents[1]
GROUPS=['scan','locate','detail','weapons','export','verify','save','completed']

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--flat',required=True); parser.add_argument('--sketch',required=True)
    parser.add_argument('--disappear',required=True); parser.add_argument('--restore',required=True)
    args=parser.parse_args(); target=ROOT/'public/mascots/blanca'; target.mkdir(parents=True,exist_ok=True)
    report={'styles':{},'sounds':{},'original_pixels_preserved':True}
    for style in ['flat','sketch']:
        folder=target/style; folder.mkdir(exist_ok=True); frames=[]
        with zipfile.ZipFile(getattr(args,style)) as archive:
            for entry in archive.infolist():
                parts=entry.filename.replace('\\','/').split('/')
                if len(parts)!=2 or not parts[1].endswith('.png'): continue
                prefix=parts[0].split('_')[0]
                if prefix not in [f'{i:02d}' for i in range(1,9)] or parts[1] not in ['01.png','02.png','03.png','04.png']:
                    raise ValueError('不支持的素材条目：'+entry.filename)
                group=GROUPS[int(prefix)-1]; name=f'{group}-{parts[1]}'
                dest=folder/name; dest.resolve().relative_to(target.resolve())
                data=archive.read(entry); dest.write_bytes(data)
                rgba=Image.open(BytesIO(data)).convert('RGBA'); width,height=rgba.size
                alpha=np.asarray(rgba)[:,:,3]
                mask=(alpha>=40).astype(np.uint8)*255
                mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
                contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                curves=[]
                for contour in contours:
                    if cv2.contourArea(contour)<70: continue
                    points=cv2.approxPolyDP(contour,.8,True).reshape(-1,2)
                    if len(points)>=3: curves.append('M'+'L'.join(f'{x} {y}' for x,y in points)+'Z')
                svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"><path d="{" ".join(curves)}" fill="none" stroke="currentColor" stroke-width="5" stroke-dasharray="11 9" stroke-linecap="round" stroke-linejoin="round"/></svg>'
                dest.with_suffix('.svg').write_text(svg,encoding='utf-8')
                frames.append({'file':name,'size':[width,height],'alpha_bbox':rgba.getbbox(),'sha256':hashlib.sha256(data).hexdigest(),'contours':len(curves)})
        if len(frames)!=32: raise ValueError(f'{style}需要32帧，实际{len(frames)}')
        report['styles'][style]=frames
    audio=ROOT/'public/mascots/audio';audio.mkdir(parents=True,exist_ok=True)
    for sound in ['disappear','restore']:
        source=Path(getattr(args,sound)); dest=audio/(sound+'.wav');shutil.copyfile(source,dest)
        with wave.open(str(source),'rb') as wav: duration=wav.getnframes()/wav.getframerate()
        report['sounds'][sound]={'duration':duration,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    report_path=ROOT/'output/playwright/blanca/import-report.json';report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'frames':64,'audio':report['sounds'],'directory':str(target)},ensure_ascii=False))

if __name__=='__main__':main()
