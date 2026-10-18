import {useRef,type ReactNode} from 'react';
import {X} from 'lucide-react';

export default function FilterControl({active,onClear,label,children}:{active:boolean;onClear:()=>void;label:string;children:ReactNode}){
 const root=useRef<HTMLDivElement>(null);
 return <div ref={root} className="filter-control" data-active={active}>
  <div className="filter-control-value">{children}</div>
  <div className="filter-clear-slot" aria-hidden={!active} inert={!active}><button type="button" className="filter-clear" aria-label={`清除${label}筛选`} tabIndex={active?0:-1} onClick={event=>{event.preventDefault();event.stopPropagation();onClear();requestAnimationFrame(()=>root.current?.querySelector<HTMLElement>('[role="combobox"],input')?.focus());}}><X size={14}/></button></div>
 </div>;
}
