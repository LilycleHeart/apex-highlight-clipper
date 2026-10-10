import fs from 'node:fs/promises';
import path from 'node:path';
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
 const seen=new Set<string>();return results.map(result=>({...result,clips:result.clips.filter(clip=>{const id=key(clip.path);if(seen.has(id))return false;seen.add(id);return true;})})).filter(result=>result.clips.length>0);
}
export class LibraryStore{
 private tasks=new Map<string,string>();private roots=new Map<string,string>();private writes=Promise.resolve();
 constructor(private file:string){}
 async load(){try{const state=JSON.parse((await fs.readFile(this.file,'utf8')).replace(/^\uFEFF/,''));if(state.version!==1)return;for(const task of state.tasks||[])if(typeof task==='string'&&path.isAbsolute(task))this.tasks.set(key(task),task);for(const root of state.roots||[])if(typeof root==='string'&&path.isAbsolute(root))this.roots.set(key(root),root);}catch{}}
 async remember(task:string){this.tasks.set(key(task),path.resolve(task));this.roots.set(key(path.dirname(path.dirname(task))),path.dirname(path.dirname(task)));await this.save();}
 async addRoot(root:string){this.roots.set(key(root),path.resolve(root));await this.save();}
 async discover(extraRoots:string[]){return discoverTasks([...this.roots.values(),...extraRoots],[...this.tasks.values()]);}
 private save(){const body=JSON.stringify({version:1,tasks:[...this.tasks.values()],roots:[...this.roots.values()]});this.writes=this.writes.catch(()=>{}).then(async()=>{await fs.mkdir(path.dirname(this.file),{recursive:true});await fs.writeFile(this.file+'.tmp',body,'utf8');await fs.rename(this.file+'.tmp',this.file);});return this.writes;}
}
