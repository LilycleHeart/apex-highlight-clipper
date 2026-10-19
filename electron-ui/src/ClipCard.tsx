import {memo,useContext,useId,useRef,useState,type CSSProperties} from 'react';
import type {ClipView} from './ClipLibrary';
import {Film,FolderOpen,LoaderCircle,PanelBottomOpen,Play} from 'lucide-react';
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

function ClipCard({clip,source,onFilter,index,identity,view,playback=false,current=false,disabled,deleting,deleteDisabled,onSelect,onOpen,onDelete,onGeometryChange,position,total,layoutRow,layoutColumn}:{clip:Clip;source?:string;onFilter:(filter:ClipDetailFilter)=>void;index:number;identity:string;view:ClipView;playback?:boolean;current?:boolean;disabled:boolean;deleting:boolean;deleteDisabled:boolean;onDelete:(file:string)=>void;onSelect:(id:string|null)=>void;onOpen:(file:string,folder:boolean)=>void;onGeometryChange:()=>void;position?:number;total?:number;layoutRow?:number;layoutColumn?:number}){
 const actions=useContext(ClipActionsContext),[metadataOpen,setMetadataOpen]=useState(false),metadataId=useId(),cover=useRef<HTMLDivElement>(null);
 const [ratio,setRatio]=useState(displayRatio(clip.media)||16/9),thumbnail=useThumbnail(clip.path,clip.thumbnail,cover);
 const displayName=clip.name.replace('未知杀',clip.kills===null?'—杀':`${clip.kills}杀`).replace('未知伤',clip.damage===null?'—伤':`${clip.damage}伤`).replaceAll('未知枪','—枪');
 return <article role="listitem" aria-posinset={position} aria-setsize={total} style={layoutRow!==undefined?{gridRow:layoutRow+1,gridColumn:(layoutColumn||0)+1}:undefined} className={`clip-card ${playback?'playback-clip':''} ${current?'clip-current':''}`} data-layout-row={layoutRow} data-identity={identity} data-path={clip.path} data-selected="false" data-checked={actions?.checked.has(clip.path)||false}>
  {!playback&&<ClipSelection file={clip.path} name={displayName}/>}<svg className="card-surface" aria-hidden="true" preserveAspectRatio="none"><path/></svg>
  <div ref={cover} className="clip-cover"><div className="media-frame" style={{aspectRatio:ratio,'--media-ratio':ratio} as CSSProperties}>
   {thumbnail.url?<img src={thumbnail.url} alt="交战片段代表画面" loading="lazy" decoding="async" onLoad={event=>{const next=displayRatio(clip.media)||event.currentTarget.naturalWidth/event.currentTarget.naturalHeight;if(Number.isFinite(next)&&next>0)setRatio(next);}} onError={thumbnail.retry}/>:<div className="cover-placeholder" title={thumbnail.error||undefined}>{thumbnail.error?<Film size={32}/>:<LoaderCircle size={32} className="loading-spinner"/>}{thumbnail.error?'封面暂不可用':'正在载入画面'}</div>}
   {current&&<span className="clip-current-label">当前片段</span>}<span className="duration">{clock(clip.duration)}</span><button hidden={playback} aria-label={`播放第${index}段`} className="play-button" disabled={disabled} onClick={()=>onSelect(clip.path)}><Play size={18} fill="currentColor"/></button>
  </div></div>
  <div className="clip-info">{playback?<PlaybackClipInfo clip={clip} source={source} index={index} current={current}/>:<>
   <div className="clip-number">交战 {String(index).padStart(2,'0')}</div>
   <h3 title={clip.name}>{displayName}</h3><ClipDetails clip={clip} source={source} onFilter={onFilter} compact={view!=='detail'}/>
   <div className="clip-tail"><div className={`clip-file-actions clip-action-toolbar ${view!=='detail'?'clip-actions-compact':''}`} role="group" aria-label="片段操作">
    {view!=='detail'&&<button type="button" className={`clip-action ${view==='list'?'clip-primary-action':''}`} aria-label="片段详情" aria-expanded={metadataOpen} aria-controls={metadataId} title={metadataOpen?'收起片段详情':'展开片段详情'} onClick={()=>{setMetadataOpen(value=>!value);onGeometryChange();}}><PanelBottomOpen size={16}/>{view==='list'&&<span>详情</span>}</button>}
    <button type="button" className="clip-action" disabled={disabled} aria-label="查看文件" title="在文件夹中查看视频" onClick={()=>onOpen(clip.path,true)}><FolderOpen size={16}/>{view==='detail'&&<span>查看文件</span>}</button>
    <ClipActionButtons file={clip.path} name={displayName} labels={view==='detail'?'all':'none'}/><ClipDeleteButton className="clip-action clip-delete" text={view==='detail'?'删除':undefined} label={`删除片段 ${displayName}`} resetKey={clip.path+':'+view} deleting={deleting} disabled={deleteDisabled} onDelete={()=>onDelete(clip.path)}/>
   </div>{view!=='detail'&&<MotionDisclosure open={metadataOpen} id={metadataId} onComplete={onGeometryChange}><div className="compact-details"><ClipDetails clip={clip} source={source} onFilter={onFilter} summary={false}/></div></MotionDisclosure>}</div>
  </>}</div>
  {playback&&<button type="button" className="playback-clip-select" aria-label={`播放交战 ${index}：${displayName}`} aria-current={current?'true':undefined} title={displayName} disabled={disabled} onClick={()=>onSelect(clip.path)}><Play size={19} className="playback-clip-play" fill="currentColor"/></button>}
 </article>;
}
export default memo(ClipCard);
