import fs from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import type {InstallerAsset} from '../src/shared';

export function installationPaths(executable:string){
 const desktop=path.dirname(executable),project=path.dirname(desktop);
 const target=path.basename(desktop)==='desktop'&&path.basename(project)==='resources'?path.dirname(project):project;
 return{target,project,helper:path.join(project,'scripts/update-install.ps1')};
}
export async function pruneLegacyLauncher(target:string){
 const folder=path.join(target,'app'),legacy=path.join(folder,'Apex Highlight Clipper.exe'),launcher=path.join(target,'Apex Highlight Clipper.exe');
 const stat=await fs.lstat(folder).catch(()=>null);if(!stat?.isDirectory()||stat.isSymbolicLink())return;
 const entries=await fs.readdir(folder);if(entries.length!==1||entries[0]!=='Apex Highlight Clipper.exe')return;
 for(const file of [legacy,launcher]){const stat=await fs.lstat(file).catch(()=>null);if(!stat?.isFile()||stat.isSymbolicLink())return;}
 if(await digest(legacy)!==await digest(launcher))return;
 await fs.unlink(legacy);await fs.rmdir(folder);
}

const pattern=/^Apex-Clipper-\d+\.\d+\.\d+-Setup-x64\.exe(?:\.part)?$/;
async function digest(file:string){const hash=createHash('sha256');for await(const chunk of createReadStream(file))hash.update(chunk);return hash.digest('hex');}
export async function pruneUpdates(root:string,protectedName=''){
 const entries=await fs.readdir(root).catch(()=>[]),files=[];
 for(const name of entries)if(pattern.test(name)&&name!==protectedName){const file=path.join(root,name),stat=await fs.lstat(file).catch(()=>null);if(stat?.isFile()&&!stat.isSymbolicLink())files.push({file,name,time:stat.mtimeMs});}
 files.sort((a,b)=>b.time-a.time);
 for(const [i,file]of files.entries())if(file.name.endsWith('.part')?Date.now()-file.time>86400000:i>=2||Date.now()-file.time>7*86400000)await fs.unlink(file.file).catch(()=>{});
}
export async function downloadInstaller(asset:InstallerAsset,root:string,fetcher:(url:string,init:RequestInit)=>Promise<Response>,onProgress:(percent:number)=>void,signal?:AbortSignal,mirror=''){
 if(!pattern.test(asset.name)||asset.name!==`Apex-Clipper-${asset.version}-Setup-x64.exe`||!/^\d+\.\d+\.\d+$/.test(asset.version)||! /^[a-f0-9]{64}$/.test(asset.sha256)||!Number.isSafeInteger(asset.bytes)||asset.bytes<=0||asset.bytes>1024**3||asset.url!==`https://github.com/LilycleHeart/apex-highlight-clipper/releases/download/v${asset.version}/${asset.name}`)throw new Error('安装包信息无效，请重新检查更新');
 await fs.mkdir(root,{recursive:true});
 const lockFile=path.join(root,'download.lock'),token=randomUUID();
 const acquire=async()=>{const lock=await fs.open(lockFile,'wx');try{await lock.writeFile(JSON.stringify({pid:process.pid,token}));}finally{await lock.close();}};
 try{await acquire();}catch(error){
  if((error as NodeJS.ErrnoException).code!=='EEXIST')throw error;
  const previous=await fs.readFile(lockFile,'utf8').then(raw=>{try{return JSON.parse(raw);}catch{return{};}}).catch(()=>({}));let alive=true;
  if(Number.isInteger(previous.pid)&&previous.pid>0)try{process.kill(previous.pid,0);}catch(e){alive=(e as NodeJS.ErrnoException).code!=='ESRCH';}
  else{const stat=await fs.lstat(lockFile);if(!stat.isFile()||stat.isSymbolicLink())throw new Error('更新缓存锁无效');alive=Date.now()-stat.mtimeMs<120000;}
  if(alive)throw new Error('另一个程序窗口正在下载更新，请稍后再试');
  await fs.unlink(lockFile);await acquire();
 }
 try{
 await pruneUpdates(root,asset.name);
 const target=path.join(root,asset.name),partial=target+'.part';
 const existing=await fs.lstat(target).catch(()=>null);
 if(existing){if(!existing.isFile()||existing.isSymbolicLink())throw new Error('更新缓存路径无效');if(existing.size===asset.bytes&&await digest(target)===asset.sha256){onProgress(100);return target;}await fs.unlink(target);}
 await fs.unlink(partial).catch(()=>{});
 let file:Awaited<ReturnType<typeof fs.open>>|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
 try{
  const response=await fetcher(mirror?mirror+asset.url:asset.url,{signal});if(!response.ok||!response.body)throw new Error('无法下载安装包，请稍后重试');
  reader=response.body.getReader();file=await fs.open(partial,'wx');const hash=createHash('sha256');let bytes=0,last=-1;
  while(true){const result=await reader.read();if(result.done)break;signal?.throwIfAborted();bytes+=result.value.byteLength;if(bytes>asset.bytes)throw new Error('安装包大小不匹配');hash.update(result.value);await file.writeFile(result.value);const percent=Math.floor(bytes/asset.bytes*100);if(percent!==last){last=percent;onProgress(percent);}}
  await file.close();file=undefined;if(bytes!==asset.bytes||hash.digest('hex')!==asset.sha256)throw new Error('安装包校验失败，请重新下载');await fs.rename(partial,target);return target;
 }catch(error){await reader?.cancel().catch(()=>{});await file?.close().catch(()=>{});await fs.unlink(partial).catch(()=>{});throw error;}
 }finally{const owner=await fs.readFile(lockFile,'utf8').then(raw=>{try{return JSON.parse(raw);}catch{return{};}}).catch(()=>({}));if(owner.token===token)await fs.unlink(lockFile).catch(()=>{});}
}
