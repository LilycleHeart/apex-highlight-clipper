import {createContext,useContext,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {ScanText,Share2,X,LoaderCircle} from 'lucide-react';
import type {HudJob} from './useHudEnrichment';
import type {HudEnrichmentField,HudEnrichmentResult} from './shared';
import {enrichmentFields,hudFields,HudFieldPicker} from './HudSettings';
import {useMotionPresence} from './surfaceMotion';

export interface LibraryClipActions {
 selectionMode:boolean;checked:ReadonlySet<string>;onCheck:(file:string)=>void;
 recognitionDisabled:boolean;recognizing:string|null;enrichment:HudJob|null;
 onRecognize:(file:string,fields:HudEnrichmentField[])=>Promise<HudEnrichmentResult>;
 sharing:boolean;onShare:(files:string[])=>void;
}
export const ClipActionsContext=createContext<LibraryClipActions|null>(null);
export function ClipSelection({file,name}:{file:string;name:string}){
 const actions=useContext(ClipActionsContext);if(!actions?.selectionMode)return null;
 return <label className="clip-selection" title={name}><input type="checkbox" aria-label={`选择片段 ${name}`} checked={actions.checked.has(file)} disabled={actions.sharing} onChange={()=>actions.onCheck(file)}/><span>{actions.checked.has(file)?'已选':'选择'}</span></label>;
}
export function ClipActionButtons({file,name,labels='all',imported=false}:{file:string;name:string;labels?:'all'|'share'|'none';imported?:boolean}){
 const actions=useContext(ClipActionsContext),anchor=useRef<HTMLButtonElement>(null),panel=useRef<HTMLDivElement>(null);
 const task=actions?.enrichment?.kind==='single'&&actions.enrichment.files.includes(file)?actions.enrichment:null;
 const [open,setOpen]=useState(false),[fields,setFields]=useState<HudEnrichmentField[]>(()=>task?.fields||(imported?[...hudFields.map(field=>field.key),'statistics' as HudEnrichmentField]:hudFields.map(field=>field.key))),[message,setMessage]=useState(''),[failed,setFailed]=useState(false),[position,setPosition]=useState({left:0,top:0});
 const present=useMotionPresence(open,panel),running=actions?.recognizing===file;
 const taskMessage=task?(task.error||task.progress.message)+(task.running&&task.progress.framesTotal?` · 画面 ${task.progress.framesDone}/${task.progress.framesTotal}`:''):'';
 const displayMessage=running?taskMessage:message||taskMessage,displayFailed=failed||!!task?.error;
 useLayoutEffect(()=>{if(!open)return;const place=()=>{if(!anchor.current||!panel.current)return;const a=anchor.current.getBoundingClientRect(),p=panel.current.getBoundingClientRect();setPosition({left:Math.max(10,Math.min(innerWidth-p.width-10,a.right-p.width)),top:a.top>p.height+16?a.top-p.height-8:Math.max(10,Math.min(innerHeight-p.height-10,a.bottom+8))});};place();window.addEventListener('resize',place);window.addEventListener('scroll',place,true);return()=>{window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);};},[open,displayMessage,running]);
 useEffect(()=>{if(!open)return;const outside=(e:PointerEvent)=>{if(!running&&!panel.current?.contains(e.target as Node)&&!anchor.current?.contains(e.target as Node))setOpen(false);};document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);},[open,running]);

 async function run(){if(!actions||!fields.length)return;setFailed(false);setMessage('准备重新识别');try{const result=await actions.onRecognize(file,fields);setFailed(!!result.errors.length||!!result.unconfirmed);setMessage(result.errors.length?result.errors[0].message:result.unconfirmed?'识别完成，仍有未确认信息，请核验读数。':'本片段所选信息已重新识别');}catch(error){setFailed(true);setMessage(String(error).replace(/^Error:\s*/,''));}}
 if(!actions)return null;
 return <><span className="clip-action-buttons">
  <button ref={anchor} type="button" className="clip-action" aria-label={`重新识别片段 ${name}`} title={running?'正在识别此片段':'重新识别此片段'} aria-expanded={open} aria-haspopup="dialog" aria-busy={running} disabled={actions.recognitionDisabled&&!running} onClick={()=>setOpen(value=>!value)}>{running?<LoaderCircle size={16} className="loading-spinner"/>:<ScanText size={16}/>}{labels==='all'&&<span>{running?'识别中':'重新识别'}</span>}</button>
  <button type="button" className="clip-action" aria-label={`分享到 QQ ${name}`} title="分享到 QQ，选择会话" disabled={actions.sharing} onClick={()=>actions.onShare([file])}><Share2 size={16}/>{labels!=='none'&&<span>分享</span>}</button>
 </span>{present&&createPortal(<section ref={panel} className="clip-recognition-panel" role="dialog" aria-label="重新识别此片段" data-motion-surface aria-hidden={!open} inert={!open} style={position} onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();setOpen(false);anchor.current?.focus();}}}>
  <div className="clip-recognition-heading"><b>重新识别此片段</b><button type="button" className="icon-button" aria-label="关闭单片段识别" onClick={()=>setOpen(false)}><X size={16}/></button></div><p className="clip-recognition-name" title={name}>{name}</p>
  <p>只重读此视频中勾选的信息，其他字段保留。</p><HudFieldPicker items={enrichmentFields} value={running&&task?task.fields:fields} onChange={setFields} disabled={running}/>
  {displayMessage&&<p className="clip-recognition-status" role={displayFailed?'alert':'status'}>{displayMessage}</p>}
  <div className="clip-recognition-footer">{running?<button type="button" className="secondary" onClick={()=>void window.apex.stop().catch(error=>{setFailed(true);setMessage(String(error));})}>停止识别</button>:<span/>}<button type="button" className="primary" disabled={actions.recognitionDisabled||!fields.length} onClick={()=>void run()}>{running?<><LoaderCircle size={14} className="loading-spinner"/>正在识别…</>:'开始重新识别此片段'}</button></div>
 </section>,document.fullscreenElement||document.body)}</>;
}
