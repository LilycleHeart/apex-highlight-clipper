"""按采样块和独立成片提交断点；未完成块/片段重新生成，原录像不动。"""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import uuid

def load(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def file_digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def sample_with_resume(source,out,fps,cuda=False,chunk_seconds=30,on_checkpoint=None,abort_event=None,frame_ranges=None,cpu_threads=None):
    from apex_clipper import probe,fingerprint,write_json,tool
    from app_cancel import check_cancel
    out=Path(out).resolve(); out.mkdir(parents=True,exist_ok=True); hud=out/'hud'; hud.mkdir(exist_ok=True)
    meta,video=probe(source); duration=float(meta['format']['duration'])
    info={'source':fingerprint(source),'fps':fps,'width':1280,'duration':duration}
    state_path=out/'sampling-checkpoint.json'; complete=out/'complete.json'
    total=max(1,math.floor(duration*fps+.5)); chunk_frames=max(1,round(chunk_seconds*fps))
    ranges=frame_ranges if frame_ranges is not None else [[1,total]]
    for i,(first,last) in enumerate(ranges):
        if i and first<=ranges[i-1][1]: raise ValueError('局部采样范围重叠或未按时间排序')
    if frame_ranges is not None: info['frame_ranges']=ranges
    planned=[]
    for first,last in ranges:
        if not 1<=first<=last<=total: raise ValueError('局部采样范围不合法')
        for first_frame in range(first,last+1,chunk_frames): planned.append((first_frame,min(chunk_frames,last-first_frame+1)))
    requested=sum(count for _,count in planned)
    state=load(state_path) if state_path.exists() else {'version':1,'info':info,'chunks':[]}
    if state.get('info')!=info: raise ValueError('采样断点与源录像或识别频率不匹配')
    if frame_ranges is None and complete.exists() and not state_path.exists():
        old=load(complete)
        if all(old.get(k)==v for k,v in info.items()) and len(list(out.glob('*.jpg')))==total:
            print('复用已完成的画面采样',flush=True); return
    valid=[]
    for position,block in enumerate(state['chunks']):
        if position>=len(planned) or (block['first'],block['count'])!=planned[position]: break
        next_frame=block['first']
        expected={str(p) for j in range(int(block.get('count',0))) for p in
            [Path(f'{next_frame+j:06d}.jpg'),Path('hud')/f'{next_frame+j:06d}.jpg']}
        if not block.get('count') or next_frame+block['count']-1>total or {entry['path'] for entry in block['files']}!=expected or len(block['files'])!=len(expected): break
        good=True
        for item in block['files']:
            path=out/item['path']
            path.resolve().relative_to(out)
            if not path.is_file() or file_digest(path)!=item['sha256']: good=False; break
        if not good: break
        valid.append(block)
    state['chunks']=valid; write_json(state_path,state)
    if len(valid)==len(planned):
        write_json(complete,info); print('采样断点已全部完成，跳过解码',flush=True)
        if valid:
            from ui_observer import preview
            last=valid[-1]['first']+valid[-1]['count']-1
            preview(out/f'{last:06d}.jpg',(last-.5)/fps)
        if on_checkpoint: on_checkpoint(state)
        return
    completed_count=sum(block['count'] for block in valid)
    if valid: print(f'采样续接：保留 {completed_count} 帧',flush=True)
    if valid and on_checkpoint: on_checkpoint(state)
    # 只写当前未提交块；时间边界对齐采样网格，保持全片 fps 滤镜的取样相位。
    for next_frame,count in planned[len(valid):]:
        check_cancel()
        if abort_event is not None and abort_event.is_set(): raise RuntimeError('识别端已停止，结束采样')
        start=(next_frame-1)/fps
        scratch=out/'chunks'/uuid.uuid4().hex; (scratch/'hud').mkdir(parents=True)
        args=[tool('ffmpeg'),'-hide_banner','-loglevel','warning','-nostdin','-ss',f'{start:.9f}',
              '-t',f'{count/fps+1/fps:.9f}']
        if not cuda and cpu_threads is not None: args+=['-threads',str(cpu_threads),'-filter_complex_threads',str(cpu_threads)]
        if cuda:
            from gpu_load import get_gpu_policy
            policy=get_gpu_policy()
            if policy['decode_rate']: args+=['-readrate',str(policy['decode_rate'])]
            args+=['-hwaccel','cuda','-hwaccel_output_format','cuda']
        width,height=video['width'],video['height']; cx=round(width*.75/2)*2; cy=round(height*5/6/2)*2
        transfer='hwdownload,format=p010le,' if '10' in video.get('pix_fmt','') else 'hwdownload,format=nv12,'
        graph=f"[0:v:0]fps={fps},"+(transfer if cuda else '')+f"split=2[b][h];[b]scale=1280:-2[body];[h]crop={width-cx}:{height-cy}:{cx}:{cy}[hud]"
        jpeg_threads=['-threads:v','1'] if cpu_threads is not None else []
        args+=['-i',str(source),'-filter_complex',graph,'-map','[body]','-frames:v',str(count),'-q:v','2']+jpeg_threads+['-n',str(scratch/'%06d.jpg'),
               '-map','[hud]','-frames:v',str(count),'-q:v','2']+jpeg_threads+['-n',str(scratch/'hud/%06d.jpg')]
        with (scratch/'decode.log').open('w',encoding='utf-8') as log:
            proc=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                last_progress=0.
                while proc.poll() is None:
                    check_cancel()
                    if abort_event is not None and abort_event.is_set(): raise RuntimeError('识别端已停止，结束采样')
                    now=time.monotonic()
                    if now-last_progress>=1:
                        seen=len(list(scratch.glob('*.jpg')))
                        print(f'画面采样: {min(100,(completed_count+seen)/max(1,requested)*100):.1f}% ({completed_count+seen}帧)',flush=True)
                        last_progress=now
                    # 日志仍每秒一次，但短采样块不再被固定一秒sleep拖住。
                    try: proc.wait(timeout=.1)
                    except subprocess.TimeoutExpired: pass
            except BaseException:
                proc.terminate(); proc.wait(); raise
        if proc.returncode: raise RuntimeError((scratch/'decode.log').read_text(encoding='utf-8',errors='replace')[-3000:])
        if len(list(scratch.glob('*.jpg')))!=count or len(list((scratch/'hud').glob('*.jpg')))!=count:
            raise ValueError('采样块帧数不完整，不提交断点')
        files=[]
        for j in range(count):
            for relative in [Path(f'{next_frame+j:06d}.jpg'),Path('hud')/f'{next_frame+j:06d}.jpg']:
                parent=scratch/'hud' if relative.parent.name=='hud' else scratch
                origin=parent/f'{j+1:06d}.jpg'; target=out/relative
                origin.resolve().relative_to(out); target.resolve().relative_to(out)
                encoded=origin.read_bytes()
                if not encoded.endswith(b'\xff\xd9'): raise ValueError('采样 JPEG 未完整写入')
                origin.replace(target)
                files.append({'path':str(relative),'sha256':hashlib.sha256(encoded).hexdigest()})
        state['chunks'].append({'first':next_frame,'count':count,'files':files})
        write_json(state_path,state); completed_count+=count
        from ui_observer import preview
        last=next_frame+count-1
        preview(out/f'{last:06d}.jpg',(last-.5)/fps)
        check_cancel()
        if on_checkpoint: on_checkpoint(state)
    write_json(complete,info)

def export_with_resume(source,segments,output,events=None,on_checkpoint=None):
    from apex_clipper import probe,fingerprint,write_json,tool,run,align_segments,keyframes,segment_summary,informative_filename
    import csv
    from app_cancel import check_cancel
    source=Path(source).resolve(); output=Path(output).resolve(); output.mkdir(parents=True,exist_ok=True)
    meta,_=probe(source); aligned=align_segments(segments,keyframes(source),float(meta['format']['duration']))
    summaries=[segment_summary(events,s) for s in aligned]
    targets=[output/informative_filename(source,i+1,summary) for i,summary in enumerate(summaries)]
    signature=digest({'source':fingerprint(source),'segments':aligned,'targets':[str(p) for p in targets],'summaries':summaries})
    checkpoint=output/'export-checkpoint.json'
    state=load(checkpoint) if checkpoint.exists() else {'signature':signature,'clips':[],'commands':[]}
    if state['signature']!=signature: raise ValueError('导出断点与分析参数不匹配，请新建任务')
    write_json(checkpoint,state); clips=[]; commands=[]
    for i,(segment,target,summary) in enumerate(zip(aligned,targets,summaries)):
        check_cancel()
        target.relative_to(output)
        previous=next((c for c in state['clips'] if c['output']==str(target)),None)
        if previous and target.is_file() and previous.get('output_identity')==fingerprint(target):
            clips.append(previous); print(f'导出续接：跳过已完成第 {i+1} 段',flush=True); continue
        if target.exists():
            preserved=output/'未确认文件'/('未记录-'+uuid.uuid4().hex[:8]+' '+target.name); preserved.parent.mkdir(exist_ok=True)
            target.resolve().relative_to(output); preserved.resolve().relative_to(output); target.replace(preserved)
        partial=output/('.working-'+uuid.uuid4().hex+'.mp4')
        args=[tool('ffmpeg'),'-hide_banner','-loglevel','warning','-nostdin','-n','-ss',f"{segment['start']:.9f}",
              '-i',str(source),'-t',f"{segment['end']-segment['start']:.9f}",'-map','0:v:0','-map','0:a?',
              '-map_metadata','0','-c','copy','-avoid_negative_ts','make_zero','-movflags','+faststart',str(partial)]
        print(f'无损切割 {i+1}/{len(aligned)}: {segment["start"]:.3f}—{segment["end"]:.3f}s',flush=True)
        log=run(args); result_meta,_=probe(partial)
        expected=[(s['codec_type'],s['codec_name']) for s in meta['streams']]
        if expected!=[(s['codec_type'],s['codec_name']) for s in result_meta['streams']]: raise ValueError('导出音视频轨不匹配')
        partial.resolve().relative_to(output); target.resolve().relative_to(output); partial.replace(target)
        clip={'output':str(target),'segment':segment,'summary':summary,'metadata':result_meta,'output_identity':fingerprint(target)}
        result_meta['format']['filename']=str(target)
        clips.append(clip); state['clips']=[c for c in state['clips'] if c['output']!=str(target)]+[clip]
        state['commands'].append({'args':args,'log':log}); write_json(checkpoint,state)
        if on_checkpoint: on_checkpoint(state)
    manifest={'mode':'segments','source':fingerprint(source),'segments':aligned,'outputs':[str(p) for p in targets],
              'commands':state['commands'],'clips':clips}
    write_json(output/'export.json',manifest)
    with (output/'segments.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream)
        for i,s in enumerate(aligned): writer.writerow([s['start'],s['end'],f'交战 {i+1}'])
    return targets
