import {useCallback,useEffect,useId,useLayoutEffect,useRef,useState,type KeyboardEvent} from 'react';
import {createPortal} from 'react-dom';
import {Check,ChevronDown,LoaderCircle,RotateCcw,Search,X} from 'lucide-react';
import {excludedTeammateKey} from './teammateExclusions';
import {useMotionPresence} from './surfaceMotion';

export default function TeammatePicker({value,onChange,names,excluded,onExclude}:{value:string;onChange:(name:string)=>void;names:string[];excluded:string[];onExclude:(name:string,excluded:boolean)=>Promise<void>}){
 const [open,setOpen]=useState(false),[manage,setManage]=useState(false),[query,setQuery]=useState(''),[pending,setPending]=useState<string|null>(null),[error,setError]=useState(''),[position,setPosition]=useState({left:0,top:0,width:300,maxHeight:340});
 const trigger=useRef<HTMLButtonElement>(null),panel=useRef<HTMLDivElement>(null),search=useRef<HTMLInputElement>(null),id=useId(),present=useMotionPresence(open,panel);
 const hidden=new Set(excluded.map(excludedTeammateKey)),visible=names.filter(name=>!hidden.has(excludedTeammateKey(name))),shown=(manage?excluded:visible).filter(name=>name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).sort((a,b)=>a.localeCompare(b,'zh-CN'));
 const close=useCallback((focus=false)=>{setOpen(false);if(focus)trigger.current?.focus();},[]);
 const place=useCallback(()=>{if(!trigger.current)return;const desired=Math.min(380,128+(shown.length+(!manage&&!query.trim()?1:0))*40+(error?32:0)),box=trigger.current.getBoundingClientRect(),below=innerHeight-box.bottom-14,above=box.top-14,up=below<240&&above>below,height=Math.min(desired,Math.max(180,up?above:below)),width=Math.min(Math.max(box.width,280),innerWidth-20);setPosition({left:Math.max(10,Math.min(innerWidth-width-10,box.left)),top:up?Math.max(10,box.top-height-6):box.bottom+6,width,maxHeight:height});},[shown.length,manage,query,error]);
 useLayoutEffect(()=>{if(open)place();},[open,place]);
 useEffect(()=>{if(open)search.current?.focus({preventScroll:true});},[open,manage]);
 useEffect(()=>{if(!open)return;const outside=(event:PointerEvent)=>{if(!panel.current?.contains(event.target as Node)&&!trigger.current?.contains(event.target as Node))close();};document.addEventListener('pointerdown',outside);window.addEventListener('resize',place);window.addEventListener('scroll',place,true);return()=>{document.removeEventListener('pointerdown',outside);window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);};},[open,close,place]);
 function show(){setManage(false);setQuery('');setError('');setOpen(true);}
 async function mark(name:string,remove:boolean){if(pending)return;setPending(name);setError('');try{await onExclude(name,remove);}catch(error){setError(String(error).replace(/^Error:\s*/,''));}finally{setPending(null);requestAnimationFrame(()=>search.current?.focus({preventScroll:true}));}}
 function keys(event:KeyboardEvent){
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return;}
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){
   const choices=[...panel.current?.querySelectorAll<HTMLButtonElement>('[data-teammate-choice]:not(:disabled)')||[]];if(!choices.length)return;
   event.preventDefault();const current=choices.indexOf(document.activeElement as HTMLButtonElement),direction=event.key==='ArrowDown'?1:-1;choices[current<0?(direction>0?0:choices.length-1):(current+direction+choices.length)%choices.length]?.focus();
  }
 }
 return <><button ref={trigger} type="button" className="styled-select" data-fixed-ink role="combobox" aria-label="队友筛选" aria-haspopup="dialog" aria-expanded={open} aria-controls={open?id:undefined} onClick={()=>open?close():show()} onKeyDown={event=>{if(event.key==='ArrowDown'){event.preventDefault();show();}}}><span className="styled-select-label">{value||'所有队友'}</span><ChevronDown size={15}/></button>
  {present&&createPortal(<div ref={panel} id={id} className="styled-select-menu teammate-picker-menu" data-motion-surface role="dialog" aria-label={manage?'非好友管理':'队友筛选选项'} aria-hidden={!open} inert={!open} style={position} onKeyDown={keys}>
   <div className="teammate-picker-heading"><b>{manage?'非好友管理':'队友'}</b><span>{manage?'恢复后重新显示在筛选里':'× 标记非好友'}</span></div>
   <label className="teammate-picker-search"><Search size={14}/><input ref={search} type="search" aria-label={manage?'搜索非好友':'搜索队友'} placeholder="搜索名称" value={query} onChange={event=>setQuery(event.target.value)}/></label>
   <div className="teammate-picker-options">
    {!manage&&!query.trim()&&<button type="button" className="teammate-option" data-teammate-choice aria-pressed={!value} onClick={()=>{onChange('');close(true);}}><span>所有队友</span>{!value&&<Check size={15}/>}</button>}
    {shown.map(name=><div key={excludedTeammateKey(name)} className="teammate-option-row">
     {manage?<span className="teammate-excluded-name">{name}</span>:<button type="button" className="teammate-option" data-teammate-choice aria-pressed={excludedTeammateKey(value)===excludedTeammateKey(name)} onClick={()=>{onChange(name);close(true);}}><span>{name}</span>{excludedTeammateKey(value)===excludedTeammateKey(name)&&<Check size={15}/>}</button>}
     <button type="button" className="teammate-mark" data-teammate-choice disabled={!!pending} aria-label={manage?`恢复队友 ${name}`:`将 ${name} 标记为非好友`} title={manage?'恢复到队友筛选':'标记为非好友，以后不在筛选列表显示'} onClick={()=>void mark(name,!manage)}>{pending===name?<LoaderCircle size={14} className="loading-spinner"/>:manage?<RotateCcw size={14}/>:<X size={14}/>}</button>
    </div>)}
    {!shown.length&&<p className="teammate-picker-empty">{manage?'没有匹配的非好友':query?'没有匹配的队友':'暂无队友选项'}</p>}
   </div>
   {error&&<p role="alert" className="teammate-picker-error">{error}</p>}
   <div className="teammate-picker-footer"><button type="button" onClick={()=>{setManage(!manage);setQuery('');setError('');}} disabled={!manage&&!excluded.length}>{manage?'返回队友列表':`非好友管理（${excluded.length}）`}</button><button type="button" aria-label="关闭队友筛选" onClick={()=>close(true)}><X size={14}/></button></div>
  </div>,document.body)}
 </>;
}
