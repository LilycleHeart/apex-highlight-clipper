"""持久批次、成片完整性与进程锁；恢复时沿用原任务参数和输出目录。"""
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import uuid

def load(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def planner_for_item(task,item,was_pending,has_cache):
    """只给尚未开始且没有旧缓存的同规则任务升级规划，保留进行中的断点。"""
    current=item.get('smart_cache_version',task.get('smart_cache_version','smart-v2'))
    if (current=='evidence-v3' and was_pending and not has_cache and
            task.get('result_filter_version')=='own-center-result-v4'):
        return 'focused-v6'
    return current

def config_stamp(profile):
    from apex_clipper import BASE
    from weapon_reader import MODEL_SHA
    files=[BASE/profile['counter_marker'],BASE/profile['downed_marker'],BASE/'weapon-catalog.json']
    data={'profile':profile,'model':MODEL_SHA,'pipeline':'resume-v1','files':[hashlib.sha256(p.read_bytes()).hexdigest() for p in files]}
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

@contextmanager
def task_lock(directory):
    import msvcrt
    path=Path(directory)/'.resume.lock'; stream=path.open('a+b')
    stream.seek(0,os.SEEK_END)
    if stream.tell()==0: stream.write(b'0'); stream.flush()
    stream.seek(0)
    try: msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        stream.close(); raise RuntimeError('这个任务或录像正在另一个进程处理，请稍后继续')
    try: yield
    finally:
        stream.seek(0); msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1); stream.close()

def open_task(request):
    from apex_clipper import BASE,fingerprint,write_json
    from app_options import parse_options
    if request.get('resume_task'):
        path=Path(request['resume_task']).resolve(); task=load(path)
        if task.get('version')!=1 or Path(task['directory']).resolve()!=path.parent: raise ValueError('任务记录格式或目录不匹配')
        if config_stamp(task['profile'])!=task['config_stamp']: raise ValueError('HUD 配置、模型或枪械目录已变化，请新建任务')
        effective=dict(task['request'])
        for key in ['backend','gpu_load','pipeline']:
            if key in request: effective[key]=request[key]
        options=parse_options(effective)
        task['request']=effective; task['finished']=False
    else:
        from combat_outcome_reader import RULE_VERSION
        profile=load(BASE/'profile-ultrawide.json'); options=parse_options(request)
        if options['fps']<1: raise ValueError('新任务细查频率至少为 1 帧/秒，建议使用默认 2 帧/秒')
        effective={**request,**options}
        output=Path(request['output']).resolve(); output.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y年%m月%d日 %H点%M分%S秒')
        directory=output/('任务 '+stamp+' '+uuid.uuid4().hex[:4]); directory.mkdir()
        path=directory/'task.json'; items=[]; names=set()
        for name in request['files']:
            source=Path(name).resolve(); identity=fingerprint(source) if source.is_file() else None
            destination=directory/source.stem
            if destination.name in names: destination=directory/(source.stem+'_'+str(len(items)+1))
            names.add(destination.name)
            items.append({'source':str(source),'source_identity':identity,'destination':str(destination),
                'status':'pending','stage':'pending','record':None})
        if not items: raise ValueError('没有选择录像')
        task={'version':1,'directory':str(directory),'request':effective,'profile':profile,
            'config_stamp':config_stamp(profile),'items':items,'finished':False,'smart_cache_version':'focused-v6',
            'result_filter_version':RULE_VERSION}
        write_json(path,task)
    if effective.get('backend') not in ['cpu','dml']: raise ValueError('识别后端不支持')
    return path,task,effective,options

def save_task(path,task):
    from apex_clipper import BASE,write_json
    write_json(path,task)
    records=[item['record'] for item in task['items'] if item.get('record')]
    write_json(Path(task['directory'])/'batch-results.json',records)
    if os.environ.get('APEX_DISABLE_LAST_TASK')!='1':
        write_json(BASE/'validation/app-last-task.json',{'task':str(path),'finished':task['finished']})

def outputs_intact(record):
    from apex_clipper import fingerprint
    if not record or record.get('status')!='complete': return False
    outputs=record.get('outputs',[]); identities=record.get('output_identities',[])
    if not outputs:
        return (Path(record['directory'])/'analysis.json').is_file()
    if len(outputs)!=len(identities): return False
    return all(Path(path).is_file() and fingerprint(path)==identity for path,identity in zip(outputs,identities))
