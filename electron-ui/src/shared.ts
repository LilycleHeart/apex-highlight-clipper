import {performanceDefaults,type PerformanceOptions} from './performanceOptions';
import type {PlayerAudioPreferences} from './audioPreferences';
import type {AnimationPreferences} from './animationPreferences';
export type Stage = 'idle'|'importing'|'probe'|'coarse'|'bisect'|'fine'|'audit'|'fallback'|'smart'|'sample'|'numeric'|'pipeline'|'cache'|'hud_info'|'lifecycle'|'weapons'|'rank'|'statistics'|'outcomes'|'combat_outcomes'|'export'|'stopping'|'stopped'|'completed'|'error'|'unknown';
export type State = 'empty'|'ready'|'starting'|'running'|'stopping'|'stopped'|'completed'|'completed_with_errors'|'failed';
export type HudField='account'|'weapons'|'teammates'|'hero'|'rank';
export type HudEnrichmentField=HudField|'statistics'|'opponents'|'event_weapons';
export interface HudEnrichmentResult {updated:number;errors:{directory:string;message:string}[];unconfirmed?:number}
export interface ClipCollection {id:string;name:string;createdAt:string;files:string[];synced:boolean}

export interface Clip {algorithmFields?:readonly import('./algorithmStatus').AlgorithmFieldRecord[];/** 未经本软件处理、由用户添加的已有片段：只有画面 HUD 信息，移除时文件保留。 */imported?:boolean;fieldStatus?:Partial<Record<string,'confirmed'|'unknown'>>}
export interface WorkerEvent {performance_policy?:import('./performanceOptions').PerformanceRuntime}
export type HudEnrichmentMode='missing'|'refresh';
export interface Options extends PerformanceOptions {export_layout:'task'|'flat';scan_mode:'smart'|'complete'|'indexed';fps:number;gap:number;pre:number;post:number;delete_source:boolean;pipeline:boolean;hud_info_enabled:boolean;hud_info_fields:HudField[];filter_enabled:boolean;filter_mode:'any'|'all';min_damage:number;min_kills:number;min_assists:number;min_duration:number}
export const defaults:Options={export_layout:'task',scan_mode:'indexed',...performanceDefaults,fps:2,gap:10,pre:6,post:6,delete_source:false,pipeline:false,hud_info_enabled:false,hud_info_fields:['account','weapons','teammates','hero','rank'],filter_enabled:false,filter_mode:'any',min_damage:0,min_kills:0,min_assists:0,min_duration:0};
export interface FileItem {id:string;path:string;name:string;bytes?:number;duration?:number;width?:number;height?:number;fps?:number;processingSeconds?:number;status:'pending'|'running'|'complete'|'stopped'|'error';error?:string;missing?:boolean}
export type MascotStyle='flat'|'sketch';
export interface ThemePreferences extends AnimationPreferences {mode:'system'|'light'|'dark';seed:string|null;reduceMotion:boolean;mascotStyle:MascotStyle;mascotEnabled:boolean}
export interface SystemTheme {dark:boolean;accent:string;reduceMotion:boolean}
export interface OutcomeEvidence {kind:'knock'|'assist'|'elimination';time:number;processStart?:number;processStartBasis?:'shoot'|'hit'|'candidate'|'near_result';text?:string;confidence?:number;target?:string;weapon?:string;weaponContext?:{scope:'nearby_firing'|'held_at_event'|'held_before_event'|'held_near_event';weapon:string;label:string}}
export interface Rank {tier:string;name:string;division:string|null;confidence:number;method:string;scope?:string}
export interface HudName {name:string;confidence:number;method?:string;raw_name?:string}
export interface Hero extends HudName {id:string}
export interface HudInfo {version:string;requested_fields:HudField[];refreshed_fields?:HudEnrichmentField[];field_status:Partial<Record<HudField,'confirmed'|'unknown'>>;account?:HudName|null;teammates?:HudName[];hero?:Hero|null;rank?:Rank|null;weapons?:{id:string;name:string;confidence:number}[];checked_frames?:number}
export interface Clip {roundTotals?:{kills:number|null;damage:number|null};media?:import('./mediaGeometry').MediaGeometry;taskPath?:string;source?:string;exportedAt?:string;path:string;name:string;duration:number;kills:number|null;damage:number|null;weapons:string[];thumbnail?:string;start:number;end:number;assists?:number|null;knockdowns?:number|null;outcomeCountsPartial?:boolean;evidence?:OutcomeEvidence[];statisticsBasis?:string;rank?:Rank|null;recordedAt?:string|null;statisticsPartial?:{kills:boolean;assists:boolean;knockdowns:boolean;damage:boolean};statisticsNotes?:string[];settlementTotals?:{kills:number;assists:number}|null;hudInfo?:HudInfo|null;accountName?:string|null;accountAliases?:string[];teammates?:HudName[];hero?:Hero|null;matchKey?:string}
export interface FilterSummary {kept:number;rejected:number;review:number;rule:string}
export interface Result {source:string;status:string;outputs:string[];directory:string;review_count?:number;rejected_count?:number;result_filter_version?:string|null;result_filter_summary?:FilterSummary;verified?:boolean;source_cleanup?:{status:string;reason:string};clips:Clip[];review?:{start:number;end:number}[];rejected?:{start:number;end:number}[];error?:string;quality_rejected_count?:number;quality_filter_summary?:{kept:number;rejected:number;review:number}|null;qualityRejected?:{start:number;end:number;reason:string}[]}
export interface TaskInfo {path:string;directory:string;output:string;finished:boolean;options:Options;items:FileItem[];legacyRule:boolean;samplingWarning:string}
export interface WorkerEvent {type:string;file?:string;fields?:HudEnrichmentField[];frames_done?:number;frames_total?:number;backend?:string;updated?:number;errors?:{directory:string;message:string}[];processing_seconds?:number;skipped?:boolean;stage?:Stage;progress?:number;message?:string;index?:number;total?:number;source?:string;directory?:string;task_path?:string;timestamp_seconds?:number;sample_path?:string;imageUrl?:string;cached?:boolean;failures?:number;clips?:number;result?:Result;elapsed_seconds?:number;hidden?:boolean;legacy_rule?:string|null;result_filter_rule?:string;result_filter_version?:string|null;rejected_count?:number;review_count?:number;result_filter_summary?:FilterSummary;sampling_warning?:string|null;results?:Result[]}
export interface InstallerAsset {version:string;name:string;url:string;bytes:number;sha256:string}
/** 内置的 GitHub 加速前缀；空字符串表示直连。 */
export const GITHUB_MIRRORS:Array<{value:string;label:string}>=[
 {value:'',label:'不使用加速'},
 {value:'https://edgeone.gh-proxy.com/',label:'edgeone.gh-proxy.com'},
 {value:'https://hk.gh-proxy.com/',label:'hk.gh-proxy.com'},
 {value:'https://gh-proxy.com/',label:'gh-proxy.com'},
 {value:'https://gh.dpik.top/',label:'gh.dpik.top（仅下载）'},
 {value:'https://ghfast.top/',label:'ghfast.top（仅下载）'},
];

