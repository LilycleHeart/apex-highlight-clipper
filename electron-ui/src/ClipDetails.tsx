import type {Clip} from './shared';
import {clock} from './state';
import {recordingTime,recordingTimeLabel} from './clipStats';
import weapons from './weaponIcons.json';

const asset=(file:string)=>new URL(`${import.meta.env.BASE_URL}apex-icons/${file}`,location.href).href;
export function ApexIcon({file,className=''}:{file:string;className?:string}){
 return <span aria-hidden="true" className={`apex-icon ${className}`} style={{maskImage:`url("${asset(file)}")`,WebkitMaskImage:`url("${asset(file)}")`}}/>;
}
function weaponFor(name:string){const key=name.toLowerCase().replace(/[\s.\-_]/g,'');return weapons.find(w=>[w.name,w.id,...w.aliases].some(alias=>alias.toLowerCase().replace(/[\s.\-_]/g,'')===key));}
export default function ClipDetails({clip,compact=false}:{clip:Clip;compact?:boolean}){
 const partial=clip.statisticsPartial?Object.values(clip.statisticsPartial).some(Boolean):clip.outcomeCountsPartial!==false;
 const recordedAt=clip.recordedAt||recordingTime(clip.name);
 const observed=(n:number|null|undefined,key:'kills'|'assists'|'knockdowns'|'damage')=>n===null||n===undefined?'—':`${(clip.statisticsPartial?.[key]??(key==='assists'||key==='knockdowns'?partial:false))?'≥':''}${n}`;
 return <div className="clip-details">
  {!compact&&<div className="clip-recorded" aria-label="录制日期时间"><span>录制时间</span><time dateTime={recordedAt||undefined}>{recordingTimeLabel(recordedAt)}</time></div>}
  <dl className="combat-stats" aria-label="本段识别战绩">
   <div><dt title="击杀" aria-label="击杀"><ApexIcon file="stats/kills.svg"/></dt><dd>{observed(clip.kills,'kills')}</dd></div>
   <div><dt title="助攻" aria-label="助攻"><ApexIcon file="stats/assists.svg"/></dt><dd>{observed(clip.assists,'assists')}</dd></div>
   <div><dt title="击倒" aria-label="击倒"><ApexIcon file="stats/knockdowns.svg"/></dt><dd>{observed(clip.knockdowns,'knockdowns')}</dd></div>
   <div><dt title="伤害" aria-label="伤害"><ApexIcon file="stats/damage.svg"/></dt><dd>{observed(clip.damage,'damage')}</dd></div>
  </dl>
  <div className="clip-weapons" aria-label="识别枪械">{(clip.weapons.length?clip.weapons:['未知枪']).map(name=>{const w=weaponFor(name);return <span className="weapon-chip" key={name}>{w&&<ApexIcon className="weapon-icon" file={w.file}/>}<span>{name==='未知枪'?'—枪':name}</span></span>;})}</div>
  {!compact&&<><div className="clip-range"><span>原片时间</span><b>{clock(clip.start)} — {clock(clip.end)}</b></div>
  <div className="clip-rank" aria-label="本人当前段位">{clip.rank?<><img src={asset(`ranks/${clip.rank.tier}.png`)} alt=""/><span>本人段位</span><b>{clip.rank.name}{clip.rank.division?` ${clip.rank.division}`:''}</b></>:<><span>本人段位</span><b>未识别</b></>}</div>
  {partial&&<p className="stats-basis">“≥”表示已确认下限；“—”表示暂无可靠计数。</p>}
  {clip.settlementTotals&&<p className="stats-basis">末队结算累计 {clip.settlementTotals.kills} 杀 / {clip.settlementTotals.assists} 助攻，已按本段基线扣除。</p>}
  {!!clip.evidence?.length&&<details className="outcome-evidence"><summary>查看已确认战果</summary>{clip.evidence.map((e,i)=><div key={`${e.time}-${i}`}><time>{clock(e.time)}</time><b>{e.kind==='knock'?'本人击倒':e.kind==='assist'?'本人助攻':'本人消灭'}</b>{e.text&&<span>{e.text}</span>}</div>)}</details>}
 </>}
 </div>;
}
