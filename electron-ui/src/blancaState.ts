import type {MascotStyle,Stage} from './shared';
export type BlancaAction='scan'|'locate'|'detail'|'weapons'|'export'|'verify'|'save'|'completed';
export const FRAME_DURATIONS=[2600,2600,2600,4000] as const;
export const CYCLE_MS=11800;
export const PUPPET_TURN_MS=600;
export function actionForStage(stage:Stage):BlancaAction{
 if(stage==='bisect')return'locate';
 if(stage==='weapons'||stage==='rank')return'weapons';
 if(stage==='export')return'export';
 if(['audit','verify','combat_outcomes','statistics'].includes(stage))return'verify';
 if(['stopping','stopped','error'].includes(stage))return'save';
 if(stage==='completed')return'completed';
 if(['probe','fine','numeric','lifecycle','outcomes','unknown'].includes(stage))return'detail';
 return'scan';
}
export function frameAt(stage:Stage,elapsedMs:number,reduced=false){
 if(['idle','cache','importing','error','unknown'].includes(stage))return 0;
 if(stage==='stopped')return 3;
 if(reduced)return stage==='completed'||stage==='stopping'?3:1;
 const once=stage==='completed'||stage==='stopping';
 let time=once?Math.min(CYCLE_MS-1,Math.max(0,elapsedMs)):((elapsedMs%CYCLE_MS)+CYCLE_MS)%CYCLE_MS;
 for(let i=0;i<FRAME_DURATIONS.length;i++){if(time<FRAME_DURATIONS[i])return i;time-=FRAME_DURATIONS[i];}
 return 3;
}
export function assetUrl(style:MascotStyle,action:BlancaAction,frame:number,outline=false){return `./mascots/blanca/${style}/${action}-${String(frame+1).padStart(2,'0')}.${outline?'svg':'png'}`;}
export const clamp=(value:number)=>Math.max(0,Math.min(1,value));
const smooth=(value:number)=>{const v=clamp(value);return v*v*(3-2*v);};
export function puppetTurnState(elapsedMs:number,durationMs=PUPPET_TURN_MS){const t=clamp(elapsedMs/durationMs);return{angle:t>=1?0:t<.5?90*smooth(t*2):-90*(1-smooth((t-.5)*2)),swap:t>=.5,done:t>=1};}
export function visibilityLayers(value:number){return{image:smooth((value-.42)/.58),outline:smooth(value/.4)*smooth((1-value)/.25)};}
export class VisibilityMotion{
 private from:number;private target:number;private started=0;private duration=0;
 constructor(enabled:boolean){this.from=this.target=enabled?1:0;}
 value(now:number){const t=this.duration?clamp((now-this.started)/this.duration):1;return this.from+(this.target-this.from)*smooth(t);}
 set(enabled:boolean,now:number,durationMs:number){const next=enabled?1:0;if(next===this.target)return;this.from=this.value(now);this.target=next;this.started=now;this.duration=durationMs*Math.abs(next-this.from);}
 settled(now:number){return this.duration===0||now-this.started>=this.duration;}
 get destination(){return this.target;}
}
