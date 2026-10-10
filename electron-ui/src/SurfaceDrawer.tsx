import {useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {Palette,Settings2} from 'lucide-react';
import {useTweenValue} from './surfaceMotion';
import {MENU_EASE,connectedTabPath} from './surfaceGeometry';
import type {MenuKind} from './Titlebar';
function Tool({kind,active,q,left,onClick,reduced}:{kind:MenuKind;active:boolean;q:number;left:number;onClick:()=>void;reduced:boolean}){
 const selected=useTweenValue(active?1:0,reduced,MENU_EASE);
 return <button className={'menu-tool '+(active?'active':'')} data-menu-proxy={kind} aria-label={kind==='theme'?'配色与动效':'剪辑设置'} aria-haspopup="dialog" aria-expanded={active} data-fixed-ink style={{left}} onClick={onClick}><svg width="68" height="38" aria-hidden="true"><path d={connectedTabPath(selected*q,36)} fill="var(--card-paper)"/></svg>{kind==='theme'?<Palette size={20}/>:<Settings2 size={20}/>}</button>;
}
export default function SurfaceDrawer({open,reduced,label,onClose,children,kind,onSwitch}:{open:boolean;reduced:boolean;label:string;onClose:()=>void;children:ReactNode;kind:MenuKind;onSwitch:(kind:MenuKind)=>void}){
 const body=useRef<HTMLDivElement>(null),[measure,setMeasure]=useState({width:456,height:640,left:656,theme:898,settings:938});
 useLayoutEffect(()=>{const update=()=>{const width=Math.min(456,innerWidth-16),height=Math.min(innerHeight-44,body.current?.scrollHeight||640),left=innerWidth-8-width,theme=document.querySelector<HTMLElement>('[data-menu=theme]')?.getBoundingClientRect().left??innerWidth-222,settings=document.querySelector<HTMLElement>('[data-menu=settings]')?.getBoundingClientRect().left??innerWidth-182;setMeasure({width,height,left,theme,settings});};update();const observer=new ResizeObserver(update);if(body.current)observer.observe(body.current);window.addEventListener('resize',update);return()=>{observer.disconnect();window.removeEventListener('resize',update);};},[kind]);
 const anchor=measure[kind]-measure.left,left=useTweenValue(open?0:anchor,reduced,MENU_EASE),right=useTweenValue(open?measure.width:anchor+36,reduced,MENU_EASE),height=useTweenValue(open?measure.height:0,reduced,MENU_EASE),q=useTweenValue(open?1:0,reduced,MENU_EASE),r=Math.max(0,Math.min(20,(right-left)/2,height/2)),h=Math.max(0,height);
 const path='M'+(left+r)+' 0H'+(right-r)+'Q'+right+' 0 '+right+' '+r+'V'+(h-r)+'Q'+right+' '+h+' '+(right-r)+' '+h+'H'+(left+r)+'Q'+left+' '+h+' '+left+' '+(h-r)+'V'+r+'Q'+left+' 0 '+(left+r)+' 0Z';
 return createPortal(<div className="menu-layer" style={{visibility:open||q>0?'visible':'hidden',pointerEvents:open?'auto':'none'}} aria-hidden={!open}>
  <div className="menu-scrim" style={{opacity:.32*q}} onClick={onClose}/>
  <div className="menu-tool-row">{(['theme','settings'] as const).map(type=><Tool key={type} kind={type} reduced={reduced} active={kind===type} q={q} left={measure[type]} onClick={()=>type===kind?onClose():onSwitch(type)}/>)}</div>
  <section className="settings-panel surface-drawer" role="dialog" aria-modal="true" aria-label={label} style={{width:measure.width,left:measure.left,height:measure.height,clipPath:"path('"+path+"')"}}><svg className="drawer-surface" aria-hidden="true" viewBox={'0 0 '+measure.width+' '+measure.height}><path d={path}/></svg><div ref={body} className="drawer-content">{children}</div></section>
 </div>,document.body);
}
