import type {OutcomeEvidence} from './shared';
import {withProcessStarts,type PlaybackAnalysis} from './combatPlayback';

const count=(value:unknown):number|null=>typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;
const nativeNumericMethods=new Set(['numeric-three-model-v3','numeric-three-model-v4','numeric-three-model-v5','hud-digits-v1']);
const eventCompletionVersion='native-event-completion-v1';
const nativeTargetNameVersions=new Set(['target-name-v14','target-name-v15']);
const resultPrefix=/^(?:(?:ASSIST|助攻)\s*[,.:，：]*\s*|KN[O0]CK(?:ED)?\s*D[O0]WN\s*|ELIMINAT(?:ED|ION)\s*|(?:已)?[擊击撃擎驛驿]倒\s*|(?:已)?消[滅灭減减]\s*)/i;
/** 兼容旧任务中的整行 target；未知姓名不能退回显示原始 OCR。 */
export function cleanTargetName(value:unknown,allowRenderedSquare=false):string|undefined{
 if(typeof value!=='string')return undefined;
 let target=value.normalize('NFKC').replace(/\s+/g,' ').trim();
 for(let i=0;i<3;i++){const stripped=target.replace(resultPrefix,'');if(stripped===target)break;target=stripped;}
 target=target.replace(/\s*\+\s*[0-9OoIiLlSsBbZz]{1,5}(?:\s|$|[^A-Za-z0-9]).*$/,'').replace(/^[ ,:;，：；]+|[ ,:;，：；]+$/g,'');
 const compact=target.replace(/\s+/g,'').toUpperCase();
 if(!target||target.length>48||!(/[\p{L}]/u.test(target)||/^\d{5,20}$/.test(target))||/[\x00-\x1f\ufffd<>:=+!?！？。]/.test(target)||target.includes('□')&&!allowRenderedSquare)return undefined;
 if(/DAMAGE|INFLICT|SHIELDBROKEN|YOUSPOTTED|SPOTTEDANENEMY|PRESS|HOLD|TOGGLE|RELOAD|ELIMINAT|KNOCK|KN0CK|ASSIST|SQUAD|擊倒|击倒|造成|傷害|伤害|護盾|护盾|按住|按下|切換|切换|你發現|你发现|我被|你被/i.test(compact))return undefined;
 if(/^(?:KN[O0]?(?:C(?:K(?:ED)?)?)?|D[O0]WN|ELIM|ELIMIN|ELIMINA|ELIMINATE|XP|RP)$/.test(compact))return undefined;
 return target;
}
export function outcomeTarget(event:{target_text?:unknown;target?:unknown;text?:unknown;text_confidence?:unknown;target_confidence?:unknown;target_method?:unknown;native_name_status?:unknown;native_name_version?:unknown;native_event_version?:unknown;confirmed?:unknown;target_shape_evidence?:unknown}):string|undefined{
 if(event.native_event_version===eventCompletionVersion&&(event.confirmed!==true||event.native_name_status!=='confirmed'||!nativeTargetNameVersions.has(String(event.native_name_version))||event.target_method!=='two_frame_native_name_consensus'))return undefined;
 if(event.native_name_status==='unconfirmed')return undefined;
 const confidence=event.native_name_status==='confirmed'&&event.target_method==='two_frame_native_name_consensus'&&typeof event.target_confidence==='number'?event.target_confidence:event.text_confidence;
 if(typeof confidence==='number'&&confidence<.80)return undefined;
 const shapeFrames=Array.isArray(event.target_shape_evidence)?event.target_shape_evidence.filter((proof:any)=>Number.isFinite(proof?.time)&&typeof proof.score==='number'&&proof.score>=.82&&Array.isArray(proof.box)&&proof.box.length===4&&proof.box.every((n:any)=>typeof n==='number'&&Number.isFinite(n))):[];
 const square=event.native_name_status==='confirmed'&&event.target_method==='two_frame_native_name_consensus'&&new Set(shapeFrames.map((proof:any)=>proof.time)).size>=2;
 for(const value of [event.target_text,event.target])if(typeof value==='string')return cleanTargetName(value,square);
 return typeof event.text==='string'&&resultPrefix.test(event.text.normalize('NFKC').trim())?cleanTargetName(event.text):undefined;
}

