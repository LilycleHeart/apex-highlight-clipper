import path from 'node:path';
import fs from 'node:fs/promises';
import {isDeepStrictEqual} from 'node:util';
const key=(value:string)=>path.resolve(value).toLowerCase();
export function inside(child:string,parent:string){const relative=path.relative(path.resolve(parent),path.resolve(child));return relative===''||(!relative.startsWith('..'+path.sep)&&relative!=='..'&&!path.isAbsolute(relative));}
/** Old tasks keep their original directory contract. New tasks split metadata from videos. */
export function validateTaskStorage(task:any,file:string){
 if(![1,2].includes(task?.version)||typeof task.directory!=='string'||key(task.directory)!==key(path.dirname(file))||!Array.isArray(task.items))throw new Error('任务记录格式不正确');
 if(task.version===2){
  if(typeof task.data_root!=='string'||!path.isAbsolute(task.data_root)||key(path.dirname(task.directory))!==key(path.join(task.data_root,'tasks')))throw new Error('任务数据目录无效');
  if(typeof task.request?.output!=='string'||!path.isAbsolute(task.request.output)||typeof task.video_directory!=='string'||!inside(task.video_directory,task.request.output))throw new Error('视频输出目录无效');
 }
 for(const item of task.items){
  if(typeof item.source!=='string'||!path.isAbsolute(item.source)||typeof item.destination!=='string'||!path.isAbsolute(item.destination)||key(item.destination)===key(task.directory)||!inside(item.destination,task.directory))throw new Error('任务分析目录无效');
  if(task.version===2&&(typeof item.video_directory!=='string'||key(item.video_directory)!==key(task.video_directory)||inside(item.destination,item.video_directory)||inside(item.video_directory,item.destination)||!/^[a-f0-9]{8}-\d+$/.test(item.export_suffix)))throw new Error('任务视频目录无效');
 }
}
export function videoDirectory(task:any,item:any){return task.version===2?item.video_directory:item.destination;}
export function isRecordedVideo(task:any,item:any,file:unknown){
 if(typeof file!=='string'||!path.isAbsolute(file))return false;
 const directory=videoDirectory(task,item);
 if(task.version===2&&key(path.dirname(file))!==key(directory))return false;
 return inside(file,directory)&&Array.isArray(item.record?.outputs)&&item.record.outputs.some((p:unknown)=>typeof p==='string'&&key(p)===key(file));
}
/** Only explicit, matching task caches can grant access to samples from a previous install. */
export async function recordedSampleDirectories(task:any,liveSample?:string){
 const roots=new Set<string>(),read=async(file:string)=>JSON.parse((await fs.readFile(file,'utf8')).replace(/^\uFEFF/,''));
 for(const item of task.items){
  for(const raw of [item.analysis_cache,item.record?.analysis_cache])try{
   if(typeof raw!=='string'||!path.isAbsolute(raw)||!/^[a-f0-9]{16}$/.test(path.basename(raw))||path.basename(path.dirname(raw))!=='app-cache'||path.basename(path.dirname(path.dirname(raw)))!=='validation')continue;
   const cache=await fs.realpath(raw),use=await read(path.join(cache,'.cache-use.json')),hud=await read(path.join(cache,'hud.json'));
   if(key(use.task)!==key(path.join(task.directory,'task.json'))||key(use.source)!==key(item.source)||!isDeepStrictEqual(hud.source,item.source_identity)||!isDeepStrictEqual(hud.profile,item.hud_profile||task.profile)||hud.fps!==(task.request.fps??2))continue;
   const reference=await read(path.join(cache,'sample-reference.json')).catch(()=>null);
   for(const sample of [item.sample_directory,item.record?.sample_directory,reference?.samples,liveSample]){
    if(typeof sample!=='string'||!path.isAbsolute(sample)||!/^samples(?:-[a-f0-9]+)?$/.test(path.basename(sample)))continue;
    const real=await fs.realpath(sample).catch(()=>null);if(real&&inside(real,cache))roots.add(real);
   }
  }catch{}
 }
 return [...roots];
}
