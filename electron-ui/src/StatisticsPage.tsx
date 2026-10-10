import {useMemo} from 'react';
import type {Result,Clip} from './shared';
import {ApexIcon} from './ClipDetails';
import {clock} from './state';
function sum(clips:Clip[],key:'kills'|'assists'|'knockdowns'|'damage'){
 const values=clips.filter(c=>typeof c[key]==='number');if(!values.length)return '—';
 const n=values.reduce((s,c)=>s+c[key]!,0),partial=values.length<clips.length||values.some(c=>c.statisticsPartial?.[key]??((key==='assists'||key==='knockdowns')&&c.outcomeCountsPartial!==false));return `${partial?'≥':''}${n.toLocaleString('zh-CN')}`;
}
export default function StatisticsPage({results,demo}:{results:Result[];demo:boolean}){
 const clips=useMemo(()=>results.flatMap(r=>r.clips),[results]);const weapons=useMemo(()=>{const counts=new Map<string,number>();for(const c of clips)for(const w of new Set(c.weapons)){const key=w==='未知枪'?'—枪':w;counts.set(key,(counts.get(key)||0)+1);}return [...counts].sort((a,b)=>b[1]-a[1]);},[clips]);
 const ranks=useMemo(()=>{const counts=new Map<string,number>();for(const c of clips){const key=c.rank?c.rank.name+(c.rank.division?` ${c.rank.division}`:''):'未识别';counts.set(key,(counts.get(key)||0)+1);}return [...counts].sort((a,b)=>b[1]-a[1]);},[clips]);
 return <div className="statistics-page" id="page-statistics" role="tabpanel" aria-labelledby="tab-statistics"><div className="page-heading"><h1>统计数据</h1><p>{demo?'状态预览 · 示例数据':'当前任务 · 已导出片段'}</p></div><div className="statistics-totals"><div><span>已识别片段</span><b>{clips.length}</b></div><div><span>片段总时长</span><b>{clock(clips.reduce((s,c)=>s+c.duration,0))}</b></div>{(['kills','assists','knockdowns','damage'] as const).map((key,i)=><div key={key}><span><ApexIcon file={`stats/${key}.svg`}/>{['击杀增量','助攻增量','击倒增量','伤害增量'][i]}</span><b>{sum(clips,key)}</b></div>)}</div>
  <div className="statistics-charts"><section className="stat-card"><h2>枪械出现次数</h2><p>按已识别片段统计</p>{weapons.length?weapons.map(([name,count])=><div className="weapon-bar" key={name}><div><b>{name}</b><span>{count}</span></div><div className="bar-track"><span style={{width:`${count/(weapons[0]?.[1]||1)*100}%`}}/></div></div>):<div className="chart-empty">暂无已导出片段</div>}</section><section className="stat-card"><h2>段位分布</h2><p>录像中本人的当前段位</p><div className="rank-ring"><b>{ranks.length===1?ranks[0][0]:clips.length?`${ranks.filter(r=>r[0]!=='未识别').length} 种段位`:'—'}</b></div><div className="rank-distribution">{ranks.map(([name,n])=><div key={name}><span>{name}</span><b>{n} 段</b><div className="bar-track"><span style={{width:`${n/clips.length*100}%`}}/></div></div>)}</div></section></div>
  <p className="statistics-disclaimer">“≥”为已确认下限；“—”表示暂无可靠计数。枪械次数来自当前片段样本。</p>
 </div>;
}
