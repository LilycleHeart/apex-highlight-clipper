import {useEffect,useId,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import type {Stage,MascotStyle} from './shared';
import {actionForStage,frameAt,visibilityLayers,VisibilityMotion,CYCLE_MS,FRAME_DURATIONS,puppetTurnState,actionPosition,hopState} from './blancaState';
import {getBlancaSprite} from './blancaSprites';

declare global {interface Window {fluidPreview?:{sample(stage:Stage,seconds:number):void;transition(stage:Stage,seconds:number):void;release():void;metrics():{frames:number;meanMs:number;maxMs:number}};blancaPreview?:{visibility():{value:number;target:number;image:number;outline:number}}}}
type Sprite={style:MascotStyle;stage:Stage;frame:number;walk?:'left'|'right'};
const staticStages=['idle','cache','importing','stopped','error','unknown'];
export default function Mascot({stage,demo=false,style='flat',enabled=true,ready=true,fps=30}:{stage:Stage;demo?:boolean;style?:MascotStyle;enabled?:boolean;ready?:boolean;fps?:number}){
 const [carrier]=useState(()=>{const node=document.createElement('div');node.className='blanca-page-anchor';return node;});
 const root=useRef<HTMLDivElement>(null),puppet=useRef<HTMLDivElement>(null),journey=useRef<HTMLDivElement>(null),first=useRef<HTMLImageElement>(null),second=useRef<HTMLImageElement>(null),outline=useRef<HTMLDivElement>(null),outlineShape=useRef<HTMLDivElement>(null),outlineFilter=useId();
 const live=useRef({stage,demo,style,enabled,ready,fps});live.current={stage,demo,style,enabled,ready,fps};
 const stamp=useRef({stage,started:performance.now()});if(stamp.current.stage!==stage){if(actionForStage(stamp.current.stage)!==actionForStage(stage)||staticStages.includes(stage)||staticStages.includes(stamp.current.stage))stamp.current.started=performance.now();stamp.current.stage=stage;}
 const wake=useRef<()=>void>(()=>{});useEffect(()=>wake.current(),[stage,demo,style,enabled,ready,fps]);
 useEffect(()=>{
  let raf=0,timer:ReturnType<typeof setTimeout>|null=null,closed=false,initialized=false,lastEnabled=live.current.enabled,lastRender:number|null=null,layoutUntil=0;
  let motion=new VisibilityMotion(lastEnabled),selected=0,active:Sprite|null=null,pending='',forced:{stage:Stage;seconds:number;still:boolean}|null=null;
  let turn:{slot:number;sprite:Sprite;started:number;committed:boolean}|null=null;
  let blend:{started:number}|null=null;
  let x=actionPosition(actionForStage(live.current.stage)),y=0,lastAction=actionForStage(live.current.stage);
  let travel:{from:number;fromY:number;to:number;direction:'left'|'right';started:number|null}|null=null;
  let frames=0,totalMs=0,maxMs=0,lastStage=live.current.stage;
  const hidden=()=>document.hidden||document.documentElement.dataset.hidden==='true';
  const reduced=()=>document.documentElement.dataset.reduced==='true'||matchMedia('(prefers-reduced-motion: reduce)').matches;
  const images=[first.current!,second.current!];
  const identity=(s:Sprite)=>s.walk?`walk-${s.walk}`:actionForStage(s.stage);
  const key=(s:Sprite)=>`${identity(s)}/${s.walk?0:s.frame}`;
  function paintLayers(now:number){
   const layers=visibilityLayers(motion.value(now)),t=blend?Math.min(1,Math.max(0,(now-blend.started)/180)):1,q=t*t*(3-2*t);
   images[selected].style.opacity=String(layers.image*q);images[1-selected].style.opacity=String(blend?layers.image*(1-q):0);
   if(t===1)blend=null;
   if(outline.current)outline.current.style.opacity=String(layers.outline);
  }
  function commitSprite(sprite:Sprite,slot:number,fade=false){
   if(active?.walk&&!sprite.walk&&!forced?.still)stamp.current.started=performance.now();
   blend=fade&&active&&selected!==slot?{started:performance.now()}:null;
   selected=slot;active=sprite;const url=images[slot].src;
   paintLayers(performance.now());
   if(outlineShape.current){const style=outlineShape.current.style;style.maskImage=`url("${url}")`;style.webkitMaskImage=`url("${url}")`;style.maskSize='contain';style.maskPosition='center';}
   if(outline.current){outline.current.dataset.sheet='true';outline.current.style.filter=`url(#${outlineFilter})`;}
   if(travel&&sprite.walk===travel.direction&&travel.started===null)travel.started=performance.now();
   if(root.current){root.current.dataset.style='playful';root.current.dataset.action=identity(sprite);root.current.dataset.frame=String(sprite.walk?1:sprite.frame+1);delete root.current.dataset.assetError;}
  }
  function requestSprite(sprite:Sprite,immediate=false){
   const id=key(sprite);if(immediate)turn=null;if(turn||blend||(active&&key(active)===id)||pending===id)return;
   pending=id;const slot=active?1-selected:0,image=images[slot];
   void getBlancaSprite(sprite.walk?`walk-${sprite.walk}`:actionForStage(sprite.stage),sprite.frame).then(url=>{
    if(closed||pending!==id)return;
    image.onload=()=>{if(closed||pending!==id)return;pending='';if(!active||reduced()||!motion.destination||forced?.still)commitSprite(sprite,slot);else if(immediate||identity(active)===identity(sprite))commitSprite(sprite,slot,true);else turn={slot,sprite,started:performance.now(),committed:false};schedule();};
    image.onerror=()=>{if(pending===id){pending='';if(root.current)root.current.dataset.assetError='true';}};
    if(image.src===url&&image.complete&&image.naturalWidth>0)image.onload?.(new Event('load'));else image.src=url;
   },()=>{if(pending===id){pending='';if(root.current)root.current.dataset.assetError='true';}});
  }
  function schedule(){if(closed)return;if(timer){clearTimeout(timer);timer=null;}if(hidden()){if(raf)cancelAnimationFrame(raf);raf=0;return;}if(!raf)raf=requestAnimationFrame(render);}
  function placeInPage(){const slot=document.querySelector<HTMLElement>('.mascot-slot:not(.theme-slot)');if(slot&&carrier.parentElement!==slot){slot.appendChild(carrier);schedule();}}
  function render(now:number){
   raf=0;if(closed||hidden())return;
   const interval=1000/live.current.fps;
   if(lastRender!==null&&now-lastRender<interval-.25){raf=requestAnimationFrame(render);return;}
   // Retain the fractional remainder so e.g. 60 FPS does not drift to 30 when
   // display callbacks land just before the interval boundary.
   lastRender=lastRender===null?now:lastRender+Math.max(1,Math.floor((now-lastRender+.25)/interval))*interval;
   const began=performance.now(),p=live.current,node=root.current;if(!node)return;
   if(!p.ready){node.style.visibility='hidden';return;}if(p.stage!==lastStage){if(forced&&forced.stage!==p.stage)forced=null;lastStage=p.stage;layoutUntil=now+650;}
   if(!initialized){initialized=true;lastEnabled=p.enabled;motion=new VisibilityMotion(p.enabled);layoutUntil=now+650;}
   const targetStage=forced&&p.demo?forced.stage:p.stage,elapsed=forced&&p.demo?forced.seconds*1000:now-stamp.current.started,targetAction=actionForStage(targetStage),targetX=actionPosition(targetAction);
   const sprite:Sprite={style:p.style,stage:targetStage,frame:frameAt(targetStage,elapsed,reduced())};
   if(p.enabled!==lastEnabled){
    if(p.enabled&&motion.value(now)<.001){x=targetX;y=0;travel=null;lastAction=targetAction;requestSprite(sprite,true);}
    motion.set(p.enabled,now,reduced()?400:p.enabled?1511:1644);lastEnabled=p.enabled;
   }
   if(!active||reduced()||forced?.still){x=targetX;y=0;travel=null;lastAction=targetAction;requestSprite(sprite,!!forced?.still||reduced());}
   else if(targetAction!==lastAction){
    lastAction=targetAction;
    if(p.enabled&&!travel){const to=x<=0?12:-12;travel={from:x,fromY:y,to,direction:to<x?'left':'right',started:null};}
   }
   let scaleX=1,scaleY=1;
   if(travel){
    const walking:Sprite={...sprite,frame:0,walk:travel.direction};requestSprite(walking,!turn);
    if(travel.started===null&&active?.walk===travel.direction&&!turn)travel.started=now;
    if(travel.started!==null){const state=hopState(now-travel.started,travel.from,travel.to,travel.fromY);x=state.x;y=state.y;scaleX=state.scaleX;scaleY=state.scaleY;if(state.done){travel=null;requestSprite(sprite);}}
   }else if(!active||motion.settled(now)&&motion.destination===1)requestSprite(sprite);
   let angle=0;if(turn){const state=reduced()?{angle:0,swap:true,done:true}:puppetTurnState(now-turn.started);angle=state.angle;if(state.swap&&!turn.committed){angle=reduced()?0:-90;commitSprite(turn.sprite,turn.slot);turn.committed=true;}if(state.done)turn=null;}
   if(journey.current)journey.current.style.transform=`translate(${x}%,${y}%) scale(${scaleX},${scaleY})`;
   if(puppet.current)puppet.current.style.transform=`rotateY(${angle}deg)`;
   node.dataset.turnAngle=String(angle);node.dataset.turning=String(!!turn);node.dataset.moving=String(!!travel);node.dataset.positionX=String(x);node.dataset.positionY=String(y);node.dataset.targetAction=targetAction;
   const value=motion.value(now),layers=visibilityLayers(value);
   if(reduced())blend=null;paintLayers(now);node.dataset.blending=String(!!blend);
   node.style.visibility=value<.0001&&motion.destination===0?'hidden':'visible';node.style.opacity='1';node.dataset.stage=targetStage;node.dataset.visibility=String(value);node.dataset.imageOpacity=String(layers.image);node.dataset.outlineOpacity=String(layers.outline);node.dataset.sampleSeconds=forced&&p.demo?String(forced.seconds):'';
   const duration=performance.now()-began;frames++;totalMs+=duration;maxMs=Math.max(maxMs,duration);
   if(!motion.settled(now)||turn||travel||blend||!reduced()&&now<layoutUntil){raf=requestAnimationFrame(render);return;}
   const once=p.stage==='completed'||p.stage==='stopping';
   if(p.enabled&&!reduced()&&!forced&&!staticStages.includes(p.stage)&&(!once||elapsed<CYCLE_MS)){
    const time=once?elapsed:((elapsed%CYCLE_MS)+CYCLE_MS)%CYCLE_MS;let edge=0;for(const length of FRAME_DURATIONS){edge+=length;if(edge>time+1)break;}
    timer=setTimeout(schedule,Math.max(20,edge-time+5));
   }
  }
  wake.current=()=>{layoutUntil=performance.now()+650;schedule();};
  window.fluidPreview={sample(s,t){if(live.current.demo){forced={stage:s,seconds:t,still:true};travel=null;x=actionPosition(actionForStage(s));y=0;lastAction=actionForStage(s);requestSprite({style:live.current.style,stage:s,frame:frameAt(s,t*1000,reduced())},true);schedule();}},transition(s,t){if(live.current.demo){forced={stage:s,seconds:t,still:false};schedule();}},release(){forced=null;schedule();},metrics(){return{frames,meanMs:frames?totalMs/frames:0,maxMs};}};
  window.blancaPreview={visibility(){const value=motion.value(performance.now());return{value,target:motion.destination,...visibilityLayers(value)};}};
  const visibility=()=>schedule();document.addEventListener('visibilitychange',visibility);
  const observer=new MutationObserver(()=>{layoutUntil=performance.now()+200;schedule();});observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-reduced','data-theme','data-hidden']});
  const placement=new MutationObserver(placeInPage);const app=document.querySelector('.app');if(app)placement.observe(app,{childList:true,subtree:true});placeInPage();
  const layout=new ResizeObserver(()=>{layoutUntil=performance.now()+650;schedule();});const main=document.querySelector('main');if(main)layout.observe(main);
  const resize=()=>{layoutUntil=performance.now()+650;schedule();};window.addEventListener('resize',resize);schedule();
  return()=>{closed=true;if(raf)cancelAnimationFrame(raf);if(timer)clearTimeout(timer);observer.disconnect();placement.disconnect();layout.disconnect();carrier.remove();images.forEach(i=>{i.onload=null;i.onerror=null;});document.removeEventListener('visibilitychange',visibility);window.removeEventListener('resize',resize);delete window.fluidPreview;delete window.blancaPreview;};
 },[]);
 return createPortal(<div ref={root} className="mascot fluid-mascot blanca-mascot" data-stage="idle" aria-hidden="true"><svg width="0" height="0" className="blanca-effects"><defs><filter id={outlineFilter}><feMorphology in="SourceAlpha" operator="erode" radius="1.5" result="inner"/><feComposite in="SourceGraphic" in2="inner" operator="out"/></filter></defs></svg><div ref={journey} className="blanca-journey"><div ref={puppet} className="blanca-puppet"><div className="blanca-frame"><img ref={first} className="blanca-layer blanca-sprite" alt=""/><img ref={second} className="blanca-layer blanca-sprite" alt=""/><div ref={outline} className="blanca-outline"><div ref={outlineShape} className="blanca-outline-shape"/></div></div></div></div></div>,carrier);
}
