import {app,BrowserWindow,dialog,ipcMain,nativeTheme,systemPreferences,protocol,shell,net} from 'electron';
import {spawn,ChildProcess} from 'node:child_process';
import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import path from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import {JsonLines,safeOptions,videoExtensions} from './protocol';
import {defaults,Options,ThemePreferences,WorkerEvent,TaskInfo,Result,FileItem,SystemTheme,UpdateInfo} from '../src/shared';
import {clipStatistics,recordingTime} from '../src/clipStats';
import {UpdateChecker,shouldAutoCheck,releasePage,restoreUpdateInfo} from './updates';
import {VideoRegistry} from './media';

protocol.registerSchemesAsPrivileged([{scheme:'apex-media',privileges:{standard:true,secure:true,supportFetchAPI:true,stream:true}}]);
if(process.env.APEX_UI_TEST_HOME)app.setPath('userData',process.env.APEX_UI_TEST_HOME);
else {const legacy=path.join(app.getPath('appData'),'Apex交战剪辑');if(existsSync(path.join(legacy,'preferences.json')))app.setPath('userData',legacy);}
function locateProject(){if(process.env.APEX_PROJECT_ROOT)return path.resolve(process.env.APEX_PROJECT_ROOT);for(const base of [__dirname,app.getAppPath(),path.dirname(app.getPath('exe'))]){let dir=base;for(let i=0;i<8;i++){if(existsSync(path.join(dir,'app_worker.py')))return dir;const next=path.dirname(dir);if(next===dir)break;dir=next;}}throw new Error('未找到剪辑内核。请将程序保留在项目目录内，或设置 APEX_PROJECT_ROOT。');}
const project=locateProject();
function pythonFor(backend:'cpu'|'dml'='cpu'){const bundled=path.join(project,'runtime',backend,'python.exe');return existsSync(bundled)?bundled:path.join(project,backend==='dml'?'.gpu-venv/Scripts/python.exe':'.venv/Scripts/python.exe');}
const development=!app.isPackaged||process.argv.includes('--preview');
let win:BrowserWindow;let worker:ChildProcess|null=null;let launching=false;let stopFile='';let stopRequested=false;let closing=false;let terminal=false;let currentTask='';let currentSource='';let eventChain=Promise.resolve();
let workerExit:Promise<void>=Promise.resolve();let resolveWorkerExit:(()=>void)|null=null;let closeSaveFinished=false;
let preferences:ThemePreferences={mode:'system',seed:null,reduceMotion:false,mascotStyle:'flat',mascotEnabled:true};let options:Options={...defaults};let output=path.join(project,'output');
let updateInfo:UpdateInfo={status:'idle',currentVersion:app.getVersion(),autoCheck:true};let updateTimer:ReturnType<typeof setTimeout>|null=null;
function publishUpdate(info:UpdateInfo){updateInfo=info;if(info.status!=='checking')void save().catch(()=>{});if(win&&!win.isDestroyed())win.webContents.send('update-status',info);}
const updater=new UpdateChecker(app.getVersion(),(url,init)=>net.fetch(url,init),()=>updateInfo,publishUpdate);
function scheduleUpdate(){if(updateTimer)clearTimeout(updateTimer);updateTimer=setTimeout(()=>{updateTimer=null;if(shouldAutoCheck(updateInfo))void updater.check().catch(()=>{});},3000);updateTimer.unref();}
const allowedPaths=new Set<string>();const allowedTasks=new Set<string>();const images=new Map<string,string>();const imageKeys=new Map<string,string>();
const allowedClips=new Set<string>();const videos=new VideoRegistry(file=>allowedClips.has(normalized(file)));
const normalized=(p:string)=>path.resolve(p).toLowerCase();
const within=(child:string,parent:string)=>{const relative=path.relative(parent,child);return relative===''||(!relative.startsWith('..'+path.sep)&&relative!=='..'&&!path.isAbsolute(relative));};
const readJson=async(p:string)=>JSON.parse((await fs.readFile(p,'utf8')).replace(/^\uFEFF/,''));
function send(e:WorkerEvent){if(win&&!win.isDestroyed())win.webContents.send('worker-event',e);}
function theme():SystemTheme{let accent='#526b4a';let reduceMotion=false;try{const color=systemPreferences.getAccentColor();if(/^[\da-f]{8}$/i.test(color))accent='#'+color.slice(0,6);}catch{}try{reduceMotion=systemPreferences.getAnimationSettings().prefersReducedMotion;}catch{}return{accent,dark:nativeTheme.shouldUseDarkColors,reduceMotion};}
let saveChain=Promise.resolve();
async function save(){const snapshot=JSON.stringify({preferences,options,output,updatePreferences:{autoCheck:updateInfo.autoCheck},updateCache:updateInfo.status==='checking'?undefined:updateInfo});saveChain=saveChain.catch(()=>{}).then(async()=>{await fs.mkdir(app.getPath('userData'),{recursive:true});const target=path.join(app.getPath('userData'),'preferences.json');await fs.writeFile(target+'.tmp',snapshot,'utf8');await fs.rename(target+'.tmp',target);});return saveChain;}
async function imageUrl(p:string){
 const real=await fs.realpath(p);if(!['.jpg','.jpeg','.png'].includes(path.extname(real).toLowerCase()))throw new Error('预览格式无效');
 const validation=await fs.realpath(path.join(project,'validation'));if(!within(real,validation))throw new Error('预览路径不属于分析缓存');
 let key=imageKeys.get(real);if(!key){key=randomUUID();images.set(key,real);imageKeys.set(real,key);if(images.size>300){const oldest=images.keys().next().value!;imageKeys.delete(images.get(oldest)!);images.delete(oldest);}}
 return `apex-media://image/${key}`;
}
async function taskInfo(p:string):Promise<TaskInfo>{const task=await readJson(p);if(task.version!==1||normalized(task.directory)!==normalized(path.dirname(p))||!Array.isArray(task.items))throw new Error('任务记录格式不正确');allowedTasks.add(normalized(p));allowedPaths.add(normalized(task.directory));for(const item of task.items)allowedPaths.add(normalized(item.source));return{path:p,directory:task.directory,output:task.request.output||path.dirname(task.directory),finished:task.finished,legacyRule:!task.result_filter_version,samplingWarning:task.request.fps<1?'旧任务低采样率可能漏掉交战；新建任务建议至少1帧/秒':'',options:safeOptions({...defaults,...task.request},true),items:task.items.map((i:any)=>({id:normalized(i.source),path:i.source,name:path.basename(i.source),status:i.status==='error'?'error':i.status==='complete'?'complete':i.status==='running'?'stopped':'pending',missing:!existsSync(i.source),error:i.record?.error}))};}
async function lastTask(){try{const record=await readJson(path.join(project,'validation/app-last-task.json'));return await taskInfo(record.task);}catch{return null;}}
const repairedCounters=new Set<string>();let counterRepair:Promise<void>|null=null;let repairWorker:ChildProcess|null=null;
async function repairLegacyCounters(task:any){
 if(counterRepair){await counterRepair;}const records:any[]=[];
 for(const item of task.items){const record=item.record;if(!record||record.status!=='complete'||repairedCounters.has(normalized(item.destination))||normalized(record.directory)!==normalized(item.destination)||!within(path.resolve(item.destination),path.resolve(task.directory)))continue;
  if(typeof record.analysis_cache!=='string'||typeof record.sample_directory!=='string'||!within(path.resolve(record.analysis_cache),path.join(project,'validation'))||!within(path.resolve(record.sample_directory),path.join(project,'validation')))continue;
  try{const stats=await readJson(path.join(item.destination,'statistics.json'));if(stats.version!=='combat-statistics-v7'&&stats.segments?.some((s:any)=>['kills','assists','damage'].some(k=>s.counts[k]===null)))records.push(record);}catch{}
 }
 if(!records.length)return;
 counterRepair=(async()=>{const dir=path.join(project,'validation/app-requests');await fs.mkdir(dir,{recursive:true});const file=path.join(dir,randomUUID()+'-counter-repair.json');await fs.writeFile(file,JSON.stringify(records),'utf8');await new Promise<void>(resolve=>{const proc=spawn(pythonFor(),['repair_cached_statistics.py',file],{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});repairWorker=proc;proc.stdout?.resume();proc.stderr?.resume();const timeout=setTimeout(()=>proc.kill(),60000);proc.on('error',()=>{clearTimeout(timeout);resolve();});proc.on('close',code=>{clearTimeout(timeout);if(repairWorker===proc)repairWorker=null;if(code===0)records.forEach(r=>repairedCounters.add(normalized(r.directory)));resolve();});});})().finally(()=>{counterRepair=null;});await counterRepair;
}
async function collectResults(p:string,repair=true):Promise<Result[]>{
 if(!allowedTasks.has(normalized(p)))throw new Error('请先选择任务');const task=await readJson(p);const results:Result[]=[];
 if(!worker&&repair)void repairLegacyCounters(task).then(()=>collectResults(p,false)).then(results=>send({type:'results-refreshed',task_path:p,results})).catch(()=>{});
 for(const item of task.items){const record=item.record;if(!record)continue;
  if(!within(path.resolve(item.destination),path.resolve(task.directory)))throw new Error('成片目录不属于任务');
  const result:Result={...record,clips:[]};
  try{const report=await readJson(path.join(item.destination,'quality-filter.json'));result.qualityRejected=report.decisions?.filter((s:any)=>s.status==='rejected');}catch{}
  if(record.outputs?.length&&record.outputs.some((f:string)=>!existsSync(f))){result.status='error';result.error='记录中的成片缺失，请检查输出目录或恢复原片后续接。';}
  try{result.review=await readJson(path.join(item.destination,'review-candidates.json'));}catch{}try{const rejected=await readJson(path.join(item.destination,'rejected-candidates.json'));if(Array.isArray(rejected))result.rejected=rejected.filter(s=>Number.isFinite(s.start)&&Number.isFinite(s.end));}catch{}
  try{const manifest=await readJson(path.join(item.destination,'export.json'));let corrected:any=null;try{const raw=await fs.readFile(path.join(item.destination,'statistics.json'));const fix=await readJson(path.join(item.destination,'statistics-corrected.json'));if(fix.repair_signature===createHash('sha256').update(raw).update(fix.version).update(fix.counter_recipe||'').digest('hex'))corrected=fix;}catch{}let candidates:any[]=[];try{candidates=(await readJson(path.join(item.destination,'analysis.json'))).segments||[];}catch{}let frames:string[]=[];let samples=record.sample_directory;
   if(!samples){try{const dirs=await fs.readdir(path.join(project,'validation/app-cache'));for(const d of dirs){const base=path.join(project,'validation/app-cache',d);try{const hud=await readJson(path.join(base,'hud.json'));if(normalized(hud.source.path)===normalized(item.source)){samples=(await readJson(path.join(base,'sample-reference.json'))).samples;break;}}catch{}}}catch{}}
   if(samples){try{const real=await fs.realpath(samples);if(within(real,path.join(project,'validation')))frames=(await fs.readdir(samples)).filter(f=>/^\d+[.]jpg$/.test(f)).sort();}catch{}}
   for(const c of manifest.clips||[]){const target=path.resolve(c.output);if(!within(target,path.resolve(item.destination))||!videoExtensions.has(path.extname(target).toLowerCase())||!existsSync(target))continue;allowedPaths.add(normalized(target));
    if(corrected){const fix=corrected.segments.find((s:any)=>Math.abs(s.start-c.segment.start)<.001&&Math.abs(s.end-c.segment.end)<.001);if(fix){for(const key of ['kills','assists','damage'])if((c.summary?.[key]===null||c.summary?.statistics_partial?.[key]&&fix.partial[key]===false)&&typeof fix.counts[key]==='number'){c.summary[key]=fix.counts[key];c.summary.statistics_partial={...c.summary.statistics_partial,[key]:fix.partial[key]};}c.summary.statistics_version=corrected.version;c.recognition={...c.recognition,statistics:fix};}}
    allowedClips.add(normalized(target));const start=Number(c.segment.start),end=Number(c.segment.end);const rate=record.parameters?.fps||2;const targetTime=(start+end)/2;
    const inside=frames.filter(f=>{const t=(Number(path.parse(f).name)-.5)/rate;return t>=start&&t<=end;});const frame=inside.sort((a,b)=>Math.abs((Number(path.parse(a).name)-.5)/rate-targetTime)-Math.abs((Number(path.parse(b).name)-.5)/rate-targetTime))[0];let thumbnail:string|undefined;
    if(frame)try{thumbnail=await imageUrl(path.join(samples,frame));}catch{}
    result.clips.push({path:target,name:path.basename(target),recordedAt:recordingTime(item.source)||recordingTime(path.basename(target)),duration:Number(c.metadata?.format?.duration)||end-start,start,end,...clipStatistics(c,candidates),thumbnail});
   }
  }catch{}
  allowedPaths.add(normalized(item.destination));results.push(result);
 }
 return results;
}
async function metadata(file:FileItem){await new Promise<void>(resolve=>{const executable=pythonFor();const proc=spawn(executable,['app_ui_info.py',file.path],{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});let result='';proc.stdout.setEncoding('utf8');proc.stdout.on('data',t=>result+=t);const timeout=setTimeout(()=>proc.kill(),20000);proc.on('error',()=>{clearTimeout(timeout);resolve();});proc.on('close',()=>{clearTimeout(timeout);try{const info=JSON.parse(result.trim());send({type:'metadata',source:file.path,...info} as WorkerEvent);}catch{send({type:'metadata',source:file.path,message:'无法读取录像信息'});}resolve();});});}
async function imports(paths:unknown):Promise<{files:FileItem[];rejected:string[]}>{if(!Array.isArray(paths)||paths.length>500)throw new Error('录像清单无效');const files:FileItem[]=[];const rejected:string[]=[];const seen=new Set<string>();for(const raw of paths){if(typeof raw!=='string'||!raw)continue;const p=path.resolve(raw);if(seen.has(normalized(p)))continue;seen.add(normalized(p));try{const stat=await fs.stat(p);if(!stat.isFile()||!videoExtensions.has(path.extname(p).toLowerCase()))throw new Error();allowedPaths.add(normalized(p));files.push({id:normalized(p),path:p,name:path.basename(p),bytes:stat.size,status:'pending'});}catch{rejected.push(path.basename(p));}}let next=0;const pump=async()=>{while(next<files.length)await metadata(files[next++]);};void pump();void pump();return{files,rejected};}
async function start(payload:any,resume=false){if(worker&&terminal)await workerExit;if(worker||launching)throw new Error('已有批次正在处理');launching=true;stopRequested=false;terminal=false;
 try{let effective=safeOptions(payload.options,resume);let request:any;
  if(resume){if(!allowedTasks.has(normalized(payload.task)))throw new Error('请先选择续接任务');const info=await taskInfo(payload.task);request={resume_task:info.path,backend:effective.backend,gpu_load:effective.gpu_load,pipeline:effective.pipeline};currentTask=info.path;}
  else{if(!Array.isArray(payload.files)||!payload.files.length||payload.files.some((f:unknown)=>typeof f!=='string'||!allowedPaths.has(normalized(f))))throw new Error('请先导入录像');if(typeof payload.output!=='string'||!path.isAbsolute(payload.output))throw new Error('输出目录无效');options=effective;output=payload.output;await save();request={...effective,files:payload.files,output:payload.output};}
  const root=path.join(project,'validation/app-requests');await fs.mkdir(root,{recursive:true});const id=randomUUID();stopFile=path.join(root,id+'.stop');const requestPath=path.join(root,id+'.json');request.stop_file=stopFile;await fs.writeFile(requestPath,JSON.stringify(request),'utf8');if(stopRequested)await fs.writeFile(stopFile,'stop','utf8');
  const python=pythonFor(effective.backend);if(!existsSync(python))throw new Error('未找到选定设备的 Python 环境');
  const proc=spawn(python,['app_worker.py',requestPath],{cwd:project,windowsHide:true,env:{...process.env,PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8'}});worker=proc;workerExit=new Promise<void>(resolve=>{resolveWorkerExit=resolve;});
  let stderr='';const lines=new JsonLines(e=>{eventChain=eventChain.then(async()=>{const event=e as unknown as WorkerEvent;
   if(event.type==='run'&&event.task_path){currentTask=event.task_path;await taskInfo(currentTask);}
   if(event.type==='file')currentSource=event.source||'';
   if(event.type==='preview'&&event.sample_path){try{event.imageUrl=await imageUrl(event.sample_path);}catch{return;}delete event.sample_path;}
   if(event.type==='result'&&currentTask){const list=await collectResults(currentTask);event.result=list.find(r=>normalized(r.source)===normalized(event.source||currentSource));}
   if(['done','stopped','fatal'].includes(event.type))terminal=true;send(event);
  }).catch(error=>send({type:'log',message:'界面状态读取：'+error.message}));},line=>send({type:'log',message:'后台非状态输出：'+line}));
  proc.stdout!.on('data',chunk=>lines.push(chunk));proc.stderr!.setEncoding('utf8');proc.stderr!.on('data',chunk=>{stderr=(stderr+chunk).slice(-20000);send({type:'stderr',message:chunk});});
  proc.on('error',error=>{send({type:'fatal',message:'无法启动处理进程：'+error.message});});
  proc.on('close',code=>{lines.end();eventChain=eventChain.then(()=>{worker=null;launching=false;stopFile='';resolveWorkerExit?.();resolveWorkerExit=null;if(!terminal){send({type:code===75?'stopped':'fatal',message:code===75?'断点已保存':`处理进程退出（${code}）。${stderr.slice(-1200)}`});}send({type:'exit'});if(closing){closing=false;win.close();}});});
 }catch(error){launching=false;throw error;}finally{if(worker)launching=false;}
}
async function stop(){stopRequested=true;if(stopFile)await fs.writeFile(stopFile,'stop','utf8');}
function trusted(event:Electron.IpcMainInvokeEvent){if(!win||event.sender!==win.webContents||event.senderFrame!==win.webContents.mainFrame)throw new Error('不允许的界面请求');}
function handle(name:string,fn:(...args:any[])=>any){ipcMain.handle(name,(event,...args)=>{trusted(event);return fn(...args);});}
app.whenReady().then(async()=>{
 try{const saved=await readJson(path.join(app.getPath('userData'),'preferences.json'));if(typeof saved.updatePreferences?.autoCheck==='boolean')updateInfo.autoCheck=saved.updatePreferences.autoCheck;updateInfo=restoreUpdateInfo(saved.updateCache,app.getVersion(),updateInfo.autoCheck);preferences={...preferences,...saved.preferences};options=safeOptions({...defaults,...saved.options,fps:saved.options?.fps<1?defaults.fps:saved.options?.fps??defaults.fps});output=saved.output||output;}catch{}
 protocol.handle('apex-media',async request=>{try{const url=new URL(request.url);if(url.hostname==='video')return videos.respond(request);const p=images.get(url.pathname.slice(1));if(url.hostname!=='image'||!p)return new Response('Not found',{status:404});const data=await fs.readFile(p);return new Response(data,{headers:{'Content-Type':p.endsWith('.png')?'image/png':'image/jpeg','Cache-Control':'private, max-age=60'}});}catch{return new Response('Unavailable',{status:404});}});
 const initial=theme();const dark=preferences.mode==='dark'||(preferences.mode==='system'&&initial.dark);
 win=new BrowserWindow({width:1120,height:820,minWidth:760,minHeight:620,show:false,title:'Apex Highlight Clipper',backgroundColor:'#211e1a',titleBarStyle:'hidden',titleBarOverlay:{color:'#211e1a',symbolColor:'#f8f7f2',height:36},autoHideMenuBar:true,webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
 let shown=false;handle('ui-ready',()=>{if(!shown&&!win.isDestroyed()){shown=true;win.show();scheduleUpdate();}});setTimeout(()=>{if(!shown&&!win.isDestroyed())win.show();},10000).unref();
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));win.webContents.on('will-navigate',event=>event.preventDefault());
 win.on('minimize',()=>send({type:'visibility',hidden:true}));win.on('hide',()=>send({type:'visibility',hidden:true}));win.on('restore',()=>send({type:'visibility',hidden:false}));win.on('show',()=>send({type:'visibility',hidden:false}));
 win.on('close',event=>{repairWorker?.kill();repairWorker=null;if(worker||launching){event.preventDefault();if(!closing){closing=true;send({type:'close-request',message:'窗口将在断点保存后关闭'});void stop();}}else if(!closeSaveFinished){event.preventDefault();void saveChain.catch(()=>{}).then(()=>{closeSaveFinished=true;if(!win.isDestroyed())win.close();});}});
 const changed=()=>{if(!win.isDestroyed())win.webContents.send('system-theme',theme());};nativeTheme.on('updated',changed);systemPreferences.on('accent-color-changed',changed);systemPreferences.on('color-changed',changed);
 handle('bootstrap',async()=>({output,options,preferences,theme:theme(),development,lastTask:await lastTask(),backendAvailable:existsSync(pythonFor('dml')),update:updateInfo}));
 handle('check-update',async()=>{await updater.check();await saveChain;return updateInfo;});
 handle('auto-check-update',async(enabled:unknown)=>{if(typeof enabled!=='boolean')throw new Error('更新开关无效');publishUpdate({...updateInfo,autoCheck:enabled});await save();if(enabled)scheduleUpdate();else if(updateTimer){clearTimeout(updateTimer);updateTimer=null;}return updateInfo;});
 handle('open-release',()=>shell.openExternal(releasePage(updateInfo.status==='available'?updateInfo.releaseTag:undefined)));
 handle('choose-files',async()=>{const result=await dialog.showOpenDialog(win,{properties:['openFile','multiSelections'],filters:[{name:'录像',extensions:[...videoExtensions].map(x=>x.slice(1))}]});return imports(result.filePaths);});
 handle('choose-folder',async()=>{const result=await dialog.showOpenDialog(win,{properties:['openDirectory']});if(result.canceled)return{files:[],rejected:[]};const dir=result.filePaths[0];return imports((await fs.readdir(dir,{withFileTypes:true})).filter(e=>e.isFile()&&videoExtensions.has(path.extname(e.name).toLowerCase())).map(e=>path.join(dir,e.name)));});
 handle('import-files',imports);
 handle('choose-output',async()=>{const result=await dialog.showOpenDialog(win,{properties:['openDirectory','createDirectory'],defaultPath:output});if(result.canceled)return null;output=result.filePaths[0];allowedPaths.add(normalized(output));await save();return output;});
 handle('preferences',async(p:ThemePreferences)=>{if(!['system','light','dark'].includes(p.mode)||p.seed!==null&&!/^#[\da-f]{6}$/i.test(p.seed)||typeof p.reduceMotion!=='boolean'||!['flat','sketch'].includes(p.mascotStyle)||typeof p.mascotEnabled!=='boolean')throw new Error('外观选项无效');preferences=p;await save();});
 handle('options',async(o:Options,p:string)=>{options=safeOptions(o);if(typeof p==='string'&&path.isAbsolute(p))output=p;await save();});
 handle('start',p=>start(p));handle('stop',stop);handle('resume',p=>start(p,true));handle('last-task',lastTask);
 handle('task',p=>{if(typeof p!=='string'||!allowedTasks.has(normalized(p)))throw new Error('请先选择任务');return taskInfo(p);});
 handle('choose-task',async()=>{const result=await dialog.showOpenDialog(win,{properties:['openFile'],filters:[{name:'任务记录 task.json',extensions:['json']}]});if(result.canceled)return null;return taskInfo(result.filePaths[0]);});
 handle('results',collectResults);
 handle('video-url',file=>videos.url(file));
 handle('open',async(p:string,folder=false)=>{if(typeof p!=='string'||!allowedPaths.has(normalized(p)))throw new Error('只允许打开本任务的录像或成片');const stat=await fs.stat(p);if(!stat.isDirectory()&&!videoExtensions.has(path.extname(p).toLowerCase()))throw new Error('只允许打开录像或输出文件夹');if(folder)shell.showItemInFolder(p);else{const error=await shell.openPath(p);if(error)throw new Error(error);}});
 if(process.env.APEX_UI_VALIDATE==='1'){
  handle('validation-import',imports);handle('validation-task',taskInfo);handle('validation-project',()=>project);
 }
 const renderer=path.join(__dirname,'../../dist/index.html');if(process.env.APEX_UI_DEV_URL)await win.loadURL(process.env.APEX_UI_DEV_URL);else await win.loadFile(renderer);
}).catch(error=>{dialog.showErrorBox('Apex 启动失败',String(error));app.quit();});
app.on('window-all-closed',()=>app.quit());