type VideoIdentity={path:string;size:number;mtime_ms:number;aliases?:string[]};
// v2 放宽了枪名分数门槛并增加「战果前持枪」；v1 结果按原规则继续显示，重新识别后升级。
const weaponContextVersions=new Set(['event-weapon-context-v1','event-weapon-context-v2']);
const outcomeIdentity=(event:any)=>`${event.kind}-${event.time}-${event.text||''}-${JSON.stringify(event.prefix_box||event.box||[])}`;
// 成片被片段库确认移动后，旧路径记在 moved_from（aliases）；其他路径的证据仍不能借用。
const samePath=(a:string,b:string)=>a.toLowerCase().replaceAll('\\','/')===b.toLowerCase().replaceAll('\\','/');
function sameVideoIdentity(expected:any,actual?:VideoIdentity):boolean{return !!actual&&typeof actual.path==='string'&&!!actual.path&&typeof expected?.path==='string'&&!!expected.path&&Number.isSafeInteger(expected.size)&&expected.size>=0&&Number.isSafeInteger(expected.mtime_ms)&&expected.mtime_ms>=0&&[actual.path,...(actual.aliases||[])].some(path=>typeof path==='string'&&samePath(expected.path,path))&&expected.size===actual.size&&expected.mtime_ms===actual.mtime_ms;}
const finiteBox=(value:any):boolean=>Array.isArray(value)&&value.length===4&&value.every((n:any)=>typeof n==='number'&&Number.isFinite(n))&&value[2]>value[0]&&value[3]>value[1];
function classificationPrefix(text:unknown):{kind:string;action:string;english:boolean;length:number}|undefined{
 if(typeof text!=='string')return undefined;const value=text.normalize('NFKC').replace(/\s+/g,' ').trim();
 const patterns:[string,string,boolean,RegExp][]=[
  ['assist','knock',true,/^ASSIST\s*[,.:]*\s*KN[O0]CK(?:ED)?\s*D[O0]WN\s*/i],
  ['assist','elimination',true,/^ASSIST\s*[,.:]*\s*ELIMINAT(?:ED|ION)\s*/i],
  ['assist','knock',false,/^助攻\s*[,，:：]*\s*[擊击撃擎驛驿]倒\s*/],
  ['assist','elimination',false,/^助攻\s*[,，:：]*\s*(?:已)?消[滅灭減减]\s*/],
  ['knock','knock',true,/^KN[O0]CKED\s*D[O0]WN\s*/i],['elimination','elimination',true,/^ELIMINATED\s*/i],
  ['knock','knock',false,/^(?:已)?[擊击撃]倒\s*/],['elimination','elimination',false,/^已消[滅灭]\s*/],
 ];
 for(const [kind,action,english,pattern] of patterns){const match=value.match(pattern);if(match)return {kind,action,english,length:match[0].length};}
 return undefined;
}
function nativeEventBase(event:any,fileIdentity?:VideoIdentity,allowEmptyContext=false):boolean{
 const bounds=event?.native_event_context_bounds;
 return !!event&&event.native_event_version===eventCompletionVersion&&event.native_event_original_confirmed===false&&typeof event.native_event_recipe==='string'&&/^native-event-completion-v1:[a-f0-9]{64}$/.test(event.native_event_recipe)&&event.ownership==='self'&&['knock','assist','elimination'].includes(event.kind)&&Number.isFinite(event.time)&&sameVideoIdentity(event.native_event_source,fileIdentity)&&Array.isArray(bounds)&&bounds.length===2&&bounds.every((n:any)=>typeof n==='number'&&Number.isFinite(n)&&n>=0)&&(allowEmptyContext||bounds[1]>bounds[0]);
}
function nativeEventObservation(read:any,event:any):boolean{
 const bounds=event.native_event_context_bounds,own=read?.own_view,proof=read?.prefix_evidence,prefix=classificationPrefix(read?.text);
 if(read?.accepted!==true||!prefix||prefix.kind!==event.kind||prefix.action!==read.action||read.kind!==event.kind||!['knock','elimination'].includes(read.action)||['knock','elimination'].includes(event.action)&&event.action!==read.action||!finiteBox(read.box)||typeof read.association_target!=='string'||!read.association_target.trim()||!own||own.inactive!==false||own.friend_spectate!==false||own.spectator!==false)return false;
 if(!Number.isFinite(read.native_pts)||!Number.isFinite(read.requested_time)||read.native_pts<bounds[0]||read.native_pts>=bounds[1]||read.requested_time<bounds[0]||read.requested_time>=bounds[1]||read.native_pts-read.requested_time<0||read.native_pts-read.requested_time>=.15)return false;
 const raw=read.text.normalize('NFKC').replace(/\s+/g,' ').trim();if(!cleanTargetName(raw.slice(prefix.length)))return false;
 if(typeof read.prefix_confidence!=='number'||!Number.isFinite(read.prefix_confidence)||read.prefix_confidence<(prefix.english?.90:.85))return false;
 if(prefix.english){
  const ctc=classificationPrefix(proof?.ctc_prefix);
  return proof?.type==='english_complete_prefix_grammar'&&ctc?.english===true&&ctc.kind===prefix.kind&&ctc.action===prefix.action&&typeof proof.ctc_prefix_mean_letter_confidence==='number'&&Number.isFinite(proof.ctc_prefix_mean_letter_confidence)&&proof.ctc_prefix_mean_letter_confidence>=.85&&finiteBox(proof.box)&&proof.box[2]<read.box[2]&&Math.abs(proof.box[0]-read.box[0])<=4&&Math.abs(proof.box[1]-read.box[1])<=4&&typeof proof.crop_sha256==='string'&&/^[a-f0-9]{64}$/.test(proof.crop_sha256);
 }
 return proof?.type==='same_row_fixed_prefix_template'&&Array.isArray(proof.matches)&&proof.matches.some((match:any)=>match.kind===event.kind&&typeof match.score==='number'&&Number.isFinite(match.score)&&match.score>=.80&&match.score<=1.001&&finiteBox(match.box)&&Math.abs(match.box[0]-read.box[0])<=10&&Math.abs((match.box[1]+match.box[3]-read.box[1]-read.box[3])/2)<=10);
}
function nativeEventProof(event:any,fileIdentity?:VideoIdentity):boolean{
 if(!nativeEventBase(event,fileIdentity)||event.confirmed!==true||event.native_event_status!=='confirmed')return false;
 const pair=event.native_event_confirmation;
 if(!Array.isArray(pair?.pts)||pair.pts.length!==2||!pair.pts.every((n:any)=>typeof n==='number'&&Number.isFinite(n))||new Set(pair.pts).size!==2||Math.abs(pair.pts[0]-pair.pts[1])>1.1||!Array.isArray(event.native_event_evidence))return false;
 const reads=pair.pts.map((pts:number)=>event.native_event_evidence.find((read:any)=>read.native_pts===pts&&nativeEventObservation(read,event)));
 if(reads.some((read:any)=>!read)||reads[0].association_target!==reads[1].association_target||reads[0].action!==reads[1].action||Math.abs((reads[0].box[1]+reads[0].box[3]-reads[1].box[1]-reads[1].box[3])/2)>10)return false;
 if(reads[0].prefix_evidence.type==='same_row_fixed_prefix_template')return reads[1].prefix_evidence.type==='same_row_fixed_prefix_template'&&pair.type==='two_native_full_grammar_and_fixed_template_observations';
 const a=reads[0].prefix_evidence.box,b=reads[1].prefix_evidence.box,pixels=pair.pixel_agreement;
 return reads[1].prefix_evidence.type==='english_complete_prefix_grammar'&&pair.type==='english_full_grammar_with_native_prefix_persistence'&&pair.not_an_independent_semantic_vote===true&&typeof pixels?.score==='number'&&Number.isFinite(pixels.score)&&pixels.score>=.75&&pixels.score<=1.001&&Number.isInteger(pixels.dx)&&Math.abs(pixels.dx)<=3&&Number.isInteger(pixels.dy)&&Math.abs(pixels.dy)<=3&&Math.abs(a[0]-b[0])<=8&&Math.abs(a[1]-b[1])<=8&&Math.abs((a[3]-a[1])-(b[3]-b[1]))<=4&&Math.abs((a[2]-a[0])-(b[2]-b[0]))<=Math.max(6,(a[2]-a[0])*.08);
}
function completionForDisplay(event:any,fileIdentity?:VideoIdentity){
 return event.native_name_status==='confirmed'&&!sameVideoIdentity(event.native_name_source,fileIdentity)?{...event,native_name_status:'unconfirmed'}:event;
}
function terminalUnreadable(endpoint:any,key:string):boolean{
 const rows=Array.isArray(endpoint?.end_frames)?endpoint.end_frames.filter((row:any)=>Number.isFinite(row.native_time??row.time)):[];
 if(!rows.length)return false;
 const last=rows.reduce((a:any,b:any)=>(a.native_time??a.time)>=(b.native_time??b.time)?a:b);
 return count(endpoint.last_hud?.[key])!==null&&last[key]==null;
}
function nativeCounterProof(fix:any,key:string):boolean{
 const endpoint=fix.endpoint;if(!endpoint||!Array.isArray(fix.native_repaired_fields)||!fix.native_repaired_fields.includes(key)||typeof fix.partial?.[key]!=='boolean'||key in(endpoint.unconfirmed_latest||{})&&fix.partial[key]!==true)return false;
 if(endpoint.native_view_version!=='self-hud-view-v3'||!nativeNumericMethods.has(endpoint.native_numeric_method)||endpoint.excluded_terminal_view&&fix.partial[key]!==true)return false;
 if(endpoint.native_counter_scope==='exported_visible_delta'&&!endpoint.export_baseline_fields?.includes(key))return false;
 const baseline=count(endpoint.baseline?.[key]),last=count(endpoint.last_hud?.[key]);
 if(baseline===null||last===null||!Number.isInteger(baseline)||!Number.isInteger(last)||last<baseline||fix.counts?.[key]!==last-baseline)return false;
 if(typeof endpoint.unconfirmed_latest?.[key]==='number'&&endpoint.unconfirmed_latest[key]<last)return false;
 for(const [field,frames] of [['baseline','baseline_frames'],['last_hud','end_frames']]){
  if(!Array.isArray(endpoint[frames]))return false;
  const times=new Set(endpoint[frames].filter((row:any)=>row.native_verified===true&&typeof row.native_time==='number'&&Number.isFinite(row.native_time)&&row[key]===endpoint[field][key]).map((row:any)=>row.native_time));
  if(times.size<2)return false;
 }
 return true;
}

