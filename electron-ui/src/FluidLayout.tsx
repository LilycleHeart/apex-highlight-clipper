import {Component,useCallback,useLayoutEffect,useRef,type CSSProperties,type ReactNode} from 'react';
type Box={x:number;y:number;width:number;height:number};
class BeforeLayout extends Component<{revision:string;capture:()=>Map<string,Box>;snapshot:(value:Map<string,Box>)=>void;children:ReactNode}>{
 getSnapshotBeforeUpdate(previous:Readonly<typeof this.props>){return previous.revision!==this.props.revision?this.props.capture():null;}
 componentDidUpdate(_previous:Readonly<typeof this.props>,_state:unknown,snapshot:Map<string,Box>|null){if(snapshot)this.props.snapshot(snapshot);}
 render(){return this.props.children;}
}
export default function FluidLayout({children,revision,reduced,className,style,positioned=false,allKeys=[]}:{children:ReactNode;revision:string;reduced:boolean;className:string;style?:CSSProperties;positioned?:boolean;allKeys?:string[]}){
 const root=useRef<HTMLDivElement>(null),snapshots=useRef(new Map<string,Box>()),previousMode=useRef(className),seen=useRef(new Set<string>());
 const collection=allKeys.join('\0'),snapshotRevision=revision+':'+collection;
 const capture=useCallback(()=>{const map=new Map<string,Box>();for(const el of root.current?.querySelectorAll<HTMLElement>(':scope > .clip-slot,:scope > .clip-day-heading')||[]){const r=el.getBoundingClientRect();map.set(el.dataset.identity!,{x:r.x,y:r.y,width:r.width,height:r.height});}return map;},[]);
 useLayoutEffect(()=>{
  const node=root.current;if(!node)return;
  const elements=[...node.querySelectorAll<HTMLElement>(':scope > .clip-slot,:scope > .clip-day-heading')],modeChanged=previousMode.current!==className;previousMode.current=className;
  const viewport=node.closest('.library-scroll')?.getBoundingClientRect()||{top:0,bottom:innerHeight},animations:Animation[]=[];
  let live=true,entryIndex=0;
  if(!positioned){const columns=getComputedStyle(node).gridTemplateColumns.split(' ').length,chosen=elements.findIndex(el=>el.dataset.selected==='true'),group=chosen>=0?Math.floor(chosen/columns)*columns:-1;elements.forEach((el,i)=>el.style.order=String(i===chosen?group*2:i>=group&&i<group+columns&&group>=0?i*2+1:i*2));}
  for(const el of elements){
   // Animating dimensions reflows grid rows during virtual-list measurement.
   // Keep final geometry stable and animate position or opacity only.
   for(const property of ['translate','scale','width','height','opacity','clip-path'])el.style.removeProperty(property);
   const key=el.dataset.identity!,r=el.getBoundingClientRect(),from=snapshots.current.get(key),fresh=!seen.current.has(key),visible=r.bottom>viewport.top&&r.top<viewport.bottom;
   seen.current.add(key);el.dataset.surfaceProgress='1';el.dataset.entryProgress='1';
   const resized=!!from&&(Math.abs(from.width-r.width)>1||Math.abs(from.height-r.height)>1);
   if(reduced||!visible||document.documentElement.dataset.libraryReveal)continue;
   if(modeChanged||resized||fresh){animations.push(el.animate([{opacity:(modeChanged||resized)?0.75:0},{opacity:1}],{duration:240,delay:fresh&&!modeChanged?Math.min(entryIndex++*35,140):0,easing:'cubic-bezier(.2,.9,.25,1)'}));}
   else if(from){const x=from.x-r.x,y=from.y-r.y;if(Math.abs(x)+Math.abs(y)>.5)animations.push(el.animate([{translate:`${x}px ${y}px`},{translate:'0 0'}],{duration:320,easing:'cubic-bezier(.2,.9,.25,1)'}));}
  }
  const settle=()=>{if(!live||document.documentElement.dataset.libraryReveal)return;for(const el of elements)if(el.dataset.selected==='true')el.dispatchEvent(new Event('surface-settled'));node.dispatchEvent(new Event('layout-settled'));};
  if(animations.length)void Promise.all(animations.map(animation=>animation.finished.catch(()=>{}))).then(settle);else queueMicrotask(settle);
  return()=>{live=false;for(const animation of animations)animation.cancel();};
 },[revision,reduced,positioned,collection,className]);
 return <BeforeLayout revision={snapshotRevision} capture={capture} snapshot={value=>snapshots.current=value}><div ref={root} className={className} style={style} role="list">{children}</div></BeforeLayout>;
}
