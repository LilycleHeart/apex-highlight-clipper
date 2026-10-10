import {useId,useState,useRef,useLayoutEffect} from 'react';
import {createPortal} from 'react-dom';
import {Info} from 'lucide-react';
export default function InfoTip({text,label='说明'}:{text:string;label?:string}){
 const id=useId(),button=useRef<HTMLButtonElement>(null),[hover,setHover]=useState(false),[focus,setFocus]=useState(false),[pinned,setPinned]=useState(false),[box,setBox]=useState({left:0,top:0});const open=hover||focus||pinned;
 useLayoutEffect(()=>{if(!open||!button.current)return;const r=button.current.getBoundingClientRect();setBox({left:Math.min(Math.max(8,r.left-120),innerWidth-288),top:Math.max(8,Math.min(r.bottom+8,innerHeight-140))});},[open]);
 return <><button ref={button} className="info-tip-button" type="button" aria-label={label} aria-describedby={open?id:undefined} onPointerEnter={()=>setHover(true)} onPointerLeave={()=>setHover(false)} onFocus={()=>setFocus(true)} onBlur={()=>{setFocus(false);setPinned(false);}} onClick={()=>setPinned(!pinned)} onKeyDown={e=>{if(e.key==='Escape'){e.stopPropagation();setHover(false);setFocus(false);setPinned(false);}}}><Info size={16}/></button>{open&&createPortal(<div id={id} role="tooltip" className="info-tip" style={box}>{text}</div>,document.fullscreenElement||document.body)}</>;
}
