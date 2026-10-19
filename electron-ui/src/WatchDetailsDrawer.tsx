import {useRef} from 'react';
import {X} from 'lucide-react';
import type {Clip} from './shared';
import type {ClipDetailFilter} from './libraryFilters';
import ClipDetails from './ClipDetails';
import {useMotionPresence} from './surfaceMotion';

export default function WatchDetailsDrawer({open,id,clip,source,onClose,onFilter}:{open:boolean;id:string;clip:Clip;source?:string;onClose:()=>void;onFilter:(filter:ClipDetailFilter)=>void}){
 const node=useRef<HTMLElement>(null),present=useMotionPresence(open,node,'drawer');
 return present?<aside ref={node} id={id} className="watch-details-drawer" role="dialog" aria-label="片段详情卡片" aria-modal="false" aria-hidden={!open} inert={!open} onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();event.preventDefault();onClose();}}}><div className="watch-drawer-heading"><h2>片段详情</h2><button type="button" className="icon-button" aria-label="关闭详情卡片" onClick={onClose}><X size={18}/></button></div><div className="watch-drawer-body watch-details"><ClipDetails clip={clip} source={source} onFilter={onFilter}/></div></aside>:null;
}
