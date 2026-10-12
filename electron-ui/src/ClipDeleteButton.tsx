import {useEffect,useRef,useState} from 'react';
import {Check,LoaderCircle,Trash2} from 'lucide-react';

export default function ClipDeleteButton({label,resetKey,disabled,deleting=false,className='clip-delete',onDelete}:{label:string;resetKey:string;disabled:boolean;deleting?:boolean;className?:string;onDelete:()=>void}){
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
 return <button ref={button} type="button" className={className} data-confirming={confirming} data-deleting={deleting} disabled={disabled||deleting} aria-label={confirming?`确认${label}`:label} title={confirming?'再点一次移至回收站；5秒后取消':'点击后需再次确认，才移至回收站'} onClick={click} onKeyDown={event=>{if(event.repeat&&(event.key==='Enter'||event.key===' '))event.preventDefault();}}>
  {deleting?<LoaderCircle size={16}/>:confirming?<Check size={16}/>:<Trash2 size={16}/>}{confirming&&<span aria-live="polite">确认删除</span>}
 </button>;
}