function nativeEndProof(endpoint:any,key:string):boolean{
 if(endpoint?.native_view_version!=='self-hud-view-v3'||!nativeNumericMethods.has(endpoint?.native_numeric_method)||!Array.isArray(endpoint.end_frames))return false;
 if(terminalUnreadable(endpoint,key)||key in(endpoint.unconfirmed_latest||{}))return false;
 const value=count(endpoint.last_hud?.[key]);if(value===null||!Number.isInteger(value)||typeof endpoint.unconfirmed_latest?.[key]==='number'&&endpoint.unconfirmed_latest[key]<value)return false;
 return new Set(endpoint.end_frames.filter((row:any)=>row.native_verified===true&&Number.isFinite(row.native_time)&&row[key]===value).map((row:any)=>row.native_time)).size>=2;
}

function weaponContextBound(event:any,clip:any,fileIdentity?:VideoIdentity):boolean{
 const context=event?.weapon_context,bound=context?.event;
 if(!weaponContextVersions.has(context?.version)||!sameVideoIdentity(context.source,fileIdentity)||typeof context.recipe!=='string'||!/^[a-f0-9]{64}$/.test(context.recipe)||!['observed','unknown'].includes(context.status)||context.kill_attribution!==false||event.ownership!=='self'||event.confirmed!==true||!['knock','assist','elimination'].includes(event.kind)||!Number.isFinite(event.time)||bound?.kind!==event.kind||(bound.action??null)!==(event.action??null)||bound.time!==event.time)return false;
 const rawOrigin=clip.metadata?.streams?.find((stream:any)=>stream.codec_type==='video')?.start_time;
 const origin=rawOrigin===undefined?0:Number(rawOrigin),local=bound.source_time??bound.time;
 return Number.isFinite(local)&&local>=0&&Number.isFinite(origin)&&Number.isFinite(clip.segment?.start)&&Math.abs(local-(event.time-clip.segment.start+origin))<=.001;
}
function weaponIconSimilarity(a:unknown,b:unknown):number{
 if(typeof a!=='string'||typeof b!=='string'||!/^[A-Za-z0-9+/]{448}$/.test(a)||!/^[A-Za-z0-9+/]{448}$/.test(b))return 0;
 const left=atob(a),right=atob(b);let total=0,intersection=0;
 const bits=(value:number)=>{let n=0;for(;value;value&=value-1)n++;return n;};
 for(let i=0;i<left.length;i++){const x=left.charCodeAt(i),y=right.charCodeAt(i);total+=bits(x)+bits(y);intersection+=bits(x&y);}
 return total?2*intersection/total:0;
}
export function weaponContextFor(event:any,clip:any,fileIdentity?:VideoIdentity):OutcomeEvidence['weaponContext']{
 if(!weaponContextBound(event,clip,fileIdentity))return undefined;
 const context=event.weapon_context,weapon=context.weapon,second=context.event.source_time??context.event.time;
 const v2=context.version==='event-weapon-context-v2',minimum=v2?.75:.80;
 if(v2&&context.scope==='held_near_event')return nearEventContext(context,weapon,second);
 if(context.status!=='observed'||!['nearby_firing','held_at_event',...(v2?['held_before_event']:[])].includes(context.scope)||typeof weapon?.id!=='string'||!weapon.id||typeof weapon.name!=='string'||!weapon.name.trim()||weapon.name.length>60||/[\x00-\x1f<>]/.test(weapon.name)||!Array.isArray(context.evidence))return undefined;
 const rows=context.evidence.filter((row:any)=>typeof row?.actual_pts==='number'&&Number.isFinite(row.actual_pts)&&row.actual_pts>=0&&row.actual_pts>=second-1.5&&row.actual_pts<=second+.25).sort((a:any,b:any)=>a.actual_pts-b.actual_pts);
 if(rows.length!==context.evidence.length||rows.some((row:any)=>row.excluded_view)||new Set(rows.map((row:any)=>row.actual_pts)).size!==rows.length||rows.length<2)return undefined;
 const sameWeapon=(a:any,b:any)=>a?.weapon?.id===b?.weapon?.id&&(a?.weapon?.variant??null)===(b?.weapon?.variant??null)&&a?.weapon?.name===b?.weapon?.name;
 const usable=(row:any)=>row.weapon&&[0,1].includes(row.slot)&&typeof row.confidence==='number'&&Number.isFinite(row.confidence)&&row.confidence>=minimum&&Number.isInteger(row.name_view_agreement)&&row.name_view_agreement>=2;
 // v2 另存图标白色前景掩膜：开枪闪光改变边缘纹理但不改图标形状，掩膜同形（≥0.88）亦视为同一图标。
 const sameIcon=(a:any,b:any)=>weaponIconSimilarity(a.weapon_icon,b.weapon_icon)>=.80||v2&&weaponIconSimilarity(a.weapon_icon_mask,b.weapon_icon_mask)>=.88;
 const sameHeld=(a:any,b:any)=>usable(a)&&usable(b)&&a.slot===b.slot&&sameWeapon(a,b)&&sameIcon(a,b);
 const shots:any[]=[];
 for(let i=1;i<rows.length;i++){
  const before=rows[i-1],after=rows[i],a=before.ammo,b=after.ammo,interval=after.actual_pts-before.actual_pts;
  if(after.actual_pts>second+.04||interval<=0||interval>.75||!sameHeld(before,after)||!Number.isInteger(a?.value)||!Number.isInteger(b?.value)||!Number.isFinite(a?.confidence)||!Number.isFinite(b?.confidence)||Math.min(a.confidence,b.confidence)<.88||!(0<b.value&&b.value<a.value&&a.value<=1000&&a.value-b.value<=50))continue;
  shots.push(after);
 }
 if(shots.length){
  if(context.scope!=='nearby_firing'||!shots.every(row=>sameWeapon(row,{weapon})))return undefined;
  return {scope:'nearby_firing',weapon:weapon.name,label:'战果前射击：'+weapon.name};
 }
 const held=rows.filter((row:any)=>row.actual_pts>=second-.04&&row.actual_pts<=second+.25);
 if(context.scope==='held_before_event'){
  // 与 event_weapon_reader 相同：事件前可用帧至少两帧同槽同枪，期间没有另一把枪。
  const valid=rows.filter((row:any)=>usable(row)),last=valid[valid.length-1];
  if(last&&sameWeapon(last,{weapon})&&!valid.some((row:any)=>!sameWeapon(row,last))&&valid.filter((row:any)=>sameHeld(last,row)).length>=2)
   return {scope:'held_before_event',weapon:weapon.name,label:'战果前持枪：'+weapon.name};
  // 每帧只有一个视图读对时：至少三帧不同画面同槽同枪、图标同形，期间没有其他枪名。
  const read=rows.filter((row:any)=>row.weapon&&[0,1].includes(row.slot)&&typeof row.confidence==='number'&&row.confidence>=minimum&&Number.isInteger(row.name_view_agreement)&&row.name_view_agreement>=1);
  const tail=read[read.length-1];
  if(context.reason!=='three_frame_single_view_consensus'||read.length<3||!tail||!sameWeapon(tail,{weapon})||read.some((row:any)=>row.slot!==tail.slot||!sameWeapon(row,tail)||!sameIcon(row,tail)))return undefined;
  return {scope:'held_before_event',weapon:weapon.name,label:'战果前持枪：'+weapon.name};
 }
 if(context.scope!=='held_at_event'||held.length<2||!sameWeapon(held[0],{weapon})||!held.slice(1).every((row:any)=>sameHeld(held[0],row)))return undefined;
 return {scope:'held_at_event',weapon:weapon.name,label:'当时持枪：'+weapon.name};
}

