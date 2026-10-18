import {Fragment,useCallback,useEffect,useId,useLayoutEffect,useRef,useState,type KeyboardEvent,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {Check,ChevronDown} from 'lucide-react';
import {useMotionPresence} from './surfaceMotion';

export interface SelectChoice<T extends string=string>{value:T;label:string;disabled?:boolean;group?:string;icon?:ReactNode;meta?:string}
interface Props<T extends string>{value:T;onChange:(value:T)=>void;options:readonly SelectChoice<T>[];label:string;disabled?:boolean;className?:string;menuClassName?:string;renderGroup?:(group:string)=>ReactNode}

export default function StyledSelect<T extends string>({value,onChange,options,label,disabled=false,className='',menuClassName='',renderGroup}:Props<T>){
 const [open,setOpen]=useState(false),[active,setActive]=useState(0),[position,setPosition]=useState({left:0,top:0,width:166,maxHeight:300});
 const trigger=useRef<HTMLButtonElement>(null),menu=useRef<HTMLDivElement>(null),search=useRef({text:'',time:0}),id=useId();
 const present=useMotionPresence(open,menu);
 const selected=options.findIndex(option=>option.value===value),selectedLabel=options[selected]?.label||'请选择';
 const close=useCallback((focus=false)=>{setOpen(false);search.current.text='';if(focus)trigger.current?.focus();},[]);
 const place=useCallback(()=>{
  if(!trigger.current)return;
  const rect=trigger.current.getBoundingClientRect(),availableBelow=innerHeight-rect.bottom-14,availableAbove=rect.top-14;
  const desired=Math.min(320,options.length*40+new Set(options.map(option=>option.group).filter(Boolean)).size*(renderGroup?48:28)+10),above=availableBelow<Math.min(desired,160)&&availableAbove>availableBelow;
  const maxHeight=Math.max(40,Math.min(desired,above?availableAbove:availableBelow)),width=Math.min(Math.max(rect.width,166),innerWidth-16);
  setPosition({left:Math.max(8,Math.min(rect.left,innerWidth-width-8)),top:above?Math.max(8,rect.top-maxHeight-6):rect.bottom+6,width,maxHeight});
 },[options.length,renderGroup]);
 function show(index=selected){setActive(index>=0&&!options[index]?.disabled?index:Math.max(0,options.findIndex(option=>!option.disabled)));search.current.text='';setOpen(true);}
 function move(direction:number){setActive(index=>{for(let step=1;step<=options.length;step++){const next=(index+direction*step+options.length)%options.length;if(!options[next].disabled)return next;}return index;});}
 function keyDown(event:KeyboardEvent){
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);}
  else if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();if(open)move(event.key==='ArrowDown'?1:-1);else show();}
  else if(event.key==='Home'||event.key==='End'){event.preventDefault();const indexes=options.map((_,index)=>index);if(event.key==='End')indexes.reverse();const next=indexes.find(index=>!options[index].disabled);if(next!==undefined){setActive(next);if(!open)show(next);}}
  else if(event.key==='Tab'&&open)close(true);
  else if(event.key.length===1&&event.key!==' '&&!event.ctrlKey&&!event.altKey&&!event.metaKey){
   const now=Date.now();search.current.text=(now-search.current.time<650?search.current.text:'')+event.key.toLocaleLowerCase();search.current.time=now;
   const next=options.findIndex(option=>!option.disabled&&option.label.toLocaleLowerCase().startsWith(search.current.text));
   if(next>=0){event.preventDefault();if(open)setActive(next);else show(next);}
  }
 }
 useLayoutEffect(()=>{if(open)place();},[open,place]);
 useEffect(()=>{
  if(!open)return;
  const option=menu.current?.querySelectorAll<HTMLButtonElement>('[role=option]')[active];option?.focus({preventScroll:true});
  const list=menu.current;if(list&&option){if(option.offsetTop<list.scrollTop)list.scrollTop=option.offsetTop;else if(option.offsetTop+option.offsetHeight>list.scrollTop+list.clientHeight)list.scrollTop=option.offsetTop+option.offsetHeight-list.clientHeight;}
 },[open,active]);
 useEffect(()=>{if(disabled)close();},[disabled,close]);
 useEffect(()=>{
  if(!open)return;
  const outside=(event:PointerEvent)=>{if(!menu.current?.contains(event.target as Node)&&!trigger.current?.contains(event.target as Node))close();};
  const scroll=(event:Event)=>{if(!menu.current?.contains(event.target as Node))place();};
  document.addEventListener('pointerdown',outside);document.addEventListener('scroll',scroll,true);window.addEventListener('resize',place);
  return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('scroll',scroll,true);window.removeEventListener('resize',place);};
 },[open,close,place]);
 return <><button type="button" ref={trigger} data-fixed-ink className={`styled-select ${className}`} role="combobox" aria-label={label} aria-haspopup="listbox" aria-expanded={open} aria-controls={open?id:undefined} disabled={disabled||!options.length} onKeyDown={keyDown} onClick={()=>open?close():show()}><span className="styled-select-value">{options[selected]?.icon&&<span className="styled-select-choice-icon">{options[selected].icon}</span>}<span className="styled-select-label">{selectedLabel}</span>{options[selected]?.meta&&<small className="styled-select-meta">{options[selected].meta}</small>}</span><ChevronDown size={15} aria-hidden="true"/></button>{present&&createPortal(<div ref={menu} id={id} data-motion-surface aria-hidden={!open} inert={!open} className={`styled-select-menu ${menuClassName}`} role="listbox" aria-label={label} style={position} onKeyDown={keyDown}>{options.map((option,index)=><Fragment key={option.value}>{option.group&&option.group!==options[index-1]?.group&&<div className="styled-select-group" role="presentation">{renderGroup?renderGroup(option.group):option.group}</div>}<button type="button" data-fixed-ink role="option" aria-selected={value===option.value} aria-disabled={option.disabled||undefined} disabled={option.disabled} tabIndex={active===index?0:-1} onClick={()=>{onChange(option.value);close(true);}}><span className="styled-select-option-content">{option.icon&&<span className="styled-select-choice-icon">{option.icon}</span>}<span className="styled-select-label">{option.label}</span></span>{option.meta&&<small className="styled-select-meta">{option.meta}</small>}{value===option.value&&<Check size={15} aria-hidden="true"/>}</button></Fragment>)}</div>,document.body)}</>;
}
