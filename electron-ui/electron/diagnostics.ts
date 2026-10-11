import fs from 'node:fs/promises';
import {appendFileSync,mkdirSync} from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';

type Entry={name:string;text:string};
const logPattern=/^app-\d{4}-\d{2}-\d{2}T[\d-]+Z-\d+-[a-f0-9-]+\.log$/;
const defaultLimits={fileBytes:1024*1024,totalBytes:20*1024*1024,days:7};

/** Store-only ZIP: small text diagnostics need no external archive runtime. */
function textZip(entries:Entry[]){
 const crcTable=Array.from({length:256},(_,n)=>{let c=n;for(let i=0;i<8;i++)c=c&1?0xedb88320^(c>>>1):c>>>1;return c>>>0;});
 const local:Buffer[]=[],central:Buffer[]=[];let offset=0;
 for(const entry of entries){
  if(!/^[\w./-]+$/.test(entry.name)||entry.name.split('/').includes('..'))throw new Error('诊断附件名称无效');
  const name=Buffer.from(entry.name),data=Buffer.from(entry.text,'utf8');let crc=0xffffffff;for(const byte of data)crc=crcTable[(crc^byte)&255]^(crc>>>8);crc=(crc^0xffffffff)>>>0;
  const header=Buffer.alloc(30);header.writeUInt32LE(0x04034b50);header.writeUInt16LE(20,4);header.writeUInt16LE(0x800,6);header.writeUInt16LE(33,12);header.writeUInt32LE(crc,14);header.writeUInt32LE(data.length,18);header.writeUInt32LE(data.length,22);header.writeUInt16LE(name.length,26);
  local.push(header,name,data);
  const index=Buffer.alloc(46);index.writeUInt32LE(0x02014b50);index.writeUInt16LE(20,4);index.writeUInt16LE(20,6);index.writeUInt16LE(0x800,8);index.writeUInt16LE(33,14);index.writeUInt32LE(crc,16);index.writeUInt32LE(data.length,20);index.writeUInt32LE(data.length,24);index.writeUInt16LE(name.length,28);index.writeUInt32LE(offset,42);central.push(index,name);offset+=header.length+name.length+data.length;
 }
 const directory=Buffer.concat(central),end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50);end.writeUInt16LE(entries.length,8);end.writeUInt16LE(entries.length,10);end.writeUInt32LE(directory.length,12);end.writeUInt32LE(offset,16);
 return Buffer.concat([...local,directory,end]);
}

