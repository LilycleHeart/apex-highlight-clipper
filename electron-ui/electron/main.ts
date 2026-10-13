import {app,BrowserWindow,dialog,ipcMain,nativeTheme,systemPreferences,protocol,shell,net} from 'electron';
import {spawn,ChildProcess} from 'node:child_process';
import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import path from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import os from 'node:os';
import {Diagnostics} from './diagnostics';
import {JsonLines,safeOptions,videoExtensions} from './protocol';
import {defaults,Options,ThemePreferences,WorkerEvent,TaskInfo,Result,FileItem,SystemTheme,UpdateInfo} from '../src/shared';
import {normalizePlayerAudio,defaultPlayerAudio,type PlayerAudioPreferences} from '../src/audioPreferences';
import {clipStatistics,recordingTime} from '../src/clipStats';
import {UpdateChecker,shouldAutoCheck,releasePage,restoreUpdateInfo} from './updates';
import {downloadInstaller,pruneUpdates} from './updateInstaller';
import {VideoRegistry} from './media';
import {ClipDeletions} from './clipDeletions';
import {ProcessingTimes,historicProcessingSeconds} from './processingTimes';
import {LibraryStore,mergeLibrary} from './library';
import {validateTaskStorage,videoDirectory,isRecordedVideo,recordedSampleDirectories} from './taskStorage';
import {mediaGeometry} from '../src/mediaGeometry';
import {ThumbnailStore} from './thumbnails';

