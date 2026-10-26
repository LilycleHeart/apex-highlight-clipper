import {app,BrowserWindow,dialog,ipcMain,nativeTheme,systemPreferences,protocol,shell,net,screen} from 'electron';
import {execFile,spawn,ChildProcess} from 'node:child_process';
import fs from 'node:fs/promises';
import {existsSync,constants as fsConstants} from 'node:fs';
import path from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import os from 'node:os';
import {normalizePerformance,resolvePerformance} from '../src/performanceOptions';
import {restoreWindowPlacement,type WindowPlacement} from './windowPlacement';
import {normalizeTeammateExclusions,changeTeammateExclusion} from '../src/teammateExclusions';
import {shareFiles} from './qqShare';
import {Diagnostics} from './diagnostics';
import {JsonLines,safeOptions,safeHudFiles,videoExtensions} from './protocol';
import {defaults,Options,ThemePreferences,WorkerEvent,TaskInfo,Result,FileItem,SystemTheme,UpdateInfo,HudEnrichmentResult} from '../src/shared';
import {animationDefaults,normalizeAnimationPreferences} from '../src/animationPreferences';
import {normalizePlayerAudio,defaultPlayerAudio,type PlayerAudioPreferences} from '../src/audioPreferences';
import {clipStatistics,recordingTime,applyStatisticsCorrection} from '../src/clipStats';
import {UpdateChecker,shouldAutoCheck,releasePage,restoreUpdateInfo,RELEASES_API} from './updates';
import {downloadInstaller,pruneUpdates,installationPaths,pruneLegacyLauncher} from './updateInstaller';
import {VideoRegistry} from './media';
import {ClipDeletions} from './clipDeletions';
import {ProcessingTimes,historicProcessingSeconds} from './processingTimes';
import {LibraryStore,mergeLibrary,scanLibraryRoots,matchMovedClips,libraryVideoExtensions,type MissingClip,type LibraryVideo} from './library';
import {validateTaskStorage,videoDirectory,isRecordedVideo,isRelocatedOutput,recordedSampleDirectories} from './taskStorage';
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
 throw new Error('请通过程序目录中的 Apex Highlight Clipper.exe 启动以准备视频工具');
});
const clipDurations=new Map<string,number>();const clipDirectories=new Map<string,string>();
const clipTasks=new Map<string,string>();const originalVideos=new Set<string>();
let hudWorker:ChildProcess|null=null;let hudLaunching=false;let hudStopFile='';let hudStopRequested=false;
function pythonFor(backend:'cpu'|'dml'|'cuda'='cpu'){const bundled=path.join(project,'runtime',backend,'python.exe');return existsSync(bundled)?bundled:path.join(project,backend==='cuda'?'.cuda-venv/Scripts/python.exe':backend==='dml'?'.gpu-venv/Scripts/python.exe':'.venv/Scripts/python.exe');}
let cudaHealth:Promise<boolean>|null=null;
function cudaAvailable():Promise<boolean>{
 if(!existsSync(pythonFor('cuda')))return Promise.resolve(false);
 // Provider enumeration can succeed even when cuDNN/CUDA DLLs cannot load.
 // Probe once per app process with the same adapter used by recognition jobs.
 return cudaHealth??=new Promise<boolean>(resolve=>{
  let timeout:ReturnType<typeof setTimeout>|undefined;
  const probe=execFile(pythonFor('cuda'),['-B','-X','utf8','-c',"import numpy as np; from gpu_ocr_backend import create_ocr_engine; e=create_ocr_engine(backend='cuda',rec_batch_num=1); e.text_rec([np.zeros((32,160,3),dtype=np.uint8)]); print('APEX_CUDA_READY')"],{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1',APEX_GPU_LOAD:'fast'}},(error,stdout)=>{
   if(timeout)clearTimeout(timeout);
   resolve(!error&&stdout.trim().split(/\r?\n/).includes('APEX_CUDA_READY'));
  });
  timeout=setTimeout(()=>{
   resolve(false);
   // A Windows venv launcher may own another Python process; stop both.
   if(process.platform==='win32'&&probe.pid)execFile('taskkill',['/PID',String(probe.pid),'/T','/F'],{windowsHide:true,timeout:5000},()=>{if(!probe.killed)probe.kill();});
   else probe.kill();
  },20000);
 });
}
// Upgrades may preserve source timestamps; never reuse adjacent bytecode from an older kernel.
function pythonArguments(entry:string,...args:string[]){return ['-B','-X','utf8','-X',`pycache_prefix=${path.join(validationRoot,'unused-bytecode',randomUUID())}`,entry,...args];}
const development=!app.isPackaged||process.argv.includes('--preview');
let win:BrowserWindow;let worker:ChildProcess|null=null;let launching=false;let stopFile='';let stopRequested=false;let closing=false;let terminal=false;let currentTask='';let currentSource='';let eventChain=Promise.resolve();
if(process.argv.includes('--preview')){
 if(!app.requestSingleInstanceLock())app.quit();
 else app.on('second-instance',()=>{if(!win||win.isDestroyed())return;if(win.isMinimized())win.restore();win.show();win.focus();});
}
let updating=false;let updateAbort:AbortController|null=null;
const processingTimes=new ProcessingTimes(path.join(dataRoot,'processing-times.json'),(source,seconds)=>send({type:'file-timing',source,processing_seconds:seconds}),error=>diagnostics.log('error','processing-time',String(error)));
const updateRoot=path.join(app.getPath('userData'),'updates');
let workerExit:Promise<void>=Promise.resolve();let resolveWorkerExit:(()=>void)|null=null;let closeSaveFinished=false;
let windowPlacement:WindowPlacement|undefined;let placementTimer:ReturnType<typeof setTimeout>|undefined;
let excludedTeammates:string[]=[];let teammateWrites:Promise<unknown>=Promise.resolve();
let playerAudio:PlayerAudioPreferences={...defaultPlayerAudio};
let preferences:ThemePreferences={mode:'system',seed:null,reduceMotion:false,mascotStyle:'flat',mascotEnabled:false,...animationDefaults};let options:Options={...defaults};let output=app.isPackaged?path.join(app.getPath('videos'),'Apex Highlight Clipper'):path.join(project,'output');
// 国内直连 github.com 的安装包下载经常超时；默认走实测延迟最低的加速镜像，
// 用户仍可在「版本更新 → GitHub 加速」里改成不使用或自定义。
let updateInfo:UpdateInfo={status:'idle',currentVersion:app.getVersion(),autoCheck:true};let updateMirror='https://gh-proxy.com/';let updateTimer:ReturnType<typeof setTimeout>|null=null;
function publishUpdate(info:UpdateInfo){diagnostics.log(info.status==='error'?'error':'info','update',info.status,{currentVersion:info.currentVersion,latestVersion:info.latestVersion,message:info.message});updateInfo=info;if(info.status!=='checking')void save().catch(error=>diagnostics.log('error','preferences',String(error)));if(win&&!win.isDestroyed())win.webContents.send('update-status',info);}
const updater=new UpdateChecker(app.getVersion(),(url,init)=>net.fetch(url,init),()=>updateInfo,publishUpdate,()=>updateMirror);
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
  const stat=await fs.lstat(file),real=await fs.realpath(file),directory=await fs.realpath(videoDirectory(task,item));if(!stat.isFile()||stat.isSymbolicLink()||!within(real,directory)&&!isRelocatedOutput(item.record,file))throw new Error('成片路径无效');
  if(originalVideos.has(normalized(real)))throw new Error('原录像不能从片段库回收');for(const source of new Set<string>(task.items.map((item:any)=>item.source))){const original=await fs.realpath(source).catch(()=>null);if(original&&normalized(original)===normalized(real))throw new Error('此文件正在作为原录像使用，不能从片段库回收');}
 }
},file=>videos.release(file),file=>shell.trashItem(file));
const normalized=(p:string)=>path.resolve(p).toLowerCase();
const within=(child:string,parent:string)=>{const relative=path.relative(parent,child);return relative===''||(!relative.startsWith('..'+path.sep)&&relative!=='..'&&!path.isAbsolute(relative));};
const readJson=async(p:string)=>JSON.parse((await fs.readFile(p,'utf8')).replace(/^\uFEFF/,''));
async function pruneRequests(){
 const root=path.join(validationRoot,'app-requests');
 for(const item of await fs.readdir(root,{withFileTypes:true}).catch(()=>[])){
  if(!item.isFile()||! /^[a-f0-9-]{36}(?:-counter-repair|-qq-share)?\.(?:json|stop|ps1)$/.test(item.name))continue;
  const file=path.join(root,item.name),stat=await fs.lstat(file).catch(()=>null);
  if(stat?.isFile()&&Date.now()-stat.mtimeMs>7*86400000)await fs.unlink(file).catch(()=>{});
 }
}
let loggedStage='',loggedProgress=-1;
function send(e:WorkerEvent){if(e.source)diagnostics.alias(e.source,'<video>');const progress=Math.floor((e.progress||0)/10);if(['run','file','stage','done','stopped','fatal','error','exit','log','stderr','close-request','hud-info-start','hud-info-file','hud-info-error','hud-info-done'].includes(e.type)||(e.type==='progress'&&(e.stage!==loggedStage||progress!==loggedProgress))){loggedStage=e.stage||loggedStage;loggedProgress=progress;diagnostics.log(['fatal','error','stderr','hud-info-error'].includes(e.type)?'error':'info','worker',e.message||e.type,{type:e.type,stage:e.stage,progress:e.progress,index:e.index,total:e.total,failures:e.failures,clips:e.clips});}if(win&&!win.isDestroyed())win.webContents.send('worker-event',e);}
function theme():SystemTheme{let accent='#526b4a';let reduceMotion=false;try{const color=systemPreferences.getAccentColor();if(/^[\da-f]{8}$/i.test(color))accent='#'+color.slice(0,6);}catch{}try{reduceMotion=systemPreferences.getAnimationSettings().prefersReducedMotion;}catch{}return{accent,dark:nativeTheme.shouldUseDarkColors,reduceMotion};}
let saveChain=Promise.resolve();
async function flushSaves(){await teammateWrites.catch(()=>{});let pending:Promise<void>;do{pending=saveChain;await pending.catch(()=>{});}while(pending!==saveChain);await diagnostics.flush();}
let maintenance:ChildProcess|null=null;let maintenanceExit:Promise<void>=Promise.resolve();let maintenanceTimer:ReturnType<typeof setTimeout>|null=null;
function scheduleMaintenance(force=false){
 if(process.env.APEX_UI_TEST_HOME||process.env.APEX_UI_VALIDATE||maintenanceTimer||maintenance)return;
 maintenanceTimer=setTimeout(async()=>{
  maintenanceTimer=null;if(worker||launching||closing||hudWorker||hudLaunching)return;
  const completed=await fs.stat(path.join(validationRoot,'.maintenance.json')).catch(()=>null);
  const previous=await readJson(path.join(validationRoot,'.maintenance.json')).catch(()=>null);
  const cacheCount=(await fs.readdir(path.join(validationRoot,'app-cache'),{withFileTypes:true}).catch(()=>[])).filter(item=>item.isDirectory()).length;
  // 已完成任务的画面缓存在任务结束后立即清除；这里只需看是否还有被未完成断点保护以外的残留。
  const retained=Math.max(0,Number(previous?.cache_count)||0);
  if(!force&&completed&&Date.now()-completed.mtimeMs<86400000&&cacheCount<=retained)return;
  if(worker||launching||closing||hudWorker||hudLaunching)return;
  const script=path.join(project,'scripts/cleanup-validation.ps1');if(!existsSync(script))return;
  const proc=spawn(path.join(process.env.SystemRoot||'C:/Windows','System32/WindowsPowerShell/v1.0/powershell.exe'),['-NoProfile','-ExecutionPolicy','Bypass','-File',script,'-Apply','-KeepCaches','0','-OutputRoot',output,'-UserData',app.getPath('userData'),'-DataRoot',dataRoot],{windowsHide:true});
  maintenance=proc;let result='';proc.stdout?.setEncoding('utf8');proc.stdout?.on('data',data=>result=(result+data).slice(-2000));proc.stderr?.resume();
  maintenanceExit=new Promise<void>(resolve=>{const finish=()=>{if(maintenance===proc)maintenance=null;resolve();};proc.once('error',finish);proc.once('close',code=>{if(code===0&&result.includes('"Bytes"'))send({type:'log',message:'缓存维护已完成'});finish();});});
 },10000);maintenanceTimer.unref();
}
async function save(){const snapshot=JSON.stringify({preferences,options,playerAudio,windowPlacement,excludedTeammates,optionDefaultsVersion:2,output,updatePreferences:{autoCheck:updateInfo.autoCheck,mirror:updateMirror},updateCache:updateInfo.status==='checking'?undefined:updateInfo});saveChain=saveChain.catch(()=>{}).then(async()=>{await fs.mkdir(app.getPath('userData'),{recursive:true});const target=path.join(app.getPath('userData'),'preferences.json');await fs.writeFile(target+'.tmp',snapshot,'utf8');await fs.rename(target+'.tmp',target);});return saveChain;}
async function imageUrl(p:string){
 const real=await fs.realpath(p);if(!['.jpg','.jpeg','.png'].includes(path.extname(real).toLowerCase()))throw new Error('预览格式无效');
 const roots=await Promise.all([validationRoot,legacyValidationRoot,thumbnails.directory,...taskSampleRoots].map(p=>fs.realpath(p).catch(()=>'')));if(!roots.some(root=>root&&within(real,root)))throw new Error('预览路径不属于画面缓存');
 let key=imageKeys.get(real);if(!key){key=randomUUID();images.set(key,real);imageKeys.set(real,key);if(images.size>6000){const oldest=images.keys().next().value!;imageKeys.delete(images.get(oldest)!);images.delete(oldest);}}
 return `apex-media://image/${key}`;
}
async function taskInfo(p:string):Promise<TaskInfo>{const task=await readJson(p);validateTaskStorage(task,p);const historic={...task,items:task.items.filter((item:any)=>[item.analysis_cache,item.record?.analysis_cache].some(raw=>typeof raw==='string'&&path.isAbsolute(raw)&&![validationRoot,legacyValidationRoot].some(root=>within(path.resolve(raw),root))&&![...taskSampleRoots].some(root=>within(root,path.resolve(raw)))))};for(const root of await recordedSampleDirectories(historic))taskSampleRoots.add(root);allowedTasks.add(normalized(p));allowedPaths.add(normalized(task.directory));for(const item of task.items){allowedPaths.add(normalized(item.source));originalVideos.add(normalized(item.source));diagnostics.alias(item.source,'<video>');diagnostics.alias(path.basename(item.source),'<video>');}return{path:p,directory:task.directory,output:task.request.output||path.dirname(task.directory),finished:task.finished,legacyRule:!task.result_filter_version,samplingWarning:task.request.fps<1?'旧任务低采样率可能漏掉交战；新建任务建议至少1帧/秒':'',options:safeOptions({...defaults,...task.request,...normalizePerformance(task.request)},true),items:task.items.map((i:any)=>({id:normalized(i.source),path:i.source,name:path.basename(i.source),status:i.status==='error'?'error':i.status==='complete'?'complete':i.status==='running'?'stopped':'pending',missing:!existsSync(i.source),processingSeconds:processingTimes.seconds(p,i.source,historicProcessingSeconds(i)),error:i.record?.error}))};}
async function lastTask(){for(const root of [validationRoot,legacyValidationRoot])try{const record=await readJson(path.join(root,'app-last-task.json'));if(!libraryStore.isIgnored(record.task))return await taskInfo(record.task);}catch{}return libraryStore.recoverLastTask([output,path.join(dataRoot,'tasks')],path.join(validationRoot,'app-last-task.json'),taskInfo);}
const repairedCounters=new Set<string>();let counterRepair:Promise<void>|null=null;let repairWorker:ChildProcess|null=null;let counterStopFile='';
async function stopCounterRepair(){const pending=counterRepair;if(!pending)return;const file=counterStopFile;if(file){await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file,'stop','utf8');}await pending;}
async function repairLegacyCounters(task:any){
 if(counterRepair){await counterRepair;}const records:any[]=[];
 for(const item of task.items){const record=item.record;if(!record||record.status!=='complete'||typeof record.directory!=='string'||repairedCounters.has(normalized(item.destination))||normalized(record.directory)!==normalized(item.destination)||!within(path.resolve(item.destination),path.resolve(task.directory)))continue;
  if(typeof record.analysis_cache!=='string'||typeof record.sample_directory!=='string'||(![validationRoot,legacyValidationRoot].some(root=>within(path.resolve(record.analysis_cache),root))&&![...taskSampleRoots].some(root=>within(root,path.resolve(record.analysis_cache))))||![validationRoot,legacyValidationRoot,...taskSampleRoots].some(root=>within(path.resolve(record.sample_directory),root)))continue;
  try{const stats=await readJson(path.join(item.destination,'statistics.json'));if(stats.version!=='combat-statistics-v9'&&stats.segments?.some((s:any)=>['kills','assists','damage'].some(k=>s.counts[k]===null)))records.push(record);}catch{}
 }
 if(!records.length||worker||launching||hudWorker||hudLaunching||updating)return;
 counterRepair=(async()=>{let timedOut=false;const dir=path.join(validationRoot,'app-requests'),id=randomUUID();const marker=path.join(dir,id+'-counter-repair.stop');counterStopFile=marker;await fs.mkdir(dir,{recursive:true});const file=path.join(dir,id+'-counter-repair.json');await fs.writeFile(file,JSON.stringify(records),'utf8');await new Promise<void>(resolve=>{const proc=spawn(pythonFor(),pythonArguments('repair_cached_statistics.py',file),{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1',APEX_TASK_STOP_FILE:marker}});repairWorker=proc;proc.stdout?.resume();proc.stderr?.resume();const timeout=setTimeout(()=>{timedOut=true;void fs.writeFile(marker,'stop','utf8');proc.kill();},60000);proc.on('error',()=>{clearTimeout(timeout);resolve();});proc.on('close',code=>{clearTimeout(timeout);if(repairWorker===proc)repairWorker=null;if(code===0)records.forEach(r=>repairedCounters.add(normalized(r.directory)));resolve();});});await fs.unlink(file).catch(()=>{});if(!timedOut)await fs.unlink(marker).catch(()=>{});if(counterStopFile===marker)counterStopFile='';})().finally(()=>{counterRepair=null;});await counterRepair;
}
async function collectResults(p:string,repair=true):Promise<Result[]>{
 if(!allowedTasks.has(normalized(p)))throw new Error('请先选择任务');const task=await readJson(p);validateTaskStorage(task,p);const results:Result[]=[];
 if(!updating&&!worker&&!hudWorker&&!hudLaunching&&repair)void repairLegacyCounters(task).then(()=>collectResults(p,false)).then(results=>send({type:'results-refreshed',task_path:p,results})).catch(()=>{});
 for(const item of task.items){const record=item.record;if(!record)continue;
  if(!within(path.resolve(item.destination),path.resolve(task.directory)))throw new Error('成片目录不属于任务');
  if(existsSync(item.destination)&&!within(await fs.realpath(item.destination),await fs.realpath(task.directory)))throw new Error('任务分析目录指向外部位置');
  const result:Result={...record,source:item.source,directory:item.destination,clips:[]};
  try{const report=await readJson(path.join(item.destination,'quality-filter.json'));result.qualityRejected=report.decisions?.filter((s:any)=>s.status==='rejected');}catch{}
  if(record.outputs?.length&&record.outputs.some((f:string)=>!existsSync(f)&&!clipDeletions.isRemoved(f))){result.status='error';result.error='记录中的成片缺失，请检查输出目录或恢复原片后续接。';}
  try{result.review=await readJson(path.join(item.destination,'review-candidates.json'));}catch{}try{const rejected=await readJson(path.join(item.destination,'rejected-candidates.json'));if(Array.isArray(rejected))result.rejected=rejected.filter(s=>Number.isFinite(s.start)&&Number.isFinite(s.end));}catch{}
  try{const manifest=await readJson(path.join(item.destination,'export.json'));if(manifest.metadata_directory&&normalized(manifest.metadata_directory)!==normalized(item.destination))throw new Error('成片元数据目录不匹配');if(manifest.video_directory&&normalized(manifest.video_directory)!==normalized(videoDirectory(task,item)))throw new Error('成片视频目录不匹配');let corrected:any[]=[];try{const raw=await fs.readFile(path.join(item.destination,'statistics.json'));const context=(await fs.realpath(item.destination)).replaceAll('\\','/').toLowerCase();const key=createHash('sha256').update(raw).update('\0').update(context).digest('hex');const legacyKey=createHash('sha256').update(raw).digest('hex');for(const file of [path.join(dataRoot,'recognition-corrections',key+'.json'),path.join(dataRoot,'recognition-corrections',legacyKey+'.json'),path.join(item.destination,'statistics-corrected.json')])try{const fix=await readJson(file);if(fix.repair_signature===createHash('sha256').update(raw).update(fix.version).update(fix.counter_recipe||'').digest('hex'))corrected.push(fix);}catch{}}catch{}let analysis:any={};let candidates:any[]=[];try{analysis=await readJson(path.join(item.destination,'analysis.json'));candidates=analysis.segments||[];}catch{}let frames:string[]=[];let samples=record.sample_directory;
   if(!samples){for(const root of [validationRoot,legacyValidationRoot]){if(samples)break;try{const dirs=await fs.readdir(path.join(root,'app-cache'));for(const d of dirs){const base=path.join(root,'app-cache',d);try{const hud=await readJson(path.join(base,'hud.json'));if(normalized(hud.source.path)===normalized(item.source)){samples=(await readJson(path.join(base,'sample-reference.json'))).samples;break;}}catch{}}}catch{}}}
   if(samples){try{const real=await fs.realpath(samples);if([validationRoot,legacyValidationRoot,...taskSampleRoots].some(root=>within(real,root)))frames=(await fs.readdir(samples)).filter(f=>/^\d+[.]jpg$/.test(f)).sort();}catch{}}
   for(const c of manifest.clips||[]){if(!isRecordedVideo(task,item,c.output)||!Array.isArray(manifest.outputs)||!manifest.outputs.some((file:unknown)=>typeof file==='string'&&normalized(file)===normalized(c.output)))continue;const target=path.resolve(c.output);if(!videoExtensions.has(path.extname(target).toLowerCase())||!existsSync(target))continue;const realTarget=await fs.realpath(target);if(!isRelocatedOutput(item.record,target)){const realDirectory=await fs.realpath(videoDirectory(task,item)).catch(()=>'');if(!realDirectory||!within(realTarget,realDirectory))continue;}allowedPaths.add(normalized(target));
    const stat=await fs.stat(target);if(corrected.length){for(const correction of corrected.slice().reverse()){const fix=correction.segments.find((s:any)=>Math.abs(s.start-c.segment.start)<.001&&Math.abs(s.end-c.segment.end)<.001);if(fix&&(correction.repair_schema!==2||fix.repair_applied===true))Object.assign(c,applyStatisticsCorrection(c,fix,correction.version,{path:realTarget,size:stat.size,mtime_ms:Math.floor(stat.mtimeMs),aliases:movedFrom(c)}));}}
    allowedClips.add(normalized(target));clipTasks.set(normalized(target),p);clipDirectories.set(normalized(target),item.destination);const start=Number(c.segment.start),end=Number(c.segment.end);clipDurations.set(normalized(target),Number(c.metadata?.format?.duration)||end-start);const rate=record.parameters?.fps||2;const targetTime=(start+end)/2;
    const inside=frames.filter(f=>{const t=(Number(path.parse(f).name)-.5)/rate;return t>=start&&t<=end;});const frame=inside.sort((a,b)=>Math.abs((Number(path.parse(a).name)-.5)/rate-targetTime)-Math.abs((Number(path.parse(b).name)-.5)/rate-targetTime))[0];let thumbnail:string|undefined;
    if(frame)try{thumbnail=await imageUrl(path.join(samples,frame));}catch{}
    result.clips.push({media:mediaGeometry(c.metadata),taskPath:p,source:item.source,exportedAt:stat.mtime.toISOString(),path:target,name:path.basename(target),recordedAt:recordingTime(item.source)||recordingTime(path.basename(target)),duration:Number(c.metadata?.format?.duration)||end-start,start,end,...clipStatistics(c,candidates,analysis,{path:realTarget,size:stat.size,mtime_ms:Math.floor(stat.mtimeMs),aliases:movedFrom(c)}),thumbnail});
   }
  }catch{}
  allowedPaths.add(normalized(item.destination));results.push(result);
 }
 return results;
}
let libraryRead:Promise<{results:Result[];tasks:number;errors:number}>|null=null;
let unreadableTasks:string[]=[];
const importedRoot=path.join(dataRoot,'imported'),importedManifest=path.join(importedRoot,'export.json');
const importedClips=new Set<string>();const importedFields=new Set(['account','weapons','teammates','hero','rank']);
/** 片段库记录的改写统一交给 Python（保持文件时间戳等大整数精确）；不移动、不删除任何视频。 */
function libraryRecords(command:Record<string,unknown>):Promise<any>{
 return new Promise((resolve,reject)=>{
  const proc=spawn(pythonFor('cpu'),pythonArguments('library_records.py'),{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});let text='',error='';
  const timer=setTimeout(()=>proc.kill(),5*60000);
  proc.stdout?.setEncoding('utf8');proc.stdout?.on('data',chunk=>text+=chunk);proc.stderr?.setEncoding('utf8');proc.stderr?.on('data',chunk=>error=(error+chunk).slice(-2000));
  proc.once('error',error=>{clearTimeout(timer);reject(error);});
  proc.once('close',code=>{clearTimeout(timer);if(code!==0){reject(new Error(error.trim().split(/\r?\n/).pop()||'片段库记录更新失败'));return;}try{resolve(JSON.parse(text.trim().split(/\r?\n/).pop()||'{}'));}catch(parse){reject(parse);}});
  proc.stdin?.end(JSON.stringify(command));
 });
}
let migrating=false;
const movedFrom=(clip:any):string[]=>Array.isArray(clip?.moved_from)?clip.moved_from.filter((file:unknown):file is string=>typeof file==='string'):[];
const libraryBusy=()=>!!(worker||launching||hudWorker||hudLaunching||updating||counterRepair||clipDeletions.busy||migrating);
async function readTaskRecord(file:string){try{const task=await readJson(file);return [1,2].includes(task?.version)&&Array.isArray(task.items)&&typeof task.directory==='string'?task:null;}catch{return null;}}
async function readImported(){try{const manifest=await readJson(importedManifest);return manifest?.mode==='imported'&&Array.isArray(manifest.clips)?manifest:null;}catch{return null;}}
const libraryScanRoots=()=>[output,...libraryStore.rootList()];
type MaintenanceResult={moved:number;imported:number;rejected:number};
let maintenanceRun:Promise<MaintenanceResult>|null=null;
/** 扫描输出目录与添加的目录（不限层级）：认领被移动的成片，整体移动的旧版任务改写路径，并登记尚未入库的视频。 */
function maintainLibrary(options:{autoImport:boolean;explicit?:string[]}):Promise<MaintenanceResult>{
 if(maintenanceRun)return maintenanceRun.then(():Promise<MaintenanceResult>=>maintainLibrary(options));
 maintenanceRun=(async():Promise<MaintenanceResult>=>{
  let moved=0,imported=0,rejected=0;
  const scan=await scanLibraryRoots([...libraryScanRoots(),path.join(dataRoot,'tasks')]);
  const tasks=new Map<string,any>();
  for(const file of [...scan.tasks,...await libraryStore.discover([output,path.join(dataRoot,'tasks')])]){if(tasks.has(normalized(file))||libraryStore.isIgnored(file))continue;const task=await readTaskRecord(file);if(task)tasks.set(normalized(file),{file,task});}
  const rebase=[...tasks.values()].filter(({file,task})=>task.version===1&&normalized(task.directory)!==normalized(path.dirname(file))).map(({file})=>file);
  if(rebase.length&&!libraryBusy()){try{await libraryRecords({command:'rebase',tasks:rebase});for(const file of rebase){const task=await readTaskRecord(file);if(task)tasks.set(normalized(file),{file,task});}}catch(error){diagnostics.log('warning','library','旧版任务路径更新失败',{error:String(error)});}}
  await libraryStore.rememberMany([...tasks.values()].filter(({file,task})=>task.version===2||normalized(task.directory)===normalized(path.dirname(file))).map(({file})=>file));
  const recorded=new Set<string>(),sources=new Set<string>(),missing:MissingClip[]=[];
  for(const {file,task} of tasks.values())for(const item of task.items){
   if(typeof item.source==='string')sources.add(normalized(item.source));
   const record=item.record;if(!record||!Array.isArray(record.outputs))continue;
   let durations:Map<string,number>|undefined;
   for(const [index,output] of record.outputs.entries()){
    if(typeof output!=='string'||!path.isAbsolute(output))continue;recorded.add(normalized(output));
    if(existsSync(output)||clipDeletions.isRemoved(output))continue;
    const identity=record.output_identities?.[index];if(!identity||!Number.isSafeInteger(identity.size))continue;
    if(!durations){durations=new Map();try{const manifest=await readJson(path.join(item.destination,'export.json'));for(const clip of manifest.clips||[])if(typeof clip.output==='string')durations.set(normalized(clip.output),Number(clip.metadata?.format?.duration));}catch{}}
    missing.push({recorded:output,size:identity.size,mtimeMs:Number.isFinite(identity.mtime_ns)?identity.mtime_ns/1e6:undefined,duration:durations.get(normalized(output)),task:file});
   }
  }
  const importedRecord=await readImported();
  for(const clip of importedRecord?.clips||[]){if(typeof clip.output!=='string')continue;recorded.add(normalized(clip.output));if(existsSync(clip.output))continue;const identity=clip.output_identity;if(Number.isSafeInteger(identity?.size))missing.push({recorded:clip.output,size:identity.size,mtimeMs:Number.isFinite(identity.mtime_ns)?identity.mtime_ns/1e6:undefined,duration:Number(clip.metadata?.format?.duration),manifest:importedManifest});}
  const candidates=scan.videos.filter(video=>!recorded.has(normalized(video.path))&&!sources.has(normalized(video.path))&&!originalVideos.has(normalized(video.path)));
  const moves=missing.length?matchMovedClips(missing,candidates):[];
  if(moves.length&&!libraryBusy()){
   try{await libraryRecords({command:'relocate',moves,tasks:[...new Set(moves.flatMap(move=>move.task?[move.task]:[]))],manifests:[...new Set(moves.flatMap(move=>move.manifest?[move.manifest]:[]))]});moved=moves.length;diagnostics.log('info','library','已认领移动过的成片',{count:moves.length,bases:[...new Set(moves.map(move=>move.basis))]});}
   catch(error){diagnostics.log('warning','library','移动过的成片未能认领',{error:String(error)});}
  }
  const claimed=new Set(moves.map(move=>normalized(move.to)));
  const explicit=new Set((options.explicit||[]).map(normalized));
  const fresh=(options.autoImport?candidates:candidates.filter(video=>explicit.has(normalized(video.path)))).filter(video=>!claimed.has(normalized(video.path))&&!clipDeletions.isRemoved(video.path)&&(explicit.has(normalized(video.path))||!libraryStore.isHidden(video.path)));
  const scanned=new Set(scan.videos.map(video=>normalized(video.path)));
  const extra=[...explicit].filter(file=>!scanned.has(file)&&!recorded.has(file));
  const toImport=[...fresh.map(video=>video.path),...(options.explicit||[]).filter(file=>extra.includes(normalized(file)))];
  if(toImport.length&&!libraryBusy()){
   await libraryStore.unhide(toImport.filter(file=>explicit.has(normalized(file))));
   // 自动扫描时跳过超长视频（多半是原录像）；用户手动选择的片段不受限。
   for(let i=0;i<toImport.length;i+=50){const batch=toImport.slice(i,i+50),manual=batch.filter(file=>explicit.has(normalized(file))),auto=batch.filter(file=>!explicit.has(normalized(file)));
    for(const [files,limit] of [[manual,undefined],[auto,1800]] as const){if(!files.length)continue;try{const result=await libraryRecords({command:'import',data_root:dataRoot,files,max_duration:limit});imported+=result.added.length;rejected+=result.rejected.filter((row:any)=>!row.skipped).length;}catch(error){diagnostics.log('warning','library','已有片段登记失败',{error:String(error)});}}
   }
  }
  return {moved,imported,rejected};
 })().finally(()=>{maintenanceRun=null;});
 return maintenanceRun;
}
async function collectImported():Promise<Result|null>{
 const manifest=await readImported();if(!manifest)return null;
 const result:Result={source:'已有片段',status:'complete',outputs:[],directory:importedRoot,clips:[]};
 const outputs=new Set((manifest.outputs||[]).filter((file:unknown)=>typeof file==='string').map((file:string)=>normalized(file)));
 for(const c of manifest.clips){
  if(typeof c.output!=='string'||!path.isAbsolute(c.output)||!outputs.has(normalized(c.output))||!videoExtensions.has(path.extname(c.output).toLowerCase())||libraryStore.isHidden(c.output))continue;
  const target=path.resolve(c.output);let stat;try{stat=await fs.stat(target);if(!stat.isFile())continue;}catch{continue;}
  allowedPaths.add(normalized(target));allowedClips.add(normalized(target));importedClips.add(normalized(target));clipDirectories.set(normalized(target),importedRoot);clipTasks.delete(normalized(target));
  const duration=Number(c.metadata?.format?.duration)||Number(c.segment?.end)||0;clipDurations.set(normalized(target),duration);
  const {matchKey:_matchKey,...statistics}=clipStatistics(c,[],{},{path:target,size:stat.size,mtime_ms:Math.floor(stat.mtimeMs),aliases:movedFrom(c)});
  result.clips.push({media:mediaGeometry(c.metadata),exportedAt:stat.mtime.toISOString(),path:target,name:path.basename(target),recordedAt:recordingTime(path.basename(target)),duration,start:0,end:duration,imported:true,...statistics,kills:null,damage:null,assists:null,knockdowns:null});
 }
 return result.clips.length?result:null;
}
let backgroundImport:Promise<void>|null=null;
async function collectLibrary(){
 if(libraryRead)return libraryRead;
 libraryRead=(async()=>{const last=await lastTask();if(last)await libraryStore.remember(last.path);
  // 认领移动过的成片要在读取记录前完成；新视频的登记较慢，放到后台，完成后通知界面刷新。
  try{await maintainLibrary({autoImport:false});}catch(error){diagnostics.log('warning','library','片段库整理失败',{error:String(error)});}
  const paths=await libraryStore.discover([output,path.join(dataRoot,'tasks')]);let tasks=0;const results:Result[]=[],failed:string[]=[];for(const p of paths){try{await taskInfo(p);results.push(...await collectResults(p,false));tasks++;}catch(error){failed.push(p);diagnostics.log('warning','library','任务记录无法读取',{error:String(error)});}}
  try{const imported=await collectImported();if(imported)results.push(imported);}catch(error){diagnostics.log('warning','library','已有片段记录无法读取',{error:String(error)});}
  unreadableTasks=failed;diagnostics.log('info','library','片段库载入',{tasks,unreadable:failed.length,clips:results.reduce((n,r)=>n+r.clips.length,0)});
  if(!backgroundImport&&!libraryBusy())backgroundImport=maintainLibrary({autoImport:true}).then(result=>{if(result.imported||result.moved)send({type:'library-changed',message:`已加入 ${result.imported} 段已有片段`});}).catch(error=>diagnostics.log('warning','library','后台登记已有片段失败',{error:String(error)})).finally(()=>{backgroundImport=null;});
  return{results:mergeLibrary(results),tasks,errors:failed.length};})().finally(()=>{libraryRead=null;});return libraryRead;
}
/** 原输出位置中已完成任务的成片与已登记的已有片段；未完成任务的成片留在原处，续接时仍写回原位置。 */
async function migratableClips(root:string){
 const library=await collectLibrary(),complete=new Map<string,Set<string>>();
 const files:string[]=[];
 for(const result of library.results)for(const clip of result.clips){
  const file=path.resolve(clip.path);if(!within(file,path.resolve(root)))continue;
  if(importedClips.has(normalized(file))){files.push(file);continue;}
  const taskFile=clipTasks.get(normalized(file));if(!taskFile)continue;
  if(!complete.has(taskFile)){const task=await readTaskRecord(taskFile);complete.set(taskFile,new Set((task?.items||[]).filter((item:any)=>item.status==='complete').flatMap((item:any)=>item.record?.outputs||[]).map((output:string)=>normalized(output))));}
  if(complete.get(taskFile)!.has(normalized(file)))files.push(file);
 }
 return files;
}
async function migrateClips(files:string[],from:string,to:string){
 if(libraryBusy())throw new Error('请先等待当前处理或识别结束，再迁移片段');
 migrating=true;try{return await moveClips(files,from,to);}finally{migrating=false;}
}
async function moveClips(files:string[],from:string,to:string){
 const moves:{from:string;to:string;size:number}[]=[];let failed=0;
 for(const [index,file] of files.entries()){
  const target=path.join(to,path.relative(from,file));
  try{
   if(existsSync(target))throw new Error('新位置已有同名文件');
   const stat=await fs.stat(file);await videos.release(file);await fs.mkdir(path.dirname(target),{recursive:true});
   try{await fs.rename(file,target);}
   catch(error:any){
    if(error?.code!=='EXDEV')throw error;
    // 跨磁盘：复制并保留修改时间，核对大小后才删除原文件。
    await fs.copyFile(file,target,fsConstants.COPYFILE_EXCL);await fs.utimes(target,stat.atime,stat.mtime);
    if((await fs.stat(target)).size!==stat.size){await fs.unlink(target).catch(()=>{});throw new Error('复制不完整');}
    await fs.unlink(file);
   }
   moves.push({from:file,to:target,size:stat.size});
  }catch(error){failed++;diagnostics.log('warning','library','片段迁移失败',{error:String(error)});}
  if(index%10===0||index===files.length-1)send({type:'log',message:`正在迁移片段 ${index+1}/${files.length}`});
 }
 if(moves.length){
  const tasks=[...new Set(moves.map(move=>clipTasks.get(normalized(move.from))).filter((file):file is string=>!!file))];
  // 迁移期间 libraryBusy 为真，maintainLibrary 不会同时改写记录。
  try{await libraryRecords({command:'relocate',moves,tasks,manifests:moves.some(move=>importedClips.has(normalized(move.from)))?[importedManifest]:[]});}
  catch(error){diagnostics.log('warning','library','迁移后记录更新失败，下次载入片段库时重新认领',{error:String(error)});}
 }
 return failed?`已迁移 ${moves.length} 个片段，${failed} 个未能移动（仍在原位置并保留在片段库中）`:`已迁移 ${moves.length} 个片段到新的输出位置`;
}
async function addExistingClips(files:string[],folders:string[]){
 if(libraryBusy())throw new Error('请先等待当前处理或识别结束，再添加片段');
 for(const folder of folders)await libraryStore.addRoot(folder);
 const scan=folders.length?await scanLibraryRoots(folders):{videos:[] as LibraryVideo[],tasks:[],truncated:false};
 const explicit=[...new Set([...files,...scan.videos.map(video=>video.path)].map(file=>path.resolve(file)))].filter(file=>libraryVideoExtensions.has(path.extname(file).toLowerCase()));
 const before=new Set(allowedClips);
 const result=await maintainLibrary({autoImport:false,explicit});
 if(libraryRead)await libraryRead.catch(()=>{});
 const library=await collectLibrary();
 const present=explicit.filter(file=>allowedClips.has(normalized(file)));
 const fresh=present.filter(file=>!before.has(normalized(file))).length;
 // 认领到原记录的片段恢复完整战绩与识别信息；其余按未处理过的片段加入。
 return {library,restored:Math.min(fresh,result.moved),added:Math.max(0,fresh-result.moved),existing:present.length-fresh,rejected:explicit.length-present.length,truncated:scan.truncated};
}
async function metadata(file:FileItem){await new Promise<void>(resolve=>{const executable=pythonFor();const proc=spawn(executable,pythonArguments('app_ui_info.py',file.path),{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});let result='';proc.stdout.setEncoding('utf8');proc.stdout.on('data',t=>result+=t);const timeout=setTimeout(()=>proc.kill(),20000);proc.on('error',()=>{clearTimeout(timeout);resolve();});proc.on('close',()=>{clearTimeout(timeout);try{const info=JSON.parse(result.trim());send({type:'metadata',source:file.path,...info} as WorkerEvent);}catch{send({type:'metadata',source:file.path,message:'无法读取录像信息'});}resolve();});});}
async function imports(paths:unknown):Promise<{files:FileItem[];rejected:string[]}>{if(!Array.isArray(paths)||paths.length>500)throw new Error('录像清单无效');const files:FileItem[]=[];const rejected:string[]=[];const seen=new Set<string>();for(const raw of paths){if(typeof raw!=='string'||!raw)continue;const p=path.resolve(raw);diagnostics.alias(p,'<video>');diagnostics.alias(path.basename(p),'<video>');if(seen.has(normalized(p)))continue;seen.add(normalized(p));try{const stat=await fs.stat(p);if(!stat.isFile()||!videoExtensions.has(path.extname(p).toLowerCase()))throw new Error();allowedPaths.add(normalized(p));files.push({id:normalized(p),path:p,name:path.basename(p),bytes:stat.size,status:'pending'});}catch{rejected.push(path.basename(p));}}let next=0;const pump=async()=>{while(next<files.length)await metadata(files[next++]);};void pump();void pump();return{files,rejected};}
async function performanceSnapshot(value:Options){
 const captured=normalizePerformance(value,true);let available=existsSync(pythonFor('dml'));
 if(captured.backend==='auto'&&available)available=await new Promise<boolean>(resolve=>execFile(pythonFor('dml'),['-B','-c',"import onnxruntime as ort; print('DmlExecutionProvider' in ort.get_available_providers())"],{cwd:project,windowsHide:true,timeout:10000,env:{...process.env,PYTHONUTF8:'1'}},(error,stdout)=>resolve(!error&&stdout.trim()==='True')));
 return resolvePerformance(captured,available,os.cpus().length,captured.backend==='cuda'?await cudaAvailable():false);
}
async function start(payload:any,resume=false){if(clipDeletions.busy)throw new Error('正在回收片段，请稍候再开始任务');if(migrating)throw new Error('正在迁移片段，请稍候再开始任务');if(updating)throw new Error('正在更新软件，请稍后再开始任务');if(worker&&terminal)await workerExit;if(worker||launching||hudWorker||hudLaunching)throw new Error('已有识别任务正在处理');launching=true;stopRequested=false;terminal=false;
 try{const chosen=safeOptions(payload.options,resume);if(!resume)options=chosen;await stopCounterRepair();if(maintenanceTimer){clearTimeout(maintenanceTimer);maintenanceTimer=null;}if(maintenance){maintenance.kill();await maintenanceExit;}const effective={...chosen,...await performanceSnapshot(chosen)};let request:any;
  if(resume){if(!allowedTasks.has(normalized(payload.task)))throw new Error('请先选择续接任务');const info=await taskInfo(payload.task);request={resume_task:info.path,...normalizePerformance(effective),backend:effective.backend,pipeline:effective.pipeline};currentTask=info.path;}
  else{if(!Array.isArray(payload.files)||!payload.files.length||payload.files.some((f:unknown)=>typeof f!=='string'||!allowedPaths.has(normalized(f))))throw new Error('请先导入录像');if(typeof payload.output!=='string'||!path.isAbsolute(payload.output))throw new Error('输出目录无效');output=payload.output;await save();request={...effective,files:payload.files,output:payload.output};}
  const root=path.join(validationRoot,'app-requests');await fs.mkdir(root,{recursive:true});const id=randomUUID();stopFile=path.join(root,id+'.stop');const requestPath=path.join(root,id+'.json');request.stop_file=stopFile;await fs.writeFile(requestPath,JSON.stringify(request),'utf8');if(stopRequested)await fs.writeFile(stopFile,'stop','utf8');
  const python=pythonFor(effective.backend);if(!existsSync(python))throw new Error('未找到选定设备的 Python 环境');
  const proc=spawn(python,pythonArguments('app_worker.py',requestPath),{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8'}});worker=proc;workerExit=new Promise<void>(resolve=>{resolveWorkerExit=resolve;});
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
async function stop(){stopRequested=true;if(stopFile)await fs.writeFile(stopFile,'stop','utf8');if(hudWorker||hudLaunching){hudStopRequested=true;if(hudStopFile)await fs.writeFile(hudStopFile,'stop','utf8');}}
function trusted(event:Electron.IpcMainInvokeEvent){if(!win||event.sender!==win.webContents||event.senderFrame!==win.webContents.mainFrame)throw new Error('不允许的界面请求');}
const hudRecoveryRoot=path.join(app.getPath('userData'),'hud-jobs');
let activeHudJob='';let abandoningHud=false;
// Library/checkpoint refreshes can fire faster than a snapshot finishes. Keep at
// most one running snapshot plus one queued follow-up (started after every
// caller that joined it), instead of piling up a Python process per refresh.
let recoveryRunning:Promise<any>|null=null,recoveryQueued:Promise<any>|null=null;
const RECOVERY_TIMEOUT_MS=120_000;
function recoveryMetadata(extra:Record<string,unknown>={}):Promise<any>{
 if(Object.keys(extra).length)return recoverySnapshot(extra);
 if(!recoveryRunning){recoveryRunning=recoverySnapshot({}).finally(()=>{recoveryRunning=null;});return recoveryRunning;}
 if(!recoveryQueued){recoveryQueued=recoveryRunning.catch(()=>undefined).then(()=>{recoveryQueued=null;return recoveryMetadata();});}
 return recoveryQueued;
}
async function recoverySnapshot(extra:Record<string,unknown>){
 const payload={root:hudRecoveryRoot,clips:[...clipDirectories].filter(([file])=>allowedClips.has(file)).map(([file,directory])=>({file,directory})),...extra};
 return new Promise<any>((resolve,reject)=>{
  const proc=spawn(pythonFor('cpu'),pythonArguments('hud_recovery_snapshot.py','--stdin'),{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});let text='',error='',timedOut=false;
  const timer=setTimeout(()=>{timedOut=true;proc.kill();},RECOVERY_TIMEOUT_MS);
  proc.stdout?.setEncoding('utf8');proc.stdout?.on('data',chunk=>text+=chunk);proc.stderr?.setEncoding('utf8');proc.stderr?.on('data',chunk=>error=(error+chunk).slice(-2000));
  proc.once('error',failure=>{clearTimeout(timer);reject(failure);});proc.once('close',code=>{clearTimeout(timer);if(timedOut){reject(new Error('读取识别检查点超时，请稍后刷新'));return;}if(code!==0){reject(new Error(error||'无法读取识别检查点'));return;}try{const result=JSON.parse(text);if(Array.isArray(result.jobs))result.jobs=result.jobs.map((job:any)=>job.id===activeHudJob&&job.status!=='completed'?{...job,status:'running'}:job);resolve(result);}catch(error){reject(error);}});
  proc.stdin?.end(JSON.stringify(payload));
 });
}
async function enrichHud(files:unknown,fields:unknown,mode:unknown='missing',recovery:Record<string,unknown>={}){
 if(updating)throw new Error('正在更新软件，请稍后补充信息');
 if(clipDeletions.busy||worker||launching||hudWorker||hudLaunching||migrating)throw new Error('请先等待当前处理结束');
 const selectedFiles=safeHudFiles(files,allowedClips,normalized);
 if(!Array.isArray(fields)||!fields.length||fields.some(field=>!['account','weapons','teammates','hero','rank','statistics','opponents','event_weapons'].includes(field)))throw new Error('请选择要补充的HUD信息');
 if(mode!=='missing'&&mode!=='refresh')throw new Error('HUD识别模式无效');
 const chosen={...options};
 for(const file of selectedFiles){diagnostics.alias(file,'<clip>');diagnostics.alias(path.basename(file),'<clip>');}hudLaunching=true;hudStopRequested=false;let requestPath='';
 try{
 const snapshot=await performanceSnapshot(chosen);
 if(counterRepair){send({type:'hud-info-start',index:0,total:selectedFiles.length,message:'正在结束后台记录处理'});await stopCounterRepair();}
 if(maintenance){maintenance.kill();await maintenanceExit;}
 if(hudStopRequested)throw new Error('识别已停止');
 const grouped=new Map<string,string[]>();for(const file of selectedFiles){const dir=clipDirectories.get(normalized(file));if(!dir)throw new Error('片段没有对应任务记录');const group=grouped.get(dir);if(group)group.push(file);else grouped.set(dir,[file]);}
 // 未经本软件处理的已有片段没有原录像和交战分析，只读取画面中的 HUD 信息。
 const visual=(list:unknown[])=>list.filter(field=>importedFields.has(String(field)));
 const jobs=[...grouped].map(([directory,files])=>normalized(directory)===normalized(importedRoot)?{directory,files,fields:visual(fields)}:{directory,files}).filter(job=>!('fields' in job)||job.fields!.length);
 if(!jobs.length)throw new Error('已有片段只能补充账号、队友、武器、英雄和段位');
 if(recovery.selection&&typeof recovery.selection==='object')recovery={...recovery,selection:Object.fromEntries(Object.entries(recovery.selection as Record<string,unknown[]>).map(([file,list])=>[file,importedClips.has(normalized(file))?visual(list):list]).filter(([,list])=>(list as unknown[]).length))};
 const root=path.join(validationRoot,'app-requests');await fs.mkdir(root,{recursive:true});requestPath=path.join(root,randomUUID()+'.json');hudStopFile=requestPath+'.stop';
 await fs.writeFile(requestPath,JSON.stringify({stop_file:hudStopFile,jobs,fields,force:mode==='refresh',...normalizePerformance(snapshot),backend:snapshot.backend,recovery_root:hudRecoveryRoot,...recovery}),'utf8');if(hudStopRequested)await fs.writeFile(hudStopFile,'stop','utf8');
 send({type:'hud-info-start',index:0,total:selectedFiles.length,message:mode==='refresh'?'准备重新识别':'准备补充未识别信息'});
 return await new Promise<HudEnrichmentResult>((resolve,reject)=>{
  const proc=spawn(pythonFor(snapshot.backend),pythonArguments('hud_enrichment.py',requestPath),{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});hudWorker=proc;
  let done:HudEnrichmentResult|null=null,stderr='';
  const lines=new JsonLines(event=>{if(event.type==='hud-info-checkpoint'&&typeof event.job_id==='string')activeHudJob=event.job_id;if(event.type==='hud-info-done')done=event as unknown as typeof done;else send(event as unknown as WorkerEvent);},()=>{});
  proc.stdout?.on('data',chunk=>lines.push(chunk));proc.stderr?.setEncoding('utf8');proc.stderr?.on('data',chunk=>stderr=(stderr+chunk).slice(-2000));
  proc.once('error',reject);proc.once('close',code=>{lines.end();hudWorker=null;if(code===0&&done)resolve(done);else reject(new Error(abandoningHud?'已放弃本次识别，进度记录已删除':code===75?'识别已停止，已读取的信息已保存':stderr||'信息识别中断，可重新继续'));});
 });}finally{activeHudJob='';hudWorker=null;hudLaunching=false;if(requestPath)await fs.unlink(requestPath).catch(()=>{});if(hudStopFile)await fs.unlink(hudStopFile).catch(()=>{});hudStopFile='';scheduleMaintenance(true);if(closing&&!worker&&!launching){closing=false;if(!win.isDestroyed())win.close();}}
}
async function abandonHud(id?:unknown){
 if(clipDeletions.busy||migrating)throw new Error('正在回收或迁移片段，请稍后再放弃');
 if(id!==undefined&&(typeof id!=='string'||!/^[a-f0-9]{32}$/.test(id)))throw new Error('检查点编号无效');
 const jobId=typeof id==='string'?id:activeHudJob,worker=hudWorker;
 if(worker){
  // 让工作进程先在提交边界停下，再删除检查点；否则它退出时会把进度重新写回去。
  abandoningHud=true;
  try{
   await stop();
   await new Promise<void>(resolve=>{
    const timer=setTimeout(()=>{try{worker.kill();}catch{}resolve();},8000);
    worker.once('close',()=>{clearTimeout(timer);resolve();});
   });
  }finally{abandoningHud=false;}
 }
 if(!jobId)return {abandoned:''};
 await recoverySnapshot({action:'abandon',id:jobId});
 return {abandoned:jobId};
}

function normalizeMirror(value:unknown){
 if(typeof value!=='string')throw new Error('更新加速地址无效');
 const text=value.trim();
 if(!text)return '';
 let parsed:URL;
 try{parsed=new URL(text);}catch{throw new Error('更新加速地址不是合法链接');}
 if(parsed.protocol!=='https:')throw new Error('更新加速地址必须使用 https');
 if(parsed.search||parsed.hash||parsed.username||parsed.password)throw new Error('更新加速地址不能带查询参数或账号信息');
 return parsed.href.endsWith('/')?parsed.href:parsed.href+'/';
}

/** 用与检查更新相同的请求验证加速前缀是否真的可用。 */
async function testMirror(value:unknown){
 const mirror=normalizeMirror(value),endpoint=(mirror||'')+RELEASES_API,started=Date.now();
 try{
  const response=await net.fetch(endpoint,{headers:{Accept:'application/vnd.github+json','User-Agent':`Apex-Highlight-Clipper/${app.getVersion()}`},signal:AbortSignal.timeout(12000)});
  const ms=Date.now()-started;
  if(!response.ok)return{ok:false,ms,message:`服务返回 ${response.status}`};
  const raw=await response.text();
  if(!Array.isArray(JSON.parse(raw)))return{ok:false,ms,message:'返回内容不是版本列表'};
  return{ok:true,ms,message:'连接正常'};
 }catch(error){
  return{ok:false,ms:Date.now()-started,message:error instanceof Error?error.message:'连接失败'};
 }
}

function handle(name:string,fn:(...args:any[])=>any){ipcMain.handle(name,async(event,...args)=>{trusted(event);try{return await fn(...args);}catch(error){diagnostics.log('error','ipc:'+name,error instanceof Error?error.message:String(error),{stack:error instanceof Error?error.stack:undefined});throw error;}});}

async function diagnosticTask(){
 const attachments:{name:string;text:string}[]=[];let file=currentTask;
 if(!file)for(const root of [validationRoot,legacyValidationRoot]){try{file=(await readJson(path.join(root,'app-last-task.json'))).task;if(file)break;}catch{}}
 let summary:unknown=null;const traceFiles=[path.join(updateRoot,'install.log')],traceRoots=[validationRoot,legacyValidationRoot,updateRoot];
 try{if(file){const task=await readJson(file);validateTaskStorage(task,file);traceRoots.push(task.directory);traceFiles.push(path.join(task.directory,'error.log'));summary={version:task.version,finished:task.finished,options:safeOptions({...defaults,...task.request,...normalizePerformance(task.request)},true),items:task.items.slice(0,500).map((item:any,index:number)=>{diagnostics.alias(item.source,`<video-${index+1}>`);diagnostics.alias(path.basename(item.source),`<video-${index+1}>`);const cache=item.analysis_cache||item.record?.analysis_cache;if(['error','running'].includes(item.status)&&typeof cache==='string'&&path.isAbsolute(cache))traceFiles.push(path.join(cache,'error.log'));return{index:index+1,status:item.status,stage:item.stage,error:item.record?.error,outputs:item.record?.outputs?.length||0};})};}}
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
 try{const saved=await readJson(path.join(app.getPath('userData'),'preferences.json'));windowPlacement=restoreWindowPlacement(saved.windowPlacement,screen.getAllDisplays().map(display=>display.workArea),screen.getPrimaryDisplay().workArea);playerAudio=normalizePlayerAudio(saved.playerAudio);excludedTeammates=normalizeTeammateExclusions(saved.excludedTeammates);if(typeof saved.updatePreferences?.autoCheck==='boolean')updateInfo.autoCheck=saved.updatePreferences.autoCheck;if(typeof saved.updatePreferences?.mirror==='string')updateMirror=saved.updatePreferences.mirror;updateInfo=restoreUpdateInfo(saved.updateCache,app.getVersion(),updateInfo.autoCheck);updateInfo={...updateInfo,mirror:updateMirror};preferences={...preferences,...saved.preferences,...normalizeAnimationPreferences(saved.preferences)};const previousOptions={...saved.options};if(!saved.optionDefaultsVersion&&previousOptions.gap===35&&previousOptions.pre===10&&previousOptions.post===15){previousOptions.gap=defaults.gap;previousOptions.pre=defaults.pre;previousOptions.post=defaults.post;}options=safeOptions({...defaults,...previousOptions,...normalizePerformance(previousOptions),fps:saved.options?.fps<1?defaults.fps:saved.options?.fps??defaults.fps});output=saved.output||output;}catch{}
 diagnostics.alias(dataRoot,'<data>');diagnostics.alias(output,'<output>');diagnostics.log('info','startup','设置已载入',{options,theme:preferences.mode});
 protocol.handle('apex-media',async request=>{try{const url=new URL(request.url);if(url.hostname==='video')return videos.respond(request);const p=images.get(url.pathname.slice(1));if(url.hostname!=='image'||!p)return new Response('Not found',{status:404});const data=await fs.readFile(p);return new Response(data,{headers:{'Content-Type':p.endsWith('.png')?'image/png':'image/jpeg','Cache-Control':'private, max-age=60'}});}catch{return new Response('Unavailable',{status:404});}});
 const initial=theme();const dark=preferences.mode==='dark'||(preferences.mode==='system'&&initial.dark);
 const placement=windowPlacement||restoreWindowPlacement(null,[],screen.getPrimaryDisplay().workArea);
 win=new BrowserWindow({...placement,minWidth:Math.min(760,placement.width),minHeight:Math.min(620,placement.height),show:false,title:'Apex Highlight Clipper',icon:path.join(__dirname,'../../dist/brand/cat-clapperboard.png'),backgroundColor:'#211e1a',titleBarStyle:'hidden',titleBarOverlay:false,autoHideMenuBar:true,webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
 win.webContents.on('console-message',details=>{if(details.level==='error')diagnostics.log('error','renderer-console',details.message,{line:details.lineNumber,source:details.sourceId});});
 win.webContents.on('render-process-gone',(_event,details)=>diagnostics.log('error','renderer-process','界面进程退出',details));
 win.on('unresponsive',()=>diagnostics.log('warning','renderer','界面无响应'));
 const rememberPlacement=()=>{if(win.isDestroyed()||win.isFullScreen())return;windowPlacement={...win.getNormalBounds(),maximized:win.isMinimized()?windowPlacement?.maximized===true:win.isMaximized()};};
 const persistPlacement=()=>{rememberPlacement();clearTimeout(placementTimer);placementTimer=setTimeout(()=>{placementTimer=undefined;void save().catch(error=>diagnostics.log('error','window-placement',String(error)));},300);};
 win.on('move',persistPlacement);win.on('resize',persistPlacement);win.on('maximize',persistPlacement);win.on('unmaximize',persistPlacement);
 const windowState=()=>({maximized:win.isMaximized()});
 const publishWindowState=()=>{if(!win.isDestroyed())win.webContents.send('window-state',windowState());};
 win.on('maximize',publishWindowState);win.on('unmaximize',publishWindowState);win.on('restore',publishWindowState);
 handle('window-state',windowState);
 handle('window-command',(command:unknown)=>{if(command==='minimize')win.minimize();else if(command==='maximize'){if(win.isMaximized())win.unmaximize();else win.maximize();}else if(command==='close')win.close();else throw new Error('窗口操作无效');});
 handle('diagnostics-info',()=>diagnostics.info());
 let rendererReports=0,rendererReportWindow=Date.now();
 handle('renderer-diagnostic',(report:unknown)=>{if(!report||typeof report!=='object')return;const{type,message,stack}=report as Record<string,unknown>;if(!['error','action'].includes(String(type))||typeof message!=='string')return;if(Date.now()-rendererReportWindow>60000){rendererReports=0;rendererReportWindow=Date.now();}if(++rendererReports>120)return;diagnostics.log(type==='error'?'error':'info','renderer-'+type,message.slice(0,2000),{stack:typeof stack==='string'?stack.slice(0,8000):undefined});});
 handle('open-diagnostics',async()=>{const info=await diagnostics.info();if(!info.available)throw new Error(info.message||'日志尚未生成');const error=await shell.openPath(diagnostics.directory);if(error)throw new Error(error);});
 handle('export-diagnostics',async()=>{const choice=await dialog.showSaveDialog(win,{title:'导出诊断包',defaultPath:path.join(app.getPath('desktop'),`AHC-diagnostics-v${app.getVersion()}-${new Date().toISOString().slice(0,10)}.zip`),filters:[{name:'诊断包 ZIP',extensions:['zip']}]});if(choice.canceled||!choice.filePath)return null;const file=choice.filePath.endsWith('.zip')?choice.filePath:choice.filePath+'.zip',task=await diagnosticTask();let gpu:unknown;try{const info=await app.getGPUInfo('basic') as Record<string,unknown>;if(Array.isArray(info.gpuDevice))gpu=info.gpuDevice.map(device=>Object.fromEntries(['vendorId','deviceId','driverVendor','driverVersion','deviceString','active'].filter(key=>device[key]!==undefined).map(key=>[key,device[key]])));}catch{}await diagnostics.export(file,{createdAt:new Date().toISOString(),version:app.getVersion(),system:{platform:process.platform,release:os.release(),arch:process.arch,cpu:os.cpus()[0]?.model,logicalCores:os.cpus().length,memoryMiB:Math.round(os.totalmem()/1024**2),versions:process.versions,gpu},options,theme:preferences,task:task.summary,library:{unreadable:unreadableTasks.length},update:{status:updateInfo.status,latestVersion:updateInfo.latestVersion,installState:updateInfo.installState,installMessage:updateInfo.installMessage},runtime:{cpu:existsSync(pythonFor('cpu')),dml:existsSync(pythonFor('dml')),cuda:existsSync(pythonFor('cuda'))}},task.attachments);return file;});
 handle('open-feedback',()=>shell.openExternal('https://github.com/LilycleHeart/apex-highlight-clipper/issues/new?title='+encodeURIComponent(`[v${app.getVersion()}] 问题反馈`)+'&body='+encodeURIComponent(`软件版本：v${app.getVersion()}\n\n问题现象：\n\n复现步骤：\n1. \n\n请将“剪辑设置 → 诊断与反馈 → 导出诊断包”生成的 ZIP 拖入此处上传。`)));
 let shown=false;const showWindow=()=>{if(shown||win.isDestroyed())return;shown=true;if(placement.maximized)win.maximize();win.show();scheduleUpdate();scheduleMaintenance();};handle('ui-ready',showWindow);setTimeout(showWindow,10000).unref();
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));win.webContents.on('will-navigate',event=>event.preventDefault());
 win.on('minimize',()=>send({type:'visibility',hidden:true}));win.on('hide',()=>send({type:'visibility',hidden:true}));win.on('restore',()=>send({type:'visibility',hidden:false}));win.on('show',()=>send({type:'visibility',hidden:false}));
 win.on('close',event=>{if(hudWorker||hudLaunching){event.preventDefault();if(!closing){closing=true;send({type:'close-request',message:'正在停止信息识别，已读结果会保留'});void stop();}return;}if(counterRepair){event.preventDefault();if(!closing){closing=true;void stopCounterRepair().finally(()=>{closing=false;if(!win.isDestroyed())win.close();});}return;}repairWorker?.kill();repairWorker=null;if(worker||launching){event.preventDefault();if(!closing){closing=true;send({type:'close-request',message:'窗口将在断点保存后关闭'});void stop();}}else if(!closeSaveFinished){event.preventDefault();clearTimeout(placementTimer);placementTimer=undefined;rememberPlacement();void save().catch(error=>diagnostics.log('error','window-placement',String(error))).then(()=>flushSaves()).then(()=>{closeSaveFinished=true;if(!win.isDestroyed())win.close();});}});
 const changed=()=>{if(!win.isDestroyed())win.webContents.send('system-theme',theme());};nativeTheme.on('updated',changed);systemPreferences.on('accent-color-changed',changed);systemPreferences.on('color-changed',changed);
 handle('chrome',(color:string,foreground:string)=>{if(!/^#[\da-f]{6}$/i.test(color)||!/^#[\da-f]{6}$/i.test(foreground))throw new Error('窗口配色无效');win.setBackgroundColor(color);});
 handle('bootstrap',async()=>({output,options,preferences,playerAudio,excludedTeammates,theme:theme(),development,lastTask:await lastTask(),backendAvailable:existsSync(pythonFor('dml')),cudaAvailable:await cudaAvailable(),logicalCores:os.cpus().length,update:updateInfo}));
 handle('check-update',async()=>{await updater.check();await saveChain;return updateInfo;});
 handle('set-update-mirror',async(value:unknown)=>{updateMirror=normalizeMirror(value);publishUpdate({...updateInfo,mirror:updateMirror});await save();return updateInfo;});
 handle('test-update-mirror',(value:unknown)=>testMirror(value));
 handle('install-update',async()=>{
  if(updating)throw new Error('更新正在进行');
  if(worker||launching||hudWorker||hudLaunching||repairWorker)throw new Error('请先暂停或完成当前任务后更新');
  if(!app.isPackaged)throw new Error('开发预览请使用发布页安装正式程序');
  updating=true;let scheduled=false;
  const report=(installState:NonNullable<UpdateInfo['installState']>,installProgress?:number,installMessage?:string)=>{if(installState!==updateInfo.installState||installProgress!==undefined&&installProgress%10===0)diagnostics.log(installState==='error'?'error':'info','update-install',installState,{progress:installProgress,message:installMessage});updateInfo={...updateInfo,installState,installProgress,installMessage};if(!win.isDestroyed())win.webContents.send('update-status',updateInfo);};
  try{
   const latest=await updater.check();if(latest.status!=='available')throw new Error(latest.message||'当前没有可安装的新版本');if(!latest.installer)throw new Error('该版本没有可校验的安装包，请使用发布页安装');
   const {target,helper}=installationPaths(app.getPath('exe'));
   if(!existsSync(path.join(project,'app_worker.py'))||!existsSync(path.join(project,'runtime/runtime-layout.json'))||!existsSync(helper))throw new Error('无法确定程序安装位置，请使用发布页安装');
   updateAbort=new AbortController();report('downloading',0);
   const installer=await downloadInstaller(latest.installer,updateRoot,(url,init)=>net.fetch(url,init),percent=>report('downloading',percent),updateAbort.signal,updateMirror);updateAbort=null;
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
 handle('choose-output',async()=>{const result=await dialog.showOpenDialog(win,{properties:['openDirectory','createDirectory'],defaultPath:output});if(result.canceled)return null;
  const next=result.filePaths[0],previous=output;
  if(normalized(next)!==normalized(previous)){
   const files=await migratableClips(previous);
   if(files.length){
    if(within(path.resolve(next),path.resolve(previous)))throw new Error('新位置不能放在原输出位置里面，请选择其他文件夹');
    const choice=await dialog.showMessageBox(win,{type:'question',title:'更改输出位置',message:`原输出位置里有 ${files.length} 个片段，是否迁移到新位置？`,detail:'迁移：把这些片段移动到新位置，保持原来的子文件夹结构，战绩和识别信息随片段保留。\n不迁移：原位置的片段继续在片段库中显示，之后的新任务输出到新位置。',buttons:['迁移片段','不迁移','取消'],defaultId:0,cancelId:2,noLink:true});
    if(choice.response===2)return null;
    await libraryStore.addRoot(previous);
    output=next;allowedPaths.add(normalized(output));await save();
    if(choice.response===0)void migrateClips(files,previous,next).then(summary=>send({type:'library-changed',message:summary})).catch(error=>send({type:'library-changed',message:'片段迁移未完成：'+String(error).replace(/^Error: /,'')}));
    return output;
   }
   await libraryStore.addRoot(previous);
  }
  output=next;allowedPaths.add(normalized(output));await save();return output;});
 handle('player-audio',async(value:PlayerAudioPreferences)=>{if(!value||!Number.isFinite(value.volume)||value.volume<0||value.volume>1||typeof value.muted!=='boolean'||!Number.isFinite(value.lastAudibleVolume)||value.lastAudibleVolume<=0||value.lastAudibleVolume>1)throw new Error('音量设置无效');playerAudio=normalizePlayerAudio(value);await save();});
 handle('teammate-exclusion',(name:unknown,excluded:unknown)=>{const request=teammateWrites.catch(()=>{}).then(async()=>{const previous=excludedTeammates,next=changeTeammateExclusion(previous,name,excluded);if(next!==previous){excludedTeammates=next;try{await save();}catch(error){excludedTeammates=previous;throw error;}}return [...excludedTeammates];});teammateWrites=request;return request;});
 handle('preferences',async(p:ThemePreferences)=>{if(!['system','light','dark'].includes(p.mode)||p.seed!==null&&!/^#[\da-f]{6}$/i.test(p.seed)||typeof p.reduceMotion!=='boolean'||!['flat','sketch'].includes(p.mascotStyle)||typeof p.mascotEnabled!=='boolean')throw new Error('外观选项无效');preferences={...p,...normalizeAnimationPreferences(p)};await save();});
 handle('options',async(o:Options,p:string)=>{options=safeOptions(o);if(typeof p==='string'&&path.isAbsolute(p))output=p;await save();});
 handle('performance-options',async(value:unknown)=>{options={...options,...normalizePerformance(value,true)};await save();});
 handle('start',p=>start(p));handle('stop',stop);handle('resume',p=>start(p,true));handle('last-task',lastTask);
 handle('task',p=>{if(typeof p!=='string'||!allowedTasks.has(normalized(p)))throw new Error('请先选择任务');return taskInfo(p);});
 handle('choose-task',async()=>{const result=await dialog.showOpenDialog(win,{properties:['openFile'],filters:[{name:'任务记录 task.json',extensions:['json']}]});if(result.canceled)return null;const info=await taskInfo(result.filePaths[0]);await libraryStore.remember(info.path,true);return info;});
 handle('results',collectResults);handle('library',collectLibrary);
 handle('ignore-library-errors',async()=>{if(libraryRead)await libraryRead;await libraryStore.ignore(unreadableTasks);return collectLibrary();});
 handle('enrich-hud',(files,fields,mode)=>enrichHud(files,fields,mode));
 handle('abandon-hud',(id)=>abandonHud(id));
  handle('hud-recovery',()=>recoveryMetadata());
  handle('resume-hud',async(id:unknown)=>{
   if(typeof id!=='string'||!/^[a-f0-9]{32}$/.test(id))throw new Error('检查点编号无效');
   const saved=await recoveryMetadata({action:'load',id});
   const files=Object.values(saved.clips).map((row:any)=>row.file);
   return enrichHud(files,saved.request.fields,saved.request.force?'refresh':'missing',{resume_job:id});
  });
  handle('upgrade-hud',async(selection:unknown,includeUnknown:unknown=false)=>{
   if(!Array.isArray(selection)||!selection.length||typeof includeUnknown!=='boolean')throw new Error('请选择待更新的片段字段');
   const current=await recoveryMetadata(),statuses=new Map<string,any>(current.clips.map((clip:any)=>[normalized(clip.file),clip]));
   const selected:Record<string,string[]>={};
   for(const row of selection){
    if(!row||typeof row.file!=='string'||!Array.isArray(row.fields))throw new Error('待更新字段无效');
    const clip=statuses.get(normalized(row.file));if(!clip)throw new Error('片段尚未载入');
    const fields=clip.fields.filter((field:any)=>row.fields.includes(field.field)&&(field.status==='old'||includeUnknown&&field.status==='unknown')).map((field:any)=>field.field);
    if(fields.length)selected[normalized(row.file)]=[...new Set([...(selected[normalized(row.file)]||[]),...fields])] as string[];
   }
   const files=Object.keys(selected),fields=[...new Set(Object.values(selected).flat())];if(!files.length)throw new Error('所选字段已是当前版本，无需重新识别');
   return enrichHud(files,fields,'refresh',{job_kind:'upgrade',selection:selected});
  });
 let sharingClips=false;handle('share-clips',async(files:unknown)=>{if(sharingClips)throw new Error('正在打开 QQ 分享，请稍候');sharingClips=true;try{const result=await shareFiles(files,allowedClips,uri=>shell.openExternal(uri));diagnostics.log('info','qq-share','已请求QQ会话选择',{count:result.count,command:result.command});return result;}finally{sharingClips=false;}});
 handle('choose-library-root',async()=>{const selected=await dialog.showOpenDialog(win,{title:'添加历史输出目录',properties:['openDirectory']});if(selected.canceled)return false;await libraryStore.addRoot(selected.filePaths[0]);return true;});
 handle('video-url',file=>videos.url(file));
 handle('delete-clip',async(file:string)=>{
  if(typeof file==='string'&&importedClips.has(normalized(file))){
   // 已有片段不是本软件生成的文件：只移出片段库，视频保留在原处。
   if(libraryBusy())throw new Error('请先等待当前处理或识别结束');
   await libraryStore.hide([file]);await libraryRecords({command:'remove-imported',data_root:dataRoot,files:[file]});
   importedClips.delete(normalized(file));allowedClips.delete(normalized(file));await videos.release(file);diagnostics.log('info','library','已有片段已移出片段库');return;
  }
  await clipDeletions.remove(file);allowedClips.delete(normalized(file));diagnostics.log('info','library','片段已移至回收站');});
 handle('add-existing-clips',async()=>{const selected=await dialog.showOpenDialog(win,{title:'添加已有片段',properties:['openFile','multiSelections'],filters:[{name:'视频',extensions:[...libraryVideoExtensions].map(x=>x.slice(1))}]});if(selected.canceled||!selected.filePaths.length)return null;return addExistingClips(selected.filePaths,[]);});
 handle('add-existing-folder',async()=>{const selected=await dialog.showOpenDialog(win,{title:'添加片段文件夹（包含所有子文件夹）',properties:['openDirectory','multiSelections']});if(selected.canceled||!selected.filePaths.length)return null;return addExistingClips([],selected.filePaths);});
 handle('thumbnail-url',async(file:string)=>{if(typeof file!=='string'||!allowedClips.has(normalized(file)))throw new Error('只允许读取片段库中已导出的录像');return imageUrl(await thumbnails.get(file,clipDurations.get(normalized(file))||0));});
 handle('thumbnail-stats',()=>thumbnails.stats());
 handle('open',async(p:string,folder=false)=>{if(typeof p!=='string'||!allowedPaths.has(normalized(p))&&normalized(p)!==normalized(output))throw new Error('只允许打开本任务的录像或成片');const stat=await fs.stat(p);if(!stat.isDirectory()&&!videoExtensions.has(path.extname(p).toLowerCase()))throw new Error('只允许打开录像或输出文件夹');if(folder)shell.showItemInFolder(p);else{const error=await shell.openPath(p);if(error)throw new Error(error);}});
 if(process.env.APEX_UI_VALIDATE==='1'){
  handle('validation-import',imports);handle('validation-task',taskInfo);handle('validation-project',()=>project);
 }
 const renderer=path.join(__dirname,'../../dist/index.html');if(process.env.APEX_UI_DEV_URL)await win.loadURL(process.env.APEX_UI_DEV_URL);else await win.loadFile(renderer);
 if(app.isPackaged&&path.basename(project)==='resources')setTimeout(()=>{void pruneLegacyLauncher(path.dirname(project)).catch(error=>diagnostics.log('info','layout-migration',String(error)));},2000).unref();
}).catch(error=>{diagnostics.fatal(error instanceof Error?error:new Error(String(error)));dialog.showErrorBox('Apex 启动失败',String(error));app.quit();});
app.on('window-all-closed',()=>app.quit());
app.on('before-quit',()=>{updateAbort?.abort();if(maintenanceTimer)clearTimeout(maintenanceTimer);maintenance?.kill();hudWorker?.kill();thumbnails.dispose();});
