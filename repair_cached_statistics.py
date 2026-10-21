"""补齐旧任务；显式原生复核可纠正非空误读，修复记录存入软件目录。"""
import hashlib
import copy
import json
import os
import math
import time
from contextlib import contextmanager
from dataclasses import dataclass,replace
from pathlib import Path
import sys


@dataclass(frozen=True)
class PreparedRepair:
    directory:Path
    original_sha256:str
    target:Path
    report:dict
    selected:tuple
    media_identities:tuple=()
    computed_fields:tuple=()


def prepare_repair(record,on_activity=None):
    """Compute one clip's evidence without writing a shared correction file."""
    from native_frame_reader import native_frame_session
    from apex_clipper import fingerprint
    identities=tuple(fingerprint(Path(file)) for file in record.get('files',[]))
    original=Path(record['directory'])/'statistics.json'
    if original.is_file():record=_existing_recheck_request(record,original.read_bytes(),original)
    with native_frame_session():result=_repair(record,on_activity,deferred=True)
    if any(fingerprint(Path(identity['path']))!=identity for identity in identities):raise ValueError('成片在后台复核期间发生变化')
    return replace(result,media_identities=identities) if isinstance(result,PreparedRepair) else result


def commit_repair(prepared,on_activity=None):
    """Rebase untouched segments under the record lock, then atomically save."""
    if prepared is None:return None
    from app_task import data_root
    from apex_clipper import write_json,fingerprint
    original=prepared.directory/'statistics.json';raw=original.read_bytes()
    key=correction_key(raw,prepared.directory)
    with correction_lock(data_root()/'recognition-corrections/locks'/(key+'.lock'),on_activity):
        if hashlib.sha256(raw).hexdigest()!=prepared.original_sha256 or original.read_bytes()!=raw:raise ValueError('统计记录已变化，请重新开始复核')
        if any(fingerprint(Path(identity['path']))!=identity for identity in prepared.media_identities):raise ValueError('成片在后台复核后发生变化，请重新识别')
        target=data_root()/'recognition-corrections'/(key+'.json')
        if target!=prepared.target:raise ValueError('复核保存位置已变化')
        report=copy.deepcopy(prepared.report)
        try:
            latest=json.loads(target.read_text('utf-8-sig'))
            valid=latest.get('repair_signature')==hashlib.sha256(raw+latest.get('version','').encode()+latest.get('counter_recipe','').encode()).hexdigest()
            context=str(prepared.directory.resolve()).replace('\\','/').lower()
            if valid and latest.get('correction_context',context)==context:
                by_bounds={(segment['start'],segment['end']):segment for segment in latest['segments']}
                selected={(report['segments'][index]['start'],report['segments'][index]['end']) for index in prepared.selected}
                report['segments']=[segment if (segment['start'],segment['end']) in selected else copy.deepcopy(by_bounds.get((segment['start'],segment['end']),segment)) for segment in report['segments']]
        except (OSError,ValueError,TypeError,KeyError,AttributeError):pass
        report['verification_mode']='native-existing' if any(segment.get('native_repaired_fields') for segment in report['segments']) else 'missing'
        write_json(target,report)
        return report


def opponent_needs_review(event):
    from combat_outcome_reader import PARSER_VERSION
    from target_name_reader import name_recipe
    if event.get('confirmed') is False and event.get('ownership')=='self':return True
    if event.get('native_event_version'):
        from combat_candidate_completion import VERSION as EVENT_VERSION,recipe as event_recipe
        if event.get('native_event_version')!=EVENT_VERSION or event.get('native_event_recipe')!=event_recipe() or event.get('native_event_status')!='confirmed':return True
    return (event.get('native_name_status')!='confirmed' or event.get('native_name_version')!=PARSER_VERSION or event.get('native_name_recipe')!=name_recipe()
            or event.get('kind')=='assist' and (event.get('native_action_status')!='confirmed' or event.get('native_action_version')!=PARSER_VERSION))


