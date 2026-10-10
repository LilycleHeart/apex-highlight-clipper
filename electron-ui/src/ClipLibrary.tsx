import {useMemo,useState,useCallback} from 'react';
import {FolderOpen,RefreshCw,Filter,X} from 'lucide-react';
import type {Result} from './shared';
import {recordingTime} from './clipStats';
import ClipCard from './ClipCard';
import FluidLayout from './FluidLayout';
import FluidChoices from './FluidChoices';
import DesignIcon from './DesignIcon';
import InfoTip from './InfoTip';
export type ClipView='detail'|'grid'|'list';
export interface LibraryPreferences {view:ClipView;source:string;descending:boolean;query:string;date?:string;sort?:'exported'|'recorded'|'source'|'duration';minKills?:number;minDuration?:number;onlyVerified?:boolean;keepUnknown?:boolean}
export default function ClipLibrary({results,selected,onSelect,reduced,disabled,onOpen,onTask,onDirectory,preferences,onPreferences,playback,loading=false,error='',onRefresh,onImport,onAddRoot}:{results:Result[];selected:string|null;onSelect:(id:string|null)=>void;reduced:boolean;disabled:boolean;onOpen:(path:string,folder:boolean)=>void;onTask:()=>void;onDirectory:()=>void;preferences:LibraryPreferences;onPreferences:(patch:Partial<LibraryPreferences>)=>void;playback:Map<string,number>;loading?:boolean;error?:string;onRefresh:()=>void;onImport:()=>void;onAddRoot:()=>void}){
 const {view,source,query}=preferences,[filters,setFilters]=useState(false),[geometry,setGeometry]=useState(0);
 const notifyGeometry=useCallback(()=>setGeometry(v=>v+1),[]);
 const all=useMemo(()=>{const seen=new Set<string>();return results.flatMap((r,sourceIndex)=>r.clips.map((clip,i)=>({clip,result:r,sourceIndex,index:i+1,identity:clip.path||r.source+'-'+i}))).filter(r=>{const key=r.identity.toLowerCase();if(seen.has(key))return false;seen.add(key);return true;});},[results]);
 const dateFor=(row:typeof all[number])=>(row.clip.recordedAt||recordingTime(row.clip.source||row.result.source)||'').slice(0,10);
 const clips=useMemo(()=>all.filter(row=>{
  if(source&&row.result.source!==source)return false;
  if(preferences.date&&(dateFor(row)||'unknown')!==preferences.date)return false;
  if(query&&!([row.clip.name,row.clip.source||row.result.source,...row.clip.weapons].join(' ').toLowerCase().includes(query.toLowerCase())))return false;
  if(preferences.onlyVerified&&!row.result.verified)return false;
  if((preferences.minDuration||0)>0&&Number.isFinite(row.clip.duration)&&row.clip.duration<(preferences.minDuration||0))return false;
  if((preferences.minKills||0)>0){const n=row.clip.kills,partial=row.clip.statisticsPartial?.kills;if(n===null||partial&&n<(preferences.minKills||0)){if(preferences.keepUnknown===false)return false;}else if(n<(preferences.minKills||0))return false;}
  return true;
 }).sort((a,b)=>{const sort=preferences.sort||'exported';let delta=sort==='duration'?a.clip.duration-b.clip.duration:sort==='source'?a.result.source.localeCompare(b.result.source)||a.clip.start-b.clip.start:sort==='recorded'?dateFor(a).localeCompare(dateFor(b))||(a.clip.recordedAt||'').localeCompare(b.clip.recordedAt||''): (a.clip.exportedAt||'').localeCompare(b.clip.exportedAt||'');return delta?delta*(preferences.descending?-1:1):a.sourceIndex-b.sourceIndex||a.clip.start-b.clip.start;}),[all,preferences]);
 const dates=[...new Set(all.map(r=>dateFor(r)||'unknown'))].sort().reverse(),sources=[...new Set(results.filter(r=>r.clips.length).map(r=>r.source))];
 return <div className="clip-library" id="page-clips" role="tabpanel" aria-labelledby="tab-clips">
  <div className="page-heading"><div className="heading-with-info"><h1>整理片段</h1><InfoTip label="片段库说明" text="自动聚合已知输出目录和历史任务的已导出片段。浏览筛选只改变显示，不修改任何录像或已有片段。任务记录可从片段详情追溯。"/><button className="icon-button" aria-label="添加历史输出目录" onClick={onAddRoot}><FolderOpen size={17}/></button><button className="icon-button library-refresh" aria-label="刷新片段库" onClick={onRefresh} disabled={loading}><RefreshCw size={17}/></button></div><p>{loading&&!all.length?'正在载入':clips.length+' 段'}</p></div>
  <div className="library-toolbar"><div className="library-controls">
   <select aria-label="录像来源" value={source} onChange={e=>onPreferences({source:e.target.value})}><option value="">所有来源</option>{sources.map(value=><option key={value} value={value}>{value.split(/[\\/]/).pop()}</option>)}</select>
   <select aria-label="来源日期" value={preferences.date||''} onChange={e=>onPreferences({date:e.target.value})}><option value="">全部日期</option>{dates.map(date=><option key={date} value={date}>{date==='unknown'?'日期未识别':date}</option>)}</select>
   <button className="browse-filter-toggle" aria-expanded={filters} onClick={()=>setFilters(!filters)}><Filter size={14}/>筛选</button>
   <select aria-label="片段排序" value={(preferences.sort||'exported')+':'+(preferences.descending?'desc':'asc')} onChange={e=>{const [sort,order]=e.target.value.split(':');onPreferences({sort:sort as LibraryPreferences['sort'],descending:order==='desc'});}}><option value="exported:desc">最近整理 ↓</option><option value="recorded:desc">录制时间 ↓</option><option value="recorded:asc">录制时间 ↑</option><option value="source:asc">原片时间 ↑</option><option value="duration:desc">片段时长 ↓</option></select>
  </div><FluidChoices className="view-switch" label="片段视图" reduced={reduced} value={view} onChange={view=>onPreferences({view})} options={(['detail','grid','list'] as const).map((value,i)=>({value,label:['详细','网格','列表'][i],content:<><DesignIcon name={value}/>{['详细','网格','列表'][i]}</>}))}/></div>
  {filters&&<section className="browse-filter-panel" aria-label="浏览筛选"><div className="browse-heading"><b>浏览条件</b><InfoTip label="浏览筛选说明" text="这里只筛选历史库显示。处理时不保留新输出的阈值在剪辑设置中单独配置。"/><button className="icon-button" aria-label="关闭浏览筛选" onClick={()=>setFilters(false)}><X size={16}/></button></div><label>搜索<input type="search" aria-label="搜索片段" placeholder="原文件、片段名或枪械" value={query} onChange={e=>onPreferences({query:e.target.value})}/></label><label>最低击杀<input type="number" aria-label="浏览最低击杀" min="0" max="60" value={preferences.minKills||0} onChange={e=>onPreferences({minKills:Math.max(0,e.target.valueAsNumber||0)})}/></label><label>最短时长（秒）<input type="number" aria-label="浏览最短时长" min="0" max="86400" value={preferences.minDuration||0} onChange={e=>onPreferences({minDuration:Math.max(0,e.target.valueAsNumber||0)})}/></label><label><input type="checkbox" checked={!!preferences.onlyVerified} onChange={e=>onPreferences({onlyVerified:e.target.checked})}/>仅已无损校验</label><label><input type="checkbox" checked={preferences.keepUnknown!==false} onChange={e=>onPreferences({keepUnknown:e.target.checked})}/>保留计数未知或下界待核验</label></section>}
  {error&&<div className="library-error" role="alert">{error}<button onClick={onRefresh}>重试</button></div>}
  {loading&&!all.length?<div className="empty-clips" role="status"><RefreshCw size={32}/><h2>正在载入历史片段</h2></div>:!clips.length?<div className="empty-clips"><FolderOpen size={36}/><h2>{all.length?'没有符合条件的片段':'片段库还是空的'}</h2><button className="primary" onClick={()=>all.length?onPreferences({source:'',date:'',query:'',minKills:0,minDuration:0,onlyVerified:false}):onImport()}>{all.length?'清除浏览条件':'回开始导入录像'}</button></div>:<div className="library-scroll" tabIndex={0} role="region" aria-label="片段列表"><FluidLayout className={'clips-grid view-'+view} reduced={reduced} revision={view+':'+selected+':'+geometry+':'+clips.map(c=>c.identity).join('|')}>
   {clips.map(({clip,result,index,identity})=><ClipCard key={identity} clip={clip} index={index} identity={identity} view={view} playback={playback} verified={result.verified} selected={!!clip.path&&selected===clip.path} disabled={disabled||!clip.path} reduced={reduced} onSelect={()=>onSelect(clip.path)} onCollapse={()=>onSelect(null)} onOpen={folder=>onOpen(clip.path,folder)} onGeometryChange={notifyGeometry}/>)}
  </FluidLayout></div>}
 </div>;
}