/** 与 event_weapon_reader.context_near_event 相同：事件前 6 秒至后 3 秒，从事件向两侧取最近的可读帧，遇到另一把枪即停；
 *  这一串同槽同枪、图标同形，事件前后各至少一帧或事件前两帧，总计两帧双视图一致或三帧单视图一致，中间没有离开本人视角。 */
function nearEventContext(context:any,weapon:any,second:number):OutcomeEvidence['weaponContext']{
 if(context.status!=='observed'||context.reason!=='same_slot_chain_near_event'||typeof weapon?.id!=='string'||!weapon.id||typeof weapon.name!=='string'||!weapon.name.trim()||weapon.name.length>60||/[\x00-\x1f<>]/.test(weapon.name)||!Array.isArray(context.evidence))return undefined;
 const rows=context.evidence.filter((row:any)=>typeof row?.actual_pts==='number'&&Number.isFinite(row.actual_pts)&&row.actual_pts>=0&&row.actual_pts>=second-6&&row.actual_pts<=second+3).sort((a:any,b:any)=>a.actual_pts-b.actual_pts);
 if(rows.length!==context.evidence.length||new Set(rows.map((row:any)=>row.actual_pts)).size!==rows.length)return undefined;
 const read=(row:any)=>!row.excluded_view&&row.weapon&&[0,1].includes(row.slot)&&typeof row.confidence==='number'&&row.confidence>=.75&&Number.isInteger(row.name_view_agreement)&&row.name_view_agreement>=1;
 const icon=(a:any,b:any)=>weaponIconSimilarity(a.weapon_icon,b.weapon_icon)>=.80||weaponIconSimilarity(a.weapon_icon_mask,b.weapon_icon_mask)>=.88;
 const reads=rows.filter(read),before=reads.filter((row:any)=>row.actual_pts<=second+.25).reverse(),after=reads.filter((row:any)=>row.actual_pts>second+.25);
 const anchor=before[0]||after[0];if(!anchor||anchor.weapon.id!==weapon.id||anchor.weapon.name!==weapon.name)return undefined;
 const same=(row:any)=>row.slot===anchor.slot&&row.weapon.id===anchor.weapon.id&&(row.weapon.variant??null)===(anchor.weapon.variant??null)&&icon(anchor,row);
 const chain:any[]=[];for(const side of [before,after])for(const row of side){if(!same(row))break;chain.push(row);}
 const left=chain.filter((row:any)=>row.actual_pts<=second+.25).length,right=chain.length-left,strong=chain.filter((row:any)=>row.name_view_agreement>=2).length;
 if(!chain.length||!(strong>=2||chain.length>=3)||!(left>0&&(right>0||left>=2)))return undefined;
 const first=Math.min(...chain.map((row:any)=>row.actual_pts)),last=Math.max(...chain.map((row:any)=>row.actual_pts));
 if(rows.some((row:any)=>row.excluded_view&&row.actual_pts>=first&&row.actual_pts<=last))return undefined;
 return {scope:'held_near_event',weapon:weapon.name,label:'战果前后持枪：'+weapon.name};
}

