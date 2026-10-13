import {useMemo,useState,useCallback,useRef,useEffect} from 'react';
import {FolderOpen,RefreshCw,Filter,X,LocateFixed} from 'lucide-react';
import type {Result,HudField,HudEnrichmentMode} from './shared';
import {HudFieldPicker,hudFields} from './HudSettings';
import {recordingTime} from './clipStats';
import {groupRecordingDays} from './clipTimeline';
import VirtualClips from './VirtualClips';
import FluidChoices from './FluidChoices';
import DesignIcon from './DesignIcon';
import InfoTip from './InfoTip';
import LibrarySortMenu from './LibrarySortMenu';
import StyledSelect from './StyledSelect';
import MotionDisclosure from './MotionDisclosure';
import {useMotionPresence} from './surfaceMotion';
import {compareLibraryClips,type LibrarySort} from './librarySort';
import {cancelLibraryViewReveal,revealLibraryView} from './libraryViewReveal';
export type ClipView='detail'|'grid'|'list';
export interface LibraryPreferences {view:ClipView;source:string;descending:boolean;query:string;date?:string;sort?:LibrarySort;minKills?:number;minDamage?:number;minAssists?:number;minDuration?:number;keepUnknown?:boolean;account?:string;weapon?:string}
export default function ClipLibrary({results,selected,onSelect,reduced,disabled,onOpen,onTask,onDirectory,preferences,onPreferences,playback,loading=false,error='',onRefresh,onDismissError,canIgnoreError=false,onIgnoreError,onImport,onAddRoot,onEnrich,deleting,onDelete,deleteDisabled}:{results:Result[];selected:string|null;onSelect:(id:string|null)=>void;reduced:boolean;disabled:boolean;onOpen:(path:string,folder:boolean)=>void;onTask:()=>void;onDirectory:()=>void;preferences:LibraryPreferences;onPreferences:(patch:Partial<LibraryPreferences>)=>void;playback:Map<string,number>;loading?:boolean;error?:string;onRefresh:()=>void;onDismissError:()=>void;canIgnoreError?:boolean;onIgnoreError:()=>void;onImport:()=>void;onAddRoot:()=>void;onEnrich:(files:string[],fields:HudField[],mode:HudEnrichmentMode)=>Promise<void>;deleting:string|null;onDelete:(file:string)=>void;deleteDisabled:boolean}){
 const {view,source,query}=preferences,[filters,setFilters]=useState(false);
 const [hudPanel,setHudPanel]=useState(false),[hudRunning,setHudRunning]=useState(false),[hudError,setHudError]=useState(''),[hudSelection,setHudSelection]=useState<HudField[]>(hudFields.map(field=>field.key)),[hudScope,setHudScope]=useState<'visible'|'selected'>('visible'),[hudMode,setHudMode]=useState<HudEnrichmentMode>('missing');
 async function enrich(){setHudRunning(true);setHudError('');try{const paths=hudScope==='selected'&&selected?[selected]:clips.map(row=>row.clip.path);await onEnrich(paths,hudSelection,hudMode);setHudPanel(false);}catch(error){setHudError(String(error).replace(/^Error: /,''));}finally{setHudRunning(false);}}
 const lastError=useRef(error);if(error)lastError.current=error;
 const actions=useRef({onSelect,onOpen,onDelete});actions.current={onSelect,onOpen,onDelete};
 const deleteClip=useCallback((file:string)=>actions.current.onDelete(file),[]);
 const selectClip=useCallback((id:string|null)=>actions.current.onSelect(id),[]),openClip=useCallback((file:string,folder:boolean)=>actions.current.onOpen(file,folder),[]);
 const all=useMemo(()=>{const seen=new Set<string>();return results.flatMap((r,sourceIndex)=>r.clips.map((clip,i)=>({clip,result:r,sourceIndex,index:i+1,identity:clip.path||r.source+'-'+i}))).filter(r=>{const key=r.identity.toLowerCase();if(seen.has(key))return false;seen.add(key);return true;});},[results]);
 const dateFor=(row:typeof all[number])=>(row.clip.recordedAt||recordingTime(row.clip.source||row.result.source)||'').slice(0,10);
 const clips=useMemo(()=>all.filter(row=>{
  if(source&&row.result.source!==source)return false;
  if(preferences.date&&(dateFor(row)||'unknown')!==preferences.date)return false;
  if(preferences.account&&row.clip.accountName?.toLocaleLowerCase()!==preferences.account.toLocaleLowerCase())return false;
  if(preferences.weapon&&!row.clip.weapons.some(weapon=>weapon===preferences.weapon))return false;
  if(query&&!([row.clip.name,row.clip.source||row.result.source,...row.clip.weapons].join(' ').toLowerCase().includes(query.toLowerCase())))return false;
  if((preferences.minDuration||0)>0&&Number.isFinite(row.clip.duration)&&row.clip.duration<(preferences.minDuration||0))return false;
  if((preferences.minKills||0)>0){const n=row.clip.kills,partial=row.clip.statisticsPartial?.kills;if(n===null||partial&&n<(preferences.minKills||0)){if(preferences.keepUnknown===false)return false;}else if(n<(preferences.minKills||0))return false;}
  for(const [key,minimum] of [['damage',preferences.minDamage],['assists',preferences.minAssists]] as const){if(!minimum)continue;const n=row.clip[key],partial=row.clip.statisticsPartial?.[key];if(n==null||partial&&n<minimum){if(preferences.keepUnknown===false)return false;}else if(n<minimum)return false;}
  return true;
 }).sort((a,b)=>compareLibraryClips(a.clip,b.clip,preferences.sort||'recent',preferences.descending,a.result.source,b.result.source)||a.sourceIndex-b.sourceIndex||a.clip.start-b.clip.start),[all,preferences]);
 const timelineItems=useMemo(()=>groupRecordingDays(clips,preferences.sort||'recent').flatMap(group=>group.items),[clips,preferences.sort]);
 const dates=[...new Set(all.map(r=>dateFor(r)||'unknown'))].sort().reverse(),sources=[...new Set(results.filter(r=>r.clips.length).map(r=>r.source))];
 const accounts=[...new Set(all.map(row=>row.clip.accountName).filter((name):name is string=>!!name))].sort(),weapons=[...new Set(all.flatMap(row=>row.clip.weapons).filter(name=>!['未知枪','—枪'].includes(name)))].sort();
 const scrollRoot=useRef<HTMLDivElement>(null),locator=useRef<HTMLButtonElement>(null),[offscreenPlayer,setOffscreenPlayer]=useState<string|null>(null);
 useEffect(()=>()=>cancelLibraryViewReveal(),[]);
 useEffect(()=>{if(reduced)cancelLibraryViewReveal();},[reduced]);
 const canLocate=!!selected&&offscreenPlayer===selected&&clips.some(row=>row.clip.path===selected),locatorPresent=useMotionPresence(canLocate,locator);
 useEffect(()=>{
  setOffscreenPlayer(null);
  const root=scrollRoot.current,frame=root?.querySelector<HTMLElement>('.clip-card[data-selected="true"] .media-frame');
  if(!selected||!root||!frame)return;
  // Observe the picture itself: the controls or card footer may still be visible.
  let live=true;
  const observer=new IntersectionObserver(([entry])=>{
   if(live)setOffscreenPlayer(entry.isIntersecting&&entry.intersectionRect.width>0&&entry.intersectionRect.height>0?null:selected);
  },{root,threshold:[0,.001]});
  observer.observe(frame);
  return()=>{live=false;observer.disconnect();};
 },[selected,clips,view]);
 function locatePlayer(){
  const root=scrollRoot.current,frame=root?.querySelector<HTMLElement>('.clip-card[data-selected="true"] .media-frame');
  if(!root||!frame)return;
  root.scrollTo({top:Math.max(0,root.scrollTop+frame.getBoundingClientRect().top-root.getBoundingClientRect().top-root.clientTop-12),behavior:reduced?'instant':'smooth'});
 }
 return <div className="clip-library" id="page-clips" role="tabpanel" aria-labelledby="tab-clips">
  <div className="page-heading"><div className="heading-with-info"><h1>整理片段</h1><button className="icon-button" aria-label="添加历史输出目录" onClick={onAddRoot}><FolderOpen size={17}/></button><div className="library-heading-actions">{locatorPresent&&<button ref={locator} className="icon-button library-player-locator" data-motion-surface aria-label="定位正在播放" title="定位正在播放" aria-hidden={!canLocate} inert={!canLocate} onClick={locatePlayer}><LocateFixed size={17}/></button>}<button className="icon-button library-refresh" aria-label="刷新片段库" onClick={onRefresh} disabled={loading}><RefreshCw size={17}/></button></div></div><p>{loading&&!all.length?'正在载入':clips.length+' 段'}</p></div>
  <div className="library-toolbar"><div className="library-controls">
   <button className="browse-filter-toggle" aria-expanded={filters} onClick={()=>setFilters(!filters)}><Filter size={14}/>筛选</button>
   <button className="browse-filter-toggle" aria-expanded={hudPanel} disabled={disabled||hudRunning} onClick={()=>setHudPanel(!hudPanel)}>{hudRunning?'正在识别…':'补充 HUD'}</button>
   <LibrarySortMenu value={preferences.sort||'recent'} onChange={sort=>onPreferences({sort,descending:true})}/>
  </div><FluidChoices className="view-switch" label="片段视图" reduced={reduced} value={view} onChange={next=>revealLibraryView(scrollRoot.current,()=>onPreferences({view:next}),!reduced&&next!==view)} options={(['detail','grid','list'] as const).map((value,i)=>({value,label:['详细','网格','列表'][i],content:<><DesignIcon name={value}/>{['详细','网格','列表'][i]}</>}))}/></div>
  <MotionDisclosure open={filters}><section className="browse-filter-panel" aria-label="浏览筛选">
   <div className="browse-heading"><b>浏览条件</b><InfoTip label="浏览筛选说明" text="这里只筛选历史库显示。处理时不保留新输出的阈值在首页的片段过滤中配置。"/><button className="icon-button" aria-label="关闭浏览筛选" onClick={()=>setFilters(false)}><X size={16}/></button></div>
   <label className="library-filter-field"><span>录像来源</span><StyledSelect label="录像来源" value={source} onChange={source=>onPreferences({source})} options={[{value:'',label:'所有来源'},...sources.map(value=>({value,label:value.split(/[\\/]/).pop()||value}))]}/></label>
   <label className="library-filter-field"><span>来源日期</span><StyledSelect label="来源日期" value={preferences.date||''} onChange={date=>onPreferences({date})} options={[{value:'',label:'全部日期'},...dates.map(date=>({value:date,label:date==='unknown'?'日期未识别':date}))]}/></label>
   <label className="library-filter-field"><span>本人账号</span><StyledSelect label="本人账号筛选" value={preferences.account||''} onChange={account=>onPreferences({account})} options={[{value:'',label:'所有账号'},...accounts.map(name=>({value:name,label:name}))]}/></label>
   <label className="library-filter-field"><span>武器</span><StyledSelect label="武器筛选" value={preferences.weapon||''} onChange={weapon=>onPreferences({weapon})} options={[{value:'',label:'所有武器'},...weapons.map(name=>({value:name,label:name}))]}/></label>
   <label className="library-filter-field"><span>搜索</span><input type="search" aria-label="搜索片段" placeholder="原文件、片段名或枪械" value={query} onChange={e=>onPreferences({query:e.target.value})}/></label>
   <label className="library-filter-field"><span>最低击杀</span><input type="number" aria-label="浏览最低击杀" min="0" max="60" value={preferences.minKills||0} onChange={e=>onPreferences({minKills:Math.max(0,e.target.valueAsNumber||0)})}/></label>
   <label className="library-filter-field"><span>最短时长（秒）</span><input type="number" aria-label="浏览最短时长" min="0" max="86400" value={preferences.minDuration||0} onChange={e=>onPreferences({minDuration:Math.max(0,e.target.valueAsNumber||0)})}/></label>
   <label className="library-filter-field"><span>最低伤害</span><input type="number" aria-label="浏览最低伤害" min="0" max="20000" value={preferences.minDamage||0} onChange={e=>onPreferences({minDamage:Math.max(0,e.target.valueAsNumber||0)})}/></label>
   <label className="library-filter-field"><span>最低助攻</span><input type="number" aria-label="浏览最低助攻" min="0" max="99" value={preferences.minAssists||0} onChange={e=>onPreferences({minAssists:Math.max(0,e.target.valueAsNumber||0)})}/></label>
   <label className="library-filter-check"><input type="checkbox" checked={preferences.keepUnknown!==false} onChange={e=>onPreferences({keepUnknown:e.target.checked})}/>保留计数未知或下界待核验</label>
  </section></MotionDisclosure>
  <MotionDisclosure open={hudPanel}><section className="browse-filter-panel hud-enrichment-panel" aria-label="补充HUD信息"><div className="browse-heading"><b>补充已导出片段的信息</b><button className="icon-button" aria-label="关闭HUD补充选项" disabled={hudRunning} onClick={()=>setHudPanel(false)}><X size={16}/></button></div><p>{hudMode==='refresh'?'重新读取所选信息并替换已有结果；无法确认时显示 —。':'只补充所选信息中缺失或未确认的字段，已确认的结果保留。'}</p><HudFieldPicker value={hudSelection} disabled={hudRunning} onChange={setHudSelection}/><label className="library-filter-field"><span>识别模式</span><StyledSelect label="HUD识别模式" value={hudMode} disabled={hudRunning} onChange={setHudMode} options={[{value:'missing',label:'未识别片段'},{value:'refresh',label:'重新识别'}]}/></label><label className="library-filter-field"><span>范围</span><StyledSelect label="HUD补充范围" value={hudScope} disabled={hudRunning} onChange={setHudScope} options={[{value:'visible',label:`当前筛选的 ${clips.length} 个片段`},{value:'selected',label:'当前播放片段',disabled:!selected}]}/></label><button className="primary" disabled={hudRunning||!hudSelection.length||!clips.length} onClick={()=>void enrich()}>{hudRunning?'正在识别…':hudMode==='refresh'?'开始重新识别':'开始补充'}</button>{hudError&&<p role="alert">{hudError}</p>}</section></MotionDisclosure>
  <MotionDisclosure open={!!error}><div className="library-error" role="alert"><span>{error||lastError.current}</span><div className="library-error-actions"><button onClick={onRefresh} disabled={loading}>重试</button>{canIgnoreError&&<button onClick={onIgnoreError} disabled={loading} title="忽略这些记录，下次启动不再读取">忽略</button>}<button className="icon-button" aria-label="关闭错误提示" onClick={onDismissError}><X size={16}/></button></div></div></MotionDisclosure>
  {loading&&!all.length?<div className="empty-clips" role="status"><RefreshCw size={32}/><h2>正在载入历史片段</h2></div>:!clips.length?<div className="empty-clips"><FolderOpen size={36}/><h2>{all.length?'没有符合条件的片段':'片段库还是空的'}</h2><button className="primary" onClick={()=>all.length?onPreferences({source:'',date:'',query:'',account:'',weapon:'',minKills:0,minDamage:0,minAssists:0,minDuration:0}):onImport()}>{all.length?'清除浏览条件':'回开始导入录像'}</button></div>:<div ref={scrollRoot} className="library-scroll" tabIndex={0} role="region" aria-label="片段列表"><VirtualClips items={timelineItems} deleting={deleting} onDelete={deleteClip} view={view} selected={selected} reduced={reduced} disabled={disabled} deleteDisabled={deleteDisabled||hudRunning} playback={playback} onSelect={selectClip} onOpen={openClip}/></div>}
 </div>;
}
