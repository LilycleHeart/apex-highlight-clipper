import {flushSync} from 'react-dom';
import {cancelLibraryViewReveal} from './libraryViewReveal';

type Options={kind:'open'|'close'|'mode';file?:string;reduced?:boolean;afterLayout?:()=>void};
type Frame={box:DOMRect;picture?:DOMRect};
let active:(()=>void)|null=null;
export function cancelLibraryPlaybackMotion(){const finish=active;active=null;finish?.();}
const frame=(node:HTMLElement):Frame=>({box:node.getBoundingClientRect(),picture:node.querySelector<HTMLElement>('.clip-cover')?.getBoundingClientRect()});
const move=(parent:HTMLElement,node:HTMLElement,before:ChildNode|null=null)=>{if(typeof parent.moveBefore==='function'&&parent.isConnected&&node.isConnected)parent.moveBefore(node,before);else parent.insertBefore(node,before);};

/** Move the live portal host, not a snapshot or a second player. The card and
 * picture nodes retain their identity while the library changes its layout. */
export function transitionLibraryPlayback(shell:HTMLElement|null,library:HTMLElement|null,update:()=>void,options:Options){
 cancelLibraryPlaybackMotion();cancelLibraryViewReveal();
 const root=document.documentElement,old=shell?.querySelector<HTMLElement>('.watch-player')||[...library?.querySelectorAll<HTMLElement>('.clip-card[data-path]')||[]].find(node=>node.dataset.path===options.file),from=old?frame(old):null;
 root.dataset.libraryReveal='true';root.dataset.libraryPlayback=options.kind;
 const clear=()=>{delete root.dataset.libraryReveal;delete root.dataset.libraryPlayback;library?.querySelector('.clips-grid')?.dispatchEvent(new Event('layout-settled'));};
 const settle=()=>{for(let pass=0;pass<3;pass++){flushSync(()=>library?.querySelector('.clips-grid')?.dispatchEvent(new Event('library-layout-measure')));options.afterLayout?.();shell?.querySelector('.watch-player')?.dispatchEvent(new Event('player-layout'));}};
 flushSync(update);settle();
 const node=shell?.querySelector<HTMLElement>('.watch-player')||[...library?.querySelectorAll<HTMLElement>('.clip-card[data-path]')||[]].find(card=>card.dataset.path===options.file);
 const reduced=options.reduced||root.dataset.reduced==='true'||matchMedia('(prefers-reduced-motion: reduce)').matches;
 const host=node?.parentElement;
 if(!node||!from||!host?.classList.contains('clip-surface-host')||reduced||document.hidden){clear();return;}
 const to=frame(node),picture=node.querySelector<HTMLElement>('.clip-cover'),layer=document.createElement('div'),spacer=document.createElement('div'),saved=node.style.cssText,pictureStyle=picture?.style.cssText,scroll=node.scrollTop;
 const chrome=[...node.querySelectorAll<HTMLElement>('.watch-navigation,.watch-title-row,.watch-footer,.watch-card-info>.motion-disclosure,:scope>.clip-info,.player-controls')],chromeStyles=new Map(chrome.map(part=>[part,part.style.cssText])),chromeWidths=new Map(chrome.map(part=>[part,part.getBoundingClientRect().width]));
 layer.className='library-morph-layer '+(node.closest('.view-list')?'view-list':node.closest('.view-grid')?'view-grid':'');
 const viewport=shell!.getBoundingClientRect();layer.style.clipPath=`inset(${Math.max(0,viewport.top)}px ${Math.max(0,innerWidth-viewport.right)}px ${Math.max(0,innerHeight-viewport.bottom)}px ${Math.max(0,viewport.left)}px round 24px)`;
 const colors=getComputedStyle(node);for(const key of colors)if(key.startsWith('--'))layer.style.setProperty(key,colors.getPropertyValue(key));
 spacer.className='library-morph-spacer';spacer.style.width=to.box.width+'px';spacer.style.height=to.box.height+'px';host.before(spacer);document.body.appendChild(layer);move(layer,host);
 Object.assign(node.style,{position:'absolute',left:to.box.left+'px',top:to.box.top+'px',width:to.box.width+'px',height:to.box.height+'px',maxWidth:'none',maxHeight:'none',minHeight:'0',margin:'0',overflow:'hidden',boxSizing:'border-box'});
 node.dataset.libraryMorph='true';node.scrollTop=0;
 const animations:Animation[]=[],timing={duration:460,easing:'cubic-bezier(.22,.8,.24,1)',fill:'both' as FillMode};
 if(library)animations.push(library.animate([{opacity:.25,translate:options.kind==='close'?'0 8px':'16px 0'},{opacity:1,translate:'0 0'}],{duration:340,delay:60,easing:timing.easing,fill:'both'}));
 animations.push(node.animate([{left:from.box.left+'px',top:from.box.top+'px',width:from.box.width+'px',height:from.box.height+'px'},{left:to.box.left+'px',top:to.box.top+'px',width:to.box.width+'px',height:to.box.height+'px'}],timing));
 if(picture&&from.picture&&to.picture){
  // Keep the destination offset fixed while the outer width changes. Auto
  // centering here would shift the picture a second time during the morph.
  Object.assign(picture.style,{width:to.picture.width+'px',height:to.picture.height+'px',maxWidth:'none',marginLeft:(to.picture.left-to.box.left-parseFloat(colors.paddingLeft))+'px',marginRight:'0',transformOrigin:'top left'});
  const dx=from.picture.left-from.box.left-(to.picture.left-to.box.left),dy=from.picture.top-from.box.top-(to.picture.top-to.box.top),scale=from.picture.width/Math.max(1,to.picture.width);
  animations.push(picture.animate([{translate:`${dx}px ${dy}px`,scale},{translate:'0 0',scale:1}],timing));
 }
 for(const part of chrome){const width=chromeWidths.get(part)!;if(width){part.style.width=width+'px';part.style.minWidth=width+'px';}animations.push(part.animate([{opacity:0},{opacity:1}],{duration:220,delay:120,fill:'both'}));}
 let finished=false;
 const finish=()=>{if(finished)return;finished=true;for(const animation of animations)animation.cancel();node.style.cssText=saved;if(picture&&pictureStyle!==undefined)picture.style.cssText=pictureStyle;for(const [part,style]of chromeStyles)part.style.cssText=style;delete node.dataset.libraryMorph;if(spacer.parentElement)move(spacer.parentElement,host,spacer);spacer.remove();layer.remove();node.scrollTop=scroll;node.dispatchEvent(new Event('player-layout'));if(active===finish)active=null;clear();};
 active=finish;void Promise.all(animations.map(animation=>animation.finished.catch(()=>{}))).then(finish);
}
