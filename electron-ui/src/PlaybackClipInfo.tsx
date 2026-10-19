import {Film,Volume2} from 'lucide-react';
import type {Clip} from './shared';
import {ApexIcon} from './ClipDetails';
import {recordingTime} from './clipStats';

export default function PlaybackClipInfo({clip,source,index,current,compact=false}:{clip:Clip;source?:string;index:number;current:boolean;compact?:boolean}){
 const recordedAt=clip.recordedAt||recordingTime(clip.source||source||clip.name),date=recordedAt?.match(/^\d{4}-(\d{2})-(\d{2})[T ](\d{2}:\d{2})/);
 const weapons=clip.weapons.filter(name=>!['未知枪','—枪'].includes(name)),context=[clip.hero?.name,weapons.join(' / ')].filter(Boolean).join(' · ');
 const original=source||clip.source||'',sourceName=original.split(/[\\/]/).pop()||'原录像待确认';
 const partial=clip.statisticsPartial?Object.values(clip.statisticsPartial).some(Boolean):clip.outcomeCountsPartial!==false;
 const observed=(key:'kills'|'assists'|'knockdowns'|'damage')=>clip[key]==null?'—':`${(clip.statisticsPartial?.[key]??((key==='assists'||key==='knockdowns')&&partial))?'≥':''}${clip[key]}`;
 return <div className={`playback-clip-info ${compact?'is-compact':''}`}>
  <div className="playback-clip-title"><span className="playback-clip-index">{String(index).padStart(2,'0')}</span><h3 title={clip.name}>{clip.name}</h3>{current&&<Volume2 size={14} aria-label="当前片段"/>}</div>
  <p className="playback-clip-source" title={original||sourceName}><Film size={11}/><span>{sourceName}</span></p>
  <time dateTime={recordedAt||undefined}>{date?`${Number(date[1])}/${Number(date[2])} ${date[3]}`:'录制时间待确认'}</time>
  {context&&<p className="playback-clip-context" title={context}>{context}</p>}
  <div className="playback-clip-stats">{([['kills','击杀'],['assists','助攻'],['knockdowns','击倒'],['damage','伤害']] as const).map(([key,label])=><span key={key} title={label} aria-label={`${label} ${observed(key)}`}><ApexIcon file={`stats/${key}.svg`}/>{observed(key)}</span>)}</div>
 </div>;
}
