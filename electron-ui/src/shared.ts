export type Stage = 'idle'|'importing'|'probe'|'coarse'|'bisect'|'fine'|'audit'|'fallback'|'smart'|'sample'|'numeric'|'pipeline'|'cache'|'lifecycle'|'weapons'|'rank'|'statistics'|'outcomes'|'combat_outcomes'|'export'|'verify'|'stopping'|'stopped'|'completed'|'error'|'unknown';
export type State = 'empty'|'ready'|'starting'|'running'|'stopping'|'stopped'|'completed'|'completed_with_errors'|'failed';
export interface Options {scan_mode:'smart'|'complete'|'indexed'; backend:'dml'|'cpu';gpu_load:'low'|'balanced'|'fast';fps:number;gap:number;pre:number;post:number;verify:boolean;delete_source:boolean;pipeline:boolean;filter_enabled:boolean;filter_mode:'any'|'all';min_damage:number;min_kills:number;min_assists:number}
export const defaults:Options={scan_mode:'indexed',backend:'dml',gpu_load:'low',fps:2,gap:35,pre:10,post:15,verify:true,delete_source:false,pipeline:false,filter_enabled:false,filter_mode:'any',min_damage:0,min_kills:0,min_assists:0};
export interface FileItem {id:string;path:string;name:string;bytes?:number;duration?:number;width?:number;height?:number;fps?:number;status:'pending'|'running'|'complete'|'stopped'|'error';error?:string;missing?:boolean}
export type MascotStyle='flat'|'sketch';
export interface ThemePreferences {mode:'system'|'light'|'dark';seed:string|null;reduceMotion:boolean;mascotStyle:MascotStyle;mascotEnabled:boolean}
export interface SystemTheme {dark:boolean;accent:string;reduceMotion:boolean}
export interface OutcomeEvidence {kind:'knock'|'assist'|'elimination';time:number;text?:string;confidence?:number}
export interface Rank {tier:string;name:string;division:string|null;confidence:number;method:string;scope?:string}
export interface Clip {path:string;name:string;duration:number;kills:number|null;damage:number|null;weapons:string[];thumbnail?:string;start:number;end:number;assists?:number|null;knockdowns?:number|null;outcomeCountsPartial?:boolean;evidence?:OutcomeEvidence[];statisticsBasis?:string;rank?:Rank|null;recordedAt?:string|null;statisticsPartial?:{kills:boolean;assists:boolean;knockdowns:boolean;damage:boolean};statisticsNotes?:string[];settlementTotals?:{kills:number;assists:number}|null}
export interface FilterSummary {kept:number;rejected:number;review:number;rule:string}
export interface Result {source:string;status:string;outputs:string[];directory:string;review_count?:number;rejected_count?:number;result_filter_version?:string|null;result_filter_summary?:FilterSummary;verified?:boolean;source_cleanup?:{status:string;reason:string};clips:Clip[];review?:{start:number;end:number}[];rejected?:{start:number;end:number}[];error?:string;quality_rejected_count?:number;quality_filter_summary?:{kept:number;rejected:number;review:number}|null;qualityRejected?:{start:number;end:number;reason:string}[]}
export interface TaskInfo {path:string;directory:string;output:string;finished:boolean;options:Options;items:FileItem[];legacyRule:boolean;samplingWarning:string}
export interface WorkerEvent {type:string;stage?:Stage;progress?:number;message?:string;index?:number;total?:number;source?:string;directory?:string;task_path?:string;timestamp_seconds?:number;sample_path?:string;imageUrl?:string;cached?:boolean;failures?:number;clips?:number;result?:Result;elapsed_seconds?:number;hidden?:boolean;legacy_rule?:string|null;result_filter_rule?:string;result_filter_version?:string|null;rejected_count?:number;review_count?:number;result_filter_summary?:FilterSummary;sampling_warning?:string|null;results?:Result[]}
export interface UpdateInfo {status:'idle'|'checking'|'available'|'up_to_date'|'no_release'|'error';currentVersion:string;latestVersion?:string;releaseTag?:string;releaseName?:string;releaseNotes?:string;publishedAt?:string;checkedAt?:string;message?:string;autoCheck:boolean}
export interface Bootstrap {output:string;options:Options;preferences:ThemePreferences;theme:SystemTheme;development:boolean;lastTask:TaskInfo|null;backendAvailable:boolean;update:UpdateInfo}
export interface ImportResult {files:FileItem[];rejected:string[]}
export interface DesktopAPI {
 ready():Promise<void>;
 bootstrap():Promise<Bootstrap>;chooseFiles():Promise<ImportResult>;chooseFolder():Promise<ImportResult>;importFiles(files:File[]):Promise<ImportResult>;
 chooseOutput():Promise<string|null>;savePreferences(prefs:ThemePreferences):Promise<void>;saveOptions(options:Options,output:string):Promise<void>;
 start(files:string[],output:string,options:Options):Promise<void>;stop():Promise<void>;resume(task:string,options:Options):Promise<void>;
 chooseTask():Promise<TaskInfo|null>;lastTask():Promise<TaskInfo|null>;task(task:string):Promise<TaskInfo>;results(task:string):Promise<Result[]>;
 open(path:string,folder?:boolean):Promise<void>;onEvent(cb:(event:WorkerEvent)=>void):()=>void;onTheme(cb:(theme:SystemTheme)=>void):()=>void;
 videoURL(path:string):Promise<string>;
 checkUpdate():Promise<UpdateInfo>;setAutoCheck(enabled:boolean):Promise<UpdateInfo>;openRelease():Promise<void>;onUpdate(cb:(info:UpdateInfo)=>void):()=>void;
}
declare global {interface Window {apex:DesktopAPI}}
