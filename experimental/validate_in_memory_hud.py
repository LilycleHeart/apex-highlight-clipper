"""Parameterised read-only HUD experiment; reports must stay in validation/."""
import argparse
from collections import Counter
from fractions import Fraction
import json
import os
from pathlib import Path
import time

from apex_clipper import (BASE, probe, fingerprint, detect_events, segments_from_events, downed_intervals,
                          classify_combat_candidates)
from outcome_reader import cap_segment_ends, preserve_team_continuation, result_kind
from .indexed_reader import IndexedKeyframeReader
from .in_memory_hud import read_indexed_hud


def validate_output_paths(report,inputs,validation_root):
    output=Path(report).resolve(); output.relative_to(Path(validation_root).resolve())
    rows=output.with_name(output.stem+'-rows.json')
    input_paths={Path(path).resolve() for path in inputs if path is not None}
    for path in [output,rows]:
        if path in input_paths: raise ValueError('Report paths cannot overwrite an input')
        if path.exists(): raise FileExistsError('Experimental reports must use new files')
    return output,rows


def summarise(rows,duration,outcomes=None):
    events=detect_events(rows)
    lifecycle=downed_intervals(rows,duration)
    candidates=segments_from_events(events,duration,35,10,15,lifecycle)
    if outcomes is not None:
        candidates=cap_segment_ends(candidates,outcomes)
        candidates=preserve_team_continuation(candidates,rows,outcomes,duration)
    accepted,review=classify_combat_candidates(events,candidates)
    counters={}
    for key in ['damage','kills']:
        visible=[r[key] for r in rows if not r.get('inactive_view') and r.get(key) is not None]
        counters[key]={'first_observed':visible[0] if visible else None,'last_observed':visible[-1] if visible else None,
                       'max_observed':max(visible) if visible else None}
    return {'event_counts':dict(Counter(e['kind'] for e in events)),
        'damage_event_total':sum(e['after']-(e.get('before') or 0) for e in events if e['kind']=='hit'),
        'kill_event_total':sum(e['after']-(e.get('before') or 0) for e in events if e['kind']=='kill'),
        'counters':counters,'segments':accepted,'review_candidates':review,'lifecycle_intervals':lifecycle,
        'state_frames':{key:sum(bool(r.get(key)) for r in rows) for key in ['downed','inactive_view','friend_spectate']},
        'events':events}


