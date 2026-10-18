import fs from 'node:fs/promises';
import path from 'node:path';
import {safeHudFiles,videoExtensions} from './protocol';

/** Match QQ's installed file-share payload with query-safe UTF-8 escaping.
 * Its Explorer extension leaves '+' literal; query parsing turns it into space.
 */
export function qqShareUrl(files:string[]){
 const payload={sourceType:'shareToQQ',msgItems:files.map(file=>({type:'file',path:file.replaceAll('\\','/')}))};
 const uri='tencent://ntqq-open?subCmd=friendSelector&action=share&actionParams='+encodeURIComponent(JSON.stringify(payload));
 if(uri.length>30000)throw new Error('所选片段的完整路径过长，请减少本次分享数量');
 return uri;
}
export async function shareFiles(raw:unknown,allowed:ReadonlySet<string>,open:(uri:string)=>Promise<void>){
 if(process.platform!=='win32')throw new Error('QQ 文件分享目前支持 Windows 桌面版');
 const files=safeHudFiles(raw,allowed,file=>path.resolve(file).toLowerCase());
 if(files.length>100)throw new Error('每次最多分享 100 个片段，请减少所选数量');
 // Validate the entire batch before opening QQ; never silently send a partial set.
 for(const file of files){const stat=await fs.stat(file).catch(()=>null);if(!stat?.isFile()||!videoExtensions.has(path.extname(file).toLowerCase()))throw new Error('部分片段已移动或无法读取，请刷新片段库后重新选择');}
 const uri=qqShareUrl(files);
 try{await open(uri);}catch(error){throw new Error('无法打开 QQ 会话选择窗口，请确认已安装并登录 QQ。',{cause:error});}
 return{status:'opened' as const,count:files.length,command:'QQ好友'};
}
