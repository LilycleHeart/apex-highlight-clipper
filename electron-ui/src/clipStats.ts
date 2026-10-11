import type {OutcomeEvidence} from './shared';
import {withProcessStarts,type PlaybackAnalysis} from './combatPlayback';

const count=(value:unknown):number|null=>typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;
const resultPrefix=/^(?:(?:ASSIST|助攻)\s*[,.:，：]*\s*|KN[O0]CK(?:ED)?\s*D[O0]WN\s*|ELIMINAT(?:ED|ION)\s*|(?:已)?[擊击擎驛驿]倒\s*|(?:已)?消[滅灭減减]\s*)/i;
/** 兼容旧任务中的整行 target；未知姓名不能退回显示原始 OCR。 */
export function cleanTargetName(value:unknown):string|undefined{
 if(typeof value!=='string')return undefined;
 let target=value.normalize('NFKC').replace(/\s+/g,' ').trim();
 for(let i=0;i<3;i++){const stripped=target.replace(resultPrefix,'');if(stripped===target)break;target=stripped;}
 target=target.replace(/\s*\+\s*[0-9OoIiLlSsBbZz]{1,5}(?:\s|$|[^A-Za-z0-9]).*$/,'').replace(/^[ ,.:;，。：；]+|[ ,.:;，。：；]+$/g,'');
 const compact=target.replace(/\s+/g,'').toUpperCase();
 if(!target||target.length>48||!/[\p{L}]/u.test(target)||/[\x00-\x1f\ufffd□<>:=+!?！？。]/.test(target))return undefined;
 if(/DAMAGE|INFLICT|SHIELDBROKEN|YOUSPOTTED|SPOTTEDANENEMY|PRESS|HOLD|TOGGLE|RELOAD|ELIMINAT|KNOCK|KN0CK|ASSIST|SQUAD|擊倒|击倒|造成|傷害|伤害|護盾|护盾|按住|按下|切換|切换|你發現|你发现|我被|你被/i.test(compact))return undefined;
 if(/^(?:KN[O0]?(?:C(?:K(?:ED)?)?)?|D[O0]WN|ELIM|ELIMIN|ELIMINA|ELIMINATE|XP|RP)$/.test(compact))return undefined;
 return target;
}
export function outcomeTarget(event:{target_text?:unknown;target?:unknown;text?:unknown;text_confidence?:unknown}):string|undefined{
 if(typeof event.text_confidence==='number'&&event.text_confidence<.80)return undefined;
 for(const value of [event.target_text,event.target])if(typeof value==='string')return cleanTargetName(value);
 return typeof event.text==='string'&&resultPrefix.test(event.text.normalize('NFKC').trim())?cleanTargetName(event.text):undefined;
}
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
/** 新统计完整扫描本段提示；旧缓存可能只保留正例下限，按字段状态展示。 */
export function clipStatistics(clip:any,candidates:any[]=[],analysis:PlaybackAnalysis={}){
 const summary=clip.summary||{};const segment=clip.segment||{};
 const hudInfo=clip.recognition?.hud_info||null;
 const start=segment.requested_start??segment.start,end=segment.requested_end??segment.end;
 const related=candidates.filter(s=>s.start<end&&s.end>start);
 const found=summary.statistics_version?(clip.recognition?.outcome_evidence||[]):[...(clip.recognition?.outcome_evidence||[]),...(segment.own_result_filter?.events||[]),...related.flatMap(s=>s.own_result_filter?.events||[])];
 const unique=new Map<string,OutcomeEvidence>();
 for(const e of found)if(['knock','assist','elimination'].includes(e.kind)&&Number.isFinite(e.time)&&e.ownership==='self'&&e.time>=segment.start&&e.time<segment.end)unique.set(`${e.kind}-${e.time}-${e.text||''}`,{kind:e.kind,time:e.time,text:e.text,confidence:e.confidence,target:outcomeTarget(e),weapon:typeof e.weapon==='string'?e.weapon:undefined});
 const evidence=withProcessStarts([...unique.values()].sort((a,b)=>a.time-b.time),segment,related,analysis);
 const ranks=related.map(s=>s.rank).filter(Boolean);
 const rank=hudInfo?.rank||clip.recognition?.rank||segment.rank||(ranks.length===related.length&&ranks.length&&ranks.every(r=>r.tier===ranks[0].tier&&r.division===ranks[0].division)?ranks[0]:null);
 const observed=(kind:string)=>{const n=evidence.filter(e=>e.kind===kind).length;return n||null;};
 const precise=!!summary.statistics_version;
 const lastHud=clip.recognition?.statistics?.endpoint?.last_hud;
 const roundKills=count(lastHud?.kills),roundDamage=count(lastHud?.damage);
 const roundTotals=roundKills!==null||roundDamage!==null?{kills:roundKills,damage:roundDamage}:undefined;
 return {kills:count(summary.kills),damage:count(summary.damage),weapons:hudInfo?.weapons?.length?hudInfo.weapons.map((w:{name:string})=>w.name):Array.isArray(summary.weapons)?summary.weapons.filter((w:unknown)=>typeof w==='string'):[],
  hudInfo,accountName:hudInfo?.account?.name||null,teammates:hudInfo?.teammates||[],hero:hudInfo?.hero||null,matchKey:clip.recognition?.match_key,
  assists:precise?count(summary.assists):count(summary.assists)??observed('assist'),knockdowns:precise?count(summary.knockdowns):count(summary.knockdowns)??observed('knock'),
  outcomeCountsPartial:summary.assists===undefined||summary.knockdowns===undefined,evidence,rank,
  statisticsPartial:summary.statistics_partial,statisticsNotes:summary.statistics_notes,settlementTotals:clip.recognition?.statistics?.settlement_totals,roundTotals,
  statisticsBasis:summary.statistics_basis||'击杀与伤害来自本段本人 HUD 增量；助攻和击倒展示已确认提示下限。'};
}