function confirmedCenterCounts(events:any[],segment:any,fileIdentity?:VideoIdentity){
 const confirmed=[...new Map<string,any>(events.filter(event=>event.confirmed===true&&event.ownership==='self'&&Number.isFinite(event.time)&&event.time>=segment.start&&event.time<segment.end&&(event.native_event_version===undefined||nativeEventProof(event,fileIdentity))).map(event=>[outcomeIdentity(event),event])).values()];
 return {kills:confirmed.filter(event=>event.kind==='elimination').length,knockdowns:confirmed.filter(event=>event.kind==='knock').length,
  assists:confirmed.filter(event=>event.kind==='assist'&&(event.native_action_status!==undefined?event.native_action_status==='confirmed'&&event.action==='elimination':classificationPrefix(event.text)?.kind==='assist'&&classificationPrefix(event.text)?.action==='elimination')).length};
}
function completeCenterCoverage(coverage:any,events:any[],segment:any):boolean{
 return Number.isInteger(coverage?.expected_frames)&&coverage.expected_frames>0&&coverage.checked_frames===coverage.expected_frames&&Array.isArray(coverage.ambiguous_frames)&&coverage.ambiguous_frames.length===0&&coverage.calibrated_style_confirmed===true&&coverage.reliable_absence===true&&coverage.stopped_after_positive!==true&&!events.some(event=>event.kind==='knock'&&event.ownership==='self'&&event.confirmed!==true&&event.time>=segment.start&&event.time<segment.end);
}

