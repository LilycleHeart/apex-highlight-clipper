import {Palette,Settings2} from 'lucide-react';
import {useSurfaceValue} from './surfaceMotion';
import {clamp,tabGeometry} from './surfaceGeometry';
export type Page='start'|'clips'|'statistics';
const tabs=[{id:'start',label:'开始'},{id:'clips',label:'整理片段'},{id:'statistics',label:'统计数据'}] as const;
function Tab({id,label,selected,onSelect,reduced}:{id:Page;label:string;selected:boolean;onSelect:()=>void;reduced:boolean}){
 const q=useSurfaceValue(selected?1:0,reduced),g=tabGeometry(q,16,116),u=clamp(q);
 return <button className="nav-tab" role="tab" id={`tab-${id}`} aria-controls={`page-${id}`} aria-selected={selected} onClick={onSelect} onKeyDown={e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();const buttons=[...e.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('[role=tab]')];const i=buttons.indexOf(e.currentTarget),n=buttons[(i+(e.key==='ArrowRight'?1:buttons.length-1))%buttons.length];n.focus();n.click();}}}>
  <svg className="nav-surface" width="148" height="38" aria-hidden="true"><path d={g.path} fill="var(--page-blue)" opacity={g.opacity}/></svg><span style={{opacity:.8+.2*u}}>{label}</span>
 </button>;
}
export default function Titlebar({page,onPage,reduced,ready,hasUpdate,onPanel}:{page:Page;onPage:(page:Page)=>void;reduced:boolean;ready:boolean;hasUpdate:boolean;onPanel:(panel:'theme'|'settings')=>void}){
 return <header className="titlebar"><img className="wordmark" src={`${import.meta.env.BASE_URL}brand/apexclipper-wordmark.svg`} alt="apexclipper"/><nav aria-label="主页面" role="tablist">{tabs.map(tab=><Tab key={tab.id} {...tab} selected={page===tab.id} onSelect={()=>onPage(tab.id)} reduced={reduced}/>)}</nav><div className="titlebar-tools"><button className="icon-button" aria-label="配色与动效" title="配色与动效" disabled={!ready} onClick={()=>onPanel('theme')}><Palette size={20}/></button><button className={`icon-button ${hasUpdate?'has-update':''}`} aria-label="剪辑设置" title="剪辑设置" disabled={!ready} onClick={()=>onPanel('settings')}><Settings2 size={20}/>{hasUpdate&&<span className="update-dot"/>}</button></div></header>;
}
