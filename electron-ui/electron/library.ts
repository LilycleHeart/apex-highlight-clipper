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
const skippedDirectories=new Set(['validation','node_modules','runtime','.git','$recycle.bin','system volume information','windows','program files','program files (x86)','programdata','appdata']);
export const libraryVideoExtensions=new Set(['.mp4','.mkv','.mov','.ts','.m4v']);
export interface LibraryVideo {path:string;size:number;mtimeMs:number}
export interface LibraryScan {tasks:string[];videos:LibraryVideo[];truncated:boolean}
/** 遍历输出目录与用户添加的目录，不限层级；跳过系统/缓存目录与链接，限制总量避免误选整盘时卡住。 */
export async function scanLibraryRoots(roots:string[],limit=200000):Promise<LibraryScan>{
 const tasks=new Map<string,string>(),files:string[]=[],visited=new Set<string>();let seen=0,truncated=false;
 const pending=[...new Set(roots.filter(value=>typeof value==='string'&&path.isAbsolute(value)).map(value=>path.resolve(value)))];
 while(pending.length){
  const dir=pending.pop()!;if(visited.has(key(dir)))continue;visited.add(key(dir));
  let entries;try{entries=await fs.readdir(dir,{withFileTypes:true});}catch{continue;}
  for(const entry of entries){
   if(++seen>limit){truncated=true;break;}
   const full=path.join(dir,entry.name);
   if(entry.isSymbolicLink())continue;
   if(entry.isDirectory()){if(!entry.name.startsWith('.')&&!skippedDirectories.has(entry.name.toLowerCase()))pending.push(full);}
   else if(entry.isFile()){if(entry.name==='task.json')tasks.set(key(full),full);else if(libraryVideoExtensions.has(path.extname(entry.name).toLowerCase()))files.push(full);}
  }
  if(truncated)break;
 }
 const videos:LibraryVideo[]=[];
 for(let i=0;i<files.length;i+=64)await Promise.all(files.slice(i,i+64).map(async file=>{try{const stat=await fs.stat(file);if(stat.isFile())videos.push({path:file,size:stat.size,mtimeMs:stat.mtimeMs});}catch{}}));
 return {tasks:[...tasks.values()],videos,truncated};
}
export interface MissingClip {recorded:string;size:number;mtimeMs?:number;duration?:number;task?:string;manifest?:string}
export interface ProposedMove {from:string;to:string;size:number;basis:'size_mtime'|'size_name'|'size_unique';duration?:number;task?:string;manifest?:string}
/** 记录中的成片找不到时，从现有视频里认领同一文件：大小相同且修改时间相近，或大小与文件名都相同，或该大小唯一（再由时长复核）。只接受一对一结果。 */
export function matchMovedClips(missing:MissingClip[],candidates:LibraryVideo[]):ProposedMove[]{
 const bySize=new Map<number,LibraryVideo[]>();for(const video of candidates){const list=bySize.get(video.size);if(list)list.push(video);else bySize.set(video.size,[video]);}
 const missingBySize=new Map<number,number>();for(const item of missing)missingBySize.set(item.size,(missingBySize.get(item.size)||0)+1);
 const name=(file:string)=>path.basename(file).toLowerCase();
 const options=missing.map(item=>{
  const same=(bySize.get(item.size)||[]).filter(video=>key(video.path)!==key(item.recorded));
  const timed=item.mtimeMs===undefined?[]:same.filter(video=>Math.abs(video.mtimeMs-item.mtimeMs!)<=2000);
  if(timed.length)return {item,choices:timed,basis:'size_mtime' as const};
  const named=same.filter(video=>name(video.path)===name(item.recorded));
  if(named.length)return {item,choices:named,basis:'size_name' as const};
  if(same.length===1&&missingBySize.get(item.size)===1&&Number.isFinite(item.duration))return {item,choices:same,basis:'size_unique' as const};
  return {item,choices:[] as LibraryVideo[],basis:'size_unique' as const};
 });
 const claims=new Map<string,number>();for(const option of options)for(const video of option.choices)claims.set(key(video.path),(claims.get(key(video.path))||0)+1);
 return options.filter(option=>option.choices.length===1&&claims.get(key(option.choices[0].path))===1).map(({item,choices:[video],basis})=>({from:item.recorded,to:video.path,size:item.size,basis,...(basis==='size_unique'?{duration:item.duration}:{}),...(item.task?{task:item.task}:{}),...(item.manifest?{manifest:item.manifest}:{})}));
}
export function mergeLibrary(results:Result[]){
 const seen=new Set<string>();return normalizeLibraryNames(results.map(result=>({...result,clips:result.clips.filter(clip=>{const id=key(clip.path);if(seen.has(id))return false;seen.add(id);return true;})})).filter(result=>result.clips.length>0));
}
export class LibraryStore{
 private tasks=new Map<string,string>();private roots=new Map<string,string>();private ignored=new Map<string,string>();private hiddenClips=new Map<string,string>();private writes=Promise.resolve();
 constructor(private file:string){}
 async load(){try{const state=JSON.parse((await fs.readFile(this.file,'utf8')).replace(/^\uFEFF/,''));if(state.version!==1)return;for(const task of state.tasks||[])if(typeof task==='string'&&path.isAbsolute(task))this.tasks.set(key(task),task);for(const root of state.roots||[])if(typeof root==='string'&&path.isAbsolute(root))this.roots.set(key(root),root);for(const task of state.ignoredTasks||[])if(typeof task==='string'&&path.isAbsolute(task))this.ignored.set(key(task),task);for(const file of state.hiddenClips||[])if(typeof file==='string'&&path.isAbsolute(file))this.hiddenClips.set(key(file),file);}catch{}}
 /** 用户从片段库移除的已有片段：文件保留，重新扫描时不再自动加入；手动再次添加会恢复。 */
 isHidden(file:string){return this.hiddenClips.has(key(file));}
 async hide(files:string[]){for(const file of files)this.hiddenClips.set(key(file),path.resolve(file));await this.save();}
 async unhide(files:string[]){let changed=false;for(const file of files)changed=this.hiddenClips.delete(key(file))||changed;if(changed)await this.save();}
 rootList(){return [...this.roots.values()];}
 taskList(){return [...this.tasks.values()];}
 isIgnored(task:string){return this.ignored.has(key(task));}
 async ignore(tasks:string[]){for(const task of tasks)this.ignored.set(key(task),path.resolve(task));await this.save();}
 async remember(task:string,explicit=false){if(explicit)this.ignored.delete(key(task));this.tasks.set(key(task),path.resolve(task));this.roots.set(key(path.dirname(path.dirname(task))),path.dirname(path.dirname(task)));await this.save();}
 /** 扫描发现的任务批量登记，只在有新增时写一次。 */
 async rememberMany(tasks:string[]){let changed=false;for(const task of tasks)if(!this.tasks.has(key(task))){this.tasks.set(key(task),path.resolve(task));this.roots.set(key(path.dirname(path.dirname(task))),path.dirname(path.dirname(task)));changed=true;}if(changed)await this.save();}
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
 private save(){const body=JSON.stringify({version:1,tasks:[...this.tasks.values()],roots:[...this.roots.values()],ignoredTasks:[...this.ignored.values()],hiddenClips:[...this.hiddenClips.values()]});this.writes=this.writes.catch(()=>{}).then(async()=>{await fs.mkdir(path.dirname(this.file),{recursive:true});await fs.writeFile(this.file+'.tmp',body,'utf8');await fs.rename(this.file+'.tmp',this.file);});return this.writes;}
}
