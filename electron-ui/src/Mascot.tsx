import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import type {Stage,MascotStyle} from './shared';
import {actionForStage,assetUrl,frameAt,visibilityLayers,VisibilityMotion,CYCLE_MS,FRAME_DURATIONS,puppetTurnState} from './blancaState';

declare global {interface Window {fluidPreview?:{sample(stage:Stage,seconds:number):void;transition(stage:Stage,seconds:number):void;release():void;metrics():{frames:number;meanMs:number;maxMs:number}};blancaPreview?:{visibility():{value:number;target:number;image:number;outline:number}}}}
type Sprite={style:MascotStyle;stage:Stage;frame:number};
const staticStages=['idle','cache','importing','stopped','error','unknown'];
export default function Mascot({stage,demo=false,style='flat',enabled=true,ready=true}:{stage:Stage;demo?:boolean;style?:MascotStyle;enabled?:boolean;ready?:boolean}){
 const [carrier]=useState(()=>{const node=document.createElement('div');node.className='blanca-page-anchor';return node;});
 const root=useRef<HTMLDivElement>(null),puppet=useRef<HTMLDivElement>(null),first=useRef<HTMLImageElement>(null),second=useRef<HTMLImageElement>(null),outline=useRef<HTMLDivElement>(null);
 const live=useRef({stage,demo,style,enabled,ready});live.current={stage,demo,style,enabled,ready};
 const stamp=useRef({stage,started:performance.now()});if(stamp.current.stage!==stage){if(actionForStage(stamp.current.stage)!==actionForStage(stage)||staticStages.includes(stage)||staticStages.includes(stamp.current.stage))stamp.current.started=performance.now();stamp.current.stage=stage;}
 const wake=useRef<()=>void>(()=>{});useEffect(()=>wake.current(),[stage,demo,style,enabled,ready]);
 useEffect(()=>{
  let raf=0,timer:ReturnType<typeof setTimeout>|null=null,closed=false,initialized=false,lastEnabled=live.current.enabled,lastRender=0,layoutUntil=0;
  let motion=new VisibilityMotion(lastEnabled),selected=0,active:Sprite|null=null,pending='',forced:{stage:Stage;seconds:number}|null=null;
  let turn:{slot:number;sprite:Sprite;started:number;committed:boolean}|null=null;
  let frames=0,totalMs=0,maxMs=0,lastStage=live.current.stage;
  const hidden=()=>document.hidden||document.documentElement.dataset.hidden==='true';
  const reduced=()=>document.documentElement.dataset.reduced==='true'||matchMedia('(prefers-reduced-motion: reduce)').matches;
  const images=[first.current!,second.current!];
  const key=(s:Sprite)=>`${s.style}/${actionForStage(s.stage)}/${s.frame}`;
  function commitSprite(sprite:Sprite,slot:number){selected=slot;active=sprite;const url=assetUrl(sprite.style,actionForStage(sprite.stage),sprite.frame,true);if(outline.current){outline.current.style.maskImage=`url("${url}")`;outline.current.style.webkitMaskImage=`url("${url}")`;}if(root.current){root.current.dataset.style=sprite.style;root.current.dataset.action=actionForStage(sprite.stage);root.current.dataset.frame=String(sprite.frame+1);}}
  function requestSprite(sprite:Sprite){
   const id=key(sprite);if(turn||(active&&key(active)===id)||pending===id)return;
   pending=id;const slot=active?1-selected:0;const image=images[slot];
   image.onload=()=>{if(closed||pending!==id)return;pending='';if(!active||reduced()||!motion.destination)commitSprite(sprite,slot);else turn={slot,sprite,started:performance.now(),committed:false};
    schedule();};
   image.onerror=()=>{if(pending===id){pending='';if(root.current)root.current.dataset.assetError='true';}};
   image.src=assetUrl(sprite.style,actionForStage(sprite.stage),sprite.frame);
  }
  function schedule(){if(closed)return;if(timer){clearTimeout(timer);timer=null;}if(hidden()){if(raf)cancelAnimationFrame(raf);raf=0;return;}if(!raf)raf=requestAnimationFrame(render);}
  function placeInPage(){const slot=document.querySelector<HTMLElement>('.mascot-slot:not(.theme-slot)');if(slot&&carrier.parentElement!==slot){slot.appendChild(carrier);schedule();}}
  function render(now:number){
   raf=0;if(closed||hidden())return;
   if(now-lastRender<1000/30){raf=requestAnimationFrame(render);return;}lastRender=now;
   const began=performance.now(),p=live.current,node=root.current;if(!node)return;
   if(!p.ready){node.style.visibility='hidden';return;}if(p.stage!==lastStage){if(forced&&forced.stage!==p.stage)forced=null;lastStage=p.stage;layoutUntil=now+650;}
   if(!initialized){initialized=true;lastEnabled=p.enabled;motion=new VisibilityMotion(p.enabled);layoutUntil=now+650;}
   if(p.enabled!==lastEnabled){if(p.enabled&&motion.value(now)<.001)requestSprite({style:p.style,stage:p.stage,frame:frameAt(p.stage,now-stamp.current.started,reduced())});motion.set(p.enabled,now,reduced()?400:p.enabled?1511:1644);lastEnabled=p.enabled;}
   const targetStage=forced&&p.demo?forced.stage:p.stage,elapsed=forced&&p.demo?forced.seconds*1000:now-stamp.current.started;
   if(!active||motion.settled(now)&&motion.destination===1)requestSprite({style:p.style,stage:targetStage,frame:frameAt(targetStage,elapsed,reduced())});
   let angle=0;if(turn){const state=reduced()?{angle:0,swap:true,done:true}:puppetTurnState(now-turn.started);angle=state.angle;if(state.swap&&!turn.committed){commitSprite(turn.sprite,turn.slot);turn.committed=true;}if(state.done)turn=null;}
   if(puppet.current)puppet.current.style.transform=`rotateY(${angle}deg)`;node.dataset.turnAngle=String(angle);node.dataset.turning=String(!!turn);
   const value=motion.value(now),layers=visibilityLayers(value);
   images[selected].style.opacity=String(layers.image);images[1-selected].style.opacity='0';if(outline.current)outline.current.style.opacity=String(layers.outline);
   node.style.visibility=value<.0001&&motion.destination===0?'hidden':'visible';node.style.opacity='1';node.dataset.stage=p.stage;node.dataset.visibility=String(value);node.dataset.imageOpacity=String(layers.image);node.dataset.outlineOpacity=String(layers.outline);node.dataset.sampleSeconds=forced&&p.demo?String(forced.seconds):'';
   const duration=performance.now()-began;frames++;totalMs+=duration;maxMs=Math.max(maxMs,duration);
   if(!motion.settled(now)||turn||!reduced()&&now<layoutUntil){raf=requestAnimationFrame(render);return;}
   const once=p.stage==='completed'||p.stage==='stopping';
   if(p.enabled&&!reduced()&&!forced&&!staticStages.includes(p.stage)&&(!once||elapsed<CYCLE_MS)){
    const time=once?elapsed:((elapsed%CYCLE_MS)+CYCLE_MS)%CYCLE_MS;let edge=0;for(const length of FRAME_DURATIONS){edge+=length;if(edge>time+1)break;}
    timer=setTimeout(schedule,Math.max(20,edge-time+5));
   }
  }
  wake.current=()=>{layoutUntil=performance.now()+650;schedule();};
  window.fluidPreview={sample(s,t){if(live.current.demo){forced={stage:s,seconds:t};requestSprite({style:live.current.style,stage:s,frame:frameAt(s,t*1000,reduced())});schedule();}},transition(s,t){if(live.current.demo){forced={stage:s,seconds:t};schedule();}},release(){forced=null;schedule();},metrics(){return{frames,meanMs:frames?totalMs/frames:0,maxMs};}};
  window.blancaPreview={visibility(){const value=motion.value(performance.now());return{value,target:motion.destination,...visibilityLayers(value)};}};
  const visibility=()=>schedule();document.addEventListener('visibilitychange',visibility);
  const observer=new MutationObserver(()=>{layoutUntil=performance.now()+200;schedule();});observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-reduced','data-theme','data-hidden']});
  const placement=new MutationObserver(placeInPage);const app=document.querySelector('.app');if(app)placement.observe(app,{childList:true,subtree:true});placeInPage();
  const layout=new ResizeObserver(()=>{layoutUntil=performance.now()+650;schedule();});const main=document.querySelector('main');if(main)layout.observe(main);
  const resize=()=>{layoutUntil=performance.now()+650;schedule();};window.addEventListener('resize',resize);schedule();
  return()=>{closed=true;if(raf)cancelAnimationFrame(raf);if(timer)clearTimeout(timer);observer.disconnect();placement.disconnect();layout.disconnect();carrier.remove();images.forEach(i=>{i.onload=null;i.onerror=null;});document.removeEventListener('visibilitychange',visibility);window.removeEventListener('resize',resize);delete window.fluidPreview;delete window.blancaPreview;};
 },[]);
 return createPortal(<div ref={root} className="mascot fluid-mascot blanca-mascot" data-stage="idle" aria-hidden="true"><div ref={puppet} className="blanca-puppet"><img ref={first} className="blanca-layer" alt=""/><img ref={second} className="blanca-layer" alt=""/><div ref={outline} className="blanca-outline"/></div></div>,carrier);
}
