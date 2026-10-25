"""数字框识别失败时，用独立图标定位和前景分离补读，不能降低置信门槛填数。"""
from pathlib import Path
import hashlib
import cv2
from image_io import read_image
import numpy as np
from functools import lru_cache

BASE=Path(__file__).resolve().parent
@lru_cache(maxsize=1)
def counter_recipe():
    digest=hashlib.sha256(Path(__file__).read_bytes())
    for name in ['combat_statistics.py','hud_enrichment.py','repair_cached_statistics.py','outcome_reader.py','numeric_reader.py','gpu_ocr_backend.py','ocr_cache.py']:digest.update((BASE/name).read_bytes())
    import rapidocr_onnxruntime
    digest.update((Path(rapidocr_onnxruntime.__file__).parent/'models/ch_PP-OCRv4_rec_infer.onnx').read_bytes())
    for model in ['weapon_rec_v5.onnx','numeric_rec_en_v4.onnx']:digest.update((BASE/'models'/model).read_bytes())
    for file in sorted((BASE/'templates/statistics').glob('*.png')):digest.update(file.read_bytes())
    return digest.hexdigest()


def counter_box(profile,key):
    box=list(profile[key])
    if key=='damage':
        sx=profile.get('hud_scale',[1,1])[0]
        # 四位伤害不能沿用仅够三位数字的旧裁剪宽度；保留与段位徽章的间隔。
        box[2]=max(box[2],min(box[2]+round(24*sx),profile.get('rank_roi',[profile['reference_size'][0]])[0]-round(8*sx)))
    return box

def without_counter_divider(image):
    """只移除贯穿裁片高度的右侧斜分隔线，保留较矮的数字笔画。"""
    if image is None or not image.size:return None
    height,width=image.shape[:2]
    edges=cv2.Canny(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),80,180)
    lines=cv2.HoughLinesP(edges,1,np.pi/180,threshold=max(8,round(height*.3)),minLineLength=round(height*.75),maxLineGap=round(height*.08))
    candidates=[]
    for x1,y1,x2,y2 in [] if lines is None else lines.reshape(-1,4):
        dy=abs(int(y2)-int(y1));dx=abs(int(x2)-int(x1))
        # 斜线可能从裁片右侧上四分之一处进入，不一定触碰顶边。
        if dy>=height*.75 and .2*dy<=dx<=.8*dy and min(y1,y2)<=height*.25 and max(y1,y2)>=height*.85 and min(x1,x2)>width*.35:candidates.append(int(min(x1,x2)))
    return image[:,:max(1,min(candidates)-2)].copy() if candidates else None


def digit_view(patch):
    if patch is None or not patch.size:return None
    # 长分隔线在前景分离后会留下逗号状残片，使真实“1”读成“1,”。
    clean=without_counter_divider(patch)
    if clean is not None:patch=clean
    gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
    count,labels,stats,_=cv2.connectedComponentsWithStats((gray>180).astype(np.uint8))
    mask=np.zeros(gray.shape,np.uint8)
    for i,(x,y,w,h,area) in enumerate(stats[1:],1):
        # 排除贯穿整框的白色背景、底边和图标碎片；保留数字的独立笔画。
        if 4<=h<=gray.shape[0]-2 and area>=4 and w<=h*1.6:mask[labels==i]=255
    yy,xx=np.where(mask>0)
    if not len(xx):return None
    glyph=255-mask[yy.min():yy.max()+1,xx.min():xx.max()+1]
    glyph=cv2.resize(glyph,None,fx=4,fy=4)
    glyph=cv2.copyMakeBorder(glyph,8,8,8,8,cv2.BORDER_CONSTANT,value=255)
    return cv2.cvtColor(glyph,cv2.COLOR_GRAY2BGR)


