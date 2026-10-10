import {useEffect,useRef,useState} from 'react';
import type {ClipView} from './ClipLibrary';
import {ExternalLink,Film,Minimize2,Play,ShieldCheck} from 'lucide-react';
import type {Clip} from './shared';
import {clock} from './state';
import ClipDetails from './ClipDetails';

export default function ClipCard({clip,index,identity,view,playback,verified,selected,disabled,reduced,onSelect,onCollapse,onOpen}:{clip:Clip;index:number;identity:string;view:ClipView;playback:Map<string,number>;verified?:boolean;selected:boolean;disabled:boolean;reduced:boolean;onSelect:()=>void;onCollapse:()=>void;onOpen:(folder:boolean)=>void}){
 const[media,setMedia]=useState<string|null>(null);const[error,setError]=useState('');const[playing,setPlaying]=useState(false);const[needsPlay,setNeedsPlay]=useState(false);
 const video=useRef<HTMLVideoElement|null>(null);const cover=useRef<HTMLDivElement|null>(null);const scrolled=useRef(false);
 const displayName=clip.name.replace('未知杀',clip.kills===null?'—杀':`${clip.kills}杀`).replace('未知伤',clip.damage===null?'—伤':`${clip.damage}伤`).replaceAll('未知枪','—枪');
 useEffect(()=>{
  let live=true;setError('');setPlaying(false);setNeedsPlay(false);scrolled.current=false;
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
 function expanded(){if(selected&&!scrolled.current){scrolled.current=true;cover.current?.scrollIntoView({block:'nearest',behavior:reduced?'instant':'smooth'});}}
 return <article className={`clip-card ${selected?'clip-expanded':''}`} data-identity={identity} data-path={clip.path} data-selected={selected}>
  <svg className="card-surface" aria-hidden="true" preserveAspectRatio="none"><path/></svg>
  <div ref={cover} className="clip-cover">
   {selected&&media?<video ref={video} src={media} poster={clip.thumbnail} controls playsInline preload="metadata" aria-label={`播放交战 ${index}`} onLoadedMetadata={e=>{const t=playback.get(identity);if(t&&t<e.currentTarget.duration)e.currentTarget.currentTime=t;}} onTimeUpdate={e=>playback.set(identity,e.currentTarget.currentTime)} onPlay={()=>{setPlaying(true);setNeedsPlay(false);}} onPause={()=>setPlaying(false)} onError={()=>setError('此片段暂时无法在应用内播放，可使用系统播放器打开')}/>:clip.thumbnail?<img src={clip.thumbnail} alt="交战片段代表画面" loading="lazy" decoding="async"/>:<div className="cover-placeholder"><Film size={32}/>片段已保存</div>}
   {!selected&&<><span className="duration">{clock(clip.duration)}</span><button aria-label={`播放第${index}段`} className="play-button" disabled={disabled} onClick={onSelect}><Play size={18} fill="currentColor"/></button></>}
   {selected&&!media&&!error&&<div className="player-loading" role="status">正在打开视频…</div>}
   {selected&&needsPlay&&!error&&<button className="player-resume" aria-label="开始播放" onClick={()=>void video.current?.play().catch(()=>setError('无法开始播放，请重试或用系统播放器打开'))}><Play size={22}/>开始播放</button>}
   {selected&&error&&<div className="player-error" role="alert"><p>{error}</p><button className="secondary" onClick={()=>onOpen(false)}>系统播放器打开<ExternalLink size={14}/></button></div>}
  </div>
  <div className="clip-info">
   <div className="clip-number">交战 {String(index).padStart(2,'0')}<span>{verified?<><ShieldCheck size={13}/>无损已校验</>:'未执行无损校验'}</span>{selected&&<button className="player-collapse" aria-label={`收起第${index}段`} onClick={onCollapse}><Minimize2 size={14}/>收起播放</button>}</div>
   {selected&&<div className="player-caption"><span>{playing?'正在播放':'已暂停'} · {clock(clip.duration)}</span><span>拖动进度条可定位片段</span></div>}
   <h3 title={clip.name}>{displayName}</h3><ClipDetails clip={clip} compact={view!=='detail'&&!selected}/>{view!=='detail'&&!selected&&<details className="compact-details"><summary>详情 →</summary><ClipDetails clip={clip}/></details>}
   <button className="text-button" disabled={disabled} onClick={()=>onOpen(true)}>查看文件<ExternalLink size={13}/></button>
  </div>
 </article>;
}
