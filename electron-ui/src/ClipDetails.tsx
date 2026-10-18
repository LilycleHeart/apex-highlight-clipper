import type {Clip} from './shared';
import type {ReactNode} from 'react';
import type {ClipDetailFilter} from './libraryFilters';
import {dateFilterLabel} from './libraryFilters';
import {recordingDay} from './clipTimeline';
import MotionDetails from './MotionDetails';
import {clock} from './state';
import {recordingTime,recordingTimeLabel} from './clipStats';
import weapons from './weaponIcons.json';

export const apexAsset=(file:string)=>new URL(`${import.meta.env.BASE_URL}apex-icons/${file}`,location.href).href;
export const rankAsset=(tier:string)=>apexAsset(`ranks/${tier}.${tier==='unranked'?'svg':'png'}`);
export function ApexIcon({file,className=''}:{file:string;className?:string}){
 return <span aria-hidden="true" className={`apex-icon ${className}`} style={{maskImage:`url("${apexAsset(file)}")`,WebkitMaskImage:`url("${apexAsset(file)}")`}}/>;
}
export function weaponFor(name:string){const key=name.toLowerCase().replace(/[\s.\-_]/g,'');return weapons.find(w=>[w.name,w.id,...w.aliases].some(alias=>alias.toLowerCase().replace(/[\s.\-_]/g,'')===key));}
export default function ClipDetails({clip,source,compact=false,summary=true,onFilter}:{clip:Clip;source?:string;compact?:boolean;summary?:boolean;onFilter?:(filter:ClipDetailFilter)=>void}){
 const partial=clip.statisticsPartial?Object.values(clip.statisticsPartial).some(Boolean):clip.outcomeCountsPartial!==false;
 const originalSource=source||clip.source,recordedAt=clip.recordedAt||recordingTime(originalSource||clip.name),day=recordingDay(clip,originalSource);
 const filterable=(children:ReactNode,filter:ClipDetailFilter|undefined,className='')=>onFilter&&filter?<button type="button" className={`detail-filter ${className}`} data-detail-filter={filter.field} aria-label={`按${filter.label}筛选`} title={`点击筛选：${filter.label}`} onClick={()=>onFilter(filter)}>{children}</button>:<span className={className}>{children}</span>;
 const observed=(n:number|null|undefined,key:'kills'|'assists'|'knockdowns'|'damage')=>n===null||n===undefined?'—':`${(clip.statisticsPartial?.[key]??(key==='assists'||key==='knockdowns'?partial:false))?'≥':''}${n}`;
 return <div className="clip-details">
  {!compact&&<div className="clip-recorded" aria-label="录制日期时间"><span>录制时间</span><time dateTime={recordedAt||undefined}>{day?<>{[day.slice(0,4),day.slice(0,7),day].map((value,index)=><span key={value}>{filterable(index===0?`${value}年`:index===1?`${Number(value.slice(5))}月`:`${Number(value.slice(8))}日`,{field:'date',value,label:dateFilterLabel(value)})}</span>)}<span className="recording-clock">{recordedAt?.match(/[T ](\d{2}:\d{2}(?::\d{2})?)/)?.[1]||''}</span></>:recordingTimeLabel(recordedAt)}</time></div>}
  {summary&&<><dl className="combat-stats" aria-label="本段识别战绩">
   <div><dt title="击杀" aria-label="击杀"><ApexIcon file="stats/kills.svg"/></dt><dd>{observed(clip.kills,'kills')}</dd></div>
   <div><dt title="助攻" aria-label="助攻"><ApexIcon file="stats/assists.svg"/></dt><dd>{observed(clip.assists,'assists')}</dd></div>
   <div><dt title="击倒" aria-label="击倒"><ApexIcon file="stats/knockdowns.svg"/></dt><dd>{observed(clip.knockdowns,'knockdowns')}</dd></div>
   <div><dt title="伤害" aria-label="伤害"><ApexIcon file="stats/damage.svg"/></dt><dd>{observed(clip.damage,'damage')}</dd></div>
  </dl>
  <div className="clip-weapons" aria-label="识别枪械">{(clip.weapons.length?clip.weapons:['未知枪']).map(name=>{const w=weaponFor(name);return <span key={name}>{filterable(<>{w&&<ApexIcon className="weapon-icon" file={w.file}/>}<span>{name==='未知枪'?'—枪':name}</span></>,!['未知枪','—枪'].includes(name)?{field:'weapon',value:name,label:`武器：${name}`}:undefined,'weapon-chip')}</span>;})}</div></>}
  {!compact&&<>{originalSource&&<div className="clip-source"><span>原录像</span><b title={originalSource}>{filterable(originalSource.split(/[\\/]/).pop(),{field:'source',value:originalSource,label:`原录像：${originalSource.split(/[\\/]/).pop()}`})}</b></div>}<div className="clip-range"><span>原片时间</span><b>{clock(clip.start)} — {clock(clip.end)}</b></div>
  <div className="clip-identity"><span>本人账号</span><b>{clip.accountName?filterable(clip.accountName,{field:'account',value:clip.accountName,label:`本人账号：${clip.accountName}`}):'—'}</b></div><div className="clip-identity"><span>英雄</span><b>{clip.hero?filterable(clip.hero.name,{field:'hero',value:clip.hero.id,label:`英雄：${clip.hero.name}`}):'—'}</b></div><div className="clip-identity"><span>队友</span><b className="detail-names">{clip.teammates?.length?clip.teammates.map((player,index)=><span key={`${player.name}-${index}`}>{index>0&&'、'}{filterable(player.name,{field:'teammate',value:player.name,label:`队友：${player.name}`})}</span>):'—'}</b></div>
  <div className="clip-rank" aria-label="当前对局模式或段位">{clip.rank?<><img src={rankAsset(clip.rank.tier)} alt=""/><span>{clip.rank.tier==='unranked'?'对局模式':'本人段位'}</span><b>{filterable(clip.rank.name,{field:'rank',value:clip.rank.tier,label:`模式/段位：${clip.rank.name}`})}{clip.rank.division&&<> {filterable(clip.rank.division,{field:'rank',value:clip.rank.tier,division:clip.rank.division,label:`段位：${clip.rank.name} ${clip.rank.division}`})}</>}</b></>:<><span>模式/段位</span><b>未识别</b></>}</div>
  {partial&&<p className="stats-basis">“≥”表示已确认下限；“—”表示暂无可靠计数。</p>}
  {clip.settlementTotals&&<p className="stats-basis">末队结算累计 {clip.settlementTotals.kills} 杀 / {clip.settlementTotals.assists} 助攻，已按本段基线扣除。</p>}
  {!!clip.evidence?.length&&<MotionDetails className="outcome-evidence" label="查看已确认战果">{clip.evidence.map((e,i)=><div key={`${e.time}-${i}`}><time>{clock(e.time)}</time><b>{e.kind==='knock'?'本人击倒':e.kind==='assist'?'本人助攻':'本人消灭'}</b><span>{e.target||'—'}</span>{e.weaponContext&&<span>{e.weaponContext.label}</span>}</div>)}</MotionDetails>}
 </>}
 </div>;
}
