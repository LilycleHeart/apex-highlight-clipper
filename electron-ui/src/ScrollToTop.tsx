import {useEffect,useRef,useState} from 'react';
import {ArrowUp} from 'lucide-react';
import type {Page} from './Titlebar';
import {useMotionPresence} from './surfaceMotion';

export default function ScrollToTop({page,reduced}:{page:Page;reduced:boolean}){
 const root=useRef<HTMLElement|null>(null),button=useRef<HTMLButtonElement>(null),[visible,setVisible]=useState(false),present=useMotionPresence(visible,button);
 useEffect(()=>{
  const element=page==='start'?document.querySelector<HTMLElement>('.page-surface'):document.getElementById('page-'+page);root.current=element;setVisible(false);if(!element)return;
  const update=()=>{const remaining=element.scrollHeight-element.clientHeight-element.scrollTop;setVisible(!document.fullscreenElement&&element.scrollTop>0&&(element.scrollTop>Math.max(240,element.clientHeight*.5)||remaining<=2));};
  const observer=new ResizeObserver(update);observer.observe(element);element.addEventListener('scroll',update,{passive:true});document.addEventListener('fullscreenchange',update);update();
  return()=>{observer.disconnect();element.removeEventListener('scroll',update);document.removeEventListener('fullscreenchange',update);root.current=null;};
 },[page]);
 return present?<button ref={button} type="button" className="scroll-to-top" data-motion-surface aria-hidden={!visible} inert={!visible} aria-label="回到顶部" onClick={()=>root.current?.scrollTo({top:0,behavior:reduced?'instant':'smooth'})}><ArrowUp size={17}/><span>回到顶部</span></button>:null;
}
