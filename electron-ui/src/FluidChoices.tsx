import {useRef,useLayoutEffect,useState,type ReactNode} from 'react';
import {useTweenValue} from './surfaceMotion';
import {MENU_EASE} from './surfaceGeometry';
export default function FluidChoices<T extends string>({value,options,onChange,reduced,className,label,disabled=false}:{value:T;options:{value:T;label:string;content:ReactNode}[];onChange:(value:T,button:HTMLButtonElement,origin?:{x:number;y:number})=>void;reduced:boolean;className:string;label:string;disabled?:boolean}){
 const index=Math.max(0,options.findIndex(o=>o.value===value)),node=useRef<HTMLDivElement>(null),initialized=useRef(false),[bounds,setBounds]=useState({left:0,right:0,top:4,bottom:4,width:1,height:1,animate:false,ready:false});
 useLayoutEffect(()=>{
  const n=node.current;if(!n)return;
  const buttons=n.querySelectorAll<HTMLButtonElement>(':scope > button');
  const measure=()=>{
   const b=buttons[index];
   // Layout coordinates remain stable while the surrounding drawer animates.
   // Hidden controls must not replace a valid selection with a zero-width shape.
   if(!b||!n.clientWidth||!n.clientHeight||!b.offsetWidth||!b.offsetHeight){initialized.current=false;return;}
   const next={left:b.offsetLeft,right:b.offsetLeft+b.offsetWidth,top:b.offsetTop,bottom:b.offsetTop+b.offsetHeight,width:n.clientWidth,height:n.clientHeight,animate:initialized.current,ready:true};
   setBounds(old=>old.left===next.left&&old.right===next.right&&old.top===next.top&&old.bottom===next.bottom&&old.width===next.width&&old.height===next.height&&old.ready?old:next);
   initialized.current=true;
  };
  measure();const observer=new ResizeObserver(measure);observer.observe(n);buttons.forEach(button=>observer.observe(button));
  return()=>observer.disconnect();
 },[index,options.length]);
 const left=useTweenValue(bounds.left,reduced||!bounds.animate,MENU_EASE,.32),right=useTweenValue(bounds.right,reduced||!bounds.animate,MENU_EASE,.32),w=Math.max(1,right-left),h=Math.max(1,bounds.bottom-bounds.top),r=Math.min(10,h/2,w/2),top=bounds.top,bottom=bounds.bottom;
 const path=`M${left+r} ${top}H${right-r}Q${right} ${top} ${right} ${top+r}V${bottom-r}Q${right} ${bottom} ${right-r} ${bottom}H${left+r}Q${left} ${bottom} ${left} ${bottom-r}V${top+r}Q${left} ${top} ${left+r} ${top}Z`;
 return <div ref={node} className={`fluid-choices ${className}`} role="group" aria-label={label} data-choice-ready={bounds.ready}><svg className="choice-surface" aria-hidden="true" preserveAspectRatio="none" viewBox={`0 0 ${bounds.width} ${bounds.height}`}>{bounds.ready&&<path d={path}/>}</svg>{options.map(option=><button key={option.value} data-fixed-ink disabled={disabled} aria-label={option.label} aria-pressed={value===option.value} onClick={event=>onChange(option.value,event.currentTarget,event.detail>0?{x:event.clientX,y:event.clientY}:undefined)}>{option.content}</button>)}</div>;
}
