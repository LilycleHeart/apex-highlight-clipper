import type {OutcomeEvidence} from './shared';
type Signal={time:number;kind:string;before?:number|null;after?:number};
type Bounds={start:number;end:number;first_signal?:number};
export interface PlaybackAnalysis {events?:Signal[];parameters?:{pre?:number}}

/** Export pre-roll belongs to clip creation, never to an event's firing timestamp. */
export function withProcessStarts(events:OutcomeEvidence[],clip:Bounds,candidates:Bounds[]=[],analysis:PlaybackAnalysis={}):OutcomeEvidence[]{
 const signals=(Array.isArray(analysis.events)?analysis.events:[]).filter(e=>Number.isFinite(e.time)&&e.time>=clip.start&&e.time<clip.end&&
  (e.kind==='shoot'||e.kind==='hit'&&typeof e.after==='number'&&e.after>(e.before??0))).sort((a,b)=>a.time-b.time);
 const result:OutcomeEvidence[]=[];
 for(const event of [...events].sort((a,b)=>a.time-b.time)){
  let start:number|undefined,basis:OutcomeEvidence['processStartBasis'];
  const prior=result.slice().reverse().find(e=>e.kind===event.kind&&e.time<event.time);
  const floor=Math.max(clip.start,prior?Math.min(event.time,prior.time+.001):clip.start);
  // A delayed elimination of the same downed player belongs to their earlier fight.
  // Reuse it only when doing so does not cross a previous kill of another player.
  if(event.kind==='elimination'&&event.target){const target=event.target.normalize('NFKC').toLocaleUpperCase();const knock=result.slice().reverse().find(e=>e.kind==='knock'&&e.target?.normalize('NFKC').toLocaleUpperCase()===target&&event.time-e.time<=120);if(knock?.processStart!==undefined&&knock.processStart>=floor){start=knock.processStart;basis=knock.processStartBasis;}}
  const previous=result.slice().reverse().find(e=>e.time<event.time&&(!event.target||!e.target||e.target.normalize('NFKC').toLocaleUpperCase()!==event.target.normalize('NFKC').toLocaleUpperCase()));
  if(start===undefined){
   const nearby=signals.filter(s=>s.time>=floor&&s.time<=event.time&&(!previous||s.time>previous.time));
   // Kill confirmation can arrive after firing stopped. Prefer a real recent
   // burst over a later damage tick (for example, a downed player's bleed-out).
   const shots=nearby.filter(s=>s.kind==='shoot'),lastShot=shots.at(-1);
   if(lastShot&&event.time-lastShot.time<=12){
    let index=shots.length-1;while(index>0&&shots[index].time-shots[index-1].time<=3)index--;
    start=shots[index].time;basis='shoot';
   }else{
    const hits=nearby.filter(s=>s.kind==='hit'),lastHit=hits.at(-1);
    if(lastHit&&event.time-lastHit.time<=3){let index=hits.length-1;while(index>0&&hits[index].time-hits[index-1].time<=3)index--;start=hits[index].time;basis='hit';}
   }
  }
  if(start===undefined){const candidate=candidates.filter(c=>c.start<=event.time&&c.end>=event.time&&Number.isFinite(c.first_signal)&&c.first_signal!>=floor&&c.first_signal!<=event.time&&event.time-c.first_signal!<=3&&(!previous||c.first_signal!>previous.time)).sort((a,b)=>b.first_signal!-a.first_signal!)[0];if(candidate){start=candidate.first_signal!;basis='candidate';}}
  // Incomplete old timelines cannot establish the firing onset. Be explicit in the UI.
  if(start===undefined){start=event.time-1;basis='near_result';}
  result.push({...event,processStart:Math.max(floor,Math.min(event.time,start)),processStartBasis:basis});
 }
 return result;
}
