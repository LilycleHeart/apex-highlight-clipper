import type {Clip,OutcomeEvidence} from './shared';
export interface ClipEvent extends OutcomeEvidence {id:string;clipTime:number}
export function clipEvents(clip:Clip,duration=clip.duration):ClipEvent[]{
 const unique=new Map<string,ClipEvent>();for(const e of clip.evidence||[]){const time=e.time-clip.start;if(!['knock','assist','elimination'].includes(e.kind)||!Number.isFinite(time)||time<0||time>duration)continue;const id=`${e.kind}:${e.time}:${e.text||''}`;unique.set(id,{...e,id,clipTime:time});}return[...unique.values()].sort((a,b)=>a.clipTime-b.clipTime);
}
export function eventGroups(events:ClipEvent[],duration:number,width:number,minGap=36){
 const groups:{id:string;events:ClipEvent[];fraction:number}[]=[];
 for(const e of events){const f=duration>0?e.clipTime/duration:0,last=groups.at(-1);if(last&&(f-last.events.at(-1)!.clipTime/duration)*width<minGap){last.events.push(e);last.fraction=last.events.reduce((s,e)=>s+e.clipTime/duration,0)/last.events.length;}else groups.push({id:e.id,events:[e],fraction:f});}return groups;
}
export const eventLabel=(kind:OutcomeEvidence['kind'])=>kind==='knock'?'击倒':kind==='assist'?'助攻':'击杀';
export const eventIcon=(kind:OutcomeEvidence['kind'])=>kind==='knock'?'knockdowns':kind==='assist'?'assists':'kills';
