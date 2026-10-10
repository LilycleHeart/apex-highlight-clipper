import type {OutcomeEvidence} from './shared';

const count=(value:unknown):number|null=>typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;
export function recordingTime(source:string):string|null{
 const name=source.split(/[\\/]/).pop()||source;
 const standard=name.match(/(\d{4})[-_]?(\d{2})[-_]?(\d{2})[ T_-]+(\d{2})[-_:]?(\d{2})(?:[-_:]?(\d{2}))?/);
 const natural=name.match(/(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2})点(\d{1,2})分(?:(\d{1,2})秒)?/);
 const match=standard||natural;if(!match)return null;
 const [year,month,day,hour,minute,second]=match.slice(1).map(v=>v===undefined?undefined:Number(v));
 const date=new Date(Date.UTC(year!,month!-1,day!,hour!,minute!,second??0));
 if(date.getUTCFullYear()!==year||date.getUTCMonth()!==month!-1||date.getUTCDate()!==day||hour!>23||minute!>59||(second??0)>59)return null;
 const pad=(n:number)=>String(n).padStart(2,'0');return `${year}-${pad(month!)}-${pad(day!)}T${pad(hour!)}:${pad(minute!)}${second===undefined?'':':'+pad(second)}`;
}
export function recordingTimeLabel(value:string|null|undefined):string{
 if(!value)return'—';const m=value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}(?::\d{2})?)/);
 return m?`${m[1]}年${Number(m[2])}月${Number(m[3])}日 ${m[4]}`:'—';
}
/** 战果核查遇到第一个正例便停止，提示数量是已确认下限，不能冒充全段总数。 */
export function clipStatistics(clip:any,candidates:any[]=[]){
 const summary=clip.summary||{};const segment=clip.segment||{};
 const start=segment.requested_start??segment.start,end=segment.requested_end??segment.end;
 const related=candidates.filter(s=>s.start<end&&s.end>start);
 const found=summary.statistics_version?(clip.recognition?.outcome_evidence||[]):[...(clip.recognition?.outcome_evidence||[]),...(segment.own_result_filter?.events||[]),...related.flatMap(s=>s.own_result_filter?.events||[])];
 const unique=new Map<string,OutcomeEvidence>();
 for(const e of found)if(['knock','assist','elimination'].includes(e.kind)&&Number.isFinite(e.time)&&e.ownership==='self'&&e.time>=segment.start&&e.time<segment.end)unique.set(`${e.kind}-${e.time}-${e.text||''}`,{kind:e.kind,time:e.time,text:e.text,confidence:e.confidence});
 const evidence=[...unique.values()].sort((a,b)=>a.time-b.time);
 const ranks=related.map(s=>s.rank).filter(Boolean);
 const rank=clip.recognition?.rank||segment.rank||(ranks.length===related.length&&ranks.length&&ranks.every(r=>r.tier===ranks[0].tier&&r.division===ranks[0].division)?ranks[0]:null);
 const observed=(kind:string)=>{const n=evidence.filter(e=>e.kind===kind).length;return n||null;};
 const precise=!!summary.statistics_version;
 return {kills:count(summary.kills),damage:count(summary.damage),weapons:Array.isArray(summary.weapons)?summary.weapons.filter((w:unknown)=>typeof w==='string'):[],
  assists:precise?count(summary.assists):count(summary.assists)??observed('assist'),knockdowns:precise?count(summary.knockdowns):count(summary.knockdowns)??observed('knock'),
  outcomeCountsPartial:summary.assists===undefined||summary.knockdowns===undefined,evidence,rank,
  statisticsPartial:summary.statistics_partial,statisticsNotes:summary.statistics_notes,settlementTotals:clip.recognition?.statistics?.settlement_totals,
  statisticsBasis:summary.statistics_basis||'击杀与伤害来自本段本人 HUD 增量；助攻和击倒展示已确认提示下限。'};
}
