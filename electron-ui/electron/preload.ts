import {contextBridge,ipcRenderer,webUtils} from 'electron';
import type {DesktopAPI,WorkerEvent,SystemTheme,UpdateInfo} from '../src/shared';
const api:DesktopAPI={
 ready:()=>ipcRenderer.invoke('ui-ready'),
 bootstrap:()=>ipcRenderer.invoke('bootstrap'),chooseFiles:()=>ipcRenderer.invoke('choose-files'),chooseFolder:()=>ipcRenderer.invoke('choose-folder'),
 importFiles:files=>ipcRenderer.invoke('import-files',files.map(file=>webUtils.getPathForFile(file))),
 chooseOutput:()=>ipcRenderer.invoke('choose-output'),savePreferences:p=>ipcRenderer.invoke('preferences',p),saveOptions:(o,p)=>ipcRenderer.invoke('options',o,p),
 start:(files,output,options)=>ipcRenderer.invoke('start',{files,output,options}),stop:()=>ipcRenderer.invoke('stop'),resume:(task,options)=>ipcRenderer.invoke('resume',{task,options}),
 chooseTask:()=>ipcRenderer.invoke('choose-task'),lastTask:()=>ipcRenderer.invoke('last-task'),task:task=>ipcRenderer.invoke('task',task),results:task=>ipcRenderer.invoke('results',task),open:(path,folder)=>ipcRenderer.invoke('open',path,folder),
 videoURL:file=>ipcRenderer.invoke('video-url',file),
 onEvent:cb=>{const fn=(_:unknown,e:WorkerEvent)=>cb(e);ipcRenderer.on('worker-event',fn);return()=>ipcRenderer.removeListener('worker-event',fn);},
 onTheme:cb=>{const fn=(_:unknown,e:SystemTheme)=>cb(e);ipcRenderer.on('system-theme',fn);return()=>ipcRenderer.removeListener('system-theme',fn);},
 checkUpdate:()=>ipcRenderer.invoke('check-update'),setAutoCheck:enabled=>ipcRenderer.invoke('auto-check-update',enabled),openRelease:()=>ipcRenderer.invoke('open-release'),
 onUpdate:cb=>{const fn=(_:unknown,info:UpdateInfo)=>cb(info);ipcRenderer.on('update-status',fn);return()=>ipcRenderer.removeListener('update-status',fn);}
};contextBridge.exposeInMainWorld('apex',api);
