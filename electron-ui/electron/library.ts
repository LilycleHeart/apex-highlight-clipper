import {normalizeLibraryNames} from '../src/libraryNames';
import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import type {Result} from '../src/shared';
const key=(value:string)=>path.resolve(value).toLowerCase();
/** 仅扫描已知输出根和登记任务，不遍历用户磁盘，不改写任务或成片。 */
export async function discoverTasks(roots:string[],registered:string[]=[]){
 const found=new Map<string,string>();for(const file of registered)if(path.isAbsolute(file))found.set(key(file),file);
 async function walk(dir:string,depth:number){
  let entries;try{entries=await fs.readdir(dir,{withFileTypes:true});}catch{return;}
  if(entries.some(e=>e.name==='task.json'&&e.isFile())){const file=path.join(dir,'task.json');found.set(key(file),file);return;}
  if(depth>=3)return;
  for(const entry of entries)if(entry.isDirectory()&&!entry.isSymbolicLink()&&!['validation','node_modules','runtime','.git'].includes(entry.name))await walk(path.join(dir,entry.name),depth+1);
 }
 for(const root of [...new Set(roots.filter(value=>typeof value==='string'&&path.isAbsolute(value)).map(value=>path.resolve(value)))])await walk(root,0);
 return [...found.values()];
}
export function mergeLibrary(results:Result[]){
 const seen=new Set<string>();return normalizeLibraryNames(results.map(result=>({...result,clips:result.clips.filter(clip=>{const id=key(clip.path);if(seen.has(id))return false;seen.add(id);return true;})})).filter(result=>result.clips.length>0));
}
export class LibraryStore{
 private tasks=new Map<string,string>();private roots=new Map<string,string>();private ignored=new Map<string,string>();private writes=Promise.resolve();
 constructor(private file:string){}
 async load(){try{const state=JSON.parse((await fs.readFile(this.file,'utf8')).replace(/^\uFEFF/,''));if(state.version!==1)return;for(const task of state.tasks||[])if(typeof task==='string'&&path.isAbsolute(task))this.tasks.set(key(task),task);for(const root of state.roots||[])if(typeof root==='string'&&path.isAbsolute(root))this.roots.set(key(root),root);for(const task of state.ignoredTasks||[])if(typeof task==='string'&&path.isAbsolute(task))this.ignored.set(key(task),task);}catch{}}
 isIgnored(task:string){return this.ignored.has(key(task));}
 async ignore(tasks:string[]){for(const task of tasks)this.ignored.set(key(task),path.resolve(task));await this.save();}
 async remember(task:string,explicit=false){if(explicit)this.ignored.delete(key(task));this.tasks.set(key(task),path.resolve(task));this.roots.set(key(path.dirname(path.dirname(task))),path.dirname(path.dirname(task)));await this.save();}
 async addRoot(root:string){this.roots.set(key(root),path.resolve(root));await this.save();}
 async discover(extraRoots:string[]){return (await discoverTasks([...this.roots.values(),...extraRoots],[...this.tasks.values()])).filter(task=>!this.isIgnored(task));}
 async recoverLastTask<T extends {path:string;finished:boolean}>(extraRoots:string[],pointer:string,readTask:(file:string)=>Promise<T>){
  const candidates:{info:T;time:number}[]=[];
  for(const file of await this.discover(extraRoots))try{const info=await readTask(file);const stat=await fs.stat(file);candidates.push({info,time:stat.mtimeMs});}catch{}
  candidates.sort((a,b)=>Number(a.info.finished)-Number(b.info.finished)||b.time-a.time);
  const selected=candidates[0]?.info;if(!selected)return null;
  await fs.mkdir(path.dirname(pointer),{recursive:true});const temporary=pointer+'.'+randomUUID()+'.tmp';try{await fs.writeFile(temporary,JSON.stringify({task:selected.path,finished:selected.finished}),'utf8');await fs.rename(temporary,pointer);}finally{await fs.unlink(temporary).catch(()=>{});}
  return selected;
 }
 private save(){const body=JSON.stringify({version:1,tasks:[...this.tasks.values()],roots:[...this.roots.values()],ignoredTasks:[...this.ignored.values()]});this.writes=this.writes.catch(()=>{}).then(async()=>{await fs.mkdir(path.dirname(this.file),{recursive:true});await fs.writeFile(this.file+'.tmp',body,'utf8');await fs.rename(this.file+'.tmp',this.file);});return this.writes;}
}
