import {useMemo,useState,useRef} from 'react';
import type {Result,Clip} from './shared';
import {ApexIcon,weaponFor} from './ClipDetails';
import {clock} from './state';
import MotionDisclosure from './MotionDisclosure';
import {useMotionPresence} from './surfaceMotion';

function frequency(clips:Clip[],values:(clip:Clip)=>string[]){
 const seen=new Set<string>(),counts=new Map<string,number>();
 for(const clip of clips){const match=clip.matchKey||clip.source||clip.path;for(const name of new Set(values(clip))){const key=match+'|'+name.toLocaleLowerCase();if(seen.has(key))continue;seen.add(key);counts.set(name,(counts.get(name)||0)+1);}}
 return [...counts].sort((a,b)=>b[1]-a[1]);
}
function sum(clips:Clip[],key:'kills'|'damage'){
 const values=clips.filter(c=>typeof c[key]==='number');if(!values.length)return '—';const n=values.reduce((s,c)=>s+c[key]!,0),partial=values.length<clips.length||values.some(c=>c.statisticsPartial?.[key]);return (partial?'≥':'')+n.toLocaleString('zh-CN');
}
export default function StatisticsPage({results,demo}:{results:Result[];demo:boolean}){
 const [moreWeapons,setMoreWeapons]=useState(false),[moreRanks,setMoreRanks]=useState(false),[hover,setHover]=useState<string|null>(null);
 const [moreTeams,setMoreTeams]=useState(false),[moreHeroes,setMoreHeroes]=useState(false);
 const rankPopup=useRef<HTMLDivElement>(null),lastHover=useRef(''),hoverPresent=useMotionPresence(!!hover,rankPopup);if(hover)lastHover.current=hover;
 const clips=useMemo(()=>{const unique=new Map<string,Clip>();for(const r of results)for(const clip of r.clips)unique.set(clip.path.toLowerCase(),clip);return [...unique.values()];},[results]);
 const weapons=useMemo(()=>frequency(clips,clip=>clip.weapons.filter(name=>!['未知枪','—枪'].includes(name))),[clips]);
 const teammates=useMemo(()=>frequency(clips,clip=>(clip.teammates||[]).filter(player=>player.confidence>=.8&&player.name!==clip.accountName).map(player=>player.name)),[clips]);
 const heroes=useMemo(()=>frequency(clips,clip=>clip.hero?[clip.hero.name]:[]),[clips]);
 const ranks=useMemo(()=>{const counts=new Map<string,{name:string;n:number;tier:string}>();for(const c of clips){const valid=c.rank&&c.rank.method!=='example'&&c.rank.confidence>=.8,key=valid?c.rank!.tier:'unknown',name=valid?c.rank!.name:'未识别';const old=counts.get(key);counts.set(key,{name,tier:key,n:(old?.n||0)+1});}return [...counts.values()].sort((a,b)=>b.n-a.n);},[clips]);
 const known=ranks.filter(r=>r.tier!=='unknown'),knownCount=known.reduce((n,r)=>n+r.n,0),total=clips.length||1,circumference=2*Math.PI*66;
 const colorFor=(tier:string,i:number)=>tier==='unknown'?'var(--card-line)':tier==='platinum'?'var(--rank-0)':tier==='diamond'?'var(--rank-1)':tier==='gold'?'var(--rank-2)':tier==='master'||tier==='predator'?'var(--rank-3)':'var(--rank-'+i%4+')';
 let offset=0;const sectors=ranks.map((rank,i)=>{const start=offset;offset+=rank.n/total*circumference;return {...rank,color:colorFor(rank.tier,i),start,length:rank.n/total*circumference};});
 return <div className="statistics-page" tabIndex={0} id="page-statistics" role="tabpanel" aria-labelledby="tab-statistics"><div className="page-heading"><div className="heading-with-info"><h1>统计数据</h1></div></div>
  <div className="statistics-totals"><div><span>已识别片段</span><b>{clips.length}</b></div><div><span>片段总时长</span><b>{clock(clips.reduce((s,c)=>s+c.duration,0))}</b></div><div><span>击杀增量</span><b>{sum(clips,'kills')}</b></div><div><span>伤害增量</span><b>{sum(clips,'damage')}</b></div></div>
  <div className="statistics-charts"><section className="stat-card weapons-stat"><h2>常玩武器</h2>{weapons.slice(0,3).map(([name,n])=>{const asset=weaponFor(name);return <div className="weapon-summary" key={name}><div className="weapon-art">{asset?<ApexIcon file={asset.file} className="weapon-stat-icon"/>:<span>—</span>}</div><div className="weapon-summary-data"><div><b>{name}</b><span>{n}次记录</span></div><div className="bar-track"><span style={{width:n/(weapons[0]?.[1]||1)*100+'%'}}/></div></div></div>;})}
   {!weapons.length&&<div className="chart-empty">暂无可靠枪械记录</div>}<button className="statistics-expand" aria-expanded={moreWeapons} disabled={weapons.length<=3} onClick={()=>setMoreWeapons(!moreWeapons)}>{moreWeapons?'收起':'展开更多'}</button><MotionDisclosure open={moreWeapons}><div className="stat-more">{weapons.slice(3).map(([name,n])=><div key={name}><span>{name}</span><b>{n}次</b></div>)}</div></MotionDisclosure>
  </section><section className="stat-card ranks-stat"><div className="heading-with-info"><h2>段位分布</h2></div>
   <div className="rank-ring-wrapper"><svg className="rank-ring" width="144" height="144" viewBox="0 0 144 144" aria-label="本人段位片段分布"><circle cx="72" cy="72" r="66" fill="none" stroke="var(--card-line)" strokeWidth="12"/>{knownCount?sectors.map(rank=><circle key={rank.tier} cx="72" cy="72" r="66" fill="none" stroke={rank.color} strokeWidth="12" strokeDasharray={rank.length+' '+(circumference-rank.length)} strokeDashoffset={-rank.start} transform="rotate(-90 72 72)" tabIndex={0} aria-label={rank.name+' '+rank.n+'段'} onPointerEnter={()=>setHover(rank.name+' · '+rank.n+'段')} onPointerLeave={()=>setHover(null)} onFocus={()=>setHover(rank.name+' · '+rank.n+'段')} onBlur={()=>setHover(null)}><title>{rank.name+' · '+rank.n+'段'}</title></circle>):<circle cx="72" cy="72" r="66" fill="none" stroke="var(--rank-0)" strokeWidth="12" strokeDasharray="8 4"><title>暂无可靠段位数据</title></circle>}</svg><div className="rank-ring-center">{known.length===1?known[0].name:knownCount?knownCount+'段':'未识别'}</div>{hoverPresent&&<div ref={rankPopup} data-motion-surface aria-hidden={!hover} inert={!hover} className="rank-hover" role="tooltip">{hover||lastHover.current}</div>}</div>
   <div className="rank-legend">{ranks.slice(0,3).map((r,i)=><div key={r.tier}><span className="rank-dot" style={{background:colorFor(r.tier,i)}}/><span>{r.name}</span><b>{r.n}段</b></div>)}</div><button className="statistics-expand" aria-expanded={moreRanks} disabled={ranks.length<=3} onClick={()=>setMoreRanks(!moreRanks)}>{moreRanks?'收起':'展开更多'}</button><MotionDisclosure open={moreRanks}><div className="stat-more">{ranks.slice(3).map(r=><div key={r.tier}><span>{r.name}</span><b>{r.n}段</b></div>)}</div></MotionDisclosure>
  </section>{[{title:'常玩队友',data:teammates,more:moreTeams,toggle:()=>setMoreTeams(!moreTeams)},{title:'常玩英雄',data:heroes,more:moreHeroes,toggle:()=>setMoreHeroes(!moreHeroes)}].map(group=><section className="stat-card" key={group.title}><h2>{group.title}</h2>{group.data.slice(0,3).map(([name,n])=><div className="preference-summary" key={name}><div><b>{name}</b><span>{n}次记录</span></div><div className="bar-track"><span style={{width:n/(group.data[0]?.[1]||1)*100+'%'}}/></div></div>)}<MotionDisclosure open={group.more}>{group.data.slice(3).map(([name,n])=><div className="preference-summary" key={name}><div><b>{name}</b><span>{n}次记录</span></div><div className="bar-track"><span style={{width:n/(group.data[0]?.[1]||1)*100+'%'}}/></div></div>)}</MotionDisclosure>{!group.data.length&&<div className="chart-empty">—<p>可在片段库补充 HUD 信息</p></div>}<button className="statistics-expand" disabled={group.data.length<=3} aria-expanded={group.more} onClick={group.toggle}>{group.more?'收起':'展开更多'}</button></section>)}</div>
 </div>;
}
