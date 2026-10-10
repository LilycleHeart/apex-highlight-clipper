import {useRef,useLayoutEffect,useState,type ReactNode} from 'react';
import {useSurfaceValue} from './surfaceMotion';
import {NAV} from './surfaceGeometry';
const TAIL={duration:.56,decay:NAV.decay*.5/.56,omega:NAV.omega*.5/.56};
export default function FluidChoices<T extends string>({value,options,onChange,reduced,className,label}:{value:T;options:{value:T;label:string;content:ReactNode}[];onChange:(value:T)=>void;reduced:boolean;className:string;label:string}){
 const index=Math.max(0,options.findIndex(o=>o.value===value)),lead=useSurfaceValue(index,reduced),tail=useSurfaceValue(index,reduced,TAIL),node=useRef<HTMLDivElement>(null),[size,setSize]=useState({width:300,height:40});
 useLayoutEffect(()=>{if(!node.current)return;const observer=new ResizeObserver(()=>{const n=node.current!;setSize({width:n.clientWidth,height:n.clientHeight});});observer.observe(node.current);return()=>observer.disconnect();},[]);
 const slot=(size.width-8)/options.length,h=size.height-8,w=slot+Math.min(slot*.26,Math.abs(lead-tail)*slot),x=4+(lead+tail)/2*slot-(w-slot)/2,r=Math.min(12,h/2),strain=Math.min(5,Math.abs(lead-tail)*10);
 const path=`M${x+r} 4H${x+w-r}Q${x+w} 4 ${x+w} ${4+r}Q${x+w-strain} ${4+h/2} ${x+w} ${4+h-r}Q${x+w} ${4+h} ${x+w-r} ${4+h}H${x+r}Q${x} ${4+h} ${x} ${4+h-r}Q${x+strain} ${4+h/2} ${x} ${4+r}Q${x} 4 ${x+r} 4Z`;
 return <div ref={node} className={`fluid-choices ${className}`} role="group" aria-label={label}><svg className="choice-surface" aria-hidden="true" viewBox={`0 0 ${size.width} ${size.height}`}><path d={path}/></svg>{options.map(option=><button key={option.value} aria-label={option.label} aria-pressed={value===option.value} onClick={()=>onChange(option.value)}>{option.content}</button>)}</div>;
}