protocol.registerSchemesAsPrivileged([{scheme:'apex-media',privileges:{standard:true,secure:true,supportFetchAPI:true,stream:true}}]);
app.commandLine.appendSwitch('disk-cache-size',String(64*1024*1024));
if(process.env.APEX_UI_TEST_HOME)app.setPath('userData',process.env.APEX_UI_TEST_HOME);
else {const legacy=path.join(app.getPath('appData'),'Apex交战剪辑');if(existsSync(path.join(legacy,'preferences.json')))app.setPath('userData',legacy);}
const diagnostics=new Diagnostics(path.join(app.getPath('userData'),'logs'),{home:os.homedir(),data:app.getPath('userData')});
process.on('uncaughtExceptionMonitor',error=>diagnostics.fatal(error));
diagnostics.log('info','startup','程序启动',{version:app.getVersion(),packaged:app.isPackaged,platform:process.platform,arch:process.arch,versions:process.versions});
function locateProject(){if(process.env.APEX_PROJECT_ROOT)return path.resolve(process.env.APEX_PROJECT_ROOT);for(const base of [__dirname,app.getAppPath(),path.dirname(app.getPath('exe'))]){let dir=base;for(let i=0;i<8;i++){if(existsSync(path.join(dir,'app_worker.py')))return dir;const next=path.dirname(dir);if(next===dir)break;dir=next;}}throw new Error('未找到剪辑内核。请将程序保留在项目目录内，或设置 APEX_PROJECT_ROOT。');}
const project=locateProject();
diagnostics.alias(project,'<app>');
const dataRoot=path.resolve(process.env.APEX_DATA_ROOT||app.getPath('userData'));
const validationRoot=path.join(dataRoot,'validation');
const legacyValidationRoot=path.join(project,'validation');
process.env.APEX_DATA_ROOT=dataRoot;
process.env.APEX_CLIP_DELETIONS=path.join(app.getPath('userData'),'clip-deletions.json');
const libraryStore=new LibraryStore(path.join(app.getPath('userData'),'library.json'));
const thumbnails=new ThumbnailStore(path.join(app.getPath('userData'),'thumbnails'),()=>{
 const shared=process.env.LOCALAPPDATA&&path.join(process.env.LOCALAPPDATA,'Apex Highlight Clipper','dependencies','ffmpeg','9.0.2');
 for(const folder of [process.env.APEX_FFMPEG_DIR,shared,path.join(project,'tools'),...(process.env.PATH||'').split(path.delimiter)])if(folder&&existsSync(path.join(folder,'ffmpeg.exe'))&&existsSync(path.join(folder,'ffprobe.exe')))return path.join(folder,'ffmpeg.exe');
 throw new Error('请先通过 Start.cmd 启动以准备视频工具');
});
const clipDurations=new Map<string,number>();const clipDirectories=new Map<string,string>();
const clipTasks=new Map<string,string>();const originalVideos=new Set<string>();
let hudWorker:ChildProcess|null=null;let hudLaunching=false;
function pythonFor(backend:'cpu'|'dml'='cpu'){const bundled=path.join(project,'runtime',backend,'python.exe');return existsSync(bundled)?bundled:path.join(project,backend==='dml'?'.gpu-venv/Scripts/python.exe':'.venv/Scripts/python.exe');}
const development=!app.isPackaged||process.argv.includes('--preview');
let win:BrowserWindow;let worker:ChildProcess|null=null;let launching=false;let stopFile='';let stopRequested=false;let closing=false;let terminal=false;let currentTask='';let currentSource='';let eventChain=Promise.resolve();
let updating=false;let updateAbort:AbortController|null=null;
const processingTimes=new ProcessingTimes(path.join(dataRoot,'processing-times.json'),(source,seconds)=>send({type:'file-timing',source,processing_seconds:seconds}),error=>diagnostics.log('error','processing-time',String(error)));
const updateRoot=path.join(app.getPath('userData'),'updates');
let workerExit:Promise<void>=Promise.resolve();let resolveWorkerExit:(()=>void)|null=null;let closeSaveFinished=false;
let playerAudio:PlayerAudioPreferences={...defaultPlayerAudio};
let preferences:ThemePreferences={mode:'system',seed:null,reduceMotion:false,mascotStyle:'flat',mascotEnabled:false};let options:Options={...defaults};let output=path.join(project,'output');
let updateInfo:UpdateInfo={status:'idle',currentVersion:app.getVersion(),autoCheck:true};let updateTimer:ReturnType<typeof setTimeout>|null=null;
function publishUpdate(info:UpdateInfo){diagnostics.log(info.status==='error'?'error':'info','update',info.status,{currentVersion:info.currentVersion,latestVersion:info.latestVersion,message:info.message});updateInfo=info;if(info.status!=='checking')void save().catch(error=>diagnostics.log('error','preferences',String(error)));if(win&&!win.isDestroyed())win.webContents.send('update-status',info);}
const updater=new UpdateChecker(app.getVersion(),(url,init)=>net.fetch(url,init),()=>updateInfo,publishUpdate);
function scheduleUpdate(){if(updateTimer)clearTimeout(updateTimer);updateTimer=setTimeout(()=>{updateTimer=null;if(shouldAutoCheck(updateInfo))void updater.check().catch(()=>{});},3000);updateTimer.unref();}
const taskSampleRoots=new Set<string>();
const allowedPaths=new Set<string>();const allowedTasks=new Set<string>();const images=new Map<string,string>();const imageKeys=new Map<string,string>();
const allowedClips=new Set<string>();const videos=new VideoRegistry(file=>allowedClips.has(normalized(file)));
const clipDeletions=new ClipDeletions(process.env.APEX_CLIP_DELETIONS!,async file=>{
 if(worker||launching||hudWorker||hudLaunching||updating)throw new Error('请先停止当前处理任务，再回收片段');
 const taskFile=clipTasks.get(normalized(file));if(!allowedClips.has(normalized(file))||!taskFile||originalVideos.has(normalized(file)))throw new Error('只允许回收片段库中的成片，原录像保留');
 const task=await readJson(taskFile);validateTaskStorage(task,taskFile);if(task.items.some((item:any)=>normalized(item.source)===normalized(file)))throw new Error('原录像不能从片段库回收');const item=task.items.find((item:any)=>isRecordedVideo(task,item,file));if(!item)throw new Error('片段不属于已登记的导出任务');
 const manifest=await readJson(path.join(item.destination,'export.json'));if(!manifest.clips?.some((clip:any)=>typeof clip.output==='string'&&normalized(clip.output)===normalized(file)))throw new Error('未找到此片段的导出记录');
 if(existsSync(file)){
  const stat=await fs.lstat(file),real=await fs.realpath(file),directory=await fs.realpath(videoDirectory(task,item));if(!stat.isFile()||stat.isSymbolicLink()||!within(real,directory))throw new Error('成片路径无效');
  if(originalVideos.has(normalized(real)))throw new Error('原录像不能从片段库回收');for(const source of new Set<string>(task.items.map((item:any)=>item.source))){const original=await fs.realpath(source).catch(()=>null);if(original&&normalized(original)===normalized(real))throw new Error('此文件正在作为原录像使用，不能从片段库回收');}
 }
},file=>videos.release(file),file=>shell.trashItem(file));
const normalized=(p:string)=>path.resolve(p).toLowerCase();
const within=(child:string,parent:string)=>{const relative=path.relative(parent,child);return relative===''||(!relative.startsWith('..'+path.sep)&&relative!=='..'&&!path.isAbsolute(relative));};
const readJson=async(p:string)=>JSON.parse((await fs.readFile(p,'utf8')).replace(/^\uFEFF/,''));
async function pruneRequests(){
 const root=path.join(validationRoot,'app-requests');
 for(const item of await fs.readdir(root,{withFileTypes:true}).catch(()=>[])){
  if(!item.isFile()||! /^[a-f0-9-]{36}(?:-counter-repair)?\.(?:json|stop)$/.test(item.name))continue;
  const file=path.join(root,item.name),stat=await fs.lstat(file).catch(()=>null);
  if(stat?.isFile()&&Date.now()-stat.mtimeMs>7*86400000)await fs.unlink(file).catch(()=>{});
 }
}
let loggedStage='',loggedProgress=-1;
function send(e:WorkerEvent){if(e.source)diagnostics.alias(e.source,'<video>');const progress=Math.floor((e.progress||0)/10);if(['run','file','stage','done','stopped','fatal','error','exit','log','stderr','close-request','hud-info-start','hud-info-file','hud-info-error','hud-info-done'].includes(e.type)||(e.type==='progress'&&(e.stage!==loggedStage||progress!==loggedProgress))){loggedStage=e.stage||loggedStage;loggedProgress=progress;diagnostics.log(['fatal','error','stderr','hud-info-error'].includes(e.type)?'error':'info','worker',e.message||e.type,{type:e.type,stage:e.stage,progress:e.progress,index:e.index,total:e.total,failures:e.failures,clips:e.clips});}if(win&&!win.isDestroyed())win.webContents.send('worker-event',e);}
function theme():SystemTheme{let accent='#526b4a';let reduceMotion=false;try{const color=systemPreferences.getAccentColor();if(/^[\da-f]{8}$/i.test(color))accent='#'+color.slice(0,6);}catch{}try{reduceMotion=systemPreferences.getAnimationSettings().prefersReducedMotion;}catch{}return{accent,dark:nativeTheme.shouldUseDarkColors,reduceMotion};}
let saveChain=Promise.resolve();
async function flushSaves(){let pending:Promise<void>;do{pending=saveChain;await pending.catch(()=>{});}while(pending!==saveChain);await diagnostics.flush();}
let maintenance:ChildProcess|null=null;let maintenanceExit:Promise<void>=Promise.resolve();let maintenanceTimer:ReturnType<typeof setTimeout>|null=null;
function scheduleMaintenance(force=false){
 if(process.env.APEX_UI_TEST_HOME||process.env.APEX_UI_VALIDATE||maintenanceTimer||maintenance)return;
 maintenanceTimer=setTimeout(async()=>{
  maintenanceTimer=null;if(worker||launching||closing||hudWorker||hudLaunching)return;
  const completed=await fs.stat(path.join(validationRoot,'.maintenance.json')).catch(()=>null);
  const previous=await readJson(path.join(validationRoot,'.maintenance.json')).catch(()=>null);
  const cacheCount=(await fs.readdir(path.join(validationRoot,'app-cache'),{withFileTypes:true}).catch(()=>[])).filter(item=>item.isDirectory()).length;
  const retained=Math.max(3,Number(previous?.cache_count)||3);
  if(!force&&completed&&Date.now()-completed.mtimeMs<86400000&&cacheCount<=retained)return;
  if(worker||launching||closing||hudWorker||hudLaunching)return;
  const script=path.join(project,'scripts/cleanup-validation.ps1');if(!existsSync(script))return;
  const proc=spawn(path.join(process.env.SystemRoot||'C:/Windows','System32/WindowsPowerShell/v1.0/powershell.exe'),['-NoProfile','-ExecutionPolicy','Bypass','-File',script,'-Apply','-OutputRoot',output,'-UserData',app.getPath('userData'),'-DataRoot',dataRoot],{windowsHide:true});
  maintenance=proc;let result='';proc.stdout?.setEncoding('utf8');proc.stdout?.on('data',data=>result=(result+data).slice(-2000));proc.stderr?.resume();
  maintenanceExit=new Promise<void>(resolve=>{const finish=()=>{if(maintenance===proc)maintenance=null;resolve();};proc.once('error',finish);proc.once('close',code=>{if(code===0&&result.includes('"Bytes"'))send({type:'log',message:'缓存维护已完成'});finish();});});
 },10000);maintenanceTimer.unref();
}
async function save(){const snapshot=JSON.stringify({preferences,options,playerAudio,optionDefaultsVersion:2,output,updatePreferences:{autoCheck:updateInfo.autoCheck},updateCache:updateInfo.status==='checking'?undefined:updateInfo});saveChain=saveChain.catch(()=>{}).then(async()=>{await fs.mkdir(app.getPath('userData'),{recursive:true});const target=path.join(app.getPath('userData'),'preferences.json');await fs.writeFile(target+'.tmp',snapshot,'utf8');await fs.rename(target+'.tmp',target);});return saveChain;}
async function imageUrl(p:string){
 const real=await fs.realpath(p);if(!['.jpg','.jpeg','.png'].includes(path.extname(real).toLowerCase()))throw new Error('预览格式无效');
 const roots=await Promise.all([validationRoot,legacyValidationRoot,thumbnails.directory,...taskSampleRoots].map(p=>fs.realpath(p).catch(()=>'')));if(!roots.some(root=>root&&within(real,root)))throw new Error('预览路径不属于画面缓存');
 let key=imageKeys.get(real);if(!key){key=randomUUID();images.set(key,real);imageKeys.set(real,key);if(images.size>6000){const oldest=images.keys().next().value!;imageKeys.delete(images.get(oldest)!);images.delete(oldest);}}
 return `apex-media://image/${key}`;
}
async function taskInfo(p:string):Promise<TaskInfo>{const task=await readJson(p);validateTaskStorage(task,p);const historic={...task,items:task.items.filter((item:any)=>[item.analysis_cache,item.record?.analysis_cache].some(raw=>typeof raw==='string'&&path.isAbsolute(raw)&&![validationRoot,legacyValidationRoot].some(root=>within(path.resolve(raw),root))&&![...taskSampleRoots].some(root=>within(root,path.resolve(raw)))))};for(const root of await recordedSampleDirectories(historic))taskSampleRoots.add(root);allowedTasks.add(normalized(p));allowedPaths.add(normalized(task.directory));for(const item of task.items){allowedPaths.add(normalized(item.source));originalVideos.add(normalized(item.source));diagnostics.alias(item.source,'<video>');diagnostics.alias(path.basename(item.source),'<video>');}return{path:p,directory:task.directory,output:task.request.output||path.dirname(task.directory),finished:task.finished,legacyRule:!task.result_filter_version,samplingWarning:task.request.fps<1?'旧任务低采样率可能漏掉交战；新建任务建议至少1帧/秒':'',options:safeOptions({...defaults,...task.request},true),items:task.items.map((i:any)=>({id:normalized(i.source),path:i.source,name:path.basename(i.source),status:i.status==='error'?'error':i.status==='complete'?'complete':i.status==='running'?'stopped':'pending',missing:!existsSync(i.source),processingSeconds:processingTimes.seconds(p,i.source,historicProcessingSeconds(i)),error:i.record?.error}))};}
async function lastTask(){for(const root of [validationRoot,legacyValidationRoot])try{const record=await readJson(path.join(root,'app-last-task.json'));if(!libraryStore.isIgnored(record.task))return await taskInfo(record.task);}catch{}return libraryStore.recoverLastTask([output,path.join(dataRoot,'tasks')],path.join(validationRoot,'app-last-task.json'),taskInfo);}
const repairedCounters=new Set<string>();let counterRepair:Promise<void>|null=null;let repairWorker:ChildProcess|null=null;
async function repairLegacyCounters(task:any){
 if(counterRepair){await counterRepair;}const records:any[]=[];
 for(const item of task.items){const record=item.record;if(!record||record.status!=='complete'||repairedCounters.has(normalized(item.destination))||normalized(record.directory)!==normalized(item.destination)||!within(path.resolve(item.destination),path.resolve(task.directory)))continue;
  if(typeof record.analysis_cache!=='string'||typeof record.sample_directory!=='string'||(![validationRoot,legacyValidationRoot].some(root=>within(path.resolve(record.analysis_cache),root))&&![...taskSampleRoots].some(root=>within(root,path.resolve(record.analysis_cache))))||![validationRoot,legacyValidationRoot,...taskSampleRoots].some(root=>within(path.resolve(record.sample_directory),root)))continue;
  try{const stats=await readJson(path.join(item.destination,'statistics.json'));if(stats.version!=='combat-statistics-v7'&&stats.segments?.some((s:any)=>['kills','assists','damage'].some(k=>s.counts[k]===null)))records.push(record);}catch{}
 }
 if(!records.length)return;
 counterRepair=(async()=>{const dir=path.join(validationRoot,'app-requests');await fs.mkdir(dir,{recursive:true});const file=path.join(dir,randomUUID()+'-counter-repair.json');await fs.writeFile(file,JSON.stringify(records),'utf8');await new Promise<void>(resolve=>{const proc=spawn(pythonFor(),['repair_cached_statistics.py',file],{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});repairWorker=proc;proc.stdout?.resume();proc.stderr?.resume();const timeout=setTimeout(()=>proc.kill(),60000);proc.on('error',()=>{clearTimeout(timeout);resolve();});proc.on('close',code=>{clearTimeout(timeout);if(repairWorker===proc)repairWorker=null;if(code===0)records.forEach(r=>repairedCounters.add(normalized(r.directory)));resolve();});});await fs.unlink(file).catch(()=>{});})().finally(()=>{counterRepair=null;});await counterRepair;
}
async function collectResults(p:string,repair=true):Promise<Result[]>{
 if(!allowedTasks.has(normalized(p)))throw new Error('请先选择任务');const task=await readJson(p);validateTaskStorage(task,p);const results:Result[]=[];
 if(!updating&&!worker&&!hudWorker&&!hudLaunching&&repair)void repairLegacyCounters(task).then(()=>collectResults(p,false)).then(results=>send({type:'results-refreshed',task_path:p,results})).catch(()=>{});
 for(const item of task.items){const record=item.record;if(!record)continue;
  if(!within(path.resolve(item.destination),path.resolve(task.directory)))throw new Error('成片目录不属于任务');
  if(existsSync(item.destination)&&!within(await fs.realpath(item.destination),await fs.realpath(task.directory)))throw new Error('任务分析目录指向外部位置');
  const result:Result={...record,clips:[]};
  try{const report=await readJson(path.join(item.destination,'quality-filter.json'));result.qualityRejected=report.decisions?.filter((s:any)=>s.status==='rejected');}catch{}
  if(record.outputs?.length&&record.outputs.some((f:string)=>!existsSync(f)&&!clipDeletions.isRemoved(f))){result.status='error';result.error='记录中的成片缺失，请检查输出目录或恢复原片后续接。';}
  try{result.review=await readJson(path.join(item.destination,'review-candidates.json'));}catch{}try{const rejected=await readJson(path.join(item.destination,'rejected-candidates.json'));if(Array.isArray(rejected))result.rejected=rejected.filter(s=>Number.isFinite(s.start)&&Number.isFinite(s.end));}catch{}
  try{const manifest=await readJson(path.join(item.destination,'export.json'));if(manifest.metadata_directory&&normalized(manifest.metadata_directory)!==normalized(item.destination))throw new Error('成片元数据目录不匹配');if(manifest.video_directory&&normalized(manifest.video_directory)!==normalized(videoDirectory(task,item)))throw new Error('成片视频目录不匹配');let corrected:any=null;try{const raw=await fs.readFile(path.join(item.destination,'statistics.json'));const fix=await readJson(path.join(item.destination,'statistics-corrected.json'));if(fix.repair_signature===createHash('sha256').update(raw).update(fix.version).update(fix.counter_recipe||'').digest('hex'))corrected=fix;}catch{}let analysis:any={};let candidates:any[]=[];try{analysis=await readJson(path.join(item.destination,'analysis.json'));candidates=analysis.segments||[];}catch{}let frames:string[]=[];let samples=record.sample_directory;
   if(!samples){for(const root of [validationRoot,legacyValidationRoot]){if(samples)break;try{const dirs=await fs.readdir(path.join(root,'app-cache'));for(const d of dirs){const base=path.join(root,'app-cache',d);try{const hud=await readJson(path.join(base,'hud.json'));if(normalized(hud.source.path)===normalized(item.source)){samples=(await readJson(path.join(base,'sample-reference.json'))).samples;break;}}catch{}}}catch{}}}
   if(samples){try{const real=await fs.realpath(samples);if([validationRoot,legacyValidationRoot,...taskSampleRoots].some(root=>within(real,root)))frames=(await fs.readdir(samples)).filter(f=>/^\d+[.]jpg$/.test(f)).sort();}catch{}}
   for(const c of manifest.clips||[]){if(!isRecordedVideo(task,item,c.output)||!Array.isArray(manifest.outputs)||!manifest.outputs.some((file:unknown)=>typeof file==='string'&&normalized(file)===normalized(c.output)))continue;const target=path.resolve(c.output);if(!videoExtensions.has(path.extname(target).toLowerCase())||!existsSync(target))continue;const realTarget=await fs.realpath(target),realDirectory=await fs.realpath(videoDirectory(task,item));if(!within(realTarget,realDirectory))continue;allowedPaths.add(normalized(target));
    if(corrected){const fix=corrected.segments.find((s:any)=>Math.abs(s.start-c.segment.start)<.001&&Math.abs(s.end-c.segment.end)<.001);if(fix){for(const key of ['kills','assists','damage'])if((c.summary?.[key]===null||c.summary?.statistics_partial?.[key]&&fix.partial[key]===false)&&typeof fix.counts[key]==='number'){c.summary[key]=fix.counts[key];c.summary.statistics_partial={...c.summary.statistics_partial,[key]:fix.partial[key]};}c.summary.statistics_version=corrected.version;c.recognition={...c.recognition,statistics:fix};}}
    allowedClips.add(normalized(target));clipTasks.set(normalized(target),p);clipDirectories.set(normalized(target),item.destination);const start=Number(c.segment.start),end=Number(c.segment.end);clipDurations.set(normalized(target),Number(c.metadata?.format?.duration)||end-start);const rate=record.parameters?.fps||2;const targetTime=(start+end)/2;
    const inside=frames.filter(f=>{const t=(Number(path.parse(f).name)-.5)/rate;return t>=start&&t<=end;});const frame=inside.sort((a,b)=>Math.abs((Number(path.parse(a).name)-.5)/rate-targetTime)-Math.abs((Number(path.parse(b).name)-.5)/rate-targetTime))[0];let thumbnail:string|undefined;
    if(frame)try{thumbnail=await imageUrl(path.join(samples,frame));}catch{}
    result.clips.push({media:mediaGeometry(c.metadata),taskPath:p,source:item.source,exportedAt:(await fs.stat(target)).mtime.toISOString(),path:target,name:path.basename(target),recordedAt:recordingTime(item.source)||recordingTime(path.basename(target)),duration:Number(c.metadata?.format?.duration)||end-start,start,end,...clipStatistics(c,candidates,analysis),thumbnail});
   }
  }catch{}
  allowedPaths.add(normalized(item.destination));results.push(result);
 }
 return results;
}
let libraryRead:Promise<{results:Result[];tasks:number;errors:number}>|null=null;
let unreadableTasks:string[]=[];
async function collectLibrary(){
 if(libraryRead)return libraryRead;
 libraryRead=(async()=>{const last=await lastTask();if(last)await libraryStore.remember(last.path);const paths=await libraryStore.discover([output,path.join(dataRoot,'tasks')]);let tasks=0;const results:Result[]=[],failed:string[]=[];for(const p of paths){try{await taskInfo(p);results.push(...await collectResults(p,false));tasks++;}catch(error){failed.push(p);diagnostics.log('warning','library','任务记录无法读取',{error:String(error)});}}unreadableTasks=failed;diagnostics.log('info','library','片段库载入',{tasks,unreadable:failed.length,clips:results.reduce((n,r)=>n+r.clips.length,0)});return{results:mergeLibrary(results),tasks,errors:failed.length};})().finally(()=>{libraryRead=null;});return libraryRead;
}
async function metadata(file:FileItem){await new Promise<void>(resolve=>{const executable=pythonFor();const proc=spawn(executable,['app_ui_info.py',file.path],{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});let result='';proc.stdout.setEncoding('utf8');proc.stdout.on('data',t=>result+=t);const timeout=setTimeout(()=>proc.kill(),20000);proc.on('error',()=>{clearTimeout(timeout);resolve();});proc.on('close',()=>{clearTimeout(timeout);try{const info=JSON.parse(result.trim());send({type:'metadata',source:file.path,...info} as WorkerEvent);}catch{send({type:'metadata',source:file.path,message:'无法读取录像信息'});}resolve();});});}
async function imports(paths:unknown):Promise<{files:FileItem[];rejected:string[]}>{if(!Array.isArray(paths)||paths.length>500)throw new Error('录像清单无效');const files:FileItem[]=[];const rejected:string[]=[];const seen=new Set<string>();for(const raw of paths){if(typeof raw!=='string'||!raw)continue;const p=path.resolve(raw);diagnostics.alias(p,'<video>');diagnostics.alias(path.basename(p),'<video>');if(seen.has(normalized(p)))continue;seen.add(normalized(p));try{const stat=await fs.stat(p);if(!stat.isFile()||!videoExtensions.has(path.extname(p).toLowerCase()))throw new Error();allowedPaths.add(normalized(p));files.push({id:normalized(p),path:p,name:path.basename(p),bytes:stat.size,status:'pending'});}catch{rejected.push(path.basename(p));}}let next=0;const pump=async()=>{while(next<files.length)await metadata(files[next++]);};void pump();void pump();return{files,rejected};}
async function start(payload:any,resume=false){if(clipDeletions.busy)throw new Error('正在回收片段，请稍候再开始任务');if(updating)throw new Error('正在更新软件，请稍后再开始任务');if(worker&&terminal)await workerExit;if(worker||launching||hudWorker||hudLaunching)throw new Error('已有识别任务正在处理');launching=true;stopRequested=false;terminal=false;
 try{if(maintenanceTimer){clearTimeout(maintenanceTimer);maintenanceTimer=null;}if(maintenance){maintenance.kill();await maintenanceExit;}let effective=safeOptions(payload.options,resume);let request:any;
  if(resume){if(!allowedTasks.has(normalized(payload.task)))throw new Error('请先选择续接任务');const info=await taskInfo(payload.task);request={resume_task:info.path,backend:effective.backend,gpu_load:effective.gpu_load,pipeline:effective.pipeline};currentTask=info.path;}
  else{if(!Array.isArray(payload.files)||!payload.files.length||payload.files.some((f:unknown)=>typeof f!=='string'||!allowedPaths.has(normalized(f))))throw new Error('请先导入录像');if(typeof payload.output!=='string'||!path.isAbsolute(payload.output))throw new Error('输出目录无效');options=effective;output=payload.output;await save();request={...effective,files:payload.files,output:payload.output};}
  const root=path.join(validationRoot,'app-requests');await fs.mkdir(root,{recursive:true});const id=randomUUID();stopFile=path.join(root,id+'.stop');const requestPath=path.join(root,id+'.json');request.stop_file=stopFile;await fs.writeFile(requestPath,JSON.stringify(request),'utf8');if(stopRequested)await fs.writeFile(stopFile,'stop','utf8');
  const python=pythonFor(effective.backend);if(!existsSync(python))throw new Error('未找到选定设备的 Python 环境');
  const proc=spawn(python,['app_worker.py',requestPath],{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8'}});worker=proc;workerExit=new Promise<void>(resolve=>{resolveWorkerExit=resolve;});
  let stderr='';const lines=new JsonLines(e=>{eventChain=eventChain.then(async()=>{const event=e as unknown as WorkerEvent;
   if(event.type==='run'&&event.task_path){currentTask=event.task_path;await taskInfo(currentTask);await libraryStore.remember(currentTask);}
   if(event.type==='file'){
    currentSource=event.source||'';const task=await readJson(currentTask);const item=task.items.find((i:any)=>normalized(i.source)===normalized(currentSource));
    processingTimes.begin(currentTask,currentSource,historicProcessingSeconds(item)??0);event.processing_seconds=processingTimes.seconds(currentTask,currentSource);
   }
   if(event.type==='preview'&&event.sample_path){try{event.imageUrl=await imageUrl(event.sample_path);}catch{try{const task=await readJson(currentTask);validateTaskStorage(task,currentTask);for(const root of await recordedSampleDirectories(task,path.dirname(event.sample_path)))taskSampleRoots.add(root);event.imageUrl=await imageUrl(event.sample_path);}catch{return;}}delete event.sample_path;}
   if(event.type==='result'&&currentTask){event.processing_seconds=processingTimes.finish(!!event.skipped);const list=await collectResults(currentTask);event.result=list.find(r=>normalized(r.source)===normalized(event.source||currentSource));}
   if(['error','done','stopped','fatal'].includes(event.type))processingTimes.finish();
   if(['done','stopped','fatal'].includes(event.type))terminal=true;send(event);
  }).catch(error=>send({type:'log',message:'界面状态读取：'+error.message}));},line=>send({type:'log',message:'后台非状态输出：'+line}));
  proc.stdout!.on('data',chunk=>lines.push(chunk));proc.stderr!.setEncoding('utf8');proc.stderr!.on('data',chunk=>{stderr=(stderr+chunk).slice(-20000);send({type:'stderr',message:chunk});});
  proc.on('error',error=>{processingTimes.finish();send({type:'fatal',message:'无法启动处理进程：'+error.message});});
  proc.on('close',code=>{lines.end();eventChain=eventChain.then(async()=>{processingTimes.finish();await processingTimes.flush();await fs.unlink(requestPath).catch(()=>{});if(stopFile)await fs.unlink(stopFile).catch(()=>{});worker=null;launching=false;stopFile='';resolveWorkerExit?.();resolveWorkerExit=null;if(!terminal){send({type:code===75?'stopped':'fatal',message:code===75?'断点已保存':`处理进程退出（${code}）。${stderr.slice(-1200)}`});}send({type:'exit'});scheduleMaintenance(true);if(closing){closing=false;win.close();}});});
 }catch(error){launching=false;throw error;}finally{if(worker)launching=false;}
}
async function stop(){stopRequested=true;if(stopFile)await fs.writeFile(stopFile,'stop','utf8');}
function trusted(event:Electron.IpcMainInvokeEvent){if(!win||event.sender!==win.webContents||event.senderFrame!==win.webContents.mainFrame)throw new Error('不允许的界面请求');}
async function enrichHud(files:unknown,fields:unknown,mode:unknown='missing'){
 if(updating)throw new Error('正在更新软件，请稍后补充信息');
 if(clipDeletions.busy||worker||launching||hudWorker||hudLaunching)throw new Error('请先等待当前处理结束');
 if(!Array.isArray(files)||!files.length||files.length>500||files.some(file=>typeof file!=='string'||!allowedClips.has(normalized(file))))throw new Error('请选择片段库中已导出的片段');
 if(!Array.isArray(fields)||!fields.length||fields.some(field=>!['account','weapons','teammates','hero','rank'].includes(field)))throw new Error('请选择要补充的HUD信息');
 if(mode!=='missing'&&mode!=='refresh')throw new Error('HUD识别模式无效');
 for(const file of files){diagnostics.alias(file,'<clip>');diagnostics.alias(path.basename(file),'<clip>');}hudLaunching=true;let requestPath='';
 try{
 if(maintenance){maintenance.kill();await maintenanceExit;}
 const grouped=new Map<string,string[]>();for(const file of files){const dir=clipDirectories.get(normalized(file));if(!dir)throw new Error('片段没有对应任务记录');grouped.set(dir,[...(grouped.get(dir)||[]),file]);}
 const root=path.join(validationRoot,'app-requests');await fs.mkdir(root,{recursive:true});requestPath=path.join(root,randomUUID()+'.json');
 await fs.writeFile(requestPath,JSON.stringify({jobs:[...grouped].map(([directory,files])=>({directory,files})),fields,force:mode==='refresh',backend:options.backend,gpu_load:options.gpu_load}),'utf8');
 return await new Promise<{updated:number;errors:{directory:string;message:string}[]}>((resolve,reject)=>{
  const proc=spawn(pythonFor(options.backend),['hud_enrichment.py',requestPath],{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});hudWorker=proc;
  let done:{updated:number;errors:{directory:string;message:string}[]}|null=null,stderr='';
  const lines=new JsonLines(event=>{if(event.type==='hud-info-done')done=event as unknown as typeof done;else send(event as unknown as WorkerEvent);},()=>{});
  proc.stdout?.on('data',chunk=>lines.push(chunk));proc.stderr?.setEncoding('utf8');proc.stderr?.on('data',chunk=>stderr=(stderr+chunk).slice(-2000));
  proc.once('error',reject);proc.once('close',code=>{lines.end();hudWorker=null;if(code===0&&done)resolve(done);else reject(new Error(stderr||'HUD补充识别中断，可重新继续'));});
 });}finally{hudWorker=null;hudLaunching=false;if(requestPath)await fs.unlink(requestPath).catch(()=>{});scheduleMaintenance(true);}
}
function handle(name:string,fn:(...args:any[])=>any){ipcMain.handle(name,async(event,...args)=>{trusted(event);try{return await fn(...args);}catch(error){diagnostics.log('error','ipc:'+name,error instanceof Error?error.message:String(error),{stack:error instanceof Error?error.stack:undefined});throw error;}});}

async function diagnosticTask(){
 const attachments:{name:string;text:string}[]=[];let file=currentTask;
 if(!file)for(const root of [validationRoot,legacyValidationRoot]){try{file=(await readJson(path.join(root,'app-last-task.json'))).task;if(file)break;}catch{}}
 let summary:unknown=null;const traceFiles=[path.join(updateRoot,'install.log')],traceRoots=[validationRoot,legacyValidationRoot,updateRoot];
 try{if(file){const task=await readJson(file);validateTaskStorage(task,file);traceRoots.push(task.directory);traceFiles.push(path.join(task.directory,'error.log'));summary={version:task.version,finished:task.finished,options:safeOptions({...defaults,...task.request},true),items:task.items.slice(0,500).map((item:any,index:number)=>{diagnostics.alias(item.source,`<video-${index+1}>`);diagnostics.alias(path.basename(item.source),`<video-${index+1}>`);const cache=item.analysis_cache||item.record?.analysis_cache;if(['error','running'].includes(item.status)&&typeof cache==='string'&&path.isAbsolute(cache))traceFiles.push(path.join(cache,'error.log'));return{index:index+1,status:item.status,stage:item.stage,error:item.record?.error,outputs:item.record?.outputs?.length||0};})};}}
 catch(error){summary={unavailable:true,error:String(error)};}
 const roots=(await Promise.all(traceRoots.map(root=>fs.realpath(root).catch(()=>'')))).filter(Boolean);
 for(const candidate of [...new Set(traceFiles)].slice(0,11)){try{const stat=await fs.lstat(candidate);if(!stat.isFile()||stat.isSymbolicLink()||Date.now()-stat.mtimeMs>7*86400000)continue;const real=await fs.realpath(candidate);if(!roots.some(root=>within(real,root)))continue;const reader=await fs.open(candidate,'r');try{const size=Math.min(128*1024,stat.size),buffer=Buffer.alloc(size);const{bytesRead}=await reader.read(buffer,0,size,Math.max(0,stat.size-size));attachments.push({name:`errors/error-${attachments.length+1}.log`,text:buffer.subarray(0,bytesRead).toString('utf8')});}finally{await reader.close();}}catch{}}
 return{summary,attachments};
}
app.whenReady().then(async()=>{
 await thumbnails.prune(true).catch(()=>{});
 await pruneUpdates(updateRoot).catch(()=>{});
 await pruneRequests().catch(()=>{});
 await libraryStore.load();
 await clipDeletions.load();
 await processingTimes.load();
 try{const saved=await readJson(path.join(app.getPath('userData'),'preferences.json'));playerAudio=normalizePlayerAudio(saved.playerAudio);if(typeof saved.updatePreferences?.autoCheck==='boolean')updateInfo.autoCheck=saved.updatePreferences.autoCheck;updateInfo=restoreUpdateInfo(saved.updateCache,app.getVersion(),updateInfo.autoCheck);preferences={...preferences,...saved.preferences};const previousOptions={...saved.options};if(!saved.optionDefaultsVersion&&previousOptions.gap===35&&previousOptions.pre===10&&previousOptions.post===15){previousOptions.gap=defaults.gap;previousOptions.pre=defaults.pre;previousOptions.post=defaults.post;}options=safeOptions({...defaults,...previousOptions,fps:saved.options?.fps<1?defaults.fps:saved.options?.fps??defaults.fps});output=saved.output||output;}catch{}
 diagnostics.alias(dataRoot,'<data>');diagnostics.alias(output,'<output>');diagnostics.log('info','startup','设置已载入',{options,theme:preferences.mode});
 protocol.handle('apex-media',async request=>{try{const url=new URL(request.url);if(url.hostname==='video')return videos.respond(request);const p=images.get(url.pathname.slice(1));if(url.hostname!=='image'||!p)return new Response('Not found',{status:404});const data=await fs.readFile(p);return new Response(data,{headers:{'Content-Type':p.endsWith('.png')?'image/png':'image/jpeg','Cache-Control':'private, max-age=60'}});}catch{return new Response('Unavailable',{status:404});}});
 const initial=theme();const dark=preferences.mode==='dark'||(preferences.mode==='system'&&initial.dark);
 win=new BrowserWindow({width:1120,height:820,minWidth:760,minHeight:620,show:false,title:'Apex Highlight Clipper',backgroundColor:'#211e1a',titleBarStyle:'hidden',titleBarOverlay:false,autoHideMenuBar:true,webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
 win.webContents.on('console-message',details=>{if(details.level==='error')diagnostics.log('error','renderer-console',details.message,{line:details.lineNumber,source:details.sourceId});});
 win.webContents.on('render-process-gone',(_event,details)=>diagnostics.log('error','renderer-process','界面进程退出',details));
 win.on('unresponsive',()=>diagnostics.log('warning','renderer','界面无响应'));
 const windowState=()=>({maximized:win.isMaximized()});
 const publishWindowState=()=>{if(!win.isDestroyed())win.webContents.send('window-state',windowState());};
 win.on('maximize',publishWindowState);win.on('unmaximize',publishWindowState);win.on('restore',publishWindowState);
 handle('window-state',windowState);
 handle('window-command',(command:unknown)=>{if(command==='minimize')win.minimize();else if(command==='maximize'){if(win.isMaximized())win.unmaximize();else win.maximize();}else if(command==='close')win.close();else throw new Error('窗口操作无效');});
 handle('diagnostics-info',()=>diagnostics.info());
 let rendererReports=0,rendererReportWindow=Date.now();
 handle('renderer-diagnostic',(report:unknown)=>{if(!report||typeof report!=='object')return;const{type,message,stack}=report as Record<string,unknown>;if(!['error','action'].includes(String(type))||typeof message!=='string')return;if(Date.now()-rendererReportWindow>60000){rendererReports=0;rendererReportWindow=Date.now();}if(++rendererReports>120)return;diagnostics.log(type==='error'?'error':'info','renderer-'+type,message.slice(0,2000),{stack:typeof stack==='string'?stack.slice(0,8000):undefined});});
 handle('open-diagnostics',async()=>{const info=await diagnostics.info();if(!info.available)throw new Error(info.message||'日志尚未生成');const error=await shell.openPath(diagnostics.directory);if(error)throw new Error(error);});
 handle('export-diagnostics',async()=>{const choice=await dialog.showSaveDialog(win,{title:'导出诊断包',defaultPath:path.join(app.getPath('desktop'),`AHC-diagnostics-v${app.getVersion()}-${new Date().toISOString().slice(0,10)}.zip`),filters:[{name:'诊断包 ZIP',extensions:['zip']}]});if(choice.canceled||!choice.filePath)return null;const file=choice.filePath.endsWith('.zip')?choice.filePath:choice.filePath+'.zip',task=await diagnosticTask();let gpu:unknown;try{const info=await app.getGPUInfo('basic') as Record<string,unknown>;if(Array.isArray(info.gpuDevice))gpu=info.gpuDevice.map(device=>Object.fromEntries(['vendorId','deviceId','driverVendor','driverVersion','deviceString','active'].filter(key=>device[key]!==undefined).map(key=>[key,device[key]])));}catch{}await diagnostics.export(file,{createdAt:new Date().toISOString(),version:app.getVersion(),system:{platform:process.platform,release:os.release(),arch:process.arch,cpu:os.cpus()[0]?.model,logicalCores:os.cpus().length,memoryMiB:Math.round(os.totalmem()/1024**2),versions:process.versions,gpu},options,theme:preferences,task:task.summary,library:{unreadable:unreadableTasks.length},update:{status:updateInfo.status,latestVersion:updateInfo.latestVersion,installState:updateInfo.installState,installMessage:updateInfo.installMessage},runtime:{cpu:existsSync(pythonFor('cpu')),dml:existsSync(pythonFor('dml'))}},task.attachments);return file;});
 handle('open-feedback',()=>shell.openExternal('https://github.com/LilycleHeart/apex-highlight-clipper/issues/new?title='+encodeURIComponent(`[v${app.getVersion()}] 问题反馈`)+'&body='+encodeURIComponent(`软件版本：v${app.getVersion()}\n\n问题现象：\n\n复现步骤：\n1. \n\n请将“剪辑设置 → 诊断与反馈 → 导出诊断包”生成的 ZIP 拖入此处上传。`)));
 let shown=false;handle('ui-ready',()=>{if(!shown&&!win.isDestroyed()){shown=true;win.show();scheduleUpdate();scheduleMaintenance();}});setTimeout(()=>{if(!shown&&!win.isDestroyed())win.show();},10000).unref();
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));win.webContents.on('will-navigate',event=>event.preventDefault());
 win.on('minimize',()=>send({type:'visibility',hidden:true}));win.on('hide',()=>send({type:'visibility',hidden:true}));win.on('restore',()=>send({type:'visibility',hidden:false}));win.on('show',()=>send({type:'visibility',hidden:false}));
 win.on('close',event=>{repairWorker?.kill();repairWorker=null;if(worker||launching){event.preventDefault();if(!closing){closing=true;send({type:'close-request',message:'窗口将在断点保存后关闭'});void stop();}}else if(!closeSaveFinished){event.preventDefault();void flushSaves().then(()=>{closeSaveFinished=true;if(!win.isDestroyed())win.close();});}});
 const changed=()=>{if(!win.isDestroyed())win.webContents.send('system-theme',theme());};nativeTheme.on('updated',changed);systemPreferences.on('accent-color-changed',changed);systemPreferences.on('color-changed',changed);
 handle('chrome',(color:string,foreground:string)=>{if(!/^#[\da-f]{6}$/i.test(color)||!/^#[\da-f]{6}$/i.test(foreground))throw new Error('窗口配色无效');win.setBackgroundColor(color);});
 handle('bootstrap',async()=>({output,options,preferences,playerAudio,theme:theme(),development,lastTask:await lastTask(),backendAvailable:existsSync(pythonFor('dml')),update:updateInfo}));
 handle('check-update',async()=>{await updater.check();await saveChain;return updateInfo;});
 handle('install-update',async()=>{
  if(updating)throw new Error('更新正在进行');
  if(worker||launching||hudWorker||hudLaunching||repairWorker)throw new Error('请先暂停或完成当前任务后更新');
  if(!app.isPackaged)throw new Error('开发预览请使用发布页安装正式程序');
  updating=true;let scheduled=false;
  const report=(installState:NonNullable<UpdateInfo['installState']>,installProgress?:number,installMessage?:string)=>{if(installState!==updateInfo.installState||installProgress!==undefined&&installProgress%10===0)diagnostics.log(installState==='error'?'error':'info','update-install',installState,{progress:installProgress,message:installMessage});updateInfo={...updateInfo,installState,installProgress,installMessage};if(!win.isDestroyed())win.webContents.send('update-status',updateInfo);};
  try{
   const latest=await updater.check();if(latest.status!=='available')throw new Error(latest.message||'当前没有可安装的新版本');if(!latest.installer)throw new Error('该版本没有可校验的安装包，请使用发布页安装');
   const target=path.dirname(path.dirname(app.getPath('exe'))),helper=path.join(target,'scripts/update-install.ps1');
   if(!existsSync(path.join(target,'app_worker.py'))||!existsSync(path.join(target,'runtime/runtime-layout.json'))||!existsSync(helper))throw new Error('无法确定程序安装位置，请使用发布页安装');
   updateAbort=new AbortController();report('downloading',0);
   const installer=await downloadInstaller(latest.installer,updateRoot,(url,init)=>net.fetch(url,init),percent=>report('downloading',percent),updateAbort.signal);updateAbort=null;
   await flushSaves();const portable=!(await fs.readdir(target)).some(name=>/^unins\d+\.exe$/i.test(name));
   const args=['-NoProfile','-WindowStyle','Hidden','-ExecutionPolicy','Bypass','-File',helper,'-Installer',installer,'-Target',target,'-ParentPid',String(process.pid),...(portable?['-Portable']:[])];
   app.relaunch({execPath:path.join(process.env.SystemRoot||'C:/Windows','System32/WindowsPowerShell/v1.0/powershell.exe'),args});
   scheduled=true;report('installing',100);setTimeout(()=>win.close(),250);
  }catch(error){report('error',undefined,error instanceof Error&&/^[\u4e00-\u9fff]/.test(error.message)?error.message:'更新未完成，请重试');throw error;}
  finally{updateAbort=null;if(!scheduled)updating=false;}
 });
 handle('auto-check-update',async(enabled:unknown)=>{if(typeof enabled!=='boolean')throw new Error('更新开关无效');publishUpdate({...updateInfo,autoCheck:enabled});await save();if(enabled)scheduleUpdate();else if(updateTimer){clearTimeout(updateTimer);updateTimer=null;}return updateInfo;});
 handle('open-release',()=>shell.openExternal(releasePage(updateInfo.status==='available'?updateInfo.releaseTag:undefined)));
 handle('choose-files',async()=>{const result=await dialog.showOpenDialog(win,{properties:['openFile','multiSelections'],filters:[{name:'录像',extensions:[...videoExtensions].map(x=>x.slice(1))}]});return imports(result.filePaths);});
 handle('choose-folder',async()=>{const result=await dialog.showOpenDialog(win,{properties:['openDirectory']});if(result.canceled)return{files:[],rejected:[]};const dir=result.filePaths[0];return imports((await fs.readdir(dir,{withFileTypes:true})).filter(e=>e.isFile()&&videoExtensions.has(path.extname(e.name).toLowerCase())).map(e=>path.join(dir,e.name)));});
 handle('import-files',imports);
 handle('choose-output',async()=>{const result=await dialog.showOpenDialog(win,{properties:['openDirectory','createDirectory'],defaultPath:output});if(result.canceled)return null;output=result.filePaths[0];allowedPaths.add(normalized(output));await save();return output;});
 handle('player-audio',async(value:PlayerAudioPreferences)=>{if(!value||!Number.isFinite(value.volume)||value.volume<0||value.volume>1||typeof value.muted!=='boolean'||!Number.isFinite(value.lastAudibleVolume)||value.lastAudibleVolume<=0||value.lastAudibleVolume>1)throw new Error('音量设置无效');playerAudio=normalizePlayerAudio(value);await save();});
 handle('preferences',async(p:ThemePreferences)=>{if(!['system','light','dark'].includes(p.mode)||p.seed!==null&&!/^#[\da-f]{6}$/i.test(p.seed)||typeof p.reduceMotion!=='boolean'||!['flat','sketch'].includes(p.mascotStyle)||typeof p.mascotEnabled!=='boolean')throw new Error('外观选项无效');preferences=p;await save();});
 handle('options',async(o:Options,p:string)=>{options=safeOptions(o);if(typeof p==='string'&&path.isAbsolute(p))output=p;await save();});
 handle('start',p=>start(p));handle('stop',stop);handle('resume',p=>start(p,true));handle('last-task',lastTask);
 handle('task',p=>{if(typeof p!=='string'||!allowedTasks.has(normalized(p)))throw new Error('请先选择任务');return taskInfo(p);});
 handle('choose-task',async()=>{const result=await dialog.showOpenDialog(win,{properties:['openFile'],filters:[{name:'任务记录 task.json',extensions:['json']}]});if(result.canceled)return null;const info=await taskInfo(result.filePaths[0]);await libraryStore.remember(info.path,true);return info;});
 handle('results',collectResults);handle('library',collectLibrary);
 handle('ignore-library-errors',async()=>{if(libraryRead)await libraryRead;await libraryStore.ignore(unreadableTasks);return collectLibrary();});
 handle('enrich-hud',enrichHud);
 handle('choose-library-root',async()=>{const selected=await dialog.showOpenDialog(win,{title:'添加历史输出目录',properties:['openDirectory']});if(selected.canceled)return false;await libraryStore.addRoot(selected.filePaths[0]);return true;});
 handle('video-url',file=>videos.url(file));
 handle('delete-clip',async(file:string)=>{await clipDeletions.remove(file);allowedClips.delete(normalized(file));diagnostics.log('info','library','片段已移至回收站');});
 handle('thumbnail-url',async(file:string)=>{if(typeof file!=='string'||!allowedClips.has(normalized(file)))throw new Error('只允许读取片段库中已导出的录像');return imageUrl(await thumbnails.get(file,clipDurations.get(normalized(file))||0));});
 handle('thumbnail-stats',()=>thumbnails.stats());
 handle('open',async(p:string,folder=false)=>{if(typeof p!=='string'||!allowedPaths.has(normalized(p)))throw new Error('只允许打开本任务的录像或成片');const stat=await fs.stat(p);if(!stat.isDirectory()&&!videoExtensions.has(path.extname(p).toLowerCase()))throw new Error('只允许打开录像或输出文件夹');if(folder)shell.showItemInFolder(p);else{const error=await shell.openPath(p);if(error)throw new Error(error);}});
 if(process.env.APEX_UI_VALIDATE==='1'){
  handle('validation-import',imports);handle('validation-task',taskInfo);handle('validation-project',()=>project);
 }
 const renderer=path.join(__dirname,'../../dist/index.html');if(process.env.APEX_UI_DEV_URL)await win.loadURL(process.env.APEX_UI_DEV_URL);else await win.loadFile(renderer);
}).catch(error=>{diagnostics.fatal(error instanceof Error?error:new Error(String(error)));dialog.showErrorBox('Apex 启动失败',String(error));app.quit();});
app.on('window-all-closed',()=>app.quit());
app.on('before-quit',()=>{updateAbort?.abort();if(maintenanceTimer)clearTimeout(maintenanceTimer);maintenance?.kill();hudWorker?.kill();thumbnails.dispose();});
