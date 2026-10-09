"""按战斗元数据重命名已经导出的片段，同时更新清单与验证记录。"""
import argparse
import csv
import json
from pathlib import Path
from apex_clipper import fingerprint, informative_filename, label_event_weapons, segment_summary, write_json, same_hud_profile, tool
from weapon_reader import enrich_weapon_labels

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('analysis'); p.add_argument('directory')
    p.add_argument('--confirmed-only',action='store_true',help='将未确认的旧分段移到待复核子目录')
    args=p.parse_args()
    analysis_path=Path(args.analysis)
    analysis=json.loads(analysis_path.read_text(encoding='utf-8'))
    directory=Path(args.directory).resolve()
    manifest_path=directory/'export.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('mode')!='segments': raise ValueError('仅支持独立分段导出')
    if analysis['source']!=manifest['source']: raise ValueError('分析与导出不是同一录像')
    source=Path(manifest['source']['path'])
    if fingerprint(source)!=manifest['source']: raise ValueError('源录像已发生变化')
    hud=json.loads((analysis_path.parent/'hud.json').read_text(encoding='utf-8'))
    if hud['source']!=analysis['source']: raise ValueError('HUD 缓存不匹配')
    profile=hud['profile']
    if 'weapon_name_boxes' not in profile:
        current=json.loads((Path(__file__).parent/'profile-ultrawide.json').read_text(encoding='utf-8'))
        if not same_hud_profile(profile,current): raise ValueError('旧 HUD 配置需要补充武器名称区域')
        profile=current
    # 与 analyze 同一个采样目录：先查分析目录父级的 samples，再查同目录 samples。
    samples=analysis_path.parent.parent/'samples'
    if not samples.is_dir(): samples=analysis_path.parent/'samples'
    hud=enrich_weapon_labels(hud,samples,profile,tool('ffmpeg'))
    write_json(analysis_path.parent/'hud.json',hud)
    label_event_weapons(analysis['events'],hud['rows'])
    plan=[]; index=0
    review_directory=directory/'待复核'
    for i,clip in enumerate(manifest['clips']):
        summary=segment_summary(analysis['events'],clip['segment'])
        old=Path(clip['output']).resolve()
        confirmed=(not args.confirmed_only or any(clip['segment']['start']<=s['start']
                    and clip['segment']['end']>=s['end'] for s in analysis['segments']))
        if confirmed:
            index+=1
            new=directory/informative_filename(source,index,summary)
        else:
            review_directory.mkdir(exist_ok=True)
            new=review_directory/old.name
        if old.parent!=directory or new.parent not in [directory,review_directory]: raise ValueError('片段路径超出输出目录')
        if old!=new and new.exists(): raise FileExistsError(f'文件已存在: {new}')
        if not old.is_file(): raise FileNotFoundError(old)
        plan.append((clip,old,new,summary,confirmed))
    moved=[]
    try:
        for _,old,new,_,_ in plan:
            if old!=new: old.rename(new); moved.append((old,new))
    except BaseException:
        for old,new in reversed(moved): new.rename(old)
        raise
    history=[]
    mapping={}
    for clip,old,new,summary,confirmed in plan:
        mapping[str(old)]=str(new)
        clip['output']=str(new); clip['summary']=summary
        clip['metadata']['format']['filename']=str(new)
        clip['classification']='confirmed' if confirmed else 'review'
        history.append({'from':str(old),'to':str(new),'summary':summary,'classification':clip['classification']})
        print(f"{clip['classification']}: {new}",flush=True)
    manifest.setdefault('review_clips',[]).extend(c for c,_,_,_,accepted in plan if not accepted)
    manifest['clips']=[c for c,_,_,_,accepted in plan if accepted]
    manifest['segments']=[c['segment'] for c in manifest['clips']]
    manifest['review_candidates']=analysis.get('review_candidates',[])
    manifest['outputs']=[c['output'] for c in manifest['clips']]
    manifest.setdefault('rename_history',[]).extend(history)
    write_json(manifest_path,manifest); write_json(analysis_path,analysis)
    with (directory/'segments.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.writer(f)
        for clip in manifest['clips']:
            s=clip['segment']; writer.writerow([s['start'],s['end'],Path(clip['output']).stem])
    verification_path=directory/'verification.json'
    if verification_path.exists():
        verification=json.loads(verification_path.read_text(encoding='utf-8'))
        verification['outputs']=manifest['outputs']
        for clip in verification.get('clips',[]):
            clip['file']=mapping.get(clip['file'],clip['file'])
        reviewed=[c for c in verification.get('clips',[]) if c['file'] not in manifest['outputs']]
        verification.setdefault('review_clips',[]).extend(reviewed)
        verification['clips']=[c for c in verification.get('clips',[]) if c['file'] in manifest['outputs']]
        verification['filename_update_only']=True
        write_json(verification_path,verification)

if __name__=='__main__': main()
