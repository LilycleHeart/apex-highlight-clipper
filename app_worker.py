"""桌面程序的本地工作进程；JSON 行传递状态，直接调用已验证的剪辑内核。"""
from contextlib import redirect_stdout
from datetime import datetime,timezone,timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import traceback
import uuid
import threading

if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr,'reconfigure'): sys.stderr.reconfigure(encoding='utf-8')
_STAGE_TIMINGS={}
_ON_STAGE=None
_EMIT_LOCK=threading.RLock()

def emit(kind,**values):
    with _EMIT_LOCK: print(json.dumps({'type':kind,**values},ensure_ascii=False),file=sys.__stdout__,flush=True)

class ProgressLog(io.TextIOBase):
    def __init__(self,stage,start,end):
        self.stage,self.start,self.end=stage,start,end
        self.buffers={}
        self.lock=threading.RLock(); self.decode_ratio=0.; self.ocr_ratio=0.
    def write(self,text):
        with self.lock: return self._write(text)
    def _write(self,text):
        thread=threading.get_ident()
        self.buffers[thread]=self.buffers.get(thread,'')+text
        while '\n' in self.buffers[thread]:
            line,self.buffers[thread]=self.buffers[thread].split('\n',1)
            if not line.strip(): continue
            percent=self.start
            if self.stage=='sample':
                match=re.search(r'画面采样: ([\d.]+)%',line)
                if match: percent=self.start+(self.end-self.start)*float(match[1])/100
            elif self.stage=='numeric':
                match=re.search(r'OCR: ([\d.]+)s / ([\d.]+)s',line)
                if match and float(match[2]): percent=self.start+(self.end-self.start)*float(match[1])/float(match[2])
            elif self.stage=='pipeline':
                sampling=re.search(r'画面采样: ([\d.]+)%',line)
                numeric=re.search(r'OCR: ([\d.]+)s / ([\d.]+)s',line)
                if sampling: self.decode_ratio=min(1,float(sampling[1])/100)
                if numeric and float(numeric[2]): self.ocr_ratio=min(1,float(numeric[1])/float(numeric[2]))
                percent=self.start+(self.end-self.start)*(self.decode_ratio+self.ocr_ratio)/2
            elif self.stage=='smart':
                mark=re.search(r'SMART_PROGRESS: ([\d.]+)',line)
                percent=float(mark[1]) if mark else None
            emit('log',message=line,**({'progress':round(percent)} if percent is not None else {}))
        return len(text)
    def flush(self): pass

def stage(name,label,start,end,action):
    import time
    from app_cancel import check_cancel
    check_cancel()
    if _ON_STAGE: _ON_STAGE(name)
    from ui_observer import set_stage
    set_stage(name)
    emit('stage',stage=name,message=label,progress=start)
    started=time.perf_counter()
    with redirect_stdout(ProgressLog(name,start,end)):
        result=action()
    elapsed=time.perf_counter()-started
    _STAGE_TIMINGS[name]=round(_STAGE_TIMINGS.get(name,0)+elapsed,3)
    check_cancel()
    emit('progress',progress=end,elapsed_seconds=round(elapsed,3))
    return result

