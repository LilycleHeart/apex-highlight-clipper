import {useCallback,useEffect,useId,useLayoutEffect,useRef,useState,type CSSProperties,type KeyboardEvent} from 'react';
import {createPortal} from 'react-dom';
import {Check,ChevronDown,UsersRound,X} from 'lucide-react';
import {ApexIcon,apexAsset} from './ClipDetails';
import {legendFor,legendRoles} from './legendRoster';
import {useMotionPresence} from './surfaceMotion';

export interface AvailableHero {id:string;name:string;count:number}
export default function HeroPicker({value,onChange,heroes,hasUnknown}:{value:string;onChange:(value:string)=>void;heroes:AvailableHero[];hasUnknown:boolean}){
 const [open,setOpen]=useState(false),[position,setPosition]=useState({left:8,top:48,width:880,maxHeight:440});
 const trigger=useRef<HTMLButtonElement>(null),panel=useRef<HTMLDivElement>(null),id=useId(),present=useMotionPresence(open,panel);
 const selected=legendFor(value)||heroes.find(hero=>hero.id===value),known=new Map(heroes.map(hero=>[hero.id,hero]));
 const extras=heroes.filter(hero=>!legendFor(hero.id));
 const close=useCallback((focus=false)=>{setOpen(false);if(focus)trigger.current?.focus();},[]);
 const place=useCallback(()=>{
  const rect=trigger.current?.getBoundingClientRect();if(!rect)return;
  const width=Math.min(880,innerWidth-16),below=innerHeight-rect.bottom-14,above=rect.top-14,wanted=460+(hasUnknown||extras.length?40:0);
  const floating=wanted>Math.max(below,above),upward=below<wanted&&above>below;
  const maxHeight=Math.max(180,Math.min(wanted,floating?innerHeight-52:upward?above:below));
  const top=floating?Math.max(44,Math.min(rect.bottom+6,innerHeight-maxHeight-12)):upward?Math.max(8,rect.top-maxHeight-6):rect.bottom+6;
  setPosition({left:Math.max(8,Math.min(rect.left+rect.width/2-width/2,innerWidth-width-8)),top,width,maxHeight});
 },[hasUnknown,extras.length]);
 useLayoutEffect(()=>{if(open)place();},[open,place]);
 useEffect(()=>{
  if(!open)return;
  const choices=[...panel.current?.querySelectorAll<HTMLButtonElement>('[data-hero-option]:not(:disabled)')||[]];
  (choices.find(button=>button.dataset.heroOption===value)||choices[0])?.focus({preventScroll:true});
  const outside=(event:PointerEvent)=>{if(!panel.current?.contains(event.target as Node)&&!trigger.current?.contains(event.target as Node))close();};
  const scroll=(event:Event)=>{if(!panel.current?.contains(event.target as Node))place();};
  const focus=(event:FocusEvent)=>{if(!panel.current?.contains(event.target as Node)&&!trigger.current?.contains(event.target as Node))close();};
  document.addEventListener('pointerdown',outside);document.addEventListener('focusin',focus);document.addEventListener('scroll',scroll,true);window.addEventListener('resize',place);
  return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',focus);document.removeEventListener('scroll',scroll,true);window.removeEventListener('resize',place);};
 },[open,close,place,value]);
 function choose(next:string){onChange(next);close(true);}
 function keyDown(event:KeyboardEvent){
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return;}
  if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
  event.preventDefault();
  const buttons=[...panel.current?.querySelectorAll<HTMLButtonElement>('[data-hero-option]:not(:disabled)')||[]];
  if(event.key==='Home'||event.key==='End'){(event.key==='Home'?buttons[0]:buttons.at(-1))?.focus();return;}
  const current=(event.target as HTMLElement).closest<HTMLButtonElement>('button')?.getBoundingClientRect();if(!current)return;
  const horizontal=['ArrowLeft','ArrowRight'].includes(event.key),sign=['ArrowRight','ArrowDown'].includes(event.key)?1:-1;
  const candidates=buttons.map(button=>{const rect=button.getBoundingClientRect(),dx=rect.x+rect.width/2-current.x-current.width/2,dy=rect.y+rect.height/2-current.y-current.height/2;return{button,along:(horizontal?dx:dy)*sign,across:Math.abs(horizontal?dy:dx)};}).filter(candidate=>candidate.along>2).sort((a,b)=>(a.along+a.across*3)-(b.along+b.across*3));
  candidates[0]?.button.focus();
 }
 return <><button type="button" ref={trigger} data-fixed-ink className="styled-select hero-picker-trigger" role="combobox" aria-label="英雄筛选" aria-haspopup="dialog" aria-expanded={open} aria-controls={open?id:undefined} onClick={()=>open?close():setOpen(true)} onKeyDown={event=>{if(event.key==='ArrowDown'){event.preventDefault();setOpen(true);}}}><span className="hero-picker-value">{selected&&legendFor(value)?<img src={apexAsset(`legends/${value}.png`)} alt=""/>:<UsersRound size={17}/>}<span>{selected?.name||(value==='unknown'?'英雄未识别':'所有英雄')}</span></span><ChevronDown size={15}/></button>
  {present&&createPortal(<div ref={panel} id={id} className="hero-picker-panel" role="dialog" aria-label="英雄选择" data-motion-surface aria-hidden={!open} inert={!open} style={position} onKeyDown={keyDown}>
   <div className="hero-picker-heading"><div><b>选择英雄</b><span>按角色定位排列</span></div><button type="button" data-hero-option="" aria-pressed={!value} onClick={()=>choose('')}>所有英雄{!value&&<Check size={14}/>}</button><button type="button" className="icon-button" aria-label="关闭英雄选择" onClick={()=>close(true)}><X size={16}/></button></div>
   <div className="hero-picker-roster">{legendRoles.map(role=><section key={role.id} className="legend-class" role="group" aria-label={`${role.name}英雄`} style={{'--legend-role-color':role.color} as CSSProperties}><h3><ApexIcon file={`classes/${role.id}.svg`} className="legend-role-icon"/>{role.name}</h3><div className="legend-class-grid">{role.legends.map(legend=>{const available=known.get(legend.id),count=available?.count||0;return <button type="button" key={legend.id} className="legend-option" data-hero-option={legend.id} aria-label={legend.name} aria-pressed={value===legend.id} disabled={!count} title={`${legend.name} · ${count?count+' 个片段':'暂无片段'}`} onClick={()=>choose(legend.id)}><span className="legend-portrait"><img src={apexAsset(`legends/${legend.id}.png`)} alt="" draggable={false}/>{count>0&&<span className="legend-clip-count">{count}</span>}{value===legend.id&&<Check className="legend-selected-check" size={15}/>}</span><span className="legend-option-name">{legend.name}</span></button>;})}</div></section>)}</div>
   {(hasUnknown||extras.length>0)&&<div className="hero-picker-other">{hasUnknown&&<button type="button" data-hero-option="unknown" aria-pressed={value==='unknown'} onClick={()=>choose('unknown')}>英雄未识别</button>}{extras.map(hero=><button type="button" key={hero.id} data-hero-option={hero.id} aria-pressed={value===hero.id} onClick={()=>choose(hero.id)}>{hero.name}<span>{hero.count}</span></button>)}</div>}
  </div>,document.body)}
 </>;
}
