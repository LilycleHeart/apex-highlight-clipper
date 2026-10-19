import {playerNameKey} from './libraryNames';
import {useMemo,useState,useCallback,useRef,useEffect,useLayoutEffect,type CSSProperties} from 'react';
import {FolderOpen,RefreshCw,Filter,X,Package,ListChecks,ListX,Share2,LoaderCircle} from 'lucide-react';
import type {Result,HudEnrichmentField} from './shared';
import {HudFieldPicker,enrichmentFields} from './HudSettings';
import {groupRecordingDays,recordingDay} from './clipTimeline';
import type {HudEnrichmentSession} from './useHudEnrichment';
import {ClipActionsContext} from './ClipActions';
import FilterControl from './FilterControl';
import DatePicker from './DatePicker';
import {dateFilterLabel,detailFilterPatch,matchesLibraryMetadata,type LibraryMetadataFilters,type ClipDetailFilter} from './libraryFilters';
import {weaponFor,ApexIcon,apexAsset,rankAsset} from './ClipDetails';
import TeammatePicker from './TeammatePicker';
import HeroPicker from './HeroPicker';
import {ammoGroups} from './weaponAmmo';
import VirtualClips from './VirtualClips';
import WatchPlayer from './WatchPlayer';
import PlaybackBrowserHeader from './PlaybackBrowserHeader';
import {displayRatio} from './mediaGeometry';
import FluidChoices from './FluidChoices';
import DesignIcon from './DesignIcon';
import InfoTip from './InfoTip';
import LibrarySortMenu from './LibrarySortMenu';
import StyledSelect from './StyledSelect';
import MotionDisclosure from './MotionDisclosure';
import {compareLibraryClips,type LibrarySort} from './librarySort';
import {cancelLibraryViewReveal,revealLibraryView} from './libraryViewReveal';
import {cancelLibraryPlaybackMotion,transitionLibraryPlayback} from './libraryPlaybackMotion';
export type ClipView='detail'|'grid'|'list';
export interface LibraryPreferences extends LibraryMetadataFilters {view:ClipView;source:string;descending:boolean;query:string;date?:string;sort?:LibrarySort;minKills?:number;minDamage?:number;minAssists?:number;minDuration?:number;keepUnknown?:boolean;account?:string;weapon?:string;hero?:string}
export default function ClipLibrary({results,selected,onSelect,reduced,disabled,onOpen,onTask,onDirectory,preferences,onPreferences:commitPreferences,excludedTeammates,onExcludeTeammate,playback,loading=false,error='',onRefresh,onDismissError,canIgnoreError=false,onIgnoreError,onImport,onAddRoot,hud,deleting,onDelete,deleteDisabled}:{results:Result[];selected:string|null;onSelect:(id:string|null)=>void;reduced:boolean;disabled:boolean;onOpen:(path:string,folder:boolean)=>void;onTask:()=>void;onDirectory:()=>void;preferences:LibraryPreferences;onPreferences:(patch:Partial<LibraryPreferences>)=>void;excludedTeammates:string[];onExcludeTeammate:(name:string,excluded:boolean)=>Promise<void>;playback:Map<string,number>;loading?:boolean;error?:string;onRefresh:()=>void;onDismissError:()=>void;canIgnoreError?:boolean;onIgnoreError:()=>void;onImport:()=>void;onAddRoot:()=>void;hud:HudEnrichmentSession;deleting:string|null;onDelete:(file:string)=>void;deleteDisabled:boolean}){
 const {view,source,query}=preferences,[filters,setFilters]=useState(false),[playbackFilters,setPlaybackFilters]=useState(false);
 const scrollRoot=useRef<HTMLDivElement>(null),browseAnchor=useRef<{path:string;top:number;scroll?:number}|null>(null),libraryReturn=useRef<{path:string;top:number;scroll:number}|null>(null);
 const onPreferences=(patch:Partial<LibraryPreferences>)=>{cancelLibraryPlaybackMotion();revealLibraryView(scrollRoot.current,()=>commitPreferences(patch),!reduced&&!Object.keys(patch).some(key=>['query','minKills','minDamage','minAssists','minDuration'].includes(key)));};
 const {panelOpen:hudPanel,setPanelOpen:setHudPanel,fields:hudSelection,setFields:setHudSelection,scope:hudScope,setScope:setHudScope,mode:hudMode,setMode:setHudMode,running:hudRunning,progress:hudProgress}=hud;
 const [hudInputError,setHudError]=useState('');const hudError=hudInputError||hud.job?.error||'';
 // Returning to the library exposes the retained task, including an off-page completion.
 useEffect(()=>{if(hud.job)hud.setPanelOpen(true);},[]);
 async function enrich(){if(hudScope==='selected'&&!selected){setHudError('请先选择要识别的片段');return;}const paths=hudScope==='selected'&&selected?[selected]:clips.map(row=>row.clip.path);setHudError('');try{await hud.run(paths,hudSelection,hudMode,'batch');}catch{/* The app-owned task keeps its failure or stop message. */}}
 const lastError=useRef(error);if(error)lastError.current=error;
 const actions=useRef({onSelect,onOpen,onDelete,onPreferences,selected});actions.current={onSelect,onOpen,onDelete,onPreferences,selected};
 const deleteClip=useCallback((file:string)=>actions.current.onDelete(file),[]);
 const selectClip=useCallback((id:string|null)=>{
  const root=scrollRoot.current;
  if(root&&!!id!==!!actions.current.selected){
   const cards=[...root.querySelectorAll<HTMLElement>('.clip-card[data-path]')],viewport=root.getBoundingClientRect();
   const first=cards.find(card=>{const r=card.getBoundingClientRect();return r.bottom>viewport.top&&r.top<viewport.bottom;});
   if(id){
    libraryReturn.current=first?{path:first.dataset.path!,top:first.getBoundingClientRect().top-viewport.top,scroll:root.scrollTop}:null;
    const card=cards.find(card=>card.dataset.path===id);browseAnchor.current=card&&root.scrollTop>1?{path:card.dataset.path!,top:card.getBoundingClientRect().top-viewport.top}:null;
   }else browseAnchor.current=libraryReturn.current;
  }
  if(!!id!==!!actions.current.selected){
   transitionLibraryPlayback(root?.closest<HTMLElement>('.clip-library-shell')||null,root,()=>{setPlaybackFilters(false);actions.current.onSelect(id);},{kind:id?'open':'close',file:id||actions.current.selected||undefined,reduced,afterLayout:()=>{
    const anchor=browseAnchor.current;if(!root||!anchor)return;const card=[...root.querySelectorAll<HTMLElement>('.clip-card[data-path]')].find(card=>card.dataset.path===anchor.path);if(card)root.scrollTop+=card.getBoundingClientRect().top-root.getBoundingClientRect().top-anchor.top;else if(anchor.scroll!==undefined)root.scrollTop=anchor.scroll;
   }});
  }else{cancelLibraryPlaybackMotion();actions.current.onSelect(id);}
 },[reduced]),openClip=useCallback((file:string,folder:boolean)=>actions.current.onOpen(file,folder),[]);
 const all=useMemo(()=>{const seen=new Set<string>();return results.flatMap((r,sourceIndex)=>r.clips.map((clip,i)=>({clip,result:r,sourceIndex,index:i+1,identity:clip.path||r.source+'-'+i}))).filter(r=>{const key=r.identity.toLowerCase();if(seen.has(key))return false;seen.add(key);return true;});},[results]);
 const active=all.find(row=>row.clip.path===selected),sessionRatio=useRef<number|null>(null);
 if(!active)sessionRatio.current=null;else if(sessionRatio.current===null)sessionRatio.current=displayRatio(active.clip.media)||16/9;
 // Opening/closing changes the available list width once. Keep the browsing
 // anchor through that reflow; changing recordings never scrolls the list.
 useLayoutEffect(()=>{
  const root=scrollRoot.current,anchor=browseAnchor.current;if(!root||!anchor)return;
  let raf=0,frames=0,stable=0,live=true;
  const cancel=()=>{live=false;cancelAnimationFrame(raf);if(browseAnchor.current===anchor)browseAnchor.current=null;};
  const restore=()=>{
   if(!live)return;const card=[...root.querySelectorAll<HTMLElement>('.clip-card[data-path]')].find(card=>card.dataset.path===anchor.path);
   if(card){const delta=card.getBoundingClientRect().top-root.getBoundingClientRect().top-anchor.top;if(Math.abs(delta)>.5){root.scrollTop+=delta;stable=0;}else stable++;}
   if(++frames<30&&stable<6)raf=requestAnimationFrame(restore);else cancel();
  };
  root.addEventListener('wheel',cancel,{passive:true});root.addEventListener('touchstart',cancel,{passive:true});raf=requestAnimationFrame(restore);
  return()=>{cancel();root.removeEventListener('wheel',cancel);root.removeEventListener('touchstart',cancel);};
 },[!!active]);
 const dateFor=(row:typeof all[number])=>recordingDay(row.clip,row.result.source);
 const clips=useMemo(()=>all.filter(row=>{
  if(!matchesLibraryMetadata(row.clip,row.result.source,preferences))return false;
  if(query&&!([row.clip.name,row.clip.source||row.result.source,...row.clip.weapons].join(' ').toLowerCase().includes(query.toLowerCase())))return false;
  if((preferences.minDuration||0)>0&&Number.isFinite(row.clip.duration)&&row.clip.duration<(preferences.minDuration||0))return false;
  if((preferences.minKills||0)>0){const n=row.clip.kills,partial=row.clip.statisticsPartial?.kills;if(n===null||partial&&n<(preferences.minKills||0)){if(preferences.keepUnknown===false)return false;}else if(n<(preferences.minKills||0))return false;}
  for(const [key,minimum] of [['damage',preferences.minDamage],['assists',preferences.minAssists]] as const){if(!minimum)continue;const n=row.clip[key],partial=row.clip.statisticsPartial?.[key];if(n==null||partial&&n<minimum){if(preferences.keepUnknown===false)return false;}else if(n<minimum)return false;}
  return true;
 }).sort((a,b)=>compareLibraryClips(a.clip,b.clip,preferences.sort||'recent',preferences.descending,a.result.source,b.result.source)||a.sourceIndex-b.sourceIndex||a.clip.start-b.clip.start),[all,preferences]);

 const [selectionMode,setSelectionMode]=useState(false),[checked,setChecked]=useState<Set<string>>(new Set()),[sharing,setSharing]=useState(false),[actionNotice,setActionNotice]=useState('');
 const sharingLock=useRef(false),recognizing=hud.job?.running&&hud.job.kind==='single'?hud.job.files[0]:null;
 useEffect(()=>{const available=new Set(all.map(row=>row.clip.path));setChecked(previous=>[...previous].some(file=>!available.has(file))?new Set([...previous].filter(file=>available.has(file))):previous);},[all]);
 function checkClip(file:string){if(!checked.has(file)&&checked.size>=100){setActionNotice('每次最多选择 100 个片段');return;}setChecked(previous=>{const next=new Set(previous);if(next.has(file))next.delete(file);else next.add(file);return next;});}
 function selectVisible(){if(clips.length>100){setActionNotice('每次最多分享 100 段，请缩小筛选范围后再全选');return;}setChecked(new Set(clips.map(row=>row.clip.path)));}
 async function share(files:string[]){if(sharingLock.current)return;sharingLock.current=true;setSharing(true);setActionNotice('正在打开 QQ 会话选择…');try{const result=await window.apex.shareClips(files);setActionNotice(`已将 ${result.count} 个片段交给 QQ，请在 QQ 窗口选择会话并发送。`);}catch(error){setActionNotice(String(error).replace(/^Error:\s*/,''));}finally{sharingLock.current=false;setSharing(false);}}
 async function recognize(file:string,fields:HudEnrichmentField[]){if(deleteDisabled||disabled)throw new Error('请先等待当前识别任务结束');setHudError('');return hud.run([file],fields,'refresh','single');}
 const timeline=(!preferences.sort||preferences.sort==='recent');
 const timelineItems=useMemo(()=>timeline?groupRecordingDays(clips).flatMap(group=>group.items):clips,[clips,timeline]);
 const activePosition=timelineItems.findIndex(item=>item.clip.path===selected);
 const dates=useMemo(()=>{const counts=new Map<string,number>();for(const row of all){const date=dateFor(row);if(date)counts.set(date,(counts.get(date)||0)+1);}return [...counts].map(([date,count])=>({date,count}));},[all]),sources=[...new Set(results.filter(r=>r.clips.length).map(r=>r.source))];
 const accounts=[...new Set(all.map(row=>row.clip.accountName).filter((name):name is string=>!!name))].sort();
 const teammates=[...new Map(all.flatMap(row=>row.clip.teammates||[]).map(player=>[playerNameKey(player.name),player.name])).values()].sort((a,b)=>a.localeCompare(b,'zh-CN'));
 const rankOrder=['unranked','rookie','bronze','silver','gold','platinum','diamond','master','predator'];
 const ranks=[...new Map(all.flatMap(row=>row.clip.rank?[{tier:row.clip.rank.tier,name:row.clip.rank.name}]:[]).map(rank=>[rank.tier,rank])).values()].sort((a,b)=>rankOrder.indexOf(a.tier)-rankOrder.indexOf(b.tier));
 const rankOptions=ranks.flatMap(rank=>{const icon=<img className="rank-filter-icon" src={rankAsset(rank.tier)} alt=""/>,divisions=[...new Set(all.filter(row=>row.clip.rank?.tier===rank.tier).map(row=>row.clip.rank?.division).filter((value):value is string=>!!value))].sort();return [{value:rank.tier,label:rank.name,icon},...divisions.map(division=>({value:rank.tier+':'+division,label:rank.name+' '+division,icon}))];});
 const weaponCounts=useMemo(()=>{const counts=new Map<string,number>();for(const {clip} of all)for(const name of new Set(clip.weapons)){if(!['未知枪','—枪'].includes(name))counts.set(name,(counts.get(name)||0)+1);}return counts;},[all]);
 const weapons=[...weaponCounts.keys()].sort();
 const heroes=useMemo(()=>{const values=new Map<string,{id:string;name:string;count:number}>();for(const {clip} of all){if(clip.hero){const old=values.get(clip.hero.id);values.set(clip.hero.id,{id:clip.hero.id,name:clip.hero.name,count:(old?.count||0)+1});}}return [...values.values()];},[all]);
 const weaponOptions=weapons.map(name=>{const weapon=weaponFor(name);return{value:name,label:name,meta:`${weaponCounts.get(name)} 段`,icon:weapon?<ApexIcon file={weapon.file} className="weapon-option-icon"/>:undefined,group:ammoGroups.find(group=>group.ids.includes(weapon?.id||''))?.label||'其他武器'};}).sort((a,b)=>{const order=(label:string)=>{const index=ammoGroups.findIndex(group=>group.label===label);return index<0?ammoGroups.length:index;};return order(a.group)-order(b.group)||a.label.localeCompare(b.label,'zh-CN');});
 function ammoHeading(group:string){const family=ammoGroups.find(family=>family.label===group);return <div className="ammo-group-heading" style={{'--ammo-accent':family?.color||'var(--card-accent)'} as CSSProperties}><span className="ammo-family-icons">{family?.icons.length?family.icons.map(icon=><img key={icon} src={apexAsset(`ammo/${icon}.svg`)} alt=""/>):<Package size={18}/>}</span><b>{group}</b><span className="ammo-group-count">{weaponOptions.filter(option=>option.group===group).length} 种</span></div>;}
 const filterClip=useCallback((filter:ClipDetailFilter)=>{actions.current.onPreferences(detailFilterPatch(filter));},[]);
 const clearFilters=()=>onPreferences({source:'',date:'',query:'',account:'',teammate:'',weapon:'',hero:'',rank:'',rankDivision:'',minKills:0,minDamage:0,minAssists:0,minDuration:0,keepUnknown:true});
 const activeFilters:{key:string;label:string;clear:Partial<LibraryPreferences>}[]=[];
 if(source)activeFilters.push({key:'来源',label:'来源：'+source.split(/[\\/]/).pop(),clear:{source:''}});
 if(preferences.date)activeFilters.push({key:'日期',label:'日期：'+dateFilterLabel(preferences.date),clear:{date:''}});
 for(const [key,label] of [['account','本人账号'],['teammate','队友'],['weapon','武器']] as const)if(preferences[key])activeFilters.push({key:label,label:label+'：'+preferences[key],clear:{[key]:''}});
 if(preferences.hero)activeFilters.push({key:'英雄',label:'英雄：'+(preferences.hero==='unknown'?'未识别':heroes.find(hero=>hero.id===preferences.hero)?.name||preferences.hero),clear:{hero:''}});
 if(preferences.rank)activeFilters.push({key:'模式段位',label:'模式/段位：'+(preferences.rank==='unknown'?'未识别':ranks.find(rank=>rank.tier===preferences.rank)?.name||preferences.rank)+(preferences.rankDivision?' '+preferences.rankDivision:''),clear:{rank:'',rankDivision:''}});
 if(query)activeFilters.push({key:'搜索',label:'搜索：'+query,clear:{query:''}});
 for(const [key,label,unit] of [['minKills','击杀',''],['minDamage','伤害',''],['minAssists','助攻',''],['minDuration','时长','秒']] as const)if(preferences[key])activeFilters.push({key:label,label:`${label} ≥ ${preferences[key]}${unit}`,clear:{[key]:0}});
 useEffect(()=>()=>{cancelLibraryPlaybackMotion();cancelLibraryViewReveal();},[]);
 useEffect(()=>{if(reduced){cancelLibraryPlaybackMotion();cancelLibraryViewReveal();}},[reduced]);
 function locateCurrent(){const root=scrollRoot.current,card=root&&[...root.querySelectorAll<HTMLElement>('.clip-card[data-path]')].find(card=>card.dataset.path===selected);if(root&&card)root.scrollTo({top:Math.max(0,root.scrollTop+card.getBoundingClientRect().top-root.getBoundingClientRect().top-12),behavior:reduced?'instant':'smooth'});}
 const browseFilterPanel=<section className="browse-filter-panel" aria-label="浏览筛选">
   <div className="browse-heading"><b>浏览条件</b><button className="text-button" aria-label="添加历史输出目录" onClick={onAddRoot}>添加目录</button><InfoTip label="浏览筛选说明" text="这里只筛选历史库显示。处理时不保留新输出的阈值在首页的片段过滤中配置。"/><button className="icon-button" aria-label="关闭浏览筛选" onClick={()=>active?setPlaybackFilters(false):setFilters(false)}><X size={16}/></button></div>
   <label className="library-filter-field"><span>录像来源</span><FilterControl active={!!source} label="录像来源" onClear={()=>onPreferences({source:''})}><StyledSelect label="录像来源" value={source} onChange={source=>onPreferences({source})} options={[{value:'',label:'所有来源'},...sources.map(value=>({value,label:value.split(/[\\/]/).pop()||value}))]}/></FilterControl></label>
   <label className="library-filter-field"><span>录制日期</span><FilterControl active={!!preferences.date} label="录制日期" onClear={()=>onPreferences({date:''})}><DatePicker value={preferences.date||''} onChange={date=>onPreferences({date})} dates={dates} hasUnknown={all.some(row=>!dateFor(row))}/></FilterControl></label>
   <label className="library-filter-field"><span>本人账号</span><FilterControl active={!!preferences.account} label="本人账号" onClear={()=>onPreferences({account:''})}><StyledSelect label="本人账号筛选" value={all.find(row=>row.clip.accountAliases?.some(name=>playerNameKey(name)===playerNameKey(preferences.account||'')))?.clip.accountName||preferences.account||''} onChange={account=>onPreferences({account})} options={[{value:'',label:'所有账号'},...accounts.map(name=>({value:name,label:name}))]}/></FilterControl></label>
   <label className="library-filter-field"><span>武器</span><FilterControl active={!!preferences.weapon} label="武器" onClear={()=>onPreferences({weapon:''})}><StyledSelect menuClassName="weapon-select-menu" renderGroup={ammoHeading} label="武器筛选" value={preferences.weapon||''} onChange={weapon=>onPreferences({weapon})} options={[{value:'',label:'所有武器',meta:`${all.length} 段`},...weaponOptions]}/></FilterControl></label>
   <label className="library-filter-field"><span>英雄</span><FilterControl active={!!preferences.hero} label="英雄" onClear={()=>onPreferences({hero:''})}><HeroPicker value={preferences.hero||''} onChange={hero=>onPreferences({hero})} heroes={heroes} hasUnknown={all.some(row=>!row.clip.hero)}/></FilterControl></label>
   <label className="library-filter-field"><span>队友</span><FilterControl active={!!preferences.teammate} label="队友" onClear={()=>onPreferences({teammate:''})}><TeammatePicker value={preferences.teammate||''} onChange={teammate=>onPreferences({teammate})} names={teammates} excluded={excludedTeammates} onExclude={onExcludeTeammate}/></FilterControl></label>
   <label className="library-filter-field"><span>模式/段位</span><FilterControl active={!!preferences.rank} label="模式/段位" onClear={()=>onPreferences({rank:'',rankDivision:''})}><StyledSelect label="模式段位筛选" value={(preferences.rank||'')+(preferences.rankDivision?':'+preferences.rankDivision:'')} onChange={value=>{const [rank,rankDivision='']=value.split(':');onPreferences({rank,rankDivision});}} options={[{value:'',label:'所有模式/段位'},...rankOptions,...(all.some(row=>!row.clip.rank)?[{value:'unknown',label:'模式/段位未识别'}]:[])]}/></FilterControl></label>
   <label className="library-filter-field"><span>搜索</span><FilterControl active={!!query} label="搜索" onClear={()=>onPreferences({query:''})}><input type="search" aria-label="搜索片段" placeholder="原文件、片段名或枪械" value={query} onChange={e=>onPreferences({query:e.target.value})}/></FilterControl></label>
   <label className="library-filter-field"><span>最低击杀</span><FilterControl active={!!preferences.minKills} label="最低击杀" onClear={()=>onPreferences({minKills:0})}><input type="number" aria-label="浏览最低击杀" min="0" max="60" value={preferences.minKills||0} onChange={e=>onPreferences({minKills:Math.max(0,e.target.valueAsNumber||0)})}/></FilterControl></label>
   <label className="library-filter-field"><span>最短时长（秒）</span><FilterControl active={!!preferences.minDuration} label="最短时长（秒）" onClear={()=>onPreferences({minDuration:0})}><input type="number" aria-label="浏览最短时长" min="0" max="86400" value={preferences.minDuration||0} onChange={e=>onPreferences({minDuration:Math.max(0,e.target.valueAsNumber||0)})}/></FilterControl></label>
   <label className="library-filter-field"><span>最低伤害</span><FilterControl active={!!preferences.minDamage} label="最低伤害" onClear={()=>onPreferences({minDamage:0})}><input type="number" aria-label="浏览最低伤害" min="0" max="20000" value={preferences.minDamage||0} onChange={e=>onPreferences({minDamage:Math.max(0,e.target.valueAsNumber||0)})}/></FilterControl></label>
   <label className="library-filter-field"><span>最低助攻</span><FilterControl active={!!preferences.minAssists} label="最低助攻" onClear={()=>onPreferences({minAssists:0})}><input type="number" aria-label="浏览最低助攻" min="0" max="99" value={preferences.minAssists||0} onChange={e=>onPreferences({minAssists:Math.max(0,e.target.valueAsNumber||0)})}/></FilterControl></label>
   <label className="library-filter-check"><input type="checkbox" checked={preferences.keepUnknown!==false} onChange={e=>onPreferences({keepUnknown:e.target.checked})}/>保留计数未知或下界待核验</label>

  </section>;
 return <ClipActionsContext.Provider value={{selectionMode,checked,onCheck:checkClip,recognitionDisabled:disabled||deleteDisabled||hudRunning||!!recognizing,recognizing,enrichment:hud.job,onRecognize:recognize,sharing,onShare:files=>void share(files)}}><div className={`clip-library-shell ${active?'is-playing':''}`}>
  {active&&<div className="library-player-pane" aria-label="观看区域"><WatchPlayer key="library-player" ratio={sessionRatio.current||16/9} clip={active.clip} source={active.result.source} index={active.index} playback={playback} onClose={()=>selectClip(null)} onFilter={filterClip} onOpen={openClip} onDelete={deleteClip} deleting={deleting===active.clip.path} deleteDisabled={disabled||deleteDisabled||hudRunning||!!recognizing||!!deleting} disabled={disabled} onPrevious={activePosition>0?()=>selectClip(timelineItems[activePosition-1].clip.path):undefined} onNext={activePosition>=0&&activePosition<timelineItems.length-1?()=>selectClip(timelineItems[activePosition+1].clip.path):undefined}/></div>}
  <div ref={scrollRoot} className="clip-library library-scroll" tabIndex={0} id="page-clips" role="tabpanel" aria-labelledby="tab-clips">
  <div className="page-heading library-management" hidden={!!active}><div className="heading-with-info"><h1>整理片段</h1><button className="icon-button" aria-label="打开输出目录" title="打开输出目录" onClick={onDirectory}><FolderOpen size={17}/></button><div className="library-heading-actions"><button className="icon-button library-refresh" aria-label="刷新片段库" onClick={onRefresh} disabled={loading}><RefreshCw size={17} className={loading?'loading-spinner':undefined}/></button></div></div><p>{loading&&!all.length?'正在载入':clips.length+' 段'}</p></div>
  <div className="library-toolbar library-management" hidden={!!active}><div className="library-controls">
   <button className="browse-filter-toggle" aria-expanded={filters} onClick={()=>setFilters(!filters)}><Filter size={14}/>筛选</button>
   <button className="browse-filter-toggle" aria-expanded={hudPanel} disabled={disabled} onClick={()=>setHudPanel(!hudPanel)}>{hudRunning?'正在识别…':'补充 HUD'}</button>
   <button className="browse-filter-toggle library-multiselect" aria-pressed={selectionMode} disabled={sharing} onClick={()=>{setSelectionMode(value=>!value);if(selectionMode)setChecked(new Set());}}><ListChecks size={15}/>多选分享</button>
   <LibrarySortMenu value={preferences.sort||'recent'} descending={preferences.descending} onChange={sort=>onPreferences({sort})} onDirectionChange={()=>onPreferences({descending:!preferences.descending})}/>
  </div><FluidChoices className="view-switch" label="片段视图" reduced={reduced} value={view} onChange={next=>onPreferences({view:next})} options={(['detail','grid','list'] as const).map((value,i)=>({value,label:['详细','网格','列表'][i],content:<><DesignIcon name={value}/>{['详细','网格','列表'][i]}</>}))}/></div>

  {active&&<PlaybackBrowserHeader total={clips.length} position={activePosition+1} filterCount={activeFilters.length} filtersOpen={playbackFilters} onFilters={()=>setPlaybackFilters(!playbackFilters)} onLocate={locateCurrent} job={hud.job} onStop={()=>void window.apex.stop().catch(error=>setHudError(String(error)))} sort={<LibrarySortMenu value={preferences.sort||'recent'} descending={preferences.descending} onChange={sort=>onPreferences({sort})} onDirectionChange={()=>onPreferences({descending:!preferences.descending})}/>}/>}
  <div className="library-active-filters" role="region" aria-label="当前筛选"><b>当前筛选</b><div className="library-filter-values">{activeFilters.length?activeFilters.map(filter=><button type="button" key={filter.key} className="library-filter-chip" title={filter.label} aria-label={`移除${filter.key}筛选`} onClick={()=>onPreferences(filter.clear)}><span>{filter.label}</span><X size={12}/></button>):<span className="library-filter-all">全部片段</span>}</div>{!!activeFilters.length&&<button type="button" className="clear-library-filters" onClick={clearFilters}>清除全部</button>}</div>
  <div className="library-management-panel" hidden={!!active}><MotionDisclosure open={filters}>{browseFilterPanel}</MotionDisclosure></div>
  {active&&<MotionDisclosure open={playbackFilters}>{browseFilterPanel}</MotionDisclosure>}

  {selectionMode&&<div className="library-selection-toolbar" hidden={!!active} role="region" aria-label="批量分享"><b>已选 {checked.size} 段{[...checked].some(file=>!clips.some(row=>row.clip.path===file))&&<small>（含筛选外片段）</small>}</b><button type="button" disabled={sharing} onClick={selectVisible}><ListChecks size={15}/>全选当前结果</button><button type="button" disabled={!checked.size||sharing} onClick={()=>setChecked(new Set())}><ListX size={15}/>清空选择</button><button type="button" className="primary" disabled={!checked.size||sharing} onClick={()=>void share([...checked])}>{sharing?<LoaderCircle size={15} className="loading-spinner"/>:<Share2 size={15}/>}分享到 QQ</button><button type="button" disabled={sharing} onClick={()=>{setSelectionMode(false);setChecked(new Set());}}><X size={15}/>退出多选</button></div>}
  {actionNotice&&<div className="library-action-notice" role="status"><span>{actionNotice}</span><button type="button" className="icon-button" aria-label="关闭片段操作提示" onClick={()=>setActionNotice('')}><X size={15}/></button></div>}
  <div className="library-management-panel" hidden={!!active}><MotionDisclosure open={hudPanel}><section className="browse-filter-panel hud-enrichment-panel" aria-label="补充HUD信息"><div className="browse-heading"><b>补充已导出片段的信息</b><button className="icon-button" aria-label="关闭HUD补充选项" onClick={()=>setHudPanel(false)}><X size={16}/></button></div>{hud.job&&<div className="hud-run-progress" role="status" aria-live="polite"><div className="hud-run-heading"><b>{hud.job.running?(hud.job.mode==='refresh'?'重新识别':'补充识别'):hud.job.status==='stopped'?'已停止':hud.job.status==='failed'?'识别未完成':hud.job.status==='review'?'识别完成，待复核':'识别完成'} · {hudProgress.completed} / {hudProgress.total} 项</b><span>{hudProgress.total?Math.floor(hudProgress.completed/hudProgress.total*100):0}%</span>{hudRunning&&<button className="text-button" onClick={()=>void window.apex.stop().catch(error=>setHudError(String(error)))}>停止</button>}</div><progress aria-label="HUD识别进度" max={Math.max(1,hudProgress.total)} value={hudProgress.completed}/>{hudProgress.file&&<div className="hud-current-file" title={hudProgress.file}>当前片段 · {hudProgress.file.split(/[\\/]/).pop()}</div>}<div className="hud-run-activity">{hudProgress.message}{hudProgress.backend&&` · ${hudProgress.backend==='dml'?'GPU':'CPU'}`}{hudProgress.framesTotal>0&&` · 画面 ${hudProgress.framesDone}/${hudProgress.framesTotal}`}</div>{!!hudProgress.fields.length&&<div className="hud-run-fields">{hudProgress.fields.map(key=>enrichmentFields.find(field=>field.key===key)?.label||key).join(' · ')}</div>}{hudProgress.failures>0&&<span>{hudProgress.failures} 组需要重试</span>}</div>}{hud.job?.kind==='single'&&<p className="hud-job-target" title={hud.job.files[0]}>单片段：{hud.job.files[0].split(/[\\/]/).pop()}</p>}<p>{(hudRunning?hud.job!.mode:hudMode)==='refresh'?'重新读取所选信息；未确认字段会提示复核，原始战绩记录保留。':'只补充所选信息中缺失或未确认的字段，已确认的结果保留。'}</p><HudFieldPicker items={enrichmentFields} value={hudRunning?hud.job!.fields:hudSelection} disabled={hudRunning} onChange={setHudSelection}/><label className="library-filter-field"><span>识别模式</span><StyledSelect label="HUD识别模式" value={hudRunning?hud.job!.mode:hudMode} disabled={hudRunning} onChange={setHudMode} options={[{value:'missing',label:'未识别片段'},{value:'refresh',label:'重新识别'}]}/></label>{!(hudRunning&&hud.job?.kind==='single')&&<label className="library-filter-field"><span>范围</span><StyledSelect label="HUD补充范围" value={hudScope} disabled={hudRunning} onChange={setHudScope} options={[{value:'visible',label:`当前筛选的 ${clips.length} 个片段`},{value:'selected',label:'当前播放片段',disabled:!selected}]}/></label>}<button className="primary" disabled={hudRunning||deleteDisabled||!hudSelection.length||!clips.length||hudScope==='selected'&&!selected} onClick={()=>void enrich()}>{hudRunning?'正在识别…':hudMode==='refresh'?'开始重新识别':'开始补充'}</button>{hudError&&<p role="alert">{hudError}</p>}</section></MotionDisclosure></div>
  <MotionDisclosure open={!!error}><div className="library-error" role="alert"><span>{error||lastError.current}</span><div className="library-error-actions"><button onClick={onRefresh} disabled={loading}>重试</button>{canIgnoreError&&<button onClick={onIgnoreError} disabled={loading} title="忽略这些记录，下次启动不再读取">忽略</button>}<button className="icon-button" aria-label="关闭错误提示" onClick={onDismissError}><X size={16}/></button></div></div></MotionDisclosure>
  {loading&&!all.length?<div className="empty-clips" role="status"><RefreshCw size={32} className="loading-spinner"/><h2>正在载入历史片段</h2></div>:!clips.length?<div className="empty-clips"><FolderOpen size={36}/><h2>{all.length?'没有符合条件的片段':'片段库还是空的'}</h2><button className="primary" onClick={()=>all.length?clearFilters():onImport()}>{all.length?'清除浏览条件':'回开始导入录像'}</button></div>:<div className="library-items" role="region" aria-label="片段列表"><VirtualClips playback={!!active} onFilter={filterClip} timeline={timeline} items={timelineItems} deleting={deleting} onDelete={deleteClip} view={view} selected={selected} reduced={reduced} disabled={disabled} deleteDisabled={deleteDisabled||hudRunning||!!recognizing} onSelect={selectClip} onOpen={openClip}/></div>}
 </div></div></ClipActionsContext.Provider>;
}
