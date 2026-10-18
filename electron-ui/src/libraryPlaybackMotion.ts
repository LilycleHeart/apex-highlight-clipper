import {flushSync} from 'react-dom';
import {cancelLibraryViewReveal} from './libraryViewReveal';

type Options={kind:'open'|'close'|'mode';file?:string;reduced?:boolean;afterLayout?:()=>void};
let active:{transition:ViewTransition;restore:()=>void}|null=null;
let generation=0;

export function cancelLibraryPlaybackMotion(){generation++;const previous=active;if(!previous)return;active=null;previous.transition.skipTransition();previous.restore();}

/** Animate snapshots of final layouts. Never resize the measured virtual grid
 * frame by frame, or detach the live video to create the transition. */
export function transitionLibraryPlayback(shell:HTMLElement|null,library:HTMLElement|null,update:()=>void,options:Options){
 cancelLibraryPlaybackMotion();cancelLibraryViewReveal();
 const settleLayout=()=>{
  for(let pass=0;pass<2;pass++)flushSync(()=>library?.querySelector('.clips-grid')?.dispatchEvent(new Event('library-layout-measure')));
  options.afterLayout?.();
 };
 const root=document.documentElement,reduced=options.reduced||root.dataset.reduced==='true'||matchMedia('(prefers-reduced-motion: reduce)').matches;
 if(!shell||!library||reduced||document.hidden||typeof document.startViewTransition!=='function'){flushSync(update);settleLayout();return;}
 const closing=options.kind==='close',token=generation,names=new Map<HTMLElement,string>(),backgrounds=new Map<HTMLElement,{image:string;size:string;position:string;repeat:string}>(),previousRootName=root.style.viewTransitionName;
 const name=(element:HTMLElement|null,value:string)=>{if(!element)return;if(!names.has(element))names.set(element,element.style.viewTransitionName);element.style.viewTransitionName=value;};
 const clearNames=()=>{for(const [element,value]of names)element.style.viewTransitionName=value;};
 const thumbnail=()=>[...library.querySelectorAll<HTMLElement>('.clip-card[data-path]')].find(card=>card.dataset.path===options.file)?.querySelector<HTMLElement>('.media-frame')||null;
 const visible=(element:HTMLElement|null)=>{if(!element||getComputedStyle(element).visibility==='hidden')return false;const box=element.getBoundingClientRect(),viewport=library.getBoundingClientRect();return box.bottom>viewport.top&&box.top<viewport.bottom&&box.right>viewport.left&&box.left<viewport.right;};
 const cardNames=new Map<string,string>(),chromeNames=new Map<HTMLElement,string>();
 const nameClosingLibrary=()=>{
  // Capture complete cards, including their covers. Extracting the target cover
  // from a resizing library snapshot leaves a hole underneath the flying image.
  for(const card of library.querySelectorAll<HTMLElement>('.clips-grid>.clip-card,.clips-grid>.clip-day-heading')){
   if(!visible(card))continue;
   const identity=card.dataset.identity!;let value=cardNames.get(identity);if(!value){value='library-return-card-'+cardNames.size;cardNames.set(identity,value);}name(card,value);
  }
  for(const element of library.children){
   if(!(element instanceof HTMLElement)||element.classList.contains('virtual-clips')||!visible(element))continue;
   let value=chromeNames.get(element);if(!value){value='library-return-chrome-'+chromeNames.size;chromeNames.set(element,value);}name(element,value);
  }
 };
 const oldPlayer=shell.querySelector<HTMLElement>('.watch-player'),oldPicture=oldPlayer?.querySelector<HTMLElement>('.watch-screen')||(options.kind==='open'?thumbnail():null);
 const poster=oldPicture?.querySelector<HTMLImageElement>('img')?.currentSrc||oldPicture?.querySelector<HTMLVideoElement>('video')?.poster;
 name(library,'library-browse');name(oldPlayer,'library-player-panel');
 if(closing)nameClosingLibrary();else name(oldPicture,'library-active-picture');
 const box=shell.getBoundingClientRect();root.style.viewTransitionName='none';root.dataset.libraryReveal='true';root.dataset.libraryPlayback=options.kind;
 if(closing&&cardNames.size)root.dataset.libraryReturnReflow='true';
 root.style.setProperty('--library-reveal-clip',`inset(${Math.max(0,box.top)}px ${Math.max(0,innerWidth-box.right)}px ${Math.max(0,innerHeight-box.bottom)}px ${Math.max(0,box.left)}px)`);
 const restore=()=>{clearNames();for(const [element,value]of backgrounds){element.style.backgroundImage=value.image;element.style.backgroundSize=value.size;element.style.backgroundPosition=value.position;element.style.backgroundRepeat=value.repeat;}root.style.viewTransitionName=previousRootName;delete root.dataset.libraryReveal;delete root.dataset.libraryPlayback;delete root.dataset.libraryReturnReflow;root.style.removeProperty('--library-reveal-clip');};
 let transition:ViewTransition;
 try{transition=document.startViewTransition(()=>{
  if(token!==generation)return;
  flushSync(update);settleLayout();clearNames();
  const player=shell.querySelector<HTMLElement>('.watch-player'),picture=player?.querySelector<HTMLElement>('.watch-screen')||thumbnail();
  name(library,'library-browse');name(player,'library-player-panel');
  if(closing)nameClosingLibrary();else if(player||visible(picture))name(picture,'library-active-picture');
  const frame=player?.querySelector<HTMLElement>('.media-frame');
  if(frame&&poster){backgrounds.set(frame,{image:frame.style.backgroundImage,size:frame.style.backgroundSize,position:frame.style.backgroundPosition,repeat:frame.style.backgroundRepeat});frame.style.backgroundImage=`url(${JSON.stringify(poster)})`;frame.style.backgroundSize='contain';frame.style.backgroundPosition='center';frame.style.backgroundRepeat='no-repeat';}
 });}catch{restore();flushSync(update);settleLayout();return;}
 const current={transition,restore};active=current;
 void transition.ready.catch(()=>{});void transition.updateCallbackDone.catch(()=>{});
 void transition.finished.catch(()=>{}).finally(()=>{if(active!==current)return;active=null;restore();library.querySelector('.clips-grid')?.dispatchEvent(new Event('layout-settled'));});
}
