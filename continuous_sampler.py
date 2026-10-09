"""One FFmpeg process per continuous range, with independent logical commits.

The v1 sampling checkpoint schema and JPEG parameters match resume_media.
Only confirmed-closed, paired body/HUD files are copied into committed storage.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import uuid

from apex_clipper import probe,fingerprint,write_json,tool
from app_cancel import check_cancel


def _check(abort_event):
    check_cancel()
    if abort_event is not None and abort_event.is_set():
        raise RuntimeError('识别端已停止，结束连续采样')


def _block_closed(scratch,last_local,exited_successfully=False):
    """image2 closes frame N before opening N+1 in each output muxer.

    EOI alone is insufficient. Both successor files must have appeared, or the
    entire child process must have exited successfully (closing every handle).
    """
    scratch=Path(scratch)
    if exited_successfully: return True
    successor=f'{last_local+1:06d}.jpg'
    return (scratch/successor).is_file() and (scratch/'hud'/successor).is_file()


def _replace_with_retry(partial,target):
    for attempt in range(6):
        try:
            partial.replace(target); return
        except PermissionError:
            if attempt==5: raise
            time.sleep(.025*(attempt+1))


def _publish_block(scratch,out,run_first,first,count):
    files=[]
    for index in range(first,first+count):
        local=index-run_first+1
        for relative in [Path(f'{index:06d}.jpg'),Path('hud')/f'{index:06d}.jpg']:
            origin=(scratch/'hud' if relative.parent.name=='hud' else scratch)/f'{local:06d}.jpg'
            origin.resolve().relative_to(out.resolve())
            target=out/relative; target.resolve().relative_to(out.resolve())
            content=origin.read_bytes()
            if not content.startswith(b'\xff\xd8') or not content.endswith(b'\xff\xd9'):
                raise ValueError('连续采样 JPEG 不完整，不提交断点')
            # Never rename a file managed by the running decoder. The .part
            # suffix is also invisible to existing *.jpg readers.
            partial=target.with_name('.'+target.name+'.'+uuid.uuid4().hex+'.part')
            with partial.open('xb') as stream:
                stream.write(content)
            _replace_with_retry(partial,target)
            files.append({'path':str(relative),'sha256':hashlib.sha256(content).hexdigest()})
    return {'first':first,'count':count,'files':files}


def _valid_prefix(state,planned,out,total):
    valid=[]
    for position,block in enumerate(state['chunks']):
        if position>=len(planned) or (block.get('first'),block.get('count'))!=planned[position]: break
        first,count=planned[position]
        expected={str(p) for index in range(first,first+count) for p in [Path(f'{index:06d}.jpg'),Path('hud')/f'{index:06d}.jpg']}
        entries=block.get('files',[])
        if first+count-1>total or len(entries)!=len(expected) or {entry.get('path') for entry in entries}!=expected: break
        good=True
        for entry in entries:
            path=out/entry['path']; path.resolve().relative_to(out)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=entry.get('sha256'):
                good=False; break
        if not good: break
        valid.append(block)
    return valid


def _command(source,scratch,video,first,count,fps,cuda,cpu_threads):
    start=(first-1)/fps
    args=[tool('ffmpeg'),'-hide_banner','-loglevel','warning','-nostdin','-ss',f'{start:.9f}',
          '-t',f'{count/fps+1/fps:.9f}']
    if not cuda and cpu_threads is not None:
        args+=['-threads',str(cpu_threads),'-filter_complex_threads',str(cpu_threads)]
    if cuda:
        from gpu_load import get_gpu_policy
        policy=get_gpu_policy()
        if policy['decode_rate']: args+=['-readrate',str(policy['decode_rate'])]
        args+=['-hwaccel','cuda','-hwaccel_output_format','cuda']
    width,height=video['width'],video['height']
    cx=round(width*.75/2)*2; cy=round(height*5/6/2)*2
    transfer='hwdownload,format=p010le,' if '10' in video.get('pix_fmt','') else 'hwdownload,format=nv12,'
    graph=f'[0:v:0]fps={fps},'+(transfer if cuda else '')+f'split=2[b][h];[b]scale=1280:-2[body];[h]crop={width-cx}:{height-cy}:{cx}:{cy}[hud]'
    jpeg_threads=['-threads:v','1'] if cpu_threads is not None else []
    args+=['-i',str(source),'-filter_complex',graph,'-map','[body]','-frames:v',str(count),'-q:v','2']+jpeg_threads+['-n',str(scratch/'%06d.jpg'),
           '-map','[hud]','-frames:v',str(count),'-q:v','2']+jpeg_threads+['-n',str(scratch/'hud/%06d.jpg')]
    return args


def sample_continuous_with_resume(source,out,fps,cuda=False,chunk_seconds=30,on_checkpoint=None,
                                 abort_event=None,frame_ranges=None,cpu_threads=None):
    _check(abort_event)
    if not math.isfinite(fps) or fps<=0 or not math.isfinite(chunk_seconds) or chunk_seconds<=0:
        raise ValueError('采样频率和提交块时长必须为正数')
    out=Path(out).resolve(); out.mkdir(parents=True,exist_ok=True); (out/'hud').mkdir(exist_ok=True)
    meta,video=probe(source); duration=float(meta['format']['duration']); identity=fingerprint(source)
    info={'source':identity,'fps':fps,'width':1280,'duration':duration}
    total=max(1,math.floor(duration*fps+.5)); chunk_frames=max(1,round(chunk_seconds*fps))
    ranges=frame_ranges if frame_ranges is not None else [[1,total]]
    if frame_ranges is not None: info['frame_ranges']=ranges
    planned=[]; groups=[]
    for i,(first,last) in enumerate(ranges):
        if not 1<=first<=last<=total or (i and first<=ranges[i-1][1]):
            raise ValueError('局部采样范围不合法或未按时间排序')
        blocks=[(start,min(chunk_frames,last-start+1)) for start in range(first,last+1,chunk_frames)]
        planned.extend(blocks); groups.append((last,blocks))
    requested=sum(count for _,count in planned)
    state_path=out/'sampling-checkpoint.json'; complete=out/'complete.json'
    state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'version':1,'info':info,'chunks':[]}
    if state.get('info')!=info: raise ValueError('采样断点与源录像或识别频率不匹配')
    # A marker without a per-image checkpoint is intentionally not trusted here.
    # Existing v1 checkpoints remain fully interchangeable with resume_media.
    state['chunks']=_valid_prefix(state,planned,out,total); write_json(state_path,state)
    valid_count=len(state['chunks']); completed=sum(block['count'] for block in state['chunks'])
    if valid_count==len(planned):
        write_json(complete,info)
        if state['chunks']:
            from ui_observer import preview
            last=state['chunks'][-1]['first']+state['chunks'][-1]['count']-1
            preview(out/f'{last:06d}.jpg',(last-.5)/fps)
        if on_checkpoint: on_checkpoint(state)
        return
    if complete.exists():
        complete.resolve().relative_to(out); complete.unlink()
    if state['chunks'] and on_checkpoint: on_checkpoint(state)
    skipped=0
    for range_last,blocks in groups:
        pending=blocks[max(0,valid_count-skipped):] if skipped<valid_count else blocks
        skipped+=len(blocks)
        if not pending: continue
        _check(abort_event)
        run_first=pending[0][0]; run_count=range_last-run_first+1
        scratch=out/'continuous-runs'/uuid.uuid4().hex; (scratch/'hud').mkdir(parents=True)
        args=_command(source,scratch,video,run_first,run_count,fps,cuda,cpu_threads)
        with (scratch/'decode.log').open('w',encoding='utf-8') as log:
            proc=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            position=0; last_progress=0.
            try:
                while True:
                    _check(abort_event); code=proc.poll()
                    if code is not None and code!=0:
                        raise RuntimeError((scratch/'decode.log').read_text(encoding='utf-8',errors='replace')[-3000:])
                    if code==0:
                        if len(list(scratch.glob('*.jpg')))!=run_count or len(list((scratch/'hud').glob('*.jpg')))!=run_count:
                            raise ValueError('连续采样帧数不完整，不提交尾部断点')
                    while position<len(pending):
                        first,count=pending[position]; local_last=first+count-run_first
                        if not _block_closed(scratch,local_last,code==0): break
                        _check(abort_event)
                        block=_publish_block(scratch,out,run_first,first,count)
                        if fingerprint(source)!=identity: raise ValueError('连续采样时源录像发生变化')
                        state['chunks'].append(block); write_json(state_path,state)
                        completed+=count; position+=1
                        from ui_observer import preview
                        last=first+count-1; preview(out/f'{last:06d}.jpg',(last-.5)/fps)
                        if on_checkpoint: on_checkpoint(state)
                        _check(abort_event)
                    if code==0:
                        if position!=len(pending): raise ValueError('连续采样未提交全部逻辑块')
                        break
                    now=time.monotonic()
                    if now-last_progress>=1:
                        print(f'画面采样: {completed/max(1,requested)*100:.1f}% ({completed}帧已提交)',flush=True)
                        last_progress=now
                    try: proc.wait(timeout=.1)
                    except subprocess.TimeoutExpired: pass
            except BaseException:
                if proc.poll() is None:
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                raise
    _check(abort_event)
    if fingerprint(source)!=identity: raise ValueError('连续采样时源录像发生变化')
    write_json(complete,info)
