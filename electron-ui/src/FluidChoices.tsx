import {useRef,useLayoutEffect,useState,type ReactNode} from 'react';
import {useTweenValue} from './surfaceMotion';
import {VIEW_HEAD,VIEW_TAIL} from './surfaceGeometry';
export default function FluidChoices<T extends string>({value,options,onChange,reduced,className,label,disabled=false}:{value:T;options:{value:T;label:string;content:ReactNode}[];onChange:(value:T)=>void;reduced:boolean;className:string;label:string;disabled?:boolean}){
 const index=Math.max(0,options.findIndex(o=>o.value===value)),previous=useRef(index),direction=useRef(1),node=useRef<HTMLDivElement>(null),[bounds,setBounds]=useState({left:4,right:104,width:316,height:40});
 if(index!==previous.current){direction.current=index>previous.current?1:-1;previous.current=index;}
 useLayoutEffect(()=>{const n=node.current;if(!n)return;const measure=()=>{const b=n.querySelectorAll<HTMLButtonElement>(':scope > button')[index];if(b)setBounds({left:b.offsetLeft,right:b.offsetLeft+b.offsetWidth,width:n.clientWidth,height:n.clientHeight});};measure();const observer=new ResizeObserver(measure);observer.observe(n);return()=>observer.disconnect();},[index,options.length]);
 const left=useTweenValue(bounds.left,reduced,direction.current>0?VIEW_TAIL:VIEW_HEAD),right=useTweenValue(bounds.right,reduced,direction.current>0?VIEW_HEAD:VIEW_TAIL),w=Math.max(1,right-left),h=bounds.height-8,r=Math.min(10,h/2,w/2);
 const path=`M${left+r} 4H${right-r}Q${right} 4 ${right} ${4+r}V${4+h-r}Q${right} ${4+h} ${right-r} ${4+h}H${left+r}Q${left} ${4+h} ${left} ${4+h-r}V${4+r}Q${left} 4 ${left+r} 4Z`;
 return <div ref={node} className={`fluid-choices ${className}`} role="group" aria-label={label}><svg className="choice-surface" aria-hidden="true" viewBox={`0 0 ${bounds.width} ${bounds.height}`}><path d={path}/></svg>{options.map(option=><button key={option.value} data-fixed-ink disabled={disabled} aria-label={option.label} aria-pressed={value===option.value} onClick={()=>onChange(option.value)}>{option.content}</button>)}</div>;
}
