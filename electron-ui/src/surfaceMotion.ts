import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {NAV,PRESS,sampleSpring} from './surfaceGeometry';
const hidden=()=>document.hidden||document.documentElement.dataset.hidden==='true';
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
  const down=(e:PointerEvent)=>{const el=(e.target as Element)?.closest<HTMLButtonElement>('button');if(el&&!el.disabled){active=el;retarget(el,1);}};
  const up=()=>{if(active)retarget(active,0);active=null;};
  const visibility=()=>{last=0;if(!hidden())schedule();};const observer=new MutationObserver(visibility);observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-hidden']});
  const keyDown=(e:KeyboardEvent)=>{if(!e.repeat&&(e.key===' '||e.key==='Enter')){const el=e.target as HTMLButtonElement;if(el.tagName==='BUTTON'&&!el.disabled){active=el;retarget(el,1);}}};const keyUp=(e:KeyboardEvent)=>{if(e.key===' '||e.key==='Enter')up();};document.addEventListener('keydown',keyDown);document.addEventListener('keyup',keyUp);
  document.addEventListener('pointerdown',down);document.addEventListener('pointerup',up);document.addEventListener('pointercancel',up);window.addEventListener('blur',up);document.addEventListener('visibilitychange',visibility);
  return()=>{cancelAnimationFrame(raf);observer.disconnect();document.removeEventListener('keydown',keyDown);document.removeEventListener('keyup',keyUp);for(const el of jobs.keys()){el.style.removeProperty('scale');el.style.removeProperty('translate');}document.removeEventListener('pointerdown',down);document.removeEventListener('pointerup',up);document.removeEventListener('pointercancel',up);window.removeEventListener('blur',up);document.removeEventListener('visibilitychange',visibility);};
 },[reduced]);
}
