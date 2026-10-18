import {useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {useMotionPresence} from './surfaceMotion';
import {ApexIcon,weaponFor} from './ClipDetails';
import {eventIcon,eventLabel,type ClipEvent} from './eventTimeline';

export function preciseClock(seconds:number){const n=Math.round(Math.max(0,seconds)*100),s=Math.floor(n/100),m=Math.floor(s/60),h=Math.floor(m/60);return(h?String(h).padStart(2,'0')+':':'')+String(m%60).padStart(2,'0')+':'+String(s%60).padStart(2,'0')+'.'+String(n%100).padStart(2,'0');}

function EventInformation({event}:{event:ClipEvent}){
 const weapon=event.weapon?weaponFor(event.weapon):null,contextWeapon=event.weaponContext?weaponFor(event.weaponContext.weapon):null;
 return <><span className="event-hover-title"><ApexIcon file={'stats/'+eventIcon(event.kind)+'.svg'}/><b>{eventLabel(event.kind)}</b><time>{preciseClock(event.clipTime)}</time></span>
  {(event.target||event.weapon||event.weaponContext)&&<span className="event-hover-fields">{event.target&&<span>目标 <b>{event.target}</b></span>}{event.weapon&&<span>武器 <b>{weapon&&<ApexIcon className="weapon-icon" file={weapon.file}/>} {event.weapon}</b></span>}{event.weaponContext&&<span><b>{contextWeapon&&<ApexIcon className="weapon-icon" file={contextWeapon.file}/>} {event.weaponContext.label}</b></span>}</span>}
  <span className="event-hover-hint">回看起点 {preciseClock(event.seekTime)}</span>
 </>;
}

export default function EventMarker({events,fraction,onSeek}:{events:ClipEvent[];fraction:number;onSeek:(event:ClipEvent)=>void}){
 const id=useId(),anchor=useRef<HTMLButtonElement>(null),popup=useRef<HTMLDivElement>(null),closeTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
 const [open,setOpen]=useState(false),[position,setPosition]=useState({left:0,top:0});
 const present=useMotionPresence(open,popup);
 const multiple=events.length>1;
 const clearClose=()=>{if(closeTimer.current!==null){clearTimeout(closeTimer.current);closeTimer.current=null;}};
 const show=()=>{clearClose();setOpen(true);};
 const containsFocus=()=>{const active=document.activeElement;return active instanceof HTMLElement&&active.matches(':focus-visible')&&(anchor.current===active||!!popup.current?.contains(active));};
 const scheduleClose=()=>{clearClose();closeTimer.current=setTimeout(()=>{if(!containsFocus())setOpen(false);},130);};
 useEffect(()=>()=>clearClose(),[]);
 useLayoutEffect(()=>{
  if(!open)return;
  const place=()=>{if(!anchor.current||!popup.current)return;const r=anchor.current.getBoundingClientRect(),p=popup.current.getBoundingClientRect();setPosition({left:Math.max(8,Math.min(innerWidth-p.width-8,r.left+r.width/2-p.width/2)),top:r.top>=p.height+16?r.top-p.height-8:Math.max(8,Math.min(innerHeight-p.height-8,r.bottom+8))});};
  place();window.addEventListener('resize',place);window.addEventListener('scroll',place,true);
  return()=>{window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);};
 },[open,events]);
 function dismiss(){clearClose();setOpen(false);}
 return <div className="event-marker-slot" style={{left:`clamp(42px, ${fraction*100}%, calc(100% - 42px))`}}>
  <button ref={anchor} type="button" data-fixed-ink className="event-marker" data-hovered={open} aria-label={'回看 '+eventLabel(events[0].kind)+' 从 '+preciseClock(events[0].seekTime)+'，结果 '+preciseClock(events[0].clipTime)+(multiple?'，附近还有 '+(events.length-1)+' 个事件':'')} aria-describedby={open?id:undefined} aria-expanded={multiple?open:undefined} aria-controls={multiple&&open?id:undefined} onPointerEnter={show} onPointerLeave={scheduleClose} onFocus={show} onBlur={scheduleClose} onClick={()=>onSeek(events[0])} onKeyDown={e=>{if(e.key==='Escape'){e.stopPropagation();dismiss();}else if(multiple&&e.key==='ArrowDown'){e.preventDefault();show();requestAnimationFrame(()=>popup.current?.querySelector<HTMLButtonElement>('button')?.focus());}}}>
   <ApexIcon file={'stats/'+eventIcon(events[0].kind)+'.svg'}/><span>{multiple?'事件 '+events.length:eventLabel(events[0].kind)}</span>
  </button>
  {present&&createPortal(<div ref={popup} id={id} data-motion-surface aria-hidden={!open} inert={!open} className="event-hover-popover" role={multiple?'group':'tooltip'} aria-label={multiple?'附近的 HUD 事件':undefined} style={position} onPointerEnter={show} onPointerLeave={scheduleClose} onFocus={show} onBlur={scheduleClose} onKeyDown={e=>{if(e.key==='Escape'){e.stopPropagation();anchor.current?.focus();dismiss();}}}>
   {multiple?<><div className="event-hover-heading">{events.length} 个事件 · 点击回看</div><div className="event-hover-list">{events.map(event=><button type="button" key={event.id} className="event-hover-item" aria-label={'回看 '+eventLabel(event.kind)+' 从 '+preciseClock(event.seekTime)+'，结果 '+preciseClock(event.clipTime)} onClick={()=>onSeek(event)}><EventInformation event={event}/></button>)}</div></>:<div className="event-hover-single"><EventInformation event={events[0]}/><span className="event-hover-hint">点击回看交战过程</span></div>}
  </div>,document.fullscreenElement||document.body)}
 </div>;
}
