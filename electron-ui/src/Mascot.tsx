import {useEffect,useRef} from 'react';
import type {Stage} from './shared';
import {poseAt,staticPose,blendPose,Pose} from './kaomojiGeometry';
import KaomojiArt,{artAttributes} from './KaomojiArt';
declare global {interface Window {fluidPreview?:{sample(stage:Stage,seconds:number):void;transition(stage:Stage,seconds:number):void;release():void;metrics():{frames:number;meanMs:number;maxMs:number}}}}
/** 持久组件；只在局部 SVG 内绘制，同一几何状态贯穿布局与阶段。 */
export default function Mascot({stage,demo=false}:{stage:Stage;demo?:boolean}){
 const container=useRef<HTMLDivElement>(null),svg=useRef<SVGSVGElement>(null);
 const liveStage=useRef(stage),liveDemo=useRef(demo);liveStage.current=stage;liveDemo.current=demo;
 const stageStamp=useRef({stage,started:performance.now()});if(stageStamp.current.stage!==stage)stageStamp.current={stage,started:performance.now()};
 const wake=useRef<()=>void>(()=>{});useEffect(()=>wake.current(),[stage,demo]);
 useEffect(()=>{
  let frame=0,lastDraw=0,lastLayout=0,stageStart=performance.now(),transitionStart=stageStart;
  let previousStage=liveStage.current,current:Pose=poseAt(previousStage,0),from=current;
  let forced:{stage:Stage;seconds:number;transition:boolean}|null=null;let frames=0,totalMs=0,maxMs=0,lastGeometry='';
  const reduced=()=>document.documentElement.dataset.reduced==='true'||matchMedia('(prefers-reduced-motion: reduce)').matches;
  const hidden=()=>document.hidden||document.documentElement.dataset.hidden==='true';
  const parts=new Map<string,SVGElement>();svg.current?.querySelectorAll<SVGElement>('[data-art]').forEach(node=>parts.set(node.dataset.art!,node));
  function draw(pose:Pose){const started=performance.now();for(const [part,attrs] of Object.entries(artAttributes(pose))){const node=parts.get(part);if(node)for(const [key,value] of Object.entries(attrs))if(node.getAttribute(key)!==value)node.setAttribute(key,value);}const ms=performance.now()-started;frames++;totalMs+=ms;maxMs=Math.max(maxMs,ms);}
  function render(now:number){
   if(hidden()){frame=0;return;}const reduce=reduced();frame=requestAnimationFrame(render);if(now-lastDraw<1000/30)return;lastDraw=now;
   const next=liveStage.current;if(next!==previousStage){from=current;previousStage=next;stageStart=stageStamp.current.started;transitionStart=stageStart;forced=null;}
   if(now-lastLayout>100){lastLayout=now;const slot=document.querySelector<HTMLElement>('.mascot-slot:not(.theme-slot)');if(slot&&container.current){const box=slot.getBoundingClientRect();const node=container.current;node.style.width=box.width+'px';node.style.height=box.height+'px';node.style.transform=`translate(${box.left}px,${box.top}px)`;node.style.opacity='1';}}
   const elapsed=(now-stageStart)/1000,duration=next==='completed'?1000:next==='stopping'?900:550;
   const target=reduced()?staticPose(next):poseAt(next,elapsed);const mix=reduced()?1:Math.min(1,(now-transitionStart)/duration);
   current=reduce?target:blendPose(from,target,mix,now-transitionStart);
   if(forced&&liveDemo.current){if(forced.transition){const q=Math.min(1,forced.seconds/(duration/1000));current=blendPose(from,poseAt(forced.stage,forced.seconds),q,forced.seconds*1000);}else current=poseAt(forced.stage,forced.seconds);}else if(forced)forced=null;
   const signature=forced&&liveDemo.current?`${forced.stage}:${forced.seconds}:${forced.transition}`:reduce?`${next}:static`:'';
   if(!signature||signature!==lastGeometry){draw(current);lastGeometry=signature;}
   if(container.current){container.current.dataset.stage=next;container.current.dataset.sampleSeconds=forced&&liveDemo.current?String(forced.seconds):'';}
   if(reduce||forced&&liveDemo.current||['completed','stopping'].includes(next)&&elapsed>duration/1000){cancelAnimationFrame(frame);frame=0;}
  }
  const schedule=()=>{lastLayout=0;lastDraw=0;if(hidden()){cancelAnimationFrame(frame);frame=0;}else if(!frame)frame=requestAnimationFrame(render);};wake.current=schedule;
  window.fluidPreview={sample(s,t){if(liveDemo.current){forced={stage:s,seconds:t,transition:false};schedule();}},transition(s,t){if(liveDemo.current){forced={stage:s,seconds:t,transition:true};schedule();}},release(){forced=null;lastGeometry='';schedule();},metrics(){return{frames,meanMs:frames?totalMs/frames:0,maxMs};}};
  const visibility=()=>{if(document.hidden){if(frame)cancelAnimationFrame(frame);frame=0;}else{lastDraw=0;frame=requestAnimationFrame(render);}};document.addEventListener('visibilitychange',visibility);
  const observer=new MutationObserver(schedule);observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-reduced','data-theme','data-hidden']});const layoutObserver=new ResizeObserver(schedule);if(document.querySelector('main'))layoutObserver.observe(document.querySelector('main')!);window.addEventListener('resize',schedule);window.addEventListener('scroll',schedule,{passive:true});
  frame=requestAnimationFrame(render);return()=>{cancelAnimationFrame(frame);document.removeEventListener('visibilitychange',visibility);window.removeEventListener('resize',schedule);window.removeEventListener('scroll',schedule);observer.disconnect();layoutObserver.disconnect();delete window.fluidPreview;};
 },[]);
 return <div ref={container} className="mascot fluid-mascot" data-stage="idle" aria-hidden="true"><svg ref={svg} viewBox="0 0 200 160"><KaomojiArt pose={poseAt('idle',0)}/></svg></div>;
}
