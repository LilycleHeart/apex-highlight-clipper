import {useEffect,useState} from 'react';
import {createPortal} from 'react-dom';
import {Minus,Square,Copy,X} from 'lucide-react';
import type {WindowCommand} from './shared';

/** DOM controls participate in the same root snapshot as the circular theme reveal. */
export default function WindowControls(){
 const [maximized,setMaximized]=useState(false);
 useEffect(()=>{
  const api=window.apex;if(!api?.windowState)return;let live=true;
  void api.windowState().then(state=>{if(live)setMaximized(state.maximized);}).catch(()=>{});
  const unsubscribe=api.onWindowState(state=>setMaximized(state.maximized));
  return()=>{live=false;unsubscribe();};
 },[]);
 const command=(value:WindowCommand)=>{void window.apex?.windowCommand(value).catch(()=>{});};
 return createPortal(<div className="window-controls" role="group" aria-label="窗口控制">
  <button type="button" aria-label="最小化窗口" title="最小化" onClick={()=>command('minimize')}><Minus size={14}/></button>
  <button type="button" aria-label={maximized?'还原窗口':'最大化窗口'} title={maximized?'还原':'最大化'} aria-pressed={maximized} onClick={()=>command('maximize')}>{maximized?<Copy size={13}/>:<Square size={11}/>}</button>
  <button type="button" className="window-close" aria-label="关闭窗口" title="关闭" onClick={()=>command('close')}><X size={15}/></button>
 </div>,document.body);
}
