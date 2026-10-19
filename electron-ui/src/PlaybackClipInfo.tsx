import {Volume2} from 'lucide-react';
import type {Clip} from './shared';
import {ApexIcon} from './ClipDetails';
import {recordingTime} from './clipStats';

export default function PlaybackClipInfo({clip,source,index,current}:{clip:Clip;source?:string;index:number;current:boolean}){
 const recordedAt=clip.recordedAt||recordingTime(clip.source||source||clip.name),date=recordedAt?.match(/^\d{4}-(\d{2})-(\d{2})[T ](\d{2}:\d{2})/);
 const weapons=clip.weapons.filter(name=>!['未知枪','—枪'].includes(name)),context=[clip.hero?.name,weapons.join(' / ')].filter(Boolean).join(' · ');
 const observed=(key:'kills'|'damage')=>clip[key]==null?'—':`${clip.statisticsPartial?.[key]?'≥':''}${clip[key]}`;
 return <div className="playback-clip-info">
  <div className="playback-clip-title"><h3>交战 {String(index).padStart(2,'0')}</h3>{current&&<Volume2 size={14} aria-label="当前片段"/>}</div>
  <time dateTime={recordedAt||undefined}>{date?`${Number(date[1])}/${Number(date[2])} ${date[3]}`:'录制时间待确认'}</time>
  {context&&<p className="playback-clip-context" title={context}>{context}</p>}
  <div className="playback-clip-stats"><span title="击杀" aria-label={`击杀 ${observed('kills')}`}><ApexIcon file="stats/kills.svg"/>{observed('kills')}</span><span title="伤害" aria-label={`伤害 ${observed('damage')}`}><ApexIcon file="stats/damage.svg"/>{observed('damage')}</span></div>
 </div>;
}
