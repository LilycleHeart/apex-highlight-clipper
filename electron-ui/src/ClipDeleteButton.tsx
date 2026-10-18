import {useEffect,useRef,useState} from 'react';
import {Check,LoaderCircle,Trash2} from 'lucide-react';

export default function ClipDeleteButton({label,resetKey,disabled,deleting=false,className='clip-delete',text,onDelete}:{label:string;resetKey:string;disabled:boolean;deleting?:boolean;className?:string;text?:string;onDelete:()=>void}){
 const [confirming,setConfirming]=useState(false);
 const button=useRef<HTMLButtonElement>(null);
 useEffect(()=>setConfirming(false),[resetKey,disabled,deleting]);
 useEffect(()=>{
  if(!confirming)return;
  const timer=setTimeout(()=>setConfirming(false),5000);
  const outside=(event:PointerEvent)=>{if(event.target instanceof Node&&!button.current?.contains(event.target))setConfirming(false);};
  const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')setConfirming(false);};
  const blur=()=>setConfirming(false);
  document.addEventListener('pointerdown',outside,true);document.addEventListener('keydown',escape);window.addEventListener('blur',blur);
  return()=>{clearTimeout(timer);document.removeEventListener('pointerdown',outside,true);document.removeEventListener('keydown',escape);window.removeEventListener('blur',blur);};
 },[confirming]);
 function click(){
  if(disabled||deleting)return;
  if(!confirming){setConfirming(true);return;}
  setConfirming(false);onDelete();
 }
 return <button ref={button} type="button" className={className} data-confirming={confirming} data-deleting={deleting} disabled={disabled||deleting} aria-label={deleting?`正在${label}`:confirming?`确认${label}`:label} title={deleting?'正在删除片段':confirming?'再点一次移至回收站；5秒后取消':'删除片段，点击后需再次确认才移至回收站'} onClick={click} onKeyDown={event=>{if(event.repeat&&(event.key==='Enter'||event.key===' '))event.preventDefault();}}>
  {deleting?<LoaderCircle size={16} className="loading-spinner"/>:confirming?<Check size={16}/>:<Trash2 size={16}/>}{(confirming||text)&&<span aria-live={confirming?'polite':undefined}>{confirming?'确认删除':deleting?'删除中':text}</span>}
 </button>;
}
