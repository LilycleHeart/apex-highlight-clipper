import {normalizePerformance} from '../src/performanceOptions';
import {StringDecoder} from 'node:string_decoder';
import type {HudField} from '../src/shared';
export class JsonLines {
  private decoder=new StringDecoder('utf8');private pending='';
  constructor(private receive:(event:Record<string,unknown>)=>void,private malformed:(line:string)=>void){}
  push(chunk:Buffer){this.consume(this.decoder.write(chunk));}
  end(){this.consume(this.decoder.end());if(this.pending.trim())this.line(this.pending);this.pending='';}
  private consume(text:string){this.pending+=text;let index:number;while((index=this.pending.indexOf('\n'))>=0){const value=this.pending.slice(0,index);this.pending=this.pending.slice(index+1);this.line(value);}if(this.pending.length>4*1024*1024){this.malformed('后台状态行过长');this.pending='';}}
  private line(value:string){if(!value.trim())return;try{const parsed=JSON.parse(value);if(parsed&&typeof parsed==='object'&&typeof parsed.type==='string')this.receive(parsed);else this.malformed(value.slice(0,500));}catch{this.malformed(value.slice(0,500));}}
}
export const videoExtensions=new Set(['.mp4','.mkv','.mov','.ts','.m4v']);
export function safeHudFiles(value:unknown,allowed:ReadonlySet<string>,normalize:(file:string)=>string):string[]{
 if(!Array.isArray(value)||!value.length)throw new Error('请选择片段库中已导出的片段');
 const selected=new Map<string,string>();
 for(const file of value){
  if(typeof file!=='string')throw new Error('请选择片段库中已导出的片段');
  const key=normalize(file);
  if(!allowed.has(key))throw new Error('所选片段已不在当前片段库中，请刷新后重试');
  if(!selected.has(key))selected.set(key,file);
 }
 return [...selected.values()];
}
export function safeOptions(value:any,legacy=false){
 const performance=normalizePerformance(value,true);
 const export_layout=value.export_layout??'task';if(!['task','flat'].includes(export_layout))throw new Error('导出布局无效');
 const limits:Record<string,[number,number]>={fps:[legacy?.5:1,5],gap:[0,600],pre:[0,120],post:[0,180]};
 if(!legacy&&typeof value.fps==='number'&&value.fps<1)throw new Error('新任务细查频率至少需要1帧/秒');
 for(const [key,[a,b]] of Object.entries(limits))if(typeof value[key]!=='number'||!Number.isFinite(value[key])||value[key]<a||value[key]>b)throw new Error(`${key} 参数超出范围`);
 if(!['smart','complete','indexed'].includes(value.scan_mode))throw new Error('识别选项无效');
 for(const key of ['delete_source','pipeline'])if(typeof value[key]!=='boolean')throw new Error('开关参数无效');
 const filters={filter_enabled:value.filter_enabled??false,filter_mode:value.filter_mode??'any',min_damage:value.min_damage??0,min_kills:value.min_kills??0,min_assists:value.min_assists??0,min_duration:value.min_duration??0};
 if(typeof filters.filter_enabled!=='boolean'||!['any','all'].includes(filters.filter_mode))throw new Error('过滤选项无效');
 for(const [key,max] of [['min_damage',20000],['min_kills',60],['min_assists',99],['min_duration',86400]] as const)if(!Number.isInteger(filters[key])||filters[key]<0||filters[key]>max)throw new Error('过滤阈值超出范围');
 const hud_info_enabled=value.hud_info_enabled??false,hud_info_fields:HudField[]=value.hud_info_fields??['account','weapons','teammates','hero','rank'];
 if(typeof hud_info_enabled!=='boolean'||!Array.isArray(hud_info_fields)||hud_info_fields.some(field=>!['account','weapons','teammates','hero','rank'].includes(field)))throw new Error('HUD信息选项无效');
 return {export_layout:export_layout as 'task'|'flat',fps:value.fps,gap:value.gap,pre:value.pre,post:value.post,scan_mode:legacy?value.scan_mode:'indexed',...performance,delete_source:value.delete_source,pipeline:legacy&&value.scan_mode==='complete'&&value.pipeline,hud_info_enabled,hud_info_fields:[...new Set(hud_info_fields)],...filters};
}
