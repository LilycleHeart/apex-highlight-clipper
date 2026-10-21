"""用本人技能 HUD 的稳定图形识别英雄，不依赖皮肤或敌人头像。"""
from pathlib import Path
from collections import OrderedDict
from functools import lru_cache
import threading
import json
import cv2
from image_io import read_image
import numpy as np

BASE=Path(__file__).resolve().parent
_TEMPLATE_LOCK=threading.RLock()
NAMES={'bloodhound':'寻血猎犬','gibraltar':'直布罗陀','lifeline':'命脉','pathfinder':'探路者',
 'wraith':'恶灵','bangalore':'班加罗尔','caustic':'侵蚀','mirage':'幻象','octane':'动力小子',
 'wattson':'沃特森','crypto':'密客','revenant':'亡灵','loba':'罗芭','rampart':'兰伯特',
 'horizon':'地平线','fuse':'暴雷','valkyrie':'瓦尔基里','seer':'希尔','ash':'艾许',
 'mad-maggie':'疯玛吉','newcastle':'纽卡斯尔','vantage':'万蒂奇','catalyst':'催化姬',
 'ballistic':'弹道','conduit':'导管','alter':'变幻','sparrow':'Sparrow','axle':'艾克赛尔'}

@lru_cache(maxsize=2)
def _template_bank(signature):
  # The signature includes asset metadata, so edited HUD assets invalidate both
  # the decoded glyphs and the scaled variants between clips.
  templates=[];contrast_templates=[]
  data=json.loads((BASE/'assets/legends/sources.json').read_text('utf-8'))
  for hero in data['legends']:
   for kind,asset in hero.get('abilities',{}).items():
    image=read_image(str(BASE/'assets/legends'/asset['file']),cv2.IMREAD_UNCHANGED)
    if image is None:continue
    mask=image[:,:,3] if image.shape[2]==4 else cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    ys,xs=np.where(mask>127)
    if not len(xs):continue
    glyph=(mask[ys.min():ys.max()+1,xs.min():xs.max()+1]>127).astype(np.uint8)*255
    templates.append((hero['id'],kind,glyph))
  hud=BASE/'assets/legends/hud/sources.json'
  if hud.is_file():
   for item in json.loads(hud.read_text('utf-8'))['templates']:
    glyph=read_image(hud.parent/item['file'],cv2.IMREAD_GRAYSCALE)
    if glyph is not None:contrast_templates.append((item['id'],item['slot'],glyph))
  return templates,contrast_templates,OrderedDict()


class HeroReader:
 def __init__(self):
  root=BASE/'assets/legends'
  signature=tuple((str(path),path.stat().st_size,path.stat().st_mtime_ns)
      for path in sorted(root.rglob('*')) if path.is_file() and path.suffix.lower() in {'.png','.json'})
  self.templates,self.contrast_templates,self._scaled=_template_bank(signature)
  self._matches=OrderedDict()
 def _prepared(self,kind,image_shape,profile,roi_shape):
  with _TEMPLATE_LOCK:return self._prepared_locked(kind,image_shape,profile,roi_shape)
 def _prepared_locked(self,kind,image_shape,profile,roi_shape):
  rw,rh=profile['reference_size'];sx,sy=profile.get('hud_scale',[1.,1.])
  key=(kind,tuple(image_shape[:2]),rw,rh,sx,sy,tuple(roi_shape[:2]))
  if key not in self._scaled:
   prepared=[]
   for hero,slot,glyph,contrast in [(hero,slot,glyph,False) for hero,slot,glyph in self.templates]+[(hero,slot,glyph,True) for hero,slot,glyph in self.contrast_templates]:
    if slot!=kind:continue
    variants=[];sizes=set()
    for height in range(20,101) if contrast and kind=='ultimate' else range(20,81) if contrast else range(20,69,3):
     h=max(4,round(height*sy*image_shape[0]/rh));w=max(4,round(height*glyph.shape[1]/glyph.shape[0]*sx*image_shape[1]/rw))
     if h>=roi_shape[0] or w>=roi_shape[1] or (w,h) in sizes:continue
     sizes.add((w,h))
     x1=max(0,int(np.ceil(roi_shape[1]*.4-w/2)));x2=min(roi_shape[1]-w+1,int(np.floor(roi_shape[1]*.6-w/2))+1)
     y1=max(0,int(np.ceil(roi_shape[0]*.3-h/2)));y2=min(roi_shape[0]-h+1,int(np.floor(roi_shape[0]*.7-h/2))+1)
     if x1>=x2 or y1>=y2:continue
     variants.append((cv2.resize(glyph,(w,h),interpolation=cv2.INTER_AREA),(x1,x2,y1,y2)))
    prepared.append((hero,contrast,variants))
   self._scaled[key]=prepared
   while len(self._scaled)>4:self._scaled.popitem(last=False)
  self._scaled.move_to_end(key)
  return self._scaled[key]
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
   # Identical threshold masks and rounded sizes need only one match. Keep the
   # full-size OpenCV call so score rounding and all decision thresholds stay
   # exactly the same as the original implementation.
   unique_masks=[];unique_contrast=[]
   for source,target in [(masks,unique_masks),(contrast_masks,unique_contrast)]:
    for mask in source:
     if not any(np.array_equal(mask,other) for other in target):target.append(mask)
   prepared=self._prepared(kind,image.shape,profile,roi.shape)
   if not hasattr(self,'_matches'):self._matches=OrderedDict()
   cache_key=(kind,tuple(image.shape),tuple(roi.shape),tuple(profile['reference_size']),tuple(profile.get('hud_scale',[1.,1.])),tuple(mask.tobytes() for mask in unique_masks),tuple(mask.tobytes() for mask in unique_contrast))
   cached=self._matches.get(cache_key)
   if cached is not None:
    for hero,(best,native) in cached.items():
     scores[hero]=max(scores.get(hero,0.),best);slot_scores.setdefault(hero,{})[kind]=best
     if native is not None:native_scores[hero]=max(native_scores.get(hero,0.),native)
    self._matches.move_to_end(cache_key)
    continue
   matched={}
   for hero,contrast,variants in prepared:
    best=0.
    for template,(x1,x2,y1,y2) in variants:
     for mask in unique_contrast if contrast else unique_masks:
      # 技能图形居中；不能把按钮左侧的梯形边框或邻近场景当作技能。
      response=cv2.matchTemplate(mask,template,cv2.TM_CCOEFF_NORMED)
      score=float(cv2.minMaxLoc(response[y1:y2,x1:x2])[1]);best=max(best,score)
    scores[hero]=max(scores.get(hero,0.),best)
    slot_scores.setdefault(hero,{})[kind]=max(slot_scores.get(hero,{}).get(kind,0.),best)
    if contrast:native_scores[hero]=max(native_scores.get(hero,0.),best)
    previous=matched.get(hero,(0.,None))
    matched[hero]=(max(previous[0],best),max(previous[1] or 0.,best) if contrast else previous[1])
   self._matches[cache_key]=matched
   while len(self._matches)>8:self._matches.popitem(last=False)
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