export interface UpdateInfo {status:'idle'|'checking'|'available'|'up_to_date'|'no_release'|'error';currentVersion:string;latestVersion?:string;releaseTag?:string;releaseName?:string;releaseNotes?:string;publishedAt?:string;checkedAt?:string;message?:string;autoCheck:boolean;installer?:InstallerAsset;installState?:'downloading'|'installing'|'error';installProgress?:number;installMessage?:string;mirror?:string}
export interface Bootstrap {excludedTeammates:string[];playerAudio:PlayerAudioPreferences;output:string;options:Options;preferences:ThemePreferences;theme:SystemTheme;development:boolean;lastTask:TaskInfo|null;backendAvailable:boolean;cudaAvailable?:boolean;logicalCores:number;update:UpdateInfo}
export interface ImportResult {files:FileItem[];rejected:string[]}
export interface LibrarySnapshot {results:Result[];tasks:number;errors:number}
/** restored：认领到原有记录、恢复战绩与识别信息；added：按未处理过的片段新加入。 */
export interface AddExistingResult {library:LibrarySnapshot;restored:number;added:number;existing:number;rejected:number;truncated:boolean}
export type WindowCommand='minimize'|'maximize'|'close';
export interface WindowState {maximized:boolean}
export interface DesktopAPI {
 diagnosticsInfo():Promise<{directory:string;available:boolean;message?:string}>;
 openDiagnostics():Promise<void>;
 exportDiagnostics():Promise<string|null>;
 openFeedback():Promise<void>;
 reportDiagnostic(value:{type:'error'|'action';message:string;stack?:string}):Promise<void>;
 windowState():Promise<WindowState>;
 windowCommand(value:WindowCommand):Promise<void>;
 onWindowState(cb:(state:WindowState)=>void):()=>void;
 setTeammateExcluded(name:string,excluded:boolean):Promise<string[]>;
 savePlayerAudio(value:PlayerAudioPreferences):Promise<void>;
 shareClips(files:string[]):Promise<{status:'opened';count:number}>;
 enrichHud(files:string[],fields:HudEnrichmentField[],mode?:HudEnrichmentMode):Promise<HudEnrichmentResult>;
  hudRecovery():Promise<{clips:import('./algorithmStatus').ClipAlgorithmStatus[];jobs:import('./algorithmStatus').RecognitionRecoveryJob[]}>;
  resumeHud(id:string):Promise<HudEnrichmentResult>;
  abandonHud(id?:string):Promise<{abandoned:string}>;
  setUpdateMirror(mirror:string):Promise<UpdateInfo>;
  testUpdateMirror(mirror:string):Promise<{ok:boolean;ms:number;message:string}>;
  upgradeHud(selection:import('./algorithmStatus').UpgradeSelection[],includeUnknown:boolean):Promise<HudEnrichmentResult>;
 library():Promise<LibrarySnapshot>;
 deleteClip(file:string):Promise<void>;
  removeImported(files:string[]):Promise<{removed:number}>;
  listCollections():Promise<ClipCollection[]>;
  addToCollection(files:string[],name:string,syncFolder:boolean):Promise<{collection:ClipCollection;moved:number}>;
  removeFromCollection(id:string,files:string[]):Promise<{collection:ClipCollection}>;
  deleteCollection(id:string):Promise<{removed:number}>;
 ignoreLibraryErrors():Promise<LibrarySnapshot>;
 chooseLibraryRoot():Promise<boolean>;
 addExistingClips():Promise<AddExistingResult|null>;
 addExistingFolder():Promise<AddExistingResult|null>;
 ready():Promise<void>;
 chrome(color:string,foreground:string):Promise<void>;
 bootstrap():Promise<Bootstrap>;chooseFiles():Promise<ImportResult>;chooseFolder():Promise<ImportResult>;importFiles(files:File[]):Promise<ImportResult>;
 chooseOutput():Promise<string|null>;savePreferences(prefs:ThemePreferences):Promise<void>;saveOptions(options:Options,output:string):Promise<void>;savePerformance(options:PerformanceOptions):Promise<void>;
 start(files:string[],output:string,options:Options):Promise<void>;stop():Promise<void>;resume(task:string,options:Options):Promise<void>;
 chooseTask():Promise<TaskInfo|null>;lastTask():Promise<TaskInfo|null>;task(task:string):Promise<TaskInfo>;results(task:string):Promise<Result[]>;
 open(path:string,folder?:boolean):Promise<void>;onEvent(cb:(event:WorkerEvent)=>void):()=>void;onTheme(cb:(theme:SystemTheme)=>void):()=>void;
 videoURL(path:string):Promise<string>;
 thumbnailURL(path:string):Promise<string>;
 thumbnailStats():Promise<{active:number;queued:number;generated:number;failed:number;cacheHits:number}>;
 checkUpdate():Promise<UpdateInfo>;setAutoCheck(enabled:boolean):Promise<UpdateInfo>;openRelease():Promise<void>;onUpdate(cb:(info:UpdateInfo)=>void):()=>void;
 installUpdate():Promise<void>;
}
declare global {interface Window {apex:DesktopAPI}}
