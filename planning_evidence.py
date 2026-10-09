"""规划层区分真正的新计数与回落后的反复读数；原OCR行和最终统计不改动。"""
def classify_seed_strength(rows,seeds):
    high={'damage':None,'kills':None}; previous_t={'damage':None,'kills':None}; rebounds=set()
    for row in rows:
        if row.get('inactive_view'): continue
        for field in high:
            value=row.get(field)
            if value is None: continue
            # 确认零基线后允许新局重新增长；普通误读回落不抬高活动等级。
            if value==0:
                high[field]=0; previous_t[field]=row['time']; continue
            old=high[field]
            if old is not None and value<=old: rebounds.add((field,row['time']))
            if old is None or value>old: high[field]=value
            previous_t[field]=row['time']
    result=[]
    for seed in seeds:
        item=dict(seed)
        if seed['reason'] in ['damage','kills'] and (seed['reason'],seed['end']) in rebounds:
            item['reason']='counter_rebound_or_uncertain'
        result.append(item)
    return result

def focused_windows(rows,seeds,duration,merge_windows,gap=35):
    """保留所有不确定证据的局部检查，但不让零散误读连成数分钟连续细查。"""
    from adaptive_evidence import evidence_windows
    strong=[s for s in seeds if s['reason'] in ['damage','kills','ammo_change','recording_started_in_play']]
    weak=[s for s in seeds if s not in strong]
    windows=evidence_windows(rows,strong,duration,merge_windows,gap)
    patches=[{'start':max(0,s['start']-(10 if s['reason']=='team_or_downed' else 3)),
              'end':min(duration,s['end']+6)} for s in weak]
    combined=merge_windows([{'start':a,'end':b} for a,b in windows]+patches,duration,0)
    # 计分确认需要后继帧；不能恰在窗口末尾截掉确认样本而把事件时间提前。
    return merge_windows([{'start':a,'end':min(duration,b+1.1)} for a,b in combined],duration,0)
