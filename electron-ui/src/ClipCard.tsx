import {createPortal} from 'react-dom';
import useWatchPlayer,{type WatchPlayerOptions} from './WatchPlayer';
import {memo,useContext,useId,useRef,useState,useLayoutEffect,type CSSProperties} from 'react';
import type {ClipView} from './ClipLibrary';
import {Film,FolderOpen,LoaderCircle,LogOut,PanelBottomOpen,Play,Star} from 'lucide-react';
import type {Clip} from './shared';
import type {ClipDetailFilter} from './libraryFilters';
import {clock} from './state';
import {ClipActionsContext,ClipSelection,ClipActionButtons} from './ClipActions';
import ClipDetails from './ClipDetails';
import {displayRatio} from './mediaGeometry';
import useThumbnail from './useThumbnail';
import MotionDisclosure from './MotionDisclosure';
import ClipDeleteButton from './ClipDeleteButton';
import PlaybackClipInfo from './PlaybackClipInfo';
import CollectionMenu from './CollectionMenu';
import {useClipCollections} from './collections';

function ClipCard({clip,source,onFilter,index,identity,view,playback=false,compactPlayback=false,player,current=false,disabled,deleting,deleteDisabled,onSelect,onOpen,onDelete,onRemoveImported,onGeometryChange,position,total,layoutRow,layoutColumn}:{clip:Clip;source?:string;onFilter:(filter:ClipDetailFilter)=>void;index:number;identity:string;view:ClipView;playback?:boolean;compactPlayback?:boolean;player?:WatchPlayerOptions;current?:boolean;disabled:boolean;deleting:boolean;deleteDisabled:boolean;onDelete:(file:string)=>void;onRemoveImported?:(file:string)=>void;onSelect:(id:string|null)=>void;onOpen:(file:string,folder:boolean)=>void;onGeometryChange:()=>void;position?:number;total?:number;layoutRow?:number;layoutColumn?:number}){
 const actions=useContext(ClipActionsContext),[metadataOpen,setMetadataOpen]=useState(false),[collectionOpen,setCollectionOpen]=useState(false),[collectionNote,setCollectionNote]=useState(''),metadataId=useId(),cover=useRef<HTMLDivElement>(null),article=useRef<HTMLElement>(null),slot=useRef<HTMLDivElement>(null);
 const memberOf=useClipCollections(clip.path);
 const [surface]=useState(()=>{const node=document.createElement('div');node.className='clip-surface-host';return node;});
 const [ratio,setRatio]=useState(displayRatio(clip.media)||16/9),thumbnail=useThumbnail(clip.path,clip.thumbnail,cover);
 const displayName=clip.name.replace('未知杀',clip.kills===null?'—杀':`${clip.kills}杀`).replace('未知伤',clip.damage===null?'—伤':`${clip.damage}伤`).replaceAll('未知枪','—枪');
 const watch=useWatchPlayer({clip,source,index,onFilter,onOpen,onDelete,deleting,deleteDisabled,disabled,player,article,cover,thumbnail:thumbnail.url});
 useLayoutEffect(()=>{const target=player?slot.current?.closest('.clip-library-shell')?.querySelector('.library-player-pane'):slot.current;if(target&&surface.parentNode!==target)target.appendChild(surface);article.current?.dispatchEvent(new Event('player-layout'));},[!!player,player?.wide,surface]);
 useLayoutEffect(()=>()=>surface.remove(),[surface]);
 const positionStyle=layoutRow!==undefined?{gridRow:layoutRow+1,gridColumn:(layoutColumn||0)+1}:undefined;
 const card=<article ref={article} role="listitem" aria-posinset={position} aria-setsize={total} className={`clip-card ${watch?'watch-player clip-expanded':''} ${watch&&player?.wide?'player-wide':''} ${playback&&!watch?'playback-clip':''} ${current?'clip-current':''}`} data-identity={identity} data-path={clip.path} data-selected={!!watch} data-checked={actions?.checked.has(clip.path)||false} data-layout={watch?(player?.wide?'wide':'normal'):undefined} aria-label={watch?'片段播放器':undefined}>
  {!playback&&!watch&&<ClipSelection file={clip.path} name={displayName}/>}<svg className="card-surface" aria-hidden="true" preserveAspectRatio="none"><path/></svg>
  {watch?.navigation}<div key="picture" ref={cover} className={`clip-cover ${watch?'watch-screen':''}`} data-player-active={!!watch}><div className="media-frame" style={{aspectRatio:ratio,'--media-ratio':ratio} as CSSProperties}>
   {watch?watch.picture:thumbnail.url?<img src={thumbnail.url} alt="交战片段代表画面" loading="lazy" decoding="async" onLoad={event=>{const next=displayRatio(clip.media)||event.currentTarget.naturalWidth/event.currentTarget.naturalHeight;if(Number.isFinite(next)&&next>0)setRatio(next);}} onError={thumbnail.retry}/>:<div className="cover-placeholder" title={thumbnail.error||undefined}>{thumbnail.error?<Film size={32}/>:<LoaderCircle size={32} className="loading-spinner"/>}{thumbnail.error?'封面暂不可用':'正在载入画面'}</div>}
   {!watch&&<>{current&&<span className="clip-current-label">当前片段</span>}<span className="duration">{clock(clip.duration)}</span><button hidden={playback} aria-label={`播放第${index}段`} className="play-button" disabled={disabled} onClick={()=>onSelect(clip.path)}><Play size={18} fill="currentColor"/></button></>}
  </div>{watch?.controls}{watch?.drawer}</div>
  <div key="info" className={watch?'watch-card-info':'clip-info'}>{watch?watch.info:playback?<PlaybackClipInfo clip={clip} source={source} index={index} current={current} compact={compactPlayback}/>:<>
   <div className="clip-number">交战 {String(index).padStart(2,'0')}</div>
   <h3 title={clip.name}>{displayName}</h3><ClipDetails clip={clip} source={source} onFilter={onFilter} compact={view!=='detail'}/>
   <div className="clip-tail"><div className={`clip-file-actions clip-action-toolbar ${view!=='detail'?'clip-actions-compact':''}`} role="group" aria-label="片段操作">
    {view!=='detail'&&<button type="button" className={`clip-action ${view==='list'?'clip-primary-action':''}`} aria-label="片段详情" aria-expanded={metadataOpen} aria-controls={metadataId} title={metadataOpen?'收起片段详情':'展开片段详情'} onClick={()=>{setMetadataOpen(value=>!value);onGeometryChange();}}><PanelBottomOpen size={16}/>{view==='list'&&<span>详情</span>}</button>}
    <button type="button" className="clip-action" disabled={disabled} aria-label="查看文件" title="在文件夹中查看视频" onClick={()=>onOpen(clip.path,true)}><FolderOpen size={16}/>{view==='detail'&&<span>查看文件</span>}</button>
    <ClipActionButtons file={clip.path} name={displayName} imported={!!clip.imported} labels={view==='detail'?'all':'none'}/><ClipDeleteButton className="clip-action clip-delete" text={view==='detail'?'删除':undefined} label={`删除片段 ${displayName}`} resetKey={clip.path+':'+view} deleting={deleting} disabled={deleteDisabled} onDelete={()=>onDelete(clip.path)}/><button type="button" className="clip-action clip-collect" data-collected={memberOf.length>0} aria-pressed={memberOf.length>0} disabled={deleteDisabled} aria-label={`收藏 ${displayName}`} title={memberOf.length?`已收藏到：${memberOf.map(item=>item.name).join('、')}`:collectionNote||'添加到收藏夹'} onClick={()=>setCollectionOpen(true)}><Star size={16} fill={memberOf.length?'currentColor':'none'}/>{view==='detail'&&<span>{memberOf.length?'已收藏':'收藏'}</span>}</button>{clip.imported&&<button type="button" className="clip-action" aria-label={`移出片段库 ${displayName}`} title="移出片段库，视频文件保留在原处" disabled={deleteDisabled} onClick={()=>onRemoveImported?.(clip.path)}><LogOut size={16}/>{view==='detail'&&<span>移出</span>}</button>}
   </div>{view!=='detail'&&<MotionDisclosure open={metadataOpen} id={metadataId} onComplete={onGeometryChange}><div className="compact-details"><ClipDetails clip={clip} source={source} onFilter={onFilter} summary={false}/></div></MotionDisclosure>}</div>
  </>}</div>
  {playback&&!watch&&<button type="button" className="playback-clip-select" aria-label={`播放交战 ${index}：${displayName}`} aria-current={current?'true':undefined} title={displayName} disabled={disabled} onClick={()=>onSelect(clip.path)}><Play size={19} className="playback-clip-play" fill="currentColor"/></button>}
 </article>;
 return <div ref={slot} className="clip-slot" hidden={!!player&&position===undefined} style={positionStyle} data-layout-row={layoutRow} data-identity={identity} data-path={clip.path}>
  {createPortal(card,surface)}
  {collectionOpen&&<CollectionMenu files={[clip.path]} onClose={()=>setCollectionOpen(false)} onDone={message=>{setCollectionNote(message);setCollectionOpen(false);}}/>}
  {watch&&<article className="clip-card playback-clip clip-current" data-path={clip.path} data-identity={identity+'-entry'} role="listitem" aria-posinset={position} aria-setsize={total}>
   <div className="clip-cover"><div className="media-frame">{thumbnail.url&&<img src={thumbnail.url} alt="当前片段代表画面"/>}<span className="duration">{clock(clip.duration)}</span></div></div>
   <div className="clip-info"><PlaybackClipInfo clip={clip} source={source} index={index} current/></div>
   <button type="button" className="playback-clip-select" aria-label={`当前播放交战 ${index}`} aria-current="true" onClick={()=>onSelect(clip.path)}/>
  </article>}
 </div>;
}
export default memo(ClipCard);
