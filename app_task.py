"""持久批次、成片完整性与进程锁；恢复时沿用原任务参数和输出目录。"""
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
import re
from pathlib import Path
import uuid
import sys

def load(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def data_root(request=None):
    """稳定的用户数据目录；版本升级不改变任务、分析和断点的位置。"""
    override=os.environ.get('APEX_DATA_ROOT') or (request or {}).get('data_root')
    if override: return Path(override).expanduser().resolve()
    if sys.platform=='win32': return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'Apex Highlight Clipper'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'apex-highlight-clipper'

def task_cache_root(task):
    from apex_clipper import BASE
    return Path(task['data_root'])/'validation/app-cache' if task.get('version')==2 else BASE/'validation/app-cache'

def recorded_cache(task,item,config):
    """仅恢复任务明确登记、来源及配置匹配的旧安装缓存，调用者仍须持有缓存锁。"""
    if task.get('version')!=1:return None
    base=hashlib.sha256(json.dumps({**config,'cache_version':'resume-v1'},sort_keys=True).encode()).hexdigest()[:16]
    for raw in [item.get('analysis_cache'),(item.get('record') or {}).get('analysis_cache')]:
        if not isinstance(raw,str) or not Path(raw).is_absolute():continue
        cache=Path(raw).resolve()
        if not re.fullmatch(r'[a-f0-9]{16}',cache.name) or cache.parent.name!='app-cache' or cache.parent.parent.name!='validation' or not cache.is_dir():continue
        try:
            use=load(cache/'.cache-use.json')
            if Path(use['source']).resolve()!=Path(item['source']).resolve() or Path(use['task']).resolve()!=Path(task['directory']).resolve()/'task.json':continue
            name=base;seen=set()
            while name!=cache.name and name not in seen:
                seen.add(name);marker=cache.parent/name/'.images-pruned.json'
                if not marker.is_file():break
                name=hashlib.sha256((name+load(marker)['generation']).encode()).hexdigest()[:16]
            if name!=cache.name:continue
            if (cache/'hud.json').is_file():
                hud=load(cache/'hud.json')
                if hud.get('source')!=config['source'] or hud.get('profile')!=config['profile'] or hud.get('fps')!=config['fps']:continue
            return cache
        except (OSError,ValueError,KeyError,TypeError):continue
    return None

def validate_task(task,path):
    path=Path(path).resolve()
    if task.get('version') not in (1,2) or Path(task['directory']).resolve()!=path.parent:
        raise ValueError('任务记录格式或目录不匹配')
    directory=path.parent
    for item in task['items']:
        destination=Path(item['destination']).resolve()
        if destination==directory or not destination.is_relative_to(directory):raise ValueError('任务分析目录无效')
        if task['version']==2:
            output=Path(task['request']['output']).resolve();video=Path(item['video_directory']).resolve()
            if video!=Path(task['video_directory']).resolve() or not video.is_relative_to(output):raise ValueError('任务视频目录无效')
            if destination.is_relative_to(video) or video.is_relative_to(destination):raise ValueError('视频和分析目录必须分离')
            if not re.fullmatch(r'[a-f0-9]{8}-\d+',item.get('export_suffix','')):raise ValueError('导出文件标识无效')
            for file in (item.get('record') or {}).get('outputs',[]):
                target=Path(file).resolve()
                if target.parent!=video or target.suffix.lower()!='.mp4':raise ValueError('任务成片路径无效')
    if task['version']==2 and directory.parent!=(Path(task['data_root'])/'tasks').resolve():raise ValueError('任务数据目录无效')

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
        validate_task(task,path)
        if config_stamp(task['profile'])!=task['config_stamp']: raise ValueError('HUD 配置、模型或枪械目录已变化，请新建任务')
        effective=dict(task['request'])
        for key in ['backend','gpu_load','pipeline']:
            if key in request: effective[key]=request[key]
        options=parse_options(effective,legacy=True)
        task['request']=effective; task['finished']=False
    else:
        from combat_outcome_reader import RULE_VERSION
        profile=load(BASE/'profile-ultrawide.json'); options=parse_options(request)
        if options['fps']<1: raise ValueError('新任务细查频率至少为 1 帧/秒，建议使用默认 2 帧/秒')
        effective={**request,**options}
        output=Path(request['output']).resolve(); output.mkdir(parents=True,exist_ok=True)
        moment=datetime.now(timezone(timedelta(hours=8)))
        # Windows英文区域的strftime会先用locale编码格式串；中文放在格式串外。
        stamp=f'{moment:%Y}年{moment:%m}月{moment:%d}日 {moment:%H}点{moment:%M}分{moment:%S}秒'
        task_id=uuid.uuid4().hex;root=data_root(request);directory=root/'tasks'/task_id
        video_directory=output/('整理 '+stamp+' '+task_id[:8]) if options['export_layout']=='task' else output
        if directory.is_relative_to(video_directory) or video_directory.is_relative_to(directory):raise ValueError('请将视频输出位置设在软件数据目录之外')
        directory.mkdir(parents=True);video_directory.mkdir(parents=True,exist_ok=True)
        path=directory/'task.json'; items=[]; names=set()
        for name in request['files']:
            source=Path(name).resolve(); identity=fingerprint(source) if source.is_file() else None
            destination=directory/source.stem
            if destination.name.casefold() in names: destination=directory/(source.stem+'_'+str(len(items)+1))
            names.add(destination.name.casefold())
            items.append({'source':str(source),'source_identity':identity,'destination':str(destination),
                'video_directory':str(video_directory),'export_suffix':f'{task_id[:8]}-{len(items)+1}',
                'status':'pending','stage':'pending','record':None})
        if not items: raise ValueError('没有选择录像')
        task={'version':2,'directory':str(directory),'data_root':str(root),'video_directory':str(video_directory),'request':effective,'profile':profile,
            'config_stamp':config_stamp(profile),'items':items,'finished':False,
            'smart_cache_version':'indexed-v2' if options['scan_mode']=='indexed' else 'focused-v6',
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
        write_json(Path(task.get('data_root',data_root()))/'validation/app-last-task.json',{'task':str(path),'finished':task['finished']})

def outputs_intact(record):
    from apex_clipper import fingerprint
    from clip_deletions import is_removed
    if not record or record.get('status')!='complete': return False
    outputs=record.get('outputs',[]); identities=record.get('output_identities',[])
    if not outputs:
        return (Path(record['directory'])/'analysis.json').is_file()
    if len(outputs)!=len(identities): return False
    return all(is_removed(path) or Path(path).is_file() and fingerprint(path)==identity for path,identity in zip(outputs,identities))
