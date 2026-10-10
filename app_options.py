"""桌面参数与原录像回收策略；导出和可选无损校验分别控制。"""
import math
from pathlib import Path

DEFAULTS={'gap':35.,'pre':10.,'post':15.,'fps':2.}
LIMITS={'gap':(0,600),'pre':(0,120),'post':(0,180),'fps':(.5,5)}

def parse_options(request,legacy=False):
    values={}
    for key,default in DEFAULTS.items():
        raw=request.get(key,default)
        if isinstance(raw,bool): raise ValueError(f'{key} 必须是数值')
        try: value=float(raw)
        except (TypeError,ValueError): raise ValueError(f'{key} 必须是数值')
        low,high=LIMITS[key]
        if not math.isfinite(value) or not low<=value<=high:
            raise ValueError(f'{key} 必须在 {low}–{high} 范围内')
        values[key]=value
    for key,default in [('delete_source',False),('verify',True),('pipeline',True)]:
        value=request.get(key,default)
        if not isinstance(value,bool): raise ValueError(f'{key} 必须是布尔值')
        values[key]=value
    from gpu_load import get_gpu_policy
    values['gpu_load']=get_gpu_policy(request.get('gpu_load','low'))['name']
    values['scan_mode']=request.get('scan_mode','indexed')
    if values['scan_mode'] not in ['complete','smart','indexed']: raise ValueError('识别方式必须是 complete、smart 或 indexed')
    # 新任务统一索引算法；旧任务只在恢复时保留原规划和缓存，避免混用断点。
    if not legacy: values['scan_mode']='indexed'
    if values['scan_mode']!='complete': values['pipeline']=False
    enabled=request.get('filter_enabled',False)
    if not isinstance(enabled,bool):raise ValueError('过滤开关必须是布尔值')
    values['filter_enabled']=enabled;values['filter_mode']=request.get('filter_mode','any')
    if values['filter_mode'] not in ['any','all']:raise ValueError('过滤条件必须是 any 或 all')
    for key,limit in [('min_damage',20000),('min_kills',60),('min_assists',99)]:
        value=request.get(key,0)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value!=int(value) or not 0<=value<=limit:raise ValueError(key+'必须是范围内的非负整数')
        values[key]=int(value)
    return values

def recycle_source(source,identity,outputs,verification,review,segments,recycler=None):
    """从已完成记录回收源文件；拒绝未完成、来源变化或有待复核内容的任务。"""
    from apex_clipper import fingerprint
    source=Path(source).resolve()
    if not outputs: return {'status':'kept','reason':'没有交战视频输出'}
    if review or any(s.get('team_end_needs_review') for s in segments):
        return {'status':'kept','reason':'有待复核候选或交战结束边界，保留原录像'}
    if verification is not None and not all(verification.get(k) is True for k in
        ['passed','encoded_payloads_unchanged','all_tracks_preserved','monotonic_dts']):
        return {'status':'kept','reason':'无损校验未通过'}
    if verification is not None and Path(verification.get('source','')).resolve()!=source:
        return {'status':'kept','reason':'校验记录的源录像不匹配'}
    files=[Path(p).resolve() for p in outputs]
    verified=[Path(p).resolve() for p in verification.get('outputs',[])] if verification is not None else files
    if len(files)!=len(set(files)) or files!=verified:
        return {'status':'kept','reason':'成片清单与校验记录不匹配'}
    if source in files or any(not p.is_file() or p.stat().st_size==0 for p in files):
        return {'status':'kept','reason':'成片缺失或输出路径与源录像相同'}
    if not source.is_file() or fingerprint(source)!=identity:
        return {'status':'kept','reason':'源录像在处理期间发生变化'}
    try:
        if recycler is None:
            # 强制使用 Windows 8+ 的 IFileOperation，不回退到永久删除接口。
            from send2trash.win.modern import send2trash
            recycler=send2trash
        recycler(str(source))
        if source.exists(): raise OSError('回收站操作后源文件仍存在')
        return {'status':'recycled','reason':'已移入 Windows 回收站'}
    except Exception as error:
        return {'status':'kept','reason':'无法移入回收站：'+str(error)}
