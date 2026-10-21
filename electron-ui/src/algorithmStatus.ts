/** Status is classified by the backend's semantic manifest, never by app version. */
export type AlgorithmFreshness='current'|'old'|'unknown';
export type ClipAlgorithmFreshness=AlgorithmFreshness|'mixed';
export interface AlgorithmFieldRecord {
 field:string;label?:string;status:AlgorithmFreshness;version?:string;currentVersion?:string;
 updatedAt?:string;reason?:string;fingerprint?:string;currentSignature?:string;modelFingerprint?:string;semanticFingerprint?:string;
}
export interface ClipAlgorithmStatus {file:string;fields:readonly AlgorithmFieldRecord[]}
export interface UpgradeSelection {file:string;fields:string[]}
export interface RecognitionRecoveryJob {
 id:string;status:'running'|'paused'|'failed'|'interrupted'|'completed';compatible:boolean;
 /** Only successfully committed clip/field items. In-flight work never contributes. */
 completed:number;total:number;inFlight?:number;fields?:readonly string[];
 files?:readonly string[];updatedAt?:string;invalidReason?:string;
}
export const algorithmStatusLabels:Record<ClipAlgorithmFreshness,string>={current:'当前算法',old:'旧算法',unknown:'版本未知',mixed:'混合版本'};
const fileKey=(file:string)=>file.replace(/\\/g,'/').toLocaleLowerCase('en-US');

export function clipAlgorithmFreshness(fields:readonly AlgorithmFieldRecord[]):ClipAlgorithmFreshness {
 const values=new Set(fields.map(field=>field.status));
 return values.size===0?'unknown':values.size===1?[...values][0]:'mixed';
}

/** Merge duplicate clip records without ever selecting a current field for rerun. */
function mergedStatuses(clips:readonly ClipAlgorithmStatus[]) {
 const selected=new Map<string,{file:string;fields:Map<string,AlgorithmFreshness>}>();
 for(const clip of clips){
  const key=fileKey(clip.file);if(!key)continue;
  let item=selected.get(key);if(!item){item={file:clip.file,fields:new Map()};selected.set(key,item);}
  for(const field of clip.fields){
   if(!field.field)continue;
   // Backend should supply one record per field. A current duplicate always wins.
   const previous=item.fields.get(field.field);
   if(previous==='current')continue;
   if(field.status==='current'||previous===undefined||field.status==='old')item.fields.set(field.field,field.status);
  }
 }
 return [...selected.values()];
}
export function selectAlgorithmUpgrade(clips:readonly ClipAlgorithmStatus[],includeUnknown=false):UpgradeSelection[] {
 return mergedStatuses(clips).flatMap(item=>{
  const fields=[...item.fields].filter(([,status])=>status==='old'||includeUnknown&&status==='unknown').map(([field])=>field);
  return fields.length?[{file:item.file,fields}]:[];
 });
}

export function algorithmUpgradeSummary(clips:readonly ClipAlgorithmStatus[]){
 const old=selectAlgorithmUpgrade(clips),withUnknown=selectAlgorithmUpgrade(clips,true);
 const unknown=mergedStatuses(clips).filter(clip=>[...clip.fields.values()].some(status=>status==='unknown'));
 const fields=[...new Set(old.flatMap(clip=>clip.fields))];
 const labels=new Map(clips.flatMap(clip=>clip.fields.map(field=>[field.field,field.label||field.field] as const)));
 return {oldCount:old.length,unknownCount:unknown.length,allCount:withUnknown.length,fields,fieldLabels:fields.map(field=>labels.get(field)||field)};
}

/** Ignore this semantic update, regardless of progress or library ordering. */
export function algorithmNoticeKey(clips:readonly ClipAlgorithmStatus[]){
 return JSON.stringify([...new Set(clips.flatMap(clip=>clip.fields.map(field=>`${field.field}:${field.currentSignature||field.currentVersion||'unknown'}`)))].sort());
}

export function algorithmVersionDetails(fields:readonly AlgorithmFieldRecord[]):string {
 if(!fields.length)return '历史结果未记录算法版本。';
 return fields.map(field=>{
  const version=field.version||'未记录',current=field.currentVersion&&field.currentVersion!==field.version?` → ${field.currentVersion}`:'';
  const fingerprints=[field.fingerprint&&`指纹 ${field.fingerprint}`,field.modelFingerprint&&`模型 ${field.modelFingerprint}`,field.semanticFingerprint&&`规则 ${field.semanticFingerprint}`].filter(Boolean);
  return `${field.label||field.field}：${algorithmStatusLabels[field.status]} · ${version}${current}${field.updatedAt?` · ${field.updatedAt}`:''}${field.reason?`（${field.reason}）`:''}${fingerprints.length?` · ${fingerprints.join(' · ')}`:''}`;
 }).join('\n');
}

export function recoveryProgress(job:RecognitionRecoveryJob){
 const total=Number.isFinite(job.total)?Math.max(0,Math.floor(job.total)):0;
 const completed=Number.isFinite(job.completed)?Math.max(0,Math.min(total,Math.floor(job.completed))):0;
 const inFlight=Number.isFinite(job.inFlight)?Math.max(0,Math.min(total-completed,Math.floor(job.inFlight!))):0;
 return {total,completed,inFlight,remaining:total-completed};
}
