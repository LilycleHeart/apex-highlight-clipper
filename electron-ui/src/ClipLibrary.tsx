import {useMemo} from 'react';
import {ArrowDown,ArrowUp,LayoutGrid,Rows3,PanelsTopLeft,FolderOpen} from 'lucide-react';
import type {Result,Clip} from './shared';
import {recordingTime} from './clipStats';
import ClipCard from './ClipCard';
import FluidLayout from './FluidLayout';
import FluidChoices from './FluidChoices';
export type ClipView='detail'|'grid'|'list';
export interface LibraryPreferences {view:ClipView;source:string;descending:boolean;query:string}
export default function ClipLibrary({results,selected,onSelect,reduced,disabled,onOpen,onTask,onDirectory,preferences,onPreferences,playback}:{preferences:LibraryPreferences;onPreferences:(patch:Partial<LibraryPreferences>)=>void;playback:Map<string,number>;results:Result[];selected:string|null;onSelect:(id:string|null)=>void;reduced:boolean;disabled:boolean;onOpen:(path:string,folder:boolean)=>void;onTask:()=>void;onDirectory:()=>void}){
 const {view,source,descending,query}=preferences;const setView=(view:ClipView)=>onPreferences({view}),setSource=(source:string)=>onPreferences({source}),setDescending=(descending:boolean)=>onPreferences({descending}),setQuery=(query:string)=>onPreferences({query});
 const clips=useMemo(()=>results.flatMap((r,sourceIndex)=>r.clips.map((clip,i)=>({clip,result:r,sourceIndex,index:i+1,identity:clip.path||`${r.source}-${i}`}))).filter(r=>(!source||r.result.source===source)&&(!query||[r.clip.name,...r.clip.weapons].join(' ').toLowerCase().includes(query.toLowerCase()))).sort((a,b)=>{
  const at=a.clip.recordedAt||recordingTime(a.result.source),bt=b.clip.recordedAt||recordingTime(b.result.source);
  // 无可靠日期的源单独保持来源顺序，避免用 mtime 编造录制时间。
  const delta=at&&bt?at.localeCompare(bt):at?-1:bt?1:a.sourceIndex-b.sourceIndex;
  return (delta||a.clip.start-b.clip.start||a.index-b.index)*(descending?-1:1);
 }),[results,source,descending,query]);
 return <div className="clip-library" id="page-clips" role="tabpanel" aria-labelledby="tab-clips"><div className="page-heading"><h1>整理片段</h1><p>{clips.length} 段{disabled?' · 状态预览':''}</p></div>
  <div className="library-toolbar"><select aria-label="录像来源" value={source} onChange={e=>setSource(e.target.value)}><option value="">全部录像</option>{results.map((r,i)=><option key={`${r.source}-${i}`} value={r.source}>{r.source.split(/[\\/]/).pop()}</option>)}</select><button className="sort-control" onClick={()=>setDescending(!descending)}>按原片时间{descending?<ArrowDown size={15}/>:<ArrowUp size={15}/>}</button><FluidChoices className="view-switch" label="片段视图" reduced={reduced} value={view} onChange={setView} options={([{id:'detail',label:'详细',Icon:PanelsTopLeft},{id:'grid',label:'网格',Icon:LayoutGrid},{id:'list',label:'列表',Icon:Rows3}] as const).map(({id,label,Icon})=>({value:id,label,content:<><Icon size={18}/>{label}</>}))}/></div>
  {results.length>2&&<input className="clip-search" type="search" aria-label="搜索片段" placeholder="搜索文件名或枪械" value={query} onChange={e=>setQuery(e.target.value)}/>}
  {!clips.length?<div className="empty-clips"><FolderOpen size={36}/><h2>{results.length?'没有符合筛选的片段':'片段会在这里等你'}</h2><p>{results.length?'调整录像来源或搜索条件':'完成一批录像，或打开已有任务记录'}</p><button className="primary" disabled={disabled} onClick={onTask}>打开任务记录</button></div>:<FluidLayout className={`clips-grid view-${view}`} reduced={reduced} revision={`${view}:${selected}:${clips.map(c=>c.identity).join('|')}`}>
   {clips.map(({clip,result,index,identity})=><ClipCard key={identity} clip={clip} index={index} identity={identity} view={view} playback={playback} verified={result.verified} selected={!!clip.path&&selected===clip.path} disabled={disabled||!clip.path} reduced={reduced} onSelect={()=>onSelect(clip.path)} onCollapse={()=>onSelect(null)} onOpen={folder=>onOpen(clip.path,folder)}/>)}
  </FluidLayout>}
  <div className="library-actions"><button className="secondary" disabled={disabled||!results.length} onClick={onDirectory}><FolderOpen size={16}/>打开输出目录</button><button className="text-button" disabled={disabled} onClick={onTask}>打开任务记录</button></div>
 </div>;
}