def separated_digit_views(image):
    """较亮前景可断开纹理造成的字间粘连；保留原有笔画，不补画字符。"""
    if image is None or not image.size:return []
    clean=without_counter_divider(image)
    if clean is None:clean=image
    gray=cv2.cvtColor(clean,cv2.COLOR_BGR2GRAY);height,width=gray.shape;result=[]
    for level in [200,220,240]:
        mask=(gray>level).astype(np.uint8);_,labels,stats,_=cv2.connectedComponentsWithStats(mask)
        parts=[(i,box) for i,box in enumerate(stats[1:],1) if height*.3<=box[3]<=height*.85 and 1<=box[2]<=box[3]*1.5 and box[4]>=max(4,box[3]*.5)]
        if not parts:continue
        tallest=max(box[3] for _,box in parts);parts=[(i,box) for i,box in parts if box[3]>=tallest*.65]
        bottom=float(np.median([box[1]+box[3] for _,box in parts]));parts=[(i,box) for i,box in parts if abs(box[1]+box[3]-bottom)<=tallest*.2]
        groups=[]
        for index,box in sorted(parts,key=lambda item:item[1][0]):
            x,y,w,h,_=map(int,box)
            if groups and x<groups[-1][2]:
                old=groups[-1];old[1]=min(old[1],y);old[2]=max(old[2],x+w);old[3]=max(old[3],y+h);old[4].append(index)
            else:groups.append([x,y,x+w,y+h,[index]])
        foreground=np.isin(labels,[i for group in groups for i in group[4]])
        # 重复数字的顶部横笔可能相连；宽连通块不能当成一个字来证明短读数。
        # 只在两个完整笔画之间存在薄连接时切开，并仅移动已有前景像素。
        separated=[];split=False;unresolved=False
        for x,y,right,bottom,indices in groups:
            glyph=foreground[y:bottom,x:right];h,w=glyph.shape
            if w>h*.95:
                projection=glyph.sum(axis=0);left=round(w*.35);right_cut=round(w*.65)
                cut=min(range(left,right_cut+1),key=lambda i:(projection[i],abs(i-w/2)))
                pieces=[]
                for start,end in [(0,cut),(cut,w)]:
                    yy,xx=np.where(glyph[:,start:end])
                    if not len(xx):break
                    box=[x+start+int(xx.min()),y+int(yy.min()),x+start+int(xx.max())+1,y+int(yy.max())+1,indices]
                    if not h*.2<=box[2]-box[0]<=h*.85 or box[3]-box[1]<h*.65:break
                    pieces.append(box)
                if len(pieces)==2 and projection[cut]<=h*.35:
                    separated.extend(pieces);split=True;continue
                unresolved=True
            separated.append([x,y,right,bottom,indices])
        groups=separated
        if unresolved:continue
        if not 2<=len(groups)<=5:continue
        ys,xs=np.where(foreground)
        if not len(xs):continue
        if split:
            top=min(group[1] for group in groups);bottom=max(group[3] for group in groups)
            gap=max(2,round(tallest*.2));cursor=0
            view=np.full((bottom-top,sum(group[2]-group[0] for group in groups)+gap*(len(groups)-1)),255,np.uint8)
            for x,y,right,lower,_ in groups:
                view[y-top:lower-top,cursor:cursor+right-x]=np.where(foreground[y:lower,x:right],0,255)
                cursor+=right-x+gap
        else:view=np.where(foreground[ys.min():ys.max()+1,xs.min():xs.max()+1],0,255).astype(np.uint8)
        view=cv2.copyMakeBorder(view,10,10,10,10,cv2.BORDER_CONSTANT,value=255)
        result.append({'image':cv2.cvtColor(view,cv2.COLOR_GRAY2BGR),'glyph_count':len(groups),'threshold':level,'boxes':[group[:4] for group in groups],**({'touching_glyphs_separated':True} if split else {})})
    return result


KILLS_FALLBACK='icon-digit-span-v1'


def digit_span(patch):
    """返回窗口内计数数字的左右边界；跳过贴左缘的图标残边、斜分隔线和右侧白色底块。"""
    if patch is None or not patch.size:return None
    gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY);height,width=gray.shape
    level=max(150,int(np.percentile(gray,99)*.75))
    _,labels,stats,_=cv2.connectedComponentsWithStats((gray>=level).astype(np.uint8),connectivity=8)
    glyphs=[];others=[]
    for index,(x,y,w,h,area) in enumerate(stats[1:],1):
        if area<3:continue
        digit=x>0 and .4*height<=h<=.95*height and w<=h*.9 and not (area/(w*h)<.38 and w>=h*.25)
        if digit:
            ys,xs=np.where(labels[y:y+h,x:x+w]==index)
            top=xs[ys<h*.3];bottom=xs[ys>h*.7]
            # 「/」上端明显比下端靠右；数字 1 基本竖直。
            digit=not (len(top) and len(bottom) and top.mean()-bottom.mean()>max(1.5,h*.18))
        (glyphs if digit else others).append((x,x+w,h))
    if not glyphs:return None
    glyphs.sort();first=glyphs[0];right=first[1]
    for x,x2,h in glyphs[1:]:
        if x-right>first[2]*.5 or abs(h-first[2])>first[2]*.25:break
        right=x2
    pad=max(1,round(first[2]*.25))
    # 留白不能伸进左侧图标残边或右侧分隔线。
    left_wall=max([x2 for x,x2,_ in others if x2<=first[0]],default=0)
    right_wall=min([x for x,_,_ in others if x>=right],default=width)
    return max(left_wall,first[0]-pad),min(right_wall,right+pad)


