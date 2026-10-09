"""区分需要识别的证据时间与成片保留时间；只规划，不伪造采样行。"""
import os


def decode_policy(video,cuda):
    """本机低GPU档把H.264细查交给有限CPU线程，GPU只运行受节奏限制的OCR。"""
    from gpu_load import get_gpu_policy
    if (cuda and get_gpu_policy()['name']=='low' and (os.cpu_count() or 1)>=16
            and video.get('codec_name')=='h264' and video.get('pix_fmt') in ['yuv420p','yuvj420p','nv12']
            and os.environ.get('APEX_SMART_CPU_DECODE','1')!='0'):
        return False,4,'cpu4_low_gpu'
    return cuda,None,'cuda' if cuda else 'cpu'


def refinement_names(rows, seeds):
    """优先复读已存在的关键帧，避免为二分反复启动解码器。"""
    windows=[(s['start']-2.5,s['end']+2.5) for s in seeds]
    return {r['frame'] for r in rows if r.get('ammo') is None
            and any(a<=r['time']<=b for a,b in windows)}


def evidence_windows(rows,seeds,duration,merge_windows,gap=35):
    # 多留三秒用于双帧确认、命中前的开火、换弹与结束画面。
    groups=[]
    for seed in sorted(seeds,key=lambda s:s['start']):
        # 两端各有一个关键帧间隔的不确定性，不能把长TTK拉扯拆断。
        if groups and seed['start']-groups[-1]['end']<=gap+5:
            groups[-1]['end']=max(groups[-1]['end'],seed['end'])
        else: groups.append({'start':seed['start'],'end':seed['end']})
    windows=merge_windows(groups,duration,3.)
    # HUD 初次显现可能是从半局录入；头部短锚点建立真实基线。
    anchors=[]
    visible=[r for r in rows if not r.get('inactive_view') and
             (r.get('damage') is not None or r.get('kills') is not None)]
    if visible:
        anchors.append(visible[0])
        last=visible[0]['time']
        for r in visible[1:]:
            # 目标间隔12秒；在约8秒的粗查网格上通常为16秒，低于20秒连续性限制。
            if r['time']-last>=12:
                anchors.append(r); last=r['time']
        anchors.append(visible[-1])
    pieces=[{'start':0,'end':min(duration,1.5)}]+[{'start':a,'end':b} for a,b in windows]
    pieces += [{'start':max(0,r['time']-1),'end':min(duration,r['time']+1)} for r in anchors]
    # 视角转换是队伍战斗结束的重要证据：保留5秒文字识别尾部。
    pieces += [{'start':max(0,s['start']-3),'end':min(duration,s['end']+6)} for s in seeds
               if s['reason'] in ['view_transition','team_or_downed','counter_reset_or_uncertain']]
    # 友方绿色提示会闪现，不能要求粗查帧刚好命中。本人倒地后切观战，
    # 细查整个本次观战直到重新出现可读的本人武器HUD；最终导出仍由真实全灭/友方证据决定。
    last_downed=None; watching=None
    for r in rows:
        t=r['time']
        if r.get('downed'):
            last_downed=t
            pieces.append({'start':max(0,t-3),'end':min(duration,t+15)})
        if r.get('inactive_view') and (r.get('friend_spectate') or last_downed is not None and t-last_downed<=15):
            if watching is None: watching=max(0,t-3)
        if watching is not None and not r.get('inactive_view') and r.get('ammo') is not None:
            pieces.append({'start':watching,'end':min(duration,t+6)}); watching=None; last_downed=None
    if watching is not None: pieces.append({'start':watching,'end':duration})
    return merge_windows(pieces,duration,0)
