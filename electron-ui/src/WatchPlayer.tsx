import {useCallback,useEffect,useId,useLayoutEffect,useRef,useState,type RefObject} from 'react';
import {X,ChevronDown,ExternalLink,FolderOpen,LoaderCircle,Play,PanelRight,PanelRightOpen,PanelRightClose,RectangleHorizontal} from 'lucide-react';
import type {Clip} from './shared';
import type {ClipDetailFilter} from './libraryFilters';
import {applyPlayerAudio} from './playerAudio';
import {fitPlayerSize} from './mediaGeometry';
import {clock} from './state';
import ClipDetails,{ApexIcon} from './ClipDetails';
import WatchDetailsDrawer from './WatchDetailsDrawer';
import MotionDisclosure from './MotionDisclosure';
import {ClipActionButtons} from './ClipActions';
import ClipDeleteButton from './ClipDeleteButton';
import PlayerControls from './PlayerControls';

export type WatchPlayerOptions={wide:boolean;onWide:(wide:boolean)=>void;ratio:number;playback:Map<string,number>;onClose:()=>void;onPrevious?:()=>void;onNext?:()=>void};
/** Player behavior and controls belong to the persistent library card surface. */
export default function useWatchPlayer({clip,index,source,onFilter,onOpen,onDelete,deleting,deleteDisabled,disabled,player,article,cover,thumbnail}:{clip:Clip;index:number;source?:string;onFilter:(filter:ClipDetailFilter)=>void;onOpen:(file:string,folder:boolean)=>void;onDelete:(file:string)=>void;deleting:boolean;deleteDisabled:boolean;disabled:boolean;player?:WatchPlayerOptions;article:RefObject<HTMLElement|null>;cover:RefObject<HTMLDivElement|null>;thumbnail?:string}){
 const enabled=!!player,wide=player?.wide||false,ratio=player?.ratio||16/9;
 const [buffering,setBuffering]=useState(true),[needsPlay,setNeedsPlay]=useState(false),[error,setError]=useState('');
 const [media,setMedia]=useState<{path:string;url:string}|null>(null),[detailsOpen,setDetailsOpen]=useState(true),[wideDetailsOpen,setWideDetailsOpen]=useState(false),detailsId=useId();const detailsTrigger=useRef<HTMLButtonElement>(null);
 useEffect(()=>setWideDetailsOpen(false),[wide,clip.path]);
 const video=useRef<HTMLVideoElement>(null);
 const mediaURL=enabled&&media?.path===clip.path?media.url:null;
 const attachVideo=useCallback((element:HTMLVideoElement|null)=>{video.current=element;if(element)applyPlayerAudio(element);},[]);
 const displayName=clip.name.replace('未知杀',clip.kills===null?'—杀':`${clip.kills}杀`).replace('未知伤',clip.damage===null?'—伤':`${clip.damage}伤`).replaceAll('未知枪','—枪');
 useEffect(()=>{
  if(!enabled)return;let live=true;setMedia(null);setError('');setBuffering(true);setNeedsPlay(false);
  void window.apex.videoURL(clip.path).then(url=>{if(live)setMedia({path:clip.path,url});}).catch(()=>{if(live)setError('无法读取此片段，请检查文件是否仍在输出目录');});
  return()=>{live=false;};
 },[clip.path,enabled]);
 useEffect(()=>{
  const element=video.current;if(!element||!mediaURL)return;let live=true;
  void element.play().catch(()=>{if(live)setNeedsPlay(true);});
  return()=>{live=false;element.pause();element.removeAttribute('src');element.load();};
 },[mediaURL]);
 useLayoutEffect(()=>{
  const node=article.current;if(!node||!enabled)return;let watchedPane:HTMLElement|null=null,watchedShell:HTMLElement|null=null;
  const fit=()=>{const pane=node.closest<HTMLElement>('.library-player-pane'),shell=node.closest<HTMLElement>('.clip-library-shell');if(!pane||!shell)return;
   if(pane!==watchedPane){if(watchedPane)observer.unobserve(watchedPane);observer.observe(pane);watchedPane=pane;}if(shell!==watchedShell){if(watchedShell)observer.unobserve(watchedShell);observer.observe(shell);watchedShell=shell;}
   const style=getComputedStyle(shell),rail=shell.querySelector<HTMLElement>('.library-scroll'),availableHeight=wide?shell.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom)-parseFloat(style.rowGap)-(rail?.clientHeight||0):pane.clientHeight;
   const width=Math.max(1,wide?pane.clientWidth-16:pane.clientWidth-32),box=fitPlayerSize(width,Math.max(1,availableHeight),ratio,wide);node.style.setProperty('--watch-picture-height',box.height+'px');node.style.setProperty('--watch-picture-width',box.width+'px');if(wide)shell.style.setProperty('--wide-player-width',Math.min(pane.clientWidth,box.width+16)+'px');};
  const observer=new ResizeObserver(fit);observer.observe(node);node.addEventListener('player-layout',fit);fit();return()=>{observer.disconnect();node.removeEventListener('player-layout',fit);};
 },[ratio,wide,enabled]);
 function togglePlayback(){const element=video.current;if(!element)return;if(element.paused)void element.play().catch(()=>setNeedsPlay(true));else element.pause();}
 function setLayout(next:boolean){if(next!==wide)player?.onWide(next);}
 function toggleWide(){setLayout(!wide);}
 function showDetails(){if(wide)setWideDetailsOpen(value=>!value);else setDetailsOpen(value=>!value);}
 const observed=(key:'kills'|'damage')=>clip[key]==null?'—':`${clip.statisticsPartial?.[key]?'≥':''}${clip[key]}`;
 if(!player)return null;
 return {
  navigation:(<div className="watch-navigation"><button type="button" onClick={player.onClose}><X size={17}/>收起播放</button><div className="watch-navigation-info"><span>交战 {String(index).padStart(2,'0')}<span>·</span>{clock(clip.duration)}</span><div className="watch-layout-switch" role="group" aria-label="播放布局"><button type="button" aria-label="常规模式" aria-pressed={!wide} onClick={()=>setLayout(false)}><PanelRight size={15}/><span>常规</span></button><button type="button" aria-label="切换到宽屏模式" aria-pressed={wide} onClick={()=>setLayout(true)}><RectangleHorizontal size={15}/><span>宽屏</span></button></div></div></div>),
  picture:(<>{mediaURL?<video ref={attachVideo} src={mediaURL} poster={thumbnail} playsInline preload="metadata" tabIndex={0} onClick={togglePlayback} onDoubleClick={()=>{if(document.fullscreenElement)void document.exitFullscreen().catch(()=>setError('无法退出全屏'));else void cover.current?.requestFullscreen().catch(()=>setError('无法进入全屏'));}} onKeyDown={event=>{if(event.key===' '){event.preventDefault();togglePlayback();}}} aria-label={`播放交战 ${index}`} onLoadStart={()=>setBuffering(true)} onWaiting={()=>setBuffering(true)} onCanPlay={()=>setBuffering(false)} onPlaying={()=>setBuffering(false)} onLoadedMetadata={event=>{const v=event.currentTarget,requested=v.dataset.seekRequested,t=requested===undefined?player.playback.get(clip.path):Number(requested);if(t!==undefined&&t<v.duration)v.currentTime=t;}} onTimeUpdate={event=>player.playback.set(clip.path,event.currentTarget.currentTime)} onError={()=>setError('此片段暂时无法在应用内播放，可使用系统播放器打开')}/>:thumbnail?<img src={thumbnail} alt="片段代表画面"/>:null}
    {(!mediaURL||buffering)&&!needsPlay&&!error&&<div className="player-loading" role="status"><LoaderCircle size={24} className="loading-spinner"/><span>正在载入视频…</span></div>}
    {needsPlay&&!error&&<button className="player-resume" onClick={()=>void video.current?.play().then(()=>setNeedsPlay(false)).catch(()=>setError('无法开始播放，请重试或用系统播放器打开'))}><Play size={22}/>开始播放</button>}
    {error&&<div className="player-error" role="alert"><p>{error}</p><button onClick={()=>onOpen(clip.path,false)}>系统播放器打开<ExternalLink size={14}/></button></div>}</>),
  controls:(mediaURL&&<PlayerControls key={clip.path} clip={clip} video={video} stage={cover} roundTotals={clip.roundTotals} onError={setError} wide={wide} onWide={toggleWide} onPrevious={player.onPrevious} onNext={player.onNext}/>),
  drawer:(wide&&<WatchDetailsDrawer open={wideDetailsOpen} id={detailsId+'-drawer'} clip={clip} source={source} onFilter={onFilter} onClose={()=>{setWideDetailsOpen(false);detailsTrigger.current?.focus({preventScroll:true});}}/>),
  info:(<><div className="watch-title-row"><h1 title={displayName}>{displayName}</h1></div>
  <div className="watch-footer">{wide&&<div className="watch-quick-info" aria-label="片段摘要"><span title="击杀"><ApexIcon file="stats/kills.svg"/>{observed('kills')}</span><span title="伤害"><ApexIcon file="stats/damage.svg"/>{observed('damage')}</span>{clip.hero&&<span className="watch-quick-hero">{clip.hero.name}</span>}</div>}<div className="watch-actions" role="group" aria-label="当前片段操作"><button ref={detailsTrigger} className={`watch-details-toggle ${wide?'watch-drawer-toggle':''}`} type="button" aria-label="片段详情" title={wide?wideDetailsOpen?'收起右侧详情':'展开右侧详情':detailsOpen?'收起下方详情':'展开下方详情'} aria-expanded={wide?wideDetailsOpen:detailsOpen} aria-controls={detailsId+(wide?'-drawer':'-below')} onClick={showDetails}>{wide?<>{wideDetailsOpen?<PanelRightClose size={16}/>:<PanelRightOpen size={16}/>}<span>详情</span></>:<>{detailsOpen?'收起详情':'展开详情'}<ChevronDown size={15}/></>}</button><button className="clip-action" disabled={disabled} aria-label="查看文件" title="在文件夹中查看视频" onClick={()=>onOpen(clip.path,true)}><FolderOpen size={16}/></button><ClipActionButtons file={clip.path} name={displayName} labels={wide?'none':'share'}/><ClipDeleteButton keepFile={!!clip.imported} className="clip-action" label={clip.imported?`移出片段库 ${displayName}`:`删除片段 ${displayName}`} resetKey={clip.path} deleting={deleting} disabled={deleteDisabled} onDelete={()=>onDelete(clip.path)}/></div></div><MotionDisclosure open={!wide&&detailsOpen} id={detailsId+'-below'}><section className="watch-details watch-details-below" aria-label="片段详细信息"><h2>片段信息</h2><ClipDetails clip={clip} source={source} onFilter={onFilter}/></section></MotionDisclosure></>)
 };
}
