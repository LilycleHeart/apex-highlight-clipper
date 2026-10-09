"""本地 Apex 交战识别与关键帧流复制；首版命令行验证内核。"""
from __future__ import annotations

import argparse
import base64
import bisect
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

import cv2
import numpy as np
from weapon_reader import enrich_weapon_labels
from outcome_reader import enrich_outcomes,cap_segment_ends,preserve_team_continuation

BASE = Path(__file__).resolve().parent
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.mov', '.ts', '.m4v'}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt in range(6):
        try:
            temp.replace(path); break
        except PermissionError:
            if attempt==5: raise
            time.sleep(.05*(attempt+1))


def tool(name):
    suffix = '.exe' if os.name == 'nt' else ''
    candidates = [BASE/'tools'/f'{name}{suffix}']
    override = os.environ.get('APEX_FFMPEG_DIR')
    if override:
        candidates.append(Path(override)/f'{name}{suffix}')
    local_config=BASE/'ffmpeg.local.json'
    if local_config.is_file():
        local=json.loads(local_config.read_text(encoding='utf-8-sig'))
        if local.get('directory'): candidates.append(Path(local['directory'])/f'{name}{suffix}')
    for path in candidates:
        if path.is_file():
            return str(path.resolve())
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError(f'找不到 {name}，请放入 tools 或设置 APEX_FFMPEG_DIR')


