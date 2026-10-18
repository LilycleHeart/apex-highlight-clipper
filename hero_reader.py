"""用本人技能 HUD 的稳定图形识别英雄，不依赖皮肤或敌人头像。"""
from pathlib import Path
import json
import cv2
from image_io import read_image
import numpy as np

BASE=Path(__file__).resolve().parent
NAMES={'bloodhound':'寻血猎犬','gibraltar':'直布罗陀','lifeline':'命脉','pathfinder':'探路者',
 'wraith':'恶灵','bangalore':'班加罗尔','caustic':'侵蚀','mirage':'幻象','octane':'动力小子',
 'wattson':'沃特森','crypto':'密客','revenant':'亡灵','loba':'罗芭','rampart':'兰伯特',
 'horizon':'地平线','fuse':'暴雷','valkyrie':'瓦尔基里','seer':'希尔','ash':'艾许',
 'mad-maggie':'疯玛吉','newcastle':'纽卡斯尔','vantage':'万蒂奇','catalyst':'催化姬',
 'ballistic':'弹道','conduit':'导管','alter':'变幻','sparrow':'Sparrow','axle':'艾克赛尔'}

class HeroReader:
 def __init__(self):
  self.templates=[];self.contrast_templates=[]
  data=json.loads((BASE/'assets/legends/sources.json').read_text('utf-8'))
  for hero in data['legends']:
   for kind,asset in hero.get('abilities',{}).items():
    image=read_image(str(BASE/'assets/legends'/asset['file']),cv2.IMREAD_UNCHANGED)
    if image is None:continue
    mask=image[:,:,3] if image.shape[2]==4 else cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    ys,xs=np.where(mask>127)
    if not len(xs):continue
    glyph=(mask[ys.min():ys.max()+1,xs.min():xs.max()+1]>127).astype(np.uint8)*255
    self.templates.append((hero['id'],kind,glyph))
  hud=BASE/'assets/legends/hud/sources.json'
  if hud.is_file():
   for item in json.loads(hud.read_text('utf-8'))['templates']:
    glyph=read_image(hud.parent/item['file'],cv2.IMREAD_GRAYSCALE)
    if glyph is not None:self.contrast_templates.append((item['id'],item['slot'],glyph))
 def inspect(self,image,profile):
  rw,rh=profile['reference_size'];sx,sy=profile.get('hud_scale',[1.,1.]);scores={};slot_scores={};native_scores={}
  for kind in ['tactical','ultimate']:
   x1,y1,x2,y2=profile['hero_'+kind+'_roi']
   roi=image[round(y1*image.shape[0]/rh):round(y2*image.shape[0]/rh),round(x1*image.shape[1]/rw):round(x2*image.shape[1]/rw)]
   if not roi.size:continue
   # White HUD glyphs, not colored readiness frames or world geometry.
   hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
   masks=[((hsv[:,:,1]<70)&(hsv[:,:,2]>level)).astype(np.uint8)*255 for level in [155,85]]
   contrast_masks=list(masks)
   if any(slot==kind for _,slot,_ in self.contrast_templates):
    gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY).astype(np.float32)
    difference=np.maximum(0,gray-np.median(gray,axis=1)[:,None])
    # 未充能背景有水平条纹，按行移除背景，保留灰色的实际技能符号。
    contrast_masks.append(np.where(hsv[:,:,1]<70,np.clip((difference-4)*8,0,255),0).astype(np.uint8))
   for hero,slot,glyph,contrast in [(hero,slot,glyph,False) for hero,slot,glyph in self.templates]+[(hero,slot,glyph,True) for hero,slot,glyph in self.contrast_templates]:
    if slot!=kind:continue
    best=0.
    for height in range(20,101) if contrast and kind=='ultimate' else range(20,81) if contrast else range(20,69,3):
     h=max(4,round(height*sy*image.shape[0]/rh));w=max(4,round(height*glyph.shape[1]/glyph.shape[0]*sx*image.shape[1]/rw))
     if h>=roi.shape[0] or w>=roi.shape[1]:continue
     template=cv2.resize(glyph,(w,h),interpolation=cv2.INTER_AREA)
     for mask in contrast_masks if contrast else masks:
      # 技能图形居中；不能把按钮左侧的梯形边框或邻近场景当作技能。
      response=cv2.matchTemplate(mask,template,cv2.TM_CCOEFF_NORMED)
      x1=max(0,int(np.ceil(roi.shape[1]*.4-w/2)));x2=min(response.shape[1],int(np.floor(roi.shape[1]*.6-w/2))+1)
      y1=max(0,int(np.ceil(roi.shape[0]*.3-h/2)));y2=min(response.shape[0],int(np.floor(roi.shape[0]*.7-h/2))+1)
      if x1>=x2 or y1>=y2:continue
      score=float(cv2.minMaxLoc(response[y1:y2,x1:x2])[1]);best=max(best,score)
    scores[hero]=max(scores.get(hero,0.),best)
    slot_scores.setdefault(hero,{})[kind]=max(slot_scores.get(hero,{}).get(kind,0.),best)
    if contrast:native_scores[hero]=max(native_scores.get(hero,0.),best)
  raw_ordered=sorted(scores.items(),key=lambda value:-value[1])
  self.last_scores=raw_ordered[:5]
  self.last_slots=slot_scores
  # 先剔除缺乏独立图形证据的候选，不能让进度条的高分压过真实技能图标。
  scores={hero:score for hero,score in scores.items() if native_scores.get(hero,0.)>=.78
      or min(slot_scores[hero].get(kind,0.) for kind in ['tactical','ultimate'])>=.65
      or score>=.90 and score-max((other for key,other in scores.items() if key!=hero),default=0)>=.08}
  ordered=sorted(scores.items(),key=lambda value:-value[1])
  if not ordered or ordered[0][1]<.70:return None
  margin=.025 if ordered[0][1]>=.80 else .055
  if len(ordered)>1 and ordered[0][1]-ordered[1][1]<margin:return None
  hero,score=ordered[0]
  return {'id':hero,'name':NAMES.get(hero,hero.title()),'confidence':round(score,3),'method':'self_ability_glyph'}