def audit_text_samples(source,cache,span,budget):
    """Re-read a bounded selection as images; never hand memory IDs to file OCR."""
    from combat_outcome_reader import load_profile,recognize_frame
    from weapon_reader import new_engine
    from rapidocr_onnxruntime.ch_ppocr_det.utils import DetPreProcess
    rows=cache['rows']; chosen={}; started=time.perf_counter()
    for i,row in enumerate(rows):
        scores=row.get('diagnostics',{}).get('toast_prefix_scores',[])
        if not row['inactive_view'] and any(s['score']>=.65 for s in scores): chosen.setdefault(i,set()).add('toast')
        if row['inactive_view'] and (i==0 or not rows[i-1]['inactive_view']):
            for index in range(max(0,i-2),min(len(rows),i+10)): chosen.setdefault(index,set()).add('terminal')
    selected=sorted(chosen)[:budget]; engine=new_engine(); profile=load_profile(); observations=[]
    decoded_index=None; decoded=None
    with IndexedKeyframeReader(source,threads=1) as reader:
        for index in selected:
            row=rows[index]; key=row['keyframe_index']
            if decoded_index!=key:
                if cache['sampling']['mode']=='bursts':
                    first,last,_=reader.read_burst(key,span); decoded=[first,last]
                else: decoded=[reader.read_keyframe(key)]
                decoded_index=key
            frame=decoded[row['burst_slot']]
            if frame.pts!=row['pts']: raise ValueError('Diagnostic re-read returned a different PTS')
            image=reader.body_image(frame); observation={'time':row['time'],'pts':frame.pts,'frame':row['frame']}
            if 'toast' in chosen[index]:
                result=recognize_frame(image,profile,engine)
                observation['own_result_text']=result
            if 'terminal' in chosen[index]:
                engine.text_det.get_preprocess=lambda max_wh:DetPreProcess(512,'max',engine.text_det.mean,engine.text_det.std)
                h,w=image.shape[:2]; region=image[round(h*.18):round(h*.67),round(w*.20):round(w*.80)]
                result,_=engine(region,use_cls=False)
                text=' '.join(x[1] for x in result or [] if float(x[2])>=.60)
                observation['terminal_text']=text; observation['terminal_kind']=result_kind(text,row['inactive_view'])
            observations.append(observation)
    return {'seconds':time.perf_counter()-started,'selected_frames':len(selected),'eligible_frames':len(chosen),
            'budget_exhausted':len(selected)<len(chosen),'observations':observations,
            'scope':'Diagnostic text recognition on sampled memory frames; not full temporal coverage'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--profile',type=Path,default=BASE/'profile-ultrawide.json')
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--mode',choices=['keyframes','bursts'],default='bursts')
    parser.add_argument('--span',default='1/8')
    parser.add_argument('--workers',type=int,choices=[1,2,4],default=4)
    parser.add_argument('--prefetch',type=int,default=8)
    parser.add_argument('--batch-frames',type=int,default=16)
    parser.add_argument('--backend',choices=['cpu','dml'],default='cpu')
    parser.add_argument('--gpu-load',choices=['low','balanced','fast'],default='low')
    parser.add_argument('--reference-hud',type=Path)
    parser.add_argument('--reference-toast-windows',type=Path)
    parser.add_argument('--audit-text',action='store_true')
    parser.add_argument('--audit-budget',type=int,default=64)
    args=parser.parse_args()
    if args.audit_budget<1: parser.error('--audit-budget must be at least 1')
    output,rows_path=validate_output_paths(args.report,[args.source,args.profile,args.reference_hud,args.reference_toast_windows],BASE/'validation')
    reference=None; reference_verified=False
    if args.reference_hud:
        reference=json.loads(args.reference_hud.read_text(encoding='utf-8'))
        if reference.get('source') is not None:
            if reference['source']!=fingerprint(args.source): raise ValueError('Reference HUD source identity does not match this video')
            reference_verified=True
    output.parent.mkdir(parents=True,exist_ok=True)
    os.environ.update(APEX_OCR_BACKEND=args.backend,APEX_GPU_LOAD=args.gpu_load,APEX_OCR_POOL='1')
    profile=json.loads(args.profile.read_text(encoding='utf-8')); span=Fraction(args.span)
    hook=None
    if args.audit_text:
        from combat_outcome_reader import PrefixGate,load_profile
        gate=PrefixGate(load_profile())
        hook=lambda image,row:{'toast_prefix_scores':gate.inspect(image)}
    cache=read_indexed_hud(args.source,profile,mode=args.mode,span=span,workers=args.workers,
        prefetch=args.prefetch,batch_frames=args.batch_frames,backend=args.backend,feature_hook=hook)
    duration=float(probe(args.source)[0]['format']['duration'])
    times=[r['time'] for r in cache['rows']]
    report={'source_name':args.source.name,'settings':{'mode':args.mode,'span':str(span),'workers':args.workers,
        'prefetch':args.prefetch,'batch_frames':args.batch_frames,'backend':args.backend,'gpu_load':args.gpu_load},
        'duration':duration,'stats':cache['stats'],'sample_frames':len(times),
        'largest_sample_gap':max((b-a for a,b in zip(times,times[1:])),default=0),
        'gaps_over_1_1s':sum(b-a>1.1 for a,b in zip(times,times[1:])),
        'raw_numeric_and_state_analysis':summarise(cache['rows'],duration),
        'scope':'Indexed reading + bounded in-memory numeric HUD experiment; no export, no production integration, OS caches uncontrolled'}
    if args.reference_hud:
        ref_rows=reference['rows']; outcomes=reference.get('outcome_events',[])
        ref_summary=summarise(ref_rows,duration,outcomes)
        report['reference']=ref_summary
        report['with_reference_terminal_evidence']=summarise(cache['rows'],duration,outcomes)
        report['reference_evidence_warning']='Reference end times are supplied only to isolate sampling differences; the experiment did not discover them.'
        comparison=report['with_reference_terminal_evidence']
        report['comparison']={'damage_total_equal':comparison['damage_event_total']==ref_summary['damage_event_total'],
            'kills_total_equal':comparison['kill_event_total']==ref_summary['kill_event_total'],
            'bounds_equal_with_reference_endings':[(s['start'],s['end']) for s in comparison['segments']]==[(s['start'],s['end']) for s in ref_summary['segments']],
            'shoot_samples_difference':comparison['event_counts'].get('shoot',0)-ref_summary['event_counts'].get('shoot',0)}
        report['comparison']['reference_source_verified']=reference_verified
        if not reference_verified: report['reference_identity_warning']='Reference has no source identity; comparisons are unverified, not a quality pass.'
    if args.audit_text:
        audit=audit_text_samples(args.source,cache,span,args.audit_budget); report['text_audit']=audit
        outcomes=[{'time':r['time'],'kind':r['terminal_kind'],'text':r['terminal_text'],'frame':r['frame']} for r in audit['observations'] if r.get('terminal_kind')]
        report['with_sampled_terminal_evidence']=summarise(cache['rows'],duration,outcomes)
        if args.reference_toast_windows:
            windows=json.loads(args.reference_toast_windows.read_text(encoding='utf-8'))
            report['labelled_toast_coverage']=[{**window,'sampled_text_event':any(
                window['start']<=r['time']<=window['end'] and any(e['kind']==window['kind'] for e in r.get('own_result_text',{}).get('events',[]))
                for r in audit['observations'])} for window in windows]
    rows_path.write_text(json.dumps(cache,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report['rows_file']=str(rows_path.relative_to(BASE))
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    brief={key:report[key] for key in ['sample_frames','largest_sample_gap','gaps_over_1_1s','stats']}
    brief.update(comparison=report.get('comparison'),report=str(output.relative_to(BASE)))
    print(json.dumps(brief,ensure_ascii=True,indent=2),flush=True)


if __name__=='__main__': main()
