import type {ReactNode} from 'react';
import {Filter,LocateFixed,LoaderCircle,Square,ChevronLeft,ChevronRight} from 'lucide-react';
import type {HudJob} from './useHudEnrichment';

export default function PlaybackBrowserHeader({total,position,filterCount,filtersOpen,onFilters,onLocate,sort,job,onStop,horizontal=false,onRailScroll}:{total:number;position:number;filterCount:number;filtersOpen:boolean;onFilters:()=>void;onLocate:()=>void;sort:ReactNode;job:HudJob|null;onStop:()=>void;horizontal?:boolean;onRailScroll?:(direction:number)=>void}){
 return <header className="playback-browser-header" aria-label="播放片段浏览">
  <div className="playback-browser-title"><h2>片段<span>{total}</span></h2><div>{horizontal&&<><button type="button" className="playback-browser-icon" aria-label="向左浏览片段" onClick={()=>onRailScroll?.(-1)}><ChevronLeft size={17}/></button><button type="button" className="playback-browser-icon" aria-label="向右浏览片段" onClick={()=>onRailScroll?.(1)}><ChevronRight size={17}/></button></>}<button type="button" className="playback-browser-icon" aria-label="定位当前片段" title="定位当前片段" disabled={!position} onClick={onLocate}><LocateFixed size={17}/></button><button type="button" className="playback-browser-icon" aria-label="筛选播放列表" title="筛选片段" aria-expanded={filtersOpen} onClick={onFilters}><Filter size={16}/>{filterCount>0&&<span className="playback-filter-count">{filterCount}</span>}</button></div></div>
  <div className="playback-browser-order">{!horizontal&&sort}<span>{position?`${position} / ${total}`:'当前片段不在结果中'}</span></div>
  {job?.running&&<div className="playback-job-progress" role="status"><LoaderCircle size={13} className="loading-spinner"/><span>识别 {job.progress.completed} / {job.progress.total}</span><button type="button" className="playback-browser-icon" aria-label="停止HUD识别" title="停止识别" onClick={onStop}><Square size={12}/></button></div>}
 </header>;
}
