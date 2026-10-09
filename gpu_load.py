"""GPU 工作节奏：限制突发批次，并在推理间给其他程序留出时间。"""
import os

POLICIES={
    'low':{'name':'low','label':'低占用','batch':4,'duty':.25,'min_pause':.025,'decode_rate':2},
    'balanced':{'name':'balanced','label':'均衡','batch':8,'duty':.50,'min_pause':.010,'decode_rate':5},
    'fast':{'name':'fast','label':'全速','batch':24,'duty':1.,'min_pause':0.,'decode_rate':None},
}

def get_gpu_policy(mode=None):
    name=mode or os.environ.get('APEX_GPU_LOAD','fast')
    if name not in POLICIES: raise ValueError('GPU 档位必须是 low、balanced 或 fast')
    return dict(POLICIES[name])

def cooldown_seconds(active_seconds,policy):
    if policy['duty']>=1: return 0.
    return max(policy['min_pause'],max(0.,active_seconds)*(1/policy['duty']-1))
