import {useRef,type ReactNode} from 'react';
import {useMotionPresence} from './surfaceMotion';

export default function MotionDisclosure({open,id,className='',children,onComplete}:{open:boolean;id?:string;className?:string;children:ReactNode;onComplete?:()=>void}){
 const node=useRef<HTMLDivElement>(null),present=useMotionPresence(open,node,'disclosure',onComplete);
 return present?<div ref={node} id={id} className={`motion-disclosure ${className}`} data-open={open} aria-hidden={!open} inert={!open}><div className="motion-disclosure-content">{children}</div></div>:null;
}
