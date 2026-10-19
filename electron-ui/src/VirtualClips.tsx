import {useCallback,useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import type {Clip,Result} from './shared';
import type {ClipDetailFilter} from './libraryFilters';
import type {ClipView} from './ClipLibrary';
import {displayRatio} from './mediaGeometry';
import {recordingDay,dayLabel} from './clipTimeline';
import ClipCard from './ClipCard';
import FluidLayout from './FluidLayout';
type Item={clip:Clip;result:Result;index:number;identity:string};
type Row={key:string;indices:number[];day?:string;count?:number};
export default function VirtualClips({items,timeline,onFilter,selected,view,playback=false,reduced,disabled,deleteDisabled,deleting,onSelect,onOpen,onDelete}:{items:Item[];onFilter:(filter:ClipDetailFilter)=>void;timeline:boolean;selected:string|null;view:ClipView;playback?:boolean;reduced:boolean;disabled:boolean;deleteDisabled:boolean;deleting:string|null;onSelect:(id:string|null)=>void;onOpen:(file:string,folder:boolean)=>void;onDelete:(file:string)=>void}){
 const layoutView=playback?'playback':view;
 const wrapper=useRef<HTMLDivElement>(null),heights=useRef(new Map<string,number>()),rowsRef=useRef<Row[]>([]),committedKeys=useRef(new Set<string>()),retained=useRef(new Set<string>()),transition=useRef({items,view:layoutView,selected}),[dimensions,setDimensions]=useState({width:1000,columns:2,gap:16,height:600}),[scroll,setScroll]=useState(0),[measurement,setMeasurement]=useState(0),[geometry,setGeometry]=useState(0),[,release]=useState(0);
 if(transition.current.items!==items||transition.current.view!==layoutView||transition.current.selected!==selected){retained.current=new Set(committedKeys.current);transition.current={items,view:layoutView,selected};}
 const notifyGeometry=useCallback(()=>setGeometry(n=>n+1),[]);
 const rows=useMemo(()=>{
  const rows:Row[]=[],columns=dimensions.columns,groups=new Map<string,number[]>();
  items.forEach((item,i)=>{const day=timeline?recordingDay(item.clip,item.result.source):'';const indices=groups.get(day)||[];indices.push(i);groups.set(day,indices);});
  for(const [day,original]of groups){
   if(timeline)rows.push({key:'date:'+day,day,count:original.length,indices:[]});const indices=[...original];
   let group:number[]=[];const push=()=>{if(group.length){rows.push({key:layoutView+':'+Math.round(dimensions.width)+':'+Math.round(dimensions.height)+':'+group.map(i=>items[i].identity).join('|'),indices:group});group=[];}};
   for(const i of indices){group.push(i);if(group.length===columns)push();}push();
  }
  return rows;
 },[items,timeline,layoutView,dimensions]);rowsRef.current=rows;
 const layout=useMemo(()=>{let y=0;return rows.map(row=>{const top=y,columns=dimensions.columns,width=(dimensions.width-dimensions.gap*(columns-1))/columns,estimate=row.day!==undefined?(playback?28:40):Math.max(...row.indices.map(i=>{if(playback)return 100;const c=items[i].clip,ratio=displayRatio(c.media)||16/9;if(view==='list')return Math.max(160,Math.min(300,(innerWidth<=820?200:248)/ratio));return Math.min(360,width/ratio)+(view==='detail'?450:260);})),height=heights.current.get(row.key)||estimate;y+=height+dimensions.gap;return{...row,top,height};});},[rows,items,view,playback,dimensions,measurement]);
 const materialized=new Set<number>();let first=layout.findIndex(row=>row.top+row.height>=scroll),last=layout.findIndex(row=>row.top>scroll+dimensions.height);if(first<0)first=Math.max(0,layout.length-1);if(last<0)last=layout.length;for(let i=Math.max(0,first-2);i<Math.min(layout.length,last+2);i++)materialized.add(i);for(let i=0;i<rows.length;i++)if(rows[i].indices.some(n=>items[n].clip.path===selected||retained.current.has(items[n].identity)))materialized.add(i);
 const positions=new Map<number,{row:number;column:number}>();for(const row of materialized)rows[row]?.indices.forEach((index,column)=>positions.set(index,{row,column}));
 useLayoutEffect(()=>{committedKeys.current=new Set([...positions.keys()].map(i=>items[i].identity));});
 useLayoutEffect(()=>{
  const grid=wrapper.current?.firstElementChild as HTMLDivElement|undefined,scroller=grid?.closest<HTMLElement>('.library-scroll');if(!grid||!scroller)return;let raf=0;
  const update=()=>{const style=getComputedStyle(grid),next={width:grid.clientWidth,columns:Math.max(1,Number.parseInt(style.getPropertyValue('--clip-columns'),10)||1),gap:parseFloat(style.rowGap)||16,height:scroller.clientHeight};setDimensions(old=>Object.keys(next).some(k=>next[k as keyof typeof next]!==old[k as keyof typeof old])?next:old);};
  const measure=()=>{const found=new Map<number,number>();for(const el of grid.querySelectorAll<HTMLElement>(':scope > [data-layout-row]')){const row=Number(el.dataset.layoutRow);found.set(row,Math.max(found.get(row)||0,el.offsetHeight));}let changed=false;for(const [row,height]of found){const key=rowsRef.current[row]?.key;if(key&&height>0&&Math.abs((heights.current.get(key)||0)-height)>.5){heights.current.set(key,height);changed=true;}}if(changed)setMeasurement(n=>n+1);};
  const readScroll=()=>setScroll(scroller.scrollTop-(grid.getBoundingClientRect().top-scroller.getBoundingClientRect().top+scroller.scrollTop-scroller.clientTop));
  const measureNow=()=>{update();measure();readScroll();};
  const onScroll=()=>{if(!raf)raf=requestAnimationFrame(()=>{raf=0;readScroll();});};const observer=new ResizeObserver(measureNow);observer.observe(grid);observer.observe(scroller);grid.addEventListener('layout-settled',measure);grid.addEventListener('library-layout-measure',measureNow);scroller.addEventListener('scroll',onScroll,{passive:true});update();readScroll();return()=>{observer.disconnect();grid.removeEventListener('layout-settled',measure);grid.removeEventListener('library-layout-measure',measureNow);scroller.removeEventListener('scroll',onScroll);cancelAnimationFrame(raf);};
 },[view,playback]);
 useEffect(()=>{const grid=wrapper.current?.firstElementChild;if(!grid)return;const settled=()=>{if(retained.current.size){retained.current.clear();release(n=>n+1);}};grid.addEventListener('layout-settled',settled);return()=>grid.removeEventListener('layout-settled',settled);},[]);
 const allKeys=useMemo(()=>items.map(i=>i.identity),[items]);
 const revision=layoutView+':'+selected+':'+geometry+':'+measurement+':'+Math.round(dimensions.width)+':'+rows.map(r=>r.key).join('|')+':'+[...positions.keys()].join('|');
 return <div ref={wrapper} className="virtual-clips"><FluidLayout positioned allKeys={allKeys} className={'clips-grid view-'+layoutView} style={{gridTemplateRows:layout.map((row,i)=>materialized.has(i)?'auto':row.height+'px').join(' ')}} reduced={reduced} revision={revision}>
  {rows.map((row,i)=>row.day!==undefined&&materialized.has(i)?<div key={row.key} className="clip-day-heading" data-identity={"date:"+row.day} data-layout-row={i} data-date={row.day||'unknown'} style={{gridRow:i+1,gridColumn:'1/-1'}} role="heading" aria-level={2}><time dateTime={row.day||undefined}>{dayLabel(row.day)}</time><span>{row.count} 段</span></div>:null)}
  {items.map(({clip,result,index,identity},i)=>{const position=positions.get(i);return position?<ClipCard key={identity} clip={clip} source={result.source} onFilter={onFilter} index={index} identity={identity} position={i+1} total={items.length} layoutRow={position.row} layoutColumn={position.column} view={view} playback={playback} current={!!clip.path&&selected===clip.path} disabled={disabled||!clip.path} deleting={deleting===clip.path} deleteDisabled={disabled||deleteDisabled||!!deleting} onSelect={onSelect} onOpen={onOpen} onDelete={onDelete} onGeometryChange={notifyGeometry}/>:null;})}
 </FluidLayout></div>;
}
