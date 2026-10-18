import {useMemo,useState,useRef,type CSSProperties} from 'react';
import {ChevronDown,UsersRound} from 'lucide-react';
import type {Result,Clip} from './shared';
import {ApexIcon,apexAsset,rankAsset,weaponFor} from './ClipDetails';
import {legendRoles} from './legendRoster';
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
// Fixed accents from the bundled game badges, independent of theme and order.
const rankColors:Record<string,string>={rookie:'#92826a',bronze:'#ba835d',silver:'#b8bbc0',gold:'#e6bd62',platinum:'#80c9cd',diamond:'#54b5ed',master:'#ad78e5',predator:'#ef5144',unranked:'#a9afb9'};
const colorFor=(tier:string)=>rankColors[tier]||'var(--card-line)';
const preview={weapons:3,heroes:8,ranks:3,teammates:3};
function ExpandButton({open,onClick,count,controls}:{open:boolean;onClick:()=>void;count:number;controls:string}){
 return count>0?<button type="button" className="statistics-expand" aria-expanded={open} aria-controls={controls} onClick={onClick}><span>{open?'收起列表':`展开其余 ${count} 项`}</span><ChevronDown size={15}/></button>:null;
}
export default function StatisticsPage({results}:{results:Result[];demo:boolean}){
 const [moreWeapons,setMoreWeapons]=useState(false),[moreRanks,setMoreRanks]=useState(false),[hover,setHover]=useState<string|null>(null);
 const [moreTeams,setMoreTeams]=useState(false),[moreHeroes,setMoreHeroes]=useState(false);
 const rankPopup=useRef<HTMLDivElement>(null),lastHover=useRef(''),hoverPresent=useMotionPresence(!!hover,rankPopup);if(hover)lastHover.current=hover;
 const clips=useMemo(()=>{const unique=new Map<string,Clip>();for(const r of results)for(const clip of r.clips)unique.set(clip.path.toLowerCase(),clip);return [...unique.values()];},[results]);
 const weapons=useMemo(()=>frequency(clips,clip=>clip.weapons.filter(name=>!['未知枪','—枪'].includes(name))),[clips]);
 const teammates=useMemo(()=>frequency(clips,clip=>(clip.teammates||[]).filter(player=>player.confidence>=.8&&player.name!==clip.accountName).map(player=>player.name)).filter(([,count])=>count>=2),[clips]);
 const heroes=useMemo(()=>{
  const observed=new Map(clips.flatMap(clip=>clip.hero?[[clip.hero.id,clip.hero] as const]:[]));
  return frequency(clips,clip=>clip.hero?[clip.hero.id]:[]).map(([id,n])=>({id,n,name:observed.get(id)!.name,role:legendRoles.find(role=>role.legends.some(hero=>hero.id===id))}));
 },[clips]);
 const ranks=useMemo(()=>{const counts=new Map<string,{name:string;n:number;tier:string}>();for(const c of clips){const valid=c.rank&&c.rank.method!=='example'&&c.rank.confidence>=.8,key=valid?c.rank!.tier:'unknown',name=valid?c.rank!.name:'未识别';const old=counts.get(key);counts.set(key,{name,tier:key,n:(old?.n||0)+1});}return [...counts.values()].sort((a,b)=>b.n-a.n);},[clips]);
 const known=ranks.filter(r=>r.tier!=='unknown'),knownCount=known.reduce((n,r)=>n+r.n,0),total=clips.length||1,circumference=2*Math.PI*66;
 let offset=0;const sectors=ranks.map(rank=>{const start=offset;offset+=rank.n/total*circumference;return {...rank,color:colorFor(rank.tier),start,length:rank.n/total*circumference};});
 const weaponRows=(entries:typeof weapons)=>entries.map(([name,n])=>{const asset=weaponFor(name);return <div className="weapon-summary" key={name}><div className="weapon-art">{asset?<ApexIcon file={asset.file} className="weapon-stat-icon"/>:<span>—</span>}</div><div className="weapon-summary-data"><div><b>{name}</b><span>{n}次记录</span></div><div className="bar-track"><span style={{width:n/(weapons[0]?.[1]||1)*100+'%'}}/></div></div></div>;});
 const heroCards=(entries:typeof heroes)=>entries.map(hero=><div className="hero-stat" key={hero.id} style={{'--legend-role-color':hero.role?.color||'var(--card-accent)'} as CSSProperties}>
  <div className="hero-stat-portrait">{hero.role?<img src={apexAsset(`legends/${hero.id}.png`)} alt="" draggable={false}/>:<UsersRound size={42}/>}<span className="hero-stat-count"><b>{hero.n}</b>次记录</span></div>
  <div className="hero-stat-info"><b>{hero.name}</b>{hero.role&&<span className="hero-stat-role"><ApexIcon file={`classes/${hero.role.id}.svg`}/>{hero.role.name}</span>}<div className="bar-track"><span style={{width:hero.n/(heroes[0]?.n||1)*100+'%'}}/></div></div>
 </div>);
 const rankRows=(entries:typeof ranks)=><div className="rank-legend">{entries.map(r=><div key={r.tier}><span className="rank-dot" style={{background:colorFor(r.tier)}}/>{rankColors[r.tier]&&<img src={rankAsset(r.tier)} alt=""/>}<span>{r.name}</span><b>{r.n}段</b></div>)}</div>;
 const teamRows=(entries:typeof teammates)=>entries.map(([name,n])=><div className="preference-summary" key={name}><div><b>{name}</b><span>{n}次记录</span></div><div className="bar-track"><span style={{width:n/(teammates[0]?.[1]||1)*100+'%'}}/></div></div>);
 return <div className="statistics-page" tabIndex={0} id="page-statistics" role="tabpanel" aria-labelledby="tab-statistics"><div className="page-heading"><div className="heading-with-info"><h1>统计数据</h1></div></div>
  <div className="statistics-totals"><div><span>已识别片段</span><b>{clips.length}</b></div><div><span>片段总时长</span><b>{clock(clips.reduce((s,c)=>s+c.duration,0))}</b></div><div><span>击杀增量</span><b>{sum(clips,'kills')}</b></div><div><span>伤害增量</span><b>{sum(clips,'damage')}</b></div></div>
  <div className="statistics-charts"><div className="statistics-column statistics-column-wide">
   <section className="stat-card weapons-stat" aria-labelledby="weapons-stat-heading"><h2 id="weapons-stat-heading">常玩武器</h2>{weaponRows(weapons.slice(0,preview.weapons))}
    {!weapons.length&&<div className="chart-empty">暂无可靠枪械记录</div>}
    <MotionDisclosure id="more-stat-weapons" open={moreWeapons}><div className="weapon-stat-more">{weaponRows(weapons.slice(preview.weapons))}</div></MotionDisclosure>
    <ExpandButton open={moreWeapons} controls="more-stat-weapons" count={weapons.length-preview.weapons} onClick={()=>setMoreWeapons(!moreWeapons)}/>
   </section>
   <section className="stat-card heroes-stat" aria-labelledby="heroes-stat-heading"><div className="stat-heading"><h2 id="heroes-stat-heading">常玩英雄</h2><span>按对局去重</span></div>
    <div className="hero-stat-grid">{heroCards(heroes.slice(0,preview.heroes))}</div><MotionDisclosure id="more-stat-heroes" open={moreHeroes}><div className="hero-stat-grid hero-stat-more">{heroCards(heroes.slice(preview.heroes))}</div></MotionDisclosure>
    {!heroes.length&&<div className="chart-empty">暂无英雄记录<p>可在片段库补充 HUD 信息</p></div>}
    <ExpandButton open={moreHeroes} controls="more-stat-heroes" count={heroes.length-preview.heroes} onClick={()=>setMoreHeroes(!moreHeroes)}/>
   </section>
  </div><div className="statistics-column statistics-column-narrow">
   <section className="stat-card ranks-stat" aria-labelledby="ranks-stat-heading"><h2 id="ranks-stat-heading">模式/段位分布</h2>
    <div className="rank-stat-summary"><div className="rank-ring-wrapper"><svg className="rank-ring" width="144" height="144" viewBox="0 0 144 144" aria-label="对局模式与段位片段分布"><circle cx="72" cy="72" r="66" fill="none" stroke="var(--card-line)" strokeWidth="12"/>{knownCount?sectors.map(rank=><circle key={rank.tier} cx="72" cy="72" r="66" fill="none" stroke={rank.color} strokeWidth="12" strokeDasharray={rank.length+' '+(circumference-rank.length)} strokeDashoffset={-rank.start} transform="rotate(-90 72 72)" tabIndex={0} aria-label={rank.name+' '+rank.n+'段'} onPointerEnter={()=>setHover(rank.name+' · '+rank.n+'段')} onPointerLeave={()=>setHover(null)} onFocus={()=>setHover(rank.name+' · '+rank.n+'段')} onBlur={()=>setHover(null)}><title>{rank.name+' · '+rank.n+'段'}</title></circle>):<circle cx="72" cy="72" r="66" fill="none" stroke="var(--card-muted)" strokeWidth="12" strokeDasharray="8 4"><title>暂无可靠模式或段位数据</title></circle>}</svg><div className="rank-ring-center">{known.length===1?known[0].name:knownCount?knownCount+'段':'未识别'}</div>{hoverPresent&&<div ref={rankPopup} data-motion-surface aria-hidden={!hover} inert={!hover} className="rank-hover" role="tooltip">{hover||lastHover.current}</div>}</div>
    {rankRows(ranks.slice(0,preview.ranks))}</div><MotionDisclosure id="more-stat-ranks" open={moreRanks}>{rankRows(ranks.slice(preview.ranks))}</MotionDisclosure>
    {!ranks.length&&<div className="rank-empty">暂无模式或段位记录</div>}
    <ExpandButton open={moreRanks} controls="more-stat-ranks" count={ranks.length-preview.ranks} onClick={()=>setMoreRanks(!moreRanks)}/>
   </section>
   <section className="stat-card teammates-stat" aria-labelledby="teammates-stat-heading"><h2 id="teammates-stat-heading">常玩队友</h2>{teamRows(teammates.slice(0,preview.teammates))}
    <MotionDisclosure id="more-stat-teammates" open={moreTeams}>{teamRows(teammates.slice(preview.teammates))}</MotionDisclosure>
    {!teammates.length&&<div className="chart-empty">暂无出现 2 次及以上的队友</div>}
    <ExpandButton open={moreTeams} controls="more-stat-teammates" count={teammates.length-preview.teammates} onClick={()=>setMoreTeams(!moreTeams)}/>
   </section>
  </div></div>
 </div>;
}
