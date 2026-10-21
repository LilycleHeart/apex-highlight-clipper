"""Validated, immutable-at-launch resource settings; recognition rules are unchanged."""
import math
import os

PRESETS={
    'low':dict(gpu_load='low',cpu_workers=1,decode_threads=1,frame_cache_mb=32),
    'balanced':dict(gpu_load='fast',cpu_workers=3,decode_threads=1,frame_cache_mb=64),
    'high':dict(gpu_load='fast',cpu_workers=3,decode_threads=1,frame_cache_mb=64),
}
LIMITS={'cpu_workers':(1,1024),'decode_threads':(1,4),'frame_cache_mb':(16,128)}
RESOURCE_ENV={'cpu_workers':'APEX_HUD_WORKERS','decode_threads':'APEX_DECODE_THREADS','frame_cache_mb':'APEX_FRAME_CACHE_MB'}


def performance_options(request):
    preset=request.get('performance_preset','balanced')
    if preset not in (*PRESETS,'custom'):raise ValueError('性能档位无效')
    if 'performance_preset' not in request and (any(key in request for key in LIMITS) or request.get('gpu_load','fast')!='fast'):preset='custom'
    values=dict(PRESETS['balanced'],performance_preset=preset)
    for key,(low,high) in LIMITS.items():
        raw=request.get(key,values[key])
        if isinstance(raw,bool) or not isinstance(raw,(int,float)) or not math.isfinite(raw) or raw!=int(raw) or not low<=raw<=high:raise ValueError(key+' 参数超出范围')
        values[key]=int(raw)
    from gpu_load import get_gpu_policy
    values['gpu_load']=get_gpu_policy(request.get('gpu_load',values['gpu_load']))['name']
    if preset!='custom':values.update(PRESETS[preset])
    return values


def worker_limit(backend,wanted,cores=None):
    logical=max(1,cores if cores is not None else os.cpu_count() or 1)
    return min(int(wanted),max(1,logical//2) if backend=='cpu' else logical)


def apply_resources(request):
    """Called once in a dedicated task process; children inherit the snapshot."""
    settings=performance_options(request)
    backend=request.get('backend','cpu')
    settings['cpu_workers']=worker_limit(backend,settings['cpu_workers'])
    for key,env in RESOURCE_ENV.items():os.environ[env]=str(settings[key])
    os.environ['APEX_SCHEDULE_PRESET']=settings['performance_preset']
    os.environ['APEX_ADAPTIVE_HUD']='1'
    # Avoid multiplying OpenCV's global thread pool by each clip worker.
    import cv2
    cv2.setNumThreads(1)
    return settings


def inherited_resources():
    values={key:int(os.environ.get(env,PRESETS['balanced'][key])) for key,env in RESOURCE_ENV.items()}
    if os.environ.get('APEX_ADAPTIVE_HUD')=='1':values.update(adaptive_schedule=True,schedule_preset=os.environ.get('APEX_SCHEDULE_PRESET','high'))
    return values


def native_resources():
    """Read bounded defaults once when opening a decoder, including legacy calls."""
    values={}
    for key in ('decode_threads','frame_cache_mb'):
        low,high=LIMITS[key]
        try:value=int(os.environ.get(RESOURCE_ENV[key],PRESETS['balanced'][key]))
        except (ValueError,TypeError):value=PRESETS['balanced'][key]
        values[key]=min(high,max(low,value))
    return values
