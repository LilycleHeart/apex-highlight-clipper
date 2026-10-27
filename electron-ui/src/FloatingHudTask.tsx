import {useEffect,useRef,useState} from 'react';
import {ChevronDown,LoaderCircle,Square,Trash2} from 'lucide-react';
import type {HudJob,HudProgress} from './useHudEnrichment';

const clock=(seconds:number)=>{
 const total=Math.max(0,Math.round(seconds)),minutes=Math.floor(total/60),rest=total%60;
 return minutes?`${minutes}分${String(rest).padStart(2,'0')}秒`:`${rest}秒`;
};
const WINDOW_MS=60000;

/** 识别任务的常态入口：一行悬浮条，点开才显示进度条和实时速率。 */
export default function FloatingHudTask({job,progress,onPause,onAbandon}:{job:HudJob|null;progress:HudProgress;onPause:()=>void;onAbandon:()=>void}){
 const [expanded,setExpanded]=useState(false),[now,setNow]=useState(Date.now());
 const samples=useRef<{time:number;completed:number}[]>([]);
 const current=useRef(progress.completed);
 current.current=progress.completed;
 useEffect(()=>{
  samples.current=[{time:Date.now(),completed:current.current}];
  const push=()=>{
   const time=Date.now();
   samples.current.push({time,completed:current.current});
   // 只保留最近一分钟，避免早期慢阶段把速率拖低
   while(samples.current.length>1&&time-samples.current[0].time>WINDOW_MS)samples.current.shift();
   setNow(time);
  };
  const timer=setInterval(push,1000);
  return()=>clearInterval(timer);
 },[]);
 const total=Math.max(0,progress.total),completed=Math.max(0,progress.completed);
 const fraction=total?Math.min(1,completed/total):0,percent=Math.floor(fraction*100);
 const remaining=Math.max(0,total-completed);
 const elapsed=job?.startedAt?Math.max(0,(now-job.startedAt)/1000):null;
 // 速率用最近一分钟的实际完成量；样本不足时退回整体平均
 const window=samples.current;
 const span=window.length>1?window[window.length-1].time-window[0].time:0;
 let speed:number|null=null;
 if(window.length>2&&span>=3000){
  const doneInWindow=window[window.length-1].completed-window[0].completed;
  if(doneInWindow>0)speed=doneInWindow/(span/1000);
 }
 if(speed===null&&elapsed&&elapsed>=5&&completed>0)speed=completed/elapsed;
 const eta=speed&&speed>0?remaining/speed:null;
 const label=job?.mode==='refresh'?'信息重新识别':'补充 HUD';
 return <section className="hud-task-float" data-expanded={expanded} aria-label="识别任务进度">
  <button type="button" className="hud-task-float-main" onClick={()=>setExpanded(value=>!value)} aria-expanded={expanded}>
   <LoaderCircle size={17} className="loading-spinner"/>
   <span>{label} · {completed} / {total} 项</span>
   <span className="hud-task-float-percent">{percent}%</span>
   {speed!==null&&<span className="hud-task-float-rate">{speed.toFixed(1)} 项/秒</span>}
   {elapsed!==null&&<span className="hud-task-float-time">已用 {clock(elapsed)}{eta!==null?` · 剩余 ${clock(eta)}`:''}</span>}
   <span className="hud-task-float-toggle">详细<ChevronDown size={13}/></span>
  </button>
  {expanded&&<div className="hud-task-float-detail">
   <progress aria-label="识别任务进度" max={Math.max(1,total)} value={completed}/>
   <div className="hud-task-float-meta">
    <span>{progress.message||'正在识别'}</span>
    <span>{completed} / {total} 项 · {percent}%</span>
   </div>
   <div className="hud-task-float-actions"><button type="button" className="secondary" onClick={onPause}><Square size={13}/>暂停保存</button><button type="button" className="secondary" onClick={onAbandon}><Trash2 size={13}/>放弃</button></div>
   <div className="hud-task-float-meta">
    <span>{speed!==null?`最近一分钟 ${speed.toFixed(1)} 项/秒`:'正在测速…'}</span>
    <span>{elapsed!==null?`已用 ${clock(elapsed)}`:'—'}{eta!==null?` · 剩余 ${clock(eta)}`:' · 剩余计算中'}</span>
   </div>
  </div>}
 </section>;
}
