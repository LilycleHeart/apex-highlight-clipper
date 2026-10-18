import {useCallback,useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import {X,ChevronDown,ExternalLink,FolderOpen,LoaderCircle,Play} from 'lucide-react';
import type {Clip} from './shared';
import type {ClipDetailFilter} from './libraryFilters';
import {applyPlayerAudio} from './playerAudio';
import {fitPlayerSize} from './mediaGeometry';
import {clock} from './state';
import useThumbnail from './useThumbnail';
import ClipDetails from './ClipDetails';
import {ClipActionButtons} from './ClipActions';
import ClipDeleteButton from './ClipDeleteButton';
import MotionDisclosure from './MotionDisclosure';
import PlayerControls from './PlayerControls';
import {transitionLibraryPlayback} from './libraryPlaybackMotion';

export default function WatchPlayer({clip,source,index,ratio,playback,onClose,onOpen,onDelete,onFilter,deleting,deleteDisabled,disabled,onPrevious,onNext}:{clip:Clip;source?:string;index:number;ratio:number;playback:Map<string,number>;onClose:()=>void;onOpen:(file:string,folder:boolean)=>void;onDelete:(file:string)=>void;onFilter:(filter:ClipDetailFilter)=>void;deleting:boolean;deleteDisabled:boolean;disabled:boolean;onPrevious?:()=>void;onNext?:()=>void}){
 const [wide,setWide]=useState(false),[detailsOpen,setDetailsOpen]=useState(true),[buffering,setBuffering]=useState(true),[needsPlay,setNeedsPlay]=useState(false),[error,setError]=useState('');
 const [media,setMedia]=useState<{path:string;url:string}|null>(null),detailsId=useId();
 const article=useRef<HTMLElement>(null),cover=useRef<HTMLDivElement>(null),video=useRef<HTMLVideoElement>(null);
 const thumbnail=useThumbnail(clip.path,clip.thumbnail,cover),mediaURL=media?.path===clip.path?media.url:null;
 const attachVideo=useCallback((element:HTMLVideoElement|null)=>{video.current=element;if(element)applyPlayerAudio(element);},[]);
 const displayName=clip.name.replace('未知杀',clip.kills===null?'—杀':`${clip.kills}杀`).replace('未知伤',clip.damage===null?'—伤':`${clip.damage}伤`).replaceAll('未知枪','—枪');
 useEffect(()=>{
  let live=true;setMedia(null);setError('');setBuffering(true);setNeedsPlay(false);
  void window.apex.videoURL(clip.path).then(url=>{if(live)setMedia({path:clip.path,url});}).catch(()=>{if(live)setError('无法读取此片段，请检查文件是否仍在输出目录');});
  return()=>{live=false;};
 },[clip.path]);
 useEffect(()=>{
  const element=video.current;if(!element||!mediaURL)return;let live=true;
  void element.play().catch(()=>{if(live)setNeedsPlay(true);});
  return()=>{live=false;element.pause();element.removeAttribute('src');element.load();};
 },[mediaURL]);
 useLayoutEffect(()=>{
  const node=article.current,pane=node?.closest<HTMLElement>('.library-player-pane'),shell=node?.closest<HTMLElement>('.clip-library-shell');if(!node||!pane||!shell)return;
  const fit=()=>{const style=getComputedStyle(node),width=Math.max(1,node.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight)),box=fitPlayerSize(width,shell.clientHeight,ratio,wide);node.style.setProperty('--watch-picture-height',box.height+'px');};
  const observer=new ResizeObserver(fit);observer.observe(node);observer.observe(pane);observer.observe(shell);fit();return()=>observer.disconnect();
 },[ratio,wide]);
 function togglePlayback(){const element=video.current;if(!element)return;if(element.paused)void element.play().catch(()=>setNeedsPlay(true));else element.pause();}
 function changeLayout(update:()=>void){const shell=article.current?.closest<HTMLElement>('.clip-library-shell')||null;transitionLibraryPlayback(shell,shell?.querySelector<HTMLElement>('.library-scroll')||null,update,{kind:'mode',file:clip.path});}
 function toggleWide(){changeLayout(()=>{if(wide)setDetailsOpen(true);setWide(!wide);});}
 function showDetails(){if(wide){changeLayout(()=>{setWide(false);setDetailsOpen(true);});}else setDetailsOpen(!detailsOpen);}
 return <article ref={article} className={`watch-player clip-card clip-expanded ${wide?'player-wide':''}`} data-selected="true" data-path={clip.path} aria-label="片段播放器">
  <div className="watch-navigation"><button type="button" onClick={onClose}><X size={17}/>收起播放</button><span>交战 {String(index).padStart(2,'0')}<span>·</span>{clock(clip.duration)}</span></div>
  <div ref={cover} className="clip-cover watch-screen" data-player-active={!!mediaURL}>
   <div className="media-frame">
    {mediaURL?<video ref={attachVideo} src={mediaURL} poster={thumbnail.url} playsInline preload="metadata" tabIndex={0} onClick={togglePlayback} onDoubleClick={()=>{if(document.fullscreenElement)void document.exitFullscreen().catch(()=>setError('无法退出全屏'));else void cover.current?.requestFullscreen().catch(()=>setError('无法进入全屏'));}} onKeyDown={event=>{if(event.key===' '){event.preventDefault();togglePlayback();}}} aria-label={`播放交战 ${index}`} onLoadStart={()=>setBuffering(true)} onWaiting={()=>setBuffering(true)} onCanPlay={()=>setBuffering(false)} onPlaying={()=>setBuffering(false)} onLoadedMetadata={event=>{const v=event.currentTarget,requested=v.dataset.seekRequested,t=requested===undefined?playback.get(clip.path):Number(requested);if(t!==undefined&&t<v.duration)v.currentTime=t;}} onTimeUpdate={event=>playback.set(clip.path,event.currentTarget.currentTime)} onError={()=>setError('此片段暂时无法在应用内播放，可使用系统播放器打开')}/>:thumbnail.url?<img src={thumbnail.url} alt="片段代表画面"/>:null}
    {(!mediaURL||buffering)&&!needsPlay&&!error&&<div className="player-loading" role="status"><LoaderCircle size={24} className="loading-spinner"/><span>正在载入视频…</span></div>}
    {needsPlay&&!error&&<button className="player-resume" onClick={()=>void video.current?.play().then(()=>setNeedsPlay(false)).catch(()=>setError('无法开始播放，请重试或用系统播放器打开'))}><Play size={22}/>开始播放</button>}
    {error&&<div className="player-error" role="alert"><p>{error}</p><button onClick={()=>onOpen(clip.path,false)}>系统播放器打开<ExternalLink size={14}/></button></div>}
   </div>
   {mediaURL&&<PlayerControls key={clip.path} clip={clip} video={video} stage={cover} roundTotals={clip.roundTotals} onError={setError} wide={wide} onWide={toggleWide} onPrevious={onPrevious} onNext={onNext}/>}
  </div>
  <div className="watch-title-row"><h1 title={displayName}>{displayName}</h1><button className="watch-details-toggle" type="button" aria-label="片段详情" aria-expanded={!wide&&detailsOpen} aria-controls={detailsId} onClick={showDetails}>{!wide&&detailsOpen?'收起详情':'展开详情'}<ChevronDown size={15}/></button></div>
  {!wide&&<div className="watch-actions" role="group" aria-label="当前片段操作"><button className="clip-action" disabled={disabled} aria-label="查看文件" title="在文件夹中查看视频" onClick={()=>onOpen(clip.path,true)}><FolderOpen size={16}/></button><ClipActionButtons file={clip.path} name={displayName} labels="share"/><ClipDeleteButton className="clip-action" label={`删除片段 ${displayName}`} resetKey={clip.path} deleting={deleting} disabled={deleteDisabled} onDelete={()=>onDelete(clip.path)}/></div>}
  <MotionDisclosure open={!wide&&detailsOpen} id={detailsId}><section className="watch-details" aria-label="片段详细信息"><h2>片段信息</h2><ClipDetails clip={clip} source={source} onFilter={onFilter}/></section></MotionDisclosure>
 </article>;
}
