import type {OutcomeEvidence} from './shared';
type Signal={time:number;kind:string;before?:number|null;after?:number};
type Bounds={start:number;end:number;first_signal?:number};
export interface PlaybackAnalysis {events?:Signal[];parameters?:{pre?:number}}

/** Result timestamps locate markers; continuous shooting/damage locates the process to replay. */
export function withProcessStarts(events:OutcomeEvidence[],clip:Bounds,candidates:Bounds[]=[],analysis:PlaybackAnalysis={}):OutcomeEvidence[]{
 const requested=analysis.parameters?.pre;
 const lead=typeof requested==='number'&&Number.isFinite(requested)?Math.min(12,Math.max(0,requested)):6;
 const signals=(Array.isArray(analysis.events)?analysis.events:[]).filter(e=>Number.isFinite(e.time)&&e.time>=clip.start&&e.time<clip.end&&
  (e.kind==='shoot'||e.kind==='hit'&&typeof e.after==='number'&&e.after>(e.before??0))).sort((a,b)=>a.time-b.time);
 const groups:{start:number;end:number}[]=[];
 for(const signal of signals){const last=groups.at(-1);if(last&&signal.time-last.end<=12)last.end=signal.time;else groups.push({start:signal.time,end:signal.time});}
 const result:OutcomeEvidence[]=[];
 for(const event of events){
  let start:number|undefined;
  // A delayed elimination of the same downed player belongs to their earlier fight.
  if(event.kind!=='knock'&&event.target){const target=event.target.normalize('NFKC').toLocaleUpperCase();const knock=result.slice().reverse().find(e=>e.kind==='knock'&&e.target?.normalize('NFKC').toLocaleUpperCase()===target&&event.time-e.time<=120);start=knock?.processStart;}
  const previous=result.slice().reverse().find(e=>e.time<event.time&&(!event.target||!e.target||e.target.normalize('NFKC').toLocaleUpperCase()!==event.target.normalize('NFKC').toLocaleUpperCase()));
  if(start===undefined){const group=groups.slice().reverse().find(g=>g.start<=event.time&&event.time-g.end<=12);if(group){const first=signals.find(s=>s.time>=group.start&&s.time<=event.time&&(!previous||s.time>previous.time));if(first)start=first.time-lead;}}
  if(start===undefined){const candidate=candidates.slice().reverse().find(c=>c.start<=event.time&&c.end>=event.time&&Number.isFinite(c.first_signal)&&c.first_signal! <= event.time&&(!previous||c.first_signal!>previous.time));if(candidate)start=candidate.first_signal!-lead;}
  // Old records without a timeline retain a bounded lead-in rather than land on the result.
  if(start===undefined)start=event.time-6;
  result.push({...event,processStart:Math.max(clip.start,Math.min(event.time,start))});
 }
 return result;
}
