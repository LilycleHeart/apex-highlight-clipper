import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn,type ChildProcess} from 'node:child_process';
import {createHash,randomUUID} from 'node:crypto';
export class ThumbnailStore{
 private active=0;private closed=false;private queue:(()=>Promise<void>)[]=[];private pending=new Map<string,Promise<string>>();private processes=new Set<ChildProcess>();
 private generated=0;private failed=0;private cacheHits=0;
 private lastCleanup=0;private cleanup:Promise<void>|null=null;
 async prune(force=false){
  if(this.cleanup)return this.cleanup;
  if(this.active||this.queue.length||(!force&&Date.now()-this.lastCleanup<3600000))return;
  this.lastCleanup=Date.now();
  this.cleanup=(async()=>{
   const now=Date.now(),entries: {file:string;size:number;mtime:number;temporary:boolean}[]=[];
   for(const item of await fs.readdir(this.directory,{withFileTypes:true}).catch(()=>[])){
    if(!item.isFile()||! /^[a-f0-9]{64}(?:-[a-f0-9-]{36})?\.jpg$/.test(item.name)||this.pending.has(item.name.slice(0,64)))continue;
    const file=path.join(this.directory,item.name),stat=await fs.lstat(file).catch(()=>null);
    if(stat?.isFile())entries.push({file,size:stat.size,mtime:stat.mtimeMs,temporary:item.name.length>68});
   }
   entries.sort((a,b)=>a.mtime-b.mtime);let bytes=entries.reduce((sum,item)=>sum+item.size,0);
   for(const item of entries){
    if(this.active||this.queue.length||this.closed)break;
    if(!(item.temporary&&now-item.mtime>86400000)&&!(now-item.mtime>60*86400000)&&bytes<=256*1024*1024)continue;
    try{await fs.unlink(item.file);bytes-=item.size;}catch{}
   }
  })().finally(()=>{this.cleanup=null;});return this.cleanup;
 }
 stats(){return{active:this.active,queued:this.queue.length,generated:this.generated,failed:this.failed,cacheHits:this.cacheHits};}
 constructor(readonly directory:string,private ffmpeg:()=>string){}
 async get(file:string,duration:number){
  const stat=await fs.stat(file),key=createHash('sha256').update(JSON.stringify([path.resolve(file).toLowerCase(),stat.size,stat.mtimeMs,'preview-v1'])).digest('hex');
  const cached=path.join(this.directory,key+'.jpg');try{const info=await fs.stat(cached);if(info.size>0){if(Date.now()-info.mtimeMs>86400000)await fs.utimes(cached,new Date(),new Date()).catch(()=>{});this.cacheHits++;return cached;}}catch{}
  const previous=this.pending.get(key);if(previous)return previous;
  const promise=new Promise<string>((resolve,reject)=>{this.queue.push(async()=>{let temporary='';try{if(this.closed)throw new Error('程序已关闭');await fs.mkdir(this.directory,{recursive:true});temporary=path.join(this.directory,key+'-'+randomUUID()+'.jpg');await this.render(file,temporary,Number.isFinite(duration)&&duration>0?Math.max(0,duration/2):0);await fs.rename(temporary,cached);this.generated++;resolve(cached);}catch(error){if(!this.closed)this.failed++;reject(error);}finally{if(temporary)await fs.unlink(temporary).catch(()=>{});this.pending.delete(key);}});});
  this.pending.set(key,promise);this.pump();return promise;
 }
 private pump(){while(!this.closed&&this.active<2&&this.queue.length){const job=this.queue.shift()!;this.active++;void job().finally(()=>{this.active--;this.pump();});}if(!this.closed&&!this.active&&!this.queue.length)void this.prune().catch(()=>{});}
 private async render(file:string,output:string,time:number){
  await new Promise<void>((resolve,reject)=>{const proc=spawn(this.ffmpeg(),['-hide_banner','-loglevel','error','-threads','1','-ss',String(time),'-i',file,'-map','0:v:0','-frames:v','1','-an','-sn','-dn','-filter_threads','1','-vf',"scale=w='min(480,360*dar)':h='ow/dar',setsar=1",'-q:v','4','-threads','1','-y',output],{windowsHide:true});this.processes.add(proc);let stderr='';proc.stderr?.setEncoding('utf8');proc.stderr?.on('data',value=>stderr=(stderr+value).slice(-1200));const timer=setTimeout(()=>proc.kill(),15000);proc.once('error',()=>{clearTimeout(timer);this.processes.delete(proc);reject(new Error('无法准备预览画面，请先通过 Start.cmd 启动以准备视频工具'));});proc.once('close',code=>{clearTimeout(timer);this.processes.delete(proc);if(code===0)resolve();else reject(new Error(stderr?'暂时无法生成画面，可直接播放片段':'封面读取超时，可直接播放片段'));});});
  if(!(await fs.stat(output).catch(()=>null))?.size)throw new Error('暂时没有读取到视频画面，可直接播放片段');
 }
 dispose(){this.closed=true;for(const process of this.processes)process.kill();while(this.queue.length)void this.queue.shift()!();}
}
