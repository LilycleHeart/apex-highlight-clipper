import {Palette,Settings2} from 'lucide-react';
import {useSurfaceValue} from './surfaceMotion';
import {clamp,connectedTabPath} from './surfaceGeometry';
export type Page='start'|'clips'|'statistics';
export type MenuKind='theme'|'settings';
const tabs=[{id:'start',label:'开始'},{id:'clips',label:'整理片段'},{id:'statistics',label:'统计数据'}] as const;
function Tab({id,label,selected,onSelect,reduced}:{id:Page;label:string;selected:boolean;onSelect:()=>void;reduced:boolean}){
 const q=clamp(useSurfaceValue(selected?1:0,reduced));
 return <button className="nav-tab" role="tab" id={'tab-'+id} aria-controls={'page-'+id} aria-selected={selected} data-fixed-ink onClick={onSelect} style={{color:q>.75?'var(--page-on)':'var(--chrome-on)'}} onKeyDown={e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();const buttons=[...e.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('[role=tab]')];const i=buttons.indexOf(e.currentTarget),n=buttons[(i+(e.key==='ArrowRight'?1:buttons.length-1))%buttons.length];n.focus();n.click();}}}>
  <svg className="nav-surface" width="148" height="38" aria-hidden="true"><path d={connectedTabPath(q)} fill="var(--page-blue)" opacity={q}/></svg><span>{label}</span>
 </button>;
}
export default function Titlebar({page,onPage,reduced,ready,hasUpdate,onPanel,menuOpen=false}:{page:Page;onPage:(page:Page)=>void;reduced:boolean;ready:boolean;hasUpdate:boolean;onPanel:(panel:MenuKind)=>void;menuOpen?:boolean}){
 return <header className="titlebar"><div className="ahc-region"><button className="ahc-home" aria-label="AHC 返回开始" onClick={()=>onPage('start')}><span className="ahc-art" aria-hidden="true"/></button></div><nav aria-label="主页面" role="tablist">{tabs.map(tab=><Tab key={tab.id} {...tab} selected={page===tab.id} onSelect={()=>onPage(tab.id)} reduced={reduced}/>)}</nav><div className={'titlebar-tools '+(menuOpen?'tools-covered':'')}>
  <button className="icon-button" data-menu="theme" title="个性化设置" aria-label="配色与动效" aria-haspopup="dialog" aria-expanded={menuOpen} aria-hidden={menuOpen||undefined} disabled={!ready} onClick={()=>onPanel('theme')}><Palette size={20}/></button>
  <button className={'icon-button '+(hasUpdate?'has-update':'')} data-menu="settings" title="剪辑设置" aria-label="剪辑设置" aria-haspopup="dialog" aria-expanded={menuOpen} aria-hidden={menuOpen||undefined} disabled={!ready} onClick={()=>onPanel('settings')}><Settings2 size={20}/>{hasUpdate&&<span className="update-dot"/>}</button>
 </div></header>;
}
