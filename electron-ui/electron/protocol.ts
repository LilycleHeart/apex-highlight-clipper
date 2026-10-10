import {StringDecoder} from 'node:string_decoder';
export class JsonLines {
  private decoder=new StringDecoder('utf8');private pending='';
  constructor(private receive:(event:Record<string,unknown>)=>void,private malformed:(line:string)=>void){}
  push(chunk:Buffer){this.consume(this.decoder.write(chunk));}
  end(){this.consume(this.decoder.end());if(this.pending.trim())this.line(this.pending);this.pending='';}
  private consume(text:string){this.pending+=text;let index:number;while((index=this.pending.indexOf('\n'))>=0){const value=this.pending.slice(0,index);this.pending=this.pending.slice(index+1);this.line(value);}if(this.pending.length>4*1024*1024){this.malformed('后台状态行过长');this.pending='';}}
  private line(value:string){if(!value.trim())return;try{const parsed=JSON.parse(value);if(parsed&&typeof parsed==='object'&&typeof parsed.type==='string')this.receive(parsed);else this.malformed(value.slice(0,500));}catch{this.malformed(value.slice(0,500));}}
}
export const videoExtensions=new Set(['.mp4','.mkv','.mov','.ts','.m4v']);
export function safeOptions(value:any,legacy=false){
 const limits:Record<string,[number,number]>={fps:[legacy?.5:1,5],gap:[0,600],pre:[0,120],post:[0,180]};
 if(!legacy&&typeof value.fps==='number'&&value.fps<1)throw new Error('新任务细查频率至少需要1帧/秒');
 for(const [key,[a,b]] of Object.entries(limits))if(typeof value[key]!=='number'||!Number.isFinite(value[key])||value[key]<a||value[key]>b)throw new Error(`${key} 参数超出范围`);
 if(!['smart','complete','indexed'].includes(value.scan_mode)||!['cpu','dml'].includes(value.backend)||!['low','balanced','fast'].includes(value.gpu_load))throw new Error('识别选项无效');
 for(const key of ['verify','delete_source','pipeline'])if(typeof value[key]!=='boolean')throw new Error('开关参数无效');
 const filters={filter_enabled:value.filter_enabled??false,filter_mode:value.filter_mode??'any',min_damage:value.min_damage??0,min_kills:value.min_kills??0,min_assists:value.min_assists??0};
 if(typeof filters.filter_enabled!=='boolean'||!['any','all'].includes(filters.filter_mode))throw new Error('过滤选项无效');
 for(const [key,max] of [['min_damage',20000],['min_kills',60],['min_assists',99]] as const)if(!Number.isInteger(filters[key])||filters[key]<0||filters[key]>max)throw new Error('过滤阈值超出范围');
 return {fps:value.fps,gap:value.gap,pre:value.pre,post:value.post,scan_mode:legacy?value.scan_mode:'indexed',backend:value.backend,gpu_load:value.gpu_load,delete_source:value.delete_source,verify:value.verify,pipeline:legacy&&value.scan_mode==='complete'&&value.pipeline,...filters};
}
