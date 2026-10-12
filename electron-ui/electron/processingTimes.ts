import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';

export function historicProcessingSeconds(item:any):number|undefined{
 const value=item?.processing_seconds??item?.record?.processing_seconds;
 if(typeof value==='number'&&Number.isFinite(value)&&value>=0)return value;
 const stages=item?.record?.stage_seconds;
 if(!stages||typeof stages!=='object')return;
 const values=Object.values(stages).filter((n):n is number=>typeof n==='number'&&Number.isFinite(n)&&n>=0);
 return values.length?values.reduce((sum,n)=>sum+n,0):undefined;
}

/** Per-task processing time: monotonic while active, persisted totals exclude pause and queue wait. */
export class ProcessingTimes{
 private values:Record<string,number>={};private active:{key:string;source:string;base:number;start:number;checkpoint:number}|null=null;
 private timer:ReturnType<typeof setInterval>|null=null;private writes:Promise<void>=Promise.resolve();
 constructor(private file:string,private publish:(source:string,seconds:number)=>void,private failure:(error:unknown)=>void=()=>{},private now:()=>number=()=>performance.now()){}
 private key(task:string,source:string){return createHash('sha256').update(path.resolve(task).toLowerCase()+'\0'+path.resolve(source).toLowerCase()).digest('hex');}
 async load(){try{const data=JSON.parse(await fs.readFile(this.file,'utf8'));if(data.version===1)for(const[k,v]of Object.entries(data.seconds||{}))if(/^[a-f0-9]{64}$/.test(k)&&typeof v==='number'&&Number.isFinite(v)&&v>=0)this.values[k]=v;}catch(error){if((error as NodeJS.ErrnoException).code!=='ENOENT')this.failure(error);}}
 seconds(task:string,source:string,fallback?:number){const key=this.key(task,source);return this.active?.key===key?this.elapsed():this.values[key]??fallback;}
 private elapsed(){return this.active?this.active.base+Math.max(0,this.now()-this.active.start)/1000:0;}
 begin(task:string,source:string,fallback=0){
  this.finish();const key=this.key(task,source),start=this.now();
  this.active={key,source,base:this.values[key]??fallback,start,checkpoint:start};this.tick();
  this.timer=setInterval(()=>this.tick(),1000);this.timer.unref();
 }
 tick(){const active=this.active;if(!active)return;const seconds=this.elapsed();this.values[active.key]=seconds;this.publish(active.source,seconds);if(this.now()-active.checkpoint>=5000){active.checkpoint=this.now();this.save();}}
 finish(skipped=false){
  if(this.timer){clearInterval(this.timer);this.timer=null;}
  const active=this.active;if(!active)return;
  const seconds=skipped?active.base:this.elapsed();this.active=null;this.values[active.key]=seconds;this.publish(active.source,seconds);this.save();return seconds;
 }
 private save(){const data=JSON.stringify({version:1,seconds:this.values});this.writes=this.writes.catch(()=>{}).then(async()=>{await fs.mkdir(path.dirname(this.file),{recursive:true});const temporary=this.file+'.tmp';await fs.writeFile(temporary,data,'utf8');await fs.rename(temporary,this.file);}).catch(error=>this.failure(error));}
 async flush(){await this.writes;}
}