/** Nonempty historical counters need native evidence on both sides, not just a newer version label. */
export function applyStatisticsCorrection(clip:any,fix:any,version:string,fileIdentity?:VideoIdentity){
 if(!fix||!Number.isFinite(clip.segment?.start)||!Number.isFinite(clip.segment?.end)||Math.abs(fix.start-clip.segment.start)>.001||Math.abs(fix.end-clip.segment.end)>.001||!Number.isFinite(fix.start)||!Number.isFinite(fix.end))return clip;
 const unreadable=['kills','assists','damage'].filter(key=>terminalUnreadable(fix.endpoint,key));
 if(unreadable.length)fix={...fix,partial:{...fix.partial,...Object.fromEntries(unreadable.map(key=>[key,true]))}};
 const counterFileValid=fix.endpoint?.native_counter_scope!=='exported_visible_delta'||sameVideoIdentity(fix.endpoint.exported_video_identity,fileIdentity);
 const endpointUpdated=counterFileValid&&(!Array.isArray(fix.repair_fields)||fix.repair_fields.includes('statistics'))&&fix.endpoint?.native_view_version==='self-hud-view-v3'&&nativeNumericMethods.has(fix.endpoint?.native_numeric_method);
 const countersRequested=!Array.isArray(fix.repair_fields)||fix.repair_fields.includes('statistics');
 const opponentsRequested=!Array.isArray(fix.repair_fields)||fix.repair_fields.includes('opponents');
 const summary={...(clip.summary||{})};let changed=false,centerChanged=false;
 for(const key of counterFileValid&&(!Array.isArray(fix.repair_fields)||fix.repair_fields.includes('statistics'))?['kills','assists','damage']:[]){
  if(endpointUpdated&&fix.counter_verification_pending?.includes(key)&&!nativeCounterProof(fix,key)){
   // 原片已删时复核只能看成片首尾；沿用导出时的完整统计作为已确认下限，不能清成未知。
   const kept=Array.isArray(fix.source_lower_bound_fields)&&fix.source_lower_bound_fields.includes(key)?count(fix.counts?.[key]):null;
   summary[key]=kept!==null&&Number.isInteger(kept)?kept:null;summary.statistics_partial={...summary.statistics_partial,[key]:true};changed=true;continue;
  }
  const value=count(fix.counts?.[key]);if(value===null||!Number.isInteger(value))continue;
  if(!nativeCounterProof(fix,key))continue;
  if(summary[key]==null||summary.statistics_partial?.[key]&&fix.partial?.[key]===false||nativeCounterProof(fix,key)){
   summary[key]=value;summary.statistics_partial={...summary.statistics_partial,[key]:fix.partial?.[key]??true};changed=true;
  }
 }
 const rows=Array.isArray(fix.events)?fix.events:[];
 const completions=opponentsRequested?rows.filter((event:any)=>event.time>=clip.segment.start&&event.time<clip.segment.end&&nativeEventProof(event,fileIdentity)).map((event:any)=>completionForDisplay(event,fileIdentity)):[];
 const freshEvents=opponentsRequested?rows.filter((event:any)=>event.native_event_version===undefined&&event.confirmed===true&&['confirmed','unconfirmed'].includes(event.native_name_status)&&(!event.native_name_source||sameVideoIdentity(event.native_name_source,fileIdentity))):[];
 const evidence=Array.isArray(clip.recognition?.outcome_evidence)?clip.recognition.outcome_evidence:[];
 const updatedEvents=evidence.map((event:any)=>{
  if(event.native_event_version!==undefined)return event;
  const exact=freshEvents.find((fresh:any)=>outcomeIdentity(fresh)===outcomeIdentity(event));if(exact)return exact;
  const candidates=freshEvents.filter((fresh:any)=>fresh.kind===event.kind&&fresh.time===event.time);
  return candidates.length===1&&evidence.filter((other:any)=>other.kind===event.kind&&other.time===event.time).length===1?candidates[0]:event;
 });
 let completionChanged=false;
 for(const event of completions){
  const index=updatedEvents.findIndex((old:any)=>outcomeIdentity(old)===outcomeIdentity(event));
  if(index<0){updatedEvents.push(event);completionChanged=true;}
  else if(updatedEvents[index].confirmed===false||nativeEventProof(updatedEvents[index],fileIdentity)){updatedEvents[index]=event;completionChanged=true;}
 }
 if(opponentsRequested&&fix.event_completion_version===eventCompletionVersion)for(const event of rows){
  if(event.confirmed!==false||event.native_event_status!=='unconfirmed'||event.time<clip.segment.start||event.time>=clip.segment.end||!Array.isArray(event.native_event_evidence)||!nativeEventBase(event,fileIdentity,true))continue;
  const index=updatedEvents.findIndex((old:any)=>outcomeIdentity(old)===outcomeIdentity(event)&&nativeEventProof(old,fileIdentity));
  if(index>=0){updatedEvents[index]=event;completionChanged=true;}
 }
 let weaponChanged=false;
 for(let index=0;index<updatedEvents.length;index++){
  const event=updatedEvents[index],matches=rows.filter((fresh:any)=>outcomeIdentity(fresh)===outcomeIdentity(event)&&weaponContextBound(fresh,clip,fileIdentity));
  if(matches.length!==1||JSON.stringify(event.weapon_context)===JSON.stringify(matches[0].weapon_context))continue;
  updatedEvents[index]={...event,weapon_context:matches[0].weapon_context};weaponChanged=true;
 }
 const center=confirmedCenterCounts(updatedEvents,clip.segment,fileIdentity),confirmedKnockdowns=center.knockdowns;
 if(completionChanged&&fix.event_completion_version===eventCompletionVersion&&typeof fix.partial?.knockdowns==='boolean'&&(fix.counts?.knockdowns===null||Number.isInteger(fix.counts?.knockdowns)&&fix.counts.knockdowns===confirmedKnockdowns)){
  summary.knockdowns=fix.counts.knockdowns;summary.statistics_partial={...summary.statistics_partial,knockdowns:fix.partial.knockdowns||!completeCenterCoverage(fix.coverage,updatedEvents,clip.segment)};summary.event_completion_version=eventCompletionVersion;
 }
 if(countersRequested&&counterFileValid&&Array.isArray(fix.center_recomputed_fields))for(const key of ['kills','assists','knockdowns'] as const){
  const oldEndpoint=clip.recognition?.statistics?.endpoint;
  if(!fix.center_recomputed_fields.includes(key)||clip.summary?.statistics_partial?.[key]!==true||nativeCounterProof(fix,key)||key!=='knockdowns'&&count(oldEndpoint?.baseline?.[key])!==null&&count(oldEndpoint?.last_hud?.[key])!==null)continue;
  // 仅撤销没有双端点支撑的旧中心下限；重算证据仍来自已接纳事件，不能用修正数字代替。
  const value=center[key]||null;
  if(summary[key]!==value||summary.statistics_partial?.[key]!==true){summary[key]=value;summary.statistics_partial={...summary.statistics_partial,[key]:true};centerChanged=true;}
 }
 if(countersRequested)for(const key of ['kills','assists','knockdowns'] as const){
  const previous=count(summary[key]),value=center[key];
  if(!value||previous!==null&&summary.statistics_partial?.[key]!==true||previous!==null&&value<=previous)continue;
  summary[key]=value;summary.statistics_partial={...summary.statistics_partial,[key]:key!=='knockdowns'||!completeCenterCoverage(fix.coverage,updatedEvents,clip.segment)};centerChanged=true;
 }
 if(!changed&&!centerChanged&&!freshEvents.length&&!endpointUpdated&&!completionChanged&&!weaponChanged)return clip;
 if(changed||centerChanged){summary.statistics_version=version;if(Array.isArray(fix.notes))summary.statistics_notes=fix.notes;if(centerChanged)summary.statistics_basis='本人 HUD 可见增量与已确认中心战果提示；中心补齐仅表示已确认下限';else if(fix.endpoint?.native_counter_scope==='exported_visible_delta')summary.statistics_basis='现有成片首尾本人 HUD 可见增量，原生双帧复核';}
 return {...clip,summary,recognition:{...clip.recognition,statistics:counterFileValid&&(changed||endpointUpdated)?fix:clip.recognition?.statistics,outcome_evidence:updatedEvents}};
}
export function recordingTime(source:string):string|null{
 const name=source.split(/[\\/]/).pop()||source;
 const standard=name.match(/(\d{4})[-_]?(\d{2})[-_]?(\d{2})[ T_-]+(\d{2})[-_:]?(\d{2})(?:[-_:]?(\d{2}))?/);
 const natural=name.match(/(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2})点(\d{1,2})分(?:(\d{1,2})秒)?/);
 const outplayed=name.match(/(?:Apex Legends|Outplayed)[_-](\d{2})-(\d{2})-(\d{4})[_-](\d{2})-(\d{2})-(\d{2})/i);
 const match=(outplayed?[outplayed[0],outplayed[3],outplayed[1],outplayed[2],outplayed[4],outplayed[5],outplayed[6]]:null)||standard||natural;if(!match)return null;
 const [year,month,day,hour,minute,second]=match.slice(1).map(v=>v===undefined?undefined:Number(v));
 const date=new Date(Date.UTC(year!,month!-1,day!,hour!,minute!,second??0));
 if(date.getUTCFullYear()!==year||date.getUTCMonth()!==month!-1||date.getUTCDate()!==day||hour!>23||minute!>59||(second??0)>59)return null;
 const pad=(n:number)=>String(n).padStart(2,'0');return `${year}-${pad(month!)}-${pad(day!)}T${pad(hour!)}:${pad(minute!)}${second===undefined?'':':'+pad(second)}`;
}
export function recordingTimeLabel(value:string|null|undefined):string{
 if(!value)return'—';const m=value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}(?::\d{2})?)/);
 return m?`${m[1]}年${Number(m[2])}月${Number(m[3])}日 ${m[4]}`:'—';
}
/** 导入片段的统计写在 statistics 下；只有记录了 partial 的字段才标「≥」，旧记录没有时保持原样显示。 */
export function importedStatisticsPartial(statistics:any):{kills:boolean;assists:boolean;knockdowns:boolean;damage:boolean}|undefined{
 const partial=statistics?.partial;
 if(!partial||typeof partial!=='object'||!['kills','assists','knockdowns','damage'].every(key=>typeof partial[key]==='boolean'))return undefined;
 return {kills:partial.kills,assists:partial.assists,knockdowns:partial.knockdowns,damage:partial.damage};
}
/** 新统计完整扫描本段提示；旧缓存可能只保留正例下限，按字段状态展示。 */
export function clipStatistics(clip:any,candidates:any[]=[],analysis:PlaybackAnalysis={},fileIdentity?:VideoIdentity){
 const summary=clip.summary||{};const segment=clip.segment||{};
 const hudInfo=clip.recognition?.hud_info||null;
 const start=segment.requested_start??segment.start,end=segment.requested_end??segment.end;
 const related=candidates.filter(s=>s.start<end&&s.end>start);
 const found=summary.statistics_version?(clip.recognition?.outcome_evidence||[]):[...(clip.recognition?.outcome_evidence||[]),...(segment.own_result_filter?.events||[]),...related.flatMap(s=>s.own_result_filter?.events||[])];
 const unique=new Map<string,OutcomeEvidence>();
 const excludedKeys=new Set((clip.recognition?.outcome_evidence||[]).filter((e:any)=>e.confirmed===false).map(outcomeIdentity));
 const nativeKeys=new Set(found.filter((e:any)=>e.confirmed!==false&&!excludedKeys.has(outcomeIdentity(e))&&e.native_name_status==='confirmed').map(outcomeIdentity));
 for(const e of found)if(e.confirmed!==false&&!excludedKeys.has(outcomeIdentity(e))&&['knock','assist','elimination'].includes(e.kind)&&Number.isFinite(e.time)&&e.ownership==='self'&&e.time>=segment.start&&e.time<segment.end){const key=outcomeIdentity(e);if(nativeKeys.has(key)&&e.native_name_status!=='confirmed')continue;unique.set(key,{kind:e.kind,time:e.time,text:e.text,confidence:e.confidence,target:outcomeTarget(e),weapon:typeof e.weapon==='string'?e.weapon:undefined,weaponContext:weaponContextFor(e,clip,fileIdentity)});}
 const evidence=withProcessStarts([...unique.values()].sort((a,b)=>a.time-b.time),segment,related,analysis);
 const ranks=related.map(s=>s.rank).filter(Boolean);
 const rank=hudInfo?.refreshed_fields?.includes('rank')?(hudInfo.rank||null):hudInfo?.rank||clip.recognition?.rank||segment.rank||(ranks.length===related.length&&ranks.length&&ranks.every(r=>r.tier===ranks[0].tier&&r.division===ranks[0].division)?ranks[0]:null);
 const weapons=hudInfo?.refreshed_fields?.includes('weapons')||hudInfo?.weapons?.length?(hudInfo.weapons||[]).map((w:{name:string})=>w.name):Array.isArray(summary.weapons)?summary.weapons.filter((w:unknown)=>typeof w==='string'):[];
 const observed=(kind:string)=>{const n=evidence.filter(e=>e.kind===kind).length;return n||null;};
 const precise=!!summary.statistics_version;
 const completedKnockdowns=summary.event_completion_version===eventCompletionVersion&&typeof summary.statistics_partial?.knockdowns==='boolean';
 const endpoint=clip.recognition?.statistics?.endpoint;
 const roundKills=nativeEndProof(endpoint,'kills')?count(endpoint.last_hud.kills):null,roundDamage=nativeEndProof(endpoint,'damage')?count(endpoint.last_hud.damage):null;
 const roundTotals=roundKills!==null||roundDamage!==null?{kills:roundKills,damage:roundDamage}:undefined;
 return {kills:count(summary.kills),damage:count(summary.damage),weapons,
  hudInfo,accountName:hudInfo?.account?.name||null,teammates:hudInfo?.teammates||[],hero:hudInfo?.hero||null,matchKey:clip.recognition?.match_key,
  assists:precise?count(summary.assists):count(summary.assists)??observed('assist'),knockdowns:precise||completedKnockdowns?count(summary.knockdowns):count(summary.knockdowns)??observed('knock'),
  outcomeCountsPartial:summary.assists===undefined||summary.knockdowns===undefined,evidence,rank,
  statisticsPartial:summary.statistics_partial,statisticsNotes:summary.statistics_notes,settlementTotals:clip.recognition?.statistics?.settlement_totals,roundTotals,
  statisticsBasis:summary.statistics_basis||'击杀与伤害来自本段本人 HUD 增量；助攻和击倒展示已确认提示下限。'};
}
