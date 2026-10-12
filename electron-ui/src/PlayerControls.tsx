import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Play,Pause,Volume2,VolumeX,Maximize,Minimize} from 'lucide-react';
import type {Clip} from './shared';
import InfoTip from './InfoTip';
import {ApexIcon} from './ClipDetails';
import {clipEvents,eventGroups} from './eventTimeline';
import {readPlayerAudio,rememberPlayerAudio} from './playerAudio';
import EventMarker,{preciseClock} from './EventMarker';
import ClipDeleteButton from './ClipDeleteButton';
export {preciseClock} from './EventMarker';
export default function PlayerControls({clip,video,stage,roundTotals,onError,onCollapse,onDetails,onDelete,deleteDisabled}:{clip:Clip;video:{current:HTMLVideoElement|null};stage:{current:HTMLDivElement|null};roundTotals?:{kills:number|null;damage:number|null;partial?:{kills?:boolean;damage?:boolean}};onError:(message:string)=>void;onCollapse:()=>void;onDetails:()=>void;onDelete:()=>void;deleteDisabled:boolean}){
 const initialAudio=useRef(readPlayerAudio()).current;
 const [audioSaveFailed,setAudioSaveFailed]=useState(false);
 const [time,setTime]=useState(0),[duration,setDuration]=useState(clip.duration),[playing,setPlaying]=useState(false),[volume,setVolume]=useState(initialAudio.volume),[muted,setMuted]=useState(initialAudio.muted),[width,setWidth]=useState(600),[fullscreen,setFullscreen]=useState(false),[controlsVisible,setControlsVisible]=useState(true);
 const [volumeVisible,setVolumeVisible]=useState(false),[volumePercent,setVolumePercent]=useState(Math.round((initialAudio.muted?0:initialAudio.volume)*100));
 const bar=useRef<HTMLDivElement>(null),pending=useRef<number|null>(null),volumeTimer=useRef<ReturnType<typeof setTimeout>|null>(null),lastAudibleVolume=useRef(initialAudio.lastAudibleVolume);
 const showVolume=useCallback((value:number)=>{setVolumePercent(Math.round(value*100));setVolumeVisible(true);if(volumeTimer.current!==null)clearTimeout(volumeTimer.current);volumeTimer.current=setTimeout(()=>{setVolumeVisible(false);volumeTimer.current=null;},900);},[]);
 const saveAudio=useCallback((v:HTMLVideoElement)=>{void rememberPlayerAudio({volume:v.volume,muted:v.muted,lastAudibleVolume:lastAudibleVolume.current}).then(()=>setAudioSaveFailed(false),()=>setAudioSaveFailed(true));},[]);
 const changeVolume=useCallback((value:number)=>{const v=video.current;if(!v)return;const next=Math.max(0,Math.min(1,Math.round(value*1000)/1000));v.volume=next;v.muted=next===0;if(next>0)lastAudibleVolume.current=next;setVolume(next);setMuted(next===0);showVolume(next);saveAudio(v);},[video,showVolume,saveAudio]);
 useEffect(()=>{
  const container=stage.current;if(!container)return;
  const wheel=(event:WheelEvent)=>{
   const v=video.current,target=event.target;if(!v||!container.isConnected||container.dataset.playerActive!=='true'||!container.closest('.clip-card[data-selected="true"]')||event.ctrlKey||event.deltaY===0||!(target instanceof Element))return;
   const fullscreenElement=document.fullscreenElement;if(fullscreenElement&&fullscreenElement!==container)return;
   // Inline playback keeps ordinary wheel gestures available for page scrolling.
   const surface=target.closest(fullscreenElement===container?'.media-frame,.player-volume':'.player-volume');if(!surface||!container.contains(surface)||target.closest('.event-hover-popover'))return;
   const box=surface.getBoundingClientRect(),scroller=container.closest('.library-scroll')?.getBoundingClientRect();
   if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)return;
   if(!document.fullscreenElement&&scroller&&(event.clientY<scroller.top||event.clientY>scroller.bottom))return;
   // A stale or occluded player must never consume the page's scrolling.
   const hit=document.elementFromPoint(event.clientX,event.clientY);if(!hit||!surface.contains(hit))return;
   if(event.cancelable)event.preventDefault();event.stopPropagation();
   const pixels=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?container.clientHeight:1),change=Math.sign(pixels)*Math.min(.05,Math.abs(pixels)/2000);changeVolume((v.muted?0:v.volume)-change);
  };
  container.addEventListener('wheel',wheel,{passive:false});return()=>container.removeEventListener('wheel',wheel);
 },[clip.path,stage,video,changeVolume]);
 useEffect(()=>{const update=()=>{setFullscreen(document.fullscreenElement===stage.current);setControlsVisible(true);};document.addEventListener('fullscreenchange',update);update();return()=>document.removeEventListener('fullscreenchange',update);},[stage]);
 useEffect(()=>{
  const container=stage.current;if(!container)return;let timer:ReturnType<typeof setTimeout>|undefined;
  const focused=()=>{const el=document.activeElement;return el instanceof HTMLElement&&container.contains(el)&&el.matches(':focus-visible');};
  const schedule=()=>{clearTimeout(timer);const inside=container.matches(':hover');setControlsVisible(!playing||inside||focused());if(!fullscreen||!playing||!inside)return;timer=setTimeout(()=>{if(focused()||container.querySelector('.player-controls:hover,.event-hover-popover:hover'))schedule();else setControlsVisible(false);},2400);};
  const leave=()=>{clearTimeout(timer);if(playing&&!focused())setControlsVisible(false);};
  for(const name of ['pointerenter','pointermove','pointerdown','keydown','focusin','focusout'])container.addEventListener(name,schedule);container.addEventListener('pointerleave',leave);schedule();
  return()=>{clearTimeout(timer);for(const name of ['pointerenter','pointermove','pointerdown','keydown','focusin','focusout'])container.removeEventListener(name,schedule);container.removeEventListener('pointerleave',leave);};
 },[fullscreen,playing,stage]);
 const visible=controlsVisible;
 useEffect(()=>{const container=stage.current;if(!container)return;container.dataset.controlsVisible=String(visible);return()=>{delete container.dataset.controlsVisible;};},[stage,visible]);
 useEffect(()=>()=>{if(volumeTimer.current!==null)clearTimeout(volumeTimer.current);},[]);
 useEffect(()=>{const v=video.current;if(!v)return;const update=()=>{setTime(v.currentTime);setPlaying(!v.paused&&!v.ended);setMuted(v.muted);setVolume(v.volume);if(Number.isFinite(v.duration)&&v.duration>0)setDuration(v.duration);};const ready=()=>{if(pending.current!==null){v.currentTime=pending.current;pending.current=null;}update();};for(const name of ['timeupdate','play','pause','volumechange','ended','seeked'])v.addEventListener(name,update);v.addEventListener('loadedmetadata',ready);update();return()=>{for(const name of ['timeupdate','play','pause','volumechange','ended','seeked'])v.removeEventListener(name,update);v.removeEventListener('loadedmetadata',ready);};},[clip.path,video]);
 useEffect(()=>{if(!bar.current)return;const observer=new ResizeObserver(entries=>setWidth(entries[0].contentRect.width));observer.observe(bar.current);return()=>observer.disconnect();},[]);
 const events=useMemo(()=>clipEvents(clip,duration),[clip,duration]),groups=useMemo(()=>eventGroups(events,duration,width,80),[events,duration,width]);
 function seek(target:number){const v=video.current;if(!v)return;const next=Math.max(0,Math.min(duration,target));v.dataset.seekRequested=String(next);if(v.readyState<1)pending.current=next;else v.currentTime=next;setTime(next);}
 function play(){const v=video.current;if(!v)return;if(v.paused)void v.play().catch(()=>onError('无法开始播放，可重试或使用系统播放器'));else v.pause();}
 function toggleMute(){const v=video.current;if(!v)return;if(v.muted||v.volume===0)changeVolume(v.volume||lastAudibleVolume.current);else{lastAudibleVolume.current=v.volume;v.muted=true;setMuted(true);showVolume(0);saveAudio(v);}}
 function toggleFullscreen(){if(document.fullscreenElement)void document.exitFullscreen().catch(()=>onError('无法退出全屏'));else void stage.current?.requestFullscreen().catch(()=>onError('无法进入全屏'));}
 const totals=roundTotals||{kills:clip.kills,damage:clip.damage,partial:clip.statisticsPartial};
 const observed=(key:'kills'|'damage')=>totals[key]===null||totals[key]===undefined?'—':`${totals.partial?.[key]?'≥':''}${totals[key]}`;
 return <><div className="player-controls" data-visible={visible} aria-hidden={!visible} inert={!visible}>
  <div className="event-seekbar" ref={bar}>
   <div className="event-markers">{groups.map(g=><EventMarker key={g.id} events={g.events} fraction={g.fraction} onSeek={event=>seek(event.seekTime)}/>)}</div>
   <input type="range" className="video-seek" aria-label="视频进度" min="0" max={duration||0} step="0.01" value={Math.min(time,duration)} onChange={e=>seek(e.target.valueAsNumber)} style={{background:'linear-gradient(to right,var(--card-accent) '+(duration>0?time/duration*100:0)+'%,var(--card-line) 0)'}}/>
  </div>
  <div className="player-control-row"><button className="player-play" aria-label={playing?'暂停视频':'播放视频'} onClick={play}>{playing?<Pause size={18}/>:<Play size={18}/>}</button><time>{preciseClock(time)} / {preciseClock(duration)}</time><InfoTip label="事件标记说明" text={events.length?'悬停或聚焦标记查看 HUD 信息，点击从对应交战过程起点回看，标记时间表示结果发生时刻。密集事件可逐条选择；键盘按向下键进入事件列表。':'此片段没有可靠的事件级 HUD 信息。'}/><button className="player-details-button" aria-label="片段详情" onClick={onDetails}>详情</button><button className="player-collapse-button" aria-label="收起播放" onClick={onCollapse}>收起</button><ClipDeleteButton className="player-delete" label="删除当前片段" resetKey={clip.path} disabled={deleteDisabled} onDelete={onDelete}/><div className="player-volume">{audioSaveFailed&&<span role="status" title="音量调整已生效，但设置暂时无法保存">音量未保存</span>}<button aria-label={muted||volume===0?'取消静音':'静音'} onClick={toggleMute}>{muted||volume===0?<VolumeX size={17}/>:<Volume2 size={17}/>}</button><input type="range" aria-label="音量" min="0" max="1" step="0.01" value={muted?0:volume} onChange={e=>changeVolume(e.target.valueAsNumber)}/></div><button aria-label="切换全屏" aria-pressed={fullscreen} title={fullscreen?'退出全屏':'全屏播放'} onClick={toggleFullscreen}>{fullscreen?<Minimize size={17}/>:<Maximize size={17}/>}</button></div>
 </div>{stage.current&&createPortal(<>
  <div className="player-round-totals" data-visible={visible} aria-hidden={!visible} aria-label={roundTotals?'本局战绩':'本段战绩'}><span>{roundTotals?'本局':'本段'}</span><span><ApexIcon file="stats/kills.svg"/><span>击杀</span><b>{observed('kills')}</b></span><span><ApexIcon file="stats/damage.svg"/><span>伤害</span><b>{observed('damage')}</b></span></div>
  <div className="player-volume-hud" data-visible={volumeVisible} aria-hidden={!volumeVisible} role="status" aria-live="polite"><div className="player-volume-hud-value">{volumePercent===0?<VolumeX size={28}/>:<Volume2 size={28}/>}<strong>{volumePercent}%</strong></div><div className="player-volume-hud-track" aria-hidden="true"><span style={{width:volumePercent+'%'}}/></div></div>
 </>,stage.current)}</>;
}