def _run_task(request_path):
    global _ON_STAGE
    from app_task import open_task,save_task,task_lock,outputs_intact,load,planner_for_item,data_root,task_cache_root,recorded_cache
    from app_options import recycle_source
    from apex_clipper import (BASE,VIDEO_EXTENSIONS,fingerprint,probe,sample_video,read_hud,
        same_hud_profile,enrich_lifecycle,enrich_weapon_labels,tool,detect_events,label_event_weapons,
        downed_intervals,segments_from_events,classify_combat_candidates,export_lossless,write_json,align_segments,keyframes)
    from outcome_reader import enrich_outcomes,cap_segment_ends,preserve_team_continuation
    incoming=load(request_path)
    task_path,task,request,options=open_task(incoming)
    gap,pre,post,fps=(options[k] for k in ['gap','pre','post','fps'])
    os.environ['APEX_OCR_BACKEND']=request['backend']; os.environ['APEX_GPU_LOAD']=options['gpu_load']
    # 硬解只跟随 CUDA 后端。2560x1080/120fps 实测：d3d11 硬解 547 fps 但只用 0.4 核 CPU，
    # 同机软解 1151 fps；软解与硬解 120 帧识别逐字段一致。DirectML 后端因此改走软解，
    # 让 CPU 之外的空闲算力留给推理。4K/5K 素材两者接近打平，需要时可手动设 APEX_HARDWARE_DECODER=d3d11。
    os.environ['APEX_HARDWARE_DECODER']={'cuda':'cuda'}.get(request['backend'],'')
    os.environ['APEX_OCR_POOL']='1'
    from performance_options import apply_resources
    apply_resources({**options,'backend':request['backend']})
    run_root=Path(task['directory']); cache_root=task_cache_root(task); profile=task['profile']; skipped=0
    from gpu_load import get_gpu_policy
    with task_lock(run_root):
        from app_cancel import check_cancel
        if incoming.get('stop_file'):
            stop_marker=Path(incoming['stop_file']).resolve()
            if not any(stop_marker.is_relative_to(root.resolve()) for root in [data_root()/'validation/app-requests',BASE/'validation/app-requests']):raise ValueError('停止请求不属于软件请求目录')
            if stop_marker.suffix!='.stop': raise ValueError('停止请求路径不正确')
        else:
            stop_marker=run_root/'stop.request'; stop_marker.unlink(missing_ok=True)
        os.environ['APEX_TASK_STOP_FILE']=str(stop_marker)
        save_task(task_path,task)
        emit('run',directory=str(run_root),task_path=str(task_path),message=('继续任务 · ' if incoming.get('resume_task') else '新任务 · ')+('GPU '+get_gpu_policy()['label'] if request['backend'] in {'dml','cuda'} else 'CPU'),
            scan_mode=options['scan_mode'],indexed_experimental=options['scan_mode']=='indexed',
            result_filter_version=task.get('result_filter_version'),
            result_filter_rule='击倒/助攻/消灭任一' if task.get('result_filter_version') else '沿用旧任务交战规则',
            sampling_warning='沿用旧任务低于 1 帧/秒的参数，可能漏掉交战候选；建议新建至少 1 帧/秒的任务' if fps<1 else None,
            legacy_rule=None if task.get('result_filter_version') else '此任务沿用旧规则；要应用本人击倒/助攻/消灭筛选，请新建任务')
        check_cancel()
        if request['backend'] in {'dml','cuda'}:
            import onnxruntime
            provider={'dml':'DmlExecutionProvider','cuda':'CUDAExecutionProvider'}[request['backend']]
            if provider not in onnxruntime.get_available_providers(): raise RuntimeError(f'{provider} 环境不可用，可改用 CPU 继续任务')
        for index,item in enumerate(task['items']):
            check_cancel()
            _STAGE_TIMINGS.clear(); source=Path(item['source']); destination=Path(item['destination']); destination.resolve().relative_to(run_root.resolve())
            video_directory=Path(item.get('video_directory',destination))
            cache_root=task_cache_root(task)
            from ui_observer import configure,phase,preview
            configure(emit,source)
            was_pending=item['status']=='pending'
            job=None; emit('file',index=index+1,total=len(task['items']),source=str(source),message=source.name,progress=0)
            def update_stage(name):
                item.update(status='running',stage=name); save_task(task_path,task)
            _ON_STAGE=update_stage
            try:
                previous=item.get('record')
                from hud_layout import needs_layout_retry
                if outputs_intact(previous) and item['status'] in ['complete','cleanup'] and not (source.is_file() and needs_layout_retry(previous,item.get('hud_profile'))):
                    if item['status']=='cleanup' or (options['delete_source'] and source.is_file() and previous.get('source_cleanup',{}).get('status')!='recycled'):
                        if not source.exists():
                            previous['source_cleanup']={'status':'source_absent_after_cleanup','reason':'成片已完成；原录像在回收阶段后已不存在'}
                        else:
                            verification=None
                            analysis=load(destination/'analysis.json')
                            previous['source_cleanup']=recycle_source(source,item['source_identity'],previous['outputs'],verification,
                                analysis['review_candidates'],analysis['segments'])
                        item.update(status='complete',stage='complete'); save_task(task_path,task)
                    skipped+=1
                    emit('result',**previous,message='续接：跳过已完成 '+source.name,skipped=True,progress=100)
                    continue
                if not source.is_file(): raise ValueError('源录像不存在；如成片缺失且原片已回收，请先恢复原片再继续')
                if source.suffix.lower() not in VIDEO_EXTENSIONS: raise ValueError('录像格式不支持')
                identity=fingerprint(source)
                if item['source_identity'] is not None and identity!=item['source_identity']: raise ValueError('源录像已变化，不能使用旧任务断点，请新建任务')
                item['source_identity']=identity; save_task(task_path,task)
                meta,video=stage('probe','检查录像',0,5,lambda:probe(source))
                from hud_layout import detect_video,DETECTOR_VERSION
                frozen=item.get('hud_profile')
                if frozen and frozen.get('reference_size')==[video['width'],video['height']] and frozen.get('layout_status')!='unconfirmed' and item.get('hud_detector')==DETECTOR_VERSION:profile=frozen
                else:
                    # 旧版只按高度缩放，16:10 等比例可能以错误几何「确认」；续接时按当前候选重测。
                    profile=stage('probe','自动适配分辨率与HUD拉伸比例',2,5,
                        lambda:detect_video(source,video,float(meta['format']['duration']),task['profile']))
                    item['hud_profile']=profile;item['hud_detector']=DETECTOR_VERSION;save_task(task_path,task)
                emit('metadata',source=str(source),width=video['width'],height=video['height'],hud_layout=profile['layout'],hud_layout_status=profile.get('layout_status'))
                config={'source':identity,'profile':profile,'fps':fps}
                planner_version=item.get('smart_cache_version',task.get('smart_cache_version','smart-v2'))
                if options['scan_mode']=='indexed' and planner_version not in ['indexed-v1','indexed-v2']:
                    raise ValueError('索引任务版本不支持，请保留原任务并新建批次')
                if options['scan_mode'] in ['smart','indexed']: config.update(scan_mode=planner_version,gap=gap,pre=pre,post=post)
                if planner_version=='indexed-v2': config['fine_pipeline']='continuous-v1'
                old_digest=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()[:16]
                digest=hashlib.sha256(json.dumps({**config,'cache_version':'resume-v1'},sort_keys=True).encode()).hexdigest()[:16]
                registered=recorded_cache(task,item,config)
                if registered:cache_root=registered.parent
                job=registered or cache_root/digest
                if options['scan_mode']=='smart':
                    selected=planner_for_item(task,item,was_pending,job.exists() or (cache_root/old_digest).exists())
                    if selected!=planner_version:
                        planner_version=selected;item['smart_cache_version']=selected;save_task(task_path,task)
                        config['scan_mode']=selected
                        old_digest=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()[:16]
                        digest=hashlib.sha256(json.dumps({**config,'cache_version':'resume-v1'},sort_keys=True).encode()).hexdigest()[:16]
                        job=cache_root/digest
                # 清理过图片的历史缓存保留JSON供成片展示；识别改用新代次，不能误用缺帧断点。
                while (job/'.images-pruned.json').is_file():
                    generation=load(job/'.images-pruned.json')['generation']
                    job=cache_root/hashlib.sha256((job.name+generation).encode()).hexdigest()[:16]
                job.mkdir(parents=True,exist_ok=True)
                item['analysis_cache']=str(job); save_task(task_path,task)
                with task_lock(job):
                    if registered and job==registered and recorded_cache(task,item,config)!=registered:raise ValueError('旧任务缓存已变化，停止续接以保护断点')
                    write_json(job/'.cache-use.json',{'source':str(source),'task':str(task_path)})
                    reference=job/'sample-reference.json'; samples=job/'samples'; hud_path=job/'hud.json'
                    legacy=cache_root/old_digest
                    if not reference.exists() and (legacy/'hud.json').exists() and (legacy/'sample-reference.json').exists():
                        seed=load(legacy/'hud.json'); old_samples=Path(load(legacy/'sample-reference.json')['samples'])
                        if seed.get('complete') and seed.get('source')==identity and same_hud_profile(seed['profile'],profile) and (old_samples/'complete.json').exists():
                            write_json(hud_path,seed); write_json(reference,{'samples':str(old_samples)})
                    if reference.exists(): samples=Path(load(reference)['samples'])
                    saved=None
                    if hud_path.exists():
                        candidate=load(hud_path)
                        if candidate.get('complete') and candidate.get('source')==identity and candidate.get('fps')==fps and same_hud_profile(candidate['profile'],profile) and (options['scan_mode']=='complete' or candidate.get('smart_plan',{}).get('finished')): saved=candidate
                    if saved is None:
                        if options['scan_mode'] in ['smart','indexed']:
                            from smart_scan import smart_read
                            _,samples=stage('smart','索引实验：内存粗定位和局部细查' if options['scan_mode']=='indexed' else '智能识别：粗查、二分和局部细查',5,65,
                                lambda:smart_read(source,job,samples,profile,fps,hud_path,gap,pre,post,cuda=request['backend'] in {'dml','cuda'},
                                    result_first=planner_version.startswith('focused-v6'),indexed=options['scan_mode']=='indexed',
                                    continuous=planner_version=='indexed-v2'))
                        elif options['pipeline']:
                            from sample_pipeline import sample_and_read
                            stage('pipeline','采样与数字识别并行（支持续接）',5,65,
                                lambda:sample_and_read(source,samples,profile,fps,hud_path,cuda=request['backend'] in {'dml','cuda'}))
                        else:
                            stage('sample','提取交战识别画面（支持续接）',5,30,
                                lambda:sample_video(source,samples,fps,cuda=request['backend'] in {'dml','cuda'},resume=True))
                            stage('numeric','识别弹药、伤害和击杀（支持续接）',30,65,
                                lambda:read_hud(samples,profile,fps,hud_path,resume=True,source_identity=identity))
                        saved=load(hud_path)
                    else:
                        if options['scan_mode']=='complete': stage('sample','复查已完成采样',5,30,lambda:sample_video(source,samples,fps,cuda=request['backend'] in {'dml','cuda'},resume=True))
                        phase('cache','复用本录像已完成的识别缓存',65,cached=True)
                        if saved['rows']:
                            row=saved['rows'][-1]; preview(samples/row['frame'],row['time'],force=True)
                    write_json(reference,{'samples':str(samples)})
                    for row in saved['rows']:
                        for field in ['weapon_labels','current_weapon','current_weapon_confidence','active_weapon_slot']:row.pop(field,None)
                    result_first=bool(task.get('result_filter_version') and (planner_version.startswith('focused-v6') or planner_version in ['indexed-v1','indexed-v2']))
                    saved=stage('lifecycle','识别倒地状态',65,70 if result_first else 78,lambda:enrich_lifecycle(saved,samples,profile)); write_json(hud_path,saved)
                    saved=stage('outcomes','确认全灭及队友交战尾部（支持续接）',70 if result_first else 82,74 if result_first else 86,lambda:enrich_outcomes(saved,samples,checkpoint=hud_path)); write_json(hud_path,saved)
                    rows=saved['rows']; duration=float(meta['format']['duration'])
                    events=detect_events(rows)
                    from hud_layout import ensure_activity_is_readable
                    ensure_activity_is_readable(profile,events,saved.get('smart_plan',{}))
                    lifecycle=downed_intervals(rows,duration,gap,post)
                    candidates=segments_from_events(events,duration,gap,pre,post,lifecycle)
                    candidates=cap_segment_ends(candidates,saved['outcome_events'])
                    candidates=preserve_team_continuation(candidates,rows,saved['outcome_events'],duration)
                    segments,review=classify_combat_candidates(events,candidates)
                    rejected=[]; result_filter=None
                    if task.get('result_filter_version'):
                        from combat_outcome_reader import inspect_combat_outcomes,filter_combat_outcomes
                        result_candidates=sorted(segments+review,key=lambda c:c['start'])
                        result_filter=stage('combat_outcomes','确认本人击倒、助攻或消灭提示',74 if result_first else 86,80 if result_first else 90,
                            lambda:inspect_combat_outcomes(saved,samples,result_candidates,checkpoint=job/'combat-outcomes.json'))
                        segments,rejected,review=filter_combat_outcomes(result_candidates,result_filter)
                    destination.mkdir(exist_ok=True)
                    analysis={'source':identity,'duration':duration,'parameters':{'gap':gap,'pre':pre,'post':post,'fps':fps},'events':events,
                        'segments':segments,'review_candidates':review,'lifecycle_intervals':lifecycle,'outcome_events':saved['outcome_events'],'combat_filter_version':2}
                    if result_filter:
                        analysis.update(own_result_filter=result_filter,rejected_candidates=rejected,result_filter_version=result_filter['version'])
                        write_json(destination/'rejected-candidates.json',rejected)
                    smart_plan=saved.get('smart_plan',{})
                    if smart_plan.get('counter_review_reason'):
                        analysis['counter_review_reason']=smart_plan['counter_review_reason']
                        analysis['counter_audit_after_completion']=smart_plan.get('audit_after_completion')
                    write_json(destination/'analysis.json',analysis); write_json(destination/'review-candidates.json',review)
                    outputs=[]; verified=False; verification=None; quality_report=None; quality_rejected=[]
                    if segments:
                        from combat_statistics import collect_statistics
                        aligned=align_segments(segments,keyframes(source),duration)
                        frozen_statistics=None
                        if (destination/'export-checkpoint.json').exists() and (destination/'statistics.json').exists():
                            candidate=load(destination/'statistics.json')
                            from combat_outcome_reader import PARSER_VERSION
                            if candidate.get('parser_version')==PARSER_VERSION and candidate.get('source')==saved['source'] and [(s['start'],s['end']) for s in candidate.get('segments',[])]==[(s['start'],s['end']) for s in aligned]:frozen_statistics=candidate
                        statistics=stage('statistics','核对整段本人击杀、助攻、击倒与末队结算',90,90,
                            lambda:frozen_statistics or collect_statistics(saved,samples,aligned,profile,job/'statistics-report.json'))
                        write_json(destination/'statistics.json',statistics)
                        from clip_quality_filter import apply_thresholds
                        export_segments,export_statistics,quality_report,quality_rejected,quality_review=apply_thresholds(aligned,statistics,options)
                        review.extend(quality_review)
                        analysis['quality_filter']=quality_report
                        write_json(destination/'quality-filter.json',quality_report)
                        write_json(destination/'analysis.json',analysis);write_json(destination/'review-candidates.json',review)
                        if options['filter_enabled']:emit('log',message=f"战绩过滤：保留 {len(export_segments)} 段，未达标 {len(quality_rejected)} 段，待复核 {len(quality_review)} 段",progress=90)
                        if export_segments:
                            saved=stage('weapons','确认保留交战的枪械名称',90,90,
                                lambda:enrich_weapon_labels(saved,samples,profile,tool('ffmpeg'),checkpoint=hud_path,segments=export_segments))
                            label_event_weapons(events,saved['rows']);write_json(hud_path,saved)
                            analysis['events']=events;write_json(destination/'analysis.json',analysis)
                            export_input=export_segments if options['filter_enabled'] and any(options[k]>0 for k in ['min_damage','min_kills','min_assists','min_duration']) else segments
                            outputs=stage('export','无损导出独立交战视频（支持续接）',90 if result_filter else 86,95,lambda:export_lossless(source,export_input,video_directory,events,resume=True,statistics=export_statistics,metadata_dir=destination,name_suffix=item.get('export_suffix','')))
                            manifest=load(destination/'export.json')
                            for clip in manifest['clips']:
                                bound=clip['segment'];left=bound.get('requested_start',bound['start']);right=bound.get('requested_end',bound['end'])
                                related=[s for s in segments if s['start']<right and s['end']>left]
                                unique={}
                                for event in [e for s in related for e in s.get('own_result_filter',{}).get('events',[])]:
                                    if event.get('ownership')=='self' and bound['start']<=event['time']<bound['end']:
                                        unique[(event['kind'],event['time'],event.get('text',''))]=event
                                stats=next(s for s in export_statistics['segments'] if abs(s['start']-bound['start'])<.001 and abs(s['end']-bound['end'])<.001)
                                evidence=[e for e in stats['events'] if e['confirmed']];ranks=[s.get('rank') for s in related]
                                rank=ranks[0] if ranks and all(ranks) and all((r['tier'],r['division'])==(ranks[0]['tier'],ranks[0]['division']) for r in ranks) else None
                                round_index=sum(event['time']<=bound['start'] for event in saved.get('outcome_events',[]))
                                match_key=hashlib.sha256((json.dumps(identity,sort_keys=True)+':'+str(round_index)).encode()).hexdigest()[:16]
                                clip['recognition']={'scope':'self','rank':rank,'match_key':match_key,'outcome_evidence':evidence,
                                    'assists_minimum':sum(e['kind']=='assist' for e in evidence) or None,
                                    'knockdowns_minimum':sum(e['kind']=='knock' for e in evidence) or None,
                                    'outcome_counts_complete':not any(stats['partial'].values()),
                                    'statistics':stats}
                            write_json(destination/'export.json',manifest)
                            if options['hud_info_enabled'] and options['hud_info_fields']:
                                from hud_enrichment import enrich_manifest_isolated
                                from app_cancel import TaskStopped
                                try:
                                    stage('hud_info','导出完成，补充所选HUD信息',99,99,
                                        lambda:enrich_manifest_isolated(destination,fields=options['hud_info_fields'],
                                            on_log=lambda message:emit('log',message=message,progress=99)))
                                except TaskStopped:raise
                                except Exception as error:
                                    emit('log',message='片段已导出，HUD信息尚未补齐，可稍后继续：'+str(error),progress=99)
                    record={'source':str(source),'status':'complete','outputs':[str(p) for p in outputs],
                        'output_identities':[fingerprint(p) for p in outputs],'review_count':len(review),'directory':str(destination),
                        'verified':verified,'parameters':options,'stage_seconds':dict(_STAGE_TIMINGS),'sample_directory':str(samples),
                        'planner_version':planner_version,'analysis_cache':str(job),'quality_rejected_count':len(quality_rejected),'quality_filter_summary':quality_report['summary'] if quality_report else None,
                        'source_cleanup':{'status':'kept','reason':'未开启输出后删除'}}
                    if analysis.get('counter_review_reason'): record['counter_review_reason']=analysis['counter_review_reason']
                    record.update(result_filter_version=result_filter['version'] if result_filter else None,rejected_count=len(rejected),
                        result_filter_summary={'kept':len(outputs),'rejected':len(rejected),'review':len(review),
                                               'rule':'击倒/助攻/消灭任一' if result_filter else '沿用旧任务交战规则'})
                    item['record']=record
                    if options['delete_source']:
                        record['source_cleanup']={'status':'pending','reason':'等待移入回收站'}
                        item.update(status='cleanup',stage='cleanup'); save_task(task_path,task)
                        check_cancel()
                        record['source_cleanup']=recycle_source(source,identity,outputs,verification,review,segments)
                        emit('log',message=source.name+'：'+record['source_cleanup']['reason'],progress=99)
                    item.update(status='complete',stage='complete'); save_task(task_path,task)
                    emit('result',**record,message=f'完成：{len(outputs)} 段交战，排除 {len(rejected)} 段，{len(review)} 个待复核候选',progress=100)
            except Exception as error:
                item.update(status='error',stage='error',record={'source':str(source),'status':'error','error':str(error) or type(error).__name__,'outputs':[]})
                emit('error',source=str(source),message=source.name+'：'+item['record']['error'],progress=100); save_task(task_path,task)
                (job/'error.log' if job else run_root/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
        _ON_STAGE=None; task['finished']=all(i['status']=='complete' for i in task['items']); save_task(task_path,task)
        records=[i['record'] for i in task['items']]; failed=sum(r['status']=='error' for r in records)
        emit('done',directory=str(run_root),failures=failed,clips=sum(len(r['outputs']) for r in records),
            recycled=sum(r.get('source_cleanup',{}).get('status')=='recycled' for r in records),skipped=skipped,
            review_count=sum(r.get('review_count',0) for r in records),rejected_count=sum(r.get('rejected_count',0) for r in records),
            result_filter_version=task.get('result_filter_version'),
            result_filter_summary={'kept':sum(len(r['outputs']) for r in records),'rejected':sum(r.get('rejected_count',0) for r in records),
                'review':sum(r.get('review_count',0) for r in records),'rule':'击倒/助攻/消灭任一' if task.get('result_filter_version') else '沿用旧任务交战规则'},
            message='任务结束',progress=100)
        return 1 if failed else 0

def main(request_path):
    from app_cancel import TaskStopped
    try: return _run_task(request_path)
    except TaskStopped:
        emit('stopped',message='断点已保存，可以继续上次任务'); return 75

if __name__=='__main__':
    import faulthandler
    faulthandler.enable()
    try: raise SystemExit(main(sys.argv[1]))
    except Exception as error:
        emit('fatal',message=str(error)); traceback.print_exc(file=sys.stderr); raise SystemExit(1)