class CounterFallback:
    def __init__(self):
        self.templates={key:read_image(str(BASE/'templates/statistics'/f'{key}-gray.png'),0) for key in ['kills','assists','participation']}
        crown=read_image(str(BASE/'templates/statistics/kills-crown-gray.png'),0)
        self.extra_templates={'kills':[crown]} if crown is not None else {}
        self.digits={key:read_image(str(BASE/'templates/statistics'/f'digit-{key}.png'),0) for key in ['0','6','8']}
    def decode_numeric_alias(self,text,view):
        self.last_match_score=0.
        zero_aliases=['D','O','〇','日','口']
        if not text or not any(c in text for c in zero_aliases+['B']):return None
        gray=cv2.cvtColor(view,cv2.COLOR_BGR2GRAY);mask=gray<128;columns=np.where(mask.any(axis=0))[0];runs=[]
        for x in columns:
            if runs and x==runs[-1][-1]+1:runs[-1].append(x)
            else:runs.append([x])
        if len(runs)!=len(text):return None
        output=[];matched_scores=[]
        for character,run in zip(text,runs):
            if character.isdigit():output.append(character);continue
            if character not in zero_aliases+['B']:return None
            part=mask[:,run[0]:run[-1]+1];ys=np.where(part.any(axis=1))[0]
            glyph=cv2.resize(part[ys.min():ys.max()+1].astype(np.uint8),(24,32),interpolation=cv2.INTER_NEAREST)>0
            scores=[]
            for key,template in self.digits.items():
                if template is None:continue
                reference=template>128;scores.append((2*np.count_nonzero(glyph&reference)/max(1,np.count_nonzero(glyph)+np.count_nonzero(reference)),key))
            scores.sort(reverse=True)
            if len(scores)<2 or scores[0][0]<.95 or scores[0][0]-scores[1][0]<.05:return None
            allowed=['0'] if character in zero_aliases else ['6','8']
            if scores[0][1] not in allowed:return None
            output.append(scores[0][1]);matched_scores.append(scores[0][0])
        self.last_match_score=min(matched_scores) if matched_scores else 0.
        return ''.join(output)
    def regions(self,image,profile,delta):
        from hud_layout import template_for
        rw,rh=profile['reference_size'];fx=image.shape[1]/rw;fy=image.shape[0]/rh
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);dx,dy=delta;anchors={};anchor_scores={}
        sx,sy=profile.get('hud_scale',[1,1]);origin=profile['counter_marker_origin']
        marker_x=round((origin[0]+dx)*fx)
        for key,reference in [('kills',profile['kills']),('assists',profile.get('assists',[2202,94,2228,124])),('participation',profile.get('participation',[2260,94,2300,124]))]:
            # 不同游戏 HUD 可能只有击杀/助攻，没有参与数；各字段必须跟随图标，不能固定平移。
            x1=max(0,marker_x-round(300*sx*fx));x2=min(image.shape[1],marker_x)
            y1=max(0,round((reference[1]+dy)*fy)-8);y2=min(image.shape[0],round((reference[3]+dy)*fy)+8)
            region=gray[y1:y2,x1:x2]
            for template in [self.templates[key],*self.extra_templates.get(key,[])]:
                if template is None:continue
                template=template_for(profile,template)
                for factor in [.75,1.,1.25]:
                    scaled=cv2.resize(template,None,fx=fx*2*factor,fy=fy*2*factor)
                    if region.shape[0]<scaled.shape[0] or region.shape[1]<scaled.shape[1]:continue
                    _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(region,scaled,cv2.TM_CCOEFF_NORMED))
                    if score>=.84 and score>anchor_scores.get(key,0):
                        anchor_scores[key]=score;anchors[key]=(x1+point[0],y1+point[1],x1+point[0]+scaled.shape[1],y1+point[1]+scaled.shape[0])
        result={}
        for key in ['kills','assists']:
            if key in anchors:
                a=anchors[key]
                next_x=min([point[0] for name,point in anchors.items() if name!=key and point[0]>a[2]]+[marker_x])
                # 完整图标模板已经含边缘留白，不再使用包含相邻数字的旧模板边界。
                padding=max(1,round(sx*fx));left=a[2];right=min(next_x-padding,left+round(40*sx*fx))
                if right-left>=3:
                    top=max(0,a[1]-round(2*sy*fy));bottom=min(image.shape[0],a[3]+round(2*sy*fy))
                    # 图标匹配的右缘会随缩放偏 1~3 像素：从图标中线起找实际数字字形再裁，
                    # 避免切掉首位数字或带进斜分隔线；找不到字形时保持原裁剪。
                    start=(a[0]+a[2])//2;end=min(next_x-padding,a[2]+round(48*sx*fx))
                    span=digit_span(image[top:bottom,start:end]) if end-start>=3 else None
                    if span:left,right=start+span[0],start+span[1]
                    result[key]=image[top:bottom,left:right].copy()
        box=counter_box(profile,'damage');x1,y1,x2,y2=[round((v+(dx if i%2==0 else dy))*(fx if i%2==0 else fy)) for i,v in enumerate(box)]
        result['damage']=image[y1:y2,x1:x2].copy()
        return result

    def kills_crop(self,image,profile,delta):
        """按骷髅图标定位的击杀数字裁片（已放大三倍，供数字识别）；没有图标时返回 None。"""
        if delta is None:return None
        try:region=self.regions(image,profile,delta).get('kills')
        except (cv2.error,ValueError,KeyError):return None  # 旧配置或测试配置缺少计分栏锚点时不补读
        if region is None or not region.size:return None
        return cv2.resize(region,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)

    def patches(self,image,profile,delta):
        return {key:digit_view(region) for key,region in self.regions(image,profile,delta).items()}
