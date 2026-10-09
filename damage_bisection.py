"""按累计伤害/击杀的变化二分细查；未知或状态变化时保留补扫，不能证明零漏检。"""
from collections import Counter
import math

def plan_damage_search(length,fps,query,anchor_seconds=20,unknown_seconds=5,context_seconds=25,include_ammo=False):
    if length<1: return {'probe_indices':[],'dense_indices':[],'windows':[],'growth_brackets':[]}
    observed={}; points={}; growth=[]; uncertain=[]
    def read(i):
        i=max(0,min(length-1,i))
        if i not in observed: observed[i]=query(i)
        return observed[i]
    def snapshot(i):
        if i in points: return points[i]
        neighbours=[read(j) for j in range(max(0,i-1),min(length,i+2))]
        center=read(i); value={k:center.get(k) for k in ['inactive_view','downed','ammo','weapon_icon']}
        for key in ['damage','kills']:
            counts=Counter(r.get(key) for r in neighbours if r.get(key) is not None and not r.get('inactive_view'))
            value[key]=next((v for v,n in counts.most_common() if n>=2),None)
        points[i]=value; return value
    def changed(a,b):
        return any(a[k]!=b[k] for k in ['damage','kills','inactive_view','downed'])
    def increase(a,b):
        return any(b[k] is not None and b[k]>0 and (a[k] is None or b[k]>a[k]) for k in ['damage','kills'])
    def lifecycle(a,b):
        return a['inactive_view']!=b['inactive_view'] or a.get('downed') or b.get('downed')
    def search(left,right):
        a,b=snapshot(left),snapshot(right)
        if right-left<=max(1,round(fps)):
            if increase(a,b) or lifecycle(a,b): growth.append((left,right))
            return
        middle=(left+right)//2; c=snapshot(middle)
        evidence=changed(a,c) or changed(c,b) or any(p.get('downed') for p in [a,b,c])
        known=all(p['damage'] is not None for p in [a,b,c])
        if not evidence and known: return
        absent=all(p['damage'] is None and p['kills'] is None for p in [a,b,c])
        menu=absent and all(p['ammo'] is None for p in [a,b,c]) and not evidence
        if menu: return
        if not known and right-left<=max(1,round(unknown_seconds*fps)):
            if increase(a,c) or increase(c,b) or lifecycle(a,b): growth.append((left,right))
            if include_ammo:
                from apex_clipper import icon_similarity
                for before,after in [(a,c),(c,b)]:
                    if before['ammo'] is not None and after['ammo'] is not None and 1<=before['ammo']-after['ammo']<=50:
                        if before.get('weapon_icon') and after.get('weapon_icon') and icon_similarity(before['weapon_icon'],after['weapon_icon'])>=.65:
                            uncertain.append((left,right)); break
            return
        search(left,middle); search(middle,right)
    stride=max(1,round(anchor_seconds*fps))
    anchors=sorted(set(range(0,length,stride))|{length-1})
    for left,right in zip(anchors,anchors[1:]): search(left,right)
    windows=[]
    padding=math.ceil(context_seconds*fps)
    for left,right in sorted(growth+uncertain):
        start=max(0,left-padding); end=min(length-1,right+padding)
        if windows and start<=windows[-1][1]+1: windows[-1][1]=max(windows[-1][1],end)
        else: windows.append([start,end])
    dense=set()
    for start,end in windows: dense.update(range(start,end+1))
    return {'probe_indices':sorted(observed),'dense_indices':sorted(dense),'windows':windows,
            'growth_brackets':growth,'unknown_activity_brackets':uncertain,
            'warning':'累计值相同并不能排除无伤害交火或中间换局；本计划需要独立补扫，禁止自动回收原片。'}
