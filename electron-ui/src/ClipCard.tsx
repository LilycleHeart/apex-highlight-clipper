import {memo,useCallback,useEffect,useLayoutEffect,useRef,useState,type CSSProperties} from 'react';
import type {ClipView} from './ClipLibrary';
import {ExternalLink,Film,Minimize2,Play,Trash2,LoaderCircle} from 'lucide-react';
import type {Clip} from './shared';
import {clock} from './state';
import ClipDetails from './ClipDetails';
import PlayerControls from './PlayerControls';
import {displayRatio} from './mediaGeometry';
import useThumbnail from './useThumbnail';
import MotionDetails from './MotionDetails';
import {applyPlayerAudio} from './playerAudio';

function ClipCard({clip,index,identity,view,playback,selected,disabled,deleting,deleteDisabled,reduced,onSelect,onOpen,onDelete,onGeometryChange,position,total,layoutRow,layoutColumn}:{clip:Clip;index:number;identity:string;view:ClipView;playback:Map<string,number>;selected:boolean;disabled:boolean;deleting:boolean;deleteDisabled:boolean;reduced:boolean;onDelete:(file:string)=>void;onSelect:(id:string|null)=>void;onOpen:(file:string,folder:boolean)=>void;onGeometryChange:()=>void;position?:number;total?:number;layoutRow?:number;layoutColumn?:number}){
 const [detailsOpen,setDetailsOpen]=useState(false);
 const[ratio,setRatio]=useState(displayRatio(clip.media)||16/9);const ratioRef=useRef(ratio);
 const[media,setMedia]=useState<string|null>(null);const[error,setError]=useState('');const[playing,setPlaying]=useState(false);const[needsPlay,setNeedsPlay]=useState(false);
 const video=useRef<HTMLVideoElement|null>(null);const cover=useRef<HTMLDivElement|null>(null);const scrolled=useRef(false);
 const attachVideo=useCallback((element:HTMLVideoElement|null)=>{video.current=element;if(element)applyPlayerAudio(element);},[]);
 const thumbnail=useThumbnail(clip.path,clip.thumbnail,cover);
 const collapse=()=>{if(document.fullscreenElement===cover.current)void document.exitFullscreen().catch(()=>{}).finally(()=>onSelect(null));else onSelect(null);};
 useLayoutEffect(()=>{if(selected)onGeometryChange();},[media,selected,detailsOpen,onGeometryChange]);
 useLayoutEffect(()=>{if(selected){scrolled.current=false;onGeometryChange();}},[view,selected,onGeometryChange]);
 const displayName=clip.name.replace('未知杀',clip.kills===null?'—杀':`${clip.kills}杀`).replace('未知伤',clip.damage===null?'—伤':`${clip.damage}伤`).replaceAll('未知枪','—枪');
 useEffect(()=>{
  let live=true;setError('');setPlaying(false);setNeedsPlay(false);scrolled.current=false;setDetailsOpen(false);
  if(!selected){setMedia(null);return;}
  void window.apex.videoURL(clip.path).then(url=>{if(live)setMedia(url);}).catch(()=>{if(live)setError('无法读取此片段，请检查文件是否仍在输出目录');});
  return()=>{live=false;};
 },[selected,clip.path]);
 useEffect(()=>{
  const element=video.current;if(!media||!element)return;
  let live=true;void element.play().catch(()=>{if(live)setNeedsPlay(true);});
  return()=>{live=false;element.pause();element.removeAttribute('src');element.load();};
 },[media]);
 useEffect(()=>{const el=cover.current?.parentElement;if(!el)return;el.addEventListener('surface-settled',expanded);return()=>el.removeEventListener('surface-settled',expanded);},[selected,reduced]);
 function updateRatio(value:number){if(Number.isFinite(value)&&value>0&&Math.abs(value-ratioRef.current)>.001){ratioRef.current=value;setRatio(value);onGeometryChange();}}
 function expanded(){if(selected&&!scrolled.current){scrolled.current=true;cover.current?.scrollIntoView({block:'nearest',behavior:reduced?'instant':'smooth'});}}
 return <article role="listitem" aria-posinset={position} aria-setsize={total} style={layoutRow!==undefined?{gridRow:layoutRow+1,gridColumn:selected?'1/-1':(layoutColumn||0)+1}:undefined} className={`clip-card ${selected?'clip-expanded':''} ${selected&&!detailsOpen?'player-info-hidden':''}`} data-layout-row={layoutRow} data-identity={identity} data-path={clip.path} data-selected={selected}>
  <svg className="card-surface" aria-hidden="true" preserveAspectRatio="none"><path/></svg>
  <div ref={cover} className="clip-cover" data-player-active={selected&&!!media}><div className="media-frame" style={{aspectRatio:ratio,'--media-ratio':ratio} as CSSProperties}>
   {selected&&media?<video ref={attachVideo} src={media} poster={thumbnail.url} playsInline preload="metadata" aria-label={`播放交战 ${index}`} onLoadedMetadata={e=>{const v=e.currentTarget;updateRatio(clip.media&&(clip.media.rotation!==0||clip.media.sampleAspectRatio!==1)?displayRatio(clip.media)!:v.videoWidth/v.videoHeight);const explicit=v.dataset.seekRequested,t=explicit!==undefined?Number(explicit):playback.get(identity);if(t!==undefined&&t<v.duration)v.currentTime=t;}} onTimeUpdate={e=>playback.set(identity,e.currentTarget.currentTime)} onPlay={()=>{setPlaying(true);setNeedsPlay(false);}} onPause={()=>setPlaying(false)} onError={()=>setError('此片段暂时无法在应用内播放，可使用系统播放器打开')}/>:thumbnail.url?<img src={thumbnail.url} alt="交战片段代表画面" loading="lazy" decoding="async" onLoad={e=>updateRatio(displayRatio(clip.media)||e.currentTarget.naturalWidth/e.currentTarget.naturalHeight)} onError={thumbnail.retry}/>:<div className="cover-placeholder" title={thumbnail.error||undefined}><Film size={32}/>{thumbnail.error?'封面暂不可用':'正在载入画面'}</div>}
   {!selected&&<><span className="duration">{clock(clip.duration)}</span><button aria-label={`播放第${index}段`} className="play-button" disabled={disabled} onClick={()=>onSelect(clip.path)}><Play size={18} fill="currentColor"/></button></>}
   {selected&&!media&&!error&&<div className="player-loading" role="status">正在打开视频…</div>}
   {selected&&needsPlay&&!error&&<button className="player-resume" aria-label="开始播放" onClick={()=>void video.current?.play().catch(()=>setError('无法开始播放，请重试或用系统播放器打开'))}><Play size={22}/>开始播放</button>}
   {selected&&error&&<div className="player-error" role="alert"><p>{error}</p><button className="secondary" onClick={()=>onOpen(clip.path,false)}>系统播放器打开<ExternalLink size={14}/></button></div>}
  </div>{selected&&media&&<PlayerControls onDelete={()=>onDelete(clip.path)} deleteDisabled={deleteDisabled} clip={clip} video={video} stage={cover} roundTotals={clip.roundTotals} onError={setError} onCollapse={collapse} onDetails={()=>{setDetailsOpen(!detailsOpen);onGeometryChange();}}/>}</div>
  <div className="clip-info">
   <div className="clip-number">交战 {String(index).padStart(2,'0')}{selected&&<button className="player-collapse" aria-label={`收起第${index}段`} onClick={collapse}><Minimize2 size={14}/>收起播放</button>}</div>
   {selected&&<div className="player-caption"><span>{playing?'正在播放':'已暂停'} · {clock(clip.duration)}</span></div>}
   <h3 title={clip.name}>{displayName}</h3><ClipDetails clip={clip} compact={view!=='detail'&&!selected}/>
   <div className="clip-tail">{view!=='detail'&&!selected&&<MotionDetails className="compact-details" label="详情 →" onGeometryChange={onGeometryChange}><ClipDetails clip={clip}/></MotionDetails>}
   <div className="clip-file-actions"><button className="text-button" disabled={disabled} onClick={()=>onOpen(clip.path,true)}>查看文件<ExternalLink size={13}/></button><button type="button" className="clip-delete" data-deleting={deleting} disabled={deleteDisabled} aria-label={`删除片段 ${displayName}`} title="移至回收站" onClick={()=>onDelete(clip.path)}>{deleting?<LoaderCircle size={16}/>:<Trash2 size={16}/>}</button></div></div>
  </div>
 </article>;
}
export default memo(ClipCard);