def needs_fields(segment,requested):
    return ('statistics' in requested and (any(segment['counts'].get(key) is None or segment['partial'].get(key,False) for key in ['kills','assists','damage']) or bool(segment.get('counter_verification_pending')) or bool(set(segment.get('native_repaired_fields',[]))-set(native_verified_fields(segment.get('endpoint',{})))) )
            or 'opponents' in requested and any(opponent_needs_review(event) for event in segment.get('events',[]))
            or 'event_weapons' in requested and any(event.get('confirmed') is True and event.get('ownership')=='self' and event.get('weapon_context',{}).get('status')!='observed' for event in segment.get('events',[])))


def recheck_event_names(source,events,profile,force,on_activity,selected_keys=None):
    from combat_outcome_reader import native_target_names,PARSER_VERSION
    from target_name_reader import name_recipe
    from apex_clipper import fingerprint
    identity=fingerprint(source) if any(event.get('native_name_source') or event.get('native_event_source') for event in events) else None
    def source_changed(event):
        if identity is None:return False
        for key in ['native_name_source','native_event_source']:
            saved=event.get(key)
            if saved and not isinstance(saved,dict):return True
            if saved and (str(saved.get('path','')).replace('\\','/').casefold()!=str(identity['path']).replace('\\','/').casefold() or saved.get('size')!=identity['size'] or saved.get('mtime_ms')!=identity['mtime_ns']//1000000):return True
        return False
    selected=[index for index,event in enumerate(events)
              if (selected_keys is None or (event.get('kind'),round(event.get('time',-1),6)) in selected_keys)
              and (force or opponent_needs_review(event) or source_changed(event))]
    if not selected:return events
    if identity is None:identity=fingerprint(source)
    pending=[]
    for index in selected:
        event=copy.deepcopy(events[index])
        if force or source_changed(event) or event.get('native_name_version')!=PARSER_VERSION or event.get('native_name_recipe')!=name_recipe():
            event.update(native_name_status='unconfirmed',native_name_version=PARSER_VERSION,native_name_recipe=name_recipe(),native_name_evidence=[])
        if event.get('kind')=='assist' and (force or source_changed(event) or event.get('native_action_version')!=PARSER_VERSION):
            event.update(native_action_status='unconfirmed',native_action_version=PARSER_VERSION,native_action_evidence=[])
        pending.append(event)
    fresh=native_target_names(source,pending,hud_profile=profile,on_activity=on_activity,context_events=events)
    result=list(events)
    model_source={'path':identity['path'],'size':identity['size'],'mtime_ms':identity['mtime_ns']//1000000}
    for index,event in zip(selected,fresh):result[index]={**event,'native_name_source':dict(model_source)}
    from combat_candidate_completion import VERSION as EVENT_VERSION,recipe as event_recipe,complete_candidates
    candidates=[index for index in selected if result[index].get('ownership')=='self' and (result[index].get('confirmed') is False or result[index].get('native_event_version') and (force or source_changed(events[index]) or result[index].get('native_event_version')!=EVENT_VERSION or result[index].get('native_event_recipe')!=event_recipe()))]
    if candidates:
        probes=[{**copy.deepcopy(result[index]),'confirmed':False} for index in candidates]
        completed=complete_candidates(source,probes,context_events=list(result),hud_profile=profile,on_activity=on_activity)
        for index,event in zip(candidates,completed):result[index]=event
    if fingerprint(source)!=identity:raise ValueError('重新识别期间录像发生变化，不能组合新旧画面证据')
    return result


def native_verified_fields(endpoint):
    from outcome_reader import SELF_VIEW_VERSION
    from numeric_reader import METHOD
    if endpoint.get('native_view_version')!=SELF_VIEW_VERSION or endpoint.get('native_numeric_method')!=METHOD:return []
    fields=[]
    for key in ['kills','assists','damage']:
        if endpoint.get('native_counter_scope')=='exported_visible_delta' and key not in endpoint.get('export_baseline_fields',[]):continue
        verified=True
        for group,frames in [('baseline','baseline_frames'),('last_hud','end_frames')]:
            value=endpoint.get(group,{}).get(key)
            if not isinstance(value,int) or isinstance(value,bool) or value<0:verified=False;break
            times={row['native_time'] for row in endpoint.get(frames,[]) if row.get('native_verified') is True and isinstance(row.get('native_time'),(int,float)) and not isinstance(row['native_time'],bool) and math.isfinite(row['native_time']) and row.get(key)==value}
            if len(times)<2:verified=False;break
        latest=endpoint.get('unconfirmed_latest',{}).get(key)
        if latest is not None and endpoint.get('last_hud',{}).get(key) is not None and latest<endpoint['last_hud'][key]:verified=False
        if verified and endpoint['last_hud'][key]<endpoint['baseline'][key]:verified=False
        if verified:fields.append(key)
    return fields


def exported_clips(destination,report):
    try:manifest=json.loads((destination/'export.json').read_text('utf-8-sig'))
    except (OSError,ValueError):return []
    if manifest.get('source')!=report.get('source'):return []
    if manifest.get('metadata_directory') and Path(manifest['metadata_directory']).resolve()!=destination.resolve():return []
    video_root=Path(manifest.get('video_directory',destination)).resolve()
    outputs={str(Path(path).resolve()).casefold() for path in manifest.get('outputs',[]) if isinstance(path,str)}
    clips=[]
    for clip in manifest.get('clips',[]):
        raw=clip.get('output',clip.get('file'))
        if not isinstance(raw,str):continue
        file=Path(raw).resolve()
        if file.suffix.lower()!='.mp4' or str(file).casefold() not in outputs or not file.is_relative_to(video_root) or not file.is_file():continue
        stat=file.stat();identity={'path':str(file),'size':stat.st_size,'mtime_ms':stat.st_mtime_ns//1_000_000}
        clips.append((clip,identity))
    return clips


def exported_view(clips,segment,profile):
    from apex_clipper import probe
    for clip,identity in clips:
        bound=clip.get('segment',{})
        if any(abs(bound.get(key,-1)-segment[key])>.001 for key in ['start','end']):continue
        source=Path(identity['path']);metadata,video=probe(source)
        try:origin=float(video.get('start_time') or 0)
        except (TypeError,ValueError):origin=0.
        if not math.isfinite(origin):origin=0.
        try:duration=float(video.get('duration') or metadata['format']['duration'])
        except (TypeError,ValueError):duration=float(metadata['format']['duration'])
        if not math.isfinite(duration) or duration<=0:duration=float(metadata['format']['duration'])
        if duration<.35:return None
        selected_profile=clip.get('recognition',{}).get('hud_info',{}).get('profile') or profile
        from hud_recovery import profile_reusable,active
        if active() and not profile_reusable(clip.get('recognition',{}),['statistics','opponents','event_weapons']):selected_profile={}
        if not selected_profile.get('layout_version'):
            from hud_layout import make_profile
            selected_profile=make_profile(video['width'],video['height'])
        return source,identity,origin,duration,selected_profile
    return None


def exported_endpoint(clips,segment,profile):
    from apex_clipper import fingerprint
    from combat_statistics import counter_endpoints
    view=exported_view(clips,segment,profile)
    if view is None:return None
    source,identity,origin,duration,selected_profile=view
    moments=[origin,origin+.04,origin+.08]+sorted({origin+max(.16,duration-.04-i*.25) for i in range(5)})
    cache={'source':fingerprint(source),'profile':selected_profile,'fps':2.,'rows':[{'frame':f'native:export:{second:.5f}','time':second,'counter_marker_score':1.,'inactive_view':False} for second in moments]}
    endpoint=counter_endpoints(cache,source.parent,[{'start':origin+.12,'end':origin+duration}],selected_profile)[0]
    excluded=[row for row in endpoint['end_frames'] if row.get('excluded_view')]
    if excluded:
        endpoint['excluded_terminal_view']=True
    # 开箱、菜单和观战都会隐藏片尾计分栏。有限回看此前的本人读数，
    # 保留全部不可读片尾证据，不能把较早值冒充完整结尾。
    if all(value is None for value in endpoint['last_hud'].values()):
        terminal=list(endpoint['end_frames'])
        for distance in [1.5,3.,6.,12.,24.,48.,96.]:
            second=origin+duration-distance
            if second<origin+.24:continue
            prior={**cache,'rows':[{'frame':f'native:export:{time:.5f}','time':time,'counter_marker_score':1.,'inactive_view':False} for time in [second-.08,second]]}
            checked=counter_endpoints(prior,source.parent,[{'start':origin+.12,'end':origin+duration}],selected_profile)[0]
            if any(value is not None for value in checked['last_hud'].values()):
                for key in ['last_hud','last_hud_update','unconfirmed_latest']:endpoint[key]=checked[key]
                endpoint['end_frames']=checked['end_frames']+terminal
                endpoint['terminal_hud_hidden']=True
                break
    endpoint['export_baseline_fields']=early_export_baseline_fields(endpoint,origin)
    for rows in ['baseline_frames','end_frames']:
        for row in endpoint[rows]:row['time']+=segment['start']-origin
    endpoint.update(native_counter_scope='exported_visible_delta',exported_video_identity=identity,native_profile=selected_profile,native_video_origin=origin)
    return endpoint

def early_export_baseline_fields(endpoint,origin):
    """逐项使用80毫秒内最早的有效原生读数；首个坏帧不能遮掉随后已确认的数字。"""
    fields=[]
    for key in ['kills','assists','damage']:
        frames=sorted((row for row in endpoint.get('baseline_frames',[]) if row.get('native_verified') is True and isinstance(row.get('native_time'),(int,float)) and math.isfinite(row['native_time']) and row.get(key) is not None),key=lambda row:row['native_time'])
        first=frames[0] if frames else None
        if first and 0<=first['native_time']-origin<=.08 and first[key]==endpoint.get('baseline',{}).get(key):fields.append(key)
    return fields


def correction_key(raw,directory):
    context=str(Path(directory).resolve()).replace('\\','/').lower()
    return hashlib.sha256(raw+b'\0'+context.encode('utf-8')).hexdigest()


@contextmanager
def correction_lock(path,on_activity=None,timeout=90.):
    from app_cancel import check_cancel
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    stream=path.open('a+b');stream.seek(0,os.SEEK_END)
    if stream.tell()==0:stream.write(b'0');stream.flush()
    started=time.monotonic();last_notice=0.
    try:
        while True:
            check_cancel();stream.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()-started>=timeout:raise RuntimeError('该记录仍在其他进程中复核，请稍后重试')
                if on_activity and time.monotonic()-last_notice>=1:
                    on_activity({'message':'等待当前记录处理结束','frames_done':0,'frames_total':0});last_notice=time.monotonic()
                time.sleep(.1)
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)
    finally:stream.close()


def _existing_recheck_request(record,raw,original):
    from app_task import data_root
    if record.get('native') and not record.get('force') and 'statistics' in record.get('fields',['statistics']):
        root=data_root()/'recognition-corrections';key=correction_key(raw,original.parent)
        candidates=[root/(key+'.json'),root/(hashlib.sha256(raw).hexdigest()+'.json'),original.with_name('statistics-corrected.json')]
        wanted={str(Path(file).resolve()).casefold() for file in record['files']} if record.get('files') is not None else None
        bounds=[clip.get('segment',{}) for clip,identity in exported_clips(original.parent,json.loads(raw)) if wanted is not None and identity['path'].casefold() in wanted]
        for candidate in candidates:
            try:
                saved=json.loads(candidate.read_text('utf-8-sig'))
                if saved.get('repair_signature')!=hashlib.sha256(raw+saved.get('version','').encode()+saved.get('counter_recipe','').encode()).hexdigest():continue
                selected=[segment for segment in saved['segments'] if wanted is None or any(all(abs(segment[key]-bound.get(key,-1))<.001 for key in ['start','end']) for bound in bounds)]
                if any(segment.get('repair_applied') and 'statistics' in segment.get('repair_fields',[]) and needs_fields(segment,{'statistics'}) for segment in selected):record={**record,'recheck_existing':True}
                break
            except (OSError,ValueError,TypeError,KeyError,AttributeError):continue
    return record


def repair(record,on_activity=None):
    from app_task import data_root
    original=Path(record['directory'])/'statistics.json'
    if not original.is_file():return
    raw=original.read_bytes();key=correction_key(raw,original.parent)
    with correction_lock(data_root()/'recognition-corrections/locks'/(key+'.lock'),on_activity):
        if original.read_bytes()!=raw:raise ValueError('统计记录已变化，请重新开始复核')
        return _repair(_existing_recheck_request(record,raw,original),on_activity)


def _repair(record,on_activity=None,*,deferred=False):
    from combat_statistics import counter_endpoints,reconciled_counts,VERSION
    from apex_clipper import BASE,write_json
    destination=Path(record['directory']);original=destination/'statistics.json'
    if not original.is_file():return
    raw=original.read_bytes();report=json.loads(raw)
    requested=set(record.get('fields',['statistics']+(['opponents'] if record.get('recheck_names') else [])))
    counters='statistics' in requested;recheck_names='opponents' in requested;recheck_weapons='event_weapons' in requested
    verify_existing=counters and record.get('recheck_existing') is True
    native_exports=record.get('native') is True or verify_existing or recheck_names or recheck_weapons
    missing=any(s['counts'].get(key) is None or s['partial'].get(key,False) for s in report['segments'] for key in ['kills','assists','damage'])
    if not recheck_names and not recheck_weapons and not verify_existing and (not counters or not missing):return
    try:cache=json.loads((Path(record.get('analysis_cache',destination/'absent-cache'))/'hud.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        if not native_exports:return
        cache={'source':report.get('source'),'rows':[]}
    if cache.get('source')!=report.get('source'):
        if not native_exports:return
        cache={'source':report.get('source'),'rows':[]}
    from stat_counter_fallback import counter_recipe
    from app_task import data_root
    from combat_outcome_reader import PARSER_VERSION
    base_recipe=counter_recipe();recipe=base_recipe+(':native-existing' if verify_existing else ':missing')+(':names-'+PARSER_VERSION if recheck_names else '')
    if recheck_names:
        from target_name_reader import MODEL_SHA as name_model_sha,LATIN_MODEL_SHA,name_recipe
        from combat_candidate_completion import VERSION as EVENT_VERSION,recipe as event_recipe
        recipe+=':name-model-'+name_model_sha+':latin-model-'+LATIN_MODEL_SHA+':name-recipe-'+name_recipe()+':candidate-'+EVENT_VERSION+':candidate-recipe-'+event_recipe()
    if recheck_weapons:
        from event_weapon_reader import recipe as weapon_recipe
        recipe+=':event-weapons-'+weapon_recipe()
    clips=exported_clips(destination,report) if native_exports else []
    wanted={str(Path(file).resolve()).casefold() for file in record['files']} if record.get('files') is not None else None
    if wanted is not None and (not wanted or wanted-{identity['path'].casefold() for _,identity in clips}):raise ValueError('所选片段不在已验证的导出记录中')
    selected=[index for index,segment in enumerate(report['segments']) if wanted is None or any(identity['path'].casefold() in wanted and all(abs(clip.get('segment',{}).get(key,-1)-segment[key])<.001 for key in ['start','end']) for clip,identity in clips)]
    if wanted is not None and not selected:raise ValueError('片段没有对应的战绩区间')
    if not verify_existing and not recheck_names and not recheck_weapons and not any(report['segments'][index]['counts'].get(key) is None or report['segments'][index]['partial'].get(key,False) for index in selected for key in ['kills','assists','damage']):return
    if native_exports:
        inputs=json.dumps([identity for _,identity in clips],sort_keys=True).encode()
        recipe+=':inputs-'+hashlib.sha256(inputs).hexdigest()
    if recheck_weapons:
        profiles=[clip.get('recognition',{}).get('hud_info',{}).get('profile') for clip,_ in clips]
        recipe+=':weapon-profiles-'+hashlib.sha256(json.dumps(profiles,sort_keys=True).encode()).hexdigest()
    recipe+=':fields-'+','.join(sorted(requested))+':selection-'+hashlib.sha256(json.dumps(sorted(wanted) if wanted is not None else 'all').encode()).hexdigest()
    if recheck_names and record.get('opponent_events') is not None:
        recipe+=':opponent-selection-'+hashlib.sha256(json.dumps(record['opponent_events'],sort_keys=True).encode()).hexdigest()
    signature=hashlib.sha256(raw+VERSION.encode()+recipe.encode()).hexdigest()
    root=data_root()/'recognition-corrections'
    if not deferred:root.mkdir(parents=True,exist_ok=True)
    target=root/(correction_key(raw,destination)+'.json')
    candidates=[target,root/(hashlib.sha256(raw).hexdigest()+'.json'),destination/'statistics-corrected.json']
    for candidate in candidates:
        if not candidate.is_file():continue
        try:
            saved=json.loads(candidate.read_text(encoding='utf-8'))
            if saved.get('repair_signature')==signature and not record.get('force') and not any(needs_fields(saved['segments'][index],requested) for index in selected):
                if deferred:return PreparedRepair(destination,hashlib.sha256(raw).hexdigest(),target,saved,tuple(selected))
                if candidate!=target:write_json(target,saved)
                return saved
            saved_valid=saved.get('repair_signature')==hashlib.sha256(raw+saved.get('version','').encode()+saved.get('counter_recipe','').encode()).hexdigest()
            if saved_valid and not native_exports and saved.get('verification_mode')=='native-existing' and saved.get('version')==VERSION and saved.get('base_counter_recipe')==base_recipe:
                return PreparedRepair(destination,hashlib.sha256(raw).hexdigest(),target,saved,tuple(selected)) if deferred else saved
            if saved_valid and isinstance(saved.get('segments'),list):
                prior={(segment['start'],segment['end']):segment for segment in saved['segments']}
                for segment in prior.values():
                    if segment.get('native_repaired_fields'):segment.setdefault('counter_repair_recipe',saved.get('base_counter_recipe'))
                report['segments']=[copy.deepcopy(prior.get((segment['start'],segment['end']),segment)) for segment in report['segments']]
                break
        except (OSError,ValueError,TypeError,KeyError,AttributeError):pass
    profile=json.loads((BASE/'profile-ultrawide.json').read_text(encoding='utf-8'))
    source_available=Path(cache['source']['path']).is_file()
    if not source_available and not native_exports:return
    segments=[report['segments'][index] for index in selected]
    if not counters:endpoints=[copy.deepcopy(segment['endpoint']) for segment in segments]
    elif native_exports and (not source_available or not cache['rows']):
        endpoints=[exported_endpoint(clips,segment,cache.get('profile') or profile) or counter_endpoints(cache,record.get('sample_directory',destination),[segment],profile)[0] for segment in segments]
    else:endpoints=counter_endpoints(cache,record.get('sample_directory',destination),segments,profile)
    changed=0
    for index,segment,fresh in zip(selected,segments,endpoints):
        old=segment['endpoint']
        counter_keys={key for key in ['kills','assists','damage']
                      if counters and (verify_existing or record.get('force') or segment['counts'].get(key) is None
                          or segment['partial'].get(key,False) or key in segment.get('counter_verification_pending',[]))}
        verified=native_verified_fields(fresh);new_verified=set(verified)
        # 新一次读取不清晰时，保留同一媒体中已有的原生证据，不能回退成原始错误数值。
        from outcome_reader import SELF_VIEW_VERSION
        same_media=old.get('native_view_version')==SELF_VIEW_VERSION and old.get('native_counter_scope')==fresh.get('native_counter_scope') and old.get('exported_video_identity')==fresh.get('exported_video_identity')
        previous_verified=set(segment.get('native_repaired_fields',[]))
        previous_recipes=segment.get('native_field_recipes',{})
        same_recipe={key for key in previous_verified if previous_recipes.get(key,segment.get('counter_repair_recipe'))==base_recipe}
        reusable=same_recipe|({key for key in previous_verified if key not in counter_keys} if counters else previous_verified)
        retained=set(native_verified_fields(old))&reusable-new_verified if same_media and not record.get('force') else set()
        for key in retained:
            for group,frames in [('baseline','baseline_frames'),('last_hud','end_frames')]:
                fresh[group][key]=old[group][key]
                fresh.setdefault(frames,[]).extend({**{name:row[name] for name in ['frame','time','native_time','native_verified'] if name in row},key:row[key]} for row in old.get(frames,[]) if row.get('native_verified') is True and row.get(key)==old[group][key])
            if key in old.get('unconfirmed_latest',{}):fresh.setdefault('unconfirmed_latest',{}).setdefault(key,old['unconfirmed_latest'][key])
        verified=sorted(set(verified)|retained)
        # 原生读取的空值也属于本次证据；旧截图或观战数字不能补入新首尾。
        for group in ['baseline','last_hud'] if counters and not native_exports else []:
            for key,value in old[group].items():
                if value is not None and (not verify_existing or key not in verified):fresh[group][key]=value
        if recheck_names and source_available and not record.get('files'):
            selected_keys={(event['kind'],round(event['time'],6)) for event in record['opponent_events']} if record.get('opponent_events') is not None else None
            segment['events']=recheck_event_names(Path(cache['source']['path']),segment['events'],cache.get('profile'),record.get('force',False),on_activity,selected_keys)
        elif recheck_names:
            view=exported_view(clips,segment,cache.get('profile') or profile)
            if view is not None:
                _,identity,origin,_,name_profile=view
            else:identity=fresh.get('exported_video_identity');origin=fresh.get('native_video_origin',0);name_profile=fresh.get('native_profile')
            local=[]
            for event in segment['events']:
                event=dict(event)
                for key in ['time','last_seen']:
                    if key in event:event[key]+=origin-segment['start']
                local.append(event)
            selected_keys={(event['kind'],round(event['time']+origin-segment['start'],6)) for event in record['opponent_events']} if record.get('opponent_events') is not None else None
            if identity:local=recheck_event_names(Path(identity['path']),local,name_profile,record.get('force',False),on_activity,selected_keys)
            for original_event,event in zip(segment['events'],local):
                for key in ['time','last_seen']:
                    if key in original_event:event[key]=original_event[key]
                if identity:event['native_name_source']=identity
            segment['events']=local
        if recheck_weapons:
            from event_weapon_reader import recheck_event_weapons
            view=exported_view(clips,segment,cache.get('profile') or profile)
            if view is None:raise ValueError('战果相关武器缺少可核对的成片')
            weapon_source,identity,origin,_,weapon_profile=view
            local=copy.deepcopy(segment['events'])
            for event in local:
                for key in ['time','last_seen']:
                    if key in event:event[key]+=origin-segment['start']
                if event.get('weapon_context'):
                    saved=event['weapon_context'].get('event',{})
                    event['weapon_context']['event']={key:saved.get(key) for key in ['kind','action','time']}
                    if isinstance(saved.get('source_time'),(int,float)):event['weapon_context']['event']['time']=saved['source_time']
                    elif isinstance(saved.get('time'),(int,float)):event['weapon_context']['event']['time']+=origin-segment['start']
            fresh_events=recheck_event_weapons(weapon_source,local,weapon_profile,force=record.get('force',False),on_activity=on_activity)
            for original_event,event in zip(segment['events'],fresh_events):
                local_time=event.get('time')
                for key in ['time','last_seen']:
                    if key in original_event:event[key]=original_event[key]
                if event.get('weapon_context'):
                    event['weapon_context']['event'].update(time=event['time'],source_time=local_time)
            segment['events']=fresh_events
        settlement=report.get('last_team_settlement') if index==len(report['segments'])-1 and fresh.get('native_counter_scope')!='exported_visible_delta' else None
        result=reconciled_counts(fresh,segment['events'],segment['coverage'],settlement)
        if fresh.get('native_counter_scope')=='exported_visible_delta':
            for key in ['kills','assists','damage']:
                if key not in verified:result['partial'][key]=True
        for key in ['kills','assists','damage'] if counters else []:
            if key not in counter_keys:continue
            # 显式重读或算法变更后，未知也是新证据；不能把旧算法的错误值再灌回来。
            if native_exports and key not in verified and (record.get('force') or key in previous_verified-same_recipe):
                changed+=int(segment['counts'].get(key)!=result['counts'][key] or segment['partial'].get(key) is not True)
                segment['counts'][key]=result['counts'][key];segment['partial'][key]=True
                segment['native_repaired_fields']=[field for field in segment.get('native_repaired_fields',[]) if field!=key]
                segment.get('native_field_recipes',{}).pop(key,None)
                continue
            verified_delta=key in verified and result['counts'][key]==fresh['last_hud'][key]-fresh['baseline'][key]
            allowed_native=verify_existing and verified_delta
            improved_lower=verified_delta and segment['partial'].get(key,False) and result['counts'][key]>(segment['counts'].get(key) or 0)
            if result['counts'][key] is not None and (allowed_native or improved_lower or segment['counts'].get(key) is None or segment['partial'].get(key,False) and not result['partial'][key]):
                if segment['counts'].get(key)!=result['counts'][key] or segment['partial'].get(key)!=result['partial'][key]:changed+=1
                segment['counts'][key]=result['counts'][key];segment['partial'][key]=result['partial'][key]
                if verified_delta:segment['native_repaired_fields']=sorted(set(segment.get('native_repaired_fields',[]))|{key})
        if counters:
            from combat_statistics import confirmed_assist_eliminations
            own=[event for event in segment['events'] if event.get('confirmed') is True and event.get('ownership')=='self']
            center={'kills':sum(event['kind']=='elimination' for event in own),
                    'assists':len(confirmed_assist_eliminations(segment['events'])),
                    'knockdowns':sum(event['kind']=='knock' for event in own)}
            for key,value in center.items():
                previous=segment['counts'].get(key)
                center_only=key=='knockdowns' or old.get('baseline',{}).get(key) is None or old.get('last_hud',{}).get(key) is None
                if (key in counter_keys or key=='knockdowns') and segment['partial'].get(key,True) and center_only and key not in verified:
                    repaired=value or None
                    changed+=int(previous!=repaired)
                    segment['counts'][key]=repaired;segment['partial'][key]=True
                    segment['center_recomputed_fields']=sorted(set(segment.get('center_recomputed_fields',[]))|{key})
                    continue
                if (key in counter_keys or key=='knockdowns') and value>0 and (previous is None or segment['partial'].get(key,False) and value>previous):
                    segment['counts'][key]=value;segment['partial'][key]=True;changed+=1
                    segment['center_repaired_fields']=sorted(set(segment.get('center_repaired_fields',[]))|{key})
        segment['endpoint']=fresh
        if counters:
            segment['notes']=result['notes']
            if fresh.get('native_counter_scope')=='exported_visible_delta':segment['notes'].append('按现有成片首尾原生 HUD 可见增量复核；原片或采样缓存不可用')
        segment['repair_applied']=True;segment['repair_fields']=sorted(set(segment.get('repair_fields',[]))|requested)
        if counters:
            recipes=segment.setdefault('native_field_recipes',{})
            for key in retained:recipes.setdefault(key,segment.get('counter_repair_recipe'))
            for key in new_verified&counter_keys:recipes[key]=base_recipe
            segment['counter_repair_recipe']=base_recipe
            segment['counter_verification_pending']=[key for key in ['kills','assists','damage'] if
                key in counter_keys and (key not in new_verified or result['partial'][key]) or
                key not in counter_keys and key in segment.get('counter_verification_pending',[])]
        if recheck_names:segment['name_parser_version']=PARSER_VERSION
        if recheck_names and any(event.get('native_event_version')==EVENT_VERSION for event in segment['events']):
            segment['event_completion_version']=EVENT_VERSION
            segment['counts']['knockdowns']=result['counts']['knockdowns'];segment['partial']['knockdowns']=True
            segment['event_completion_basis']='confirmed_native_candidates_only'
    report.update(repair_signature=signature,counter_recipe=recipe,base_counter_recipe=base_recipe,version=VERSION,repair_fields=changed,repair_schema=2,verification_mode='native-existing' if any(segment.get('native_repaired_fields') for segment in report['segments']) else 'missing',original_statistics_sha256=hashlib.sha256(raw).hexdigest())
    report['correction_context']=str(destination.resolve()).replace('\\','/').lower()
    if recheck_names:report['parser_version']=PARSER_VERSION
    if deferred:return PreparedRepair(destination,hashlib.sha256(raw).hexdigest(),target,report,tuple(selected),computed_fields=tuple(sorted(requested)))
    write_json(target,report)
    return report

def main(request):
    os.environ['APEX_OCR_BACKEND']='cpu';os.environ['APEX_GPU_LOAD']='low';os.environ['APEX_OCR_POOL']='1'
    records=json.loads(Path(request).read_text(encoding='utf-8'));done=0
    for record in records:
        try:repair(record);done+=1
        except (OSError,ValueError,KeyError):pass
    print(json.dumps({'processed':done}),flush=True)

if __name__=='__main__':main(sys.argv[1])
