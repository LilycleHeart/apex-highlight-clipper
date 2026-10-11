import {flushSync} from 'react-dom';
import {cancelLibraryViewReveal} from './libraryViewReveal';

let generation=0;
let active:{transition:ViewTransition;animation?:Animation}|null=null;

function clearOrigin(){const root=document.documentElement;delete root.dataset.themeReveal;root.style.removeProperty('--theme-reveal-x');root.style.removeProperty('--theme-reveal-y');}

export function cancelThemeReveal(){
 generation++;
 active?.animation?.cancel();
 active?.transition.skipTransition();
 active=null;
 clearOrigin();
}

/** Reveal the new page from the selected button; interrupted clicks keep the latest choice. */
export function revealTheme(button:HTMLElement,update:()=>void,animated:boolean,origin?:{x:number;y:number}){
 cancelLibraryViewReveal();
 cancelThemeReveal();
 if(!animated||typeof document.startViewTransition!=='function'){flushSync(update);return;}
 const token=generation,box=button.getBoundingClientRect();
 const pointer=origin&&Number.isFinite(origin.x)&&Number.isFinite(origin.y)?origin:null;
 const x=Math.max(0,Math.min(innerWidth,pointer?.x??box.left+box.width/2)),y=Math.max(0,Math.min(innerHeight,pointer?.y??box.top+box.height/2));
 const radius=Math.hypot(Math.max(x,innerWidth-x),Math.max(y,innerHeight-y));
 const root=document.documentElement;
 root.style.setProperty('--theme-reveal-x',`${x}px`);root.style.setProperty('--theme-reveal-y',`${y}px`);
 root.dataset.themeReveal='true';
 let transition:ViewTransition;
 try{transition=document.startViewTransition(()=>{if(token===generation)flushSync(update);});}
 catch{clearOrigin();flushSync(update);return;}
 const current:{transition:ViewTransition;animation?:Animation}={transition};active=current;
 void transition.ready.then(()=>{
  if(active!==current)return;
  current.animation=root.animate(
   [{clipPath:`circle(0px at ${x}px ${y}px)`,offset:0},
    {clipPath:`circle(12px at ${x}px ${y}px)`,offset:.12,easing:'cubic-bezier(.4,0,.2,1)'},
    {clipPath:`circle(${radius}px at ${x}px ${y}px)`,offset:1}],
   {duration:600,easing:'linear',fill:'both',pseudoElement:'::view-transition-new(root)'}
  );
  return current.animation.finished;
 }).catch(()=>{});
 void transition.finished.catch(()=>{}).finally(()=>{
  if(active===current){active=null;clearOrigin();}
 });
}
