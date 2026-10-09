export type Stage = 'idle'|'importing'|'probe'|'coarse'|'bisect'|'fine'|'audit'|'fallback'|'smart'|'sample'|'numeric'|'pipeline'|'cache'|'lifecycle'|'weapons'|'outcomes'|'combat_outcomes'|'export'|'verify'|'stopping'|'stopped'|'completed'|'error'|'unknown';
export type State = 'empty'|'ready'|'starting'|'running'|'stopping'|'stopped'|'completed'|'completed_with_errors'|'failed';
export interface Options {scan_mode:'smart'|'complete'; backend:'dml'|'cpu';gpu_load:'low'|'balanced'|'fast';fps:number;gap:number;pre:number;post:number;verify:boolean;delete_source:boolean;pipeline:boolean}
export const defaults:Options={scan_mode:'smart',backend:'dml',gpu_load:'low',fps:2,gap:35,pre:10,post:15,verify:true,delete_source:false,pipeline:false};
export interface FileItem {id:string;path:string;name:string;bytes?:number;duration?:number;width?:number;height?:number;fps?:number;status:'pending'|'running'|'complete'|'stopped'|'error';error?:string;missing?:boolean}
export interface ThemePreferences {mode:'system'|'light'|'dark';seed:string|null;reduceMotion:boolean}
export interface SystemTheme {dark:boolean;accent:string;reduceMotion:boolean}
export interface Clip {path:string;name:string;duration:number;kills:number|null;damage:number|null;weapons:string[];thumbnail?:string;start:number;end:number}
export interface FilterSummary {kept:number;rejected:number;review:number;rule:string}
export interface Result {source:string;status:string;outputs:string[];directory:string;review_count?:number;rejected_count?:number;result_filter_version?:string|null;result_filter_summary?:FilterSummary;verified?:boolean;source_cleanup?:{status:string;reason:string};clips:Clip[];review?:{start:number;end:number}[];rejected?:{start:number;end:number}[];error?:string}
export interface TaskInfo {path:string;directory:string;output:string;finished:boolean;options:Options;items:FileItem[];legacyRule:boolean;samplingWarning:string}
export interface WorkerEvent {type:string;stage?:Stage;progress?:number;message?:string;index?:number;total?:number;source?:string;directory?:string;task_path?:string;timestamp_seconds?:number;sample_path?:string;imageUrl?:string;cached?:boolean;failures?:number;clips?:number;result?:Result;elapsed_seconds?:number;hidden?:boolean;legacy_rule?:string|null;result_filter_rule?:string;result_filter_version?:string|null;rejected_count?:number;review_count?:number;result_filter_summary?:FilterSummary;sampling_warning?:string|null}
export interface Bootstrap {output:string;options:Options;preferences:ThemePreferences;theme:SystemTheme;development:boolean;lastTask:TaskInfo|null;backendAvailable:boolean}
export interface ImportResult {files:FileItem[];rejected:string[]}
export interface DesktopAPI {
 ready():Promise<void>;
 bootstrap():Promise<Bootstrap>;chooseFiles():Promise<ImportResult>;chooseFolder():Promise<ImportResult>;importFiles(files:File[]):Promise<ImportResult>;
 chooseOutput():Promise<string|null>;savePreferences(prefs:ThemePreferences):Promise<void>;saveOptions(options:Options,output:string):Promise<void>;
 start(files:string[],output:string,options:Options):Promise<void>;stop():Promise<void>;resume(task:string,options:Options):Promise<void>;
 chooseTask():Promise<TaskInfo|null>;lastTask():Promise<TaskInfo|null>;task(task:string):Promise<TaskInfo>;results(task:string):Promise<Result[]>;
 open(path:string,folder?:boolean):Promise<void>;onEvent(cb:(event:WorkerEvent)=>void):()=>void;onTheme(cb:(theme:SystemTheme)=>void):()=>void;
}
declare global {interface Window {apex:DesktopAPI}}
