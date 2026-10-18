import type {Clip,OutcomeEvidence} from './shared';
export interface ClipEvent extends OutcomeEvidence {id:string;clipTime:number;seekTime:number}
const replayLeadSeconds=2;
export function clipEvents(clip:Clip,duration=clip.duration):ClipEvent[]{
 const unique=new Map<string,ClipEvent>();for(const e of clip.evidence||[]){const time=e.time-clip.start;if(!['knock','assist','elimination'].includes(e.kind)||!Number.isFinite(time)||time<0||time>duration)continue;const id=`${e.kind}:${e.time}:${e.text||''}`,hasStart=Number.isFinite(e.processStart);
  // Add viewing lead-in only at playback; preserve the actual evidence timestamp
  // and do not subtract again from the already estimated near-result fallback.
  const start=hasStart?e.processStart!-clip.start:time-1,lead=hasStart&&e.processStartBasis!=='near_result'?replayLeadSeconds:0;
  const seekTime=Math.max(0,Math.min(time,start-lead));unique.set(id,{...e,id,clipTime:time,seekTime,processStartBasis:e.processStartBasis||(hasStart?undefined:'near_result')});}
 const sorted=[...unique.values()].sort((a,b)=>a.clipTime-b.clipTime),previous=new Map<string,number>();
 for(const event of sorted){const prior=previous.get(event.kind);if(prior!==undefined&&prior<event.clipTime&&event.seekTime<=prior){
   if(Number.isFinite(event.processStart)&&event.processStart!-clip.start>prior){event.seekTime=Math.min(event.clipTime,prior+.001);}
   else{event.seekTime=Math.min(event.clipTime,Math.max(prior+.001,event.clipTime-1));event.processStartBasis='near_result';}
  }previous.set(event.kind,event.clipTime);}
 return sorted;
}
export function eventGroups(events:ClipEvent[],duration:number,width:number,minGap=36){
 const groups:{id:string;events:ClipEvent[];fraction:number}[]=[];
 for(const e of events){const f=duration>0?e.clipTime/duration:0,last=groups.at(-1);if(last&&(f-last.events.at(-1)!.clipTime/duration)*width<minGap){last.events.push(e);last.fraction=last.events.reduce((s,e)=>s+e.clipTime/duration,0)/last.events.length;}else groups.push({id:e.id,events:[e],fraction:f});}return groups;
}
export const eventLabel=(kind:OutcomeEvidence['kind'])=>kind==='knock'?'击倒':kind==='assist'?'助攻':'击杀';
export const eventIcon=(kind:OutcomeEvidence['kind'])=>kind==='knock'?'knockdowns':kind==='assist'?'assists':'kills';
