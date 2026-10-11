import {useId,useState,type ReactNode} from 'react';
import MotionDisclosure from './MotionDisclosure';

export default function MotionDetails({label,className,children,onGeometryChange}:{label:string;className:string;children:ReactNode;onGeometryChange?:()=>void}){
 const [open,setOpen]=useState(false),[layoutOpen,setLayoutOpen]=useState(false),id=useId();
 function toggle(){const next=!open;setOpen(next);if(next)setLayoutOpen(true);onGeometryChange?.();}
 return <div className={className} data-open={layoutOpen}><button type="button" className="details-toggle" data-fixed-ink aria-expanded={open} aria-controls={id} onClick={toggle}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3L12 8L5 13Z"/></svg>{label}</button><MotionDisclosure open={open} id={id} onComplete={()=>{if(!open)setLayoutOpen(false);onGeometryChange?.();}}>{children}</MotionDisclosure></div>;
}