def run(args):
    result = subprocess.run([str(x) for x in args], capture_output=True,
                            encoding='utf-8', errors='replace',
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError(result.stderr[-6000:] or f'命令失败: {args[0]}')
    return result.stdout


def probe(source):
    data = json.loads(run([tool('ffprobe'), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', source]))
    video = next(s for s in data['streams'] if s['codec_type'] == 'video')
    if not float(data['format'].get('duration', 0)):
        raise ValueError('录像没有可用的时长')
    return data, video


def fingerprint(source):
    source = Path(source).resolve()
    st = source.stat()
    return {'path': str(source), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}


def sample_video(source, out, fps, cuda=False,resume=False):
    if resume:
        from resume_media import sample_with_resume
        return sample_with_resume(source,out,fps,cuda)
    meta, video = probe(source)
    duration = float(meta['format']['duration'])
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    info = {'source': fingerprint(source), 'fps': fps, 'width': 1280, 'duration': duration}
    marker = out/'complete.json'
    if marker.exists():
        saved=json.loads(marker.read_text(encoding='utf-8'))
        if all(saved.get(k)==v for k,v in info.items()):
            print('复用已完成的画面采样（缺少的原生 HUD 会按需补取）', flush=True)
            return
    if list(out.glob('*.jpg')):
        raise ValueError(f'采样目录存在未确认的帧，请使用新目录或先检查: {out}')
    args = [tool('ffmpeg'), '-hide_banner', '-loglevel', 'warning', '-nostdin']
    if cuda:
        from gpu_load import get_gpu_policy
        policy=get_gpu_policy()
        if policy['decode_rate']:
            args += ['-readrate',str(policy['decode_rate'])]
            print(f"GPU 解码节奏：{policy['label']}（最高 {policy['decode_rate']} 倍录像速度）",flush=True)
        args += ['-hwaccel','cuda','-hwaccel_output_format','cuda']
    hud=out/'hud'; hud.mkdir(exist_ok=True)
    width,height=video['width'],video['height']
    cx=round(width*.75/2)*2; cy=round(height*(5/6)/2)*2
    cw=width-cx; ch=height-cy
    transfer='hwdownload,format=p010le,' if '10' in video.get('pix_fmt','') else 'hwdownload,format=nv12,'
    thinning=f'fps={fps},'+(transfer if cuda else '')
    graph=f'[0:v:0]{thinning}split=2[b][h];[b]scale=1280:-2[body];[h]crop={cw}:{ch}:{cx}:{cy}[hud]'
    args += ['-i',str(source),'-filter_complex',graph,
             '-map','[body]','-q:v','2','-n',str(out/'%06d.jpg'),
             '-map','[hud]','-q:v','2','-n',str(hud/'%06d.jpg')]
    log_path=out/'decode.log'
    with log_path.open('w', encoding='utf-8') as log:
        proc=subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=log,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            while proc.poll() is None:
                count=sum(1 for _ in out.glob('*.jpg'))
                print(f'画面采样: {min(count/fps/duration*100, 100):.1f}% ({count}帧)', flush=True)
                time.sleep(5)
        except BaseException:
            proc.terminate(); proc.wait(); raise
    if proc.returncode:
        raise RuntimeError(log_path.read_text(encoding='utf-8', errors='replace')[-3000:])
    count=sum(1 for _ in out.glob('*.jpg'))
    if abs(count/fps - duration) > 2/fps:
        raise ValueError('采样时长不完整')
    write_json(marker, info)


def crop(frame, box, reference):
    h,w=frame.shape[:2]
    rw,rh=reference
    x1,y1,x2,y2=box
    region=frame[round(y1*h/rh):round(y2*h/rh),round(x1*w/rw):round(x2*w/rw)]
    if not region.size:
        raise ValueError('HUD 识别区域为空')
    return cv2.resize(region, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)


def numeric(text, score, limit, minimum=.88):
    text=text.strip()
    if score < minimum or not re.fullmatch(r'\d+', text):
        return None
    value=int(text)
    return value if value <= limit else None


def ammo_number(text, score):
    # Apex 的斜杠零被中文识别模型稳定识别成“日”；只在弹药小区域修正。
    if '日' in text and score >= .67:
        text=text.replace('日','0')
        return numeric(text,score,1000,.67)
    if score>=.80 and re.fullmatch(r'[0-9O〇Ø]+',text):
        return numeric(text.translate(str.maketrans({'O':'0','〇':'0','Ø':'0'})),score,1000,.80)
    return numeric(text,score,1000,.86)


def icon_signature(frame, profile):
    image=crop(frame, profile['weapon_icon'], profile['reference_size'])
    image=cv2.resize(image,(96,28))
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(gray,65,130)>0
    return base64.b64encode(np.packbits(edges).tobytes()).decode('ascii')


def icon_similarity(a,b):
    x=np.unpackbits(np.frombuffer(base64.b64decode(a),dtype=np.uint8)).astype(bool)
    y=np.unpackbits(np.frombuffer(base64.b64decode(b),dtype=np.uint8)).astype(bool)
    intersection=np.count_nonzero(x&y)
    return 2*intersection/max(np.count_nonzero(x)+np.count_nonzero(y),1)


def counter_offset(frame, profile, template):
    # Apex 的计分 HUD 会因动画和数字宽度整体平移，用图标作锚点。
    ref=cv2.resize(frame,(profile['reference_size'][0]//2,profile['reference_size'][1]//2))
    x1,y1,x2,y2=[round(v/2) for v in profile['counter_marker_search']]
    region=cv2.cvtColor(ref[y1:y2,x1:x2],cv2.COLOR_BGR2GRAY)
    _,score,_,location=cv2.minMaxLoc(cv2.matchTemplate(region,template,cv2.TM_CCOEFF_NORMED))
    if score<.78: return None,score
    origin=profile['counter_marker_origin']
    return ((location[0]+x1)*2-origin[0],(location[1]+y1)*2-origin[1]),score


def inactive_view(frame):
    h,w=frame.shape[:2]
    # 观战和赛后面板都有底部黑色控制栏；本样本用来阻断他人的弹药信号。
    bottom=frame[round(h*.985):,round(w*.12):round(w*.88)]
    return float(np.mean(np.max(bottom,axis=2)<14))>.72


HUD_FIELDS=('reference_size','ammo','weapon','weapon_icon','damage','kills',
            'counter_marker','counter_marker_origin','counter_marker_search')


def same_hud_profile(a,b):
    # 新增生命周期配置时可复用原有弹药/计分 OCR，但区域变更仍必须重新识别。
    return all(a.get(k)==b.get(k) for k in HUD_FIELDS)


def lifecycle_signature(profile):
    template_path=BASE/profile['downed_marker']
    return hashlib.sha256(template_path.read_bytes()+json.dumps({
        'version':1,'search':profile['downed_marker_search'],
        'threshold':profile['downed_marker_threshold'],
        'reference':profile['reference_size']},sort_keys=True).encode()).hexdigest()


def downed_score(frame,profile,template):
    rw,rh=profile['reference_size']
    x1,y1,x2,y2=[round(v/2) for v in profile['downed_marker_search']]
    ref=cv2.resize(frame,(rw//2,rh//2))
    region=cv2.cvtColor(ref[y1:y2,x1:x2],cv2.COLOR_BGR2GRAY)
    return float(cv2.minMaxLoc(cv2.matchTemplate(region,template,cv2.TM_CCOEFF_NORMED))[1])


def enrich_lifecycle(cache, samples, profile):
    template_path=BASE/profile['downed_marker']
    signature=lifecycle_signature(profile)
    if cache.get('lifecycle_signature')==signature: return cache
    template=cv2.imread(str(template_path),cv2.IMREAD_GRAYSCALE)
    if template is None: raise ValueError('缺少倒地 HUD 图标模板')
    for row in cache['rows']:
        frame=cv2.imread(str(Path(samples)/row['frame']))
        if frame is None: raise ValueError(f"采样帧不存在: {row['frame']}")
        score=downed_score(frame,profile,template)
        row['downed_score']=float(score)
        row['downed']=score>=profile['downed_marker_threshold']
        row['inactive_view']=inactive_view(frame)
    cache['lifecycle_signature']=signature; cache['profile']=profile
    return cache


def downed_intervals(rows, duration, gap=35, post=15, terminal_tail=2):
    """倒地不按停止开枪结束；覆盖救援/再次倒地，到赛后或复活后的收尾。"""
    confirmed=[]
    for i,row in enumerate(rows):
        if not row.get('downed') or row.get('inactive_view'): continue
        neighbours=rows[max(0,i-2):i+3]
        votes=sum(r.get('downed',False) and not r.get('inactive_view')
                  and abs(r['time']-row['time'])<=1.1 for r in neighbours)
        if votes>=2: confirmed.append(row['time'])
    if not confirmed: return []
    groups=[]; first=last=confirmed[0]
    for t in confirmed[1:]:
        if t-last<=gap: last=t
        else: groups.append((first,last)); first=last=t
    groups.append((first,last))
    intervals=[]
    for first,last in groups:
        terminal=None
        for i,row in enumerate(rows[:-1]):
            if not last<row['time']<=last+post: continue
            following=rows[i+1]
            if row.get('inactive_view') and following.get('inactive_view') and following['time']-row['time']<=1.1:
                terminal=row['time']; break
        end=min(duration, terminal+terminal_tail if terminal is not None else last+post)
        intervals.append({'start':first,'end':end,'last_downed':last,'terminal_time':terminal,
                          'reason':'downed_until_terminal' if terminal is not None else 'downed_recovery_tail'})
    return intervals


HUD_BATCH_SIZE=16


def read_hud(samples, profile, fps, output, start=0, end=math.inf,optimize=True,timestamps=None,resume=False,source_identity=None,frame_limit=None,expected_frames=None,partial=False,session=None,selected_names=None,expected_names=None):
    backend=os.environ.get('APEX_OCR_BACKEND','cpu').lower()
    from engine_pool import pooled_engine
    def make_engine():
        if backend=='cpu':
            from rapidocr_onnxruntime import RapidOCR
            return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1,
                        det_limit_side_len=256, det_limit_type='max', rec_batch_num=24)
        from gpu_ocr_backend import create_ocr_engine
        return create_ocr_engine(backend=backend,rec_batch_num=24)
    engine=pooled_engine(('digits',backend,os.environ.get('APEX_GPU_LOAD','fast')),make_engine)
    if backend!='cpu':
        print(f'OCR 后端: {engine.backend_info["providers"]}',flush=True)
    from ocr_cache import ExactTextCache
    recognizer_key=(id(engine),optimize,backend,os.environ.get('APEX_GPU_LOAD','fast'))
    if session is not None and session.get('recognizer_key')==recognizer_key:
        recognizer=session['recognizer']
    else:
        recognizer=ExactTextCache(engine.text_rec) if optimize else engine.text_rec
        if session is not None: session.update(recognizer_key=recognizer_key,recognizer=recognizer,recognizer_engine=engine)
    rows=[]; tic=time.perf_counter()
    # 名称已由原生 HUD 独立读取；基础 OCR 只保留三个数字区域。
    keys=['ammo','damage','kills']
    marker=cv2.imread(str(BASE/profile['counter_marker']),cv2.IMREAD_GRAYSCALE)
    if marker is None: raise ValueError('缺少 HUD 图标模板')
    lifecycle_marker=cv2.imread(str(BASE/profile['downed_marker']),cv2.IMREAD_GRAYSCALE) if optimize and profile.get('downed_marker') else None
    lifecycle_id=lifecycle_signature(profile) if lifecycle_marker is not None else None
    frames=sorted(Path(samples).glob('*.jpg'))
    def frame_time(path): return timestamps[path.name] if timestamps is not None else (int(path.stem)-.5)/fps
    if expected_names is not None:
        if expected_frames is not None or selected_names is not None: raise ValueError('明确采样计划不能混用计数或临时选择')
        ids=[]
        for name in expected_names:
            if not isinstance(name,str) or not re.fullmatch(r'\d{6,}\.jpg',name): raise ValueError('采样计划文件名无效')
            number=int(name[:-4])
            if number<1 or name!=f'{number:06d}.jpg' or (ids and number<=ids[-1]): raise ValueError('采样计划必须按全局编号严格递增')
            ids.append(number)
        expected=[Path(samples)/name for name in expected_names]
        selected=[p for p in expected if frame_limit is None or int(p.stem)<=frame_limit]
        if any(not p.is_file() for p in selected): raise ValueError('已提交采样前缀有缺帧，不能提前完成识别')
        if any(not start<=frame_time(p)<=end for p in selected): raise ValueError('采样计划与时间过滤不匹配')
        if not partial and len(selected)!=len(expected): raise ValueError('尚未消费完整采样计划')
    else:
        selected=[p for p in frames if start <= frame_time(p) <= end]
        if selected_names is not None: selected=[p for p in selected if p.name in selected_names]
        expected=[Path(samples)/f'{i:06d}.jpg' for i in range(1,expected_frames+1)] if expected_frames is not None else list(selected)
        if frame_limit is not None: selected=[p for p in selected if int(p.stem)<=frame_limit]
    display_duration=max((frame_time(p) for p in expected),default=0)+.5/fps
    journal=None
    if resume:
        from resume_io import RowJournal
        signature=hashlib.sha256(json.dumps({'version':1,'source':source_identity,'samples':str(Path(samples).resolve()),
            'profile':profile,'fps':fps,'selected':[(p.name,frame_time(p)) for p in expected],
            'marker':hashlib.sha256((BASE/profile['counter_marker']).read_bytes()).hexdigest(),
            'lifecycle':lifecycle_id},sort_keys=True).encode()).hexdigest()
        def valid_row(row,index):
            return index<len(expected) and row.get('frame')==expected[index].name and row.get('time')==frame_time(expected[index]) and all(key in row for key in ['ammo','damage','kills','weapon_icon','inactive_view'])
        if session is not None and session.get('signature')==signature:
            journal=session['journal']
        else:
            journal=RowJournal(Path(output).with_suffix('.rows.jsonl'),signature,valid_row)
            if session is not None: session.update(signature=signature,journal=journal)
        rows=list(journal.rows)
        if rows: print(f'OCR 续接：保留 {len(rows)} 帧，从 {rows[-1]["time"]:.2f} 秒后继续',flush=True)
    for offset in range(len(rows),len(selected),HUD_BATCH_SIZE):
        if resume:
            from app_cancel import check_cancel
            check_cancel()
        before_count=len(rows)
        batch=selected[offset:offset+HUD_BATCH_SIZE]
        crops=[]; slots=[]; signatures=[]; offsets=[]; inactive=[]; downed_scores=[]
        for path in batch:
            frame=cv2.imread(str(path))
            delta,score=counter_offset(frame,profile,marker)
            offsets.append((delta,score)); inactive.append(inactive_view(frame))
            if lifecycle_marker is not None: downed_scores.append(downed_score(frame,profile,lifecycle_marker))
            for k in keys:
                box=profile[k]
                if k in ['damage','kills']:
                    if delta is None:
                        if optimize: slots.append(None)
                        else: slots.append(len(crops)); crops.append(np.zeros((48,64,3),dtype=np.uint8))
                        continue
                    dx,dy=delta
                    box=[box[0]+dx,box[1]+dy,box[2]+dx,box[3]+dy]
                slots.append(len(crops)); crops.append(crop(frame,box,profile['reference_size']))
            signatures.append(icon_signature(frame,profile))
        recognized,_=recognizer(crops)
        result=[('',0.) if index is None else recognized[index] for index in slots]
        for j,path in enumerate(batch):
            # fps 滤镜在每个采样单元取近中心帧；用中心时间标注（2 Hz 时 +0.25s）。
            t=frame_time(path)
            row={'time':t,'frame':path.name,'weapon_icon':signatures[j],
                 'counter_offset':offsets[j][0],'counter_marker_score':offsets[j][1],
                 'inactive_view':inactive[j]}
            if lifecycle_marker is not None:
                row.update(downed_score=downed_scores[j],downed=downed_scores[j]>=profile['downed_marker_threshold'])
            for k,(text,score) in zip(keys,result[j*len(keys):(j+1)*len(keys)]):
                row[k+'_text']=text; row[k+'_score']=float(score)
                if k!='weapon':
                    row[k]=ammo_number(text,score) if k=='ammo' else numeric(text,score, {'damage':20000,'kills':60}[k], .88)
            rows.append(row)
        if journal: journal.append(rows[before_count:])
        from ui_observer import preview
        preview(batch[-1],rows[-1]['time'])
        if offset%64==0:
            print(f'OCR: {t:.1f}s / {display_duration:.1f}s，{len(rows)}帧，耗时{time.perf_counter()-tic:.1f}s',flush=True)
            if not resume: write_json(output,{'profile':profile,'fps':fps,'timestamp_basis':'cell_center','complete':False,'rows':rows})
    completed={'profile':profile,'fps':fps,'timestamp_basis':'explicit_pts' if timestamps is not None else 'cell_center','complete':not partial,'rows':rows}
    if lifecycle_id: completed['lifecycle_signature']=lifecycle_id
    if optimize: completed['ocr_optimization']=recognizer.stats()
    if source_identity is not None: completed['source']=source_identity
    if not partial: write_json(output,completed)
    print(f'OCR完成: {len(rows)}帧 / {time.perf_counter()-tic:.1f}s',flush=True)
    if optimize: print(f'OCR 精确复用: {recognizer.stats()}；未显示的计分区域不送入模型',flush=True)
    return rows


def stable_counter(rows, key):
    """计数增长需要相邻多帧确认，屏蔽 OCR 单帧误读与菜单切换。"""
    result={}
    for i,row in enumerate(rows):
        value=None if row.get('inactive_view') else row.get(key)
        if value is None: continue
        neighbours=rows[max(0,i-2):min(len(rows),i+3)]
        votes=sum(r.get(key)==value and abs(r['time']-row['time'])<=1.1 for r in neighbours)
        if votes>=2: result[i]=value
    return result


def detect_events(rows):
    events=[]; reborn=[]
    # 命中与击杀用本人 HUD 的累计值，不读取全队击杀播报。
    for key,kind,max_step in [('damage','hit',1000),('kills','kill',3)]:
        confirmed=stable_counter(rows,key)
        previous=None; previous_t=None
        for i,value in confirmed.items():
            t=rows[i]['time']
            if previous is not None and value>previous and value-previous<=max_step and t-previous_t<=20:
                events.append({'time':t,'kind':kind,'before':previous,'after':value,'evidence':'own_'+key+'_counter'})
            if previous is not None and t-previous_t>20:
                # 新局第一次数值可能与上一局相等或更大，不能仅靠数值下降辨识。
                between=[r for r in rows if previous_t<r['time']<t]
                if value>0 and any(r.get('round_ended',False) for r in between):
                    reborn.append({'time':t,'kind':kind,'before':0,'after':value,'evidence':'new_round_counter'})
            if previous is None or value>=previous or t-previous_t>20:
                previous=value; previous_t=t
    # 枪械切换可能造成弹药减少；要求相同枪名或连续多次下降。
    candidates=[]
    previous=None
    for i,b in enumerate(rows):
        if b.get('inactive_view'): previous=None; continue
        if b.get('ammo') is None: continue
        old=previous; previous=i
        if old is None: continue
        a=rows[old]
        if b['time']-a['time']>1.1: continue
        drop=a['ammo']-b['ammo']
        if not 1 <= drop <= 50: continue
        similarity=icon_similarity(a['weapon_icon'],b['weapon_icon'])
        same_weapon=similarity>=.65
        if a.get('current_weapon') and b.get('current_weapon'):
            same_weapon=same_weapon and a['current_weapon']['id']==b['current_weapon']['id']
        if a.get('active_weapon_slot') is not None and b.get('active_weapon_slot') is not None:
            same_weapon=same_weapon and a['active_weapon_slot']==b['active_weapon_slot']
        candidates.append({'time':b['time'],'kind':'shoot','before':a['ammo'],'after':b['ammo'],
                           'evidence':'ammo_decrease','same_weapon':bool(same_weapon),
                           'icon_similarity':round(similarity,3),'index':i})
    for c in candidates:
        confirmed_hit=any(e['kind']=='hit' and abs(e['time']-c['time'])<=1.5 for e in events)
        if c['same_weapon'] or confirmed_hit:
            events.append(c)
    # 首次击杀前 HUD 不显示计分栏。第一次出现的正计数须有近邻开枪支持。
    for key,kind in [('damage','hit'),('kills','kill')]:
        confirmed=stable_counter(rows,key)
        if confirmed:
            i=next(iter(confirmed)); value=confirmed[i]; t=rows[i]['time']
            # 回放从半局开始时，开头已有的累计数是基线，不是新贡献。
            if value>0 and t-rows[0]['time']>=15 and any(e['kind']=='shoot' and abs(e['time']-t)<=12 for e in events):
                events.append({'time':t,'kind':kind,'before':None,'after':value,
                               'evidence':'own_counter_became_visible'})
    for birth in reborn:
        if any(e['kind']=='shoot' and abs(e['time']-birth['time'])<=12 for e in events): events.append(birth)
    return sorted(events,key=lambda e:e['time'])


def segments_from_events(events, duration, gap=35, pre=10, post=15, protected_intervals=None):
    if not all(math.isfinite(x) and x>=0 for x in [duration,gap,pre,post]):
        raise ValueError('时间参数必须为非负有限数')
    times=sorted({e['time'] for e in events if 0 <= e['time'] < duration})
    if not times and not protected_intervals: return []
    groups=[]
    first=last=times[0] if times else None
    for t in times[1:]:
        if t-last<=gap: last=t
        else: groups.append((first,last)); first=last=t
    if times: groups.append((first,last))
    segments=[]
    for first,last in groups:
        start=max(0,first-pre); end=min(duration,last+post)
        if segments and start<=segments[-1]['end']:
            segments[-1]['end']=max(segments[-1]['end'],end)
            segments[-1]['last_signal']=last
        else: segments.append({'start':start,'end':end,'first_signal':first,'last_signal':last})
    for interval in protected_intervals or []:
        if not (0<=interval['start']<interval['end']<=duration):
            raise ValueError('非法生命周期片段')
        segments.append({'start':max(0,interval['start']-pre),'end':interval['end'],
                         'first_signal':interval['start'],'last_signal':interval.get('last_downed',interval['start']),
                         'protected_reasons':[interval['reason']]})
    merged=[]
    for segment in sorted(segments,key=lambda s:s['start']):
        if merged and segment['start']<=merged[-1]['end']:
            target=merged[-1]; target['end']=max(target['end'],segment['end'])
            target['first_signal']=min(target['first_signal'],segment['first_signal'])
            target['last_signal']=max(target['last_signal'],segment['last_signal'])
            reasons=target.get('protected_reasons',[])+segment.get('protected_reasons',[])
            if reasons: target['protected_reasons']=sorted(set(reasons))
        else: merged.append(dict(segment))
    return merged


def classify_combat_candidates(events, segments, hit_window=12):
    """开枪是候选信号，不能直接证明完整交战。低证据候选留待复核。"""
    confirmed=[]; review=[]
    for segment in segments:
        relevant=[e for e in events if segment['start']<=e['time']<segment['end']]
        hits=sorted(e['time'] for e in relevant if e['kind']=='hit'
                    and e.get('after',0)>(e.get('before') or 0))
        has_kill=any(e['kind']=='kill' and e.get('after',0)>(e.get('before') or 0) for e in relevant)
        continuing_downed=bool(segment.get('protected_reasons'))
        repeated_hits=any(0<b-a<=hit_window for a,b in zip(hits,hits[1:]))
        strong_single=any(e['kind']=='hit' and e.get('after',0)-(e.get('before') or 0)>=60
                          and any(s['kind']=='shoot' and abs(s['time']-e['time'])<=1.5 for s in relevant)
                          for e in relevant)
        reasons=[]
        if has_kill: reasons.append('own_kill')
        if continuing_downed: reasons.append('downed_continuation')
        if repeated_hits: reasons.append('repeated_hit_feedback')
        if strong_single: reasons.append('strong_hit_with_shot')
        candidate=dict(segment)
        candidate['combat_evidence']={'shoot_samples':sum(e['kind']=='shoot' for e in relevant),
                                      'hit_updates':len(hits),'repeated_hit_window':hit_window,
                                      'accepted_reasons':reasons}
        candidate['classification']='confirmed' if reasons else 'review'
        if reasons: confirmed.append(candidate)
        else:
            candidate['review_reason']='只有开枪或孤立命中，缺少连续命中/击杀/倒地延续证据'
            review.append(candidate)
    return confirmed,review


def keyframes(source):
    # 包标志足够定位随机访问点，无须全片解码。
    data=run([tool('ffprobe'),'-v','error','-select_streams','v:0','-show_packets',
              '-show_entries','packet=pts_time,flags','-of','csv=p=0',source])
    keys=[]
    for line in data.splitlines():
        parts=line.split(',')
        if len(parts)>=2 and 'K' in parts[1]:
            try: keys.append(float(parts[0]))
            except ValueError: pass
    keys=sorted(set(keys))
    if not keys: raise ValueError('找不到可用关键帧')
    return keys


def align_segments(segments, keys, duration):
    aligned=[]
    for segment in segments:
        start,end=segment['start'],segment['end']
        if not (math.isfinite(start) and math.isfinite(end) and 0<=start<end<=duration+.05):
            raise ValueError(f'非法片段: {segment}')
        left=keys[max(0,bisect.bisect_right(keys,start)-1)]
        j=bisect.bisect_left(keys,end)
        right=keys[j] if j<len(keys) else duration
        if aligned and left<=aligned[-1]['end']:
            aligned[-1]['end']=max(aligned[-1]['end'],right)
        else: aligned.append({'start':left,'end':right,'requested_start':start,'requested_end':end})
    return aligned


def label_event_weapons(events, rows):
    catalog_path=BASE/'weapon-catalog.json'
    catalog=json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.exists() else {'weapons':[]}
    by_time={round(r['time'],6):r for r in rows}
    # 同一录像中，多次可靠的当前槽文字可以提供该皮肤/光照下的图标回退。
    local={}
    for r in rows:
        w=r.get('current_weapon')
        if w and r.get('current_weapon_confidence',0)>=.90 and r.get('weapon_icon'):
            local.setdefault(w['id'],[]).append(r)
    for event in events:
        if event['kind']!='shoot': continue
        row=by_time.get(round(event['time'],6))
        match=row.get('current_weapon') if row else None
        confidence=row.get('current_weapon_confidence',0) if row else 0
        if row and not match:
            neighbours=[r for r in rows if abs(r['time']-event['time'])<=.6 and r.get('current_weapon')
                        and icon_similarity(row['weapon_icon'],r['weapon_icon'])>=.80]
            if neighbours:
                neighbour=max(neighbours,key=lambda r:r['current_weapon_confidence'])
                match=neighbour['current_weapon']; confidence=neighbour['current_weapon_confidence']
        if match:
            event['weapon']=match['name']; event['weapon_id']=match['id']
            event['weapon_variant']=match.get('variant'); event['weapon_confidence']=round(confidence,3)
            event['weapon_method']='native_hud_text'
            continue
        if row:
            learned=[]
            for ident,known in local.items():
                scores_for_id=sorted([float(icon_similarity(row['weapon_icon'],r['weapon_icon'])) for r in known],reverse=True)
                if len(scores_for_id)>=2 and scores_for_id[1]>=.86:
                    learned.append((scores_for_id[1],known[0]['current_weapon']))
            learned.sort(key=lambda item:item[0],reverse=True)
            if learned and (len(learned)==1 or learned[0][0]-learned[1][0]>=.10):
                confidence,w=learned[0]
                event['weapon']=w['name']; event['weapon_id']=w['id']; event['weapon_variant']=w.get('variant')
                event['weapon_confidence']=round(confidence,3); event['weapon_method']='recording_icon_consensus'
                continue
        scores=[]
        if row and row.get('weapon_icon'):
            for weapon in catalog['weapons']:
                if not weapon.get('prototypes'): continue
                score=max(icon_similarity(row['weapon_icon'],p) for p in weapon['prototypes'])
                scores.append((float(score),weapon['name']))
        scores.sort(reverse=True)
        accepted=(scores and scores[0][0]>=.86 and (len(scores)==1 or scores[0][0]-scores[1][0]>=.10))
        event['weapon']=scores[0][1] if accepted else '未知枪'
        event['weapon_confidence']=round(scores[0][0],3) if scores else 0
        event['weapon_method']='calibrated_icon' if accepted else 'unknown'
        event['weapon_id']=next((w['id'] for w in catalog['weapons'] if w['name']==event['weapon']),None)
    return events


def segment_summary(events, segment):
    if events is None: return {'kills':None,'damage':None,'weapons':['未知枪']}
    relevant=[e for e in events if segment['start']<=e['time']<segment['end']]
    weapons=[]
    for event in relevant:
        if event['kind']=='shoot':
            weapon=event.get('weapon','未知枪')
            if weapon not in weapons: weapons.append(weapon)
    def increments(kind):
        return sum(max(0,e['after']-(e['before'] if e['before'] is not None else 0))
                   for e in relevant if e['kind']==kind)
    return {'kills':increments('kill'),'damage':increments('hit'),'weapons':weapons or ['未知枪'],
            'statistics_basis':'本段本人 HUD 计数增量；首次显现且无旧计数的事件按零基线计'}


def recording_prefix(source):
    match=re.search(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})[ T_-]+(\d{2})[-_:]?(\d{2})[-_:]?(\d{2})',Path(source).stem)
    if match:
        try:
            date=datetime(*map(int,match.groups()))
            return f'{date.year}年{date.month}月{date.day}日 {date.hour}点{date.minute:02d}分'
        except ValueError: pass
    # 无录像时间时使用文件修改时间，明确采用用户时区。
    date=datetime.fromtimestamp(Path(source).stat().st_mtime,timezone(timedelta(hours=8)))
    return f'{date.year}年{date.month}月{date.day}日 {date.hour}点{date.minute:02d}分'


def informative_filename(source, index, summary):
    kills=f"{summary['kills']}杀" if summary['kills'] is not None else '未知杀'
    damage=f"{summary['damage']}伤" if summary['damage'] is not None else '未知伤'
    weapons='+'.join(summary['weapons'][:3])+('等' if len(summary['weapons'])>3 else '')
    weapons=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',weapons).strip(' .') or '未知枪'
    return f'{recording_prefix(source)} 第{index}段 {kills} {weapons} {damage}.mp4'


def export_lossless(source, segments, output, events=None,resume=False):
    if resume:
        from resume_media import export_with_resume
        return export_with_resume(source,segments,output,events)
    output=Path(output).resolve(); output.mkdir(parents=True,exist_ok=True)
    if not segments: raise ValueError('没有片段；不会生成空视频')
    source=Path(source).resolve()
    meta,_=probe(source); duration=float(meta['format']['duration'])
    aligned=align_segments(segments,keyframes(source),duration)
    summaries=[segment_summary(events,s) for s in aligned]
    targets=[output/informative_filename(source,i+1,summaries[i]) for i in range(len(aligned))]
    if (output/'export.json').exists(): raise FileExistsError('此目录已有导出清单，请使用新目录')
    for target in targets:
        if target.exists(): raise FileExistsError(f'输出已存在，不覆盖: {target}')
    files=[]; commands=[]; clips=[]
    for i,s in enumerate(aligned):
        clip=targets[i]
        args=[tool('ffmpeg'),'-hide_banner','-loglevel','warning','-nostdin','-n',
              '-ss',f"{s['start']:.9f}",'-i',str(source),'-t',f"{s['end']-s['start']:.9f}",
              '-map','0:v:0','-map','0:a?','-map_metadata','0','-c','copy',
              '-avoid_negative_ts','make_zero','-movflags','+faststart',str(clip)]
        print(f"无损切割 {i+1}/{len(aligned)}: {s['start']:.3f}—{s['end']:.3f}s",flush=True)
        log=run(args); commands.append({'args':args,'log':log}); files.append(clip)
        result_meta,_=probe(clip)
        if [(s['codec_type'],s['codec_name']) for s in result_meta['streams']]!=[(s['codec_type'],s['codec_name']) for s in meta['streams']]:
            raise ValueError('导出后音视频流不符，请检查导出物')
        clips.append({'output':str(clip),'segment':s,'summary':summaries[i],'metadata':result_meta})
    write_json(output/'export.json',{'mode':'segments','source':fingerprint(source),'segments':aligned,
               'outputs':[str(f) for f in files],'commands':commands,'clips':clips})
    with (output/'segments.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f)
        for i,s in enumerate(aligned): writer.writerow([s['start'],s['end'],f'交战 {i+1}'])
    print(f'导出完成: {len(files)} 个独立交战视频 -> {output}',flush=True)
    return files


def batch_process(folder, output, profile, fps=2, cuda=False, gap=35, pre=10, post=15):
    folder=Path(folder).resolve(); output=Path(output).resolve()
    if not folder.is_dir(): raise ValueError('输入文件夹不存在')
    files=sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
    if not files: raise ValueError('输入文件夹没有支持的录像')
    output.mkdir(parents=True,exist_ok=True); results=[]
    for i,source in enumerate(files):
        print(f'\n录像 {i+1}/{len(files)}: {source.name}',flush=True)
        identity=fingerprint(source)
        job_config={'source':identity,'profile':profile,'fps':fps,
                    'marker_sha256':hashlib.sha256((BASE/profile['counter_marker']).read_bytes()).hexdigest(),
                    'downed_sha256':hashlib.sha256((BASE/profile['downed_marker']).read_bytes()).hexdigest()}
        token=hashlib.sha256(json.dumps(job_config,sort_keys=True).encode()).hexdigest()[:12]
        job=output/(source.stem+'_'+token); job.mkdir(exist_ok=True)
        catalog_path=BASE/'weapon-catalog.json'
        naming_id=hashlib.sha256(catalog_path.read_bytes()+b'|name-v3-human-date').hexdigest()[:8] if catalog_path.exists() else 'unknown-v3'
        export_dir=job/f'export_confirmed_v2_{naming_id}_g{gap:g}_pre{pre:g}_post{post:g}'
        try:
            meta,video=probe(source)
            rw,rh=profile['reference_size']
            if abs(video['width']/video['height']-rw/rh)>.03:
                raise ValueError('录像宽高比与 HUD 配置不同，请先校准 profile')
            manifest=export_dir/'export.json'
            if manifest.exists():
                existing=json.loads(manifest.read_text(encoding='utf-8'))
                clips=existing.get('clips',[])
                intact=(existing.get('mode')=='segments' and clips and all(Path(c['output']).is_file()
                        and Path(c['output']).stat().st_size==int(c['metadata']['format']['size']) for c in clips))
                if existing['source']==identity and intact:
                    results.append({'source':str(source),'status':'existing','outputs':existing['outputs']})
                    write_json(output/'batch-results.json',results); continue
            sample_video(source,job/'samples',fps,cuda)
            cache=job/'hud.json'
            if cache.exists():
                saved=json.loads(cache.read_text(encoding='utf-8'))
                reusable=(saved.get('complete') and saved.get('source')==identity
                          and saved.get('profile')==profile and saved.get('fps')==fps)
            else: reusable=False
            rows=saved['rows'] if reusable else read_hud(job/'samples',profile,fps,cache)
            if not reusable:
                saved=json.loads(cache.read_text(encoding='utf-8')); saved['source']=identity; write_json(cache,saved)
            saved=enrich_lifecycle(saved,job/'samples',profile)
            saved=enrich_weapon_labels(saved,job/'samples',profile,tool('ffmpeg'))
            saved=enrich_outcomes(saved,job/'samples')
            write_json(cache,saved); rows=saved['rows']
            events=label_event_weapons(detect_events(rows),rows)
            duration=float(meta['format']['duration'])
            lifecycle=downed_intervals(rows,duration,gap,post)
            candidates=segments_from_events(events,duration,gap,pre,post,lifecycle)
            candidates=cap_segment_ends(candidates,saved['outcome_events'])
            candidates=preserve_team_continuation(candidates,rows,saved['outcome_events'],duration)
            segments,review=classify_combat_candidates(events,candidates)
            write_json(job/'analysis.json',{'source':identity,'duration':duration,
                       'parameters':{'gap':gap,'pre':pre,'post':post},'events':events,
                       'lifecycle_intervals':lifecycle,'segments':segments,'review_candidates':review,
                       'combat_filter_version':2})
            if segments:
                targets=export_lossless(source,segments,export_dir,events)
                results.append({'source':str(source),'status':'exported','outputs':[str(t) for t in targets]})
            else: results.append({'source':str(source),'status':'review_needed' if review else 'no_signals',
                                  'review_candidates':review})
        except Exception as exc:
            results.append({'source':str(source),'status':'error','error':str(exc)})
            print(f'本录像失败，继续队列: {exc}',flush=True)
        write_json(output/'batch-results.json',results)
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('sample'); s.add_argument('video'); s.add_argument('--out',required=True)
    s.add_argument('--fps',type=float,default=2); s.add_argument('--cuda',action='store_true')
    a=sub.add_parser('analyze'); a.add_argument('video'); a.add_argument('--samples',required=True)
    a.add_argument('--out',required=True); a.add_argument('--profile',default=str(BASE/'profile-ultrawide.json'))
    a.add_argument('--fps',type=float,default=2); a.add_argument('--reuse',action='store_true')
    a.add_argument('--gap',type=float,default=35); a.add_argument('--pre',type=float,default=10); a.add_argument('--post',type=float,default=15)
    e=sub.add_parser('export'); e.add_argument('video'); e.add_argument('--analysis',required=True); e.add_argument('--out',required=True)
    b=sub.add_parser('batch'); b.add_argument('folder'); b.add_argument('--out',default=str(BASE/'output'/'batch'))
    b.add_argument('--profile',default=str(BASE/'profile-ultrawide.json')); b.add_argument('--fps',type=float,default=2)
    b.add_argument('--cuda',action='store_true'); b.add_argument('--gap',type=float,default=35)
    b.add_argument('--pre',type=float,default=10); b.add_argument('--post',type=float,default=15)
    args=p.parse_args()
    if args.command=='batch':
        if not math.isfinite(args.fps) or args.fps<=0: p.error('fps 必须大于 0')
        segments_from_events([],1,args.gap,args.pre,args.post)
        profile=json.loads(Path(args.profile).read_text(encoding='utf-8'))
        results=batch_process(args.folder,args.out,profile,args.fps,args.cuda,args.gap,args.pre,args.post)
        print(json.dumps(results,ensure_ascii=False,indent=2))
        if any(r['status']=='error' for r in results): raise SystemExit(1)
    elif args.command=='sample':
        if not math.isfinite(args.fps) or args.fps<=0: p.error('fps 必须大于 0')
        sample_video(args.video,args.out,args.fps,args.cuda)
    elif args.command=='analyze':
        out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
        profile=json.loads(Path(args.profile).read_text(encoding='utf-8'))
        meta,_=probe(args.video)
        stamp=Path(args.samples)/'complete.json'
        if not stamp.exists(): raise ValueError('采样目录没有完成标记，先运行 sample')
        sampling=json.loads(stamp.read_text(encoding='utf-8'))
        if sampling['source']!=fingerprint(args.video) or sampling['fps']!=args.fps:
            raise ValueError('采样与录像或帧率不匹配')
        if args.reuse:
            cache=json.loads((out/'hud.json').read_text(encoding='utf-8'))
            if not cache['complete'] or not same_hud_profile(cache['profile'],profile) or cache['fps']!=args.fps or cache.get('source')!=fingerprint(args.video):
                raise ValueError('OCR 缓存不匹配或未完成')
            rows=cache['rows']
        else:
            rows=read_hud(args.samples,profile,args.fps,out/'hud.json')
            cache=json.loads((out/'hud.json').read_text(encoding='utf-8'))
            cache['source']=fingerprint(args.video)
            write_json(out/'hud.json',cache)
        cache=enrich_lifecycle(cache,args.samples,profile)
        cache=enrich_weapon_labels(cache,args.samples,profile,tool('ffmpeg'))
        cache=enrich_outcomes(cache,args.samples)
        write_json(out/'hud.json',cache); rows=cache['rows']
        events=label_event_weapons(detect_events(rows),rows)
        duration=float(meta['format']['duration'])
        lifecycle=downed_intervals(rows,duration,args.gap,args.post)
        candidates=segments_from_events(events,duration,args.gap,args.pre,args.post,lifecycle)
        candidates=cap_segment_ends(candidates,cache['outcome_events'])
        candidates=preserve_team_continuation(candidates,rows,cache['outcome_events'],duration)
        segments,review=classify_combat_candidates(events,candidates)
        write_json(out/'analysis.json',{'source':fingerprint(args.video),'duration':duration,
                   'parameters':{'gap':args.gap,'pre':args.pre,'post':args.post},'events':events,
                   'lifecycle_intervals':lifecycle,'segments':segments,'review_candidates':review,
                   'combat_filter_version':2})
        print(json.dumps({'events':len(events),'lifecycle_intervals':lifecycle,'segments':segments,
                          'review_candidates':review},ensure_ascii=False,indent=2),flush=True)
    else:
        analysis=json.loads(Path(args.analysis).read_text(encoding='utf-8'))
        if analysis['source']!=fingerprint(args.video): raise ValueError('识别记录与输入录像不一致')
        events=analysis['events']
        if any(e['kind']=='shoot' and 'weapon' not in e for e in events):
            hud_path=Path(args.analysis).parent/'hud.json'
            if hud_path.exists():
                hud=json.loads(hud_path.read_text(encoding='utf-8'))
                if hud.get('source')==analysis['source']:
                    label_event_weapons(events,hud['rows'])
                    write_json(args.analysis,analysis)
        if analysis.get('combat_filter_version')!=2:
            confirmed,review=classify_combat_candidates(events,analysis['segments'])
            analysis['segments']=confirmed
            analysis['review_candidates']=analysis.get('review_candidates',[])+review
            analysis['combat_filter_version']=2
            write_json(args.analysis,analysis)
        export_lossless(args.video,analysis['segments'],args.out,events)


if __name__=='__main__': main()
