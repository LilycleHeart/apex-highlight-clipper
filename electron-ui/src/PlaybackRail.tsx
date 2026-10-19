import {useEffect,useLayoutEffect,useRef,useState,type ComponentProps,type RefObject} from 'react';
import type VirtualClips from './VirtualClips';
import ClipCard from './ClipCard';
import {libraryGroup} from './clipTimeline';

const STEP=328,GAP=12;
type Props=Pick<ComponentProps<typeof VirtualClips>,'items'|'view'|'sort'|'selected'|'disabled'|'deleteDisabled'|'deleting'|'onSelect'|'onOpen'|'onDelete'|'onFilter'>&{scrollPosition:RefObject<number|null>;initialIndex:number};
export default function PlaybackRail({items,view,sort='recent',selected,disabled,deleteDisabled,deleting,onSelect,onOpen,onDelete,onFilter,scrollPosition,initialIndex}:Props){
 const viewport=useRef<HTMLDivElement>(null),[window,setWindow]=useState({left:scrollPosition.current??initialIndex*STEP,width:1000});
 useLayoutEffect(()=>{const node=viewport.current;if(!node)return;node.scrollLeft=scrollPosition.current??initialIndex*STEP;const update=()=>setWindow({left:node.scrollLeft,width:node.clientWidth});const observer=new ResizeObserver(update);observer.observe(node);update();return()=>observer.disconnect();},[]);
 useEffect(()=>{const node=viewport.current;if(!node)return;const wheel=(event:WheelEvent)=>{if(event.ctrlKey||event.shiftKey||Math.abs(event.deltaX)>=Math.abs(event.deltaY))return;const before=node.scrollLeft;node.scrollLeft+=event.deltaY*(event.deltaMode===1?18:event.deltaMode===2?node.clientWidth:1);if(node.scrollLeft!==before)event.preventDefault();};node.addEventListener('wheel',wheel,{passive:false});return()=>node.removeEventListener('wheel',wheel);},[]);
 const start=Math.max(0,Math.floor(window.left/STEP)-2),end=Math.min(items.length,Math.ceil((window.left+window.width)/STEP)+2);
 return <div ref={viewport} className="playback-rail-scroll" aria-label="横向片段列表" tabIndex={0} onScroll={event=>{const node=event.currentTarget;scrollPosition.current=node.scrollLeft;setWindow({left:node.scrollLeft,width:node.clientWidth});}}><div className="playback-rail-track" role="list" style={{width:Math.max(0,items.length*STEP-GAP)}}>
  {items.map(({clip,result,index,identity},i)=>{if(!(i>=start&&i<end||clip.path===selected))return null;const group=libraryGroup(clip,result.source,sort),previous=i?libraryGroup(items[i-1].clip,items[i-1].result.source,sort):null;return <div key={identity} className="playback-rail-slot" data-group={group.key} style={{left:i*STEP,width:STEP-GAP}}><span className="playback-rail-group-label">{previous?.key!==group.key?group.label:''}</span><ClipCard playback compactPlayback current={clip.path===selected} clip={clip} source={result.source} identity={identity} index={index} position={i+1} total={items.length} view={view} disabled={disabled} deleteDisabled={deleteDisabled} deleting={deleting===clip.path} onSelect={onSelect} onOpen={onOpen} onDelete={onDelete} onFilter={onFilter} onGeometryChange={()=>{}}/></div>;})}
 </div></div>;
}
