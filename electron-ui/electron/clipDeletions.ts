import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {videoExtensions} from './protocol';

const key=(file:string)=>path.resolve(file).toLowerCase();
/** Durable intent is saved before recycling; existing/restored files remain visible. */
export class ClipDeletions{
 private files=new Map<string,string>();private jobs:Promise<unknown>=Promise.resolve();private pending=0;
 constructor(private file:string,private authorize:(file:string)=>Promise<void>,private release:(file:string)=>Promise<void>,private recycle:(file:string)=>Promise<void>){}
 async load(){try{const saved=JSON.parse((await fs.readFile(this.file,'utf8')).replace(/^\uFEFF/,''));if(saved.version===1)for(const file of saved.files||[])if(typeof file==='string'&&path.isAbsolute(file)&&videoExtensions.has(path.extname(file).toLowerCase()))this.files.set(key(file),file);}catch{}}
 isRemoved(file:string){return this.files.has(key(file))&&!existsSync(file);}
 get busy(){return this.pending>0;}
 remove(input:unknown){
  if(typeof input!=='string'||!path.isAbsolute(input)||!videoExtensions.has(path.extname(input).toLowerCase()))return Promise.reject(new Error('只允许回收已导出的片段'));
  this.pending++;const file=path.resolve(input),job=this.jobs.then(async()=>{
   await this.authorize(file);await this.release(file);
   const previous=this.files.get(key(file));this.files.set(key(file),file);
   try{await this.save();if(existsSync(file))await this.recycle(file);if(existsSync(file))throw new Error('片段未能移至回收站');}
   catch(error){if(existsSync(file)){if(previous)this.files.set(key(file),previous);else this.files.delete(key(file));await this.save();}throw error;}
  });this.jobs=job.catch(()=>{});return job.finally(()=>{this.pending--;});
 }
 private async save(){await fs.mkdir(path.dirname(this.file),{recursive:true});const temporary=this.file+'.'+randomUUID()+'.tmp';try{await fs.writeFile(temporary,JSON.stringify({version:1,files:[...this.files.values()]}),'utf8');await fs.rename(temporary,this.file);}finally{await fs.unlink(temporary).catch(()=>{});}}
}
