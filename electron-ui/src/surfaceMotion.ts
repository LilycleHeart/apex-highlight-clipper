import {useEffect,useLayoutEffect,useRef,useState,type RefObject} from 'react';
import {NAV,PRESS,MENU_EASE,sampleSpring,bezierProgress} from './surfaceGeometry';
const hidden=()=>document.hidden||document.documentElement.dataset.hidden==='true';
// Keep small surfaces mounted through exit. Interruptions start from the current
// presentation; only disclosure height is measured, never card or text geometry.
export function useMotionPresence(open:boolean,node:RefObject<HTMLElement|null>,kind:'popover'|'disclosure'|'drawer'='popover',onComplete?:()=>void){
 const [retained,setRetained]=useState(open),present=open||retained,completion=useRef(onComplete),initial=useRef(true);completion.current=onComplete;
 useLayoutEffect(()=>{
  const first=initial.current;initial.current=false;const element=node.current;if(!present||!element)return;
  if(open)setRetained(true);
  const style=getComputedStyle(element),from:Keyframe={opacity:style.opacity},to:Keyframe={opacity:open?1:0};
  if(kind==='disclosure'){
   from.height=element.getBoundingClientRect().height+'px';
   to.height=open?(element.firstElementChild?.getBoundingClientRect().height||0)+'px':'0px';
  }else{const offset=kind==='drawer'?'calc(100% + 16px) 0':'0 -6px';from.translate=style.translate==='none'?offset:style.translate;to.translate=open?'0 0':offset;}
  let animation:Animation|null=null,finished=false;
  const finish=()=>{
   if(finished)return;finished=true;
   element.style.opacity=open?'1':'0';
   if(kind==='disclosure')element.style.height=open?'auto':'0px';else element.style.translate=open?'0 0':kind==='drawer'?'calc(100% + 16px) 0':'0 -6px';
   animation?.cancel();if(!open)setRetained(false);completion.current?.();
  };
  const media=matchMedia('(prefers-reduced-motion: reduce)'),reduced=()=>media.matches||document.documentElement.dataset.reduced==='true';
  // A live card morph measures its destination once; nested disclosures must
  // already have their final height rather than growing again after arrival.
  if(reduced()||document.documentElement.dataset.libraryPlayback||kind==='disclosure'&&first&&open)finish();else animation=element.animate([from,to],{duration:320,easing:`cubic-bezier(${MENU_EASE.join(',')})`,fill:'both'});
  if(animation)animation.onfinish=finish;
  const sync=()=>{if(finished)return;if(reduced())finish();else if(hidden())animation?.pause();else animation?.play();};
  const observer=new MutationObserver(sync);observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-hidden','data-reduced']});
  media.addEventListener('change',sync);document.addEventListener('visibilitychange',sync);sync();
  return()=>{
   observer.disconnect();media.removeEventListener('change',sync);document.removeEventListener('visibilitychange',sync);
   if(animation&&!finished){try{animation.commitStyles();}catch{/* Detached surface. */}animation.cancel();}
  };
 },[open,present,node,kind]);
 return present;
}
export function useTweenValue(target:number,reduced:boolean,curve:readonly number[],duration=.32,sample?:()=>number|undefined){
 const [value,setValue]=useState(target),live=useRef(target),sampler=useRef(sample);sampler.current=sample;
 useLayoutEffect(()=>{if(reduced){live.current=target;setValue(target);return;}let raf=0,last=0,elapsed=0,closed=false;const from=sampler.current?.()??live.current;live.current=from;setValue(from);if(Math.abs(from-target)<.001)return;
  function schedule(){if(!raf&&!hidden()&&!closed)raf=requestAnimationFrame(tick);}function tick(t:number){raf=0;if(hidden()){last=0;return;}if(last)elapsed+=Math.min(.04,(t-last)/1000);last=t;live.current=from+(target-from)*bezierProgress(elapsed/duration,curve);setValue(live.current);if(elapsed<duration)schedule();}
  const visibility=()=>{last=0;if(hidden()){cancelAnimationFrame(raf);raf=0;}else schedule();};const observer=new MutationObserver(visibility);observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-hidden']});document.addEventListener('visibilitychange',visibility);schedule();
  return()=>{closed=true;cancelAnimationFrame(raf);observer.disconnect();document.removeEventListener('visibilitychange',visibility);};
 },[target,reduced,curve,duration]);return value;
}
export function useSurfaceValue(target:number,reduced:boolean,parameters=NAV){
 const [value,setValue]=useState(target),live=useRef(target);
 useLayoutEffect(()=>{
  if(reduced){live.current=target;setValue(target);return;}
  let raf=0,last=0,elapsed=0,closed=false;const from=live.current;
  const schedule=()=>{if(!raf&&!hidden()&&!closed)raf=requestAnimationFrame(tick);};
  function tick(now:number){raf=0;if(hidden()){last=0;return;}if(last)elapsed+=Math.min(.04,(now-last)/1000);last=now;live.current=sampleSpring(from,target,elapsed,parameters);setValue(live.current);if(elapsed<parameters.duration)schedule();}
  const visibility=()=>{last=0;if(hidden()){cancelAnimationFrame(raf);raf=0;}else schedule();};
  const observer=new MutationObserver(visibility);observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-hidden']});document.addEventListener('visibilitychange',visibility);schedule();
  return()=>{closed=true;cancelAnimationFrame(raf);observer.disconnect();document.removeEventListener('visibilitychange',visibility);};
 },[target,reduced,parameters]);return value;
}
// 独立 CSS scale/translate 属性，不覆盖布局的 transform 或播放器定位。
export function useButtonPress(reduced:boolean){
 useEffect(()=>{
  const jobs=new Map<HTMLElement,{from:number;to:number;value:number;elapsed:number}>();let raf=0,last=0;
  const schedule=()=>{if(!raf&&!hidden())raf=requestAnimationFrame(tick);};
  function tick(t:number){raf=0;if(hidden()){last=0;return;}const dt=last?Math.min(.04,(t-last)/1000):0;last=t;for(const [el,j] of jobs){j.elapsed+=dt;j.value=sampleSpring(j.from,j.to,j.elapsed,PRESS);el.style.scale=String(1-.05*j.value);el.style.translate=`0 ${j.value}px`;if(j.elapsed>=PRESS.duration){if(j.to===0){el.style.removeProperty('scale');el.style.removeProperty('translate');jobs.delete(el);}}}if([...jobs.values()].some(j=>j.elapsed<PRESS.duration))schedule();else last=0;}
  const retarget=(el:HTMLElement,to:number)=>{const value=jobs.get(el)?.value??0;jobs.set(el,{from:value,to,value,elapsed:reduced?PRESS.duration:0});if(reduced){el.style.scale=String(1-.05*to);el.style.translate=`0 ${to}px`;}else schedule();};
  let active:HTMLElement|null=null;
  const down=(e:PointerEvent)=>{const el=(e.target as Element)?.closest<HTMLButtonElement>('button');if(el&&!el.disabled&&!el.hasAttribute('data-fixed-ink')){active=el;retarget(el,1);}};
  const up=()=>{if(active)retarget(active,0);active=null;};
  const visibility=()=>{last=0;if(!hidden())schedule();};const observer=new MutationObserver(visibility);observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-hidden']});
  const keyDown=(e:KeyboardEvent)=>{if(!e.repeat&&(e.key===' '||e.key==='Enter')){const el=e.target as HTMLButtonElement;if(el.tagName==='BUTTON'&&!el.disabled&&!el.hasAttribute('data-fixed-ink')){active=el;retarget(el,1);}}};const keyUp=(e:KeyboardEvent)=>{if(e.key===' '||e.key==='Enter')up();};document.addEventListener('keydown',keyDown);document.addEventListener('keyup',keyUp);
  document.addEventListener('pointerdown',down);document.addEventListener('pointerup',up);document.addEventListener('pointercancel',up);window.addEventListener('blur',up);document.addEventListener('visibilitychange',visibility);
  return()=>{cancelAnimationFrame(raf);observer.disconnect();document.removeEventListener('keydown',keyDown);document.removeEventListener('keyup',keyUp);for(const el of jobs.keys()){el.style.removeProperty('scale');el.style.removeProperty('translate');}document.removeEventListener('pointerdown',down);document.removeEventListener('pointerup',up);document.removeEventListener('pointercancel',up);window.removeEventListener('blur',up);document.removeEventListener('visibilitychange',visibility);};
 },[reduced]);
}