export class Diagnostics{
 readonly directory:string;
 private file='';private bytes=0;private queue:Promise<void>=Promise.resolve();private failure='';private aliases=new Map<string,string>();private lastPrune=0;
 constructor(directory:string,roots:Record<string,string>={},private limits=defaultLimits){this.directory=directory;for(const [label,value] of Object.entries(roots))if(value)this.aliases.set(value,`<${label}>`);}
 alias(value:string,label:string){if(value)this.aliases.set(value,label);}
 redact(value:string){
  let result=value;
  for(const [raw,label]of [...this.aliases].sort((a,b)=>b[0].length-a[0].length)){for(const variant of new Set([raw,raw.replaceAll('\\','/'),raw.replaceAll('\\','\\\\')])){if(variant.length<3)continue;result=result.replace(new RegExp(variant.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi'),()=>label);}}
  result=result.replace(/\b(?:[a-z]:[\\/]|file:\/\/\/)[^\r\n"'<>]+/gi,'<path>').replace(/\\\\[^\s"'<>]+/g,'<path>');
  result=result.replace(/\b(Bearer)\s+[^\s"'<>]+/gi,'$1 <redacted>').replace(/((?:token|password|secret|api[_-]?key|authorization)["']?\s*[:=]\s*["']?)[^\s"',}]+/gi,'$1<redacted>');
  return result.replace(/(https?:\/\/[^\s?"'<>]+)\?[^\s"'<>]*/gi,'$1?<redacted>');
 }
 private nextFile(){this.file=path.join(this.directory,`app-${new Date().toISOString().replace(/[.:]/g,'-')}-${process.pid}-${randomUUID()}.log`);this.bytes=0;}
 private clean(value:unknown,seen=new Set<object>(),depth=0):unknown{if(typeof value==='string')return this.redact(value).slice(0,12000);if(!value||typeof value!=='object')return value;if(depth>6||seen.has(value))return '<truncated>';seen.add(value);if(Array.isArray(value))return value.slice(0,500).map(item=>this.clean(item,seen,depth+1));return Object.fromEntries(Object.entries(value).slice(0,100).map(([key,item])=>[key,/token|password|secret|api[_-]?key|authorization/i.test(key)?'<redacted>':this.clean(item,seen,depth+1)]));}
 private line(level:string,component:string,message:string,details?:unknown){return JSON.stringify({time:new Date().toISOString(),level,component,message:this.redact(message).slice(0,12000),...(details===undefined?{}:{details:this.clean(details)})})+'\n';}
 log(level:'info'|'warning'|'error',component:string,message:string,details?:unknown){
  let line:string;try{line=this.line(level,component,message,details);}catch{line=this.line('error','diagnostics','日志字段无法序列化');}
  this.queue=this.queue.then(async()=>{try{await fs.mkdir(this.directory,{recursive:true});if(!this.file||this.bytes+Buffer.byteLength(line)>this.limits.fileBytes)this.nextFile();await fs.appendFile(this.file,line,'utf8');this.bytes+=Buffer.byteLength(line);this.failure='';if(Date.now()-this.lastPrune>60000)await this.prune();}catch(error){this.failure=this.redact(String(error));}});
 }
 fatal(error:Error){try{mkdirSync(this.directory,{recursive:true});if(!this.file)this.nextFile();appendFileSync(this.file,this.line('error','main-fatal',error.message,{stack:error.stack}),'utf8');}catch{}}
 async flush(){await this.queue;}
 async info(){await this.flush();return{directory:this.directory,available:!!this.file&&!this.failure,message:this.failure||undefined};}
 async prune(){
  this.lastPrune=Date.now();const entries:{file:string;size:number;mtime:number}[]=[];
  for(const entry of await fs.readdir(this.directory,{withFileTypes:true}).catch(()=>[])){if(!entry.isFile()||!logPattern.test(entry.name))continue;const file=path.join(this.directory,entry.name),stat=await fs.lstat(file);if(stat.isFile()&&!stat.isSymbolicLink())entries.push({file,size:stat.size,mtime:stat.mtimeMs});}
  entries.sort((a,b)=>b.mtime-a.mtime);let bytes=0;
  for(const entry of entries){bytes+=entry.size;if(entry.file===this.file)continue;const pid=Number(path.basename(entry.file).match(/Z-(\d+)-/)?.[1]);if(pid&&pid!==process.pid){try{process.kill(pid,0);continue;}catch(error){if((error as NodeJS.ErrnoException).code!=='ESRCH')continue;}}if(Date.now()-entry.mtime>this.limits.days*86400000||bytes>this.limits.totalBytes)await fs.unlink(entry.file).catch(()=>{});}
 }
 async export(file:string,report:unknown,extra:Entry[]=[]){
  this.log('info','diagnostics','用户导出诊断包');await this.flush();if(this.failure)throw new Error('日志无法写入：'+this.failure);
  const files=[];for(const entry of await fs.readdir(this.directory,{withFileTypes:true})){if(!entry.isFile()||!logPattern.test(entry.name))continue;const target=path.join(this.directory,entry.name),stat=await fs.lstat(target);if(stat.isFile()&&!stat.isSymbolicLink())files.push({file:target,name:entry.name,time:stat.mtimeMs});}files.sort((a,b)=>b.time-a.time);
  const entries:Entry[]=[{name:'diagnostics.json',text:JSON.stringify(this.clean(report),null,2)},{name:'README.txt',text:'请将此 ZIP 附加到 https://github.com/LilycleHeart/apex-highlight-clipper/issues/new，并写明问题现象、发生时间和复现步骤。\n包含近期程序日志、运行环境与任务状态摘要；本机路径已隐藏，不包含录像、封面、完整任务记录或 HUD 账号识别结果。\n'}];
  for(const entry of files.slice(0,5))entries.push({name:'logs/'+entry.name,text:this.redact((await fs.readFile(entry.file,'utf8')).slice(-this.limits.fileBytes))});
  for(const entry of extra.slice(0,10))entries.push({...entry,text:this.redact(entry.text.slice(-128*1024))});
  const temporary=file+'.'+randomUUID()+'.tmp';try{await fs.writeFile(temporary,textZip(entries),{flag:'wx'});await fs.rename(temporary,file);}finally{await fs.unlink(temporary).catch(()=>{});}
 }
}
