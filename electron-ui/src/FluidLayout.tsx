import {useLayoutEffect,useRef,type ReactNode} from 'react';
import {NAV,sampleSpring,clamp,edgeGeometry} from './surfaceGeometry';
type Box={x:number;y:number;width:number;height:number;alpha?:number};
// Grid 流仍保持源码顺序；定位补偿只在当前元素上，绝不缩放媒体/文本平面。
export default function FluidLayout({children,revision,reduced,className}:{children:ReactNode;revision:string;reduced:boolean;className:string}){
 const root=useRef<HTMLDivElement>(null),visible=useRef(new Map<string,Box>()),finish=useRef(()=>{});
 useLayoutEffect(()=>{
  const node=root.current;if(!node)return;finish.current();
  let raf=0,last=0,elapsed=0,disposed=false;const elements=[...node.querySelectorAll<HTMLElement>(':scope > .clip-card')];
  const columns=getComputedStyle(node).gridTemplateColumns.split(' ').length;const chosen=elements.findIndex(el=>el.dataset.selected==='true'),group=chosen>=0?Math.floor(chosen/columns)*columns:-1;for(let i=0;i<elements.length;i++){elements[i].style.order=String(i===chosen?group*2:i>=group&&i<group+columns&&group>=0?i*2+1:i*2);}
  const origin=node.getBoundingClientRect();
  const jobs=elements.map(el=>{el.style.removeProperty('translate');el.style.removeProperty('width');el.style.removeProperty('height');const rect=el.getBoundingClientRect();const target={x:rect.x-origin.x,y:rect.y-origin.y,width:rect.width,height:rect.height};const key=el.dataset.identity!;const from=visible.current.get(key)??{...target,y:target.y+48,alpha:0};return{el,key,from,target};});
  function paint(q:number){
   // 先批量改尺寸，再读取网格自然位置：列表高度也连续变化，且每帧只需一次布局。
   for(const {el,key,from,target} of jobs){const box={x:from.x+(target.x-from.x)*q,y:from.y+(target.y-from.y)*q,width:from.width+(target.width-from.width)*q,height:from.height+(target.height-from.height)*q,alpha:(from.alpha??1)+(1-(from.alpha??1))*clamp(q)};visible.current.set(key,box);el.style.opacity=String(box.alpha);el.style.width=`${box.width}px`;el.style.height=`${box.height}px`;el.dataset.surfaceProgress=String(q);const path=el.querySelector<SVGPathElement>(':scope > .card-surface path');const svg=path?.ownerSVGElement;if(svg){svg.setAttribute('viewBox',`0 0 ${box.width} ${box.height}`);path!.setAttribute('d',edgeGeometry(box.width,box.height,q));}el.style.clipPath=`path('${edgeGeometry(box.width,box.height,q)}')`;}
   for(const {el,key} of jobs){const box=visible.current.get(key)!;el.style.translate=`${box.x-el.offsetLeft}px ${box.y-el.offsetTop}px`;}
  }
  function settle(){paint(1);for(const j of jobs){j.el.style.removeProperty('translate');j.el.style.removeProperty('width');j.el.style.removeProperty('height');j.el.style.removeProperty('clip-path');j.el.style.removeProperty('opacity');j.el.dispatchEvent(new Event('surface-settled'));}last=0;}
  function schedule(){if(!raf&&!document.hidden&&document.documentElement.dataset.hidden!=='true'&&!disposed)raf=requestAnimationFrame(tick);}
  function tick(t:number){raf=0;if(document.hidden||document.documentElement.dataset.hidden==='true'){last=0;return;}if(last)elapsed+=Math.min(.04,(t-last)/1000);last=t;paint(sampleSpring(0,1,elapsed));if(elapsed<NAV.duration)schedule();else settle();}
  const visibility=()=>{last=0;schedule();};document.addEventListener('visibilitychange',visibility);const hiddenObserver=new MutationObserver(visibility);hiddenObserver.observe(document.documentElement,{attributes:true,attributeFilter:['data-hidden']});
  if(reduced)settle();else{paint(0);schedule();}
  const resize=new ResizeObserver(()=>{if(elapsed>=NAV.duration||reduced){for(const j of jobs){const r=j.el.getBoundingClientRect(),o=node.getBoundingClientRect();j.target={x:r.x-o.x,y:r.y-o.y,width:r.width,height:r.height};visible.current.set(j.key,j.target);}settle();}});resize.observe(node);
  finish.current=()=>{disposed=true;cancelAnimationFrame(raf);for(const j of jobs){j.el.style.removeProperty('translate');j.el.style.removeProperty('width');j.el.style.removeProperty('height');j.el.style.removeProperty('clip-path');j.el.style.removeProperty('opacity');}resize.disconnect();hiddenObserver.disconnect();document.removeEventListener('visibilitychange',visibility);};return()=>finish.current();
 },[revision,reduced]);
 return <div ref={root} className={className}>{children}</div>;
}
