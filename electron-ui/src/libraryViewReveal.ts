import {flushSync} from 'react-dom';

let active:{transition:ViewTransition;restore:()=>void}|null=null;
let generation=0;

export function cancelLibraryViewReveal(){
 generation++;
 const previous=active;if(!previous)return;
 active=null;previous.transition.skipTransition();previous.restore();
}

/** Animate browser snapshots, never the grid's measured dimensions. */
export function revealLibraryView(scroller:HTMLElement|null,update:()=>void,animated:boolean,afterLayout?:()=>void){
 cancelLibraryViewReveal();
 if(!scroller||!animated||document.documentElement.dataset.themeReveal||typeof document.startViewTransition!=='function'){flushSync(update);afterLayout?.();return;}
 const token=generation,root=document.documentElement,previousName=root.style.viewTransitionName,box=scroller.getBoundingClientRect(),names=new Map<string,string>(),named=new Set<HTMLElement>();
 root.style.viewTransitionName='none';root.dataset.libraryReveal='true';
 root.style.setProperty('--library-reveal-clip',`inset(${Math.max(0,box.top)}px ${Math.max(0,innerWidth-box.right)}px ${Math.max(0,innerHeight-box.bottom)}px ${Math.max(0,box.left)}px)`);
 const nameCards=()=>{for(const card of scroller.querySelectorAll<HTMLElement>('.clip-card,.clip-day-heading')){const identity=card.dataset.identity!;let name=names.get(identity);if(!name){name='library-card-'+names.size;names.set(identity,name);}card.style.viewTransitionName=name;named.add(card);}};
 const restore=()=>{for(const card of named)card.style.removeProperty('view-transition-name');root.style.viewTransitionName=previousName;delete root.dataset.libraryReveal;root.style.removeProperty('--library-reveal-clip');};
 nameCards();
 let transition:ViewTransition;
 try{transition=document.startViewTransition(()=>{
  if(token!==generation)return;
  flushSync(update);afterLayout?.();
  // The transition suspends animation frames; commit and measure synchronously.
  nameCards();
 });}catch{restore();flushSync(update);afterLayout?.();return;}
 const current={transition,restore};active=current;
 void transition.ready.catch(()=>{});
 void transition.updateCallbackDone.catch(()=>{});
 void transition.finished.catch(()=>{}).finally(()=>{
  if(active!==current)return;active=null;restore();
  const grid=scroller.querySelector('.clips-grid');grid?.querySelector('.clip-card[data-selected="true"]')?.dispatchEvent(new Event('surface-settled'));grid?.dispatchEvent(new Event('layout-settled'));
 });
}
