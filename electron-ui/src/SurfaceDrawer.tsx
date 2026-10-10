import {useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {useSurfaceValue} from './surfaceMotion';
import {drawerGeometry} from './surfaceGeometry';
export default function SurfaceDrawer({open,reduced,label,onClose,children}:{open:boolean;reduced:boolean;label:string;onClose:()=>void;children:ReactNode}){
 const q=useSurfaceValue(open?1:0,reduced),panel=useRef<HTMLElement>(null),[size,setSize]=useState({w:420,h:820});
 useLayoutEffect(()=>{if(!panel.current)return;const observer=new ResizeObserver(entries=>{const r=entries[0].contentRect;setSize({w:r.width,h:r.height});});observer.observe(panel.current);return()=>observer.disconnect();},[]);
 return <div className="panel-backdrop surface-backdrop" onClick={onClose} style={{opacity:open?1:Math.max(0,q),pointerEvents:open?'auto':'none'}}><section ref={panel} className="settings-panel surface-drawer" role="dialog" aria-modal="true" aria-label={label} onClick={e=>e.stopPropagation()} style={{clipPath:`path('${drawerGeometry(size.w,size.h,q)}')`}}><svg className="drawer-surface" aria-hidden="true" viewBox={`0 0 ${size.w} ${size.h}`} preserveAspectRatio="none"><path d={drawerGeometry(size.w,size.h,q)}/></svg><div className="drawer-content">{children}</div></section></div>;
}
